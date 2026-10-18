"""Stage 1: local PDF text extraction and Korean OCR; temporary images are removed."""
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError
from mvp.knowledge import ROOT


class ReadingError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def ocr_settings():
    binary = shutil.which("tesseract")
    data = Path(os.environ.get("GWOLLION_TESSDATA", ROOT / "var/ocr/tessdata"))
    return binary, data


def ocr_available():
    binary, data = ocr_settings()
    return bool(binary and all((data / f"{lang}.traineddata").is_file() for lang in ("kor", "eng")))


def recognize(image, directory, page):
    if not ocr_available():
        raise ReadingError("한국어 OCR이 준비되지 않았습니다. scripts/setup_ocr.py를 실행하거나 텍스트를 직접 입력해주세요.", 503)
    binary, data = ocr_settings()
    image.save(Path(directory) / f"page-{page}.png")
    try:
        result = subprocess.run([binary, str(Path(directory) / f"page-{page}.png"), "stdout", "--tessdata-dir", str(data), "-l", "kor+eng", "--oem", "1", "--psm", "6"],
                                capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        raise ReadingError("OCR 제한 시간을 초과했습니다. 더 선명한 사진이나 페이지를 나눈 PDF를 사용해주세요.")
    if result.returncode:
        raise ReadingError("OCR로 문서를 읽지 못했습니다. 파일을 확인하거나 텍스트를 직접 입력해주세요.")
    return result.stdout.strip()


def read_document(raw, suffix):
    pages, methods, warnings = [], [], []
    if suffix == ".txt":
        try:
            pages = raw.decode("utf-8-sig").split("\f")
        except UnicodeDecodeError:
            raise ReadingError("UTF-8로 저장된 텍스트 파일을 사용해주세요.")
        methods = ["text"] * len(pages)
    elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            with Image.open(BytesIO(raw)) as source:
                if source.width * source.height > 20_000_000:
                    raise ReadingError("사진은 2,000만 화소 이하로 올려주세요.", 413)
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ReadingError("읽을 수 있는 사진 파일이 아닙니다.")
        with tempfile.TemporaryDirectory(prefix="gwollion-ocr-") as directory:
            pages = [recognize(image, directory, 1)]
        methods = ["ocr"]
    elif suffix == ".pdf":
        try:
            document = fitz.open(stream=raw, filetype="pdf")
        except Exception:
            raise ReadingError("읽을 수 있는 PDF 파일이 아닙니다.")
        with document, tempfile.TemporaryDirectory(prefix="gwollion-ocr-") as directory:
            if document.is_encrypted or not 1 <= len(document) <= 20:
                raise ReadingError("암호화되지 않은 20페이지 이하의 PDF를 사용해주세요.")
            ocr_pages = 0
            for number, page in enumerate(document, 1):
                text = page.get_text(sort=True).strip()
                method = "pdf_text"
                # Mixed PDFs are handled page by page, preserving original page numbers.
                if len(text) < 20:
                    ocr_pages += 1
                    if ocr_pages > 5:
                        raise ReadingError("한 번에 OCR로 읽는 스캔 페이지는 5페이지까지입니다. 문서를 나눠주세요.", 413)
                    if page.rect.width * page.rect.height * 9 > 20_000_000:
                        raise ReadingError("PDF 페이지가 너무 큽니다. A4 크기로 저장해주세요.", 413)
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                    text = recognize(Image.open(BytesIO(pixmap.tobytes("png"))), directory, number)
                    method = "ocr"
                pages.append(text)
                methods.append(method)
                if len(text.strip()) < 20:
                    warnings.append(f"{number}페이지에서 읽은 텍스트가 부족합니다. 빈 페이지인지 확인해주세요.")
    else:
        raise ReadingError("TXT, PDF 또는 JPG·PNG·WEBP 사진을 사용해주세요.", 415)
    text = "\f".join(pages)
    if len(text.strip()) < 20:
        raise ReadingError("읽을 수 있는 텍스트가 부족합니다. 선명한 문서를 올리거나 내용을 직접 입력해주세요.")
    if len(text) > 50000:
        raise ReadingError("읽은 텍스트는 50,000자까지 지원합니다.", 413)
    if len(pages) > 20:
        raise ReadingError("문서는 20페이지까지 지원합니다.", 413)
    if "ocr" in methods:
        warnings.append("OCR 결과에는 오인식이 있을 수 있습니다. 날짜·금액·시간·선택 표시를 원본과 대조한 뒤 분석해주세요.")
    return {"text": text, "pages": len(pages), "reading": {"methods": methods, "ocr_used": "ocr" in methods, "warnings": warnings}}
