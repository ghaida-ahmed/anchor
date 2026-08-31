import {
  Boxes,
  BrainCircuit,
  FileStack,
  Layers,
  Quote,
  Target,
  TrendingUp,
  Wand2,
} from 'lucide-react';

interface Feature {
  icon: typeof Boxes;
  title: string;
  body: string;
}

const FEATURES: Feature[] = [
  {
    icon: FileStack,
    title: 'Multi-document courses',
    body: 'Keep every file for a course together, so questions can draw on the whole semester rather than one PDF.',
  },
  {
    icon: Quote,
    title: 'Cited answers',
    body: 'Every response names the document and page it came from, so nothing has to be taken on trust.',
  },
  {
    icon: Wand2,
    title: 'Summaries',
    body: 'Condense a lecture or a whole week into a readable overview of the key ideas.',
  },
  {
    icon: Layers,
    title: 'Quizzes and flashcards',
    body: 'Generate practice questions and spaced-repetition decks directly from your material.',
  },
  {
    icon: Target,
    title: 'Adaptive practice',
    body: 'Later quizzes weight towards the topics your answers show you are weakest on.',
  },
  {
    icon: TrendingUp,
    title: 'Mastery tracking',
    body: 'A per-topic score that moves as you practise, so revision time goes where it is needed.',
  },
  {
    icon: BrainCircuit,
    title: 'Knowledge maps',
    body: 'See how topics in a course connect, and which branches are still unexplored.',
  },
  {
    icon: Boxes,
    title: 'Exam preparation mode',
    body: 'A focused revision plan assembled from weak topics and unreviewed material.',
  },
];

export function FeatureSection() {
  return (
    <section id="features" className="mx-auto max-w-6xl px-6 py-20">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-serif text-3xl text-ink-900">What ANCHOR does</h2>
          <p className="mt-3 max-w-2xl text-ink-600">
            Each of these works from the documents you upload to a course, not from
            general knowledge.
          </p>
        </div>
      </div>

      <div className="mt-12 grid gap-x-10 gap-y-9 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map((feature) => (
          <div key={feature.title}>
            <feature.icon className="size-5 text-ink-700" strokeWidth={1.75} aria-hidden />
            <h3 className="mt-4 text-[15px] font-semibold text-ink-900">{feature.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-600">{feature.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
