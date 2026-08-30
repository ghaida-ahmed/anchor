"""Document endpoints.

Access is always checked through the owning course, so a document id from another
account reads as 404. Uploads are multipart; the file is streamed to storage rather
than buffered in memory.
"""

import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DocumentProcessorDep, DocumentServiceDep, StorageDep
from app.core.exceptions import ResourceNotFoundError
from app.core.rate_limit import rate_limit_ai
from app.models import Document
from app.schemas import DocumentRead
from app.services import UploadPayload
from app.services.document_service import ALLOWED_TYPES, parse_upload_filename

router = APIRouter(tags=["documents"])

_AUTH_RESPONSES = {status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."}}
_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Not found for this user."}}

SUPPORTED_EXTENSIONS = ", ".join(sorted(ALLOWED_TYPES)).upper()

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


@router.get(
    "/courses/{course_id}/documents",
    response_model=list[DocumentRead],
    responses={**_AUTH_RESPONSES, **_NOT_FOUND},
    summary="List a course's documents",
)
def list_course_documents(
    service: DocumentServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> list[Document]:
    return service.list_for_course(user.id, course_id)


@router.post(
    "/courses/{course_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_AUTH_RESPONSES,
        **_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": f"Unsupported type, empty file, or over the size limit. "
            f"Accepts {SUPPORTED_EXTENSIONS}."
        },
    },
    summary="Upload a document",
)
async def upload_document(
    service: DocumentServiceDep,
    processor: DocumentProcessorDep,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    course_id: uuid.UUID,
    file: UploadFile = File(..., description=f"A {SUPPORTED_EXTENSIONS} file."),
) -> Document:
    """Stores the file, returns immediately, and processes it in the background.

    The response carries `processing_status: "uploaded"`. Extraction, chunking and
    embedding then run after the response is sent — a 40-page PDF would otherwise
    hold the request open for many seconds. Clients poll the document until it
    reaches `ready` or `failed`.
    """
    display_name, file_type = parse_upload_filename(file.filename)

    # Starlette spools to a temp file past a threshold, so size comes from seeking
    # the underlying stream rather than from a client-supplied header. `UploadFile`
    # exposes only absolute seeks, hence going through `.file` here.
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)

    payload = UploadPayload(
        original_filename=display_name,
        file_type=file_type,
        size=size,
        stream=file.file,
    )
    document = service.create(user.id, course_id, payload)

    background_tasks.add_task(processor.process, document.id)
    return document


@router.get(
    "/documents/{document_id}",
    response_model=DocumentRead,
    responses={**_AUTH_RESPONSES, **_NOT_FOUND},
    summary="Read one document's metadata",
)
def get_document(
    service: DocumentServiceDep, user: CurrentUser, document_id: uuid.UUID
) -> Document:
    return service.get(user.id, document_id)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_AUTH_RESPONSES, **_NOT_FOUND},
    summary="Delete a document and its stored file",
)
def delete_document(
    service: DocumentServiceDep, user: CurrentUser, document_id: uuid.UUID
) -> None:
    service.delete(user.id, document_id)


@router.post(
    "/documents/{document_id}/reprocess",
    dependencies=[Depends(rate_limit_ai)],
    response_model=DocumentRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_AUTH_RESPONSES, **_NOT_FOUND},
    summary="Re-extract and re-embed a document",
)
def reprocess_document(
    service: DocumentServiceDep,
    processor: DocumentProcessorDep,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    document_id: uuid.UUID,
) -> Document:
    """Rebuild a document's chunks from its stored file.

    Needed whenever the embedding provider or model changes: vectors from different
    models are not comparable, so existing chunks must be regenerated rather than
    mixed. Also the way to retry a document that failed processing, without
    deleting and re-uploading it.

    Returns immediately; the work runs in the background like the original upload.
    `force` bypasses the "already ready, nothing to do" short-circuit.
    """
    document = service.get(user.id, document_id)
    background_tasks.add_task(processor.process, document.id, force=True)
    return document


@router.get(
    "/documents/{document_id}/download",
    responses={**_AUTH_RESPONSES, **_NOT_FOUND},
    summary="Download a document's original file",
    response_class=FileResponse,
)
def download_document(
    service: DocumentServiceDep,
    storage: StorageDep,
    user: CurrentUser,
    document_id: uuid.UUID,
) -> FileResponse:
    """Serves the stored file so a citation can open its source.

    Ownership is checked first; the path comes from the storage layer, never from
    anything the client sent.
    """
    document = service.get(user.id, document_id)

    if not storage.exists(document.storage_path):
        raise ResourceNotFoundError("Document file", str(document_id))

    return FileResponse(
        path=storage.get_path(document.storage_path),
        filename=document.original_filename,
        media_type=MEDIA_TYPES.get(document.file_type.value, "application/octet-stream"),
        # inline so a browser can display a PDF rather than forcing a save.
        content_disposition_type="inline",
    )
