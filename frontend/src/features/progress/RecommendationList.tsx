import { Lightbulb } from 'lucide-react';

import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Spinner } from '@/components/ui/Spinner';
import type { Recommendation } from '@/services/api/learning';

/**
 * "Recommended next".
 *
 * Built by the backend from templates over the mastery table — no model call, so
 * this renders on every page load without cost and says the same thing each time.
 */
export function RecommendationList({
  recommendations,
  isPending,
}: {
  recommendations: Recommendation[];
  isPending: boolean;
}) {
  return (
    <Card>
      <CardHeader
        title="Recommended next"
        description="Chosen from your mastery record."
      />
      {isPending ? (
        <CardBody>
          <span className="flex items-center gap-2 text-sm text-ink-500">
            <Spinner className="text-ink-400" label="Loading" />
            Working out what to suggest…
          </span>
        </CardBody>
      ) : recommendations.length === 0 ? (
        <CardBody>
          <p className="text-sm text-ink-500">Nothing to suggest yet.</p>
        </CardBody>
      ) : (
        <ul className="divide-y divide-paper-200">
          {recommendations.map((item) => (
            <li key={`${item.kind}-${item.title}`} className="flex items-start gap-3 px-5 py-3.5">
              <Lightbulb
                className="mt-0.5 size-4 shrink-0 text-brass-500"
                strokeWidth={1.75}
                aria-hidden
              />
              <div>
                <p className="text-sm font-medium text-ink-900">{item.title}</p>
                <p className="mt-0.5 text-sm text-ink-500">{item.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
