"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, setToken, setUser } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    company_name: "",
    slug: "",
    sector: "",
    email: "",
    password: "",
    full_name: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value, ...(k === "company_name" && !form.slug ? { slug: e.target.value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") } : {}) });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api<{ access_token: string; user: unknown }>("/api/auth/register", {
        method: "POST",
        body: form,
        auth: false,
      });
      setToken(data.access_token);
      setUser(data.user);
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur lors de la création");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-4">
      <div className="card w-full max-w-lg p-8">
        <div className="mb-6 text-center">
          <div className="text-3xl mb-2">🏢</div>
          <h1 className="text-2xl font-bold">Créer votre entreprise</h1>
          <p className="text-sm text-slate-500 mt-1">
            Étape 1/10 — Configurer → Alimenter → Tester → Publier → Superviser
          </p>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label">Nom de l&apos;entreprise</label>
            <input className="input" value={form.company_name} onChange={set("company_name")} placeholder="Clinique Dentaire Dupont" required />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Identifiant (slug)</label>
              <input className="input" value={form.slug} onChange={set("slug")} placeholder="clinique-dupont" pattern="[a-z0-9-]+" required />
            </div>
            <div>
              <label className="label">Secteur</label>
              <input className="input" value={form.sector} onChange={set("sector")} placeholder="Santé, BTP, coaching…" />
            </div>
          </div>
          <div>
            <label className="label">Votre nom</label>
            <input className="input" value={form.full_name} onChange={set("full_name")} placeholder="Dr Dupont" />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="input" type="email" value={form.email} onChange={set("email")} placeholder="vous@entreprise.fr" required />
          </div>
          <div>
            <label className="label">Mot de passe (8 caractères min.)</label>
            <input className="input" type="password" value={form.password} onChange={set("password")} minLength={8} required />
          </div>
          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}
          <button className="btn-primary w-full" disabled={loading}>
            {loading ? "Création…" : "Créer mon entreprise"}
          </button>
        </form>
        <p className="text-sm text-slate-500 text-center mt-6">
          Déjà un compte ?{" "}
          <Link href="/login" className="text-brand-600 font-medium hover:underline">Se connecter</Link>
        </p>
      </div>
    </main>
  );
}
