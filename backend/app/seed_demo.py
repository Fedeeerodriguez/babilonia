"""Seed DEMO — cartera ficticia completa para mostrar el sistema en producción.

Genera datos 100% inventados (nada de clientes reales) pero realistas:
  - 1 admin + 4 asesores (cada uno con login)
  - 12 clientes con conversaciones de WhatsApp a lo largo de ~30 días
  - Respuestas de Tommy (bot), seguimientos de asesores y templates
  - Documentos en la base de conocimiento (documents_meta)
  - Uso del agente interno (agent_chats) para que las analíticas tengan datos

Idempotente: si detecta que ya hay datos demo (admin demo presente) NO duplica.
Forzar recarga: correr con  DEMO_RESET=1  (borra messages/docs/agent_chats demo y recrea).

Uso:
    python -m app.seed_demo
o en el deploy, setear  DEMO_SEED=1  y se corre al arrancar (ver main.py).
"""
import os
import random
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal, Base, engine
from app import models
from app.security import hash_password

random.seed(42)  # determinístico → demos reproducibles

Base.metadata.create_all(bind=engine)
db = SessionLocal()

DEMO_ADMIN_EMAIL = "demo@babilonia.com"
DEMO_ADMIN_PASS = "DemoBabilonia2026"

# ---------------------------------------------------------------- usuarios
ASESORES = [
    {"email": "sofia.martinez@babilonia.demo",  "full_name": "Sofía Martínez",  "operator_name": "Sofía Martínez"},
    {"email": "diego.fernandez@babilonia.demo", "full_name": "Diego Fernández", "operator_name": "Diego Fernández"},
    {"email": "valentina.gomez@babilonia.demo", "full_name": "Valentina Gómez", "operator_name": "Valentina Gómez"},
    {"email": "matias.rios@babilonia.demo",     "full_name": "Matías Ríos",     "operator_name": "Matías Ríos"},
]
ASESOR_PASS = "Asesor2026"

# ---------------------------------------------------------------- clientes ficticios
CLIENTES = [
    {"wa_id": "5491160000101", "nombre": "Lucía Sandoval",     "producto": "PPR Optimaxx Plus"},
    {"wa_id": "5491160000102", "nombre": "Ramiro Cáceres",     "producto": "Seguro Patrimonial Hogar"},
    {"wa_id": "5491160000103", "nombre": "Florencia Aguirre",  "producto": "GMM Elite"},
    {"wa_id": "5491160000104", "nombre": "Tomás Benítez",      "producto": "Seguro Auto"},
    {"wa_id": "5491160000105", "nombre": "Camila Ferreyra",    "producto": "PPR Educacional"},
    {"wa_id": "5491160000106", "nombre": "Joaquín Medina",     "producto": "Rentas Privadas"},
    {"wa_id": "5491160000107", "nombre": "Agustina Pereyra",   "producto": "Seguro Patrimonial Residencial"},
    {"wa_id": "5491160000108", "nombre": "Bruno Acosta",       "producto": "GMM Familiar"},
    {"wa_id": "5491160000109", "nombre": "Martina Vega",       "producto": "PPR Optimaxx Plus"},
    {"wa_id": "5491160000110", "nombre": "Nicolás Herrera",    "producto": "Seguro Auto Premium"},
    {"wa_id": "5491160000111", "nombre": "Julieta Morales",    "producto": "Protección Elite"},
    {"wa_id": "5491160000112", "nombre": "Federico Luna",      "producto": "PPR + GMM (multiproducto)"},
]

# Guiones realistas de conversación (cliente -> tommy -> a veces asesor)
GUIONES = [
    [
        ("cliente", "Hola, quería saber cómo va mi póliza de {producto}"),
        ("bot", "¡Hola {nombre}! 👋 Tu póliza de {producto} está activa y al día. La próxima cuota vence el día 10 del mes que viene. ¿Querés que te pase el detalle del plan o el comprobante de pago?"),
        ("cliente", "Sí, pasame el detalle por favor"),
        ("bot", "Perfecto. Tu plan {producto} tiene una prima mensual y aportes que se acreditan a tu fondo. Te dejo el resumen y cualquier duda te puede ampliar tu asesor. 📄"),
    ],
    [
        ("cliente", "Buenas, necesito hacer un cambio en los datos de mi {producto}"),
        ("bot", "¡Hola {nombre}! Claro, puedo ayudarte a iniciar la modificación de tu {producto}. ¿Qué dato necesitás actualizar: domicilio, medio de pago o beneficiarios?"),
        ("cliente", "El medio de pago, quiero cambiar la tarjeta"),
        ("bot", "Genial, dejo registrada la solicitud de cambio de medio de pago. Un asesor te va a contactar para validar los datos de forma segura. 🔒"),
        ("asesor", "Hola {nombre}, soy {asesor} de Babilonia. Ya tengo tu solicitud de cambio de tarjeta, te ayudo a completarla."),
    ],
    [
        ("cliente", "Tuve un siniestro con el {producto}, ¿qué tengo que hacer?"),
        ("bot", "Lamento lo ocurrido, {nombre}. Para tu {producto} el primer paso es denunciar el siniestro. Te guío: necesitás número de póliza, fecha y una breve descripción. ¿Querés que inicie la denuncia ahora?"),
        ("cliente", "Sí, dale"),
        ("bot", "Listo, dejé iniciada la denuncia de siniestro. Un asesor especializado va a tomar el caso y te contacta a la brevedad. 🧾"),
        ("asesor", "Hola {nombre}, soy {asesor}. Estoy con tu denuncia de siniestro, ya pedí la documentación al área correspondiente."),
    ],
    [
        ("cliente", "Quería consultar por la renovación de mi {producto}"),
        ("bot", "¡Hola {nombre}! Tu {producto} entra en período de renovación pronto. La renovación es automática y te mantiene las condiciones vigentes. ¿Querés revisar coberturas o sumar algún beneficio?"),
        ("cliente", "Me interesa sumar cobertura, ¿qué opciones hay?"),
        ("bot", "Buenísimo. Para tu perfil puedo sugerir mejoras de cobertura y un asesor te arma una propuesta a medida. Dejo la consulta derivada. 📈"),
    ],
    [
        ("cliente", "Hola! quiero información para contratar {producto}"),
        ("bot", "¡Hola {nombre}! Gracias por tu interés en {producto} 🙌. Te cuento: es un plan pensado para proteger y hacer crecer tu capital. ¿Querés que coordine una llamada con un asesor para armarte una propuesta sin cargo?"),
        ("cliente", "Sí, me gustaría"),
        ("bot", "Perfecto, agendo el contacto. Un asesor se comunica con vos para coordinar día y horario. 📅"),
        ("asesor", "¡Hola {nombre}! Soy {asesor} de Babilonia. Coordinamos una llamada para mostrarte la propuesta de {producto}."),
    ],
]

TEMPLATES = [
    ("recordatorio_cuota", "Hola {nombre}, te recordamos que la cuota de tu {producto} vence pronto. ¡Gracias por confiar en Babilonia!"),
    ("bienvenida", "¡Bienvenido/a a Babilonia, {nombre}! Tu asesor y Tommy están para ayudarte cuando lo necesites. 💙"),
]

DOCS = [
    "Manual_Optimaxx_Plus_2026.pdf",
    "Condiciones_Generales_GMM_Elite.pdf",
    "Reglamento_Siniestros_Patrimonial.pdf",
    "Tabla_Comisiones_Asesores_Q2.pdf",
    "Guia_Renovaciones_Allianz.pdf",
    "FAQ_Clientes_Babilonia.pdf",
    "Plan_Educacional_Folleto.pdf",
    "Proceso_Onboarding_Cliente.pdf",
]

PREGUNTAS_AGENTE = [
    "¿Cuántas pólizas activas tiene Sofía Martínez en su cartera?",
    "Mostrame los clientes con cuota vencida este mes",
    "¿Cuál es el total de comisiones del Q2?",
    "Resumime los siniestros abiertos de la semana",
    "¿Qué clientes están en proceso de renovación?",
    "Dame el ranking de asesores por pólizas emitidas",
]


def _ya_sembrado() -> bool:
    return db.query(models.User).filter(models.User.email == DEMO_ADMIN_EMAIL).first() is not None


def _reset():
    print("DEMO_RESET=1 → limpiando datos demo previos…")
    db.query(models.AgentChatMessage).delete()
    db.query(models.Message).delete()
    db.query(models.DocumentMeta).delete()
    db.query(models.User).filter(models.User.email.like("%babilonia.demo")).delete(synchronize_session=False)
    db.query(models.User).filter(models.User.email == DEMO_ADMIN_EMAIL).delete(synchronize_session=False)
    db.commit()


def run():
    if os.getenv("DEMO_RESET", "0") == "1":
        _reset()
    elif _ya_sembrado():
        print("Demo ya sembrado (existe demo@babilonia.com). Nada que hacer. Usar DEMO_RESET=1 para recrear.")
        return

    now = datetime.now(timezone.utc)

    # --- admin demo ---
    admin = models.User(
        email=DEMO_ADMIN_EMAIL, password_hash=hash_password(DEMO_ADMIN_PASS),
        full_name="Admin Demo Babilonia", role=models.UserRole.admin, operator_name="Admin Demo",
    )
    db.add(admin)

    # --- asesores ---
    asesor_users = []
    for a in ASESORES:
        u = models.User(
            email=a["email"], password_hash=hash_password(ASESOR_PASS),
            full_name=a["full_name"], role=models.UserRole.asesor, operator_name=a["operator_name"],
        )
        db.add(u)
        asesor_users.append(u)
    db.commit()

    nombres_asesores = [a["operator_name"] for a in ASESORES]

    # --- conversaciones (mensajes) ---
    total_msgs = 0
    for cli in CLIENTES:
        n_convs = random.randint(2, 4)
        for _ in range(n_convs):
            dia = random.randint(0, 29)
            base = now - timedelta(days=dia, hours=random.randint(8, 20), minutes=random.randint(0, 59))
            guion = random.choice(GUIONES)
            asesor = random.choice(nombres_asesores)
            t = base
            for emisor, texto in guion:
                t = t + timedelta(minutes=random.randint(1, 8))
                msg = texto.format(nombre=cli["nombre"].split()[0], producto=cli["producto"], asesor=asesor)
                if emisor == "cliente":
                    db.add(models.Message(
                        wa_id=cli["wa_id"], sender_name=cli["nombre"],
                        direction=models.MessageDirection.cliente,
                        message_type="text", content=msg, created_at=t,
                    ))
                elif emisor == "bot":
                    db.add(models.Message(
                        wa_id=cli["wa_id"], sender_name=cli["nombre"], operator_name="Tommy",
                        direction=models.MessageDirection.bot,
                        message_type="text", content=msg, created_at=t,
                    ))
                else:  # asesor
                    db.add(models.Message(
                        wa_id=cli["wa_id"], sender_name=cli["nombre"], operator_name=asesor,
                        direction=models.MessageDirection.asesor,
                        message_type="text", content=msg, created_at=t,
                    ))
                total_msgs += 1

        # algún template suelto
        if random.random() < 0.5:
            tname, ttext = random.choice(TEMPLATES)
            db.add(models.Message(
                wa_id=cli["wa_id"], sender_name=cli["nombre"], operator_name="Sistema",
                direction=models.MessageDirection.template, message_type="template", template_name=tname,
                content=ttext.format(nombre=cli["nombre"].split()[0], producto=cli["producto"]),
                created_at=now - timedelta(days=random.randint(0, 29)),
            ))
            total_msgs += 1
    db.commit()

    # --- documentos (base de conocimiento) ---
    for i, fn in enumerate(DOCS):
        db.add(models.DocumentMeta(
            file_name=fn, source="demo", uploaded_by="Admin Demo",
            size_bytes=random.randint(120_000, 2_400_000), chunks=random.randint(8, 60),
            status="ready", storage_path=f"demo/{fn}",
            uploaded_at=now - timedelta(days=random.randint(1, 40)),
        ))
    db.commit()

    # --- uso del agente interno (analíticas) ---
    for _ in range(40):
        u = random.choice(asesor_users + [admin])
        t = now - timedelta(days=random.randint(0, 29), hours=random.randint(0, 23))
        q = random.choice(PREGUNTAS_AGENTE)
        db.add(models.AgentChatMessage(user_id=u.id, role="user", content=q, created_at=t))
        db.add(models.AgentChatMessage(
            user_id=u.id, role="assistant",
            content="Procesado: consulté la cartera y armé el resumen solicitado.",
            tool_calls=[{"tool": random.choice(["bases_datos", "renovaciones", "comisiones", "siniestros", "memorias"])}],
            created_at=t + timedelta(seconds=random.randint(2, 9)),
        ))
    db.commit()

    print("=" * 56)
    print("  SEED DEMO OK")
    print("=" * 56)
    print(f"  Admin demo : {DEMO_ADMIN_EMAIL} / {DEMO_ADMIN_PASS}")
    print(f"  Asesores   : {len(ASESORES)} (pass: {ASESOR_PASS})")
    print(f"  Clientes   : {len(CLIENTES)}")
    print(f"  Mensajes   : {total_msgs}")
    print(f"  Documentos : {len(DOCS)}")
    print("=" * 56)


if __name__ == "__main__":
    try:
        run()
    finally:
        db.close()
