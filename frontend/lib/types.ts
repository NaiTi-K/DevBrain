// =============================================================================
// DevBrain AI — Frontend Type Definitions
// =============================================================================
// These interfaces mirror the backend Pydantic schemas / SQLAlchemy models.
// Every API response that flows through lib/api.ts is typed here.
// Part 5B pages import directly from this file.
// =============================================================================

// ---------------------------------------------------------------------------
// Auth / User
// ---------------------------------------------------------------------------

export interface User {
  id: string; // UUID
  github_id: string;
  username: string;
  email: string | null;
  avatar_url: string | null;
  name: string | null;
  created_at: string; // ISO datetime
  updated_at: string;
}

// ---------------------------------------------------------------------------
// GitHub / Skill Profile
// ---------------------------------------------------------------------------

export interface SkillProfile {
  id: string;
  user_id: string;
  skills: Record<string, number>; // e.g. { "Python": 82, "TypeScript": 45 } (0–100)
  skill_delta_7d?: Record<string, number>;
  top_languages?: string[];
  total_repos?: number;
  summary?: string;
  last_analyzed_at?: string;
  repositories_analyzed?: number;
  total_commits: number;
  primary_languages: string[];
  frameworks_detected: string[];
  weak_areas: string[];
  strong_areas: string[];
  created_at: string;
  updated_at: string;
}

export interface GithubAnalyzeRequest {
  github_token?: string;
}

export interface GithubAnalyzeResponse {
  status: "started" | "completed" | "error";
  message: string;
  profile?: SkillProfile;
}

// ---------------------------------------------------------------------------
// Roadmap
// ---------------------------------------------------------------------------

export type RoadmapItemStatus = "pending" | "in_progress" | "completed" | "skipped";
export type RoadmapDifficulty = "beginner" | "intermediate" | "advanced";

export interface RoadmapItem {
  id: string;
  title: string;
  description: string;
  topic: string;
  difficulty: RoadmapDifficulty;
  estimated_hours: number;
  status: RoadmapItemStatus;
  resources: string[];
  week_number: number;
  day_number: number;
}

export interface Roadmap {
  id: string;
  user_id: string;
  target_role: string;
  current_week: number;
  total_weeks: number;
  items: RoadmapItem[];
  weeks?: any[];
  focus_areas: string[];
  generated_at: string;
  updated_at: string;
  plan: any;
}

export interface GenerateRoadmapRequest {
  target_role: string;
}

// ---------------------------------------------------------------------------
// Challenges
// ---------------------------------------------------------------------------

export type ChallengeDifficulty = "easy" | "medium" | "hard";
export type ChallengeStatus = "unsolved" | "attempted" | "solved";
export type SubmissionResult = "accepted" | "wrong_answer" | "error" | "timeout";

export interface TestCase {
  input: string;
  expected_output: string;
  explanation?: string;
}

export interface MCQ {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

export interface Challenge {
  id: string;
  user_id: string;
  title: string;
  description: string;
  difficulty: ChallengeDifficulty;
  topic: string;
  language: string;
  starter_code: string;
  starter_codes?: Record<string, string>;
  constraints?: string[];
  examples?: any[];
  test_cases: any[];
  mcqs: MCQ[];
  hints: string[];
  solution_explanation?: string;
  status: ChallengeStatus;
  target_skill: string;
  created_at: string;
  updated_at: string;
}

export interface ChallengeAttempt {
  id: string;
  challenge_id: string;
  user_id: string;
  submitted_code: string;
  result: SubmissionResult;
  test_cases_passed: number;
  test_cases_total: number;
  mcqs_passed: number;
  execution_time_ms: number | null;
  feedback: string;
  score: number; // 0–1
  submitted_at: string;
}

export interface SubmitChallengeRequest {
  code: string;
  mcq_answers: number[];
}

export interface SubmitChallengeResponse {
  attempt: ChallengeAttempt;
  skill_updated: boolean;
  delta: number;
}

// ---------------------------------------------------------------------------
// Code Review
// ---------------------------------------------------------------------------

export type ReviewQuality = "poor" | "fair" | "good" | "excellent";

export interface ReviewIssue {
  line: number | null;
  severity: "error" | "warning" | "suggestion";
  message: string;
  category: string; // e.g. "performance", "security", "style"
}

export interface CodeReview {
  id?: string;
  user_id?: string;
  code: string;
  language: string;
  context?: string | null;
  score: number;
  annotations: ReviewIssue[];
  complexity?: { time: string; space: string };
  edge_cases: string[];
  improvements: {
    title: string;
    description: string;
    code_after?: string;
    verification?: {
      verified: boolean;
      badge: string;
      message: string;
      speedup?: number;
    };
  }[];
  best_practices: string[];
  summary: string;
  ast_facts?: any;
  lint_facts?: any;
  time_complexity?: string;
  space_complexity?: string;
  reflection_loops?: number;
}

export interface SubmitCodeReviewRequest {
  code: string;
  language: string;
  context?: string;
}

// ---------------------------------------------------------------------------
// Resources
// ---------------------------------------------------------------------------

export type ResourceType = "article" | "video" | "course" | "book" | "tool" | "documentation";

export interface Resource {
  id: string;
  title: string;
  url: string;
  description: string;
  type: ResourceType;
  topic: string;
  difficulty: RoadmapDifficulty;
  estimated_minutes: number | null;
  tags: string[];
  source: "rag" | "web_search";
  relevance_score: number; // 0–1
  why_recommended?: string;
}

export interface ResourceSearchResponse {
  resources: Resource[];
  total: number;
  topic: string;
  difficulty: RoadmapDifficulty | null;
  learning_path?: string;
}

// ---------------------------------------------------------------------------
// Interview
// ---------------------------------------------------------------------------

export type InterviewMode = "dsa" | "system_design";
export type InterviewStatus = "active" | "completed" | "abandoned";

export interface InterviewMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export interface InterviewSession {
  id: string;
  user_id: string;
  mode: InterviewMode;
  status: InterviewStatus;
  messages: InterviewMessage[];
  topic: string | null;
  difficulty: RoadmapDifficulty | null;
  score: number | null; // 0–1, filled when completed
  feedback: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface StartInterviewRequest {
  mode: InterviewMode;
}

export interface SendInterviewMessageRequest {
  message: string;
}

export interface SendInterviewMessageResponse {
  message: InterviewMessage;
  session_complete: boolean;
  score?: number;
  feedback?: string;
}

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------

export interface StreakInfo {
  current_streak: number;
  longest_streak: number;
  last_activity_date: string | null;
}

export interface SkillDelta {
  skill: string;
  delta_7d: number;
  delta_30d: number;
  current_score: number;
}

export interface DailyActivity {
  date: string; // ISO date "YYYY-MM-DD"
  challenges_solved: number;
  reviews_submitted: number;
  interview_sessions: number;
  total_activity: number;
}

export interface RoadmapTracker {
  id: string;
  target_role: string;
  total_weeks: number;
  completed_weeks: number;
  percent_completed: number;
  total_topics: number;
  completed_topics: number;
}

export interface TrendPoint {
  date: string;
  score: number;
}

export interface ProgressDashboard {
  user: User;
  streak: StreakInfo;
  skill_profile: SkillProfile | null;
  skill_deltas: SkillDelta[];
  total_challenges_solved: number;
  total_reviews_submitted: number;
  total_interview_sessions: number;
  exam_readiness_score: number; // 0–1
  top_improvements: string[];
  focus_recommendations: string[];
  daily_activity: DailyActivity[]; // last 30 days
  recent_activity?: any[];
  weekly_challenge_goal: number;
  weekly_challenges_done: number;
  roadmap_tracker?: RoadmapTracker | null;
  exam_readiness?: Record<string, number>;
  weekly_digest?: string;
  trend_data?: TrendPoint[];
}

// ---------------------------------------------------------------------------
// Generic API types
// ---------------------------------------------------------------------------

export interface ApiError {
  detail: string;
  status_code?: number;
}

export interface AuthLoginResponse {
  auth_url: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  services: Record<string, "ok" | "error">;
}