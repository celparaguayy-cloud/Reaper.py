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


class TestJuezContrato(BaseTest):
    """Motor central, paso 1: el juez convierte el pedido en un CONTRATO de criterios y vigila la cobertura."""
    def _orq(self, respuesta_juez):
        llm = MockLLM(lambda mensajes, kw: respuesta_juez if kw.get("rol") == "juez" else "{}")
        return Orquestador(llm, self.proyecto(), self.ajustes(), self.ui()), llm

    def test_parsea_criterios(self):
        c = parsear_criterios_entrega('{"criterios": ["hay login", "lista productos", "hay login"]}')
        self.assertEqual(c, ["hay login", "lista productos"])        # dedup

    def test_criterios_cap_y_basura(self):
        self.assertEqual(parsear_criterios_entrega("no json"), [])
        muchos = '{"criterios": [' + ",".join(f'"c{i}"' for i in range(20)) + ']}'
        self.assertEqual(len(parsear_criterios_entrega(muchos)), 8)   # acotado

    def test_cobertura_detecta_criterio_sin_tarea(self):
        plan = Plan("web", [Tarea("1", "crear index.html con el listado", ["index.html"])], [])
        self.assertEqual(cobertura_criterios(["mostrar listado"], plan), [])          # 'listado' está en el plan
        self.assertEqual(cobertura_criterios(["enviar emails"], plan), ["enviar emails"])  # nada que ver
        self.assertEqual(cobertura_criterios([], plan), [])

    def test_contrato_desde_el_pedido(self):
        orq, _ = self._orq('{"criterios": ["hay login", "hay listado"]}')
        self.assertEqual(orq._contrato_de_entrega("una web con login y listado"), ["hay login", "hay listado"])

    def test_contrato_apagado_o_basura_no_rompe(self):
        orq, llm = self._orq('{"criterios": ["x"]}')
        orq.settings.juez = False
        self.assertEqual(orq._contrato_de_entrega("algo"), [])        # apagado: ni una llamada
        self.assertEqual(llm.llamadas, [])
        orq2, _ = self._orq("no json")
        self.assertEqual(orq2._contrato_de_entrega("algo"), [])       # basura: lista vacía, sin romper

    def test_gate_usa_el_contrato(self):
        orq, _ = self._orq('{"cumple": false, "faltantes": ["falta el login"], "confianza": "high"}')
        informe = InformeBuild("verificada")
        informe.criterios_entrega = ["hay login", "hay listado"]      # contrato ya fijado
        orq._juicio_de_entrega("una web con login", _plan_web(), _verif_ok(), informe)
        self.assertEqual(informe.estado, "parcial")                  # juzgó contra el contrato y endureció


class TestJuezCierra(BaseTest):
    """Motor central, paso final: si falta algo del pedido, el juez INTERVIENE (acotado) y re-juzga."""
    PLAN = """<plan>
<objetivo>App con dos módulos</objetivo>
<interfaz>
- app.py: módulo principal
</interfaz>
<tarea id="1" archivos="app.py">Crear app.py.</tarea>
<criterios>
- existe app.py
</criterios>
</plan>"""

    def test_debe_intervenir_logica(self):
        llm = MockLLM(lambda m, k: "{}")
        orq = Orquestador(llm, self.proyecto(), self.ajustes(), self.ui())
        inf = InformeBuild("verificada")
        inf.juicio = Juicio(False, ["falta x"], confianza="high")
        self.assertTrue(orq._debe_intervenir_juez(inf, 1))
        inf.juicio = Juicio(True, [], confianza="high")
        self.assertFalse(orq._debe_intervenir_juez(inf, 1))            # cumple
        inf.juicio = Juicio(False, ["x"], confianza="low")
        self.assertFalse(orq._debe_intervenir_juez(inf, 1))            # confianza baja
        inf.juicio = Juicio(False, [], confianza="high")
        self.assertFalse(orq._debe_intervenir_juez(inf, 1))            # sin faltantes
        inf.juicio = Juicio(False, ["x"], confianza="high"); inf.intervenciones_juez = 1
        self.assertFalse(orq._debe_intervenir_juez(inf, 1))            # agotó el cupo
        inf.intervenciones_juez = 0; inf.estado = "fallida"
        self.assertFalse(orq._debe_intervenir_juez(inf, 1))            # build roja: no interviene
        self.assertFalse(orq._debe_intervenir_juez(InformeBuild("verificada"), 1))   # sin juicio

    def test_juez_interviene_y_cierra(self):
        st = {"verdict": 0}

        def guion(mensajes, kw):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
            user = mensajes[-1]["content"]
            if rol == "arquitecto":
                return terminar_xml(self.PLAN)
            if rol == "implementador":
                return herramienta_xml("write_to_file", path="app.py", content="x = 1\n") if turno == 0 \
                    else terminar_xml("app.py listo")
            if rol == "reparador":
                return herramienta_xml("write_to_file", path="extra.py", content="y = 2\n") if turno == 0 \
                    else terminar_xml("extra.py agregado")
            if rol == "juez":
                if "CONTRATO" in user:
                    return '{"criterios": ["existe app.py", "existe extra.py"]}'
                st["verdict"] += 1
                if st["verdict"] == 1:
                    return '{"cumple": false, "faltantes": ["falta extra.py"], "confianza": "high"}'
                return '{"cumple": true, "confianza": "high"}'
            return terminar_xml("ok")

        ws = self.proyecto()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=0, juez=True, juez_max_intervenciones=1)
        informe = Orquestador(MockLLM(guion), ws, ajustes, self.ui()).construir("app con dos módulos", confirmar=False)
        self.assertTrue(ws.existe("extra.py"))                         # el juez intervino y agregó lo que faltaba
        self.assertEqual(informe.intervenciones_juez, 1)
        self.assertTrue(informe.juicio and informe.juicio.cumple)
        self.assertIn(informe.estado, ("verificada", "validada"))

    def test_juez_no_interviene_si_el_cupo_es_cero(self):
        def guion(mensajes, kw):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
            user = mensajes[-1]["content"]
            if rol == "arquitecto":
                return terminar_xml(self.PLAN)
            if rol == "implementador":
                return herramienta_xml("write_to_file", path="app.py", content="x = 1\n") if turno == 0 \
                    else terminar_xml("app.py listo")
            if rol == "juez" and "CONTRATO" not in user:
                return '{"cumple": false, "faltantes": ["falta extra.py"], "confianza": "high"}'
            if rol == "juez":
                return '{"criterios": ["existe app.py"]}'
            return terminar_xml("ok")

        ws = self.proyecto()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=0, juez=True, juez_max_intervenciones=0)
        informe = Orquestador(MockLLM(guion), ws, ajustes, self.ui()).construir("app", confirmar=False)
        self.assertEqual(informe.intervenciones_juez, 0)              # cupo 0: solo avisa
        self.assertFalse(ws.existe("extra.py"))
        self.assertEqual(informe.estado, "parcial")                  # el juez igual bajó a parcial


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

    def test_plan_grande_no_se_trunca_con_el_tope_por_defecto(self):
        # El tope por defecto subió para que un proyecto mediano/grande no se cram-ee en una sola tarea.
        self.assertGreaterEqual(Settings().max_tareas, 12)
        texto = "".join(f'<tarea id="{i}" archivos="m{i}.py">módulo {i}</tarea>' for i in range(1, 11))
        plan = parsear_plan(texto, "proyecto grande", Settings().max_tareas)
        self.assertEqual(len(plan.tareas), 10)                  # 10 módulos quedan como 10 tareas, no una sola
        # Y al pasarse del tope, el resto se agrupa (no se pierde): sigue habiendo a lo sumo max_tareas.
        muchas = "".join(f'<tarea id="{i}">t{i}</tarea>' for i in range(1, 40))
        self.assertEqual(len(parsear_plan(muchas, "p", 12).tareas), 12)
