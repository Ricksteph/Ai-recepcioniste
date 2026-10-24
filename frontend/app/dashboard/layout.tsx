"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, getUser, setToken, setUser } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Vue d'ensemble", icon: "📊" },
  { href: "/dashboard/conversations", label: "Conversations", icon: "💬" },
  { href: "/dashboard/leads", label: "Prospects", icon: "🎯" },
  { href: "/dashboard/appointments", label: "Rendez-vous", icon: "📅" },
  { href: "/dashboard/handoffs", label: "Transferts humains", icon: "🙋" },
  { href: "/dashboard/knowledge", label: "Knowledge Base", icon: "📚" },
  { href: "/dashboard/rules", label: "Règles métier", icon: "⚖️" },
  { href: "/dashboard/identity", label: "Réceptionniste", icon: "🤖" },
  { href: "/dashboard/sandbox", label: "Sandbox", icon: "🧪" },
  { href: "/dashboard/analytics", label: "Analytics", icon: "📈" },
  { href: "/dashboard/audit", label: "Journal d'audit", icon: "🔒" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [tenant, setTenant] = useState<{ name: string; slug: string } | null>(null);
  const [published, setPublished] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api<{ tenant: { name: string; slug: string }; receptionist: { is_published: boolean } }>("/api/tenants/me")
      .then((data) => {
        setTenant(data.tenant);
        setPublished(data.receptionist.is_published);
        setReady(true);
      })
      .catch(() => router.replace("/login"));
  }, [router]);

  function logout() {
    setToken(null);
    setUser(null);
    router.push("/login");
  }

  if (!ready) {
    return <main className="min-h-screen flex items-center justify-center text-slate-400">Chargement…</main>;
  }

  const user = getUser();

  return (
    <div className="min-h-screen flex">
      <aside className={`${menuOpen ? "block" : "hidden"} md:flex fixed md:static inset-y-0 left-0 z-40 w-64 bg-slate-900 text-slate-200 flex-col`}>
        <div className="p-5 border-b border-slate-800">
          <div className="font-bold text-white">🤖 AI Receptionist</div>
          <div className="text-xs text-slate-400 mt-1 truncate">{tenant?.name}</div>
          {tenant && (
            <span className={`badge mt-2 ${published ? "bg-green-500/20 text-green-300" : "bg-slate-700 text-slate-300"}`}>
              {published ? "● Publié" : "○ Non publié"}
            </span>
          )}
        </div>
        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMenuOpen(false)}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm ${
                  active ? "bg-brand-600 text-white" : "hover:bg-slate-800 text-slate-300"
                }`}
              >
                <span>{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-slate-800 text-sm">
          <div className="text-slate-400 text-xs mb-2 truncate">{user?.email} · {user?.role}</div>
          <button onClick={logout} className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-800 text-slate-300">
            ← Déconnexion
          </button>
        </div>
      </aside>

      <div className="flex-1 min-w-0">
        <header className="md:hidden bg-slate-900 text-white p-3 flex items-center justify-between">
          <button onClick={() => setMenuOpen(!menuOpen)} className="text-xl">☰</button>
          <span className="font-semibold text-sm">AI Receptionist</span>
          <span className="w-6" />
        </header>
        <main className="p-4 md:p-8 max-w-6xl mx-auto">{children}</main>
      </div>
    </div>
  );
}
