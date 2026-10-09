"""Autotests del Tool Forge (REAPER v11, §6/§22): gate de calidad real y catálogo persistente."""


class TestForjaHerramientas(BaseTest):
    def forja(self):
        return ForjaHerramientas(self.proyecto().raiz)

    def test_crear_con_tests_verdes_queda_available(self):
        f = self.forja()
        m, recibo = f.crear(manifiesto_demo(), _FORGE_DEMO_CODIGO, _FORGE_DEMO_TEST)
        self.assertEqual((m.estado, m.verificacion), ("AVAILABLE", "verified"))
        self.assertTrue(m.disponible())
        self.assertEqual(recibo.exit_code, 0)
        self.assertTrue(m.code_hash)
        self.assertEqual(m.tests_resultado, "PASS")

    def test_crear_con_tests_rojos_no_entra_al_catalogo_como_disponible(self):
        f = self.forja()
        m, recibo = f.crear(manifiesto_demo("detector-malo"), _FORGE_DEMO_CODIGO, _FORGE_DEMO_TEST_MALO)
        self.assertNotEqual(recibo.exit_code, 0)
        self.assertFalse(m.disponible())
        self.assertEqual(m.estado, "FAILED")
        self.assertIn("FAIL", m.tests_resultado)

    def test_ejecutar_herramienta_available(self):
        f = self.forja()
        f.crear(manifiesto_demo(), _FORGE_DEMO_CODIGO, _FORGE_DEMO_TEST)
        objetivo = f.catalogo.dir / "entrada.py"
        objetivo.write_text("DEBUG = True\n", encoding="utf-8")
        r = f.ejecutar("detector-debug", [str(objetivo)])
        self.assertEqual(r.exit_code, 0)
        self.assertIn("VULN", r.stdout_preview)

    def test_ejecutar_herramienta_fallida_rechazada(self):
        f = self.forja()
        f.crear(manifiesto_demo("detector-malo"), _FORGE_DEMO_CODIGO, _FORGE_DEMO_TEST_MALO)
        with self.assertRaises(ValueError):
            f.ejecutar("detector-malo")

    def test_ejecutar_desconocida(self):
        with self.assertRaises(ValueError):
            self.forja().ejecutar("no-existe")

    def test_catalogo_persiste(self):
        raiz = self.proyecto().raiz
        ForjaHerramientas(raiz).crear(manifiesto_demo(), _FORGE_DEMO_CODIGO, _FORGE_DEMO_TEST)
        # otra instancia del catálogo ve la herramienta registrada
        m = CatalogoHerramientas(raiz).obtener("detector-debug")
        self.assertIsNotNone(m)
        self.assertTrue(m.disponible())

    def test_por_capacidad(self):
        f = self.forja()
        f.crear(manifiesto_demo(), _FORGE_DEMO_CODIGO, _FORGE_DEMO_TEST)
        caps = f.catalogo.por_capacidad("inspect_source_code")
        self.assertEqual([m.id for m in caps], ["detector-debug"])

    def test_manifiesto_round_trip(self):
        m = manifiesto_demo()
        m2 = ManifiestoHerramienta.desde_dict(m.como_dict())
        self.assertEqual(m2.id, m.id)
        self.assertEqual(m2.capabilities, m.capabilities)


class TestForgeCLI(BaseTest):
    def test_comando_forge_demo(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/forge demo")
        texto = app.ui.texto_registrado()
        self.assertIn("AVAILABLE", texto)
        self.assertIn("VULN", texto)       # la reutilización real corrió sobre el input sembrado

    def test_comando_forge_listar_vacio(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/forge listar")
        self.assertIn("vacío", app.ui.texto_registrado())
