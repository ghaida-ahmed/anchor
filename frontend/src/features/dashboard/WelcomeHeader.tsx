function greetingFor(date: Date): string {
  const hour = date.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

interface WelcomeHeaderProps {
  name: string;
  courseCount: number;
}

export function WelcomeHeader({ name, courseCount }: WelcomeHeaderProps) {
  const firstName = name.split(' ')[0] ?? name;

  const summary =
    courseCount === 0
      ? 'You have not added a course yet.'
      : courseCount === 1
        ? 'You have 1 course. Here is where things stand.'
        : `You have ${courseCount} courses. Here is where things stand.`;

  return (
    <header className="mb-8">
      <h1 className="font-serif text-3xl text-ink-900">
        {greetingFor(new Date())}, {firstName}
      </h1>
      <p className="mt-2 text-ink-600">{summary}</p>
    </header>
  );
}
