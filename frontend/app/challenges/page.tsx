"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { generateChallenge, submitChallenge, getChallengeHistory, getAttemptDetails } from "@/lib/api";
import type { Challenge } from "@/lib/types";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-gray-500 text-sm">
      Loading editor…
    </div>
  ),
});

interface TestResult {
  case: number;
  status: "AC" | "WA" | "CE" | "RE" | "TLE";
  stdout: string;
  expected: string;
}

interface Verdict {
  status: "AC" | "WA" | "CE" | "RE" | "TLE";
  stderr: string;
  test_results: TestResult[];
}

type SubmitResult = {
  passed: boolean;
  output: string;
  error?: string;
  feedback: string;
  score?: number;
  mcqs_passed?: number;
};

type HistoryEntry = {
  id: string;
  title: string;
  language: string;
  passed: boolean;
  score?: number;
  created_at: string;
};

function DiffBadge({ difficulty }: { difficulty: string }) {
  const map: Record<string, { bg: string; color: string }> = {
    easy: { bg: "#22c55e22", color: "#22c55e" },
    medium: { bg: "#f59e0b22", color: "#f59e0b" },
    hard: { bg: "#ef444422", color: "#ef4444" },
  };
  const s = map[difficulty?.toLowerCase()] ?? map.medium;
  return (
    <span
      className="text-xs font-semibold px-2.5 py-1 rounded-full capitalize"
      style={s}
    >
      {difficulty}
    </span>
  );
}

function TestCaseInput({ input }: { input: Record<string, unknown> }) {
  if (!input || typeof input !== "object") return <span>{String(input)}</span>;
  return (
    <div className="font-mono text-sm space-y-1">
      {Object.entries(input).map(([key, val]) => (
        <div key={key}>
          <span className="text-muted-foreground text-gray-500">{key}</span>
          <span className="text-gray-400">{" = "}</span>
          <span className="text-foreground text-gray-200">{JSON.stringify(val)}</span>
        </div>
      ))}
    </div>
  );
}

const STATUS_CONFIG = {
  AC:  { label: "Accepted",              color: "text-green-500",  bg: "bg-[#22c55e22]"  },
  WA:  { label: "Wrong Answer",          color: "text-red-500",    bg: "bg-[#ef444422]"  },
  CE:  { label: "Compilation Error",     color: "text-red-500",    bg: "bg-[#ef444422]"  },
  RE:  { label: "Runtime Error",         color: "text-orange-500", bg: "bg-[#f9731622]"  },
  TLE: { label: "Time Limit Exceeded",   color: "text-orange-500", bg: "bg-[#f9731622]"  },
};

function VerdictPanel({ verdict, testCases }: { verdict: Verdict, testCases?: any[] }) {
  // If parsing failed or verdict is malformed
  if (!verdict || !verdict.status) {
     return <div className="text-red-500">Evaluation error.</div>;
  }
  const cfg = STATUS_CONFIG[verdict.status] || STATUS_CONFIG["WA"];

  return (
    <div className={`rounded-lg p-4 ${cfg.bg}`}>
      <p className={`font-semibold text-lg ${cfg.color}`}>{cfg.label}</p>

      {/* Show compiler/runtime stderr */}
      {(verdict.status === "CE" || verdict.status === "RE") && verdict.stderr && (
        <pre className="mt-2 text-xs text-red-400 whitespace-pre-wrap font-mono">
          {verdict.stderr}
        </pre>
      )}

      {/* Per-test-case breakdown */}
      {verdict.test_results?.map((tr) => (
        <div key={tr.case} className="mt-3 border-t border-white/10 pt-3">
          <div className="flex items-center justify-between mb-2">
            <span className={`font-medium ${tr.status === "AC" ? "text-green-400" : "text-red-400"}`}>
              Case {tr.case + 1}: {tr.status === "AC" ? "Passed" : "Failed"}
            </span>
          </div>
          
          {/* Input display */}
          {testCases && testCases[tr.case]?.input && (
            <div className="mb-2 bg-black/20 p-2 rounded">
              <TestCaseInput input={testCases[tr.case].input} />
            </div>
          )}

          {(tr.status === "WA" || tr.status === "AC") && (
            <div className="text-xs mt-1 font-mono space-y-1 bg-black/20 p-2 rounded">
              <div><span className="text-gray-500">Expected: </span><span className="text-green-400">{tr.expected}</span></div>
              <div><span className="text-gray-500">Got:      </span><span className={tr.status === "AC" ? "text-green-400" : "text-red-400"}>{tr.stdout}</span></div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function ChallengesPage() {
  const router = useRouter();
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [code, setCode] = useState("");
  const [generating, setGenerating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [mcqAnswers, setMcqAnswers] = useState<Record<number, number>>({});
  const [activeStep, setActiveStep] = useState<"code" | "mcq">("code");
  const [language, setLanguage] = useState<string>("python");
  const [error, setError] = useState<string | null>(null);
  const [selectedAttempt, setSelectedAttempt] = useState<any | null>(null);
  const [attemptDetailsLoading, setAttemptDetailsLoading] = useState(false);
  const [mcqsSubmitted, setMcqsSubmitted] = useState(false);

  const handleHistoryRowClick = async (attemptId: string) => {
    setAttemptDetailsLoading(true);
    try {
      const details = await getAttemptDetails(attemptId);
      setSelectedAttempt(details);
    } catch (e: any) {
      alert("Failed to load attempt details: " + (e?.message ?? String(e)));
    } finally {
      setAttemptDetailsLoading(false);
    }
  };

  useEffect(() => {
    if (!localStorage.getItem("devbrain_token")) {
      router.push("/");
      return;
    }
    setHistoryLoading(true);
    getChallengeHistory()
      .then((h) => setHistory(h ?? []))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, [router]);

  const handleGenerate = async () => {
    setGenerating(true);
    setResult(null);
    setError(null);
    try {
      const c = await generateChallenge();
      setChallenge(c);
      setLanguage("python");
      setCode(c.starter_codes?.["python"] ?? c.starter_code ?? "");
    } catch (e: any) {
      setError(e?.message ?? "Failed to generate challenge. Please try again.");
    } finally {
      setGenerating(false);
      setMcqAnswers({});
      setActiveStep("code");
      setMcqsSubmitted(false);
    }
  };

  const handleSubmit = async () => {
    if (!challenge || !code.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const isMcqStep = activeStep === "mcq";
      const answersArray = isMcqStep ? (challenge.mcqs?.map((_: any, i: number) => mcqAnswers[i] ?? -1) ?? []) : [];
      const r = await submitChallenge(challenge.id, code, language, answersArray);
      
      // Always set result so user can see compiler output / test feedback immediately
      setResult(r);
      
      if (isMcqStep) {
        setMcqsSubmitted(true);
      }
      
      if (r.passed && !isMcqStep && challenge.mcqs?.length > 0) {
        setActiveStep("mcq");
      }
      
      const h = await getChallengeHistory().catch(() => []);
      setHistory(h ?? []);
    } catch (e: any) {
      setError(e?.message ?? "Submission failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Daily Challenges
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            AI-generated problems targeting your weak areas
          </p>
        </div>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="px-5 py-2.5 bg-[#6366f1] hover:bg-[#5558e3] text-white font-semibold text-sm rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
        >
          {generating ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Generating…
            </>
          ) : (
            "⚡ Get Today's Challenge"
          )}
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-500/50 rounded-xl px-4 py-3 text-red-400 text-sm flex items-center gap-2">
          <span>⚠️</span> {error}
        </div>
      )}

      {challenge && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* ── Left: Problem description ── */}
          <div className="space-y-4">
            <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
              <div className="flex items-start justify-between gap-3 mb-4">
                <h2 className="text-white font-bold text-lg">
                  {challenge.title}
                </h2>
                <DiffBadge difficulty={challenge.difficulty ?? "medium"} />
              </div>
              <p className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
                {challenge.description}
              </p>
            </div>

            {/* Constraints */}
            {(challenge.constraints?.length ?? 0) > 0 && (
              <details className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl overflow-hidden">
                <summary className="px-5 py-3.5 text-sm font-semibold text-white cursor-pointer hover:bg-[#2d3148]/30 transition-colors flex items-center justify-between">
                  <span>📏 Constraints</span>
                  <span className="text-gray-500 text-xs">click to expand</span>
                </summary>
                <div className="px-5 pb-4">
                  <ul className="space-y-1.5">
                    {challenge.constraints?.map((c: string, i: number) => (
                      <li key={i} className="text-gray-400 text-sm flex gap-2">
                        <span className="text-[#6366f1]">•</span>
                        {c}
                      </li>
                    ))}
                  </ul>
                </div>
              </details>
            )}

            {/* Examples */}
            {(challenge.examples?.length ?? 0) > 0 && (
              <details className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl overflow-hidden" open>
                <summary className="px-5 py-3.5 text-sm font-semibold text-white cursor-pointer hover:bg-[#2d3148]/30 transition-colors">
                  💡 Examples
                </summary>
                <div className="px-5 pb-4 space-y-3">
                  {challenge.examples?.map(
                    (ex: { input: string; output: string; explanation?: string }, i: number) => (
                      <div
                        key={i}
                        className="bg-[#0f1117] rounded-lg p-3 text-xs font-mono"
                      >
                        <p>
                          <span className="text-gray-500">Input: </span>
                          <span className="text-gray-300">{ex.input}</span>
                        </p>
                        <p>
                          <span className="text-gray-500">Output: </span>
                          <span className="text-[#22c55e]">{ex.output}</span>
                        </p>
                        {ex.explanation && (
                          <p className="text-gray-500 mt-1">{ex.explanation}</p>
                        )}
                      </div>
                    )
                  )}
                </div>
              </details>
            )}

            {/* Test Cases (Read-only) */}
            {activeStep === "code" && challenge.test_cases?.length > 0 && (
              <details className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl overflow-hidden">
                <summary className="px-5 py-3.5 text-sm font-semibold text-white cursor-pointer hover:bg-[#2d3148]/30 transition-colors">
                  🧪 Sample Test Cases ({Math.min(4, challenge.test_cases.length)})
                </summary>
                <div className="px-5 pb-4 space-y-3">
                  {challenge.test_cases.slice(0, 4).map(
                    (tc: { input: string; expected_output: string; expected?: string; type?: string }, i: number) => (
                      <div
                        key={i}
                        className="bg-[#0f1117] rounded-lg p-3 text-xs font-mono"
                      >
                        {tc.type && (
                           <p className="text-[#6366f1] mb-1 font-bold">{tc.type}</p>
                        )}
                        <p>
                          <span className="text-gray-500">Input: </span>
                          <span className="text-gray-300">
                            {(() => {
                              const str = typeof tc.input === "object" ? JSON.stringify(tc.input) : String(tc.input || "");
                              return str.length > 100 ? str.substring(0, 100) + "..." : str;
                            })()}
                          </span>
                        </p>
                        <p>
                          <span className="text-gray-500">Expected: </span>
                          <span className="text-[#22c55e]">{tc.expected_output || tc.expected}</span>
                        </p>
                      </div>
                    )
                  )}
                  {challenge.test_cases.length > 4 && (
                    <div className="text-xs text-gray-500 text-center py-2 border-t border-white/5 font-sans">
                      🔒 +{challenge.test_cases.length - 4} private test cases are hidden and will be executed upon code submission.
                    </div>
                  )}
                </div>
              </details>
            )}

            {/* Submit results */}
            {result && (
              <div
                className={`border rounded-xl p-5 ${
                  result.passed
                    ? "bg-[#22c55e11] border-[#22c55e44]"
                    : "bg-[#ef444411] border-[#ef444444]"
                }`}
              >
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xl">{result.passed ? "🎉" : "❌"}</span>
                  <span
                    className={`font-bold ${
                      result.passed ? "text-[#22c55e]" : "text-[#ef4444]"
                    }`}
                  >
                    {result.passed ? "All tests passed!" : "Some tests failed"}
                  </span>
                  {result.score != null && (
                    <span className="ml-auto text-sm text-gray-400">
                      Score: {result.score}/100
                    </span>
                  )}
                  {mcqsSubmitted && result.mcqs_passed !== undefined && (
                    <span className="ml-auto text-sm font-semibold text-pink-400">
                      MCQs: {result.mcqs_passed}/{challenge.mcqs?.length ?? 0}
                    </span>
                  )}
                </div>
                {result.output && (
                  <div className="space-y-2 mb-3">
                    <VerdictPanel 
                      verdict={(() => {
                        try { return JSON.parse(result.output); } catch { return null; }
                      })()} 
                      testCases={challenge.test_cases}
                    />
                  </div>
                )}

                {mcqsSubmitted && result.mcqs_passed !== undefined && (
                  <div className="mb-3 bg-pink-500/10 border border-pink-500/20 rounded-xl p-4 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-pink-400 uppercase tracking-widest">🧠 MCQ Scorecard</span>
                      <span className="text-xs font-bold text-white bg-pink-500/20 px-2.5 py-0.5 rounded font-mono">
                        {Math.round((result.mcqs_passed / (challenge.mcqs?.length || 1)) * 100)}% Accuracy
                      </span>
                    </div>
                    <p className="text-[11px] text-gray-400 leading-relaxed font-sans">
                      💡 **Scoring Weightage:** Theoretical questions represent equal weightage of your theoretical evaluation score.
                    </p>
                  </div>
                )}

                {result.feedback && (
                  <div className="bg-[#0f1117] rounded-lg p-3">
                    <p className="text-gray-400 text-xs uppercase tracking-widest mb-1">
                      Grok Feedback
                    </p>
                    <p className="text-gray-300 text-sm leading-relaxed">
                      {result.feedback}
                    </p>
                  </div>
                )}
                
                {/* Step transition */}
                {!result.passed && activeStep === "code" && (
                  <button 
                    onClick={() => setActiveStep("mcq")}
                    className="mt-4 w-full bg-[#ec4899] hover:bg-[#db2777] text-white py-2 rounded-lg text-sm font-semibold transition-colors"
                  >
                    Try Knowledge Check Instead
                  </button>
                )}
              </div>
            )}
          </div>

          {/* ── Right: Editor or Knowledge Check ── */}
          <div className="flex flex-col gap-4">
            {activeStep === "code" ? (
              <>
                <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#22c55e]" />
                    <select
                      value={language}
                      onChange={(e) => {
                        const newLang = e.target.value;
                        setLanguage(newLang);
                        if (challenge.starter_codes && challenge.starter_codes[newLang]) {
                          setCode(challenge.starter_codes[newLang]);
                        }
                      }}
                      disabled={submitting}
                      className="bg-transparent text-gray-400 text-xs font-medium uppercase tracking-widest outline-none cursor-pointer appearance-none border border-[#2d3148] rounded px-2 py-1 hover:text-white transition-colors"
                    >
                      <option value="python">Python</option>
                      <option value="java">Java</option>
                      <option value="cpp">C++</option>
                    </select>
                  </div>
                  
                  <button
                    onClick={handleSubmit}
                    disabled={submitting}
                    className="flex items-center gap-2 bg-[#22c55e] hover:bg-[#16a34a] text-white px-5 py-2.5 rounded-lg font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-[0_0_15px_rgba(34,197,94,0.3)]"
                  >
                    {submitting ? (
                      <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    ) : (
                      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                    Run Code
                  </button>
                </div>

                <div className="flex-1 bg-[#1a1d2e] border border-[#2d3148] rounded-xl overflow-hidden shadow-[0_0_15px_rgba(99,102,241,0.1)] min-h-[500px]">
                  <MonacoEditor
                    language={language.replace("cpp", "c++")}
                    value={code}
                    onChange={(v) => setCode(v ?? "")}
                    theme="vs-dark"
                    options={{
                      minimap: { enabled: false },
                      fontSize: 14,
                      lineHeight: 24,
                      padding: { top: 20 },
                      scrollBeyondLastLine: false,
                      smoothScrolling: true,
                      cursorBlinking: "smooth",
                      cursorSmoothCaretAnimation: "on",
                      formatOnPaste: true,
                      readOnly: false,
                    }}
                  />
                </div>
              </>
            ) : (
              <div className="flex-1 bg-[#1a1d2e] border border-[#2d3148] rounded-xl overflow-hidden shadow-[0_0_15px_rgba(236,72,153,0.1)] flex flex-col">
              <div className="bg-[#2d3148]/30 px-6 py-4 flex items-center justify-between border-b border-[#2d3148]">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <span className="text-2xl">🧠</span> Knowledge Check
                  </h2>
                  <p className="text-xs text-pink-400 mt-1">
                    ⚡ Each question carries equal weightage towards theoretical correctness.
                  </p>
                </div>
                <button
                  onClick={handleSubmit}
                  disabled={submitting || mcqsSubmitted}
                  className="flex items-center gap-2 bg-[#ec4899] hover:bg-[#db2777] text-white px-5 py-2.5 rounded-lg font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-[0_0_15px_rgba(236,72,153,0.3)]"
                >
                  {submitting ? (
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    "Submit Answers"
                  )}
                </button>
              </div>
                <div className="p-8 space-y-8 overflow-y-auto">
                  {challenge.mcqs?.map((mcq: any, i: number) => (
                    <div key={i} className="bg-[#0f1117] rounded-xl p-6 border border-[#2d3148]">
                      <p className="text-gray-200 text-base font-medium leading-relaxed mb-4">
                        <span className="text-[#ec4899] font-bold mr-2">Q{i + 1}.</span>
                        {mcq.question}
                      </p>
                      <div className="space-y-3">
                        {mcq.options.map((opt: string, optIdx: number) => (
                          <label
                            key={optIdx}
                            className={`flex items-start gap-3 p-4 rounded-lg border cursor-pointer transition-colors ${
                              mcqAnswers[i] === optIdx
                                ? "bg-[#ec489911] border-[#ec489955]"
                                : "bg-[#1a1d2e] border-[#2d3148] hover:border-gray-500"
                            } ${
                              mcqsSubmitted
                                ? optIdx === mcq.correct_index
                                  ? "bg-[#22c55e11] border-[#22c55e55]"
                                  : mcqAnswers[i] === optIdx
                                  ? "bg-[#ef444411] border-[#ef444455]"
                                  : "opacity-50 cursor-default"
                                : ""
                            }`}
                          >
                            <input
                              type="radio"
                              name={`mcq-${i}`}
                              checked={mcqAnswers[i] === optIdx}
                              onChange={() => !mcqsSubmitted && setMcqAnswers(prev => ({ ...prev, [i]: optIdx }))}
                              disabled={mcqsSubmitted}
                              className="mt-0.5 text-[#ec4899] focus:ring-[#ec4899] bg-transparent border-gray-600"
                            />
                            <span className={`text-sm ${mcqsSubmitted && optIdx === mcq.correct_index ? "text-[#22c55e] font-semibold" : "text-gray-300"}`}>
                              {opt}
                            </span>
                          </label>
                        ))}
                      </div>
                      {mcqsSubmitted && mcq.explanation && (
                        <div className="mt-4 p-4 bg-[#2d3148]/20 border-l-4 border-[#6366f1] rounded-r-lg">
                          <p className="text-sm text-gray-300">
                            <span className="font-semibold text-[#6366f1] mr-2">Explanation:</span>
                            {mcq.explanation}
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {!challenge && !generating && (
        <div className="text-center py-16">
          <div className="text-6xl mb-5">⚡</div>
          <p className="text-gray-300 font-semibold text-lg mb-2">
            Ready for a challenge?
          </p>
          <p className="text-gray-500 text-sm">
            Click "Get Today's Challenge" to receive a problem tailored to your weak areas.
          </p>
        </div>
      )}

      {/* ── History table ── */}
      {(history.length > 0 || historyLoading) && (
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl overflow-hidden shadow-[0_0_15px_rgba(99,102,241,0.1)]">
          <div className="px-6 py-4 border-b border-[#2d3148]">
            <h2 className="text-white font-semibold flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#f59e0b]" />
              Challenge History
            </h2>
          </div>
          {historyLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(3)].map((_, i) => (
                <div
                  key={i}
                  className="h-4 bg-[#2d3148] rounded animate-pulse"
                />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#2d3148]">
                    {["Challenge", "Language", "Status", "Score", "Date"].map(
                      (h) => (
                        <th
                          key={h}
                          className="px-5 py-3 text-left text-xs text-gray-400 uppercase tracking-widest font-medium"
                        >
                          {h}
                        </th>
                      )
                    )}
                  </tr>
                </thead>
                <tbody>
                  {history.slice(0, 10).map((entry) => (
                    <tr
                      key={entry.id}
                      onClick={() => handleHistoryRowClick(entry.id)}
                      className="border-b border-[#2d3148] last:border-0 hover:bg-[#2d3148]/20 transition-colors cursor-pointer"
                      title="Click to view detailed submission history"
                    >
                      <td className="px-5 py-3 text-gray-300">{entry.title}</td>
                      <td className="px-5 py-3 text-gray-400 capitalize">
                        {entry.language}
                      </td>
                      <td className="px-5 py-3">
                        <span
                          className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                            entry.passed
                              ? "bg-[#22c55e22] text-[#22c55e]"
                              : "bg-[#ef444422] text-[#ef4444]"
                          }`}
                        >
                          {entry.passed ? "Passed" : "Failed"}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-gray-400">
                        {entry.score != null ? `${entry.score}/100` : "—"}
                      </td>
                      <td className="px-5 py-3 text-gray-500 text-xs">
                        {new Date(entry.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Loading Overlay for Fetching Attempt Details ── */}
      {attemptDetailsLoading && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm transition-all">
          <div className="flex flex-col items-center gap-4 bg-[#111322] border border-[#2d3148] px-8 py-6 rounded-2xl shadow-2xl">
            <div className="w-10 h-10 border-4 border-[#6366f1]/20 border-t-[#6366f1] rounded-full animate-spin" />
            <span className="text-sm font-semibold text-gray-300">Fetching submission details…</span>
          </div>
        </div>
      )}

      {/* ── LeetCode-style Attempt Details Modal ── */}
      {selectedAttempt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md transition-all duration-300">
          <div className="bg-[#111322] border border-[#2d3148] w-full max-w-6xl h-[85vh] rounded-2xl flex flex-col overflow-hidden shadow-[0_0_50px_rgba(99,102,241,0.25)] animate-in fade-in zoom-in duration-200">
            
            {/* Header */}
            <div className="px-6 py-4 bg-[#1a1d2e] border-b border-[#2d3148] flex items-center justify-between">
              <div>
                <div className="flex items-center gap-3 flex-wrap">
                  <h3 className="text-xl font-bold text-white tracking-tight">
                    {selectedAttempt.challenge_title}
                  </h3>
                  <span className={`text-xs font-semibold px-2.5 py-1 rounded-full capitalize ${
                    selectedAttempt.challenge_difficulty?.toLowerCase() === 'easy' ? 'bg-[#22c55e22] text-[#22c55e]' :
                    selectedAttempt.challenge_difficulty?.toLowerCase() === 'hard' ? 'bg-[#ef444422] text-[#ef4444]' :
                    'bg-[#f59e0b22] text-[#f59e0b]'
                  }`}>
                    {selectedAttempt.challenge_difficulty}
                  </span>
                  <span className="text-xs text-gray-400 bg-[#2d3148] px-2.5 py-1 rounded-md font-mono">
                    {selectedAttempt.challenge_topic}
                  </span>
                </div>
                <p className="text-gray-400 text-xs mt-1">
                  Submitted on {new Date(selectedAttempt.submitted_at).toLocaleString()} via <span className="font-semibold text-[#6366f1] uppercase">{selectedAttempt.language}</span>
                </p>
              </div>
              <button
                onClick={() => setSelectedAttempt(null)}
                className="p-2 hover:bg-[#2d3148] rounded-lg text-gray-400 hover:text-white transition-colors"
              >
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content Layout */}
            <div className="flex-1 overflow-hidden flex flex-col md:flex-row">
              
              {/* Left Panel: Description & MCQs */}
              <div className="w-full md:w-1/2 p-6 border-r border-[#2d3148] overflow-y-auto space-y-6">
                <div>
                  <h4 className="text-white font-bold text-xs uppercase tracking-widest text-gray-400 mb-2">Problem Description</h4>
                  <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-4 text-gray-300 text-sm leading-relaxed whitespace-pre-wrap font-sans">
                    {selectedAttempt.challenge_description}
                  </div>
                </div>

                {/* MCQs section in Attempt Details */}
                {selectedAttempt.mcqs && selectedAttempt.mcqs.length > 0 && (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between border-b border-[#2d3148] pb-2">
                      <h4 className="text-white font-bold text-xs uppercase tracking-widest text-gray-400">Knowledge Check MCQs</h4>
                      <span className="text-xs font-semibold text-pink-400 bg-pink-400/10 px-3 py-1 rounded-full">
                        {selectedAttempt.mcqs_passed} / {selectedAttempt.mcqs.length} Correct
                      </span>
                    </div>
                    <div className="space-y-4">
                       {selectedAttempt.mcqs.map((mcq: any, i: number) => (
                         <div key={i} className="bg-[#0f1117] rounded-xl p-5 border border-[#2d3148] space-y-3">
                           <p className="text-gray-200 text-sm font-medium leading-relaxed font-sans">
                             <span className="text-[#ec4899] font-bold mr-1">Q{i + 1}.</span> {mcq.question}
                           </p>
                           <div className="grid grid-cols-1 gap-2">
                             {mcq.options?.map((opt: string, optIdx: number) => (
                               <div
                                 key={optIdx}
                                 className={`p-3 rounded-lg border text-xs text-gray-300 flex items-center justify-between ${
                                   optIdx === mcq.correct_index
                                     ? "bg-[#22c55e11] border-[#22c55e44] text-[#22c55e] font-semibold"
                                     : "bg-[#1a1d2e]/50 border-[#2d3148]"
                                 }`}
                               >
                                 <span>{opt}</span>
                                 {optIdx === mcq.correct_index && (
                                   <span className="text-[#22c55e] text-[10px] font-bold uppercase tracking-wider bg-[#22c55e22] px-2 py-0.5 rounded">Correct Answer</span>
                                 )}
                               </div>
                             ))}
                           </div>
                           {mcq.explanation && (
                             <div className="mt-3 p-3 bg-[#2d3148]/20 border-l-4 border-[#6366f1] rounded-r-lg text-xs text-gray-300 leading-relaxed font-sans">
                               <span className="font-semibold text-[#6366f1] mr-1">Explanation:</span>
                               {mcq.explanation}
                             </div>
                           )}
                         </div>
                       ))}
                     </div>
                  </div>
                )}
              </div>

              {/* Right Panel: Submitted Code & Outcomes */}
              <div className="w-full md:w-1/2 p-6 overflow-y-auto space-y-6 bg-[#0c0d17]">
                
                {/* Submitted Code */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-white font-bold text-xs uppercase tracking-widest text-gray-400">Submitted Code</h4>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(selectedAttempt.code);
                        alert("Code copied to clipboard!");
                      }}
                      className="text-xs text-[#6366f1] hover:text-[#5558e3] hover:underline font-semibold transition-colors"
                    >
                      Copy Code
                    </button>
                  </div>
                  <pre className="p-4 bg-[#141625] border border-[#2d3148] rounded-xl text-xs font-mono text-gray-200 overflow-x-auto whitespace-pre leading-relaxed select-text max-h-[300px]">
                    {selectedAttempt.code}
                  </pre>
                </div>

                {/* Outcome Indicators */}
                <div className="grid grid-cols-2 gap-4">
                   <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-4">
                     <p className="text-gray-500 text-[10px] uppercase tracking-widest font-bold">Verdict</p>
                     <p className={`text-base font-bold mt-1 ${selectedAttempt.passed ? 'text-[#22c55e]' : 'text-[#ef4444]'}`}>
                       {selectedAttempt.passed ? 'Accepted' : 'Failed'}
                     </p>
                   </div>
                   <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-4">
                     <p className="text-gray-500 text-[10px] uppercase tracking-widest font-bold">Test Cases Passed</p>
                     <p className="text-base font-bold text-white mt-1">
                       {selectedAttempt.tests_passed} / {selectedAttempt.tests_total}
                     </p>
                   </div>
                </div>

                {/* Test Case Execution Output */}
                {selectedAttempt.output && (
                  <div>
                    <h4 className="text-white font-bold text-xs uppercase tracking-widest text-gray-400 mb-2">Test Case Executions</h4>
                    <div className="space-y-3">
                      <VerdictPanel
                        verdict={(() => {
                          try { return JSON.parse(selectedAttempt.output); } catch { return null; }
                        })()}
                        testCases={selectedAttempt.test_cases}
                      />
                    </div>
                  </div>
                )}

                {/* Grok Feedback */}
                {selectedAttempt.feedback && (
                  <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 space-y-2">
                    <p className="text-gray-400 text-xs font-bold uppercase tracking-widest font-sans">Grok AI Code Review</p>
                    <p className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap font-sans">{selectedAttempt.feedback}</p>
                  </div>
                )}
              </div>

            </div>
          </div>
        </div>
      )}
    </div>
  );
}