"""Higiene de datos: vincular trámites Allianz huérfanos con su cliente probable.

Los trámites con la relación 'Clientes General' vacía hacen que Tomi 'no encuentre'
pendientes que sí existen. Acá:
  1) Traemos los huérfanos (Tickets Allianz sin cliente).
  2) Indexamos TODOS los clientes por token de nombre.
  3) Para cada huérfano, sugerimos el cliente más parecido por el nombre del trámite.

El equipo confirma cada sugerencia desde la plataforma (la escritura a Notion la hace
notion_client.vincular_ticket_a_cliente). 100% determinístico, sin LLM.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from app.services.tomi import notion_client as nc

# Prefijos de reenvío de mail que ensucian el título del trámite.
_PREFIJOS = re.compile(r"^\s*(rv|fw|fwd|re)\s*:\s*", re.IGNORECASE)
# Títulos genéricos que NO son un nombre de cliente → no sugerimos.
_GENERICOS = {
    "", "comprobante de pago", "comprobante", "pago", "solicitud", "documento",
    "tramite", "cobranza", "endoso", "siniestro", "aclaracion", "renovacion",
}


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s = _PREFIJOS.sub("", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9 ]", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: Optional[str]) -> List[str]:
    return [t for t in _norm(s).split() if len(t) >= 3]


def tickets_con_sugerencia(umbral: float = 0.84) -> List[Dict[str, Any]]:
    """Lista de huérfanos, cada uno con la sugerencia de cliente (o None)."""
    orphans = nc.tickets_allianz_sin_cliente()
    clientes = nc.listar_clientes_general()

    # Índice invertido: token de nombre -> [(cliente, nombre_normalizado)]
    idx: Dict[str, List[Any]] = {}
    for c in clientes:
        n = _norm(c.get("nombre"))
        if not n:
            continue
        for tok in set(_tokens(c.get("nombre"))):
            idx.setdefault(tok, []).append((c, n))

    result: List[Dict[str, Any]] = []
    for t in orphans:
        titulo = t.get("Nombre del Trámite") or ""
        nt = _norm(titulo)
        sug: Optional[Dict[str, Any]] = None

        if nt and nt not in _GENERICOS:
            # Candidatos: clientes que comparten al menos un token con el título.
            cands: Dict[str, Any] = {}
            for tok in set(_tokens(titulo)):
                for c, n in idx.get(tok, []):
                    cands[c["id"]] = (c, n)
            best, best_score = None, 0.0
            for c, n in cands.values():
                if not n:
                    continue
                sc = SequenceMatcher(None, nt, n).ratio()
                if n in nt or nt in n:           # contención = match fuerte
                    sc = max(sc, 0.9)
                if sc > best_score:
                    best, best_score = c, sc
            if best and best_score >= umbral:
                sug = {
                    "cliente_id": best["id"],
                    "nombre": best.get("nombre"),
                    "correo": best.get("correo"),
                    "score": round(best_score, 2),
                }

        result.append({
            "ticket_id": t.get("_id"),
            "tramite": titulo,
            "tipo": t.get("Tipo de Trámite"),
            "estado": t.get("Estado"),
            "url": t.get("_url"),
            "sugerencia": sug,
        })

    # Con sugerencia primero, mejores scores arriba.
    result.sort(key=lambda r: (r["sugerencia"] is None, -(r["sugerencia"]["score"] if r["sugerencia"] else 0.0)))
    return result
