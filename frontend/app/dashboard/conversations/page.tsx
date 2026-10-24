"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Conversation, Message } from "@/lib/api";

interface ActionRow {
  id: string;
  tool: string;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  status: string;
  created_at: string;
}

const STATUS_LABEL: Record<string, string> = {
  open: "Ouverte", handoff: "Transférée", resolved: "Résolue", closed: "Clôturée",
};

export default function ConversationsPage() {
  const [rows, setRows] = useState<Conversation[]>([]);
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [actions, setActions] = useState<ActionRow[]>([]);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const data = await api<Conversation[]>(`/api/conversations${status ? `?status=${status}` : ""}`);
    setRows(data);
  }, [status]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function open(id: string) {
    setSelected(id);
    const [msgs, acts] = await Promise.all([
      api<Message[]>(`/api/conversations/${id}/messages`),
      api<ActionRow[]>(`/api/conversations/${id}/actions`),
    ]);
    setMessages(msgs);
    setActions(acts);
  }

  async function sendReply() {
    if (!reply.trim() || !selected) return;
    setBusy(true);
    try {
      await api(`/api/conversations/${selected}/reply`, { method: "POST", body: { message: reply } });
      setReply("");
      await open(selected);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function resolve() {
    if (!selected) return;
    await api(`/api/conversations/${selected}/resolve`, { method: "POST" });
    await open(selected);
    await load();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold">Conversations</h1>
        <select className="input w-48" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Tous les statuts</option>
          <option value="open">Ouvertes</option>
          <option value="handoff">Transférées</option>
          <option value="resolved">Résolues</option>
        </select>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card divide-y divide-slate-100 max-h-[70vh] overflow-y-auto">
          {rows.length === 0 && <p className="p-4 text-sm text-slate-500">Aucune conversation.</p>}
          {rows.map((c) => (
            <button
              key={c.id}
              onClick={() => open(c.id)}
              className={`w-full text-left p-4 hover:bg-slate-50 ${selected === c.id ? "bg-brand-50" : ""}`}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-sm truncate">
                  {c.contact_name || "Visiteur anonyme"} · {c.channel === "sandbox" ? "🧪 sandbox" : "💬 web chat"}
                </span>
                <span className={`badge ${
                  c.status === "handoff" ? "bg-amber-100 text-amber-800" :
                  c.status === "resolved" ? "bg-green-100 text-green-800" :
                  "bg-blue-100 text-blue-800"
                }`}>
                  {STATUS_LABEL[c.status] || c.status}
                </span>
              </div>
              <div className="text-xs text-slate-500 mt-1 flex gap-2">
                <span>{c.intent || "—"}</span>
                <span>·</span>
                <span>{new Date(c.created_at).toLocaleString("fr-FR")}</span>
              </div>
              {c.summary && <p className="text-xs text-slate-600 mt-1 line-clamp-2">{c.summary}</p>}
            </button>
          ))}
        </div>

        <div className="card p-4 max-h-[70vh] overflow-y-auto">
          {!selected && <p className="text-sm text-slate-500">Sélectionnez une conversation pour voir les messages.</p>}
          {selected && (
            <div className="space-y-4">
              <div className="flex gap-2">
                <button className="btn-secondary text-xs" onClick={resolve}>✓ Marquer résolue</button>
              </div>
              <div className="space-y-2">
                {messages.map((m) => (
                  <div key={m.id} className={`rounded-lg px-3 py-2 text-sm ${
                    m.role === "user" ? "bg-slate-100" :
                    m.role === "human_agent" ? "bg-green-100" : "bg-brand-50"
                  }`}>
                    <div className="text-[10px] uppercase text-slate-400 mb-1">
                      {m.role === "user" ? "Visiteur" : m.role === "human_agent" ? "Agent humain" : "Assistant IA"}
                      {m.intent && ` · ${m.intent}`}
                    </div>
                    <div className="whitespace-pre-wrap">{m.content}</div>
                    {Array.isArray(m.sources) && m.sources.length > 0 && (
                      <div className="text-[10px] text-slate-500 mt-1">
                        Sources : {m.sources.map((s: { name: string }) => s.name).join(", ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {actions.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold uppercase text-slate-500 mb-2">Actions exécutées</h3>
                  <div className="space-y-1">
                    {actions.map((a) => (
                      <div key={a.id} className="text-xs bg-slate-50 rounded px-2 py-1.5 flex items-center justify-between">
                        <code>{a.tool}</code>
                        <span className={`badge ${a.status === "success" ? "bg-green-100 text-green-800" : a.status === "failed" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"}`}>
                          {a.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex gap-2 pt-2 border-t">
                <input className="input flex-1" placeholder="Répondre en tant qu'agent humain…" value={reply} onChange={(e) => setReply(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendReply()} />
                <button className="btn-primary" onClick={sendReply} disabled={busy || !reply.trim()}>Envoyer</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
