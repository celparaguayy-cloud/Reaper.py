"""Autotests del registro multi-proveedor (Fase 6 / v9): ruteo de cada modelo a su endpoint/clave."""


class TestDestinoModelo(BaseTest):
    def test_modelo_sin_proveedor_usa_el_activo(self):
        s = self.ajustes(proveedor="openrouter")
        d = destino_modelo("venice", s)       # alias con id de OpenRouter, sin proveedor propio
        self.assertEqual(d.proveedor, "openrouter")
        self.assertEqual(d.url, s.url_api())
        self.assertTrue(d.necesita_clave())

    def test_modelo_rutea_a_ollama(self):
        s = self.ajustes(proveedor="openrouter")
        d = destino_modelo("ollama-qwen", s)
        self.assertEqual(d.proveedor, "ollama")
        self.assertEqual(d.url, PROVEEDORES["ollama"]["url"])
        self.assertFalse(d.necesita_clave())

    def test_modelo_rutea_a_openai(self):
        s = self.ajustes(proveedor="openrouter")
        d = destino_modelo("gpt4o-mini", s)
        self.assertEqual((d.proveedor, d.clave_env), ("openai", "OPENAI_API_KEY"))
        self.assertEqual(d.modelo, "gpt-4o-mini")

    def test_api_url_override_para_proveedor_activo(self):
        s = self.ajustes(proveedor="openai", api_url="http://local/v1/chat")
        self.assertEqual(destino_modelo("gpt4o-mini", s).url, "http://local/v1/chat")

    def test_clave_de_proveedor_ollama_sin_clave(self):
        self.assertEqual(clave_de_proveedor("ollama", self.ajustes()), "sin-clave")

    def test_proveedores_de_cuenta_fallbacks_y_roles(self):
        s = self.ajustes(proveedor="openrouter", modelos_rol={"revisor": "ollama-qwen"}, fallbacks=["gpt4o-mini"])
        provs = proveedores_de(s)
        self.assertIn("openrouter", provs)
        self.assertIn("ollama", provs)
        self.assertIn("openai", provs)


class TestRuteoEnCliente(BaseTest):
    def cliente(self, eventos, **ajustes):
        c = LLMClient("clave-activa", self.ajustes(**ajustes), url="http://activo",
                      transporte=transporte_falso(eventos))
        c.dormir = lambda _s: None
        return c

    def test_headers_del_proveedor_activo(self):
        c = self.cliente([], proveedor="openrouter")
        h = c._headers(c._destino("venice"))
        self.assertEqual(h["Authorization"], "Bearer clave-activa")
        self.assertIn("X-Title", h)

    def test_headers_ollama_sin_authorization(self):
        c = self.cliente([], proveedor="openrouter")
        h = c._headers(c._destino("ollama-qwen"))
        self.assertNotIn("Authorization", h)
        self.assertNotIn("X-Title", h)

    def test_payload_usa_proveedor_del_modelo(self):
        c = self.cliente([], proveedor="openrouter")
        p = c._payload("gpt4o-mini", [{"role": "user", "content": "x"}], 0.2, 100, None, "openai")
        self.assertIn("stream_options", p)
        self.assertNotIn("usage", p)

    def test_modelo_sin_clave_del_proveedor_falla_claro(self):
        self.addCleanup(lambda v=os.environ.get("VENICE_API_KEY"): os.environ.__setitem__("VENICE_API_KEY", v)
                        if v is not None else os.environ.pop("VENICE_API_KEY", None))
        os.environ.pop("VENICE_API_KEY", None)
        c = self.cliente(["no debería llegar"], proveedor="openrouter")
        with self.assertRaises(LLMError) as cm:
            c.chat([{"role": "user", "content": "x"}], modelo="venice-directo", sin_respaldo=True)
        self.assertIn("venice", str(cm.exception).lower())
