"""Renderizador determinístico de informes — sin LLM, 100% fiel a Notion.

Toma el resultado crudo de bd.consultar() y genera markdown con plantillas
fijas. Cada número, cada string, sale del dict verbatim. Cero parafraseo.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _safe(val: Any, default: str = "—") -> str:
    if val is None or val == "":
        return default
    if isinstance(val, (list, dict)) and not val:
        return default
    return str(val)


def _md_link(text: str, url: Optional[str]) -> str:
    return f"[{text}]({url})" if url else text


def _render_usuario_asesor(u: Dict[str, Any]) -> List[str]:
    exp = u.get("expandido") or {}
    data = u.get("data") or {}
    lines = [
        f"### Asesor: **{_safe(u.get('nombre'))}**",
        f"- Email: `{u['email']}`",
        f"- Teléfono: `{_safe(u.get('telefono'))}`",
        f"- Estado: `{_safe(data.get('Estado de Asesor'))}`",
        f"- Nivel: `{_safe(data.get('Nivel'))}`",
        f"- Ubicación: `{_safe(data.get('Ubicación (Estado)'))}` ({_safe(data.get('Ubicación (País) '))})",
        f"- Fecha inicio capacitación: `{_safe((data.get('Inicio de Capacitación') or {}).get('start'))}`",
        f"- Cierres este mes: `{_safe(data.get('Cierres este Mes'))}`",
        f"- Cierres este año: `{_safe(data.get('Cierres este Año'))}`",
        f"- Cierres totales: `{_safe(data.get('Cierres en Total'))}`",
        f"- Tasa de cierre: `{_safe(data.get('Tasa de Cierre'))}`",
        f"- Último cierre: `{_safe((data.get('Último cierre') or {}).get('start'))}`",
        f"- Racha dorada: `{_safe(data.get('Racha Dorada'))}` | Racha roja: `{_safe(data.get('Racha Roja'))}`",
        f"- URL Notion: {_md_link('abrir record', data.get('_url'))}",
        "",
    ]

    # Conteos por fuente (transparencia)
    pf = exp.get("clientes_por_fuente") or {}
    if pf:
        lines.append("#### Conteo de clientes (por fuente, deduplicado al final)")
        lines.append(f"- En relaciones del record del asesor (forward): `{pf.get('total_forward_unico', 0)}`")
        for prop, n in (pf.get("forward_record_asesor") or {}).items():
            lines.append(f"  - `{prop}`: {n}")
        lines.append(f"- En DB Clientes con Asesor=él (backward): `{pf.get('total_backward_unico', 0)}`")
        lines.append(f"- Intersección (ambos lados): `{pf.get('interseccion', 0)}`")
        lines.append(f"- Solo forward: `{pf.get('solo_forward', 0)}` | Solo backward: `{pf.get('solo_backward', 0)}`")
        lines.append(f"- **TOTAL ÚNICO: `{exp.get('total_clientes', 0)}`**")
        lines.append("")

    # Lista completa de clientes
    clientes = exp.get("clientes") or []
    if clientes:
        lines.append(f"#### Lista completa de clientes ({len(clientes)})")
        for i, c in enumerate(clientes, 1):
            marker = "✓" if c.get("tiene_asesor_asignado") else "○"
            n = _md_link(_safe(c.get("nombre")), c.get("url"))
            correo = c.get("correo") or "—"
            tel = c.get("telefono") or "—"
            lines.append(f"{i}. {marker} {n} — `{correo}` — `{tel}`")
        lines.append("")
        lines.append("> Leyenda: ✓ = tiene a este asesor asignado (backward) | ○ = solo enlazado desde el record del asesor (forward)")
        lines.append("")

    # Emisiones
    emis = exp.get("emisiones") or []
    if emis:
        lines.append(f"#### Emisiones del asesor ({len(emis)})")
        for i, e_ in enumerate(emis, 1):
            sol = _md_link(_safe(e_.get("solicitud")), e_.get("url"))
            lines.append(
                f"{i}. {sol} — Cliente: `{_safe(e_.get('cliente'))}` | "
                f"Póliza: `{_safe(e_.get('poliza'))}` | "
                f"Prima: `{_safe(e_.get('prima'))}` | "
                f"Estado: `{_safe(e_.get('estado'))}` | "
                f"Fecha: `{_safe(e_.get('fecha_emision'))}`"
            )
        lines.append("")

    # Eventos Calendly
    eventos = exp.get("eventos_calendly") or []
    if eventos:
        lines.append(f"#### Eventos Calendly ({len(eventos)})")
        for i, ev in enumerate(eventos, 1):
            ev_link = _md_link(_safe(ev.get("evento")), ev.get("url"))
            lines.append(
                f"{i}. {ev_link} — `{_safe(ev.get('fecha'))}` | "
                f"Invitado: `{_safe(ev.get('invitado'))}` (`{_safe(ev.get('correo_invitado'))}`) | "
                f"Estado: `{_safe(ev.get('estado'))}`"
            )
        lines.append("")

    return lines


def _render_usuario_cliente(u: Dict[str, Any]) -> List[str]:
    exp = u.get("expandido") or {}
    data = u.get("data") or {}
    lines = [
        f"### Cliente: **{_safe(u.get('nombre'))}**",
        f"- Email: `{u['email']}`",
        f"- Teléfono (record cliente): `{_safe(u.get('telefono'))}`",
        f"- Fecha nacimiento: `{_safe((data.get('Fecha de Nacimiento') or {}).get('start'))}`",
        f"- Notas: `{_safe(data.get('Notas General'))}`",
        f"- URL Notion: {_md_link('abrir record', data.get('_url'))}",
        "",
    ]
    asesor = exp.get("asesor")
    if asesor:
        src = " (resuelto desde sus emisiones)" if asesor.get("_source") == "from_emision" else ""
        lines.append(f"#### Asesor asignado{src}")
        lines.append(
            f"- {_md_link(_safe(asesor.get('Nombre Completo')), asesor.get('_url'))} — "
            f"`{_safe(asesor.get('Correo'))}` — `{_safe(asesor.get('Teléfono'))}`"
        )
        lines.append("")

    emis = exp.get("emisiones") or []
    if emis:
        lines.append(f"#### Pólizas del cliente ({len(emis)})")
        for i, e_ in enumerate(emis, 1):
            sol = _md_link(_safe(e_.get("solicitud")), e_.get("url"))
            lines.append(
                f"{i}. {sol}\n"
                f"   - **Póliza:** `{_safe(e_.get('poliza'))}` | **Estado:** `{_safe(e_.get('estado'))}`\n"
                f"   - **Producto:** `{_safe(e_.get('producto'))}` | **Plazo:** `{_safe(e_.get('plazo'))}` años | **Valor plan:** `{_safe(e_.get('valor_plan'))}`\n"
                f"   - **Prima:** `{_safe(e_.get('prima'))}` | **Conducto cobro:** `{_safe(e_.get('conducto_cobro'))}` | **Fecha cobro original:** `{_safe(e_.get('fecha_cobro_original'))}`\n"
                f"   - **Asesor:** `{_safe(e_.get('asesor'))}` (`{_safe(e_.get('correo_asesor'))}`) | **Tel. cliente:** `{_safe(e_.get('telefono_cliente'))}`"
            )
            if e_.get("notas") and e_.get("notas") not in ("—", ""):
                lines.append(f"   - **Notas:** `{e_.get('notas')}`")
        lines.append("")
    return lines


def _render_usuario_estudiante(u: Dict[str, Any]) -> List[str]:
    data = u.get("data") or {}
    return [
        f"### Estudiante: **{_safe(u.get('nombre'))}**",
        f"- Email: `{u['email']}`",
        f"- Producto: `{_safe(data.get('Producto'))}`",
        f"- Fecha compra: `{_safe((data.get('Fecha de compra') or {}).get('start'))}`",
        f"- Tipo plan: `{_safe(data.get('Tipo de plan'))}`",
        f"- Estado: `{_safe(data.get('Estado'))}`",
        f"- URL Notion: {_md_link('abrir record', data.get('_url'))}",
        "",
    ]


def _render_usuario_prospecto(u: Dict[str, Any]) -> List[str]:
    return [
        f"### Prospecto (no encontrado en bases)",
        f"- Email consultado: `{u['email']}`",
        "",
    ]


def renderizar(resultado: Dict[str, Any]) -> str:
    """Genera markdown determinístico desde el resultado de bd.consultar().

    NO usa LLM. Todos los valores salen verbatim del dict.
    """
    lines: List[str] = ["# Informe de bases de datos — Tomi · Babilonia", ""]

    # Entidades identificadas
    stats = resultado.get("stats") or {}
    lines.append("## Consulta procesada")
    lines.append(f"- Emails consultados: `{stats.get('emails_consultados', 0)}`")
    lines.append(f"- Pólizas consultadas: `{stats.get('polizas_consultadas', 0)}`")
    lines.append(f"- Nombres cliente consultados: `{stats.get('nombres_clientes', 0)}`")
    lines.append(f"- Nombres asesor consultados: `{stats.get('nombres_asesores', 0)}`")
    lines.append(f"- Tiempo total: `{stats.get('tiempo_ms', 0)} ms` | Queries Notion: `{stats.get('queries_notion', 0)}`")
    lines.append("")

    # Usuarios
    usuarios = resultado.get("usuarios") or []
    if usuarios:
        lines.append("## Usuarios encontrados")
        lines.append("")
        for u in usuarios:
            t = u.get("tipo")
            if t == "asesor":
                lines.extend(_render_usuario_asesor(u))
            elif t == "cliente":
                lines.extend(_render_usuario_cliente(u))
            elif t == "estudiante":
                lines.extend(_render_usuario_estudiante(u))
            else:
                lines.extend(_render_usuario_prospecto(u))

    # Búsquedas por nombre
    asesores_n = resultado.get("asesores_por_nombre") or []
    if asesores_n:
        lines.append(f"## Asesores encontrados por nombre ({len(asesores_n)})")
        for a in asesores_n:
            nombre = a.get("Nombre Completo") or a.get("Primer Nombre") or "(sin nombre)"
            lines.append(
                f"- {_md_link(_safe(nombre), a.get('_url'))} — "
                f"`{_safe(a.get('Correo'))}` — `{_safe(a.get('Teléfono'))}`"
            )
        lines.append("")

    clientes_n = resultado.get("clientes_por_nombre") or []
    if clientes_n:
        lines.append(f"## Clientes encontrados por nombre ({len(clientes_n)})")
        for c in clientes_n:
            lines.append(
                f"- {_md_link(_safe(c.get('Nombre del Cliente')), c.get('_url'))} — "
                f"`{_safe(c.get('Correo'))}`"
            )
        lines.append("")

    # Emisiones (generales)
    emis = resultado.get("emisiones") or []
    if emis:
        lines.append(f"## Emisiones ({len(emis)})")
        for i, e_ in enumerate(emis, 1):
            sol = _md_link(_safe(e_.get("Solicitud")), e_.get("_url"))
            # Asesor resuelto via relation
            asesor_rel = e_.get("Asesor") or []
            asesor_nombre = (asesor_rel[0].get("name") if asesor_rel and isinstance(asesor_rel[0], dict) else None) or "—"
            fecha_emi = (e_.get("Fecha de Emisión") or {}).get("start") if isinstance(e_.get("Fecha de Emisión"), dict) else None
            fecha_cobro = (e_.get("Fecha de Cobro Original") or {}).get("start") if isinstance(e_.get("Fecha de Cobro Original"), dict) else None
            lines.append(
                f"{i}. {sol}\n"
                f"   - **Póliza:** `{_safe(e_.get('Número de Póliza'))}` | **Solicitud n°:** `{_safe(e_.get('Número de Solicitud'))}`\n"
                f"   - **Cliente:** `{_safe(e_.get('Nombre Cliente'))}` — `{_safe(e_.get('Correo Cliente'))}` — `{_safe(e_.get('Teléfono Cliente'))}`\n"
                f"   - **Asesor:** `{asesor_nombre}` (`{_safe(e_.get('Correo Asesor'))}`)\n"
                f"   - **Producto:** `{_safe(e_.get('Producto (nombre)'))}` | **Plazo:** `{_safe(e_.get('Plazo Comprometido'))}` años | **Valor plan:** `{_safe(e_.get('Valor Plan'))}`\n"
                f"   - **Prima:** `{_safe(e_.get('Prima'))}` `{_safe(e_.get('Periodicidad'))}` | **Conducto:** `{_safe(e_.get('Conducto de cobro'))}`\n"
                f"   - **Estado:** `{_safe(e_.get('Estado'))}` | **Fecha emisión:** `{_safe(fecha_emi)}` | **Fecha cobro original:** `{_safe(fecha_cobro)}`"
            )
            notas = e_.get("Notas de Emisión")
            if notas and notas != "—":
                lines.append(f"   - **Notas:** `{notas}`")
        lines.append("")

    # Cobranzas
    cobr = resultado.get("cobranzas") or []
    if cobr:
        lines.append(f"## Cobranzas ({len(cobr)})")
        for i, c in enumerate(cobr, 1):
            pol = _md_link(_safe(c.get("Póliza")), c.get("_url"))
            lines.append(
                f"{i}. {pol} — "
                f"Estado: `{_safe(c.get('Estado de Cobranza'))}` | "
                f"Días atraso: `{_safe(c.get('Días de atraso'))}` | "
                f"Próximo cobro: `{_safe((c.get('Próximo intento de cobro') or {}).get('start'))}`"
            )
        lines.append("")

    # Tickets Allianz
    tk = resultado.get("tickets_allianz") or []
    if tk:
        lines.append(f"## Tickets Allianz ({len(tk)})")
        for i, t in enumerate(tk, 1):
            tit = _md_link(_safe(t.get("Nombre del Trámite")), t.get("_url"))
            lines.append(
                f"{i}. {tit} — "
                f"Tipo: `{_safe(t.get('Tipo de Trámite'))}` | "
                f"Estado: `{_safe(t.get('Estado'))}` | "
                f"Fecha solicitud: `{_safe((t.get('Fecha de Solicitud') or {}).get('start'))}`"
            )
        lines.append("")

    # Calendly (general, no por usuario)
    cal = resultado.get("calendly") or []
    if cal:
        lines.append(f"## Eventos Calendly ({len(cal)})")
        for i, c in enumerate(cal, 1):
            ev = _md_link(_safe(c.get("Evento ")), c.get("_url"))
            lines.append(
                f"{i}. {ev} — "
                f"`{_safe((c.get('Fecha de Evento') or {}).get('start'))}` | "
                f"Invitado: `{_safe(c.get('Nombre del invitado'))}` (`{_safe(c.get('Correo invitado'))}`)"
            )
        lines.append("")

    # No encontrados
    ne = resultado.get("no_encontrados") or {}
    if ne.get("emails") or ne.get("polizas"):
        lines.append("## No encontrado")
        if ne.get("emails"):
            lines.append(f"- Emails sin match: {', '.join(f'`{e}`' for e in ne['emails'])}")
        if ne.get("polizas"):
            lines.append(f"- Pólizas sin match: {', '.join(f'`{p}`' for p in ne['polizas'])}")
        lines.append("")

    if len(lines) == 4:  # solo el header y consulta
        lines.append("**Sin resultados.** Verificá que los datos consultados existan en Notion o que la integración tenga acceso a las DBs relevantes.")

    return "\n".join(lines)
