"""Autotests del catálogo vivo offline (REAPER AUTO-6-IA §4): parser tolerante, nulls honestos, TTL."""

_CAT_MD = (
    "# Directorio\n\n"
    "| Proveedor | Modelo | Contexto | Free | URL |\n"
    "|-----------|--------|----------|------|-----|\n"
    "| Groq | llama-3.1-8b | 131072 | yes | https://api.groq.com |\n"
    "| Groq | llama-3.1-8b | 131072 | yes | https://api.groq.com |\n"   # duplicado
    "| NVIDIA | nemotron-4 | | no | ftp://raro |\n"                      # contexto vacío, URL rara
    "| Mistral |\n"                                                      # fila incompleta
    "\nTexto suelto, no tabla.\n"
)


class TestParserCatalogo(BaseTest):
    def test_parsea_filas(self):
        filas = parsear_tablas_markdown(_CAT_MD)
        self.assertTrue(any(f.get("model_id") == "llama-3.1-8b" for f in filas))

    def test_tolera_tabla_rota(self):
        # encabezado sin separador: no es tabla válida, no revienta ni inventa filas
        self.assertEqual(parsear_tablas_markdown("| a | b |\n| 1 | 2 |"), [])

    def test_fila_incompleta_no_rompe(self):
        filas = parsear_tablas_markdown(_CAT_MD)
        mistral = [f for f in filas if f.get("provider", "").lower() == "mistral"]
        self.assertTrue(mistral)                     # fila incompleta se tolera (campos vacíos)

    def test_unicode(self):
        md = "| Proveedor | Modelo |\n|---|---|\n| Münïç | mödël-ü |\n"
        self.assertEqual(parsear_tablas_markdown(md)[0]["model_id"], "mödël-ü")


class TestNormalizacion(BaseTest):
    def test_dedup_y_nulls(self):
        fichas = normalizar_fichas(parsear_tablas_markdown(_CAT_MD))
        groq = [f for f in fichas if f.provider == "groq"]
        self.assertEqual(len(groq), 1)               # duplicado colapsado
        self.assertEqual(groq[0].context_tokens, 131072)

    def test_contexto_vacio_es_null_no_cero(self):
        fichas = normalizar_fichas(parsear_tablas_markdown(_CAT_MD))
        nvidia = next(f for f in fichas if f.provider == "nvidia")
        self.assertIsNone(nvidia.context_tokens)     # NUNCA 0 por defecto
        self.assertIsNone(nvidia.supports_tools)

    def test_free_del_directorio_no_es_verificado(self):
        fichas = normalizar_fichas(parsear_tablas_markdown(_CAT_MD))
        groq = next(f for f in fichas if f.provider == "groq")
        self.assertFalse(groq.free_tier_verified)    # 'yes' en el directorio NO verifica coste cero
        self.assertFalse(groq.gratis_verificado())
        self.assertEqual(groq.status, "unverified")

    def test_url_rara_se_descarta(self):
        fichas = normalizar_fichas(parsear_tablas_markdown(_CAT_MD))
        nvidia = next(f for f in fichas if f.provider == "nvidia")
        self.assertNotIn("ftp://", nvidia.source)    # URL no http(s) no se usa como fuente


class TestCacheCatalogo(BaseTest):
    def test_sincronizar_y_cargar(self):
        cat = CatalogoModelos(self.dir / "cat.json")
        n = cat.sincronizar_desde_markdown(_CAT_MD, source_url="fixture.md")
        self.assertGreaterEqual(n, 2)
        self.assertTrue(cat.vigente())
        self.assertEqual(cat.estado(), "actualizado")
        self.assertEqual(cat.meta()["confidence"], "baja")

    def test_ttl_vencido(self):
        cat = CatalogoModelos(self.dir / "cat.json", ttl_horas=24)
        cat.sincronizar_desde_markdown(_CAT_MD)
        # con un 'ahora' 48h en el futuro, la caché está vencida pero las fichas siguen disponibles
        self.assertFalse(cat.vigente(ahora=datetime.now() + timedelta(hours=48)))
        self.assertTrue(cat.fichas())

    def test_marcar_verificado(self):
        cat = CatalogoModelos(self.dir / "cat.json")
        cat.sincronizar_desde_markdown(_CAT_MD)
        self.assertTrue(cat.marcar_verificado("groq", "llama-3.1-8b", free_tier_verified=True))
        f = next(x for x in cat.fichas() if x.provider == "groq")
        self.assertEqual(f.status, "verified")
        self.assertTrue(f.gratis_verificado())
        self.assertEqual(len(cat.gratis_verificados()), 1)

    def test_vacio(self):
        self.assertIn("vacío", CatalogoModelos(self.dir / "nada.json").estado())


class TestCatalogoCLI(BaseTest):
    def test_sincronizar_y_descubrir(self):
        ws = self.proyecto({"dir.md": _CAT_MD})
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/modelos sincronizar dir.md")
        app.comando("/modelos descubrir")
        texto = app.ui.texto_registrado()
        self.assertIn("llama-3.1-8b", texto)
        self.assertIn("unverified", texto)

    def test_gratis_vacio_honesto(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/modelos gratis")
        self.assertIn("VERIFICADO", app.ui.texto_registrado())
