"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { getProgressDashboard, getInterviewHistory } from "@/lib/api";
import type { ProgressDashboard } from "@/lib/types";

const SkillRadarChart = dynamic(
  () => import("@/components/SkillRadarChart"),
  { ssr: false }
);
const ProgressHeatmap = dynamic(
  () => import("@/components/ProgressHeatmap"),
  { ssr: false }
);

function MarkdownRenderer({ content }: { content: string }) {
  const renderLineContent = (text: string) => {
    const parts = text.split(/(\*\*.*?\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={i} className="font-bold text-white bg-[#6366f1]/10 px-1.5 py-0.5 rounded border border-[#6366f1]/30 font-sans text-xs mx-0.5 shadow-[0_0_8px_rgba(99,102,241,0.2)]">
            {part.slice(2, -2)}
          </strong>
        );
      }
      return part;
    });
  };

  // Safe check and parsing
  const normalized = (content ?? "").replace(/\\n/g, "\n");
  const sections: { title: string; items: string[] }[] = [];
  let currentSection: { title: string; items: string[] } | null = null;

  const lines = normalized.split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    if (trimmed.startsWith("#### ") || trimmed.startsWith("### ")) {
      if (currentSection) {
        sections.push(currentSection);
      }
      currentSection = {
        title: trimmed.replace(/^#+\s+/, ""),
        items: [],
      };
    } else if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      if (currentSection) {
        currentSection.items.push(trimmed.substring(2).trim());
      } else {
        currentSection = {
          title: "Overview",
          items: [trimmed.substring(2).trim()],
        };
      }
    } else {
      if (currentSection) {
        currentSection.items.push(trimmed);
      } else {
        currentSection = {
          title: "Overview",
          items: [trimmed],
        };
      }
    }
  }
  if (currentSection) {
    sections.push(currentSection);
  }

  const getSectionConfig = (title: string) => {
    const t = title.toLowerCase();
    if (t.includes("win") || t.includes("progress")) {
      return {
        icon: "🏆",
        bg: "from-emerald-500/5 to-transparent",
        border: "border-t-emerald-500/40 hover:border-emerald-500/60",
        bullet: "text-emerald-400",
        titleColor: "text-emerald-400",
      };
    }
    if (t.includes("improve") || t.includes("attention")) {
      return {
        icon: "⚠️",
        bg: "from-amber-500/5 to-transparent",
        border: "border-t-amber-500/40 hover:border-amber-500/60",
        bullet: "text-amber-400",
        titleColor: "text-amber-400",
      };
    }
    return {
      icon: "🚀",
      bg: "from-indigo-500/5 to-transparent",
      border: "border-t-indigo-500/40 hover:border-indigo-500/60",
      bullet: "text-indigo-400",
      titleColor: "text-indigo-400",
    };
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4 w-full">
      {sections.map((section, idx) => {
        const config = getSectionConfig(section.title);
        return (
          <div
            key={idx}
            className={`bg-[#1a1d2e]/60 border border-[#2d3148] border-t-2 ${config.border} bg-gradient-to-b ${config.bg} rounded-xl p-5 shadow-[0_0_20px_rgba(99,102,241,0.03)] hover:shadow-[0_0_25px_rgba(99,102,241,0.06)] hover:bg-[#1a1d2e]/80 transition-all duration-300 flex flex-col justify-between`}
          >
            <div>
              <h4 className={`text-xs font-extrabold uppercase tracking-wider flex items-center gap-2 mb-4 ${config.titleColor}`}>
                <span className="text-base">{config.icon}</span>
                {section.title}
              </h4>
              <ul className="space-y-3">
                {section.items.map((item, itemIdx) => (
                  <li key={itemIdx} className="flex gap-2 text-sm text-gray-300 leading-relaxed items-start">
                    <span className={`text-base font-bold shrink-0 leading-none select-none ${config.bullet}`}>•</span>
                    <span className="flex-1">{renderLineContent(item)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CircularProgress({
  pct,
  label,
  sub,
}: {
  pct: number;
  label: string;
  sub: string;
}) {
  const r = 36;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;

  return (
    <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex flex-col items-center gap-2">
      <svg width="90" height="90" viewBox="0 0 90 90">
        <circle
          cx="45"
          cy="45"
          r={r}
          fill="none"
          stroke="#2d3148"
          strokeWidth="7"
        />
        <circle
          cx="45"
          cy="45"
          r={r}
          fill="none"
          stroke="#6366f1"
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ - dash}`}
          transform="rotate(-90 45 45)"
          style={{ transition: "stroke-dasharray 0.8s ease" }}
        />
        <text
          x="45"
          y="50"
          textAnchor="middle"
          fill="white"
          fontSize="16"
          fontWeight="700"
        >
          {pct}%
        </text>
      </svg>
      <p className="text-white font-semibold text-sm text-center">{label}</p>
      <p className="text-gray-400 text-xs text-center">{sub}</p>
    </div>
  );
}

function DeltaBadge({ delta }: { delta: number }) {
  const pos = delta > 0;
  return (
    <span
      className="text-xs font-bold px-1.5 py-0.5 rounded-full"
      style={{
        background: pos ? "#22c55e22" : "#ef444422",
        color: pos ? "#22c55e" : "#ef4444",
      }}
    >
      {pos ? "+" : ""}
      {delta.toFixed(1)}
    </span>
  );
}

const CustomTooltip = ({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}) => {
  if (active && payload?.length) {
    return (
      <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-lg px-3 py-2">
        <p className="text-gray-400 text-xs">{label}</p>
        <p className="text-white font-semibold text-sm">
          Score: {payload[0].value.toFixed(1)}
        </p>
      </div>
    );
  }
  return null;
};

export default function ProgressPage() {
  const router = useRouter();
  const [dashboard, setDashboard] = useState<ProgressDashboard | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!localStorage.getItem("devbrain_token")) {
      router.push("/");
      return;
    }
    Promise.all([
      getProgressDashboard().then(setDashboard).catch(() => setDashboard(null)),
      getInterviewHistory().then(setHistory).catch(() => setHistory([]))
    ]).finally(() => setLoading(false));
  }, [router]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="w-10 h-10 border-2 border-[#6366f1] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="max-w-lg mx-auto mt-24 text-center px-4">
        <div className="text-5xl mb-4">📊</div>
        <h2 className="text-white text-xl font-bold mb-2">
          No progress data yet
        </h2>
        <p className="text-gray-400 text-sm">
          Complete challenges and code reviews to see your progress here.
        </p>
      </div>
    );
  }

  const streak = dashboard.streak?.current_streak ?? 0;
  const passRate = Math.round(((dashboard.total_challenges_solved / Math.max(1, dashboard.total_challenges_solved + dashboard.total_reviews_submitted)) * 100) || 0);
  const reviewCount = dashboard.total_reviews_submitted ?? 0;
  const skills = dashboard.skill_profile?.skills ?? {};
  const deltas = dashboard.skill_deltas?.reduce((acc, curr) => {
    acc[curr.skill] = curr.delta_7d;
    return acc;
  }, {} as Record<string, number>) ?? {};
  const examReadiness = dashboard.exam_readiness ?? {};
  const weeklyDigest = dashboard.weekly_digest ?? "";
  const activityData = dashboard.daily_activity ?? [];
  const trendData: any[] = dashboard.trend_data ?? [];

  const formattedTrend = trendData.map(
    (pt: { date: string; score: number }) => ({
      date: pt.date?.slice(5) ?? "", // MM-DD
      score: pt.score,
    })
  );

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">
          Progress Analytics
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          Your growth at a glance — skill deltas, streaks & readiness
        </p>
      </div>

      {/* ── Top row: KPIs ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Streak */}
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex items-center gap-4">
          <div className="w-14 h-14 bg-[#f59e0b22] rounded-2xl flex items-center justify-center text-3xl flex-shrink-0">
            🔥
          </div>
          <div>
            <p className="text-gray-400 text-xs uppercase tracking-widest">
              Streak
            </p>
            <p className="text-white text-3xl font-extrabold leading-none mt-1">
              {streak}
              <span className="text-gray-400 text-base font-normal ml-1">
                days
              </span>
            </p>
          </div>
        </div>

        {/* Challenge pass rate */}
        <CircularProgress
          pct={passRate}
          label="Challenges Solved"
          sub={`${dashboard.total_challenges_solved ?? 0} total solved`}
        />

        {/* Reviews done */}
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex items-center gap-4">
          <div className="w-14 h-14 bg-[#22c55e22] rounded-2xl flex items-center justify-center text-3xl flex-shrink-0">
            🔬
          </div>
          <div>
            <p className="text-gray-400 text-xs uppercase tracking-widest">
              Reviews Done
            </p>
            <p className="text-white text-3xl font-extrabold leading-none mt-1">
              {reviewCount}
            </p>
          </div>
        </div>
      </div>

      {/* ── Roadmap Tracker Card ── */}
      {dashboard.roadmap_tracker && (
        <div className="bg-[#1a1d2e] border border-[#6366f133] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.15)] flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 bg-[#6366f122] rounded-2xl flex items-center justify-center text-3xl flex-shrink-0">
              🗺️
            </div>
            <div>
              <p className="text-gray-400 text-xs uppercase tracking-widest font-medium">Active Learning Roadmap</p>
              <h3 className="text-white font-extrabold text-lg mt-0.5">{dashboard.roadmap_tracker.target_role}</h3>
              <p className="text-gray-400 text-xs mt-1">
                Progress: <span className="text-white font-semibold">{dashboard.roadmap_tracker.completed_topics}</span> of <span className="text-white font-semibold">{dashboard.roadmap_tracker.total_topics}</span> sub-tasks completed
              </p>
            </div>
          </div>
          <div className="flex-1 max-w-xs w-full space-y-1.5">
            <div className="flex justify-between text-xs font-semibold text-gray-400">
              <span>Roadmap Progress</span>
              <span className="text-[#6366f1]">{Math.round(dashboard.roadmap_tracker.percent_completed * 100)}%</span>
            </div>
            <div className="h-2.5 bg-[#0f1117] rounded-full overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-[#6366f1] to-[#818cf8] rounded-full transition-all duration-700" 
                style={{ width: `${dashboard.roadmap_tracker.percent_completed * 100}%` }}
              />
            </div>
          </div>
          <Link 
            href="/roadmap" 
            className="px-4 py-2 bg-[#6366f1] hover:bg-[#5558e3] text-white text-sm font-semibold rounded-lg transition-colors shrink-0 text-center w-full sm:w-auto"
          >
            Go to Tracker →
          </Link>
        </div>
      )}

      {/* ── Skill delta section ── */}
      {Object.keys(skills).length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
            <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#6366f1]" />
              Skill Radar (7d Deltas)
            </h2>
            <SkillRadarChart skills={skills} delta={deltas} />
          </div>

          <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
            <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#22c55e]" />
              7-Day Changes
            </h2>
            <div className="space-y-3">
              {Object.entries(skills)
                .sort(([, a], [, b]) => (b as number) - (a as number))
                .slice(0, 8)
                .map(([skill, score]) => {
                  const delta = (deltas[skill] as number) ?? 0;
                  return (
                    <div key={skill}>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <div className="flex items-center gap-2">
                          <span className="text-gray-300 capitalize">
                            {skill}
                          </span>
                          <DeltaBadge delta={delta} />
                        </div>
                        <span className="text-gray-400 text-xs">
                          {score as number}/100
                        </span>
                      </div>
                      <div className="h-1.5 bg-[#0f1117] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${score}%`,
                            background:
                              (score as number) >= 75
                                ? "#22c55e"
                                : (score as number) >= 45
                                ? "#6366f1"
                                : "#f59e0b",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        </div>
      )}

      {/* ── Exam readiness ── */}
      {Object.keys(examReadiness).length > 0 && (
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
          <h2 className="text-white font-semibold mb-5 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#f59e0b]" />
            Exam Readiness
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
            {Object.entries(examReadiness).map(([topic, pct]) => (
              <div key={topic}>
                <div className="flex items-center justify-between text-sm mb-1.5">
                  <span className="text-gray-300 capitalize">{topic}</span>
                  <span
                    className="text-xs font-semibold"
                    style={{
                      color:
                        (pct as number) >= 75
                          ? "#22c55e"
                          : (pct as number) >= 50
                          ? "#f59e0b"
                          : "#ef4444",
                    }}
                  >
                    {pct as number}%
                  </span>
                </div>
                <div className="h-2 bg-[#0f1117] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${pct}%`,
                      background:
                        (pct as number) >= 75
                          ? "#22c55e"
                          : (pct as number) >= 50
                          ? "#f59e0b"
                          : "#ef4444",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Weekly digest ── */}
      {weeklyDigest && (
        <div className="space-y-4">
          <h2 className="text-white font-semibold flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#6366f1]" />
            AI Weekly Progress Digest
          </h2>
          <MarkdownRenderer content={weeklyDigest} />
        </div>
      )}

      {/* ── Heatmap ── */}
      {Object.keys(activityData).length > 0 && (
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
          <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#f59e0b]" />
            30-Day Activity
          </h2>
          <ProgressHeatmap data={activityData} />
        </div>
      )}

      {/* ── Trend chart ── */}
      {formattedTrend.length > 1 && (
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
          <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#22c55e]" />
            Skill Score Trend (30 days)
          </h2>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={formattedTrend}>
                <CartesianGrid stroke="#2d3148" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#6b7280", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={["auto", "auto"]}
                  tick={{ fill: "#6b7280", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip content={<CustomTooltip />} />
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke="#6366f1"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, fill: "#6366f1" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── Interview History ── */}
      {history.length > 0 && (
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)] mt-8">
          <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#6366f1]" />
            Interview History
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {history.filter(h => h.completed).map((h, i) => (
              <div key={i} className="bg-[#0f1117] border border-[#2d3148] rounded-lg p-4 flex flex-col justify-between">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-[#6366f1] text-xs font-semibold uppercase tracking-widest">{h.mode === "dsa" ? "DSA" : "Resume"}</span>
                  {h.overall_score !== null && (
                    <span className="text-[#22c55e] text-sm font-bold">{Number(h.overall_score).toFixed(1)}/10</span>
                  )}
                </div>
                <p className="text-gray-400 text-xs">{new Date(h.created_at).toLocaleDateString()}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}