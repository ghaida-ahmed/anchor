import type { ReactNode } from 'react';

interface StatTileProps {
  label: string;
  value: string;
  hint?: ReactNode;
}

export function StatTile({ label, value, hint }: StatTileProps) {
  return (
    <div className="rounded-card border border-paper-300 bg-white px-5 py-4">
      <p className="text-xs font-medium tracking-wide text-ink-500 uppercase">{label}</p>
      <p className="tabular mt-2 font-serif text-3xl text-ink-900">{value}</p>
      {hint ? <p className="mt-1 text-sm text-ink-500">{hint}</p> : null}
    </div>
  );
}
