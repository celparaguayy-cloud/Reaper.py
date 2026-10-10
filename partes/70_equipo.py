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
    for etiqueta, rol in ROLES_EQUIPO_SEIS:
        modelo = settings.modelo_para(rol)
        destino = destino_modelo(modelo, settings)
        try:
            tiene = bool(clave_de_proveedor(destino.proveedor, replace(settings, proveedor=destino.proveedor)))
        except (TypeError, ValueError):
            tiene = False
        salida.append({"rol": etiqueta, "reaper_rol": rol, "modelo": modelo,
                       "proveedor": destino.proveedor, "tiene_clave": tiene})
    return salida


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
    for i, (_, rol) in enumerate(ROLES_EQUIPO_SEIS):
        asignacion[rol] = candidatos[i % len(candidatos)]
    return asignacion, ""


def _probar_modelo(llm, modelo: str) -> dict:
    """Petición mínima REAL a un modelo concreto (sin fallback): dice si responde de verdad."""
    t0 = time.monotonic()
    try:
        resp = llm.chat([{"role": "user", "content": "ping"}], modelo=modelo, max_tokens=1,
                        temperatura=0, sin_respaldo=True, rol="probe")
        ms = round((time.monotonic() - t0) * 1000)
        return {"estado": "RESPONDE", "detalle": f"{ms}ms", "modelo_servido": getattr(resp, "modelo", "")}
    except LLMError as e:
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
    return (f"6 roles → {ind['modelos_distintos']} modelo(s)/{ind['proveedores_distintos']} prov{aviso}"
            f" · conectividad NO VERIFICADA (/equipo probar)")


def independencia_equipo(estado: list) -> dict:
    """Independencia REAL: proveedores y modelos distintos (no premiar seis alias al mismo endpoint)."""
    provs = {e["proveedor"] for e in estado}
    modelos = {e["modelo"] for e in estado}
    return {"proveedores_distintos": len(provs), "modelos_distintos": len(modelos),
            "reducida": len(provs) <= 1}
