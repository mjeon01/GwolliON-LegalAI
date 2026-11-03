"""Stored page copies for the review viewer, and locating evidence on them."""
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata

import fitz
from PIL import Image

from backend.reading import ReadingError, ocr_available, ocr_settings, sanitized_image

MAX_SIDE = 1800


def encoded(image):
    image = image.copy()
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=82)
    return image.size, stream.getvalue()


def pdf_page(page):
    rect = page.rect
    pixmap = page.get_pixmap(matrix=fitz.Matrix(*[min(2, MAX_SIDE / max(rect.width, rect.height))] * 2), alpha=False)
    size, image = encoded(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples))
    words = [[w[0] / rect.width, w[1] / rect.height, w[2] / rect.width, w[3] / rect.height, w[4]] for w in page.get_text("words", sort=True)]
    # Scanned pages have no text layer, matching the reading threshold; OCR fills them later.
    return size, image, words if len(page.get_text(sort=True).strip()) >= 20 else None


def snapshot(files, rotations=None):
    """Render uploaded PDF or photo pages. TXT and unreadable files simply have no page view."""
    rendered = []
    try:
        if len(files) == 1 and files[0][1] == ".pdf":
            with fitz.open(stream=files[0][0], filetype="pdf") as document:
                rendered = [pdf_page(page) for page in document]
        elif all(suffix in {".png", ".jpg", ".jpeg", ".webp"} for _, suffix in files):
            for (raw, _), rotation in zip(files, rotations or [0] * len(files)):
                rendered.append((*encoded(sanitized_image(raw, rotation)), None))
    except (ReadingError, OSError, ValueError, RuntimeError):
        return []
    return [{"page": number, "width": size[0], "height": size[1], "image": image, "words": words}
            for number, (size, image, words) in enumerate(rendered, 1)]


def ocr_words(image, width, height):
    """Word boxes for a stored page. Failure only means highlights fall back to the text view."""
    if not ocr_available():
        return []
    binary, data = ocr_settings()
    with tempfile.TemporaryDirectory(prefix="gwollion-ocr-") as directory:
        path = Path(directory) / "page.jpg"
        path.write_bytes(image)
        try:
            output = subprocess.run([binary, str(path), "stdout", "--tessdata-dir", str(data), "-l", "kor+eng", "--oem", "1", "--psm", "6", "-c", "tessedit_create_tsv=1"],
                                    capture_output=True, text=True, timeout=25)
        except subprocess.TimeoutExpired:
            return []
    if output.returncode:
        return []
    words = []
    for line in output.stdout.splitlines()[1:]:
        cells = line.split("\t", 11)
        if len(cells) == 12 and cells[0] == "5" and cells[11].strip():
            left, top, box_width, box_height = map(int, cells[6:10])
            words.append([left / width, top / height, (left + box_width) / width, (top + box_height) / height, cells[11]])
    return words


def compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def visual_lines(words):
    lines = []
    for word in words:
        middle = (word[1] + word[3]) / 2
        if lines and lines[-1][0][1] <= middle <= lines[-1][0][3]:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def line_rects(words):
    return [[min(w[0] for w in line), min(w[1] for w in line), max(w[2] for w in line), max(w[3] for w in line)]
            for line in visual_lines(words)]


def locate(quote, words, occurrence=0):
    """Return (rects, match). OCR noise falls back to the most similar single line."""
    target = compact(quote)
    if not target or not words:
        return [], None
    chars, owners = "", []
    for index, word in enumerate(words):
        piece = compact(word[4])
        chars += piece
        owners += [index] * len(piece)
    position = chars.find(target)
    for _ in range(occurrence):
        following = chars.find(target, position + 1)
        if following < 0:
            break
        position = following
    if position >= 0:
        return line_rects(words[owners[position]:owners[position + len(target) - 1] + 1]), "exact"
    if len(target) < 6:
        return [], None
    best, score = None, 0.72
    for line in visual_lines(words):
        similarity = SequenceMatcher(None, target, compact("".join(w[4] for w in line)), autojunk=False).ratio()
        if similarity >= score:
            best, score = line, similarity
    return (line_rects(best), "approximate") if best else ([], None)


def evidence_key(evidence):
    return f"{evidence['block_id']}:{evidence['start']}:{evidence['end']}"


def highlights(result, pages):
    """Rectangles (0..1 of the page) for every evidence span shown in the review."""
    layout = {p["page"]: p["words"] or [] for p in pages}
    located = {}
    for item in [*result["review"]["findings"], *result["issues"]]:
        for evidence in item["evidence"]:
            key = evidence_key(evidence)
            if key in located:
                continue
            target = compact(evidence["quote"])
            earlier = sum(b["page"] == evidence["page"] and b["block_id"] < evidence["block_id"] and target in compact(b["text"]) for b in result["blocks"])
            rects, match = locate(evidence["quote"], layout.get(evidence["page"], []), earlier)
            if rects:
                located[key] = {"page": evidence["page"], "rects": rects, "match": match}
    return located
