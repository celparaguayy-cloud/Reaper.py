"""Autotests de aislamiento de credenciales por proveedor (REAPER AUTO-6-IA §1.1) y /proveedores."""


class _BaseCred(BaseTest):
    _VARS = ("OPENROUTER_API_KEY", "VENICE_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY",
             "GEMINI_API_KEY", "MISTRAL_API_KEY", "COHERE_API_KEY", "GITHUB_MODELS_TOKEN", "REAPER_CLAVE_PROVEEDOR")

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


class TestAislamientoCredenciales(_BaseCred):
    def test_clave_desde_env(self):
        os.environ["GROQ_API_KEY"] = "gk-123"
        self.assertEqual(obtener_clave_api(self.ajustes(proveedor="groq")), "gk-123")

    def test_no_filtra_entre_proveedores_por_env(self):
        # clave de NVIDIA presente; pedir la de Groq NO debe devolver la de NVIDIA
        os.environ["NVIDIA_API_KEY"] = "nv-secreta"
        self.assertIsNone(obtener_clave_api(self.ajustes(proveedor="groq")))
        self.assertIsNone(clave_de_proveedor("groq", self.ajustes(proveedor="openrouter")))

    def test_clave_heredada_no_se_usa_sin_dueno(self):
        # el .clave heredado sin dueño declarado no se usa para NINGÚN proveedor (ni el default)
        (BASE_DIR / ".clave").write_text("secreto-de-openrouter", encoding="utf-8")
        self.assertIsNone(obtener_clave_api(self.ajustes(proveedor="openrouter")))
        self.assertIsNone(obtener_clave_api(self.ajustes(proveedor="groq")))

    def test_clave_heredada_con_dueno_declarado(self):
        (BASE_DIR / ".clave").write_text("k-openrouter", encoding="utf-8")
        (BASE_DIR / ".clave_proveedor").write_text("openrouter", encoding="utf-8")
        self.assertEqual(obtener_clave_api(self.ajustes(proveedor="openrouter")), "k-openrouter")
        self.assertIsNone(obtener_clave_api(self.ajustes(proveedor="groq")))   # dueño no coincide

    def test_dueno_via_variable_entorno(self):
        (BASE_DIR / ".clave").write_text("k-groq", encoding="utf-8")
        os.environ["REAPER_CLAVE_PROVEEDOR"] = "groq"
        self.assertEqual(obtener_clave_api(self.ajustes(proveedor="groq")), "k-groq")
        self.assertIsNone(obtener_clave_api(self.ajustes(proveedor="nvidia")))

    def test_archivo_por_proveedor(self):
        (BASE_DIR / ".clave_groq").write_text("gk-archivo", encoding="utf-8")
        self.assertEqual(obtener_clave_api(self.ajustes(proveedor="groq")), "gk-archivo")
        self.assertIsNone(obtener_clave_api(self.ajustes(proveedor="nvidia")))

    def test_env_tiene_prioridad_sobre_archivo(self):
        (BASE_DIR / ".clave_groq").write_text("gk-archivo", encoding="utf-8")
        os.environ["GROQ_API_KEY"] = "gk-env"
        self.assertEqual(obtener_clave_api(self.ajustes(proveedor="groq")), "gk-env")

    def test_clave_de_proveedor_no_activo_desde_archivo(self):
        (BASE_DIR / ".clave_groq").write_text("gk", encoding="utf-8")
        self.assertEqual(clave_de_proveedor("groq", self.ajustes(proveedor="openrouter")), "gk")
        # pero el .clave heredado NO se usa para un proveedor no activo
        (BASE_DIR / ".clave").write_text("otra", encoding="utf-8")
        self.assertIsNone(clave_de_proveedor("nvidia", self.ajustes(proveedor="openrouter")))

    def test_ollama_sin_clave(self):
        self.assertEqual(obtener_clave_api(self.ajustes(proveedor="ollama")), "sin-clave")


class TestProveedoresCLI(_BaseCred):
    def test_estado_no_revela_secreto(self):
        os.environ["GROQ_API_KEY"] = "supersecreta-no-mostrar"
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/proveedores")
        texto = app.ui.texto_registrado()
        self.assertIn("groq", texto)
        self.assertIn("CONFIGURADO", texto)
        self.assertNotIn("supersecreta-no-mostrar", texto)      # el valor NUNCA aparece

    def test_falta_clave(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/proveedores")
        self.assertIn("FALTA CLAVE", app.ui.texto_registrado())
