"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Rule {
  id: string;
  name: string;
  kind: string;
  condition: Record<string, unknown>;
  action: string;
  params: Record<string, unknown>;
  description: string;
  priority: number;
  enabled: boolean;
}

const ACTION_LABEL: Record<string, { label: string; style: string }> = {
  allow: { label: "Autoriser", style: "bg-slate-100 text-slate-700" },
  block: { label: "Bloquer", style: "bg-red-100 text-red-700" },
  require_human: { label: "Transfert humain", style: "bg-amber-100 text-amber-800" },
  set: { label: "Contrainte", style: "bg-blue-100 text-blue-800" },
};

const PRESETS = [
  {
    name: "Pas de réservation le lundi",
    kind: "hours",
    condition: { field: "intent", op: "in", value: ["APPOINTMENT"] },
    action: "set",
    params: { closed_days: ["monday"] },
    description: "Le lundi est fermé pour les réservations",
  },
  {
    name: "Transfert sur urgence",
    kind: "transfer",
    condition: { field: "entities.urgency", op: "eq", value: "urgent" },
    action: "require_human",
    params: {},
    description: "Toute demande urgente part vers un humain",
  },
  {
    name: "Champ email obligatoire pour réserver",
    kind: "appointment",
    condition: { field: "intent", op: "in", value: ["APPOINTMENT"] },
    action: "set",
    params: { require_fields: ["date", "name", "email"] },
    description: "Exige l'email avant de créer un rendez-vous",
  },
];

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [editing, setEditing] = useState<Partial<Rule> | null>(null);
  const [busy, setBusy] = useState(false);
  const [simIntent, setSimIntent] = useState("APPOINTMENT");
  const [simResult, setSimResult] = useState<{ matched: { rule: string; action: string }[] } | null>(null);

  const load = useCallback(async () => {
    setRules(await api<Rule[]>("/api/rules"));
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function save() {
    if (!editing?.name) return;
    setBusy(true);
    try {
      const body = {
        name: editing.name,
        kind: editing.kind || "custom",
        condition: editing.condition || {},
        action: editing.action || "allow",
        params: editing.params || {},
        description: editing.description || "",
        priority: editing.priority ?? 100,
        enabled: editing.enabled ?? true,
      };
      if (editing.id) await api(`/api/rules/${editing.id}`, { method: "PUT", body });
      else await api("/api/rules", { method: "POST", body });
      setEditing(null);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function toggle(r: Rule) {
    await api(`/api/rules/${r.id}`, { method: "PUT", body: { ...r, enabled: !r.enabled } });
    await load();
  }

  async function remove(r: Rule) {
    if (!confirm(`Supprimer la règle « ${r.name} » ?`)) return;
    await api(`/api/rules/${r.id}`, { method: "DELETE" });
    await load();
  }

  async function simulate() {
    const data = await api<{ matched: { rule: string; action: string }[] }>("/api/rules/simulate", {
      method: "POST",
      body: { context: { intent: simIntent, entities: {}, unknown_streak: 0 } },
    });
    setSimResult(data);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Règles métier</h1>
        <button className="btn-primary" onClick={() => setEditing({ action: "allow", kind: "custom", priority: 100, enabled: true })}>
          + Nouvelle règle
        </button>
      </div>

      <p className="text-sm text-slate-500">
        Les règles s&apos;exécutent indépendamment du LLM et encadrent ses actions : horaires, conditions de
        réservation, transfert humain, limites d&apos;actions. Aucune règle ne peut être contournée par l&apos;IA.
      </p>

      {editing && (
        <div className="card p-5 space-y-3 border-brand-200">
          <h2 className="font-semibold">{editing.id ? "Modifier" : "Créer"} une règle</h2>
          <input className="input" placeholder="Nom de la règle" value={editing.name || ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="label">Action</label>
              <select className="input" value={editing.action} onChange={(e) => setEditing({ ...editing, action: e.target.value })}>
                <option value="allow">Autoriser</option>
                <option value="block">Bloquer</option>
                <option value="require_human">Exiger transfert humain</option>
                <option value="set">Appliquer contraintes</option>
              </select>
            </div>
            <div>
              <label className="label">Priorité</label>
              <input className="input" type="number" value={editing.priority ?? 100} onChange={(e) => setEditing({ ...editing, priority: Number(e.target.value) })} />
            </div>
            <div>
              <label className="label">Type</label>
              <select className="input" value={editing.kind} onChange={(e) => setEditing({ ...editing, kind: e.target.value })}>
                <option value="custom">Personnalisée</option>
                <option value="hours">Horaires</option>
                <option value="appointment">Rendez-vous</option>
                <option value="transfer">Transfert</option>
                <option value="unknown">Inconnu</option>
                <option value="action_limit">Limites d&apos;actions</option>
              </select>
            </div>
          </div>
          <div>
            <label className="label">Condition (JSON)</label>
            <textarea
              className="input font-mono text-xs" rows={3}
              value={JSON.stringify(editing.condition ?? {}, null, 0)}
              onChange={(e) => { try { setEditing({ ...editing, condition: JSON.parse(e.target.value) }); } catch {} }}
            />
            <p className="text-xs text-slate-400 mt-1">
              Ex. {'{"field": "intent", "op": "in", "value": ["APPOINTMENT"]}'} — ops: eq, ne, in, not_in, gte, lte, contains, exists
            </p>
          </div>
          <div>
            <label className="label">Paramètres (JSON, pour action=set)</label>
            <textarea
              className="input font-mono text-xs" rows={2}
              value={JSON.stringify(editing.params ?? {}, null, 0)}
              onChange={(e) => { try { setEditing({ ...editing, params: JSON.parse(e.target.value) }); } catch {} }}
            />
            <p className="text-xs text-slate-400 mt-1">
              min_lead_hours, max_days_ahead, require_fields, allowed_services, closed_days, max_actions_per_conversation, unknown_streak_handoff
            </p>
          </div>
          <input className="input" placeholder="Description / motif affiché" value={editing.description || ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
          <div className="flex gap-2">
            <button className="btn-primary" onClick={save} disabled={busy}>{busy ? "…" : "Enregistrer"}</button>
            <button className="btn-secondary" onClick={() => setEditing(null)}>Annuler</button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {rules.map((r) => (
          <div key={r.id} className="card p-4 flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-sm">{r.name}</span>
                <span className={`badge ${ACTION_LABEL[r.action]?.style || "bg-slate-100"}`}>
                  {ACTION_LABEL[r.action]?.label || r.action}
                </span>
                <span className="text-xs text-slate-400">priorité {r.priority}</span>
              </div>
              {r.description && <p className="text-xs text-slate-500 mt-1">{r.description}</p>}
              <p className="text-[10px] font-mono text-slate-400 mt-1 truncate">{JSON.stringify(r.condition)}</p>
            </div>
            <button className="btn-secondary text-xs" onClick={() => toggle(r)}>{r.enabled ? "Désactiver" : "Activer"}</button>
            <button className="btn-secondary text-xs" onClick={() => setEditing(r)}>Modifier</button>
            <button className="btn-danger text-xs" onClick={() => remove(r)}>Suppr.</button>
          </div>
        ))}
        {rules.length === 0 && <p className="text-sm text-slate-500">Aucune règle. Ajoutez-en depuis un préréglage :</p>}
      </div>

      <div className="card p-5 space-y-3">
        <h2 className="font-semibold">⚡ Préréglages</h2>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.name}
              className="btn-secondary text-xs"
              onClick={async () => {
                await api("/api/rules", { method: "POST", body: { ...p, enabled: true, priority: 50 } });
                await load();
              }}
            >
              + {p.name}
            </button>
          ))}
        </div>
      </div>

      <div className="card p-5 space-y-3">
        <h2 className="font-semibold">🧪 Simuler l&apos;évaluation</h2>
        <div className="flex gap-2">
          <select className="input w-64" value={simIntent} onChange={(e) => setSimIntent(e.target.value)}>
            {["APPOINTMENT", "CANCELLATION", "RESCHEDULING", "COMPLAINT", "HUMAN_TRANSFER", "PRICE_REQUEST", "UNKNOWN"].map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
          <button className="btn-primary" onClick={simulate}>Simuler</button>
        </div>
        {simResult && (
          <div className="text-sm">
            {simResult.matched.length === 0 ? (
              <p className="text-slate-500">Aucune règle ne s&apos;applique à ce contexte.</p>
            ) : (
              <ul className="space-y-1">
                {simResult.matched.map((m, i) => (
                  <li key={i} className="bg-slate-50 rounded px-3 py-1.5">
                    <b>{m.rule}</b> → {m.action}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
