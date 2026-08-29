import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { FormError } from '@/components/ui/ErrorState';
import { Spinner } from '@/components/ui/Spinner';
import { useDeleteCourse } from '@/hooks/queries/useCourses';
import { toErrorMessage } from '@/services/api/client';
import type { Course } from '@/types/domain';

interface DeleteCourseDialogProps {
  open: boolean;
  course: Course;
  onClose: () => void;
  onDeleted: () => void;
}

export function DeleteCourseDialog({
  open,
  course,
  onClose,
  onDeleted,
}: DeleteCourseDialogProps) {
  const deleteCourse = useDeleteCourse();
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setError(null);
    try {
      await deleteCourse.mutateAsync(course.id);
      onDeleted();
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  const documentNote =
    course.documentCount === 1
      ? 'Its 1 uploaded document will be deleted too.'
      : `Its ${course.documentCount} uploaded documents will be deleted too.`;

  return (
    <Dialog open={open} onClose={onClose} title={`Delete ${course.title}?`}>
      <div className="space-y-4">
        {error ? <FormError message={error} /> : null}

        <p className="text-sm leading-relaxed text-ink-600">
          This cannot be undone.{' '}
          {course.documentCount > 0 ? documentNote : 'This course has no documents.'}
        </p>

        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={deleteCourse.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleDelete}
            disabled={deleteCourse.isPending}
            className="bg-signal-danger hover:bg-red-800"
          >
            {deleteCourse.isPending ? <Spinner label="Deleting" /> : null}
            Delete course
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
