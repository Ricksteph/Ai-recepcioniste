"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Analytics {
  intents: { intent: string; count: number }[];
  top_questions: { question: string; count: number }[];
  escalations: { reason: string; count: number }[];
  tools: { tool: string; status: string; count: number }[];
}

function Bar({ label, value, max, color = "bg-brand-500" }: { label: string; value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.max(3, Math.round((value / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <div className="w-44 truncate text-slate-600" title={label}>{label}</div>
      <div className="flex-1 bg-slate-100 rounded-full h-5 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="w-10 text-right font-medium">{value}</div>
    </div>
  );
}

export default function AnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null);

  useEffect(() => {
    api<Analytics>("/api/analytics/intents").then(setData).catch(() => {});
  }, []);

  const maxIntent = data ? Math.max(1, ...data.intents.map((i) => i.count)) : 1;
  const maxTool = data ? Math.max(1, ...data.tools.map((t) => t.count)) : 1;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Analytics</h1>
      {!data && <p className="text-slate-400">Chargement…</p>}

      {data && (
        <>
          <section className="card p-5">
            <h2 className="font-semibold mb-4">🎯 Intentions détectées</h2>
            {data.intents.length === 0 ? (
              <p className="text-sm text-slate-500">Aucune conversation encore.</p>
            ) : (
              <div className="space-y-2">
                {data.intents.map((i) => (
                  <Bar key={i.intent} label={i.intent} value={i.count} max={maxIntent} />
                ))}
              </div>
            )}
          </section>

          <div className="grid md:grid-cols-2 gap-6">
            <section className="card p-5">
              <h2 className="font-semibold mb-4">❓ Questions fréquentes</h2>
              {data.top_questions.length === 0 ? (
                <p className="text-sm text-slate-500">Aucune donnée.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {data.top_questions.map((q, i) => (
                    <li key={i} className="flex justify-between gap-3 bg-slate-50 rounded-lg px-3 py-2">
                      <span className="truncate">{q.question}</span>
                      <span className="badge bg-slate-200 text-slate-600 shrink-0">×{q.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card p-5">
              <h2 className="font-semibold mb-4">🙋 Escalades humaines</h2>
              {data.escalations.length === 0 ? (
                <p className="text-sm text-slate-500">Aucune escalade.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {data.escalations.map((e, i) => (
                    <li key={i} className="flex justify-between gap-3 bg-slate-50 rounded-lg px-3 py-2">
                      <span className="truncate">{e.reason}</span>
                      <span className="badge bg-amber-100 text-amber-800 shrink-0">×{e.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <section className="card p-5">
            <h2 className="font-semibold mb-4">🛠️ Exécutions d&apos;outils (vérifiées)</h2>
            {data.tools.length === 0 ? (
              <p className="text-sm text-slate-500">Aucune action exécutée.</p>
            ) : (
              <div className="space-y-2">
                {data.tools.map((t) => (
                  <Bar
                    key={`${t.tool}-${t.status}`}
                    label={`${t.tool} — ${t.status}`}
                    value={t.count}
                    max={maxTool}
                    color={t.status === "success" ? "bg-green-500" : t.status === "failed" ? "bg-red-500" : "bg-amber-500"}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
