"""Autotests de Test Intelligence (Fase 1 / v9): detectores estáticos + MutationProbe + herramienta."""

_TAUT = '''
import unittest
class T(unittest.TestCase):
    def test_a(self):
        self.assertTrue(True)
    def test_b(self):
        x = 5
        assert x == x
    def test_c(self):
        self.assertEqual(1, 1)
    def test_d(self):
        assert True
'''

_MOCK_SUJETO = '''
import unittest
from app.core import procesar
from unittest.mock import patch
class T(unittest.TestCase):
    def test_proc(self):
        with patch("app.core.procesar", return_value="ok"):
            self.assertEqual(procesar(), "ok")
'''

_INTEGRACION_FALSA = '''
import unittest
import subprocess
from unittest.mock import patch
class T(unittest.TestCase):
    def test_script_integration(self):
        """integration test del script real"""
        with patch("subprocess.run", return_value="Denuncia enviada"):
            r = subprocess.run(["x"])
            self.assertEqual(r, "Denuncia enviada")
'''

_BUENO = '''
import unittest
from calc import suma, dividir
class T(unittest.TestCase):
    def test_suma(self):
        self.assertEqual(suma(2, 3), 5)
    def test_dividir_cero(self):
        with self.assertRaises(ZeroDivisionError):
            dividir(1, 0)
'''


class TestTautologias(BaseTest):
    def test_detecta_variantes(self):
        res = analizar_tests_python(_TAUT)
        tipos = [p.tipo for p in res.problemas]
        self.assertEqual(tipos.count("TAUTOLOGIA"), 4)
        self.assertFalse(res.ok)
        self.assertEqual(res.discriminacion, 0.0)

    def test_assert_bueno_no_es_tautologia(self):
        res = analizar_tests_python(_BUENO)
        self.assertEqual(res.problemas, [])
        self.assertTrue(res.ok)
        self.assertEqual(res.discriminacion, 1.0)


class TestMocks(BaseTest):
    def test_mock_del_sistema_bajo_prueba(self):
        res = analizar_tests_python(_MOCK_SUJETO)
        tipos = {p.tipo for p in res.problemas}
        self.assertIn("MOCK_SISTEMA_BAJO_PRUEBA", tipos)
        self.assertIn("VALOR_DESDE_MOCK", tipos)
        self.assertFalse(res.ok)

    def test_integracion_mockeada_mal_etiquetada(self):
        res = analizar_tests_python(_INTEGRACION_FALSA)
        tipos = {p.tipo for p in res.problemas}
        self.assertIn("INTEGRACION_MOCKEADA", tipos)
        self.assertIn("VALOR_DESDE_MOCK", tipos)
        t = res.tests[0]
        self.assertEqual(t.nivel_declarado, "integration")
        self.assertEqual(t.nivel_real, "unit")        # mockea subprocess → no es integración real

    def test_mock_externo_legitimo(self):
        # mockear la red en un unit test está bien y NO debe marcarse si no finge ser integración
        fuente = ('import unittest\nfrom clima import temperatura\nfrom unittest.mock import patch\n'
                  'class T(unittest.TestCase):\n'
                  '    def test_temp(self):\n'
                  '        with patch("urllib.request.urlopen"):\n'
                  '            self.assertIsInstance(temperatura("rosario"), float)\n')
        res = analizar_tests_python(fuente)
        self.assertNotIn("INTEGRACION_MOCKEADA", {p.tipo for p in res.problemas})
        self.assertNotIn("MOCK_SISTEMA_BAJO_PRUEBA", {p.tipo for p in res.problemas})


class TestSinAssert(BaseTest):
    def test_sin_assert(self):
        fuente = 'import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        resultado = 1 + 1\n'
        res = analizar_tests_python(fuente)
        self.assertIn("SIN_ASSERT", {p.tipo for p in res.problemas})

    def test_assert_raises_cuenta_como_verificacion(self):
        fuente = ('import unittest\nfrom m import f\nclass T(unittest.TestCase):\n'
                  '    def test_x(self):\n        with self.assertRaises(ValueError):\n            f(-1)\n')
        res = analizar_tests_python(fuente)
        self.assertNotIn("SIN_ASSERT", {p.tipo for p in res.problemas})


class TestMutationProbe(BaseTest):
    def _ws(self, codigo: str, test: str):
        ws = self.proyecto({"calc.py": codigo, "tests/test_calc.py": test})
        def correr() -> bool:
            r = ejecutar_tests(ws, timeout=90, completo=True)
            return bool(r and r.ok)
        return ws, correr

    def test_tests_debiles_dejan_mutantes_vivos(self):
        codigo = "def clasificar(n):\n    if n < 0:\n        return 'neg'\n    if n == 0:\n        return 'cero'\n    return 'pos'\n"
        test = "import unittest\nfrom calc import clasificar\nclass T(unittest.TestCase):\n    def test_pos(self):\n        self.assertEqual(clasificar(5), 'pos')\n"
        ws, correr = self._ws(codigo, test)
        res = probar_discriminacion(ws, "calc.py", correr, maximo=12)
        self.assertEqual(res.error, "")
        self.assertGreater(len(res.sobrevivientes), 0)
        self.assertLess(res.puntaje, 1.0)
        self.assertEqual(ws.leer("calc.py"), codigo)       # restaurado

    def test_tests_fuertes_matan_mutantes(self):
        codigo = "def suma(a, b):\n    return a + b\n"
        test = ("import unittest\nfrom calc import suma\nclass T(unittest.TestCase):\n"
                "    def test_s(self):\n        self.assertEqual(suma(2, 3), 5)\n"
                "    def test_neg(self):\n        self.assertEqual(suma(-1, 1), 0)\n")
        ws, correr = self._ws(codigo, test)
        res = probar_discriminacion(ws, "calc.py", correr, maximo=12)
        self.assertEqual(res.sobrevivientes, [])
        self.assertEqual(res.puntaje, 1.0)

    def test_base_rojo_no_mide(self):
        codigo = "def suma(a, b):\n    return a - b\n"   # roto a propósito
        test = "import unittest\nfrom calc import suma\nclass T(unittest.TestCase):\n    def test_s(self):\n        self.assertEqual(suma(2, 3), 5)\n"
        ws, correr = self._ws(codigo, test)
        res = probar_discriminacion(ws, "calc.py", correr)
        self.assertIn("base", res.error)


class TestHerramientaInspect(BaseTest):
    def test_inspect_tests_reporta(self):
        ws = self.proyecto({"tests/test_x.py": _TAUT})
        salida = self.herramienta(self.contexto(ws), "inspect_tests")
        self.assertIn("TAUTOLOGIA", salida)
        self.assertIn("discriminación", salida)

    def test_inspect_tests_con_path(self):
        ws = self.proyecto({"tests/test_mock.py": _MOCK_SUJETO, "tests/test_ok.py": _BUENO})
        salida = self.herramienta(self.contexto(ws), "inspect_tests", path="tests/test_mock.py")
        self.assertIn("MOCK_SISTEMA_BAJO_PRUEBA", salida)
        self.assertNotIn("test_ok.py", salida)

    def test_inspect_tests_mutacion(self):
        ws = self.proyecto({
            "calc.py": "def clasificar(n):\n    return 'pos' if n > 0 else 'no'\n",
            "tests/test_calc.py": "import unittest\nfrom calc import clasificar\nclass T(unittest.TestCase):\n    def test_p(self):\n        self.assertEqual(clasificar(5), 'pos')\n",
        })
        salida = self.herramienta(self.contexto(ws), "inspect_tests", mutacion="true", target="calc.py")
        self.assertIn("MUTACIÓN", salida)

    def test_rol_tiene_la_herramienta(self):
        for rol in ("principal", "implementador", "qa", "especificador", "revisor", "reparador"):
            self.assertIn("inspect_tests", ROLES[rol].herramientas)


class TestAvisoAlEscribirTests(BaseTest):
    def test_escribir_test_tautologico_avisa(self):
        ws = self.proyecto()
        salida = self.herramienta(self.contexto(ws), "write_to_file", path="tests/test_x.py", content=_MOCK_SUJETO)
        self.assertIn("MOCK_SISTEMA_BAJO_PRUEBA", salida)

    def test_escribir_codigo_normal_no_avisa(self):
        ws = self.proyecto()
        salida = self.herramienta(self.contexto(ws), "write_to_file", path="app.py", content="def f(x):\n    return x * 2\n")
        self.assertNotIn("INTELIGENCIA DE TESTS", salida)
