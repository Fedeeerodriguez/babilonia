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

_ENTRAR = re.compile(r"^\s*demo\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE)
_SALIR = re.compile(r"^\s*salir\s+(?:del?\s+)?(?:modo\s+)?demo\s*[.!]?\s*$", re.IGNORECASE)


def usuario() -> str:
    return os.getenv("TOMI_DEMO_USUARIO", "").strip()


def email() -> str:
    return (os.getenv("TOMI_DEMO_EMAIL", "") or EMAIL_DEFAULT).strip().lower()


def nombre() -> str:
    return (os.getenv("TOMI_DEMO_NOMBRE", "") or NOMBRE_DEFAULT).strip()


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


NOTA_BIENVENIDA = (
    "SISTEMA: este número acaba de activar el MODO DEMO como el cliente ficticio \"{nombre}\". "
    "Confirmale en una frase que el registro demo quedó listo, que desde ahora lo atendés como "
    "cliente y que puede preguntarte por sus pólizas, pagos o trámites. Para salir: SALIR DEMO."
)
NOTA_CLAVE_MAL = (
    "SISTEMA: el usuario intentó entrar al modo demo pero el usuario o la contraseña no son "
    "correctos. Decíselo en una frase y pedile que lo revise. No reveles el usuario ni la clave."
)
NOTA_SALIDA = ("SISTEMA: este número salió del modo demo. Confirmáselo en una frase.")
NOTA_SALIDA_SIN_DEMO = ("SISTEMA: el usuario pidió salir del modo demo pero no estaba en modo "
                        "demo. Decíselo en una frase.")
