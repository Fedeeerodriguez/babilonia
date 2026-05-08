"""Seed datos demo (admin user + mensajes sintéticos) para E2E local con SQLite."""
import random
from datetime import datetime, timedelta, timezone
from app.database import SessionLocal, Base, engine
from app import models
from app.security import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# Admin
if not db.query(models.User).filter(models.User.email == "admin@babilonia.com").first():
    db.add(models.User(
        email="admin@babilonia.com",
        password_hash=hash_password("babilonia123"),
        full_name="Admin Babilonia",
        role=models.UserRole.admin,
        operator_name="Admin",
    ))
    db.commit()
    print("OK admin@babilonia.com / babilonia123")

# Mensajes demo
if db.query(models.Message).count() == 0:
    now = datetime.now(timezone.utc)
    asesores = ["María González", "Juan Pérez", "Lucía Romero"]
    waids = ["5491155551001", "5491155551002", "5491155551003", "5491155551004"]
    nombres = {"5491155551001": "Belinda López", "5491155551002": "Carlos Ruiz",
               "5491155551003": "Andrea Soto",   "5491155551004": "Pedro Núñez"}

    for d in range(7):
        for waid in waids:
            base = now - timedelta(days=d, hours=random.randint(0, 23))
            for k in range(random.randint(2, 6)):
                t = base + timedelta(minutes=k * random.randint(5, 90))
                if k % 2 == 0:
                    db.add(models.Message(
                        wa_id=waid, sender_name=nombres[waid], direction=models.MessageDirection.cliente,
                        message_type="text", content=f"Consulta {k} sobre PPR / Patrimonial", created_at=t,
                    ))
                else:
                    db.add(models.Message(
                        wa_id=waid, sender_name=nombres[waid],
                        operator_name=random.choice(asesores),
                        direction=random.choice([models.MessageDirection.asesor, models.MessageDirection.bot]),
                        message_type="text", content=f"Respuesta del equipo #{k}", created_at=t,
                    ))
    db.commit()
    print(f"OK {db.query(models.Message).count()} mensajes demo")

db.close()
print("seed ok")
