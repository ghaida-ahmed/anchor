import {
  BarChart3,
  BookOpen,
  CalendarClock,
  FileStack,
  Layers,
  LayoutList,
  ListChecks,
  MessagesSquare,
  Network,
} from 'lucide-react';

import type { TabItem } from '@/components/ui/Tabs';

export const WORKSPACE_TABS = [
  { value: 'overview', label: 'Overview', icon: LayoutList },
  { value: 'materials', label: 'Materials', icon: FileStack },
  { value: 'tutor', label: 'AI Tutor', icon: MessagesSquare },
  { value: 'guide', label: 'Study Guide', icon: BookOpen },
  { value: 'quizzes', label: 'Quizzes', icon: ListChecks },
  { value: 'flashcards', label: 'Flashcards', icon: Layers },
  { value: 'knowledge', label: 'Knowledge Map', icon: Network },
  { value: 'progress', label: 'Progress', icon: BarChart3 },
  { value: 'exam', label: 'Exam Prep', icon: CalendarClock },
] as const satisfies ReadonlyArray<TabItem<string>>;

export type WorkspaceTab = (typeof WORKSPACE_TABS)[number]['value'];

const VALUES: readonly string[] = WORKSPACE_TABS.map((tab) => tab.value);

export function isWorkspaceTab(value: string | null): value is WorkspaceTab {
  return value !== null && VALUES.includes(value);
}
