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


def independencia_equipo(estado: list) -> dict:
    """Independencia REAL: proveedores y modelos distintos (no premiar seis alias al mismo endpoint)."""
    provs = {e["proveedor"] for e in estado}
    modelos = {e["modelo"] for e in estado}
    return {"proveedores_distintos": len(provs), "modelos_distintos": len(modelos),
            "reducida": len(provs) <= 1}
