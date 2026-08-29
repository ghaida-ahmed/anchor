import { ArrowRight } from 'lucide-react';

import { ButtonLink } from '@/components/ui/Button';
import { paths } from '@/routes/paths';

export function ClosingCtaSection() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-24">
      <div className="rounded-card border border-paper-300 bg-ink-900 px-8 py-14 text-center sm:px-16">
        <h2 className="font-serif text-3xl text-paper-100">
          Start with one course and see how it reads your material.
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-ink-200">
          Upload one set of lecture notes and ANCHOR will find the topics, write
          questions from them, and track what you know as you go.
        </p>
        <div className="mt-9 flex justify-center">
          <ButtonLink
            to={paths.dashboard}
            size="lg"
            variant="secondary"
            className="border-transparent"
          >
            Open the dashboard
            <ArrowRight className="size-4" strokeWidth={2} aria-hidden />
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}
