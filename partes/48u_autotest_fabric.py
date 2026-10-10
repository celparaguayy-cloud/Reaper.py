"""Autotests del provider fabric (REAPER V9 §3): manifiestos validados, dedup canónico, contadores honestos."""


def _manifiesto_valido(**extra) -> dict:
    base = {
        "provider_id": "acme",
        "display_name": "ACME",
        "operator_id": "acme",
        "provider_type": "direct",
        "api_style": "openai_chat_compatible",
        "official_domains": ["api.acme.ai"],
        "base_url": "https://api.acme.ai/v1/chat/completions",
        "auth_env_var": "ACME_API_KEY",
        "free_policy": "unknown",
    }
    base.update(extra)
    return base


class TestValidarManifiesto(BaseTest):
    def test_acepta_manifiesto_valido(self):
        ok, problemas = validar_manifiesto(_manifiesto_valido())
        self.assertTrue(ok, problemas)
        self.assertEqual(problemas, [])

    def test_rechaza_sin_provider_id(self):
        ok, problemas = validar_manifiesto(_manifiesto_valido(provider_id=""))
        self.assertFalse(ok)
        self.assertTrue(any("provider_id" in p for p in problemas))

    def test_rechaza_api_style_no_soportado(self):
        ok, problemas = validar_manifiesto(_manifiesto_valido(api_style="telepatia"))
        self.assertFalse(ok)
        self.assertTrue(any("api_style" in p for p in problemas))

    def test_rechaza_sin_dominios(self):
        ok, problemas = validar_manifiesto(_manifiesto_valido(official_domains=[]))
        self.assertFalse(ok)
        self.assertTrue(any("official_domains" in p for p in problemas))

    def test_rechaza_base_no_https(self):
        ok, problemas = validar_manifiesto(_manifiesto_valido(base_url="http://api.acme.ai/v1"))
        self.assertFalse(ok)
        self.assertTrue(any("https" in p for p in problemas))

    def test_rechaza_contenido_ejecutable(self):
        # un manifiesto no es código: si trae JS/python/shell como valor, se rechaza
        ok, problemas = validar_manifiesto(_manifiesto_valido(display_name="<script>alert(1)</script>"))
        self.assertFalse(ok)
        self.assertTrue(any("ejecutable" in p for p in problemas))
        ok2, _ = validar_manifiesto(_manifiesto_valido(free_policy="os.system('rm -rf /')"))
        self.assertFalse(ok2)

    def test_local_exento_de_https_y_dominio(self):
        # ollama corre en loopback: http y host:port son válidos para un proveedor local
        ok, problemas = validar_manifiesto(_manifiesto_valido(
            provider_id="ollama", provider_type="local", api_style="ollama",
            official_domains=["127.0.0.1:11434"], base_url="http://127.0.0.1:11434/v1", auth_env_var=""))
        self.assertTrue(ok, problemas)


class TestCargarEIdentidad(BaseTest):
    def test_cargar_invalido_es_none(self):
        self.assertIsNone(cargar_manifiesto({"provider_id": ""}))

    def test_cargar_normaliza_dominios_a_tupla(self):
        m = cargar_manifiesto(_manifiesto_valido(official_domains=["API.Acme.AI"]))
        self.assertIsInstance(m, ManifiestoProveedor)
        self.assertEqual(m.official_domains, ("api.acme.ai",))

    def test_identidad_canonica_colapsa_mismo_operador(self):
        # dos ENTRADAS distintas (otro provider_id) del mismo operador/estilo/dominio son UN proveedor
        a = cargar_manifiesto(_manifiesto_valido(provider_id="acme-1"))
        b = cargar_manifiesto(_manifiesto_valido(provider_id="acme-2"))
        self.assertEqual(identidad_canonica(a), identidad_canonica(b))

    def test_identidad_difiere_por_dominio(self):
        a = cargar_manifiesto(_manifiesto_valido(operator_id="x", official_domains=["a.ai"]))
        b = cargar_manifiesto(_manifiesto_valido(operator_id="x", official_domains=["b.ai"]))
        self.assertNotEqual(identidad_canonica(a), identidad_canonica(b))


class TestManifiestoDesdeProveedor(BaseTest):
    def test_openrouter_es_gateway(self):
        m = manifiesto_desde_proveedor("openrouter")
        self.assertIsNotNone(m)
        self.assertEqual(m.provider_type, "gateway")
        self.assertTrue(m.es_gateway())
        self.assertEqual(m.official_domains, ("openrouter.ai",))

    def test_gemini_estilo_gemini(self):
        self.assertEqual(manifiesto_desde_proveedor("gemini").api_style, "gemini")

    def test_ollama_es_local(self):
        m = manifiesto_desde_proveedor("ollama")
        self.assertEqual(m.provider_type, "local")

    def test_proveedor_inexistente(self):
        self.assertIsNone(manifiesto_desde_proveedor("no-existe"))


class TestRegistroProveedores(BaseTest):
    def test_dedup_por_identidad(self):
        reg = RegistroProveedores()
        self.assertTrue(reg.agregar(cargar_manifiesto(_manifiesto_valido(provider_id="acme-1"))))
        self.assertFalse(reg.agregar(cargar_manifiesto(_manifiesto_valido(provider_id="acme-2"))))  # mismo operador
        self.assertEqual(len(reg.manifiestos()), 1)

    def test_gateways_se_listan(self):
        reg = RegistroProveedores()
        reg.agregar(manifiesto_desde_proveedor("openrouter"))
        reg.agregar(manifiesto_desde_proveedor("groq"))
        self.assertEqual(len(reg.gateways()), 1)


class TestContadoresProveedores(BaseTest):
    def test_contadores_honestos_de_builtin(self):
        c = contadores_proveedores(self.ajustes())
        self.assertEqual(c["providers_discovered"], len(PROVEEDORES))
        self.assertEqual(c["gateways"], 1)                       # OpenRouter es 1 gateway, no cientos
        self.assertEqual(c["meta_objetivo"], 100)
        self.assertLessEqual(c["providers_with_valid_manifest"], c["providers_discovered"])
        self.assertLessEqual(c["providers_credentials_present"], c["providers_discovered"])

    def test_no_inventa_autenticados_ni_free(self):
        c = contadores_proveedores(self.ajustes())
        self.assertEqual(c["providers_authenticated"], "NO VERIFICADO")
        self.assertEqual(c["providers_chat_operational"], "NO VERIFICADO")
        self.assertEqual(c["providers_free_confirmed"], "NO VERIFICADO")

    def test_credencial_presente_cuenta_solo_con_la_variable_propia(self):
        var = "REAPER_FABRIC_TEST_KEY"
        os.environ.pop(var, None)
        base = contadores_proveedores(self.ajustes())["providers_credentials_present"]
        extra = cargar_manifiesto(_manifiesto_valido(
            provider_id="externo-test", operator_id="externo", official_domains=["ext.example"],
            base_url="https://ext.example/v1", auth_env_var=var))
        sin = contadores_proveedores(self.ajustes(), manifiestos_extra=[extra])
        self.assertEqual(sin["providers_credentials_present"], base)      # sin la variable: no cuenta
        self.assertEqual(sin["providers_discovered"], len(PROVEEDORES) + 1)
        os.environ[var] = "k-de-prueba"
        self.addCleanup(os.environ.pop, var, None)
        con = contadores_proveedores(self.ajustes(), manifiestos_extra=[extra])
        self.assertEqual(con["providers_credentials_present"], base + 1)  # con su propia variable: cuenta


class TestPruebaProveedor(BaseTest):
    """R-005: /proveedores probar prueba de verdad y distingue la causa (no 'falló' a secas)."""

    _VARS = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "VENICE_API_KEY")

    def setUp(self):
        super().setUp()
        self._env_bak = {k: os.environ.pop(k, None) for k in self._VARS}

    def tearDown(self):
        for k, v in self._env_bak.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def _cliente(self, eventos, **ajustes):
        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte_falso(eventos))
        c.dormir = lambda _s: None
        return c

    def test_clasifica_por_causa(self):
        casos = {
            "Falta clave. HTTP 401. invalid api key": "AUTH_INVALIDA",
            "Prohibido. HTTP 403. forbidden": "SIN_PERMISO",
            "No existe. HTTP 404. model_not_found": "MODELO_INEXISTENTE",
            "Lento. HTTP 429. rate limit": "LIMITE",
            "Sin saldo. HTTP 402. payment required": "SIN_SALDO",
            "Caído. HTTP 503. service unavailable": "CAIDO",
            "timed out after 30s": "TIMEOUT",
            "getaddrinfo failed": "RED",
        }
        for msg, esperado in casos.items():
            estado, _ = clasificar_prueba_proveedor(LLMError(msg))
            self.assertEqual(estado, esperado, msg)

    def test_sin_clave_no_llama(self):
        c = self._cliente([])                         # guion vacío: si intentara conectarse, reventaría
        r = probar_proveedor(c, "groq", c.settings)
        self.assertEqual(r["estado"], "SIN_CLAVE")
        self.assertEqual(c.uso.llamadas, 0)

    def test_ok_cuando_responde(self):
        os.environ["OPENROUTER_API_KEY"] = "ok"
        c = self._cliente(["pong"], proveedor="openrouter")
        r = probar_proveedor(c, "openrouter", c.settings)
        self.assertEqual(r["estado"], "OK")
        self.assertTrue(r["modelo"])
        self.assertIn("checked_at", r)

    def test_404_da_modelo_inexistente(self):
        os.environ["OPENROUTER_API_KEY"] = "ok"
        c = self._cliente([LLMError("No existe. HTTP 404. model_not_found", probar_otro_modelo=True)],
                          proveedor="openrouter")
        r = probar_proveedor(c, "openrouter", c.settings)
        self.assertEqual(r["estado"], "MODELO_INEXISTENTE")

    def test_cli_probar_sin_claves_avisa(self):
        app = App(self.ajustes(forense=False, escalar=False), self._cliente([]), self.ui(), self.proyecto(),
                  persistir=False)
        app.comando("/proveedores probar")
        self.assertIn("credencial", app.ui.texto_registrado().lower())


class TestFabricCLI(BaseTest):
    def test_comando_estadisticas(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/proveedores estadisticas")
        texto = app.ui.texto_registrado()
        self.assertIn("descubiertos", texto.lower())
        self.assertIn("gateways", texto.lower())
        self.assertIn("NO VERIFICADO", texto)
