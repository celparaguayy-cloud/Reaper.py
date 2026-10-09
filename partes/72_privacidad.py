"""
Reporte de privacidad (REAPER AUTO-6-IA §11 / v11 §24.7).

Informa, con honestidad, QUÉ proveedores fueron contactados esta sesión y QUÉ categorías de datos les envía
REAPER — sin mostrar datos sensibles. No promete confidencialidad absoluta: una API externa recibe lo que se
le manda. Lo que sí se garantiza: los secretos (claves, Authorization) se redactan de logs/stdout y no se
ponen en los prompts a propósito.
"""


def categorias_enviadas() -> list:
    return [
        "instrucciones del sistema y tu pedido (prompts)",
        "contenido de archivos del proyecto incluido como contexto (código)",
        "resultados de herramientas (stdout/validación), con secretos redactados",
    ]


def reporte_privacidad(llm, settings) -> dict:
    """Arma el reporte a partir del uso real del cliente (proveedores contactados) + los ajustes."""
    por_proveedor = {}
    uso = getattr(llm, "uso", None)
    por_modelo = getattr(uso, "por_modelo", {}) or {}
    for modelo, datos in por_modelo.items():
        try:
            prov = destino_modelo(modelo, settings).proveedor
        except (ValueError, KeyError, AttributeError, TypeError):
            prov = "?"
        por_proveedor[prov] = por_proveedor.get(prov, 0) + int(getattr(datos, "llamadas", 0) or 0)
    return {
        "proveedores_contactados": por_proveedor,
        "categorias": categorias_enviadas(),
        "redaccion_secretos": True,
        "no_envia": ["claves de API / Authorization (redactadas)", "archivos .env (bloqueados)"],
        "privacidad_estricta": bool(getattr(settings, "privacidad_estricta", False)),
    }


def texto_reporte_privacidad(rep: dict) -> str:
    provs = rep.get("proveedores_contactados") or {}
    lineas = ["Reporte de privacidad (qué salió del dispositivo esta sesión):"]
    if provs:
        lineas.append("  Proveedores contactados: " + ", ".join(f"{p} ({n} llamada(s))" for p, n in provs.items()))
    else:
        lineas.append("  Proveedores contactados: ninguno todavía en esta sesión.")
    lineas.append("  Categorías de datos enviadas a los modelos:")
    lineas += [f"    - {c}" for c in rep.get("categorias", [])]
    lineas.append("  Redacción de secretos (claves/Authorization): " + ("ACTIVA" if rep.get("redaccion_secretos") else "OFF"))
    lineas.append("  NO se envía: " + "; ".join(rep.get("no_envia", [])))
    lineas.append("  Privacidad estricta: " + ("ON" if rep.get("privacidad_estricta") else "OFF")
                  + "  (ON = evitar subir contenido del proyecto a proveedores externos)")
    lineas.append("  Nota honesta: las APIs externas reciben lo que se les envía; no hay confidencialidad absoluta.")
    return "\n".join(lineas)
