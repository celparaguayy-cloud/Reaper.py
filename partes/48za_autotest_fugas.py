"""
Autotests anti-fuga (hallazgos de la caza de bugs): la clave de un proveedor nunca va a otro, un repo no
confiable no puede redirigir el endpoint ni aflojar la red, los subprocesos no heredan secretos del usuario,
y la salida de comandos / las sesiones guardadas no conservan secretos.
"""


class _BaseFuga(BaseTest):
    _VARS = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY", "REAPER_CLAVE_PROVEEDOR")

    def setUp(self):
        super().setUp()
        self._env_bak = {k: os.environ.pop(k, None) for k in self._VARS}

    def tearDown(self):
        for k, v in self._env_bak.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()


class TestClaveNoCruzaProveedor(_BaseFuga):
    def _cliente(self, api_key, **ajustes):
        c = LLMClient(api_key, self.ajustes(**ajustes), url="http://falso", transporte=transporte_falso([]))
        c.dormir = lambda _s: None
        return c

    def test_key_provider_a_never_sent_to_provider_b(self):
        # cliente creado para openrouter; si el proveedor activo pasa a groq, la clave de openrouter NO se reusa
        c = self._cliente("CLAVE-OPENROUTER", proveedor="openrouter")
        c.settings = replace(c.settings, proveedor="groq")
        os.environ["GROQ_API_KEY"] = "CLAVE-GROQ"
        d_groq = destino_modelo("groq:openai/gpt-oss-120b", c.settings)
        self.assertEqual(c._clave_de(d_groq), "CLAVE-GROQ")
        d_or = destino_modelo("deepseek", replace(c.settings, proveedor="openrouter"))
        self.assertEqual(c._clave_de(d_or), "CLAVE-OPENROUTER")   # solo su proveedor de origen

    def test_sin_clave_del_destino_no_devuelve_la_de_otro(self):
        c = self._cliente("CLAVE-OPENROUTER", proveedor="openrouter")
        d_groq = destino_modelo("groq:openai/gpt-oss-120b", c.settings)   # sin GROQ_API_KEY
        self.assertNotEqual(c._clave_de(d_groq), "CLAVE-OPENROUTER")
        self.assertIn(c._clave_de(d_groq), (None, ""))

    def test_headers_del_destino_llevan_solo_su_clave(self):
        os.environ["GROQ_API_KEY"] = "CLAVE-GROQ"
        c = self._cliente("CLAVE-OPENROUTER", proveedor="openrouter")
        h = c._headers(destino_modelo("groq:openai/gpt-oss-120b", c.settings))
        self.assertEqual(h.get("Authorization"), "Bearer CLAVE-GROQ")
        self.assertNotIn("CLAVE-OPENROUTER", str(h))


class TestProyectoNoRedirigeEndpoint(_BaseFuga):
    def test_project_config_cannot_replace_provider_endpoint(self):
        local = {"settings": {"api_url": "http://127.0.0.1:9/robar", "proveedor": "groq", "candidatos": 3}}
        s = settings_con_local(Settings(), local)
        self.assertEqual(s.api_url, "")                 # el api_url del repo se ignora
        self.assertEqual(s.proveedor, "openrouter")     # el proveedor no lo cambia el repo
        self.assertEqual(s.candidatos, 3)               # un override seguro sí se aplica
        self.assertEqual(set(overrides_proyecto_ignorados(local)), {"api_url", "proveedor"})

    def test_project_config_cannot_weaken_privacy_or_network(self):
        base = Settings(privacidad_estricta=True, web=False)
        s = settings_con_local(base, {"settings": {"privacidad_estricta": False, "web": True, "plugins": True}})
        self.assertTrue(s.privacidad_estricta)          # el repo no apaga la privacidad estricta del usuario
        self.assertFalse(s.web)


class TestEntornoSinSecretos(_BaseFuga):
    def test_subprocess_env_strips_secrets(self):
        marcas = {"MI_API_KEY": "x", "DB_PASSWORD": "x", "SMTP_PASS": "x", "DB_PWD": "x", "NPM_AUTH": "x",
                  "SENTRY_DSN": "x", "GH_PAT": "x", "CONTRASENA_DB": "x", "SIGNING_KEY": "x", "SESSION_SECRET": "x"}
        for k, v in marcas.items():
            os.environ[k] = v
            self.addCleanup(os.environ.pop, k, None)
        env = entorno_seguro()
        for k in marcas:
            self.assertNotIn(k, env, f"{k} no debería pasar al subproceso")
        self.assertIn("PATH", env)                      # las variables inocuas siguen

    def test_keeps_innocuous_vars(self):
        os.environ["NODE_ENV"] = "test"; self.addCleanup(os.environ.pop, "NODE_ENV", None)
        self.assertEqual(entorno_seguro().get("NODE_ENV"), "test")


class TestRedaccionSecretos(_BaseFuga):
    def test_formatos_de_clave_se_redactan(self):
        claves = ["gsk_0AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIj", "sk-or-v1-0123456789abcdef0123456789",
                  "AIzaSyA0bCdEfGhIjKlMnOpQrStUvWxYz012345", "github_pat_11ABCDE0123456789abcdefgh",
                  "nvapi-0123456789abcdefghijABCDEF"]
        for k in claves:
            self.assertNotIn(k, redactar_secretos("clave: " + k), k[:10])

    def test_asignaciones_y_url(self):
        self.assertIn("[REDACTADO]", redactar_secretos("MISTRAL_API_KEY=abcdefghijklmnop"))
        self.assertIn("[REDACTADO]", redactar_secretos('{"api_key": "abcdefghijklmnop"}'))
        self.assertNotIn("Secreta123", redactar_secretos("DATABASE_URL=postgres://u:Secreta123@h/db"))

    def test_no_redacta_texto_inocuo(self):
        for ok in ("author = 'Shakespeare fue un escritor'", "token_count = 5", "el total de palabras es 1234"):
            self.assertEqual(redactar_secretos(ok), ok)


class TestSalidaComandoRedactada(_BaseFuga):
    def test_execute_command_redacta_la_salida(self):
        ctx = self.contexto(self.proyecto({}), modo="auto")
        salida = self.herramienta(ctx, "execute_command",
                                  command="printf 'GROQ_API_KEY=gsk_0AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGh\\n'")
        self.assertIn("[REDACTADO]", salida)
        self.assertNotIn("gsk_0AbCdEfGhIjKl", salida)

    def test_sesion_guardada_no_conserva_secretos(self):
        ws = self.proyecto({})
        app = App(self.ajustes(modo="auto"), MockLLM([]), self.ui(), ws, persistir=True)
        app.principal.mensajes = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "mirá el archivo"},
            {"role": "assistant",
             "content": "salida: GROQ_API_KEY=gsk_0AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGh"}]
        app._guardar_sesion()
        texto = app._ruta_sesion().read_text(encoding="utf-8")
        self.assertIn("[REDACTADO]", texto)
        self.assertNotIn("gsk_0AbCdEfGhIjKl", texto)
