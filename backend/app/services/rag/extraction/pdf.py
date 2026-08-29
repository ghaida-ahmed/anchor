"""PDF text extraction, preserving page numbers."""

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.rag.extraction.base import (
    DocumentExtractor,
    ExtractedPage,
    ExtractionError,
)
from app.services.rag.normalise import normalise_text

# A page holding less than this after normalisation is treated as empty. Slide
# decks often carry a stray page number or footer on an otherwise blank page.
MIN_PAGE_CHARS = 20


class PdfExtractor(DocumentExtractor):
    """Reads a PDF's embedded text layer with pypdf.

    There is no OCR. A scanned or image-only PDF has no text layer, so extraction
    yields nothing and raises `ExtractionError` — the document is marked failed
    rather than silently indexed as empty.
    """

    def extract(self, path: Path) -> list[ExtractedPage]:
        try:
            reader = PdfReader(str(path))
        except (PdfReadError, OSError, ValueError) as error:
            raise ExtractionError(
                "The PDF could not be opened or is corrupted."
            ) from error

        if reader.is_encrypted:
            # An empty user password is common and pypdf can open those; anything
            # else needs a password we do not have.
            try:
                if reader.decrypt("") == 0:
                    raise ExtractionError("The PDF is password protected.")
            except (PdfReadError, NotImplementedError) as error:
                raise ExtractionError("The PDF is password protected.") from error

        pages: list[ExtractedPage] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text() or ""
            except Exception as error:  # pypdf raises assorted errors per page
                raise ExtractionError(
                    f"Text could not be read from page {index} of the PDF."
                ) from error

            text = normalise_text(raw)
            if len(text) >= MIN_PAGE_CHARS:
                pages.append(ExtractedPage(page_number=index, text=text))

        if not pages:
            raise ExtractionError(
                "No readable text was found in this PDF. Scanned or image-only "
                "documents are not supported."
            )

        return pages
