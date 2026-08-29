import { GraduationCap, MessagesSquare, Upload } from 'lucide-react';

const STEPS = [
  {
    icon: Upload,
    title: 'Upload a course',
    body: 'Add the lecture slides, notes and readings for one course. Documents are grouped by course rather than dumped into one pile.',
  },
  {
    icon: MessagesSquare,
    title: 'Study against your own material',
    body: 'Ask questions, generate summaries, quizzes and flashcards. Answers are drawn from your documents and cite the file and page.',
  },
  {
    icon: GraduationCap,
    title: 'Let it adapt',
    body: 'ANCHOR records which topics you answer well and which you do not, then weights later quizzes towards the gaps.',
  },
];

export function HowItWorksSection() {
  return (
    <section id="how-it-works" className="border-y border-paper-300 bg-paper-200">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="font-serif text-3xl text-ink-900">How ANCHOR works</h2>
        <p className="mt-3 max-w-2xl text-ink-600">
          Three steps, in the order you would actually use them during a semester.
        </p>

        <ol className="mt-12 grid gap-8 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title}>
              <div className="flex items-center gap-3">
                <span className="tabular font-serif text-sm text-brass-600">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <span className="h-px flex-1 bg-paper-400" aria-hidden />
              </div>
              <step.icon className="mt-6 size-5 text-ink-700" strokeWidth={1.75} aria-hidden />
              <h3 className="mt-4 font-serif text-xl text-ink-900">{step.title}</h3>
              <p className="mt-2 leading-relaxed text-ink-600">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
