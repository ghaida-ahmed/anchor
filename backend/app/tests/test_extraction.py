"""Text extraction from each supported format."""

from pathlib import Path

import pytest

from app.models import DocumentFileType
from app.services.rag.extraction import ExtractionError, get_extractor
from app.services.rag.normalise import normalise_text
from app.tests.factories import make_image_only_pdf, make_text_pdf


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_pdf_extraction_preserves_page_numbers(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "lecture.pdf",
        make_text_pdf(
            [
                "TCP halves the congestion window after packet loss.",
                "DNS resolves human readable names into IP addresses.",
                "BGP exchanges routing information between systems.",
            ]
        ),
    )

    pages = get_extractor(DocumentFileType.PDF).extract(path)

    assert [page.page_number for page in pages] == [1, 2, 3]
    assert "congestion window" in pages[0].text
    assert "DNS" in pages[1].text
    assert "BGP" in pages[2].text


def test_pdf_without_a_text_layer_fails_clearly(tmp_path: Path) -> None:
    """Scanned documents must fail, not be indexed as empty. There is no OCR."""
    path = write(tmp_path, "scan.pdf", make_image_only_pdf())

    with pytest.raises(ExtractionError) as caught:
        get_extractor(DocumentFileType.PDF).extract(path)

    assert "image-only" in str(caught.value)


def test_corrupt_pdf_fails_clearly(tmp_path: Path) -> None:
    path = write(tmp_path, "broken.pdf", b"%PDF-1.4\nnot really a pdf")

    with pytest.raises(ExtractionError):
        get_extractor(DocumentFileType.PDF).extract(path)


def test_text_extraction_is_a_single_page(tmp_path: Path) -> None:
    path = write(tmp_path, "notes.txt", b"Sliding windows provide flow control.")

    pages = get_extractor(DocumentFileType.TXT).extract(path)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "Sliding windows" in pages[0].text


def test_markdown_keeps_its_structure(tmp_path: Path) -> None:
    """Headings and list markers are useful structure, not noise to strip."""
    path = write(tmp_path, "summary.md", b"# Transport Layer\n\n- TCP\n- UDP\n")

    pages = get_extractor(DocumentFileType.MD).extract(path)

    assert "# Transport Layer" in pages[0].text
    assert "- TCP" in pages[0].text


def test_empty_text_file_fails(tmp_path: Path) -> None:
    path = write(tmp_path, "blank.txt", b"   \n\n  \t \n")

    with pytest.raises(ExtractionError):
        get_extractor(DocumentFileType.TXT).extract(path)


def test_undecodable_bytes_do_not_crash(tmp_path: Path) -> None:
    path = write(tmp_path, "latin.txt", b"Caf\xe9 protocols and windows")

    pages = get_extractor(DocumentFileType.TXT).extract(path)

    assert "protocols" in pages[0].text


class TestNormalisation:
    def test_collapses_horizontal_runs(self) -> None:
        assert normalise_text("TCP     UDP") == "TCP UDP"

    def test_rejoins_hyphenated_line_breaks(self) -> None:
        assert normalise_text("conges-\ntion") == "congestion"

    def test_keeps_paragraph_breaks(self) -> None:
        assert normalise_text("One.\n\nTwo.") == "One.\n\nTwo."

    def test_collapses_excess_blank_lines(self) -> None:
        assert normalise_text("One.\n\n\n\n\nTwo.") == "One.\n\nTwo."

    def test_strips_control_characters(self) -> None:
        assert normalise_text("TCP\x00\x07 UDP") == "TCP UDP"
