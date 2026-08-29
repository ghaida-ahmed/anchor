import { Check } from 'lucide-react';

import { cn } from '@/lib/cn';

interface Phase {
  label: string;
  title: string;
  items: string[];
  complete: boolean;
}

const PHASES: Phase[] = [
  {
    label: 'Phase 1',
    title: 'Foundations',
    items: ['Interface and design system', 'FastAPI service', 'PostgreSQL schema'],
    complete: true,
  },
  {
    label: 'Phase 2',
    title: 'Real courses and documents',
    items: ['Authentication', 'Course CRUD', 'Document upload and storage'],
    complete: false,
  },
  {
    label: 'Phase 3',
    title: 'Retrieval and the tutor',
    items: ['Text extraction and chunking', 'Vector search', 'Cited question answering'],
    complete: false,
  },
  {
    label: 'Phase 4',
    title: 'Adaptive learning',
    items: ['Generated quizzes and flashcards', 'Mastery scoring', 'Analytics and exam mode'],
    complete: false,
  },
];

export function RoadmapSection() {
  return (
    <section id="roadmap" className="border-t border-paper-300 bg-paper-200">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="font-serif text-3xl text-ink-900">Build roadmap</h2>
        <p className="mt-3 max-w-2xl text-ink-600">
          ANCHOR is being built in phases, and this page reflects where it actually is.
        </p>

        <div className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {PHASES.map((phase) => (
            <div
              key={phase.label}
              className={cn(
                'border-t-2 pt-5',
                phase.complete ? 'border-ink-900' : 'border-paper-400',
              )}
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium tracking-wider text-ink-500 uppercase">
                  {phase.label}
                </span>
                {phase.complete ? (
                  <Check className="size-3.5 text-signal-success" strokeWidth={2.5} aria-label="Complete" />
                ) : null}
              </div>
              <h3 className="mt-2 font-serif text-lg text-ink-900">{phase.title}</h3>
              <ul className="mt-3 space-y-1.5">
                {phase.items.map((item) => (
                  <li key={item} className="text-sm text-ink-600">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
