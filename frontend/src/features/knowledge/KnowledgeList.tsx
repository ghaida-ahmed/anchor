import { ArrowRight, Link2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { BAND_BADGE_TONE } from '@/features/quiz/masteryTone';
import { layerNodes } from '@/features/knowledge/layout';
import type { KnowledgeEdge, KnowledgeNode } from '@/services/api/knowledge';
import type { MasteryBand } from '@/services/api/learning';

/**
 * The map as a list, for narrow screens.
 *
 * Not a degraded view: the same layering decides the order, so it reads as the
 * same study order the graph draws — first the topics nothing depends on, then
 * what builds on them. Each entry names its prerequisites explicitly, which is
 * the information the arrows carry.
 */
export function KnowledgeList({
  nodes,
  edges,
  gapTopicIds,
}: {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  gapTopicIds: ReadonlySet<string>;
}) {
  const layers = layerNodes(nodes, edges);
  const names = new Map(nodes.map((node) => [node.topicId, node.name]));

  const ordered = [...nodes].sort((a, b) => {
    const byLayer = (layers.get(a.topicId) ?? 0) - (layers.get(b.topicId) ?? 0);
    return byLayer !== 0 ? byLayer : a.name.localeCompare(b.name);
  });

  return (
    <ul className="divide-y divide-paper-200">
      {ordered.map((node) => {
        const prerequisites = edges
          .filter(
            (edge) =>
              edge.relationshipType === 'prerequisite' &&
              edge.targetTopicId === node.topicId,
          )
          .map((edge) => names.get(edge.sourceTopicId))
          .filter((name): name is string => name !== undefined);

        const related = edges
          .filter(
            (edge) =>
              edge.relationshipType === 'related' &&
              (edge.sourceTopicId === node.topicId ||
                edge.targetTopicId === node.topicId),
          )
          .map((edge) =>
            names.get(
              edge.sourceTopicId === node.topicId
                ? edge.targetTopicId
                : edge.sourceTopicId,
            ),
          )
          .filter((name): name is string => name !== undefined);

        return (
          <li key={node.topicId} className="px-5 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-ink-900">{node.name}</p>
              <Badge tone={BAND_BADGE_TONE[node.band as MasteryBand] ?? 'neutral'}>
                {node.questionsAttempted === 0
                  ? 'Not started'
                  : `${node.effectiveMastery.toFixed(0)}% · ${node.bandLabel}`}
              </Badge>
              {gapTopicIds.has(node.topicId) ? (
                <Badge tone="caution">Knowledge gap</Badge>
              ) : null}
            </div>

            {prerequisites.length > 0 ? (
              <p className="mt-1.5 flex items-start gap-1.5 text-xs text-ink-500">
                <ArrowRight
                  className="mt-0.5 size-3 shrink-0 text-ink-400"
                  strokeWidth={2}
                  aria-hidden
                />
                Builds on {prerequisites.join(', ')}
              </p>
            ) : null}

            {related.length > 0 ? (
              <p className="mt-1 flex items-start gap-1.5 text-xs text-ink-400">
                <Link2 className="mt-0.5 size-3 shrink-0" strokeWidth={2} aria-hidden />
                Related to {related.join(', ')}
              </p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
