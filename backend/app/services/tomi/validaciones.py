"""Detección de inconsistencias en datos Notion.

Corre DESPUÉS de bd.consultar() y agrega una lista de advertencias al resultado.
Útil para que Tommy (y el asesor humano) sepan cuando un dato registrado parece
incorrecto, faltante o contradictorio.

Cada advertencia tiene:
- severidad: "info" | "warning" | "error"
- tipo: código corto para tracking
- entidad: a qué se refiere (cliente_id, poliza, etc.)
- mensaje: descripción humana
- sugerencia: qué acción tomar (opcional)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Regex permisivo de teléfono: empieza con + o dígito, al menos 7 dígitos en total
RX_TELEFONO = re.compile(r"^[\+]?[\d\s\-\(\)]{7,}$")


def _es_telefono_valido(tel: Optional[str]) -> bool:
    if not tel or not isinstance(tel, str):
        return False
    tel = tel.strip()
    if not tel:
        return False
    # Tiene que tener al menos 7 dígitos cuando le sacás separadores
    digits_only = re.sub(r"[^\d]", "", tel)
    if len(digits_only) < 7:
        return False
    return bool(RX_TELEFONO.match(tel))


def detectar(resultado: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Inspecciona el resultado de bd.consultar y devuelve lista de advertencias."""
    advs: List[Dict[str, Any]] = []

    # --- 1. Validaciones sobre cada usuario ---
    for u in resultado.get("usuarios") or []:
        if not isinstance(u, dict):
            continue
        tipo = u.get("tipo")
        data = u.get("data") or {}
        exp = u.get("expandido") or {}
        uid = data.get("_id")
        email = u.get("email")
        nombre = u.get("nombre") or "(sin nombre)"

        # 1a. Teléfono no parece teléfono
        tel = u.get("telefono")
        if tel and not _es_telefono_valido(tel):
            advs.append({
                "severidad": "warning",
                "tipo": "telefono_invalido",
                "entidad": email or uid,
                "mensaje": f"El teléfono registrado de {nombre} no parece un número válido: «{tel}»",
                "sugerencia": "Verificar y corregir el campo Teléfono en Notion.",
            })

        # 1b. Cliente sin Asesor asignado (campo vacío)
        if tipo == "cliente":
            cliente_asesor = data.get("Asesor") or []
            crm_asesores = data.get("CRM Asesores") or []
            tiene_asesor_directo = bool(cliente_asesor) or bool(crm_asesores)

            # 1b.i. CRM Asesores apunta a sí mismo (data sucia)
            for rel in crm_asesores:
                rel_id = rel.get("id") if isinstance(rel, dict) else rel
                if rel_id == uid:
                    advs.append({
                        "severidad": "warning",
                        "tipo": "crm_asesores_self_reference",
                        "entidad": email or uid,
                        "mensaje": f"El campo CRM Asesores de {nombre} apunta a sí mismo (auto-referencia).",
                        "sugerencia": "Corregir la relación CRM Asesores en Notion para que apunte al asesor real.",
                    })

            # 1b.ii. Cliente sin asesor directo pero tiene asesor en sus emisiones
            exp_asesor = exp.get("asesor")
            if not tiene_asesor_directo and exp_asesor and exp_asesor.get("_source") == "from_emision":
                ase_name = exp_asesor.get("Nombre Completo") or "(sin nombre)"
                advs.append({
                    "severidad": "info",
                    "tipo": "asesor_solo_en_emisiones",
                    "entidad": email or uid,
                    "mensaje": f"{nombre} no tiene Asesor asignado en su record, pero sus emisiones figuran con {ase_name}.",
                    "sugerencia": "Asignar el campo Asesor en el record del cliente para mantener la relación bidireccional.",
                })

        # 1c. Asesor con desfase entre cierres declarados y emisiones reales
        if tipo == "asesor":
            cierres_total = data.get("Cierres en Total") or 0
            total_emis = exp.get("total_emisiones") or 0
            # Solo flag si hay emisiones reales pero el contador dice 0 o muy desviado
            if total_emis > 0 and cierres_total == 0:
                advs.append({
                    "severidad": "warning",
                    "tipo": "cierres_inconsistente",
                    "entidad": email or uid,
                    "mensaje": f"{nombre} tiene 0 cierres registrados pero {total_emis} emisiones reales en Notion.",
                    "sugerencia": "Revisar la fórmula 'Cierres en Total' o forzar refresh.",
                })

    # --- 2. Validaciones sobre emisiones ---
    for e in resultado.get("emisiones") or []:
        estado = e.get("Estado")
        prima = e.get("Prima")
        poliza = e.get("Número de Póliza") or e.get("Solicitud") or "(sin póliza)"
        cliente = e.get("Nombre Cliente") or "(sin cliente)"
        fecha_emi = e.get("Fecha de Emisión")
        if isinstance(fecha_emi, dict):
            fecha_emi = fecha_emi.get("start")

        # 2a. Activa sin prima
        if estado == "Activa" and (prima is None or prima == 0):
            advs.append({
                "severidad": "warning",
                "tipo": "poliza_activa_sin_prima",
                "entidad": poliza,
                "mensaje": f"La póliza «{poliza}» de {cliente} está Activa pero tiene Prima 0/sin valor.",
                "sugerencia": "Verificar el valor de Prima en Notion.",
            })

        # 2b. Activa sin fecha de emisión
        if estado == "Activa" and not fecha_emi:
            advs.append({
                "severidad": "info",
                "tipo": "poliza_activa_sin_fecha_emision",
                "entidad": poliza,
                "mensaje": f"La póliza «{poliza}» de {cliente} está Activa pero no tiene Fecha de Emisión cargada.",
                "sugerencia": "Cargar Fecha de Emisión en Notion.",
            })

        # 2c. Sin Correo Cliente cuando el resto del registro está completo
        if estado in ("Activa", "Pagada – Pendiente de Emisión") and not e.get("Correo Cliente"):
            advs.append({
                "severidad": "info",
                "tipo": "poliza_sin_correo_cliente",
                "entidad": poliza,
                "mensaje": f"La póliza «{poliza}» de {cliente} no tiene Correo Cliente registrado.",
                "sugerencia": "Cargar Correo Cliente en la emisión.",
            })

    # --- 3. Validaciones sobre cobranzas ---
    for c in resultado.get("cobranzas") or []:
        poliza = c.get("Póliza") or "(sin póliza)"
        dias_atraso = c.get("Días de atraso") or c.get("Días de Atraso Actuales") or 0
        try:
            dias_atraso = int(dias_atraso)
        except Exception:
            dias_atraso = 0
        monto_faltante = c.get("Monto Faltante") or 0
        estado_cob = c.get("Estado de Cobranza")

        # 3a. Atraso significativo (>15 días)
        if dias_atraso > 15:
            advs.append({
                "severidad": "warning",
                "tipo": "cobranza_atraso_alto",
                "entidad": poliza,
                "mensaje": f"Cobranza de «{poliza}» tiene {dias_atraso} días de atraso. Estado: {estado_cob or 'desconocido'}.",
                "sugerencia": "Contactar al cliente para regularizar el pago.",
            })

        # 3b. Monto faltante sin atraso (caso raro)
        if monto_faltante and monto_faltante > 0 and dias_atraso == 0:
            advs.append({
                "severidad": "info",
                "tipo": "cobranza_faltante_sin_atraso",
                "entidad": poliza,
                "mensaje": f"Cobranza de «{poliza}»: hay monto faltante (${monto_faltante}) pero días de atraso es 0.",
                "sugerencia": "Verificar si la fecha límite ya pasó.",
            })

    return advs


def resumen_severidades(advs: List[Dict[str, Any]]) -> Dict[str, int]:
    """Cuenta advertencias por severidad."""
    out = {"info": 0, "warning": 0, "error": 0}
    for a in advs:
        s = a.get("severidad", "info")
        out[s] = out.get(s, 0) + 1
    return out
