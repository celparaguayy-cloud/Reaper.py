#!/usr/bin/env python3
"""
/construir de punta a punta con el gate de aceptación independiente activo.

El MODELO está simulado (MockLLM: el implementador escribe app.py y web/ de la variante elegida); el servidor HTTP,
SQLite, el evaluador externo y la verificación de REAPER son REALES. Comprueba que:
  - con la app ROTA la build NO termina "verificada" (el evaluador externo falla y bloquea),
  - con la app de REFERENCIA la build sí termina "verificada" por la aceptación externa.
Esto NO es una construcción con IA real: eso queda NO VERIFICADO sin claves ni el workspace del usuario.

Uso:  python3 pruebas_fusion/mercadocontrol/construir_con_mock.py [ruta/a/reaper.py] [log_de_salida]
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REAPER = Path(sys.argv[1] if len(sys.argv) > 1 else AQUI.parents[1] / "reaper_v8.py").resolve()
LOG = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None

spec = importlib.util.spec_from_file_location("reaper", REAPER)
m = importlib.util.module_from_spec(spec)
sys.modules["reaper"] = m
spec.loader.exec_module(m)

PLAN = """<plan>
<objetivo>MercadoControl: inventario web con API JSON y SQLite</objetivo>
<tarea id="1" archivos="app.py">Crear el servidor app.py (PORT, MERCADO_DB) con /api/productos CRUD, validaciones 400 y estáticos de web/ con MIME correcto</tarea>
<tarea id="2" archivos="web/index.html" deps="1">Crear web/index.html que enlaza /style.css y /script.js</tarea>
<tarea id="3" archivos="web/style.css" deps="2">Crear web/style.css</tarea>
<tarea id="4" archivos="web/script.js" deps="2">Crear web/script.js que usa la API</tarea>
<criterios>
- GET / devuelve HTML; /style.css y /script.js con MIME correcto
- CRUD JSON en /api/productos con validaciones 400 y persistencia en SQLite
</criterios>
</plan>"""


def construir(variante: str) -> tuple:
    origen = AQUI / variante
    archivos = {str(p.relative_to(origen)): p.read_text(encoding="utf-8")
                for p in sorted(origen.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    def guion(mensajes, kwargs):
        rol = m.MockLLM.rol_de(mensajes)
        turno = m._turno(mensajes)
        if rol == "arquitecto":
            return m.terminar_xml(PLAN)
        if rol == "implementador":
            # el implementador simulado escribe SOLO los archivos de su tarea (como haría un modelo disciplinado)
            pedido = mensajes[1]["content"] if len(mensajes) > 1 else ""
            pedido = pedido.split("TU TAREA AHORA", 1)[-1].split("CONTEXTO DE EXPLORACIÓN", 1)[0]
            frases = {"Crear el servidor app.py": "app.py", "Crear web/index.html": "web/index.html",
                      "Crear web/style.css": "web/style.css", "Crear web/script.js": "web/script.js"}
            propios = [rel for frase, rel in frases.items() if frase in pedido]
            if turno < len(propios):
                return m.herramienta_xml("write_to_file", path=propios[turno], content=archivos[propios[turno]])
            return m.terminar_xml("hecho")
        return m.terminar_xml("sin cambios adicionales")

    with tempfile.TemporaryDirectory(prefix=f"mc_build_{variante}_") as tmp:
        suite = Path(tmp) / "evaluador"
        shutil.copytree(AQUI / "evaluador", suite)
        raiz = Path(tmp) / "mercadocontrol"
        (raiz / ".reaper").mkdir(parents=True)
        (raiz / ".reaper" / "acceptance.json").write_text(
            json.dumps({"suite_dir": str(suite), "min_tests": 10, "timeout": 120}), encoding="utf-8")
        (raiz / "README.md").write_text("# MercadoControl\n", encoding="utf-8")
        ws = m.Workspace(raiz)
        s = m.Settings(modo="auto", tests_primero=False, torneo=False, qa=False, max_revisiones=0,
                       max_reparaciones=1, umbral_escalada=1, forense=False, lecciones=False, escalar=False,
                       roles_x=False)
        ui = m.UI(silencioso=True, interactivo=False)
        inicio = time.monotonic()
        informe = m.Orquestador(m.MockLLM(guion), ws, s, ui).construir("Construí MercadoControl", confirmar=False)
        dur = time.monotonic() - inicio
        acept = informe.aceptacion
        linea = next((l for l in (acept.stderr if acept else "").splitlines() if l.startswith("ACEPTACIÓN:")), "—")
        return informe.estado, (acept.ok if acept else None), linea, dur


def main() -> int:
    filas = [f"REAPER: {REAPER}", f"Python: {sys.version.split()[0]}", "Modelo: MockLLM (simulado)", ""]
    ok = True
    for variante, esperado in (("rota", False), ("referencia", True)):
        estado, acept_ok, linea, dur = construir(variante)
        coincide = (estado == "verificada") == esperado
        ok &= coincide
        filas.append(f"=== {variante}: estado={estado} aceptación_ok={acept_ok} · {dur:.1f}s "
                     f"{'OK' if coincide else 'NO COINCIDE'}")
        filas.append("  " + linea)
    filas.append("RESULTADO: " + ("sin falsos verdes" if ok else "DISCREPANCIA"))
    texto = "\n".join(filas)
    print(texto)
    if LOG:
        LOG.write_text(texto + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
