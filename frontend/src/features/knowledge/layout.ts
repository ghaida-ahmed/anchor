/**
 * Laying the knowledge map out as a layered graph.
 *
 * No graph library. The project already draws its charts as inline SVG (see
 * `features/progress`), and this needs one deterministic layered layout rather
 * than the force simulation, zoom and hit-testing a library brings — plus its
 * bundle. If the map grows interactive enough to need dragging or panning, that
 * is the point to reconsider, and this file is what gets deleted.
 *
 * The layout is a longest-path layering over prerequisite edges, which is the
 * standard first pass of a Sugiyama-style drawing:
 *
 *   layer(topic) = 0 if nothing is a prerequisite of it
 *                  1 + max(layer(prerequisites)) otherwise
 *
 * so every prerequisite sits strictly to the left of what depends on it, and the
 * columns read as a study order. `related` edges do not affect layering — they
 * are undirected and would only smear the ordering.
 *
 * The backend rejects prerequisite cycles at write time, but this function must
 * still terminate on a graph that somehow contains one, so it iterates a bounded
 * number of times rather than recursing.
 */

import type { KnowledgeEdge, KnowledgeNode } from '@/services/api/knowledge';

export interface PositionedNode extends KnowledgeNode {
  x: number;
  y: number;
  layer: number;
}

export interface PositionedEdge extends KnowledgeEdge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface GraphLayout {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
}

export const NODE_WIDTH = 168;
export const NODE_HEIGHT = 56;

const COLUMN_GAP = 96;
const ROW_GAP = 28;
const PADDING = 16;

export function layerNodes(
  nodes: KnowledgeNode[],
  edges: KnowledgeEdge[],
): Map<string, number> {
  const prerequisites = edges.filter((edge) => edge.relationshipType === 'prerequisite');
  const layers = new Map(nodes.map((node) => [node.topicId, 0]));

  // Relaxation, bounded by the number of nodes: a correct DAG settles within that
  // many passes, and a malformed one stops rather than looping.
  for (let pass = 0; pass < nodes.length; pass += 1) {
    let changed = false;
    for (const edge of prerequisites) {
      const from = layers.get(edge.sourceTopicId);
      const to = layers.get(edge.targetTopicId);
      if (from === undefined || to === undefined) continue;
      if (to < from + 1) {
        layers.set(edge.targetTopicId, from + 1);
        changed = true;
      }
    }
    if (!changed) break;
  }

  return layers;
}

/**
 * Positions every node. Ordering within a column is by name, so the same map
 * always draws the same way — a layout that shuffled between renders would make
 * the graph unreadable as a reference.
 */
export function buildLayout(
  nodes: KnowledgeNode[],
  edges: KnowledgeEdge[],
): GraphLayout {
  if (nodes.length === 0) {
    return { nodes: [], edges: [], width: 0, height: 0 };
  }

  const layers = layerNodes(nodes, edges);
  const columns = new Map<number, KnowledgeNode[]>();

  for (const node of [...nodes].sort((a, b) => a.name.localeCompare(b.name))) {
    const layer = layers.get(node.topicId) ?? 0;
    const column = columns.get(layer) ?? [];
    column.push(node);
    columns.set(layer, column);
  }

  const tallest = Math.max(...[...columns.values()].map((column) => column.length));
  const height = PADDING * 2 + tallest * NODE_HEIGHT + (tallest - 1) * ROW_GAP;
  const columnCount = Math.max(...columns.keys()) + 1;
  const width =
    PADDING * 2 + columnCount * NODE_WIDTH + (columnCount - 1) * COLUMN_GAP;

  const positioned: PositionedNode[] = [];
  for (const [layer, column] of columns) {
    // Columns are centred against each other so a sparse layer does not hug the
    // top edge while a full one fills the height.
    const columnHeight =
      column.length * NODE_HEIGHT + (column.length - 1) * ROW_GAP;
    const top = (height - columnHeight) / 2;

    column.forEach((node, index) => {
      positioned.push({
        ...node,
        layer,
        x: PADDING + layer * (NODE_WIDTH + COLUMN_GAP),
        y: top + index * (NODE_HEIGHT + ROW_GAP),
      });
    });
  }

  const byId = new Map(positioned.map((node) => [node.topicId, node]));
  const positionedEdges: PositionedEdge[] = [];

  for (const edge of edges) {
    const from = byId.get(edge.sourceTopicId);
    const to = byId.get(edge.targetTopicId);
    if (!from || !to) continue;

    // Leave from the right edge and arrive at the left when the edge points
    // forwards; otherwise join the nearest sides.
    const forwards = to.x >= from.x;
    positionedEdges.push({
      ...edge,
      x1: forwards ? from.x + NODE_WIDTH : from.x,
      y1: from.y + NODE_HEIGHT / 2,
      x2: forwards ? to.x : to.x + NODE_WIDTH,
      y2: to.y + NODE_HEIGHT / 2,
    });
  }

  return { nodes: positioned, edges: positionedEdges, width, height };
}

/** A smooth horizontal curve, so crossing edges stay tellable apart. */
export function edgePath(edge: PositionedEdge): string {
  const midpoint = (edge.x1 + edge.x2) / 2;
  return `M ${edge.x1} ${edge.y1} C ${midpoint} ${edge.y1}, ${midpoint} ${edge.y2}, ${edge.x2} ${edge.y2}`;
}
