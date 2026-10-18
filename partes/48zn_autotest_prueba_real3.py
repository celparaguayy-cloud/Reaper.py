"""
Tercera prueba REAL de /grande en el teléfono: la etapa 1 quedó verificada; la 2 (ventas) se detuvo.

- La especificación mockeaba la conexión del propio proyecto (patch('almacen.sales.get_connection')) y exigía el SQL
  exacto: el implementador reusó db.get_product (razonable), el mock dejó de aplicar y nadie lo pudo arreglar.
- El reparador escribió 3 veces "Ahora, ejecutemos los tests" sin llamar run_tests y se cerró "sin herramientas".
- Se agotó el tiempo de la tarea en medio de un reintento (Nvidia 500) y el error subió como "el modelo no responde":
  /grande se DETENÍA entero en vez de dar la tarea por fallida y seguir.
"""

_PR3_TEST_ACOPLADO = '''import unittest
from unittest.mock import MagicMock, patch

from almacen.sales import validate_stock


class TestValidateStock(unittest.TestCase):
    def test_stock_suficiente(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"stock": 10}
        with patch("almacen.sales.get_connection", return_value=conn):
            self.assertTrue(validate_stock(1, 5))
        conn.execute.assert_called_with("SELECT stock FROM products WHERE id = ?", (1,))
'''
_PR3_TEST_REAL = '''import unittest

from almacen import db
from almacen.sales import validate_stock


class TestValidateStock(unittest.TestCase):
    def test_stock_suficiente(self):
        con = db.conectar(":memory:")
        db.agregar_producto(con, 1, 10)
        self.assertTrue(validate_stock(con, 1, 5))
        self.assertFalse(validate_stock(con, 1, 11))
'''


class TestTestsAcopladosALaImplementacion(BaseTest):
    def test_detecta_mock_de_la_conexion_y_sql_exacto(self):
        hallazgos = acoples_a_la_implementacion(_PR3_TEST_ACOPLADO)
        self.assertEqual(len(hallazgos), 2, hallazgos)
        self.assertTrue(any("mockea la conexión" in h for h in hallazgos))
        self.assertTrue(any("SQL exacto" in h for h in hallazgos))
        self.assertEqual(acoples_a_la_implementacion(_PR3_TEST_REAL), [])
        self.assertEqual(acoples_a_la_implementacion(
            "from unittest.mock import patch\nwith patch('builtins.input', return_value='s'):\n    pass\n"), [])
        self.assertTrue(any("acoplado a la implementación" in a for a in advertencias_tests_python(_PR3_TEST_ACOPLADO)))

    def test_el_especificador_los_reescribe_una_vez(self):
        ws = self.proyecto({})
        pedidos = []

        def guion(mensajes, kw):
            if MockLLM.rol_de(mensajes) != "especificador":
                return terminar_xml("listo")
            if MockLLM.turnos_asistente(mensajes) == 0:
                primero = MockLLM.ultimo_usuario(mensajes)
                pedidos.append(primero)
                contenido = _PR3_TEST_REAL if "CÓMO está hecho" in primero else _PR3_TEST_ACOPLADO
                return herramienta_xml("write_to_file", path="tests/test_sales.py", content=contenido)
            return terminar_xml("tests escritos")
        ui = self.ui()
        orq = Orquestador(MockLLM(guion), ws, self.ajustes(tests_primero=True), ui)
        plan = Plan("Ventas", [Tarea("1", "validate_stock", ["almacen/sales.py", "tests/test_sales.py"])], [])
        espec = orq.especificar("Ventas del almacén", plan, ws.checkpoints.iniciar("espec"))
        self.assertEqual(len(pedidos), 2)
        self.assertIn("almacen.sales.get_connection", pedidos[1])
        self.assertEqual(espec.get("tests/test_sales.py"), _PR3_TEST_REAL)
        self.assertIn("acoplados a la implementación", ui.texto_registrado())


class TestReparadorQueNoPuedeTerminar(BaseTest):
    def test_si_el_reparador_falla_la_tarea_queda_fallida_y_la_build_sigue(self):
        ws = self.proyecto({})

        def guion(mensajes, kw):
            rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
            if rol == "arquitecto":
                return terminar_xml('<plan><objetivo>Calc</objetivo><criterios>- sumar</criterios>'
                                    '<tarea id="1" archivos="calc.py, tests/test_calc.py">sumar con test</tarea></plan>')
            if rol == "implementador":
                archivos = [("calc.py", "def sumar(a, b):\n    return a - b\n"),
                            ("tests/test_calc.py", "import unittest\nfrom calc import sumar\n\n\n"
                                                   "class T(unittest.TestCase):\n    def test_sumar(self):\n"
                                                   "        self.assertEqual(sumar(2, 3), 5)\n")]
                if turno < len(archivos):
                    return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
                return terminar_xml("listo")
            if rol == "reparador":
                raise LLMError("Error del proveedor durante el streaming: Upstream error from Nvidia: Internal server "
                               "error (no reintento: se agotó el tiempo de la tarea 1)")
            return terminar_xml("listo")
        ui = self.ui()
        informe = Orquestador(MockLLM(guion), ws, self.ajustes(juez=False, max_reparaciones=1), ui).construir(
            "Calculadora con sumar", confirmar=False)                               # antes: LLMError hacia arriba
        self.assertFalse(informe.ok)
        self.assertIn("el reparador no pudo terminar", ui.texto_registrado())
        self.assertTrue(any("el reparador no pudo terminar" in n for n in informe.notas))

    def test_cupo_diario_en_el_reparador_sigue_frenando_todo(self):
        ws = self.proyecto({"calc.py": "def sumar(a, b):\n    return a - b\n",
                            "tests/test_calc.py": "import unittest\nfrom calc import sumar\n\n\n"
                                                  "class T(unittest.TestCase):\n    def test_sumar(self):\n"
                                                  "        self.assertEqual(sumar(2, 3), 5)\n"})
        orq = Orquestador(MockLLM(lambda m, k: terminar_xml("x")), ws, self.ajustes(), self.ui())
        orq.reparar = lambda *a, **k: (_ for _ in ()).throw(_cupo_agotado(6 * 3600))
        verif = orq.verificar(ws.checkpoints.iniciar("x"))
        with self.assertRaises(LLMError) as ctx:
            orq._reparar_con_escalada("p", verif, ws.checkpoints.iniciar("g"), False, InformeBuild("fallida"),
                                      "final", 2, lambda: verif)
        self.assertTrue(ctx.exception.cupo_diario)


class TestAgenteQueAnunciaLosTests(BaseTest):
    def test_si_anuncia_que_corre_los_tests_los_corre_reaper(self):
        ws = self.proyecto({"calc.py": "def sumar(a, b):\n    return a + b\n",
                            "tests/test_calc.py": "import unittest\nfrom calc import sumar\n\n\n"
                                                  "class T(unittest.TestCase):\n    def test_sumar(self):\n"
                                                  "        self.assertEqual(sumar(2, 3), 5)\n"})
        vistos = []

        def guion(mensajes, kw):
            vistos.append(MockLLM.ultimo_usuario(mensajes))
            if MockLLM.turnos_asistente(mensajes) < 2:
                return "VERIFICACIÓN\n\nAhora, ejecutemos los tests para ver si pasan."
            return terminar_xml("Los tests pasan: 1 pasó.")
        res = Agente("reparador", MockLLM(guion), ws, self.ajustes(forense=False, escalar=False), self.ui()).ejecutar(
            "Arreglá los fallos")
        self.assertNotEqual(res.motivo if hasattr(res, "motivo") else "", "sin_herramientas")
        self.assertTrue(any("los corrí yo" in v and "PASARON" in v for v in vistos), vistos[-1][:500])
