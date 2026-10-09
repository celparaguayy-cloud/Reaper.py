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


def independencia_equipo(estado: list) -> dict:
    """Independencia REAL: proveedores y modelos distintos (no premiar seis alias al mismo endpoint)."""
    provs = {e["proveedor"] for e in estado}
    modelos = {e["modelo"] for e in estado}
    return {"proveedores_distintos": len(provs), "modelos_distintos": len(modelos),
            "reducida": len(provs) <= 1}
