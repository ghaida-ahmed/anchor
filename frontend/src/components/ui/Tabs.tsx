import type { LucideIcon } from 'lucide-react';

import { cn } from '@/lib/cn';

export interface TabItem<TValue extends string> {
  value: TValue;
  label: string;
  icon: LucideIcon;
}

interface TabsProps<TValue extends string> {
  items: ReadonlyArray<TabItem<TValue>>;
  value: TValue;
  onChange: (value: TValue) => void;
  /** Used to associate each tab with its panel for assistive technology. */
  idPrefix: string;
}

export function Tabs<TValue extends string>({
  items,
  value,
  onChange,
  idPrefix,
}: TabsProps<TValue>) {
  return (
    <div role="tablist" aria-label="Course sections" className="flex gap-1 overflow-x-auto">
      {items.map((item) => {
        const isActive = item.value === value;
        const Icon = item.icon;

        return (
          <button
            key={item.value}
            role="tab"
            id={`${idPrefix}-tab-${item.value}`}
            aria-selected={isActive}
            aria-controls={`${idPrefix}-panel-${item.value}`}
            onClick={() => onChange(item.value)}
            className={cn(
              'inline-flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
              isActive
                ? 'border-ink-900 text-ink-900'
                : 'border-transparent text-ink-500 hover:border-paper-400 hover:text-ink-800',
            )}
          >
            <Icon className="size-4" strokeWidth={1.75} aria-hidden />
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
