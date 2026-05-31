"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { startInterview, sendInterviewMessage, getInterviewHistory } from "@/lib/api";
import type { InterviewSession } from "@/lib/types";

const ChatInterface = dynamic(() => import("@/components/ChatInterface"), {
  ssr: false,
});

type Mode = "dsa" | "resume";

type Message = {
  role: "user" | "assistant";
  content: string;
};

type ReportCard = {
  overall_score?: number;
  strengths?: string[];
  weak_areas?: string[];
  summary?: string;
};

const MODES: { value: Mode; label: string; icon: string; desc: string }[] = [
  {
    value: "dsa",
    label: "DSA Interview",
    icon: "🧩",
    desc: "Data structures, algorithms, time/space complexity. LeetCode-style questions with guided hints.",
  },
  {
    value: "resume",
    label: "Resume & Projects",
    icon: "💼",
    desc: "Personalized interview based on your resume. We'll ask about your projects, technical choices, and behaviorals.",
  },
];

function ModeCard({
  mode,
  selected,
  onSelect,
}: {
  mode: (typeof MODES)[0];
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`flex-1 min-w-[200px] bg-[#1a1d2e] border rounded-xl p-6 text-left transition-all shadow-[0_0_15px_rgba(99,102,241,0.1)] ${
        selected
          ? "border-[#6366f1] shadow-[0_0_20px_rgba(99,102,241,0.25)]"
          : "border-[#2d3148] hover:border-[#6366f1]/50"
      }`}
    >
      <div className="text-3xl mb-3">{mode.icon}</div>
      <p className="text-white font-semibold mb-2">{mode.label}</p>
      <p className="text-gray-400 text-xs leading-relaxed">{mode.desc}</p>
      {selected && (
        <div className="mt-3 flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-[#6366f1]" />
          <span className="text-[#6366f1] text-xs font-medium">Selected</span>
        </div>
      )}
    </button>
  );
}

function ScoreCircle({ score }: { score: number }) {
  const r = 44;
  const circ = 2 * Math.PI * r;
  const dash = (score / 10) * circ;
  const color = score >= 8 ? "#22c55e" : score >= 5 ? "#f59e0b" : "#ef4444";

  return (
    <svg width="110" height="110" viewBox="0 0 110 110">
      <circle cx="55" cy="55" r={r} fill="none" stroke="#2d3148" strokeWidth="8" />
      <circle
        cx="55"
        cy="55"
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray={`${dash} ${circ - dash}`}
        transform="rotate(-90 55 55)"
      />
      <text x="55" y="60" textAnchor="middle" fill="white" fontSize="22" fontWeight="800">
        {Number(score).toFixed(1)}
      </text>
      <text x="55" y="74" textAnchor="middle" fill="#6b7280" fontSize="10">
        / 10
      </text>
    </svg>
  );
}

export default function InterviewPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("dsa");
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [session, setSession] = useState<InterviewSession | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [report, setReport] = useState<ReportCard | null>(null);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [history, setHistory] = useState<any[]>([]);

  useEffect(() => {
    if (!localStorage.getItem("devbrain_token")) {
      router.push("/");
      return;
    }
    getInterviewHistory().then(setHistory).catch(console.error);
  }, [router]);

  const handleStart = async () => {
    if (mode === "resume" && !resumeFile) {
      setError("Please upload your PDF resume to start this interview mode.");
      return;
    }
    setStarting(true);
    setMessages([]);
    setReport(null);
    setSessionComplete(false);
    setError(null);
    try {
      const s = await startInterview(mode, resumeFile || undefined);
      setSession(s);
      if (s.opening_message) {
        setMessages([{ role: "assistant", content: s.opening_message }]);
      }
    } catch (e: any) {
      setError(e?.message ?? "Failed to start interview. Please try again.");
    } finally {
      setStarting(false);
    }
  };

  const handleSend = async (text: string) => {
    if (!session) return;
    const userMsg: Message = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setError(null);
    try {
      const res = await sendInterviewMessage(session.id, text);
      const aiMsg: Message = {
        role: "assistant",
        content: res.message ?? res.response ?? "",
      };
      setMessages((prev) => [...prev, aiMsg]);
      if (res.session_complete) {
        setSessionComplete(true);
        setReport(res.report ?? null);
      }
    } catch (e: any) {
      setError(e?.message ?? "Failed to send message. Please try again.");
      setMessages((prev) => prev.slice(0, -1)); // remove the optimistic user message
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setSession(null);
    setMessages([]);
    setReport(null);
    setSessionComplete(false);
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">
          Mock Interview
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          Adaptive AI interviewer — practice DSA or system design
        </p>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-500/50 rounded-xl px-4 py-3 text-red-400 text-sm flex items-center gap-2">
          <span>⚠️</span> {error}
        </div>
      )}

      {!session ? (
        /* ── Mode selector ── */
        <div className="space-y-6">
          <div className="flex gap-4 flex-wrap">
            {MODES.map((m) => (
              <ModeCard
                key={m.value}
                mode={m}
                selected={mode === m.value}
                onSelect={() => setMode(m.value)}
              />
            ))}
          </div>

          <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
            {mode === "resume" && (
              <div className="mb-5 pb-5 border-b border-[#2d3148]">
                <label className="block text-gray-300 text-sm font-semibold mb-2">
                  Upload Resume (PDF)
                </label>
                <input
                  type="file"
                  accept="application/pdf"
                  onChange={(e) => setResumeFile(e.target.files?.[0] || null)}
                  className="text-white text-sm file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-[#6366f1] file:text-white hover:file:bg-[#5558e3]"
                />
              </div>
            )}
            <p className="text-gray-400 text-xs uppercase tracking-widest mb-3">
              What to expect
            </p>
            <ul className="space-y-2">
              {mode === "dsa"
                ? [
                    "2–3 algorithmic problems of increasing difficulty",
                    "Real-time hints if you get stuck",
                    "Time & space complexity discussion",
                    "Code walkthrough and edge case probing",
                  ]
                : [
                    "One challenging behavioral question",
                    "Deep dive into 3-5 of your resume projects",
                    "Discussion on architecture and technical decisions",
                  ].map((item, i) => (
                    <li key={i} className="text-gray-300 text-sm flex gap-2">
                      <span className="text-[#6366f1]">•</span>
                      {item}
                    </li>
                  ))}
            </ul>
          </div>

          <button
            onClick={handleStart}
            disabled={starting}
            className="px-8 py-3 bg-[#6366f1] hover:bg-[#5558e3] text-white font-bold rounded-xl transition-colors disabled:opacity-50 flex items-center gap-2 text-base"
          >
            {starting ? (
              <>
                <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Starting session…
              </>
            ) : (
              `Start ${mode === "dsa" ? "DSA" : "Resume"} Interview →`
            )}
          </button>
          
          {history.length > 0 && (
            <div className="pt-6 mt-6 border-t border-[#2d3148]">
              <h2 className="text-white font-semibold mb-4 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[#6366f1]" />
                Previous Interviews
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {history.filter((h) => h.completed).map((h, i) => (
                  <div key={i} className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-4 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
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
      ) : (
        /* ── Active session ── */
        <div className="space-y-4">
          <div className="flex items-center justify-between bg-[#1a1d2e] border border-[#2d3148] rounded-xl px-5 py-3 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
            <div className="flex items-center gap-3">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  sessionComplete ? "bg-[#22c55e]" : "bg-[#6366f1] animate-pulse"
                }`}
              />
              <span className="text-white text-sm font-medium">
                {mode === "dsa" ? "DSA" : "Resume"} Interview
              </span>
              {sessionComplete && (
                <span className="text-xs text-[#22c55e] font-semibold">
                  Complete
                </span>
              )}
            </div>
            <button
              onClick={handleReset}
              className="text-gray-400 hover:text-white text-sm border border-[#2d3148] px-3 py-1.5 rounded-lg transition-colors"
            >
              New Session
            </button>
          </div>

          {/* ── Report card ── */}
          {sessionComplete && report && (
            <div className="bg-[#1a1d2e] border border-[#22c55e33] rounded-xl p-6 shadow-[0_0_20px_rgba(34,197,94,0.1)] space-y-5">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-2 h-2 rounded-full bg-[#22c55e]" />
                <span className="text-[#22c55e] text-xs font-semibold uppercase tracking-widest">
                  Interview Report
                </span>
              </div>

              <div className="flex items-start gap-6 flex-wrap">
                {report.overall_score != null && (
                  <ScoreCircle score={report.overall_score} />
                )}
                <div className="flex-1 min-w-[200px] space-y-4">
                  {report.summary && (
                    <p className="text-gray-300 text-sm leading-relaxed">
                      {report.summary}
                    </p>
                  )}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {report.strengths && report.strengths.length > 0 && (
                      <div>
                        <p className="text-[#22c55e] text-xs font-semibold uppercase tracking-widest mb-2">
                          Strengths
                        </p>
                        <ul className="space-y-1">
                          {report.strengths.map((s, i) => (
                            <li
                              key={i}
                              className="text-gray-300 text-sm flex gap-2"
                            >
                              <span className="text-[#22c55e]">✓</span>
                              {s}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {report.weak_areas && report.weak_areas.length > 0 && (
                      <div>
                        <p className="text-[#ef4444] text-xs font-semibold uppercase tracking-widest mb-2">
                          Areas to Improve
                        </p>
                        <ul className="space-y-1">
                          {report.weak_areas.map((w, i) => (
                            <li
                              key={i}
                              className="text-gray-300 text-sm flex gap-2"
                            >
                              <span className="text-[#ef4444]">↗</span>
                              {w}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <button
                onClick={handleReset}
                className="px-6 py-2.5 bg-[#6366f1] hover:bg-[#5558e3] text-white text-sm font-semibold rounded-lg transition-colors"
              >
                Start Another Session →
              </button>
            </div>
          )}

          <div className="h-[480px]">
            <ChatInterface
              messages={messages}
              onSend={handleSend}
              isLoading={isLoading}
              sessionComplete={sessionComplete}
            />
          </div>
        </div>
      )}
    </div>
  );
}