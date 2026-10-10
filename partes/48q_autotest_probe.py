"""Autotests del probe real de los seis agentes (/equipo probar) y el aviso de arranque (AUTO-6-IA §8/§9)."""


class _BaseProbe(BaseTest):
    _VARS = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "REAPER_CLAVE_PROVEEDOR")

    def setUp(self):
        super().setUp()
        self._env_bak = {k: os.environ.pop(k, None) for k in self._VARS}

    def tearDown(self):
        for k, v in self._env_bak.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def cliente(self, eventos, **ajustes):
        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte_falso(eventos))
        c.dormir = lambda _s: None
        return c


class TestProbarEquipo(_BaseProbe):
    def test_todos_responden_con_clave(self):
        os.environ["OPENROUTER_API_KEY"] = "ok"      # default = openrouter para los seis roles
        c = self.cliente(["pong"] * 6)               # dedup por modelo: con 1 modelo basta 1 evento
        res = probar_equipo(c, c.settings)
        self.assertEqual(len(res), 6)
        responden = [r for r in res if r["estado"] == "RESPONDE"]
        self.assertEqual(len(responden), 6)
        self.assertTrue(all("ms" in r["detalle"] for r in responden))

    def test_sin_clave_marca_sin_clave_y_no_llama(self):
        # sin ninguna credencial, el probe NO intenta y marca SIN_CLAVE
        c = self.cliente([])                         # guion vacío: si intentara llamar, reventaría
        res = probar_equipo(c, c.settings)
        self.assertTrue(all(r["estado"] == "SIN_CLAVE" for r in res))
        self.assertEqual(c.uso.llamadas, 0)         # no hizo ninguna petición

    def test_falla_se_reporta(self):
        os.environ["OPENROUTER_API_KEY"] = "ok"
        c = self.cliente([LLMError("404 modelo inexistente", probar_otro_modelo=True)])
        res = probar_equipo(c, c.settings)
        self.assertTrue(any(r["estado"] == "FALLA" for r in res))
        falla = next(r for r in res if r["estado"] == "FALLA")
        self.assertIn("404", falla["detalle"])

    def test_dedup_por_modelo_una_sola_llamada(self):
        os.environ["OPENROUTER_API_KEY"] = "ok"
        c = self.cliente(["pong"])                   # un solo evento: los 6 roles comparten modelo → 1 llamada
        probar_equipo(c, c.settings)
        self.assertEqual(c.uso.llamadas, 1)

    def test_resumen_arranque(self):
        texto = resumen_arranque_equipo(self.ajustes())
        self.assertIn("6 roles", texto)
        self.assertIn("NO VERIFICADA", texto)


class TestProbeCLI(_BaseProbe):
    def test_equipo_probar_cli(self):
        os.environ["OPENROUTER_API_KEY"] = "ok"
        ws = self.proyecto()
        llm = self.cliente(["pong"])
        app = App(self.ajustes(forense=False, escalar=False), llm, self.ui(), ws, persistir=False)
        app.comando("/equipo probar")
        texto = app.ui.texto_registrado()
        self.assertIn("RESPONDEN", texto)
        self.assertIn("/6", texto)

    def test_banner_inicio_muestra_agentes(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.mostrar_inicio(animar=False)
        self.assertIn("6 roles", app.ui.texto_registrado())
