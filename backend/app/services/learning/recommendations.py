"""Personalised study recommendations, built from templates.

Every recommendation is a pure function of the mastery table and the review queue.
There is no model call: this text appears on the Progress and Overview pages, which
load on every visit, and paying for a generation each time would be indefensible on
a free tier — and non-deterministic for something that should be stable.

Recommendations are ranked by the same deterministic priority the adaptive quiz
uses, so what the page suggests and what a quiz would actually practise agree.
"""

from dataclasses import dataclass

from app.services.learning.adaptive import TopicCandidate, priority_for
from app.services.learning.mastery import (
    DEVELOPING,
    NEEDS_PRACTICE,
    NOT_STARTED,
    STRONG,
)
from app.services.learning.retention import REVIEW_SOON_AFTER_DAYS, days_since_practice


@dataclass(frozen=True)
class Recommendation:
    """A suggested next action, plus the topic it concerns."""

    kind: str
    title: str
    detail: str
    topic_id: str | None = None
    topic_name: str | None = None


def build(
    candidates: list[TopicCandidate],
    *,
    limit: int = 4,
    due_cards: int = 0,
    overdue_cards: int = 0,
) -> list[Recommendation]:
    """Rank what the student should do next."""
    if not candidates:
        return [
            Recommendation(
                kind="no_topics",
                title="Add course material to get started",
                detail=(
                    "Upload your lecture notes and extract topics — ANCHOR builds "
                    "quizzes and mastery tracking from your own material."
                ),
            )
        ]

    ranked = sorted(candidates, key=lambda c: (-priority_for(c), c.name.lower()))
    recommendations: list[Recommendation] = []

    # Overdue reviews come first: they are the cheapest way to recover ground.
    if overdue_cards > 0:
        card_word = "card" if overdue_cards == 1 else "cards"
        recommendations.append(
            Recommendation(
                kind="overdue_reviews",
                title=f"Catch up on {overdue_cards} overdue {card_word}",
                detail="Reviewing these first is the quickest way to steady your recall.",
            )
        )
    elif due_cards > 0:
        card_word = "card" if due_cards == 1 else "cards"
        recommendations.append(
            Recommendation(
                kind="due_reviews",
                title=f"Review {due_cards} {card_word} due today",
                detail="Short reviews now keep topics from slipping.",
            )
        )

    for candidate in ranked:
        if len(recommendations) >= limit:
            break

        state = candidate.state
        elapsed = days_since_practice(state.last_practised_at)
        band = candidate.effective_band

        if band == NOT_STARTED:
            recommendations.append(
                Recommendation(
                    kind="start_topic",
                    title=f"Start {candidate.name}",
                    detail="You have not practised this topic yet.",
                    topic_id=str(candidate.topic_id),
                    topic_name=candidate.name,
                )
            )
        elif candidate.due_cards > 0:
            card_word = "flashcard is" if candidate.due_cards == 1 else "flashcards are"
            recommendations.append(
                Recommendation(
                    kind="topic_reviews_due",
                    title=f"Review {candidate.name}",
                    detail=f"{candidate.due_cards} {card_word} due.",
                    topic_id=str(candidate.topic_id),
                    topic_name=candidate.name,
                )
            )
        elif state.last_answer_correct is False:
            recommendations.append(
                Recommendation(
                    kind="recent_mistake",
                    title=f"Practise {candidate.name}",
                    detail="Your most recent answer on this topic was incorrect.",
                    topic_id=str(candidate.topic_id),
                    topic_name=candidate.name,
                )
            )
        elif band == NEEDS_PRACTICE:
            attempted = state.questions_attempted
            noun = "question" if attempted == 1 else "questions"
            recommendations.append(
                Recommendation(
                    kind="practice_weak",
                    title=f"Practise {candidate.name}",
                    detail=(
                        f"Estimated mastery {candidate.effective_mastery:.0f}% "
                        f"after {attempted} {noun}."
                    ),
                    topic_id=str(candidate.topic_id),
                    topic_name=candidate.name,
                )
            )
        elif band == STRONG and elapsed is not None and elapsed >= REVIEW_SOON_AFTER_DAYS:
            # Deliberately framed as time elapsed, not as knowledge lost: the
            # student did not suddenly forget a measured percentage.
            recommendations.append(
                Recommendation(
                    kind="refresh_strong",
                    title=f"Refresh {candidate.name}",
                    detail=(
                        f"You know this well, but it was last practised "
                        f"{elapsed:.0f} days ago."
                    ),
                    topic_id=str(candidate.topic_id),
                    topic_name=candidate.name,
                )
            )
        elif band == DEVELOPING:
            recommendations.append(
                Recommendation(
                    kind="review_developing",
                    title=f"Build on {candidate.name}",
                    detail=(
                        f"Estimated mastery {candidate.effective_mastery:.0f}% — "
                        "solid, but not yet consistent."
                    ),
                    topic_id=str(candidate.topic_id),
                    topic_name=candidate.name,
                )
            )

    if not recommendations:
        recommendations.append(
            Recommendation(
                kind="keep_going",
                title="Take an adaptive quiz",
                detail="ANCHOR will pick the topics that need work most.",
            )
        )

    return recommendations[:limit]
