import { Network, RefreshCw, Sparkles } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Card, CardHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState, FormError } from '@/components/ui/ErrorState';
import { SectionSpinner } from '@/components/ui/Spinner';
import { Spinner } from '@/components/ui/Spinner';
import { GapList } from '@/features/knowledge/GapList';
import { KnowledgeGraph } from '@/features/knowledge/KnowledgeGraph';
import { KnowledgeList } from '@/features/knowledge/KnowledgeList';
import { SourceLine } from '@/features/quiz/SourceLine';
import { TopicSyncNotice } from '@/features/workspace/TopicSyncNotice';
import {
  useGenerateKnowledgeMap,
  useKnowledgeGaps,
  useKnowledgeMap,
} from '@/hooks/queries/useKnowledge';
import { toErrorMessage } from '@/services/api/client';

/**
 * The knowledge map and the gaps derived from it.
 *
 * Reading this tab never spends anything: the map is fetched, and building it is
 * an explicit action. The gap list works whether or not a map exists — without
 * one it can still find weak topics, it just cannot say what they block.
 */
export function KnowledgeTab({ courseId }: { courseId: string }) {
  const map = useKnowledgeMap(courseId);
  const gaps = useKnowledgeGaps(courseId);
  const generate = useGenerateKnowledgeMap(courseId);

  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setError(null);
    try {
      await generate.mutateAsync();
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  if (map.isPending) return <SectionSpinner label="Loading the knowledge map" />;

  if (map.isError) {
    return (
      <Card>
        <ErrorState
          title="Could not load the knowledge map"
          message={toErrorMessage(map.error)}
          onRetry={() => void map.refetch()}
        />
      </Card>
    );
  }

  const { nodes, edges } = map.data;
  const gapTopicIds = new Set((gaps.data?.gaps ?? []).map((gap) => gap.topicId));
  const selectedEdges = selectedTopicId
    ? edges.filter(
        (edge) =>
          edge.sourceTopicId === selectedTopicId ||
          edge.targetTopicId === selectedTopicId,
      )
    : [];
  const names = new Map(nodes.map((node) => [node.topicId, node.name]));

  return (
    <div className="space-y-6">
      {error ? <FormError message={error} /> : null}

      <TopicSyncNotice courseId={courseId} />

      <Card>
        <CardHeader
          title="Knowledge map"
          description="How this course's topics relate, derived from your own materials."
          action={
            <Button
              variant={edges.length > 0 ? 'secondary' : 'primary'}
              size="sm"
              onClick={() => void handleGenerate()}
              disabled={generate.isPending || nodes.length < 2}
            >
              {generate.isPending ? (
                <Spinner label="Building" />
              ) : edges.length > 0 ? (
                <RefreshCw className="size-3.5" strokeWidth={2} aria-hidden />
              ) : (
                <Sparkles className="size-3.5" strokeWidth={2} aria-hidden />
              )}
              {generate.isPending
                ? 'Reading your material…'
                : edges.length > 0
                  ? 'Rebuild'
                  : 'Build the map'}
            </Button>
          }
        />

        {nodes.length < 2 ? (
          <EmptyState
            icon={Network}
            title="Not enough topics yet"
            description="A map needs at least two topics. Upload more material and extract topics from the Quizzes tab first."
          />
        ) : edges.length === 0 ? (
          <EmptyState
            icon={Network}
            title="No map built yet"
            description="ANCHOR looks for topics your materials discuss in the same passages, then works out which ones build on which."
          />
        ) : (
          <>
            {/* The graph is meaningful only where it has room; below that the list
                carries exactly the same ordering and relationships. */}
            <div className="hidden px-5 pb-5 md:block">
              <KnowledgeGraph
                nodes={nodes}
                edges={edges}
                gapTopicIds={gapTopicIds}
                selectedTopicId={selectedTopicId}
                onSelect={setSelectedTopicId}
              />
              <Legend />
            </div>
            <div className="md:hidden">
              <KnowledgeList nodes={nodes} edges={edges} gapTopicIds={gapTopicIds} />
            </div>
          </>
        )}
      </Card>

      {selectedTopicId && selectedEdges.length > 0 ? (
        <Card>
          <CardHeader
            title={names.get(selectedTopicId) ?? 'Selected topic'}
            description="The excerpts behind each relationship."
          />
          <ul className="divide-y divide-paper-200">
            {selectedEdges.map((edge) => (
              <li key={edge.id} className="px-5 py-4">
                <p className="text-sm text-ink-800">
                  {edge.relationshipType === 'prerequisite'
                    ? `${names.get(edge.sourceTopicId) ?? '—'} comes before ${names.get(edge.targetTopicId) ?? '—'}`
                    : `Related to ${names.get(
                        edge.sourceTopicId === selectedTopicId
                          ? edge.targetTopicId
                          : edge.sourceTopicId,
                      ) ?? '—'}`}
                </p>
                <p className="mt-1 text-xs text-ink-400">
                  Supported by {edge.supportingChunkCount}{' '}
                  {edge.supportingChunkCount === 1 ? 'excerpt' : 'excerpts'} from your
                  materials
                </p>
                {edge.sources.map((source) => (
                  <SourceLine key={source.chunkId} source={source} />
                ))}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title="Knowledge gaps"
          description="Worked out from your mastery and the map. No AI decides this."
        />
        {gaps.isPending ? (
          <SectionSpinner label="Checking for gaps" />
        ) : gaps.isError ? (
          <ErrorState
            title="Could not check for gaps"
            message={toErrorMessage(gaps.error)}
            onRetry={() => void gaps.refetch()}
          />
        ) : (
          <>
            {!gaps.data.hasMap && gaps.data.gaps.length > 0 ? (
              <p className="border-b border-paper-200 px-5 py-3 text-xs text-ink-500">
                Build the map above and ANCHOR can also tell you which of these are
                holding other topics back.
              </p>
            ) : null}
            <GapList gaps={gaps.data.gaps} />
          </>
        )}
      </Card>
    </div>
  );
}

function Legend() {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-paper-200 pt-3 text-xs text-ink-500">
      <span className="flex items-center gap-1.5">
        <svg width="26" height="8" aria-hidden>
          <line x1="0" y1="4" x2="20" y2="4" className="stroke-ink-300" strokeWidth="1.25" />
          <path d="M 20 1 L 26 4 L 20 7 z" className="fill-ink-400" />
        </svg>
        Learn first
      </span>
      <span className="flex items-center gap-1.5">
        <svg width="26" height="8" aria-hidden>
          <line
            x1="0"
            y1="4"
            x2="26"
            y2="4"
            className="stroke-ink-300"
            strokeWidth="1.25"
            strokeDasharray="4 4"
          />
        </svg>
        Related
      </span>
      <span className="flex items-center gap-1.5">
        <svg width="16" height="12" aria-hidden>
          <rect
            x="0.5"
            y="0.5"
            width="15"
            height="11"
            rx="2"
            className="fill-paper-100 stroke-paper-400"
            strokeDasharray="5 3"
          />
        </svg>
        Knowledge gap
      </span>
      <span>Colour shows mastery. Left to right is a study order.</span>
    </div>
  );
}
