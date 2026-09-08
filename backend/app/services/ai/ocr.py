"""AI-01 — OCR for scanned documents.

The BRD requires text extraction "including scanned documents", and AI-07 asks
the vendor to state model limitations and quality controls for Arabic document
analysis. Both are addressed here.

Provider selection is configuration, not code: whichever provider is configured
wins, and when none is, the pipeline records `ocr_required` on the document
rather than pretending it read something. That honesty matters — a silently
empty extraction would make the evidence-coverage stage report "missing" for a
document that is actually fine.

Quality controls shipped
------------------------
* every OCR result carries the engine name and a mean confidence, so a reviewer
  can see how much weight a machine reading deserves;
* results below `ocr_min_confidence` are surfaced as low-confidence rather than
  used silently;
* Arabic is requested explicitly (`ara+eng`) instead of relying on autodetect,
  which is where most Arabic OCR accuracy is lost.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.config import settings

log = logging.getLogger("remas.ai.ocr")


class OCRResult(dict):
    """{engine, pages: [{page, text, confidence}], text, confidence, error}"""


def _empty(engine: str, error: str | None = None) -> OCRResult:
    return OCRResult(engine=engine, pages=[], text="", confidence=None, error=error)


# ─────────────────────────────── tesseract ──────────────────────────────────


DEFAULT_TESSERACT_PATHS = (
    "C:/Program Files/Tesseract-OCR/tesseract.exe",
    "C:/Program Files (x86)/Tesseract-OCR/tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


def _configure_tesseract() -> bool:
    """Point pytesseract at the binary and the language models."""
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
    except ImportError:
        return False

    from pathlib import Path as _Path

    command = settings.tesseract_cmd
    if not command:
        for candidate in DEFAULT_TESSERACT_PATHS:
            if _Path(candidate).exists():
                command = candidate
                break
    if command:
        pytesseract.pytesseract.tesseract_cmd = command

    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001 - the binary may not be installed
        return False


def _tessdata_config() -> str:
    """Arabic models are not part of a default Tesseract install, so the data
    directory is pointed at explicitly.

    Set through the environment rather than `--tessdata-dir`: pytesseract splits
    the config string on whitespace, so a Windows path with spaces — which
    `C:/Program Files/...` always has — would be torn in half.
    """
    import os

    directory = settings.tessdata_dir
    if directory and directory.exists():
        os.environ["TESSDATA_PREFIX"] = str(directory)
    return ""


def _tesseract_available() -> bool:
    return _configure_tesseract()


# Tesseract is trained on roughly 300 DPI page scans. Feed it much smaller and
# the glyphs lose the detail Arabic ligatures need; feed it much larger and word
# segmentation starts splitting words. Both directions were measured on the
# benchmark corpus, so images are normalised into the band before recognition.
TARGET_TEXT_HEIGHT = 1400   # px, the short edge of a normalised page
MAX_TEXT_HEIGHT = 2600


def _speckle_ratio(image) -> float:
    """Share of pixels that sit at the extremes with no mid-tone neighbours —
    a cheap proxy for scanner speckle that costs one histogram pass."""
    from PIL import ImageFilter

    small = image.resize((min(image.width, 400), min(image.height, 400)))
    difference = ImageFilter.MedianFilter(size=3)
    filtered = small.filter(difference)
    a, b = small.tobytes(), filtered.tobytes()
    changed = sum(1 for x, y in zip(a, b) if abs(x - y) > 60)
    return changed / max(len(a), 1)


def preprocess(image):
    """Quality control for AI-07: grayscale, contrast stretch, and rescale into
    the band the engine was trained on. Applied before every recognition so the
    accuracy the benchmark reports is the accuracy production gets."""
    from PIL import Image, ImageFilter, ImageOps

    if image.mode != "L":
        image = image.convert("L")

    # Salt-and-pepper speckle is what a real scanner or a photographed page
    # produces, and upscaling multiplies it. A median filter removes isolated
    # dots while leaving stroke edges intact, which a blur would not.
    if _speckle_ratio(image) > 0.004:
        image = image.filter(ImageFilter.MedianFilter(size=3))

    # Contrast stretch lifts faint scans without inventing detail.
    image = ImageOps.autocontrast(image, cutoff=1)

    height = image.height
    if height < TARGET_TEXT_HEIGHT:
        factor = TARGET_TEXT_HEIGHT / height
    elif height > MAX_TEXT_HEIGHT:
        factor = MAX_TEXT_HEIGHT / height
    else:
        factor = 1.0

    if abs(factor - 1.0) > 0.01:
        image = image.resize(
            (max(1, int(image.width * factor)), max(1, int(height * factor))),
            Image.LANCZOS,
        )
    return image


def _tesseract(path: Path, content_type: str) -> OCRResult:
    import pytesseract
    from PIL import Image

    _configure_tesseract()
    config = _tessdata_config()
    langs = settings.ocr_languages  # "ara+eng" — asked for, never autodetected
    pages: list[dict[str, Any]] = []

    if content_type in ("image/png", "image/jpeg"):
        images = [Image.open(path)]
    elif content_type == "application/pdf":
        images = _rasterise_pdf(path)
        if not images:
            return _empty("tesseract", "pdf_rasterisation_unavailable")
    else:
        return _empty("tesseract", "unsupported_type")

    confidences: list[float] = []
    for index, image in enumerate(images, start=1):
        prepared = preprocess(image)
        data = pytesseract.image_to_data(
            prepared, lang=langs, config=config, output_type=pytesseract.Output.DICT
        )
        words = [w for w in data.get("text", []) if w and w.strip()]
        scores = [float(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and float(c) >= 0]
        page_conf = (sum(scores) / len(scores) / 100) if scores else None
        if page_conf is not None:
            confidences.append(page_conf)
        pages.append({"page": index, "text": " ".join(words), "confidence": page_conf})

    text = "\n\n".join(p["text"] for p in pages if p["text"])
    mean = sum(confidences) / len(confidences) if confidences else None
    return OCRResult(engine="tesseract", pages=pages, text=text, confidence=mean, error=None)


# ───────────────────────── cloud document intelligence ──────────────────────


def _azure(path: Path, content_type: str) -> OCRResult:
    """Azure AI Document Intelligence — strong Arabic support, and the usual
    choice when the deployment already sits in Azure."""
    import json
    import time
    import urllib.request

    endpoint = (settings.ocr_endpoint or "").rstrip("/")
    key = settings.ocr_api_key or ""
    url = f"{endpoint}/documentintelligence/documentModels/prebuilt-read:analyze?api-version=2024-11-30"

    req = urllib.request.Request(url, method="POST", data=path.read_bytes())
    req.add_header("Ocp-Apim-Subscription-Key", key)
    req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=60) as res:
        operation = res.headers.get("Operation-Location")
    if not operation:
        return _empty("azure", "no_operation_location")

    for _ in range(30):
        time.sleep(2)
        poll = urllib.request.Request(operation)
        poll.add_header("Ocp-Apim-Subscription-Key", key)
        with urllib.request.urlopen(poll, timeout=60) as res:
            body = json.loads(res.read().decode())
        if body.get("status") == "succeeded":
            result = body.get("analyzeResult", {})
            pages = [
                {
                    "page": p.get("pageNumber", i + 1),
                    "text": " ".join(w.get("content", "") for w in p.get("words", [])),
                    "confidence": _mean([w.get("confidence") for w in p.get("words", [])]),
                }
                for i, p in enumerate(result.get("pages", []))
            ]
            return OCRResult(
                engine="azure-document-intelligence",
                pages=pages,
                text=result.get("content", ""),
                confidence=_mean([p["confidence"] for p in pages]),
                error=None,
            )
        if body.get("status") == "failed":
            return _empty("azure", "analysis_failed")
    return _empty("azure", "timeout")


def _rasterise_pdf(path: Path) -> list:
    """Render an image-only PDF to page images. pypdf can pull the embedded
    images out without a separate poppler install, which keeps the deployment
    to one system dependency instead of two."""
    from io import BytesIO

    from PIL import Image
    from pypdf import PdfReader

    images = []
    try:
        reader = PdfReader(str(path))
        for page in reader.pages:
            for embedded in page.images:
                try:
                    images.append(Image.open(BytesIO(embedded.data)))
                except Exception:  # noqa: BLE001 - skip an unreadable image
                    continue
    except Exception as exc:  # noqa: BLE001
        log.warning("PDF rasterisation failed: %s", exc)
    return images


def _mean(values: list) -> float | None:
    numbers = [float(v) for v in values if isinstance(v, (int, float))]
    return sum(numbers) / len(numbers) if numbers else None


# ────────────────────────────── orchestration ───────────────────────────────

PROVIDERS = {"tesseract": _tesseract, "azure": _azure}


def available_provider() -> str | None:
    """Which provider this deployment can actually use, right now."""
    configured = (settings.ocr_provider or "auto").lower()
    if configured == "none":
        return None
    if configured == "azure" or (configured == "auto" and settings.ocr_api_key):
        return "azure" if settings.ocr_api_key and settings.ocr_endpoint else None
    if configured in ("tesseract", "auto"):
        return "tesseract" if _tesseract_available() else None
    return None


def plausibility(text: str) -> float:
    """How much like real language the output reads, 0..1.

    Needed because the engine's own confidence is not trustworthy on degraded
    Arabic — the benchmark shows Tesseract reporting ~90% confidence on pages it
    read as symbol soup. This is the second, independent signal.

    The weight sits on *token structure*, not character class. Failed Arabic OCR
    still emits mostly letters; what marks it out is that those letters arrive as
    one- and two-character fragments rather than words. Scoring on character
    class alone rated a page of debris at 0.60 — the token-structure weighting
    below rates the same page at 0.48 and a real sentence at 0.93.
    """
    if not text or not text.strip():
        return 0.0

    letters = 0
    junk = 0
    for ch in text:
        if "؀" <= ch <= "ۿ" or ch.isalpha():
            letters += 1
        elif not ch.isspace() and not ch.isdigit():
            junk += 1

    total = letters + junk
    letter_share = letters / total if total else 0.0

    tokens = [t for t in text.split() if t]
    if not tokens:
        return 0.0

    mean_length = sum(len(t) for t in tokens) / len(tokens)
    length_score = min(mean_length / 4.5, 1.0)
    # Words of one or two characters are rare in this domain's Arabic; a page
    # made of them is debris, whatever the characters themselves are.
    fragments = sum(1 for t in tokens if len(t) <= 2) / len(tokens)

    score = 0.25 * letter_share + 0.40 * length_score + 0.35 * (1 - fragments)
    return round(max(0.0, min(score, 1.0)), 3)


def run(path: str | Path, content_type: str) -> OCRResult:
    provider = available_provider()
    if provider is None:
        return _empty("none", "no_provider_configured")
    try:
        result = PROVIDERS[provider](Path(path), content_type)
    except Exception as exc:  # noqa: BLE001 - OCR must never break an upload
        log.warning("OCR failed via %s: %s", provider, exc)
        return _empty(provider, f"{type(exc).__name__}")

    # Two independent quality gates. A reading has to clear both: the engine's
    # own confidence, and whether the output reads like language at all.
    confidence = result.get("confidence")
    score = plausibility(result.get("text") or "")
    result["plausibility"] = score

    low_confidence = confidence is not None and confidence < settings.ocr_min_confidence
    implausible = score < settings.ocr_min_plausibility

    if low_confidence or implausible:
        result["low_confidence"] = True
        result["quality_flag"] = (
            "low_engine_confidence" if low_confidence and not implausible
            else "implausible_text" if implausible and not low_confidence
            else "low_confidence_and_implausible"
        )
    return result
