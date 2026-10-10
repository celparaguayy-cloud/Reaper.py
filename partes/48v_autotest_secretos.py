"""
Autotests de los P0 de secretos (REAPER Ω): egreso bajo privacidad estricta (R-001) y bloqueo de lectura de
archivos sensibles en TODAS las herramientas (R-002).
"""


class TestEgresoEstricto(BaseTest):
    """R-001: con privacidad estricta y destino externo, 0 llamadas de red y error claro; local permitido."""

    def _cliente_espia(self, eventos, **ajustes):
        base = transporte_falso(eventos)
        llamadas = []

        def espia(url, headers, payload, timeout):
            llamadas.append(url)
            return base(url, headers, payload, timeout)

        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=espia)
        c.dormir = lambda _s: None
        return c, llamadas

    def test_externo_bloqueado_cero_llamadas(self):
        c, llamadas = self._cliente_espia(["no debería enviarse"], privacidad_estricta=True)  # proveedor openrouter
        with self.assertRaises(LLMError) as cm:
            c.chat([{"role": "user", "content": "código privado"}])
        self.assertEqual(llamadas, [])                         # 0 conexiones al proveedor externo
        self.assertIn("estricta", str(cm.exception).lower())

    def test_chat_simple_tambien_bloqueado(self):
        c, llamadas = self._cliente_espia(["no"], privacidad_estricta=True)
        with self.assertRaises(LLMError):
            c.chat_simple("resumí este archivo privado")       # el mismo punto de egreso cubre chat_simple
        self.assertEqual(llamadas, [])

    def test_local_permitido(self):
        c, llamadas = self._cliente_espia(["hola desde ollama"], proveedor="ollama", privacidad_estricta=True)
        r = c.chat([{"role": "user", "content": "x"}], modelo="llama3", sin_respaldo=True)
        self.assertEqual(r.texto, "hola desde ollama")
        self.assertEqual(len(llamadas), 1)                     # el backend local sí opera

    def test_sin_estricta_sale_normal(self):
        c, llamadas = self._cliente_espia(["respuesta"], privacidad_estricta=False)
        c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(len(llamadas), 1)

    def test_privacy_strict_blocks_private_lan_and_mdns(self):
        for url in ("http://192.168.1.20:11434/v1/chat/completions", "http://10.0.0.5/v1",
                    "http://169.254.10.1/v1", "http://servidor.local:11434/v1"):
            self.assertFalse(DestinoModelo("m", "ollama", url, "").es_local(), url)
        for url in ("http://127.0.0.1:11434/v1", "http://[::1]:11434/v1", "http://localhost:11434/v1"):
            self.assertTrue(DestinoModelo("m", "ollama", url, "").es_local(), url)

    def test_destino_es_local_detecta_loopback(self):
        s = self.ajustes(proveedor="ollama")
        self.assertTrue(destino_modelo("llama3", s).es_local())
        self.assertFalse(destino_modelo("deepseek", self.ajustes(proveedor="openrouter")).es_local())


class TestArchivoSensible(BaseTest):
    """R-002: tabla de sensibilidad acotada (no rechaza inocuos por coincidencia parcial)."""

    def test_sensibles(self):
        for n in (".env", ".env.local", ".env.production", "secrets.json", "secret.json",
                  "credentials.json", "id_rsa", "id_ed25519", "id_ecdsa", "id_ed25519_sk", ".netrc", ".npmrc",
                  "server.key", "private.pem", "store.p12", "app.pfx", ".git-credentials"):
            self.assertTrue(es_archivo_sensible(n), f"debería ser sensible: {n}")

    def test_inocuos(self):
        for n in (".env.example", ".env.sample", ".env.template", "id_rsa.pub", "key.pub",
                  "environment.py", "config.json", "app.py", "README.md", "keyboard.js", "license.txt",
                  "id_generator", "id_usuarios"):
            self.assertFalse(es_archivo_sensible(n), f"NO debería ser sensible: {n}")


class TestLecturaSensible(BaseTest):
    def test_leer_bloquea_y_permite_codigo(self):
        ws = self.proyecto({"secrets.json": '{"token":"abc"}\n', ".env": "SECRET=1\n", "app.py": "x = 1\n"})
        with self.assertRaises(ErrorRuta):
            ws.leer("secrets.json")
        with self.assertRaises(ErrorRuta):
            ws.leer(".env")
        self.assertEqual(ws.leer("app.py"), "x = 1\n")

    def test_leer_permite_ejemplo(self):
        ws = self.proyecto({".env.example": "SECRET=changeme\n"})
        self.assertIn("changeme", ws.leer(".env.example"))

    def test_leer_forzado_redacta(self):
        ws = self.proyecto({".env": "API_KEY=sk-abcdefghijklmnop12345\n"})
        texto = ws.leer(".env", permitir_sensible=True)          # autorización explícita
        self.assertNotIn("sk-abcdefghijklmnop12345", texto)      # ...y aun así, redactado
        self.assertIn("REDACTADO", texto)

    def test_escribir_bloquea_variantes(self):
        ws = self.proyecto({})
        for n in (".env.local", "id_ecdsa", "server.key"):
            with self.assertRaises(ErrorRuta):
                ws.escribir(n, "x")

    def test_archivos_codigo_excluye_sensibles(self):
        ws = self.proyecto({".env": "X=1\n", "a.py": "y = 1\n", "server.key": "-----BEGIN KEY-----\n"})
        archivos = ws.archivos_codigo()
        self.assertIn("a.py", archivos)
        self.assertNotIn(".env", archivos)
        self.assertNotIn("server.key", archivos)


class TestHerramientasSensibles(BaseTest):
    def _ctx(self, archivos):
        return self.contexto(self.proyecto(archivos))

    def test_read_file_bloquea(self):
        ctx = self._ctx({"secrets.json": '{"a":1}\n', "ok.py": "x = 1\n"})
        with self.assertRaises(ErrorHerramienta):
            self.herramienta(ctx, "read_file", path="secrets.json")
        self.assertIn("x = 1", self.herramienta(ctx, "read_file", path="ok.py"))

    def test_search_files_no_filtra_secretos(self):
        ctx = self._ctx({".env": "TOKEN=supersecreto123\n", "a.py": "TOKEN_usado = 1\n"})
        out = self.herramienta(ctx, "search_files", regex="TOKEN")
        self.assertNotIn("supersecreto123", out)                 # el .env no se escanea
        self.assertIn("a.py", out)

    def test_read_symbol_no_expone_sensible(self):
        ws = self.proyecto({"private.key": "def secreto():\n    return 42\n"})
        self.assertEqual(indice_de(ws).de_archivo("private.key"), [])   # ni la estructura
