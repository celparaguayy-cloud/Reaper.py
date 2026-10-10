"""Autotests del fix de /modelo (Ω §5.1) y de la exclusión/retiro del disyuntor (Ω §5.2)."""


class TestModeloParser(BaseTest):
    def _app(self):
        return App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), self.proyecto(), persistir=False)

    def test_rol_desconocido_no_guarda(self):
        app = self._app()
        antes = app.settings.modelo
        app.comando("/modelo noesunrol venice")          # T01/T03: no debe guardar 'noesunrol' como modelo
        self.assertEqual(app.settings.modelo, antes)
        self.assertNotIn("noesunrol", app.settings.modelos_rol)
        self.assertIn("desconocido", app.ui.texto_registrado().lower())

    def test_demasiados_argumentos_no_guarda(self):
        app = self._app()
        antes = app.settings.modelo
        app.comando("/modelo a b c")
        self.assertEqual(app.settings.modelo, antes)

    def test_rol_valido_se_guarda(self):
        app = self._app()
        app.comando("/modelo revisor qwen")
        self.assertEqual(app.settings.modelos_rol.get("revisor"), resolver_modelo("qwen"))

    def test_modelo_principal_se_guarda(self):
        app = self._app()
        app.comando("/modelo qwen")
        self.assertEqual(app.settings.modelo, resolver_modelo("qwen"))

    def test_cambiar_principal_avisa_de_overrides(self):
        # R-021: /modelo <alias> NO pisa los overrides por rol, pero avisa que siguen mandando
        app = self._app()
        app.comando("/modelo revisor qwen")
        app.comando("/modelo venice")
        self.assertEqual(app.settings.modelos_rol.get("revisor"), resolver_modelo("qwen"))  # no se borró solo
        self.assertIn("override", app.ui.texto_registrado().lower())

    def test_reset_limpia_overrides(self):
        app = self._app()
        app.comando("/modelo revisor qwen")
        app.comando("/modelo reset")
        self.assertEqual(app.settings.modelos_rol, {})


class TestDisyuntorExcluye(BaseTest):
    def test_elegibles_excluye_abierto(self):
        d = DisyuntorModelos(umbral=1)
        d.fallo("a")                                     # abre 'a'
        self.assertEqual(d.elegibles(["a", "b"]), ["b"])

    def test_elegibles_vacio_si_todos_abiertos(self):
        d = DisyuntorModelos(umbral=1)
        d.fallo("a"); d.fallo("b")
        self.assertEqual(d.elegibles(["a", "b"]), [])    # a propósito vacío: el cliente da diagnóstico

    def test_retirar_excluye_y_estado(self):
        d = DisyuntorModelos()
        d.retirar("groq/llama")
        self.assertFalse(d.disponible("groq/llama"))
        self.assertEqual(d.estado("groq/llama"), "retirado")
        self.assertEqual(d.elegibles(["groq/llama", "otro"]), ["otro"])

    def test_exito_revive_retirado(self):
        d = DisyuntorModelos()
        d.retirar("m")
        d.exito("m")
        self.assertTrue(d.disponible("m"))


class TestChatDisyuntor(BaseTest):
    def cliente(self, eventos, **ajustes):
        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte_falso(eventos))
        c.dormir = lambda _s: None
        return c

    def test_404_retira_el_modelo_y_no_reintenta(self):
        c = self.cliente([LLMError("404 model_not_found", probar_otro_modelo=True), "desde respaldo"],
                         fallbacks=["qwen"])
        principal = resolver_modelo(c.settings.modelo)
        self.assertEqual(c.chat([{"role": "user", "content": "hola"}]).texto, "desde respaldo")
        self.assertEqual(c.disyuntor.estado(principal), "retirado")

    def test_todos_en_enfriamiento_da_diagnostico(self):
        # un solo modelo: 3 fallos lo abren; el 4º chat no "prueba igual", da diagnóstico claro
        c = self.cliente([LLMError("503 caído", probar_otro_modelo=True)] * 3)
        for _ in range(3):
            with self.assertRaises(LLMError):
                c.chat([{"role": "user", "content": "x"}])
        with self.assertRaises(LLMError) as cm:
            c.chat([{"role": "user", "content": "x"}])        # no consume guion: elegibles vacío
        self.assertIn("enfriamiento", str(cm.exception).lower())