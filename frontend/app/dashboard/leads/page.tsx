"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Lead {
  id: string;
  name: string;
  email: string;
  phone: string;
  need: string;
  service: string;
  budget: string;
  urgency: string;
  source: string;
  comment: string;
  score: number;
  score_reasons: string[];
  status: string;
  created_at: string;
}

const STATUS_LABEL: Record<string, { label: string; style: string }> = {
  new: { label: "Nouveau", style: "bg-blue-100 text-blue-800" },
  contacted: { label: "Contacté", style: "bg-slate-100 text-slate-700" },
  qualified: { label: "Qualifié", style: "bg-amber-100 text-amber-800" },
  converted: { label: "Converti", style: "bg-green-100 text-green-800" },
  lost: { label: "Perdu", style: "bg-red-100 text-red-800" },
};

const URGENCY_LABEL: Record<string, string> = { low: "Faible", normal: "Normale", high: "Élevée", urgent: "Urgent" };

function scoreColor(score: number) {
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-amber-600";
  return "text-slate-500";
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Lead | null>(null);

  const load = useCallback(async () => {
    setLeads(await api<Lead[]>(`/api/leads${filter ? `?status=${filter}` : ""}`));
  }, [filter]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function updateStatus(id: string, status: string) {
    await api(`/api/leads/${id}`, { method: "PATCH", body: { status } });
    await load();
    if (selected) setSelected({ ...selected, status });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold">Prospects ({leads.length})</h1>
        <select className="input w-44" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">Tous</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Nom</th>
              <th className="text-left px-4 py-3">Contact</th>
              <th className="text-left px-4 py-3">Besoin</th>
              <th className="text-left px-4 py-3">Urgence</th>
              <th className="text-left px-4 py-3">Score</th>
              <th className="text-left px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {leads.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">
                Aucun prospect. L&apos;agent en crée automatiquement lors des demandes de devis ou d&apos;achat.
              </td></tr>
            )}
            {leads.map((l) => (
              <tr key={l.id} className="hover:bg-slate-50 cursor-pointer" onClick={() => setSelected(l)}>
                <td className="px-4 py-3 font-medium">{l.name || <span className="text-slate-400">Anonyme</span>}</td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {l.email && <div>{l.email}</div>}
                  {l.phone && <div>{l.phone}</div>}
                </td>
                <td className="px-4 py-3 max-w-[220px] truncate">{l.need || l.service || "—"}</td>
                <td className="px-4 py-3">
                  <span className={`badge ${l.urgency === "urgent" || l.urgency === "high" ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-600"}`}>
                    {URGENCY_LABEL[l.urgency] || l.urgency}
                  </span>
                </td>
                <td className={`px-4 py-3 font-bold ${scoreColor(l.score)}`}>
                  {l.score}
                  <span className="text-[10px] text-slate-400 font-normal ml-1">{l.source}</span>
                </td>
                <td className="px-4 py-3">
                  <span className={`badge ${STATUS_LABEL[l.status]?.style || "bg-slate-100"}`}>
                    {STATUS_LABEL[l.status]?.label || l.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">{selected.name || "Prospect anonyme"}</h2>
            <button className="text-slate-400 text-xl" onClick={() => setSelected(null)}>✕</button>
          </div>
          <div className="grid md:grid-cols-2 gap-4 text-sm">
            <div>
              <div className="text-slate-500">Email</div>
              <div>{selected.email || "—"}</div>
              <div className="text-slate-500 mt-2">Téléphone</div>
              <div>{selected.phone || "—"}</div>
              <div className="text-slate-500 mt-2">Service</div>
              <div>{selected.service || "—"}</div>
            </div>
            <div>
              <div className="text-slate-500">Besoin</div>
              <div>{selected.need || "—"}</div>
              <div className="text-slate-500 mt-2">Budget</div>
              <div>{selected.budget || "—"}</div>
              <div className="text-slate-500 mt-2">Créé le</div>
              <div>{new Date(selected.created_at).toLocaleString("fr-FR")}</div>
            </div>
          </div>
          <div className="bg-slate-50 rounded-lg p-3 text-sm">
            <div className="font-medium mb-1">Score explicable : <span className={scoreColor(selected.score)}>{selected.score}/100</span></div>
            <ul className="text-xs text-slate-600 space-y-0.5">
              {selected.score_reasons.map((r, i) => <li key={i}>• {r}</li>)}
            </ul>
          </div>
          <div className="flex gap-2 items-center">
            <span className="text-sm text-slate-500">Statut :</span>
            {Object.entries(STATUS_LABEL).map(([k, v]) => (
              <button key={k}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium ${selected.status === k ? v.style : "bg-slate-100 text-slate-500"}`}
                onClick={() => updateStatus(selected.id, k)}>
                {v.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
