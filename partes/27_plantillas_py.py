"""Plantillas Python (librería estándar): CLIs, APIs, juegos, bots y utilidades. Lote 1."""

_PY_TESTS = "python3 -m unittest discover -s tests -t ."

# ======================================================================
# python-cli
# ======================================================================
registrar_plantilla(
    "python-cli",
    "CLI en Python con subcomandos (argparse), lógica pura separada y tests. Base para cualquier herramienta de terminal.",
    "python",
    {
        "__PROYECTO__/__init__.py": r'''
"""__TITULO__: herramienta de línea de comandos."""

__version__ = "0.1.0"
''',
        "__PROYECTO__/__main__.py": r'''
import sys

from __PROYECTO__.cli import main

sys.exit(main())
''',
        "__PROYECTO__/nucleo.py": r'''
"""Lógica pura (sin input/print): fácil de testear y de reutilizar."""

import re
from collections import Counter

_PALABRA = re.compile(r"[a-záéíóúüñ0-9']+", re.IGNORECASE)


def normalizar(texto: str) -> str:
    """Minúsculas y espacios simples."""
    return " ".join(texto.lower().split())


def palabras(texto: str) -> list[str]:
    """Lista de palabras del texto, en minúsculas."""
    return [p.lower() for p in _PALABRA.findall(texto)]


def contar(texto: str) -> dict[str, int]:
    """Cantidad de líneas, palabras y caracteres."""
    return {
        "lineas": len(texto.splitlines()),
        "palabras": len(palabras(texto)),
        "caracteres": len(texto),
    }


def frecuentes(texto: str, n: int = 5) -> list[tuple[str, int]]:
    """Las n palabras más frecuentes (empates por orden alfabético)."""
    if n <= 0:
        return []
    conteo = Counter(palabras(texto))
    return sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def saludo(nombre: str, gritar: bool = False) -> str:
    nombre = nombre.strip() or "mundo"
    texto = f"Hola, {nombre}!"
    return texto.upper() if gritar else texto
''',
        "__PROYECTO__/cli.py": r'''
"""Interfaz de línea de comandos."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from __PROYECTO__ import __version__
from __PROYECTO__.nucleo import contar, frecuentes, saludo


def _leer(ruta: str) -> str:
    if ruta == "-":
        return sys.stdin.read()
    return Path(ruta).read_text(encoding="utf-8")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="__PROYECTO__", description="__TITULO__")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("saludar", help="saluda a alguien")
    p.add_argument("nombre", nargs="?", default="mundo")
    p.add_argument("--gritar", action="store_true")

    p = sub.add_parser("contar", help="cuenta líneas, palabras y caracteres de un archivo")
    p.add_argument("archivo", help="ruta o - para stdin")
    p.add_argument("--json", action="store_true", help="salida en JSON")

    p = sub.add_parser("top", help="palabras más frecuentes")
    p.add_argument("archivo")
    p.add_argument("-n", type=int, default=5)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        if args.comando == "saludar":
            print(saludo(args.nombre, args.gritar))
        elif args.comando == "contar":
            datos = contar(_leer(args.archivo))
            if args.json:
                print(json.dumps(datos, ensure_ascii=False))
            else:
                for clave, valor in datos.items():
                    print(f"{clave}: {valor}")
        elif args.comando == "top":
            for palabra, veces in frecuentes(_leer(args.archivo), args.n):
                print(f"{veces:>5}  {palabra}")
    except FileNotFoundError as e:
        print(f"error: no existe {e.filename}", file=sys.stderr)
        return 1
    except UnicodeDecodeError:
        print("error: el archivo no es texto UTF-8", file=sys.stderr)
        return 1
    return 0
''',
        "tests/__init__.py": "",
        "tests/test_nucleo.py": r'''
import unittest

from __PROYECTO__.nucleo import contar, frecuentes, normalizar, palabras, saludo


class TestNucleo(unittest.TestCase):
    def test_normalizar(self):
        self.assertEqual(normalizar("  Hola   MUNDO "), "hola mundo")

    def test_palabras_con_tildes(self):
        self.assertEqual(palabras("Árbol, canción y ñandú"), ["árbol", "canción", "y", "ñandú"])

    def test_contar(self):
        self.assertEqual(contar("uno dos\ntres"), {"lineas": 2, "palabras": 3, "caracteres": 12})

    def test_contar_vacio(self):
        self.assertEqual(contar(""), {"lineas": 0, "palabras": 0, "caracteres": 0})

    def test_frecuentes_ordena_y_desempata(self):
        self.assertEqual(frecuentes("b a b c a b", 2), [("b", 3), ("a", 2)])
        self.assertEqual(frecuentes("x y", 0), [])

    def test_saludo(self):
        self.assertEqual(saludo("Ana"), "Hola, Ana!")
        self.assertEqual(saludo("", gritar=True), "HOLA, MUNDO!")


if __name__ == "__main__":
    unittest.main()
''',
        "tests/test_cli.py": r'''
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from __PROYECTO__.cli import main


def correr(*argv):
    salida, errores = io.StringIO(), io.StringIO()
    with redirect_stdout(salida), redirect_stderr(errores):
        codigo = main(list(argv))
    return codigo, salida.getvalue(), errores.getvalue()


class TestCLI(unittest.TestCase):
    def test_saludar(self):
        self.assertEqual(correr("saludar", "Leo"), (0, "Hola, Leo!\n", ""))

    def test_contar_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "a.txt"
            ruta.write_text("hola hola\nchau\n", encoding="utf-8")
            codigo, salida, _ = correr("contar", str(ruta), "--json")
            self.assertEqual(codigo, 0)
            self.assertEqual(json.loads(salida)["palabras"], 3)

    def test_archivo_inexistente(self):
        codigo, _, errores = correr("contar", "/no/existe.txt")
        self.assertEqual(codigo, 1)
        self.assertIn("no existe", errores)

    def test_top(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "a.txt"
            ruta.write_text("sol luna sol", encoding="utf-8")
            codigo, salida, _ = correr("top", str(ruta), "-n", "1")
            self.assertEqual(codigo, 0)
            self.assertIn("sol", salida)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m __PROYECTO__ saludar Termux",
    etiquetas=("cli", "terminal", "argparse", "herramienta", "comandos"),
)

# ======================================================================
# tareas (todo)
# ======================================================================
registrar_plantilla(
    "tareas",
    "Gestor de tareas (todo) en la terminal con prioridades, búsqueda y guardado atómico en JSON.",
    "python",
    {
        "tareas/__init__.py": "",
        "tareas/modelo.py": r'''
"""Modelo de tareas sin entrada/salida."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

PRIORIDADES = ("baja", "media", "alta")


@dataclass
class Tarea:
    id: int
    texto: str
    prioridad: str = "media"
    hecha: bool = False
    creada: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def __post_init__(self):
        self.texto = self.texto.strip()
        if not self.texto:
            raise ValueError("la tarea no puede estar vacía")
        if self.prioridad not in PRIORIDADES:
            raise ValueError(f"prioridad inválida: {self.prioridad} (usá {', '.join(PRIORIDADES)})")


class ListaTareas:
    def __init__(self, tareas: Optional[list] = None):
        self.tareas: list[Tarea] = list(tareas or [])

    def _siguiente_id(self) -> int:
        return max((t.id for t in self.tareas), default=0) + 1

    def agregar(self, texto: str, prioridad: str = "media") -> Tarea:
        tarea = Tarea(self._siguiente_id(), texto, prioridad)
        self.tareas.append(tarea)
        return tarea

    def obtener(self, id_: int) -> Tarea:
        for t in self.tareas:
            if t.id == id_:
                return t
        raise KeyError(f"no existe la tarea {id_}")

    def completar(self, id_: int) -> Tarea:
        tarea = self.obtener(id_)
        tarea.hecha = True
        return tarea

    def borrar(self, id_: int) -> Tarea:
        tarea = self.obtener(id_)
        self.tareas.remove(tarea)
        return tarea

    def pendientes(self) -> list[Tarea]:
        orden = {p: i for i, p in enumerate(reversed(PRIORIDADES))}
        return sorted((t for t in self.tareas if not t.hecha), key=lambda t: (orden[t.prioridad], t.id))

    def buscar(self, texto: str) -> list[Tarea]:
        texto = texto.lower().strip()
        return [t for t in self.tareas if texto in t.texto.lower()]

    def a_dicts(self) -> list[dict]:
        return [asdict(t) for t in self.tareas]

    @classmethod
    def desde_dicts(cls, datos: list) -> "ListaTareas":
        return cls([Tarea(**d) for d in datos])
''',
        "tareas/almacen.py": r'''
"""Guardado en JSON con escritura atómica (no se corrompe si se corta a mitad)."""

import json
import os
import tempfile
from pathlib import Path

from tareas.modelo import ListaTareas


def cargar(ruta: Path) -> ListaTareas:
    ruta = Path(ruta)
    if not ruta.exists():
        return ListaTareas()
    texto = ruta.read_text(encoding="utf-8").strip()
    if not texto:
        return ListaTareas()
    return ListaTareas.desde_dicts(json.loads(texto))


def guardar(ruta: Path, lista: ListaTareas) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, temporal = tempfile.mkstemp(dir=str(ruta.parent), prefix=".tareas_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(lista.a_dicts(), f, ensure_ascii=False, indent=2)
        os.replace(temporal, ruta)
    except BaseException:
        if os.path.exists(temporal):
            os.unlink(temporal)
        raise
''',
        "tareas/cli.py": r'''
"""Uso: python3 -m tareas.cli agregar "comprar pan" -p alta | listar | hecha 1 | borrar 1 | buscar pan"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from tareas.almacen import cargar, guardar
from tareas.modelo import PRIORIDADES

MARCAS = {"alta": "!!", "media": "! ", "baja": "  "}


def ruta_datos() -> Path:
    return Path(os.environ.get("TAREAS_ARCHIVO", Path.home() / ".tareas.json"))


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="tareas")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("agregar")
    p.add_argument("texto")
    p.add_argument("-p", "--prioridad", choices=PRIORIDADES, default="media")
    p = sub.add_parser("listar")
    p.add_argument("--todas", action="store_true")
    for nombre in ("hecha", "borrar"):
        sub.add_parser(nombre).add_argument("id", type=int)
    sub.add_parser("buscar").add_argument("texto")
    args = parser.parse_args(argv)

    ruta = ruta_datos()
    lista = cargar(ruta)
    try:
        if args.cmd == "agregar":
            t = lista.agregar(args.texto, args.prioridad)
            print(f"agregada #{t.id}: {t.texto}")
        elif args.cmd == "listar":
            tareas = lista.tareas if args.todas else lista.pendientes()
            if not tareas:
                print("no hay tareas")
            for t in tareas:
                print(f"{'✓' if t.hecha else '○'} #{t.id:<3} {MARCAS[t.prioridad]} {t.texto}")
        elif args.cmd == "hecha":
            print(f"completada: {lista.completar(args.id).texto}")
        elif args.cmd == "borrar":
            print(f"borrada: {lista.borrar(args.id).texto}")
        elif args.cmd == "buscar":
            for t in lista.buscar(args.texto):
                print(f"#{t.id} {t.texto}")
    except (KeyError, ValueError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 1
    guardar(ruta, lista)
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_tareas.py": r'''
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tareas import cli
from tareas.almacen import cargar, guardar
from tareas.modelo import ListaTareas, Tarea


class TestModelo(unittest.TestCase):
    def test_agregar_y_ids(self):
        lista = ListaTareas()
        self.assertEqual(lista.agregar("a").id, 1)
        self.assertEqual(lista.agregar("b").id, 2)

    def test_vacia_o_prioridad_invalida(self):
        with self.assertRaises(ValueError):
            Tarea(1, "   ")
        with self.assertRaises(ValueError):
            Tarea(1, "x", "urgente")

    def test_pendientes_ordenadas_por_prioridad(self):
        lista = ListaTareas()
        lista.agregar("baja", "baja")
        lista.agregar("alta", "alta")
        lista.agregar("media")
        self.assertEqual([t.texto for t in lista.pendientes()], ["alta", "media", "baja"])

    def test_completar_borrar_buscar(self):
        lista = ListaTareas()
        lista.agregar("Comprar pan")
        lista.agregar("Llamar")
        lista.completar(1)
        self.assertEqual([t.texto for t in lista.pendientes()], ["Llamar"])
        self.assertEqual(len(lista.buscar("PAN")), 1)
        lista.borrar(2)
        with self.assertRaises(KeyError):
            lista.obtener(2)


class TestAlmacen(unittest.TestCase):
    def test_ida_y_vuelta(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "t.json"
            lista = ListaTareas()
            lista.agregar("persistir", "alta")
            guardar(ruta, lista)
            otra = cargar(ruta)
            self.assertEqual(otra.tareas[0].texto, "persistir")
            self.assertEqual(otra.tareas[0].prioridad, "alta")

    def test_archivo_inexistente_o_vacio(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cargar(Path(tmp) / "no.json").tareas, [])
            (Path(tmp) / "vacio.json").write_text("")
            self.assertEqual(cargar(Path(tmp) / "vacio.json").tareas, [])


class TestCLI(unittest.TestCase):
    def test_flujo(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TAREAS_ARCHIVO"] = str(Path(tmp) / "t.json")
            try:
                salida = io.StringIO()
                with redirect_stdout(salida):
                    self.assertEqual(cli.main(["agregar", "uno", "-p", "alta"]), 0)
                    self.assertEqual(cli.main(["hecha", "1"]), 0)
                    self.assertEqual(cli.main(["listar"]), 0)
                self.assertIn("no hay tareas", salida.getvalue())
                self.assertEqual(cli.main(["borrar", "9"]), 1)
            finally:
                del os.environ["TAREAS_ARCHIVO"]


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar='python3 -m tareas.cli agregar "probar REAPER" -p alta',
    etiquetas=("tareas", "todo", "pendientes", "json", "cli", "lista"),
)

# ======================================================================
# api-notas (http.server + sqlite)
# ======================================================================
registrar_plantilla(
    "api-notas",
    "API REST JSON de notas con http.server y sqlite3 (CRUD completo, errores 400/404, tests con servidor real).",
    "python",
    {
        "api/__init__.py": "",
        "api/db.py": r'''
"""Repositorio de notas sobre sqlite3."""

import sqlite3
import threading
from datetime import datetime
from typing import Optional


class Repositorio:
    def __init__(self, ruta: str = ":memory:"):
        self._conexion = sqlite3.connect(ruta, check_same_thread=False)
        self._conexion.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conexion:
            self._conexion.execute(
                "CREATE TABLE IF NOT EXISTS notas ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " titulo TEXT NOT NULL,"
                " texto TEXT NOT NULL DEFAULT '',"
                " creada TEXT NOT NULL)"
            )

    @staticmethod
    def _dict(fila: Optional[sqlite3.Row]) -> Optional[dict]:
        return dict(fila) if fila is not None else None

    def crear(self, titulo: str, texto: str = "") -> dict:
        titulo = (titulo or "").strip()
        if not titulo:
            raise ValueError("el título es obligatorio")
        with self._lock, self._conexion:
            cursor = self._conexion.execute(
                "INSERT INTO notas (titulo, texto, creada) VALUES (?, ?, ?)",
                (titulo, texto or "", datetime.now().isoformat(timespec="seconds")),
            )
            nuevo_id = cursor.lastrowid
        return self.obtener(nuevo_id)

    def listar(self, buscar: str = "") -> list[dict]:
        with self._lock:
            if buscar:
                filas = self._conexion.execute(
                    "SELECT * FROM notas WHERE titulo LIKE ? OR texto LIKE ? ORDER BY id",
                    (f"%{buscar}%", f"%{buscar}%"),
                ).fetchall()
            else:
                filas = self._conexion.execute("SELECT * FROM notas ORDER BY id").fetchall()
        return [dict(f) for f in filas]

    def obtener(self, id_: int) -> Optional[dict]:
        with self._lock:
            fila = self._conexion.execute("SELECT * FROM notas WHERE id = ?", (id_,)).fetchone()
        return self._dict(fila)

    def actualizar(self, id_: int, titulo: Optional[str] = None, texto: Optional[str] = None) -> Optional[dict]:
        actual = self.obtener(id_)
        if actual is None:
            return None
        nuevo_titulo = actual["titulo"] if titulo is None else titulo.strip()
        if not nuevo_titulo:
            raise ValueError("el título no puede quedar vacío")
        with self._lock, self._conexion:
            self._conexion.execute(
                "UPDATE notas SET titulo = ?, texto = ? WHERE id = ?",
                (nuevo_titulo, actual["texto"] if texto is None else texto, id_),
            )
        return self.obtener(id_)

    def borrar(self, id_: int) -> bool:
        with self._lock, self._conexion:
            cursor = self._conexion.execute("DELETE FROM notas WHERE id = ?", (id_,))
        return cursor.rowcount > 0

    def cerrar(self) -> None:
        self._conexion.close()
''',
        "api/servidor.py": r'''
"""Servidor HTTP JSON. Rutas:
    GET    /notas?buscar=texto
    POST   /notas            {"titulo": "...", "texto": "..."}
    GET    /notas/<id>
    PUT    /notas/<id>       {"titulo": "...", "texto": "..."}
    DELETE /notas/<id>
"""

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from api.db import Repositorio

_RUTA_NOTA = re.compile(r"^/notas/(\d+)/?$")
MAX_CUERPO = 1_000_000


class Manejador(BaseHTTPRequestHandler):
    repo: Repositorio = None  # se asigna en crear_servidor
    server_version = "__Proyecto__/0.1"

    def log_message(self, formato, *args):  # silencio en tests; poner print para depurar
        if os.environ.get("API_LOG"):
            sys.stderr.write(formato % args + "\n")

    def _responder(self, estado: int, datos=None) -> None:
        cuerpo = b"" if datos is None else json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        if cuerpo:
            self.wfile.write(cuerpo)

    def _json(self):
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > MAX_CUERPO:
            raise ValueError("cuerpo demasiado grande")
        crudo = self.rfile.read(largo) if largo else b"{}"
        try:
            datos = json.loads(crudo.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("JSON inválido")
        if not isinstance(datos, dict):
            raise ValueError("se esperaba un objeto JSON")
        return datos

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.rstrip("/") == "/notas":
            buscar = parse_qs(url.query).get("buscar", [""])[0]
            return self._responder(200, self.repo.listar(buscar))
        m = _RUTA_NOTA.match(url.path)
        if m:
            nota = self.repo.obtener(int(m.group(1)))
            return self._responder(200, nota) if nota else self._responder(404, {"error": "no existe"})
        return self._responder(404, {"error": "ruta desconocida"})

    def do_POST(self):
        if urlparse(self.path).path.rstrip("/") != "/notas":
            return self._responder(404, {"error": "ruta desconocida"})
        try:
            datos = self._json()
            nota = self.repo.crear(datos.get("titulo", ""), datos.get("texto", ""))
        except ValueError as e:
            return self._responder(400, {"error": str(e)})
        return self._responder(201, nota)

    def do_PUT(self):
        m = _RUTA_NOTA.match(urlparse(self.path).path)
        if not m:
            return self._responder(404, {"error": "ruta desconocida"})
        try:
            datos = self._json()
            nota = self.repo.actualizar(int(m.group(1)), datos.get("titulo"), datos.get("texto"))
        except ValueError as e:
            return self._responder(400, {"error": str(e)})
        return self._responder(200, nota) if nota else self._responder(404, {"error": "no existe"})

    def do_DELETE(self):
        m = _RUTA_NOTA.match(urlparse(self.path).path)
        if not m:
            return self._responder(404, {"error": "ruta desconocida"})
        if self.repo.borrar(int(m.group(1))):
            return self._responder(204)
        return self._responder(404, {"error": "no existe"})


def crear_servidor(puerto: int = 8000, ruta_db: str = "notas.db", host: str = "127.0.0.1") -> ThreadingHTTPServer:
    manejador = type("ManejadorConfigurado", (Manejador,), {"repo": Repositorio(ruta_db)})
    return ThreadingHTTPServer((host, puerto), manejador)


def main() -> int:
    puerto = int(os.environ.get("PUERTO", "8000"))
    servidor = crear_servidor(puerto, os.environ.get("NOTAS_DB", "notas.db"))
    print(f"API de notas en http://127.0.0.1:{servidor.server_address[1]}/notas (Ctrl+C para salir)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_api.py": r'''
import json
import threading
import unittest
import urllib.error
import urllib.request

from api.db import Repositorio
from api.servidor import crear_servidor


class TestRepositorio(unittest.TestCase):
    def setUp(self):
        self.repo = Repositorio(":memory:")

    def tearDown(self):
        self.repo.cerrar()

    def test_crud(self):
        nota = self.repo.crear("Hola", "mundo")
        self.assertEqual(nota["titulo"], "Hola")
        self.assertEqual(self.repo.actualizar(nota["id"], texto="chau")["texto"], "chau")
        self.assertEqual(len(self.repo.listar("chau")), 1)
        self.assertTrue(self.repo.borrar(nota["id"]))
        self.assertIsNone(self.repo.obtener(nota["id"]))

    def test_titulo_obligatorio(self):
        with self.assertRaises(ValueError):
            self.repo.crear("  ")


class TestServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = crear_servidor(0, ":memory:")
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def pedir(self, metodo, ruta, datos=None):
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        pedido = urllib.request.Request(self.base + ruta, data=cuerpo, method=metodo,
                                        headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=5) as r:
                texto = r.read().decode()
                return r.status, json.loads(texto) if texto else None
        except urllib.error.HTTPError as e:
            texto = e.read().decode()
            return e.code, json.loads(texto) if texto else None

    def test_flujo_completo(self):
        estado, nota = self.pedir("POST", "/notas", {"titulo": "Comprar", "texto": "pan"})
        self.assertEqual(estado, 201)
        estado, lista = self.pedir("GET", "/notas")
        self.assertEqual(estado, 200)
        self.assertTrue(any(n["id"] == nota["id"] for n in lista))
        estado, editada = self.pedir("PUT", f"/notas/{nota['id']}", {"texto": "leche"})
        self.assertEqual((estado, editada["texto"]), (200, "leche"))
        self.assertEqual(self.pedir("DELETE", f"/notas/{nota['id']}")[0], 204)
        self.assertEqual(self.pedir("GET", f"/notas/{nota['id']}")[0], 404)

    def test_errores(self):
        self.assertEqual(self.pedir("POST", "/notas", {"titulo": ""})[0], 400)
        self.assertEqual(self.pedir("GET", "/otra")[0], 404)
        self.assertEqual(self.pedir("PUT", "/notas/999", {"titulo": "x"})[0], 404)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m api.servidor",
    etiquetas=("api", "rest", "servidor", "http", "sqlite", "notas", "backend", "json"),
)

# ======================================================================
# snake (curses)
# ======================================================================
registrar_plantilla(
    "snake",
    "Juego de la serpiente en la terminal con curses: motor puro testeable, velocidad creciente y récord guardado.",
    "python",
    {
        "snake/__init__.py": "",
        "snake/motor.py": r'''
"""Motor del juego: sin curses ni tiempo real, para poder testearlo."""

import random
from collections import deque
from typing import Optional

ARRIBA, ABAJO, IZQUIERDA, DERECHA = (0, -1), (0, 1), (-1, 0), (1, 0)
OPUESTA = {ARRIBA: ABAJO, ABAJO: ARRIBA, IZQUIERDA: DERECHA, DERECHA: IZQUIERDA}


class Juego:
    def __init__(self, ancho: int = 20, alto: int = 12, semilla: Optional[int] = None, paredes: bool = True):
        if ancho < 5 or alto < 5:
            raise ValueError("el tablero mínimo es 5x5")
        self.ancho, self.alto = ancho, alto
        self.paredes = paredes
        self.azar = random.Random(semilla)
        centro = (ancho // 2, alto // 2)
        self.serpiente = deque([centro, (centro[0] - 1, centro[1]), (centro[0] - 2, centro[1])])
        self.direccion = DERECHA
        self._pendiente = DERECHA
        self.puntaje = 0
        self.vivo = True
        self.comida = self._colocar_comida()

    @property
    def cabeza(self) -> tuple:
        return self.serpiente[0]

    def _colocar_comida(self) -> Optional[tuple]:
        libres = [(x, y) for x in range(self.ancho) for y in range(self.alto) if (x, y) not in self.serpiente]
        return self.azar.choice(libres) if libres else None

    def girar(self, direccion: tuple) -> None:
        """Cambia la dirección del próximo paso (no se puede dar media vuelta)."""
        if direccion in OPUESTA and direccion != OPUESTA[self.direccion]:
            self._pendiente = direccion

    def paso(self) -> bool:
        """Avanza un paso. Devuelve True si comió. Si choca, vivo pasa a False."""
        if not self.vivo:
            return False
        self.direccion = self._pendiente
        x, y = self.cabeza
        nx, ny = x + self.direccion[0], y + self.direccion[1]
        if self.paredes:
            if not (0 <= nx < self.ancho and 0 <= ny < self.alto):
                self.vivo = False
                return False
        else:
            nx, ny = nx % self.ancho, ny % self.alto
        come = (nx, ny) == self.comida
        cuerpo = list(self.serpiente) if come else list(self.serpiente)[:-1]
        if (nx, ny) in cuerpo:
            self.vivo = False
            return False
        self.serpiente.appendleft((nx, ny))
        if come:
            self.puntaje += 10
            self.comida = self._colocar_comida()
            if self.comida is None:
                self.vivo = False  # ganó: llenó el tablero
        else:
            self.serpiente.pop()
        return come

    def velocidad(self) -> float:
        """Segundos entre pasos: arranca en 0.18 y baja hasta 0.06 con el puntaje."""
        return max(0.06, 0.18 - self.puntaje / 1000)
''',
        "snake/records.py": r'''
import json
from pathlib import Path

ARCHIVO = Path.home() / ".snake_record.json"


def leer_record(ruta: Path = ARCHIVO) -> int:
    try:
        return int(json.loads(Path(ruta).read_text(encoding="utf-8")).get("record", 0))
    except (OSError, ValueError, AttributeError):
        return 0


def guardar_record(puntaje: int, ruta: Path = ARCHIVO) -> bool:
    """Guarda si supera el récord. Devuelve True si fue récord nuevo."""
    if puntaje <= leer_record(ruta):
        return False
    Path(ruta).write_text(json.dumps({"record": puntaje}), encoding="utf-8")
    return True
''',
        "snake/__main__.py": r'''
"""Jugar: python3 -m snake   (flechas o WASD, q para salir)"""

import curses
import time

from snake.motor import ABAJO, ARRIBA, DERECHA, IZQUIERDA, Juego
from snake.records import guardar_record, leer_record

TECLAS = {
    curses.KEY_UP: ARRIBA, curses.KEY_DOWN: ABAJO, curses.KEY_LEFT: IZQUIERDA, curses.KEY_RIGHT: DERECHA,
    ord("w"): ARRIBA, ord("s"): ABAJO, ord("a"): IZQUIERDA, ord("d"): DERECHA,
}


def jugar(pantalla) -> int:
    curses.curs_set(0)
    pantalla.nodelay(True)
    alto, ancho = pantalla.getmaxyx()
    juego = Juego(max(10, (ancho - 2) // 2), max(8, alto - 4))
    record = leer_record()
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
    while juego.vivo:
        tecla = pantalla.getch()
        if tecla in (ord("q"), 27):
            break
        if tecla in TECLAS:
            juego.girar(TECLAS[tecla])
        juego.paso()
        pantalla.erase()
        pantalla.addstr(0, 0, f" Puntaje: {juego.puntaje}  Récord: {record}  (q sale) "[: ancho - 1])
        for x, y in juego.serpiente:
            pantalla.addstr(y + 2, x * 2, "██", curses.color_pair(1))
        if juego.comida:
            cx, cy = juego.comida
            pantalla.addstr(cy + 2, cx * 2, "●", curses.color_pair(2))
        pantalla.refresh()
        time.sleep(juego.velocidad())
    return juego.puntaje


def main() -> None:
    puntaje = curses.wrapper(jugar)
    nuevo = guardar_record(puntaje)
    print(f"Fin del juego. Puntaje: {puntaje}" + ("  ¡RÉCORD NUEVO!" if nuevo else ""))


main()
''',
        "tests/__init__.py": "",
        "tests/test_motor.py": r'''
import tempfile
import unittest
from pathlib import Path

from snake.motor import ABAJO, ARRIBA, DERECHA, IZQUIERDA, Juego
from snake.records import guardar_record, leer_record


class TestMotor(unittest.TestCase):
    def test_avanza_a_la_derecha(self):
        j = Juego(10, 10, semilla=1)
        x, y = j.cabeza
        j.comida = (0, 0)
        j.paso()
        self.assertEqual(j.cabeza, (x + 1, y))
        self.assertEqual(len(j.serpiente), 3)

    def test_no_puede_dar_media_vuelta(self):
        j = Juego(10, 10, semilla=1)
        j.girar(IZQUIERDA)
        j.comida = (0, 0)
        j.paso()
        self.assertEqual(j.direccion, DERECHA)

    def test_comer_crece_y_suma(self):
        j = Juego(10, 10, semilla=1)
        x, y = j.cabeza
        j.comida = (x + 1, y)
        self.assertTrue(j.paso())
        self.assertEqual(len(j.serpiente), 4)
        self.assertEqual(j.puntaje, 10)
        self.assertNotIn(j.comida, j.serpiente)

    def test_choque_con_pared(self):
        j = Juego(5, 5, semilla=1)
        j.comida = (0, 0)
        for _ in range(5):
            j.paso()
        self.assertFalse(j.vivo)

    def test_sin_paredes_da_la_vuelta(self):
        j = Juego(5, 5, semilla=1, paredes=False)
        j.comida = (0, 0)
        j.girar(ARRIBA)
        for _ in range(5):
            j.paso()
        self.assertTrue(j.vivo)

    def test_choque_consigo_misma(self):
        j = Juego(10, 10, semilla=1)
        x, y = j.cabeza
        j.serpiente.extend([(x - 3, y), (x - 4, y)])
        j.comida = (0, 0)
        for d in (ABAJO, IZQUIERDA, ARRIBA):
            j.girar(d)
            j.paso()
        self.assertFalse(j.vivo)

    def test_tablero_minimo_y_velocidad(self):
        with self.assertRaises(ValueError):
            Juego(3, 3)
        j = Juego(10, 10)
        j.puntaje = 5000
        self.assertEqual(j.velocidad(), 0.06)


class TestRecords(unittest.TestCase):
    def test_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "r.json"
            self.assertEqual(leer_record(ruta), 0)
            self.assertTrue(guardar_record(30, ruta))
            self.assertFalse(guardar_record(20, ruta))
            self.assertEqual(leer_record(ruta), 30)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m snake",
    etiquetas=("juego", "snake", "serpiente", "curses", "terminal", "game"),
)

# ======================================================================
# quiz
# ======================================================================
registrar_plantilla(
    "quiz",
    "Juego de preguntas (trivia) desde un JSON: opciones mezcladas, puntaje, racha y resumen final.",
    "python",
    {
        "quiz/__init__.py": "",
        "quiz/preguntas.json": r'''
[
  {"pregunta": "¿Cuál es el planeta más grande del sistema solar?", "opciones": ["Júpiter", "Saturno", "Tierra", "Neptuno"], "correcta": 0, "categoria": "ciencia"},
  {"pregunta": "¿En qué año llegó el ser humano a la Luna?", "opciones": ["1965", "1969", "1972", "1959"], "correcta": 1, "categoria": "historia"},
  {"pregunta": "¿Qué lenguaje usa Termux para sus paquetes?", "opciones": ["apt/pkg", "brew", "choco", "pacman"], "correcta": 0, "categoria": "tecnología"},
  {"pregunta": "¿Cuántos lados tiene un hexágono?", "opciones": ["5", "6", "7", "8"], "correcta": 1, "categoria": "matemática"}
]
''',
        "quiz/motor.py": r'''
"""Lógica del quiz sin input/print."""

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Pregunta:
    pregunta: str
    opciones: list
    correcta: int
    categoria: str = "general"

    def __post_init__(self):
        if len(self.opciones) < 2:
            raise ValueError(f"la pregunta '{self.pregunta}' necesita al menos 2 opciones")
        if not 0 <= self.correcta < len(self.opciones):
            raise ValueError(f"índice correcto fuera de rango en '{self.pregunta}'")

    def mezclada(self, azar: random.Random) -> "Pregunta":
        orden = list(range(len(self.opciones)))
        azar.shuffle(orden)
        return Pregunta(self.pregunta, [self.opciones[i] for i in orden], orden.index(self.correcta), self.categoria)


def cargar_preguntas(ruta: Path) -> list[Pregunta]:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if not isinstance(datos, list) or not datos:
        raise ValueError("el archivo de preguntas debe ser una lista no vacía")
    return [Pregunta(**d) for d in datos]


@dataclass
class Partida:
    preguntas: list
    semilla: Optional[int] = None
    indice: int = 0
    aciertos: int = 0
    racha: int = 0
    mejor_racha: int = 0
    respuestas: list = field(default_factory=list)

    def __post_init__(self):
        azar = random.Random(self.semilla)
        self.preguntas = [p.mezclada(azar) for p in self.preguntas]
        azar.shuffle(self.preguntas)

    @property
    def terminada(self) -> bool:
        return self.indice >= len(self.preguntas)

    def actual(self) -> Pregunta:
        if self.terminada:
            raise IndexError("la partida terminó")
        return self.preguntas[self.indice]

    def responder(self, opcion: int) -> bool:
        pregunta = self.actual()
        if not 0 <= opcion < len(pregunta.opciones):
            raise ValueError("opción inválida")
        correcta = opcion == pregunta.correcta
        self.respuestas.append((pregunta.pregunta, correcta))
        self.indice += 1
        if correcta:
            self.aciertos += 1
            self.racha += 1
            self.mejor_racha = max(self.mejor_racha, self.racha)
        else:
            self.racha = 0
        return correcta

    def porcentaje(self) -> float:
        return round(100 * self.aciertos / len(self.respuestas), 1) if self.respuestas else 0.0
''',
        "quiz/__main__.py": r'''
"""Jugar: python3 -m quiz"""

from pathlib import Path

from quiz.motor import Partida, cargar_preguntas


def main() -> None:
    partida = Partida(cargar_preguntas(Path(__file__).with_name("preguntas.json")))
    while not partida.terminada:
        p = partida.actual()
        print(f"\n[{p.categoria}] {p.pregunta}")
        for i, opcion in enumerate(p.opciones, start=1):
            print(f"  {i}. {opcion}")
        respuesta = input("> ").strip()
        if not respuesta.isdigit() or not 1 <= int(respuesta) <= len(p.opciones):
            print("Respondé con el número de la opción.")
            continue
        if partida.responder(int(respuesta) - 1):
            print("¡Correcto!")
        else:
            print(f"No: era {p.opciones[p.correcta]}")
    print(f"\nAciertos: {partida.aciertos}/{len(partida.preguntas)} ({partida.porcentaje()}%)"
          f" · mejor racha: {partida.mejor_racha}")


main()
''',
        "tests/__init__.py": "",
        "tests/test_quiz.py": r'''
import json
import random
import tempfile
import unittest
from pathlib import Path

from quiz.motor import Partida, Pregunta, cargar_preguntas


def preguntas():
    return [Pregunta("2+2", ["3", "4"], 1), Pregunta("capital de Francia", ["París", "Roma", "Madrid"], 0)]


class TestQuiz(unittest.TestCase):
    def test_validacion(self):
        with self.assertRaises(ValueError):
            Pregunta("x", ["solo una"], 0)
        with self.assertRaises(ValueError):
            Pregunta("x", ["a", "b"], 5)

    def test_mezclar_conserva_la_correcta(self):
        p = Pregunta("capital", ["París", "Roma", "Madrid", "Lima"], 0).mezclada(random.Random(3))
        self.assertEqual(p.opciones[p.correcta], "París")

    def test_partida_completa(self):
        partida = Partida(preguntas(), semilla=7)
        for _ in range(2):
            p = partida.actual()
            partida.responder(p.correcta)
        self.assertTrue(partida.terminada)
        self.assertEqual((partida.aciertos, partida.mejor_racha, partida.porcentaje()), (2, 2, 100.0))
        with self.assertRaises(IndexError):
            partida.actual()

    def test_racha_se_corta(self):
        partida = Partida(preguntas(), semilla=1)
        p = partida.actual()
        partida.responder((p.correcta + 1) % len(p.opciones))
        self.assertEqual(partida.racha, 0)
        self.assertEqual(partida.porcentaje(), 0.0)

    def test_cargar(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "p.json"
            ruta.write_text(json.dumps([{"pregunta": "a", "opciones": ["x", "y"], "correcta": 1}]))
            self.assertEqual(cargar_preguntas(ruta)[0].correcta, 1)
            ruta.write_text("[]")
            with self.assertRaises(ValueError):
                cargar_preguntas(ruta)

    def test_archivo_incluido_es_valido(self):
        ruta = Path(__file__).resolve().parent.parent / "quiz" / "preguntas.json"
        self.assertGreaterEqual(len(cargar_preguntas(ruta)), 4)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m quiz",
    etiquetas=("quiz", "trivia", "preguntas", "juego", "examen"),
)

# ======================================================================
# gastos
# ======================================================================
registrar_plantilla(
    "gastos",
    "Control de gastos: montos con Decimal, categorías, resumen mensual y por categoría, importar/exportar CSV.",
    "python",
    {
        "gastos/__init__.py": "",
        "gastos/modelo.py": r'''
"""Gastos con Decimal (nunca float para dinero)."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass(frozen=True)
class Gasto:
    fecha: date
    monto: Decimal
    categoria: str
    descripcion: str = ""

    @staticmethod
    def crear(fecha: str, monto: str, categoria: str, descripcion: str = "") -> "Gasto":
        try:
            fecha_ok = date.fromisoformat(fecha.strip())
        except ValueError:
            raise ValueError(f"fecha inválida: {fecha!r} (usá AAAA-MM-DD)")
        try:
            monto_ok = Decimal(str(monto).strip().replace(",", ".")).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise ValueError(f"monto inválido: {monto!r}")
        if monto_ok <= 0:
            raise ValueError("el monto debe ser positivo")
        categoria = categoria.strip().lower()
        if not categoria:
            raise ValueError("la categoría es obligatoria")
        return Gasto(fecha_ok, monto_ok, categoria, descripcion.strip())


def total(gastos: Iterable[Gasto]) -> Decimal:
    return sum((g.monto for g in gastos), Decimal("0.00"))


def por_categoria(gastos: Iterable[Gasto]) -> dict[str, Decimal]:
    acumulado: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for g in gastos:
        acumulado[g.categoria] += g.monto
    return dict(sorted(acumulado.items(), key=lambda kv: (-kv[1], kv[0])))


def por_mes(gastos: Iterable[Gasto]) -> dict[str, Decimal]:
    acumulado: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for g in gastos:
        acumulado[g.fecha.strftime("%Y-%m")] += g.monto
    return dict(sorted(acumulado.items()))


def del_mes(gastos: Iterable[Gasto], mes: str) -> list[Gasto]:
    return [g for g in gastos if g.fecha.strftime("%Y-%m") == mes]
''',
        "gastos/csvio.py": r'''
"""Importar y exportar CSV con validación fila por fila."""

import csv
from pathlib import Path

from gastos.modelo import Gasto

COLUMNAS = ("fecha", "monto", "categoria", "descripcion")


def exportar(ruta: Path, gastos: list) -> int:
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(COLUMNAS)
        for g in gastos:
            escritor.writerow([g.fecha.isoformat(), f"{g.monto:.2f}", g.categoria, g.descripcion])
    return len(gastos)


def importar(ruta: Path) -> tuple[list, list]:
    """Devuelve (gastos válidos, errores con número de línea)."""
    gastos, errores = [], []
    with open(ruta, encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        faltan = [c for c in COLUMNAS[:3] if c not in (lector.fieldnames or [])]
        if faltan:
            return [], [f"faltan columnas: {', '.join(faltan)}"]
        for numero, fila in enumerate(lector, start=2):
            try:
                gastos.append(Gasto.crear(fila["fecha"], fila["monto"], fila["categoria"], fila.get("descripcion") or ""))
            except (ValueError, KeyError, TypeError) as e:
                errores.append(f"línea {numero}: {e}")
    return gastos, errores
''',
        "gastos/cli.py": r'''
"""Uso: python3 -m gastos.cli agregar 2026-10-01 1500 comida "super" | resumen | mes 2026-10 | exportar x.csv | importar x.csv"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from gastos.csvio import exportar, importar
from gastos.modelo import Gasto, del_mes, por_categoria, por_mes, total


def ruta_datos() -> Path:
    return Path(os.environ.get("GASTOS_ARCHIVO", Path.home() / ".gastos.json"))


def cargar() -> list:
    ruta = ruta_datos()
    if not ruta.exists():
        return []
    return [Gasto.crear(d["fecha"], d["monto"], d["categoria"], d.get("descripcion", ""))
            for d in json.loads(ruta.read_text(encoding="utf-8") or "[]")]


def guardar(gastos: list) -> None:
    datos = [{"fecha": g.fecha.isoformat(), "monto": str(g.monto), "categoria": g.categoria,
              "descripcion": g.descripcion} for g in gastos]
    ruta_datos().write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="gastos")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("agregar")
    p.add_argument("fecha")
    p.add_argument("monto")
    p.add_argument("categoria")
    p.add_argument("descripcion", nargs="?", default="")
    sub.add_parser("resumen")
    sub.add_parser("mes").add_argument("mes", help="AAAA-MM")
    sub.add_parser("exportar").add_argument("archivo")
    sub.add_parser("importar").add_argument("archivo")
    args = parser.parse_args(argv)
    gastos = cargar()
    try:
        if args.cmd == "agregar":
            gastos.append(Gasto.crear(args.fecha, args.monto, args.categoria, args.descripcion))
            guardar(gastos)
            print("gasto agregado")
        elif args.cmd == "resumen":
            for categoria, monto in por_categoria(gastos).items():
                print(f"{categoria:<15} {monto:>12.2f}")
            print(f"{'TOTAL':<15} {total(gastos):>12.2f}")
            for mes, monto in por_mes(gastos).items():
                print(f"  {mes}: {monto:.2f}")
        elif args.cmd == "mes":
            for g in del_mes(gastos, args.mes):
                print(f"{g.fecha} {g.monto:>10.2f} {g.categoria} {g.descripcion}")
        elif args.cmd == "exportar":
            print(f"{exportar(Path(args.archivo), gastos)} gastos exportados")
        elif args.cmd == "importar":
            nuevos, errores = importar(Path(args.archivo))
            gastos.extend(nuevos)
            guardar(gastos)
            print(f"{len(nuevos)} importados, {len(errores)} con error")
            for e in errores:
                print("  " + e, file=sys.stderr)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_gastos.py": r'''
import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from gastos import cli
from gastos.csvio import exportar, importar
from gastos.modelo import Gasto, del_mes, por_categoria, por_mes, total


def ejemplos():
    return [Gasto.crear("2026-10-01", "100.50", "Comida"), Gasto.crear("2026-10-15", "40", "transporte"),
            Gasto.crear("2026-11-02", "9,99", "comida", "café")]


class TestModelo(unittest.TestCase):
    def test_crear_normaliza(self):
        g = Gasto.crear(" 2026-10-01 ", "9,999", " Comida ")
        self.assertEqual((g.fecha, g.monto, g.categoria), (date(2026, 10, 1), Decimal("10.00"), "comida"))

    def test_validaciones(self):
        for args in (("10/10/2026", "1", "x"), ("2026-10-01", "abc", "x"), ("2026-10-01", "-5", "x"),
                     ("2026-10-01", "5", " ")):
            with self.assertRaises(ValueError):
                Gasto.crear(*args)

    def test_resumenes(self):
        gastos = ejemplos()
        self.assertEqual(total(gastos), Decimal("150.49"))
        self.assertEqual(list(por_categoria(gastos).items())[0], ("comida", Decimal("110.49")))
        self.assertEqual(por_mes(gastos), {"2026-10": Decimal("140.50"), "2026-11": Decimal("9.99")})
        self.assertEqual(len(del_mes(gastos, "2026-10")), 2)
        self.assertEqual(total([]), Decimal("0.00"))


class TestCSV(unittest.TestCase):
    def test_ida_y_vuelta_con_errores(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "g.csv"
            self.assertEqual(exportar(ruta, ejemplos()), 3)
            with open(ruta, "a", encoding="utf-8") as f:
                f.write("mal,xx,comida,\n")
            gastos, errores = importar(ruta)
            self.assertEqual(len(gastos), 3)
            self.assertEqual(len(errores), 1)
            self.assertIn("línea 5", errores[0])

    def test_columnas_faltantes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "g.csv"
            ruta.write_text("a,b\n1,2\n", encoding="utf-8")
            self.assertEqual(importar(ruta)[0], [])


class TestCLI(unittest.TestCase):
    def test_agregar_y_resumen(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GASTOS_ARCHIVO"] = str(Path(tmp) / "g.json")
            try:
                self.assertEqual(cli.main(["agregar", "2026-10-01", "12.5", "comida"]), 0)
                self.assertEqual(len(cli.cargar()), 1)
                self.assertEqual(cli.main(["agregar", "mal", "1", "x"]), 1)
            finally:
                del os.environ["GASTOS_ARCHIVO"]


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m gastos.cli resumen",
    etiquetas=("gastos", "dinero", "finanzas", "presupuesto", "csv", "contabilidad", "expensas"),
)

# ======================================================================
# scraper
# ======================================================================
registrar_plantilla(
    "scraper",
    "Extractor web con urllib + html.parser: título, encabezados, links absolutos y texto, con tests offline.",
    "python",
    {
        "scraper/__init__.py": "",
        "scraper/extractor.py": r'''
"""Extracción de datos de HTML sin dependencias externas."""

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


@dataclass
class Pagina:
    url: str
    titulo: str = ""
    encabezados: list = field(default_factory=list)
    links: list = field(default_factory=list)
    texto: str = ""

    def links_internos(self) -> list:
        dominio = urlparse(self.url).netloc
        return [l for l in self.links if urlparse(l).netloc == dominio]


class _Analizador(HTMLParser):
    IGNORAR = {"script", "style", "noscript", "template"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.titulo, self.encabezados, self.links, self.partes = "", [], [], []
        self._pila: list = []
        self._en_titulo = False
        self._encabezado = None

    def handle_starttag(self, tag, attrs):
        self._pila.append(tag)
        atributos = dict(attrs)
        if tag == "title":
            self._en_titulo = True
        elif tag in ("h1", "h2", "h3"):
            self._encabezado = [tag, ""]
        elif tag == "a" and atributos.get("href"):
            href = atributos["href"].strip()
            if not href.startswith(("javascript:", "mailto:", "#", "tel:")):
                absoluto = urljoin(self.base, href).split("#")[0]
                if absoluto not in self.links:
                    self.links.append(absoluto)

    def handle_endtag(self, tag):
        if tag == "title":
            self._en_titulo = False
        elif tag in ("h1", "h2", "h3") and self._encabezado:
            texto = " ".join(self._encabezado[1].split())
            if texto:
                self.encabezados.append((self._encabezado[0], texto))
            self._encabezado = None
        while self._pila and self._pila.pop() != tag:
            pass

    def handle_data(self, data):
        if any(t in self.IGNORAR for t in self._pila):
            return
        if self._en_titulo:
            self.titulo += data
        if self._encabezado is not None:
            self._encabezado[1] += data
        if data.strip():
            self.partes.append(data.strip())


def extraer(html: str, url: str = "http://localhost/") -> Pagina:
    analizador = _Analizador(url)
    analizador.feed(html or "")
    analizador.close()
    return Pagina(url, " ".join(analizador.titulo.split()), analizador.encabezados, analizador.links,
                  " ".join(analizador.partes))
''',
        "scraper/red.py": r'''
"""Descarga con límites (tamaño y tiempo) y detección de codificación."""

import urllib.request

AGENTE = "Mozilla/5.0 (Linux; Android) __Proyecto__/0.1"


def descargar(url: str, timeout: int = 15, maximo: int = 3_000_000) -> str:
    if not url.startswith(("http://", "https://")):
        raise ValueError("la URL debe empezar con http:// o https://")
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(pedido, timeout=timeout) as r:
        datos = r.read(maximo + 1)
        if len(datos) > maximo:
            raise ValueError(f"la página supera {maximo} bytes")
        codificacion = r.headers.get_content_charset() or "utf-8"
    return datos.decode(codificacion, errors="replace")
''',
        "scraper/__main__.py": r'''
"""Uso: python3 -m scraper https://ejemplo.com [--json]"""

import json
import sys
import urllib.error

from scraper.extractor import extraer
from scraper.red import descargar


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("uso: python3 -m scraper <url> [--json]", file=sys.stderr)
        return 2
    url = argv[0]
    try:
        pagina = extraer(descargar(url), url)
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if "--json" in argv:
        print(json.dumps(pagina.__dict__, ensure_ascii=False, indent=2))
    else:
        print(f"Título: {pagina.titulo}")
        for nivel, texto in pagina.encabezados[:20]:
            print(f"  {nivel}: {texto}")
        print(f"{len(pagina.links)} links ({len(pagina.links_internos())} internos)")
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_extractor.py": r'''
import unittest

from scraper.extractor import extraer
from scraper.red import descargar

HTML = """<html><head><title> Mi   sitio </title><style>.x{}</style></head>
<body><h1>Bienvenida</h1><p>Hola <b>mundo</b></p>
<a href="/a">A</a> <a href="https://otro.com/b#seccion">B</a> <a href="/a">repetido</a>
<a href="javascript:void(0)">no</a> <a href="mailto:x@y.z">mail</a>
<h2>Sección <i>dos</i></h2><script>var no = 1;</script></body></html>"""


class TestExtractor(unittest.TestCase):
    def setUp(self):
        self.pagina = extraer(HTML, "https://misitio.com/inicio")

    def test_titulo(self):
        self.assertEqual(self.pagina.titulo, "Mi sitio")

    def test_encabezados(self):
        self.assertEqual(self.pagina.encabezados, [("h1", "Bienvenida"), ("h2", "Sección dos")])

    def test_links_absolutos_sin_duplicados(self):
        self.assertEqual(self.pagina.links, ["https://misitio.com/a", "https://otro.com/b"])
        self.assertEqual(self.pagina.links_internos(), ["https://misitio.com/a"])

    def test_texto_sin_scripts(self):
        self.assertIn("Hola mundo", self.pagina.texto.replace("Hola mundo", "Hola mundo"))
        self.assertNotIn("var no", self.pagina.texto)

    def test_html_vacio(self):
        self.assertEqual(extraer("").titulo, "")

    def test_url_invalida(self):
        with self.assertRaises(ValueError):
            descargar("ftp://algo")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m scraper https://example.com",
    etiquetas=("scraper", "web", "html", "extraer", "links", "descargar", "crawler"),
)

# ======================================================================
# bot-telegram
# ======================================================================
registrar_plantilla(
    "bot-telegram",
    "Bot de Telegram con urllib (sin librerías): long polling con reintentos, router de comandos y tests sin red.",
    "python",
    {
        "bot/__init__.py": "",
        "bot/telegram.py": r'''
"""Cliente mínimo de la Bot API de Telegram. El transporte es inyectable para testear sin red."""

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

Transporte = Callable[[str, dict, int], dict]


def transporte_urllib(url: str, datos: dict, timeout: int) -> dict:
    cuerpo = json.dumps(datos).encode("utf-8")
    pedido = urllib.request.Request(url, data=cuerpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class ErrorTelegram(RuntimeError):
    pass


class ClienteTelegram:
    def __init__(self, token: str, transporte: Optional[Transporte] = None, base: str = "https://api.telegram.org"):
        if not token or ":" not in token:
            raise ValueError("token de bot inválido (pedilo a @BotFather)")
        self.url = f"{base}/bot{token}"
        self.transporte = transporte or transporte_urllib

    def _llamar(self, metodo: str, datos: dict, timeout: int = 35) -> dict:
        respuesta = self.transporte(f"{self.url}/{metodo}", datos, timeout)
        if not respuesta.get("ok"):
            raise ErrorTelegram(respuesta.get("description", "error desconocido"))
        return respuesta.get("result")

    def actualizaciones(self, offset: int = 0, espera: int = 30) -> list:
        return self._llamar("getUpdates", {"offset": offset, "timeout": espera}, timeout=espera + 5) or []

    def enviar(self, chat_id: int, texto: str) -> dict:
        return self._llamar("sendMessage", {"chat_id": chat_id, "text": texto[:4096]})
''',
        "bot/comandos.py": r'''
"""Router de comandos: @router.comando("/start") def ...(argumentos, mensaje) -> str"""

import random
from typing import Callable, Optional


class Router:
    def __init__(self):
        self._comandos: dict[str, Callable] = {}
        self._defecto: Optional[Callable] = None

    def comando(self, nombre: str, descripcion: str = ""):
        def decorador(funcion: Callable) -> Callable:
            funcion.descripcion = descripcion
            self._comandos[nombre.lower()] = funcion
            return funcion
        return decorador

    def texto_libre(self, funcion: Callable) -> Callable:
        self._defecto = funcion
        return funcion

    def ayuda(self) -> str:
        return "\n".join(f"{n} — {getattr(f, 'descripcion', '')}" for n, f in sorted(self._comandos.items()))

    def manejar(self, mensaje: dict) -> Optional[str]:
        texto = (mensaje.get("text") or "").strip()
        if not texto:
            return None
        if texto.startswith("/"):
            nombre, _, argumentos = texto.partition(" ")
            nombre = nombre.split("@")[0].lower()
            funcion = self._comandos.get(nombre)
            if funcion is None:
                return f"No conozco {nombre}. Probá /ayuda"
            return funcion(argumentos.strip(), mensaje)
        return self._defecto(texto, mensaje) if self._defecto else None


router = Router()


@router.comando("/start", "presentación")
def start(argumentos: str, mensaje: dict) -> str:
    nombre = mensaje.get("from", {}).get("first_name", "")
    return f"¡Hola {nombre}! Soy __TITULO__. Escribí /ayuda para ver lo que sé hacer."


@router.comando("/ayuda", "lista de comandos")
def ayuda(argumentos: str, mensaje: dict) -> str:
    return router.ayuda()


@router.comando("/eco", "repite el texto")
def eco(argumentos: str, mensaje: dict) -> str:
    return argumentos or "Decime algo después de /eco"


@router.comando("/dado", "tira un dado (o /dado 20)")
def dado(argumentos: str, mensaje: dict) -> str:
    caras = int(argumentos) if argumentos.isdigit() and int(argumentos) > 1 else 6
    return f"🎲 {random.randint(1, caras)} (d{caras})"


@router.texto_libre
def charla(texto: str, mensaje: dict) -> str:
    return f"Recibí: {texto}"
''',
        "bot/__main__.py": r'''
"""Correr: export TELEGRAM_TOKEN=123:abc ; python3 -m bot"""

import os
import sys
import time
import urllib.error

from bot.comandos import router
from bot.telegram import ClienteTelegram, ErrorTelegram


def bucle(cliente: ClienteTelegram, una_vez: bool = False) -> None:
    offset, espera_error = 0, 1
    while True:
        try:
            for update in cliente.actualizaciones(offset):
                offset = update["update_id"] + 1
                mensaje = update.get("message") or update.get("edited_message")
                if not mensaje:
                    continue
                respuesta = router.manejar(mensaje)
                if respuesta:
                    cliente.enviar(mensaje["chat"]["id"], respuesta)
            espera_error = 1
        except (urllib.error.URLError, TimeoutError, ErrorTelegram) as e:
            print(f"error de red/API: {e}; reintento en {espera_error}s", file=sys.stderr)
            time.sleep(espera_error)
            espera_error = min(60, espera_error * 2)
        if una_vez:
            return


def main() -> int:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    try:
        cliente = ClienteTelegram(token)
    except ValueError as e:
        print(f"{e}. export TELEGRAM_TOKEN=...", file=sys.stderr)
        return 1
    print("Bot corriendo (Ctrl+C para salir)")
    try:
        bucle(cliente)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_bot.py": r'''
import unittest

from bot.comandos import Router, router
from bot.telegram import ClienteTelegram, ErrorTelegram


class FalsoTransporte:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.pedidos = []

    def __call__(self, url, datos, timeout):
        self.pedidos.append((url, datos))
        return self.respuestas.pop(0)


class TestRouter(unittest.TestCase):
    def test_comandos_incluidos(self):
        self.assertIn("Hola Ana", router.manejar({"text": "/start", "from": {"first_name": "Ana"}}))
        self.assertEqual(router.manejar({"text": "/eco hola mundo"}), "hola mundo")
        self.assertIn("/dado", router.manejar({"text": "/ayuda"}))
        self.assertIn("No conozco", router.manejar({"text": "/nada"}))
        self.assertEqual(router.manejar({"text": "/ECO@mi_bot x"}), "x")
        self.assertIsNone(router.manejar({}))

    def test_dado_en_rango(self):
        for _ in range(20):
            valor = int(router.manejar({"text": "/dado 4"}).split()[1])
            self.assertTrue(1 <= valor <= 4)

    def test_router_nuevo(self):
        r = Router()

        @r.comando("/hola", "saluda")
        def hola(args, msg):
            return "hola!"

        self.assertEqual(r.manejar({"text": "/hola"}), "hola!")
        self.assertIsNone(r.manejar({"text": "texto suelto"}))


class TestCliente(unittest.TestCase):
    def test_token_invalido(self):
        with self.assertRaises(ValueError):
            ClienteTelegram("sin-dos-puntos")

    def test_enviar_y_actualizaciones(self):
        t = FalsoTransporte([{"ok": True, "result": [{"update_id": 5}]}, {"ok": True, "result": {"message_id": 1}}])
        c = ClienteTelegram("1:abc", transporte=t)
        self.assertEqual(c.actualizaciones(3)[0]["update_id"], 5)
        c.enviar(10, "hola")
        self.assertTrue(t.pedidos[1][0].endswith("/sendMessage"))
        self.assertEqual(t.pedidos[1][1]["chat_id"], 10)

    def test_error_de_api(self):
        c = ClienteTelegram("1:abc", transporte=FalsoTransporte([{"ok": False, "description": "Unauthorized"}]))
        with self.assertRaises(ErrorTelegram):
            c.enviar(1, "x")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="TELEGRAM_TOKEN=... python3 -m bot",
    etiquetas=("bot", "telegram", "chat", "mensajes", "api"),
)

# ======================================================================
# organizador
# ======================================================================
registrar_plantilla(
    "organizador",
    "Organizador de archivos por tipo o por fecha, con modo simulación, nombres sin pisarse y reporte.",
    "python",
    {
        "organizador/__init__.py": "",
        "organizador/reglas.py": r'''
CATEGORIAS = {
    "Imagenes": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".3gp"},
    "Audio": {".mp3", ".ogg", ".wav", ".m4a", ".flac", ".opus", ".aac"},
    "Documentos": {".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".epub"},
    "Comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2"},
    "Codigo": {".py", ".js", ".html", ".css", ".json", ".sh", ".java", ".c", ".cpp", ".go", ".rs"},
    "Apps": {".apk", ".xapk", ".aab"},
}


def categoria(nombre: str) -> str:
    sufijo = "." + nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    for cat, extensiones in CATEGORIAS.items():
        if sufijo in extensiones:
            return cat
    return "Otros"
''',
        "organizador/mover.py": r'''
"""Planifica y ejecuta movimientos. La planificación no toca el disco."""

import shutil
from datetime import datetime
from pathlib import Path

from organizador.reglas import CATEGORIAS, categoria


def destino_sin_choque(ruta: Path, reservados: set) -> Path:
    candidato, n = ruta, 1
    while candidato.exists() or candidato in reservados:
        candidato = ruta.with_name(f"{ruta.stem} ({n}){ruta.suffix}")
        n += 1
    return candidato


def planificar(carpeta: Path, por: str = "tipo") -> list:
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        raise NotADirectoryError(str(carpeta))
    if por not in ("tipo", "fecha"):
        raise ValueError("por debe ser 'tipo' o 'fecha'")
    propias = set(CATEGORIAS) | {"Otros"}
    plan, reservados = [], set()
    for archivo in sorted(carpeta.iterdir()):
        if not archivo.is_file() or archivo.name.startswith("."):
            continue
        if por == "tipo":
            subcarpeta = categoria(archivo.name)
        else:
            subcarpeta = datetime.fromtimestamp(archivo.stat().st_mtime).strftime("%Y-%m")
        if archivo.parent.name in propias:
            continue
        destino = destino_sin_choque(carpeta / subcarpeta / archivo.name, reservados)
        reservados.add(destino)
        plan.append((archivo, destino))
    return plan


def ejecutar(plan: list, simular: bool = True) -> list:
    hechos = []
    for origen, destino in plan:
        if not simular:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(destino))
        hechos.append(f"{origen.name} → {destino.parent.name}/{destino.name}")
    return hechos
''',
        "organizador/__main__.py": r'''
"""Uso: python3 -m organizador ~/storage/downloads [--por fecha] [--aplicar]"""

import sys
from pathlib import Path

from organizador.mover import ejecutar, planificar


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("uso: python3 -m organizador <carpeta> [--por tipo|fecha] [--aplicar]", file=sys.stderr)
        return 2
    por = argv[argv.index("--por") + 1] if "--por" in argv else "tipo"
    aplicar = "--aplicar" in argv
    try:
        plan = planificar(Path(argv[0]).expanduser(), por)
    except (NotADirectoryError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for linea in ejecutar(plan, simular=not aplicar):
        print(linea)
    print(f"\n{len(plan)} archivo(s) {'movidos' if aplicar else 'a mover (simulación: agregá --aplicar)'}")
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_organizador.py": r'''
import tempfile
import unittest
from pathlib import Path

from organizador.mover import ejecutar, planificar
from organizador.reglas import categoria


class TestOrganizador(unittest.TestCase):
    def test_categorias(self):
        self.assertEqual(categoria("foto.JPG"), "Imagenes")
        self.assertEqual(categoria("app.apk"), "Apps")
        self.assertEqual(categoria("sin_extension"), "Otros")

    def test_simular_no_mueve(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a.png").write_text("x")
            plan = planificar(base)
            self.assertEqual(ejecutar(plan, simular=True), ["a.png → Imagenes/a.png"])
            self.assertTrue((base / "a.png").exists())

    def test_aplicar_y_choques(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "Imagenes").mkdir()
            (base / "Imagenes" / "a.png").write_text("viejo")
            (base / "a.png").write_text("nuevo")
            (base / "doc.pdf").write_text("pdf")
            (base / ".oculto").write_text("no")
            ejecutar(planificar(base), simular=False)
            self.assertTrue((base / "Imagenes" / "a (1).png").exists())
            self.assertTrue((base / "Documentos" / "doc.pdf").exists())
            self.assertTrue((base / ".oculto").exists())

    def test_por_fecha_y_errores(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "x.txt").write_text("x")
            plan = planificar(base, por="fecha")
            self.assertRegex(plan[0][1].parent.name, r"^\d{4}-\d{2}$")
            with self.assertRaises(ValueError):
                planificar(base, por="color")
            with self.assertRaises(NotADirectoryError):
                planificar(base / "no")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m organizador ~/storage/downloads",
    etiquetas=("organizar", "archivos", "carpetas", "descargas", "ordenar", "fotos"),
)

# ======================================================================
# respaldo (backup zip con rotación)
# ======================================================================
registrar_plantilla(
    "respaldo",
    "Respaldos en ZIP con fecha, exclusiones tipo .gitignore, rotación (conservar N) y restauración segura.",
    "python",
    {
        "respaldo/__init__.py": "",
        "respaldo/nucleo.py": r'''
import fnmatch
import zipfile
from datetime import datetime
from pathlib import Path

EXCLUIR_DEFECTO = ("__pycache__", "*.pyc", ".git", "node_modules", ".venv", "*.tmp")


def _excluido(rel: str, patrones) -> bool:
    partes = rel.split("/")
    return any(fnmatch.fnmatch(p, patron) for patron in patrones for p in partes) or \
        any(fnmatch.fnmatch(rel, patron) for patron in patrones)


def crear_respaldo(origen: Path, destino: Path, excluir=EXCLUIR_DEFECTO, ahora: datetime = None) -> Path:
    origen, destino = Path(origen), Path(destino)
    if not origen.is_dir():
        raise NotADirectoryError(str(origen))
    destino.mkdir(parents=True, exist_ok=True)
    marca = (ahora or datetime.now()).strftime("%Y%m%d_%H%M%S")
    archivo = destino / f"{origen.name}_{marca}.zip"
    with zipfile.ZipFile(archivo, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ruta in sorted(origen.rglob("*")):
            rel = ruta.relative_to(origen).as_posix()
            if ruta.is_file() and not _excluido(rel, excluir) and destino not in ruta.parents:
                zf.write(ruta, rel)
    return archivo


def listar(destino: Path, nombre: str) -> list:
    return sorted(Path(destino).glob(f"{nombre}_*.zip"))


def rotar(destino: Path, nombre: str, conservar: int = 5) -> list:
    if conservar < 1:
        raise ValueError("hay que conservar al menos 1 respaldo")
    viejos = listar(destino, nombre)[:-conservar]
    for archivo in viejos:
        archivo.unlink()
    return viejos


def restaurar(archivo: Path, destino: Path) -> int:
    destino = Path(destino).resolve()
    with zipfile.ZipFile(archivo) as zf:
        for miembro in zf.namelist():
            final = (destino / miembro).resolve()
            if destino not in final.parents and final != destino:
                raise ValueError(f"ruta peligrosa en el zip: {miembro}")
        zf.extractall(destino)
        return len(zf.namelist())
''',
        "respaldo/__main__.py": r'''
"""Uso: python3 -m respaldo <carpeta> [--destino ~/respaldos] [--conservar 5]"""

import sys
from pathlib import Path

from respaldo.nucleo import crear_respaldo, rotar


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("uso: python3 -m respaldo <carpeta> [--destino DIR] [--conservar N]", file=sys.stderr)
        return 2
    origen = Path(argv[0]).expanduser()
    destino = Path(argv[argv.index("--destino") + 1]).expanduser() if "--destino" in argv else Path.home() / "respaldos"
    conservar = int(argv[argv.index("--conservar") + 1]) if "--conservar" in argv else 5
    try:
        archivo = crear_respaldo(origen, destino)
        borrados = rotar(destino, origen.name, conservar)
    except (NotADirectoryError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"respaldo: {archivo} ({archivo.stat().st_size // 1024} KB); rotados: {len(borrados)}")
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_respaldo.py": r'''
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from respaldo.nucleo import crear_respaldo, listar, restaurar, rotar


class TestRespaldo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.origen = self.base / "proyecto"
        (self.origen / "sub").mkdir(parents=True)
        (self.origen / "a.txt").write_text("A")
        (self.origen / "sub" / "b.txt").write_text("B")
        (self.origen / "__pycache__").mkdir()
        (self.origen / "__pycache__" / "x.pyc").write_text("no")

    def tearDown(self):
        self.tmp.cleanup()

    def test_crear_excluye(self):
        zipf = crear_respaldo(self.origen, self.base / "resp")
        with zipfile.ZipFile(zipf) as zf:
            self.assertEqual(sorted(zf.namelist()), ["a.txt", "sub/b.txt"])

    def test_rotar(self):
        destino = self.base / "resp"
        for minuto in range(4):
            crear_respaldo(self.origen, destino, ahora=datetime(2026, 1, 1, 10, minuto))
        borrados = rotar(destino, "proyecto", conservar=2)
        self.assertEqual(len(borrados), 2)
        self.assertEqual(len(listar(destino, "proyecto")), 2)
        with self.assertRaises(ValueError):
            rotar(destino, "proyecto", 0)

    def test_restaurar_y_ruta_peligrosa(self):
        zipf = crear_respaldo(self.origen, self.base / "resp")
        self.assertEqual(restaurar(zipf, self.base / "restaurado"), 2)
        self.assertEqual((self.base / "restaurado" / "sub" / "b.txt").read_text(), "B")
        malo = self.base / "malo.zip"
        with zipfile.ZipFile(malo, "w") as zf:
            zf.writestr("../fuera.txt", "x")
        with self.assertRaises(ValueError):
            restaurar(malo, self.base / "r2")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m respaldo ~/mi_proyecto",
    etiquetas=("backup", "respaldo", "zip", "copia", "seguridad"),
)

# ======================================================================
# chat-asyncio
# ======================================================================
registrar_plantilla(
    "chat",
    "Chat por TCP con asyncio: sala con apodos (/nick, /quien), avisos de entrada/salida, cliente y tests reales.",
    "python",
    {
        "chat/__init__.py": "",
        "chat/servidor.py": r'''
"""Servidor de chat línea por línea. Comandos: /nick nombre, /quien, /salir"""

import asyncio
import itertools
import sys


class Sala:
    def __init__(self):
        self.clientes: dict = {}  # writer → apodo
        self._numeros = itertools.count(1)

    async def difundir(self, texto: str, excepto=None) -> None:
        for writer in list(self.clientes):
            if writer is excepto:
                continue
            try:
                writer.write((texto + "\n").encode("utf-8"))
                await writer.drain()
            except (ConnectionError, RuntimeError):
                self.clientes.pop(writer, None)

    async def atender(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        apodo = f"invitado{next(self._numeros)}"
        self.clientes[writer] = apodo
        writer.write(f"* bienvenido, sos {apodo}. /nick nombre para cambiarlo\n".encode())
        await writer.drain()
        await self.difundir(f"* {apodo} entró", excepto=writer)
        try:
            while True:
                linea = await reader.readline()
                if not linea:
                    break
                texto = linea.decode("utf-8", "replace").strip()
                if not texto:
                    continue
                if texto == "/salir":
                    break
                if texto.startswith("/nick "):
                    nuevo = texto[6:].strip()[:20]
                    if not nuevo or nuevo in self.clientes.values():
                        writer.write(b"* apodo invalido o en uso\n")
                        await writer.drain()
                        continue
                    viejo, self.clientes[writer] = self.clientes[writer], nuevo
                    await self.difundir(f"* {viejo} ahora es {nuevo}")
                elif texto == "/quien":
                    writer.write(("* conectados: " + ", ".join(sorted(self.clientes.values())) + "\n").encode())
                    await writer.drain()
                else:
                    await self.difundir(f"<{self.clientes[writer]}> {texto}", excepto=writer)
        finally:
            nombre = self.clientes.pop(writer, apodo)
            await self.difundir(f"* {nombre} salió")
            writer.close()


async def iniciar(host: str = "127.0.0.1", puerto: int = 7777):
    sala = Sala()
    servidor = await asyncio.start_server(sala.atender, host, puerto)
    return servidor, sala


async def principal(puerto: int) -> None:
    servidor, _ = await iniciar(puerto=puerto)
    print(f"chat en 127.0.0.1:{servidor.sockets[0].getsockname()[1]} (Ctrl+C para salir)")
    async with servidor:
        await servidor.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(principal(int(sys.argv[1]) if len(sys.argv) > 1 else 7777))
    except KeyboardInterrupt:
        pass
''',
        "chat/cliente.py": r'''
"""Cliente: python3 -m chat.cliente [host] [puerto]"""

import asyncio
import sys


async def recibir(reader: asyncio.StreamReader) -> None:
    while True:
        linea = await reader.readline()
        if not linea:
            print("* conexión cerrada")
            return
        print(linea.decode("utf-8", "replace"), end="")


async def principal(host: str, puerto: int) -> None:
    reader, writer = await asyncio.open_connection(host, puerto)
    tarea = asyncio.create_task(recibir(reader))
    loop = asyncio.get_running_loop()
    try:
        while not tarea.done():
            linea = await loop.run_in_executor(None, sys.stdin.readline)
            if not linea:
                break
            writer.write(linea.encode("utf-8"))
            await writer.drain()
            if linea.strip() == "/salir":
                break
    finally:
        writer.close()
        tarea.cancel()


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(principal(args[0] if args else "127.0.0.1", int(args[1]) if len(args) > 1 else 7777))
''',
        "tests/__init__.py": "",
        "tests/test_chat.py": r'''
import asyncio
import unittest

from chat.servidor import iniciar


async def leer(reader, timeout=2):
    return (await asyncio.wait_for(reader.readline(), timeout)).decode().strip()


class TestChat(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.servidor, self.sala = await iniciar(puerto=0)
        self.puerto = self.servidor.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.servidor.close()
        await self.servidor.wait_closed()

    async def conectar(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.puerto)
        bienvenida = await leer(reader)
        return reader, writer, bienvenida

    async def test_difusion_y_nick(self):
        r1, w1, b1 = await self.conectar()
        self.assertIn("bienvenido", b1)
        r2, w2, _ = await self.conectar()
        self.assertIn("entró", await leer(r1))
        w1.write(b"/nick ana\n")
        await w1.drain()
        self.assertIn("ahora es ana", await leer(r2))
        self.assertIn("ahora es ana", await leer(r1))
        w1.write(b"hola\n")
        await w1.drain()
        self.assertEqual(await leer(r2), "<ana> hola")
        w2.write(b"/quien\n")
        await w2.drain()
        self.assertIn("ana", await leer(r2))
        w2.write(b"/salir\n")
        await w2.drain()
        self.assertIn("salió", await leer(r1))
        w1.close()
        w2.close()

    async def test_nick_repetido(self):
        r1, w1, _ = await self.conectar()
        r2, w2, _ = await self.conectar()
        await leer(r1)
        w1.write(b"/nick x\n")
        await w1.drain()
        await leer(r1)
        await leer(r2)
        w2.write(b"/nick x\n")
        await w2.drain()
        self.assertIn("invalido", await leer(r2))
        w1.close()
        w2.close()


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m chat.servidor  (y en otra sesión: python3 -m chat.cliente)",
    etiquetas=("chat", "asyncio", "socket", "tcp", "red", "servidor", "mensajes"),
)
