"use client";

import { useEffect, useRef, useState } from "react";
import { api, ChatResponse } from "@/lib/api";

interface Bubble {
  role: "user" | "assistant";
  content: string;
  intent?: string;
  sources?: { name: string; snippet: string }[];
  actions?: { tool: string; status: string; message: string }[];
}

export default function SandboxPage() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [published, setPublished] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<{ receptionist: { is_published: boolean; greeting: string; name: string } }>("/api/tenants/me").then((d) => {
      setPublished(d.receptionist.is_published);
      if (d.receptionist.greeting) {
        setBubbles([{ role: "assistant", content: d.receptionist.greeting }]);
      }
    });
  }, []);

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
      const res = await api<ChatResponse>("/api/sandbox/test", {
        method: "POST",
        body: { message, conversation_id: conversationId },
      });
      setConversationId(res.conversation_id);
      setBubbles((b) => [
        ...b,
        {
          role: "assistant",
          content: res.reply,
          intent: res.intent,
          sources: res.sources,
          actions: res.actions,
        },
      ]);
    } catch (err) {
      setBubbles((b) => [...b, { role: "assistant", content: `⚠️ ${err instanceof Error ? err.message : "erreur"}` }]);
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setConversationId(null);
    setBubbles([]);
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">🧪 Sandbox de test</h1>
          <p className="text-sm text-slate-500">
            Testez votre réceptionniste avant publication — mêmes règles, mêmes connaissances, mêmes outils.
          </p>
        </div>
        <button className="btn-secondary" onClick={reset}>Nouvelle session</button>
      </div>

      {!published && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-lg px-4 py-2">
          Votre réceptionniste n&apos;est pas encore publié. C&apos;est le moment de le tester ici, puis de publier depuis la vue d&apos;ensemble.
        </div>
      )}

      <div className="card flex flex-col h-[60vh]">
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {bubbles.length === 0 && (
            <p className="text-sm text-slate-400 text-center mt-8">
              Posez une question comme « Quels sont vos horaires ? », « Je voudrais prendre rendez-vous » ou « Combien coûte une prestation ? »
            </p>
          )}
          {bubbles.map((b, i) => (
            <div key={i} className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm ${b.role === "user" ? "ml-auto bg-brand-600 text-white" : "bg-slate-100"}`}>
              <div className="whitespace-pre-wrap">{b.content}</div>
              {b.sources && b.sources.length > 0 && (
                <div className="text-[10px] opacity-70 mt-1.5 border-t border-slate-200 pt-1">
                  📎 {b.sources.map((s) => s.name).join(", ")}
                </div>
              )}
              {b.actions && b.actions.length > 0 && (
                <div className="mt-1.5 space-y-1">
                  {b.actions.map((a, j) => (
                    <div key={j} className="text-[10px] flex items-center gap-1.5">
                      <span className={`px-1.5 py-0.5 rounded ${
                        a.status === "success" ? "bg-green-100 text-green-800" :
                        a.status === "failed" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"
                      }`}>
                        {a.status === "success" ? "✓" : a.status === "failed" ? "✗" : "…"} {a.tool}
                      </span>
                      <span className="opacity-70">{a.message}</span>
                    </div>
                  ))}
                </div>
              )}
              {b.role === "assistant" && b.intent && (
                <div className="text-[10px] opacity-50 mt-1">intent: {b.intent}</div>
              )}
            </div>
          ))}
          {busy && <div className="text-xs text-slate-400">Le réceptionniste réfléchit…</div>}
          <div ref={endRef} />
        </div>
        <div className="border-t p-3 flex gap-2">
          <input
            className="input flex-1"
            placeholder="Votre message de test…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={busy}
          />
          <button className="btn-primary" onClick={() => send()} disabled={busy || !input.trim()}>
            Envoyer
          </button>
        </div>
      </div>

      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-2">💡 Scénarios à tester avant publication</h3>
        <div className="flex flex-wrap gap-2">
          {[
            "Bonjour !",
            "Quels sont vos horaires ?",
            "Combien coûte une prestation ?",
            "Je voudrais prendre rendez-vous",
            "Je dois annuler mon rendez-vous",
            "Je suis mécontent, c'est une arnaque !",
            "Un humain s'il vous plaît",
          ].map((s) => (
            <button key={s} className="btn-secondary text-xs" onClick={() => send(s)} disabled={busy}>
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
