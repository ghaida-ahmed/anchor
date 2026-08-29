"""Extractor registry.

`get_extractor` is the only way the processing pipeline reaches a format-specific
implementation, so adding a format is one entry here plus one class.
"""

from app.models import DocumentFileType
from app.services.rag.extraction.base import (
    DocumentExtractor,
    ExtractedPage,
    ExtractionError,
)
from app.services.rag.extraction.pdf import PdfExtractor
from app.services.rag.extraction.text import PlainTextExtractor

_EXTRACTORS: dict[DocumentFileType, DocumentExtractor] = {
    DocumentFileType.PDF: PdfExtractor(),
    DocumentFileType.TXT: PlainTextExtractor(),
    DocumentFileType.MD: PlainTextExtractor(),
}


def get_extractor(file_type: DocumentFileType) -> DocumentExtractor:
    extractor = _EXTRACTORS.get(file_type)
    if extractor is None:
        raise ExtractionError(f"'{file_type.value}' documents cannot be processed.")
    return extractor


__all__ = [
    "DocumentExtractor",
    "ExtractedPage",
    "ExtractionError",
    "PdfExtractor",
    "PlainTextExtractor",
    "get_extractor",
]
