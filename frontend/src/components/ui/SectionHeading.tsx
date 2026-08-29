import type { ReactNode } from 'react';

interface SectionHeadingProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function SectionHeading({ title, description, action }: SectionHeadingProps) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2 className="font-serif text-xl text-ink-900">{title}</h2>
        {description ? <p className="mt-1 text-sm text-ink-500">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
