"""Course endpoints.

Routes return ORM instances and let `response_model` serialise them, which keeps the
public shape (`CourseRead`) separate from the table shape (`Course`). Ownership comes
from `CurrentUser`; a course id belonging to another user reads as 404.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CourseServiceDep, CurrentUser, StorageDep
from app.models import Course
from app.schemas import CourseCreate, CourseRead, CourseUpdate, CourseWithCounts

router = APIRouter(prefix="/courses", tags=["courses"])

_AUTH_RESPONSES = {status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."}}
_COURSE_RESPONSES = {
    **_AUTH_RESPONSES,
    status.HTTP_404_NOT_FOUND: {"description": "No such course for this user."},
}


def _with_count(course: Course, document_count: int) -> CourseWithCounts:
    return CourseWithCounts.model_validate(
        {
            **CourseRead.model_validate(course).model_dump(),
            "document_count": document_count,
        }
    )


@router.get(
    "",
    response_model=list[CourseWithCounts],
    responses=_AUTH_RESPONSES,
    summary="List your courses",
)
def list_courses(service: CourseServiceDep, user: CurrentUser) -> list[CourseWithCounts]:
    return [
        _with_count(course, count) for course, count in service.list_for_user(user.id)
    ]


@router.post(
    "",
    response_model=CourseWithCounts,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_409_CONFLICT: {"description": "Course code already used."},
    },
    summary="Create a course",
)
def create_course(
    service: CourseServiceDep, user: CurrentUser, payload: CourseCreate
) -> CourseWithCounts:
    return _with_count(service.create(user.id, payload), 0)


@router.get(
    "/{course_id}",
    response_model=CourseWithCounts,
    responses=_COURSE_RESPONSES,
    summary="Read one course",
)
def get_course(
    service: CourseServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> CourseWithCounts:
    course, count = service.get_with_count(user.id, course_id)
    return _with_count(course, count)


@router.patch(
    "/{course_id}",
    response_model=CourseWithCounts,
    responses={
        **_COURSE_RESPONSES,
        status.HTTP_409_CONFLICT: {"description": "Course code already used."},
    },
    summary="Update a course",
)
def update_course(
    service: CourseServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
    payload: CourseUpdate,
) -> CourseWithCounts:
    course = service.update(user.id, course_id, payload)
    _, count = service.get_with_count(user.id, course.id)
    return _with_count(course, count)


@router.delete(
    "/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_COURSE_RESPONSES,
    summary="Delete a course and its documents",
)
def delete_course(
    service: CourseServiceDep,
    storage: StorageDep,
    user: CurrentUser,
    course_id: uuid.UUID,
) -> None:
    # The rows cascade in the database; the files are removed afterwards so a
    # storage failure cannot roll back a committed delete.
    for key in service.delete(user.id, course_id):
        storage.delete(key)
