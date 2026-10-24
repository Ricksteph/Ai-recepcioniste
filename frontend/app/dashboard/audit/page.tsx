"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface AuditRow {
  id: string;
  actor: string;
  action: string;
  object_type: string;
  object_id: string;
  result: string;
  details: Record<string, unknown>;
  created_at: string;
}

const CATEGORIES = [
  ["", "Tous"],
  ["auth.", "Authentification"],
  ["tenant.", "Entreprise"],
  ["receptionist.", "Réceptionniste"],
  ["knowledge.", "Knowledge Base"],
  ["rule.", "Règles"],
  ["conversation.", "Conversations"],
  ["sandbox.", "Sandbox"],
  ["lead.", "Prospects"],
  ["appointment.", "Rendez-vous"],
  ["handoff.", "Transferts"],
  ["user.", "Utilisateurs"],
  ["onboarding.", "Onboarding"],
];

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [prefix, setPrefix] = useState("");

  useEffect(() => {
    api<AuditRow[]>(`/api/audit?limit=200${prefix ? `&action=${prefix}` : ""}`).then(setRows).catch(() => {});
  }, [prefix]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">Journal d&apos;audit</h1>
        <p className="text-sm text-slate-500">
          Traçabilité des actions critiques : utilisateur, date, action, objet, résultat.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {CATEGORIES.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setPrefix(key)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium ${
              prefix === key ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Acteur</th>
              <th className="text-left px-4 py-3">Action</th>
              <th className="text-left px-4 py-3">Objet</th>
              <th className="text-left px-4 py-3">Résultat</th>
              <th className="text-left px-4 py-3">Détails</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">Aucune entrée.</td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-4 py-2.5 text-xs text-slate-500 whitespace-nowrap">
                  {new Date(r.created_at).toLocaleString("fr-FR")}
                </td>
                <td className="px-4 py-2.5 text-xs">{r.actor}</td>
                <td className="px-4 py-2.5"><code className="text-xs bg-slate-100 rounded px-1.5 py-0.5">{r.action}</code></td>
                <td className="px-4 py-2.5 text-xs text-slate-500">
                  {r.object_type && `${r.object_type}${r.object_id ? ` #${r.object_id.slice(0, 8)}` : ""}`}
                </td>
                <td className="px-4 py-2.5">
                  <span className={`badge ${r.result === "success" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>
                    {r.result}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-slate-500 max-w-[280px] truncate" title={JSON.stringify(r.details)}>
                  {Object.keys(r.details || {}).length > 0 ? JSON.stringify(r.details) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
