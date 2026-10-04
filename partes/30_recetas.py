"""
Recetario: fragmentos de código correctos y probados para tareas frecuentes.

Para un modelo de 24B, un buen ejemplo en el contexto vale más que mil
instrucciones. Cuando el pedido coincide claramente con una receta (por sus
etiquetas), REAPER agrega 1-2 recetas al prompt del implementador. También se
consultan a mano con /recetas <tema>.
"""


@dataclass(frozen=True)
class Receta:
    titulo: str
    lenguaje: str
    etiquetas: tuple
    descripcion: str
    codigo: str


RECETAS: list[Receta] = []


def receta(titulo: str, lenguaje: str, etiquetas: str, descripcion: str, codigo: str) -> Receta:
    r = Receta(titulo, lenguaje, tuple(e.strip() for e in etiquetas.split(",") if e.strip()),
               descripcion.strip(), textwrap.dedent(codigo).strip("\n"))
    RECETAS.append(r)
    return r


def _tokens_receta(r: Receta) -> tuple[set, set, set]:
    etiquetas = {_raiz(sin_tildes(e.lower())) for e in r.etiquetas for e in e.split()}
    titulo = {_raiz(sin_tildes(t)) for t in re.findall(r"[a-záéíóúñ0-9]{3,}", r.titulo.lower())}
    descripcion = {_raiz(sin_tildes(t)) for t in re.findall(r"[a-záéíóúñ0-9]{4,}", r.descripcion.lower())}
    return etiquetas, titulo, descripcion


def puntuar_receta(r: Receta, tokens: dict) -> float:
    etiquetas, titulo, descripcion = _tokens_receta(r)
    puntaje = 0.0
    for t, peso in tokens.items():
        if t in etiquetas:
            puntaje += 3 * peso
        if t in titulo:
            puntaje += 2 * peso
        if t in descripcion:
            puntaje += 0.5 * peso
    return puntaje


def buscar_recetas(consulta: str, k: int = 4, lenguaje: str = "") -> list[Receta]:
    tokens = tokens_pedido(consulta)
    if not tokens:
        return []
    puntuadas = []
    for i, r in enumerate(RECETAS):
        if lenguaje and r.lenguaje != lenguaje:
            continue
        p = puntuar_receta(r, tokens)
        if p > 0:
            puntuadas.append((p, -i, r))
    puntuadas.sort(key=lambda t: (-t[0], -t[1]))
    return [r for _, _, r in puntuadas[:k]]


def recetas_para_prompt(tarea: str, k: int = 2, umbral: float = 5.0, maximo: int = 2600) -> str:
    """Recetas que coinciden FUERTE con la tarea (si no, nada: mejor sin ruido)."""
    tokens = tokens_pedido(tarea)
    if not tokens:
        return ""
    puntuadas = sorted(((puntuar_receta(r, tokens), r) for r in RECETAS), key=lambda t: -t[0])
    elegidas = [r for p, r in puntuadas[:k] if p >= umbral]
    if not elegidas:
        return ""
    partes, usado = [], 0
    for r in elegidas:
        bloque = f"### {r.titulo} ({r.lenguaje})\n{r.descripcion}\n```{r.lenguaje}\n{r.codigo}\n```"
        if usado + len(bloque) > maximo:
            break
        partes.append(bloque)
        usado += len(bloque)
    return "RECETAS DE REFERENCIA (código probado; adaptalo, no lo copies a ciegas):\n" + "\n\n".join(partes) if partes else ""


# ======================================================================
# PYTHON: datos y archivos
# ======================================================================
receta("Guardar y cargar JSON de forma segura", "python", "json, guardar, cargar, persistencia, archivo, datos",
       "Escritura atómica (no se corrompe si se corta) y valor por defecto si el archivo no existe o está vacío.", r'''
import json
import os
import tempfile
from pathlib import Path


def cargar_json(ruta: Path, defecto):
    try:
        texto = Path(ruta).read_text(encoding="utf-8").strip()
        return json.loads(texto) if texto else defecto
    except FileNotFoundError:
        return defecto


def guardar_json(ruta: Path, datos) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)
''')

receta("SQLite con contexto y filas como dict", "python", "sqlite, base de datos, db, sql, tabla, crud, guardar",
       "Conexión con row_factory, CREATE TABLE IF NOT EXISTS, parámetros con ? (nunca f-strings en SQL).", r'''
import sqlite3


def conectar(ruta: str = "datos.db") -> sqlite3.Connection:
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("""CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE,
        precio REAL NOT NULL CHECK (precio >= 0))""")
    return con


def agregar(con, nombre: str, precio: float) -> int:
    with con:  # commit automático (o rollback si hay excepción)
        return con.execute("INSERT INTO productos (nombre, precio) VALUES (?, ?)", (nombre, precio)).lastrowid


def buscar(con, texto: str) -> list[dict]:
    filas = con.execute("SELECT * FROM productos WHERE nombre LIKE ? ORDER BY nombre", (f"%{texto}%",))
    return [dict(f) for f in filas]
''')

receta("Leer y escribir CSV con encabezados", "python", "csv, planilla, excel, exportar, importar, tabla",
       "DictReader/DictWriter con newline='' y validación por fila.", r'''
import csv
from pathlib import Path


def leer_csv(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def escribir_csv(ruta: Path, filas: list[dict], columnas: list[str]) -> None:
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)
''')

receta("Rutas relativas al script", "python", "ruta, path, archivo, carpeta, directorio, pathlib",
       "Construir rutas desde la ubicación del archivo, no desde el directorio actual.", r'''
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"
DATOS.mkdir(parents=True, exist_ok=True)
config = BASE / "config.json"
for archivo in sorted(DATOS.glob("*.txt")):
    print(archivo.name, archivo.stat().st_size)
''')

receta("Configuración con valores por defecto", "python", "configuracion, config, ajustes, settings, json",
       "dataclass con defaults que se sobreescriben desde JSON ignorando claves desconocidas.", r'''
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Config:
    idioma: str = "es"
    volumen: int = 5
    modo_oscuro: bool = True

    @classmethod
    def cargar(cls, ruta: Path) -> "Config":
        try:
            datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        validas = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in datos.items() if k in validas})

    def guardar(self, ruta: Path) -> None:
        Path(ruta).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
''')

receta("Fechas: parsear, formatear y sumar", "python", "fecha, fechas, hora, datetime, calendario, dias, timedelta",
       "date.fromisoformat, strftime, diferencias en días y validación con mensaje claro.", r'''
from datetime import date, datetime, timedelta


def parsear_fecha(texto: str) -> date:
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            continue
    raise ValueError(f"fecha inválida: {texto!r} (usá AAAA-MM-DD o DD/MM/AAAA)")


hoy = date.today()
en_una_semana = hoy + timedelta(days=7)
dias_hasta_fin_de_anio = (date(hoy.year, 12, 31) - hoy).days
print(hoy.strftime("%d/%m/%Y"), en_una_semana.isoformat(), dias_hasta_fin_de_anio)
''')

receta("Dinero con Decimal", "python", "dinero, precio, monto, moneda, decimal, factura, total, impuesto",
       "Nunca float para dinero: Decimal con quantize y redondeo bancario o comercial.", r'''
from decimal import ROUND_HALF_UP, Decimal


def a_dinero(valor) -> Decimal:
    return Decimal(str(valor).replace(",", ".")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def total_con_iva(subtotal, tasa="0.21") -> Decimal:
    subtotal = a_dinero(subtotal)
    return a_dinero(subtotal * (1 + Decimal(tasa)))


assert total_con_iva("100") == Decimal("121.00")
''')

# ======================================================================
# PYTHON: CLI y terminal
# ======================================================================
receta("CLI con subcomandos (argparse)", "python", "cli, argparse, comandos, argumentos, terminal, opciones",
       "main(argv) devuelve el código de salida: testeable y con errores claros a stderr.", r'''
import argparse
import sys
from typing import Optional


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="app", description="Mi herramienta")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("agregar", help="agrega un elemento")
    p.add_argument("nombre")
    p.add_argument("-c", "--cantidad", type=int, default=1)
    sub.add_parser("listar")
    args = parser.parse_args(argv)
    if args.cmd == "agregar":
        if args.cantidad < 1:
            print("error: la cantidad debe ser positiva", file=sys.stderr)
            return 1
        print(f"agregado {args.nombre} x{args.cantidad}")
    elif args.cmd == "listar":
        print("(vacío)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
''')

receta("Menú interactivo en la terminal", "python", "menu, opciones, interactivo, input, consola, tui",
       "Bucle de menú robusto: valida la opción, no se cae con Ctrl+D/Ctrl+C.", r'''
def pedir_opcion(opciones: list[str]) -> int:
    for i, texto in enumerate(opciones, start=1):
        print(f"  {i}. {texto}")
    while True:
        try:
            respuesta = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return len(opciones)  # última opción = salir
        if respuesta.isdigit() and 1 <= int(respuesta) <= len(opciones):
            return int(respuesta)
        print(f"Elegí un número entre 1 y {len(opciones)}.")


def main() -> None:
    opciones = ["Ver lista", "Agregar", "Salir"]
    while True:
        eleccion = pedir_opcion(opciones)
        if eleccion == 3:
            break
        print(f"Elegiste: {opciones[eleccion - 1]}")
''')

receta("Colores ANSI en la terminal", "python", "colores, ansi, terminal, consola, estilo, color",
       "Colores que se apagan solos si la salida no es una terminal o existe NO_COLOR.", r'''
import os
import sys

USAR_COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")


def color(texto: str, codigo: str) -> str:
    return f"\033[{codigo}m{texto}\033[0m" if USAR_COLOR else texto


def verde(t): return color(t, "92")
def rojo(t): return color(t, "91")
def negrita(t): return color(t, "1")

print(verde("✓ listo"), rojo("✗ error"), negrita("importante"))
''')

receta("Barra de progreso sin librerías", "python", "progreso, barra, porcentaje, carga, terminal",
       "Se redibuja en la misma línea con \\r.", r'''
import sys
import time


def barra(actual: int, total: int, ancho: int = 30) -> None:
    fraccion = actual / total if total else 1
    llenos = int(ancho * fraccion)
    sys.stdout.write(f"\r[{'█' * llenos}{'·' * (ancho - llenos)}] {fraccion:6.1%}")
    sys.stdout.flush()
    if actual >= total:
        sys.stdout.write("\n")


for i in range(101):
    barra(i, 100)
    time.sleep(0.01)
''')

receta("Juego en la terminal con curses", "python", "curses, juego, terminal, teclado, pantalla, game, tui",
       "Bucle de juego no bloqueante con curses.wrapper (restaura la terminal aunque haya error).", r'''
import curses
import time


def juego(pantalla) -> int:
    curses.curs_set(0)
    pantalla.nodelay(True)  # getch no bloquea
    alto, ancho = pantalla.getmaxyx()
    x, y, puntaje = ancho // 2, alto // 2, 0
    while True:
        tecla = pantalla.getch()
        if tecla in (ord("q"), 27):
            break
        dx = {curses.KEY_LEFT: -1, curses.KEY_RIGHT: 1}.get(tecla, 0)
        dy = {curses.KEY_UP: -1, curses.KEY_DOWN: 1}.get(tecla, 0)
        x = max(0, min(ancho - 2, x + dx))
        y = max(1, min(alto - 2, y + dy))
        pantalla.erase()
        pantalla.addstr(0, 0, f"Puntaje: {puntaje}  (q para salir)")
        pantalla.addstr(y, x, "@")
        pantalla.refresh()
        time.sleep(0.05)
    return puntaje


if __name__ == "__main__":
    print("puntaje final:", curses.wrapper(juego))
''')

# ======================================================================
# PYTHON: red
# ======================================================================
receta("GET/POST JSON con urllib", "python", "http, api, request, get, post, json, urllib, red, descargar",
       "Sin requests: timeout, headers, manejo de HTTPError y JSON.", r'''
import json
import urllib.error
import urllib.request


def pedir_json(url: str, datos: dict = None, metodo: str = None, timeout: int = 15) -> dict:
    cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
    pedido = urllib.request.Request(url, data=cuerpo, method=metodo or ("POST" if datos else "GET"),
                                    headers={"Content-Type": "application/json", "User-Agent": "mi-app/1.0"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code}: {detalle}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"sin conexión: {e.reason}") from e
''')

receta("Servidor HTTP JSON mínimo", "python", "servidor, http, api, rest, backend, endpoint, web",
       "http.server con rutas, JSON y códigos de estado; ThreadingHTTPServer para varios clientes.", r'''
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATOS = {"items": []}


class Manejador(BaseHTTPRequestHandler):
    def _json(self, estado: int, cuerpo) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if self.path == "/items":
            return self._json(200, DATOS["items"])
        self._json(404, {"error": "no existe"})

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        try:
            item = json.loads(self.rfile.read(largo) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "JSON inválido"})
        DATOS["items"].append(item)
        self._json(201, item)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8000), Manejador).serve_forever()
''')

receta("Servidor de archivos estáticos para probar una web", "bash", "web, html, servidor, probar, local, navegador",
       "Para ver una web en el navegador del celular sin instalar nada.", r'''
# desde la carpeta del proyecto web:
python3 -m http.server 8080
# y abrí en el navegador: http://127.0.0.1:8080
# (Termux) abrir directo: termux-open-url http://127.0.0.1:8080
''')

receta("Reintentos con espera exponencial", "python", "reintentar, retry, backoff, red, error, fallos",
       "Decorador para reintentar operaciones que fallan de forma transitoria.", r'''
import functools
import random
import time


def reintentar(intentos: int = 4, base: float = 1.0, excepciones=(OSError,)):
    def decorador(funcion):
        @functools.wraps(funcion)
        def envoltura(*args, **kwargs):
            for intento in range(intentos):
                try:
                    return funcion(*args, **kwargs)
                except excepciones:
                    if intento == intentos - 1:
                        raise
                    time.sleep(base * 2 ** intento + random.uniform(0, 0.5))
        return envoltura
    return decorador
''')

# ======================================================================
# PYTHON: concurrencia y procesos
# ======================================================================
receta("Tareas en paralelo con ThreadPoolExecutor", "python", "paralelo, hilos, threads, concurrencia, descargas",
       "Para I/O (red, disco): resultados en orden de llegada y errores por tarea.", r'''
from concurrent.futures import ThreadPoolExecutor, as_completed


def procesar_todos(elementos, funcion, hilos: int = 4) -> dict:
    resultados, errores = {}, {}
    with ThreadPoolExecutor(max_workers=hilos) as ejecutor:
        futuros = {ejecutor.submit(funcion, e): e for e in elementos}
        for futuro in as_completed(futuros):
            elemento = futuros[futuro]
            try:
                resultados[elemento] = futuro.result()
            except Exception as error:  # se registra por elemento, no corta todo
                errores[elemento] = error
    return {"ok": resultados, "errores": errores}
''')

receta("asyncio: varias tareas con timeout", "python", "asyncio, async, await, concurrencia, timeout, tareas",
       "gather con return_exceptions y wait_for para que nada se cuelgue.", r'''
import asyncio


async def trabajo(n: int) -> int:
    await asyncio.sleep(0.1 * n)
    return n * n


async def principal() -> None:
    tareas = [asyncio.wait_for(trabajo(n), timeout=1.0) for n in range(5)]
    for n, resultado in enumerate(await asyncio.gather(*tareas, return_exceptions=True)):
        print(n, "error" if isinstance(resultado, Exception) else resultado)


asyncio.run(principal())
''')

receta("Ejecutar comandos de forma segura", "python", "subprocess, comando, shell, ejecutar, proceso, terminal",
       "Lista de argumentos (sin shell=True), timeout y salida capturada.", r'''
import subprocess


def correr(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", f"no existe el programa {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"tardó más de {timeout}s"
    return r.returncode, r.stdout, r.stderr


codigo, salida, error = correr(["git", "status", "--short"])
''')

receta("Logging a archivo y consola", "python", "logging, log, registro, bitacora, depurar, errores",
       "Configuración de logging con rotación de archivos.", r'''
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configurar_logs(nombre: str = "app", carpeta: Path = Path.home() / ".logs") -> logging.Logger:
    carpeta.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(nombre)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        archivo = RotatingFileHandler(carpeta / f"{nombre}.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        archivo.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        consola = logging.StreamHandler()
        consola.setLevel(logging.INFO)
        consola.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(archivo)
        logger.addHandler(consola)
    return logger
''')

# ======================================================================
# PYTHON: tests
# ======================================================================
receta("Tests con unittest (estructura base)", "python", "test, tests, unittest, prueba, pruebas, assert",
       "tests/test_modulo.py con casos normales, borde y errores.", r'''
import unittest

from calculadora import dividir


class TestDividir(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(dividir(10, 2), 5)

    def test_decimales(self):
        self.assertAlmostEqual(dividir(1, 3), 0.3333, places=4)

    def test_division_por_cero(self):
        with self.assertRaises(ZeroDivisionError):
            dividir(1, 0)


if __name__ == "__main__":
    unittest.main()
''')

receta("Simular input() y capturar print() en tests", "python", "test, input, print, mock, simular, stdout, consola",
       "unittest.mock.patch para input y redirect_stdout para la salida.", r'''
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from juego import main


class TestInteractivo(unittest.TestCase):
    def test_flujo(self):
        salida = io.StringIO()
        with patch("builtins.input", side_effect=["2", "salir"]), redirect_stdout(salida):
            main()
        self.assertIn("Elegiste", salida.getvalue())
''')

receta("Archivos temporales en tests", "python", "test, temporal, tempfile, archivo, carpeta, prueba",
       "Cada test trabaja en su carpeta temporal que se borra sola.", r'''
import tempfile
import unittest
from pathlib import Path

from almacen import cargar, guardar


class TestAlmacen(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ida_y_vuelta(self):
        ruta = self.dir / "datos.json"
        guardar(ruta, {"a": 1})
        self.assertEqual(cargar(ruta), {"a": 1})
''')

receta("Simular red y tiempo en tests", "python", "test, mock, red, api, tiempo, fecha, simular",
       "Nada de red real en tests: se reemplaza la función que hace la petición.", r'''
import unittest
from datetime import datetime
from unittest.mock import patch

import clima


class TestClima(unittest.TestCase):
    @patch("clima.pedir_json", return_value={"temp": 21.5})
    def test_temperatura(self, falso):
        self.assertEqual(clima.temperatura("Rosario"), 21.5)
        falso.assert_called_once()

    def test_saludo_segun_hora(self):
        self.assertEqual(clima.saludo(datetime(2026, 1, 1, 9)), "Buen día")
''')

# ======================================================================
# TERMUX
# ======================================================================
receta("Notificaciones y toasts en Android (termux-api)", "python", "termux, notificacion, notificar, android, toast, aviso",
       "Requiere `pkg install termux-api` y la app Termux:API. Falla silenciosa si no están.", r'''
import shutil
import subprocess


def notificar(titulo: str, texto: str) -> bool:
    if not shutil.which("termux-notification"):
        return False
    subprocess.run(["termux-notification", "--title", titulo, "--content", texto], timeout=10)
    return True


def toast(texto: str) -> bool:
    if not shutil.which("termux-toast"):
        return False
    subprocess.run(["termux-toast", texto], timeout=10)
    return True
''')

receta("Portapapeles, batería y vibración (termux-api)", "python", "termux, portapapeles, clipboard, bateria, vibrar, android",
       "Los comandos termux-* devuelven JSON por stdout.", r'''
import json
import shutil
import subprocess


def termux(*args: str, timeout: int = 10) -> str:
    if not shutil.which(args[0]):
        raise RuntimeError(f"falta {args[0]}: pkg install termux-api (y la app Termux:API)")
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout).stdout


def copiar(texto: str) -> None:
    subprocess.run(["termux-clipboard-set"], input=texto, text=True, timeout=10)


def pegar() -> str:
    return termux("termux-clipboard-get")


def bateria() -> dict:
    return json.loads(termux("termux-battery-status"))  # {"percentage": 80, "status": "CHARGING", ...}


def vibrar(ms: int = 300) -> None:
    termux("termux-vibrate", "-d", str(ms))
''')

receta("Rutas de almacenamiento en Termux", "bash", "termux, almacenamiento, sdcard, descargas, storage, android",
       "Acceso a /sdcard y carpetas compartidas.", r'''
termux-setup-storage            # una vez: pide permiso de almacenamiento
ls ~/storage/shared             # = /sdcard
ls ~/storage/downloads          # Descargas
ls ~/storage/dcim               # Fotos de la cámara
echo $PREFIX                    # /data/data/com.termux/files/usr (en lugar de /usr)
pkg install python nodejs git   # paquetes (sin sudo)
''')

receta("Tarea programada en Termux", "bash", "termux, cron, programar, tarea, automatico, servicio",
       "crond con termux-services (no hay systemd).", r'''
pkg install cronie termux-services
sv-enable crond                 # (reiniciá Termux si sv-enable no existe todavía)
crontab -e                      # agregar por ejemplo:
# */30 * * * * python3 $HOME/proyecto/respaldo.py >> $HOME/respaldo.log 2>&1
''')

# ======================================================================
# JAVASCRIPT
# ======================================================================
receta("Módulo ES con lógica pura + test node:test", "javascript", "javascript, node, test, modulo, esm, import, export",
       "Separar lógica testeable del DOM; tests con el runner incorporado de Node.", r'''
// src/carrito.js
export function total(items) {
  return items.reduce((suma, { precio, cantidad = 1 }) => suma + precio * cantidad, 0);
}

// tests/carrito.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { total } from '../src/carrito.js';

test('suma precio por cantidad', () => {
  assert.equal(total([{ precio: 10, cantidad: 2 }, { precio: 5 }]), 25);
});
test('carrito vacío', () => assert.equal(total([]), 0));
''')

receta("Guardar estado en localStorage", "javascript", "localstorage, guardar, navegador, web, estado, persistencia",
       "Con valor por defecto y protección contra JSON corrupto.", r'''
const CLAVE = 'mi-app-estado';

export function cargarEstado(defecto = { tareas: [] }) {
  try {
    const crudo = localStorage.getItem(CLAVE);
    return crudo ? { ...defecto, ...JSON.parse(crudo) } : defecto;
  } catch {
    return defecto;
  }
}

export function guardarEstado(estado) {
  localStorage.setItem(CLAVE, JSON.stringify(estado));
}
''')

receta("Fetch con timeout y errores claros", "javascript", "fetch, api, http, red, timeout, javascript, json",
       "AbortController para cortar pedidos colgados.", r'''
export async function pedirJSON(url, opciones = {}, ms = 10000) {
  const control = new AbortController();
  const reloj = setTimeout(() => control.abort(), ms);
  try {
    const r = await fetch(url, { ...opciones, signal: control.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
    return await r.json();
  } catch (e) {
    if (e.name === 'AbortError') throw new Error(`tardó más de ${ms} ms`);
    throw e;
  } finally {
    clearTimeout(reloj);
  }
}
''')

receta("Servidor HTTP en Node sin dependencias", "javascript", "node, servidor, http, api, backend, rest",
       "Módulo http con rutas y JSON (Node 18+).", r'''
import http from 'node:http';

const notas = [];

export const servidor = http.createServer(async (req, res) => {
  const enviar = (estado, datos) => {
    res.writeHead(estado, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(datos));
  };
  if (req.method === 'GET' && req.url === '/notas') return enviar(200, notas);
  if (req.method === 'POST' && req.url === '/notas') {
    let cuerpo = '';
    for await (const trozo of req) cuerpo += trozo;
    try {
      const nota = JSON.parse(cuerpo || '{}');
      notas.push(nota);
      return enviar(201, nota);
    } catch {
      return enviar(400, { error: 'JSON inválido' });
    }
  }
  enviar(404, { error: 'no existe' });
});

if (import.meta.url === `file://${process.argv[1]}`) servidor.listen(3000);
''')

receta("Página web base mobile-first", "html", "html, web, pagina, movil, responsive, css",
       "Estructura HTML con viewport, CSS y JS como módulo.", r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mi app</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main id="app">
    <h1>Mi app</h1>
    <form id="form"><input id="texto" required placeholder="Escribí algo"><button>Agregar</button></form>
    <ul id="lista"></ul>
  </main>
  <script type="module" src="app.js"></script>
</body>
</html>
''')

# ======================================================================
# BASH
# ======================================================================
receta("Script bash robusto", "bash", "bash, script, shell, getopts, opciones, sh",
       "Modo estricto, ayuda, opciones con getopts y limpieza al salir.", r'''
#!/usr/bin/env bash
set -euo pipefail

uso() { echo "uso: $0 [-v] [-o salida] archivo"; exit 1; }
VERBOSO=0; SALIDA="salida.txt"
while getopts ":vo:h" opt; do
  case $opt in
    v) VERBOSO=1 ;;
    o) SALIDA="$OPTARG" ;;
    h|*) uso ;;
  esac
done
shift $((OPTIND - 1))
[[ $# -eq 1 ]] || uso
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
[[ $VERBOSO -eq 1 ]] && echo "procesando $1 → $SALIDA"
sort -u "$1" > "$TMP" && mv "$TMP" "$SALIDA"
''')
