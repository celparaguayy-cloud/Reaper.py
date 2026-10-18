"""
Revisión adversarial de los arreglos de la ronda con subagentes (capa del modelo, modelos gratis, pipeline, /grande):
bugs de correctitud confirmados con una reproducción, cada uno con su test.
"""

_RV_CALC_ROTO = "def sumar(a, b):\n    return a - b\n"
_RV_CALC_BIEN = "def sumar(a, b):\n    return a + b\n"
_RV_TEST_CALC = ("import unittest\n\nfrom calc import sumar\n\n\nclass T(unittest.TestCase):\n"
                 "    def test_sumar(self):\n        self.assertEqual(sumar(2, 3), 5)\n")


class TestRevisionCierrePorAnuncio(BaseTest):
    """El rescate de "Listo, terminé" sin attempt_completion cerraba al agente aunque el mismo mensaje dijera que algo
    falla o que falta ("quedó hecho, pero los tests fallan: hay que revisar la consulta"): el reparador perdía el
    intento a mitad de trabajo."""

    def test_no_cierra_si_el_mismo_mensaje_dice_que_falla(self):
        for texto in ("El archivo quedó hecho, pero los tests fallan: hay que revisar la consulta.",
                      "He completado la lectura del archivo; el error está en la línea 3.",
                      "Listo el cambio, aunque todavía tengo que corregir el test."):
            self.assertFalse(_anuncia_fin(texto), texto)
        for texto in ("Listo, terminé.", "Implementación completada. Todos los tests pasan."):
            self.assertTrue(_anuncia_fin(texto), texto)

    def test_el_reparador_sigue_trabajando(self):
        ws = self.proyecto({"calc.py": _RV_CALC_ROTO, "tests/test_calc.py": _RV_TEST_CALC})

        def guion(mensajes, kw):
            turno = MockLLM.turnos_asistente(mensajes)
            if turno == 0:
                return herramienta_xml("write_to_file", path="calc.py", content=_RV_CALC_ROTO + "\n")
            if turno == 1:
                return "El archivo quedó hecho, pero los tests fallan: hay que revisar la consulta."
            if turno == 2:
                return herramienta_xml("write_to_file", path="calc.py", content=_RV_CALC_BIEN)
            return terminar_xml("Arreglé sumar: los tests pasan.")
        res = Agente("reparador", MockLLM(guion), ws, self.ajustes(forense=False, escalar=False), self.ui()).ejecutar(
            "Arreglá los fallos")
        self.assertEqual(ws.leer("calc.py"), _RV_CALC_BIEN)              # antes: cerraba en el turno 1, roto
        self.assertGreaterEqual(res.pasos, 3)


class TestRevisionTituloIntentoExtra(BaseTest):
    def test_el_intento_extra_no_se_ve_tres_de_dos(self):
        ws = self.proyecto({"almacen/__init__.py": "", "almacen/db.py": _PRB_DB, "almacen/sales.py": _PRB_SALES,
                            "tests/__init__.py": "", "tests/test_sales.py": _PR3_TEST_ACOPLADO})
        ui = self.ui()
        orq = Orquestador(MockLLM(lambda m, k: terminar_xml("x")), ws, self.ajustes(forense=False), ui)
        orq._protegidos = {"tests/test_sales.py": _PR3_TEST_ACOPLADO}
        informe = InformeBuild("fallida")
        informe.spec_tests = ["tests/test_sales.py"]

        def reparar(pedido, verif, cid, base_fallaba, experto="", contexto=""):
            if "tests/test_sales.py" not in orq._protegidos:
                ws.escribir("tests/test_sales.py", _PR3_TEST_REAL)
            return ResultadoAgente(True, "listo")
        orq.reparar = reparar
        cid = ws.checkpoints.iniciar("tarea")
        final = orq._reparar_con_escalada("ventas", orq.verificar(cid), cid, False, informe, "tarea 1", 2,
                                          lambda: orq.verificar(cid))
        self.assertTrue(final.ok, final.diagnostico[-1000:])
        self.assertIn("REPARACIÓN tarea 1 3/3", ui.texto_registrado())
        self.assertNotIn("3/2", ui.texto_registrado())
