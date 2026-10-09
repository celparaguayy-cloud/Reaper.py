"""Autotests de los roles-juez independientes (Fase 10 / v9): adversarial_critic, spec_judge, evidence_judge."""


class TestRolesJuez(BaseTest):
    def test_roles_existen_y_son_delegables(self):
        for r in ("adversarial_critic", "spec_judge", "evidence_judge"):
            self.assertIn(r, ROLES)
            self.assertIn(r, ROLES_DELEGABLES)
            self.assertTrue(ROLES[r].solo_lectura)
            self.assertIn("attempt_completion", ROLES[r].herramientas)

    def test_jueces_no_pueden_escribir(self):
        # ninguna herramienta de escritura en los roles-juez (verificación independiente, no edición)
        for r in ("adversarial_critic", "spec_judge", "evidence_judge"):
            self.assertFalse(set(ROLES[r].herramientas) & set(ESCRITURA))

    def test_alias(self):
        self.assertEqual(ALIAS_ROLES["critic"], "adversarial_critic")
        self.assertEqual(ALIAS_ROLES["adversarial"], "adversarial_critic")
        self.assertEqual(ALIAS_ROLES["juez"], "spec_judge")
        self.assertEqual(ALIAS_ROLES["evidencia"], "evidence_judge")

    def test_critico_corre_y_da_veredicto(self):
        ws = self.proyecto({"suma.py": "def suma(a, b):\n    return a + b\n"})
        llm = MockLLM([terminar_xml("VEREDICTO: NO PUDE ROMPERLO. Probé vacío, negativos y unicode.")])
        res = Agente("adversarial_critic", llm, ws, self.ajustes(), self.ui(),
                     mostrar_progreso=False).ejecutar("intentá romper suma.py")
        self.assertTrue(res.ok)
        self.assertIn("VEREDICTO", res.resumen)

    def test_spec_judge_corre(self):
        ws = self.proyecto({"app.py": "def f():\n    return 1\n"})
        llm = MockLLM([terminar_xml("VEREDICTO: CUMPLE. El criterio f()==1 se cumple.")])
        res = Agente("spec_judge", llm, ws, self.ajustes(), self.ui(),
                     mostrar_progreso=False).ejecutar("¿cumple el plan?")
        self.assertTrue(res.ok)
        self.assertIn("CUMPLE", res.resumen)

    def test_principal_delega_a_juez(self):
        ws = self.proyecto({"suma.py": "def suma(a, b):\n    return a + b\n"})
        guion = [
            "Pido una crítica.\n<delegate>\n<role>critic</role>\n<task>rompé suma</task>\n</delegate>",
            terminar_xml("VEREDICTO: NO PUDE ROMPERLO."),   # respuesta del subagente adversarial_critic
            "Listo, pedí la crítica independiente y no encontró fallas.",   # cierre del principal (texto)
        ]
        res = Agente("principal", llm := MockLLM(guion), ws, self.ajustes(forense=False, escalar=False,
                     max_profundidad=2), self.ui(), memoria=None, mostrar_progreso=False).ejecutar("revisá suma.py")
        obs = [MockLLM.ultimo_usuario(c["mensajes"]) for c in llm.llamadas]
        self.assertTrue(any('rol="adversarial_critic"' in o or "adversarial_critic" in o for o in obs),
                        "esperaba que el subagente crítico corriera")
        self.assertTrue(res.ok)
