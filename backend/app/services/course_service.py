"""Course business logic.

Every method takes the authenticated `user_id` and scopes its query by it. Ownership
is enforced in the query itself rather than checked afterwards, so there is no path
that loads another user's row at all.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.models import Course, Document
from app.schemas import CourseCreate, CourseUpdate


class CourseService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Course, int]]:
        """Courses with their document counts, newest first.

        A LEFT JOIN aggregate rather than a count per course — the N+1 would show up
        immediately on a dashboard that renders every course.
        """
        rows = self.session.execute(
            select(Course, func.count(Document.id))
            .outerjoin(Document, Document.course_id == Course.id)
            .where(Course.user_id == user_id)
            .group_by(Course.id)
            .order_by(Course.created_at.desc())
        ).all()
        return [(course, count) for course, count in rows]

    def get(self, user_id: uuid.UUID, course_id: uuid.UUID) -> Course:
        course = self.session.scalar(
            select(Course).where(Course.id == course_id, Course.user_id == user_id)
        )
        if course is None:
            # 404 rather than 403: a course belonging to someone else should be
            # indistinguishable from one that does not exist.
            raise ResourceNotFoundError("Course", str(course_id))
        return course

    def get_with_count(
        self, user_id: uuid.UUID, course_id: uuid.UUID
    ) -> tuple[Course, int]:
        course = self.get(user_id, course_id)
        count = self.session.scalar(
            select(func.count(Document.id)).where(Document.course_id == course.id)
        )
        return course, count or 0

    def create(self, user_id: uuid.UUID, payload: CourseCreate) -> Course:
        if payload.code:
            self._assert_code_available(user_id, payload.code)

        course = Course(
            user_id=user_id,
            title=payload.title,
            code=payload.code,
            description=payload.description,
        )
        self.session.add(course)
        self.session.commit()
        self.session.refresh(course)
        return course

    def update(
        self, user_id: uuid.UUID, course_id: uuid.UUID, payload: CourseUpdate
    ) -> Course:
        course = self.get(user_id, course_id)
        changes = payload.model_dump(exclude_unset=True)

        new_code = changes.get("code")
        if new_code and new_code != course.code:
            self._assert_code_available(user_id, new_code, exclude_id=course.id)

        for field, value in changes.items():
            setattr(course, field, value)

        self.session.commit()
        self.session.refresh(course)
        return course

    def delete(self, user_id: uuid.UUID, course_id: uuid.UUID) -> list[str]:
        """Deletes the course and returns the storage keys its documents used.

        The caller removes the files. The service does not touch storage itself: a
        failed unlink must not roll back — or be rolled back by — the transaction.
        """
        course = self.get(user_id, course_id)
        keys = [
            key
            for key in self.session.scalars(
                select(Document.storage_path).where(Document.course_id == course.id)
            )
        ]
        self.session.delete(course)
        self.session.commit()
        return keys

    def _assert_code_available(
        self,
        user_id: uuid.UUID,
        code: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        query = select(Course.id).where(Course.user_id == user_id, Course.code == code)
        if exclude_id is not None:
            query = query.where(Course.id != exclude_id)

        if self.session.scalar(query) is not None:
            raise DuplicateResourceError(
                f"You already have a course with the code '{code}'."
            )
