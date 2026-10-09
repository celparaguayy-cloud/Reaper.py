"""Autotests de /equipo auto (modelos free) y del reporte de privacidad (REAPER AUTO-6-IA §6/§11)."""


class _BasePriv(BaseTest):
    _VARS = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "GEMINI_API_KEY", "REAPER_CLAVE_PROVEEDOR")

    def setUp(self):
        super().setUp()
        self._env_bak = {k: os.environ.pop(k, None) for k in self._VARS}

    def tearDown(self):
        for k, v in self._env_bak.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()


class TestEquipoFree(_BasePriv):
    def test_sin_credenciales_no_asigna(self):
        asign, motivo = autoasignar_equipo_free(self.ajustes())
        self.assertEqual(asign, {})
        self.assertTrue(motivo)

    def test_con_groq_asigna_modelos_free(self):
        os.environ["GROQ_API_KEY"] = "gk"
        asign, motivo = autoasignar_equipo_free(self.ajustes())
        self.assertEqual(set(asign), {"principal", "arquitecto", "implementador", "revisor", "qa", "reparador"})
        # todos los modelos asignados son free y de un proveedor con credencial (groq)
        for alias in asign.values():
            self.assertTrue(INFO_MODELOS[alias].free)
            self.assertEqual(INFO_MODELOS[alias].proveedor, "groq")

    def test_dos_proveedores_mejora_independencia(self):
        os.environ["GROQ_API_KEY"] = "gk"
        os.environ["GEMINI_API_KEY"] = "gm"
        s = self.ajustes()
        asign, _ = autoasignar_equipo_free(s)
        s.modelos_rol.update(asign)
        ind = independencia_equipo(estado_equipo(s))
        self.assertGreaterEqual(ind["proveedores_distintos"], 2)
        self.assertFalse(ind["reducida"])

    def test_modelos_potentes_free_existen(self):
        libres = modelos_potentes_free()
        self.assertTrue(libres)
        self.assertTrue(all(info.free for _, info in libres))


class TestReportePrivacidad(_BasePriv):
    def cliente(self, eventos, **ajustes):
        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte_falso(eventos))
        c.dormir = lambda _s: None
        return c

    def test_reporte_registra_proveedor_contactado(self):
        c = self.cliente(["hola"])
        c.chat([{"role": "user", "content": "x"}])
        rep = reporte_privacidad(c, c.settings)
        self.assertTrue(rep["proveedores_contactados"])        # contactó al menos un proveedor
        self.assertTrue(rep["redaccion_secretos"])
        self.assertFalse(rep["privacidad_estricta"])

    def test_reporte_sin_actividad(self):
        c = self.cliente([])
        rep = reporte_privacidad(c, c.settings)
        self.assertEqual(rep["proveedores_contactados"], {})
        self.assertIn("ninguno", texto_reporte_privacidad(rep))

    def test_texto_no_revela_secretos(self):
        rep = reporte_privacidad(self.cliente([]), self.ajustes())
        texto = texto_reporte_privacidad(rep)
        self.assertIn("confidencialidad absoluta", texto)
        self.assertIn("ACTIVA", texto)


class TestPrivacidadCLI(_BasePriv):
    def _app(self):
        return App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), self.proyecto(), persistir=False)

    def test_comando_reporte(self):
        app = self._app()
        app.comando("/privacidad")
        self.assertIn("Reporte de privacidad", app.ui.texto_registrado())

    def test_comando_estricto(self):
        app = self._app()
        app.comando("/privacidad estricto on")
        self.assertTrue(app.settings.privacidad_estricta)
        app.comando("/privacy estricto off")
        self.assertFalse(app.settings.privacidad_estricta)

    def test_equipo_auto_sin_claves_avisa(self):
        app = self._app()
        app.comando("/equipo auto")
        self.assertIn("No pude autoconfigurar", app.ui.texto_registrado())
