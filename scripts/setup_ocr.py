"""Install official Tesseract Korean best and English fast models locally."""
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "var/ocr/tessdata"
    output.mkdir(parents=True, exist_ok=True)
    for language in ("kor", "eng"):
        path = output / f"{language}.traineddata"
        if not path.exists():
            repository = "tessdata_best" if language == "kor" else "tessdata_fast"
            with urlopen(f"https://raw.githubusercontent.com/tesseract-ocr/{repository}/4.1.0/{language}.traineddata", timeout=30) as response:
                data = response.read()
            if len(data) < 100_000:
                raise ValueError("OCR model download is incomplete")
            path.write_bytes(data)
        print(f"Ready: {language}")


if __name__ == "__main__":
    main()
