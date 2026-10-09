"""Autotests del MODO SEGURIDAD (pentest/CTF/lab) con gate de alcance (v9)."""


class TestBloqueSeguridad(BaseTest):
    def test_apagado_por_defecto(self):
        self.assertEqual(bloque_seguridad(self.ajustes()), "")

    def test_sin_alcance_no_activa_gate(self):
        # el modo prendido pero sin alcance declarado NO habilita nada (es el gate)
        self.assertEqual(bloque_seguridad(self.ajustes(modo_seguridad=True)), "")

    def test_con_alcance_habilita(self):
        b = bloque_seguridad(self.ajustes(modo_seguridad=True, alcance_autorizado="lab propio 10.0.0.0/24"))
        self.assertIn("MODO SEGURIDAD", b)
        self.assertIn("10.0.0.0/24", b)
        self.assertIn("SOLO", b)                 # debe recordar que es solo dentro del alcance

    def test_bloqueos_del_dispositivo_siguen_activos(self):
        # el modo seguridad NO toca los bloqueos que protegen el equipo
        for comando in ("sudo rm -rf /", "rm -rf ~", "shutdown now", "cat .env", "dd if=/dev/zero of=/dev/sda"):
            self.assertIsNotNone(comando_bloqueado(comando), f"{comando} debería seguir bloqueado")


class TestModoSeguridadEnAgente(BaseTest):
    def test_prompt_incluye_el_bloque_cuando_esta_activo(self):
        ws = self.proyecto()
        ag = Agente("principal", MockLLM(lambda *_: terminar_xml("Es 4.")), ws,
                    self.ajustes(forense=False, escalar=False, modo_seguridad=True,
                                 alcance_autorizado="CTF HackTheBox"),
                    self.ui(), memoria=None, mostrar_progreso=False)
        ag.ejecutar("cuánto es 2+2")
        sistema = ag.mensajes[0]["content"]
        self.assertIn("MODO SEGURIDAD", sistema)
        self.assertIn("HackTheBox", sistema)

    def test_prompt_sin_modo_no_incluye_el_bloque(self):
        ws = self.proyecto()
        ag = Agente("principal", MockLLM(lambda *_: terminar_xml("Es 4.")), ws,
                    self.ajustes(forense=False, escalar=False), self.ui(), memoria=None, mostrar_progreso=False)
        ag.ejecutar("cuánto es 2+2")
        self.assertNotIn("MODO SEGURIDAD", ag.mensajes[0]["content"])


class TestPentestCLI(BaseTest):
    def _app(self):
        ws = self.proyecto()
        return App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)

    def test_gate_activar_requiere_alcance(self):
        app = self._app()
        app.comando("/pentest")                    # sin alcance: no activa
        self.assertFalse(app.settings.modo_seguridad)

    def test_activar_con_alcance(self):
        app = self._app()
        app.comando("/pentest lab propio 10.0.0.0/24")
        self.assertTrue(app.settings.modo_seguridad)
        self.assertEqual(app.settings.alcance_autorizado, "lab propio 10.0.0.0/24")

    def test_apagar(self):
        app = self._app()
        app.comando("/pentest CTF HTB")
        app.comando("/pentest off")
        self.assertFalse(app.settings.modo_seguridad)
