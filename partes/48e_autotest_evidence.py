"""Autotests del Evidence Core (Fase 2 / v9): EvidenceGate, niveles de verificación y cierre del agente."""

_TAUT_EV = ('import unittest\nfrom suma import suma\nclass T(unittest.TestCase):\n'
         '    def test_a(self):\n        self.assertTrue(True)\n'
         '    def test_b(self):\n        suma(2, 3)\n        self.assertEqual(1, 1)\n')
_BUENO_EV = ('import unittest\nfrom suma import suma\nclass T(unittest.TestCase):\n'
          '    def test_a(self):\n        self.assertEqual(suma(2, 3), 5)\n'
          '    def test_b(self):\n        self.assertEqual(suma(-1, 1), 0)\n')


class TestEvidenceGate(BaseTest):
    def _receipt(self, source, ok=True, exit_code=0, revision="", discr=1.0):
        return ToolReceipt(source=source, ok=ok, exit_code=exit_code, revision=revision, discriminacion=discr)

    def test_sin_evidencia_unverified(self):
        c = Claim("Listo, los tests pasan y todo funciona.")
        EvidenceGate().evaluar(c)
        self.assertEqual(c.status, "UNVERIFIED")
        self.assertIn("evidencia", c.motivo.lower())

    def test_tests_pasan_contradicho_si_fallo(self):
        c = Claim("Todos los tests pasan.", evidence=[self._receipt("run_tests", ok=False)])
        EvidenceGate().evaluar(c)
        self.assertEqual(c.status, "CONTRADICTED")

    def test_scope_excede_evidencia(self):
        c = Claim("Los tests pasan: no hay ningún bug y funciona perfectamente.",
                  evidence=[self._receipt("run_tests", ok=True), self._receipt("execute_command", ok=True)])
        EvidenceGate().evaluar(c)
        self.assertEqual(c.status, "PARTIALLY_SUPPORTED")
        self.assertIn("CLAIM_SCOPE_EXCEEDS_EVIDENCE", c.motivo)

    def test_behavior_verified(self):
        c = Claim("Corrí los tests y el programa: dan el resultado esperado.",
                  evidence=[self._receipt("run_tests", ok=True), self._receipt("execute_command", ok=True)])
        EvidenceGate().evaluar(c)
        self.assertEqual((c.status, c.nivel), ("SUPPORTED", "BEHAVIOR_VERIFIED"))

    def test_green_sin_discriminacion(self):
        ws = self.proyecto({"suma.py": "def suma(a, b):\n    return a + b\n", "tests/test_suma.py": _TAUT_EV})
        c = Claim("Los tests pasan, el comportamiento es correcto.", evidence=[self._receipt("run_tests", ok=True)])
        EvidenceGate(ws).evaluar(c)
        self.assertEqual(c.nivel, "TEST_SUITE_GREEN")
        self.assertIn("NO BEHAVIOR_VERIFIED", c.motivo)

    def test_green_discriminante_ok(self):
        ws = self.proyecto({"suma.py": "def suma(a, b):\n    return a + b\n", "tests/test_suma.py": _BUENO_EV})
        c = Claim("Los tests pasan.", evidence=[self._receipt("run_tests", ok=True)])
        EvidenceGate(ws).evaluar(c)
        self.assertEqual((c.status, c.nivel), ("SUPPORTED", "TEST_SUITE_GREEN"))
        self.assertEqual(c.motivo, "")

    def test_stale_evidence(self):
        ws = self.proyecto({"a.py": "X = 1\n"})
        viejo = ws.huella()
        c = Claim("Los tests pasan.", evidence=[self._receipt("run_tests", ok=True, revision=viejo)])
        ws.escribir("a.py", "X = 2\n")     # el código cambió después de la evidencia
        EvidenceGate(ws).evaluar(c)
        self.assertEqual(c.status, "STALE")
        self.assertIn("STALE_EVIDENCE", c.motivo)

    def test_discriminacion_de_tests(self):
        ws = self.proyecto({"suma.py": "def suma(a, b):\n    return a + b\n", "tests/test_suma.py": _TAUT_EV})
        discr, problemas = discriminacion_de_tests(ws)
        self.assertLess(discr, 0.7)
        self.assertTrue(problemas)


class TestEvidenceGateEnAgente(BaseTest):
    def _obs(self, llm):
        return [MockLLM.ultimo_usuario(c["mensajes"]) for c in llm.llamadas]

    def test_rechaza_afirmacion_que_excede_evidencia(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("execute_command", command='python3 -c "print(2+2)"'),
            terminar_xml("2+2 da 4. No hay ningún bug y el programa funciona perfectamente."),
            terminar_xml("Ejecuté 2+2 con python y devuelve 4."),
        ])
        res = Agente("principal", llm, ws, self.ajustes(forense=True, escalar=False), self.ui(),
                     memoria=None, mostrar_progreso=False).ejecutar("cuánto es 2+2 con python")
        obs = self._obs(llm)
        self.assertTrue(any("EVIDENCE GATE" in o and "CLAIM_SCOPE" in o for o in obs))
        self.assertTrue(res.ok)
        self.assertIn("4", res.resumen)

    def test_green_sin_discriminacion_se_marca_al_cerrar(self):
        ws = self.proyecto({"suma.py": "def suma(a, b):\n    return a + b\n", "tests/test_suma.py": _TAUT_EV})
        llm = MockLLM([
            herramienta_xml("run_tests"),
            terminar_xml("Los tests pasan y el comportamiento es correcto."),
            terminar_xml("Corrí los tests: 2 pasan. No verifican casos borde (tautológicos)."),
        ])
        res = Agente("principal", llm, ws, self.ajustes(forense=True, escalar=False), self.ui(),
                     memoria=None, mostrar_progreso=False).ejecutar("revisá suma.py")
        obs = self._obs(llm)
        self.assertTrue(any("EVIDENCE GATE" in o for o in obs))
        self.assertTrue(res.ok)

    def test_informe_honesto_no_se_rechaza(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("execute_command", command='python3 -c "print(2+2)"'),
            terminar_xml("Ejecuté 2+2 con python: devuelve 4."),
        ])
        res = Agente("principal", llm, ws, self.ajustes(forense=True, escalar=False), self.ui(),
                     memoria=None, mostrar_progreso=False).ejecutar("cuánto es 2+2 con python")
        self.assertEqual(res.pasos, 2)
        self.assertNotIn("EVIDENCE GATE", res.resumen)


class TestClaimsCLI(BaseTest):
    def test_comando_claims(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("execute_command", command='python3 -c "print(2+2)"'),
            terminar_xml("Ejecuté 2+2: da 4."),
        ])
        app = App(self.ajustes(forense=True, escalar=False), llm, self.ui(), ws, persistir=False)
        app.turno("cuánto es 2+2 con python")
        app.comando("/claims")
        texto = app.ui.texto_registrado()
        self.assertIn("nivel", texto.lower())
        self.assertIn("BEHAVIOR_VERIFIED", texto)
