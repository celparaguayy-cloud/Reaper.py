"""Plantillas Python (librería estándar). Lote 2: datos, utilidades y Termux."""

# ======================================================================
# kv-store
# ======================================================================
registrar_plantilla(
    "kv-store",
    "Base clave-valor persistente: log de solo-agregado (no se corrompe), compactación, TTL y CLI.",
    "python",
    {
        "kvstore/__init__.py": "",
        "kvstore/almacen.py": r'''
"""Almacén clave-valor con log de operaciones (estilo Bitcask simplificado).

Cada escritura agrega una línea JSON al final del archivo: si el proceso se
corta, como mucho se pierde la última línea (que se ignora al cargar).
compactar() reescribe el log con solo el último valor de cada clave.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional


class Almacen:
    def __init__(self, ruta: Path, reloj: Callable[[], float] = time.time):
        self.ruta = Path(ruta)
        self.reloj = reloj
        self._datos: dict[str, tuple[Any, Optional[float]]] = {}
        self._lineas = 0
        self._cargar()

    def _cargar(self) -> None:
        if not self.ruta.exists():
            return
        with open(self.ruta, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    op = json.loads(linea)
                except json.JSONDecodeError:
                    continue  # línea cortada por un corte de energía: se ignora
                self._lineas += 1
                if op.get("op") == "set":
                    self._datos[op["k"]] = (op["v"], op.get("exp"))
                elif op.get("op") == "del":
                    self._datos.pop(op["k"], None)

    def _agregar(self, op: dict) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(op, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._lineas += 1

    def _vigente(self, clave: str) -> bool:
        if clave not in self._datos:
            return False
        _valor, expira = self._datos[clave]
        if expira is not None and self.reloj() >= expira:
            self._datos.pop(clave, None)
            return False
        return True

    def poner(self, clave: str, valor: Any, ttl: Optional[float] = None) -> None:
        if not isinstance(clave, str) or not clave:
            raise ValueError("la clave debe ser un texto no vacío")
        expira = self.reloj() + ttl if ttl else None
        self._agregar({"op": "set", "k": clave, "v": valor, "exp": expira})
        self._datos[clave] = (valor, expira)

    def obtener(self, clave: str, defecto: Any = None) -> Any:
        return self._datos[clave][0] if self._vigente(clave) else defecto

    def borrar(self, clave: str) -> bool:
        if not self._vigente(clave):
            return False
        self._agregar({"op": "del", "k": clave})
        self._datos.pop(clave, None)
        return True

    def claves(self, prefijo: str = "") -> list[str]:
        return sorted(k for k in list(self._datos) if k.startswith(prefijo) and self._vigente(k))

    def __len__(self) -> int:
        return len(self.claves())

    def __contains__(self, clave: str) -> bool:
        return self._vigente(clave)

    def desperdicio(self) -> float:
        """Proporción de líneas del log que ya no sirven (0 a 1)."""
        vivas = len(self)
        return 0.0 if not self._lineas else 1 - vivas / self._lineas

    def compactar(self) -> int:
        """Reescribe el log solo con lo vigente. Devuelve cuántas líneas se ahorraron."""
        antes = self._lineas
        temporal = self.ruta.with_suffix(".compactando")
        with open(temporal, "w", encoding="utf-8") as f:
            for clave in self.claves():
                valor, expira = self._datos[clave]
                f.write(json.dumps({"op": "set", "k": clave, "v": valor, "exp": expira}, ensure_ascii=False) + "\n")
        os.replace(temporal, self.ruta)
        self._lineas = len(self.claves())
        return antes - self._lineas
''',
        "kvstore/__main__.py": r'''
"""Uso: python3 -m kvstore [--db archivo] poner clave valor | obtener clave | borrar clave | claves [prefijo] | compactar"""

import json
import os
import sys
from pathlib import Path

from kvstore.almacen import Almacen


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    ruta = Path(os.environ.get("KV_DB", Path.home() / ".kvstore.log"))
    if argv[:1] == ["--db"] and len(argv) > 1:
        ruta, argv = Path(argv[1]), argv[2:]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    db = Almacen(ruta)
    cmd, args = argv[0], argv[1:]
    if cmd == "poner" and len(args) >= 2:
        try:
            valor = json.loads(args[1])
        except json.JSONDecodeError:
            valor = args[1]
        db.poner(args[0], valor)
    elif cmd == "obtener" and args:
        valor = db.obtener(args[0])
        if valor is None:
            print("(no existe)", file=sys.stderr)
            return 1
        print(json.dumps(valor, ensure_ascii=False))
    elif cmd == "borrar" and args:
        return 0 if db.borrar(args[0]) else 1
    elif cmd == "claves":
        print("\n".join(db.claves(args[0] if args else "")))
    elif cmd == "compactar":
        print(f"ahorradas {db.compactar()} líneas")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_kvstore.py": r'''
import tempfile
import unittest
from pathlib import Path

from kvstore.almacen import Almacen


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestAlmacen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self.tmp.name) / "db.log"

    def tearDown(self):
        self.tmp.cleanup()

    def test_persistencia(self):
        db = Almacen(self.ruta)
        db.poner("a", 1)
        db.poner("b", {"x": [1, 2]})
        db.poner("a", 2)
        db.borrar("b")
        otra = Almacen(self.ruta)
        self.assertEqual(otra.obtener("a"), 2)
        self.assertNotIn("b", otra)
        self.assertEqual(len(otra), 1)

    def test_linea_cortada_se_ignora(self):
        db = Almacen(self.ruta)
        db.poner("ok", "sí")
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write('{"op": "set", "k": "cort')
        self.assertEqual(Almacen(self.ruta).obtener("ok"), "sí")

    def test_ttl(self):
        reloj = Reloj()
        db = Almacen(self.ruta, reloj)
        db.poner("sesion", "abc", ttl=60)
        self.assertEqual(db.obtener("sesion"), "abc")
        reloj.t += 61
        self.assertIsNone(db.obtener("sesion"))
        self.assertEqual(db.claves(), [])

    def test_compactar(self):
        db = Almacen(self.ruta)
        for i in range(10):
            db.poner("contador", i)
        self.assertGreater(db.desperdicio(), 0.8)
        self.assertEqual(db.compactar(), 9)
        self.assertEqual(len(self.ruta.read_text().splitlines()), 1)
        self.assertEqual(Almacen(self.ruta).obtener("contador"), 9)

    def test_claves_y_prefijos(self):
        db = Almacen(self.ruta)
        for k in ("user:1", "user:2", "post:1"):
            db.poner(k, True)
        self.assertEqual(db.claves("user:"), ["user:1", "user:2"])
        with self.assertRaises(ValueError):
            db.poner("", 1)
        self.assertFalse(db.borrar("nada"))


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m kvstore poner saludo hola && python3 -m kvstore obtener saludo",
    etiquetas=("base de datos", "clave", "valor", "cache", "persistencia", "almacenamiento", "kv"),
)

# ======================================================================
# analizador de logs
# ======================================================================
registrar_plantilla(
    "logs",
    "Analizador de logs (formato Apache/Nginx y genérico): top IPs y rutas, errores por hora, filtros y reporte.",
    "python",
    {
        "logs/__init__.py": "",
        "logs/analisis.py": r'''
"""Parseo y estadísticas de logs de acceso."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator, Optional

PATRON_COMBINADO = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<fecha>[^\]]+)\] "(?P<metodo>[A-Z]+) (?P<ruta>\S+) [^"]*" '
    r'(?P<estado>\d{3}) (?P<bytes>\d+|-)'
)


@dataclass(frozen=True)
class Acceso:
    ip: str
    fecha: datetime
    metodo: str
    ruta: str
    estado: int
    bytes: int

    @property
    def es_error(self) -> bool:
        return self.estado >= 400


def parsear_linea(linea: str) -> Optional[Acceso]:
    m = PATRON_COMBINADO.search(linea)
    if not m:
        return None
    try:
        fecha = datetime.strptime(m.group("fecha").split()[0], "%d/%b/%Y:%H:%M:%S")
    except ValueError:
        return None
    tam = m.group("bytes")
    return Acceso(m.group("ip"), fecha, m.group("metodo"), m.group("ruta").split("?")[0], int(m.group("estado")),
                  0 if tam == "-" else int(tam))


def parsear(lineas: Iterable[str]) -> tuple[list[Acceso], int]:
    """(accesos válidos, cantidad de líneas que no se pudieron leer)."""
    accesos, malas = [], 0
    for linea in lineas:
        if not linea.strip():
            continue
        acceso = parsear_linea(linea)
        if acceso is None:
            malas += 1
        else:
            accesos.append(acceso)
    return accesos, malas


def top(valores: Iterable[str], n: int = 5) -> list[tuple[str, int]]:
    return sorted(Counter(valores).items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def errores_por_hora(accesos: Iterable[Acceso]) -> dict[str, int]:
    por_hora: dict[str, int] = defaultdict(int)
    for a in accesos:
        if a.es_error:
            por_hora[a.fecha.strftime("%Y-%m-%d %H:00")] += 1
    return dict(sorted(por_hora.items()))


def filtrar(accesos: Iterable[Acceso], estado: Optional[int] = None, ruta: str = "", ip: str = "") -> Iterator[Acceso]:
    for a in accesos:
        if estado is not None and a.estado != estado:
            continue
        if ruta and ruta not in a.ruta:
            continue
        if ip and a.ip != ip:
            continue
        yield a


def reporte(accesos: list[Acceso], malas: int = 0) -> str:
    if not accesos:
        return "No hay accesos válidos."
    total_bytes = sum(a.bytes for a in accesos)
    errores = sum(1 for a in accesos if a.es_error)
    lineas = [
        f"Accesos: {len(accesos)} ({malas} líneas ilegibles)",
        f"Errores: {errores} ({100 * errores / len(accesos):.1f}%)",
        f"Transferido: {total_bytes / 1024:.1f} KB",
        "Top IPs: " + ", ".join(f"{ip} ({n})" for ip, n in top(a.ip for a in accesos)),
        "Top rutas: " + ", ".join(f"{r} ({n})" for r, n in top(a.ruta for a in accesos)),
    ]
    return "\n".join(lineas)
''',
        "logs/__main__.py": r'''
"""Uso: python3 -m logs access.log [--estado 404] [--ruta /api]"""

import sys
from pathlib import Path

from logs.analisis import errores_por_hora, filtrar, parsear, reporte


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        lineas = Path(argv[0]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    accesos, malas = parsear(lineas)
    estado = int(argv[argv.index("--estado") + 1]) if "--estado" in argv else None
    ruta = argv[argv.index("--ruta") + 1] if "--ruta" in argv else ""
    accesos = list(filtrar(accesos, estado, ruta))
    print(reporte(accesos, malas))
    for hora, n in errores_por_hora(accesos).items():
        print(f"  {hora}: {'█' * min(n, 50)} {n}")
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_logs.py": r'''
import unittest

from logs.analisis import errores_por_hora, filtrar, parsear, parsear_linea, reporte, top

LOG = """1.1.1.1 - - [10/Oct/2026:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326
2.2.2.2 - - [10/Oct/2026:13:56:01 +0000] "GET /api/x?y=1 HTTP/1.1" 404 120
1.1.1.1 - - [10/Oct/2026:14:01:00 +0000] "POST /api/login HTTP/1.1" 500 -
esto no es un log
1.1.1.1 - - [10/Oct/2026:14:05:00 +0000] "GET /index.html HTTP/1.1" 200 1000
"""


class TestLogs(unittest.TestCase):
    def setUp(self):
        self.accesos, self.malas = parsear(LOG.splitlines())

    def test_parseo(self):
        self.assertEqual((len(self.accesos), self.malas), (4, 1))
        a = parsear_linea(LOG.splitlines()[1])
        self.assertEqual((a.ip, a.ruta, a.estado, a.bytes), ("2.2.2.2", "/api/x", 404, 120))
        self.assertEqual(self.accesos[2].bytes, 0)

    def test_top_y_errores(self):
        self.assertEqual(top([a.ip for a in self.accesos], 1), [("1.1.1.1", 3)])
        self.assertEqual(errores_por_hora(self.accesos), {"2026-10-10 13:00": 1, "2026-10-10 14:00": 1})

    def test_filtros(self):
        self.assertEqual(len(list(filtrar(self.accesos, estado=200))), 2)
        self.assertEqual(len(list(filtrar(self.accesos, ruta="/api"))), 2)
        self.assertEqual(len(list(filtrar(self.accesos, ip="2.2.2.2"))), 1)

    def test_reporte(self):
        texto = reporte(self.accesos, self.malas)
        self.assertIn("Accesos: 4", texto)
        self.assertIn("Errores: 2 (50.0%)", texto)
        self.assertEqual(reporte([]), "No hay accesos válidos.")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m logs /ruta/access.log",
    etiquetas=("logs", "registro", "analizar", "estadisticas", "servidor", "nginx", "apache", "reporte"),
)

# ======================================================================
# pomodoro
# ======================================================================
registrar_plantilla(
    "pomodoro",
    "Temporizador Pomodoro en la terminal: máquina de estados testeable con reloj inyectable y aviso de Android.",
    "python",
    {
        "pomodoro/__init__.py": "",
        "pomodoro/estado.py": r'''
"""Máquina de estados del Pomodoro (sin sleeps ni prints: se testea con un reloj falso)."""

from dataclasses import dataclass, field
from typing import Callable

TRABAJO, DESCANSO_CORTO, DESCANSO_LARGO = "trabajo", "descanso corto", "descanso largo"


@dataclass
class Config:
    trabajo: int = 25 * 60
    corto: int = 5 * 60
    largo: int = 15 * 60
    ciclos_para_largo: int = 4


@dataclass
class Pomodoro:
    config: Config = field(default_factory=Config)
    reloj: Callable[[], float] = None
    fase: str = TRABAJO
    completados: int = 0
    inicio_fase: float = 0.0
    pausado_en: float = None

    def __post_init__(self):
        import time
        self.reloj = self.reloj or time.monotonic
        self.inicio_fase = self.reloj()

    def duracion(self) -> int:
        return {TRABAJO: self.config.trabajo, DESCANSO_CORTO: self.config.corto,
                DESCANSO_LARGO: self.config.largo}[self.fase]

    def transcurrido(self) -> float:
        fin = self.pausado_en if self.pausado_en is not None else self.reloj()
        return fin - self.inicio_fase

    def restante(self) -> int:
        return max(0, int(round(self.duracion() - self.transcurrido())))

    def pausar(self) -> None:
        if self.pausado_en is None:
            self.pausado_en = self.reloj()

    def reanudar(self) -> None:
        if self.pausado_en is not None:
            self.inicio_fase += self.reloj() - self.pausado_en
            self.pausado_en = None

    def siguiente(self) -> str:
        if self.fase == TRABAJO:
            self.completados += 1
            largo = self.completados % self.config.ciclos_para_largo == 0
            self.fase = DESCANSO_LARGO if largo else DESCANSO_CORTO
        else:
            self.fase = TRABAJO
        self.inicio_fase = self.reloj()
        self.pausado_en = None
        return self.fase

    def actualizar(self) -> bool:
        """Avanza de fase si se terminó el tiempo. Devuelve True si cambió."""
        if self.pausado_en is None and self.restante() == 0:
            self.siguiente()
            return True
        return False


def formato(segundos: int) -> str:
    return f"{segundos // 60:02d}:{segundos % 60:02d}"
''',
        "pomodoro/__main__.py": r'''
"""Uso: python3 -m pomodoro [minutos_trabajo] [minutos_descanso]  (Ctrl+C para salir)"""

import shutil
import subprocess
import sys
import time

from pomodoro.estado import Config, Pomodoro, formato


def avisar(texto: str) -> None:
    print("\a", end="")
    if shutil.which("termux-notification"):
        subprocess.run(["termux-notification", "--title", "Pomodoro", "--content", texto], timeout=10)


def main() -> None:
    args = [int(a) for a in sys.argv[1:3] if a.isdigit()]
    config = Config(trabajo=(args[0] if args else 25) * 60, corto=(args[1] if len(args) > 1 else 5) * 60)
    p = Pomodoro(config)
    try:
        while True:
            print(f"\r{p.fase:<15} {formato(p.restante())}  completados: {p.completados}  ", end="", flush=True)
            if p.actualizar():
                avisar(f"Ahora: {p.fase}")
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\nPomodoros completados: {p.completados}")


main()
''',
        "tests/__init__.py": "",
        "tests/test_pomodoro.py": r'''
import unittest

from pomodoro.estado import DESCANSO_CORTO, DESCANSO_LARGO, TRABAJO, Config, Pomodoro, formato


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestPomodoro(unittest.TestCase):
    def setUp(self):
        self.reloj = Reloj()
        self.p = Pomodoro(Config(trabajo=100, corto=10, largo=30, ciclos_para_largo=2), self.reloj)

    def test_restante_y_cambio(self):
        self.reloj.t = 40
        self.assertEqual(self.p.restante(), 60)
        self.assertFalse(self.p.actualizar())
        self.reloj.t = 100
        self.assertTrue(self.p.actualizar())
        self.assertEqual((self.p.fase, self.p.completados), (DESCANSO_CORTO, 1))

    def test_descanso_largo(self):
        self.p.siguiente()
        self.p.siguiente()
        self.assertEqual(self.p.siguiente(), DESCANSO_LARGO)
        self.assertEqual(self.p.siguiente(), TRABAJO)

    def test_pausa(self):
        self.reloj.t = 30
        self.p.pausar()
        self.reloj.t = 500
        self.assertEqual(self.p.restante(), 70)
        self.assertFalse(self.p.actualizar())
        self.p.reanudar()
        self.reloj.t = 510
        self.assertEqual(self.p.restante(), 60)

    def test_formato(self):
        self.assertEqual(formato(1500), "25:00")
        self.assertEqual(formato(65), "01:05")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m pomodoro 25 5",
    etiquetas=("pomodoro", "temporizador", "timer", "productividad", "reloj", "tiempo"),
)

# ======================================================================
# conversor de unidades
# ======================================================================
registrar_plantilla(
    "conversor",
    "Conversor de unidades (longitud, masa, volumen, temperatura, datos, tiempo) con parser de texto '5 km a mi'.",
    "python",
    {
        "conversor/__init__.py": "",
        "conversor/unidades.py": r'''
"""Conversión de unidades por categorías. Temperatura se trata aparte (no es lineal)."""

import re
from decimal import Decimal

FACTORES = {
    "longitud": {"mm": "0.001", "cm": "0.01", "m": "1", "km": "1000", "in": "0.0254", "ft": "0.3048",
                 "yd": "0.9144", "mi": "1609.344"},
    "masa": {"mg": "0.000001", "g": "0.001", "kg": "1", "t": "1000", "oz": "0.028349523125", "lb": "0.45359237"},
    "volumen": {"ml": "0.001", "l": "1", "m3": "1000", "taza": "0.25", "gal": "3.785411784"},
    "datos": {"b": "1", "kb": "1000", "mb": "1000000", "gb": "1000000000", "kib": "1024", "mib": "1048576",
              "gib": "1073741824"},
    "tiempo": {"s": "1", "min": "60", "h": "3600", "dia": "86400", "semana": "604800"},
}
ALIAS = {"metro": "m", "metros": "m", "kilometro": "km", "kilometros": "km", "milla": "mi", "millas": "mi",
         "pie": "ft", "pies": "ft", "pulgada": "in", "pulgadas": "in", "gramo": "g", "gramos": "g",
         "kilo": "kg", "kilos": "kg", "libra": "lb", "libras": "lb", "litro": "l", "litros": "l",
         "hora": "h", "horas": "h", "minutos": "min", "segundos": "s", "dias": "dia", "días": "dia"}
TEMPERATURAS = {"c", "f", "k"}


def normalizar(unidad: str) -> str:
    u = unidad.strip().lower().rstrip(".")
    return ALIAS.get(u, u)


def categoria(unidad: str) -> str:
    u = normalizar(unidad)
    if u in TEMPERATURAS:
        return "temperatura"
    for cat, tabla in FACTORES.items():
        if u in tabla:
            return cat
    raise ValueError(f"unidad desconocida: {unidad}")


def _temperatura(valor: Decimal, desde: str, hasta: str) -> Decimal:
    celsius = {"c": valor, "f": (valor - 32) * 5 / 9, "k": valor - Decimal("273.15")}[desde]
    return {"c": celsius, "f": celsius * 9 / 5 + 32, "k": celsius + Decimal("273.15")}[hasta]


def convertir(valor, desde: str, hasta: str, decimales: int = 4) -> float:
    d, h = normalizar(desde), normalizar(hasta)
    cat_d, cat_h = categoria(d), categoria(h)
    if cat_d != cat_h:
        raise ValueError(f"no se puede convertir {cat_d} a {cat_h}")
    valor = Decimal(str(valor))
    if cat_d == "temperatura":
        resultado = _temperatura(valor, d, h)
    else:
        tabla = FACTORES[cat_d]
        resultado = valor * Decimal(tabla[d]) / Decimal(tabla[h])
    return round(float(resultado), decimales)


_PEDIDO = re.compile(r"^\s*(-?[\d.,]+)\s*([a-záéíóú0-9]+)\s+(?:a|en|to|->)\s+([a-záéíóú0-9]+)\s*$", re.I)


def convertir_texto(pedido: str) -> str:
    """'5 km a mi' → '5 km = 3.1069 mi'"""
    m = _PEDIDO.match(pedido)
    if not m:
        raise ValueError("formato: <número> <unidad> a <unidad>   (ej: 5 km a mi)")
    numero = m.group(1).replace(",", ".")
    resultado = convertir(numero, m.group(2), m.group(3))
    return f"{numero} {normalizar(m.group(2))} = {resultado:g} {normalizar(m.group(3))}"
''',
        "conversor/__main__.py": r'''
"""Uso: python3 -m conversor "5 km a mi"   (sin argumentos: modo interactivo)"""

import sys

from conversor.unidades import convertir_texto


def main() -> int:
    if len(sys.argv) > 1:
        try:
            print(convertir_texto(" ".join(sys.argv[1:])))
            return 0
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    while True:
        try:
            pedido = input("convertir> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if pedido in ("salir", "q"):
            return 0
        try:
            print(convertir_texto(pedido))
        except ValueError as e:
            print(e)


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_conversor.py": r'''
import unittest

from conversor.unidades import categoria, convertir, convertir_texto


class TestConversor(unittest.TestCase):
    def test_lineales(self):
        self.assertEqual(convertir(1, "km", "m"), 1000)
        self.assertAlmostEqual(convertir(1, "mi", "km"), 1.6093, places=4)
        self.assertEqual(convertir(2, "kilos", "g"), 2000)
        self.assertEqual(convertir(1, "gib", "mib"), 1024)

    def test_temperatura(self):
        self.assertEqual(convertir(100, "c", "f"), 212)
        self.assertEqual(convertir(32, "f", "c"), 0)
        self.assertEqual(convertir(0, "k", "c"), -273.15)

    def test_errores(self):
        with self.assertRaises(ValueError):
            convertir(1, "km", "kg")
        with self.assertRaises(ValueError):
            categoria("parsec")
        with self.assertRaises(ValueError):
            convertir_texto("cinco km a mi")

    def test_texto(self):
        self.assertEqual(convertir_texto("5 km a m"), "5 km = 5000 m")
        self.assertEqual(convertir_texto("1,5 horas en min"), "1.5 h = 90 min")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar='python3 -m conversor "5 km a mi"',
    etiquetas=("conversor", "unidades", "convertir", "temperatura", "medidas", "calculadora"),
)

# ======================================================================
# generador de contraseñas
# ======================================================================
registrar_plantilla(
    "claves",
    "Generador de contraseñas y frases de paso con `secrets`, cálculo de entropía y evaluación de fortaleza.",
    "python",
    {
        "claves/__init__.py": "",
        "claves/generador.py": r'''
"""Contraseñas seguras con secrets (nunca random para esto)."""

import math
import secrets
import string

PALABRAS = (
    "agua arbol barco bosque cafe campo cielo ciudad clave cobre dragon espejo faro fuego gato hierro isla "
    "jardin lago lapiz libro luna mapa mar metal miel monte nieve nube oro papel perro piedra plata playa "
    "puente radio reloj rio robot roca sal selva sol tierra tigre torre trigo valle vela viento volcan zorro"
).split()
AMBIGUOS = set("Il1O0o")


def contrasena(largo: int = 16, mayusculas: bool = True, numeros: bool = True, simbolos: bool = True,
               sin_ambiguos: bool = False) -> str:
    if largo < 8:
        raise ValueError("una contraseña segura tiene al menos 8 caracteres")
    grupos = [string.ascii_lowercase]
    if mayusculas:
        grupos.append(string.ascii_uppercase)
    if numeros:
        grupos.append(string.digits)
    if simbolos:
        grupos.append("!@#$%&*-_=+?")
    if sin_ambiguos:
        grupos = ["".join(c for c in g if c not in AMBIGUOS) for g in grupos]
    # Al menos un carácter de cada grupo pedido, el resto de cualquiera.
    caracteres = [secrets.choice(g) for g in grupos]
    todos = "".join(grupos)
    caracteres += [secrets.choice(todos) for _ in range(largo - len(caracteres))]
    secrets.SystemRandom().shuffle(caracteres)
    return "".join(caracteres)


def frase(palabras: int = 5, separador: str = "-", numero: bool = True) -> str:
    if palabras < 3:
        raise ValueError("usá al menos 3 palabras")
    partes = [secrets.choice(PALABRAS) for _ in range(palabras)]
    if numero:
        partes.append(str(secrets.randbelow(100)))
    return separador.join(partes)


def entropia(clave: str) -> float:
    """Bits de entropía estimados según los tipos de caracteres usados."""
    universo = 0
    if any(c.islower() for c in clave):
        universo += 26
    if any(c.isupper() for c in clave):
        universo += 26
    if any(c.isdigit() for c in clave):
        universo += 10
    if any(not c.isalnum() for c in clave):
        universo += 32
    return round(len(clave) * math.log2(universo), 1) if universo else 0.0


def fortaleza(clave: str) -> str:
    bits = entropia(clave)
    if len(set(clave)) <= 2:
        return "muy débil"
    if bits < 40:
        return "débil"
    if bits < 60:
        return "media"
    if bits < 80:
        return "fuerte"
    return "muy fuerte"
''',
        "claves/__main__.py": r'''
"""Uso: python3 -m claves [largo] | python3 -m claves frase [palabras] | python3 -m claves evaluar <clave>"""

import sys

from claves.generador import contrasena, entropia, fortaleza, frase


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["frase"]:
            print(frase(int(argv[1]) if len(argv) > 1 else 5))
        elif argv[:1] == ["evaluar"] and len(argv) > 1:
            print(f"{fortaleza(argv[1])} ({entropia(argv[1])} bits)")
        else:
            clave = contrasena(int(argv[0]) if argv else 16)
            print(clave)
            print(f"  {fortaleza(clave)} · {entropia(clave)} bits", file=sys.stderr)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_claves.py": r'''
import string
import unittest

from claves.generador import AMBIGUOS, contrasena, entropia, fortaleza, frase


class TestClaves(unittest.TestCase):
    def test_largo_y_grupos(self):
        for _ in range(50):
            c = contrasena(12)
            self.assertEqual(len(c), 12)
            self.assertTrue(any(ch.isupper() for ch in c))
            self.assertTrue(any(ch.isdigit() for ch in c))
            self.assertTrue(any(ch in "!@#$%&*-_=+?" for ch in c))

    def test_opciones(self):
        c = contrasena(20, mayusculas=False, numeros=False, simbolos=False)
        self.assertTrue(all(ch in string.ascii_lowercase for ch in c))
        self.assertFalse(set(contrasena(40, sin_ambiguos=True)) & AMBIGUOS)
        with self.assertRaises(ValueError):
            contrasena(5)

    def test_no_se_repiten(self):
        self.assertEqual(len({contrasena() for _ in range(100)}), 100)

    def test_frase(self):
        f = frase(4, separador=" ", numero=False)
        self.assertEqual(len(f.split()), 4)
        with self.assertRaises(ValueError):
            frase(2)

    def test_entropia_y_fortaleza(self):
        self.assertEqual(entropia(""), 0.0)
        self.assertEqual(fortaleza("aaaa"), "muy débil")
        self.assertEqual(fortaleza("hola123"), "débil")
        self.assertIn(fortaleza(contrasena(20)), ("fuerte", "muy fuerte"))


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m claves 20",
    etiquetas=("contraseña", "password", "clave", "seguridad", "generador", "secrets"),
)

# ======================================================================
# inventario (sqlite)
# ======================================================================
registrar_plantilla(
    "inventario",
    "Inventario con sqlite3: productos, movimientos de stock (entradas/salidas), alertas de stock bajo y reportes.",
    "python",
    {
        "inventario/__init__.py": "",
        "inventario/db.py": r'''
"""Inventario con historial de movimientos. El stock se calcula a partir de los movimientos."""

import sqlite3
from datetime import datetime
from typing import Optional

ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    precio REAL NOT NULL CHECK (precio >= 0),
    minimo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    cantidad INTEGER NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    fecha TEXT NOT NULL
);
"""


class ErrorInventario(ValueError):
    pass


class Inventario:
    def __init__(self, ruta: str = ":memory:"):
        self.con = sqlite3.connect(ruta)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(ESQUEMA)

    def agregar_producto(self, codigo: str, nombre: str, precio: float, minimo: int = 0) -> int:
        try:
            with self.con:
                return self.con.execute(
                    "INSERT INTO productos (codigo, nombre, precio, minimo) VALUES (?, ?, ?, ?)",
                    (codigo.strip().upper(), nombre.strip(), precio, minimo),
                ).lastrowid
        except sqlite3.IntegrityError as e:
            raise ErrorInventario(f"no se pudo agregar {codigo}: {e}") from None

    def _producto(self, codigo: str) -> sqlite3.Row:
        fila = self.con.execute("SELECT * FROM productos WHERE codigo = ?", (codigo.strip().upper(),)).fetchone()
        if fila is None:
            raise ErrorInventario(f"no existe el producto {codigo}")
        return fila

    def stock(self, codigo: str) -> int:
        p = self._producto(codigo)
        fila = self.con.execute("SELECT COALESCE(SUM(cantidad), 0) AS s FROM movimientos WHERE producto_id = ?",
                                (p["id"],)).fetchone()
        return int(fila["s"])

    def mover(self, codigo: str, cantidad: int, motivo: str = "", fecha: Optional[str] = None) -> int:
        if cantidad == 0:
            raise ErrorInventario("la cantidad no puede ser cero")
        p = self._producto(codigo)
        if cantidad < 0 and self.stock(codigo) + cantidad < 0:
            raise ErrorInventario(f"stock insuficiente de {codigo} (hay {self.stock(codigo)})")
        with self.con:
            self.con.execute("INSERT INTO movimientos (producto_id, cantidad, motivo, fecha) VALUES (?, ?, ?, ?)",
                             (p["id"], cantidad, motivo, fecha or datetime.now().isoformat(timespec="seconds")))
        return self.stock(codigo)

    def entrada(self, codigo: str, cantidad: int, motivo: str = "compra") -> int:
        return self.mover(codigo, abs(cantidad), motivo)

    def salida(self, codigo: str, cantidad: int, motivo: str = "venta") -> int:
        return self.mover(codigo, -abs(cantidad), motivo)

    def stock_bajo(self) -> list[dict]:
        filas = self.con.execute(
            "SELECT p.codigo, p.nombre, p.minimo, COALESCE(SUM(m.cantidad), 0) AS stock FROM productos p "
            "LEFT JOIN movimientos m ON m.producto_id = p.id GROUP BY p.id HAVING stock < p.minimo ORDER BY p.codigo"
        ).fetchall()
        return [dict(f) for f in filas]

    def valorizado(self) -> float:
        fila = self.con.execute(
            "SELECT COALESCE(SUM(p.precio * s.stock), 0) AS total FROM productos p JOIN "
            "(SELECT producto_id, SUM(cantidad) AS stock FROM movimientos GROUP BY producto_id) s ON s.producto_id = p.id"
        ).fetchone()
        return round(float(fila["total"]), 2)

    def historial(self, codigo: str) -> list[dict]:
        p = self._producto(codigo)
        filas = self.con.execute("SELECT cantidad, motivo, fecha FROM movimientos WHERE producto_id = ? ORDER BY id",
                                 (p["id"],)).fetchall()
        return [dict(f) for f in filas]
''',
        "inventario/__main__.py": r'''
"""Uso: python3 -m inventario alta COD "Nombre" precio [minimo] | entrada COD n | salida COD n | stock COD | bajo | valor"""

import os
import sys

from inventario.db import ErrorInventario, Inventario


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    inv = Inventario(os.environ.get("INVENTARIO_DB", "inventario.db"))
    try:
        if argv[:1] == ["alta"] and len(argv) >= 4:
            inv.agregar_producto(argv[1], argv[2], float(argv[3]), int(argv[4]) if len(argv) > 4 else 0)
            print("producto agregado")
        elif argv[:1] in (["entrada"], ["salida"]) and len(argv) == 3:
            stock = (inv.entrada if argv[0] == "entrada" else inv.salida)(argv[1], int(argv[2]))
            print(f"stock de {argv[1]}: {stock}")
        elif argv[:1] == ["stock"] and len(argv) == 2:
            print(inv.stock(argv[1]))
        elif argv[:1] == ["bajo"]:
            for p in inv.stock_bajo():
                print(f"{p['codigo']} {p['nombre']}: {p['stock']} (mínimo {p['minimo']})")
        elif argv[:1] == ["valor"]:
            print(f"${inv.valorizado():.2f}")
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except (ErrorInventario, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_inventario.py": r'''
import unittest

from inventario.db import ErrorInventario, Inventario


class TestInventario(unittest.TestCase):
    def setUp(self):
        self.inv = Inventario()
        self.inv.agregar_producto("a1", "Arroz", 2.5, minimo=10)
        self.inv.agregar_producto("B2", "Fideos", 1.0, minimo=0)

    def test_movimientos(self):
        self.assertEqual(self.inv.entrada("A1", 20), 20)
        self.assertEqual(self.inv.salida("a1", 15), 5)
        self.assertEqual(len(self.inv.historial("A1")), 2)

    def test_stock_insuficiente_y_errores(self):
        self.inv.entrada("A1", 3)
        with self.assertRaises(ErrorInventario):
            self.inv.salida("A1", 4)
        with self.assertRaises(ErrorInventario):
            self.inv.mover("A1", 0)
        with self.assertRaises(ErrorInventario):
            self.inv.stock("ZZ")
        with self.assertRaises(ErrorInventario):
            self.inv.agregar_producto("A1", "Duplicado", 1)

    def test_stock_bajo_y_valor(self):
        self.inv.entrada("A1", 4)
        self.inv.entrada("B2", 10)
        self.assertEqual([p["codigo"] for p in self.inv.stock_bajo()], ["A1"])
        self.assertEqual(self.inv.valorizado(), 20.0)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar='python3 -m inventario alta A1 "Arroz" 2.5 10',
    etiquetas=("inventario", "stock", "productos", "sqlite", "negocio", "almacen", "ventas"),
)

# ======================================================================
# notas markdown
# ======================================================================
registrar_plantilla(
    "notas",
    "Notas en archivos Markdown con etiquetas (#tag), búsqueda por texto/etiqueta, enlaces [[nota]] y backlinks.",
    "python",
    {
        "notas/__init__.py": "",
        "notas/boveda.py": r'''
"""Bóveda de notas Markdown (estilo Obsidian minimalista)."""

import re
from dataclasses import dataclass, field
from pathlib import Path

_ETIQUETA = re.compile(r"(?<![\w#])#([a-záéíóúñ][\wáéíóúñ-]*)", re.I)
_ENLACE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def slug(titulo: str) -> str:
    base = re.sub(r"[^\w\s-]", "", titulo.lower()).strip()
    return re.sub(r"[\s_]+", "-", base) or "sin-titulo"


@dataclass
class Nota:
    titulo: str
    texto: str
    ruta: Path = None
    etiquetas: set = field(default_factory=set)
    enlaces: set = field(default_factory=set)

    @classmethod
    def desde_texto(cls, titulo: str, texto: str, ruta: Path = None) -> "Nota":
        etiquetas = {e.lower() for e in _ETIQUETA.findall(texto)}
        enlaces = {slug(e) for e in _ENLACE.findall(texto)}
        return cls(titulo, texto, ruta, etiquetas, enlaces)


class Boveda:
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def _ruta(self, titulo: str) -> Path:
        return self.carpeta / f"{slug(titulo)}.md"

    def guardar(self, titulo: str, texto: str) -> Nota:
        if not titulo.strip():
            raise ValueError("la nota necesita título")
        ruta = self._ruta(titulo)
        ruta.write_text(f"# {titulo.strip()}\n\n{texto.strip()}\n", encoding="utf-8")
        return Nota.desde_texto(titulo.strip(), texto, ruta)

    def leer(self, titulo_o_slug: str) -> Nota:
        ruta = self.carpeta / f"{slug(titulo_o_slug)}.md"
        if not ruta.exists():
            raise FileNotFoundError(f"no existe la nota {titulo_o_slug}")
        contenido = ruta.read_text(encoding="utf-8")
        primera, _, resto = contenido.partition("\n")
        titulo = primera.lstrip("# ").strip() or ruta.stem
        return Nota.desde_texto(titulo, resto.strip(), ruta)

    def todas(self) -> list[Nota]:
        return [self.leer(r.stem) for r in sorted(self.carpeta.glob("*.md"))]

    def buscar(self, texto: str = "", etiqueta: str = "") -> list[Nota]:
        texto, etiqueta = texto.lower(), etiqueta.lower().lstrip("#")
        salida = []
        for n in self.todas():
            if texto and texto not in (n.titulo + " " + n.texto).lower():
                continue
            if etiqueta and etiqueta not in n.etiquetas:
                continue
            salida.append(n)
        return salida

    def etiquetas(self) -> dict[str, int]:
        conteo: dict[str, int] = {}
        for n in self.todas():
            for e in n.etiquetas:
                conteo[e] = conteo.get(e, 0) + 1
        return dict(sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0])))

    def backlinks(self, titulo: str) -> list[str]:
        objetivo = slug(titulo)
        return sorted(n.titulo for n in self.todas() if objetivo in n.enlaces)

    def enlaces_rotos(self) -> list[tuple[str, str]]:
        existentes = {r.stem for r in self.carpeta.glob("*.md")}
        return sorted((n.titulo, e) for n in self.todas() for e in n.enlaces if e not in existentes)
''',
        "notas/__main__.py": r'''
"""Uso: python3 -m notas nueva "Título" "texto con #etiquetas y [[enlaces]]" | ver T | buscar texto | tag nombre | tags"""

import os
import sys
from pathlib import Path

from notas.boveda import Boveda


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    b = Boveda(Path(os.environ.get("NOTAS_DIR", Path.home() / "notas")))
    try:
        if argv[:1] == ["nueva"] and len(argv) >= 3:
            print(f"guardada: {b.guardar(argv[1], argv[2]).ruta}")
        elif argv[:1] == ["ver"] and len(argv) == 2:
            n = b.leer(argv[1])
            print(f"# {n.titulo}\n\n{n.texto}\n")
            refs = b.backlinks(n.titulo)
            if refs:
                print("Mencionada en: " + ", ".join(refs))
        elif argv[:1] == ["buscar"] and len(argv) == 2:
            for n in b.buscar(texto=argv[1]):
                print(n.titulo)
        elif argv[:1] == ["tag"] and len(argv) == 2:
            for n in b.buscar(etiqueta=argv[1]):
                print(n.titulo)
        elif argv[:1] == ["tags"]:
            for etiqueta, n in b.etiquetas().items():
                print(f"#{etiqueta} ({n})")
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_notas.py": r'''
import tempfile
import unittest
from pathlib import Path

from notas.boveda import Boveda, Nota, slug


class TestNotas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = Boveda(Path(self.tmp.name))
        self.b.guardar("Recetas de cocina", "Ideas para la semana #cocina #casa. Ver [[Lista de compras]].")
        self.b.guardar("Lista de compras", "Pan, leche #casa")
        self.b.guardar("Proyecto REAPER", "Agente para Termux #codigo, depende de [[Inexistente]]")

    def tearDown(self):
        self.tmp.cleanup()

    def test_slug_y_parseo(self):
        self.assertEqual(slug("¡Hola, Mundo!"), "hola-mundo")
        n = Nota.desde_texto("x", "texto #Uno y #dos-tres, no#esto [[Otra Nota|alias]]")
        self.assertEqual(n.etiquetas, {"uno", "dos-tres"})
        self.assertEqual(n.enlaces, {"otra-nota"})

    def test_leer_y_buscar(self):
        self.assertEqual(self.b.leer("lista de compras").titulo, "Lista de compras")
        self.assertEqual([n.titulo for n in self.b.buscar(texto="leche")], ["Lista de compras"])
        self.assertEqual(len(self.b.buscar(etiqueta="#casa")), 2)
        with self.assertRaises(FileNotFoundError):
            self.b.leer("no existe")

    def test_etiquetas_backlinks_rotos(self):
        self.assertEqual(list(self.b.etiquetas().items())[0], ("casa", 2))
        self.assertEqual(self.b.backlinks("Lista de compras"), ["Recetas de cocina"])
        self.assertEqual(self.b.enlaces_rotos(), [("Proyecto REAPER", "inexistente")])

    def test_titulo_obligatorio(self):
        with self.assertRaises(ValueError):
            self.b.guardar("  ", "x")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar='python3 -m notas nueva "Mi primera nota" "Hola #reaper"',
    etiquetas=("notas", "markdown", "apuntes", "etiquetas", "obsidian", "wiki", "conocimiento"),
)

# ======================================================================
# sitio estático
# ======================================================================
registrar_plantilla(
    "sitio-estatico",
    "Generador de sitios estáticos: Markdown (subconjunto) → HTML con plantilla, índice de páginas y estilos.",
    "python",
    {
        "sitio/__init__.py": "",
        "sitio/markdown.py": r'''
"""Conversor Markdown → HTML (subconjunto: títulos, párrafos, listas, código, énfasis, links)."""

import html
import re


def _en_linea(texto: str) -> str:
    texto = html.escape(texto, quote=False)
    texto = re.sub(r"`([^`]+)`", r"<code>\1</code>", texto)
    texto = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", texto)
    texto = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", texto)
    texto = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', texto)
    return texto


def a_html(markdown: str) -> str:
    salida, parrafo, lista = [], [], None
    en_codigo, codigo = False, []

    def cerrar_parrafo():
        if parrafo:
            salida.append("<p>" + _en_linea(" ".join(parrafo)) + "</p>")
            parrafo.clear()

    def cerrar_lista():
        nonlocal lista
        if lista:
            salida.append(f"</{lista}>")
            lista = None

    for linea in markdown.splitlines():
        if linea.strip().startswith("```"):
            if en_codigo:
                salida.append("<pre><code>" + html.escape("\n".join(codigo)) + "</code></pre>")
                codigo, en_codigo = [], False
            else:
                cerrar_parrafo()
                cerrar_lista()
                en_codigo = True
            continue
        if en_codigo:
            codigo.append(linea)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", linea)
        if m:
            cerrar_parrafo()
            cerrar_lista()
            nivel = len(m.group(1))
            salida.append(f"<h{nivel}>{_en_linea(m.group(2).strip())}</h{nivel}>")
            continue
        m = re.match(r"^\s*([-*]|\d+\.)\s+(.*)$", linea)
        if m:
            cerrar_parrafo()
            tipo = "ol" if m.group(1)[0].isdigit() else "ul"
            if lista != tipo:
                cerrar_lista()
                salida.append(f"<{tipo}>")
                lista = tipo
            salida.append(f"<li>{_en_linea(m.group(2))}</li>")
            continue
        if not linea.strip():
            cerrar_parrafo()
            cerrar_lista()
            continue
        cerrar_lista()
        parrafo.append(linea.strip())
    if en_codigo:
        salida.append("<pre><code>" + html.escape("\n".join(codigo)) + "</code></pre>")
    cerrar_parrafo()
    cerrar_lista()
    return "\n".join(salida)
''',
        "sitio/generador.py": r'''
"""Construye el sitio: contenido/*.md → publico/*.html + index.html."""

import html
import shutil
from pathlib import Path

from sitio.markdown import a_html

PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo} · {sitio}</title><link rel="stylesheet" href="estilo.css"></head>
<body><header><a href="index.html">{sitio}</a></header><main>{contenido}</main></body></html>
"""

ESTILO = "body{font-family:system-ui,sans-serif;max-width:46rem;margin:auto;padding:1rem;line-height:1.6}" \
         "header{border-bottom:1px solid #ccc;margin-bottom:1rem}pre{background:#f4f4f4;padding:.8rem;overflow:auto}"


def titulo_de(markdown: str, defecto: str) -> str:
    for linea in markdown.splitlines():
        if linea.startswith("# "):
            return linea[2:].strip()
    return defecto


def construir(contenido: Path, publico: Path, nombre_sitio: str = "__TITULO__") -> list[Path]:
    contenido, publico = Path(contenido), Path(publico)
    if publico.exists():
        shutil.rmtree(publico)
    publico.mkdir(parents=True)
    (publico / "estilo.css").write_text(ESTILO, encoding="utf-8")
    paginas = []
    for md in sorted(contenido.glob("*.md")):
        texto = md.read_text(encoding="utf-8")
        titulo = titulo_de(texto, md.stem)
        destino = publico / f"{md.stem}.html"
        destino.write_text(PLANTILLA.format(titulo=html.escape(titulo), sitio=html.escape(nombre_sitio),
                                            contenido=a_html(texto)), encoding="utf-8")
        paginas.append((titulo, destino))
    indice = "<h1>Páginas</h1><ul>" + "".join(
        f'<li><a href="{d.name}">{html.escape(t)}</a></li>' for t, d in paginas if d.stem != "index") + "</ul>"
    if not (contenido / "index.md").exists():
        (publico / "index.html").write_text(PLANTILLA.format(titulo="Inicio", sitio=html.escape(nombre_sitio),
                                                             contenido=indice), encoding="utf-8")
    return [d for _, d in paginas]
''',
        "sitio/__main__.py": r'''
"""Uso: python3 -m sitio [contenido] [publico]   y después: python3 -m http.server -d publico"""

import sys
from pathlib import Path

from sitio.generador import construir

args = sys.argv[1:]
paginas = construir(Path(args[0] if args else "contenido"), Path(args[1] if len(args) > 1 else "publico"))
print(f"{len(paginas)} páginas generadas")
''',
        "contenido/bienvenida.md": "# Bienvenida\n\nEste sitio se generó con **REAPER**.\n\n- rápido\n- sin dependencias\n",
        "tests/__init__.py": "",
        "tests/test_sitio.py": r'''
import tempfile
import unittest
from pathlib import Path

from sitio.generador import construir, titulo_de
from sitio.markdown import a_html


class TestMarkdown(unittest.TestCase):
    def test_bloques(self):
        html = a_html("# Título\n\nUn **párrafo** con `código` y [link](http://x).\n\n- a\n- b\n\n1. uno\n")
        self.assertIn("<h1>Título</h1>", html)
        self.assertIn("<strong>párrafo</strong>", html)
        self.assertIn("<code>código</code>", html)
        self.assertIn('<a href="http://x">link</a>', html)
        self.assertIn("<ul>\n<li>a</li>\n<li>b</li>\n</ul>", html)
        self.assertIn("<ol>", html)

    def test_codigo_escapado(self):
        html = a_html("```\n<script>alert(1)</script>\n```")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_titulo(self):
        self.assertEqual(titulo_de("texto\n# Hola\n", "x"), "Hola")
        self.assertEqual(titulo_de("sin título", "defecto"), "defecto")


class TestGenerador(unittest.TestCase):
    def test_construir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "c").mkdir()
            (base / "c" / "a.md").write_text("# Página A\n\nhola", encoding="utf-8")
            paginas = construir(base / "c", base / "p", "Mi sitio")
            self.assertEqual([p.name for p in paginas], ["a.html"])
            indice = (base / "p" / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="a.html"', indice)
            self.assertTrue((base / "p" / "estilo.css").exists())


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m sitio && python3 -m http.server -d publico 8080",
    etiquetas=("sitio", "web", "estatico", "blog", "markdown", "html", "generador", "pagina"),
)

# ======================================================================
# termux-api
# ======================================================================
registrar_plantilla(
    "termux-api",
    "Envoltorio Python de termux-api (notificaciones, toast, portapapeles, batería, vibración, TTS) con tests sin Android.",
    "python",
    {
        "termuxapi/__init__.py": "",
        "termuxapi/api.py": r'''
"""Llamadas a los comandos termux-* con errores claros. El ejecutor es inyectable para testear."""

import json
import shutil
import subprocess
from typing import Callable, Optional

Ejecutor = Callable[[list, Optional[str]], str]


class ErrorTermuxAPI(RuntimeError):
    pass


def ejecutor_real(args: list, entrada: Optional[str] = None) -> str:
    if not shutil.which(args[0]):
        raise ErrorTermuxAPI(f"falta {args[0]}: pkg install termux-api (y la app Termux:API de F-Droid)")
    try:
        r = subprocess.run(args, input=entrada, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise ErrorTermuxAPI(f"{args[0]} no respondió (¿la app Termux:API tiene permisos?)") from None
    if r.returncode != 0:
        raise ErrorTermuxAPI(f"{args[0]} falló: {r.stderr.strip()[:200]}")
    return r.stdout


class TermuxAPI:
    def __init__(self, ejecutor: Ejecutor = ejecutor_real):
        self._ejecutar = ejecutor

    def notificar(self, titulo: str, texto: str, id_: str = "app") -> None:
        self._ejecutar(["termux-notification", "--id", id_, "--title", titulo, "--content", texto], None)

    def toast(self, texto: str, corto: bool = True) -> None:
        args = ["termux-toast"] + (["-s"] if corto else []) + [texto]
        self._ejecutar(args, None)

    def copiar(self, texto: str) -> None:
        self._ejecutar(["termux-clipboard-set"], texto)

    def pegar(self) -> str:
        return self._ejecutar(["termux-clipboard-get"], None)

    def bateria(self) -> dict:
        datos = json.loads(self._ejecutar(["termux-battery-status"], None) or "{}")
        return {"porcentaje": datos.get("percentage"), "estado": datos.get("status"),
                "temperatura": datos.get("temperature"), "enchufado": datos.get("plugged") not in (None, "UNPLUGGED")}

    def vibrar(self, ms: int = 300) -> None:
        if not 1 <= ms <= 5000:
            raise ValueError("la vibración va de 1 a 5000 ms")
        self._ejecutar(["termux-vibrate", "-d", str(ms)], None)

    def hablar(self, texto: str) -> None:
        self._ejecutar(["termux-tts-speak"], texto)
''',
        "termuxapi/__main__.py": r'''
"""Demo: python3 -m termuxapi"""

from termuxapi.api import ErrorTermuxAPI, TermuxAPI

api = TermuxAPI()
try:
    b = api.bateria()
    api.notificar("__TITULO__", f"Batería: {b['porcentaje']}% ({b['estado']})")
    print("notificación enviada")
except ErrorTermuxAPI as e:
    print(f"no disponible: {e}")
''',
        "tests/__init__.py": "",
        "tests/test_api.py": r'''
import json
import unittest

from termuxapi.api import ErrorTermuxAPI, TermuxAPI


class Falso:
    def __init__(self, respuestas=None):
        self.llamadas = []
        self.respuestas = respuestas or {}

    def __call__(self, args, entrada):
        self.llamadas.append((args, entrada))
        return self.respuestas.get(args[0], "")


class TestTermuxAPI(unittest.TestCase):
    def test_notificar_y_toast(self):
        f = Falso()
        api = TermuxAPI(f)
        api.notificar("T", "hola")
        api.toast("x")
        self.assertEqual(f.llamadas[0][0][:3], ["termux-notification", "--id", "app"])
        self.assertEqual(f.llamadas[1][0], ["termux-toast", "-s", "x"])

    def test_portapapeles(self):
        f = Falso({"termux-clipboard-get": "pegado"})
        api = TermuxAPI(f)
        api.copiar("copiado")
        self.assertEqual(f.llamadas[0], (["termux-clipboard-set"], "copiado"))
        self.assertEqual(api.pegar(), "pegado")

    def test_bateria(self):
        datos = {"percentage": 80, "status": "CHARGING", "plugged": "PLUGGED_USB", "temperature": 30.1}
        b = TermuxAPI(Falso({"termux-battery-status": json.dumps(datos)})).bateria()
        self.assertEqual((b["porcentaje"], b["enchufado"]), (80, True))

    def test_vibrar_valida(self):
        with self.assertRaises(ValueError):
            TermuxAPI(Falso()).vibrar(0)

    def test_error_propagado(self):
        def roto(args, entrada):
            raise ErrorTermuxAPI("falta termux-toast")
        with self.assertRaises(ErrorTermuxAPI):
            TermuxAPI(roto).toast("x")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m termuxapi",
    etiquetas=("termux", "android", "notificacion", "bateria", "portapapeles", "vibrar", "api"),
)

# ======================================================================
# paquete python (pyproject)
# ======================================================================
registrar_plantilla(
    "paquete",
    "Paquete Python instalable (pyproject.toml, layout src/, entry point de consola) con tests.",
    "python",
    {
        "pyproject.toml": r'''
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "__PROYECTO__"
version = "0.1.0"
description = "__TITULO__"
requires-python = ">=3.9"
readme = "README.md"

[project.scripts]
__PROYECTO__ = "__PROYECTO__.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
''',
        "README.md": "# __TITULO__\n\nInstalar en modo desarrollo: `pip install -e .`\n\nUsar: `__PROYECTO__ --ayuda`\n",
        "src/__PROYECTO__/__init__.py": r'''
"""__TITULO__."""

__version__ = "0.1.0"

from __PROYECTO__.nucleo import slugificar, truncar  # noqa: F401
''',
        "src/__PROYECTO__/nucleo.py": r'''
import re
import unicodedata


def slugificar(texto: str, separador: str = "-") -> str:
    """'¡Hola Mundo!' → 'hola-mundo'"""
    normal = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in normal if not unicodedata.combining(c))
    palabras = re.findall(r"[a-z0-9]+", sin_tildes.lower())
    return separador.join(palabras)


def truncar(texto: str, largo: int, sufijo: str = "…") -> str:
    """Corta en el último espacio antes del límite."""
    if largo < len(sufijo) + 1:
        raise ValueError("largo demasiado chico")
    if len(texto) <= largo:
        return texto
    corte = texto[: largo - len(sufijo)]
    espacio = corte.rfind(" ")
    return (corte[:espacio] if espacio > 0 else corte).rstrip() + sufijo
''',
        "src/__PROYECTO__/cli.py": r'''
import argparse
import sys

from __PROYECTO__ import __version__
from __PROYECTO__.nucleo import slugificar, truncar


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="__PROYECTO__")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("slug").add_argument("texto")
    t = sub.add_parser("truncar")
    t.add_argument("texto")
    t.add_argument("largo", type=int)
    args = p.parse_args(argv)
    if args.cmd == "slug":
        print(slugificar(args.texto))
    else:
        try:
            print(truncar(args.texto, args.largo))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    return 0
''',
        "tests/__init__.py": "",
        "tests/test_paquete.py": r'''
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from __PROYECTO__ import slugificar, truncar  # noqa: E402
from __PROYECTO__.cli import main  # noqa: E402


class TestNucleo(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(slugificar("¡Hola, Señor Ñandú!"), "hola-senor-nandu")
        self.assertEqual(slugificar("a b", "_"), "a_b")

    def test_truncar(self):
        self.assertEqual(truncar("hola mundo cruel", 12), "hola mundo…")
        self.assertEqual(truncar("corto", 10), "corto")
        with self.assertRaises(ValueError):
            truncar("x", 1)

    def test_cli(self):
        salida = io.StringIO()
        with redirect_stdout(salida):
            self.assertEqual(main(["slug", "Año Nuevo"]), 0)
        self.assertEqual(salida.getvalue().strip(), "ano-nuevo")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="pip install -e . && __PROYECTO__ slug 'Hola Mundo'",
    etiquetas=("paquete", "libreria", "pyproject", "pip", "instalable", "modulo", "biblioteca"),
)

# ======================================================================
# agenda de contactos
# ======================================================================
registrar_plantilla(
    "agenda",
    "Agenda de contactos con validación de email/teléfono, búsqueda difusa, cumpleaños próximos y exportación vCard.",
    "python",
    {
        "agenda/__init__.py": "",
        "agenda/contactos.py": r'''
"""Contactos con validación, búsqueda tolerante a errores y exportación vCard 3.0."""

import difflib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def normalizar_telefono(texto: str) -> str:
    digitos = re.sub(r"[^\d+]", "", texto)
    if digitos.count("+") > 1 or ("+" in digitos and not digitos.startswith("+")):
        raise ValueError(f"teléfono inválido: {texto}")
    if len(re.sub(r"\D", "", digitos)) < 6:
        raise ValueError(f"teléfono demasiado corto: {texto}")
    return digitos


@dataclass
class Contacto:
    nombre: str
    telefono: str = ""
    email: str = ""
    cumple: Optional[str] = None  # AAAA-MM-DD o MM-DD
    etiquetas: list = field(default_factory=list)

    def __post_init__(self):
        self.nombre = " ".join(self.nombre.split())
        if not self.nombre:
            raise ValueError("el contacto necesita nombre")
        if self.telefono:
            self.telefono = normalizar_telefono(self.telefono)
        if self.email and not _EMAIL.match(self.email.strip()):
            raise ValueError(f"email inválido: {self.email}")
        self.email = self.email.strip().lower()
        if self.cumple:
            self.mes_dia()  # valida

    def mes_dia(self) -> tuple[int, int]:
        partes = self.cumple.split("-")
        mes, dia = int(partes[-2]), int(partes[-1])
        date(2000, mes, dia)  # lanza ValueError si no existe
        return mes, dia

    def dias_para_cumple(self, hoy: date) -> Optional[int]:
        if not self.cumple:
            return None
        mes, dia = self.mes_dia()
        anio = hoy.year
        while True:
            try:
                proximo = date(anio, mes, dia)
            except ValueError:  # 29 de febrero en año no bisiesto
                proximo = date(anio, 3, 1)
            if proximo >= hoy:
                return (proximo - hoy).days
            anio += 1

    def vcard(self) -> str:
        lineas = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{self.nombre}", f"N:{self.nombre};;;;"]
        if self.telefono:
            lineas.append(f"TEL;TYPE=CELL:{self.telefono}")
        if self.email:
            lineas.append(f"EMAIL:{self.email}")
        if self.cumple and len(self.cumple) == 10:
            lineas.append(f"BDAY:{self.cumple}")
        lineas.append("END:VCARD")
        return "\r\n".join(lineas)


class Agenda:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self.contactos: list[Contacto] = []
        if self.ruta.exists():
            self.contactos = [Contacto(**d) for d in json.loads(self.ruta.read_text(encoding="utf-8") or "[]")]

    def guardar(self) -> None:
        self.ruta.write_text(json.dumps([asdict(c) for c in self.contactos], ensure_ascii=False, indent=1),
                             encoding="utf-8")

    def agregar(self, contacto: Contacto) -> Contacto:
        if any(c.nombre.lower() == contacto.nombre.lower() for c in self.contactos):
            raise ValueError(f"ya existe {contacto.nombre}")
        self.contactos.append(contacto)
        return contacto

    def buscar(self, texto: str) -> list[Contacto]:
        texto = texto.lower().strip()
        exactos = [c for c in self.contactos if texto in c.nombre.lower() or texto in c.email or texto in c.telefono]
        if exactos:
            return exactos
        nombres = {c.nombre.lower(): c for c in self.contactos}
        return [nombres[n] for n in difflib.get_close_matches(texto, list(nombres), n=3, cutoff=0.6)]

    def proximos_cumples(self, hoy: date, dias: int = 30) -> list[tuple[int, Contacto]]:
        lista = [(c.dias_para_cumple(hoy), c) for c in self.contactos if c.cumple]
        return sorted([(d, c) for d, c in lista if d is not None and d <= dias], key=lambda t: (t[0], t[1].nombre))

    def exportar_vcf(self, destino: Path) -> int:
        Path(destino).write_text("\r\n".join(c.vcard() for c in self.contactos) + "\r\n", encoding="utf-8")
        return len(self.contactos)
''',
        "agenda/__main__.py": r'''
"""Uso: python3 -m agenda agregar "Nombre" [telefono] [email] [cumple] | buscar texto | cumples | vcf archivo.vcf"""

import os
import sys
from datetime import date
from pathlib import Path

from agenda.contactos import Agenda, Contacto


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    agenda = Agenda(Path(os.environ.get("AGENDA_ARCHIVO", Path.home() / ".agenda.json")))
    try:
        if argv[:1] == ["agregar"] and len(argv) >= 2:
            extras = argv[2:] + ["", "", ""]
            agenda.agregar(Contacto(argv[1], extras[0], extras[1], extras[2] or None))
            agenda.guardar()
            print("contacto agregado")
        elif argv[:1] == ["buscar"] and len(argv) == 2:
            for c in agenda.buscar(argv[1]):
                print(f"{c.nombre}  {c.telefono}  {c.email}")
        elif argv[:1] == ["cumples"]:
            for dias, c in agenda.proximos_cumples(date.today()):
                print(f"{'¡hoy!' if dias == 0 else f'en {dias} días'}: {c.nombre}")
        elif argv[:1] == ["vcf"] and len(argv) == 2:
            print(f"{agenda.exportar_vcf(Path(argv[1]))} contactos exportados")
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


sys.exit(main())
''',
        "tests/__init__.py": "",
        "tests/test_agenda.py": r'''
import tempfile
import unittest
from datetime import date
from pathlib import Path

from agenda.contactos import Agenda, Contacto, normalizar_telefono


class TestContacto(unittest.TestCase):
    def test_validaciones(self):
        self.assertEqual(normalizar_telefono("+54 9 (341) 555-1234"), "+5493415551234")
        for malo in ("12", "54+9"):
            with self.assertRaises(ValueError):
                normalizar_telefono(malo)
        with self.assertRaises(ValueError):
            Contacto("Ana", email="no-es-mail")
        with self.assertRaises(ValueError):
            Contacto("   ")
        with self.assertRaises(ValueError):
            Contacto("Ana", cumple="02-30")

    def test_cumple(self):
        c = Contacto("Leo", cumple="1990-12-25")
        self.assertEqual(c.dias_para_cumple(date(2026, 12, 20)), 5)
        self.assertEqual(c.dias_para_cumple(date(2026, 12, 26)), 364)
        bisiesto = Contacto("Feb", cumple="02-29")
        self.assertEqual(bisiesto.dias_para_cumple(date(2027, 2, 28)), 1)

    def test_vcard(self):
        v = Contacto("Ana Pérez", "123456789", "ANA@x.com", "1990-01-02").vcard()
        self.assertIn("FN:Ana Pérez", v)
        self.assertIn("EMAIL:ana@x.com", v)
        self.assertIn("BDAY:1990-01-02", v)


class TestAgenda(unittest.TestCase):
    def test_flujo(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "a.json"
            a = Agenda(ruta)
            a.agregar(Contacto("Ana Gómez", "3415551234", cumple="05-10"))
            a.agregar(Contacto("Bruno Díaz", email="b@d.com", cumple="05-02"))
            with self.assertRaises(ValueError):
                a.agregar(Contacto("ana gómez"))
            a.guardar()
            b = Agenda(ruta)
            self.assertEqual([c.nombre for c in b.buscar("ana")], ["Ana Gómez"])
            self.assertEqual([c.nombre for c in b.buscar("bruno dias")], ["Bruno Díaz"])
            proximos = b.proximos_cumples(date(2026, 5, 1), dias=15)
            self.assertEqual([c.nombre for _, c in proximos], ["Bruno Díaz", "Ana Gómez"])
            self.assertEqual(b.exportar_vcf(Path(tmp) / "x.vcf"), 2)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar='python3 -m agenda agregar "Ana" 3415551234 ana@mail.com 05-10',
    etiquetas=("agenda", "contactos", "telefono", "email", "cumpleaños", "vcard"),
)

# ======================================================================
# planificador tipo cron
# ======================================================================
registrar_plantilla(
    "cron",
    "Planificador de tareas en Python con expresiones cron (*/5, rangos, listas), próximo disparo y ejecución en bucle.",
    "python",
    {
        "cron/__init__.py": "",
        "cron/expresion.py": r'''
"""Parser de expresiones cron de 5 campos y cálculo del próximo disparo."""

from dataclasses import dataclass
from datetime import datetime, timedelta

RANGOS = [("minuto", 0, 59), ("hora", 0, 23), ("dia", 1, 31), ("mes", 1, 12), ("semana", 0, 6)]
ALIAS = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *",
         "@cadahora": "0 * * * *", "@diario": "0 0 * * *"}


def parsear_campo(texto: str, minimo: int, maximo: int, nombre: str) -> frozenset:
    valores = set()
    for parte in texto.split(","):
        paso = 1
        if "/" in parte:
            parte, paso_txt = parte.split("/", 1)
            if not paso_txt.isdigit() or int(paso_txt) < 1:
                raise ValueError(f"paso inválido en {nombre}: {paso_txt}")
            paso = int(paso_txt)
        if parte in ("*", ""):
            inicio, fin = minimo, maximo
        elif "-" in parte:
            a, b = parte.split("-", 1)
            inicio, fin = int(a), int(b)
        else:
            inicio = fin = int(parte)
            if paso > 1:
                fin = maximo
        if not (minimo <= inicio <= maximo and minimo <= fin <= maximo and inicio <= fin):
            raise ValueError(f"{nombre} fuera de rango ({minimo}-{maximo}): {parte}")
        valores.update(range(inicio, fin + 1, paso))
    return frozenset(valores)


@dataclass(frozen=True)
class Cron:
    minutos: frozenset
    horas: frozenset
    dias: frozenset
    meses: frozenset
    semana: frozenset
    texto: str

    @classmethod
    def parsear(cls, texto: str) -> "Cron":
        expresion = ALIAS.get(texto.strip(), texto.strip())
        campos = expresion.split()
        if len(campos) != 5:
            raise ValueError("una expresión cron tiene 5 campos: minuto hora día mes día_semana")
        conjuntos = []
        for valor, (nombre, minimo, maximo) in zip(campos, RANGOS):
            try:
                conjuntos.append(parsear_campo(valor, minimo, maximo, nombre))
            except ValueError as e:
                raise ValueError(str(e)) from None
        return cls(*conjuntos, texto)

    def coincide(self, momento: datetime) -> bool:
        dia_semana = (momento.weekday() + 1) % 7  # cron: 0 = domingo
        return (momento.minute in self.minutos and momento.hour in self.horas and momento.month in self.meses
                and momento.day in self.dias and dia_semana in self.semana)

    def proximo(self, desde: datetime, limite_dias: int = 366 * 4) -> datetime:
        momento = desde.replace(second=0, microsecond=0) + timedelta(minutes=1)
        fin = desde + timedelta(days=limite_dias)
        while momento <= fin:
            if momento.month not in self.meses:
                momento = (momento.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
                continue
            if momento.day not in self.dias or (momento.weekday() + 1) % 7 not in self.semana:
                momento = momento.replace(hour=0, minute=0) + timedelta(days=1)
                continue
            if momento.hour not in self.horas:
                momento = momento.replace(minute=0) + timedelta(hours=1)
                continue
            if momento.minute in self.minutos:
                return momento
            momento += timedelta(minutes=1)
        raise ValueError(f"la expresión {self.texto} no se dispara en {limite_dias} días")
''',
        "cron/planificador.py": r'''
"""Planificador en proceso: registra funciones con expresiones cron y las corre a su hora."""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from cron.expresion import Cron


@dataclass
class Trabajo:
    nombre: str
    cron: Cron
    funcion: Callable[[], object]
    proximo: datetime
    ejecuciones: int = 0
    ultimo_error: str = ""


class Planificador:
    def __init__(self, ahora: Callable[[], datetime] = datetime.now):
        self.ahora = ahora
        self.trabajos: list[Trabajo] = []

    def agregar(self, nombre: str, expresion: str, funcion: Callable[[], object]) -> Trabajo:
        cron = Cron.parsear(expresion)
        trabajo = Trabajo(nombre, cron, funcion, cron.proximo(self.ahora()))
        self.trabajos.append(trabajo)
        return trabajo

    def pendientes(self) -> list[Trabajo]:
        ahora = self.ahora()
        return [t for t in self.trabajos if t.proximo <= ahora]

    def tick(self) -> list[str]:
        """Corre lo que toca. Un trabajo que falla no frena a los demás."""
        ejecutados = []
        for t in self.pendientes():
            try:
                t.funcion()
                t.ultimo_error = ""
            except Exception as e:  # se registra y se sigue
                t.ultimo_error = f"{type(e).__name__}: {e}"
            t.ejecuciones += 1
            t.proximo = t.cron.proximo(self.ahora())
            ejecutados.append(t.nombre)
        return ejecutados

    def correr(self, intervalo: float = 20.0) -> None:
        while True:
            self.tick()
            time.sleep(intervalo)
''',
        "cron/__main__.py": r'''
"""Demo: python3 -m cron "*/5 * * * *"  → muestra los próximos 5 disparos"""

import sys
from datetime import datetime

from cron.expresion import Cron

expresion = " ".join(sys.argv[1:]) or "*/15 9-18 * * 1-5"
try:
    c = Cron.parsear(expresion)
except ValueError as e:
    sys.exit(f"error: {e}")
momento = datetime.now()
for _ in range(5):
    momento = c.proximo(momento)
    print(momento.strftime("%a %Y-%m-%d %H:%M"))
''',
        "tests/__init__.py": "",
        "tests/test_cron.py": r'''
import unittest
from datetime import datetime

from cron.expresion import Cron, parsear_campo
from cron.planificador import Planificador


class TestExpresion(unittest.TestCase):
    def test_campos(self):
        self.assertEqual(parsear_campo("*/15", 0, 59, "m"), frozenset({0, 15, 30, 45}))
        self.assertEqual(parsear_campo("1-3,10", 0, 59, "m"), frozenset({1, 2, 3, 10}))
        self.assertEqual(parsear_campo("5/20", 0, 59, "m"), frozenset({5, 25, 45}))
        for malo in ("70", "5-2", "*/0"):
            with self.assertRaises(ValueError):
                parsear_campo(malo, 0, 59, "m")

    def test_proximo(self):
        c = Cron.parsear("30 9 * * 1-5")
        self.assertEqual(c.proximo(datetime(2026, 10, 2, 10, 0)), datetime(2026, 10, 5, 9, 30))  # viernes → lunes
        self.assertEqual(Cron.parsear("@daily").proximo(datetime(2026, 1, 31, 23, 59)), datetime(2026, 2, 1, 0, 0))
        self.assertEqual(Cron.parsear("0 0 29 2 *").proximo(datetime(2026, 3, 1)), datetime(2028, 2, 29, 0, 0))

    def test_coincide_y_errores(self):
        self.assertTrue(Cron.parsear("* * * * 0").coincide(datetime(2026, 10, 4, 12, 0)))  # domingo
        with self.assertRaises(ValueError):
            Cron.parsear("* * *")


class TestPlanificador(unittest.TestCase):
    def test_tick(self):
        ahora = [datetime(2026, 1, 1, 10, 0, 30)]
        p = Planificador(lambda: ahora[0])
        corridas = []
        p.agregar("cada5", "*/5 * * * *", lambda: corridas.append(1))
        p.agregar("roto", "* * * * *", lambda: 1 / 0)
        self.assertEqual(p.tick(), [])
        ahora[0] = datetime(2026, 1, 1, 10, 5)
        self.assertEqual(sorted(p.tick()), ["cada5", "roto"])
        self.assertEqual(corridas, [1])
        self.assertIn("ZeroDivisionError", p.trabajos[1].ultimo_error)
        self.assertEqual(p.trabajos[0].proximo, datetime(2026, 1, 1, 10, 10))


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar='python3 -m cron "*/5 * * * *"',
    etiquetas=("cron", "planificador", "programar", "tareas", "horario", "scheduler", "automatizar"),
)
