"""
Plantillas de Python (tercera tanda): apps útiles con lógica pura testeada, CLI fina y sin dependencias.

  flashcards     repaso espaciado (algoritmo SM-2) con mazos JSON y sesión interactiva
  habitos        hábitos con rachas, SQLite y reporte semanal
  rss            lector RSS/Atom con xml.etree, caché y marcar leídos (tests sin red)
  markdown       conversor Markdown → HTML (subconjunto útil) con escape seguro
  csv-analisis   resumen de un CSV: tipos, nulos, min/max/media, agrupaciones y Markdown
  aventura       motor de aventura de texto con mundo JSON, inventario y guardar/cargar
"""

# ======================================================================
# flashcards
# ======================================================================
registrar_plantilla(
    "flashcards",
    "Tarjetas de estudio con repaso espaciado (SM-2): mazos JSON, sesión interactiva y estadísticas.",
    "python",
    {
        "__PROYECTO__/__init__.py": '"""__TITULO__: tarjetas con repaso espaciado."""\n',
        "__PROYECTO__/sm2.py": '''
            """Algoritmo SM-2 (SuperMemo 2): decide cuándo volver a mostrar cada tarjeta."""
            from __future__ import annotations

            from dataclasses import dataclass, field
            from datetime import date, timedelta


            @dataclass
            class Tarjeta:
                frente: str
                dorso: str
                facilidad: float = 2.5
                intervalo: int = 0          # días
                repeticiones: int = 0
                proxima: date = field(default_factory=date.today)

                def a_dict(self) -> dict:
                    return {"frente": self.frente, "dorso": self.dorso, "facilidad": round(self.facilidad, 3),
                            "intervalo": self.intervalo, "repeticiones": self.repeticiones,
                            "proxima": self.proxima.isoformat()}

                @classmethod
                def desde_dict(cls, d: dict) -> "Tarjeta":
                    return cls(d["frente"], d["dorso"], float(d.get("facilidad", 2.5)), int(d.get("intervalo", 0)),
                               int(d.get("repeticiones", 0)), date.fromisoformat(d.get("proxima") or date.today().isoformat()))


            def calificar(tarjeta: Tarjeta, calidad: int, hoy: date | None = None) -> Tarjeta:
                """
                calidad: 0 (no me acordé) ... 5 (perfecto). Menos de 3 = reinicia la tarjeta.
                Devuelve la misma tarjeta actualizada (también la modifica).
                """
                if not 0 <= calidad <= 5:
                    raise ValueError("la calidad va de 0 a 5")
                hoy = hoy or date.today()
                if calidad < 3:
                    tarjeta.repeticiones = 0
                    tarjeta.intervalo = 1
                else:
                    if tarjeta.repeticiones == 0:
                        tarjeta.intervalo = 1
                    elif tarjeta.repeticiones == 1:
                        tarjeta.intervalo = 6
                    else:
                        tarjeta.intervalo = round(tarjeta.intervalo * tarjeta.facilidad)
                    tarjeta.repeticiones += 1
                tarjeta.facilidad = max(1.3, tarjeta.facilidad + 0.1 - (5 - calidad) * (0.08 + (5 - calidad) * 0.02))
                tarjeta.proxima = hoy + timedelta(days=tarjeta.intervalo)
                return tarjeta


            def pendientes(tarjetas: list[Tarjeta], hoy: date | None = None) -> list[Tarjeta]:
                hoy = hoy or date.today()
                return sorted((t for t in tarjetas if t.proxima <= hoy), key=lambda t: (t.proxima, t.facilidad))
        ''',
        "__PROYECTO__/mazo.py": '''
            """Mazos guardados en JSON (escritura atómica) e importación desde texto 'frente ; dorso'."""
            from __future__ import annotations

            import json
            from datetime import date
            from pathlib import Path

            from .sm2 import Tarjeta, pendientes


            class Mazo:
                def __init__(self, nombre: str, tarjetas: list[Tarjeta] | None = None):
                    self.nombre = nombre
                    self.tarjetas = tarjetas or []

                def agregar(self, frente: str, dorso: str) -> Tarjeta:
                    frente, dorso = frente.strip(), dorso.strip()
                    if not frente or not dorso:
                        raise ValueError("la tarjeta necesita frente y dorso")
                    if any(t.frente.lower() == frente.lower() for t in self.tarjetas):
                        raise ValueError(f"ya existe una tarjeta con frente '{frente}'")
                    t = Tarjeta(frente, dorso)
                    self.tarjetas.append(t)
                    return t

                def importar_texto(self, texto: str, separador: str = ";") -> int:
                    agregadas = 0
                    for linea in texto.splitlines():
                        if separador not in linea or linea.lstrip().startswith("#"):
                            continue
                        frente, dorso = linea.split(separador, 1)
                        try:
                            self.agregar(frente, dorso)
                            agregadas += 1
                        except ValueError:
                            continue
                    return agregadas

                def pendientes(self, hoy: date | None = None) -> list[Tarjeta]:
                    return pendientes(self.tarjetas, hoy)

                def estadisticas(self, hoy: date | None = None) -> dict:
                    hoy = hoy or date.today()
                    total = len(self.tarjetas)
                    aprendidas = sum(1 for t in self.tarjetas if t.repeticiones >= 2)
                    return {"total": total, "pendientes": len(self.pendientes(hoy)), "aprendidas": aprendidas,
                            "nuevas": sum(1 for t in self.tarjetas if t.repeticiones == 0)}

                def guardar(self, ruta: Path) -> None:
                    ruta = Path(ruta)
                    ruta.parent.mkdir(parents=True, exist_ok=True)
                    tmp = ruta.with_suffix(".tmp")
                    datos = {"nombre": self.nombre, "tarjetas": [t.a_dict() for t in self.tarjetas]}
                    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp.replace(ruta)

                @classmethod
                def cargar(cls, ruta: Path) -> "Mazo":
                    ruta = Path(ruta)
                    if not ruta.exists():
                        return cls(ruta.stem)
                    datos = json.loads(ruta.read_text(encoding="utf-8"))
                    return cls(datos.get("nombre", ruta.stem), [Tarjeta.desde_dict(d) for d in datos.get("tarjetas", [])])
        ''',
        "__PROYECTO__/__main__.py": '''
            """
            __TITULO__ — uso:
              python3 -m __PROYECTO__ agregar "capital de Francia" "París"
              python3 -m __PROYECTO__ importar archivo.txt        (líneas 'frente ; dorso')
              python3 -m __PROYECTO__ estudiar                    (sesión interactiva)
              python3 -m __PROYECTO__ estado
            Probar sin teclado: printf 'x\\n4\\n' | python3 -m __PROYECTO__ estudiar
            """
            from __future__ import annotations

            import os
            import sys
            from pathlib import Path

            from .mazo import Mazo
            from .sm2 import calificar

            RUTA = Path(os.environ.get("FLASHCARDS_MAZO", Path.home() / ".__PROYECTO__" / "mazo.json"))


            def estudiar(mazo: Mazo, entrada=input, salida=print) -> int:
                repasadas = 0
                for tarjeta in mazo.pendientes():
                    salida(f"\\n¿{tarjeta.frente}?")
                    try:
                        entrada("(Enter para ver la respuesta) ")
                        salida(f"→ {tarjeta.dorso}")
                        texto = entrada("¿Qué tan bien? 0-5 (q = salir): ").strip().lower()
                    except EOFError:
                        break
                    if texto == "q":
                        break
                    if not texto.isdigit() or not 0 <= int(texto) <= 5:
                        salida("Calificación inválida: la tarjeta queda para después.")
                        continue
                    calificar(tarjeta, int(texto))
                    repasadas += 1
                salida(f"\\nRepasaste {repasadas} tarjeta(s).")
                return repasadas


            def main(argv: list[str] | None = None) -> int:
                args = sys.argv[1:] if argv is None else argv
                mazo = Mazo.cargar(RUTA)
                comando = args[0] if args else "estado"
                if comando == "agregar" and len(args) == 3:
                    mazo.agregar(args[1], args[2])
                elif comando == "importar" and len(args) == 2:
                    print(f"importadas: {mazo.importar_texto(Path(args[1]).read_text(encoding='utf-8'))}")
                elif comando == "estudiar":
                    estudiar(mazo)
                elif comando == "estado":
                    e = mazo.estadisticas()
                    print(f"{e['total']} tarjetas · {e['pendientes']} para hoy · {e['aprendidas']} aprendidas · {e['nuevas']} nuevas")
                    return 0
                else:
                    print(__doc__)
                    return 2
                mazo.guardar(RUTA)
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "tests/test_flashcards.py": '''
            import os
            import subprocess
            import sys
            import tempfile
            import unittest
            from datetime import date, timedelta
            from pathlib import Path

            from __PROYECTO__.mazo import Mazo
            from __PROYECTO__.sm2 import Tarjeta, calificar, pendientes

            HOY = date(2024, 3, 1)


            class TestSM2(unittest.TestCase):
                def test_intervalos_crecen(self):
                    t = Tarjeta("a", "b")
                    intervalos = [calificar(t, 5, HOY).intervalo for _ in range(4)]
                    self.assertEqual(intervalos[:2], [1, 6])
                    self.assertGreater(intervalos[3], intervalos[2])

                def test_olvido_reinicia(self):
                    t = Tarjeta("a", "b")
                    calificar(t, 5, HOY); calificar(t, 5, HOY)
                    calificar(t, 1, HOY)
                    self.assertEqual((t.repeticiones, t.intervalo), (0, 1))
                    self.assertEqual(t.proxima, HOY + timedelta(days=1))

                def test_facilidad_minima(self):
                    t = Tarjeta("a", "b")
                    for _ in range(10):
                        calificar(t, 0, HOY)
                    self.assertAlmostEqual(t.facilidad, 1.3)

                def test_calidad_invalida(self):
                    with self.assertRaises(ValueError):
                        calificar(Tarjeta("a", "b"), 6)

                def test_pendientes_ordenadas(self):
                    a, b, c = Tarjeta("a", "1"), Tarjeta("b", "2"), Tarjeta("c", "3")
                    a.proxima, b.proxima, c.proxima = HOY, HOY - timedelta(days=2), HOY + timedelta(days=1)
                    self.assertEqual([t.frente for t in pendientes([a, b, c], HOY)], ["b", "a"])


            class TestMazo(unittest.TestCase):
                def test_importar_y_duplicados(self):
                    m = Mazo("geo")
                    n = m.importar_texto("# comentario\\nFrancia ; París\\nItalia;Roma\\nfrancia;otra\\nsin separador")
                    self.assertEqual(n, 2)
                    with self.assertRaises(ValueError):
                        m.agregar(" ", "x")

                def test_guardar_y_cargar(self):
                    with tempfile.TemporaryDirectory() as d:
                        ruta = Path(d) / "sub" / "mazo.json"
                        m = Mazo("geo")
                        m.agregar("Francia", "París")
                        calificar(m.tarjetas[0], 4, HOY)
                        m.guardar(ruta)
                        otro = Mazo.cargar(ruta)
                        self.assertEqual(otro.tarjetas[0].a_dict(), m.tarjetas[0].a_dict())
                        self.assertEqual(Mazo.cargar(Path(d) / "no.json").tarjetas, [])

                def test_estadisticas(self):
                    m = Mazo("x")
                    m.agregar("a", "1"); m.agregar("b", "2")
                    calificar(m.tarjetas[0], 5, HOY); calificar(m.tarjetas[0], 5, HOY)
                    e = m.estadisticas(HOY)
                    self.assertEqual((e["total"], e["aprendidas"], e["nuevas"]), (2, 1, 1))


            class TestSesionInteractiva(unittest.TestCase):
                def test_estudiar_por_stdin(self):
                    with tempfile.TemporaryDirectory() as d:
                        ruta = Path(d) / "mazo.json"
                        m = Mazo("x")
                        m.agregar("capital de Francia", "París")
                        m.guardar(ruta)
                        entorno = {**os.environ, "FLASHCARDS_MAZO": str(ruta)}
                        r = subprocess.run([sys.executable, "-m", "__PROYECTO__", "estudiar"], input="\\n5\\n",
                                           capture_output=True, text=True, timeout=20, env=entorno)
                        self.assertEqual(r.returncode, 0, r.stderr)
                        self.assertIn("París", r.stdout)
                        self.assertIn("Repasaste 1", r.stdout)
                        self.assertEqual(Mazo.cargar(ruta).tarjetas[0].repeticiones, 1)

                def test_fin_de_entrada_no_rompe(self):
                    m = Mazo("x")
                    m.agregar("a", "b")
                    def sin_entrada(_=""):
                        raise EOFError
                    from __PROYECTO__.__main__ import estudiar
                    self.assertEqual(estudiar(m, entrada=sin_entrada, salida=lambda *_: None), 0)


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 -m __PROYECTO__ estado",
    etiquetas=("estudio", "flashcards", "memoria", "cli", "interactivo"),
)

# ======================================================================
# habitos
# ======================================================================
registrar_plantilla(
    "habitos",
    "Seguimiento de hábitos con rachas (días seguidos), SQLite y un reporte semanal con barras.",
    "python",
    {
        "habitos.py": '''
            """__TITULO__: hábitos diarios con rachas, guardados en SQLite."""
            from __future__ import annotations

            import sqlite3
            from contextlib import closing
            from datetime import date, timedelta
            from pathlib import Path

            ESQUEMA = """
            CREATE TABLE IF NOT EXISTS habitos (
                id INTEGER PRIMARY KEY,
                nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
                creado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS marcas (
                habito_id INTEGER NOT NULL REFERENCES habitos(id) ON DELETE CASCADE,
                dia TEXT NOT NULL,
                PRIMARY KEY (habito_id, dia)
            );
            """


            class Habitos:
                def __init__(self, ruta: str | Path = ":memory:"):
                    self.con = sqlite3.connect(str(ruta))
                    self.con.row_factory = sqlite3.Row
                    self.con.execute("PRAGMA foreign_keys = ON")
                    self.con.executescript(ESQUEMA)

                def cerrar(self) -> None:
                    self.con.close()

                def crear(self, nombre: str, hoy: date | None = None) -> int:
                    nombre = " ".join(nombre.split())
                    if not nombre:
                        raise ValueError("el hábito necesita un nombre")
                    try:
                        with self.con:
                            cur = self.con.execute("INSERT INTO habitos (nombre, creado) VALUES (?, ?)",
                                                   (nombre, (hoy or date.today()).isoformat()))
                    except sqlite3.IntegrityError:
                        raise ValueError(f"ya existe el hábito '{nombre}'") from None
                    return cur.lastrowid

                def _id(self, nombre: str) -> int:
                    fila = self.con.execute("SELECT id FROM habitos WHERE nombre = ?", (nombre.strip(),)).fetchone()
                    if fila is None:
                        raise KeyError(f"no existe el hábito '{nombre}'")
                    return fila["id"]

                def marcar(self, nombre: str, dia: date | None = None) -> bool:
                    """Marca el hábito como hecho ese día. Devuelve False si ya estaba marcado."""
                    with self.con:
                        cur = self.con.execute("INSERT OR IGNORE INTO marcas (habito_id, dia) VALUES (?, ?)",
                                               (self._id(nombre), (dia or date.today()).isoformat()))
                    return cur.rowcount == 1

                def desmarcar(self, nombre: str, dia: date | None = None) -> None:
                    with self.con:
                        self.con.execute("DELETE FROM marcas WHERE habito_id = ? AND dia = ?",
                                         (self._id(nombre), (dia or date.today()).isoformat()))

                def borrar(self, nombre: str) -> None:
                    with self.con:
                        self.con.execute("DELETE FROM habitos WHERE id = ?", (self._id(nombre),))

                def dias(self, nombre: str) -> set[date]:
                    filas = self.con.execute("SELECT dia FROM marcas WHERE habito_id = ?", (self._id(nombre),))
                    return {date.fromisoformat(f["dia"]) for f in filas}

                def nombres(self) -> list[str]:
                    return [f["nombre"] for f in self.con.execute("SELECT nombre FROM habitos ORDER BY nombre")]

                def racha_actual(self, nombre: str, hoy: date | None = None) -> int:
                    """Días seguidos hasta hoy (si hoy todavía no se marcó, cuenta desde ayer)."""
                    hoy = hoy or date.today()
                    dias = self.dias(nombre)
                    dia = hoy if hoy in dias else hoy - timedelta(days=1)
                    racha = 0
                    while dia in dias:
                        racha += 1
                        dia -= timedelta(days=1)
                    return racha

                def mejor_racha(self, nombre: str) -> int:
                    dias = sorted(self.dias(nombre))
                    mejor = actual = 0
                    anterior = None
                    for d in dias:
                        actual = actual + 1 if anterior and d - anterior == timedelta(days=1) else 1
                        mejor = max(mejor, actual)
                        anterior = d
                    return mejor

                def semana(self, nombre: str, hoy: date | None = None) -> list[bool]:
                    hoy = hoy or date.today()
                    dias = self.dias(nombre)
                    return [(hoy - timedelta(days=6 - i)) in dias for i in range(7)]

                def reporte(self, hoy: date | None = None) -> str:
                    hoy = hoy or date.today()
                    if not self.nombres():
                        return "(sin hábitos: creá uno con 'nuevo NOMBRE')"
                    letras = "".join("LMMJVSD"[(hoy - timedelta(days=6 - i)).weekday()] for i in range(7))
                    ancho = max(len(n) for n in self.nombres())
                    filas = [f"{'':<{ancho}}  {letras}  racha"]
                    for nombre in self.nombres():
                        marcas = "".join("█" if hecho else "·" for hecho in self.semana(nombre, hoy))
                        filas.append(f"{nombre:<{ancho}}  {marcas}  {self.racha_actual(nombre, hoy):>3} (mejor {self.mejor_racha(nombre)})")
                    return "\\n".join(filas)


            def main(argv: list[str] | None = None) -> int:
                import os
                import sys
                args = sys.argv[1:] if argv is None else argv
                ruta = Path(os.environ.get("HABITOS_DB", Path.home() / ".__PROYECTO__.db"))
                with closing(Habitos(ruta)) as h:
                    comando = args[0] if args else "reporte"
                    try:
                        if comando == "nuevo" and len(args) > 1:
                            h.crear(" ".join(args[1:]))
                            print("hábito creado")
                        elif comando == "hecho" and len(args) > 1:
                            nombre = " ".join(args[1:])
                            print("¡marcado!" if h.marcar(nombre) else "ya estaba marcado hoy")
                            print(f"racha: {h.racha_actual(nombre)} día(s)")
                        elif comando == "deshacer" and len(args) > 1:
                            h.desmarcar(" ".join(args[1:]))
                        elif comando == "borrar" and len(args) > 1:
                            h.borrar(" ".join(args[1:]))
                        elif comando == "reporte":
                            print(h.reporte())
                        else:
                            print("uso: habitos.py [nuevo NOMBRE | hecho NOMBRE | deshacer NOMBRE | borrar NOMBRE | reporte]")
                            return 2
                    except (KeyError, ValueError) as e:
                        print(f"error: {e.args[0]}")
                        return 1
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "tests/test_habitos.py": '''
            import unittest
            from datetime import date, timedelta

            from habitos import Habitos

            HOY = date(2024, 3, 10)  # domingo


            def dia(n: int) -> date:
                return HOY - timedelta(days=n)


            class TestHabitos(unittest.TestCase):
                def setUp(self):
                    self.h = Habitos()
                    self.h.crear("Leer", HOY)

                def tearDown(self):
                    self.h.cerrar()

                def test_crear_duplicado_y_vacio(self):
                    with self.assertRaises(ValueError):
                        self.h.crear("leer")
                    with self.assertRaises(ValueError):
                        self.h.crear("   ")

                def test_marcar_una_vez_por_dia(self):
                    self.assertTrue(self.h.marcar("Leer", HOY))
                    self.assertFalse(self.h.marcar("Leer", HOY))
                    with self.assertRaises(KeyError):
                        self.h.marcar("Correr", HOY)

                def test_racha_actual(self):
                    for n in (0, 1, 2, 4):
                        self.h.marcar("Leer", dia(n))
                    self.assertEqual(self.h.racha_actual("Leer", HOY), 3)
                    self.h.desmarcar("Leer", HOY)
                    self.assertEqual(self.h.racha_actual("Leer", HOY), 2)   # hoy todavía no: cuenta desde ayer

                def test_mejor_racha(self):
                    for n in (10, 9, 8, 7, 3, 2):
                        self.h.marcar("Leer", dia(n))
                    self.assertEqual(self.h.mejor_racha("Leer"), 4)

                def test_semana_y_reporte(self):
                    self.h.marcar("Leer", HOY)
                    self.h.marcar("Leer", dia(6))
                    self.assertEqual(self.h.semana("Leer", HOY), [True, False, False, False, False, False, True])
                    reporte = self.h.reporte(HOY)
                    self.assertIn("LMMJVSD", reporte)
                    self.assertIn("█·····█", reporte)

                def test_borrar_en_cascada(self):
                    self.h.marcar("Leer", HOY)
                    self.h.borrar("Leer")
                    self.assertEqual(self.h.nombres(), [])
                    self.assertEqual(self.h.con.execute("SELECT COUNT(*) FROM marcas").fetchone()[0], 0)


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 habitos.py reporte",
    etiquetas=("habitos", "rachas", "sqlite", "productividad"),
)

# ======================================================================
# rss
# ======================================================================
registrar_plantilla(
    "rss",
    "Lector de noticias RSS/Atom: parser con xml.etree, caché, no leídas y búsqueda. Tests con feeds de ejemplo (sin red).",
    "python",
    {
        "lector.py": '''
            """__TITULO__: lector RSS/Atom sin dependencias."""
            from __future__ import annotations

            import hashlib
            import json
            import re
            import urllib.request
            import xml.etree.ElementTree as ET
            from dataclasses import asdict, dataclass
            from email.utils import parsedate_to_datetime
            from pathlib import Path

            ATOM = "{http://www.w3.org/2005/Atom}"


            @dataclass
            class Noticia:
                id: str
                titulo: str
                enlace: str
                fecha: str          # ISO 8601 o "" si el feed no la trae
                resumen: str
                fuente: str


            def _texto(nodo, ruta: str, ns: dict | None = None) -> str:
                hijo = nodo.find(ruta, ns or {})
                return (hijo.text or "").strip() if hijo is not None and hijo.text else ""


            def _fecha_iso(texto: str) -> str:
                if not texto:
                    return ""
                try:
                    return parsedate_to_datetime(texto).isoformat()
                except (TypeError, ValueError):
                    return texto  # Atom ya viene en ISO 8601


            def _limpiar_html(texto: str, maximo: int = 280) -> str:
                texto = re.sub(r"<[^>]+>", " ", texto or "")
                texto = " ".join(texto.split())
                return texto if len(texto) <= maximo else texto[:maximo - 1] + "…"


            def parsear_feed(xml: str | bytes, fuente: str = "") -> list[Noticia]:
                try:
                    raiz = ET.fromstring(xml)
                except ET.ParseError as e:
                    raise ValueError(f"el feed no es XML válido: {e}") from None
                noticias = []
                if raiz.tag == f"{ATOM}feed":
                    for entrada in raiz.findall(f"{ATOM}entry"):
                        enlace = entrada.find(f"{ATOM}link")
                        href = enlace.get("href", "") if enlace is not None else ""
                        titulo = _texto(entrada, f"{ATOM}title")
                        ident = _texto(entrada, f"{ATOM}id") or href or titulo
                        noticias.append(Noticia(
                            hashlib.sha1(ident.encode()).hexdigest()[:12], titulo, href,
                            _texto(entrada, f"{ATOM}updated") or _texto(entrada, f"{ATOM}published"),
                            _limpiar_html(_texto(entrada, f"{ATOM}summary") or _texto(entrada, f"{ATOM}content")),
                            fuente or _texto(raiz, f"{ATOM}title")))
                    return noticias
                canal = raiz.find("channel")
                if canal is None:
                    raise ValueError("no es un feed RSS ni Atom")
                nombre = fuente or _texto(canal, "title")
                for item in canal.findall("item"):
                    titulo, enlace = _texto(item, "title"), _texto(item, "link")
                    ident = _texto(item, "guid") or enlace or titulo
                    noticias.append(Noticia(hashlib.sha1(ident.encode()).hexdigest()[:12], titulo, enlace,
                                            _fecha_iso(_texto(item, "pubDate")), _limpiar_html(_texto(item, "description")),
                                            nombre))
                return noticias


            def descargar(url: str, timeout: float = 15) -> bytes:
                pedido = urllib.request.Request(url, headers={"User-Agent": "__PROYECTO__/1.0"})
                with urllib.request.urlopen(pedido, timeout=timeout) as r:
                    return r.read(5_000_000)


            class Lector:
                def __init__(self, ruta: Path, descargador=descargar):
                    self.ruta = Path(ruta)
                    self.descargar = descargador
                    try:
                        datos = json.loads(self.ruta.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        datos = {}
                    self.feeds: list[str] = datos.get("feeds", [])
                    self.noticias: dict[str, dict] = datos.get("noticias", {})
                    self.leidas: set[str] = set(datos.get("leidas", []))

                def guardar(self) -> None:
                    self.ruta.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self.ruta.with_suffix(".tmp")
                    tmp.write_text(json.dumps({"feeds": self.feeds, "noticias": self.noticias,
                                               "leidas": sorted(self.leidas)}, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(self.ruta)

                def suscribir(self, url: str) -> None:
                    if not re.match(r"^https?://", url):
                        raise ValueError("la URL tiene que empezar con http:// o https://")
                    if url not in self.feeds:
                        self.feeds.append(url)

                def actualizar(self) -> tuple[int, list[str]]:
                    """Descarga todos los feeds. Devuelve (noticias nuevas, errores por feed)."""
                    nuevas, errores = 0, []
                    for url in self.feeds:
                        try:
                            for n in parsear_feed(self.descargar(url)):
                                if n.id not in self.noticias:
                                    self.noticias[n.id] = asdict(n)
                                    nuevas += 1
                        except (OSError, ValueError) as e:
                            errores.append(f"{url}: {e}")
                    return nuevas, errores

                def no_leidas(self) -> list[dict]:
                    return sorted((n for i, n in self.noticias.items() if i not in self.leidas),
                                  key=lambda n: n["fecha"], reverse=True)

                def marcar_leida(self, ident: str) -> None:
                    if ident not in self.noticias:
                        raise KeyError(ident)
                    self.leidas.add(ident)

                def buscar(self, texto: str) -> list[dict]:
                    t = texto.lower()
                    return [n for n in self.noticias.values() if t in n["titulo"].lower() or t in n["resumen"].lower()]


            def main(argv: list[str] | None = None) -> int:
                import os
                import sys
                args = sys.argv[1:] if argv is None else argv
                lector = Lector(Path(os.environ.get("RSS_DATOS", Path.home() / ".__PROYECTO__.json")))
                comando = args[0] if args else "listar"
                if comando == "agregar" and len(args) == 2:
                    lector.suscribir(args[1])
                elif comando == "actualizar":
                    nuevas, errores = lector.actualizar()
                    print(f"{nuevas} noticias nuevas")
                    for e in errores:
                        print("error:", e)
                elif comando == "listar":
                    for n in lector.no_leidas()[:30]:
                        print(f"[{n['id']}] {n['titulo']} — {n['fuente']}")
                elif comando == "leer" and len(args) == 2:
                    n = lector.noticias.get(args[1])
                    if not n:
                        print("no existe esa noticia")
                        return 1
                    print(f"{n['titulo']}\\n{n['enlace']}\\n\\n{n['resumen']}")
                    lector.marcar_leida(args[1])
                elif comando == "buscar" and len(args) >= 2:
                    for n in lector.buscar(" ".join(args[1:])):
                        print(f"[{n['id']}] {n['titulo']}")
                else:
                    print("uso: lector.py [agregar URL | actualizar | listar | leer ID | buscar TEXTO]")
                    return 2
                lector.guardar()
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "tests/test_lector.py": '''
            import tempfile
            import unittest
            from pathlib import Path

            from lector import Lector, parsear_feed

            RSS = """<?xml version="1.0"?>
            <rss version="2.0"><channel><title>Diario</title>
              <item><title>Llueve en Rosario</title><link>https://x.com/1</link><guid>1</guid>
                <pubDate>Tue, 05 Mar 2024 10:00:00 +0000</pubDate><description>&lt;p&gt;Mucha &lt;b&gt;agua&lt;/b&gt;&lt;/p&gt;</description></item>
              <item><title>Sale el sol</title><link>https://x.com/2</link>
                <pubDate>Wed, 06 Mar 2024 10:00:00 +0000</pubDate><description>Por fin</description></item>
            </channel></rss>"""

            ATOM = """<?xml version="1.0"?>
            <feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title>
              <entry><title>Hola Atom</title><link href="https://b.com/a"/><id>urn:a</id>
                <updated>2024-03-07T09:00:00Z</updated><summary>Resumen</summary></entry>
            </feed>"""


            class TestParser(unittest.TestCase):
                def test_rss(self):
                    n = parsear_feed(RSS)
                    self.assertEqual([x.titulo for x in n], ["Llueve en Rosario", "Sale el sol"])
                    self.assertEqual(n[0].resumen, "Mucha agua")
                    self.assertEqual(n[0].fecha, "2024-03-05T10:00:00+00:00")
                    self.assertEqual(n[0].fuente, "Diario")

                def test_atom(self):
                    n = parsear_feed(ATOM)
                    self.assertEqual((n[0].titulo, n[0].enlace, n[0].fuente), ("Hola Atom", "https://b.com/a", "Blog"))

                def test_invalidos(self):
                    with self.assertRaises(ValueError):
                        parsear_feed("<no cierra")
                    with self.assertRaises(ValueError):
                        parsear_feed("<html></html>")


            class TestLector(unittest.TestCase):
                def setUp(self):
                    self.tmp = tempfile.TemporaryDirectory()
                    self.ruta = Path(self.tmp.name) / "datos.json"
                    feeds = {"https://d.com/rss": RSS, "https://b.com/atom": ATOM}
                    def falso(url):
                        if url not in feeds:
                            raise OSError("sin conexión")
                        return feeds[url].encode()
                    self.falso = falso

                def tearDown(self):
                    self.tmp.cleanup()

                def test_actualizar_sin_duplicar(self):
                    l = Lector(self.ruta, self.falso)
                    l.suscribir("https://d.com/rss"); l.suscribir("https://b.com/atom"); l.suscribir("https://d.com/rss")
                    self.assertEqual(l.actualizar(), (3, []))
                    self.assertEqual(l.actualizar(), (0, []))

                def test_errores_por_feed_no_cortan(self):
                    l = Lector(self.ruta, self.falso)
                    l.suscribir("https://caido.com/rss"); l.suscribir("https://d.com/rss")
                    nuevas, errores = l.actualizar()
                    self.assertEqual(nuevas, 2)
                    self.assertIn("caido.com", errores[0])

                def test_no_leidas_persisten(self):
                    l = Lector(self.ruta, self.falso)
                    l.suscribir("https://d.com/rss")
                    l.actualizar()
                    primera = l.no_leidas()[0]
                    self.assertEqual(primera["titulo"], "Sale el sol")   # la más nueva primero
                    l.marcar_leida(primera["id"])
                    l.guardar()
                    otra = Lector(self.ruta, self.falso)
                    self.assertEqual([n["titulo"] for n in otra.no_leidas()], ["Llueve en Rosario"])
                    self.assertEqual(len(otra.buscar("AGUA")), 1)

                def test_url_invalida(self):
                    with self.assertRaises(ValueError):
                        Lector(self.ruta, self.falso).suscribir("ftp://x")


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 lector.py listar",
    etiquetas=("rss", "atom", "noticias", "xml", "feeds"),
)

# ======================================================================
# markdown
# ======================================================================
registrar_plantilla(
    "markdown",
    "Conversor Markdown → HTML sin dependencias: títulos, listas, énfasis, código, citas, links e imágenes con escape seguro.",
    "python",
    {
        "md2html.py": '''
            """__TITULO__: Markdown → HTML (subconjunto práctico) con escape seguro."""
            from __future__ import annotations

            import html
            import re

            _CODIGO_INLINE = re.compile(r"`([^`]+)`")
            _IMAGEN = re.compile(r"!\\[([^\\]]*)\\]\\(([^)\\s]+)\\)")
            _LINK = re.compile(r"\\[([^\\]]+)\\]\\(([^)\\s]+)\\)")
            _NEGRITA = re.compile(r"\\*\\*(.+?)\\*\\*|__(.+?)__")
            _CURSIVA = re.compile(r"(?<!\\*)\\*(?!\\s)(.+?)(?<!\\s)\\*(?!\\*)|(?<!_)_(?!\\s)(.+?)(?<!\\s)_(?!_)")
            _TACHADO = re.compile(r"~~(.+?)~~")


            def _url_segura(url: str) -> str:
                url = url.strip()
                if re.match(r"^(javascript|data|vbscript):", url, re.I):
                    return "#"
                return html.escape(url, quote=True)


            def inline(texto: str) -> str:
                """Formato dentro de una línea. El código inline se protege para no formatear su contenido."""
                guardados: list[str] = []

                def guardar(fragmento: str) -> str:
                    guardados.append(fragmento)
                    return f"\\x00{len(guardados) - 1}\\x00"

                texto = _CODIGO_INLINE.sub(lambda m: guardar(f"<code>{html.escape(m.group(1))}</code>"), texto)
                texto = html.escape(texto, quote=False)
                texto = _IMAGEN.sub(lambda m: guardar(f'<img src="{_url_segura(html.unescape(m.group(2)))}" '
                                                      f'alt="{m.group(1)}">'), texto)
                texto = _LINK.sub(lambda m: f'<a href="{_url_segura(html.unescape(m.group(2)))}">{m.group(1)}</a>', texto)
                texto = _NEGRITA.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", texto)
                texto = _CURSIVA.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", texto)
                texto = _TACHADO.sub(r"<del>\\1</del>", texto)
                return re.sub(r"\\x00(\\d+)\\x00", lambda m: guardados[int(m.group(1))], texto)


            def convertir(md: str) -> str:
                lineas = md.replace("\\r\\n", "\\n").split("\\n")
                salida: list[str] = []
                parrafo: list[str] = []
                lista: str | None = None      # "ul" u "ol"
                i = 0

                def cerrar_parrafo():
                    if parrafo:
                        salida.append("<p>" + inline(" ".join(parrafo)) + "</p>")
                        parrafo.clear()

                def cerrar_lista():
                    nonlocal lista
                    if lista:
                        salida.append(f"</{lista}>")
                        lista = None

                while i < len(lineas):
                    linea = lineas[i]
                    if linea.startswith("```"):
                        cerrar_parrafo(); cerrar_lista()
                        lenguaje = linea[3:].strip()
                        bloque = []
                        i += 1
                        while i < len(lineas) and not lineas[i].startswith("```"):
                            bloque.append(lineas[i])
                            i += 1
                        clase = f' class="language-{html.escape(lenguaje)}"' if lenguaje else ""
                        salida.append(f"<pre><code{clase}>" + html.escape("\\n".join(bloque)) + "</code></pre>")
                        i += 1
                        continue
                    titulo = re.match(r"^(#{1,6})\\s+(.*?)\\s*#*\\s*$", linea)
                    item_ul = re.match(r"^\\s*[-*+]\\s+(.*)$", linea)
                    item_ol = re.match(r"^\\s*\\d+[.)]\\s+(.*)$", linea)
                    if not linea.strip():
                        cerrar_parrafo(); cerrar_lista()
                    elif titulo:
                        cerrar_parrafo(); cerrar_lista()
                        nivel = len(titulo.group(1))
                        salida.append(f"<h{nivel}>{inline(titulo.group(2))}</h{nivel}>")
                    elif re.match(r"^\\s*([-*_])(\\s*\\1){2,}\\s*$", linea):
                        cerrar_parrafo(); cerrar_lista()
                        salida.append("<hr>")
                    elif linea.startswith(">"):
                        cerrar_parrafo(); cerrar_lista()
                        cita = []
                        while i < len(lineas) and lineas[i].startswith(">"):
                            cita.append(lineas[i][1:].lstrip())
                            i += 1
                        salida.append("<blockquote>" + convertir("\\n".join(cita)) + "</blockquote>")
                        continue
                    elif item_ul or item_ol:
                        cerrar_parrafo()
                        tipo = "ul" if item_ul else "ol"
                        if lista != tipo:
                            cerrar_lista()
                            salida.append(f"<{tipo}>")
                            lista = tipo
                        contenido = (item_ul or item_ol).group(1)
                        tarea = re.match(r"^\\[([ xX])\\]\\s+(.*)$", contenido)
                        if tarea:
                            marcado = " checked" if tarea.group(1).lower() == "x" else ""
                            salida.append(f'<li><input type="checkbox" disabled{marcado}> {inline(tarea.group(2))}</li>')
                        else:
                            salida.append(f"<li>{inline(contenido)}</li>")
                    else:
                        cerrar_lista()
                        parrafo.append(linea.strip())
                    i += 1
                cerrar_parrafo(); cerrar_lista()
                return "\\n".join(salida)


            def pagina(md: str, titulo: str = "__TITULO__") -> str:
                return ("<!doctype html>\\n<html lang=\\"es\\"><head><meta charset=\\"utf-8\\">"
                        "<meta name=\\"viewport\\" content=\\"width=device-width, initial-scale=1\\">"
                        f"<title>{html.escape(titulo)}</title><style>body{{max-width:720px;margin:2rem auto;padding:0 1rem;"
                        "font-family:system-ui;line-height:1.6}pre{background:#f4f4f4;padding:1rem;overflow:auto}</style>"
                        f"</head><body>\\n{convertir(md)}\\n</body></html>\\n")


            def main(argv: list[str] | None = None) -> int:
                import sys
                from pathlib import Path
                args = sys.argv[1:] if argv is None else argv
                if not args:
                    print("uso: md2html.py ARCHIVO.md [SALIDA.html]   (o '-' para leer de stdin)")
                    return 2
                texto = sys.stdin.read() if args[0] == "-" else Path(args[0]).read_text(encoding="utf-8")
                resultado = pagina(texto, Path(args[0]).stem if args[0] != "-" else "__TITULO__")
                if len(args) > 1:
                    Path(args[1]).write_text(resultado, encoding="utf-8")
                    print(f"escrito {args[1]}")
                else:
                    sys.stdout.write(resultado)
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "tests/test_md2html.py": '''
            import unittest

            from md2html import convertir, inline, pagina


            class TestInline(unittest.TestCase):
                def test_enfasis(self):
                    self.assertEqual(inline("**a** y *b* y ~~c~~"), "<strong>a</strong> y <em>b</em> y <del>c</del>")

                def test_codigo_no_se_formatea(self):
                    self.assertEqual(inline("usá `a*b*c` así"), "usá <code>a*b*c</code> así")

                def test_escape_y_links(self):
                    self.assertEqual(inline("<script> [x](https://a.com?q=1&r=2)"),
                                     '&lt;script&gt; <a href="https://a.com?q=1&amp;r=2">x</a>')

                def test_link_peligroso(self):
                    self.assertIn('href="#"', inline("[x](javascript:alert)"))
                    self.assertNotIn("javascript", inline("[x](JavaScript:robar())"))

                def test_imagen(self):
                    self.assertEqual(inline("![logo](img/a.png)"), '<img src="img/a.png" alt="logo">')


            class TestBloques(unittest.TestCase):
                def test_titulos_y_parrafos(self):
                    self.assertEqual(convertir("# Hola\\n\\nlinea uno\\nlinea dos"),
                                     "<h1>Hola</h1>\\n<p>linea uno linea dos</p>")

                def test_listas(self):
                    self.assertEqual(convertir("- a\\n- b\\n\\n1. x\\n2. y"),
                                     "<ul>\\n<li>a</li>\\n<li>b</li>\\n</ul>\\n<ol>\\n<li>x</li>\\n<li>y</li>\\n</ol>")

                def test_tareas(self):
                    self.assertIn('<input type="checkbox" disabled checked> hecho', convertir("- [x] hecho"))

                def test_bloque_de_codigo(self):
                    self.assertEqual(convertir("```python\\nif a < b:\\n    pass\\n```"),
                                     '<pre><code class="language-python">if a &lt; b:\\n    pass</code></pre>')

                def test_cita_y_separador(self):
                    self.assertEqual(convertir("> **ojo**\\n> dos\\n\\n---"),
                                     "<blockquote><p><strong>ojo</strong> dos</p></blockquote>\\n<hr>")

                def test_pagina_completa(self):
                    p = pagina("# T", "mi <doc>")
                    self.assertTrue(p.startswith("<!doctype html>"))
                    self.assertIn("<title>mi &lt;doc&gt;</title>", p)


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 md2html.py README.md README.html",
    etiquetas=("markdown", "html", "conversor", "documentacion"),
)

# ======================================================================
# csv-analisis
# ======================================================================
registrar_plantilla(
    "csv-analisis",
    "Analizador de CSV: detecta separador y tipos, resume cada columna (nulos, min, max, media, únicos), agrupa y exporta Markdown.",
    "python",
    {
        "analisis.py": '''
            """__TITULO__: resumen rápido de un CSV desde la terminal (sin pandas)."""
            from __future__ import annotations

            import csv
            import io
            import math
            from collections import Counter, defaultdict
            from dataclasses import dataclass, field

            NULOS = {"", "na", "n/a", "null", "none", "nan", "-"}


            def a_numero(texto: str) -> float | None:
                t = texto.strip().replace("$", "").replace("%", "")
                if t.lower() in NULOS:
                    return None
                if "," in t and "." in t:
                    t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
                elif "," in t:
                    t = t.replace(",", ".")
                try:
                    valor = float(t)
                except ValueError:
                    return None
                return valor if math.isfinite(valor) else None


            def leer_csv(texto: str) -> tuple[list[str], list[list[str]]]:
                muestra = texto[:4096]
                try:
                    dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\\t|")
                except csv.Error:
                    dialecto = csv.excel
                filas = [f for f in csv.reader(io.StringIO(texto), dialecto) if any(c.strip() for c in f)]
                if not filas:
                    raise ValueError("el CSV está vacío")
                encabezado = [c.strip() or f"col{i + 1}" for i, c in enumerate(filas[0])]
                datos = [(f + [""] * len(encabezado))[:len(encabezado)] for f in filas[1:]]
                return encabezado, datos


            @dataclass
            class Columna:
                nombre: str
                tipo: str = "texto"
                nulos: int = 0
                unicos: int = 0
                minimo: float | None = None
                maximo: float | None = None
                media: float | None = None
                frecuentes: list = field(default_factory=list)


            def resumir(encabezado: list[str], datos: list[list[str]]) -> list[Columna]:
                columnas = []
                for i, nombre in enumerate(encabezado):
                    valores = [f[i] for f in datos]
                    presentes = [v for v in valores if v.strip().lower() not in NULOS]
                    c = Columna(nombre, nulos=len(valores) - len(presentes), unicos=len(set(presentes)))
                    numeros = [n for n in (a_numero(v) for v in presentes) if n is not None]
                    if presentes and len(numeros) == len(presentes):
                        c.tipo = "número"
                        c.minimo, c.maximo = min(numeros), max(numeros)
                        c.media = sum(numeros) / len(numeros)
                    else:
                        c.frecuentes = Counter(presentes).most_common(3)
                    columnas.append(c)
                return columnas


            def agrupar(encabezado: list[str], datos: list[list[str]], por: str, valor: str, operacion: str = "suma"):
                if por not in encabezado or valor not in encabezado:
                    raise KeyError(f"columnas disponibles: {', '.join(encabezado)}")
                ip, iv = encabezado.index(por), encabezado.index(valor)
                grupos: dict[str, list[float]] = defaultdict(list)
                for f in datos:
                    n = a_numero(f[iv])
                    if n is not None:
                        grupos[f[ip].strip() or "(vacío)"].append(n)
                ops = {"suma": sum, "media": lambda v: sum(v) / len(v), "cantidad": len, "max": max, "min": min}
                if operacion not in ops:
                    raise ValueError(f"operación inválida: {operacion} ({', '.join(ops)})")
                return sorted(((k, ops[operacion](v)) for k, v in grupos.items()), key=lambda kv: -kv[1])


            def _fmt(n: float | None) -> str:
                if n is None:
                    return "-"
                return f"{n:,.0f}".replace(",", ".") if float(n).is_integer() else f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


            def markdown(columnas: list[Columna], filas: int) -> str:
                lineas = [f"**{filas} filas · {len(columnas)} columnas**", "",
                          "| columna | tipo | nulos | únicos | mín | máx | media / más frecuentes |",
                          "|---|---|---:|---:|---:|---:|---|"]
                for c in columnas:
                    extra = _fmt(c.media) if c.tipo == "número" else ", ".join(f"{v} ({n})" for v, n in c.frecuentes)
                    lineas.append(f"| {c.nombre} | {c.tipo} | {c.nulos} | {c.unicos} | {_fmt(c.minimo)} | {_fmt(c.maximo)} | {extra} |")
                return "\\n".join(lineas)


            def main(argv: list[str] | None = None) -> int:
                import sys
                from pathlib import Path
                args = sys.argv[1:] if argv is None else argv
                if not args:
                    print("uso: analisis.py DATOS.csv [agrupar COLUMNA VALOR [suma|media|cantidad|max|min]]")
                    return 2
                encabezado, datos = leer_csv(Path(args[0]).read_text(encoding="utf-8-sig"))
                if len(args) >= 4 and args[1] == "agrupar":
                    for clave, total in agrupar(encabezado, datos, args[2], args[3], args[4] if len(args) > 4 else "suma"):
                        print(f"{clave:<25} {_fmt(total):>15}")
                else:
                    print(markdown(resumir(encabezado, datos), len(datos)))
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "ejemplo.csv": "fecha;categoria;monto;medio\n2024-03-01;comida;1.500,50;efectivo\n2024-03-02;viaje;4000;tarjeta\n"
                       "2024-03-03;comida;2.499,50;tarjeta\n2024-03-04;ocio;;efectivo\n",
        "tests/test_analisis.py": '''
            import unittest

            from analisis import a_numero, agrupar, leer_csv, markdown, resumir

            CSV = "fecha;categoria;monto;medio\\n2024-03-01;comida;1.500,50;efectivo\\n2024-03-02;viaje;4000;tarjeta\\n" \\
                  "2024-03-03;comida;2.499,50;tarjeta\\n2024-03-04;ocio;;efectivo\\n"


            class TestNumeros(unittest.TestCase):
                def test_formatos(self):
                    self.assertEqual(a_numero("1.500,50"), 1500.5)
                    self.assertEqual(a_numero("1,500.50"), 1500.5)
                    self.assertEqual(a_numero("$ 30"), 30)
                    self.assertEqual(a_numero("12,5%"), 12.5)
                    self.assertIsNone(a_numero("N/A"))
                    self.assertIsNone(a_numero("hola"))


            class TestAnalisis(unittest.TestCase):
                def setUp(self):
                    self.enc, self.datos = leer_csv(CSV)

                def test_detecta_separador(self):
                    self.assertEqual(self.enc, ["fecha", "categoria", "monto", "medio"])
                    self.assertEqual(len(self.datos), 4)

                def test_resumen(self):
                    cols = {c.nombre: c for c in resumir(self.enc, self.datos)}
                    monto = cols["monto"]
                    self.assertEqual((monto.tipo, monto.nulos, monto.minimo, monto.maximo), ("número", 1, 1500.5, 4000))
                    self.assertAlmostEqual(monto.media, 8000 / 3)
                    self.assertEqual(cols["categoria"].frecuentes[0], ("comida", 2))

                def test_agrupar(self):
                    self.assertEqual(agrupar(self.enc, self.datos, "categoria", "monto"), [("comida", 4000.0), ("viaje", 4000.0)])
                    self.assertEqual(dict(agrupar(self.enc, self.datos, "medio", "monto", "cantidad")), {"tarjeta": 2, "efectivo": 1})
                    with self.assertRaises(KeyError):
                        agrupar(self.enc, self.datos, "nada", "monto")
                    with self.assertRaises(ValueError):
                        agrupar(self.enc, self.datos, "medio", "monto", "mediana")

                def test_markdown(self):
                    md = markdown(resumir(self.enc, self.datos), len(self.datos))
                    self.assertIn("**4 filas · 4 columnas**", md)
                    self.assertIn("| monto | número | 1 | 3 | 1.500,50 | 4.000 |", md)

                def test_vacio_y_filas_cortas(self):
                    with self.assertRaises(ValueError):
                        leer_csv("\\n\\n")
                    enc, datos = leer_csv("a,b,c\\n1\\n")
                    self.assertEqual(datos, [["1", "", ""]])


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 analisis.py ejemplo.csv",
    etiquetas=("csv", "datos", "estadisticas", "planilla", "analisis"),
)

# ======================================================================
# aventura
# ======================================================================
registrar_plantilla(
    "aventura",
    "Motor de aventura de texto: mundo en JSON, salas, objetos, inventario, puertas con llave y guardar/cargar partida.",
    "python",
    {
        "mundo.json": '''
            {
              "inicio": "cocina",
              "salas": {
                "cocina": {"descripcion": "Una cocina vieja. Huele a mate.", "salidas": {"norte": "pasillo"},
                           "objetos": ["linterna"]},
                "pasillo": {"descripcion": "Un pasillo oscuro.", "salidas": {"sur": "cocina", "este": "sotano"},
                            "objetos": ["llave"], "oscura": true},
                "sotano": {"descripcion": "El sótano. ¡Encontraste el tesoro!", "salidas": {"oeste": "pasillo"},
                           "objetos": ["tesoro"], "requiere": "llave"}
              },
              "objetivo": "tesoro"
            }
        ''',
        "aventura.py": '''
            """__TITULO__: motor de aventura de texto. Comandos: ir, mirar, tomar, soltar, inventario, guardar, cargar, salir."""
            from __future__ import annotations

            import json
            from dataclasses import dataclass, field
            from pathlib import Path

            DIRECCIONES = {"n": "norte", "s": "sur", "e": "este", "o": "oeste", "arriba": "arriba", "abajo": "abajo"}


            @dataclass
            class Estado:
                sala: str
                inventario: list = field(default_factory=list)
                objetos: dict = field(default_factory=dict)     # sala → objetos que quedan
                movimientos: int = 0
                terminado: bool = False


            class Juego:
                def __init__(self, mundo: dict):
                    self.mundo = mundo
                    self.estado = Estado(mundo["inicio"], [], {k: list(v.get("objetos", [])) for k, v in mundo["salas"].items()})

                @classmethod
                def desde_archivo(cls, ruta: Path) -> "Juego":
                    return cls(json.loads(Path(ruta).read_text(encoding="utf-8")))

                def _sala(self) -> dict:
                    return self.mundo["salas"][self.estado.sala]

                def describir(self) -> str:
                    sala = self._sala()
                    if sala.get("oscura") and "linterna" not in self.estado.inventario:
                        return "Está muy oscuro. No ves nada. Quizás necesitás una linterna."
                    partes = [sala["descripcion"]]
                    objetos = self.estado.objetos.get(self.estado.sala, [])
                    if objetos:
                        partes.append("Ves: " + ", ".join(objetos) + ".")
                    partes.append("Salidas: " + ", ".join(sorted(sala.get("salidas", {}))) + ".")
                    return " ".join(partes)

                def ir(self, direccion: str) -> str:
                    direccion = DIRECCIONES.get(direccion, direccion)
                    destino = self._sala().get("salidas", {}).get(direccion)
                    if destino is None:
                        return "No podés ir para ese lado."
                    requiere = self.mundo["salas"][destino].get("requiere")
                    if requiere and requiere not in self.estado.inventario:
                        return f"La puerta está cerrada. Necesitás: {requiere}."
                    self.estado.sala = destino
                    self.estado.movimientos += 1
                    texto = self.describir()
                    if self.mundo.get("objetivo") in self.estado.objetos.get(destino, []):
                        texto += " (El objetivo está acá: tomalo.)"
                    return texto

                def tomar(self, objeto: str) -> str:
                    if self._sala().get("oscura") and "linterna" not in self.estado.inventario:
                        return "Está demasiado oscuro para buscar algo."
                    objetos = self.estado.objetos.get(self.estado.sala, [])
                    if objeto not in objetos:
                        return f"No hay {objeto} acá."
                    objetos.remove(objeto)
                    self.estado.inventario.append(objeto)
                    if objeto == self.mundo.get("objetivo"):
                        self.estado.terminado = True
                        return f"¡Tomaste {objeto}! Ganaste en {self.estado.movimientos} movimientos."
                    return f"Tomaste {objeto}."

                def soltar(self, objeto: str) -> str:
                    if objeto not in self.estado.inventario:
                        return f"No tenés {objeto}."
                    self.estado.inventario.remove(objeto)
                    self.estado.objetos.setdefault(self.estado.sala, []).append(objeto)
                    return f"Soltaste {objeto}."

                def guardar(self, ruta: Path) -> str:
                    Path(ruta).write_text(json.dumps(self.estado.__dict__, ensure_ascii=False), encoding="utf-8")
                    return "Partida guardada."

                def cargar(self, ruta: Path) -> str:
                    try:
                        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
                        self.estado = Estado(**datos)
                    except (OSError, ValueError, TypeError):
                        return "No hay una partida guardada válida."
                    return "Partida cargada. " + self.describir()

                def ejecutar(self, linea: str, ruta_partida: Path = Path("partida.json")) -> str:
                    palabras = linea.strip().lower().split()
                    if not palabras:
                        return ""
                    verbo, resto = palabras[0], " ".join(palabras[1:])
                    if verbo in DIRECCIONES or verbo in DIRECCIONES.values():
                        return self.ir(verbo)
                    acciones = {
                        "ir": lambda: self.ir(resto) if resto else "¿Para dónde?",
                        "mirar": self.describir, "m": self.describir,
                        "tomar": lambda: self.tomar(resto) if resto else "¿Qué querés tomar?",
                        "agarrar": lambda: self.tomar(resto) if resto else "¿Qué querés tomar?",
                        "soltar": lambda: self.soltar(resto) if resto else "¿Qué querés soltar?",
                        "inventario": lambda: "Llevás: " + (", ".join(self.estado.inventario) or "nada") + ".",
                        "i": lambda: "Llevás: " + (", ".join(self.estado.inventario) or "nada") + ".",
                        "guardar": lambda: self.guardar(ruta_partida),
                        "cargar": lambda: self.cargar(ruta_partida),
                        "ayuda": lambda: __doc__.split(":", 1)[1].strip(),
                    }
                    accion = acciones.get(verbo)
                    return accion() if accion else "No entiendo. Escribí 'ayuda'."


            def main() -> int:
                juego = Juego.desde_archivo(Path(__file__).with_name("mundo.json"))
                print(juego.describir())
                while not juego.estado.terminado:
                    try:
                        linea = input("> ")
                    except EOFError:
                        print()
                        break
                    if linea.strip().lower() in ("salir", "q"):
                        break
                    respuesta = juego.ejecutar(linea)
                    if respuesta:
                        print(respuesta)
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "tests/test_aventura.py": '''
            import json
            import subprocess
            import sys
            import tempfile
            import unittest
            from pathlib import Path

            from aventura import Juego

            MUNDO = json.loads((Path(__file__).resolve().parent.parent / "mundo.json").read_text(encoding="utf-8"))


            class TestJuego(unittest.TestCase):
                def setUp(self):
                    self.j = Juego(MUNDO)

                def test_oscuridad_y_linterna(self):
                    self.assertIn("muy oscuro", self.j.ejecutar("norte"))
                    self.assertIn("demasiado oscuro", self.j.ejecutar("tomar llave"))
                    self.j.ejecutar("sur")
                    self.assertEqual(self.j.ejecutar("tomar linterna"), "Tomaste linterna.")
                    self.assertIn("Ves: llave", self.j.ejecutar("n"))

                def test_puerta_con_llave_y_victoria(self):
                    for comando in ("tomar linterna", "norte"):
                        self.j.ejecutar(comando)
                    self.assertIn("Necesitás: llave", self.j.ejecutar("este"))
                    self.j.ejecutar("tomar llave")
                    self.assertIn("objetivo está acá", self.j.ejecutar("e"))
                    self.assertIn("Ganaste en 2 movimientos", self.j.ejecutar("tomar tesoro"))
                    self.assertTrue(self.j.estado.terminado)

                def test_inventario_y_soltar(self):
                    self.j.ejecutar("tomar linterna")
                    self.assertEqual(self.j.ejecutar("i"), "Llevás: linterna.")
                    self.assertEqual(self.j.ejecutar("soltar linterna"), "Soltaste linterna.")
                    self.assertEqual(self.j.ejecutar("soltar linterna"), "No tenés linterna.")
                    self.assertIn("No entiendo", self.j.ejecutar("bailar"))

                def test_guardar_y_cargar(self):
                    with tempfile.TemporaryDirectory() as d:
                        ruta = Path(d) / "p.json"
                        self.j.ejecutar("tomar linterna"); self.j.ejecutar("norte")
                        self.j.guardar(ruta)
                        otro = Juego(MUNDO)
                        self.assertIn("Partida cargada", otro.cargar(ruta))
                        self.assertEqual((otro.estado.sala, otro.estado.inventario), ("pasillo", ["linterna"]))
                        self.assertIn("No hay una partida", otro.cargar(Path(d) / "nada.json"))

                def test_partida_completa_por_stdin(self):
                    raiz = Path(__file__).resolve().parent.parent
                    r = subprocess.run([sys.executable, str(raiz / "aventura.py")], cwd=raiz, timeout=20,
                                       input="tomar linterna\\nnorte\\ntomar llave\\neste\\ntomar tesoro\\n",
                                       capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("Ganaste", r.stdout)


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 aventura.py",
    etiquetas=("juego", "aventura", "texto", "rpg", "interactivo"),
)
