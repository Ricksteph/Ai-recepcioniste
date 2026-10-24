"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

interface Overview {
  conversations: { total: number; open: number; handoff: number };
  messages_30d: number;
  resolution_rate: number;
  resolved_by_agent: number;
  leads: { total: number; qualified: number };
  appointments_confirmed: number;
  actions: { success: number; failed: number };
  pending_handoffs: number;
  daily_messages: { date: string; count: number }[];
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="text-3xl font-bold mt-1">{value}</div>
      {sub && <div className="text-xs text-slate-400 mt-1">{sub}</div>}
    </div>
  );
}

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [tenant, setTenant] = useState<{ name: string; slug: string } | null>(null);
  const [receptionist, setReceptionist] = useState<{ name: string; is_published: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function load() {
    const [ov, cfg] = await Promise.all([
      api<Overview>("/api/analytics/overview"),
      api<{ tenant: { name: string; slug: string }; receptionist: { name: string; is_published: boolean } }>("/api/tenants/me"),
    ]);
    setData(ov);
    setTenant(cfg.tenant);
    setReceptionist(cfg.receptionist);
  }

  useEffect(() => {
    load().catch(() => {});
  }, []);

  async function togglePublish() {
    if (!receptionist) return;
    setBusy(true);
    try {
      await api(`/api/tenants/me/${receptionist.is_published ? "unpublish" : "publish"}`, { method: "POST" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  const snippet = tenant
    ? `<script src="${typeof window !== "undefined" ? window.location.origin : ""}/widget.js" data-slug="${tenant.slug}" async></script>`
    : "";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">Vue d&apos;ensemble</h1>
          <p className="text-sm text-slate-500">{tenant?.name}</p>
        </div>
        <div className="flex gap-2">
          <Link href="/dashboard/sandbox" className="btn-secondary">🧪 Tester en sandbox</Link>
          <button className={receptionist?.is_published ? "btn-danger" : "btn-primary"} onClick={togglePublish} disabled={busy}>
            {receptionist?.is_published ? "Arrêter la publication" : "🚀 Publier le réceptionniste"}
          </button>
        </div>
      </div>

      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat label="Conversations" value={data.conversations.total} sub={`${data.conversations.open} ouvertes`} />
            <Stat label="Prospects" value={data.leads.total} sub={`${data.leads.qualified} qualifiés`} />
            <Stat label="Rendez-vous confirmés" value={data.appointments_confirmed} />
            <Stat label="Taux de résolution" value={`${Math.round(data.resolution_rate * 100)}%`} sub={`${data.resolved_by_agent} résolues`} />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat label="Messages (30j)" value={data.messages_30d} />
            <Stat label="Actions réussies" value={data.actions.success} sub={`${data.actions.failed} échouées`} />
            <Stat label="Transferts en attente" value={data.pending_handoffs} />
            <Stat label="Transferts humains" value={data.conversations.handoff} />
          </div>
        </>
      )}

      <div className="card p-5">
        <h2 className="font-semibold mb-2">💬 Intégrer le chat sur votre site</h2>
        <p className="text-sm text-slate-500 mb-3">
          {receptionist?.is_published
            ? "Votre réceptionniste est publié. Copiez ce code dans le <head> de votre site :"
            : "Publiez d'abord votre réceptionniste, puis copiez ce code dans le <head> de votre site :"}
        </p>
        <div className="flex gap-2 items-center">
          <code className="flex-1 bg-slate-900 text-green-300 text-xs p-3 rounded-lg overflow-x-auto whitespace-nowrap">{snippet}</code>
          <button
            className="btn-secondary whitespace-nowrap"
            onClick={() => { navigator.clipboard.writeText(snippet); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
          >
            {copied ? "✓ Copié" : "Copier"}
          </button>
        </div>
        {tenant && (
          <Link href={`/chat/${tenant.slug}`} className="text-sm text-brand-600 hover:underline inline-block mt-2">
            Ouvrir la page de chat publique →
          </Link>
        )}
      </div>
    </div>
  );
}
