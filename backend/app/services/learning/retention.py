"""Effective mastery: what a student is estimated to retain right now.

STORED VS EFFECTIVE
===================

`TopicMastery.mastery_score` is *stored* mastery — the record of what the student
actually demonstrated. It changes only when they answer something. Nothing in this
module writes to the database, and no scheduled job subtracts points as time passes:
destroying evidence because a month went by would be both wrong and unexplainable.

*Effective* mastery is derived on read: stored mastery discounted by how long it has
gone unpractised. It is an estimate of present confidence, not a claim about the
student's brain.

THE FORMULA
===========

    effective = stored x retention(days)

    retention(days) = FLOOR + (1 - FLOOR) * 0.5 ** (days / H)

    H = BASE_HALF_LIFE_DAYS
        x (0.5 + 0.5 * min(1, evidence / MIN_EVIDENCE))     evidence factor
        x (0.7 + 0.6 * stored / 100)                        strength factor

`H` is the half-life of the *uncertainty*, not of the knowledge. Two things lengthen
it: more evidence behind the score, and a higher score. Both are defensible — a
topic answered correctly ten times is a safer bet a month later than one answered
once, and material learned well decays more slowly than material barely grasped.

`FLOOR = 0.55` stops decay short of zero. Inactivity raises doubt; it does not erase
a demonstrated result. Sixty days of neglect costs a strong topic about 25 points,
which is enough to prompt review without pretending the student has forgotten
everything.

HONEST LIMITS
-------------

This is a transparent heuristic, not a validated cognitive model. It is not fitted
to recall data and makes no claim to predict what any individual remembers. Its
purpose is to rank topics for review in a way a student can understand.
"""

from datetime import datetime

from app.core.clock import days_between, now
from app.services.learning.mastery import MIN_EVIDENCE

# Retention asymptote: decay never takes a score below this fraction of stored.
FLOOR = 0.55

# Half-life for a mid-strength, fully-evidenced topic, in days.
BASE_HALF_LIFE_DAYS = 30.0


def half_life_days(stored_mastery: float, evidence: float) -> float:
    """Uncertainty half-life for a topic, in days."""
    evidence_factor = 0.5 + 0.5 * min(1.0, max(0.0, evidence) / MIN_EVIDENCE)
    strength_factor = 0.7 + 0.6 * (max(0.0, min(100.0, stored_mastery)) / 100.0)
    return BASE_HALF_LIFE_DAYS * evidence_factor * strength_factor


def retention_factor(stored_mastery: float, evidence: float, days: float) -> float:
    """The multiplier applied to stored mastery. In (FLOOR, 1.0]."""
    if days <= 0:
        return 1.0
    decayed = 0.5 ** (days / half_life_days(stored_mastery, evidence))
    return FLOOR + (1.0 - FLOOR) * decayed


def effective_mastery(
    stored_mastery: float,
    evidence: float,
    last_practised_at: datetime | None,
    *,
    at: datetime | None = None,
) -> float:
    """Estimated current mastery.

    Returns 0 for a topic with no evidence: there is nothing to decay, and the
    caller distinguishes "not started" from "forgotten" by the evidence count, not
    by this number.
    """
    if evidence <= 0:
        return 0.0
    if last_practised_at is None:
        # Evidence but no timestamp should not happen; treat as undecayed rather
        # than inventing an elapsed time.
        return _clamp(stored_mastery)

    elapsed = days_between(last_practised_at, at or now())
    return _clamp(stored_mastery * retention_factor(stored_mastery, evidence, elapsed))


def days_since_practice(
    last_practised_at: datetime | None, *, at: datetime | None = None
) -> float | None:
    if last_practised_at is None:
        return None
    return days_between(last_practised_at, at or now())


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


# --- Retention status ----------------------------------------------------------
#
# Deliberately separate from the mastery band. "Strong" says how well the student
# knows something; retention status says whether it needs looking at. A Strong topic
# left for a month is Strong AND due for review, and conflating the two would either
# hide the review or imply the student had got worse.

NEW = "new"
FRESH = "fresh"
REVIEW_SOON = "review_soon"
DUE = "due"
OVERDUE = "overdue"

RETENTION_LABELS = {
    NEW: "Not started",
    FRESH: "Fresh",
    REVIEW_SOON: "Review soon",
    DUE: "Due",
    OVERDUE: "Overdue",
}

# A topic unpractised for longer than this is flagged before anything is formally
# due, so a student is nudged before the estimate has slipped far.
REVIEW_SOON_AFTER_DAYS = 10.0


def retention_status(
    *,
    has_evidence: bool,
    days_since_practice: float | None,
    due_cards: int = 0,
    overdue_cards: int = 0,
) -> str:
    """Classify a topic by review timing rather than by attainment."""
    if not has_evidence:
        return NEW
    if overdue_cards > 0:
        return OVERDUE
    if due_cards > 0:
        return DUE
    if days_since_practice is not None and days_since_practice >= REVIEW_SOON_AFTER_DAYS:
        return REVIEW_SOON
    return FRESH
