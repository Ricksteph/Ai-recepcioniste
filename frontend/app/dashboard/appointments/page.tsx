"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Appointment {
  id: string;
  service: string;
  title: string;
  starts_at: string;
  ends_at: string;
  status: string;
  notes: string;
  contact_name: string;
  contact_email: string;
  created_at: string;
}

interface Slot { starts_at: string; ends_at: string }

const STATUS_LABEL: Record<string, { label: string; style: string }> = {
  confirmed: { label: "Confirmé", style: "bg-green-100 text-green-800" },
  cancelled: { label: "Annulé", style: "bg-red-100 text-red-800" },
  completed: { label: "Terminé", style: "bg-slate-100 text-slate-700" },
  no_show: { label: "Absent", style: "bg-amber-100 text-amber-800" },
};

export default function AppointmentsPage() {
  const [appts, setAppts] = useState<Appointment[]>([]);
  const [services, setServices] = useState<{ name: string; duration_min: number }[]>([]);
  const [form, setForm] = useState({ name: "", email: "", phone: "", service: "", date: "", time: "", notes: "" });
  const [slots, setSlots] = useState<Slot[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setAppts(await api<Appointment[]>("/api/appointments"));
    const cfg = await api<{ receptionist: { services: { name: string; duration_min: number }[] } }>("/api/tenants/me");
    setServices(cfg.receptionist.services || []);
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function fetchSlots() {
    if (!form.date) return;
    setError("");
    try {
      const data = await api<{ slots: Slot[] }>(
        `/api/appointments/availability?date=${form.date}${form.service ? `&service=${encodeURIComponent(form.service)}` : ""}`
      );
      setSlots(data.slots);
    } catch (err) {
      setError(err instanceof Error ? err.message : "erreur");
    }
  }

  useEffect(() => {
    fetchSlots().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.date, form.service]);

  async function book() {
    setBusy(true);
    setError("");
    try {
      await api("/api/appointments", { method: "POST", body: form });
      setForm({ name: "", email: "", phone: "", service: "", date: "", time: "", notes: "" });
      setSlots([]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "erreur");
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id: string) {
    if (!confirm("Annuler ce rendez-vous ?")) return;
    await api(`/api/appointments/${id}`, { method: "DELETE" });
    await load();
  }

  async function complete(id: string) {
    await api(`/api/appointments/${id}`, { method: "PATCH", body: { status: "completed" } });
    await load();
  }

  const upcoming = appts.filter((a) => a.status === "confirmed");
  const past = appts.filter((a) => a.status !== "confirmed");

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Rendez-vous</h1>

      <div className="card p-5 space-y-4">
        <h2 className="font-semibold">➕ Nouveau rendez-vous (vérification réelle des créneaux)</h2>
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <label className="label">Nom du client *</label>
            <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div>
            <label className="label">Téléphone</label>
            <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </div>
          <div>
            <label className="label">Prestation</label>
            <select className="input" value={form.service} onChange={(e) => setForm({ ...form, service: e.target.value })}>
              <option value="">— standard (30 min) —</option>
              {services.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.duration_min} min)</option>)}
            </select>
          </div>
          <div>
            <label className="label">Date *</label>
            <input className="input" type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value, time: "" })} />
          </div>
          <div>
            <label className="label">Créneau disponible *</label>
            <select className="input" value={form.time} onChange={(e) => setForm({ ...form, time: e.target.value })} disabled={!form.date}>
              <option value="">{
                !form.date ? "choisissez d'abord une date" :
                slots.length === 0 ? "aucun créneau libre (jour fermé ou complet)" :
                "— sélectionnez —"
              }</option>
              {slots.map((s) => (
                <option key={s.starts_at} value={s.starts_at.slice(11, 16)}>
                  {s.starts_at.slice(11, 16)} → {s.ends_at.slice(11, 16)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="label">Notes</label>
          <input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}
        <button className="btn-primary" onClick={book} disabled={busy || !form.name || !form.date || !form.time}>
          {busy ? "Réservation…" : "Réserver (crée un vrai rendez-vous)"}
        </button>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Quand</th>
              <th className="text-left px-4 py-3">Client</th>
              <th className="text-left px-4 py-3">Prestation</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {appts.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Aucun rendez-vous.</td></tr>
            )}
            {[...upcoming, ...past].map((a) => (
              <tr key={a.id}>
                <td className="px-4 py-3">
                  <div className="font-medium">{new Date(a.starts_at).toLocaleDateString("fr-FR")}</div>
                  <div className="text-xs text-slate-500">
                    {new Date(a.starts_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} →{" "}
                    {new Date(a.ends_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div>{a.contact_name || "—"}</div>
                  {a.contact_email && <div className="text-xs text-slate-500">{a.contact_email}</div>}
                </td>
                <td className="px-4 py-3">{a.service || "Standard"}</td>
                <td className="px-4 py-3">
                  <span className={`badge ${STATUS_LABEL[a.status]?.style || "bg-slate-100"}`}>
                    {STATUS_LABEL[a.status]?.label || a.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                  {a.status === "confirmed" && (
                    <>
                      <button className="btn-secondary text-xs" onClick={() => complete(a.id)}>Terminé</button>
                      <button className="btn-danger text-xs" onClick={() => cancel(a.id)}>Annuler</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
