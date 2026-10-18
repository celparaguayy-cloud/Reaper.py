"""
Termux recién instalado (solo python y git; sin node, ruff ni pytest) — corrida E2E del almacén en ese entorno:

- Sin node, la suite corría solo los tests de Python y la etapa Web quedaba "✓ BUILD VERIFICADA · validadores + tests
  reales" aunque tests/logica.test.mjs no se había ejecutado NUNCA (falso verde). El especificador además decía "la
  especificación ya pasa entera".
- Ahora: si lo que se cambió toca JavaScript y hay tests de JS que no pueden correr, no queda verificada; si es lo
  único que falla, no se gastan reparaciones (no se arregla con código); /grande se frena ANTES de gastar pedidos en esa
  etapa y avisa al empezar; el maestro y los roles saben que no hay node para no planificar tests de JS.
"""
import contextlib as _ztp_contextlib


@_ztp_contextlib.contextmanager
def _ztp_sin_node():
    from unittest.mock import patch
    original = shutil.which
    with patch("shutil.which", lambda nombre, *a, **k: None if nombre == "node" else original(nombre, *a, **k)):
        yield


_ZTP_TEST_JS = ('import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                'import { doble } from "../web/logica.js";\n\ntest("doble", () => { assert.equal(doble(2), 4); });\n')
_ZTP_LOGICA = "export function doble(x) {\n  return x * 2;\n}\n"
_ZTP_TEST_PY = ("import unittest\n\nfrom ops import suma\n\n\nclass T(unittest.TestCase):\n    def test_suma(self):\n"
                "        self.assertEqual(suma(2, 3), 5)\n")


class TestSinNodeNoHayFalsoVerde(BaseTest):
    def test_detecta_tests_js_que_no_pueden_correr(self):
        ws = self.proyecto({"tests/logica.test.mjs": _ZTP_TEST_JS, "web/logica.js": _ZTP_LOGICA, "ops.py": "x = 1\n"})
        with _ztp_sin_node():
            self.assertEqual(tests_js_sin_node(ws.raiz, ["web/logica.js"]), ["tests/logica.test.mjs"])
            self.assertEqual(tests_js_sin_node(ws.raiz, ["ops.py"]), [])        # un cambio de Python no se frena
        if shutil.which("node"):
            self.assertEqual(tests_js_sin_node(ws.raiz, ["web/logica.js"]), [])

    def test_la_build_no_queda_verificada_y_no_se_repara_a_ciegas(self):
        ws = self.proyecto({"ops.py": "def suma(a, b):\n    return a + b\n", "tests/test_ops.py": _ZTP_TEST_PY})
        orq = Orquestador(MockLLM(lambda m, k: terminar_xml("x")), ws, self.ajustes(forense=False), self.ui())
        cid = ws.checkpoints.iniciar("web")
        ws.escribir("web/logica.js", _ZTP_LOGICA)
        ws.escribir("tests/logica.test.mjs", _ZTP_TEST_JS)
        llamadas = []
        orq.reparar = lambda *a, **k: llamadas.append(1) or ResultadoAgente(True, "listo")
        with _ztp_sin_node():
            verif = orq.verificar(cid)
            self.assertFalse(verif.ok)                                      # antes: verificada (solo corrían los .py)
            self.assertTrue(verif.solo_entorno)
            self.assertIn("TESTS DE JAVASCRIPT SIN CORRER", verif.diagnostico)
            self.assertIn("pkg install nodejs", verif.diagnostico)
            informe = InformeBuild("fallida")
            final = orq._reparar_con_escalada("web", verif, cid, False, informe, "final", 3, lambda: orq.verificar(cid))
        self.assertFalse(final.ok)
        self.assertEqual(llamadas, [])                                      # no se gastan reparaciones
        self.assertTrue(any("TESTS DE JAVASCRIPT SIN CORRER" in n for n in informe.notas))

    def test_los_roles_saben_que_no_hay_node(self):
        with _ztp_sin_node():
            self.assertIn("node NO está instalado", _entorno())
        if shutil.which("node"):
            self.assertNotIn("node NO está instalado", _entorno())


class _ZTP_GuionWeb:
    MAESTRO = """<maestro>
<vision>Una utilidad de números y una web.</vision>
<arquitectura>Python 3 y JS sin dependencias. Tests con unittest y node:test.</arquitectura>
<etapa id="1" titulo="Números" deps="">
<objetivo>suma(a, b)</objetivo>
<archivos>ops.py, tests/test_ops.py</archivos>
</etapa>
<etapa id="2" titulo="Web" deps="1">
<objetivo>doble(x) en JS</objetivo>
<archivos>web/logica.js, tests/logica.test.mjs</archivos>
</etapa>
</maestro>"""

    def __init__(self):
        self.prompts_maestro = []
        self.arquitecto = 0

    def __call__(self, mensajes, kw):
        rol = MockLLM.rol_de(mensajes)
        primero = next((m["content"] for m in mensajes if m["role"] == "user"), "")
        if rol == "maestro":
            self.prompts_maestro.append(primero)
            return self.MAESTRO
        if rol == "arquitecto":
            self.arquitecto += 1
            return terminar_xml('<plan><objetivo>N</objetivo><tarea id="1" archivos="ops.py, tests/test_ops.py">'
                                'suma con test</tarea></plan>')
        if rol == "implementador":
            archivos = [("ops.py", "def suma(a, b):\n    return a + b\n"), ("tests/test_ops.py", _ZTP_TEST_PY)]
            turno = _turno(mensajes)
            if turno < len(archivos):
                return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
        return terminar_xml("listo")


class TestGrandeSinNode(BaseTest):
    def test_se_frena_antes_de_gastar_pedidos_en_la_etapa_de_js(self):
        ws = self.proyecto({})
        guion = _ZTP_GuionWeb()
        ui = self.ui()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               juez=False, git_snapshots=False, forense=False)
        grande = ConstructorGrande(MockLLM(guion), ws, ajustes, ui)
        grande.consultar_cuenta = lambda: None
        grande.dormir = lambda s: self.fail(f"no debía esperar {s}s")
        with _ztp_sin_node():
            self.assertFalse(grande.iniciar("Números y una web con su lógica en JS", confirmar=False))
        estado = grande.leer()
        etapas = {e["id"]: e for e in estado["maestro"]["etapas"]}
        self.assertEqual(etapas["1"]["estado"], "verificada")
        self.assertEqual(etapas["2"]["estado"], "pendiente")                 # ni se intentó
        self.assertEqual(guion.arquitecto, 1)                               # cero pedidos para la etapa 2
        self.assertIn("pkg install nodejs", estado["motivo"])
        texto = ui.texto_registrado()
        self.assertIn("Ojo: la etapa 2 tiene tests de JavaScript", texto)    # avisado al empezar
        self.assertIn("ENTORNO: node NO está instalado", guion.prompts_maestro[0])
