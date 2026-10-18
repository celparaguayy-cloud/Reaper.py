"""
Tests de la especificación liberados (rotos o acoplados a la implementación) — huecos que quedaron tras el arreglo:

- Un test liberado se podía "arreglar" vaciándolo (borrar casos, dejar `assertTrue(True)`): la suite quedaba en verde
  y nadie lo frenaba salvo el examen de realidad del final.
- Con 2 intentos por tarea (umbral_escalada=1) la liberación se decidía justo DESPUÉS del último intento: nunca servía.
"""

_LIB_TEST_VACIO = ("import unittest\n\nfrom almacen.sales import validate_stock\n\n\n"
                   "class TestValidateStock(unittest.TestCase):\n    def test_stock_suficiente(self):\n"
                   "        self.assertTrue(True)\n")
_LIB_TEST_DOS = _PR3_TEST_REAL + ("\n    def test_sin_producto(self):\n        con = db.conectar(\":memory:\")\n"
                                  "        self.assertFalse(validate_stock(con, 9, 1))\n")


class TestLiberadosDebilitamiento(BaseTest):
    def test_detecta_casos_borrados_y_asserts_vacios(self):
        self.assertEqual(debilitamiento_de_test(_PR3_TEST_REAL, 1), [])
        self.assertEqual(debilitamiento_de_test(_LIB_TEST_DOS, 2), [])
        self.assertTrue(any("tenía 2 test(s) y ahora tiene 1" in h for h in debilitamiento_de_test(_PR3_TEST_REAL, 2)))
        self.assertTrue(any("sin un assert real" in h for h in debilitamiento_de_test(_LIB_TEST_VACIO, 1)))
        sin_assert = _LIB_TEST_VACIO.replace("self.assertTrue(True)", "validate_stock(None, 1, 1)")
        self.assertTrue(any("test_stock_suficiente" in h for h in debilitamiento_de_test(sin_assert, 1)))

    def test_siempre_verdadero_disfrazado_es_tautologia(self):
        for disfraz in ("self.assertTrue(callable(validate_stock) or True)", "self.assertFalse(not True)",
                        "assert validate_stock or 1", "self.assertTrue(not (x and False))"):
            texto = _LIB_TEST_VACIO.replace("self.assertTrue(True)", disfraz)
            self.assertTrue(debilitamiento_de_test(texto, 1), disfraz)            # antes: contaba como assert real
        for real in ("self.assertTrue(validate_stock(con, 1, 5))", "assert validate_stock(con, 1, 5) or x"):
            texto = _LIB_TEST_VACIO.replace("self.assertTrue(True)", real)
            self.assertEqual(debilitamiento_de_test(texto, 1), [], real)

    def _orq(self):
        ws = self.proyecto({"almacen/__init__.py": "", "almacen/db.py": _PRB_DB, "almacen/sales.py": _PRB_SALES,
                            "tests/__init__.py": "", "tests/test_sales.py": _PR3_TEST_ACOPLADO})
        ui = self.ui()
        orq = Orquestador(MockLLM(lambda m, k: terminar_xml("x")), ws, self.ajustes(forense=False), ui)
        orq._protegidos = {"tests/test_sales.py": _PR3_TEST_ACOPLADO}
        informe = InformeBuild("fallida")
        informe.spec_tests = ["tests/test_sales.py"]
        return ws, ui, orq, informe

    def _reparar(self, orq, ws, informe, max_intentos):
        cid = ws.checkpoints.iniciar("tarea")
        return orq._reparar_con_escalada("ventas", orq.verificar(cid), cid, False, informe, "tarea 1", max_intentos,
                                         lambda: orq.verificar(cid))

    def test_vaciar_el_test_liberado_no_cuenta_como_arreglo(self):
        ws, _ui, orq, informe = self._orq()
        vistos = []

        def reparar(pedido, verif, cid, base_fallaba, experto="", contexto=""):
            vistos.append(verif.diagnostico)
            if "tests/test_sales.py" not in orq._protegidos:          # liberado: primero lo vacía, después lo arregla
                ws.escribir("tests/test_sales.py", _LIB_TEST_VACIO if len(vistos) == 3 else _PR3_TEST_REAL)
            return ResultadoAgente(True, "listo")
        orq.reparar = reparar
        final = self._reparar(orq, ws, informe, 5)
        self.assertTrue(final.ok, final.diagnostico[-1500:])
        self.assertEqual(len(vistos), 4)
        self.assertIn("TEST DEBILITADO (tests/test_sales.py)", vistos[3])   # antes: verde con assertTrue(True)
        self.assertIn("sin un assert real", vistos[3])
        self.assertEqual(ws.leer("tests/test_sales.py"), _PR3_TEST_REAL)

    def test_borrar_el_test_liberado_tampoco(self):
        ws, _ui, orq, informe = self._orq()

        def reparar(pedido, verif, cid, base_fallaba, experto="", contexto=""):
            if "tests/test_sales.py" not in orq._protegidos and ws.existe("tests/test_sales.py"):
                (ws.raiz / "tests/test_sales.py").unlink()
            return ResultadoAgente(True, "listo")
        orq.reparar = reparar
        final = self._reparar(orq, ws, informe, 3)
        self.assertFalse(final.ok)
        self.assertIn("TEST DEBILITADO (tests/test_sales.py): se borró", final.diagnostico)

    def test_con_dos_intentos_la_liberacion_llega_a_tiempo(self):
        ws, ui, orq, informe = self._orq()
        vistos = []

        def reparar(pedido, verif, cid, base_fallaba, experto="", contexto=""):
            vistos.append(set(orq._protegidos))
            if "tests/test_sales.py" not in orq._protegidos:
                ws.escribir("tests/test_sales.py", _PR3_TEST_REAL)
            return ResultadoAgente(True, "listo")
        orq.reparar = reparar
        final = self._reparar(orq, ws, informe, 2)
        self.assertTrue(final.ok, final.diagnostico[-1500:])            # antes: cortaba en rojo tras el 2.º intento
        self.assertEqual(len(vistos), 3)                                # UN intento de más, solo por la liberación
        self.assertIn("La libero", ui.texto_registrado())

    def test_sin_nada_que_liberar_no_hay_intento_de_mas(self):
        ws = self.proyecto({"calc.py": "def sumar(a, b):\n    return a - b\n", "tests/test_calc.py": _PRB_TEST_CALC})
        orq = Orquestador(MockLLM(lambda m, k: terminar_xml("x")), ws, self.ajustes(forense=False), self.ui())
        llamadas = []
        orq.reparar = lambda *a, **k: llamadas.append(1) or ResultadoAgente(True, "no pude")
        cid = ws.checkpoints.iniciar("tarea")
        final = orq._reparar_con_escalada("calc", orq.verificar(cid), cid, False, InformeBuild("fallida"), "tarea 1",
                                          2, lambda: orq.verificar(cid))
        self.assertFalse(final.ok)
        self.assertEqual(len(llamadas), 2)

    def test_marcar_anota_cuantos_tests_tenia(self):
        ws, _ui, orq, informe = self._orq()
        orq._marcar_spec_rotos(["tests/test_sales.py"])
        self.assertEqual(orq._minimo_tests, {"tests/test_sales.py": 1})
        ws.escribir("tests/test_sales.py", _LIB_TEST_VACIO)
        self.assertTrue(orq._tests_debilitados())
