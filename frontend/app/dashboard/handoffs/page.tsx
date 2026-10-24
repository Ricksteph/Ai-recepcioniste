"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

interface Handoff {
  id: string;
  conversation_id: string;
  reason: string;
  summary: string;
  status: string;
  created_at: string;
}

const STATUS_LABEL: Record<string, { label: string; style: string }> = {
  pending: { label: "En attente", style: "bg-amber-100 text-amber-800" },
  claimed: { label: "Pris en charge", style: "bg-blue-100 text-blue-800" },
  resolved: { label: "Résolu", style: "bg-green-100 text-green-800" },
};

export default function HandoffsPage() {
  const [rows, setRows] = useState<Handoff[]>([]);
  const [filter, setFilter] = useState("pending");

  const load = useCallback(async () => {
    setRows(await api<Handoff[]>(`/api/handoffs${filter ? `?status=${filter}` : ""}`));
  }, [filter]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function claim(id: string) {
    await api(`/api/handoffs/${id}/claim`, { method: "POST" });
    await load();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">Transferts humains</h1>
          <p className="text-sm text-slate-500">
            Conversations que l&apos;agent n&apos;a pas traitées seul : plainte, demande explicite, information inconnue, urgence ou échec d&apos;action.
          </p>
        </div>
        <select className="input w-44" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="pending">En attente</option>
          <option value="claimed">Pris en charge</option>
          <option value="resolved">Résolus</option>
          <option value="">Tous</option>
        </select>
      </div>

      <div className="space-y-3">
        {rows.length === 0 && (
          <div className="card p-8 text-center text-slate-500 text-sm">
            Aucun transfert {filter && `« ${STATUS_LABEL[filter]?.label.toLowerCase() || filter} »`}. 🎉
          </div>
        )}
        {rows.map((h) => (
          <div key={h.id} className="card p-5">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium">{h.reason}</span>
                  <span className={`badge ${STATUS_LABEL[h.status]?.style || "bg-slate-100"}`}>
                    {STATUS_LABEL[h.status]?.label || h.status}
                  </span>
                </div>
                <div className="text-xs text-slate-400 mt-0.5">
                  {new Date(h.created_at).toLocaleString("fr-FR")}
                </div>
              </div>
              <div className="flex gap-2">
                {h.status === "pending" && (
                  <button className="btn-primary text-xs" onClick={() => claim(h.id)}>✋ Prendre en charge</button>
                )}
                <Link href={`/dashboard/conversations?open=${h.conversation_id}`} className="btn-secondary text-xs">
                  Ouvrir la conversation →
                </Link>
              </div>
            </div>
            <pre className="mt-3 bg-slate-50 rounded-lg p-3 text-xs text-slate-700 whitespace-pre-wrap font-sans border border-slate-100">
              {h.summary}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}
