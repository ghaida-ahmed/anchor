import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

interface CardProps {
  className?: string;
  children: ReactNode;
}

/** Flat surface with a hairline border. Elevation comes from the border, not shadow. */
export function Card({ className, children }: CardProps) {
  return (
    <div
      className={cn(
        'rounded-card border border-paper-300 bg-white shadow-raise',
        className,
      )}
    >
      {children}
    </div>
  );
}

interface CardHeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function CardHeader({ title, description, action }: CardHeaderProps) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-paper-200 px-5 py-4">
      <div>
        <h3 className="font-serif text-lg text-ink-900">{title}</h3>
        {description ? (
          <p className="mt-0.5 text-sm text-ink-500">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function CardBody({ className, children }: CardProps) {
  return <div className={cn('px-5 py-4', className)}>{children}</div>;
}
