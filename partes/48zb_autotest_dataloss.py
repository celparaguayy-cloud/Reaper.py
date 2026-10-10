"""
Autotests anti-pérdida de datos (hallazgos de la caza de bugs): mover no corrompe binarios, un stream
truncado no se acepta como completo, el torneo no pisa archivos grandes que quedaron fuera de la copia, y el
modo forense no borra archivos que ya existían.
"""

_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 3 + b"\x00\xff\x80"


class TestMoverNoCorrompe(BaseTest):
    def test_mover_binario_conserva_bytes_y_modo(self):
        ws = self.proyecto({})
        (ws.raiz / "logo.png").write_bytes(_PNG)
        os.chmod(ws.raiz / "logo.png", 0o750)
        ws.mover("logo.png", "img/logo.png")
        self.assertFalse((ws.raiz / "logo.png").exists())
        self.assertEqual((ws.raiz / "img" / "logo.png").read_bytes(), _PNG)   # bytes idénticos
        self.assertEqual((ws.raiz / "img" / "logo.png").stat().st_mode & 0o777, 0o750)  # modo preservado

    def test_mover_csv_no_utf8_intacto(self):
        ws = self.proyecto({})
        crudo = "nombre;ciudad\r\nJosé;Córdoba\r\n".encode("latin-1")
        (ws.raiz / "d.csv").write_bytes(crudo)
        ws.mover("d.csv", "data/d.csv")
        self.assertEqual((ws.raiz / "data" / "d.csv").read_bytes(), crudo)

    def test_archivo_nuevo_no_queda_0600(self):
        ws = self.proyecto({})
        ws.escribir("nuevo.py", "x = 1\n")
        u = os.umask(0); os.umask(u)
        self.assertEqual((ws.raiz / "nuevo.py").stat().st_mode & 0o777, 0o666 & ~u)


class TestStreamTruncado(BaseTest):
    def _transporte(self, lineas):
        def t(url, headers, payload, timeout):
            yield from lineas
        return t

    def test_stream_sin_done_ni_finish_no_se_acepta(self):
        # content pero el stream termina sin [DONE] ni finish_reason → truncado, no se acepta
        lineas = ['data: {"choices":[{"delta":{"content":"def suma(a, b):\\n    return a +"}}]}']
        c = LLMClient("k", self.ajustes(reintentos=0), url="http://x", transporte=self._transporte(lineas))
        c.dormir = lambda _s: None
        with self.assertRaises(LLMError) as cm:
            c.chat([{"role": "user", "content": "x"}], sin_respaldo=True)
        self.assertIn("truncad", str(cm.exception).lower())

    def test_stream_con_finish_se_acepta(self):
        lineas = ['data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}']
        c = LLMClient("k", self.ajustes(reintentos=0), url="http://x", transporte=self._transporte(lineas))
        c.dormir = lambda _s: None
        self.assertEqual(c.chat([{"role": "user", "content": "x"}], sin_respaldo=True).texto, "ok")

    def test_stream_con_done_se_acepta(self):
        lineas = ['data: {"choices":[{"delta":{"content":"ok"}}]}', "data: [DONE]"]
        c = LLMClient("k", self.ajustes(reintentos=0), url="http://x", transporte=self._transporte(lineas))
        c.dormir = lambda _s: None
        self.assertEqual(c.chat([{"role": "user", "content": "x"}], sin_respaldo=True).texto, "ok")


class TestTorneoNoPisaGrandes(BaseTest):
    def test_aplicar_no_pisa_archivo_existente_fuera_de_la_copia(self):
        ws = self.proyecto({"datos.csv": "valor_real_del_usuario_muy_largo\n" * 3})
        copia = Copia(ws, "test")
        # el candidato "creó" datos.csv (lo vio como nuevo porque quedó fuera de la copia por tamaño)
        cambios = [CambioArchivo("datos.csv", "nuevo", None, "13 bytes\n"),
                   CambioArchivo("lector.py", "nuevo", None, "def contar(): return 0\n")]
        aplicados = copia.aplicar_a(ws, cambios)
        self.assertIn("lector.py", aplicados)                 # lo genuinamente nuevo sí se aplica
        self.assertNotIn("datos.csv", aplicados)              # el que ya existía NO se pisa
        self.assertIn("datos.csv", copia.conflictos)
        self.assertTrue(ws.leer("datos.csv").startswith("valor_real_del_usuario"))

    def test_modificado_existente_si_se_aplica(self):
        ws = self.proyecto({"a.py": "viejo\n"})
        copia = Copia(ws, "test")
        aplicados = copia.aplicar_a(ws, [CambioArchivo("a.py", "modificado", "viejo\n", "nuevo\n")])
        self.assertIn("a.py", aplicados)
        self.assertEqual(ws.leer("a.py"), "nuevo\n")


class TestForenseNoBorraExistentes(BaseTest):
    def test_archivo_grande_preexistente_no_se_borra(self):
        ws = self.proyecto({})
        grande = ws.raiz / "datos.bin"
        grande.write_bytes(b"x" * 5000)                       # > max_bytes del test (abajo)
        with FotoProyecto(ws, max_bytes=100):                 # no captura datos.bin (5000 > 100)
            pass
        self.assertTrue(grande.exists(), "un archivo que ya existía no se borra aunque no se pudiera fotografiar")

    def test_archivo_nuevo_se_borra_pero_es_recuperable(self):
        ws = self.proyecto({"base.py": "x = 1\n"})
        with FotoProyecto(ws, max_bytes=2_000_000):
            (ws.raiz / "generado_por_test.txt").write_text("basura\n", encoding="utf-8")
        self.assertFalse((ws.raiz / "generado_por_test.txt").exists())   # la basura del test se limpia
        self.assertTrue(ws.checkpoints.inicio_grupo() is not None)       # ...pero quedó en un checkpoint
