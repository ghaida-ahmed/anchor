import uuid
from datetime import datetime

from app.models.document import DocumentFileType, ProcessingStatus
from app.schemas.common import ORMModel


class DocumentRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    filename: str
    original_filename: str
    file_type: DocumentFileType
    file_size: int
    processing_status: ProcessingStatus
    # Populated only when processing_status is `failed`. Written for a student to
    # read — never a stack trace.
    processing_error: str | None
    created_at: datetime
    updated_at: datetime

    # `storage_path` is intentionally absent: it is an internal storage key and
    # nothing outside the service layer has any use for it.
