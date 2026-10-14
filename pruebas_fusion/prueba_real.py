#!/usr/bin/env python3
"""
Prueba REAL de REAPER contra OpenRouter, solo con modelos GRATIS: corre /construir sobre proyectos de verdad
(un juego, una página web y un script de Python) SIN ayudar al modelo, y deja todo para revisar: el código que
generó REAPER, el log completo de cada build, su informe y un resumen.

Garantías (las mismas de las pruebas reales de octubre 2026):
- La clave se lee SOLO de la variable de entorno OPENROUTER_API_KEY (cargala como secreto del entorno, no en el
  chat). Nunca se escribe en el repo; vive en un REAPER_HOME temporal y se borra al terminar.
- Solo modelos con precio 0 del catálogo real de OpenRouter, y tope de costo 0,01 USD por las dudas.
- Gasto de la cuenta antes y después, y búsqueda de la clave en todos los logs, informes y proyectos (no debe
  aparecer en ningún lado).

Uso:  OPENROUTER_API_KEY=... python3 pruebas_fusion/prueba_real.py [juego] [web] [script] [grande] [--minutos N]
      (sin nombres corre juego, web y script; "grande" va aparte porque tarda mucho más: usa --grande, por etapas)
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
REAPER = RAIZ / "reaper_v8.py"

PROYECTOS = {
    "juego": (
        "Un juego de la serpiente (snake) para el navegador, en HTML, CSS y JavaScript sin librerías externas. "
        "index.html con un canvas y un panel de puntaje; juego.js con la lógica separada en funciones puras y "
        "exportadas (mover la serpiente, crecer al comer, detectar choque con paredes y consigo misma, generar "
        "comida en una celda libre); la serpiente se maneja con las flechas del teclado y también con botones "
        "en pantalla para celular; pausa con la barra espaciadora; la velocidad sube cada 5 comidas; el récord "
        "se guarda en localStorage; pantalla de fin de juego con botón para reiniciar. style.css con un diseño "
        "lindo y que se adapte al celular. Tests con node:test en tests/juego.test.mjs para la lógica pura."
    ),
    "web": (
        "Una página web de recetas con backend en Python usando solo la librería estándar (http.server y "
        "sqlite3). servidor.py sirve los archivos estáticos de web/ y una API JSON: GET /api/recetas (con "
        "búsqueda por texto y filtro por categoría), GET /api/recetas/<id>, POST /api/recetas (validar que "
        "tenga título, ingredientes y pasos), DELETE /api/recetas/<id>. La base se crea sola con 3 recetas de "
        "ejemplo. web/index.html, web/app.js y web/style.css: lista de recetas en tarjetas, buscador, filtro "
        "por categoría, detalle de una receta y formulario para agregar con mensajes de error claros; diseño "
        "lindo y adaptable al celular. Arranca con 'python3 servidor.py --puerto 8000'. Tests con unittest "
        "para la API en tests/test_api.py levantando el servidor en un puerto libre."
    ),
    "script": (
        "Un script de Python, solo librería estándar, que organiza los archivos de una carpeta: paquete "
        "organizador/ con organizador/reglas.py (clasificar por extensión en categorías configurables: "
        "imágenes, documentos, audio, video, comprimidos, código, otros), organizador/mover.py (mover a "
        "subcarpetas por categoría y opcionalmente por año/mes de modificación, sin pisar archivos: si el "
        "nombre existe agrega un sufijo), organizador/registro.py (guardar cada movimiento en un JSON para "
        "poder deshacer) y organizador/__main__.py con argparse: 'organizar CARPETA' con --simular (no mueve, "
        "solo muestra), --por-fecha y --config reglas.json; 'deshacer CARPETA' revierte el último "
        "organizado; 'estadisticas CARPETA' muestra cuántos archivos y cuánto espacio hay por categoría. "
        "Tests con unittest en tests/ usando carpetas temporales."
    ),
    # Proyecto GRANDE: no entra en un solo /construir; se corre con --grande (plan maestro + etapas verificadas).
    "grande": (
        "Un sistema de gestión para un almacén de barrio, en Python con solo la librería estándar. Productos con "
        "código, nombre, precio y stock; clientes; ventas con varios productos que descuentan el stock y NO "
        "permiten vender sin stock; reporte de ventas por día y de los productos más vendidos; exportar productos "
        "y ventas a CSV. Base sqlite3 que se crea sola. Una API JSON con http.server: productos (listar, buscar, "
        "crear, editar), clientes, ventas (crear y listar) y reportes, validando los datos con mensajes de error "
        "claros. Una página web en web/ (index.html, app.js, style.css) para cargar una venta, ver el stock y los "
        "reportes, adaptable al celular. Arranca con 'python3 -m almacen --puerto 8000'. Tests con unittest en "
        "tests/ para cada módulo y para la API levantando el servidor en un puerto libre."
    ),
}
MODO_GRANDE = {"grande"}                                               # estos usan --grande en vez de --construir


def _key() -> str:
    clave = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not clave:
        sys.exit("Falta OPENROUTER_API_KEY. Cargala como secreto del entorno (no en el chat) y abrí una sesión "
                 "nueva.")
    return clave


def _gasto(clave: str):
    pedido = urllib.request.Request("https://openrouter.ai/api/v1/key",
                                    headers={"Authorization": f"Bearer {clave}"})
    try:
        with urllib.request.urlopen(pedido, timeout=20) as r:
            return json.loads(r.read().decode("utf-8")).get("data", {}).get("usage")
    except (OSError, ValueError):
        return None


def _configurar(home: Path, clave: str) -> dict:
    """REAPER_HOME aislado con modelos gratis del catálogo REAL (la misma lógica que /perfil gratis)."""
    sys.path.insert(0, str(RAIZ))
    os.environ["REAPER_HOME"] = str(home)
    import reaper_v8 as r                                              # noqa: E402  (después de fijar REAPER_HOME)
    catalogo = r.catalogo_free_openrouter()
    if not catalogo:
        sys.exit("No pude leer el catálogo de modelos gratis de OpenRouter (¿red?).")
    if clave and not clave.startswith("clave-de-prueba"):
        # Igual que /perfil gratis con clave: solo los modelos que RESPONDEN hoy (pedido mínimo, $0).
        home.mkdir(parents=True, exist_ok=True)
        (home / ".clave_openrouter").write_text(clave, encoding="utf-8")
        cliente = r.LLMClient(clave, r.Settings(proveedor="openrouter", costo_maximo=0.01))
        vivos = r.free_que_responden(cliente, catalogo, on_probar=lambda m: print(f"  probando {m}", flush=True))
        if vivos:
            catalogo = vivos
    s = r.Settings(proveedor="openrouter")
    r.aplicar_perfil(s, "gratis", catalogo)
    s.modelos_rol = {"juez": catalogo[1] if len(catalogo) > 1 else catalogo[0]}
    s.costo_maximo, s.modo, s.torneo, s.candidatos = 0.01, "auto", False, 1
    s.max_tareas = 20
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps(s.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    archivo = home / ".clave_openrouter"
    archivo.write_text(clave, encoding="utf-8")
    archivo.chmod(0o600)
    return {"modelo": s.modelo, "respaldos": s.fallbacks, "juez": s.modelos_rol["juez"]}


def _estado(proyecto: Path) -> str:
    grande = proyecto / ".reaper" / "proyecto_grande.json"
    if grande.is_file():
        try:
            datos = json.loads(grande.read_text(encoding="utf-8"))
            etapas = datos["maestro"]["etapas"]
            hechas = sum(1 for e in etapas if e.get("estado") in ("verificada", "validada"))
            return f"{datos.get('estado')} ({hechas}/{len(etapas)} etapas)"
        except (OSError, ValueError, KeyError, TypeError):
            return "estado de /grande ilegible"
    informes = sorted((proyecto / ".reaper" / "informes").glob("build_*.md"))
    if not informes:
        return "sin informe (no llegó al cierre)"
    return informes[-1].read_text(encoding="utf-8").splitlines()[0].replace("# Build REAPER — ", "")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    minutos = 60
    if "--minutos" in sys.argv:
        minutos = int(sys.argv[sys.argv.index("--minutos") + 1])
        args = [a for a in args if a != str(minutos)]
    elegidos = args or [p for p in PROYECTOS if p not in MODO_GRANDE]
    desconocidos = [a for a in elegidos if a not in PROYECTOS]
    if desconocidos:
        sys.exit(f"Proyectos desconocidos: {desconocidos}. Opciones: {', '.join(PROYECTOS)}")
    clave = _key()
    base = Path.home() / "reaper_pruebas_real" / datetime.now().strftime("%Y%m%d_%H%M%S")
    home = base / "home"
    modelos = _configurar(home, clave)
    antes = _gasto(clave)
    print(f"Carpeta: {base}\nModelos (gratis): {modelos}\nGasto inicial USD: {antes}", flush=True)
    filas = []
    try:
        for nombre in elegidos:
            proyecto = base / nombre
            proyecto.mkdir(parents=True)
            log = base / f"{nombre}.log"
            inicio = time.monotonic()
            print(f"\n▶ {nombre}: construyendo (log en {log})", flush=True)
            env = {**os.environ, "REAPER_HOME": str(home), "REAPER_SIN_ANIMACION": "1", "NO_COLOR": "1"}
            env.pop("OPENROUTER_API_KEY", None)                        # REAPER la lee del archivo del HOME aislado
            try:
                with open(log, "w", encoding="utf-8") as salida:
                    modo = "--grande" if nombre in MODO_GRANDE else "--construir"
                    tope = minutos * 60 * (4 if nombre in MODO_GRANDE else 1)   # varias builds, una por etapa
                    rc = subprocess.run([sys.executable, str(REAPER), "--proyecto", str(proyecto), "--sin-animacion",
                                         "--auto", modo, PROYECTOS[nombre]], stdout=salida,
                                        stderr=subprocess.STDOUT, env=env, timeout=tope).returncode
            except subprocess.TimeoutExpired:
                rc = "TIMEOUT"
            filas.append((nombre, rc, _estado(proyecto), round((time.monotonic() - inicio) / 60, 1)))
            print(f"  {nombre}: exit={rc} · {filas[-1][2]} · {filas[-1][3]} min", flush=True)
    finally:
        (home / ".clave_openrouter").unlink(missing_ok=True)           # la clave no queda en disco
    despues = _gasto(clave)
    fugas = [str(p) for p in base.rglob("*") if p.is_file() and p.stat().st_size < 20_000_000
             and clave in p.read_text(encoding="utf-8", errors="ignore")]
    print("\n=== RESUMEN ===")
    for nombre, rc, estado, mins in filas:
        print(f"{nombre:<8} exit={rc!s:<7} {estado:<12} {mins} min   código en: {base / nombre}")
    print(f"Gasto USD: antes {antes} · después {despues} (debe ser igual: solo modelos gratis)")
    print(f"Clave en archivos generados: {'NINGUNO' if not fugas else fugas}")
    shutil.rmtree(home / "tmp", ignore_errors=True)
    return 1 if fugas else 0


if __name__ == "__main__":
    sys.exit(main())
