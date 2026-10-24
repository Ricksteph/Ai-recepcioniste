import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Receptionist — Réceptionniste IA",
  description:
    "Plateforme SaaS multi-tenant de réceptionniste virtuel : RAG, règles métier, leads, rendez-vous et transfert humain.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
