"""Seed the database with a fully configured demo tenant.

Run:  python seed.py
Creates:
- a super admin account (SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD, defaults dev only)
- a demo tenant "Clinique Dentaire Dupont" with services, hours, rules, a FAQ
  knowledge base, and a published receptionist ready for the web chat widget.
"""
import asyncio
import os

from app.db import SessionLocal, init_db
from app.engine.rules import default_rules_payload
from app.models import BusinessRule, KnowledgeSource, ReceptionistConfig, Tenant, User
from app.rag.ingest import ingest_source
from app.security import hash_password

SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "super@ai-receptionist.local")
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "SuperAdmin!2026")

FAQ = """# FAQ — Clinique Dentaire Dupont

## Horaires
La clinique est ouverte du lundi au vendredi de 9h00 à 18h00, et le samedi de 9h00 à 12h30.
Nous sommes fermés le dimanche et les jours fériés.

## Adresse et accès
Nous sommes situés au 12 rue de la Paix, 75002 Paris.
Métro ligne 3, station Opéra. Un parking public se trouve à 50 mètres, rue Auber.

## Prestations et tarifs
- Consultation de contrôle : 30 minutes, 40 €
- Détartrage : 45 minutes, 70 €
- Soins conservateurs (composite) : 45 minutes, 90 €
- Extraction dentaire simple : 30 minutes, 120 €
- Blanchiment : 60 minutes, 250 €
- Devis orthodontique : 30 minutes, gratuit

## Préparer sa venue
Merci d'arriver 10 minutes avant le rendez-vous avec votre carte Vitale et votre mutuelle.
En cas de retard de plus de 15 minutes, le rendez-vous peut être reporté.

## Annulation
Toute annulation doit être signalée au moins 24 heures à l'avance afin de libérer le créneau.

## Urgences
En cas d'urgence vitale, appelez le 15. Pour une urgence dentaire en dehors des horaires,
rendez-vous aux urgences de l'hôpital le plus proche.
"""


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        from sqlalchemy import select

        existing = (
            await db.execute(select(Tenant).where(Tenant.slug == "clinique-dupont"))
        ).scalar_one_or_none()
        if existing:
            print("Le tenant de démonstration existe déjà — rien à faire.")
            return

        # Super admin (global)
        if not (
            await db.execute(select(User).where(User.email == SUPER_ADMIN_EMAIL))
        ).scalar_one_or_none():
            db.add(User(
                email=SUPER_ADMIN_EMAIL,
                password_hash=hash_password(SUPER_ADMIN_PASSWORD),
                full_name="Super Admin",
                role="super_admin",
                tenant_id=None,
            ))

        tenant = Tenant(
            slug="clinique-dupont",
            name="Clinique Dentaire Dupont",
            sector="Santé / Dentisterie",
            description="Cabinet dentaire généraliste à Paris, accueil 5j/7.",
            address="12 rue de la Paix, 75002 Paris",
            phone="+33 1 42 00 00 00",
            email="contact@clinique-dupont.fr",
            website="https://clinique-dupont.fr",
            timezone="Europe/Paris",
            languages=["fr", "en"],
            business_hours={
                "monday": {"open": "09:00", "close": "18:00"},
                "tuesday": {"open": "09:00", "close": "18:00"},
                "wednesday": {"open": "09:00", "close": "18:00"},
                "thursday": {"open": "09:00", "close": "18:00"},
                "friday": {"open": "09:00", "close": "18:00"},
                "saturday": {"open": "09:00", "close": "12:30"},
                "sunday": None,
            },
        )
        db.add(tenant)
        await db.flush()

        db.add(User(
            tenant_id=tenant.id, email="admin@clinique-dupont.fr",
            password_hash=hash_password("Demo!2026"), full_name="Dr Dupont", role="admin",
        ))
        db.add(User(
            tenant_id=tenant.id, email="conseiller@clinique-dupont.fr",
            password_hash=hash_password("Demo!2026"), full_name="Marie Conseillère", role="agent",
        ))

        db.add(ReceptionistConfig(
            tenant_id=tenant.id,
            name="Léa",
            tone="professionnel et chaleureux",
            style="concis, rassurant, sans jargon médical",
            greeting="Bonjour ! Je suis Léa, l'assistante de la Clinique Dentaire Dupont. "
                     "Je peux renseigner nos horaires, nos tarifs ou vous proposer un rendez-vous. Comment vous aider ?",
            instructions={
                "do": ["proposer des créneaux réels", "redemander le nom avant de réserver"],
                "avoid": ["inventer des prix", "donner des diagnostics médicaux"],
                "transfer": ["douleur aiguë", "urgence médicale", "plainte"],
            },
            services=[
                {"name": "Consultation de contrôle", "duration_min": 30, "description": "Bilan annuel", "price": "40 €"},
                {"name": "Détartrage", "duration_min": 45, "description": "Nettoyage professionnel", "price": "70 €"},
                {"name": "Soins conservateurs", "duration_min": 45, "description": "Composite esthétique", "price": "90 €"},
                {"name": "Extraction dentaire simple", "duration_min": 30, "description": "", "price": "120 €"},
                {"name": "Blanchiment", "duration_min": 60, "description": "Éclaircissement au fauteuil", "price": "250 €"},
                {"name": "Devis orthodontique", "duration_min": 30, "description": "Gratuit", "price": "Gratuit"},
            ],
            is_published=True,
        ))

        for rule in default_rules_payload():
            db.add(BusinessRule(tenant_id=tenant.id, **rule))

        source = KnowledgeSource(
            tenant_id=tenant.id, type="faq", name="FAQ clinique", content=FAQ, status="pending",
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)

        chunks = await ingest_source(db, source)
        print(f"Tenant de démonstration créé : clinique-dupont ({chunks} chunks indexés)")
        print(f"  Super admin : {SUPER_ADMIN_EMAIL} / {SUPER_ADMIN_PASSWORD}")
        print("  Admin       : admin@clinique-dupont.fr / Demo!2026")
        print("  Agent       : conseiller@clinique-dupont.fr / Demo!2026")


if __name__ == "__main__":
    asyncio.run(main())
