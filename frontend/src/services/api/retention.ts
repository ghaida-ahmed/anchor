import { apiRequest } from '@/services/api/client';
import type { ISODateString } from '@/types/domain';

/* --- Wire types ----------------------------------------------------------- */

interface TopicRetentionDto {
  topic_id: string;
  topic_name: string;
  mastery_score: number;
  effective_mastery: number;
  band: MasteryBand;
  band_label: string;
  effective_band: MasteryBand;
  retention_status: RetentionStatus;
  retention_label: string;
  questions_attempted: number;
  correct_answers: number;
  flashcard_reviews: number;
  accuracy: number | null;
  days_since_practice: number | null;
  last_practised_at: ISODateString | null;
  due_cards: number;
}

interface CourseMasteryDto {
  course_id: string;
  topics: TopicRetentionDto[];
  course_mastery: number;
  practised_mastery: number | null;
  coverage: number;
  topics_total: number;
  topics_started: number;
  topics_strong: number;
  questions_answered: number;
  correct_answers: number;
  accuracy: number | null;
  strongest_topic: string | null;
  weakest_topic: string | null;
  needs_review_topic: string | null;
}

/* --- Domain types --------------------------------------------------------- */

export type MasteryBand = 'not_started' | 'needs_practice' | 'developing' | 'strong';

/**
 * Review timing, deliberately distinct from the mastery band. A Strong topic can
 * still be Due — "how well do I know this" and "should I look at it" are different
 * questions.
 */
export type RetentionStatus = 'new' | 'fresh' | 'review_soon' | 'due' | 'overdue';

export type ReviewRating = 'again' | 'hard' | 'good' | 'easy';

export interface TopicRetention {
  topicId: string;
  topicName: string;
  /** What the student demonstrated. Never changes on its own. */
  masteryScore: number;
  /** Present estimate after the decay heuristic. */
  effectiveMastery: number;
  band: MasteryBand;
  bandLabel: string;
  effectiveBand: MasteryBand;
  retentionStatus: RetentionStatus;
  retentionLabel: string;
  questionsAttempted: number;
  correctAnswers: number;
  flashcardReviews: number;
  accuracy: number | null;
  daysSincePractice: number | null;
  lastPractisedAt: ISODateString | null;
  dueCards: number;
}

export interface CourseMastery {
  courseId: string;
  topics: TopicRetention[];
  /** Across every active topic, counting never-started ones as zero. */
  courseMastery: number;
  /** Across started topics only. Null when nothing has been practised. */
  practisedMastery: number | null;
  coverage: number;
  topicsTotal: number;
  topicsStarted: number;
  topicsStrong: number;
  questionsAnswered: number;
  correctAnswers: number;
  accuracy: number | null;
  strongestTopic: string | null;
  weakestTopic: string | null;
  needsReviewTopic: string | null;
}

export interface DailyActivity {
  day: string;
  answers: number;
  correct: number;
  meanMastery: number;
}

export interface AttemptScore {
  completedAt: ISODateString;
  scorePercent: number;
}

export interface TopicTrend {
  topicId: string;
  topicName: string;
  firstMastery: number;
  latestMastery: number;
  change: number;
}

export interface CourseAnalytics {
  daily: DailyActivity[];
  attemptScores: AttemptScore[];
  topicTrends: TopicTrend[];
  mostImprovedTopic: string | null;
  totalEvents: number;
  activeDays: number;
  firstActivity: ISODateString | null;
  lastActivity: ISODateString | null;
}

export interface DueSummary {
  dueNow: number;
  overdue: number;
  upcoming: number;
  total: number;
  neverReviewed: number;
}

export interface ReviewResult {
  flashcardId: string;
  nextReviewLabel: string;
  dueAt: ISODateString | null;
  intervalDays: number;
}

export interface Readiness {
  readiness: number;
  meanEffectiveMastery: number;
  coverage: number;
  reviewCurrency: number;
  topicsTotal: number;
  topicsStarted: number;
  overdueCards: number;
  totalCards: number;
}

export interface ExamStatus {
  examDate: string | null;
  daysRemaining: number | null;
  hasPassed: boolean;
  readiness: Readiness;
  topicsNeedingAttention: string[];
}

/* --- Mapping -------------------------------------------------------------- */

function toTopicRetention(dto: TopicRetentionDto): TopicRetention {
  return {
    topicId: dto.topic_id,
    topicName: dto.topic_name,
    masteryScore: dto.mastery_score,
    effectiveMastery: dto.effective_mastery,
    band: dto.band,
    bandLabel: dto.band_label,
    effectiveBand: dto.effective_band,
    retentionStatus: dto.retention_status,
    retentionLabel: dto.retention_label,
    questionsAttempted: dto.questions_attempted,
    correctAnswers: dto.correct_answers,
    flashcardReviews: dto.flashcard_reviews,
    accuracy: dto.accuracy,
    daysSincePractice: dto.days_since_practice,
    lastPractisedAt: dto.last_practised_at,
    dueCards: dto.due_cards,
  };
}

/* --- Endpoints ------------------------------------------------------------ */

export async function fetchMastery(courseId: string): Promise<CourseMastery> {
  const dto = await apiRequest<CourseMasteryDto>(`/v1/courses/${courseId}/mastery`);
  return {
    courseId: dto.course_id,
    topics: dto.topics.map(toTopicRetention),
    courseMastery: dto.course_mastery,
    practisedMastery: dto.practised_mastery,
    coverage: dto.coverage,
    topicsTotal: dto.topics_total,
    topicsStarted: dto.topics_started,
    topicsStrong: dto.topics_strong,
    questionsAnswered: dto.questions_answered,
    correctAnswers: dto.correct_answers,
    accuracy: dto.accuracy,
    strongestTopic: dto.strongest_topic,
    weakestTopic: dto.weakest_topic,
    needsReviewTopic: dto.needs_review_topic,
  };
}

export async function fetchAnalytics(courseId: string): Promise<CourseAnalytics> {
  const dto = await apiRequest<{
    daily: { day: string; answers: number; correct: number; mean_mastery: number }[];
    attempt_scores: { completed_at: string; score_percent: number }[];
    topic_trends: {
      topic_id: string;
      topic_name: string;
      first_mastery: number;
      latest_mastery: number;
      change: number;
    }[];
    most_improved_topic: string | null;
    total_events: number;
    active_days: number;
    first_activity: string | null;
    last_activity: string | null;
  }>(`/v1/courses/${courseId}/analytics`);

  return {
    daily: dto.daily.map((point) => ({
      day: point.day,
      answers: point.answers,
      correct: point.correct,
      meanMastery: point.mean_mastery,
    })),
    attemptScores: dto.attempt_scores.map((score) => ({
      completedAt: score.completed_at,
      scorePercent: score.score_percent,
    })),
    topicTrends: dto.topic_trends.map((trend) => ({
      topicId: trend.topic_id,
      topicName: trend.topic_name,
      firstMastery: trend.first_mastery,
      latestMastery: trend.latest_mastery,
      change: trend.change,
    })),
    mostImprovedTopic: dto.most_improved_topic,
    totalEvents: dto.total_events,
    activeDays: dto.active_days,
    firstActivity: dto.first_activity,
    lastActivity: dto.last_activity,
  };
}

export async function fetchDueSummary(courseId: string): Promise<DueSummary> {
  const dto = await apiRequest<{
    due_now: number;
    overdue: number;
    upcoming: number;
    total: number;
    never_reviewed: number;
  }>(`/v1/courses/${courseId}/flashcards/due`);

  return {
    dueNow: dto.due_now,
    overdue: dto.overdue,
    upcoming: dto.upcoming,
    total: dto.total,
    neverReviewed: dto.never_reviewed,
  };
}

export async function submitReview(
  flashcardId: string,
  rating: ReviewRating,
): Promise<ReviewResult> {
  const dto = await apiRequest<{
    flashcard_id: string;
    next_review_label: string;
    due_at: string | null;
    interval_days: number;
  }>(`/v1/flashcards/${flashcardId}/reviews`, { method: 'POST', body: { rating } });

  return {
    flashcardId: dto.flashcard_id,
    nextReviewLabel: dto.next_review_label,
    dueAt: dto.due_at,
    intervalDays: dto.interval_days,
  };
}

function toExamStatus(dto: {
  exam_date: string | null;
  days_remaining: number | null;
  has_passed: boolean;
  readiness: {
    readiness: number;
    mean_effective_mastery: number;
    coverage: number;
    review_currency: number;
    topics_total: number;
    topics_started: number;
    overdue_cards: number;
    total_cards: number;
  };
  topics_needing_attention: string[];
}): ExamStatus {
  return {
    examDate: dto.exam_date,
    daysRemaining: dto.days_remaining,
    hasPassed: dto.has_passed,
    readiness: {
      readiness: dto.readiness.readiness,
      meanEffectiveMastery: dto.readiness.mean_effective_mastery,
      coverage: dto.readiness.coverage,
      reviewCurrency: dto.readiness.review_currency,
      topicsTotal: dto.readiness.topics_total,
      topicsStarted: dto.readiness.topics_started,
      overdueCards: dto.readiness.overdue_cards,
      totalCards: dto.readiness.total_cards,
    },
    topicsNeedingAttention: dto.topics_needing_attention,
  };
}

export async function fetchExamStatus(courseId: string): Promise<ExamStatus> {
  return toExamStatus(await apiRequest(`/v1/courses/${courseId}/exam`));
}

export async function setExamDate(
  courseId: string,
  examDate: string | null,
): Promise<ExamStatus> {
  return toExamStatus(
    await apiRequest(`/v1/courses/${courseId}/exam`, {
      method: 'PUT',
      body: { exam_date: examDate },
    }),
  );
}
