"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

interface WidgetConfig {
  company: string;
  agent_name: string;
  greeting: string;
  language: string;
  published: boolean;
}

interface Bubble {
  role: "user" | "assistant" | "human_agent";
  content: string;
  sources?: { name: string }[];
}

const VISITOR_KEY = (slug: string) => `air_visitor_${slug}`;

export default function PublicChatPage() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug || "";
  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [error, setError] = useState("");
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [visitorId, setVisitorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [handoff, setHandoff] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!slug) return;
    let vid = localStorage.getItem(VISITOR_KEY(slug));
    if (!vid) {
      vid = Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(VISITOR_KEY(slug), vid);
    }
    setVisitorId(vid);

    fetch(`/api/public/${slug}/widget`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "Cet assistant n'est pas disponible ou n'est pas publié." : "Erreur");
        return r.json();
      })
      .then((cfg: WidgetConfig) => {
        setConfig(cfg);
        if (cfg.greeting) setBubbles([{ role: "assistant", content: cfg.greeting }]);
      })
      .catch((e) => setError(e.message));
  }, [slug]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bubbles]);

  async function send(text?: string) {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setBubbles((b) => [...b, { role: "user", content: message }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch(`/api/public/${slug}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, conversation_id: conversationId, visitor_id: visitorId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Erreur");
      setConversationId(data.conversation_id);
      setBubbles((b) => [...b, { role: "assistant", content: data.reply, sources: data.sources }]);
      if (data.handoff) setHandoff(true);
    } catch (err) {
      setBubbles((b) => [...b, { role: "assistant", content: `⚠️ ${err instanceof Error ? err.message : "Une erreur est survenue."}` }]);
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <main className="min-h-screen flex items-center justify-center p-4">
        <div className="card p-8 text-center max-w-md">
          <div className="text-4xl mb-3">🤖</div>
          <h1 className="font-semibold text-lg">Assistant indisponible</h1>
          <p className="text-sm text-slate-500 mt-2">{error}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex flex-col items-center p-4">
      <div className="w-full max-w-2xl flex-1 flex flex-col">
        <div className="card flex-1 flex flex-col overflow-hidden">
          <div className="bg-brand-600 text-white p-4 flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-white/20 flex items-center justify-center text-xl">🤖</div>
            <div>
              <div className="font-semibold">{config?.agent_name || "…"}</div>
              <div className="text-xs opacity-80">{config?.company || ""}</div>
            </div>
            {handoff && (
              <div className="ml-auto badge bg-amber-400 text-amber-900">Humain en route</div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50">
            {bubbles.map((b, i) => (
              <div key={i} className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm ${
                b.role === "user" ? "ml-auto bg-brand-600 text-white" : "bg-white border border-slate-200"
              }`}>
                <div className="whitespace-pre-wrap">{b.content}</div>
                {b.sources && b.sources.length > 0 && (
                  <div className="text-[10px] opacity-60 mt-1">📎 {b.sources.map((s) => s.name).join(", ")}</div>
                )}
              </div>
            ))}
            {busy && <div className="text-xs text-slate-400">Écriture…</div>}
            <div ref={endRef} />
          </div>

          <form
            className="border-t p-3 flex gap-2 bg-white"
            onSubmit={(e) => { e.preventDefault(); send(); }}
          >
            <input
              className="input flex-1"
              placeholder="Écrivez votre message…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy || !config}
            />
            <button className="btn-primary" disabled={busy || !input.trim()}>Envoyer</button>
          </form>
        </div>
        <p className="text-center text-xs text-slate-400 mt-3">
          Propulsé par AI Receptionist — conversations conservées selon la politique de l&apos;entreprise
        </p>
      </div>
    </main>
  );
}
