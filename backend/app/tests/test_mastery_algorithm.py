"""The mastery formula. Pure functions, so these are exact-value tests."""

import pytest

from app.models import Difficulty
from app.services.learning.mastery import (
    DEVELOPING,
    NEEDS_PRACTICE,
    NEW_TOPIC,
    NOT_STARTED,
    STRONG,
    MasteryState,
    accuracy,
    apply_answer,
    band_for,
    displayed_mastery,
)


def state(raw: float, attempted: int, correct: int = 0) -> MasteryState:
    return MasteryState(
        raw_score=raw,
        mastery_score=displayed_mastery(raw, attempted),
        questions_attempted=attempted,
        correct_answers=correct,
    )


class TestFirstAnswer:
    def test_one_easy_correct_is_not_mastery(self) -> None:
        """The headline requirement: a lucky answer must not read as mastery."""
        result = apply_answer(NEW_TOPIC, difficulty=Difficulty.EASY, correct=True)

        assert result.raw_score == pytest.approx(18.0)
        assert result.mastery_score == pytest.approx(10.8)
        assert band_for(result) == NEEDS_PRACTICE

    def test_one_hard_correct_moves_more_but_is_still_not_strong(self) -> None:
        result = apply_answer(NEW_TOPIC, difficulty=Difficulty.HARD, correct=True)

        assert result.raw_score == pytest.approx(42.0)
        assert band_for(result) != STRONG

    def test_first_answer_records_the_attempt(self) -> None:
        result = apply_answer(NEW_TOPIC, difficulty=Difficulty.MEDIUM, correct=False)

        assert result.questions_attempted == 1
        assert result.correct_answers == 0
        assert result.last_answer_correct is False
        assert result.last_practised_at is not None


class TestRepeatedPerformance:
    def test_repeated_correct_answers_reach_strong(self) -> None:
        current = NEW_TOPIC
        for _ in range(6):
            current = apply_answer(current, difficulty=Difficulty.MEDIUM, correct=True)

        assert band_for(current) == STRONG
        assert current.correct_answers == 6

    def test_repeated_incorrect_answers_fall_to_needs_practice(self) -> None:
        current = state(90.0, 10, 9)
        for _ in range(4):
            current = apply_answer(current, difficulty=Difficulty.MEDIUM, correct=False)

        assert band_for(current) == NEEDS_PRACTICE

    def test_score_never_leaves_zero_to_one_hundred(self) -> None:
        current = NEW_TOPIC
        for index in range(60):
            current = apply_answer(
                current,
                difficulty=list(Difficulty)[index % 3],
                correct=index % 3 != 0,
            )
            assert 0.0 <= current.raw_score <= 100.0
            assert 0.0 <= current.mastery_score <= 100.0

    def test_mixed_performance_settles_between_the_extremes(self) -> None:
        current = NEW_TOPIC
        for index in range(20):
            current = apply_answer(
                current, difficulty=Difficulty.MEDIUM, correct=index % 2 == 0
            )

        assert 20.0 < current.mastery_score < 80.0


class TestResilience:
    def test_one_hard_miss_dents_but_does_not_destroy_mastery(self) -> None:
        result = apply_answer(
            state(80.0, 10, 9), difficulty=Difficulty.HARD, correct=False
        )

        assert result.raw_score == pytest.approx(63.2)
        assert band_for(result) == DEVELOPING

    def test_an_easy_miss_costs_more_than_a_hard_miss(self) -> None:
        """Failing something easy is more revealing than failing something hard."""
        before = state(80.0, 10, 9)
        easy = apply_answer(before, difficulty=Difficulty.EASY, correct=False)
        hard = apply_answer(before, difficulty=Difficulty.HARD, correct=False)

        assert easy.raw_score < hard.raw_score

    def test_a_hard_win_counts_more_than_an_easy_win(self) -> None:
        before = state(30.0, 6, 2)
        easy = apply_answer(before, difficulty=Difficulty.EASY, correct=True)
        hard = apply_answer(before, difficulty=Difficulty.HARD, correct=True)

        assert hard.raw_score > easy.raw_score


class TestRecencyWeighting:
    def test_recent_answers_outweigh_older_ones(self) -> None:
        """Same six answers, opposite order: the recent run dominates."""
        improving = NEW_TOPIC
        for correct in (False, False, False, True, True, True):
            improving = apply_answer(
                improving, difficulty=Difficulty.MEDIUM, correct=correct
            )

        declining = NEW_TOPIC
        for correct in (True, True, True, False, False, False):
            declining = apply_answer(
                declining, difficulty=Difficulty.MEDIUM, correct=correct
            )

        assert improving.correct_answers == declining.correct_answers
        assert improving.mastery_score > declining.mastery_score


class TestConfidenceDamping:
    def test_thin_evidence_is_damped(self) -> None:
        assert displayed_mastery(100.0, 1) == pytest.approx(60.0)
        assert displayed_mastery(100.0, 3) == pytest.approx(80.0)

    def test_damping_disappears_once_evidence_accumulates(self) -> None:
        assert displayed_mastery(100.0, 5) == pytest.approx(100.0)
        assert displayed_mastery(100.0, 50) == pytest.approx(100.0)


class TestBands:
    def test_never_attempted_is_not_started_not_zero(self) -> None:
        """A topic never practised has not been failed."""
        assert band_for(NEW_TOPIC) == NOT_STARTED
        assert accuracy(NEW_TOPIC) is None

    def test_band_boundaries(self) -> None:
        assert band_for(state(39.0, 10)) == NEEDS_PRACTICE
        assert band_for(state(40.0, 10)) == DEVELOPING
        assert band_for(state(69.0, 10)) == DEVELOPING
        assert band_for(state(70.0, 10)) == STRONG

    def test_accuracy_is_reported_separately_from_mastery(self) -> None:
        current = state(50.0, 10, 7)
        assert accuracy(current) == pytest.approx(70.0)
        assert current.mastery_score != accuracy(current)


class TestDeterminism:
    def test_identical_input_gives_identical_output(self) -> None:
        runs = {
            apply_answer(
                state(45.0, 8, 5), difficulty=Difficulty.HARD, correct=True
            ).raw_score
            for _ in range(10)
        }
        assert len(runs) == 1
