"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { submitCodeReview, streamCodeReview } from "@/lib/api";
import type { CodeReview } from "@/lib/types";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-gray-500 text-sm">
      Loading editor…
    </div>
  ),
});

const LANGUAGES = [
  { value: "python", label: "Python" },
  { value: "javascript", label: "JavaScript" },
  { value: "typescript", label: "TypeScript" },
  { value: "go", label: "Go" },
  { value: "java", label: "Java" },
  { value: "cpp", label: "C++" },
];

const STARTER: Record<string, string> = {
  python: `def two_sum(nums: list[int], target: int) -> list[int]:
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
    return []
`,
  javascript: `function twoSum(nums, target) {
  const seen = new Map();
  for (let i = 0; i < nums.length; i++) {
    const complement = target - nums[i];
    if (seen.has(complement)) return [seen.get(complement), i];
    seen.set(nums[i], i);
  }
  return [];
}`,
  typescript: `function twoSum(nums: number[], target: number): number[] {
  const seen = new Map<number, number>();
  for (let i = 0; i < nums.length; i++) {
    const complement = target - nums[i];
    if (seen.has(complement)) return [seen.get(complement)!, i];
    seen.set(nums[i], i);
  }
  return [];
}`,
  go: `func twoSum(nums []int, target int) []int {
	seen := make(map[int]int)
	for i, n := range nums {
		if j, ok := seen[target-n]; ok {
			return []int{j, i}
		}
		seen[n] = i
	}
	return nil
}`,
  java: `class Solution {
    public int[] twoSum(int[] nums, int target) {
        Map<Integer,Integer> map = new HashMap<>();
        for (int i = 0; i < nums.length; i++) {
            int comp = target - nums[i];
            if (map.containsKey(comp)) return new int[]{map.get(comp), i};
            map.put(nums[i], i);
        }
        return new int[]{};
    }
}`,
  cpp: `vector<int> twoSum(vector<int>& nums, int target) {
    unordered_map<int,int> seen;
    for (int i = 0; i < nums.size(); i++) {
        int comp = target - nums[i];
        if (seen.count(comp)) return {seen[comp], i};
        seen[nums[i]] = i;
    }
    return {};
}`,
};

function ScoreBadge({ score }: { score: number }) {
  const color =
    score < 5 ? "#ef4444" : score <= 7 ? "#f59e0b" : "#22c55e";
  return (
    <div
      className="flex items-center justify-center w-16 h-16 rounded-2xl text-2xl font-extrabold border-2"
      style={{ color, borderColor: color, background: `${color}18` }}
    >
      {score}
    </div>
  );
}

function Collapsible({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-[#2d3148] rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-white hover:bg-[#2d3148]/40 transition-colors"
      >
        <span>{title}</span>
        <span
          className="text-gray-400 transition-transform duration-200"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
        >
          ▾
        </span>
      </button>
      {open && <div className="px-4 pb-4 pt-1">{children}</div>}
    </div>
  );
}

function ReviewSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-16 w-16 bg-[#2d3148] rounded-2xl" />
      <div className="h-4 bg-[#2d3148] rounded w-3/4" />
      <div className="h-4 bg-[#2d3148] rounded w-1/2" />
      <div className="h-24 bg-[#2d3148] rounded-xl" />
      <div className="h-24 bg-[#2d3148] rounded-xl" />
    </div>
  );
}

export default function ReviewPage() {
  const router = useRouter();
  const [code, setCode] = useState(STARTER.python);
  const [language, setLanguage] = useState("python");
  const [context, setContext] = useState("");
  const [review, setReview] = useState<CodeReview | null>(null);
  const [streamText, setStreamText] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<ReturnType<typeof streamCodeReview> | null>(null);

  useEffect(() => {
    if (!localStorage.getItem("devbrain_token")) router.push("/");
  }, [router]);

  const handleFullReview = async () => {
    if (!code.trim()) return;
    setLoading(true);
    setReview(null);
    setStreamText("");
    setError(null);
    try {
      const r = await submitCodeReview(code, language, context || undefined);
      if (!r) throw new Error("Empty response from server");
      setReview(r);
    } catch (e: any) {
      setError(e?.message ?? "Review failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleStreamReview = () => {
    if (!code.trim()) return;
    setStreaming(true);
    setReview(null);
    setStreamText("");
    setError(null);
    try {
      streamRef.current = streamCodeReview(
        code,
        language,
        (chunk) => setStreamText((p) => p + chunk),
        () => setStreaming(false),
        () => { setStreaming(false); setError("Stream connection failed."); }
      );
    } catch (e: any) {
      setStreaming(false);
      setError(e?.message ?? "Stream failed. Please try again.");
    }
  };

  const handleLanguageChange = (lang: string) => {
    setLanguage(lang);
    setCode(STARTER[lang] ?? "");
  };

  const annotations = review?.annotations ?? [];
  const edgeCases = review?.edge_cases ?? [];
  const improvements = review?.improvements ?? [];
  const bestPractices = review?.best_practices ?? [];

  return (
    <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-8 h-[calc(100vh-4rem)] flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">
          AI Code Review
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          Multi-pass analysis with self-reflection loop — quality guaranteed
        </p>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-500/50 rounded-xl px-4 py-3 text-red-400 text-sm flex items-center gap-2">
          <span>⚠️</span> {error}
        </div>
      )}

      <div className="flex-1 grid grid-cols-1 xl:grid-cols-2 gap-4 min-h-0">
        {/* ── Left: Editor ── */}
        <div className="flex flex-col gap-3">
          {/* Toolbar */}
          <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-3 flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2 flex-1 min-w-[140px]">
              <label className="text-gray-400 text-xs uppercase tracking-widest whitespace-nowrap">
                Language
              </label>
              <select
                value={language}
                onChange={(e) => handleLanguageChange(e.target.value)}
                className="bg-[#0f1117] border border-[#2d3148] text-white text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-[#6366f1] flex-1"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={handleStreamReview}
              disabled={streaming || loading}
              className="px-4 py-2 text-sm font-semibold rounded-lg bg-[#0f1117] border border-[#6366f1] text-[#6366f1] hover:bg-[#6366f118] transition-colors disabled:opacity-40 flex items-center gap-2"
            >
              {streaming ? (
                <>
                  <span className="w-3 h-3 border border-[#6366f1] border-t-transparent rounded-full animate-spin" />
                  Streaming…
                </>
              ) : (
                "⚡ Stream Review"
              )}
            </button>
            <button
              onClick={handleFullReview}
              disabled={loading || streaming}
              className="px-4 py-2 text-sm font-semibold rounded-lg bg-[#6366f1] hover:bg-[#5558e3] text-white transition-colors disabled:opacity-40 flex items-center gap-2"
            >
              {loading ? (
                <>
                  <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Analyzing…
                </>
              ) : (
                "🔬 Full Review"
              )}
            </button>
          </div>

          {/* Monaco */}
          <div className="flex-1 bg-[#1a1d2e] border border-[#2d3148] rounded-xl overflow-hidden shadow-[0_0_15px_rgba(99,102,241,0.1)] min-h-[300px]">
            <MonacoEditor
              language={language === "cpp" ? "cpp" : language}
              value={code}
              onChange={(v) => setCode(v ?? "")}
              theme="vs-dark"
              options={{
                fontSize: 13,
                fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                padding: { top: 16, bottom: 16 },
                lineNumbersMinChars: 3,
              }}
            />
          </div>

          {/* Context */}
          <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-3">
            <label className="text-gray-400 text-xs uppercase tracking-widest mb-2 block">
              Context{" "}
              <span className="text-gray-600 normal-case">(optional)</span>
            </label>
            <textarea
              rows={2}
              value={context}
              onChange={(e) => setContext(e.target.value)}
              placeholder="e.g. This function is called from a hot path, optimize for speed..."
              className="w-full bg-[#0f1117] text-gray-300 text-sm rounded-lg px-3 py-2 border border-[#2d3148] focus:outline-none focus:border-[#6366f1] resize-none placeholder-gray-600"
            />
          </div>
        </div>

        {/* ── Right: Results ── */}
        <div className="overflow-y-auto space-y-4 pr-1">
          {!review && !loading && !streaming && !streamText && (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                <div className="text-5xl mb-4">🔬</div>
                <p className="text-gray-400 text-sm">
                  Submit your code for an AI-powered review
                </p>
                <p className="text-gray-600 text-xs mt-1">
                  Stream for live feedback · Full for structured analysis
                </p>
              </div>
            </div>
          )}

          {(loading) && <ReviewSkeleton />}

          {streaming && (
            <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 rounded-full bg-[#6366f1] animate-pulse" />
                <span className="text-[#6366f1] text-sm font-medium">
                  Live Stream
                </span>
              </div>
              <pre className="text-gray-300 text-sm whitespace-pre-wrap font-mono leading-relaxed">
                {streamText}
                <span className="animate-pulse">▌</span>
              </pre>
            </div>
          )}

          {!streaming && streamText && !review && (
            <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
              <p className="text-gray-400 text-xs uppercase tracking-widest mb-3">
                Stream Result
              </p>
              <pre className="text-gray-300 text-sm whitespace-pre-wrap font-mono leading-relaxed">
                {streamText}
              </pre>
            </div>
          )}

          {review && (
            <>
              {/* Score + Reflection */}
              <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex items-start gap-4 flex-wrap">
                <ScoreBadge score={review.score} />
                <div className="flex-1 min-w-[150px]">
                  <p className="text-white font-semibold text-sm mb-1">
                    Quality Score
                  </p>
                  <div className="flex items-center gap-3 flex-wrap">
                    {review.complexity?.time && (
                      <span className="text-xs bg-[#6366f122] text-[#6366f1] px-2 py-1 rounded-full">
                        ⏱ {review.complexity.time}
                      </span>
                    )}
                    {review.complexity?.space && (
                      <span className="text-xs bg-[#22c55e22] text-[#22c55e] px-2 py-1 rounded-full">
                        💾 {review.complexity.space}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Pre-Computed Facts */}
              {(review.ast_facts || review.lint_facts) && (
                <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex gap-4 overflow-x-auto">
                  {review.ast_facts && (
                    <div className="flex-1 min-w-[250px]">
                      <p className="text-gray-400 text-xs uppercase tracking-widest mb-2">AST Analysis</p>
                      <pre className="text-xs text-gray-300 bg-[#0f1117] p-2 rounded-lg">{JSON.stringify(review.ast_facts, null, 2)}</pre>
                    </div>
                  )}
                  {review.lint_facts && (
                    <div className="flex-1 min-w-[250px]">
                      <p className="text-gray-400 text-xs uppercase tracking-widest mb-2">Linter Report</p>
                      <pre className="text-xs text-gray-300 bg-[#0f1117] p-2 rounded-lg">{JSON.stringify(review.lint_facts, null, 2)}</pre>
                    </div>
                  )}
                </div>
              )}

              {/* Summary */}
              {review.summary && (
                <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
                  <p className="text-gray-400 text-xs uppercase tracking-widest mb-2">
                    Summary
                  </p>
                  <p className="text-gray-300 text-sm leading-relaxed">
                    {review.summary}
                  </p>
                </div>
              )}

              {/* Annotations */}
              {annotations.length > 0 && (
                <Collapsible
                  title={`📌 Annotations (${annotations.length})`}
                  defaultOpen
                >
                  <div className="space-y-2">
                    {annotations.map((a: any, i: number) => (
                      <div
                        key={i}
                        className="flex gap-3 text-sm"
                      >
                        {a.line != null && (
                          <span className="text-[#6366f1] font-mono text-xs mt-0.5 shrink-0">
                            L{a.line}
                          </span>
                        )}
                        <span className="text-gray-300">{a.message}</span>
                      </div>
                    ))}
                  </div>
                </Collapsible>
              )}

              {/* Edge Cases */}
              {edgeCases.length > 0 && (
                <Collapsible title={`⚠️ Edge Cases (${edgeCases.length})`}>
                  <ul className="space-y-1.5">
                    {edgeCases.map((e: string, i) => (
                      <li key={i} className="text-gray-300 text-sm flex gap-2">
                        <span className="text-[#f59e0b] shrink-0">•</span>
                        {e}
                      </li>
                    ))}
                  </ul>
                </Collapsible>
              )}

              {/* Improvements */}
              {improvements.length > 0 && (
                <Collapsible
                  title={`🚀 Improvements (${improvements.length})`}
                >
                  <div className="space-y-4">
                    {improvements.map(
                      (
                        imp: any,
                        i
                      ) => (
                        <div key={i}>
                          <p className="text-gray-300 text-sm mb-2">
                            {imp.description}
                          </p>
                          {imp.code_after && (
                            <pre className="bg-[#0f1117] border border-[#2d3148] rounded-lg p-3 text-xs font-mono text-gray-300 overflow-x-auto">
                              {imp.code_after}
                            </pre>
                          )}
                          {imp.verification && (
                            <div className={`mt-2 px-3 py-2 rounded-lg border text-sm flex gap-2 ${imp.verification.verified ? 'bg-[#22c55e11] border-[#22c55e55] text-[#22c55e]' : 'bg-[#ef444411] border-[#ef444455] text-[#ef4444]'}`}>
                              <strong>{imp.verification.badge}</strong>: {imp.verification.message}
                            </div>
                          )}
                        </div>
                      )
                    )}
                  </div>
                </Collapsible>
              )}

              {/* Best Practices */}
              {bestPractices.length > 0 && (
                <Collapsible
                  title={`✅ Best Practices (${bestPractices.length})`}
                >
                  <ul className="space-y-1.5">
                    {bestPractices.map((b: string, i) => (
                      <li key={i} className="text-gray-300 text-sm flex gap-2">
                        <span className="text-[#22c55e] shrink-0">✓</span>
                        {b}
                      </li>
                    ))}
                  </ul>
                </Collapsible>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}