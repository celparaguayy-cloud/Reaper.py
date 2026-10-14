"""
Display de los seis agentes + métrica de independencia (REAPER AUTO-6-IA §6/§9).

Muestra, de forma HONESTA, qué proveedor/modelo tiene asignado cada uno de los seis roles lógicos y cuántos
proveedores/modelos DISTINTOS hay de verdad: "seis IAs" no puede ocultar que en realidad son tres modelos o
un solo proveedor. No afirma conectividad: la asignación es configuración; la prueba real (NO VERIFICADO
hasta ejecutarse) la hace /proveedores probar con las claves del usuario.
"""

# Seis roles lógicos del spec → rol real de REAPER que los implementa.
ROLES_EQUIPO_SEIS = (
    ("coordinador", "principal"),
    ("arquitecto", "arquitecto"),
    ("implementador", "implementador"),
    ("revisor", "revisor"),
    ("qa", "qa"),
    ("reparador", "reparador"),
)


def estado_equipo(settings) -> list:
    """Para cada rol: modelo asignado, proveedor de destino y si hay credencial para ese proveedor."""
    salida = []
    for etiqueta, rol in roles_equipo(settings):
        modelo = settings.modelo_para(rol)
        destino = destino_modelo(modelo, settings)
        try:
            tiene = bool(clave_de_proveedor(destino.proveedor, replace(settings, proveedor=destino.proveedor)))
        except (TypeError, ValueError):
            tiene = False
        salida.append({"rol": etiqueta, "reaper_rol": rol, "modelo": modelo, "modelo_real": destino.modelo,
                       "proveedor": destino.proveedor, "tiene_clave": tiene})
    return salida


def estado_juez(settings) -> dict:
    """El 8.º agente: el JUEZ DE ENTREGA. Va aparte de los 6 trabajadores porque es el control final, no un obrero."""
    modelo = settings.modelo_para("juez")
    destino = destino_modelo(modelo, settings)
    try:
        tiene = bool(clave_de_proveedor(destino.proveedor, replace(settings, proveedor=destino.proveedor)))
    except (TypeError, ValueError):
        tiene = False
    return {"rol": "juez", "activo": bool(getattr(settings, "juez", True)), "modelo": modelo,
            "modelo_real": destino.modelo, "proveedor": destino.proveedor, "tiene_clave": tiene}


# Roles donde un modelo más capaz cambia el resultado (planificar, implementar, reparar, integrar).
ROLES_CRITICOS = frozenset({"principal", "director", "arquitecto", "implementador", "reparador", "integrador"})


def modelo_sano(settings, modelo: str, disyuntor=None) -> tuple:
    """(sano, motivo). Sano = proveedor con credencial (o local), no retirado y sin el disyuntor abierto."""
    retirados = globals().get("PROVEEDORES_RETIRADOS", frozenset())
    try:
        destino = destino_modelo(modelo, settings)
    except (TypeError, ValueError):
        return False, "modelo inválido"
    if destino.proveedor in retirados:
        return False, f"proveedor retirado ({destino.proveedor})"
    if not destino.es_local():
        try:
            if not clave_de_proveedor(destino.proveedor, replace(settings, proveedor=destino.proveedor)):
                return False, f"sin clave para {destino.proveedor}"
        except (TypeError, ValueError):
            return False, f"sin clave para {destino.proveedor}"
    if disyuntor is not None:
        try:
            if not disyuntor.disponible(modelo):
                return False, "viene fallando seguido (disyuntor abierto)"
        except (AttributeError, TypeError, ValueError):
            pass
    return True, ""


def asignar_equipo_juez(settings, desempeno=None, disyuntor=None) -> tuple:
    """
    El JUEZ reparte los roles según la NECESIDAD, sin gastar tokens (todo con evidencia local):
    - ningún rol queda en un modelo caído: descarta los que no tienen clave, están retirados o vienen fallando;
    - para cada rol elige, entre los modelos SANOS del equipo, el de mejor historial en ESE rol;
    - en los roles críticos (planificar, implementar, reparar) prefiere un modelo 'fuerte' si no hay
      historial que diga lo contrario;
    - si el configurado está sano y nadie es claramente mejor, lo respeta (no cambia por cambiar).
    El modelo de ESCALADA queda reservado para cuando una tarea se traba (no se gasta en todo el build).
    Devuelve (cambios {rol: modelo}, motivos [str]).
    """
    roles = [r for _etiqueta, r in roles_equipo(settings)] + ["juez"]
    pool = []
    for rol in roles:
        modelo = settings.modelo_para(rol)
        if modelo and modelo not in pool:
            pool.append(modelo)
    for respaldo in list(getattr(settings, "fallbacks", None) or []):
        modelo = resolver_modelo(respaldo)
        if modelo and modelo not in pool:
            pool.append(modelo)
    salud = {m: modelo_sano(settings, m, disyuntor) for m in pool}
    sanos = [m for m in pool if salud[m][0]]
    if not sanos:
        return {}, []

    def puntaje(rol: str, modelo: str, actual: str) -> float:
        base = desempeno.puntaje(rol, modelo) if desempeno is not None else 0.6
        if rol in ROLES_CRITICOS and info_modelo(modelo).nivel == "fuerte":
            base += 0.1
        if modelo == actual:
            base += 0.02            # estabilidad: ante empate se queda el configurado
        return base

    cambios, motivos = {}, []
    for rol in roles:
        actual = settings.modelo_para(rol)
        mejor = max(sanos, key=lambda m: puntaje(rol, m, actual))
        if mejor == actual:
            continue
        sano_actual, motivo_actual = salud.get(actual) or modelo_sano(settings, actual, disyuntor)
        if not sano_actual:
            cambios[rol] = mejor
            motivos.append(f"{rol} → {mejor} (el asignado no está disponible: {motivo_actual})")
        elif puntaje(rol, mejor, actual) - puntaje(rol, actual, actual) >= 0.05:
            cambios[rol] = mejor
            razon = "es más capaz para este rol" if desempeno is None or not desempeno._fila(
                desempeno._cargar(), rol, mejor) else "rinde mejor en este rol según su historial"
            motivos.append(f"{rol} → {mejor} ({razon})")
    return cambios, motivos


def validar_configuracion(settings) -> list:
    """
    Revisa la config de modelos/equipo SIN tocar la red (la conectividad real la da /equipo probar). Devuelve
    una lista de (nivel, mensaje) con nivel 'error' (bloqueante), 'aviso' (mejorable) u 'ok' (bien).
    """
    retirados = globals().get("PROVEEDORES_RETIRADOS", frozenset())

    def tiene_clave(prov: str) -> bool:
        try:
            return bool(clave_de_proveedor(prov, replace(settings, proveedor=prov)))
        except (TypeError, ValueError):
            return False

    issues = []
    principal = destino_modelo(settings.modelo, settings)
    if principal.proveedor in retirados:
        issues.append(("error", f"el modelo principal usa un proveedor retirado ({principal.proveedor})"))
    elif not principal.es_local() and not tiene_clave(principal.proveedor):
        issues.append(("error", f"falta la credencial del proveedor del modelo principal ({principal.proveedor})"))
    else:
        issues.append(("ok", f"modelo principal: {settings.modelo} → {principal.proveedor}"))

    estado = estado_equipo(settings)
    sin_clave = [e["rol"] for e in estado if not e["tiene_clave"]]
    if sin_clave:
        issues.append(("error", f"{len(sin_clave)} rol(es) sin credencial para su proveedor: {', '.join(sin_clave)}"))
    retirados_rol = sorted({e["proveedor"] for e in estado if e["proveedor"] in retirados})
    if retirados_rol:
        issues.append(("error", f"rol(es) con proveedor retirado: {', '.join(retirados_rol)}"))

    provs = {e["proveedor"] for e in estado}
    if len(estado) > 1 and len(provs) <= 1:
        issues.append(("aviso", f"independencia REDUCIDA: los {len(estado)} roles usan un solo proveedor "
                                f"({next(iter(provs))}); si se cae, cae todo el equipo"))

    if settings.escalar:
        fuerte = destino_modelo(settings.modelo_fuerte, settings)
        if fuerte.proveedor in retirados:
            issues.append(("error", f"el modelo de escalada usa un proveedor retirado ({fuerte.proveedor})"))
        elif not fuerte.es_local() and not tiene_clave(fuerte.proveedor):
            issues.append(("aviso", f"escalada activada pero falta la credencial de {fuerte.proveedor}: no podrá escalar"))

    if not any(nivel == "error" for nivel, _ in issues):
        issues.append(("ok", "sin errores bloqueantes en la configuración"))
    issues.append(("aviso", "la conectividad real NO se valida acá: usá /equipo probar"))
    return issues


def diagnostico_texto(settings, incluir_equipo: bool = True) -> str:
    """
    Resumen para reportar bugs: versión, entorno, chequeos, config, qué proveedores tienen clave (solo sí/no) y
    el ruteo del equipo. Pasa por redactar_secretos: NUNCA incluye una clave, aunque aparezca en algún campo.
    """
    entorno = "Termux/Android" if es_termux() else f"{platform.system()} {platform.machine()}"
    lineas = [f"REAPER {__version__} · diagnóstico", f"python {sys.version.split()[0]} · {entorno}", ""]
    lineas.append("Chequeos del entorno:")
    for c in chequeos_sistema(settings):
        marca = "OK" if c.ok else ("FALTA" if c.critico else "opcional")
        lineas.append(f"  [{marca}] {c.nombre}: {recortar(c.detalle, 70).replace(chr(10), ' ')}")
    lineas.append("")
    lineas.append(f"Config: modo={settings.modo} · candidatos={settings.candidatos} · tests_primero={settings.tests_primero}"
                  f" · torneo={settings.torneo} · escalar={settings.escalar} · roles_x={settings.roles_x}"
                  f" · privacidad_estricta={settings.privacidad_estricta} · web={settings.web}")
    marcas = []
    for prov in PROVEEDORES:
        try:
            tiene = bool(clave_de_proveedor(prov, replace(settings, proveedor=prov)))
        except (TypeError, ValueError):
            tiene = False
        marcas.append(f"{prov}{'✓' if tiene else '·'}")
    lineas.append("Proveedores (✓=con clave, ·=sin clave): " + " ".join(marcas))
    if incluir_equipo:
        lineas += ["", "Ruteo del equipo (rol → modelo @ proveedor · credencial):"]
        for e in estado_equipo(settings):
            lineas.append(f"  {e['rol']:<16} {e['modelo_real']} @ {e['proveedor']} · "
                          f"{'con clave' if e['tiene_clave'] else 'SIN CLAVE'}")
        lineas += ["", "Validación de configuración:"]
        for nivel, msg in validar_configuracion(settings):
            lineas.append(f"  [{nivel}] {msg}")
    return redactar_secretos("\n".join(lineas))


# Catálogo REAL de OpenRouter (público: sin clave y sin costo). La lista fija de modelos gratis se pudre: en la
# prueba real (2026-10) el perfil "gratis" apuntaba a dolphin…:free, que ya no existía, y llama-3.3-70b:free tampoco.
URL_CATALOGO_OPENROUTER = "https://openrouter.ai/api/v1/models"
_RE_NO_SIRVE_PARA_CODIGO = re.compile(r"safety|guard|lyria|embed|tts|whisper|moderation|^openrouter/", re.I)
_RE_MODELO_DIMINUTO = re.compile(r"[-_/](?:0?\.\d+|[0-6](?:\.\d+)?)b\b", re.I)   # ≤ 6B: no sirven para programar


def elegir_free_de_catalogo(datos: list) -> list:
    """Del catálogo (lista de modelos de /api/v1/models) los GRATIS de chat de texto que sirven para programar,
    mejores primero (código > herramientas > contexto). Excluye pagos, música/seguridad/embeddings, el router
    'openrouter/free' (cae en modelos de 2B) y los diminutos."""
    elegidos = []
    for m in datos or []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id", ""))
        precio = m.get("pricing") or {}
        try:
            gratis = float(precio.get("prompt", 1)) == 0 and float(precio.get("completion", 1)) == 0
        except (TypeError, ValueError):
            gratis = False
        if not gratis or not mid or _RE_NO_SIRVE_PARA_CODIGO.search(mid) or _RE_MODELO_DIMINUTO.search(mid):
            continue
        salida = (m.get("architecture") or {}).get("output_modalities") or ["text"]
        if "text" not in salida:
            continue
        params = m.get("supported_parameters") or []
        puntaje = (2 if re.search(r"code|coder", mid, re.I) else 0) + (1 if "tools" in params else 0)
        if m.get("expiration_date"):
            puntaje -= 3                               # se va a retirar: no conviene que sea el principal
        elegidos.append((-puntaje, -int(m.get("context_length") or 0), mid))
    return [mid for _p, _c, mid in sorted(elegidos)]


def catalogo_free_openrouter(timeout: float = 8.0, horas_cache: float = 12.0) -> list:
    """Modelos gratis que OpenRouter ofrece HOY (con caché). [] sin red o con REAPER_SIN_RED (los autotests)."""
    if os.getenv("REAPER_SIN_RED"):
        return []
    cache = CACHE_DIR / "openrouter_free.json"
    try:
        datos = json.loads(cache.read_text(encoding="utf-8"))
        if time.time() - float(datos.get("ts", 0)) < horas_cache * 3600 and datos.get("ids"):
            return list(datos["ids"])
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        pedido = urllib.request.Request(URL_CATALOGO_OPENROUTER, headers={"User-Agent": "REAPER"})
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            lista = json.loads(r.read().decode("utf-8")).get("data", [])
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return []
    ids = elegir_free_de_catalogo(lista)
    if ids:
        try:
            escritura_atomica(cache, json.dumps({"ts": time.time(), "ids": ids}))
        except OSError:
            pass
    return ids


def modelos_potentes_free() -> list:
    """Alias curados de modelos free POTENTES (del catálogo estático), como (alias, info)."""
    return [(alias, info) for alias, info in INFO_MODELOS.items() if info.free]


def autoasignar_equipo_free(settings) -> tuple:
    """
    Asigna los seis roles a modelos free potentes SOLO de proveedores con credencial. Reparte entre
    proveedores para maximizar independencia. Devuelve (modelos_rol, motivo_si_vacio). No inventa conexión.
    """
    por_proveedor = {}
    for alias, info in modelos_potentes_free():
        prov = info.proveedor or settings.proveedor
        try:
            tiene = bool(clave_de_proveedor(prov, replace(settings, proveedor=prov)))
        except (TypeError, ValueError):
            tiene = False
        if tiene:
            por_proveedor.setdefault(prov, []).append(alias)
    if not por_proveedor:
        return {}, "ningún proveedor con nivel gratuito tiene credencial configurada"
    # intercalar proveedores para que roles consecutivos usen proveedores distintos cuando se pueda
    colas = [list(v) for v in por_proveedor.values()]
    candidatos = []
    while any(colas):
        for cola in colas:
            if cola:
                candidatos.append(cola.pop(0))
    asignacion = {}
    for i, (_, rol) in enumerate(roles_equipo(settings)):
        asignacion[rol] = candidatos[i % len(candidatos)]
    return asignacion, ""


def _probar_modelo(llm, modelo: str) -> dict:
    """Petición mínima REAL a un modelo concreto (sin fallback): dice si responde de verdad."""
    t0 = time.monotonic()
    try:
        resp = llm.chat([{"role": "user", "content": "Responde únicamente la palabra REAPER_OK."}],
                        modelo=modelo, max_tokens=64,
                        temperatura=0, sin_respaldo=True, rol="probe")
        ms = round((time.monotonic() - t0) * 1000)
        visible = str(getattr(resp, "texto", "") or "").strip()
        if "REAPER_OK" not in visible.upper():
            return {"estado": "FALLA", "detalle": f"{ms}ms; respuesta de prueba no verificable"}
        return {"estado": "RESPONDE", "detalle": f"{ms}ms (texto verificado)",
                "modelo_servido": getattr(resp, "modelo", "")}
    except LLMError as e:
        if getattr(e, "solo_razonamiento", False):
            ms = round((time.monotonic() - t0) * 1000)
            return {"estado": "FALLA", "detalle": f"{ms}ms (solo razonamiento, sin texto verificable)"}
        return {"estado": "FALLA", "detalle": recortar(str(e), 120)}
    except (OSError, ValueError, RuntimeError) as e:
        return {"estado": "FALLA", "detalle": f"{type(e).__name__}: {e}"[:120]}


def probar_equipo(llm, settings) -> list:
    """
    Prueba de verdad cada uno de los seis roles con una petición mínima. Dedup por modelo (no gasta de más).
    Devuelve, por rol: estado RESPONDE / FALLA / SIN_CLAVE + detalle. Esto es lo único que confirma que
    'las seis IAs corren': configurar no es responder.
    """
    cache = {}
    salida = []
    for e in estado_equipo(settings):
        if not e["tiene_clave"]:
            r = {"estado": "SIN_CLAVE", "detalle": "falta credencial del proveedor"}
        elif e["modelo"] in cache:
            r = dict(cache[e["modelo"]])
            r["detalle"] = (r.get("detalle", "") + " (compartido)").strip()
        else:
            r = _probar_modelo(llm, e["modelo"])
            cache[e["modelo"]] = r
        salida.append({**e, **r})
    return salida


def resumen_arranque_equipo(settings) -> str:
    """Línea para el banner de inicio: cuántos roles/modelos/proveedores y que falta verificar."""
    estado = estado_equipo(settings)
    ind = independencia_equipo(estado)
    con_clave = sum(1 for e in estado if e["tiene_clave"])
    aviso = "" if con_clave == len(estado) else f" · {len(estado) - con_clave} sin clave"
    juez = " + juez" if getattr(settings, "juez", True) else ""
    return (f"{len(estado)} roles{juez} → {ind['modelos_distintos']} modelo(s)/{ind['proveedores_distintos']} prov{aviso}"
            f" · conectividad NO VERIFICADA (/equipo probar)")


def independencia_equipo(estado: list) -> dict:
    """Independencia REAL: proveedores y modelos distintos (no premiar seis alias al mismo endpoint)."""
    provs = {e["proveedor"] for e in estado}
    modelos = {e["modelo"] for e in estado}
    return {"proveedores_distintos": len(provs), "modelos_distintos": len(modelos),
            "reducida": len(provs) <= 1}
