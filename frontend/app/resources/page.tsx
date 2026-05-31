"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { searchResources } from "@/lib/api";
import type { Resource } from "@/lib/types";

const QUICK_TOPICS = [
  "Trees",
  "Dynamic Programming",
  "System Design",
  "Python",
  "TypeScript",
  "SQL",
  "Docker",
  "Kubernetes",
  "GraphQL",
  "Concurrency",
  "Redis",
  "React",
  "LLMs",
  "Sorting Algorithms",
];

const DIFFICULTIES = [
  { value: "", label: "All Levels" },
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
];

const SOURCE_COLORS: Record<string, { bg: string; color: string }> = {
  "Official Docs": { bg: "#6366f122", color: "#6366f1" },
  GitHub: { bg: "#22c55e22", color: "#22c55e" },
  Tutorial: { bg: "#f59e0b22", color: "#f59e0b" },
  Article: { bg: "#ec489922", color: "#ec4899" },
};

function sourceBadgeStyle(source: string) {
  return (
    SOURCE_COLORS[source] ?? { bg: "#2d3148", color: "#9ca3af" }
  );
}

function ResourceCard({ resource }: { resource: Resource }) {
  const [expanded, setExpanded] = useState(false);
  const { bg, color } = sourceBadgeStyle(resource.source);
  const diffColors: Record<string, string> = {
    beginner: "#22c55e",
    intermediate: "#6366f1",
    advanced: "#ef4444",
  };
  const diffColor = diffColors[resource.difficulty] ?? "#9ca3af";

  return (
    <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-white font-semibold text-sm leading-snug flex-1">
          {resource.title}
        </h3>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ background: bg, color }}
          >
            {resource.source}
          </span>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full capitalize"
            style={{ background: `${diffColor}22`, color: diffColor }}
          >
            {resource.difficulty}
          </span>
        </div>
      </div>

      {resource.description && (
        <p className="text-gray-400 text-xs leading-relaxed line-clamp-2">
          {resource.description}
        </p>
      )}

      {resource.why_recommended && (
        <div>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-[#6366f1] text-xs font-medium hover:underline flex items-center gap-1"
          >
            {expanded ? "▴" : "▾"} Why recommended?
          </button>
          {expanded && (
            <p className="text-gray-400 text-xs mt-2 leading-relaxed bg-[#0f1117] rounded-lg px-3 py-2">
              {resource.why_recommended}
            </p>
          )}
        </div>
      )}

      <a
        href={resource.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-auto inline-flex items-center gap-1.5 text-sm font-semibold text-[#6366f1] hover:text-white bg-[#6366f118] hover:bg-[#6366f1] px-4 py-2 rounded-lg transition-colors w-fit"
      >
        Open Resource ↗
      </a>
    </div>
  );
}

function ResourceCardSkeleton() {
  return (
    <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-5 animate-pulse space-y-3">
      <div className="h-4 bg-[#2d3148] rounded w-3/4" />
      <div className="h-3 bg-[#2d3148] rounded w-full" />
      <div className="h-3 bg-[#2d3148] rounded w-2/3" />
      <div className="h-8 bg-[#2d3148] rounded-lg w-28 mt-2" />
    </div>
  );
}

function ResourcesPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [topic, setTopic] = useState(searchParams.get("topic") ?? "");
  const [difficulty, setDifficulty] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);
  const [narrative, setNarrative] = useState("");
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem("devbrain_token")) router.push("/");
  }, [router]);

  useEffect(() => {
    const t = searchParams.get("topic");
    if (t) {
      setTopic(t);
      doSearch(t, "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const doSearch = async (t: string, d: string) => {
    if (!t.trim()) return;
    setLoading(true);
    setSearched(true);
    try {
      const result = await searchResources(t, (d || undefined) as any);
      if (Array.isArray(result)) {
        setResources(result);
      } else {
        setResources(result.resources ?? []);
        setNarrative(result.learning_path ?? "");
      }
    } catch {
      setResources([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = () => doSearch(topic, difficulty);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  const handleTopicChip = (t: string) => {
    setTopic(t);
    doSearch(t, difficulty);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white tracking-tight">
          Resource Finder
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          RAG-powered recommendations tailored to your skill gaps
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[220px_1fr] gap-6">
        {/* ── Left sidebar: topic chips ── */}
        <aside>
          <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-4 shadow-[0_0_15px_rgba(99,102,241,0.1)] sticky top-4">
            <p className="text-gray-400 text-xs uppercase tracking-widest mb-3 font-medium">
              Quick Topics
            </p>
            <div className="flex flex-wrap gap-2">
              {QUICK_TOPICS.map((t) => (
                <button
                  key={t}
                  onClick={() => handleTopicChip(t)}
                  className={`text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${
                    topic === t
                      ? "bg-[#6366f1] border-[#6366f1] text-white"
                      : "bg-[#0f1117] border-[#2d3148] text-gray-400 hover:border-[#6366f1] hover:text-white"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* ── Main content ── */}
        <div className="space-y-5">
          {/* Search bar */}
          <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-4 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex items-center gap-3 flex-wrap">
            <input
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search topic, e.g. 'binary search trees'…"
              className="flex-1 min-w-[200px] bg-[#0f1117] border border-[#2d3148] text-white text-sm rounded-lg px-4 py-2.5 focus:outline-none focus:border-[#6366f1] placeholder-gray-600"
            />
            <select
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
              className="bg-[#0f1117] border border-[#2d3148] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#6366f1]"
            >
              {DIFFICULTIES.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
            <button
              onClick={handleSearch}
              disabled={loading || !topic.trim()}
              className="px-5 py-2.5 bg-[#6366f1] hover:bg-[#5558e3] text-white text-sm font-semibold rounded-lg transition-colors disabled:opacity-40"
            >
              {loading ? "Searching…" : "Search"}
            </button>
          </div>

          {/* Learning path narrative */}
          {narrative && (
            <div className="bg-[#1a1d2e] border border-[#6366f133] rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.15)]">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-2 h-2 rounded-full bg-[#6366f1]" />
                <span className="text-[#6366f1] text-xs font-semibold uppercase tracking-widest">
                  Learning Path
                </span>
              </div>
              <p className="text-gray-300 text-sm leading-relaxed">{narrative}</p>
            </div>
          )}

          {/* Results */}
          {loading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[...Array(4)].map((_, i) => (
                <ResourceCardSkeleton key={i} />
              ))}
            </div>
          ) : resources.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {resources.map((r, i) => (
                <ResourceCard key={i} resource={r} />
              ))}
            </div>
          ) : searched && !loading ? (
            <div className="text-center py-16">
              <div className="text-4xl mb-3">🔍</div>
              <p className="text-gray-400 text-sm">No resources found.</p>
              <p className="text-gray-600 text-xs mt-1">
                Try a different topic or difficulty level.
              </p>
            </div>
          ) : (
            <div className="text-center py-16">
              <div className="text-4xl mb-3">📚</div>
              <p className="text-gray-400 text-sm">
                Pick a topic chip or search above to find resources.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ResourcesPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-screen"><div className="w-10 h-10 border-2 border-[#6366f1] border-t-transparent rounded-full animate-spin" /></div>}>
      <ResourcesPageContent />
    </Suspense>
  );
}