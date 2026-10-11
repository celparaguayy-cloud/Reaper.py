"""Autotests del disyuntor de modelos (Fase 5 / v9): circuit breaker por modelo con recuperación sola."""


class _RelojFalso:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def avanzar(self, segundos):
        self.t += segundos


class TestDisyuntorModelos(BaseTest):
    def test_abre_tras_umbral(self):
        reloj = _RelojFalso()
        d = DisyuntorModelos(umbral=3, enfriamiento=30, reloj=reloj)
        self.assertFalse(d.fallo("m"))
        self.assertFalse(d.fallo("m"))
        self.assertTrue(d.fallo("m"))          # tercer fallo → abre
        self.assertFalse(d.disponible("m"))
        self.assertEqual(d.estado("m"), "abierto")

    def test_recuperacion_medio_y_cierre(self):
        reloj = _RelojFalso()
        d = DisyuntorModelos(umbral=1, enfriamiento=10, reloj=reloj)
        d.fallo("m")
        self.assertEqual(d.estado("m"), "abierto")
        reloj.avanzar(11)
        self.assertTrue(d.disponible("m"))
        self.assertEqual(d.estado("m"), "medio")   # pasó el enfriamiento: un intento permitido
        d.exito("m")
        self.assertEqual(d.estado("m"), "cerrado")

    def test_medio_falla_reabre(self):
        reloj = _RelojFalso()
        d = DisyuntorModelos(umbral=1, enfriamiento=10, reloj=reloj)
        d.fallo("m")
        reloj.avanzar(11)
        self.assertEqual(d.estado("m"), "medio")
        d.fallo("m")                                # el intento de recuperación falla
        self.assertEqual(d.estado("m"), "abierto")

    def test_exito_resetea_contador(self):
        d = DisyuntorModelos(umbral=3)
        d.fallo("m"); d.fallo("m")
        d.exito("m")
        self.assertFalse(d.fallo("m"))              # el contador arrancó de cero otra vez
        self.assertTrue(d.disponible("m"))

    def test_ordenar_pone_abiertos_al_final(self):
        d = DisyuntorModelos(umbral=1)
        d.fallo("a")
        self.assertEqual(d.ordenar(["a", "b", "c"]), ["b", "c", "a"])

    def test_modelos_independientes(self):
        d = DisyuntorModelos(umbral=1)
        d.fallo("a")
        self.assertFalse(d.disponible("a"))
        self.assertTrue(d.disponible("b"))

    def test_resumen(self):
        d = DisyuntorModelos(umbral=1)
        self.assertIn("operativos", d.resumen())
        d.fallo("a")
        self.assertIn("a", d.resumen())


class TestDisyuntorEnCliente(BaseTest):
    def cliente(self, eventos, **ajustes):
        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte_falso(eventos))
        c.dormir = lambda _s: None
        return c

    def test_modelo_caido_se_abre_y_usa_respaldo(self):
        c = self.cliente([LLMError("503 proveedor caído", probar_otro_modelo=True), "ok",
                          LLMError("503 proveedor caído", probar_otro_modelo=True), "ok",
                          LLMError("503 proveedor caído", probar_otro_modelo=True), "ok"], fallbacks=["qwen"])
        principal = resolver_modelo(c.settings.modelo)
        for _ in range(3):
            self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual(c.disyuntor.estado(principal), "abierto")
        self.assertEqual(c.uso.respaldos, 3)

    def test_sin_fallos_todo_cerrado(self):
        c = self.cliente(["bien"])
        c.chat([{"role": "user", "content": "x"}])
        self.assertIn("operativos", c.disyuntor.resumen())


class TestEsperaReintentoCancelable(BaseTest):
    """La espera entre reintentos no debe congelar el proceso (en el teléfono un sleep largo se siente colgado)."""

    def _cliente(self, eventos=(), **ajustes):
        return LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte_falso(eventos))

    def test_espera_troceada_en_tramos_de_un_segundo(self):
        c = self._cliente()
        tramos = []
        c.dormir = lambda s: tramos.append(s)
        c._dormir_cancelable(5.0)
        self.assertTrue(tramos)
        self.assertLessEqual(max(tramos), 1.0)              # ningún sleep individual supera ~1 s
        self.assertAlmostEqual(sum(tramos), 5.0, places=6)  # pero se espera el total pedido

    def test_cancelacion_corta_la_espera(self):
        c = self._cliente()
        tramos = []
        c.dormir = lambda s: tramos.append(s)
        chequeos = {"n": 0}

        def cancelado():
            chequeos["n"] += 1
            return chequeos["n"] > 2          # cancela al tercer chequeo

        with self.assertRaises(LLMError):
            c._dormir_cancelable(300.0, cancelado)
        self.assertLessEqual(sum(tramos), 3.0)              # no esperó los 300 s

    def test_retry_after_alto_se_acota_y_trocea(self):
        # un Retry-After de 480 s no debe producir un único sleep gigante: se acota a 120 s y se trocea
        c = self._cliente([_Transitorio("429 saturado", espera=480.0), "ok"], reintentos=1, rpm=0)
        tramos = []
        c.dormir = lambda s: tramos.append(s)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertLessEqual(max(tramos), 1.0)
        self.assertLessEqual(sum(tramos), 121.0)           # acotado a 120 s pese al Retry-After de 480
