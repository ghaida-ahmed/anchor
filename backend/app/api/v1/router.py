"""Versioned API router.

Health is mounted separately in `main.py` at `/api/health`: infrastructure probes
should not have to track the API version.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    courses,
    documents,
    knowledge,
    learning,
    rag,
    retention,
    study_guide,
)

api_v1_router = APIRouter()
api_v1_router.include_router(auth.router)
api_v1_router.include_router(courses.router)
api_v1_router.include_router(documents.router)
api_v1_router.include_router(rag.router)
api_v1_router.include_router(learning.router)
api_v1_router.include_router(retention.router)
api_v1_router.include_router(knowledge.router)
api_v1_router.include_router(study_guide.router)
