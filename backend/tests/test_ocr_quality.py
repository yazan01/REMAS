"""OCR quality gates — the AI-07 controls.

The benchmark (`python -m scripts.ocrbench`) produces the accuracy numbers.
These tests pin the *behaviour* those numbers justified: that a reading which
cannot be trusted is flagged rather than passed through, and that the pipeline
never silently reports a scan as an empty document.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.ai import ocr
from app.services.ai.extraction import detect_language


class TestPlausibility:
    """The second quality gate. Needed because the benchmark showed Tesseract
    reporting ~90% confidence on Arabic pages it had read as symbol soup — the
    engine's own confidence is not a usable trust signal on degraded scans."""

    def test_real_arabic_scores_high(self):
        text = "ميثاق الحوكمة المعتمد من مجلس الإدارة ومصفوفة الصلاحيات"
        assert ocr.plausibility(text) >= 0.8

    def test_real_english_scores_high(self):
        assert ocr.plausibility("Approved governance charter and authority matrix") >= 0.8

    def test_symbol_soup_scores_low(self):
        # Taken verbatim from a failed benchmark page.
        soup = "5 | J الاعتبا be ) منتمر = Hy pal 3 a | 7 ض خطة إدا a : : 0 ب : 0"
        assert ocr.plausibility(soup) < settings.ocr_min_plausibility

    def test_empty_scores_zero(self):
        assert ocr.plausibility("") == 0.0
        assert ocr.plausibility("   ") == 0.0

    def test_single_glyph_debris_scores_low(self):
        assert ocr.plausibility("a | 3 ب : 0 7 = )") < settings.ocr_min_plausibility

    def test_gate_ranks_good_above_bad(self):
        good = ocr.plausibility("تقرير المراجعة الداخلية للربع الثالث")
        bad = ocr.plausibility("| 3 ب : 0 7 = ) a")
        assert good > bad


class TestOCRPipeline:
    def test_no_provider_is_reported_not_faked(self, monkeypatch):
        """With OCR switched off a scan must come back flagged, never as an
        empty document — an empty extraction would make the evidence-coverage
        stage describe perfectly good evidence as missing."""
        monkeypatch.setattr(settings, "ocr_provider", "none")
        result = ocr.run(Path("nonexistent.png"), "image/png")
        assert result["text"] == ""
        assert result["error"] == "no_provider_configured"
        assert result["engine"] == "none"

    def test_unreadable_file_does_not_raise(self, tmp_path, monkeypatch):
        """A corrupt upload must not break the request that carries it."""
        monkeypatch.setattr(settings, "ocr_provider", "tesseract")
        broken = tmp_path / "broken.png"
        broken.write_bytes(b"not actually a png")
        result = ocr.run(broken, "image/png")
        assert result["text"] == ""
        assert result["error"]

    @pytest.mark.skipif(
        ocr.available_provider() != "tesseract",
        reason="Tesseract is not installed in this environment",
    )
    def test_reads_rendered_arabic_and_flags_nothing(self, tmp_path):
        """End to end on a clean page: the text comes back, the language is
        detected as Arabic, and neither quality gate fires."""
        from scripts.ocrbench import render

        source = "ميثاق الحوكمة المعتمد من مجلس الإدارة"
        page = tmp_path / "page.png"
        if not render(source, "print-300dpi", page):
            pytest.skip("no Arabic-capable font on this machine")

        result = ocr.run(page, "image/png")
        assert result["engine"] == "tesseract"
        assert result["text"].strip()
        assert detect_language(result["text"]) == "ar"
        assert result["plausibility"] >= settings.ocr_min_plausibility
        assert not result.get("low_confidence")

        # And it is actually the right text, not merely plausible text.
        from scripts.ocrbench import cer

        assert cer(source, result["text"]) < 0.15

    @pytest.mark.skipif(
        ocr.available_provider() != "tesseract",
        reason="Tesseract is not installed in this environment",
    )
    def test_degraded_page_is_flagged_rather_than_trusted(self, tmp_path):
        from scripts.ocrbench import render

        page = tmp_path / "fax.png"
        if not render("خطة إدارة المخاطر واستمرارية الأعمال", "fax-100dpi", page):
            pytest.skip("no Arabic-capable font on this machine")

        result = ocr.run(page, "image/png")
        # Whatever it read, it must not be presented as trustworthy.
        assert result.get("low_confidence") or not result["text"].strip()
        if result["text"].strip():
            assert result["quality_flag"]

    @pytest.mark.skipif(
        ocr.available_provider() != "tesseract",
        reason="Tesseract is not installed in this environment",
    )
    def test_arabic_is_requested_explicitly(self):
        """Autodetect is where most Arabic OCR accuracy is lost, so the language
        pair is configuration and Arabic is always in it."""
        assert "ara" in settings.ocr_languages


class TestBenchmarkMetrics:
    def test_cer_is_zero_for_identical_text(self):
        from scripts.ocrbench import cer

        assert cer("ميثاق الحوكمة", "ميثاق الحوكمة") == 0.0

    def test_cer_ignores_orthographic_variants(self):
        """أ/ا and ة/ه are transcription choices, not OCR errors."""
        from scripts.ocrbench import cer

        assert cer("الإدارة", "الاداره") == 0.0

    def test_cer_counts_real_substitutions(self):
        from scripts.ocrbench import cer

        assert cer("الحوكمة", "الحوكمت") > 0

    def test_wer_counts_whole_words(self):
        from scripts.ocrbench import wer

        assert wer("ميثاق الحوكمة المعتمد", "ميثاق الحوكمة المعتمد") == 0.0
        assert wer("ميثاق الحوكمة المعتمد", "ميثاق الحوكمة") == pytest.approx(1 / 3)
