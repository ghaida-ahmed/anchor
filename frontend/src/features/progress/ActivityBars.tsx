import type { DailyActivity } from '@/services/api/retention';

/**
 * Practice volume per active day.
 *
 * Only days on which something happened get a bar — the backend emits no bucket
 * for an idle day, and inventing a zero would imply the student sat down and did
 * nothing rather than simply not practising.
 */
export function ActivityBars({ days }: { days: DailyActivity[] }) {
  if (days.length === 0) {
    return <p className="py-6 text-center text-sm text-ink-400">No practice yet.</p>;
  }

  const peak = Math.max(...days.map((day) => day.answers), 1);
  const recent = days.slice(-14);

  return (
    <div className="flex h-24 items-end gap-1.5">
      {recent.map((day) => {
        const accuracy = day.answers > 0 ? (day.correct / day.answers) * 100 : 0;
        return (
          <div key={day.day} className="flex h-full flex-1 flex-col justify-end gap-1.5">
            <div
              className="w-full rounded-t bg-ink-700"
              style={{ height: `${Math.max((day.answers / peak) * 100, 4)}%` }}
              role="img"
              aria-label={`${day.day}: ${day.answers} answered, ${day.correct} correct (${accuracy.toFixed(0)}%)`}
            >
              <span className="sr-only">
                {day.day}: {day.answers} answered, {day.correct} correct
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
