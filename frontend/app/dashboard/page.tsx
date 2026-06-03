"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import {
  getSkillProfile,
  analyzeGithub,
  generateRoadmap,
  getProgressDashboard,
} from "@/lib/api";
import type { SkillProfile, ProgressDashboard } from "@/lib/types";

const SkillRadarChart = dynamic(
  () => import("@/components/SkillRadarChart"),
  { ssr: false }
);

const TARGET_ROLES = [
  "Frontend Engineer",
  "Backend Engineer",
  "Full Stack Engineer",
  "DevOps / Platform Engineer",
  "ML / AI Engineer",
  "Data Engineer",
  "Mobile Engineer",
  "Security Engineer",
];

function StatCard({
  icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: string;
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex items-start gap-4">
      <div
        className="text-2xl w-10 h-10 flex items-center justify-center rounded-lg flex-shrink-0"
        style={{ background: accent ? `${accent}22` : "#6366f122" }}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-gray-400 text-xs uppercase tracking-widest font-medium mb-1">
          {label}
        </p>
        <p className="text-white text-xl font-bold leading-none">{value}</p>
        {sub && <p className="text-gray-500 text-xs mt-1">{sub}</p>}
      </div>
    </div>
  );
}

function SkillLevelBadge({ level }: { level: string }) {
  const map: Record<string, { color: string; bg: string }> = {
    beginner: { color: "#f59e0b", bg: "#f59e0b22" },
    intermediate: { color: "#6366f1", bg: "#6366f122" },
    advanced: { color: "#22c55e", bg: "#22c55e22" },
  };
  const s = map[level.toLowerCase()] ?? map.intermediate;
  return (
    <span
      className="text-xs font-semibold px-2.5 py-1 rounded-full capitalize"
      style={{ color: s.color, background: s.bg }}
    >
      {level}
    </span>
  );
}

function MarkdownRenderer({ content }: { content: string }) {
  const normalized = (content ?? "").replace(/\\n/g, "\n");
  const parts = normalized.split(/(```[\s\S]*?```)/g);

  const renderLineContent = (text: string) => {
    const boldParts = text.split(/(\*\*.*?\*\*)/g);
    return boldParts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={i} className="font-bold text-white bg-white/5 px-1 py-0.5 rounded border border-white/10 font-sans text-xs mx-0.5 shadow-[0_0_8px_rgba(255,255,255,0.05)]">
            {part.slice(2, -2)}
          </strong>
        );
      }
      return part;
    });
  };

  return (
    <div className="space-y-4 text-gray-300 text-sm leading-relaxed">
      {parts.map((part, i) => {
        if (part.startsWith("```")) {
          const lines = part.split("\n");
          const firstLine = lines[0] || "```";
          const lang = firstLine.replace("```", "").trim();
          const codeContent = lines.slice(1, -1).join("\n");
          
          return (
            <div key={i} className="my-3">
              {lang && (
                <div className="text-xs text-gray-500 font-mono mb-1 uppercase tracking-wider">
                  {lang}
                </div>
              )}
              <pre className="bg-[#0f1117] border border-[#2d3148] rounded-xl p-4 overflow-x-auto font-mono text-xs text-gray-300">
                <code>{codeContent}</code>
              </pre>
            </div>
          );
        } else {
          const lines = part.split("\n");
          return (
            <div key={i} className="space-y-2.5">
              {lines.map((line, j) => {
                const trimmed = line.trim();
                if (!trimmed) return <div key={j} className="h-2" />;
                
                if (trimmed.startsWith("### ")) {
                  return (
                    <h3 key={j} className="text-base font-bold text-white mt-6 mb-3 border-l-4 border-[#6366f1] pl-3">
                      {trimmed.replace("### ", "")}
                    </h3>
                  );
                }
                if (trimmed.startsWith("#### ")) {
                  return (
                    <h4 key={j} className="text-sm font-semibold text-[#818cf8] mt-4 mb-2 uppercase tracking-wider flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#6366f1]" />
                      {trimmed.replace("#### ", "")}
                    </h4>
                  );
                }
                if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
                  const contentText = trimmed.substring(2);
                  let isCritical = contentText.includes("[CRITICAL]") || contentText.includes("CRITICAL");
                  let isHigh = contentText.includes("[HIGH]") || contentText.includes("HIGH");
                  
                  return (
                    <div key={j} className={`flex gap-2 text-sm ml-4 py-1.5 px-3 rounded-lg ${isCritical ? 'bg-red-500/5 border border-red-500/10 text-red-200' : isHigh ? 'bg-amber-500/5 border border-amber-500/10 text-amber-200' : 'text-gray-300'}`}>
                      <span className={isCritical ? 'text-red-400 font-bold shrink-0' : isHigh ? 'text-amber-400 font-bold shrink-0' : 'text-[#6366f1] shrink-0'}>•</span>
                      <span className="flex-1">{renderLineContent(contentText)}</span>
                    </div>
                  );
                }
                
                return <p key={j} className="text-sm text-gray-300 leading-relaxed">{renderLineContent(trimmed)}</p>;
              })}
            </div>
          );
        }
      })}
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<SkillProfile | null>(null);
  const [dashboard, setDashboard] = useState<ProgressDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [githubToken, setGithubToken] = useState("");
  const [targetRole, setTargetRole] = useState(TARGET_ROLES[2]);
  const [generatingRoadmap, setGeneratingRoadmap] = useState(false);
  const [showReanalyze, setShowReanalyze] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("devbrain_token");
    if (!token) {
      router.push("/");
      return;
    }
    Promise.all([
      getSkillProfile().catch(() => null),
      getProgressDashboard().catch(() => null),
    ]).then(([p, d]) => {
      setProfile(p);
      setDashboard(d);
      setLoading(false);
    });
  }, [router]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError("");
    try {
      const token = githubToken.trim();
      const useToken =
        token.startsWith("ghp_") || token.startsWith("github_pat_");
      const p = await analyzeGithub(
        useToken ? { github_token: token } : undefined,
      );
      setProfile(p);
      setShowReanalyze(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleGenerateRoadmap = async () => {
    setGeneratingRoadmap(true);
    try {
      await generateRoadmap(targetRole);
      router.push("/roadmap");
    } catch {
      setGeneratingRoadmap(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-2 border-[#6366f1] border-t-transparent rounded-full animate-spin" />
          <p className="text-gray-400 text-sm">Loading your profile…</p>
        </div>
      </div>
    );
  }

  const skills = profile?.skills ?? {};
  const topLang =
    profile?.top_languages?.[0] ?? "—";
  const repoCount = profile?.total_repos ?? 0;
  const streak = dashboard?.streak?.current_streak ?? 0;

  const avgSkill =
    Object.keys(skills).length > 0
      ? Object.values(skills).reduce((a, b) => a + b, 0) /
        Object.keys(skills).length
      : 0;
  const skillLevel =
    avgSkill >= 75 ? "advanced" : avgSkill >= 45 ? "intermediate" : "beginner";

  const lastAnalyzed = profile?.last_analyzed_at ?? profile?.updated_at;
  const lastAnalyzedLabel = lastAnalyzed
    ? new Date(lastAnalyzed).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : null;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Developer Dashboard
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            Your AI-powered growth command center
          </p>
        </div>
        {profile && (
          <div className="flex items-center gap-3 flex-wrap justify-end">
            {lastAnalyzedLabel && (
              <span className="text-gray-500 text-xs">
                Last analyzed {lastAnalyzedLabel}
              </span>
            )}
            <button
              onClick={() => setShowReanalyze((v) => !v)}
              disabled={analyzing}
              className="px-4 py-2 bg-[#1a1d2e] border border-[#2d3148] hover:border-[#6366f1] text-gray-300 hover:text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
            >
              {analyzing ? "Analyzing…" : showReanalyze ? "Cancel" : "Re-analyze GitHub"}
            </button>
            <label className="text-gray-400 text-sm">Target Role:</label>
            <select
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              className="bg-[#1a1d2e] border border-[#2d3148] text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-[#6366f1]"
            >
              {TARGET_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <button
              onClick={handleGenerateRoadmap}
              disabled={generatingRoadmap}
              className="px-4 py-2 bg-[#6366f1] hover:bg-[#5558e3] text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
            >
              {generatingRoadmap ? "Generating…" : "Generate Roadmap →"}
            </button>
          </div>
        )}
      </div>

      {profile && showReanalyze && (
        <div className="bg-[#1a1d2e] border border-[#6366f1]/40 rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
          <h2 className="text-white font-semibold mb-1">Re-analyze GitHub</h2>
          <p className="text-gray-400 text-sm mb-4">
            Refresh your skill profile from your latest repos. Add a token for
            deeper signals (manifests, commits, CI/CD).
          </p>
          <div className="flex flex-col sm:flex-row gap-3">
            <input
              type="password"
              placeholder="ghp_… (optional, recommended)"
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
              className="flex-1 bg-[#0f1117] border border-[#2d3148] text-white text-sm rounded-lg px-4 py-2.5 focus:outline-none focus:border-[#6366f1] placeholder-gray-600"
            />
            <button
              onClick={handleAnalyze}
              disabled={analyzing}
              className="px-6 py-2.5 bg-[#6366f1] hover:bg-[#5558e3] text-white text-sm font-semibold rounded-lg transition-colors disabled:opacity-50 whitespace-nowrap"
            >
              {analyzing ? "Analyzing repositories…" : "Run analysis →"}
            </button>
          </div>
          {error && (
            <p className="text-[#ef4444] text-sm bg-[#ef444411] rounded-lg px-4 py-2.5 mt-3">
              {error}
            </p>
          )}
        </div>
      )}

      {!profile ? (
        /* ── Onboarding card ── */
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-8 shadow-[0_0_15px_rgba(99,102,241,0.1)] max-w-xl">
          <div className="w-14 h-14 bg-[#6366f122] rounded-2xl flex items-center justify-center text-3xl mb-6">
            🔍
          </div>
          <h2 className="text-white text-xl font-bold mb-2">
            Analyze Your GitHub
          </h2>
          <p className="text-gray-400 text-sm mb-6 leading-relaxed">
            Connect your GitHub account so DevBrain can build a real skill
            profile from your actual code — not a quiz.
          </p>
          <div className="space-y-4">
            <div>
              <label className="text-gray-400 text-xs uppercase tracking-widest mb-2 block">
                GitHub Token{" "}
                <span className="text-gray-600 normal-case">(optional)</span>
              </label>
              <input
                type="password"
                placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                className="w-full bg-[#0f1117] border border-[#2d3148] text-white text-sm rounded-lg px-4 py-2.5 focus:outline-none focus:border-[#6366f1] placeholder-gray-600"
              />
              <p className="text-gray-600 text-xs mt-1.5">
                Provide a token to analyze private repositories.
              </p>
            </div>
            {error && (
              <p className="text-[#ef4444] text-sm bg-[#ef444411] rounded-lg px-4 py-2.5">
                {error}
              </p>
            )}
            <button
              onClick={handleAnalyze}
              disabled={analyzing}
              className="w-full py-3 bg-[#6366f1] hover:bg-[#5558e3] text-white font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {analyzing ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Analyzing repositories…
                </>
              ) : (
                "Analyze My GitHub →"
              )}
            </button>
          </div>
        </div>
      ) : (
        <>
        {/* ── Main dashboard layout ── */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Left: Radar Chart */}
          <div className="lg:col-span-2 bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
            <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#6366f1] inline-block" />
              Skill Profile
            </h2>
            <SkillRadarChart
              skills={skills}
              delta={dashboard?.skill_deltas?.reduce((acc, curr) => {
                acc[curr.skill] = curr.delta_7d;
                return acc;
              }, {} as Record<string, number>)}
            />
            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="text-gray-400">Overall Level</span>
              <SkillLevelBadge level={skillLevel} />
            </div>
          </div>

          {/* Right: Stats + Activity */}
          <div className="lg:col-span-3 space-y-6">
            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-4">
              <StatCard
                icon="📦"
                label="Repositories"
                value={repoCount}
                sub="analyzed from GitHub"
              />
              <StatCard
                icon="💻"
                label="Top Language"
                value={topLang}
                sub={`${profile.top_languages?.slice(0, 3).join(", ") ?? "—"}`}
                accent="#22c55e"
              />
              <StatCard
                icon="🔥"
                label="Current Streak"
                value={`${streak}d`}
                sub="consecutive active days"
                accent="#f59e0b"
              />
              <StatCard
                icon="⚡"
                label="Avg Skill Score"
                value={`${avgSkill.toFixed(0)} / 100`}
                sub={skillLevel}
                accent="#6366f1"
              />
            </div>

            {/* Top skills breakdown */}
            <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
              <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[#22c55e] inline-block" />
                Skill Breakdown
              </h2>
              <div className="space-y-3">
                {Object.entries(skills)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 6)
                  .map(([skill, score]) => (
                    <div key={skill}>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-gray-300 capitalize">
                          {skill}
                        </span>
                        <span className="text-gray-400">{score}/100</span>
                      </div>
                      <div className="h-1.5 bg-[#0f1117] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-700"
                          style={{
                            width: `${score}%`,
                            background:
                              score >= 75
                                ? "#22c55e"
                                : score >= 45
                                ? "#6366f1"
                                : "#f59e0b",
                          }}
                        />
                      </div>
                    </div>
                  ))}
              </div>
            </div>

            {/* Recent activity */}
            {dashboard?.recent_activity && dashboard.recent_activity.length > 0 && (
              <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
                <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#f59e0b] inline-block" />
                  Recent Activity
                </h2>
                <ul className="space-y-2">
                  {dashboard.recent_activity.slice(0, 5).map((a, i) => (
                    <li
                      key={i}
                      className="flex items-center gap-3 text-sm text-gray-400"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-[#2d3148] flex-shrink-0" />
                      {typeof a === "string" ? a : JSON.stringify(a)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>

        {profile.summary && (
          <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
            <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#6366f1] inline-block" />
              GitHub Analysis
            </h2>
            <div className="text-gray-300 text-sm leading-relaxed">
              <MarkdownRenderer content={profile.summary} />
            </div>
          </div>
        )}
        </>
      )}
    </div>
  );
}