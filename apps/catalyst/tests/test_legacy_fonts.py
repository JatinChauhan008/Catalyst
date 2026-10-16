"""Legacy Indic fonts: the OCR language comes from the font, or the problem is reported."""

from __future__ import annotations

import pytest
from catalyst.legacy_fonts import dominant_language, find_legacy_fonts, font_language
from catalyst.models import ConvertRequest


@pytest.mark.parametrize(
    ("name", "language"),
    [
        ("RMCNFX+KrutiDev010", "hi-IN"),  # from a real Hindi PDF
        ("Kruti Dev 010", "hi-IN"),
        ("DevLys 010", "hi-IN"),
        ("Walkman-Chanakya-905", "hi-IN"),
        ("AkrutiOriSarala06Normal", "od-IN"),  # from a real Odia PDF
        ("AkPOriSaralaBold", "od-IN"),
        ("OR-TTSarala", "od-IN"),
        ("SutonnyMJ", "bn-IN"),
        ("LMG-Arun", "gu-IN"),
        ("Bamini", "ta-IN"),
        # Unicode or Latin fonts, and unnamed Type 3 fonts: not legacy.
        ("Mangal", None),
        ("ZJBWCG+Utsaah", None),
        ("Nirmala UI", None),
        ("Kalinga", None),
        ("VKKQCF+ArialMT", None),
        ("TT3B3t00", None),
        ("", None),
    ],
)
def test_the_font_name_tells_a_legacy_font_and_its_language(
    name: str, language: str | None
) -> None:
    assert font_language(name) == language


# "हिमाचल प्रदेश फल एवं बेमौसमी सब्जी उत्पादन में अग्रणी है" in Kruti Dev.
KRUTI_DEV_TEXT = "fgekpy çns'k Qy ,oa csekSleh lCth mRiknu esa vxz.kh gS"


def _pdf_with_font(font: str, text: str = KRUTI_DEV_TEXT) -> bytes:
    """A one-page PDF that writes `text` in a non-embedded font named `font`."""
    content = b"BT /F1 24 Tf 50 700 Td (%s) Tj ET" % text.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /TrueType /BaseFont /%s "
        b"/Encoding /WinAnsiEncoding >>" % font.encode(),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def test_legacy_fonts_are_found_in_a_pdf() -> None:
    fonts = find_legacy_fonts(_pdf_with_font("KrutiDev010"))
    assert [(f.name, f.language) for f in fonts] == [("KrutiDev010", "hi-IN")]
    assert dominant_language(fonts) == "hi-IN"
    assert find_legacy_fonts(_pdf_with_font("Helvetica", "Hello")) == []


def _sarvam(fake_sarvam, **extra) -> dict:
    return {
        "__variant__": "SarvamOcrOptions",
        "api_key": "test-key",
        "base_url": fake_sarvam.base_url,
        "poll_interval_seconds": 0.05,
        **extra,
    }


def test_without_a_language_the_ocr_language_comes_from_the_font(
    service, fake_sarvam
) -> None:
    request = ConvertRequest.model_validate(
        {
            "export": {"to_formats": ["md"]},
            "formats": {
                "pdf": {"pipeline_options": {"ocr_options": _sarvam(fake_sarvam)}}
            },
        }
    )
    envelope = service.convert("hindi.pdf", _pdf_with_font("KrutiDev010"), request)

    assert envelope.processing is not None
    assert envelope.processing.ocr_language_from_font == (
        "hi-IN, from the legacy font KrutiDev010"
    )
    # The page was sent to Sarvam in Hindi, and the garbled text layer is gone.
    assert fake_sarvam.submissions[-1]["language"] == "hi-IN"
    markdown = envelope.outputs[0].content or ""
    assert "fgekpy" not in markdown
    assert fake_sarvam.lines[0] in markdown


def test_a_language_set_by_the_user_is_kept_and_a_mismatch_reported(
    service, fake_sarvam
) -> None:
    request = ConvertRequest.model_validate(
        {
            "export": {"to_formats": ["md"]},
            "formats": {
                "pdf": {
                    "pipeline_options": {
                        "ocr_options": _sarvam(fake_sarvam, lang=["ta-IN"])
                    }
                }
            },
        }
    )
    envelope = service.convert("hindi.pdf", _pdf_with_font("KrutiDev010"), request)

    assert envelope.processing is not None
    assert envelope.processing.ocr_language_from_font is None
    assert fake_sarvam.submissions[-1]["language"] == "ta-IN"
    [problem] = [e for e in envelope.errors if e.component == "legacy_font"]
    assert "hi-IN" in problem.message and "ta-IN" in problem.message


def test_a_legacy_font_read_without_ocr_is_reported(service) -> None:
    request = ConvertRequest.model_validate(
        {
            "export": {"to_formats": ["md"]},
            "formats": {"pdf": {"pipeline_options": {"do_ocr": False}}},
        }
    )
    envelope = service.convert("hindi.pdf", _pdf_with_font("KrutiDev010"), request)

    [problem] = [e for e in envelope.errors if e.component == "legacy_font"]
    assert "KrutiDev010" in problem.message and "Sarvam OCR" in problem.message
