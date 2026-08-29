import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="flex size-11 items-center justify-center rounded-full bg-paper-200">
        <Icon className="size-5 text-ink-400" strokeWidth={1.75} aria-hidden />
      </div>
      <h3 className="mt-4 font-serif text-lg text-ink-900">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-ink-500">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
