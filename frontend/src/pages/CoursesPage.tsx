import { BookMarked, Plus } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { SectionSpinner } from '@/components/ui/Spinner';
import { CourseCard } from '@/features/courses/CourseCard';
import { CourseFormDialog } from '@/features/courses/CourseFormDialog';
import { useCourses } from '@/hooks/queries/useCourses';
import { toErrorMessage } from '@/services/api/client';

export function CoursesPage() {
  const { data: courses, isPending, isError, error, refetch } = useCourses();
  const [isCreating, setIsCreating] = useState(false);

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl text-ink-900">Courses</h1>
          <p className="mt-2 text-ink-600">
            Each course keeps its own materials and, from Phase 4, its own mastery record.
          </p>
        </div>
        <Button onClick={() => setIsCreating(true)}>
          <Plus className="size-4" strokeWidth={2} aria-hidden />
          New course
        </Button>
      </header>

      {isPending ? <SectionSpinner label="Loading your courses" /> : null}

      {isError ? (
        <Card>
          <ErrorState
            title="Could not load your courses"
            message={toErrorMessage(error)}
            onRetry={() => void refetch()}
          />
        </Card>
      ) : null}

      {courses && courses.length === 0 ? (
        <Card>
          <EmptyState
            icon={BookMarked}
            title="No courses yet"
            description="Create your first course, then upload the lectures and notes that go with it."
            action={
              <Button onClick={() => setIsCreating(true)}>
                <Plus className="size-4" strokeWidth={2} aria-hidden />
                New course
              </Button>
            }
          />
        </Card>
      ) : null}

      {courses && courses.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {courses.map((course) => (
            <CourseCard key={course.id} course={course} />
          ))}
        </div>
      ) : null}

      <CourseFormDialog open={isCreating} onClose={() => setIsCreating(false)} />
    </div>
  );
}
