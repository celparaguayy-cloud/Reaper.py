"""Autotests del Spec Core + Bug Classifier (Fase 3 / v9): requisitos inventados, clasificación y observación."""

# El test exige crear 'denuncia.txt' aunque el usuario solo pidió parsear un CSV (fallo §1.6).
_SPEC_TEST_INVENTA = (
    "import os\n"
    "from app import procesar\n"
    "def test_crea_denuncia():\n"
    "    procesar('datos.csv')\n"
    "    assert os.path.exists('denuncia.txt')\n"
)
# El test crea el archivo él mismo y luego lo lee: NO es un requisito al código.
_SPEC_TEST_CREA = (
    "from pathlib import Path\n"
    "def test_lee_propio():\n"
    "    Path('tmpfile.txt').write_text('hola')\n"
    "    assert Path('tmpfile.txt').exists()\n"
)
# El archivo está en el pedido/criterios: legítimo.
_SPEC_TEST_PEDIDO = (
    "import os\n"
    "def test_genera_salida():\n"
    "    assert os.path.isfile('reporte.json')\n"
)
# Depende de una ruta absoluta del sistema.
_SPEC_TEST_RUTA = (
    "import os\n"
    "def test_lee_etc():\n"
    "    assert os.path.exists('/etc/miapp/config.ini')\n"
)


class TestRequisitoInventado(BaseTest):
    def test_archivo_no_pedido(self):
        reqs = requisito_inventado(_SPEC_TEST_INVENTA, "parseá datos.csv y devolvé una lista de filas")
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].tipo, "ARCHIVO_NO_PEDIDO")
        self.assertEqual(reqs[0].artefacto, "denuncia.txt")
        self.assertEqual(reqs[0].test, "test_crea_denuncia")

    def test_archivo_creado_por_el_test_no_cuenta(self):
        self.assertEqual(requisito_inventado(_SPEC_TEST_CREA, "cualquier cosa"), [])

    def test_archivo_mencionado_en_el_pedido(self):
        self.assertEqual(requisito_inventado(_SPEC_TEST_PEDIDO, "generá un reporte.json con el resumen"), [])

    def test_archivo_mencionado_en_criterios(self):
        self.assertEqual(
            requisito_inventado(_SPEC_TEST_PEDIDO, "hacé el resumen", criterios="debe quedar en reporte.json"), [])

    def test_ruta_absoluta(self):
        reqs = requisito_inventado(_SPEC_TEST_RUTA, "leé /etc/miapp/config.ini")
        self.assertTrue(reqs)
        self.assertEqual(reqs[0].tipo, "RUTA_ABSOLUTA")

    def test_fuente_rota_no_explota(self):
        self.assertEqual(requisito_inventado("def test(:\n  pass", "lo que sea"), [])

    def test_para_prompt(self):
        texto = requisitos_inventados_para_prompt(_SPEC_TEST_INVENTA, "parseá un CSV")
        self.assertIn("REQUISITOS INVENTADOS", texto)
        self.assertIn("denuncia.txt", texto)


class TestClasificarBug(BaseTest):
    def test_dependencia_terceros(self):
        c = clasificar_bug("ModuleNotFoundError: No module named 'requests'")
        self.assertEqual(c.tipo, "DEPENDENCY_BUG")

    def test_modulo_propio_es_path(self):
        c = clasificar_bug("ModuleNotFoundError: No module named 'app'", modulos_proyecto=["app", "utils"])
        self.assertEqual(c.tipo, "PATH_BUG")

    def test_assert_por_defecto_es_implementacion(self):
        c = clasificar_bug("AssertionError: 4 != 5")
        self.assertEqual(c.tipo, "IMPLEMENTATION_BUG")

    def test_assert_con_test_cambiado_es_test_bug(self):
        c = clasificar_bug("AssertionError: 4 != 5", codigo_cambiado=False, test_cambiado=True)
        self.assertEqual(c.tipo, "TEST_BUG")

    def test_typeerror_argumentos_es_input_model(self):
        c = clasificar_bug("TypeError: suma() missing 1 required positional argument: 'b'")
        self.assertEqual(c.tipo, "INPUT_MODEL_BUG")

    def test_red_es_flaky(self):
        c = clasificar_bug("ConnectionRefusedError: [Errno 111] Connection refused")
        self.assertEqual(c.tipo, "FLAKY_TEST")

    def test_fixture_no_encontrado(self):
        c = clasificar_bug("E       fixture 'db_session' not found")
        self.assertEqual(c.tipo, "FIXTURE_BUG")

    def test_not_implemented_es_implementacion(self):
        c = clasificar_bug("NotImplementedError")
        self.assertEqual(c.tipo, "IMPLEMENTATION_BUG")

    def test_requisito_inventado_fuerza_test_bug(self):
        c = clasificar_bug("AssertionError", requisito_inventado_detectado=True)
        self.assertEqual(c.tipo, "TEST_BUG")

    def test_para_prompt_incluye_tipo(self):
        texto = clasificacion_para_prompt("ModuleNotFoundError: No module named 'numpy'")
        self.assertIn("DEPENDENCY_BUG", texto)
        self.assertIn("CLASIFICACIÓN", texto)


class TestObservacionInterpretacion(BaseTest):
    def test_observacion(self):
        self.assertTrue(es_observacion("run_tests exit code 1: AssertionError 4 != 5"))
        self.assertFalse(es_interpretacion("run_tests exit code 1: AssertionError 4 != 5"))

    def test_interpretacion(self):
        self.assertTrue(es_interpretacion("Creo que la causa es un off-by-one en el bucle"))
        self.assertFalse(es_observacion("Creo que la causa es un off-by-one en el bucle"))

    def test_separar(self):
        obs, interp = separar_observacion(
            "run_tests: 1 failed, 3 passed\n"
            "El test test_suma falló con AssertionError: 4 != 5\n"
            "Probablemente el bug está en la función suma\n"
            "Deberíamos revisar el acumulador")
        self.assertTrue(any("passed" in o or "AssertionError" in o for o in obs))
        self.assertTrue(any("bug" in i.lower() or "revisar" in i.lower() for i in interp))

    def test_notas_de_prompt(self):
        self.assertIn("AUTORIDAD", nota_autoridad())
        self.assertIn("requisito", nota_autoridad().lower())
        self.assertIn("OBSERVACIÓN", nota_observacion())


class TestInspectTestsRequisitos(BaseTest):
    def test_inspect_tests_reporta_requisito_inventado(self):
        ws = self.proyecto({"tests/test_app.py": _SPEC_TEST_INVENTA})
        ctx = self.contexto(ws)
        ctx.pedido = "parseá datos.csv y devolvé una lista de filas"
        salida = self.herramienta(ctx, "inspect_tests")
        self.assertIn("REQUISITOS INVENTADOS", salida)
        self.assertIn("denuncia.txt", salida)

    def test_inspect_tests_sin_pedido_no_reporta(self):
        ws = self.proyecto({"tests/test_app.py": _SPEC_TEST_INVENTA})
        ctx = self.contexto(ws)       # pedido vacío
        salida = self.herramienta(ctx, "inspect_tests")
        self.assertNotIn("REQUISITOS INVENTADOS", salida)
