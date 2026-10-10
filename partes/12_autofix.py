"""
Arreglos automáticos sin gastar llamadas al modelo.

Después de cada edición, REAPER corrige solo lo trivial y seguro:
  - espacios al final de línea y salto de línea final
  - tabs mezclados con espacios en Python (TabError)
  - comillas tipográficas / guiones Unicode que rompen la sintaxis
  - imports de la librería estándar que faltan (os, re, json, Path, dataclass, Optional...)
  - comas finales en JSON
  - `ruff check --fix` con reglas seguras (si ruff está instalado)
  - chmod +x a scripts con shebang

Cada arreglo se aplica solo si deja el archivo compilando (o igual de bien
que antes) y se informa al agente qué se cambió.
"""

MODULOS_STDLIB_COMUNES = {
    "os", "re", "sys", "json", "math", "random", "time", "subprocess", "shutil", "itertools",
    "functools", "hashlib", "base64", "uuid", "logging", "argparse", "csv", "sqlite3", "threading",
    "asyncio", "textwrap", "string", "tempfile", "glob", "io", "copy", "heapq", "bisect",
    "statistics", "decimal", "fractions", "socket", "struct", "zlib", "gzip", "zipfile", "tarfile",
    "unittest", "inspect", "traceback", "platform", "signal", "getpass", "secrets", "operator",
    "enum", "abc", "dataclasses", "contextlib", "pprint", "queue", "calendar", "locale",
    "unicodedata", "difflib", "fnmatch", "shlex", "configparser", "pickle", "weakref", "types",
    "warnings", "collections", "typing", "pathlib", "codecs", "html", "http", "urllib", "email",
    "xml", "concurrent", "multiprocessing", "select", "ssl", "datetime", "builtins", "gc", "atexit",
    "array", "binascii", "colorsys", "keyword", "numbers", "timeit", "cmath", "mimetypes", "ipaddress",
}

NOMBRES_STDLIB = {
    "Path": "from pathlib import Path",
    "PurePath": "from pathlib import PurePath",
    "dataclass": "from dataclasses import dataclass",
    "field": "from dataclasses import field",
    "asdict": "from dataclasses import asdict",
    "astuple": "from dataclasses import astuple",
    "Optional": "from typing import Optional",
    "List": "from typing import List",
    "Dict": "from typing import Dict",
    "Tuple": "from typing import Tuple",
    "Set": "from typing import Set",
    "Any": "from typing import Any",
    "Union": "from typing import Union",
    "Callable": "from typing import Callable",
    "Iterable": "from typing import Iterable",
    "Iterator": "from typing import Iterator",
    "Sequence": "from typing import Sequence",
    "Mapping": "from typing import Mapping",
    "TypeVar": "from typing import TypeVar",
    "Generic": "from typing import Generic",
    "NamedTuple": "from typing import NamedTuple",
    "TypedDict": "from typing import TypedDict",
    "Literal": "from typing import Literal",
    "defaultdict": "from collections import defaultdict",
    "Counter": "from collections import Counter",
    "deque": "from collections import deque",
    "namedtuple": "from collections import namedtuple",
    "OrderedDict": "from collections import OrderedDict",
    "Enum": "from enum import Enum",
    "IntEnum": "from enum import IntEnum",
    "auto": "from enum import auto",
    "ABC": "from abc import ABC",
    "abstractmethod": "from abc import abstractmethod",
    "partial": "from functools import partial",
    "lru_cache": "from functools import lru_cache",
    "wraps": "from functools import wraps",
    "reduce": "from functools import reduce",
    "cached_property": "from functools import cached_property",
    "contextmanager": "from contextlib import contextmanager",
    "suppress": "from contextlib import suppress",
    "timedelta": "from datetime import timedelta",
    "timezone": "from datetime import timezone",
    "date": "from datetime import date",
    "uuid4": "from uuid import uuid4",
    "deepcopy": "from copy import deepcopy",
    "dedent": "from textwrap import dedent",
    "Decimal": "from decimal import Decimal",
    "Fraction": "from fractions import Fraction",
    "ThreadPoolExecutor": "from concurrent.futures import ThreadPoolExecutor",
    "sleep": None,  # ambiguo (time.sleep / asyncio.sleep): no se agrega solo
}

_TIPOGRAFICOS = {"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'", "–": "-", "—": "-",
                 "\u00a0": " ", "\u200b": "", "\ufeff": ""}

REGLAS_RUFF_SEGURAS = "W291,W292,W293,F541,E703,E711"


@dataclass
class ReporteAutofix:
    rel: str
    cambios: list = field(default_factory=list)
    contenido: Optional[str] = None

    @property
    def cambio(self) -> bool:
        return bool(self.cambios)

    def texto(self) -> str:
        return "; ".join(self.cambios)


def _compila(texto: str) -> bool:
    try:
        compile(texto, "<autofix>", "exec", dont_inherit=True)
        return True
    except (SyntaxError, ValueError):
        return False


def quitar_espacios_finales(texto: str, markdown: bool = False) -> str:
    lineas = texto.split("\n")
    if markdown:
        # En Markdown dos espacios al final son un salto de línea: solo se quitan tabs y espacios sueltos.
        salida = [l.rstrip("\t") if not l.endswith("  ") else l.rstrip(" \t") + "  " for l in lineas]
    else:
        salida = [l.rstrip(" \t") for l in lineas]
    return "\n".join(salida)


def asegurar_salto_final(texto: str) -> str:
    if not texto:
        return texto
    texto = texto.rstrip("\n") + "\n"
    return texto


def arreglar_tabs_python(texto: str) -> Optional[str]:
    """Convierte la indentación con tabs a 4 espacios si eso hace compilar el archivo."""
    if "\t" not in texto or _compila(texto):
        return None
    salida = []
    for linea in texto.split("\n"):
        cuerpo = linea.lstrip(" \t")
        indent = linea[: len(linea) - len(cuerpo)]
        salida.append(indent.expandtabs(4) + cuerpo)
    nuevo = "\n".join(salida)
    return nuevo if _compila(nuevo) else None


def arreglar_tipograficos(texto: str, es_python: bool = True) -> Optional[str]:
    """Reemplaza comillas tipográficas fuera de strings cuando rompen la sintaxis."""
    if not any(ch in texto for ch in _TIPOGRAFICOS):
        return None
    if es_python and _compila(texto):
        return None
    nuevo = texto
    for malo, bueno in _TIPOGRAFICOS.items():
        nuevo = nuevo.replace(malo, bueno)
    if es_python and not _compila(nuevo):
        return None
    return nuevo


def _linea_insercion_imports(arbol: ast.Module, texto: str) -> int:
    """Número de línea (0-indexado) donde insertar un import nuevo."""
    ultima = 0
    cuerpo = arbol.body
    k = 0
    if cuerpo and isinstance(cuerpo[0], ast.Expr) and isinstance(getattr(cuerpo[0], "value", None), ast.Constant) \
            and isinstance(cuerpo[0].value.value, str):
        ultima = cuerpo[0].end_lineno or cuerpo[0].lineno
        k = 1
    while k < len(cuerpo) and isinstance(cuerpo[k], (ast.Import, ast.ImportFrom)):
        ultima = cuerpo[k].end_lineno or cuerpo[k].lineno
        k += 1
    if ultima == 0:
        lineas = texto.split("\n")
        while ultima < len(lineas) and lineas[ultima].startswith("#"):
            ultima += 1
    return ultima


def _usos_como_modulo(arbol: ast.AST, nombre: str) -> tuple[bool, set[str]]:
    """(se usa como nombre.attr, atributos usados)."""
    atributos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name) and nodo.value.id == nombre:
            atributos.add(nodo.attr)
    return bool(atributos), atributos


def imports_stdlib_faltantes(texto: str) -> list[str]:
    """Sentencias import de la stdlib que faltan para nombres usados y no definidos."""
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return []
    indefinidos = {n for n, _ in nombres_indefinidos_python(texto)}
    sentencias: list[str] = []
    for nombre in sorted(indefinidos):
        if nombre == "datetime":
            como_modulo, atributos = _usos_como_modulo(arbol, nombre)
            if atributos & {"datetime", "date", "timedelta", "timezone", "time", "MINYEAR", "MAXYEAR"}:
                sentencias.append("import datetime")
            else:
                sentencias.append("from datetime import datetime")
            continue
        if nombre == "urllib":
            _, atributos = _usos_como_modulo(arbol, nombre)
            for sub in sorted(atributos & {"request", "parse", "error"}):
                sentencias.append(f"import urllib.{sub}")
            continue
        if nombre in ("concurrent", "xml", "email", "http"):
            continue  # necesitan el submódulo exacto; mejor que lo decida el modelo
        if nombre in MODULOS_STDLIB_COMUNES:
            como_modulo, _ = _usos_como_modulo(arbol, nombre)
            if como_modulo:
                sentencias.append(f"import {nombre}")
            continue
        sentencia = NOMBRES_STDLIB.get(nombre)
        if sentencia:
            sentencias.append(sentencia)
    return sentencias


def agregar_imports(texto: str, sentencias: Sequence[str]) -> Optional[str]:
    if not sentencias:
        return None
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return None
    linea = _linea_insercion_imports(arbol, texto)
    lineas = texto.split("\n")
    nuevas = [s for s in sentencias if s not in lineas]
    if not nuevas:
        return None
    resultado = "\n".join(lineas[:linea] + list(nuevas) + lineas[linea:])
    if linea == 0 and lineas and lineas[0].strip():
        resultado = "\n".join(list(nuevas) + [""] + lineas)
    return resultado if _compila(resultado) else None


def quitar_comas_finales_json(texto: str) -> Optional[str]:
    try:
        json.loads(texto)
        return None
    except ValueError:
        pass
    salida = []
    i, n = 0, len(texto)
    en_string = False
    while i < n:
        ch = texto[i]
        if en_string:
            salida.append(ch)
            if ch == "\\" and i + 1 < n:
                salida.append(texto[i + 1])
                i += 2
                continue
            if ch == '"':
                en_string = False
            i += 1
            continue
        if ch == '"':
            en_string = True
            salida.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and texto[j] in " \t\r\n":
                j += 1
            if j < n and texto[j] in "}]":
                i += 1
                continue
        salida.append(ch)
        i += 1
    nuevo = "".join(salida)
    try:
        json.loads(nuevo)
        return nuevo
    except ValueError:
        return None


def _ruff_fix(ws: Workspace, rel: str) -> bool:
    ruff = shutil.which("ruff")
    if not ruff:
        return False
    antes = ws.hash(rel)
    ejecutar([ruff, "check", "--fix", "--isolated", "--no-cache", "--select", REGLAS_RUFF_SEGURAS,
              "--quiet", rel], cwd=ws.raiz, timeout=30)
    return ws.hash(rel) != antes


def autoarreglar_texto(rel: str, texto: str) -> ReporteAutofix:
    """Arreglos puros sobre el texto (sin tocar disco). Útil también en tests."""
    reporte = ReporteAutofix(rel)
    sufijo = Path(rel).suffix.lower()
    nombre = Path(rel).name
    actual = texto

    if sufijo not in (".md", ".markdown", ".diff", ".patch") and nombre != "Makefile":
        limpio = quitar_espacios_finales(actual)
        if limpio != actual:
            actual = limpio
            reporte.cambios.append("quité espacios al final de línea")
    elif sufijo in (".md", ".markdown"):
        actual = quitar_espacios_finales(actual, markdown=True)
    con_salto = asegurar_salto_final(actual)
    if con_salto != actual:
        if actual.endswith("\n"):
            reporte.cambios.append("quité líneas vacías al final")
        else:
            reporte.cambios.append("agregué el salto de línea final")
        actual = con_salto

    if sufijo == ".py":
        tabs = arreglar_tabs_python(actual)
        if tabs is not None:
            actual = tabs
            reporte.cambios.append("convertí tabs de indentación a 4 espacios")
        tipograficos = arreglar_tipograficos(actual)
        if tipograficos is not None:
            actual = tipograficos
            reporte.cambios.append("reemplacé comillas/guiones tipográficos por ASCII")
        faltantes = imports_stdlib_faltantes(actual)
        con_imports = agregar_imports(actual, faltantes)
        if con_imports is not None:
            actual = con_imports
            reporte.cambios.append("agregué imports de la librería estándar: " + ", ".join(faltantes))
    elif sufijo in (".json", ".webmanifest") and nombre not in ("tsconfig.json", "jsconfig.json"):
        sin_comas = quitar_comas_finales_json(actual)
        if sin_comas is not None:
            actual = sin_comas
            reporte.cambios.append("quité comas finales inválidas del JSON")

    if actual != texto:
        reporte.contenido = actual
    return reporte


def autoarreglar(ws: Workspace, rel: str, usar_ruff: bool = True) -> ReporteAutofix:
    """Aplica los arreglos sobre el archivo real. Devuelve qué cambió."""
    try:
        ruta = ws.ruta(rel)
    except ErrorRuta:
        return ReporteAutofix(rel)
    rel = ws.rel(ruta)
    if not ruta.is_file() or es_binario(ruta) or not ws.es_texto(ruta) and ruta.suffix:
        return ReporteAutofix(rel)
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ReporteAutofix(rel)
    reporte = autoarreglar_texto(rel, texto)
    if reporte.contenido is not None:
        try:
            ws.escribir(rel, reporte.contenido)
        except (ErrorRuta, OSError):
            return ReporteAutofix(rel)
    if usar_ruff and ruta.suffix == ".py" and _compila(ruta.read_text(encoding="utf-8", errors="replace")):
        if _ruff_fix(ws, rel):
            reporte.cambios.append("ruff --fix (reglas seguras)")
    if ruta.suffix in (".sh", ".bash", ".py") or not ruta.suffix:
        try:
            primera = ruta.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
            modo = ruta.stat().st_mode
            if primera.startswith("#!") and not modo & 0o100:
                os.chmod(ruta, modo | 0o755)
                reporte.cambios.append("marqué el script como ejecutable (chmod +x)")
        except OSError:
            pass
    return reporte
