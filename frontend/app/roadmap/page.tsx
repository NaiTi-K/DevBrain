"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getRoadmap, generateRoadmap, patchRoadmap } from "@/lib/api";
import type { Roadmap } from "@/lib/types";

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

type Week = {
  week: number;
  focus: string;
  topics: string[];
  reason?: string;
  completed?: boolean;
  completed_topics?: string[];
};

function WeekCard({ 
  week, 
  index, 
  onToggle, 
  onToggleTopic 
}: { 
  week: Week; 
  index: number; 
  onToggle: () => void; 
  onToggleTopic: (topic: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isFirst = index === 0;

  return (
    <div className="flex gap-4">
      {/* Timeline stem */}
      <div className="flex flex-col items-center">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0 border-2"
          style={{
            background: week.completed ? "#22c55e" : isFirst ? "#6366f1" : "#1a1d2e",
            borderColor: week.completed ? "#22c55e" : isFirst ? "#6366f1" : "#2d3148",
            color: week.completed || isFirst ? "white" : "#9ca3af",
          }}
        >
          {week.completed ? "✓" : week.week}
        </div>
        <div className="flex-1 w-px bg-[#2d3148] mt-1" />
      </div>

      {/* Card */}
      <div className="flex-1 pb-6">
        <div
          className="bg-[#1a1d2e] border rounded-xl p-5 shadow-[0_0_15px_rgba(99,102,241,0.1)] transition-all duration-300"
          style={{ 
            borderColor: week.completed ? "#22c55e33" : isFirst ? "#6366f133" : "#2d3148",
            opacity: week.completed ? 0.75 : 1
          }}
        >
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex items-center gap-3">
              <input 
                type="checkbox"
                checked={week.completed ?? false}
                onChange={onToggle}
                className="w-4 h-4 rounded border-[#2d3148] bg-[#0f1117] text-[#6366f1] focus:ring-[#6366f1] focus:ring-offset-[#1a1d2e] cursor-pointer"
              />
              <div>
                <p className="text-gray-400 text-xs uppercase tracking-widest font-medium mb-0.5">
                  Week {week.week}
                </p>
                <h3 className={`font-semibold text-base transition-all ${week.completed ? 'text-gray-400 line-through' : 'text-white'}`}>{week.focus}</h3>
              </div>
            </div>
            <div className="flex gap-2 items-center">
              {week.completed ? (
                <span className="text-xs font-semibold px-2 py-1 rounded-full bg-[#22c55e22] text-[#22c55e] shrink-0">
                  Completed
                </span>
              ) : isFirst ? (
                <span className="text-xs font-semibold px-2 py-1 rounded-full bg-[#6366f122] text-[#6366f1] shrink-0">
                  Current
                </span>
              ) : null}
            </div>
          </div>

          {/* Topic checklist (subparts) */}
          <div className="space-y-2.5 mt-4 border-t border-[#2d3148]/50 pt-4">
            <p className="text-gray-400 text-[10px] uppercase tracking-widest font-semibold mb-2">
              Sub-tasks ({week.completed_topics?.length ?? 0} of {week.topics?.length ?? 0})
            </p>
            <div className="grid grid-cols-1 gap-2">
              {week.topics?.map((t) => {
                const isTopicDone = week.completed_topics?.includes(t) ?? false;
                return (
                  <div 
                    key={t} 
                    className="flex items-center justify-between bg-[#0f1117]/60 border rounded-xl px-4 py-2.5 hover:border-[#6366f1]/40 transition-all duration-300"
                    style={{
                      borderColor: isTopicDone ? "rgba(34, 197, 94, 0.2)" : "rgba(45, 49, 72, 0.6)",
                      background: isTopicDone ? "rgba(34, 197, 94, 0.02)" : "rgba(15, 17, 23, 0.6)"
                    }}
                  >
                    <label className="flex items-center gap-3 cursor-pointer text-gray-300 hover:text-white transition-colors flex-1 select-none">
                      <input 
                        type="checkbox"
                        checked={isTopicDone}
                        onChange={() => onToggleTopic(t)}
                        className="w-4 h-4 rounded border-[#2d3148] bg-[#1a1d2e] text-[#22c55e] focus:ring-[#22c55e] cursor-pointer"
                      />
                      <span className={`text-xs ${isTopicDone ? 'line-through text-gray-500' : 'text-gray-200 font-medium'}`}>
                        {t}
                      </span>
                    </label>
                    <Link 
                      href={`/resources?topic=${encodeURIComponent(t)}`}
                      className="text-[10px] text-[#6366f1] hover:text-[#818cf8] hover:underline font-bold uppercase tracking-wider ml-2"
                    >
                      Learn →
                    </Link>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Reason */}
          {week.reason && (
            <div className="mt-4">
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-[#6366f1] text-xs font-medium hover:underline flex items-center gap-1"
              >
                {expanded ? "▴" : "▾"} Why this week?
              </button>
              {expanded && (
                <p className="text-gray-400 text-xs mt-2 leading-relaxed bg-[#0f1117] rounded-lg px-3 py-2">
                  {week.reason}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function RoadmapPage() {
  const router = useRouter();
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [targetRole, setTargetRole] = useState(TARGET_ROLES[2]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!localStorage.getItem("devbrain_token")) {
      router.push("/");
      return;
    }
    getRoadmap()
      .then(setRoadmap)
      .catch(() => setRoadmap(null))
      .finally(() => setLoading(false));
  }, [router]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError("");
    try {
      const r = await generateRoadmap(targetRole);
      setRoadmap(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const handleToggleComplete = async (weekNum: number) => {
    if (!roadmap) return;
    const updatedWeeks = (roadmap.weeks ?? []).map((w: Week) => {
      if (w.week === weekNum) {
        const nextCompleted = !w.completed;
        return { 
          ...w, 
          completed: nextCompleted,
          completed_topics: nextCompleted ? [...w.topics] : []
        };
      }
      return w;
    });
    const updatedPlan = { ...roadmap.plan, weeks: updatedWeeks };
    try {
      const r = await patchRoadmap(roadmap.id, updatedPlan);
      setRoadmap(r);
    } catch (err) {
      console.error("Failed to update roadmap", err);
    }
  };

  const handleToggleTopic = async (weekNum: number, topic: string) => {
    if (!roadmap) return;
    const updatedWeeks = (roadmap.weeks ?? []).map((w: Week) => {
      if (w.week === weekNum) {
        const completedTopics = w.completed_topics ?? [];
        const isCompleted = completedTopics.includes(topic);
        const nextCompletedTopics = isCompleted 
          ? completedTopics.filter(t => t !== topic) 
          : [...completedTopics, topic];
          
        const allCompleted = w.topics.every(t => nextCompletedTopics.includes(t));
        
        return {
          ...w,
          completed_topics: nextCompletedTopics,
          completed: allCompleted
        };
      }
      return w;
    });
    const updatedPlan = { ...roadmap.plan, weeks: updatedWeeks };
    try {
      const r = await patchRoadmap(roadmap.id, updatedPlan);
      setRoadmap(r);
    } catch (err) {
      console.error("Failed to update roadmap", err);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="w-10 h-10 border-2 border-[#6366f1] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const weeks: Week[] = roadmap?.weeks ?? [];
  const totalTopics = weeks.reduce((sum, w) => sum + (w.topics?.length ?? 0), 0);
  const completedTopics = weeks.reduce((sum, w) => sum + (w.completed_topics?.length ?? 0), 0);
  const percentCompleted = totalTopics > 0 ? Math.round((completedTopics / totalTopics) * 100) : 0;

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white tracking-tight">
          Learning Roadmap
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          Personalized weekly plan based on your skill profile
        </p>
      </div>

      {!roadmap ? (
        /* ── Generate form ── */
        <div className="bg-[#1a1d2e] border border-[#2d3148] rounded-xl p-8 shadow-[0_0_15px_rgba(99,102,241,0.1)] max-w-md">
          <div className="text-4xl mb-5">🗺️</div>
          <h2 className="text-white text-xl font-bold mb-2">
            Generate Your Roadmap
          </h2>
          <p className="text-gray-400 text-sm mb-6 leading-relaxed">
            Select your target role and DevBrain will create a personalized
            week-by-week learning plan based on your GitHub skill gaps.
          </p>
          <div className="space-y-4">
            <div>
              <label className="text-gray-400 text-xs uppercase tracking-widest mb-2 block">
                Target Role
              </label>
              <select
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                className="w-full bg-[#0f1117] border border-[#2d3148] text-white text-sm rounded-lg px-4 py-2.5 focus:outline-none focus:border-[#6366f1]"
              >
                {TARGET_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            {error && (
              <p className="text-[#ef4444] text-sm bg-[#ef444411] rounded-lg px-4 py-2">
                {error}
              </p>
            )}
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="w-full py-3 bg-[#6366f1] hover:bg-[#5558e3] text-white font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {generating ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Generating roadmap…
                </>
              ) : (
                "Generate Roadmap →"
              )}
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Header info */}
          <div className="bg-[#1a1d2e] border border-[#6366f133] rounded-xl p-5 mb-8 shadow-[0_0_15px_rgba(99,102,241,0.15)] flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex flex-wrap gap-6">
              <div>
                <p className="text-gray-400 text-xs uppercase tracking-widest mb-1">
                  Target Role
                </p>
                <p className="text-white font-semibold">{roadmap.target_role}</p>
              </div>
              <div>
                <p className="text-gray-400 text-xs uppercase tracking-widest mb-1">
                  Duration
                </p>
                <p className="text-white font-semibold">
                  {weeks.length} weeks
                </p>
              </div>
              <div>
                <p className="text-gray-400 text-xs uppercase tracking-widest mb-1">
                  Topics Completed
                </p>
                <p className="text-[#22c55e] font-semibold">
                  {completedTopics} of {totalTopics} ({percentCompleted}%)
                </p>
              </div>
            </div>
            
            <div className="flex items-center gap-4 w-full md:w-auto">
              <div className="flex-1 md:w-32 bg-[#0f1117] h-2 rounded-full overflow-hidden">
                <div 
                  className="bg-[#22c55e] h-full rounded-full transition-all duration-500"
                  style={{ width: `${percentCompleted}%` }}
                />
              </div>
              <button
                onClick={() => setRoadmap(null)}
                className="text-sm text-gray-400 hover:text-white border border-[#2d3148] px-4 py-2 rounded-lg transition-colors shrink-0"
              >
                Regenerate
              </button>
            </div>
          </div>

          {/* Timeline */}
          <div>
            {weeks.map((week, i) => (
              <WeekCard 
                key={week.week} 
                week={week} 
                index={i} 
                onToggle={() => handleToggleComplete(week.week)} 
                onToggleTopic={(topic) => handleToggleTopic(week.week, topic)} 
              />
            ))}
            {/* End marker */}
            <div className="flex gap-4">
              <div className="w-9 flex justify-center">
                <div className="w-3 h-3 rounded-full bg-[#22c55e] border-2 border-[#22c55e33]" />
              </div>
              <p className="text-[#22c55e] text-sm font-medium pb-6">
                🎯 Goal reached — {roadmap.target_role}
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}