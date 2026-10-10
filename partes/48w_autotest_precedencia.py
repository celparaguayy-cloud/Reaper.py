"""
Autotests de precedencia y persistencia de la configuración:
  defaults < config global < .reaper/config.json del proyecto < entorno < flags CLI,
y los valores efímeros ("solo esta ejecución", proyecto, entorno) NO se filtran a la config global al guardar.
"""


class _BaseEnvModelo(BaseTest):
    _VARS = ("MODEL_NAME", "REAPER_MODO", "REAPER_PROVEEDOR")

    def setUp(self):
        super().setUp()
        self._env_bak = {k: os.environ.pop(k, None) for k in self._VARS}

    def tearDown(self):
        for k, v in self._env_bak.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()


class TestPrecedenciaConfig(_BaseEnvModelo):
    def _ws(self, settings_proyecto: dict):
        return self.proyecto({".reaper/config.json": json.dumps({"settings": settings_proyecto})})

    def test_cli_gana_sobre_proyecto(self):
        ws = self._ws({"torneo": True, "modelo": "qwen"})
        args = construir_parser().parse_args(["--sin-torneo", "--modelo", "deepseek"])
        s = preparar_settings_proyecto(aplicar_flags_cli(Settings(), args), ws, args)
        self.assertFalse(s.torneo)                              # --sin-torneo no lo pisa el proyecto
        self.assertEqual(s.modelo, resolver_modelo("deepseek"))  # --modelo tampoco

    def test_proyecto_gana_sobre_global(self):
        ws = self._ws({"candidatos": 2})
        args = construir_parser().parse_args([])
        s = preparar_settings_proyecto(Settings(candidatos=5), ws, args)
        self.assertEqual(s.candidatos, 2)

    def test_entorno_gana_sobre_proyecto(self):
        os.environ["MODEL_NAME"] = "deepseek"
        ws = self._ws({"modelo": "qwen"})
        s = preparar_settings_proyecto(Settings(), ws, construir_parser().parse_args([]))
        self.assertEqual(s.modelo, resolver_modelo("deepseek"))

    def test_sin_seccion_settings_no_toca(self):
        ws = self.proyecto({".reaper/config.json": '{"hooks": {}}'})
        base = Settings(candidatos=4)
        self.assertIs(preparar_settings_proyecto(base, ws, construir_parser().parse_args([])), base)


class TestPersistenciaSoloCambios(_BaseEnvModelo):
    def test_efimeros_no_se_filtran_a_la_config_global(self):
        guardar_settings(Settings(torneo=True, candidatos=3))           # config global en disco
        efimero = cargar_settings()
        efimero.torneo = False                                         # p. ej. --sin-torneo (solo esta ejecución)
        base = efimero.to_dict()
        efimero.modelo = resolver_modelo("qwen")                       # cambio real del usuario en la sesión
        guardar_cambios_sesion(efimero, base)
        en_disco = cargar_settings()
        self.assertTrue(en_disco.torneo)                               # el flag efímero NO quedó permanente
        self.assertEqual(en_disco.modelo, resolver_modelo("qwen"))     # el cambio del usuario sí
        self.assertEqual(en_disco.candidatos, 3)

    def test_app_guarda_solo_lo_que_cambia_el_comando(self):
        guardar_settings(Settings(torneo=True))
        s = cargar_settings()
        s.torneo = False                                               # efímero de esta ejecución
        app = App(s, MockLLM([]), self.ui(), self.proyecto(), persistir=False)
        app.comando("/modelo qwen")
        en_disco = cargar_settings()
        self.assertTrue(en_disco.torneo)
        self.assertEqual(en_disco.modelo, resolver_modelo("qwen"))

    def test_guardados_sucesivos_acumulan(self):
        app = App(cargar_settings(), MockLLM([]), self.ui(), self.proyecto(), persistir=False)
        app.comando("/modelo qwen")
        app.comando("/modelo revisor deepseek")
        en_disco = cargar_settings()
        self.assertEqual(en_disco.modelo, resolver_modelo("qwen"))
        self.assertEqual(en_disco.modelos_rol.get("revisor"), resolver_modelo("deepseek"))
