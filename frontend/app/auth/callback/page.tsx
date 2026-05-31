"use client";

// =============================================================================
// DevBrain AI — Auth Callback Page (/auth/callback)
// GitHub OAuth redirects here with ?token=<jwt>.
// Stores token in localStorage and forwards to /dashboard.
// =============================================================================

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Brain, AlertTriangle } from "lucide-react";
import { setToken } from "@/lib/api";

type Status = "loading" | "success" | "error";

function AuthCallbackContent() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<Status>("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const token = searchParams.get("token");

    if (!token) {
      setStatus("error");
      setMessage("No token received from GitHub. Please try logging in again.");
      return;
    }

    // Store token and redirect
    setToken(token);
    setStatus("success");

    const id = setTimeout(() => {
      router.replace("/dashboard");
    }, 800);

    return () => clearTimeout(id);
  }, [searchParams, router]);

  return (
    <div className="min-h-screen bg-[#0f1117] flex items-center justify-center px-4">
      <div className="card p-10 max-w-sm w-full text-center space-y-5">

        {/* Logo */}
        <div className="flex justify-center">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center
                          ${status === "error" ? "bg-red-500/20" : "bg-[#6366f1]/20"}`}>
            {status === "error"
              ? <AlertTriangle size={24} className="text-red-400" />
              : <Brain size={24} className="text-[#6366f1]" />
            }
          </div>
        </div>

        {/* Status text */}
        {status === "loading" && (
          <>
            <h1 className="text-xl font-bold text-white">Authenticating…</h1>
            <p className="text-gray-400 text-sm">Verifying your GitHub credentials.</p>
            {/* Spinner */}
            <div className="flex justify-center">
              <div className="w-6 h-6 border-2 border-[#6366f1]/30 border-t-[#6366f1]
                              rounded-full animate-spin" />
            </div>
          </>
        )}

        {status === "success" && (
          <>
            <h1 className="text-xl font-bold text-white">Welcome to DevBrain!</h1>
            <p className="text-gray-400 text-sm">Login successful — taking you to your dashboard…</p>
            <div className="flex justify-center">
              <div className="w-6 h-6 border-2 border-[#22c55e]/30 border-t-[#22c55e]
                              rounded-full animate-spin" />
            </div>
          </>
        )}

        {status === "error" && (
          <>
            <h1 className="text-xl font-bold text-white">Authentication Failed</h1>
            <p className="text-gray-400 text-sm">{message}</p>
            <button
              onClick={() => router.push("/")}
              className="btn-primary w-full mt-2"
            >
              Back to Home
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#0f1117] flex items-center justify-center"><div className="text-white">Loading...</div></div>}>
      <AuthCallbackContent />
    </Suspense>
  );
}