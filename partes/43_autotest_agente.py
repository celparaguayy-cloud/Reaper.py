"""Autotest: bucle del agente, escritor largo, torneo, escalada, git y pipeline completo (con MockLLM)."""

_TEST_CALC = '''import unittest
from calc import resta, suma


class TestCalc(unittest.TestCase):
    def test_suma(self):
        self.assertEqual(suma(2, 3), 5)

    def test_resta(self):
        self.assertEqual(resta(5, 3), 2)


if __name__ == "__main__":
    unittest.main()
'''

_CALC_BIEN = "def suma(a, b):\n    return a + b\n\n\ndef resta(a, b):\n    return a - b\n"
_CALC_MAL = "def suma(a, b):\n    return a + b\n\n\ndef resta(a, b):\n    return b - a\n"


def _turno(mensajes: list) -> int:
    return MockLLM.turnos_asistente(mensajes)


class TestAgente(BaseTest):
    def agente(self, llm, ws, rol="principal", **ajustes) -> Agente:
        return Agente(rol, llm, ws, self.ajustes(**ajustes), self.ui(), memoria=None, mostrar_progreso=False)

    def test_flujo_basico(self):
        ws = self.proyecto({"calc.py": "def suma(a, b):\n    return a - b\n"})
        llm = MockLLM([
            "Leo la función.\n" + herramienta_xml("read_symbol", path="calc.py", symbol="suma"),
            herramienta_xml("replace_symbol", path="calc.py", symbol="suma", content="def suma(a, b):\n    return a + b"),
            terminar_xml("Arreglé suma."),
        ])
        res = self.agente(llm, ws).ejecutar("arreglá suma en calc.py")
        self.assertTrue(res.ok, res.resumen)
        self.assertEqual(res.cambios, ["calc.py"])
        self.assertIn("a + b", ws.leer("calc.py"))
        self.assertEqual(res.motivo, "completado")
        # El mapa de archivos relevantes se agregó al pedido.
        self.assertIn("ARCHIVOS PROBABLEMENTE RELEVANTES", llm.llamadas[0]["mensajes"][1]["content"])

    def test_respuesta_directa(self):
        res = self.agente(MockLLM(["Python es un lenguaje."]), self.proyecto()).ejecutar("¿qué es python?")
        self.assertEqual((res.motivo, res.resumen), ("respuesta", "Python es un lenguaje."))

    def test_recordatorio_si_no_usa_herramientas(self):
        llm = MockLLM(["```python\nprint(1)\n```", herramienta_xml("write_to_file", path="a.py", content="print(1)"),
                       terminar_xml("listo")])
        res = self.agente(llm, self.proyecto(), rol="implementador").ejecutar("creá a.py")
        self.assertTrue(res.ok)
        self.assertIn("No usaste ninguna herramienta", llm.llamadas[1]["mensajes"][-1]["content"])

    def test_continuacion_de_archivo_cortado(self):
        ws = self.proyecto()
        cortado = ("Escribo el archivo.\n<write_to_file>\n<path>largo.py</path>\n<content>\n"
                   "def uno():\n    return 1\n\n\ndef dos():\n    return 2\n\n\ndef tres():\n    ret")
        llm = MockLLM([
            (cortado, "length"),
            herramienta_xml("append_to_file", path="largo.py",
                            content="def tres():\n    return 3\n\n\ndef cuatro():\n    return 4\n", last="true"),
            terminar_xml("Archivo largo completo."),
        ])
        res = self.agente(llm, ws, rol="implementador").ejecutar("creá largo.py con cuatro funciones")
        self.assertTrue(res.ok, res.resumen)
        texto = ws.leer("largo.py")
        for nombre in ("uno", "dos", "tres", "cuatro"):
            self.assertEqual(texto.count(f"def {nombre}"), 1, texto)
        compile(texto, "largo.py", "exec")
        self.assertIn("SEGUÍ DESDE", llm.llamadas[1]["mensajes"][-1]["content"])

    def test_rechaza_cierre_con_validacion_fallida(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("write_to_file", path="m.py", content="def f(:\n    pass") + "\n" + terminar_xml("ya está"),
            herramienta_xml("write_to_file", path="m.py", content="def f():\n    return 1"),
            terminar_xml("ahora sí"),
        ])
        res = self.agente(llm, ws, rol="implementador").ejecutar("creá m.py")
        self.assertTrue(res.ok)
        self.assertEqual(res.resumen, "ahora sí")
        self.assertIn("No acepto el cierre", llm.llamadas[1]["mensajes"][-1]["content"])

    def test_rechaza_funciones_vacias(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("write_to_file", path="v.py", content="def f():\n    pass\n\n\ndef g():\n    return 2"),
            terminar_xml("listo"),
            herramienta_xml("replace_symbol", path="v.py", symbol="f", content="def f():\n    return 1"),
            terminar_xml("implementado"),
        ])
        res = self.agente(llm, ws, rol="implementador").ejecutar("creá v.py")
        self.assertEqual(res.resumen, "implementado")
        self.assertIn("sin implementar", llm.llamadas[2]["mensajes"][-1]["content"])

    def test_rechaza_archivos_en_construccion(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("write_to_file", path="p.py", content="x = 1", partial="true"),
            terminar_xml("listo"),
            herramienta_xml("append_to_file", path="p.py", content="y = 2", last="true"),
            terminar_xml("completo"),
        ])
        res = self.agente(llm, ws, rol="implementador").ejecutar("creá p.py")
        self.assertEqual(res.resumen, "completo")
        self.assertIn("EN CONSTRUCCIÓN", llm.llamadas[2]["mensajes"][-1]["content"])

    def test_escalada_cuando_se_repite_el_error(self):
        ws = self.proyecto({"calc.py": _CALC_MAL, "tests/test_calc.py": _TEST_CALC})
        consultas = []

        def experto(error: str) -> str:
            consultas.append(error)
            return "DIAGNÓSTICO: resta invierte los operandos.\nARREGLO: return a - b"

        llm = MockLLM([
            herramienta_xml("run_tests"),
            herramienta_xml("run_tests"),
            herramienta_xml("replace_symbol", path="calc.py", symbol="resta", content="def resta(a, b):\n    return a - b"),
            terminar_xml("arreglado con ayuda"),
        ])
        agente = Agente("reparador", llm, ws, self.ajustes(escalar=True, umbral_escalada=2), self.ui(),
                        memoria=None, mostrar_progreso=False, on_atascado=experto)
        res = agente.ejecutar("los tests fallan")
        self.assertTrue(res.ok)
        self.assertTrue(res.escalado)
        self.assertEqual(len(consultas), 1)
        self.assertIn("test_resta", consultas[0])
        self.assertIn("DIAGNÓSTICO DE UN EXPERTO", llm.llamadas[2]["mensajes"][-1]["content"])

    def test_delegacion_en_paralelo(self):
        ws = self.proyecto({"a.py": "x = 1\n"})

        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            if rol == "explorador":
                return terminar_xml("INFORME: a.py define x.")
            if _turno(mensajes) == 0:
                return (herramienta_xml("delegate", role="explorador", task="mirá a.py") + "\n"
                        + herramienta_xml("delegate", role="explorer", task="mirá otra cosa"))
            return terminar_xml("Listo, ya sé todo.")

        res = self.agente(MockLLM(guion), ws, paralelo=2).ejecutar("investigá el proyecto")
        self.assertTrue(res.ok)

    def test_herramienta_no_permitida(self):
        llm = MockLLM([herramienta_xml("write_to_file", path="x.py", content="x = 1"), terminar_xml("informe")])
        res = self.agente(llm, self.proyecto(), rol="explorador").ejecutar("explorá")
        self.assertFalse((self.dir / "proy" / "x.py").exists())
        self.assertIn("no está disponible", llm.llamadas[1]["mensajes"][-1]["content"])
        self.assertTrue(res.ok)

    def test_limite_de_pasos(self):
        llm = MockLLM(lambda m, k: herramienta_xml("search_files", regex=f"cosa{_turno(m)}"))
        res = self.agente(llm, self.proyecto({"a.py": "1"}), max_pasos=4).ejecutar("dá vueltas")
        self.assertEqual(res.motivo, "max_pasos")
        self.assertFalse(res.ok)

    def test_bucle_alternado_se_corta(self):
        llm = MockLLM(lambda m, k: herramienta_xml("list_files", path=".", recursive=str(_turno(m) % 2 == 0)))
        res = self.agente(llm, self.proyecto({"a.py": "1"}), max_pasos=10).ejecutar("dá vueltas")
        self.assertEqual(res.motivo, "bucle")
        self.assertFalse(res.ok)
        self.assertLess(res.pasos, 6)

    def test_compactacion(self):
        ws = self.proyecto()
        agente = self.agente(MockLLM([]), ws, contexto_tokens=6000, max_tokens=1000)
        agente.mensajes = [{"role": "system", "content": "s"}, {"role": "user", "content": "tarea"}]
        for i in range(30):
            agente.mensajes.append({"role": "assistant", "content": f"<write_to_file><path>a</path><content>{'x' * 900}</content></write_to_file>"})
            agente.mensajes.append({"role": "user", "content": f'<resultado herramienta="read_file">\n{"y" * 2000}\n</resultado>'})
        agente._indice_tarea = 1
        antes = agente._tamano()
        agente._compactar()
        self.assertLess(agente._tamano(), antes)
        self.assertLessEqual(agente._tamano(), agente._limite_contexto() * 1.2)
        self.assertEqual(agente.mensajes[1]["content"].split("\n")[0], "tarea")

    def test_recupera_contexto_excedido(self):
        llamadas = []

        class LLMExcedido(MockLLM):
            def chat(self, mensajes, **kwargs):
                llamadas.append(1)
                if len(llamadas) == 1:
                    raise LLMError("contexto", contexto_excedido=True)
                return super().chat(mensajes, **kwargs)

        res = self.agente(LLMExcedido(["respuesta corta"]), self.proyecto()).ejecutar("hola")
        self.assertEqual(res.resumen, "respuesta corta")
        self.assertEqual(len(llamadas), 2)


class TestEscritorLargo(BaseTest):
    ESQUELETO = '''"""Inventario."""

from dataclasses import dataclass


@dataclass
class Producto:
    nombre: str
    precio: float
    stock: int = 0


class Inventario:
    def __init__(self):
        """Crea el inventario vacío."""
        self.productos = {}

    def agregar(self, producto):
        """Agrega o reemplaza un producto por nombre."""
        raise NotImplementedError("REAPER")

    def valor_total(self):
        """Suma precio * stock de todos los productos."""
        raise NotImplementedError("REAPER")


def formatear(valor):
    """Devuelve el valor con 2 decimales y signo $."""
    raise NotImplementedError("REAPER")
'''

    def guion(self, mensajes, kwargs):
        prompt = mensajes[-1]["content"]
        if "ESQUELETO" in prompt and "IMPLEMENTÁ AHORA" not in prompt:
            return "```python\n" + self.ESQUELETO + "```"
        implementaciones = {
            "agregar": "def agregar(self, producto):\n    self.productos[producto.nombre] = producto",
            "valor_total": "def valor_total(self):\n    return sum(p.precio * p.stock for p in self.productos.values())",
            "formatear": "def formatear(valor):\n    return f\"${valor:.2f}\"",
        }
        pedidas = re.findall(r"`(\w+)`", prompt.split("IMPLEMENTÁ AHORA")[1].split("\n")[0])
        return "\n\n".join(f"```python\n{implementaciones[n]}\n```" for n in pedidas)

    def test_esqueleto_y_relleno(self):
        ws = self.proyecto()
        escritor = EscritorLargo(MockLLM(self.guion), ws, self.ajustes(paralelo=2), self.ui())
        informe = escritor.escribir("inventario.py", "Un inventario con productos, valor total y formato de dinero.")
        self.assertTrue(informe.ok, informe.texto())
        self.assertEqual((informe.funciones, informe.rellenadas), (3, 3))
        texto = ws.leer("inventario.py")
        self.assertNotIn("REAPER", texto)
        espacio: dict = {}
        exec(compile(texto, "inventario.py", "exec"), espacio)
        inv = espacio["Inventario"]()
        inv.agregar(espacio["Producto"]("pan", 2.5, 4))
        self.assertEqual(espacio["formatear"](inv.valor_total()), "$10.00")

    def test_reintenta_con_el_error(self):
        intentos = collections.Counter()

        def guion(mensajes, kwargs):
            prompt = mensajes[-1]["content"]
            if "IMPLEMENTÁ AHORA" not in prompt:
                return "```python\ndef doble(x):\n    \"\"\"Duplica.\"\"\"\n    raise NotImplementedError(\"REAPER\")\n```"
            intentos["doble"] += 1
            if intentos["doble"] == 1:
                return "```python\ndef doble(x):\n    return variable_inexistente * 2\n```"
            return "```python\ndef doble(x):\n    return x * 2\n```"

        ws = self.proyecto()
        informe = EscritorLargo(MockLLM(guion), ws, self.ajustes(), self.ui()).escribir("d.py", "duplica números enteros")
        self.assertTrue(informe.ok)
        self.assertEqual(intentos["doble"], 2)

    def test_lenguaje_no_soportado(self):
        with self.assertRaises(ErrorEscritor):
            EscritorLargo(MockLLM([]), self.proyecto(), self.ajustes(), self.ui()).escribir("x.go", "algo")

    def test_utilidades(self):
        self.assertEqual(extraer_bloques_codigo("texto\n```py\nx = 1\n```"), [("py", "x = 1")])
        self.assertEqual(len(simbolos_pendientes(self.ESQUELETO, "i.py")), 3)
        self.assertIn("class Inventario", contorno_archivo(self.ESQUELETO * 3, "i.py", maximo=600))


class TestTorneo(BaseTest):
    def setUp(self):
        super().setUp()
        self.ws = self.proyecto({"tests/test_calc.py": _TEST_CALC, "README.md": "calculadora\n"})
        self.spec = copiar_contenidos(self.ws, ["tests/test_calc.py"])

    def guion(self, mensajes, kwargs):
        t = kwargs.get("temperatura")
        if _turno(mensajes) >= 1:
            return terminar_xml(f"listo t={t}")
        if t == 0.1:
            return herramienta_xml("write_to_file", path="calc.py", content=_CALC_BIEN)
        if t == 0.4:
            return herramienta_xml("write_to_file", path="calc.py", content=_CALC_MAL)
        # El tramposo intenta debilitar la especificación (y además implementa mal).
        return (herramienta_xml("write_to_file", path="calc.py", content=_CALC_MAL) + "\n"
                + herramienta_xml("write_to_file", path="tests/test_calc.py", content="import unittest\n"))

    def test_gana_el_que_pasa_mas_tests(self):
        ajustes = self.ajustes(candidatos=3, paralelo_torneo=2)
        cid = self.ws.checkpoints.iniciar("torneo")
        res = Torneo(MockLLM(self.guion), self.ws, ajustes, self.ui()).correr(
            "implementá calc.py", n=3, protegidos=self.spec, cid=cid)
        self.assertEqual(res.modo, "torneo")
        self.assertEqual(res.ganador.temperatura, 0.1)
        self.assertEqual(res.ganador.conteo.pasados, 2)
        self.assertTrue(res.todos_pasan)
        self.assertEqual(res.aplicados, ["calc.py"])
        self.assertEqual(self.ws.leer("calc.py"), _CALC_BIEN)
        self.assertEqual(self.ws.leer("tests/test_calc.py"), _TEST_CALC, "la especificación no se toca")
        perdedores = {round(c.temperatura, 1): c.conteo.pasados for c in res.candidatos}
        self.assertEqual(perdedores[0.4], 1)
        self.assertEqual(perdedores[0.7], 1, "el tramposo no gana: la especificación se restaura antes de puntuar")
        self.assertEqual(list((self.dir / "home" / "tmp").glob("reaper_*")), [], "las copias se limpian")
        self.ws.checkpoints.deshacer(cid)
        self.assertFalse(self.ws.existe("calc.py"))

    def test_desempate_por_menos_lineas(self):
        largo = _CALC_BIEN + "\n\n# comentario\n" + "\n".join(f"# relleno {i}" for i in range(20)) + "\n"

        def guion(mensajes, kwargs):
            if _turno(mensajes) >= 1:
                return terminar_xml("listo")
            contenido = largo if kwargs.get("temperatura") == 0.1 else _CALC_BIEN
            return herramienta_xml("write_to_file", path="calc.py", content=contenido)

        res = Torneo(MockLLM(guion), self.ws, self.ajustes(candidatos=2, paralelo_torneo=1), self.ui()).correr(
            "implementá calc.py", n=2, protegidos=self.spec)
        self.assertEqual(res.ganador.temperatura, 0.4)
        self.assertEqual(self.ws.leer("calc.py"), _CALC_BIEN)

    def test_tests_nuevos_no_inflan_el_puntaje(self):
        trivial = "import unittest\n\nclass T(unittest.TestCase):\n" + "".join(
            f"    def test_{i}(self):\n        self.assertTrue(True)\n" for i in range(5))

        def guion(mensajes, kwargs):
            if _turno(mensajes) >= 1:
                return terminar_xml("listo")
            if kwargs.get("temperatura") == 0.1:
                return (herramienta_xml("write_to_file", path="calc.py", content=_CALC_MAL) + "\n"
                        + herramienta_xml("write_to_file", path="tests/test_extra.py", content=trivial))
            return herramienta_xml("write_to_file", path="calc.py", content=_CALC_BIEN)

        res = Torneo(MockLLM(guion), self.ws, self.ajustes(candidatos=2, paralelo_torneo=1), self.ui()).correr(
            "implementá calc.py", n=2, protegidos=self.spec)
        self.assertEqual(res.ganador.temperatura, 0.4)

    def test_modo_simple(self):
        def guion(mensajes, kwargs):
            return terminar_xml("ok") if _turno(mensajes) else herramienta_xml("write_to_file", path="calc.py", content=_CALC_BIEN)

        res = Torneo(MockLLM(guion), self.ws, self.ajustes(), self.ui()).correr("implementá", n=1, protegidos=self.spec)
        self.assertEqual(res.modo, "simple")
        self.assertTrue(res.todos_pasan)

    def test_ningun_candidato_util(self):
        res = Torneo(MockLLM(lambda m, k: terminar_xml("no hice nada")), self.ws,
                     self.ajustes(candidatos=2, paralelo_torneo=1), self.ui()).correr("x", n=2)
        self.assertIsNone(res.ganador)
        self.assertFalse(res.ok)


class TestEscalador(BaseTest):
    def test_diagnostico_con_modelo_fuerte(self):
        modelos = []

        def guion(mensajes, kwargs):
            modelos.append(kwargs.get("modelo"))
            return terminar_xml("DIAGNÓSTICO: resta invierte los operandos.\nARREGLO: return a - b\nVERIFICACIÓN: run_tests")

        ws = self.proyecto({"calc.py": _CALC_MAL})
        escalador = Escalador(MockLLM(guion), self.ajustes(escalar=True, modelo_fuerte="deepseek"), self.ui())
        self.assertTrue(escalador.disponible())
        diagnostico = escalador.diagnosticar(ws, "arreglá resta", "AssertionError: -2 != 2", ["calc.py"])
        self.assertIn("invierte", diagnostico)
        self.assertEqual(modelos[0], "deepseek/deepseek-chat")
        self.assertEqual(len(escalador.historial), 1)
        self.assertIn("consulta", escalador.resumen())
        self.assertIn("DIAGNÓSTICO DE UN EXPERTO", tarea_con_diagnostico("t", diagnostico))

    def test_no_disponible(self):
        mismo = Escalador(MockLLM([]), self.ajustes(escalar=True, modelo_fuerte="venice"), self.ui())
        self.assertFalse(mismo.disponible())
        apagado = Escalador(MockLLM([]), self.ajustes(escalar=False), self.ui())
        self.assertIsNone(apagado.diagnosticar(self.proyecto(), "t", "e"))
        self.assertIsNone(apagado.gancho(self.proyecto(), "t"))


class TestGit(BaseTest):
    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git no está instalado")
        self.ws = self.proyecto({"a.py": "x = 1\n", ".gitignore": "*.log\n"})
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        git(self.ws, "init", "-q")
        git(self.ws, "add", "-A", env=env)
        git(self.ws, "commit", "-q", "-m", "inicial", env=env)
        self.head = git(self.ws, "rev-parse", "HEAD").stdout.strip()

    def test_snapshot_no_toca_la_rama_del_usuario(self):
        (self.ws.raiz / "a.py").write_text("x = 2\n")
        (self.ws.raiz / "ruido.log").write_text("no va")
        commit = snapshot_build(self.ws, "reaper/builds", "build 1")
        self.assertTrue(commit)
        self.assertEqual(git(self.ws, "rev-parse", "HEAD").stdout.strip(), self.head)
        self.assertIn("a.py", git(self.ws, "status", "--short").stdout)
        self.assertIn("x = 2", git(self.ws, "show", "reaper/builds:a.py").stdout)
        self.assertNotIn("ruido.log", git(self.ws, "ls-tree", "-r", "--name-only", "reaper/builds").stdout)
        self.assertIsNone(snapshot_build(self.ws, "reaper/builds", "sin cambios"))
        (self.ws.raiz / "b.py").write_text("y = 1\n")
        self.assertTrue(snapshot_build(self.ws, "reaper/builds", "build 2"))
        self.assertEqual(len(log_rama(self.ws).splitlines()), 3)
        self.assertIn("rama:", estado_git(self.ws))

    def test_rama_invalida(self):
        with self.assertRaises(RuntimeError):
            snapshot_build(self.ws, "../malo", "x")


class TestPipeline(BaseTest):
    PLAN = """<plan>
<objetivo>Calculadora con suma y resta</objetivo>
<interfaz>
- calc.py: def suma(a, b) -> número
- calc.py: def resta(a, b) -> número
</interfaz>
<tarea id="1" archivos="calc.py">Crear calc.py con suma(a, b) y resta(a, b).</tarea>
<criterios>
- suma(2, 3) == 5
- resta(5, 3) == 2
</criterios>
</plan>"""

    def guion_base(self, mensajes, kwargs, implementador):
        rol = MockLLM.rol_de(mensajes)
        turno = _turno(mensajes)
        if rol == "arquitecto":
            return terminar_xml(self.PLAN)
        if rol == "especificador":
            if turno == 0:
                return herramienta_xml("write_to_file", path="tests/test_calc.py", content=_TEST_CALC)
            return terminar_xml("Especificación escrita: tests/test_calc.py (fallan: falta calc.py)")
        if rol == "implementador":
            return implementador(mensajes, kwargs, turno)
        if not rol:  # chat_simple de lecciones
            return ("PROYECTO: En calc.py resta(a, b) debe devolver a - b (no b - a)\n"
                    "GENERAL: Revisar el orden de los operandos en funciones no conmutativas como resta")
        return terminar_xml("ok")

    def test_tests_primero_y_torneo(self):
        def implementador(mensajes, kwargs, turno):
            if turno >= 1:
                return terminar_xml("calc.py implementado")
            contenido = _CALC_BIEN if kwargs.get("temperatura") == 0.1 else _CALC_MAL
            return herramienta_xml("write_to_file", path="calc.py", content=contenido)

        ws = self.proyecto({"README.md": "# calculadora\n"})
        llm = MockLLM(lambda m, k: self.guion_base(m, k, implementador))
        ajustes = self.ajustes(tests_primero=True, torneo=True, candidatos=2, paralelo_torneo=1, lecciones=True)
        informe = Orquestador(llm, ws, ajustes, self.ui()).construir("calculadora con suma y resta", confirmar=False)
        self.assertEqual(informe.estado, "verificada", informe.notas)
        self.assertEqual(informe.spec_tests, ["tests/test_calc.py"])
        self.assertEqual(informe.torneos[0][1], "torneo")
        self.assertEqual(ws.leer("calc.py"), _CALC_BIEN)
        self.assertEqual(ws.leer("tests/test_calc.py"), _TEST_CALC)
        self.assertTrue(informe.ruta_informe and informe.ruta_informe.exists())
        roles = [MockLLM.rol_de(c["mensajes"]) for c in llm.llamadas]
        self.assertLess(roles.index("especificador"), roles.index("implementador"), "los tests van ANTES")

    def test_reparacion_con_escalada_y_leccion(self):
        def implementador(mensajes, kwargs, turno):
            if turno >= 1:
                return terminar_xml("implementado")
            return herramienta_xml("write_to_file", path="calc.py", content=_CALC_MAL)

        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
            if rol == "consultor":
                return terminar_xml("DIAGNÓSTICO: resta usa b - a.\nARREGLO: en calc.py, resta debe devolver a - b.")
            if rol == "reparador":
                tarea = mensajes[1]["content"]
                if turno >= 1:
                    return terminar_xml("Corregí resta: el orden de los operandos estaba invertido.")
                if "DIAGNÓSTICO DE UN EXPERTO" in tarea:
                    return herramienta_xml("replace_symbol", path="calc.py", symbol="resta",
                                           content="def resta(a, b):\n    return a - b")
                return herramienta_xml("replace_symbol", path="calc.py", symbol="resta",
                                       content="def resta(a, b):\n    return -(b - a) * -1")
            return self.guion_base(mensajes, kwargs, implementador)

        ws = self.proyecto({"README.md": "# calculadora\n"})
        ajustes = self.ajustes(tests_primero=True, torneo=False, escalar=True, umbral_escalada=2,
                               modelo_fuerte="deepseek", max_reparaciones=4, lecciones=True)
        orq = Orquestador(MockLLM(guion), ws, ajustes, self.ui())
        orq.memoria = MemoriaLecciones(ws, ruta_global=self.dir / "lecciones_globales.md")
        informe = orq.construir("calculadora", confirmar=False)
        self.assertEqual(informe.estado, "verificada", informe.diagnostico)
        self.assertEqual(informe.escaladas, 1)
        self.assertEqual(ws.leer("calc.py"), _CALC_BIEN)
        self.assertTrue(informe.lecciones, "la reparación exitosa deja una lección")
        self.assertTrue(any("resta" in l.texto for l in orq.memoria.proyecto.cargar()))

    def test_cancelar_plan(self):
        llm = MockLLM(lambda m, k: terminar_xml(self.PLAN))
        informe = Orquestador(llm, self.proyecto(), self.ajustes(), self.ui(respuestas=[False, ""])).construir("x")
        self.assertEqual(informe.estado, "cancelada")

    def test_parsear_plan(self):
        plan = parsear_plan(self.PLAN, "pedido")
        self.assertEqual(plan.objetivo, "Calculadora con suma y resta")
        self.assertEqual(plan.tareas[0].archivos, ["calc.py"])
        self.assertIn("def suma", plan.interfaz)
        self.assertEqual(len(plan.criterios), 2)
        self.assertIn("calc.py", plan.archivos())
        libre = parsear_plan("1. Crear el modelo de datos\n2. Agregar la interfaz web", "p")
        self.assertEqual(len(libre.tareas), 2)
        muchas = parsear_plan("".join(f'<tarea id="{i}">tarea número {i}</tarea>' for i in range(12)), "p", max_tareas=4)
        self.assertEqual(len(muchas.tareas), 4)
        self.assertEqual(veredicto("VEREDICTO: CAMBIOS\n1. x"), (False, True))
        self.assertEqual(veredicto("sin formato"), (True, False))

    def test_especificacion_reconoce_tests(self):
        self.assertTrue(_es_de_especificacion("test_calc.TestCalc.test_resta", {"tests/test_calc.py": ""}))
        self.assertTrue(_es_de_especificacion("tests/test_calc.py::test_resta", {"tests/test_calc.py": ""}))
        self.assertFalse(_es_de_especificacion("test_otro.T.test_x", {"tests/test_calc.py": ""}))
