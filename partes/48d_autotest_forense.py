"""Autotests de la guardia de regresión y del modo forense (v8)."""

_NEBULA = '''
import json
import os


class NebulaDB:
    def __init__(self, ruta="nebula.json"):
        self.ruta = ruta
        self.datos = json.load(open(ruta)) if ruta and os.path.exists(ruta) else []

    def insertar(self, doc):
        self.datos.append(doc)
        if self.ruta:
            with open(self.ruta, "w") as f:
                json.dump(self.datos, f)

    def buscar(self, **filtros):
        return [d for d in self.datos if all(d.get(k) == v for k, v in filtros.items())]
'''

_TEST_NEBULA = '''
import unittest

from nebula_db import NebulaDB


class TestNebula(unittest.TestCase):
    def test_buscar(self):
        db = NebulaDB()
        db.insertar({"tipo": "estrella", "nombre": "Sol"})
        self.assertEqual(len(db.buscar(tipo="estrella")), 1)

    def test_vacia(self):
        self.assertEqual(NebulaDB(ruta=None).buscar(tipo="nada"), [])
'''

_ORDEN = {
    "registro.py": "EVENTOS = []\n\n\ndef registrar(e):\n    EVENTOS.append(e)\n    return len(EVENTOS)\n",
    "tests/test_registro.py": (
        "import unittest\nimport registro\n\n\nclass T(unittest.TestCase):\n"
        "    def test_a_registrar(self):\n        self.assertEqual(registro.registrar('x'), 1)\n\n"
        "    def test_b_vacio(self):\n        self.assertEqual(registro.EVENTOS, [])\n"),
}

# 13 tests que dependen de normalizar(); 1 falla al principio (el de los acentos)
_TEXTO = (
    "import unicodedata\n\n\ndef normalizar(t):\n    return t.strip().lower()\n\n\n"
    "def sin_tildes(t):\n    return normalizar(t)\n"
)
_TESTS_TEXTO = "import unittest\nfrom texto import normalizar, sin_tildes\n\n\nclass T(unittest.TestCase):\n" + "".join(
    f"    def test_normalizar_{i}(self):\n        self.assertEqual(normalizar('  Hola{i} '), 'hola{i}')\n\n" for i in range(12)
) + "    def test_tildes(self):\n        self.assertEqual(sin_tildes('Canción'), 'cancion')\n"

_FIX_MALO = "def normalizar(t):\n    return t"            # rompe los 12 de normalizar (y no arregla tildes)
_FIX_BUENO = ("def sin_tildes(t):\n    return ''.join(c for c in unicodedata.normalize('NFKD', normalizar(t)) "
              "if not unicodedata.combining(c))")


def _obs(llm: "MockLLM") -> list:
    return [MockLLM.ultimo_usuario(c["mensajes"]) for c in llm.llamadas]


class TestForenseUnidad(BaseTest):
    def test_comparaciones(self):
        a = ConteoTests(pasados=10, fallados=1, reconocido=True)
        b = ConteoTests(pasados=0, fallados=13, reconocido=True)
        self.assertTrue(es_peor(b, a))
        self.assertTrue(es_mejor(a, b))
        self.assertFalse(es_peor(a, a))
        self.assertFalse(es_peor(b, ConteoTests()))      # sin conteo reconocido no se compara

    def test_nombres(self):
        self.assertEqual(nombres_para_unittest(["test_x.T.test_a", "tests/test_y.py::T::test_b", "basura con espacios"]),
                         ["test_x.T.test_a", "test_y.T.test_b"])

    def test_estado_persistente_entre_corridas(self):
        ws = self.proyecto({"nebula_db.py": _NEBULA, "tests/test_nebula_db.py": _TEST_NEBULA})
        informe = investigar(ws, self.ajustes(), self.ui(), None, con_hipotesis=False,
                             fallidos=["test_nebula_db.TestNebula.test_buscar"])
        texto = informe.texto()
        self.assertTrue(informe.inestables, texto)
        self.assertIn("nebula.json", informe.archivos_tocados_por_tests)
        self.assertIn("PERSISTE", texto)
        self.assertFalse((ws.raiz / "nebula.json").exists(), "la investigación no debe dejar basura en el proyecto")
        self.assertTrue(informe.ruta and informe.ruta.exists())

    def test_dependencia_de_orden_por_global(self):
        ws = self.proyecto(_ORDEN)
        informe = investigar(ws, self.ajustes(), self.ui(), None, con_hipotesis=False)
        self.assertIn("test_registro.T.test_b_vacio", informe.dependientes_de_orden)
        self.assertIn("ESTADO COMPARTIDO", informe.texto())

    def test_locales_y_atributos_en_el_fallo(self):
        ws = self.proyecto({
            "cuenta.py": "class Cuenta:\n    def __init__(self):\n        self.saldo = 5\n        self.titular = 'Ana'\n",
            "tests/test_cuenta.py": "import unittest\nfrom cuenta import Cuenta\n\n\nclass T(unittest.TestCase):\n"
                                    "    def test_saldo(self):\n        c = Cuenta()\n        esperado = 10\n"
                                    "        self.assertEqual(c.saldo, esperado)\n",
        })
        informe = investigar(ws, self.ajustes(), self.ui(), None, con_hipotesis=False)
        texto = informe.texto()
        self.assertIn("esperado=10", texto)
        self.assertIn("'saldo': 5", texto)
        self.assertIn("'titular': 'Ana'", texto)

    def test_biseccion_encuentra_el_bloque_culpable(self):
        ws = self.proyecto({"texto.py": _TEXTO, "tests/test_texto.py": _TESTS_TEXTO,
                            "otro.py": "X = 1\n"})
        bueno = {"texto.py": _TEXTO, "otro.py": "X = 1\n"}
        actual = _TEXTO.replace("def normalizar(t):\n    return t.strip().lower()", _FIX_MALO)
        ws.escribir("texto.py", actual)
        ws.escribir("otro.py", "X = 2\n")
        culpables = biseccion(ws, bueno)
        self.assertEqual(len(culpables), 1)
        self.assertIn("texto.py", culpables[0])
        self.assertIn("+     return t", culpables[0])
        self.assertEqual(ws.leer("texto.py"), actual, "la bisección deja el proyecto como estaba")
        self.assertEqual(ws.leer("otro.py"), "X = 2\n")

    def test_hipotesis_con_experimentos_reales(self):
        ws = self.proyecto({"nebula_db.py": _NEBULA, "tests/test_nebula_db.py": _TEST_NEBULA})
        respuesta_hipotesis = (
            "H1: la base se guarda en un archivo fijo y acumula datos\nEXPERIMENTO:\n```python\n"
            "from nebula_db import NebulaDB\nprint('ruta', NebulaDB().ruta)\n```\nSI ES VERDAD: ruta nebula.json\n\n"
            "H2: borra cosas\nEXPERIMENTO:\n```python\nimport shutil\nshutil.rmtree('.')\n```\nSI ES VERDAD: nada\n")

        def guion(mensajes, kwargs):
            if "Estos son los resultados REALES" in mensajes[-1]["content"]:
                return "CAUSA RAÍZ: el valor por defecto ruta='nebula.json' persiste entre tests.\nARREGLO: ruta=None por defecto."
            return respuesta_hipotesis

        informe = investigar(ws, self.ajustes(), self.ui(), MockLLM(guion),
                             fallidos=["test_nebula_db.TestNebula.test_buscar"])
        self.assertEqual(informe.hipotesis[0].estado, "confirmada")
        self.assertIn("ruta nebula.json", informe.hipotesis[0].resultado)
        self.assertEqual(informe.hipotesis[1].estado, "no ejecutada")      # el experimento inseguro no corre
        self.assertTrue((ws.raiz / "nebula_db.py").exists())
        self.assertIn("CAUSA RAÍZ", informe.conclusion)


class TestGuardiaRegresion(BaseTest):
    def _agente(self, llm, ws, **ajustes):
        return Agente("principal", llm, ws, self.ajustes(forense=False, **ajustes), self.ui(), memoria=None,
                      mostrar_progreso=False)

    def test_un_arreglo_que_empeora_se_revierte(self):
        """El patrón visto en Termux: 1 fallo → el 'arreglo' rompe 13 → REAPER lo revierte → arreglo correcto."""
        ws = self.proyecto({"texto.py": _TEXTO, "tests/test_texto.py": _TESTS_TEXTO})
        llm = MockLLM([
            herramienta_xml("run_tests"),
            herramienta_xml("replace_symbol", path="texto.py", symbol="normalizar", content=_FIX_MALO),
            herramienta_xml("run_tests"),
            herramienta_xml("replace_symbol", path="texto.py", symbol="sin_tildes", content=_FIX_BUENO),
            herramienta_xml("run_tests"),
            terminar_xml("Arreglé sin_tildes; run_tests pasa."),
        ])
        res = self._agente(llm, ws).ejecutar("arreglá los tests")
        obs = _obs(llm)
        self.assertIn("GUARDIA DE REGRESIÓN", obs[3])
        self.assertIn("12 pasaron, 1 fallaron", obs[3])
        self.assertIn("return t.strip().lower()", ws.leer("texto.py"), "el arreglo malo tenía que revertirse")
        self.assertIn("Tests PASARON", obs[5])
        self.assertTrue(res.ok, res.resumen)

    def test_tests_nuevos_no_disparan_la_guardia(self):
        ws = self.proyecto({"texto.py": _TEXTO, "tests/test_texto.py": _TESTS_TEXTO})
        nuevo = _TESTS_TEXTO + "\n    def test_nuevo(self):\n        self.assertEqual(normalizar('A'), 'b')\n"
        llm = MockLLM([
            herramienta_xml("run_tests"),
            herramienta_xml("write_to_file", path="tests/test_texto.py", content=nuevo),
            herramienta_xml("run_tests"),
            terminar_xml("Agregué un test que todavía falla (TDD): falla test_nuevo."),
        ])
        self._agente(llm, ws).ejecutar("agregá un test")
        self.assertNotIn("GUARDIA", " ".join(_obs(llm)))
        self.assertIn("test_nuevo", ws.leer("tests/test_texto.py"))

    def test_guardia_desactivada(self):
        ws = self.proyecto({"texto.py": _TEXTO, "tests/test_texto.py": _TESTS_TEXTO})
        llm = MockLLM([
            herramienta_xml("run_tests"),
            herramienta_xml("replace_symbol", path="texto.py", symbol="normalizar", content=_FIX_MALO),
            herramienta_xml("run_tests"),
            terminar_xml("No pude: ahora fallan 13."),
        ])
        self._agente(llm, ws, guardia_regresion=False).ejecutar("arreglá los tests")
        self.assertIn("return t\n", ws.leer("texto.py"))


class TestForenseEnElAgente(BaseTest):
    def test_antes_de_rendirse_investiga(self):
        ws = self.proyecto({"nebula_db.py": _NEBULA, "tests/test_nebula_db.py": _TEST_NEBULA})
        (ws.raiz / "nebula.json").write_text('[{"tipo": "estrella"}]')        # basura de corridas anteriores
        arreglo = _NEBULA.replace('def __init__(self, ruta="nebula.json"):', "def __init__(self, ruta=None):")

        def guion(mensajes, kwargs):
            if kwargs.get("rol") == "consultor":
                return "sin hipótesis"
            ultimo = MockLLM.ultimo_usuario(mensajes)
            turno = MockLLM.turnos_asistente(mensajes)
            if "INFORME FORENSE" in ultimo:
                return herramienta_xml("write_to_file", path="nebula_db.py", content=arreglo)
            if turno == 0:
                return herramienta_xml("run_tests")
            if turno == 1:  # un "arreglo" que no cambia nada útil
                return herramienta_xml("replace_symbol", path="nebula_db.py", symbol="buscar",
                                       content="def buscar(self, **filtros):\n    return [d for d in self.datos "
                                               "if all(d.get(k) == v for k, v in filtros.items())]")
            if turno == 2:
                return herramienta_xml("run_tests")
            if "Creé" in ultimo or "Modifiqué" in ultimo:
                return herramienta_xml("run_tests")
            if "Tests PASARON" in ultimo:
                return terminar_xml("Arreglado: la base ya no persiste en un archivo fijo por defecto.")
            return terminar_xml("No encontré la causa raíz.")

        llm = MockLLM(guion)
        res = Agente("principal", llm, ws, self.ajustes(escalar=False), self.ui(), memoria=None,
                     mostrar_progreso=False).ejecutar("arreglá los tests de nebula")
        todo = " ".join(_obs(llm))
        self.assertIn("INFORME FORENSE", todo)
        self.assertIn("nebula.json", todo)
        self.assertTrue(res.ok, res.resumen)
        self.assertIn("ruta=None", ws.leer("nebula_db.py"))


class TestGuardiaEnLaReparacion(BaseTest):
    def test_intento_que_empeora_se_revierte(self):
        ws = self.proyecto({"texto.py": _TEXTO, "tests/test_texto.py": _TESTS_TEXTO})
        intentos = []

        def guion(mensajes, kwargs):
            if MockLLM.rol_de(mensajes) != "reparador":
                return terminar_xml("ok")
            turno = MockLLM.turnos_asistente(mensajes)
            if turno == 0:
                intentos.append(mensajes[1]["content"])
                contenido = _FIX_MALO if len(intentos) == 1 else _FIX_BUENO
                simbolo = "normalizar" if len(intentos) == 1 else "sin_tildes"
                return herramienta_xml("replace_symbol", path="texto.py", symbol=simbolo, content=contenido)
            return terminar_xml("listo")

        orq = Orquestador(MockLLM(guion), ws, self.ajustes(forense=False, escalar=False), self.ui())
        orq._protegidos = {}
        grupo = ws.checkpoints.iniciar("build")
        informe = InformeBuild("fallida", cid=grupo)
        verif = orq.verificar(grupo)
        self.assertFalse(verif.ok)
        final = orq._reparar_con_escalada("arreglá", verif, grupo, False, informe, "final", 3,
                                          lambda: orq.verificar(grupo))
        self.assertTrue(final.ok, final.diagnostico)
        self.assertIn("return t.strip().lower()", ws.leer("texto.py"))
        self.assertTrue(any("se revirtió el intento 1" in n for n in informe.notas))
        self.assertIn("EMPEORÓ", intentos[1])

    def test_forense_entra_al_segundo_intento(self):
        ws = self.proyecto({"nebula_db.py": _NEBULA, "tests/test_nebula_db.py": _TEST_NEBULA})
        (ws.raiz / "nebula.json").write_text('[{"tipo": "estrella"}]')
        prompts = []

        def guion(mensajes, kwargs):
            if kwargs.get("rol") == "consultor":
                return "sin hipótesis"
            if MockLLM.rol_de(mensajes) == "reparador" and MockLLM.turnos_asistente(mensajes) == 0:
                prompts.append(mensajes[1]["content"])
            return terminar_xml("no pude")

        orq = Orquestador(MockLLM(guion), ws, self.ajustes(escalar=False), self.ui())
        orq._protegidos = {}
        grupo = ws.checkpoints.iniciar("build")
        informe = InformeBuild("fallida", cid=grupo)
        orq._reparar_con_escalada("arreglá", orq.verificar(grupo), grupo, False, informe, "final", 2,
                                  lambda: orq.verificar(grupo))
        self.assertEqual(len(prompts), 2)
        self.assertNotIn("INFORME FORENSE", prompts[0])
        self.assertIn("INFORME FORENSE", prompts[1])
        self.assertIn("nebula.json", prompts[1])


class TestForenseEvidencia(BaseTest):
    def test_traza_de_llamadas(self):
        ws = self.proyecto({"nebula_db.py": _NEBULA, "tests/test_nebula_db.py": _TEST_NEBULA})
        (ws.raiz / "nebula.json").write_text('[{"tipo": "estrella"}]')
        texto = investigar(ws, self.ajustes(), self.ui(), None, con_hipotesis=False,
                           fallidos=["test_nebula_db.TestNebula.test_buscar"]).texto()
        self.assertIn("→ __init__(ruta='nebula.json')", texto)
        self.assertIn("→ buscar(filtros={'tipo': 'estrella'})", texto)
        self.assertIn("← buscar = [{'tipo': 'estrella'}, {'nombre': 'Sol', 'tipo': 'estrella'}]", texto)
        self.assertNotIn("<genexpr>", texto)
        self.assertEqual((ws.raiz / "nebula.json").read_text(), '[{"tipo": "estrella"}]')

    def test_fixtures_de_setup(self):
        ws = self.proyecto({
            "pila.py": "class Pila:\n    def __init__(self):\n        self.items = []\n"
                       "    def sacar(self):\n        return self.items.pop(0)\n",
            "tests/test_pila.py": "import unittest\nfrom pila import Pila\n\n\nclass T(unittest.TestCase):\n"
                                  "    def setUp(self):\n        self.pila = Pila()\n        self.pila.items = [1, 2, 3]\n\n"
                                  "    def test_lifo(self):\n        self.assertEqual(self.pila.sacar(), 3)\n",
        })
        texto = investigar(ws, self.ajustes(), self.ui(), None, con_hipotesis=False).texto()
        self.assertIn("self=T{'pila': <pila.Pila object", texto)
        self.assertIn("→ sacar()", texto)
        self.assertIn("← sacar = 1", texto)

    def test_parser_de_hipotesis_tolerante(self):
        respuesta = ("**Hipótesis 1:** la ruta es fija\n```python\nprint('fija')\n```\nSi es verdad: fija\n\n"
                     "2) el filtro ignora mayúsculas\n```py\nprint('x')\n```\nESPERADO: x\n\n"
                     "H3: otra idea sin experimento\n")
        hs = parsear_hipotesis(respuesta)
        self.assertEqual([h.texto for h in hs], ["la ruta es fija", "el filtro ignora mayúsculas", "otra idea sin experimento"])
        self.assertEqual([h.esperado for h in hs], ["fija", "x", ""])
        self.assertEqual(hs[2].experimento, "")

    def test_comando_forense(self):
        ws = self.proyecto({"nebula_db.py": _NEBULA, "tests/test_nebula_db.py": _TEST_NEBULA})
        (ws.raiz / "nebula.json").write_text('[{"tipo": "estrella"}]')
        app = App(self.ajustes(escalar=False), MockLLM(lambda m, k: "sin hipótesis"), self.ui(), ws, persistir=False)
        app.comando("/forense")
        texto = app.ui.texto_registrado()
        self.assertIn("INFORME FORENSE", texto)
        self.assertIn("nebula.json", texto)
