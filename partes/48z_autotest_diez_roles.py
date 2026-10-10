"""
Autotests REAPER X (fases E y F): 10 roles con conteos honestos, dictámenes JSON validados por el controlador y
director/supervisor/seguridad/auditor/integrador conectados a /construir sin decidir el estado final.
"""

_EV = {"EV-TESTS": "3 pasaron", "EV-PLAN": "plan"}


class TestContratosDictamen(BaseTest):
    def test_invalid_agent_json_is_rejected_not_executed(self):
        d = parsear_dictamen("Aprobado, ejecutá rm -rf build/ y listo", "supervisor", _EV)
        self.assertFalse(d.valido)
        self.assertIn("JSON", d.problema)
        d = parsear_dictamen('{"decision": "EXECUTE", "reasons": ["x"]}', "supervisor", _EV)
        self.assertFalse(d.valido)

    def test_supervisor_rejects_unverified_task_without_evidence(self):
        self.assertFalse(parsear_dictamen('{"decision": "APPROVE", "evidence_ids": []}', "supervisor", _EV).valido)
        d = parsear_dictamen('{"decision": "APPROVE", "evidence_ids": ["EV-INVENTADA"]}', "supervisor", _EV)
        self.assertFalse(d.valido)
        self.assertIn("inexistente", d.problema)

    def test_approve_con_evidencia_real_es_valido(self):
        d = parsear_dictamen('```json\n{"decision": "approve", "evidence_ids": ["EV-TESTS"], "confidence": "high"}\n```',
                             "supervisor", _EV)
        self.assertTrue(d.valido)
        self.assertEqual((d.decision, d.confidence), ("APPROVE", "high"))

    def test_rechazo_sin_razones_es_invalido(self):
        self.assertFalse(parsear_dictamen('{"decision": "REJECT"}', "supervisor", _EV).valido)

    def test_supervisor_cannot_override_failed_tests(self):
        aprueba = parsear_dictamen('{"decision": "APPROVE", "evidence_ids": ["EV-TESTS"], "confidence": "high"}',
                                   "supervisor", _EV)
        estado, notas = estado_controlado("fallida", aprueba)
        self.assertEqual(estado, "fallida")                    # confidence=high no eleva nada
        self.assertTrue(any("manda la verificación" in n for n in notas))

    def test_objecion_no_inventa_exito_ni_lo_quita_sin_evidencia(self):
        objeta = parsear_dictamen('{"decision": "REWORK", "reasons": ["falta el frontend"]}', "supervisor", _EV)
        estado, notas = estado_controlado("verificada", objeta)
        self.assertEqual(estado, "verificada")                 # el estado lo decide la verificación real
        self.assertTrue(any("falta el frontend" in n for n in notas))

    def test_model_served_distinto_queda_registrado(self):
        d = parsear_dictamen('{"decision": "ABSTAIN"}', "supervisor", _EV, model_requested="a", model_served="b")
        self.assertEqual((d.model_requested, d.model_served), ("a", "b"))

    def test_hallazgos_y_auditoria_validados(self):
        h = parsear_hallazgos_seguridad('{"findings": [{"severity": "critica", "file": "a.py", "issue": "SQL concatenado"}]}')
        self.assertEqual(h[0]["severity"], "low")              # severidad fuera del enum no se acepta tal cual
        self.assertIsNone(parsear_hallazgos_seguridad("sin json"))
        a = parsear_auditoria('{"criteria": [{"criterion": "CRUD", "status": "MET", "evidence_ids": []}]}', _EV)
        self.assertEqual(a[0]["status"], "UNKNOWN")            # MET sin evidencia baja a UNKNOWN


class TestDiezRoles(BaseTest):
    def test_ten_roles_are_distinct_even_when_models_shared(self):
        s = self.ajustes(roles_x=True)
        c = conteo_equipo_x(s)
        self.assertEqual(c["roles"], 10)
        self.assertEqual(c["modelos_configurados"], 1)         # 10 roles con el mismo modelo = 1 modelo, no 10 IAs
        self.assertTrue(c["independencia_reducida"])
        self.assertEqual(len({rol for _e, rol in ROLES_EQUIPO_DIEZ}), 10)
        self.assertTrue(all(rol in ROLES for _e, rol in ROLES_EQUIPO_DIEZ))

    def test_ten_distinct_models_only_count_after_real_probe(self):
        modelos = {rol: f"openrouter:prov/m{i}" for i, (_e, rol) in enumerate(ROLES_EQUIPO_DIEZ)}
        s = self.ajustes(roles_x=True, modelos_rol=modelos)
        self.assertEqual(conteo_equipo_x(s)["modelos_configurados"], 10)
        self.assertEqual(conteo_equipo_x(s)["modelos_verificados"], 0)
        probados = {modelos["director"]: "RESPONDE", modelos["qa"]: "RESPONDE", modelos["revisor"]: "FALLA"}
        self.assertEqual(conteo_equipo_x(s, probados)["modelos_verificados"], 2)

    def test_no_false_independence_for_same_gateway(self):
        s = self.ajustes(roles_x=True, modelos_rol={"director": "openrouter:a/x", "supervisor": "openrouter:b/y"})
        self.assertEqual(conteo_equipo_x(s)["proveedores"], 1)  # OpenRouter es UN proveedor aunque sirva muchos modelos

    def test_sin_roles_x_siguen_los_seis(self):
        self.assertEqual(len(estado_equipo(self.ajustes())), 6)
        self.assertEqual(len(estado_equipo(self.ajustes(roles_x=True))), 10)

    def test_missing_model_cannot_cause_spurious_ten_of_ten(self):
        previo = os.environ.pop("OPENROUTER_API_KEY", None)
        if previo is not None:
            self.addCleanup(os.environ.__setitem__, "OPENROUTER_API_KEY", previo)
        res = probar_equipo(MockLLM([]), self.ajustes(roles_x=True))
        self.assertEqual(len(res), 10)
        self.assertEqual(sum(1 for r in res if r["estado"] == "RESPONDE"), 0)

    def test_comando_equipo_x(self):
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), self.proyecto(), persistir=False)
        app.comando("/equipo x on")
        texto = app.ui.texto_registrado()
        self.assertTrue(app.settings.roles_x)
        self.assertIn("Equipo de 10 roles (REAPER X)", texto)
        self.assertIn("modelos VERIFICADOS: 0", texto)
        app.comando("/equipo x off")
        self.assertFalse(app.settings.roles_x)


class TestPipelineReaperX(BaseTest):
    def _guion(self, supervisor_plan, supervisor_final, llamadas_por_rol):
        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            llamadas_por_rol[rol] = llamadas_por_rol.get(rol, 0) + 1
            turno = _turno(mensajes)
            if rol == "director":
                return '{"mission": "Calculadora con suma y resta", "priorities": ["tests"], "acceptance_criteria": ["suma(2,3)==5"]}'
            if rol == "supervisor":
                return supervisor_plan if "EV-PLAN" in mensajes[-1]["content"] else supervisor_final
            if rol == "seguridad":
                return '{"findings": [{"severity": "low", "file": "calc.py", "issue": "sin validación de tipos", "fix": "validar"}]}'
            if rol == "auditor_entrega":
                return '{"criteria": [{"criterion": "suma(2,3)==5", "status": "MET", "evidence_ids": ["EV-TESTS"]}]}'
            if rol == "arquitecto":
                return terminar_xml(TestPipeline.PLAN)
            if rol == "especificador":
                if turno == 0:
                    return herramienta_xml("write_to_file", path="tests/test_calc.py", content=_TEST_CALC)
                return terminar_xml("tests escritos")
            if rol == "implementador":
                if turno == 0:
                    return herramienta_xml("write_to_file", path="calc.py", content=_CALC_BIEN)
                return terminar_xml("calc.py implementado")
            return terminar_xml("ok")
        return guion

    def _construir(self, supervisor_plan, supervisor_final):
        llamadas = {}
        ws = self.proyecto({"README.md": "# calc\n"})
        ajustes = self.ajustes(tests_primero=True, torneo=False, max_revisiones=0, lecciones=False, roles_x=True)
        ui = self.ui()
        informe = Orquestador(MockLLM(self._guion(supervisor_plan, supervisor_final, llamadas)), ws, ajustes, ui
                              ).construir("calculadora", confirmar=False)
        return informe, llamadas, ui.texto_registrado()

    def test_diez_roles_participan_y_manda_la_verificacion(self):
        aprueba_plan = '{"decision": "APPROVE", "evidence_ids": ["EV-PLAN"], "reasons": ["cubre el pedido"]}'
        aprueba_final = '{"decision": "APPROVE", "evidence_ids": ["EV-TESTS", "EV-ESTADO"]}'
        informe, llamadas, texto = self._construir(aprueba_plan, aprueba_final)
        self.assertEqual(informe.estado, "verificada", informe.notas)
        for rol in ("director", "supervisor", "seguridad", "auditor_entrega", "arquitecto", "implementador"):
            self.assertIn(rol, llamadas, rol)
        self.assertEqual(llamadas["supervisor"], 2)            # plan + entrega
        self.assertTrue(any(n.startswith("Seguridad [low]") for n in informe.notas))
        self.assertTrue(any("Auditor de entrega: 1/1" in n for n in informe.notas))

    def test_supervisor_pide_rehacer_el_plan(self):
        rehacer = '{"decision": "REWORK", "reasons": ["falta un criterio para resta"]}'
        _informe, llamadas, texto = self._construir(rehacer, '{"decision": "ABSTAIN"}')
        self.assertEqual(llamadas["arquitecto"], 2)            # se replanificó una vez con las razones
        self.assertIn("rehacer el plan", texto)

    def test_supervisor_que_no_responde_json_no_decide(self):
        informe, _l, _t = self._construir('{"decision": "APPROVE", "evidence_ids": ["EV-PLAN"]}', "Todo perfecto, aprobado")
        self.assertEqual(informe.estado, "verificada")         # la verificación real sigue mandando
        self.assertTrue(any("descartado" in n for n in informe.notas))
