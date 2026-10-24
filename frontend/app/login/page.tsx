"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, setToken, setUser } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api<{ access_token: string; user: unknown }>("/api/auth/login", {
        method: "POST",
        body: { email, password },
        auth: false,
      });
      setToken(data.access_token);
      setUser(data.user);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur de connexion");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-4">
      <div className="card w-full max-w-md p-8">
        <div className="mb-6 text-center">
          <div className="text-3xl mb-2">🤖</div>
          <h1 className="text-2xl font-bold text-slate-900">AI Receptionist</h1>
          <p className="text-sm text-slate-500 mt-1">Connectez-vous à votre espace</p>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label">Email</label>
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="vous@entreprise.fr"
              required
            />
          </div>
          <div>
            <label className="label">Mot de passe</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>
          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
          <button className="btn-primary w-full" disabled={loading}>
            {loading ? "Connexion…" : "Se connecter"}
          </button>
        </form>
        <p className="text-sm text-slate-500 text-center mt-6">
          Pas encore de compte ?{" "}
          <Link href="/register" className="text-brand-600 font-medium hover:underline">
            Créer mon entreprise
          </Link>
        </p>
      </div>
    </main>
  );
}
