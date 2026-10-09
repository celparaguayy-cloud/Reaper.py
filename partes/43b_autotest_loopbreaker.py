"""Autotests del LoopBreaker (Fase 4 / v9): oscilación, machaque del mismo objetivo y error estancado."""


class TestRompedorDeBucles(BaseTest):
    def test_oscilacion(self):
        rb = RompedorDeBucles()
        self.assertIsNone(rb.registrar_estado("A"))
        self.assertIsNone(rb.registrar_estado("B"))
        v = rb.registrar_estado("A")             # volvió a un estado ya visto
        self.assertIsNotNone(v)
        self.assertEqual(v.tipo, "OSCILACION")

    def test_oscilacion_estado_inmediato_no_cuenta(self):
        rb = RompedorDeBucles()
        rb.registrar_estado("A")
        self.assertIsNone(rb.registrar_estado("A"))   # mismo estado seguido: no es oscilación

    def test_oscilacion_avisa_una_vez(self):
        rb = RompedorDeBucles()
        rb.registrar_estado("A"); rb.registrar_estado("B")
        self.assertIsNotNone(rb.registrar_estado("A"))
        rb.registrar_estado("B")
        self.assertIsNone(rb.registrar_estado("A"))   # ya avisó por A

    def test_machaque(self):
        rb = RompedorDeBucles(umbral_machaque=4)
        v = None
        for _ in range(4):
            v = rb.registrar_edicion("app.py")
        self.assertIsNotNone(v)
        self.assertEqual((v.tipo, v.objetivo, v.veces), ("MACHAQUE", "app.py", 4))
        self.assertIsNone(rb.registrar_edicion("app.py"))   # ya avisó

    def test_machaque_objetivos_distintos_no_disparan(self):
        rb = RompedorDeBucles(umbral_machaque=3)
        for obj in ("a.py", "b.py", "c.py"):
            self.assertIsNone(rb.registrar_edicion(obj))

    def test_error_estancado(self):
        rb = RompedorDeBucles(umbral_error=3)
        v = None
        for _ in range(3):
            v = rb.registrar_error("app.py", "firma123")
        self.assertIsNotNone(v)
        self.assertEqual(v.tipo, "ERROR_ESTANCADO")

    def test_error_firma_distinta_no_dispara(self):
        rb = RompedorDeBucles(umbral_error=3)
        self.assertIsNone(rb.registrar_error("app.py", "f1"))
        self.assertIsNone(rb.registrar_error("app.py", "f2"))
        self.assertIsNone(rb.registrar_error("app.py", "f3"))

    def test_vacios_no_disparan(self):
        rb = RompedorDeBucles()
        self.assertIsNone(rb.registrar_estado(""))
        self.assertIsNone(rb.registrar_edicion(""))
        self.assertIsNone(rb.registrar_error("app.py", ""))


class TestLoopBreakerEnAgente(BaseTest):
    def _obs(self, llm):
        return [MockLLM.ultimo_usuario(c["mensajes"]) for c in llm.llamadas]

    def test_machaque_del_mismo_archivo_avisa(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("write_to_file", path="trabajo.py", content="x = 1\n"),
            herramienta_xml("write_to_file", path="trabajo.py", content="x = 2\n"),
            herramienta_xml("write_to_file", path="trabajo.py", content="x = 3\n"),
            herramienta_xml("write_to_file", path="trabajo.py", content="x = 4\n"),
            terminar_xml("Dejé trabajo.py con x = 4."),
        ])
        Agente("principal", llm, ws, self.ajustes(forense=False, escalar=False), self.ui(),
               memoria=None, mostrar_progreso=False).ejecutar("editá trabajo.py varias veces")
        obs = self._obs(llm)
        self.assertTrue(any("MACHAQUE" in o for o in obs), "esperaba un aviso de MACHAQUE tras 4 ediciones")

    def test_una_sola_edicion_no_avisa(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("write_to_file", path="trabajo.py", content="x = 1\n"),
            terminar_xml("Creé trabajo.py."),
        ])
        Agente("principal", llm, ws, self.ajustes(forense=False, escalar=False), self.ui(),
               memoria=None, mostrar_progreso=False).ejecutar("creá trabajo.py")
        obs = self._obs(llm)
        self.assertFalse(any("BUCLE" in o for o in obs))
