import { AlertTriangle, Layers, TrendingDown } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';
import type { GapKind, KnowledgeGap } from '@/services/api/knowledge';

const KIND_ICON: Record<GapKind, LucideIcon> = {
  unmet_prerequisite: AlertTriangle,
  blocking: Layers,
  isolated: TrendingDown,
};

const KIND_TONE: Record<GapKind, 'danger' | 'caution' | 'neutral'> = {
  unmet_prerequisite: 'danger',
  blocking: 'caution',
  isolated: 'neutral',
};

/**
 * Detected knowledge gaps.
 *
 * The ordering and the wording both come from the backend's deterministic
 * algorithm — no model decides what the student does not know, and the reason
 * shown is assembled from the same facts as the ranking, so the explanation
 * cannot drift from the order.
 */
export function GapList({ gaps }: { gaps: KnowledgeGap[] }) {
  if (gaps.length === 0) {
    return (
      <EmptyState
        icon={Layers}
        title="No gaps detected"
        description="Nothing you have practised is holding back another topic. Keep answering questions and this will update."
      />
    );
  }

  return (
    <ul className="divide-y divide-paper-200">
      {gaps.map((gap) => {
        const Icon = KIND_ICON[gap.kind];
        return (
          <li key={gap.topicId} className="flex items-start gap-3 px-5 py-4">
            <Icon
              className="mt-0.5 size-4 shrink-0 text-ink-400"
              strokeWidth={1.75}
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-ink-900">{gap.name}</p>
                <Badge tone={KIND_TONE[gap.kind]}>{gap.kindLabel}</Badge>
                <span className="tabular text-xs text-ink-400">
                  {gap.effectiveMastery.toFixed(0)}% mastery
                </span>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-600">{gap.reason}</p>
              {gap.blockedTopics.length > 0 ? (
                <p className="mt-1 text-xs text-ink-400">
                  Sits under: {gap.blockedTopics.join(', ')}
                </p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
