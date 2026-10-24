"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Source {
  id: string;
  type: string;
  name: string;
  url: string;
  status: string;
  enabled: boolean;
  error: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

const STATUS_STYLE: Record<string, string> = {
  ready: "bg-green-100 text-green-800",
  processing: "bg-amber-100 text-amber-800",
  pending: "bg-slate-100 text-slate-600",
  error: "bg-red-100 text-red-800",
};

export default function KnowledgePage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [tab, setTab] = useState<"upload" | "web" | "text">("upload");
  const [webForm, setWebForm] = useState({ name: "", url: "" });
  const [textForm, setTextForm] = useState({ name: "", content: "" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ name: string; content: string; score: number }[] | null>(null);

  const load = useCallback(async () => {
    setSources(await api<Source[]>("/api/knowledge/sources"));
  }, []);

  useEffect(() => {
    load().catch(() => {});
    const t = setInterval(() => load().catch(() => {}), 4000);
    return () => clearInterval(t);
  }, [load]);

  async function uploadFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setMessage("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", file.name);
      await api("/api/knowledge/sources/upload", { method: "POST", formData: fd });
      setMessage(`✓ ${file.name} importé — indexation en cours…`);
      await load();
    } catch (err) {
      setMessage(`✗ ${err instanceof Error ? err.message : "erreur"}`);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function addWeb() {
    if (!webForm.url) return;
    setBusy(true);
    try {
      await api("/api/knowledge/sources", { method: "POST", body: { type: "web", ...webForm } });
      setWebForm({ name: "", url: "" });
      await load();
    } catch (err) {
      setMessage(`✗ ${err instanceof Error ? err.message : "erreur"}`);
    } finally {
      setBusy(false);
    }
  }

  async function addText() {
    if (!textForm.content.trim()) return;
    setBusy(true);
    try {
      await api("/api/knowledge/sources", { method: "POST", body: { type: "faq", name: textForm.name || "FAQ", content: textForm.content } });
      setTextForm({ name: "", content: "" });
      await load();
    } catch (err) {
      setMessage(`✗ ${err instanceof Error ? err.message : "erreur"}`);
    } finally {
      setBusy(false);
    }
  }

  async function toggle(s: Source) {
    await api(`/api/knowledge/sources/${s.id}`, { method: "PATCH", body: { enabled: !s.enabled } });
    await load();
  }

  async function remove(s: Source) {
    if (!confirm(`Supprimer « ${s.name} » et ses chunks ?`)) return;
    await api(`/api/knowledge/sources/${s.id}`, { method: "DELETE" });
    await load();
  }

  async function search() {
    if (!query.trim()) return;
    const data = await api<{ results: { name: string; content: string; score: number }[] }>(
      "/api/knowledge/search", { method: "POST", body: { query, limit: 6 } }
    );
    setResults(data.results);
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Knowledge Base &amp; RAG</h1>

      <div className="card p-5 space-y-4">
        <div className="flex gap-2 border-b pb-3">
          {([["upload", "📤 Fichier"], ["web", "🌐 Page web"], ["text", "📝 FAQ / Texte"]] as const).map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium ${tab === k ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600"}`}>
              {label}
            </button>
          ))}
        </div>

        {tab === "upload" && (
          <div>
            <label className="btn-secondary cursor-pointer">
              {busy ? "Import…" : "Choisir un document (PDF, DOCX, XLSX, CSV, TXT, MD — 10 Mo max)"}
              <input type="file" className="hidden" accept=".pdf,.docx,.xlsx,.csv,.txt,.md" onChange={uploadFile} disabled={busy} />
            </label>
          </div>
        )}

        {tab === "web" && (
          <div className="flex gap-2 items-end">
            <div className="flex-1">
              <label className="label">Nom (optionnel)</label>
              <input className="input" value={webForm.name} placeholder="Notre site" onChange={(e) => setWebForm({ ...webForm, name: e.target.value })} />
            </div>
            <div className="flex-[2]">
              <label className="label">URL</label>
              <input className="input" value={webForm.url} placeholder="https://exemple.fr" onChange={(e) => setWebForm({ ...webForm, url: e.target.value })} />
            </div>
            <button className="btn-primary" onClick={addWeb} disabled={busy}>Importer</button>
          </div>
        )}

        {tab === "text" && (
          <div className="space-y-2">
            <input className="input" placeholder="Nom (FAQ, tarifs…)" value={textForm.name} onChange={(e) => setTextForm({ ...textForm, name: e.target.value })} />
            <textarea className="input" rows={6} placeholder="Collez votre FAQ ou vos informations ici…" value={textForm.content} onChange={(e) => setTextForm({ ...textForm, content: e.target.value })} />
            <button className="btn-primary" onClick={addText} disabled={busy}>Indexer</button>
          </div>
        )}

        {message && <p className="text-sm text-slate-600">{message}</p>}
      </div>

      <div className="card divide-y divide-slate-100">
        {sources.length === 0 && <p className="p-4 text-sm text-slate-500">Aucune source. Importez un document pour que l&apos;agent puisse répondre à partir de vos connaissances.</p>}
        {sources.map((s) => (
          <div key={s.id} className="p-4 flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm truncate">{s.name}</span>
                <span className={`badge ${STATUS_STYLE[s.status] || "bg-slate-100"}`}>{s.status}</span>
                {!s.enabled && <span className="badge bg-slate-200 text-slate-600">désactivée</span>}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                {s.type.toUpperCase()} · {s.chunk_count} chunks · {new Date(s.updated_at).toLocaleString("fr-FR")}
                {s.url && ` · ${s.url}`}
              </div>
              {s.error && <div className="text-xs text-red-600 mt-1">{s.error}</div>}
            </div>
            <button className="btn-secondary text-xs" onClick={() => toggle(s)}>{s.enabled ? "Désactiver" : "Activer"}</button>
            <button className="btn-danger text-xs" onClick={() => remove(s)}>Suppr.</button>
          </div>
        ))}
      </div>

      <div className="card p-5 space-y-3">
        <h2 className="font-semibold">🔎 Tester la recherche (isolation tenant garantie)</h2>
        <div className="flex gap-2">
          <input className="input flex-1" placeholder="Quelle question un client pourrait poser ?" value={query}
            onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
          <button className="btn-primary" onClick={search}>Rechercher</button>
        </div>
        {results && (
          <div className="space-y-2">
            {results.length === 0 && <p className="text-sm text-slate-500">Aucun résultat dans vos sources activées.</p>}
            {results.map((r, i) => (
              <div key={i} className="bg-slate-50 rounded-lg p-3 text-sm">
                <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                  <span>{r.name}</span>
                  <span>score {r.score}</span>
                </div>
                <p className="text-slate-700">{r.content.slice(0, 400)}{r.content.length > 400 && "…"}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
