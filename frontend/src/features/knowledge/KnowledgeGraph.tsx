import { useState } from 'react';

import {
  NODE_HEIGHT,
  NODE_WIDTH,
  buildLayout,
  edgePath,
} from '@/features/knowledge/layout';
import { BAND_BAR_TONE } from '@/features/quiz/masteryTone';
import { cn } from '@/lib/cn';
import type { KnowledgeEdge, KnowledgeNode } from '@/services/api/knowledge';
import type { MasteryBand } from '@/services/api/learning';

/** Node fill per band, as SVG-friendly classes. */
const BAND_FILL: Record<string, string> = {
  not_started: 'fill-paper-100 stroke-paper-400',
  needs_practice: 'fill-red-50 stroke-red-300',
  developing: 'fill-amber-50 stroke-amber-300',
  strong: 'fill-emerald-50 stroke-emerald-300',
};

interface KnowledgeGraphProps {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  gapTopicIds: ReadonlySet<string>;
  onSelect: (topicId: string | null) => void;
  selectedTopicId: string | null;
}

/**
 * The map, drawn as inline SVG.
 *
 * Prerequisites read left to right, so the columns are a study order: nothing in
 * a column depends on anything to its right. Related topics are joined by a
 * dashed line with no arrow, because there is no order to imply.
 *
 * On a narrow screen this is replaced by `KnowledgeList` — a graph squeezed into
 * 375 pixels is decoration, not information.
 */
export function KnowledgeGraph({
  nodes,
  edges,
  gapTopicIds,
  onSelect,
  selectedTopicId,
}: KnowledgeGraphProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const layout = buildLayout(nodes, edges);

  if (layout.nodes.length === 0) return null;

  const active = hovered ?? selectedTopicId;
  const connected = new Set<string>();
  if (active) {
    connected.add(active);
    for (const edge of edges) {
      if (edge.sourceTopicId === active) connected.add(edge.targetTopicId);
      if (edge.targetTopicId === active) connected.add(edge.sourceTopicId);
    }
  }

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        width={layout.width}
        height={layout.height}
        role="img"
        aria-label={`Knowledge map: ${nodes.length} topics, ${edges.length} relationships`}
        className="max-w-none"
      >
        <defs>
          <marker
            id="anchor-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 8 4 L 0 8 z" className="fill-ink-400" />
          </marker>
        </defs>

        {layout.edges.map((edge) => {
          const dimmed = active !== null && !connected.has(edge.sourceTopicId);
          return (
            <path
              key={edge.id}
              d={edgePath(edge)}
              fill="none"
              className={cn(
                'stroke-ink-300 transition-opacity',
                dimmed ? 'opacity-20' : 'opacity-100',
              )}
              strokeWidth={1.25}
              strokeDasharray={edge.relationshipType === 'related' ? '4 4' : undefined}
              markerEnd={
                edge.relationshipType === 'prerequisite' ? 'url(#anchor-arrow)' : undefined
              }
            >
              <title>
                {edge.relationshipType === 'prerequisite'
                  ? 'Prerequisite'
                  : 'Related topics'}
                {` · supported by ${edge.supportingChunkCount} ${
                  edge.supportingChunkCount === 1 ? 'excerpt' : 'excerpts'
                }`}
              </title>
            </path>
          );
        })}

        {layout.nodes.map((node) => {
          const dimmed = active !== null && !connected.has(node.topicId);
          const isGap = gapTopicIds.has(node.topicId);
          return (
            <g
              key={node.topicId}
              transform={`translate(${node.x}, ${node.y})`}
              className={cn(
                'cursor-pointer transition-opacity',
                dimmed ? 'opacity-30' : 'opacity-100',
              )}
              onMouseEnter={() => setHovered(node.topicId)}
              onMouseLeave={() => setHovered(null)}
              onClick={() =>
                onSelect(selectedTopicId === node.topicId ? null : node.topicId)
              }
            >
              <rect
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx={8}
                className={cn(
                  BAND_FILL[node.band] ?? BAND_FILL.not_started,
                  selectedTopicId === node.topicId && 'stroke-ink-900',
                )}
                strokeWidth={selectedTopicId === node.topicId ? 2 : 1}
                strokeDasharray={isGap ? '5 3' : undefined}
              />
              <text
                x={12}
                y={22}
                className="fill-ink-900 text-[12px] font-medium"
                style={{ fontSize: 12 }}
              >
                {truncate(node.name, 22)}
              </text>
              <text
                x={12}
                y={40}
                className="fill-ink-500 text-[11px]"
                style={{ fontSize: 11 }}
              >
                {node.questionsAttempted === 0
                  ? 'Not started'
                  : `${node.effectiveMastery.toFixed(0)}% · ${node.bandLabel}`}
              </text>
              <rect
                x={12}
                y={NODE_HEIGHT - 8}
                width={NODE_WIDTH - 24}
                height={3}
                rx={1.5}
                className="fill-paper-300"
              />
              <rect
                x={12}
                y={NODE_HEIGHT - 8}
                width={((NODE_WIDTH - 24) * node.effectiveMastery) / 100}
                height={3}
                rx={1.5}
                className={cn(
                  BAND_BAR_TONE[node.band as MasteryBand] ?? 'bg-paper-400',
                ).replace('bg-', 'fill-')}
              />
              <title>{node.description || node.name}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function truncate(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}
