"""Two-pass OCR pipeline: vision-model first pass + LLM refinement.

Blocking work (Ollama HTTP, EasyOCR inference, PDF rasterization) is pushed
to threads so the async event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import threading
from typing import Any

from backend.core.config import Config, load_config
from backend.services.ocr_client import OllamaClient, OllamaError

logger = logging.getLogger(__name__)

MAX_CORRECTION_HINTS = 10
TRUNCATED_PREVIEW_CHARS = 200
PDF_DPI = 200


class OCRService:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.ollama = OllamaClient(self.config.ollama_url)
        self.easyocr_reader: Any = None
        self._easyocr_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Knowledge-base hints
    # ------------------------------------------------------------------
    def _get_correction_hints(self) -> str:
        """Collect recent correction pairs from labels as prompt hints."""
        if not self.config.labels_file.exists():
            return ""

        try:
            with open(self.config.labels_file, "r", encoding="utf-8") as f:
                labels: dict = json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load correction hints; ignoring labels store")
            return ""

        corrections: list[str] = []
        for record in labels.values():
            orig = ""
            corr = ""
            metadata = record.get("metadata") or {}
            if "ocr_details" in record:
                details = record.get("ocr_details") or {}
                orig = str(details.get("original_text", "")).strip()
                corr = str(details.get("corrected_text", "")).strip()
            elif "original" in record and "corrected" in record:
                orig = str(record["original"]).strip()
                corr = str(record["corrected"]).strip()
            is_corrected = record.get("is_corrected", metadata.get("is_corrected"))

            if is_corrected and orig and corr:
                preview = f"Original: {orig[:TRUNCATED_PREVIEW_CHARS]}... -> "
                preview += f"Corrected: {corr[:TRUNCATED_PREVIEW_CHARS]}..."
                corrections.append(preview)

        if not corrections:
            return ""
        hints = "\n".join(corrections[-MAX_CORRECTION_HINTS:])
        return (
            "\n\n[Correction Knowledge Base]\n"
            "Here are examples of common OCR errors in this document set and their "
            f"correct forms. Please apply these patterns to the current recognition:\n{hints}"
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    async def recognize_text(
        self,
        file_bytes: bytes,
        file_extension: str = ".jpg",
        model_name: str | None = None,
    ) -> list[dict]:
        """Recognize text from an image or PDF."""
        target_model = model_name or self.config.default_model

        if file_extension.lower() == ".pdf":
            return await self._recognize_pdf(file_bytes, target_model)
        return await self._process_image_ocr(file_bytes, target_model)

    async def _recognize_pdf(self, file_bytes: bytes, model_name: str) -> list[dict]:
        try:
            from pdf2image import convert_from_bytes
        except ImportError as exc:
            raise RuntimeError(
                "pdf2image 未安装。请运行 'pip install pdf2image'。"
            ) from exc

        kwargs: dict[str, Any] = {"dpi": PDF_DPI}
        if self.config.poppler_path:
            kwargs["poppler_path"] = self.config.poppler_path

        try:
            logger.info("PDF detected. Converting pages at dpi=%s", PDF_DPI)
            images = convert_from_bytes(file_bytes, **kwargs)
        except Exception as exc:
            hint = " (请设置 OCR_POPPLER_PATH 指向 poppler 目录)" if not self.config.poppler_path else ""
            logger.exception("PDF page conversion failed")
            raise RuntimeError(f"PDF 转图失败{hint}: {exc}") from exc

        num_pages = len(images)
        logger.info("Converted PDF to %d page images", num_pages)
        semaphore = asyncio.Semaphore(2)
        results: list[dict] = []
        for index, image in enumerate(images):
            async with semaphore:
                page_results = await self._ocr_page_image(image, index, num_pages, model_name)
                results.extend(page_results)
        return results

    async def _ocr_page_image(self, pil_image: Any, index: int, num_pages: int, model_name: str) -> list[dict]:
        try:
            buffer = io.BytesIO()
            pil_image.save(buffer, format="JPEG")
            logger.info("Processing PDF page %d/%d", index + 1, num_pages)
            return await self._process_image_ocr(buffer.getvalue(), model_name)
        except Exception as exc:  # keep other pages alive
            logger.warning("PDF page %d failed: %s", index + 1, exc)
            return [{"text": f"[Page {index + 1} error: {exc}]", "confidence": 0, "box": []}]

    # ------------------------------------------------------------------
    # Single-image two-pass pipeline
    # ------------------------------------------------------------------
    async def _process_image_ocr(self, image_bytes: bytes, model_name: str) -> list[dict]:
        hints = self._get_correction_hints()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        system_prompt = (
            "You are a professional high-precision OCR system. "
            "Your goal is to extract all text exactly as it appears in the image. "
            "Maintain the original layout and paragraph breaks. "
            "CRITICAL: Preserve the original script exactly. If the text in the image is Simplified Chinese, output Simplified Chinese. "
            "If it is Traditional Chinese, output Traditional Chinese. DO NOT translate or convert between the two. "
            "Output ONLY the extracted text without any commentary or labels."
        )

        # --- First pass ---
        if model_name == "easyocr":
            initial_text = await self._run_easyocr(image_bytes)
        else:
            first_prompt = f"{system_prompt}\n{hints}\n\nNow, please recognize the text in the provided image."
            initial_text = await self._generate_safe(model_name, first_prompt, image_b64, required=True)

        # --- Refine pass (always a capable LLM) ---
        refine_model = self.config.default_model if model_name == "easyocr" else model_name
        refine_prompt = (
            f"{system_prompt}\n"
            "I have performed an initial OCR pass on this image, but there may be errors.\n"
            f"Initial OCR Result:\n---\n{initial_text}\n---\n"
            f"{hints}\n\n"
            "Please review the initial result and the [Correction Knowledge Base] patterns. "
            "Correct any misrecognized characters, punctuation, or layout issues to produce the most accurate version possible. "
            "Ensure the script (Simplified/Traditional) matches the image exactly. "
            "Output ONLY the final corrected text."
        )
        try:
            final_text = await asyncio.to_thread(self.ollama.generate, refine_model, refine_prompt, image_b64)
        except OllamaError:
            logger.warning("Refinement pass failed; falling back to initial text")
            return [{"text": initial_text, "confidence": 0.8, "box": [], "refined": False}]

        if not final_text:
            final_text = initial_text
        return [{"text": final_text, "confidence": 1.0, "box": [], "refined": True}]

    async def _generate_safe(self, model: str, prompt: str, image_b64: str, required: bool) -> str:
        try:
            return await asyncio.to_thread(self.ollama.generate, model, prompt, image_b64)
        except OllamaError as exc:
            if required:
                raise RuntimeError(f"OCR 首次识别失败: {exc}") from exc
            return ""

    async def _run_easyocr(self, image_bytes: bytes) -> str:
        def _infer() -> list[str]:
            import easyocr

            reader = self._ensure_easyocr_reader(easyocr)
            return reader.readtext(image_bytes, detail=0)

        try:
            texts = await asyncio.to_thread(_infer)
        except ImportError as exc:
            raise RuntimeError("EasyOCR 未安装。请运行 'pip install easyocr'。") from exc
        return "\n".join(texts)

    def _ensure_easyocr_reader(self, easyocr: Any) -> Any:
        reader = self.easyocr_reader
        if reader is not None:
            return reader
        with self._easyocr_lock:
            if self.easyocr_reader is None:
                logger.info("Initializing EasyOCR Reader (lazy load)...")
                try:
                    self.easyocr_reader = easyocr.Reader(["ch_sim", "en"])
                except Exception as exc:
                    if "10060" in str(exc) or "Timeout" in str(exc):
                        raise RuntimeError(
                            "EasyOCR 模型下载失败（网络超时）。请检查网络连接或手动配置模型文件。"
                        ) from exc
                    raise RuntimeError(f"EasyOCR 初始化失败: {exc}") from exc
            return self.easyocr_reader

    # ------------------------------------------------------------------
    def get_full_text(self, results: list[dict]) -> str:
        """Concatenate recognized fragments into a single string."""
        return "\n".join(res["text"] for res in results)
