"use client";

import { useEffect, useState } from "react";
import { api, ReceptionistInfo, TenantInfo } from "@/lib/api";

export default function IdentityPage() {
  const [tenant, setTenant] = useState<TenantInfo | null>(null);
  const [rec, setRec] = useState<ReceptionistInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    api<{ tenant: TenantInfo; receptionist: ReceptionistInfo }>("/api/tenants/me").then((d) => {
      setTenant(d.tenant);
      setRec(d.receptionist);
    });
  }, []);

  async function saveTenant() {
    if (!tenant) return;
    setBusy(true);
    try {
      await api("/api/tenants/me", { method: "PUT", body: tenant });
      setSaved("Entreprise enregistrée ✓");
      setTimeout(() => setSaved(""), 2000);
    } finally {
      setBusy(false);
    }
  }

  async function saveRec() {
    if (!rec) return;
    setBusy(true);
    try {
      await api("/api/tenants/me/receptionist", { method: "PUT", body: rec });
      setSaved("Réceptionniste enregistré ✓");
      setTimeout(() => setSaved(""), 2000);
    } finally {
      setBusy(false);
    }
  }

  if (!tenant || !rec) return <p className="text-slate-400">Chargement…</p>;

  const days = [
    ["monday", "Lundi"], ["tuesday", "Mardi"], ["wednesday", "Mercredi"],
    ["thursday", "Jeudi"], ["friday", "Vendredi"], ["saturday", "Samedi"], ["sunday", "Dimanche"],
  ] as const;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Configuration</h1>
        {saved && <span className="badge bg-green-100 text-green-800">{saved}</span>}
      </div>

      <section className="card p-5 space-y-4">
        <h2 className="font-semibold">🏢 Entreprise</h2>
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <label className="label">Nom</label>
            <input className="input" value={tenant.name} onChange={(e) => setTenant({ ...tenant, name: e.target.value })} />
          </div>
          <div>
            <label className="label">Secteur</label>
            <input className="input" value={tenant.sector} onChange={(e) => setTenant({ ...tenant, sector: e.target.value })} />
          </div>
          <div>
            <label className="label">Téléphone</label>
            <input className="input" value={tenant.phone} onChange={(e) => setTenant({ ...tenant, phone: e.target.value })} />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="input" value={tenant.email} onChange={(e) => setTenant({ ...tenant, email: e.target.value })} />
          </div>
          <div>
            <label className="label">Adresse</label>
            <input className="input" value={tenant.address} onChange={(e) => setTenant({ ...tenant, address: e.target.value })} />
          </div>
          <div>
            <label className="label">Site web</label>
            <input className="input" value={tenant.website} onChange={(e) => setTenant({ ...tenant, website: e.target.value })} />
          </div>
        </div>
        <div>
          <label className="label">Description</label>
          <textarea className="input" rows={2} value={tenant.description} onChange={(e) => setTenant({ ...tenant, description: e.target.value })} />
        </div>

        <div>
          <label className="label">Horaires d&apos;ouverture</label>
          <div className="space-y-2">
            {days.map(([key, label]) => {
              const row = tenant.business_hours?.[key];
              return (
                <div key={key} className="flex items-center gap-3 text-sm">
                  <span className="w-24">{label}</span>
                  <label className="flex items-center gap-1 text-slate-500">
                    <input
                      type="checkbox"
                      checked={!row}
                      onChange={(e) =>
                        setTenant({
                          ...tenant,
                          business_hours: {
                            ...tenant.business_hours,
                            [key]: e.target.checked ? null : { open: "09:00", close: "18:00" },
                          },
                        })
                      }
                    />
                    Fermé
                  </label>
                  {row && (
                    <>
                      <input type="time" className="input w-28" value={row.open}
                        onChange={(e) => setTenant({ ...tenant, business_hours: { ...tenant.business_hours, [key]: { ...row, open: e.target.value } } })} />
                      <span>→</span>
                      <input type="time" className="input w-28" value={row.close}
                        onChange={(e) => setTenant({ ...tenant, business_hours: { ...tenant.business_hours, [key]: { ...row, close: e.target.value } } })} />
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <button className="btn-primary" onClick={saveTenant} disabled={busy}>Enregistrer l&apos;entreprise</button>
      </section>

      <section className="card p-5 space-y-4">
        <h2 className="font-semibold">🤖 Profil du réceptionniste</h2>
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <label className="label">Nom</label>
            <input className="input" value={rec.name} onChange={(e) => setRec({ ...rec, name: e.target.value })} />
          </div>
          <div>
            <label className="label">Langue</label>
            <select className="input" value={rec.language} onChange={(e) => setRec({ ...rec, language: e.target.value })}>
              <option value="fr">Français</option>
              <option value="en">English</option>
              <option value="es">Español</option>
            </select>
          </div>
          <div>
            <label className="label">Ton</label>
            <input className="input" value={rec.tone} onChange={(e) => setRec({ ...rec, tone: e.target.value })} />
          </div>
          <div>
            <label className="label">Style</label>
            <input className="input" value={rec.style} onChange={(e) => setRec({ ...rec, style: e.target.value })} />
          </div>
        </div>
        <div>
          <label className="label">Message d&apos;accueil</label>
          <textarea className="input" rows={3} value={rec.greeting} onChange={(e) => setRec({ ...rec, greeting: e.target.value })} />
        </div>

        <div>
          <label className="label">Prestations proposées</label>
          <div className="space-y-2">
            {rec.services.map((s, i) => (
              <div key={i} className="flex gap-2 items-center">
                <input className="input flex-1" value={s.name}
                  onChange={(e) => { const sv = [...rec.services]; sv[i] = { ...s, name: e.target.value }; setRec({ ...rec, services: sv }); }} />
                <input className="input w-24" type="number" min={5} step={5} value={s.duration_min}
                  onChange={(e) => { const sv = [...rec.services]; sv[i] = { ...s, duration_min: Number(e.target.value) }; setRec({ ...rec, services: sv }); }} />
                <input className="input w-28" value={s.price} placeholder="Prix"
                  onChange={(e) => { const sv = [...rec.services]; sv[i] = { ...s, price: e.target.value }; setRec({ ...rec, services: sv }); }} />
                <button className="text-red-500 text-sm" onClick={() => setRec({ ...rec, services: rec.services.filter((_, j) => j !== i) })}>✕</button>
              </div>
            ))}
          </div>
          <button className="btn-secondary text-xs mt-2"
            onClick={() => setRec({ ...rec, services: [...rec.services, { name: "", duration_min: 30, description: "", price: "" }] })}>
            + Ajouter une prestation
          </button>
        </div>

        <button className="btn-primary" onClick={saveRec} disabled={busy}>Enregistrer le réceptionniste</button>
      </section>
    </div>
  );
}
