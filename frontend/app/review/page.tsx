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

function MarkdownRenderer({ content }: { content: string }) {
  // Normalize literal \n in case backend serialized it poorly
  const normalized = (content ?? "").replace(/\\n/g, "\n");
  // Split content by code blocks and normal blocks
  const parts = normalized.split(/(```[\s\S]*?```)/g);
  
  const renderLineContent = (text: string) => {
    const boldParts = text.split(/(\*\*.*?\*\*)/g);
    return boldParts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i} className="font-bold text-white">{part.slice(2, -2)}</strong>;
      }
      return part;
    });
  };

  return (
    <div className="space-y-4 text-gray-300 text-sm leading-relaxed review-container">
      {parts.map((part, i) => {
        if (part.startsWith("```")) {
          // Code block
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
          // Inline formatting like headers, bullet points, checklists
          const lines = part.split("\n");
          return (
            <div key={i} className="space-y-2">
              {lines.map((line, j) => {
                const trimmed = line.trim();
                if (!trimmed) return null;
                
                // Headers (## or ###)
                if (trimmed.startsWith("## ")) {
                  const title = trimmed.replace("## ", "");
                  let bg = "rgba(99, 102, 241, 0.08)";
                  let border = "#6366f1";
                  
                  if (title.includes("🧩")) { bg = "rgba(59, 130, 246, 0.08)"; border = "#3b82f6"; }
                  else if (title.includes("🐛")) { bg = "rgba(239, 68, 68, 0.08)"; border = "#ef4444"; }
                  else if (title.includes("⏱")) { bg = "rgba(107, 114, 128, 0.08)"; border = "#6b7280"; }
                  else if (title.includes("💡")) { bg = "rgba(34, 197, 94, 0.08)"; border = "#22c55e"; }
                  else if (title.includes("🛠")) { bg = "rgba(245, 158, 11, 0.08)"; border = "#f59e0b"; }
                  else if (title.includes("✅")) { bg = "rgba(16, 185, 129, 0.08)"; border = "#10b981"; }
                  
                  return (
                    <h2
                      key={j}
                      className="text-base font-bold text-white mt-6 mb-3 px-4 py-2 rounded-lg border-l-4"
                      style={{ background: bg, borderLeftColor: border }}
                    >
                      {title}
                    </h2>
                  );
                }
                if (trimmed.startsWith("### ")) {
                  return (
                    <h3 key={j} className="text-sm font-semibold text-white mt-4 mb-2">
                      {trimmed.replace("### ", "")}
                    </h3>
                  );
                }

                // Complexity Highlights
                if (trimmed.toLowerCase().includes("overall time complexity")) {
                  const match = trimmed.match(/o\(.+?\)/i) || trimmed.match(/o\(.+\)/i);
                  const complexity = match ? match[0] : (trimmed.split(/overall time complexity:?/i)[1]?.trim().replace(/\*+/g, "") || "O(?)");
                  return (
                    <div key={j} className="my-3 bg-[#6366f1]/10 border border-[#6366f1]/20 rounded-xl px-4 py-3.5 flex items-center justify-between shadow-[0_0_15px_rgba(99,102,241,0.05)]">
                      <span className="font-semibold text-xs text-[#a5b4fc] uppercase tracking-wider flex items-center gap-1.5 font-sans">
                        ⏱️ Overall Time Complexity
                      </span>
                      <span className="font-mono text-sm font-bold bg-[#6366f1]/30 px-3 py-1 rounded-lg text-white border border-[#6366f1]/40 shadow-[0_0_10px_rgba(99,102,241,0.25)]">
                        {complexity}
                      </span>
                    </div>
                  );
                }
                if (trimmed.toLowerCase().includes("overall space complexity")) {
                  const match = trimmed.match(/o\(.+?\)/i) || trimmed.match(/o\(.+\)/i);
                  const complexity = match ? match[0] : (trimmed.split(/overall space complexity:?/i)[1]?.trim().replace(/\*+/g, "") || "O(?)");
                  return (
                    <div key={j} className="my-3 bg-[#22c55e]/10 border border-[#22c55e]/20 rounded-xl px-4 py-3.5 flex items-center justify-between shadow-[0_0_15px_rgba(34,197,94,0.05)]">
                      <span className="font-semibold text-xs text-[#86efac] uppercase tracking-wider flex items-center gap-1.5 font-sans">
                        💾 Overall Space Complexity
                      </span>
                      <span className="font-mono text-sm font-bold bg-[#22c55e]/30 px-3 py-1 rounded-lg text-white border border-[#22c55e]/40 shadow-[0_0_10px_rgba(34,197,94,0.25)]">
                        {complexity}
                      </span>
                    </div>
                  );
                }
                
                // Checkboxes / checklists
                if (trimmed.startsWith("- [x]") || trimmed.startsWith("- [ ]")) {
                  const checked = trimmed.startsWith("- [x]");
                  const text = trimmed.substring(5).trim();
                  return (
                    <div key={j} className="flex items-center gap-2 text-sm text-gray-300 py-0.5">
                      <span className={checked ? "text-[#22c55e]" : "text-gray-500 font-bold"}>
                        {checked ? "☑" : "☐"}
                      </span>
                      <span>{text}</span>
                    </div>
                  );
                }

                // Bullet points
                if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
                  return (
                    <div key={j} className="flex gap-2 text-sm text-gray-300 ml-4 py-0.5">
                      <span className="text-[#6366f1]">•</span>
                      <span>{renderLineContent(trimmed.substring(2))}</span>
                    </div>
                  );
                }
                
                // Severity tags or bold text color highlights
                let contentEl: React.ReactNode = renderLineContent(trimmed);
                if (trimmed.includes("🔴 Critical")) {
                  contentEl = <span className="text-red-400 font-medium">{renderLineContent(trimmed)}</span>;
                } else if (trimmed.includes("🟡 Warning")) {
                  contentEl = <span className="text-yellow-400 font-medium">{renderLineContent(trimmed)}</span>;
                } else if (trimmed.includes("🔵 Info")) {
                  contentEl = <span className="text-blue-400 font-medium">{renderLineContent(trimmed)}</span>;
                }
                
                return <p key={j} className="text-sm text-gray-300 leading-relaxed">{contentEl}</p>;
              })}
            </div>
          );
        }
      })}
    </div>
  );
}

export default function ReviewPage() {
  const router = useRouter();
  const [code, setCode] = useState(STARTER.python);
  const [language, setLanguage] = useState("python");
  const [context, setContext] = useState("");
  const [review, setReview] = useState<any | null>(null);
  const [streamText, setStreamText] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<ReturnType<typeof streamCodeReview> | null>(null);

  useEffect(() => {
    if (!localStorage.getItem("devbrain_token")) {
      router.push("/");
      return;
    }
    const prefillCode = sessionStorage.getItem("review_prefill_code");
    const prefillLang = sessionStorage.getItem("review_prefill_language");
    const prefillCtx = sessionStorage.getItem("review_prefill_context");
    
    if (prefillCode) {
      setCode(prefillCode);
      sessionStorage.removeItem("review_prefill_code");
    }
    if (prefillLang) {
      setLanguage(prefillLang);
      sessionStorage.removeItem("review_prefill_language");
    }
    if (prefillCtx) {
      setContext(prefillCtx);
      sessionStorage.removeItem("review_prefill_context");
    }
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

          {loading && <ReviewSkeleton />}

          {streaming && (
            <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
              <div className="flex items-center gap-2 mb-4 border-b border-[#2d3148] pb-3">
                <span className="w-2.5 h-2.5 rounded-full bg-[#6366f1] animate-pulse" />
                <span className="text-[#6366f1] text-xs font-semibold uppercase tracking-wider">
                  Live Stream Reviewing
                </span>
              </div>
              <MarkdownRenderer content={streamText} />
            </div>
          )}

          {!streaming && streamText && !review && (
            <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
              <div className="text-gray-400 text-xs uppercase tracking-wider mb-4 border-b border-[#2d3148] pb-3 font-semibold">
                Streaming Review Complete
              </div>
              <MarkdownRenderer content={streamText} />
            </div>
          )}

          {review && (
            <div className="space-y-4">
              {/* Pre-Analysis Hints */}
              {review.hints && (
                <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-4 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex items-center justify-between flex-wrap gap-3">
                  <div className="flex items-center gap-3">
                    <span className="text-xs bg-[#6366f122] text-[#6366f1] px-2.5 py-1 rounded-full font-semibold">
                      Lines: {review.lines}
                    </span>
                    <span className="text-xs bg-[#22c55e22] text-[#22c55e] px-2.5 py-1 rounded-full font-semibold">
                      Max Nesting Loop: {review.hints.loop_depth}
                    </span>
                    {review.hints.has_recursion && (
                      <span className="text-xs bg-[#ef444422] text-[#ef4444] px-2.5 py-1 rounded-full font-semibold">
                        Recursion Detected
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-gray-500 uppercase tracking-widest font-semibold">
                    v3.0 Reviewer
                  </span>
                </div>
              )}

              {/* Main Review Body */}
              <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-6 shadow-[0_0_15px_rgba(99,102,241,0.1)]">
                <MarkdownRenderer content={review.review} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}