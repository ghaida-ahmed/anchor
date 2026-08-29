import { useState, type FormEvent } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { FormError } from '@/components/ui/ErrorState';
import { Spinner } from '@/components/ui/Spinner';
import { TextAreaField, TextField } from '@/components/ui/TextField';
import { useCreateCourse, useUpdateCourse } from '@/hooks/queries/useCourses';
import { toErrorMessage } from '@/services/api/client';
import type { Course } from '@/types/domain';

interface CourseFormDialogProps {
  open: boolean;
  onClose: () => void;
  /** Present when editing; absent when creating. */
  course?: Course | undefined;
  onCreated?: ((course: Course) => void) | undefined;
}

export function CourseFormDialog({
  open,
  onClose,
  course,
  onCreated,
}: CourseFormDialogProps) {
  const isEditing = course !== undefined;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={isEditing ? 'Edit course' : 'New course'}
      description={
        isEditing
          ? 'Update the details for this course.'
          : 'Give the course a name. You can add materials once it exists.'
      }
    >
      {/* Remounting on open resets the form — no effect syncing state to props. */}
      <CourseForm
        key={`${course?.id ?? 'new'}-${String(open)}`}
        course={course}
        onClose={onClose}
        onCreated={onCreated}
      />
    </Dialog>
  );
}

interface CourseFormProps {
  course?: Course | undefined;
  onClose: () => void;
  onCreated?: ((course: Course) => void) | undefined;
}

function CourseForm({ course, onClose, onCreated }: CourseFormProps) {
  const isEditing = course !== undefined;

  const [title, setTitle] = useState(course?.title ?? '');
  const [code, setCode] = useState(course?.code ?? '');
  const [description, setDescription] = useState(course?.description ?? '');
  const [error, setError] = useState<string | null>(null);

  const createCourse = useCreateCourse();
  const updateCourse = useUpdateCourse(course?.id ?? '');
  const isSaving = createCourse.isPending || updateCourse.isPending;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    const payload = {
      title: title.trim(),
      code: code.trim(),
      description: description.trim(),
    };
    if (!payload.title) return;

    try {
      if (isEditing) {
        await updateCourse.mutateAsync(payload);
      } else {
        const created = await createCourse.mutateAsync(payload);
        onCreated?.(created);
      }
      onClose();
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      {error ? <FormError message={error} /> : null}

      <TextField
        label="Title"
        required
        maxLength={200}
        value={title}
        placeholder="Computer Networks"
        disabled={isSaving}
        onChange={(event) => setTitle(event.target.value)}
      />

      <TextField
        label="Course code"
        maxLength={32}
        value={code}
        placeholder="CS340"
        hint="Optional. Must be unique across your own courses."
        disabled={isSaving}
        onChange={(event) => setCode(event.target.value)}
      />

      <TextAreaField
        label="Description"
        maxLength={2000}
        value={description}
        placeholder="What this course covers."
        hint="Optional."
        disabled={isSaving}
        onChange={setDescription}
      />

      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="secondary" onClick={onClose} disabled={isSaving}>
          Cancel
        </Button>
        <Button type="submit" disabled={isSaving || !title.trim()}>
          {isSaving ? <Spinner label="Saving" /> : null}
          {isEditing ? 'Save changes' : 'Create course'}
        </Button>
      </div>
    </form>
  );
}
