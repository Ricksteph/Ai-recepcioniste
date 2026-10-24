"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "@/lib/api";

const DAYS = [
  ["monday", "Lundi"], ["tuesday", "Mardi"], ["wednesday", "Mercredi"],
  ["thursday", "Jeudi"], ["friday", "Vendredi"], ["saturday", "Samedi"], ["sunday", "Dimanche"],
];

interface HourRow { open: string; close: string; closed: boolean }

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [company, setCompany] = useState({
    name: "", sector: "", description: "", address: "", phone: "", email: "",
    website: "", timezone: "Europe/Paris", languages: ["fr"], currency: "EUR",
  });
  const [hours, setHours] = useState<Record<string, HourRow>>({
    monday: { open: "09:00", close: "18:00", closed: false },
    tuesday: { open: "09:00", close: "18:00", closed: false },
    wednesday: { open: "09:00", close: "18:00", closed: false },
    thursday: { open: "09:00", close: "18:00", closed: false },
    friday: { open: "09:00", close: "18:00", closed: false },
    saturday: { open: "09:00", close: "12:30", closed: false },
    sunday: { open: "09:00", close: "12:30", closed: true },
  });
  const [receptionist, setReceptionist] = useState({
    name: "Léa", tone: "professionnel et chaleureux", style: "concis et direct",
    conciseness: 2, language: "fr",
    greeting: "Bonjour ! Je suis Léa, l'assistant virtuelle. Comment puis-je vous aider ?",
    services: [] as { name: string; duration_min: number; description: string; price: string }[],
  });
  const [newService, setNewService] = useState({ name: "", duration_min: 30, description: "", price: "" });

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  async function finish() {
    setSaving(true);
    setError("");
    try {
      const business_hours: Record<string, { open: string; close: string } | null> = {};
      for (const [key] of DAYS) {
        const row = hours[key];
        business_hours[key] = row.closed ? null : { open: row.open, close: row.close };
      }
      await api("/api/tenants/onboarding", {
        method: "POST",
        body: {
          tenant: { ...company, business_hours },
          receptionist: { ...receptionist, instructions: {}, avatar_url: "", voice: "" },
          create_default_rules: true,
        },
      });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur lors de l'enregistrement");
      setSaving(false);
    }
  }

  const steps = ["Votre entreprise", "Horaires", "Votre réceptionniste", "Prestations"];

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-2xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Mise en route guidée</h1>
          <div className="flex gap-2 mt-4">
            {steps.map((s, i) => (
              <button
                key={s}
                onClick={() => setStep(i)}
                className={`px-3 py-1.5 rounded-full text-sm font-medium ${
                  i === step ? "bg-brand-600 text-white" : i < step ? "bg-brand-100 text-brand-700" : "bg-slate-100 text-slate-500"
                }`}
              >
                {i + 1}. {s}
              </button>
            ))}
          </div>
        </div>

        <div className="card p-6 space-y-4">
          {step === 0 && (
            <>
              <div>
                <label className="label">Nom</label>
                <input className="input" value={company.name} onChange={(e) => setCompany({ ...company, name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Secteur</label>
                  <input className="input" value={company.sector} onChange={(e) => setCompany({ ...company, sector: e.target.value })} />
                </div>
                <div>
                  <label className="label">Fuseau horaire</label>
                  <input className="input" value={company.timezone} onChange={(e) => setCompany({ ...company, timezone: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="label">Description</label>
                <textarea className="input" rows={3} value={company.description} onChange={(e) => setCompany({ ...company, description: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Adresse</label>
                  <input className="input" value={company.address} onChange={(e) => setCompany({ ...company, address: e.target.value })} />
                </div>
                <div>
                  <label className="label">Téléphone</label>
                  <input className="input" value={company.phone} onChange={(e) => setCompany({ ...company, phone: e.target.value })} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Email</label>
                  <input className="input" value={company.email} onChange={(e) => setCompany({ ...company, email: e.target.value })} />
                </div>
                <div>
                  <label className="label">Site web</label>
                  <input className="input" value={company.website} onChange={(e) => setCompany({ ...company, website: e.target.value })} />
                </div>
              </div>
            </>
          )}

          {step === 1 && (
            <div className="space-y-3">
              {DAYS.map(([key, label]) => (
                <div key={key} className="flex items-center gap-3">
                  <span className="w-24 text-sm font-medium">{label}</span>
                  <label className="flex items-center gap-1 text-sm text-slate-500">
                    <input
                      type="checkbox"
                      checked={hours[key].closed}
                      onChange={(e) => setHours({ ...hours, [key]: { ...hours[key], closed: e.target.checked } })}
                    />
                    Fermé
                  </label>
                  {!hours[key].closed && (
                    <>
                      <input type="time" className="input w-32" value={hours[key].open}
                        onChange={(e) => setHours({ ...hours, [key]: { ...hours[key], open: e.target.value } })} />
                      <span className="text-slate-400">→</span>
                      <input type="time" className="input w-32" value={hours[key].close}
                        onChange={(e) => setHours({ ...hours, [key]: { ...hours[key], close: e.target.value } })} />
                    </>
                  )}
                </div>
              ))}
            </div>
          )}

          {step === 2 && (
            <>
              <div>
                <label className="label">Nom du réceptionniste IA</label>
                <input className="input" value={receptionist.name} onChange={(e) => setReceptionist({ ...receptionist, name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Ton</label>
                  <select className="input" value={receptionist.tone} onChange={(e) => setReceptionist({ ...receptionist, tone: e.target.value })}>
                    <option>professionnel et chaleureux</option>
                    <option>formel</option>
                    <option>amical et détendu</option>
                    <option>concis et direct</option>
                  </select>
                </div>
                <div>
                  <label className="label">Niveau de concision</label>
                  <select className="input" value={receptionist.conciseness} onChange={(e) => setReceptionist({ ...receptionist, conciseness: Number(e.target.value) })}>
                    <option value={1}>Court</option>
                    <option value={2}>Équilibré</option>
                    <option value={3}>Détaillé</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Message d&apos;accueil</label>
                <textarea className="input" rows={3} value={receptionist.greeting} onChange={(e) => setReceptionist({ ...receptionist, greeting: e.target.value })} />
              </div>
            </>
          )}

          {step === 3 && (
            <>
              <div className="space-y-2">
                {receptionist.services.map((s, i) => (
                  <div key={i} className="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2 text-sm">
                    <span>{s.name} — {s.duration_min} min {s.price && `— ${s.price}`}</span>
                    <button className="text-red-500 text-xs" onClick={() => setReceptionist({ ...receptionist, services: receptionist.services.filter((_, j) => j !== i) })}>
                      Retirer
                    </button>
                  </div>
                ))}
                {receptionist.services.length === 0 && (
                  <p className="text-sm text-slate-500">Ajoutez vos prestations pour que l&apos;agent puisse proposer des créneaux adaptés.</p>
                )}
              </div>
              <div className="flex gap-2 items-end">
                <div className="flex-1">
                  <label className="label">Nouvelle prestation</label>
                  <input className="input" value={newService.name} placeholder="Consultation"
                    onChange={(e) => setNewService({ ...newService, name: e.target.value })} />
                </div>
                <div className="w-28">
                  <label className="label">Durée (min)</label>
                  <input className="input" type="number" min={5} step={5} value={newService.duration_min}
                    onChange={(e) => setNewService({ ...newService, duration_min: Number(e.target.value) })} />
                </div>
                <div className="w-28">
                  <label className="label">Prix</label>
                  <input className="input" value={newService.price} placeholder="40 €"
                    onChange={(e) => setNewService({ ...newService, price: e.target.value })} />
                </div>
                <button
                  className="btn-secondary"
                  onClick={() => {
                    if (!newService.name.trim()) return;
                    setReceptionist({ ...receptionist, services: [...receptionist.services, { ...newService, description: "" }] });
                    setNewService({ name: "", duration_min: 30, description: "", price: "" });
                  }}
                >
                  Ajouter
                </button>
              </div>
            </>
          )}

          {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}

          <div className="flex justify-between pt-4">
            <button className="btn-secondary" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>
              Précédent
            </button>
            {step < steps.length - 1 ? (
              <button className="btn-primary" onClick={() => setStep(step + 1)}>Suivant</button>
            ) : (
              <button className="btn-primary" onClick={finish} disabled={saving}>
                {saving ? "Enregistrement…" : "Terminer la configuration"}
              </button>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
