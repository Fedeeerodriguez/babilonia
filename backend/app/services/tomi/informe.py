"""Renderizador determinístico de informes — sin LLM, 100% fiel a Notion.

Toma el resultado crudo de bd.consultar() y genera markdown con plantillas
fijas. Cada número, cada string, sale del dict verbatim. Cero parafraseo.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.tomi import notion_client as nc


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

    # Desglose diferenciado de clientes (Ticket 2): NO mezclar todo en un número.
    dg = exp.get("clientes_desglose") or {}
    if dg:
        lines.append("#### Clientes del asesor (desglosados, NO sumar todo en un solo número)")
        lines.append(
            f"- 👤 **Clientes PROPIOS (es su asesor ante el cliente): `{dg.get('clientes_propios', 0)}`** "
            f"— de ellos ACTIVOS (póliza Activa): **`{dg.get('clientes_propios_activos', 0)}`**"
        )
        lines.append(f"  - Pólizas en SU portal DAF: `{dg.get('polizas_en_mi_portal_daf', 0)}`")
        otros = dg.get("polizas_en_portal_de_otros") or {}
        if otros:
            detalle = ", ".join(f"{k}: {v}" for k, v in otros.items())
            lines.append(f"  - Pólizas en portal de OTRO DAF (ej. el líder): `{sum(otros.values())}` ({detalle})")
        lines.append(f"- 🤝 Clientes ACOMPAÑADOS: `{dg.get('acompanados', 0)}`")
        lines.append(f"- 🔄 Clientes de MIGRACIÓN: `{dg.get('migracion', 0)}`")
        if dg.get("allianz_ppr_desde_daf") is not None:
            ini = dg.get("inicio_daf")
            suf = f" (desde activación DAF: {ini})" if ini else ""
            lines.append(f"- 🏛️ Clientes en portal Allianz (PPR){suf}: `{dg.get('allianz_ppr_desde_daf')}`")
        lines.append(
            f"_El total mixto anterior (`{exp.get('total_clientes', 0)}`) sumaba propios + acompañados + "
            f"migración + asignados; usá los números desglosados de arriba, NO ese total._"
        )
        lines.append("")
    else:
        # Fallback legacy (transparencia técnica) si no vino el desglose.
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

    tks = exp.get("tickets_allianz") or []
    if tks:
        lines.append(f"#### Trámites / Tickets Allianz del cliente ({len(tks)})")
        for i, t in enumerate(tks, 1):
            tit = _md_link(_safe(t.get("tramite")), t.get("url"))
            lines.append(
                f"{i}. {tit} — "
                f"Tipo: `{_safe(t.get('tipo'))}` | "
                f"Estado: `{_safe(t.get('estado'))}` | "
                f"Estado Allianz: `{_safe(t.get('estado_allianz'))}` | "
                f"Solicitud: `{_safe(t.get('fecha_solicitud'))}`"
            )
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


def _render_cartera(resultado: Dict[str, Any]) -> str:
    """Renderer especial para modo=cartera: clientes únicos con sus pólizas y fondos."""
    lines: List[str] = ["# Cartera del Asesor — Tomi · Babilonia", ""]
    lines.append(f"**Email asesor:** `{_safe(resultado.get('asesor_email'))}`")
    stats = resultado.get("stats") or {}
    seg = resultado.get("segmentos") or {}
    total = resultado.get("total_clientes_unicos", 0)
    devueltos = resultado.get("total_clientes_devueltos", total)
    filtro = resultado.get("filtro_estado")

    lines.append("")
    lines.append(f"## Resumen ejecutivo")
    lines.append(f"- **Clientes únicos totales:** {total}")
    lines.append(f"  - 🟢 Activos (con póliza vigente): **{seg.get('activos', 0)}**")
    lines.append(f"  - 🟡 En proceso (pendientes/documentos): **{seg.get('en_proceso', 0)}**")
    lines.append(f"  - 🔴 No convertidos (cancelados/pre-emisión): **{seg.get('perdidos', 0)}**")
    lines.append(f"- **Pólizas totales:** {resultado.get('total_polizas', 0)}")
    lines.append(f"- **Fondos distintos:** {resultado.get('total_fondos_distintos', 0)}")
    if filtro:
        lines.append(f"- **Filtro aplicado:** `{filtro}` → mostrando {devueltos} de {total} clientes.")
    lines.append(f"- **Latencia:** {stats.get('tiempo_ms', 0)} ms")
    lines.append(
        f"_Trazabilidad: {stats.get('emisiones_crudas_recuperadas', 0)} emisiones crudas → "
        f"{stats.get('buckets_creados', 0)} buckets → "
        f"{total} clientes únicos deduplicados._"
    )
    lines.append("")

    clientes = resultado.get("clientes") or []
    if not clientes:
        lines.append("**Sin clientes encontrados** para ese asesor (verificar email o pólizas registradas).")
        return "\n".join(lines)

    # Agrupar por categoría
    grupos = {"activo": [], "en_proceso": [], "perdido": []}
    for c in clientes:
        grupos.get(c.get("categoria") or "perdido", grupos["perdido"]).append(c)

    secciones = [
        ("activo", "🟢 Clientes Activos", "Pólizas vigentes ya emitidas."),
        ("en_proceso", "🟡 Clientes en Proceso", "Pólizas pendientes de pago, emisión o documentos."),
        ("perdido", "🔴 No Convertidos", "Solicitudes canceladas o que no llegaron a póliza."),
    ]

    indice_global = 1
    for cat, titulo, subtitulo in secciones:
        items = grupos.get(cat, [])
        if not items:
            continue
        lines.append(f"## {titulo} ({len(items)})")
        lines.append(f"_{subtitulo}_")
        lines.append("")
        for c in items:
            nombre = _safe(c.get("nombre"))
            email = c.get("email") or "—"
            tel = c.get("telefono") or "—"
            fondos = c.get("fondos_consolidados") or []
            lines.append(f"### {indice_global}. {nombre}")
            indice_global += 1
            lines.append(f"- **Email:** `{email}` | **Teléfono:** `{tel}`")
            if fondos:
                lines.append(f"- **Fondos de inversión consolidados:** {', '.join(fondos)}")
            polizas = c.get("polizas") or []
            if polizas:
                lines.append(f"- **Pólizas ({len(polizas)}):**")
                for p in polizas:
                    num = p.get("numero") or "(sin nº)"
                    prod = _safe(p.get("producto"))
                    prima = _safe(p.get("prima"))
                    period = _safe(p.get("periodicidad"))
                    estado = _safe(p.get("estado"))
                    fecha = _safe(p.get("fecha_emision"))
                    fondos_p = p.get("fondos") or []
                    fondos_str = f" — Fondos: {', '.join(fondos_p)}" if fondos_p else ""
                    url = p.get("url")
                    pol_md = f"[{num}]({url})" if url else num
                    lines.append(
                        f"  - {pol_md} — **{prod}** — Prima **${prima}** {period} — **{estado}** — Emisión: {fecha}{fondos_str}"
                    )
                    # Estado de cobranza de la póliza (lo que el asesor pidió ver)
                    cob = p.get("cobranza")
                    if cob:
                        cparts = []
                        if cob.get("numero_referencia") not in (None, ""):
                            cparts.append(f"Nº cliente: `{cob['numero_referencia']}`")
                        dias = cob.get("dias_de_atraso", 0)
                        cparts.append(f"Atraso: **{dias} días**" if dias else "Al día")
                        if cob.get("monto_faltante") not in (None, "", 0):
                            cparts.append(f"Debe: `${cob['monto_faltante']}`")
                        if cob.get("estado_cobranza"):
                            cparts.append(f"Estado: **{cob['estado_cobranza']}**")
                        if cob.get("numero_pago"):
                            cparts.append(f"Aportado: `{cob['numero_pago']}`")
                        if cob.get("proximo_cobro"):
                            cparts.append(f"Próx. cobro: `{cob['proximo_cobro']}`")
                        lines.append("    · Cobranza → " + " · ".join(cparts))
                    else:
                        lines.append("    · Cobranza → sin registro de cobranza")
            lines.append("")

    return "\n".join(lines)


def _render_cartera_atraso(resultado: Dict[str, Any]) -> str:
    """Renderer para modo=cartera_atraso: ranking de pólizas en atraso con titular."""
    lines: List[str] = ["# Pólizas en atraso de la cartera — Tomi · Babilonia", ""]
    lines.append(f"**Asesor:** `{_safe(resultado.get('asesor_email'))}`")
    filas = resultado.get("polizas_en_atraso") or []
    lines.append(
        f"- **Pólizas en atraso:** {resultado.get('total_en_atraso', 0)} "
        f"(de {resultado.get('total_polizas_revisadas', 0)} pólizas revisadas)"
    )
    tot = resultado.get("total_monto_faltante")
    if tot:
        try:
            lines.append(f"- **Monto faltante total:** ${int(tot):,}")
        except (TypeError, ValueError):
            lines.append(f"- **Monto faltante total:** {tot}")
    lines.append(f"- **Latencia:** {(resultado.get('stats') or {}).get('tiempo_ms', 0)} ms")
    lines.append("")

    if not filas:
        lines.append(
            "**No hay pólizas en atraso** en la cartera de este asesor "
            "(o no hay cobranzas registradas para sus pólizas)."
        )
        return "\n".join(lines)

    lines.append("## Ranking por días de atraso (más críticas primero)")
    lines.append("")
    for i, f in enumerate(filas, 1):
        titular = _safe(f.get("titular"))
        pol = _safe(f.get("poliza"))
        dias = f.get("dias_de_atraso", 0)
        partes = [f"**{i}. {titular}** — póliza `{pol}` — **{dias} días de atraso**"]
        if f.get("numero_referencia") not in (None, ""):
            partes.append(f"nº cliente: `{f['numero_referencia']}`")
        monto = f.get("monto_faltante")
        if monto not in (None, "", 0):
            partes.append(f"debe: `${monto}`")
        if f.get("monto_prima") not in (None, "", 0):
            partes.append(f"prima: `${f['monto_prima']}`")
        if f.get("numero_pago"):
            partes.append(f"aportado: `{f['numero_pago']}`")
        if f.get("estado"):
            partes.append(f"estado: **{f['estado']}**")
        if f.get("proximo_cobro"):
            partes.append(f"próx. cobro: `{f['proximo_cobro']}`")
        lines.append("- " + " · ".join(partes))
    lines.append("")
    return "\n".join(lines)


def _render_equipo(resultado: Dict[str, Any]) -> str:
    """Renderer para modo=equipo: asesores del equipo de un líder con su perfil de Liga."""
    lines: List[str] = ["# Equipo del líder — Tomi · Babilonia", ""]
    lines.append(f"**Líder:** {_safe(resultado.get('lider'))} (`{_safe(resultado.get('lider_email'))}`)")
    aseslist = resultado.get("asesores") or []
    lines.append(
        f"- **Integrantes del equipo:** {resultado.get('total_equipo', 0)} "
        f"(Liga activada: {resultado.get('liga_activada', 0)} · eliminados de la Liga: {resultado.get('eliminados', 0)})"
    )
    lines.append(f"- **Latencia:** {(resultado.get('stats') or {}).get('tiempo_ms', 0)} ms")
    lines.append("")
    if not aseslist:
        lines.append("**Sin asesores en el equipo** (verificar que sea líder o que tenga equipo cargado).")
        return "\n".join(lines)
    lines.append("## Asesores del equipo (semáforo y estado de Liga)")
    lines.append("")
    for i, a in enumerate(aseslist, 1):
        estado_liga = "🚫 ELIMINADO de la Liga" if a.get("eliminado") else (
            "✅ Liga activada" if a.get("liga_activada") else "⚪ Liga no activada")
        partes = [f"**{i}. {_safe(a.get('nombre'))}**"]
        if a.get("semaforo"):
            partes.append(f"semáforo: {a['semaforo']}")
        partes.append(estado_liga)
        if a.get("nivel") not in (None, ""):
            partes.append(f"nivel: `{a['nivel']}`")
        if a.get("estado_asesor"):
            partes.append(f"estado: `{a['estado_asesor']}`")
        if a.get("correo"):
            partes.append(f"`{a['correo']}`")
        lines.append("- " + " · ".join(partes))
    lines.append("")
    return "\n".join(lines)


def renderizar(resultado: Dict[str, Any]) -> str:
    """Genera markdown determinístico desde el resultado de bd.consultar().

    NO usa LLM. Todos los valores salen verbatim del dict.
    """
    # Renderer especial para modo cartera
    if resultado.get("modo") == "cartera":
        return _render_cartera(resultado)
    if resultado.get("modo") == "cartera_atraso":
        return _render_cartera_atraso(resultado)
    if resultado.get("modo") == "equipo":
        return _render_equipo(resultado)

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

    # MI REUNIÓN / LA LIGA (link de Zoom del evento de Calendly del usuario).
    # Va ARRIBA de todo: si el usuario pidió "la liga"/link/reunión, esto es lo que
    # tiene que responder Tomi (dale el link_zoom y la fecha; NO pidas que aclare).
    reuniones = resultado.get("mi_reunion") or []
    if reuniones:
        lines.append(f"## Reunión del usuario — link de Zoom, ASESOR y CERRADOR ({len(reuniones)})")
        for r in reuniones:
            lines.append(
                f"- **{_safe(r.get('evento'))}** — invitado: `{_safe(r.get('invitado'))}` | "
                f"Fecha/hora: `{_safe(r.get('fecha'))}` | Estado: `{_safe(r.get('estado'))}`"
            )
            lines.append(f"  - **Liga/Link de Zoom: {_safe(r.get('link_zoom'))}**")
            if r.get("link_reagendar"):
                lines.append(f"  - Link para reagendar: {_safe(r.get('link_reagendar'))}")
            # Asesor y Cerrador del cliente (dato pedido: vive en el evento de Calendly)
            if r.get("asesor") or r.get("asesor_correo") or r.get("asesor_telefono"):
                lines.append(
                    f"  - **Asesor del cliente:** `{_safe(r.get('asesor'))}`"
                    f" | correo: `{_safe(r.get('asesor_correo'))}`"
                    f" | tel: `{_safe(r.get('asesor_telefono'))}`"
                )
            if r.get("cerrador") or r.get("cerrador_correo") or r.get("cerrador_telefono"):
                lines.append(
                    f"  - **Cerrador del cliente:** `{_safe(r.get('cerrador'))}`"
                    f" | correo: `{_safe(r.get('cerrador_correo'))}`"
                    f" | tel: `{_safe(r.get('cerrador_telefono'))}`"
                )
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
            # "Número de Referencia" = lo que el usuario llama "número de cliente".
            ref = (
                c.get("Número de Referencia")
                or c.get("Numero de Referencia")
                or c.get("N° de Referencia")
                or c.get("Nº de Referencia")
            )
            ref_str = f"N° de cliente: `{_safe(ref)}` | " if ref else ""
            # DEUDA REAL = Monto Faltante (lo que se debe HOY). Es el dato PRINCIPAL
            # de cobranza; sin él el agente no puede responder "cuánto debo".
            monto = c.get("Monto Faltante")
            monto_str = "—" if monto is None else f"${monto}"
            prox = (
                (c.get("Próximo intento de cobro") or {}).get("start")
                or (c.get("Fecha Límite de Pago") or {}).get("start")
            )
            lines.append(
                f"{i}. {pol} — "
                f"{ref_str}"
                f"**Adeudo (deuda real hoy): `{monto_str}`** | "
                f"Estado póliza: `{_safe(c.get('Estado de la Póliza'))}` | "
                f"Estado cobranza: `{_safe(c.get('Estado de Cobranza'))}` | "
                f"Semáforo: `{_safe(c.get('Semáforo'))}` | "
                f"Días atraso: `{_safe(nc.pick_dias_atraso(c))}` | "
                f"Próximo cobro: `{_safe(prox)}`"
            )
        lines.append("")

    # DAF (cuenta de agente Allianz)
    daf = resultado.get("daf") or []
    if daf:
        lines.append(f"## DAF — Cuentas de agente ({len(daf)})")
        for i, d in enumerate(daf, 1):
            nombre = _md_link(_safe(d.get("daf")), d.get("url"))
            lines.append(
                f"{i}. {nombre} — "
                f"N° de agente: `{_safe(d.get('numero_agente'))}` | "
                f"Cédula: `{_safe(d.get('cedula'))}` | "
                f"Estado: `{_safe(d.get('estado'))}` | "
                f"Correo: `{_safe(d.get('correo_daf'))}` | "
                f"Meses con DAF: `{_safe(d.get('meses_con_daf'))}`"
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

    # Catálogo de productos (lista REAL de lo que se ofrece — para no inventar)
    prods = resultado.get("productos") or []
    if prods:
        lines.append(f"## Catálogo de productos ({len(prods)})")
        lines.append("Esta es la lista COMPLETA y REAL de lo que se ofrece. "
                     "Si el usuario pregunta por algo que NO está acá, NO existe — decilo claramente.")
        for i, p in enumerate(prods, 1):
            desc = _safe(p.get("descripcion"))
            desc = (desc[:140] + "…") if len(desc) > 140 else desc
            lines.append(
                f"{i}. **{_safe(p.get('nombre'))}** — "
                f"Tipo: `{_safe(p.get('tipo'))}`"
                + (f" — {desc}" if desc and desc != "—" else "")
            )
        lines.append("")

    # Renovaciones / Siniestros / Comisiones (bases dedicadas — render genérico-seguro).
    def _fmt_generico(row: Dict[str, Any]) -> str:
        partes: List[str] = []
        for k, v in row.items():
            if k.startswith("_") or v in (None, "", [], {}):
                continue
            if isinstance(v, dict):
                v = v.get("start") or v.get("name") or ""
            if isinstance(v, (list, dict)) or v == "":
                continue
            partes.append(f"{k}: `{_safe(v)}`")
            if len(partes) >= 5:
                break
        return " | ".join(partes)

    for _clave, _titulo in (("renovaciones", "Renovaciones"),
                            ("siniestros", "Siniestros"),
                            ("comisiones", "Comisiones")):
        _items = resultado.get(_clave) or []
        if _items:
            lines.append(f"## {_titulo} ({len(_items)})")
            for i, r in enumerate(_items, 1):
                tit = _md_link(_safe(r.get("_title") or r.get("Nombre") or _titulo[:-1]), r.get("_url"))
                det = _fmt_generico(r)
                lines.append(f"{i}. {tit}" + (f" — {det}" if det else ""))
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

    # ⚠️ Advertencias de calidad de datos
    advs = resultado.get("advertencias") or []
    if advs:
        # ordenar por severidad: error > warning > info
        sev_order = {"error": 0, "warning": 1, "info": 2}
        advs_sorted = sorted(advs, key=lambda a: sev_order.get(a.get("severidad"), 9))
        lines.append(f"## ⚠️ Inconsistencias detectadas ({len(advs)})")
        for a in advs_sorted:
            sev = a.get("severidad", "info").upper()
            ico = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(sev, "•")
            ent = a.get("entidad") or ""
            lines.append(f"- {ico} **{sev}** `{a.get('tipo')}` [{ent}]: {a.get('mensaje')}")
            if a.get("sugerencia"):
                lines.append(f"  - Sugerencia: {a['sugerencia']}")
        lines.append("")

    if len(lines) == 4:  # solo el header y consulta
        lines.append("**Sin resultados.** Verificá que los datos consultados existan en Notion o que la integración tenga acceso a las DBs relevantes.")

    return "\n".join(lines)
