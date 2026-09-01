import { apiRequest } from '@/services/api/client';
import type { ISODateString } from '@/types/domain';

/* -------------------------------------------------------------------------- */
/*  Wire types                                                                 */
/* -------------------------------------------------------------------------- */

interface TopicDto {
  id: string;
  course_id: string;
  name: string;
  description: string;
  is_active: boolean;
  created_at: ISODateString;
}

interface SourceDto {
  document_id: string;
  document_name: string;
  page_number: number | null;
  chunk_id: string;
}

interface QuizQuestionDto {
  id: string;
  position: number;
  question_text: string;
  question_type: QuestionType;
  /** Null for short answers — nothing to choose from. */
  options: string[] | null;
  difficulty: Difficulty;
  topic_id: string;
  topic_name: string;
}

interface QuizDto {
  id: string;
  course_id: string;
  title: string;
  mode: QuizMode;
  selection_rationale: string;
  difficulty_plan: Record<string, number>;
  question_count: number;
  created_at: ISODateString;
  questions?: QuizQuestionDto[];
}

interface AttemptDto {
  id: string;
  quiz_id: string;
  started_at: ISODateString;
  completed_at: ISODateString | null;
  score_percent: number | null;
  correct_count: number;
}

interface ConceptResultDto {
  concept: string;
  satisfied: boolean;
}

interface AnswerResultDto {
  question_id: string;
  question_type: QuestionType;
  explanation: string;
  source: SourceDto | null;
  selected_index: number | null;
  correct_index: number | null;
  is_correct: boolean | null;
  response_text: string | null;
  verdict: AnswerVerdict | null;
  grading_state: GradingState;
  rubric_results: ConceptResultDto[];
  feedback: string | null;
  reference_answer: string | null;
  grading_failed: boolean;
}

interface AttemptSummaryDto extends AttemptDto {
  quiz_title: string;
  question_count: number;
  results: AnswerResultDto[];
}

interface TopicMasteryDto {
  topic_id: string;
  topic_name: string;
  mastery_score: number;
  band: MasteryBand;
  band_label: string;
  questions_attempted: number;
  correct_answers: number;
  accuracy: number | null;
  last_practised_at: ISODateString | null;
}

interface CourseMasteryDto {
  course_id: string;
  topics: TopicMasteryDto[];
  overall_mastery: number | null;
  topics_total: number;
  topics_started: number;
  topics_strong: number;
  questions_answered: number;
  correct_answers: number;
  accuracy: number | null;
  strongest_topic: string | null;
  weakest_topic: string | null;
}

interface RecommendationDto {
  kind: string;
  title: string;
  detail: string;
  topic_id: string | null;
  topic_name: string | null;
}

interface FlashcardDto {
  id: string;
  course_id: string;
  topic_id: string;
  topic_name: string;
  front: string;
  back: string;
  source: SourceDto | null;
  created_at: ISODateString;
}

/* -------------------------------------------------------------------------- */
/*  Domain types                                                               */
/* -------------------------------------------------------------------------- */

export const DIFFICULTIES = ['easy', 'medium', 'hard'] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

/**
 * How a quiz's topics were chosen. `exam` is coverage-first under a deadline; the
 * backend decides in every case — the model only writes the questions.
 */
export type QuizMode = 'standard' | 'adaptive' | 'exam';

/** One stored question's format. Mirrors `QuestionType` in the backend models. */
export type QuestionType = 'mcq' | 'short_answer';

/** What a generated quiz should contain. Multiple choice stays the default. */
export const QUIZ_FORMATS = ['mcq', 'short_answer', 'mixed'] as const;
export type QuizFormat = (typeof QUIZ_FORMATS)[number];

/**
 * The outcome of marking one written answer.
 *
 * `uncertain` is a real result, not an error: the grader could not judge the
 * answer, so it neither rewards nor penalises the student and is left out of the
 * score denominator. The UI must show it as unmarked, never as wrong.
 */
export type AnswerVerdict =
  | 'correct'
  | 'partially_correct'
  | 'incorrect'
  | 'uncertain';

/** Whether marking happened at all. `failed` means the provider could not be
 * reached; the answer is stored and mastery is untouched. */
export type GradingState = 'not_required' | 'graded' | 'failed';

/** Mirrors the bands in backend/app/services/learning/mastery.py. */
export type MasteryBand = 'not_started' | 'needs_practice' | 'developing' | 'strong';

export interface Topic {
  id: string;
  courseId: string;
  name: string;
  description: string;
  isActive: boolean;
}

export interface QuizSource {
  documentId: string;
  documentName: string;
  /** Null for formats without real pages (TXT, Markdown) — never a fabricated 1. */
  pageNumber: number | null;
  chunkId: string;
}

export interface QuizQuestion {
  id: string;
  position: number;
  questionText: string;
  questionType: QuestionType;
  /** Null for short answers. The reference answer and rubric are never sent to
   * the client before the student submits. */
  options: string[] | null;
  difficulty: Difficulty;
  topicId: string;
  topicName: string;
}

export interface Quiz {
  id: string;
  courseId: string;
  title: string;
  mode: QuizMode;
  selectionRationale: string;
  difficultyPlan: Record<string, number>;
  questionCount: number;
  createdAt: ISODateString;
  questions: QuizQuestion[];
}

export interface Attempt {
  id: string;
  quizId: string;
  startedAt: ISODateString;
  completedAt: ISODateString | null;
  scorePercent: number | null;
  correctCount: number;
}

export interface ConceptResult {
  concept: string;
  satisfied: boolean;
}

export interface AnswerResult {
  questionId: string;
  questionType: QuestionType;
  explanation: string;
  source: QuizSource | null;

  /** Multiple choice. Null on a written answer. */
  selectedIndex: number | null;
  correctIndex: number | null;
  /** Null for a partial or uncertain verdict — neither is a boolean outcome. */
  isCorrect: boolean | null;

  /** Short answer. */
  responseText: string | null;
  verdict: AnswerVerdict | null;
  gradingState: GradingState;
  rubricResults: ConceptResult[];
  feedback: string | null;
  referenceAnswer: string | null;
  gradingFailed: boolean;
}

export interface AttemptSummary extends Attempt {
  quizTitle: string;
  questionCount: number;
  results: AnswerResult[];
}

export interface TopicMastery {
  topicId: string;
  topicName: string;
  masteryScore: number;
  band: MasteryBand;
  bandLabel: string;
  questionsAttempted: number;
  correctAnswers: number;
  accuracy: number | null;
  lastPractisedAt: ISODateString | null;
}

export interface CourseMastery {
  courseId: string;
  topics: TopicMastery[];
  overallMastery: number | null;
  topicsTotal: number;
  topicsStarted: number;
  topicsStrong: number;
  questionsAnswered: number;
  correctAnswers: number;
  accuracy: number | null;
  strongestTopic: string | null;
  weakestTopic: string | null;
}

export interface Recommendation {
  kind: string;
  title: string;
  detail: string;
  topicId: string | null;
  topicName: string | null;
}

export interface Flashcard {
  id: string;
  courseId: string;
  topicId: string;
  topicName: string;
  front: string;
  back: string;
  source: QuizSource | null;
}

/* -------------------------------------------------------------------------- */
/*  Mapping                                                                    */
/* -------------------------------------------------------------------------- */

function toSource(dto: SourceDto | null): QuizSource | null {
  if (!dto) return null;
  return {
    documentId: dto.document_id,
    documentName: dto.document_name,
    pageNumber: dto.page_number,
    chunkId: dto.chunk_id,
  };
}

function toTopic(dto: TopicDto): Topic {
  return {
    id: dto.id,
    courseId: dto.course_id,
    name: dto.name,
    description: dto.description,
    isActive: dto.is_active,
  };
}

function toQuestion(dto: QuizQuestionDto): QuizQuestion {
  return {
    id: dto.id,
    position: dto.position,
    questionText: dto.question_text,
    questionType: dto.question_type,
    options: dto.options,
    difficulty: dto.difficulty,
    topicId: dto.topic_id,
    topicName: dto.topic_name,
  };
}

function toQuiz(dto: QuizDto): Quiz {
  return {
    id: dto.id,
    courseId: dto.course_id,
    title: dto.title,
    mode: dto.mode,
    selectionRationale: dto.selection_rationale,
    difficultyPlan: dto.difficulty_plan,
    questionCount: dto.question_count,
    createdAt: dto.created_at,
    questions: (dto.questions ?? []).map(toQuestion),
  };
}

function toAttempt(dto: AttemptDto): Attempt {
  return {
    id: dto.id,
    quizId: dto.quiz_id,
    startedAt: dto.started_at,
    completedAt: dto.completed_at,
    scorePercent: dto.score_percent,
    correctCount: dto.correct_count,
  };
}

function toAnswerResult(dto: AnswerResultDto): AnswerResult {
  return {
    questionId: dto.question_id,
    questionType: dto.question_type,
    explanation: dto.explanation,
    source: toSource(dto.source),
    selectedIndex: dto.selected_index,
    correctIndex: dto.correct_index,
    isCorrect: dto.is_correct,
    responseText: dto.response_text,
    verdict: dto.verdict,
    gradingState: dto.grading_state,
    rubricResults: dto.rubric_results.map((row) => ({
      concept: row.concept,
      satisfied: row.satisfied,
    })),
    feedback: dto.feedback,
    referenceAnswer: dto.reference_answer,
    gradingFailed: dto.grading_failed,
  };
}

function toMastery(dto: TopicMasteryDto): TopicMastery {
  return {
    topicId: dto.topic_id,
    topicName: dto.topic_name,
    masteryScore: dto.mastery_score,
    band: dto.band,
    bandLabel: dto.band_label,
    questionsAttempted: dto.questions_attempted,
    correctAnswers: dto.correct_answers,
    accuracy: dto.accuracy,
    lastPractisedAt: dto.last_practised_at,
  };
}

function toFlashcard(dto: FlashcardDto): Flashcard {
  return {
    id: dto.id,
    courseId: dto.course_id,
    topicId: dto.topic_id,
    topicName: dto.topic_name,
    front: dto.front,
    back: dto.back,
    source: toSource(dto.source),
  };
}

/* -------------------------------------------------------------------------- */
/*  Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

export async function fetchTopics(courseId: string): Promise<Topic[]> {
  const dtos = await apiRequest<TopicDto[]>(`/v1/courses/${courseId}/topics`);
  return dtos.map(toTopic);
}

export interface TopicSyncStatus {
  courseId: string;
  /**
   * False only when the course has processed material the topic set was not
   * derived from. A course with nothing processed reports true — there is
   * nothing to extract, so prompting the student would be noise.
   */
  topicsAreCurrent: boolean;
  topicCount: number;
  readyDocumentCount: number;
}

interface TopicSyncStatusDto {
  course_id: string;
  topics_are_current: boolean;
  topic_count: number;
  ready_document_count: number;
}

/** Deterministic and cheap — no model call, safe on every page load. */
export async function fetchTopicSyncStatus(courseId: string): Promise<TopicSyncStatus> {
  const dto = await apiRequest<TopicSyncStatusDto>(
    `/v1/courses/${courseId}/topics/status`,
  );
  return {
    courseId: dto.course_id,
    topicsAreCurrent: dto.topics_are_current,
    topicCount: dto.topic_count,
    readyDocumentCount: dto.ready_document_count,
  };
}

export interface TopicExtraction {
  created: Topic[];
  reactivated: Topic[];
  deactivated: Topic[];
  unchanged: Topic[];
}

export async function extractTopics(courseId: string): Promise<TopicExtraction> {
  const dto = await apiRequest<{
    created: TopicDto[];
    reactivated: TopicDto[];
    deactivated: TopicDto[];
    unchanged: TopicDto[];
  }>(`/v1/courses/${courseId}/topics/extract`, { method: 'POST' });

  return {
    created: dto.created.map(toTopic),
    reactivated: dto.reactivated.map(toTopic),
    deactivated: dto.deactivated.map(toTopic),
    unchanged: dto.unchanged.map(toTopic),
  };
}

export interface GenerateQuizInput {
  mode: QuizMode;
  questionCount: number;
  topicIds?: string[];
  difficulty?: Difficulty | null;
  quizFormat?: QuizFormat;
}

export async function generateQuiz(
  courseId: string,
  input: GenerateQuizInput,
): Promise<Quiz> {
  const dto = await apiRequest<QuizDto>(`/v1/courses/${courseId}/quizzes`, {
    method: 'POST',
    body: {
      mode: input.mode,
      question_count: input.questionCount,
      topic_ids: input.topicIds ?? [],
      difficulty: input.difficulty ?? null,
    },
  });
  return toQuiz(dto);
}

export async function fetchQuizzes(courseId: string): Promise<Quiz[]> {
  const dtos = await apiRequest<QuizDto[]>(`/v1/courses/${courseId}/quizzes`);
  return dtos.map(toQuiz);
}

export async function fetchQuiz(quizId: string): Promise<Quiz> {
  return toQuiz(await apiRequest<QuizDto>(`/v1/quizzes/${quizId}`));
}

export async function startAttempt(quizId: string): Promise<Attempt> {
  return toAttempt(
    await apiRequest<AttemptDto>(`/v1/quizzes/${quizId}/attempts`, { method: 'POST' }),
  );
}

export async function submitAnswer(
  attemptId: string,
  questionId: string,
  selectedIndex: number,
  answeredInSeconds?: number,
): Promise<AnswerResult> {
  return toAnswerResult(
    await apiRequest<AnswerResultDto>(`/v1/attempts/${attemptId}/answers`, {
      method: 'POST',
      body: {
        question_id: questionId,
        selected_index: selectedIndex,
        ...(answeredInSeconds === undefined
          ? {}
          : { answered_in_seconds: answeredInSeconds }),
      },
    }),
  );
}

/**
 * Submit one written answer.
 *
 * Slower than `submitAnswer`: marking happens inline, because the student is
 * waiting for feedback and a queued verdict would mean showing them an answer
 * with no result attached.
 */
export async function submitShortAnswer(
  attemptId: string,
  questionId: string,
  responseText: string,
  answeredInSeconds?: number,
): Promise<AnswerResult> {
  return toAnswerResult(
    await apiRequest<AnswerResultDto>(`/v1/attempts/${attemptId}/short-answers`, {
      method: 'POST',
      body: {
        question_id: questionId,
        response_text: responseText,
        ...(answeredInSeconds === undefined
          ? {}
          : { answered_in_seconds: answeredInSeconds }),
      },
    }),
  );
}

export async function completeAttempt(attemptId: string): Promise<AttemptSummary> {
  const dto = await apiRequest<AttemptSummaryDto>(
    `/v1/attempts/${attemptId}/complete`,
    { method: 'POST' },
  );
  return {
    ...toAttempt(dto),
    quizTitle: dto.quiz_title,
    questionCount: dto.question_count,
    results: dto.results.map(toAnswerResult),
  };
}

export async function fetchMastery(courseId: string): Promise<CourseMastery> {
  const dto = await apiRequest<CourseMasteryDto>(`/v1/courses/${courseId}/mastery`);
  return {
    courseId: dto.course_id,
    topics: dto.topics.map(toMastery),
    overallMastery: dto.overall_mastery,
    topicsTotal: dto.topics_total,
    topicsStarted: dto.topics_started,
    topicsStrong: dto.topics_strong,
    questionsAnswered: dto.questions_answered,
    correctAnswers: dto.correct_answers,
    accuracy: dto.accuracy,
    strongestTopic: dto.strongest_topic,
    weakestTopic: dto.weakest_topic,
  };
}

export async function fetchRecommendations(courseId: string): Promise<Recommendation[]> {
  const dtos = await apiRequest<RecommendationDto[]>(
    `/v1/courses/${courseId}/recommendations`,
  );
  return dtos.map((dto) => ({
    kind: dto.kind,
    title: dto.title,
    detail: dto.detail,
    topicId: dto.topic_id,
    topicName: dto.topic_name,
  }));
}

export async function fetchAttempts(courseId: string): Promise<Attempt[]> {
  const dtos = await apiRequest<AttemptDto[]>(`/v1/courses/${courseId}/attempts`);
  return dtos.map(toAttempt);
}

export async function fetchFlashcards(courseId: string): Promise<Flashcard[]> {
  const dtos = await apiRequest<FlashcardDto[]>(`/v1/courses/${courseId}/flashcards`);
  return dtos.map(toFlashcard);
}

export interface GenerateFlashcardsInput {
  topicIds?: string[];
  weakTopicsOnly?: boolean;
}

export async function generateFlashcards(
  courseId: string,
  input: GenerateFlashcardsInput,
): Promise<Flashcard[]> {
  const dtos = await apiRequest<FlashcardDto[]>(`/v1/courses/${courseId}/flashcards`, {
    method: 'POST',
    body: {
      topic_ids: input.topicIds ?? [],
      weak_topics_only: input.weakTopicsOnly ?? false,
    },
  });
  return dtos.map(toFlashcard);
}
