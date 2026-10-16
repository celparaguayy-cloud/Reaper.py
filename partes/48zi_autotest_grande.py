"""
Autotests de /grande (proyecto grande por etapas) con un modelo SIMULADO que escribe código de verdad: un gestor de
biblioteca en 3 etapas (almacenamiento SQLite → préstamos → CLI). Los tests del proyecto se ejecutan de verdad en
cada etapa; lo único simulado es lo que "escribiría" el modelo.
"""


class _GuionBiblioteca:
    """Las respuestas de cada rol para el proyecto biblioteca. `prestamos_roto` simula un modelo que entrega una
    etapa con un bug real (presta dos veces el mismo libro)."""

    MAESTRO = """<maestro>
<vision>Gestor de biblioteca de consola: libros en SQLite, préstamos y una CLI.</vision>
<arquitectura>
Python 3 solo librería estándar. Paquete biblioteca/. Tests con unittest en tests/. Se arranca con python -m biblioteca.
</arquitectura>
<etapa id="1" titulo="Almacenamiento" deps="">
<objetivo>Guardar y listar libros en SQLite.</objetivo>
<archivos>biblioteca/__init__.py, biblioteca/almacen.py, tests/test_almacen.py</archivos>
<interfaz>
- biblioteca/almacen.py: class Almacen(ruta=":memory:") con agregar(titulo) -> int, listar() -> list, marcar(id, prestado) -> bool
</interfaz>
<criterios>
- agregar("Rayuela") y listar() lo devuelve sin prestar
</criterios>
</etapa>
<etapa id="2" titulo="Préstamos" deps="1">
<objetivo>Prestar y devolver libros sin prestar dos veces el mismo.</objetivo>
<archivos>biblioteca/prestamos.py, tests/test_prestamos.py</archivos>
<interfaz>
- biblioteca/prestamos.py: class Prestamos(almacen) con prestar(id) -> bool, devolver(id) -> bool
</interfaz>
<criterios>
- prestar dos veces el mismo libro devuelve False la segunda
</criterios>
</etapa>
<etapa id="3" titulo="Línea de comandos" deps="2">
<objetivo>CLI python -m biblioteca con agregar, listar y prestar.</objetivo>
<archivos>biblioteca/__main__.py, tests/test_cli.py</archivos>
<criterios>
- python -m biblioteca --db x.db agregar "Rayuela" y después listar lo muestra
</criterios>
</etapa>
</maestro>"""

    PLANES = {
        "1": """<plan><objetivo>Almacenamiento</objetivo>
<tarea id="1" archivos="biblioteca/__init__.py, biblioteca/almacen.py, tests/test_almacen.py">Crear Almacen con SQLite y sus tests (E1).</tarea>
<criterios>
- agregar y listar
</criterios></plan>""",
        "2": """<plan><objetivo>Préstamos</objetivo>
<tarea id="1" archivos="biblioteca/prestamos.py, tests/test_prestamos.py">Crear Prestamos sobre Almacen y sus tests (E2).</tarea>
<criterios>
- no se presta dos veces
</criterios></plan>""",
        "3": """<plan><objetivo>CLI</objetivo>
<tarea id="1" archivos="biblioteca/__main__.py, tests/test_cli.py">Crear la CLI con argparse y sus tests (E3).</tarea>
<criterios>
- agregar y listar desde la CLI
</criterios></plan>""",
        "INT": """<plan><objetivo>Integración</objetivo>
<tarea id="1" archivos="biblioteca/__main__.py, tests/test_cli_devolver.py">Agregar el subcomando devolver a la CLI (INT).</tarea>
<criterios>
- devolver desde la CLI
</criterios></plan>""",
    }

    ALMACEN = '''import sqlite3


class Almacen:
    def __init__(self, ruta=":memory:"):
        self.con = sqlite3.connect(ruta)
        self.con.execute("CREATE TABLE IF NOT EXISTS libros "
                         "(id INTEGER PRIMARY KEY, titulo TEXT NOT NULL, prestado INTEGER DEFAULT 0)")

    def agregar(self, titulo):
        if not titulo.strip():
            raise ValueError("el título no puede estar vacío")
        cur = self.con.execute("INSERT INTO libros (titulo) VALUES (?)", (titulo.strip(),))
        self.con.commit()
        return cur.lastrowid

    def listar(self):
        filas = self.con.execute("SELECT id, titulo, prestado FROM libros ORDER BY id")
        return [{"id": i, "titulo": t, "prestado": bool(p)} for i, t, p in filas]

    def marcar(self, libro_id, prestado):
        cur = self.con.execute("UPDATE libros SET prestado = ? WHERE id = ?", (int(prestado), libro_id))
        self.con.commit()
        return cur.rowcount == 1
'''
    TEST_ALMACEN = '''import unittest

from biblioteca.almacen import Almacen


class TestAlmacen(unittest.TestCase):
    def test_agregar_y_listar(self):
        a = Almacen()
        i = a.agregar("Rayuela")
        self.assertEqual(a.listar(), [{"id": i, "titulo": "Rayuela", "prestado": False}])

    def test_titulo_vacio(self):
        with self.assertRaises(ValueError):
            Almacen().agregar("   ")
'''
    PRESTAMOS = '''from biblioteca.almacen import Almacen


class Prestamos:
    def __init__(self, almacen: Almacen):
        self.almacen = almacen

    def _libro(self, libro_id):
        libro = next((l for l in self.almacen.listar() if l["id"] == libro_id), None)
        if libro is None:
            raise KeyError(libro_id)
        return libro

    def prestar(self, libro_id):
        if self._libro(libro_id)["prestado"]:
            return False
        return self.almacen.marcar(libro_id, True)

    def devolver(self, libro_id):
        if not self._libro(libro_id)["prestado"]:
            return False
        return self.almacen.marcar(libro_id, False)
'''
    # El bug que entregaría un modelo flojo: no mira si ya estaba prestado.
    PRESTAMOS_ROTO = PRESTAMOS.replace('        if self._libro(libro_id)["prestado"]:\n            return False\n'
                                       '        return self.almacen.marcar(libro_id, True)',
                                       '        self._libro(libro_id)\n        return self.almacen.marcar(libro_id, True)')
    TEST_PRESTAMOS = '''import unittest

from biblioteca.almacen import Almacen
from biblioteca.prestamos import Prestamos


class TestPrestamos(unittest.TestCase):
    def setUp(self):
        self.almacen = Almacen()
        self.id = self.almacen.agregar("Rayuela")
        self.p = Prestamos(self.almacen)

    def test_no_presta_dos_veces(self):
        self.assertTrue(self.p.prestar(self.id))
        self.assertFalse(self.p.prestar(self.id))

    def test_devolver(self):
        self.p.prestar(self.id)
        self.assertTrue(self.p.devolver(self.id))
        self.assertFalse(self.almacen.listar()[0]["prestado"])
'''
    CLI = '''import argparse
import sys

from biblioteca.almacen import Almacen
from biblioteca.prestamos import Prestamos


def main(argv=None):
    parser = argparse.ArgumentParser(prog="biblioteca")
    parser.add_argument("--db", default="biblioteca.db")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("agregar").add_argument("titulo")
    sub.add_parser("listar")
    sub.add_parser("prestar").add_argument("id", type=int)
    args = parser.parse_args(argv)
    almacen = Almacen(args.db)
    if args.comando == "agregar":
        print(almacen.agregar(args.titulo))
    elif args.comando == "listar":
        for libro in almacen.listar():
            print(f"{libro['id']}\\t{libro['titulo']}\\t{'prestado' if libro['prestado'] else 'disponible'}")
    elif args.comando == "prestar":
        if not Prestamos(almacen).prestar(args.id):
            print("ya estaba prestado", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''
    TEST_CLI = '''import os
import subprocess
import sys
import tempfile
import unittest


def correr(*args):
    return subprocess.run([sys.executable, "-m", "biblioteca", *args], capture_output=True, text=True, timeout=60)


class TestCli(unittest.TestCase):
    def test_agregar_y_listar(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "b.db")
            self.assertEqual(correr("--db", db, "agregar", "Rayuela").returncode, 0)
            salida = correr("--db", db, "listar").stdout
            self.assertIn("Rayuela", salida)
            self.assertIn("disponible", salida)
'''
    TEST_CLI_DEVOLVER = '''import os
import subprocess
import sys
import tempfile
import unittest


def correr(*args):
    return subprocess.run([sys.executable, "-m", "biblioteca", *args], capture_output=True, text=True, timeout=60)


class TestCliDevolver(unittest.TestCase):
    def test_devolver(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "b.db")
            correr("--db", db, "agregar", "Rayuela")
            correr("--db", db, "prestar", "1")
            self.assertEqual(correr("--db", db, "devolver", "1").returncode, 0)
            self.assertIn("disponible", correr("--db", db, "listar").stdout)
'''

    def __init__(self, ws, prestamos_roto=False, juez_pide_devolver=False):
        self.ws = ws
        self.prestamos_roto = prestamos_roto
        self.juez_pide_devolver = juez_pide_devolver
        self.llamadas = collections.Counter()

    def _archivos(self, marca):
        if marca == "E1":
            return [("biblioteca/__init__.py", ""), ("biblioteca/almacen.py", self.ALMACEN),
                    ("tests/test_almacen.py", self.TEST_ALMACEN)]
        if marca == "E2":
            return [("biblioteca/prestamos.py", self.PRESTAMOS_ROTO if self.prestamos_roto else self.PRESTAMOS),
                    ("tests/test_prestamos.py", self.TEST_PRESTAMOS)]
        if marca == "E3":
            return [("biblioteca/__main__.py", self.CLI), ("tests/test_cli.py", self.TEST_CLI)]
        cli = self.CLI.replace('    sub.add_parser("prestar").add_argument("id", type=int)\n',
                               '    sub.add_parser("prestar").add_argument("id", type=int)\n'
                               '    sub.add_parser("devolver").add_argument("id", type=int)\n')
        cli = cli.replace("    return 0\n\n\nif __name__",
                          '    elif args.comando == "devolver":\n'
                          '        if not Prestamos(almacen).devolver(args.id):\n'
                          '            return 1\n    return 0\n\n\nif __name__')
        return [("biblioteca/__main__.py", cli), ("tests/test_cli_devolver.py", self.TEST_CLI_DEVOLVER)]

    def __call__(self, mensajes, kw):
        rol = MockLLM.rol_de(mensajes)
        self.llamadas[rol] += 1
        primero = next((m["content"] for m in mensajes if m["role"] == "user"), "")
        if rol == "maestro":
            return self.MAESTRO
        if rol == "arquitecto":
            if "INTEGRACIÓN FINAL" in primero:
                return terminar_xml(self.PLANES["INT"])
            etapa = re.search(r"ETAPA (\d+) de 3", primero)
            return terminar_xml(self.PLANES[etapa.group(1) if etapa else "1"])
        if rol == "implementador":
            tarea = re.search(r"TU TAREA AHORA \(#[^)]*\):\n(.*?)\n\n", primero, re.S)
            marca = re.search(r"\((E\d|INT)\)", tarea.group(1) if tarea else "")
            archivos = self._archivos(marca.group(1) if marca else "E1")
            turno = _turno(mensajes)
            if turno < len(archivos):
                ruta, contenido = archivos[turno]
                return herramienta_xml("write_to_file", path=ruta, content=contenido)
            return terminar_xml("listo: archivos escritos")
        if rol == "juez":
            texto = MockLLM.ultimo_usuario(mensajes)
            if "TAREA: CONTRATO" in texto:
                return '{"criterios": ["lo que pide el pedido funciona y tiene tests"]}'
            global_ = "PROYECTO GRANDE —" not in texto
            if global_ and self.juez_pide_devolver and "devolver" not in self.ws.leer("biblioteca/__main__.py"):
                return ('{"cumple": false, "confianza": "high", "faltantes": ["la CLI no tiene el comando devolver"],'
                        ' "evidence_ids": ["EV-DIFF"]}')
            return '{"cumple": true, "confianza": "high", "evidence_ids": ["EV-TESTS"]}'
        return terminar_xml("sin cambios")


class TestGrandePlanMaestro(BaseTest):
    def test_parsea_etapas_y_valida(self):
        m = parsear_maestro(_GuionBiblioteca.MAESTRO)
        self.assertEqual([e.id for e in m.etapas], ["1", "2", "3"])
        self.assertEqual(m.etapas[1].deps, ["1"])
        self.assertIn("biblioteca/almacen.py", m.etapas[0].archivos)
        self.assertTrue(m.vision.startswith("Gestor de biblioteca"))
        self.assertEqual(problemas_maestro(m, 10), [])
        self.assertTrue(any("tope es 2" in p for p in problemas_maestro(m, 2)))

    def test_detecta_maestro_inservible(self):
        self.assertEqual(problemas_maestro(parsear_maestro("no sé"), 10),
                         ["no vino ninguna <etapa> con el formato pedido"])
        ciclo = parsear_maestro('<etapa id="1" deps="2"><objetivo>a</objetivo></etapa>'
                                '<etapa id="2" deps="1"><objetivo>b</objetivo></etapa>')
        self.assertTrue(any("ciclo" in p for p in problemas_maestro(ciclo, 10)))
        falso = parsear_maestro('<etapa id="1"><objetivo>Crear el esqueleto con stubs para completar después'
                                '</objetivo></etapa><etapa id="2" deps="9"><objetivo>Ejecutar todas las pruebas'
                                '</objetivo></etapa>')
        problemas = problemas_maestro(falso, 10)
        self.assertTrue(any("etapa 1 planea una simulación" in p for p in problemas), problemas)
        self.assertTrue(any("etapa 2 solo corre" in p for p in problemas), problemas)
        self.assertTrue(any("depende de '9'" in p for p in problemas), problemas)

    def test_rutas_peligrosas_no_entran(self):
        m = parsear_maestro('<etapa id="1"><objetivo>x</objetivo><archivos>/etc/passwd, ../fuera.py, '
                            '`app.py`, ~/x.py, src/ok.py</archivos></etapa>')
        self.assertEqual(m.etapas[0].archivos, ["app.py", "src/ok.py"])

    def test_pedido_de_etapa_es_determinista_y_trae_contexto(self):
        m = parsear_maestro(_GuionBiblioteca.MAESTRO)
        texto = pedido_de_etapa("una biblioteca", m, m.etapas[1])
        self.assertEqual(texto, pedido_de_etapa("una biblioteca", m, m.etapas[1]))   # retomable
        self.assertIn("ETAPA 2 de 3: Préstamos", texto)
        self.assertIn("class Almacen", texto)                                        # interfaz de la anterior
        self.assertIn("NO construyas todavía", texto)
        self.assertIn("Línea de comandos", texto)

    def test_ejemplos_pedidos_no_son_simulacion_en_el_plan(self):
        plan = Plan("x", [Tarea("1", "Crear la base con 3 datos de ejemplo de recetas", ["db.py"])], [])
        self.assertTrue(problemas_del_plan(plan))                                   # sin pedirlo: simulación
        self.assertEqual(problemas_del_plan(plan, "que arranque con datos de ejemplo"), [])

    def test_plan_que_se_pasa_del_tope_conserva_dependencias(self):
        texto = "<plan>" + "".join(f'<tarea id="{i}" archivos="m{i}.py" deps="{"1" if i > 1 else ""}">'
                                   f'Crear m{i}.py.</tarea>' for i in range(1, 6)) + "</plan>"
        plan = parsear_plan(texto, "x", max_tareas=3)
        self.assertEqual(len(plan.tareas), 3)
        self.assertEqual(plan.tareas[-1].deps, ["1"])                               # antes: [] (se perdía)


class TestGrandeConstruccion(BaseTest):
    def _ajustes(self, **extra):
        valores = dict(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                       max_reparaciones=1, juez=False, git_snapshots=False)
        valores.update(extra)
        return self.ajustes(**valores)

    def _grande(self, guion_kw=None, **ajustes):
        ws = self.proyecto({})
        guion = _GuionBiblioteca(ws, **(guion_kw or {}))
        ui = self.ui()
        return ws, guion, ui, ConstructorGrande(MockLLM(guion), ws, self._ajustes(**ajustes), ui)

    def test_tres_etapas_verificadas_e_integracion(self):
        ws, guion, ui, grande = self._grande()
        self.assertTrue(grande.iniciar("Un gestor de biblioteca con préstamos y CLI", confirmar=False),
                        ui.texto_registrado()[-3000:])
        estado = grande.leer()
        self.assertEqual(estado["estado"], "terminado")
        self.assertEqual([e["estado"] for e in estado["maestro"]["etapas"]], ["verificada"] * 3)
        self.assertTrue(estado["integracion"]["ok"])
        for rel in ("biblioteca/almacen.py", "biblioteca/prestamos.py", "biblioteca/__main__.py"):
            self.assertTrue(ws.existe(rel), rel)
        r = ejecutar_tests(ws, timeout=120)
        self.assertTrue(r.ok)
        self.assertEqual(conteo_de_resultado(r).pasados, 5)                         # los tests de las 3 etapas
        self.assertEqual(guion.llamadas["maestro"], 1)
        self.assertIsNone(RegistroBuild(ws).leer())                                 # ninguna build colgada
        self.assertIn("TERMINADO Y VERIFICADO", ui.texto_registrado())
        informes = list((ws.carpeta_reaper() / "informes").glob("proyecto_grande_*.md"))
        self.assertEqual(len(informes), 1)

    def test_etapa_rota_frena_y_continuar_la_termina(self):
        ws, guion, ui, grande = self._grande({"prestamos_roto": True})
        self.assertFalse(grande.iniciar("Un gestor de biblioteca con préstamos y CLI", confirmar=False))
        estado = grande.leer()
        etapas = {e["id"]: e for e in estado["maestro"]["etapas"]}
        self.assertEqual(estado["estado"], "detenido")
        self.assertEqual(etapas["1"]["estado"], "verificada")
        self.assertIn(etapas["2"]["estado"], ("parcial", "fallida"))
        self.assertEqual(etapas["2"]["intentos"], 2)                                # el original + 1 reanudación
        self.assertEqual(etapas["3"]["estado"], "pendiente")                        # no se construyó encima
        self.assertFalse(ws.existe("biblioteca/__main__.py"))
        self.assertIn("test_no_presta_dos_veces", etapas["2"]["motivo"])            # el error REAL
        self.assertIn("DETENIDO", ui.texto_registrado())
        self.assertEqual(ws.leer("biblioteca/almacen.py"), _GuionBiblioteca.ALMACEN)  # la etapa 1 intacta
        # El modelo "se corrige" y el usuario retoma: la build de la etapa 2 se RETOMA (no se replanifica).
        guion.prestamos_roto = False
        arquitecto_antes = guion.llamadas["arquitecto"]
        self.assertTrue(grande.continuar(), ui.texto_registrado()[-3000:])
        self.assertEqual(guion.llamadas["arquitecto"], arquitecto_antes + 1)        # solo el plan de la etapa 3
        self.assertEqual(grande.leer()["estado"], "terminado")
        self.assertEqual(guion.llamadas["maestro"], 1)

    def test_otro_construir_pendiente_no_se_pisa(self):
        ws, _guion, ui, grande = self._grande()
        # Un /construir que quedó a medias (falla y deja su diario): /grande no arranca encima ni lo pisa.
        orq = Orquestador(MockLLM([]), ws, self._ajustes(max_reparaciones=0), self.ui())
        orq.obtener_plan = lambda *a: (Plan("x", [Tarea("1", "Crear app.py", ["app.py"])], []), "")
        orq.implementar = lambda *a, **k: type("R", (), {"ok": True, "modo": "simple", "ganador": None})()
        orq._reparar_con_escalada = lambda pedido, verif, *a, **k: verif
        self.assertFalse(orq.construir("otra cosa", confirmar=False).ok)
        self.assertIsNotNone(RegistroBuild(ws).leer())
        self.assertFalse(grande.iniciar("biblioteca", confirmar=False))
        self.assertIn("/construir sin terminar", ui.texto_registrado())
        self.assertIsNone(grande.leer())

    def test_estado_con_numeros_grandes_se_puede_releer(self):
        ws, _guion, _ui, grande = self._grande()
        maestro = parsear_maestro(_GuionBiblioteca.MAESTRO)
        maestro.etapas[0].consumo, maestro.etapas[0].segundos = 123456, 98.7
        grande.guardar({"esquema": 1, "pedido": "x", "estado": "en_curso", "token_api": "sk-or-v1-0123456789abcdef0123"},
                       maestro)
        estado = grande.leer()
        self.assertEqual(estado["maestro"]["etapas"][0]["consumo"], 123456)
        self.assertNotIn("0123456789abcdef0123", grande.ruta.read_text(encoding="utf-8"))   # el secreto sí se redacta

    def test_integracion_completa_lo_que_falta_segun_el_pedido_original(self):
        ws, guion, ui, grande = self._grande({"juez_pide_devolver": True}, juez=True)
        self.assertTrue(grande.iniciar("Biblioteca con CLI para agregar, listar, prestar y devolver",
                                       confirmar=False), ui.texto_registrado()[-3000:])
        estado = grande.leer()
        self.assertTrue(estado["integracion"]["reparada"])                          # hubo build de integración
        self.assertIn("devolver", ws.leer("biblioteca/__main__.py"))
        self.assertTrue(ws.existe("tests/test_cli_devolver.py"))
        self.assertEqual(estado["estado"], "terminado")
        self.assertIn("la CLI no tiene el comando devolver", ui.texto_registrado())

    def test_el_plan_del_modelo_no_autoriza_reescrituras(self):
        orq = Orquestador(MockLLM([]), self.proyecto({}), self._ajustes(), self.ui())
        orq.pedido_usuario = "una biblioteca"
        # El texto de la etapa (que arma REAPER con lo que escribió el modelo) dice "reescribir desde cero",
        # pero el usuario no lo pidió: lo que autoriza sale de pedido_usuario.
        self.assertIsNone(_RE_REESCRITURA_PEDIDA.search(orq.pedido_usuario))

    def test_comando_grande_estado_y_uso(self):
        app = App(self._ajustes(), MockLLM([]), self.ui(), self.proyecto({}), persistir=False)
        app.cmd_grande("")
        app.cmd_grande("estado")
        texto = app.ui.texto_registrado()
        self.assertIn("Uso: /grande", texto)
        self.assertIn("No hay ningún proyecto grande", texto)
        self.assertIn("/grande", texto_ayuda())


class TestReanudarNoRegalaVerdes(BaseTest):
    """Bug de /construir que destapó la simulación de /grande: al retomar, la suite ya estaba roja por la MISMA
    build; REAPER lo tomaba como "fallaba antes de empezar" y la tarea re-ejecutada quedaba VERIFICADA con su propio
    test en rojo. Después cada /construir continuar la "conservaba" y la build no se podía arreglar nunca."""

    PLAN = """<plan><objetivo>calc</objetivo>
<tarea id="1" archivos="calc.py, tests/test_calc.py">Crear calc.py con doble(x) y su test.</tarea>
</plan>"""

    def _guion(self, roto):
        def responder(mensajes, kw):
            rol = MockLLM.rol_de(mensajes)
            if rol == "arquitecto":
                return terminar_xml(self.PLAN)
            if rol == "implementador":
                cuerpo = "x + 1" if roto[0] else "x + x"                 # roto: el bug que entrega el modelo
                archivos = [("calc.py", f"def doble(x):\n    return {cuerpo}\n"),
                            ("tests/test_calc.py", "import unittest\nfrom calc import doble\n\n\n"
                                                   "class T(unittest.TestCase):\n    def test_doble(self):\n"
                                                   "        self.assertEqual(doble(4), 8)\n")]
                turno = _turno(mensajes)
                if turno < len(archivos):
                    return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
                return terminar_xml("listo")
            return terminar_xml("sin cambios")
        return responder

    def test_tarea_reintentada_con_su_test_en_rojo_no_queda_verificada(self):
        ws = self.proyecto({})
        roto = [True]
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=0, juez=False, git_snapshots=False)
        orq = lambda: Orquestador(MockLLM(self._guion(roto)), ws, ajustes, self.ui())
        self.assertFalse(orq().construir("calculadora", confirmar=False).ok)
        diario = RegistroBuild(ws).leer()
        self.assertFalse(diario["base_fallaba"])                                    # al empezar no fallaba nada
        self.assertEqual(diario["fallaban_al_inicio"], [])
        ui = self.ui()
        informe = Orquestador(MockLLM(self._guion(roto)), ws, ajustes, ui).construir("", confirmar=False,
                                                                                     reanudar=True)
        self.assertFalse(informe.ok)
        self.assertNotEqual(RegistroBuild(ws).leer()["estados"].get("1"), "verificada")   # antes: "verificada"
        self.assertNotIn("YA falla antes de empezar", ui.texto_registrado())
        self.assertIn("por cambios de esta misma build", ui.texto_registrado())
        roto[0] = False                                                              # el modelo lo corrige
        self.assertTrue(orq().construir("", confirmar=False, reanudar=True).ok)

    def test_fallos_tolerables(self):
        tareas = [Tarea("1", "a", ["calc.py", "tests/test_calc.py"]), Tarea("2", "b", ["web.py", "tests/test_web.py"])]
        fallan = {"test_calc.T.test_doble", "test_web.T.test_ruta", "test_viejo.T.test_x"}
        self.assertEqual(fallos_tolerables_al_reintentar(fallan, ["test_viejo.T.test_x"], tareas[0], tareas),
                         {"test_web.T.test_ruta", "test_viejo.T.test_x"})            # el suyo no se tolera


class TestSeguirDespuesDeUnCorte(BaseTest):
    """En el teléfono la corrida se corta (Termux cerrado, pantalla bloqueada, límite del modelo gratis). Lo natural
    es repetir el mismo comando: antes respondía "ya hay una build incompleta" y había que saber el subcomando."""

    def _ajustes(self):
        return self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                            max_reparaciones=1, juez=False, git_snapshots=False)

    def test_repetir_el_mismo_grande_lo_retoma(self):
        ws = self.proyecto({})
        guion = _GuionBiblioteca(ws, prestamos_roto=True)
        ui = self.ui()
        grande = ConstructorGrande(MockLLM(guion), ws, self._ajustes(), ui)
        pedido = "Un gestor de biblioteca con préstamos y CLI"
        self.assertFalse(grande.iniciar(pedido, confirmar=False))
        self.assertRegex(ui.texto_registrado(),                                     # entero, sin recortar
                         re.escape(f"Desde la terminal: {comando_para_seguir(ws, 'grande')}") + r"(\n|$)")
        guion.prestamos_roto = False
        self.assertTrue(grande.iniciar("  Un gestor de biblioteca   con préstamos y CLI ", confirmar=False))
        self.assertIn("lo retomo donde quedó", ui.texto_registrado())
        self.assertEqual(guion.llamadas["maestro"], 1)                              # no se replanificó
        self.assertEqual(grande.leer()["estado"], "terminado")

    def test_otro_pedido_no_pisa_el_proyecto_a_medias(self):
        ws = self.proyecto({})
        ui = self.ui()
        grande = ConstructorGrande(MockLLM(_GuionBiblioteca(ws, prestamos_roto=True)), ws, self._ajustes(), ui)
        grande.iniciar("Un gestor de biblioteca con préstamos y CLI", confirmar=False)
        self.assertFalse(grande.iniciar("otra cosa distinta", confirmar=False))
        self.assertIn("Ya hay OTRO proyecto grande", ui.texto_registrado())
        self.assertIn("--grande continuar", ui.texto_registrado())
        self.assertEqual(grande.leer()["pedido"], "Un gestor de biblioteca con préstamos y CLI")

    def test_repetir_el_mismo_construir_lo_retoma(self):
        ws = self.proyecto({})
        roto = [True]
        guion = TestReanudarNoRegalaVerdes()._guion(roto)
        llamadas = collections.Counter()

        def contar(mensajes, kw):
            llamadas[MockLLM.rol_de(mensajes)] += 1
            return guion(mensajes, kw)
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=0, juez=False, git_snapshots=False)
        self.assertFalse(Orquestador(MockLLM(contar), ws, ajustes, self.ui()).construir("calculadora", confirmar=False).ok)
        roto[0] = False
        ui = self.ui()
        self.assertTrue(Orquestador(MockLLM(contar), ws, ajustes, ui).construir("calculadora", confirmar=False).ok)
        self.assertIn("la retomo donde quedó", ui.texto_registrado())
        self.assertEqual(llamadas["arquitecto"], 1)                                 # no se replanificó

    def test_pista_y_comando_para_seguir(self):
        ws = self.proyecto({})
        self.assertEqual(pista_para_seguir(ws), "")
        self.assertTrue(comando_para_seguir(ws, "grande").endswith("--grande continuar"))
        casa = Path.home() / "mi proyecto"
        self.assertEqual(comando_para_seguir(casa, "construir"),
                         "reaper --proyecto ~/'mi proyecto' --construir continuar")

    def test_cli_estado_y_continuar_sin_nada_pendiente(self):
        ws = self.proyecto({})
        previos = {k: os.environ.get(k) for k in ("REAPER_LIBRE", "OPENROUTER_API_KEY")}
        os.environ.update({"REAPER_LIBRE": "1", "OPENROUTER_API_KEY": "clave-de-prueba-0123456789"})
        try:
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                self.assertEqual(main(["--proyecto", str(ws.raiz), "--sin-animacion", "--grande", "estado"]), 0)
                self.assertEqual(main(["--proyecto", str(ws.raiz), "--sin-animacion", "--construir", "estado"]), 0)
                self.assertEqual(main(["--proyecto", str(ws.raiz), "--sin-animacion", "--grande", "continuar"]), 2)
            texto = salida.getvalue()
            self.assertIn("No hay ningún proyecto grande", texto)
            self.assertIn("No hay ninguna build pendiente", texto)
            self.assertFalse(ConstructorGrande(None, ws, Settings(), None).ruta.exists())   # no arrancó nada
        finally:
            for k, v in previos.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TestCarpetaDeProyectoNuevo(BaseTest):
    """Prueba real en Termux: `reaper --proyecto ~/almacen --grande "..."` terminaba en "No existe" sin hacer nada."""

    def _con_libre(self, valor):
        previo = os.environ.get("REAPER_LIBRE")
        if valor:
            os.environ["REAPER_LIBRE"] = "1"
        else:
            os.environ.pop("REAPER_LIBRE", None)
        return previo

    def _restaurar(self, previo):
        if previo is None:
            os.environ.pop("REAPER_LIBRE", None)
        else:
            os.environ["REAPER_LIBRE"] = previo

    def test_crea_solo_si_se_pide_y_nunca_fuera_del_home(self):
        nueva = Path(self.dir) / "nuevo" / "almacen"
        previo = self._con_libre(True)
        try:
            with self.assertRaises(ErrorRuta):
                resolver_workspace(str(nueva))
            self.assertFalse(nueva.exists())
            self.assertEqual(resolver_workspace(str(nueva), crear=True), nueva.resolve())
            self.assertTrue(nueva.is_dir())
        finally:
            self._restaurar(previo)
        fuera = Path(self.dir) / "fuera_del_home"
        previo = self._con_libre(False)
        try:
            if Path.home().resolve() in fuera.resolve().parents:
                self.skipTest("la carpeta temporal está dentro del home")
            with self.assertRaises(ErrorRuta) as ctx:
                resolver_workspace(str(fuera), crear=True)
            self.assertIn("Por seguridad", str(ctx.exception))
            self.assertFalse(fuera.exists())                                        # ni siquiera la crea
        finally:
            self._restaurar(previo)

    def test_cli_crea_la_carpeta_para_un_proyecto_nuevo_y_no_para_estado(self):
        nueva = Path(self.dir) / "almacen_cli"
        previo = self._con_libre(True)
        clave = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = "clave-de-prueba-0123456789"
        original = App.construir
        App.construir = lambda self, pedido, confirmar=True, reanudar=False: False
        try:
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                self.assertEqual(main(["--proyecto", str(nueva), "--sin-animacion", "--grande", "estado"]), 1)
                self.assertFalse(nueva.exists())                                    # ver el estado no crea nada
                self.assertEqual(main(["--proyecto", str(nueva), "--sin-animacion", "--construir", "algo"]), 2)
            self.assertTrue(nueva.is_dir())
            self.assertIn("Creé la carpeta del proyecto", salida.getvalue())
        finally:
            App.construir = original
            self._restaurar(previo)
            if clave is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = clave

    def test_proyecto_en_el_repl_pregunta_antes_de_crear(self):
        nueva = Path(self.dir) / "repl_nuevo"
        previo = self._con_libre(True)
        try:
            app = App(self.ajustes(), MockLLM([]), self.ui(respuestas=["s"], interactivo=True), self.proyecto({}),
                      persistir=False)
            app.cmd_proyecto(str(nueva))
            self.assertTrue(nueva.is_dir())
            self.assertEqual(app.ws.raiz, nueva.resolve())
            otra = Path(self.dir) / "repl_no"
            app2 = App(self.ajustes(), MockLLM([]), self.ui(respuestas=["n"], interactivo=True), self.proyecto({}),
                       persistir=False)
            app2.cmd_proyecto(str(otra))
            self.assertFalse(otra.exists())
        finally:
            self._restaurar(previo)


class TestPlanMaestroDeLaPruebaReal(BaseTest):
    """Primera prueba REAL de /grande (Termux, modelos :free, octubre 2026): el plan maestro tenía 10 etapas (un CRUD
    por tabla), una etapa solo de tests, ninguna etapa creaba la web que el pedido nombraba, y el juez tomó "testeadas
    con datos de ejemplo" por una simulación (replanificación de más)."""

    PEDIDO = "Almacén con API JSON y una página web en web/ (index.html, app.js, style.css). Tests con unittest."

    def test_cobertura_de_archivos_nombrados_y_etapas_de_solo_tests(self):
        m = parsear_maestro('<etapa id="1"><objetivo>datos</objetivo><archivos>almacen/db.py, tests/test_db.py'
                            '</archivos></etapa><etapa id="2" deps="1"><objetivo>e2e</objetivo>'
                            '<archivos>tests/test_integracion.py</archivos></etapa>')
        obs = observaciones_maestro(m, self.PEDIDO)
        self.assertTrue(any("index.html, app.js, style.css" in o for o in obs), obs)
        self.assertTrue(any("etapa 2 solo tiene tests" in o for o in obs), obs)
        bien = parsear_maestro('<etapa id="1"><objetivo>x</objetivo><archivos>almacen/api.py, web/index.html, '
                               'web/app.js, web/style.css, tests/test_api.py</archivos></etapa>')
        self.assertEqual(observaciones_maestro(bien, self.PEDIDO), [])

    def test_plan_fragmentado(self):
        texto = "".join(f'<etapa id="{i}"><objetivo>crud {i}</objetivo><archivos>a/m{i}.py, tests/test_m{i}.py'
                        f'</archivos></etapa>' for i in range(1, 9))
        self.assertTrue(any("fragmentado" in o for o in observaciones_maestro(parsear_maestro(texto), "")))

    def test_datos_de_ejemplo_en_tests_no_es_simulacion(self):
        en_tests = Plan("x", [Tarea("1", "Reportes por día, testeadas con datos de ejemplo en una base temporal",
                                    ["r.py"])], [])
        self.assertEqual(problemas_del_plan(en_tests), [])
        simulado = Plan("x", [Tarea("1", "Devolver datos de ejemplo hasta tener la API real", ["r.py"])], [])
        self.assertTrue(problemas_del_plan(simulado))

    def test_observacion_replanifica_una_vez_y_no_frena_si_el_modelo_insiste(self):
        plan_sin_web = ('<maestro><vision>v</vision><etapa id="1"><objetivo>api</objetivo><archivos>almacen/api.py, '
                        'tests/test_api.py</archivos></etapa></maestro>')
        respuestas = []

        def responder(mensajes, kw):
            respuestas.append(MockLLM.ultimo_usuario(mensajes))
            return plan_sin_web
        ui = self.ui()
        grande = ConstructorGrande(MockLLM(responder), self.proyecto({}), self.ajustes(), ui)
        grande.consultar_cuenta = lambda: None
        maestro = grande.planificar(self.PEDIDO, confirmar=False)
        self.assertIsNotNone(maestro)                                               # no se frena por esto
        self.assertEqual(len(respuestas), 2)                                        # UNA replanificación
        self.assertIn("NINGUNA etapa los crea", respuestas[1])                      # con la razón concreta
        self.assertIn("lo vuelve a revisar la integración final", ui.texto_registrado())
