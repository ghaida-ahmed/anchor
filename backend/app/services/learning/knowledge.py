"""Knowledge-gap detection over the topic graph.

Pure functions over plain values, for the same reason `mastery.py` is: what the
student is told to fix must be reproducible and explainable. The language model
contributes the *edges* of the graph — which topic builds on which — and nothing
else. It is never asked what the student does not know, and it never sees a
mastery score.

WHAT COUNTS AS A GAP
====================

Weakness alone is not a gap. A topic the student has not reached yet is not a
failure, and a weak topic that nothing depends on is just ordinary revision. A gap
is weakness that has *consequences*: it sits underneath other topics.

So a topic is reported only when both hold:

    1. it is below GAP_THRESHOLD on effective (retention-adjusted) mastery, and
    2. there is evidence the student is actually engaged with that region of the
       course — either they have attempted the topic itself, or they have
       attempted something that depends on it.

Rule 2 is what stops a fresh course reporting every topic as a gap on day one.

SEVERITY
========

    deficit  = (GAP_THRESHOLD - effective) / GAP_THRESHOLD          in (0, 1]
    blocked  = number of topics that transitively depend on this one, capped
    severity = deficit * (1 + BLOCKED_WEIGHT * blocked) + UNMET_BONUS?

`UNMET_BONUS` applies when a topic downstream of this one has already been
attempted: the student is trying to build on ground that is not solid, which is the
single most useful thing this feature can tell them. The result is clamped to 1.

Worked examples (GAP_THRESHOLD 60, BLOCKED_WEIGHT 0.15, UNMET_BONUS 0.35):

    effective 30, nothing depends on it, attempted     -> 0.50 * 1.00        = 0.50
    effective 30, two dependents, neither attempted    -> 0.50 * 1.30        = 0.65
    effective 30, two dependents, one attempted        -> 0.50 * 1.30 + 0.35 = 1.00
    effective 0 (never started), a dependent attempted -> 1.00 * 1.15 + 0.35 = 1.00
    effective 55, one dependent, none attempted       -> 0.08 * 1.15        = 0.10

The last one is deliberately near-zero: a student sitting just under the threshold
on a topic with one dependent has a much smaller problem than the rows above, and
the ordering should say so.
"""

import uuid
from dataclasses import dataclass, field

# Below this, a topic is not solid enough to build on. Set between
# NEEDS_PRACTICE_BELOW (40) and STRONG_AT_OR_ABOVE (70) from mastery.py: a
# "Developing" topic can still be an unmet prerequisite, a "Strong" one cannot.
GAP_THRESHOLD = 60.0

# How much each dependent topic adds to severity.
BLOCKED_WEIGHT = 0.15

# Beyond four dependents the ranking is already decided; the cap stops one hub
# topic from dominating purely on fan-out.
MAX_COUNTED_DEPENDENTS = 4

# Added when the student has already attempted something built on this topic.
UNMET_BONUS = 0.35

# Reported gaps. More than this is a to-do list, not a recommendation.
MAX_GAPS = 5

# --- Gap kinds -----------------------------------------------------------------

UNMET_PREREQUISITE = "unmet_prerequisite"
BLOCKING = "blocking"
ISOLATED = "isolated"

GAP_KIND_LABELS = {
    UNMET_PREREQUISITE: "Unmet prerequisite",
    BLOCKING: "Blocking further topics",
    ISOLATED: "Needs practice",
}


@dataclass(frozen=True)
class TopicNode:
    """One topic as the gap detector sees it. No LLM output reaches this."""

    topic_id: uuid.UUID
    name: str
    effective_mastery: float
    # Quiz-question-equivalent evidence; 0 means never practised.
    evidence: float

    @property
    def attempted(self) -> bool:
        return self.evidence > 0


@dataclass(frozen=True)
class KnowledgeGap:
    topic_id: uuid.UUID
    name: str
    kind: str
    severity: float
    effective_mastery: float
    # Topics that transitively depend on this one, nearest first.
    blocked_topics: list[str] = field(default_factory=list)
    # Of those, the ones the student has already attempted.
    attempted_dependents: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        """A plain-language explanation, assembled from the same facts as the score.

        Written here rather than in the UI so the wording cannot drift away from
        what the algorithm actually decided.
        """
        if self.kind == UNMET_PREREQUISITE:
            names = ", ".join(self.attempted_dependents[:2])
            return (
                f"You are already working on {names}, which builds on this. "
                "Shoring this up first should make those easier."
            )
        if self.kind == BLOCKING:
            count = len(self.blocked_topics)
            subject = "topic" if count == 1 else "topics"
            return (
                f"{count} later {subject} in this course build on this one, "
                "so it is worth solidifying before moving on."
            )
        return "This topic is below where it needs to be, based on your recent answers."


def dependents_of(
    topic_id: uuid.UUID, prerequisite_edges: list[tuple[uuid.UUID, uuid.UUID]]
) -> list[uuid.UUID]:
    """Every topic that transitively depends on `topic_id`, nearest first.

    Edges are `(prerequisite, dependent)`. Traversal is breadth-first so the order
    is "what this unlocks next" rather than an arbitrary walk, and `seen` makes it
    terminate even if a cycle somehow reached the database.
    """
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
    for prerequisite, dependent in prerequisite_edges:
        adjacency.setdefault(prerequisite, []).append(dependent)

    ordered: list[uuid.UUID] = []
    seen = {topic_id}
    frontier = [topic_id]

    while frontier:
        nxt: list[uuid.UUID] = []
        for current in frontier:
            for dependent in adjacency.get(current, []):
                if dependent in seen:
                    continue
                seen.add(dependent)
                ordered.append(dependent)
                nxt.append(dependent)
        frontier = nxt

    return ordered


def detect_gaps(
    nodes: list[TopicNode],
    prerequisite_edges: list[tuple[uuid.UUID, uuid.UUID]],
    *,
    limit: int = MAX_GAPS,
) -> list[KnowledgeGap]:
    """Rank the course's knowledge gaps. Deterministic and total.

    Ties break on topic name so the same inputs always produce the same order —
    a student refreshing the page must not see the list shuffle.
    """
    by_id = {node.topic_id: node for node in nodes}
    gaps: list[KnowledgeGap] = []

    for node in nodes:
        if node.effective_mastery >= GAP_THRESHOLD:
            continue

        dependents = [
            by_id[dependent_id]
            for dependent_id in dependents_of(node.topic_id, prerequisite_edges)
            if dependent_id in by_id
        ]
        attempted = [dependent for dependent in dependents if dependent.attempted]

        # Rule 2: engagement, either with the topic or with something above it.
        if not node.attempted and not attempted:
            continue

        deficit = (GAP_THRESHOLD - node.effective_mastery) / GAP_THRESHOLD
        counted = min(len(dependents), MAX_COUNTED_DEPENDENTS)
        severity = deficit * (1 + BLOCKED_WEIGHT * counted)
        if attempted:
            severity += UNMET_BONUS
        severity = min(1.0, severity)

        if attempted:
            kind = UNMET_PREREQUISITE
        elif dependents:
            kind = BLOCKING
        else:
            kind = ISOLATED

        gaps.append(
            KnowledgeGap(
                topic_id=node.topic_id,
                name=node.name,
                kind=kind,
                severity=round(severity, 4),
                effective_mastery=round(node.effective_mastery, 1),
                blocked_topics=[dependent.name for dependent in dependents],
                attempted_dependents=[dependent.name for dependent in attempted],
            )
        )

    gaps.sort(key=lambda gap: (-gap.severity, gap.name))
    return gaps[:limit]
