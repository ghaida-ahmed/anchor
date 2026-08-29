"""Topic selection and difficulty adaptation. Deterministic, so exact assertions."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Difficulty
from app.services.learning.adaptive import (
    SPACED_REVIEW_MIN_TOPICS,
    TopicCandidate,
    difficulty_plan,
    priority_for,
    select_topics,
)
from app.services.learning.mastery import (
    DEVELOPING,
    NEEDS_PRACTICE,
    NOT_STARTED,
    STRONG,
    MasteryState,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def candidate(
    name: str,
    mastery: float,
    attempted: int,
    *,
    last_correct: bool | None = None,
    days_ago: float | None = None,
    effective: float | None = None,
    due_cards: int = 0,
) -> TopicCandidate:
    """Build a candidate.

    `effective` defaults to the stored score, i.e. "practised just now". Tests that
    care about elapsed time set it explicitly: the selector no longer computes decay
    itself, which is what keeps it a pure function of its inputs.
    """
    state = MasteryState(
        raw_score=mastery,
        mastery_score=mastery,
        questions_attempted=attempted,
        correct_answers=int(attempted * 0.6),
        last_answer_correct=last_correct,
        last_practised_at=None if days_ago is None else NOW - timedelta(days=days_ago),
    )
    return TopicCandidate(
        topic_id=uuid.uuid4(),
        name=name,
        state=state,
        effective_mastery=mastery if effective is None else effective,
        due_cards=due_cards,
    )


class TestPriority:
    def test_weaker_topics_score_higher(self) -> None:
        weak = candidate("Weak", 20.0, 10, last_correct=True, days_ago=1, effective=20.0)
        strong = candidate(
            "Strong", 90.0, 10, last_correct=True, days_ago=1, effective=90.0
        )

        assert priority_for(weak, now=NOW) > priority_for(strong, now=NOW)

    def test_thin_evidence_raises_priority(self) -> None:
        """Two lucky answers should not look like a settled topic."""
        thin = candidate("Thin", 60.0, 1, last_correct=True, days_ago=1)
        established = candidate("Established", 60.0, 20, last_correct=True, days_ago=1)

        assert priority_for(thin, now=NOW) > priority_for(established, now=NOW)

    def test_a_recent_miss_raises_priority(self) -> None:
        missed = candidate("Missed", 60.0, 10, last_correct=False, days_ago=1)
        hit = candidate("Hit", 60.0, 10, last_correct=True, days_ago=1)

        assert priority_for(missed, now=NOW) > priority_for(hit, now=NOW)

    def test_elapsed_time_raises_priority_through_effective_mastery(self) -> None:
        """Staleness is no longer its own term — decay reaches priority via weakness."""
        decayed = candidate(
            "Stale", 60.0, 10, last_correct=True, days_ago=30, effective=44.0
        )
        fresh = candidate(
            "Fresh", 60.0, 10, last_correct=True, days_ago=0, effective=60.0
        )

        assert priority_for(decayed, now=NOW) > priority_for(fresh, now=NOW)

    def test_priority_ignores_the_clock(self) -> None:
        """Elapsed time must reach priority only through effective mastery.

        Passing a different `now` must change nothing; otherwise time would be
        counted twice — once in the decay and again in the selector.
        """
        item = candidate(
            "Topic", 60.0, 10, last_correct=True, days_ago=30, effective=44.0
        )

        assert priority_for(item, now=NOW) == priority_for(
            item, now=NOW + timedelta(days=90)
        )

    def test_due_cards_raise_priority(self) -> None:
        """Review pressure is the term that replaced staleness."""
        pressured = candidate("Due", 60.0, 10, last_correct=True, due_cards=5)
        clear = candidate("Clear", 60.0, 10, last_correct=True, due_cards=0)

        assert priority_for(pressured, now=NOW) > priority_for(clear, now=NOW)

    def test_never_practised_scores_highest(self) -> None:
        never = candidate("Never", 0.0, 0)
        # 0.50 weakness + 0.25 evidence_need, with no miss and no due cards.
        assert priority_for(never, now=NOW) == pytest.approx(0.75)

    def test_priority_stays_in_range(self) -> None:
        for item in (
            candidate("A", 0.0, 0),
            candidate("B", 100.0, 50, last_correct=True, days_ago=0),
            candidate("C", 50.0, 3, last_correct=False, days_ago=100),
        ):
            assert 0.0 <= priority_for(item, now=NOW) <= 1.0


class TestSelection:
    def test_weak_topics_are_prioritised(self) -> None:
        chosen = select_topics(
            [
                candidate("Strong One", 92.0, 20, last_correct=True, days_ago=0),
                candidate("Weak", 15.0, 8, last_correct=False, days_ago=1),
                candidate("Strong Two", 88.0, 20, last_correct=True, days_ago=0),
            ],
            question_count=6,
            now=NOW,
        )

        assert chosen[0].name == "Weak"

    def test_unattempted_topics_surface(self) -> None:
        chosen = select_topics(
            [
                candidate("Known", 65.0, 15, last_correct=True, days_ago=1),
                candidate("Untouched", 0.0, 0),
            ],
            question_count=4,
            now=NOW,
        )

        assert chosen[0].name == "Untouched"
        assert chosen[0].band == NOT_STARTED

    def test_strong_topics_are_not_permanently_ignored(self) -> None:
        """More weak topics than slots, so the strong one loses on priority.

        Without the reserved review slot it would never be revisited, and the
        student's best topic would silently decay.
        """
        chosen = select_topics(
            [
                candidate("Weak A", 12.0, 8, last_correct=False, days_ago=1),
                candidate("Weak B", 14.0, 8, last_correct=False, days_ago=1),
                candidate("Weak C", 16.0, 8, last_correct=False, days_ago=1),
                candidate("Weak D", 18.0, 8, last_correct=False, days_ago=1),
                candidate("Weak E", 20.0, 8, last_correct=False, days_ago=1),
                candidate("Mastered", 95.0, 30, last_correct=True, days_ago=0),
            ],
            question_count=8,
            max_topics=4,
            now=NOW,
        )

        review = [item for item in chosen if item.is_review]
        assert len(review) == 1
        assert review[0].name == "Mastered"
        assert review[0].band == STRONG

    def test_a_strong_topic_selected_on_merit_is_not_swapped_out(self) -> None:
        """Staleness already feeds priority; substituting would be pure churn."""
        chosen = select_topics(
            [
                candidate("Weak", 20.0, 8, last_correct=False, days_ago=1),
                candidate("Stale Strong", 85.0, 12, last_correct=True, days_ago=30),
                candidate("Developing", 45.0, 6, last_correct=True, days_ago=2),
                candidate("Fresh Strong", 80.0, 12, last_correct=True, days_ago=0),
            ],
            question_count=8,
            now=NOW,
        )

        names = [item.name for item in chosen]
        assert "Stale Strong" in names
        assert not any(item.is_review for item in chosen)

    def test_below_the_review_threshold_every_slot_goes_to_priority(self) -> None:
        chosen = select_topics(
            [
                candidate("Weak A", 12.0, 8, last_correct=False, days_ago=1),
                candidate("Mastered", 95.0, 30, last_correct=True, days_ago=0),
            ],
            question_count=4,
            now=NOW,
        )

        assert len(chosen) < SPACED_REVIEW_MIN_TOPICS
        assert not any(item.is_review for item in chosen)

    def test_questions_are_fully_allocated(self) -> None:
        chosen = select_topics(
            [
                candidate(f"T{index}", 40.0, 5, last_correct=True, days_ago=1)
                for index in range(6)
            ],
            question_count=10,
            now=NOW,
        )

        assert sum(item.question_count for item in chosen) == 10

    def test_selection_is_deterministic(self) -> None:
        pool = [
            candidate("Alpha", 30.0, 5, last_correct=False, days_ago=2),
            candidate("Beta", 30.0, 5, last_correct=False, days_ago=2),
            candidate("Gamma", 75.0, 12, last_correct=True, days_ago=5),
        ]

        outcomes = {
            tuple(
                (item.name, item.question_count)
                for item in select_topics(pool, question_count=7, now=NOW)
            )
            for _ in range(10)
        }

        assert len(outcomes) == 1

    def test_no_candidates_yields_nothing(self) -> None:
        assert select_topics([], question_count=5, now=NOW) == []


class TestDifficultyAdaptation:
    def test_weak_students_get_mostly_easy_but_never_only_easy(self) -> None:
        plan = difficulty_plan(NEEDS_PRACTICE, 10)

        assert plan[Difficulty.EASY] > plan[Difficulty.MEDIUM]
        assert plan[Difficulty.MEDIUM] > 0, "a weak student must still be stretched"
        assert Difficulty.HARD not in plan

    def test_strong_students_still_get_medium_review(self) -> None:
        plan = difficulty_plan(STRONG, 10)

        assert plan[Difficulty.HARD] >= plan[Difficulty.MEDIUM]
        assert plan[Difficulty.MEDIUM] > 0, "a strong student must still revise"

    def test_developing_students_get_a_spread(self) -> None:
        plan = difficulty_plan(DEVELOPING, 8)

        assert set(plan) == {Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD}

    def test_unstarted_topics_avoid_hard_questions(self) -> None:
        plan = difficulty_plan(NOT_STARTED, 6)

        assert Difficulty.HARD not in plan

    def test_difficulty_rises_with_mastery(self) -> None:
        weak = difficulty_plan(NEEDS_PRACTICE, 10)
        developing = difficulty_plan(DEVELOPING, 10)
        strong = difficulty_plan(STRONG, 10)

        assert weak.get(Difficulty.HARD, 0) < developing.get(Difficulty.HARD, 0)
        assert developing.get(Difficulty.HARD, 0) < strong.get(Difficulty.HARD, 0)

    def test_counts_always_sum_to_the_request(self) -> None:
        for band in (NOT_STARTED, NEEDS_PRACTICE, DEVELOPING, STRONG):
            for count in range(1, 21):
                assert sum(difficulty_plan(band, count).values()) == count

    def test_zero_questions_yields_no_plan(self) -> None:
        assert difficulty_plan(STRONG, 0) == {}

    def test_allocation_is_deterministic(self) -> None:
        assert (
            len(
                {tuple(sorted(difficulty_plan(DEVELOPING, 7).items())) for _ in range(10)}
            )
            == 1
        )
