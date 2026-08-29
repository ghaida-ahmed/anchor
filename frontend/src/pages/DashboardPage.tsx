import { ArrowRight, BookMarked, Plus } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { SectionHeading } from '@/components/ui/SectionHeading';
import { SectionSpinner } from '@/components/ui/Spinner';
import { StatTile } from '@/components/ui/StatTile';
import { useAuth } from '@/features/auth/useAuth';
import { CourseCard } from '@/features/courses/CourseCard';
import { CourseFormDialog } from '@/features/courses/CourseFormDialog';
import { TimezoneSetting } from '@/features/settings/TimezoneSetting';
import { WelcomeHeader } from '@/features/dashboard/WelcomeHeader';
import { useCourses } from '@/hooks/queries/useCourses';
import { paths } from '@/routes/paths';
import { toErrorMessage } from '@/services/api/client';

/**
 * Every figure here comes from the API. Per-course mastery and review counts live
 * on each course's Progress tab rather than being aggregated here: doing so would
 * need one request per course on a page that should stay cheap.
 */
export function DashboardPage() {
  const { user } = useAuth();
  const { data: courses, isPending, isError, error, refetch } = useCourses();
  const [isCreating, setIsCreating] = useState(false);

  const documentCount = (courses ?? []).reduce(
    (total, course) => total + course.documentCount,
    0,
  );

  return (
    <div className="space-y-10">
      <WelcomeHeader name={user?.name ?? 'there'} courseCount={courses?.length ?? 0} />

      {isPending ? <SectionSpinner label="Loading your dashboard" /> : null}

      {isError ? (
        <Card>
          <ErrorState
            title="Could not load your dashboard"
            message={toErrorMessage(error)}
            onRetry={() => void refetch()}
          />
        </Card>
      ) : null}

      {courses ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <StatTile
              label="Courses"
              value={String(courses.length)}
              hint={courses.length === 1 ? 'Active course' : 'Active courses'}
            />
            <StatTile
              label="Documents"
              value={String(documentCount)}
              hint="Uploaded across all courses"
            />
          </div>

          <section>
            <SectionHeading
              title="Your courses"
              description="Open a course for its mastery, reviews and exam preparation."
              action={
                courses.length > 0 ? (
                  <Link
                    to={paths.courses}
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-600 transition-colors hover:text-ink-900"
                  >
                    All courses
                    <ArrowRight className="size-3.5" strokeWidth={2} aria-hidden />
                  </Link>
                ) : null
              }
            />

            {courses.length === 0 ? (
              <Card>
                <EmptyState
                  icon={BookMarked}
                  title="Add your first course"
                  description="Create a course, upload its lectures and notes, and ANCHOR will build topics, quizzes and a mastery record from them."
                  action={
                    <Button onClick={() => setIsCreating(true)}>
                      <Plus className="size-4" strokeWidth={2} aria-hidden />
                      New course
                    </Button>
                  }
                />
              </Card>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {courses.slice(0, 6).map((course) => (
                  <CourseCard key={course.id} course={course} />
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}

      {courses && courses.length > 0 ? (
        <section className="max-w-2xl">
          <TimezoneSetting />
        </section>
      ) : null}

      <CourseFormDialog open={isCreating} onClose={() => setIsCreating(false)} />
    </div>
  );
}
