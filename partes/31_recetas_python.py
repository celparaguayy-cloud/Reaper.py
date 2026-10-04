"""
Más recetas de Python. Cada una es un programa COMPLETO: al ejecutarlo corre una demo con asserts,
así que el autotest no solo las compila: las ejecuta (las marcadas como ejecutables) y verifica que
el ejemplo que ve el modelo funciona de verdad.
"""

RECETAS_EJECUTABLES: set = set()


def receta_ejecutable(titulo: str, lenguaje: str, etiquetas: str, descripcion: str, codigo: str) -> Receta:
    r = receta(titulo, lenguaje, etiquetas, descripcion, codigo)
    RECETAS_EJECUTABLES.add(titulo)
    return r


receta_ejecutable("Caché en disco con vencimiento (TTL)", "python", "cache, cachear, ttl, vencimiento, memoizar, guardar",
                  "Guarda resultados caros (llamadas a APIs) en JSON con fecha de vencimiento.", r'''
import json
import time
from pathlib import Path


class CacheDisco:
    def __init__(self, ruta: Path, ttl_segundos: float):
        self.ruta = Path(ruta)
        self.ttl = ttl_segundos
        try:
            self.datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.datos = {}

    def obtener(self, clave: str, ahora: float | None = None):
        ahora = time.time() if ahora is None else ahora
        entrada = self.datos.get(clave)
        if entrada is None or ahora - entrada["t"] > self.ttl:
            return None
        return entrada["v"]

    def guardar(self, clave: str, valor, ahora: float | None = None) -> None:
        self.datos[clave] = {"t": time.time() if ahora is None else ahora, "v": valor}
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.datos, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.ruta)

    def o_calcular(self, clave: str, funcion):
        valor = self.obtener(clave)
        if valor is None:
            valor = funcion()
            self.guardar(clave, valor)
        return valor


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        c = CacheDisco(Path(d) / "cache.json", ttl_segundos=60)
        llamadas = []
        assert c.o_calcular("clima", lambda: llamadas.append(1) or {"temp": 21}) == {"temp": 21}
        assert c.o_calcular("clima", lambda: llamadas.append(1) or {"temp": 99}) == {"temp": 21}
        assert len(llamadas) == 1
        c.guardar("viejo", 1, ahora=0)
        assert c.obtener("viejo", ahora=61) is None          # venció
        assert CacheDisco(Path(d) / "cache.json", 60).obtener("clima") == {"temp": 21}  # persiste
        print("ok")
''')

receta_ejecutable("Limitador de tasa (token bucket)", "python", "limite, tasa, rate limit, rpm, throttle, api, peticiones",
                  "Permite ráfagas cortas pero respeta N operaciones por segundo; seguro entre hilos.", r'''
import threading
import time


EPS = 1e-9  # tolerancia: 0.6 - 0.5 da 0.0999...; sin esto el bucle de esperar() puede no terminar nunca


class LimitadorTasa:
    def __init__(self, por_segundo: float, rafaga: int = 1, reloj=time.monotonic, dormir=time.sleep):
        self.tasa = por_segundo
        self.capacidad = rafaga
        self.fichas = float(rafaga)
        self.reloj = reloj
        self.dormir = dormir
        self.ultimo = reloj()
        self.lock = threading.Lock()

    def _recargar(self) -> None:
        ahora = self.reloj()
        self.fichas = min(self.capacidad, self.fichas + (ahora - self.ultimo) * self.tasa)
        self.ultimo = ahora

    def intentar(self) -> bool:
        with self.lock:
            self._recargar()
            if self.fichas >= 1 - EPS:
                self.fichas = max(0.0, self.fichas - 1)
                return True
            return False

    def esperar(self) -> None:
        while True:
            with self.lock:
                self._recargar()
                if self.fichas >= 1 - EPS:
                    self.fichas = max(0.0, self.fichas - 1)
                    return
                falta = max((1 - self.fichas) / self.tasa, 0.001)
            self.dormir(falta)


if __name__ == "__main__":
    t = [0.0]
    lim = LimitadorTasa(2, rafaga=3, reloj=lambda: t[0])
    assert [lim.intentar() for _ in range(4)] == [True, True, True, False]   # ráfaga de 3
    t[0] += 0.5                                                              # medio segundo = 1 ficha
    assert lim.intentar() and not lim.intentar()
    dormido = []
    lim2 = LimitadorTasa(10, reloj=lambda: t[0], dormir=lambda s: (dormido.append(s), t.__setitem__(0, t[0] + s)))
    lim2.esperar(); lim2.esperar()
    assert abs(sum(dormido) - 0.1) < 1e-9
    print("ok")
''')

receta_ejecutable("Vigilar cambios en archivos (polling)", "python", "vigilar, cambios, watch, archivos, recargar, monitorear",
                  "Detecta archivos nuevos, modificados y borrados comparando fechas; sin dependencias.", r'''
import os
from pathlib import Path


def instantanea(carpeta: Path, patron: str = "*") -> dict[str, tuple[int, int]]:
    salida = {}
    for ruta in Path(carpeta).rglob(patron):
        if ruta.is_file() and "__pycache__" not in ruta.parts:
            st = ruta.stat()
            salida[str(ruta.relative_to(carpeta))] = (st.st_mtime_ns, st.st_size)
    return salida


def diferencias(antes: dict, despues: dict) -> dict[str, list[str]]:
    return {
        "nuevos": sorted(set(despues) - set(antes)),
        "borrados": sorted(set(antes) - set(despues)),
        "modificados": sorted(k for k in set(antes) & set(despues) if antes[k] != despues[k]),
    }


def vigilar(carpeta: Path, al_cambiar, intervalo: float = 1.0, patron: str = "*", vueltas: int | None = None):
    import time
    previa = instantanea(carpeta, patron)
    n = 0
    while vueltas is None or n < vueltas:
        time.sleep(intervalo)
        actual = instantanea(carpeta, patron)
        cambios = diferencias(previa, actual)
        if any(cambios.values()):
            al_cambiar(cambios)
        previa = actual
        n += 1


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "a.txt").write_text("1")
        (base / "b.txt").write_text("1")
        antes = instantanea(base)
        (base / "a.txt").write_text("12")
        os.utime(base / "a.txt", ns=(1, 1))
        (base / "b.txt").unlink()
        (base / "c.txt").write_text("nuevo")
        cambios = diferencias(antes, instantanea(base))
        assert cambios == {"nuevos": ["c.txt"], "borrados": ["b.txt"], "modificados": ["a.txt"]}, cambios
        print("ok")
''')

receta_ejecutable("Contraseñas: hash seguro y verificación", "python", "contraseña, password, hash, login, usuario, seguridad, pbkdf2",
                  "PBKDF2 con sal aleatoria (librería estándar) y comparación en tiempo constante.", r'''
import base64
import hashlib
import hmac
import secrets

ITERACIONES = 200_000


def hashear(password: str, iteraciones: int = ITERACIONES) -> str:
    sal = secrets.token_bytes(16)
    clave = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, iteraciones)
    return "pbkdf2_sha256${}${}${}".format(
        iteraciones, base64.b64encode(sal).decode(), base64.b64encode(clave).decode())


def verificar(password: str, guardado: str) -> bool:
    try:
        algoritmo, iteraciones, sal_b64, clave_b64 = guardado.split("$")
    except ValueError:
        return False
    if algoritmo != "pbkdf2_sha256":
        return False
    sal = base64.b64decode(sal_b64)
    esperado = base64.b64decode(clave_b64)
    calculado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, int(iteraciones))
    return hmac.compare_digest(calculado, esperado)


def token_sesion() -> str:
    return secrets.token_urlsafe(32)


if __name__ == "__main__":
    h = hashear("mate123", iteraciones=1000)
    assert verificar("mate123", h)
    assert not verificar("mate124", h)
    assert hashear("mate123", 1000) != h          # sal distinta cada vez
    assert not verificar("x", "basura")
    assert len(token_sesion()) >= 40
    print("ok")
''')

receta_ejecutable("Leer un archivo .env sin dependencias", "python", "env, dotenv, configuracion, variables, entorno, secretos",
                  "KEY=valor, comillas, comentarios y export; no pisa variables ya definidas.", r'''
import os
import re
from pathlib import Path

_LINEA = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def leer_env(texto: str) -> dict[str, str]:
    valores = {}
    for linea in texto.splitlines():
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        m = _LINEA.match(linea)
        if not m:
            continue
        clave, valor = m.group(1), m.group(2).strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
            valor = valor[1:-1]
            if m.group(2).strip()[0] == '"':
                valor = valor.replace("\\n", "\n")
        else:
            valor = re.sub(r"\s+#.*$", "", valor)
        valores[clave] = valor
    return valores


def cargar_env(ruta: Path = Path(".env"), pisar: bool = False) -> dict[str, str]:
    try:
        valores = leer_env(Path(ruta).read_text(encoding="utf-8"))
    except OSError:
        return {}
    for clave, valor in valores.items():
        if pisar or clave not in os.environ:
            os.environ[clave] = valor
    return valores


if __name__ == "__main__":
    v = leer_env('# comentario\nexport TOKEN="abc def"\nPUERTO=8080  # puerto\nVACIO=\nMULTI="a\\nb"\nmal linea\n')
    assert v == {"TOKEN": "abc def", "PUERTO": "8080", "VACIO": "", "MULTI": "a\nb"}, v
    print("ok")
''')

receta_ejecutable("Máquina de estados simple", "python", "estados, maquina, transiciones, flujo, pedido, workflow",
                  "Transiciones permitidas explícitas, historial y error claro si la transición no vale.", r'''
from dataclasses import dataclass, field


class TransicionInvalida(Exception):
    pass


@dataclass
class Pedido:
    TRANSICIONES = {
        "nuevo": {"pagado", "cancelado"},
        "pagado": {"enviado", "cancelado"},
        "enviado": {"entregado"},
        "entregado": set(),
        "cancelado": set(),
    }
    estado: str = "nuevo"
    historial: list = field(default_factory=list)

    def pasar_a(self, nuevo: str) -> None:
        permitidos = self.TRANSICIONES.get(self.estado, set())
        if nuevo not in permitidos:
            opciones = ", ".join(sorted(permitidos)) or "ninguno (estado final)"
            raise TransicionInvalida(f"no se puede pasar de {self.estado} a {nuevo}; opciones: {opciones}")
        self.historial.append((self.estado, nuevo))
        self.estado = nuevo

    @property
    def terminado(self) -> bool:
        return not self.TRANSICIONES[self.estado]


if __name__ == "__main__":
    p = Pedido()
    p.pasar_a("pagado"); p.pasar_a("enviado"); p.pasar_a("entregado")
    assert p.terminado and len(p.historial) == 3
    try:
        Pedido().pasar_a("enviado")
        raise AssertionError("debía fallar")
    except TransicionInvalida as e:
        assert "opciones: cancelado, pagado" in str(e)
    print("ok")
''')

receta_ejecutable("Cola de prioridad con heapq", "python", "cola, prioridad, heap, heapq, tareas, ordenar, scheduler",
                  "Desempata por orden de llegada (estable) y permite cancelar tareas.", r'''
import heapq
import itertools


class ColaPrioridad:
    def __init__(self):
        self._heap = []
        self._contador = itertools.count()
        self._entradas = {}

    def agregar(self, tarea, prioridad: int = 0) -> None:
        if tarea in self._entradas:
            self.cancelar(tarea)
        entrada = [-prioridad, next(self._contador), tarea, True]
        self._entradas[tarea] = entrada
        heapq.heappush(self._heap, entrada)

    def cancelar(self, tarea) -> None:
        entrada = self._entradas.pop(tarea)
        entrada[3] = False

    def sacar(self):
        while self._heap:
            _p, _n, tarea, viva = heapq.heappop(self._heap)
            if viva:
                del self._entradas[tarea]
                return tarea
        raise IndexError("cola vacía")

    def __len__(self) -> int:
        return len(self._entradas)


if __name__ == "__main__":
    c = ColaPrioridad()
    c.agregar("lavar", 1); c.agregar("pagar luz", 5); c.agregar("leer", 1); c.agregar("urgente", 9)
    c.cancelar("urgente")
    c.agregar("leer", 3)                      # re-prioriza
    assert [c.sacar() for _ in range(len(c))] == ["pagar luz", "leer", "lavar"]
    print("ok")
''')

receta_ejecutable("Eventos: publicar y suscribirse", "python", "eventos, observer, suscribir, publicar, callback, bus",
                  "Bus de eventos mínimo; un suscriptor que falla no rompe a los demás.", r'''
from collections import defaultdict


class BusEventos:
    def __init__(self):
        self._suscriptores = defaultdict(list)
        self.errores = []

    def suscribir(self, evento: str, funcion):
        self._suscriptores[evento].append(funcion)
        return lambda: self._suscriptores[evento].remove(funcion)   # para desuscribirse

    def publicar(self, evento: str, **datos) -> int:
        llamados = 0
        for funcion in list(self._suscriptores[evento]):
            try:
                funcion(**datos)
                llamados += 1
            except Exception as e:  # se registra y se sigue con el resto
                self.errores.append((evento, funcion.__name__, repr(e)))
        return llamados


if __name__ == "__main__":
    bus = BusEventos()
    recibidos = []
    def anotar(**d): recibidos.append(d)
    def roto(**d): raise ValueError("ups")
    desuscribir = bus.suscribir("venta", anotar)
    bus.suscribir("venta", roto)
    assert bus.publicar("venta", total=100) == 1
    assert recibidos == [{"total": 100}] and bus.errores[0][1] == "roto"
    desuscribir()
    assert bus.publicar("venta", total=5) == 0
    print("ok")
''')

receta_ejecutable("Dataclass a JSON y de vuelta (con validación)", "python", "dataclass, json, serializar, modelo, validar, dict",
                  "asdict para guardar; constructor desde dict que ignora claves extra y valida tipos básicos.", r'''
import json
from dataclasses import asdict, dataclass, field, fields
from datetime import date


@dataclass
class Contacto:
    nombre: str
    email: str = ""
    nacimiento: date | None = None
    etiquetas: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.nombre.strip():
            raise ValueError("nombre vacío")
        if self.email and "@" not in self.email:
            raise ValueError(f"email inválido: {self.email}")

    def a_dict(self) -> dict:
        d = asdict(self)
        d["nacimiento"] = self.nacimiento.isoformat() if self.nacimiento else None
        return d

    @classmethod
    def desde_dict(cls, d: dict) -> "Contacto":
        conocidos = {f.name for f in fields(cls)}
        datos = {k: v for k, v in d.items() if k in conocidos}
        if datos.get("nacimiento"):
            datos["nacimiento"] = date.fromisoformat(datos["nacimiento"])
        return cls(**datos)


if __name__ == "__main__":
    c = Contacto("Ana", "ana@mail.com", date(1990, 5, 1), ["familia"])
    texto = json.dumps(c.a_dict())
    assert Contacto.desde_dict(json.loads(texto) | {"campo_viejo": 1}) == c
    for malo in ({"nombre": " "}, {"nombre": "x", "email": "sin-arroba"}):
        try:
            Contacto.desde_dict(malo)
            raise AssertionError("debía fallar")
        except ValueError:
            pass
    print("ok")
''')

receta_ejecutable("Tamaño de carpetas y archivos más grandes", "python", "disco, espacio, tamaño, carpetas, archivos grandes, limpiar",
                  "Recorre con os.scandir (rápido) y muestra tamaños legibles; útil para liberar espacio en el celular.", r'''
import heapq
import os
from pathlib import Path


def legible(n: float) -> str:
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unidad}" if unidad == "B" else f"{n:.1f} {unidad}"
        n /= 1024
    return f"{n:.1f} TB"


def recorrer(carpeta: Path):
    pila = [Path(carpeta)]
    while pila:
        actual = pila.pop()
        try:
            with os.scandir(actual) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        pila.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False):
                        yield Path(e.path), e.stat(follow_symlinks=False).st_size
        except PermissionError:
            continue


def resumen(carpeta: Path, top: int = 5) -> tuple[int, list[tuple[int, str]]]:
    total = 0
    grandes = []
    for ruta, tam in recorrer(carpeta):
        total += tam
        heapq.heappush(grandes, (tam, str(ruta)))
        if len(grandes) > top:
            heapq.heappop(grandes)
    return total, sorted(grandes, reverse=True)


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "sub").mkdir()
        (base / "a.bin").write_bytes(b"x" * 3000)
        (base / "sub" / "b.bin").write_bytes(b"x" * 100)
        total, grandes = resumen(base, top=1)
        assert total == 3100 and grandes[0][1].endswith("a.bin")
        assert legible(3100) == "3.0 KB" and legible(5) == "5 B"
        print("ok")
''')

receta_ejecutable("Comprimir y extraer zip de forma segura", "python", "zip, comprimir, descomprimir, backup, respaldo, archivo",
                  "Crea zips de una carpeta y extrae evitando rutas peligrosas (../) del 'zip slip'.", r'''
import zipfile
from pathlib import Path


def comprimir(carpeta: Path, destino: Path, ignorar=("__pycache__", ".git")) -> int:
    carpeta, n = Path(carpeta), 0
    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for ruta in sorted(carpeta.rglob("*")):
            if ruta.is_file() and not any(p in ruta.parts for p in ignorar):
                z.write(ruta, ruta.relative_to(carpeta).as_posix())
                n += 1
    return n


def extraer_seguro(zip_ruta: Path, destino: Path) -> list[str]:
    destino = Path(destino).resolve()
    extraidos = []
    with zipfile.ZipFile(zip_ruta) as z:
        for info in z.infolist():
            objetivo = (destino / info.filename).resolve()
            if destino not in objetivo.parents and objetivo != destino:
                raise ValueError(f"ruta peligrosa en el zip: {info.filename}")
            z.extract(info, destino)
            extraidos.append(info.filename)
    return extraidos


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "proy" / "src").mkdir(parents=True)
        (base / "proy" / "src" / "a.py").write_text("print(1)")
        (base / "proy" / "__pycache__").mkdir()
        (base / "proy" / "__pycache__" / "x.pyc").write_bytes(b"0")
        assert comprimir(base / "proy", base / "p.zip") == 1
        assert extraer_seguro(base / "p.zip", base / "salida") == ["src/a.py"]
        with zipfile.ZipFile(base / "malo.zip", "w") as z:
            z.writestr("../../fuera.txt", "x")
        try:
            extraer_seguro(base / "malo.zip", base / "salida2")
            raise AssertionError("debía rechazarlo")
        except ValueError:
            pass
        print("ok")
''')

receta_ejecutable("Gráfico de barras en SVG sin librerías", "python", "grafico, svg, barras, chart, estadisticas, visualizar",
                  "Genera un SVG que se abre en el navegador del celular; escala automática y etiquetas escapadas.", r'''
from html import escape


def barras_svg(datos: dict[str, float], ancho: int = 480, alto_barra: int = 26, color: str = "#7c3aed") -> str:
    if not datos:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
    maximo = max(datos.values()) or 1
    margen = 110
    alto = len(datos) * (alto_barra + 8) + 10
    filas = []
    for i, (etiqueta, valor) in enumerate(datos.items()):
        y = 10 + i * (alto_barra + 8)
        largo = max(1, int((ancho - margen - 60) * valor / maximo))
        filas.append(
            f'<text x="{margen - 8}" y="{y + alto_barra * 0.7:.0f}" text-anchor="end" font-size="14">{escape(etiqueta)}</text>'
            f'<rect x="{margen}" y="{y}" width="{largo}" height="{alto_barra}" rx="4" fill="{color}"/>'
            f'<text x="{margen + largo + 6}" y="{y + alto_barra * 0.7:.0f}" font-size="13">{valor:g}</text>'
        )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" font-family="sans-serif">'
            + "".join(filas) + "</svg>")


if __name__ == "__main__":
    svg = barras_svg({"Comida": 120, "Transporte": 45.5, "<Otros>": 0})
    assert svg.count("<rect") == 3 and "&lt;Otros&gt;" in svg and "45.5" in svg
    print("ok")
''')

receta_ejecutable("Gráficos en la terminal (sparkline y barras)", "python", "grafico, terminal, ascii, sparkline, barras, consola",
                  "Visualización rápida de series en la consola de Termux.", r'''
BLOQUES = "▁▂▃▄▅▆▇█"


def sparkline(valores: list[float]) -> str:
    if not valores:
        return ""
    minimo, maximo = min(valores), max(valores)
    rango = (maximo - minimo) or 1
    return "".join(BLOQUES[int((v - minimo) / rango * (len(BLOQUES) - 1))] for v in valores)


def barras(datos: dict[str, float], ancho: int = 30) -> str:
    if not datos:
        return "(sin datos)"
    maximo = max(datos.values()) or 1
    etiqueta = max(len(k) for k in datos)
    return "\n".join(f"{k:<{etiqueta}} {'█' * round(v / maximo * ancho):<{ancho}} {v:g}" for k, v in datos.items())


if __name__ == "__main__":
    assert sparkline([1, 2, 3, 4, 5, 6, 7, 8]) == BLOQUES
    assert sparkline([5, 5]) == "▁▁"
    salida = barras({"lunes": 10, "martes": 5}, ancho=10)
    assert salida.splitlines()[0] == "lunes  ██████████ 10"
    print(salida)
''')

receta_ejecutable("Servidor y cliente TCP con timeout", "python", "socket, tcp, red, cliente, servidor, puerto, chat",
                  "Servidor eco con hilos; el cliente usa timeout para no colgarse nunca.", r'''
import socket
import socketserver
import threading


class Eco(socketserver.StreamRequestHandler):
    def handle(self):
        for linea in self.rfile:
            texto = linea.decode("utf-8", "replace").rstrip("\r\n")
            if texto == "chau":
                self.wfile.write(b"adios\n")
                return
            self.wfile.write(f"eco: {texto}\n".encode("utf-8"))


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def pedir(host: str, puerto: int, lineas: list[str], timeout: float = 3.0) -> list[str]:
    with socket.create_connection((host, puerto), timeout=timeout) as s:
        archivo = s.makefile("rw", encoding="utf-8", newline="\n")
        respuestas = []
        for linea in lineas:
            archivo.write(linea + "\n")
            archivo.flush()
            respuestas.append(archivo.readline().rstrip("\n"))
        return respuestas


if __name__ == "__main__":
    servidor = Servidor(("127.0.0.1", 0), Eco)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        puerto = servidor.server_address[1]
        assert pedir("127.0.0.1", puerto, ["hola", "chau"]) == ["eco: hola", "adios"]
    finally:
        servidor.shutdown()
        servidor.server_close()
    print("ok")
''')

receta_ejecutable("Extraer links y textos de HTML (html.parser)", "python", "html, scraping, links, parsear, extraer, web",
                  "Sin BeautifulSoup: links absolutos, título y texto visible.", r'''
from html.parser import HTMLParser
from urllib.parse import urljoin


class Extractor(HTMLParser):
    def __init__(self, base: str = ""):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.links: list[tuple[str, str]] = []
        self.titulo = ""
        self._en_titulo = False
        self._link_actual = None
        self._texto_link = []
        self._ignorar = 0
        self.texto: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self._ignorar += 1
        elif tag == "title":
            self._en_titulo = True
        elif tag == "a" and attrs.get("href"):
            self._link_actual = urljoin(self.base, attrs["href"])
            self._texto_link = []

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._ignorar:
            self._ignorar -= 1
        elif tag == "title":
            self._en_titulo = False
        elif tag == "a" and self._link_actual:
            self.links.append((self._link_actual, " ".join("".join(self._texto_link).split())))
            self._link_actual = None

    def handle_data(self, data):
        if self._ignorar:
            return
        if self._en_titulo:
            self.titulo += data.strip()
        if self._link_actual is not None:
            self._texto_link.append(data)
        if data.strip():
            self.texto.append(data.strip())


def analizar_html(html: str, base: str = "") -> Extractor:
    e = Extractor(base)
    e.feed(html)
    e.close()
    return e


if __name__ == "__main__":
    e = analizar_html('<html><head><title>Hola</title><script>x=1</script></head><body>'
                      '<a href="/a">Ir &amp; volver</a> <a href="https://y.com">Y</a><p>texto</p></body></html>',
                      base="https://x.com/dir/")
    assert e.titulo == "Hola"
    assert e.links == [("https://x.com/a", "Ir & volver"), ("https://y.com", "Y")]
    assert "x=1" not in " ".join(e.texto) and "texto" in e.texto
    print("ok")
''')

receta_ejecutable("SQLite: migraciones con user_version", "python", "sqlite, migracion, esquema, version, base de datos, tabla",
                  "Cada migración corre una sola vez y en orden; PRAGMA user_version guarda en qué versión está la base.", r'''
import sqlite3

MIGRACIONES = [
    "CREATE TABLE notas (id INTEGER PRIMARY KEY, texto TEXT NOT NULL)",
    "ALTER TABLE notas ADD COLUMN creada TEXT DEFAULT CURRENT_TIMESTAMP",
    "CREATE INDEX idx_notas_creada ON notas(creada)",
]


def migrar(con: sqlite3.Connection) -> int:
    version = con.execute("PRAGMA user_version").fetchone()[0]
    for numero, sql in enumerate(MIGRACIONES[version:], start=version + 1):
        with con:  # cada migración en su transacción
            con.execute(sql)
            con.execute(f"PRAGMA user_version = {numero}")
    return con.execute("PRAGMA user_version").fetchone()[0]


if __name__ == "__main__":
    con = sqlite3.connect(":memory:")
    assert migrar(con) == 3
    assert migrar(con) == 3                     # idempotente
    con.execute("INSERT INTO notas (texto) VALUES (?)", ("hola",))
    assert con.execute("SELECT texto, creada IS NOT NULL FROM notas").fetchone() == ("hola", 1)
    print("ok")
''')

receta_ejecutable("Búsqueda de texto completo con SQLite FTS5", "python", "buscar, busqueda, texto, fts, sqlite, indice, search",
                  "Índice de búsqueda rápido con ranking; cae a LIKE si FTS5 no está compilado.", r'''
import sqlite3


def crear(con: sqlite3.Connection) -> bool:
    try:
        con.execute("CREATE VIRTUAL TABLE docs USING fts5(titulo, cuerpo)")
        return True
    except sqlite3.OperationalError:
        con.execute("CREATE TABLE docs (titulo TEXT, cuerpo TEXT)")
        return False


def buscar(con: sqlite3.Connection, consulta: str, fts: bool, limite: int = 10) -> list[str]:
    if fts:
        terminos = " ".join(f'"{t}"' for t in consulta.split() if t)
        filas = con.execute("SELECT titulo FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?", (terminos, limite))
    else:
        patron = f"%{consulta}%"
        filas = con.execute("SELECT titulo FROM docs WHERE titulo LIKE ? OR cuerpo LIKE ? LIMIT ?",
                            (patron, patron, limite))
    return [f[0] for f in filas]


if __name__ == "__main__":
    con = sqlite3.connect(":memory:")
    fts = crear(con)
    con.executemany("INSERT INTO docs VALUES (?, ?)", [
        ("Receta de mate", "cómo cebar un buen mate"), ("Viaje", "fuimos a la playa"), ("Mate dulce", "con azúcar")])
    assert set(buscar(con, "mate", fts)) == {"Receta de mate", "Mate dulce"}
    assert buscar(con, "playa", fts) == ["Viaje"]
    print("ok", "(fts5)" if fts else "(like)")
''')

receta_ejecutable("Salida limpia con Ctrl+C y señales", "python", "señal, signal, sigterm, ctrl+c, salir, apagar, limpieza",
                  "Captura SIGINT/SIGTERM, termina el trabajo en curso y guarda antes de salir.", r'''
import signal
import threading


class Apagado:
    def __init__(self):
        self.evento = threading.Event()
        self.motivo = ""

    def instalar(self) -> "Apagado":
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._manejar)
        return self

    def _manejar(self, numero, _frame):
        self.motivo = signal.Signals(numero).name
        self.evento.set()

    @property
    def pedido(self) -> bool:
        return self.evento.is_set()


def trabajar(apagado: Apagado, tareas: list[int]) -> list[int]:
    hechas = []
    for t in tareas:
        if apagado.pedido:
            break               # se termina prolijo: lo hecho queda guardado
        hechas.append(t * 2)
    return hechas


if __name__ == "__main__":
    import os
    apagado = Apagado().instalar()
    assert trabajar(apagado, [1, 2]) == [2, 4]
    os.kill(os.getpid(), signal.SIGTERM)
    assert apagado.evento.wait(2) and apagado.motivo == "SIGTERM"
    assert trabajar(apagado, [1, 2]) == []
    print("ok")
''')

receta_ejecutable("Una sola instancia con archivo de lock", "python", "lock, instancia, daemon, bloqueo, fcntl, proceso",
                  "Evita que el mismo script corra dos veces a la vez (útil con cron en Termux).", r'''
import fcntl
import os
from pathlib import Path


class Instancia:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self.archivo = None

    def __enter__(self) -> "Instancia":
        self.archivo = open(self.ruta, "a+")
        try:
            fcntl.flock(self.archivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.archivo.close()
            raise RuntimeError(f"ya hay otra instancia corriendo ({self.ruta})")
        self.archivo.seek(0)
        self.archivo.truncate()
        self.archivo.write(str(os.getpid()))
        self.archivo.flush()
        return self

    def __exit__(self, *exc) -> None:
        fcntl.flock(self.archivo, fcntl.LOCK_UN)
        self.archivo.close()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        lock = Path(d) / "app.lock"
        with Instancia(lock):
            try:
                with Instancia(lock):
                    raise AssertionError("no debía poder entrar")
            except RuntimeError as e:
                assert "otra instancia" in str(e)
        with Instancia(lock):            # liberado: se puede volver a tomar
            pass
    print("ok")
''')

receta_ejecutable("¿Quisiste decir...? (sugerencias con difflib)", "python", "sugerencia, parecido, typo, corregir, fuzzy, buscar",
                  "Sugerir comandos o nombres parecidos cuando el usuario se equivoca.", r'''
import difflib
import unicodedata


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def sugerir(palabra: str, opciones: list[str], n: int = 3, corte: float = 0.6) -> list[str]:
    mapa = {normalizar(o): o for o in opciones}
    return [mapa[c] for c in difflib.get_close_matches(normalizar(palabra), list(mapa), n=n, cutoff=corte)]


def buscar_difuso(consulta: str, opciones: list[str]) -> list[str]:
    q = normalizar(consulta)
    puntuadas = []
    for o in opciones:
        n = normalizar(o)
        puntaje = 1.0 if q in n else difflib.SequenceMatcher(None, q, n).ratio()
        puntuadas.append((puntaje, o))
    return [o for p, o in sorted(puntuadas, key=lambda x: (-x[0], x[1])) if p >= 0.5]


if __name__ == "__main__":
    comandos = ["agregar", "listar", "borrar", "exportar", "configuración"]
    assert sugerir("lsitar", comandos) == ["listar"]
    assert sugerir("configuracion", comandos) == ["configuración"]
    assert sugerir("zzz", comandos) == []
    assert buscar_difuso("expor", comandos)[0] == "exportar"
    print("ok")
''')

receta_ejecutable("Detectar archivos duplicados por hash", "python", "duplicados, hash, sha256, archivos, fotos, limpiar, espacio",
                  "Agrupa por tamaño primero (rápido) y recién después calcula el hash por bloques.", r'''
import hashlib
from collections import defaultdict
from pathlib import Path


def hash_archivo(ruta: Path, bloque: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


def duplicados(carpeta: Path) -> list[list[Path]]:
    por_tamano = defaultdict(list)
    for ruta in Path(carpeta).rglob("*"):
        if ruta.is_file() and not ruta.is_symlink():
            por_tamano[ruta.stat().st_size].append(ruta)
    grupos = []
    for tam, rutas in por_tamano.items():
        if len(rutas) < 2 or tam == 0:
            continue
        por_hash = defaultdict(list)
        for ruta in rutas:
            por_hash[hash_archivo(ruta)].append(ruta)
        grupos.extend(sorted(g) for g in por_hash.values() if len(g) > 1)
    return sorted(grupos)


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "a.jpg").write_bytes(b"foto1")
        (base / "copia.jpg").write_bytes(b"foto1")
        (base / "otra.jpg").write_bytes(b"foto2")
        grupos = duplicados(base)
        assert [[p.name for p in g] for g in grupos] == [["a.jpg", "copia.jpg"]]
        print("ok")
''')

receta_ejecutable("Plantillas de texto con string.Template", "python", "plantilla, template, texto, email, mensaje, reemplazar",
                  "Variables $nombre seguras (safe_substitute no explota si falta una).", r'''
from string import Template

FACTURA = Template("""Hola $cliente,
Tu pedido #$numero por $$${total} está $estado.
""")


def renderizar(plantilla: Template, **valores) -> str:
    return plantilla.safe_substitute(**valores)


def faltantes(plantilla: Template, valores: dict) -> list[str]:
    nombres = {m.group("named") or m.group("braced") for m in plantilla.pattern.finditer(plantilla.template)}
    return sorted(n for n in nombres if n and n not in valores)


if __name__ == "__main__":
    texto = renderizar(FACTURA, cliente="Ana", numero=12, total="1500.00", estado="en camino")
    assert texto == "Hola Ana,\nTu pedido #12 por $1500.00 está en camino.\n", texto
    assert faltantes(FACTURA, {"cliente": "x"}) == ["estado", "numero", "total"]
    print("ok")
''')

receta_ejecutable("Medir tiempos y encontrar lo lento (cProfile)", "python", "rendimiento, lento, profiling, tiempo, optimizar, cprofile",
                  "Cronómetro con contexto y perfilado de una función para ver dónde se va el tiempo.", r'''
import cProfile
import io
import pstats
import time
from contextlib import contextmanager


@contextmanager
def cronometro(nombre: str, resultados: dict | None = None):
    inicio = time.perf_counter()
    try:
        yield
    finally:
        segundos = time.perf_counter() - inicio
        if resultados is not None:
            resultados[nombre] = segundos
        else:
            print(f"{nombre}: {segundos * 1000:.1f} ms")


def perfilar(funcion, *args, top: int = 5, **kwargs) -> tuple[object, str]:
    perfil = cProfile.Profile()
    resultado = perfil.runcall(funcion, *args, **kwargs)
    salida = io.StringIO()
    pstats.Stats(perfil, stream=salida).sort_stats("cumulative").print_stats(top)
    return resultado, salida.getvalue()


if __name__ == "__main__":
    tiempos = {}
    with cronometro("suma", tiempos):
        sum(range(10000))
    assert tiempos["suma"] >= 0
    def lento(n): return sorted(str(i) for i in range(n))
    resultado, informe = perfilar(lento, 1000)
    assert len(resultado) == 1000 and "function calls" in informe
    print("ok")
''')

receta_ejecutable("Tests parametrizados con subTest", "python", "test, tests, parametrizar, casos, subtest, unittest, tabla",
                  "Una tabla de casos en un solo test; cada caso que falla se informa por separado.", r'''
import unittest


def clasificar_imc(imc: float) -> str:
    if imc <= 0:
        raise ValueError("IMC inválido")
    if imc < 18.5:
        return "bajo peso"
    if imc < 25:
        return "normal"
    if imc < 30:
        return "sobrepeso"
    return "obesidad"


class TestIMC(unittest.TestCase):
    CASOS = [(17.9, "bajo peso"), (18.5, "normal"), (24.99, "normal"), (25, "sobrepeso"), (31, "obesidad")]

    def test_tabla(self):
        for imc, esperado in self.CASOS:
            with self.subTest(imc=imc):
                self.assertEqual(clasificar_imc(imc), esperado)

    def test_invalidos(self):
        for imc in (0, -3):
            with self.subTest(imc=imc), self.assertRaises(ValueError):
                clasificar_imc(imc)


if __name__ == "__main__":
    resultado = unittest.main(argv=["x"], exit=False, verbosity=0).result
    assert resultado.wasSuccessful()
''')

receta_ejecutable("Paginar resultados", "python", "paginar, paginacion, pagina, listado, resultados, limite",
                  "Página con total, cantidad de páginas y navegación; valida números fuera de rango.", r'''
import math
from dataclasses import dataclass


@dataclass
class Pagina:
    items: list
    numero: int
    por_pagina: int
    total: int

    @property
    def paginas(self) -> int:
        return max(1, math.ceil(self.total / self.por_pagina))

    @property
    def tiene_siguiente(self) -> bool:
        return self.numero < self.paginas

    @property
    def tiene_anterior(self) -> bool:
        return self.numero > 1


def paginar(items: list, numero: int = 1, por_pagina: int = 10) -> Pagina:
    if por_pagina < 1:
        raise ValueError("por_pagina debe ser >= 1")
    total = len(items)
    paginas = max(1, math.ceil(total / por_pagina))
    numero = min(max(1, numero), paginas)
    inicio = (numero - 1) * por_pagina
    return Pagina(items[inicio:inicio + por_pagina], numero, por_pagina, total)


if __name__ == "__main__":
    p = paginar(list(range(25)), 3, 10)
    assert p.items == list(range(20, 25)) and p.paginas == 3 and not p.tiene_siguiente and p.tiene_anterior
    assert paginar([], 5).numero == 1 and paginar(list(range(5)), 99, 2).numero == 3
    print("ok")
''')

receta_ejecutable("Probar un programa interactivo con subprocess", "python", "interactivo, input, probar, test, stdin, subprocess, menu, calculadora",
                  "La forma correcta de testear un programa que usa input(): pasarle la entrada, NO quitarle el input().", r'''
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

PROGRAMA = textwrap.dedent("""
    def main():
        while True:
            try:
                texto = input("número (o salir): ")
            except EOFError:
                print("\\nfin de la entrada")
                break
            if texto == "salir":
                print("chau")
                break
            print("doble:", int(texto) * 2)

    if __name__ == "__main__":
        main()
""")


def correr_con_entrada(ruta: Path, entrada: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ruta)], input=entrada, capture_output=True, text=True, timeout=timeout)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        ruta = Path(d) / "app.py"
        ruta.write_text(PROGRAMA)
        r = correr_con_entrada(ruta, "2\n5\nsalir\n")
        assert r.returncode == 0 and "doble: 4" in r.stdout and "doble: 10" in r.stdout and "chau" in r.stdout
        r = correr_con_entrada(ruta, "3\n")                # sin "salir": termina por fin de entrada
        assert "fin de la entrada" in r.stdout and r.returncode == 0
        print("ok")
''')
