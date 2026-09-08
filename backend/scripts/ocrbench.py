"""OCR quality benchmark — the AI-07 evidence pack.

    python -m scripts.ocrbench                    # synthetic corpus
    python -m scripts.ocrbench --corpus ./docs    # iValue's real documents

AI-07 asks the vendor to *state model limitations and quality controls for
Arabic document analysis*. A claim is not a statement; a measurement is. This
script produces the measurement.

Metrics
-------
* **CER** — character error rate (Levenshtein distance ÷ reference length).
  The standard OCR metric, and the one that survives Arabic's ligatures where a
  word-level metric would over-penalise.
* **WER** — word error rate, the number a reviewer feels.
* **confidence** — what the engine itself claims, so its calibration can be
  compared against the error it actually made. An engine that is confidently
  wrong is more dangerous than one that admits doubt.

Real corpus format
------------------
Put document images in a directory with a matching `.txt` of ground truth:

    docs/contract-01.png
    docs/contract-01.txt

Without a corpus the script renders its own Arabic pages at four quality
levels, so the harness is exercised end to end even before client files arrive.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.ai import ocr  # noqa: E402

# Representative sentences from the assessment domain, so the benchmark
# measures the vocabulary the product actually meets.
SAMPLES = [
    "ميثاق الحوكمة المعتمد من مجلس الإدارة",
    "مصفوفة الصلاحيات المالية والتشغيلية",
    "تقرير المراجعة الداخلية للربع الثالث",
    "خطة إدارة المخاطر واستمرارية الأعمال",
    "دراسة الجدوى الاقتصادية للمشروع السكني",
]


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def normalise(text: str) -> str:
    """Fold the differences that do not change meaning: Arabic diacritics, the
    tatweel elongation mark, and alef/ya variants an OCR engine may pick
    differently from the source without being wrong."""
    import unicodedata

    text = unicodedata.normalize("NFKC", text)
    drop = {0x0640}  # tatweel
    text = "".join(
        ch for ch in text if not unicodedata.combining(ch) and ord(ch) not in drop
    )
    for source, target in (("أإآ", "ا"), ("ى", "ي"), ("ة", "ه")):
        for ch in source:
            text = text.replace(ch, target)
    return " ".join(text.split())


def cer(reference: str, hypothesis: str) -> float:
    reference, hypothesis = normalise(reference), normalise(hypothesis)
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return levenshtein(reference, hypothesis) / len(reference)


def wer(reference: str, hypothesis: str) -> float:
    ref_words = normalise(reference).split()
    hyp_words = normalise(hypothesis).split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    # Levenshtein over word tokens.
    previous = list(range(len(hyp_words) + 1))
    for i, rw in enumerate(ref_words, start=1):
        current = [i]
        for j, hw in enumerate(hyp_words, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (rw != hw))
            )
        previous = current
    return previous[-1] / len(ref_words)


# ─────────────────────────── synthetic corpus ───────────────────────────────


def _arabic_font(size: int):
    """An Arabic-capable font from the OS. Without one the renderer draws
    boxes, which would measure the font rather than the OCR engine."""
    from PIL import ImageFont

    candidates = [
        "C:/Windows/Fonts/trado.ttf",      # Traditional Arabic
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return None


def _shape(text: str) -> str:
    """Arabic needs contextual shaping and bidi ordering before it can be drawn
    as a bitmap. PIL draws glyphs left to right without either, so the text is
    shaped here — otherwise the benchmark would measure a rendering bug rather
    than OCR accuracy."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text[::-1]  # crude fallback: at least the reading order is right


def render(text: str, quality: str, path: Path) -> bool:
    from PIL import Image, ImageDraw, ImageFilter

    # Named for the physical artefact each one imitates, at roughly the DPI
    # that artefact is produced at.
    presets = {
        "print-300dpi": {"scale": 2.4, "blur": 0.0, "noise": 0, "rotate": 0.0},
        "scan-200dpi": {"scale": 1.8, "blur": 0.4, "noise": 8, "rotate": 0.4},
        "photo-150dpi": {"scale": 1.3, "blur": 0.8, "noise": 18, "rotate": 1.2},
        "fax-100dpi": {"scale": 0.9, "blur": 1.1, "noise": 26, "rotate": 2.0},
    }
    preset = presets[quality]
    size = int(34 * preset["scale"])
    font = _arabic_font(size)
    if font is None:
        return False

    shaped = _shape(text)
    width, height = int(1100 * preset["scale"]), int(120 * preset["scale"])
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    draw.text((int(40 * preset["scale"]), int(35 * preset["scale"])), shaped, font=font, fill=20)

    if preset["rotate"]:
        image = image.rotate(preset["rotate"], resample=Image.BICUBIC, fillcolor=255)
    if preset["blur"]:
        image = image.filter(ImageFilter.GaussianBlur(preset["blur"]))
    if preset["noise"]:
        import random

        random.seed(7)
        pixels = image.load()
        for _ in range(int(width * height * preset["noise"] / 1000)):
            x, y = random.randrange(width), random.randrange(height)
            pixels[x, y] = random.choice((0, 255))

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return True


def build_synthetic(root: Path) -> list[tuple[Path, str, str]]:
    cases: list[tuple[Path, str, str]] = []
    for quality in ("print-300dpi", "scan-200dpi", "photo-150dpi", "fax-100dpi"):
        for index, text in enumerate(SAMPLES, start=1):
            path = root / quality / f"sample-{index}.png"
            if render(text, quality, path):
                cases.append((path, text, quality))
    return cases


def load_corpus(root: Path) -> list[tuple[Path, str, str]]:
    cases: list[tuple[Path, str, str]] = []
    for image in sorted(root.rglob("*")):
        if image.suffix.lower() not in (".png", ".jpg", ".jpeg", ".pdf"):
            continue
        truth = image.with_suffix(".txt")
        if not truth.exists():
            print(f"  skipped (no ground truth): {image.name}")
            continue
        cases.append((image, truth.read_text(encoding="utf-8"), "client"))
    return cases


# ──────────────────────────────── benchmark ─────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="REMAS OCR quality benchmark")
    parser.add_argument("--corpus", default=None, help="directory of real documents + .txt truth")
    parser.add_argument("--provider", default=None, help="force one provider")
    args = parser.parse_args()

    if args.provider:
        settings.ocr_provider = args.provider

    provider = ocr.available_provider()
    print(f"provider: {provider or 'NONE CONFIGURED'}")
    print(f"languages requested: {settings.ocr_languages}")
    print(f"confidence floor: {settings.ocr_min_confidence}")
    if provider is None:
        print("\nNo OCR provider is configured — nothing to measure.")
        raise SystemExit(1)

    if args.corpus:
        cases = load_corpus(Path(args.corpus))
        print(f"corpus: {args.corpus}  ({len(cases)} documents with ground truth)")
    else:
        root = Path(settings.storage_dir).parent / "ocr-bench"
        cases = build_synthetic(root)
        print(f"corpus: synthetic, rendered to {root}  ({len(cases)} pages)")
        if not cases:
            print("\nNo Arabic-capable font was found, so nothing could be rendered.")
            raise SystemExit(1)

    by_quality: dict[str, list[dict]] = {}
    print()
    for path, truth, quality in cases:
        content_type = "application/pdf" if path.suffix.lower() == ".pdf" else "image/png"
        started = time.perf_counter()
        result = ocr.run(path, content_type)
        elapsed = time.perf_counter() - started

        hypothesis = result.get("text") or ""
        row = {
            "cer": cer(truth, hypothesis),
            "wer": wer(truth, hypothesis),
            "confidence": result.get("confidence"),
            "seconds": elapsed,
            "low_confidence": bool(result.get("low_confidence")),
            "plausibility": result.get("plausibility"),
            "flag": result.get("quality_flag"),
            "error": result.get("error"),
            "name": path.name,
            "truth": truth,
            "text": hypothesis,
        }
        by_quality.setdefault(quality, []).append(row)

    print(f"{'source':<14} {'n':>3}  {'CER':>7} {'WER':>7} {'conf':>7} {'sec':>6}   verdict")
    print("-" * 72)

    overall: list[dict] = []
    for quality, rows in by_quality.items():
        overall.extend(rows)
        mean_cer = statistics.mean(r["cer"] for r in rows)
        mean_wer = statistics.mean(r["wer"] for r in rows)
        confidences = [r["confidence"] for r in rows if r["confidence"] is not None]
        mean_conf = statistics.mean(confidences) if confidences else float("nan")
        mean_time = statistics.mean(r["seconds"] for r in rows)
        verdict = (
            "usable" if mean_cer <= 0.15 else "review required" if mean_cer <= 0.40 else "not usable"
        )
        print(
            f"{quality:<14} {len(rows):>3}  {mean_cer:>6.1%} {mean_wer:>6.1%} "
            f"{mean_conf:>6.1%} {mean_time:>6.2f}   {verdict}"
        )

    mean_cer = statistics.mean(r["cer"] for r in overall)
    confidences = [(r["confidence"], r["cer"]) for r in overall if r["confidence"] is not None]

    print("-" * 72)
    print(f"{'ALL':<14} {len(overall):>3}  {mean_cer:>6.1%}")

    # Does the plausibility gate catch what the engine's confidence misses?
    flagged = [r for r in overall if r["low_confidence"]]
    passed = [r for r in overall if not r["low_confidence"]]
    print("\nquality gates (AI-07 controls):")
    if passed:
        print(f"  passed both gates:  mean CER {statistics.mean(r['cer'] for r in passed):>6.1%}  (n={len(passed)})")
    if flagged:
        print(f"  flagged for review: mean CER {statistics.mean(r['cer'] for r in flagged):>6.1%}  (n={len(flagged)})")
        reasons = {}
        for r in flagged:
            reasons[r["flag"]] = reasons.get(r["flag"], 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"      {reason}: {count}")
    if passed and flagged and statistics.mean(r["cer"] for r in flagged) > statistics.mean(r["cer"] for r in passed):
        print("  -> the gates separate readings that can be trusted from ones that cannot.")

    # Calibration: does the engine's own confidence track the error it made?
    if len(confidences) > 2:
        highs = [c for conf, c in confidences if conf >= settings.ocr_min_confidence]
        lows = [c for conf, c in confidences if conf < settings.ocr_min_confidence]
        print("\nconfidence calibration (the quality control AI-07 asks for):")
        if highs:
            print(f"  above the {settings.ocr_min_confidence:.0%} floor: mean CER {statistics.mean(highs):.1%}  (n={len(highs)})")
        if lows:
            print(f"  below the floor, flagged for review: mean CER {statistics.mean(lows):.1%}  (n={len(lows)})")
        if highs and lows and statistics.mean(lows) > statistics.mean(highs):
            print("  -> the floor separates good readings from bad ones; the flag is meaningful.")
        elif highs and lows:
            print("  -> the floor is NOT separating good from bad; retune ocr_min_confidence.")

    worst = max(overall, key=lambda r: r["cer"])
    print("\nworst page:")
    print(f"  {worst['name']}  CER {worst['cer']:.1%}")
    print(f"  expected: {worst['truth'][:70]}")
    print(f"  read:     {(worst['text'] or '(nothing)')[:70]}")

    print(
        "\nStated limitation: measured on "
        + ("iValue's own documents" if args.corpus else "a synthetic corpus")
        + f" with {provider}. "
        + (
            "Re-run with --corpus against real client scans before sign-off."
            if not args.corpus
            else "This is the acceptance measurement."
        )
    )


if __name__ == "__main__":
    main()
