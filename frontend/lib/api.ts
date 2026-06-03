// =============================================================================
// DevBrain AI — API Client
// =============================================================================
// All communication with the FastAPI backend goes through this file.
// Uses fetch() with typed responses. Token is stored in localStorage.
// SSE streaming for code review uses the native EventSource API.
// =============================================================================

import type {
  User,
  SkillProfile,
  GithubAnalyzeRequest,
  GithubAnalyzeResponse,
  Roadmap,
  GenerateRoadmapRequest,
  Challenge,
  ChallengeAttempt,
  SubmitChallengeResponse,
  CodeReview,
  SubmitCodeReviewRequest,
  Resource,
  ResourceSearchResponse,
  ProgressDashboard,
  StreakInfo,
  InterviewSession,
  StartInterviewRequest,
  SendInterviewMessageResponse,
  AuthLoginResponse,
  HealthResponse,
  RoadmapDifficulty,
} from "./types";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "devbrain_token";

// ---------------------------------------------------------------------------
// Token helpers
// ---------------------------------------------------------------------------

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

// ---------------------------------------------------------------------------
// Core request helper
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  options: { skipAuth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (!options.skipAuth) {
    const token = getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errJson = await response.json();
      detail = errJson?.detail ?? detail;
    } catch {
      // ignore parse error
    }

    // Auto-logout on expired / invalid token
    if (response.status === 401) {
      clearToken();
      if (typeof window !== "undefined") window.location.href = "/";
      throw new ApiError(401, "Session expired. Please log in again.");
    }

    throw new ApiError(response.status, detail);
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export async function checkHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("GET", "/health", undefined, {
    skipAuth: true,
  });
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** Returns the GitHub OAuth URL. Redirect the user there. */
export async function getLoginUrl(): Promise<AuthLoginResponse> {
  return apiRequest<AuthLoginResponse>("GET", "/auth/login", undefined, {
    skipAuth: true,
  });
}

/** Fetch the current authenticated user. */
export async function getCurrentUser(): Promise<User> {
  return apiRequest<User>("GET", "/auth/me");
}

// ---------------------------------------------------------------------------
// Response Mappers / Transformers
// ---------------------------------------------------------------------------

function transformSkillProfile(p: any): any {
  if (!p) return null;
  const skillsPercent: Record<string, number> = {};
  for (const [lang, score] of Object.entries(p.skills ?? {})) {
    skillsPercent[lang] = Math.round((score as number) * 100);
  }
  const topLangs = Object.keys(skillsPercent).sort((a, b) => skillsPercent[b] - skillsPercent[a]);
  
  return {
    id: p.user_id,
    user_id: p.user_id,
    skills: skillsPercent,
    top_languages: topLangs,
    total_repos: p.repo_count ?? 0,
    summary: p.summary ?? "",
    last_analyzed_at: p.analyzed_at,
    created_at: p.analyzed_at,
    updated_at: p.analyzed_at,
  };
}

function transformRoadmap(r: any): any {
  if (!r) return null;
  return {
    ...r,
    weeks: r.plan?.weeks ?? []
  };
}

// ---------------------------------------------------------------------------
// GitHub / Skill Analysis
// ---------------------------------------------------------------------------

/** Kick off repo analysis. Pass `github_token` if user provided a PAT. */
export async function analyzeGithub(
  opts?: GithubAnalyzeRequest | string,
): Promise<any> {
  const body: GithubAnalyzeRequest =
    typeof opts === "string" ? { github_token: opts } : (opts ?? {});
  const res = await apiRequest<any>("POST", "/github/analyze", body);
  return transformSkillProfile(res);
}

/** Retrieve the latest computed skill profile. */
export async function getSkillProfile(): Promise<any> {
  const res = await apiRequest<any>("GET", "/github/profile");
  return transformSkillProfile(res);
}

// ---------------------------------------------------------------------------
// Roadmap
// ---------------------------------------------------------------------------

/** Generate (or regenerate) a weekly learning roadmap for the given role. */
export async function generateRoadmap(
  target_role: string,
): Promise<any> {
  const body: GenerateRoadmapRequest = { target_role };
  const res = await apiRequest<any>("POST", "/roadmap/generate", body);
  return transformRoadmap(res);
}

/** Fetch the currently active roadmap. */
export async function getCurrentRoadmap(): Promise<any> {
  const res = await apiRequest<any>("GET", "/roadmap/current");
  return transformRoadmap(res);
}

export { getCurrentRoadmap as getRoadmap };

/** Partially update a roadmap's plan JSON. */
export async function patchRoadmap(
  roadmap_id: string,
  plan: any
): Promise<any> {
  const res = await apiRequest<any>("PATCH", `/roadmap/${roadmap_id}`, { plan });
  return transformRoadmap(res);
}

// ---------------------------------------------------------------------------
// Challenges
// ---------------------------------------------------------------------------

/** Ask the backend to generate a new challenge targeting weak areas. */
export async function generateChallenge(): Promise<Challenge> {
  return apiRequest<Challenge>("POST", "/challenges/generate");
}

/** Submit a solution for a specific challenge. */
export async function submitChallenge(
  id: string,
  code: string,
  language: string,
  mcq_answers: number[] = [],
): Promise<any> {
  const res = await apiRequest<any>(
    "POST",
    `/challenges/${id}/submit`,
    { code, language, mcq_answers },
  );
  const testsTotal = res.tests_total || 1;
  const testsPassed = res.tests_passed || 0;
  
  // Blended score: 50% code + 50% MCQs
  const codeScore = (testsPassed / testsTotal) * 50;
  const mcqScore = (res.mcqs_passed / 3) * 50;
  const score = Math.round(codeScore + mcqScore);

  return {
    passed: res.passed,
    score,
    feedback: res.feedback,
    output: res.output,
    error: res.error,
    mcqs_passed: res.mcqs_passed,
  };
}

/** Get the user's challenge attempt history. */
export async function getChallengeHistory(): Promise<any[]> {
  const items = await apiRequest<any[]>("GET", "/challenges/history");
  if (!items) return [];
  return items.map(item => {
    // Blended score: 50% code + 50% MCQs
    const codeScore = (item.tests_passed / (item.tests_total || 1)) * 50;
    const mcqScore = (item.mcqs_passed / 3) * 50;
    const score = Math.round(codeScore + mcqScore);

    return {
      id: item.attempt_id,
      title: item.challenge_title,
      language: item.language || "python",
      passed: item.passed,
      score: score,
      created_at: item.submitted_at
    };
  });
}

/** Get full details of a specific past attempt. */
export async function getAttemptDetails(attemptId: string): Promise<any> {
  return await apiRequest<any>("GET", `/challenges/attempts/${attemptId}`);
}

// ---------------------------------------------------------------------------
// Code Review
// ---------------------------------------------------------------------------

/** Submit code for a full AI review (non-streaming). */
export async function submitCodeReview(
  code: string,
  language: string,
  context?: string,
): Promise<any> {
  const body: SubmitCodeReviewRequest = { code, language, context };
  const res = await apiRequest<any>("POST", "/code-reviewer/review", body);
  return res;
}

/** Open an SSE stream for real-time code review tokens. */
export function streamCodeReview(
  code: string,
  language: string,
  onChunk: (token: string) => void,
  onComplete?: () => void,
  onError?: (err: Event) => void,
): () => void {
  const token = getToken();
  const params = new URLSearchParams({ code, language });
  if (token) params.set("token", token);

  const url = `${BASE_URL}/code-reviewer/stream?${params.toString()}`;
  const es = new EventSource(url);

  es.onmessage = (event: MessageEvent) => {
    if (event.data === "[REVIEW_DONE]") {
      es.close();
      onComplete?.();
      return;
    }
    if (event.data.startsWith("[REVIEW_ERROR]")) {
      es.close();
      onError?.(new Event("error"));
      return;
    }
    // Unescape the \n we encoded server-side
    const chunk = event.data.replace(/\\n/g, "\n");
    onChunk(chunk);
  };

  es.onerror = (err: Event) => {
    es.close();
    onError?.(err);
  };

  return () => es.close();
}

/** Get code review history for the current user. */
export async function getReviewHistory(): Promise<any[]> {
  const items = await apiRequest<any[]>("GET", "/review/history");
  if (!items) return [];
  return items.map(item => ({
    id: item.review_id,
    language: item.language,
    score: item.score,
    summary: item.summary,
    code_preview: item.code_preview,
    reflection_loops: item.reflection_loops,
    created_at: item.created_at
  }));
}

// ---------------------------------------------------------------------------
// Resources
// ---------------------------------------------------------------------------

/** Search for learning resources. */
export async function searchResources(
  topic: string,
  difficulty?: RoadmapDifficulty,
): Promise<ResourceSearchResponse> {
  const params = new URLSearchParams({ topic });
  if (difficulty) params.set("difficulty", difficulty);
  return apiRequest<ResourceSearchResponse>(
    "GET",
    `/resources/search?${params.toString()}`,
  );
}

// ---------------------------------------------------------------------------
// Interview
// ---------------------------------------------------------------------------

/** Start a new interview session. */
export async function startInterview(
  mode: "dsa" | "resume",
  resumeFile?: File | null
): Promise<any> {
  const formData = new FormData();
  formData.append("mode", mode);
  if (resumeFile) {
    formData.append("resumeFile", resumeFile);
  }

  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${BASE_URL}/interview/start`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!response.ok) {
    throw new ApiError(response.status, "Failed to start interview");
  }
  
  const res = await response.json();
  if (!res) return null;
  return {
    ...res,
    id: res.session_id,
    opening_message: res.first_question
  };
}

/** Send a message in an existing interview session. */
export async function sendInterviewMessage(
  session_id: string,
  message: string,
): Promise<any> {
  return apiRequest<any>(
    "POST",
    `/interview/${session_id}/message`,
    { message },
  );
}

/** Get interview history. */
export async function getInterviewHistory(): Promise<any[]> {
  const items = await apiRequest<any[]>("GET", "/interview/history");
  if (!items) return [];
  return items;
}

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------

/** Get the full progress dashboard data. */
export async function getProgressDashboard(): Promise<any> {
  const res = await apiRequest<any>("GET", "/progress/dashboard");
  if (!res) return null;

  const delta7d: Record<string, number> = {};
  for (const [k, v] of Object.entries(res.skill_delta_7d ?? {})) {
    delta7d[k] = Math.round((v as number) * 100);
  }
  const delta30d: Record<string, number> = {};
  for (const [k, v] of Object.entries(res.skill_delta_30d ?? {})) {
    delta30d[k] = Math.round((v as number) * 100);
  }

  const skillDeltasMapped = (res.skill_deltas ?? []).map((d: any) => ({
    skill: d.skill,
    delta_7d: Math.round(d.delta_7d * 100),
    delta_30d: Math.round(d.delta_30d * 100),
    current_score: Math.round(d.current_score * 100),
  }));

  return {
    ...res,
    skill_profile: transformSkillProfile(res.skill_profile),
    skill_delta_7d: delta7d,
    skill_delta_30d: delta30d,
    skill_deltas: skillDeltasMapped,
    recent_activity: [
      `Completed challenges with ${Math.round(res.challenge_pass_rate * 100)}% pass rate`,
      `Active streak is currently ${res.streak?.current_streak ?? 0} day(s)`
    ]
  };
}

/** Get only streak information (lightweight). */
export async function getStreak(): Promise<StreakInfo> {
  return apiRequest<StreakInfo>("GET", "/progress/streak");
}