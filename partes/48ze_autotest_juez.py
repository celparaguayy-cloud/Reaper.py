"""
Autotests del 8.º agente: el JUEZ DE ENTREGA. Al cerrar /construir compara lo entregado contra el PEDIDO y
SOLO endurece el estado (verde → parcial); nunca convierte una build roja en verde. Entrada compacta + veredicto
JSON corto = mucho menos consumo que los roles que escriben o razonan.
"""


def _verif_ok() -> Verificacion:
    return Verificacion(True, [], None, "", [], ConteoTests(pasados=3, reconocido=True))


def _plan_web() -> Plan:
    return Plan("una web con login y listado", [], ["hay login", "hay listado de productos"])


class TestJuezDeEntrega(BaseTest):
    def _orq(self, respuesta_juez):
        llm = MockLLM(lambda mensajes, kw: respuesta_juez if kw.get("rol") == "juez" else "{}")
        return Orquestador(llm, self.proyecto(), self.ajustes(), self.ui()), llm

    # ---- parser ----
    def test_parsea_cumple(self):
        j = parsear_juicio('{"cumple": true, "faltantes": [], "confianza": "high"}')
        self.assertTrue(j.cumple and j.valido)

    def test_parsea_no_cumple_con_faltantes(self):
        j = parsear_juicio('{"cumple": false, "faltantes": ["falta el login"], "confianza": "high"}')
        self.assertFalse(j.cumple)
        self.assertEqual(j.faltantes, ["falta el login"])

    def test_fuera_de_contrato_no_es_cumple(self):
        j = parsear_juicio("blah blah, no hay json")
        self.assertFalse(j.valido)
        self.assertFalse(j.cumple)

    def test_confianza_invalida_se_normaliza(self):
        self.assertEqual(parsear_juicio('{"cumple": false, "confianza": "altísima"}').confianza, "low")

    def test_no_puede_subir_una_build_roja(self):
        ev = {"EV-ESTADO": "estado por verificación real: fallida; tareas fallidas: T1"}
        j = parsear_juicio('{"cumple": true, "confianza": "high"}', ev)   # el JSON dice true, la evidencia es roja
        self.assertFalse(j.cumple)

    # ---- gate en el pipeline ----
    def test_juez_baja_verde_a_parcial(self):
        orq, _ = self._orq('{"cumple": false, "faltantes": ["falta el login"], "confianza": "high"}')
        informe = InformeBuild("verificada", plan=_plan_web())
        orq._juicio_de_entrega("hacé una web con login", _plan_web(), _verif_ok(), informe)
        self.assertEqual(informe.estado, "parcial")
        self.assertIsNotNone(informe.juicio)
        self.assertFalse(informe.juicio.cumple)
        self.assertTrue(any("login" in n for n in informe.notas))

    def test_juez_cumple_no_cambia(self):
        orq, _ = self._orq('{"cumple": true, "confianza": "high"}')
        informe = InformeBuild("verificada")
        orq._juicio_de_entrega("pedido", _plan_web(), _verif_ok(), informe)
        self.assertEqual(informe.estado, "verificada")

    def test_confianza_baja_no_castiga(self):
        orq, _ = self._orq('{"cumple": false, "faltantes": ["x"], "confianza": "low"}')
        informe = InformeBuild("validada")
        orq._juicio_de_entrega("pedido", _plan_web(), _verif_ok(), informe)
        self.assertEqual(informe.estado, "validada")        # con baja confianza no baja: queda como aviso

    def test_juez_no_toca_una_build_fallida(self):
        orq, _ = self._orq('{"cumple": true, "confianza": "high"}')
        informe = InformeBuild("fallida")
        orq._juicio_de_entrega("pedido", _plan_web(), Verificacion(False, [], None, "", []), informe)
        self.assertEqual(informe.estado, "fallida")         # solo endurece; nunca sube

    def test_juez_apagado_no_consulta(self):
        orq, llm = self._orq('{"cumple": false, "confianza": "high"}')
        orq.settings.juez = False
        informe = InformeBuild("verificada")
        orq._juicio_de_entrega("pedido", _plan_web(), _verif_ok(), informe)
        self.assertEqual(informe.estado, "verificada")
        self.assertIsNone(informe.juicio)
        self.assertEqual(llm.llamadas, [])                  # apagado = no gasta ni una llamada

    def test_fuera_de_contrato_no_cambia_estado(self):
        orq, _ = self._orq("no soy json")
        informe = InformeBuild("verificada")
        orq._juicio_de_entrega("pedido", _plan_web(), _verif_ok(), informe)
        self.assertEqual(informe.estado, "verificada")
        self.assertTrue(any("fuera de contrato" in n for n in informe.notas))

    def test_juez_consume_pocos_tokens(self):
        orq, llm = self._orq('{"cumple": true, "confianza": "high"}')
        orq._juicio_de_entrega("pedido", _plan_web(), _verif_ok(), InformeBuild("verificada"))
        llamada = next(c for c in llm.llamadas if c.get("rol") == "juez")
        self.assertEqual(llamada["max_tokens"], 400)        # presupuesto chico (los roles que escriben usan miles)


class TestTrabajosChicos(BaseTest):
    """Una página estática no debería disparar 'tests primero' y trabarse: eso rompía trabajos chicos."""
    def test_web_estatica_no_fuerza_tests_primero(self):
        self.assertFalse(_es_testeable(["index.html", "style.css"], []))      # solo assets estáticos
        self.assertFalse(_es_testeable(["index.html"], ["logo.png"]))          # ni con assets no-código

    def test_logica_si_es_testeable(self):
        self.assertTrue(_es_testeable(["calc.py"], []))                        # lógica en el plan
        self.assertTrue(_es_testeable(["index.html"], ["app.py"]))             # ya hay lógica en el proyecto
        self.assertTrue(_es_testeable(["main.js"], []))

    def test_vacio_sin_plan_sigue_testeable(self):
        self.assertTrue(_es_testeable([], []))     # proyecto vacío y plan sin archivos: no bajamos la guardia
