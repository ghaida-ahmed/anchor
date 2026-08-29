import { useCallback, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Card } from '@/components/ui/Card';
import { ErrorState } from '@/components/ui/ErrorState';
import { SectionSpinner } from '@/components/ui/Spinner';
import { Tabs } from '@/components/ui/Tabs';
import { CourseFormDialog } from '@/features/courses/CourseFormDialog';
import { DeleteCourseDialog } from '@/features/courses/DeleteCourseDialog';
import { CourseWorkspaceHeader } from '@/features/workspace/CourseWorkspaceHeader';
import { ExamTab } from '@/features/workspace/tabs/ExamTab';
import { FlashcardsTab } from '@/features/workspace/tabs/FlashcardsTab';
import { KnowledgeTab } from '@/features/workspace/tabs/KnowledgeTab';
import { MaterialsTab } from '@/features/workspace/tabs/MaterialsTab';
import { OverviewTab } from '@/features/workspace/tabs/OverviewTab';
import { ProgressTab } from '@/features/workspace/tabs/ProgressTab';
import { QuizzesTab } from '@/features/workspace/tabs/QuizzesTab';
import { StudyGuideTab } from '@/features/workspace/tabs/StudyGuideTab';
import { TutorTab } from '@/features/workspace/tabs/TutorTab';
import {
  WORKSPACE_TABS,
  isWorkspaceTab,
  type WorkspaceTab,
} from '@/features/workspace/workspaceTabs';
import { useCourse } from '@/hooks/queries/useCourses';
import { useCourseDocuments } from '@/hooks/queries/useDocuments';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { paths } from '@/routes/paths';
import { ApiError, toErrorMessage } from '@/services/api/client';

const DEFAULT_TAB: WorkspaceTab = 'overview';

export function CourseWorkspacePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const { data: course, isPending, isError, error, refetch } = useCourse(courseId);
  // Shared with the Materials tab's query cache, so the tutor sees processing
  // states without a second request.
  const { data: documents, isPending: isLoadingDocuments } = useCourseDocuments(courseId);
  const readyCount = (documents ?? []).filter(
    (document) => document.processingStatus === 'ready',
  ).length;
  const [isEditing, setIsEditing] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const requestedTab = searchParams.get('tab');
  const activeTab = isWorkspaceTab(requestedTab) ? requestedTab : DEFAULT_TAB;

  // The tab lives in the URL so a workspace view can be linked to and reloaded.
  const openTab = useCallback(
    (tab: WorkspaceTab) => {
      setSearchParams(tab === DEFAULT_TAB ? {} : { tab }, { replace: true });
    },
    [setSearchParams],
  );

  if (isPending) return <SectionSpinner label="Loading course" />;

  // A course that does not exist — or belongs to someone else — is a 404 either way.
  if (isError && error instanceof ApiError && error.status === 404) {
    return <NotFoundPage />;
  }

  if (isError || !course) {
    return (
      <Card>
        <ErrorState
          title="Could not load this course"
          message={toErrorMessage(error)}
          onRetry={() => void refetch()}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-8">
      <CourseWorkspaceHeader
        course={course}
        onEdit={() => setIsEditing(true)}
        onDelete={() => setIsDeleting(true)}
      />

      <div className="border-b border-paper-300">
        <Tabs items={WORKSPACE_TABS} value={activeTab} onChange={openTab} idPrefix="workspace" />
      </div>

      <div
        role="tabpanel"
        id={`workspace-panel-${activeTab}`}
        aria-labelledby={`workspace-tab-${activeTab}`}
      >
        {activeTab === 'overview' ? (
          <OverviewTab
            courseId={course.id}
            documentCount={course.documentCount}
            readyCount={readyCount}
            onOpenTab={openTab}
          />
        ) : null}
        {activeTab === 'materials' ? <MaterialsTab courseId={course.id} /> : null}
        {activeTab === 'tutor' ? (
          <TutorTab
            courseId={course.id}
            documents={documents ?? []}
            isLoadingDocuments={isLoadingDocuments}
            onOpenTab={openTab}
          />
        ) : null}
        {activeTab === 'guide' ? <StudyGuideTab courseId={course.id} /> : null}
        {activeTab === 'quizzes' ? (
          <QuizzesTab courseId={course.id} readyCount={readyCount} onOpenTab={openTab} />
        ) : null}
        {activeTab === 'flashcards' ? (
          <FlashcardsTab
            courseId={course.id}
            readyCount={readyCount}
            onOpenTab={openTab}
          />
        ) : null}
        {activeTab === 'knowledge' ? <KnowledgeTab courseId={course.id} /> : null}
        {activeTab === 'progress' ? <ProgressTab courseId={course.id} /> : null}
        {activeTab === 'exam' ? (
          <ExamTab courseId={course.id} onOpenTab={openTab} />
        ) : null}
      </div>

      <CourseFormDialog
        open={isEditing}
        course={course}
        onClose={() => setIsEditing(false)}
      />
      <DeleteCourseDialog
        open={isDeleting}
        course={course}
        onClose={() => setIsDeleting(false)}
        onDeleted={() => navigate(paths.courses, { replace: true })}
      />
    </div>
  );
}
