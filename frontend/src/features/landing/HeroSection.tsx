import { ArrowRight, FileText } from 'lucide-react';

import { ButtonLink } from '@/components/ui/Button';
import { paths } from '@/routes/paths';

export function HeroSection() {
  return (
    <section className="mx-auto max-w-6xl px-6 pt-16 pb-20 lg:pt-24">
      <div className="grid items-center gap-14 lg:grid-cols-[1.05fr_0.95fr]">
        <div>
          <p className="text-xs font-medium tracking-[0.2em] text-brass-600 uppercase">
            AI-Powered Adaptive Learning
          </p>

          <h1 className="mt-5 font-serif text-4xl leading-[1.1] text-ink-900 sm:text-5xl">
            Your course materials, turned into a study workspace.
          </h1>

          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-600">
            Upload the lectures, slides and notes for a course. ANCHOR reads them and
            builds summaries, quizzes and flashcards from that material — then tracks
            which topics you have actually mastered and adapts what it asks you next.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
            <ButtonLink to={paths.dashboard} size="lg">
              Open the dashboard
              <ArrowRight className="size-4" strokeWidth={2} aria-hidden />
            </ButtonLink>
            <a
              href="#how-it-works"
              className="inline-flex h-12 items-center px-2 text-sm font-medium text-ink-600 transition-colors hover:text-ink-900"
            >
              See how it works
            </a>
          </div>

          <p className="mt-8 text-sm text-ink-400">
            Answers cite the document and page they came from, so you can check them
            against the source.
          </p>
        </div>

        <CitedAnswerPreview />
      </div>
    </section>
  );
}

/**
 * A static illustration of the answer format ANCHOR will produce. Not a live
 * component — it exists to make the citation model legible on the landing page.
 */
function CitedAnswerPreview() {
  return (
    <div className="rounded-card border border-paper-300 bg-white shadow-lift">
      <div className="border-b border-paper-200 px-6 py-4">
        <p className="text-xs font-medium tracking-wide text-ink-400 uppercase">
          Computer Networks · CS340
        </p>
        <p className="mt-2 text-[15px] text-ink-900">
          Why does TCP halve the congestion window after packet loss?
        </p>
      </div>

      <div className="px-6 py-5">
        <p className="text-[15px] leading-relaxed text-ink-700">
          Loss is read as a signal that the path is saturated. Halving the window drains
          the bottleneck queue quickly, while additive increase probes for capacity again
          gradually — the AIMD behaviour that keeps competing flows roughly fair.
        </p>

        <div className="mt-5 space-y-2 border-t border-paper-200 pt-4">
          <p className="text-xs font-medium tracking-wide text-ink-400 uppercase">
            Sources
          </p>
          {[
            { file: 'Lecture 05 — Congestion Control.pdf', page: 17 },
            { file: 'Lecture 04 — Transport Layer.pdf', page: 31 },
          ].map((source) => (
            <div key={source.file} className="flex items-center gap-2.5 text-sm">
              <FileText className="size-4 shrink-0 text-brass-500" strokeWidth={1.75} aria-hidden />
              <span className="truncate text-ink-700">{source.file}</span>
              <span className="tabular ml-auto shrink-0 text-ink-400">p. {source.page}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
