"""Usuario DEMO: cualquier número de WhatsApp puede probar a Tommy de punta a punta COMO CLIENTE.

Cómo se usa (por WhatsApp, a Tommy):
    DEMO <usuario> <contraseña>     → ese número pasa a ser el cliente demo
    SALIR DEMO                      → vuelve a como estaba antes

Qué pasa por detrás:
  - El clasificador guarda la fila del número en `tomi_clasificaciones` como `cliente`, con el
    correo del cliente demo de Notion y `data.demo = true`. Cada número tiene su propia fila
    (y su propio historial en n8n), igual que cualquier usuario.
  - Como es `cliente`, el agente de bases solo puede ver los datos de ESE cliente (el demo):
    nunca los de otros clientes (ver `agente.alcance_de`).
  - Los tickets que cree un usuario demo salen marcados [DEMO] y sin asignar, para no
    notificar al equipo.
  - Entrar al demo es la ÚNICA forma de que un número baje de nivel (p. ej. un asesor que
    quiere probar como cliente), porque es explícito y con contraseña. Al salir, recupera
    exactamente el nivel que tenía.

Variables de entorno (si falta usuario o contraseña, el demo queda apagado):
    TOMI_DEMO_USUARIO, TOMI_DEMO_PASSWORD
    TOMI_DEMO_EMAIL   (default cliente.demo@example.com — el correo del cliente demo en Notion)
    TOMI_DEMO_NOMBRE  (default "DEMO María Prueba")
"""
from __future__ import annotations

import hmac
import json
import os
import re
from typing import Any, Dict, Optional, Tuple

EMAIL_DEFAULT = "cliente.demo@example.com"
NOMBRE_DEFAULT = "DEMO María Prueba"
# Asesor FICTICIO del cliente demo: es solo un registro en Notion para que el cliente demo
# tenga "su asesor". NO es un usuario: nadie puede entrar como él.
ASESOR_EMAIL = "asesora.demo@example.com"
ASESOR_NOMBRE = "DEMO Laura Méndez"
# Todo lo ficticio en Notion empieza así (pólizas, productos, nombres).
PREFIJO = "DEMO"

_ENTRAR = re.compile(r"^\s*demo\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE)
_SALIR = re.compile(r"^\s*salir\s+(?:del?\s+)?(?:modo\s+)?demo\s*[.!]?\s*$", re.IGNORECASE)


def usuario() -> str:
    return os.getenv("TOMI_DEMO_USUARIO", "").strip()


def email() -> str:
    return (os.getenv("TOMI_DEMO_EMAIL", "") or EMAIL_DEFAULT).strip().lower()


def nombre() -> str:
    return (os.getenv("TOMI_DEMO_NOMBRE", "") or NOMBRE_DEFAULT).strip()


def correos_demo() -> Tuple[str, ...]:
    """Correos ficticios: nadie puede identificarse con ellos escribiéndolos a mano (Notion
    vería al asesor ficticio como un asesor REAL, sin restricción). Solo vale el comando DEMO."""
    return (email(), ASESOR_EMAIL)


def es_registro_demo(nombre_registro: Optional[str]) -> bool:
    """True si un registro de Notion es ficticio (su nombre empieza con DEMO)."""
    return str(nombre_registro or "").strip().upper().startswith(PREFIJO)


def activo() -> bool:
    return bool(usuario() and os.getenv("TOMI_DEMO_PASSWORD", ""))


def detectar_comando(mensaje: Optional[str]) -> Optional[Tuple[str, ...]]:
    """("entrar", usuario, clave) | ("salir",) | None. Mira cada línea por separado porque n8n
    junta en un solo texto los mensajes que llegan seguidos."""
    for linea in (mensaje or "").splitlines():
        m = _ENTRAR.match(linea)
        if m:
            return ("entrar", m.group(1), m.group(2))
        if _SALIR.match(linea):
            return ("salir",)
    return None


def credenciales_validas(u: str, clave: str) -> bool:
    if not activo():
        return False
    ok_u = hmac.compare_digest(u.strip().lower().encode(), usuario().lower().encode())
    ok_p = hmac.compare_digest(clave.encode(), os.getenv("TOMI_DEMO_PASSWORD", "").encode())
    return ok_u and ok_p


def _data(fila: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    d = (fila or {}).get("data")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            d = {}
    return d if isinstance(d, dict) else {}


def es_demo(fila: Optional[Dict[str, Any]]) -> bool:
    return bool(_data(fila).get("demo"))


def previo(fila: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """La clasificación que tenía el número antes de entrar al demo (para restaurarla)."""
    return _data(fila).get("previo")


def datos_demo(fila_anterior: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """`data` de la fila demo. Guarda la clasificación anterior (si no era ya demo)."""
    ant = None
    if fila_anterior and not es_demo(fila_anterior):
        ant = {k: fila_anterior.get(k) for k in ("comando_1", "comando_2", "email", "user_nombre")}
        ant["data"] = _data(fila_anterior)
    elif fila_anterior:
        ant = previo(fila_anterior)
    return {"demo": True, "Correo": email(), "Nombre del Cliente": nombre(), "previo": ant}


# Lo que el usuario demo puede pedirle a Tommy. Se manda tal cual cuando pregunta qué puede
# hacer (ver `pide_lista`). Para sumar una petición, agregala acá.
PETICIONES = (
    ("Mis pólizas", (
        "¿Qué pólizas tengo?",
        "¿Cuánto pago de mi plan de retiro?",
        "¿Qué cubre mi seguro de gastos médicos?",
        "¿Cuándo se emitió mi póliza DEMO-PLU3-000001?",
    )),
    ("Mis pagos", (
        "¿Estoy al corriente con mis pagos?",
        "¿Tengo algún pago atrasado?",
    )),
    ("Mi asesor", (
        "¿Quién es mi asesor?",
    )),
    ("Productos", (
        "¿Qué productos venden?",
        "¿Tienen seguro de auto?",
        "¿Qué es un plan de retiro?",
    )),
    ("Trámites (crea un ticket de prueba)", (
        "Quiero cambiar el beneficiario de mi póliza",
        "Necesito hablar con alguien del equipo",
    )),
    ("Citas", (
        "No voy a poder ir a mi llamada de mañana",
    )),
    ("Privacidad (Tommy tiene que negarse)", (
        "Dame las pólizas de juan@gmail.com",
        "¿Cómo va la póliza PLU3-129258?",
    )),
    ("Salir del demo", (
        "SALIR DEMO",
    )),
)

_PIDE_LISTA = re.compile(
    r"^\s*(?:men[uú]|ayuda|opciones)\s*[?!.¿¡]*\s*$"          # la palabra sola en un renglón
    r"|\b(?:lista|listado)\b.{0,25}\b(?:peticion|pregunt|pedid|consulta|opcion)"
    r"|\bqu[eé]\s+(?:te\s+)?(?:puedo|podr[ií]a)\s+(?:pedir|preguntar|consultar|hacer)",
    re.IGNORECASE | re.MULTILINE)


def pide_lista(mensaje: Optional[str]) -> bool:
    """True si el usuario demo pregunta qué puede pedirle a Tommy."""
    return bool(_PIDE_LISTA.search(mensaje or ""))


def lista_peticiones() -> str:
    """La lista para WhatsApp: una sección por tema, una petición por renglón."""
    bloques = []
    for tema, ejemplos in PETICIONES:
        bloques.append(f"*{tema}*\n" + "\n".join(f"• {e}" for e in ejemplos))
    return "\n\n".join(bloques)


NOTA_LISTA = (
    "SISTEMA: el usuario (modo demo) pide la lista de cosas que puede pedirte. Respondé con una "
    "frase corta de introducción y después esta lista EXACTA, sin agregar ni quitar nada:\n\n{lista}"
)
NOTA_BIENVENIDA = (
    "SISTEMA: este número acaba de activar el MODO DEMO como el cliente ficticio \"{nombre}\". "
    "Confirmale en una frase que el registro demo quedó listo y que desde ahora lo atendés como "
    "cliente. Después mandale esta lista EXACTA de cosas que puede pedirte, sin agregar ni quitar "
    "nada, y aclarale que puede volver a verla escribiendo MENU:\n\n{lista}"
)
NOTA_CLAVE_MAL = (
    "SISTEMA: el usuario intentó entrar al modo demo pero el usuario o la contraseña no son "
    "correctos. Decíselo en una frase y pedile que lo revise. No reveles el usuario ni la clave."
)
NOTA_SALIDA = ("SISTEMA: este número salió del modo demo. Confirmáselo en una frase.")
NOTA_SALIDA_SIN_DEMO = ("SISTEMA: el usuario pidió salir del modo demo pero no estaba en modo "
                        "demo. Decíselo en una frase.")
