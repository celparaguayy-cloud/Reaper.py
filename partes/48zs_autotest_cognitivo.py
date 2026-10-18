"""
Fallas COGNITIVAS de un modelo gratis (simulador E2E: pruebas_fusion/e2e/openrouter_falso.py, modos MOCK_*). No son de
formato ni de red: es la cabeza del modelo la que falla.

- MOCK_MAESTRO_MALO: 13 etapas de un archivo, varias de solo tests, e insiste al replanificar. Pasarse del tope de
  etapas rechazaba el plan ENTERO (/grande no arrancaba) y los tests se unían a la etapa siguiente, no a su código.
- MOCK_JUEZ_TERCO: un juez que siempre dice "no cumple" (sin faltantes, o con uno genérico) dejaba PARCIAL cada etapa
  con la verificación real en verde: /grande se DETENÍA en la etapa 1.
- MOCK_TRAMPA: reportes que devuelven los valores que espera el test sin consultar la base: verde falso.
- MOCK_PROSA=3: tres mensajes "pensando en voz alta" antes de la primera herramienta cerraban al agente justo antes
  de actuar.
"""


def _cog_maestro(piezas: list) -> str:
    etapas = []
    for i, archivos in enumerate(piezas, 1):
        etapas.append(f'<etapa id="{i}" titulo="Pieza {i}" deps="{i - 1 if i > 1 else ""}"><objetivo>Pieza {i}.'
                      f'</objetivo><archivos>{", ".join(archivos)}</archivos></etapa>')
    return "<maestro><vision>Almacén.</vision><arquitectura>Python.</arquitectura>" + "".join(etapas) + "</maestro>"


_COG_PIEZAS_13 = [["a/__init__.py"], ["a/db.py"], ["tests/test_db.py"], ["a/ventas.py"], ["tests/test_ventas.py"],
                  ["a/reportes.py"], ["tests/test_reportes.py"], ["a/api.py"], ["tests/test_api.py"],
                  ["a/__main__.py"], ["web/logica.js"], ["tests/logica.test.mjs"], ["web/index.html", "web/app.js"]]


class TestCognitivoPlanMaestro(BaseTest):
    def _planificar(self, texto: str):
        respuestas = []

        def responder(mensajes, kw):
            respuestas.append(1)
            return texto
        ui = self.ui()
        grande = ConstructorGrande(MockLLM(responder), self.proyecto({}), self.ajustes(), ui)
        grande.consultar_cuenta = lambda: None
        return grande.planificar("Un almacén con base, ventas, reportes, API y web", confirmar=False), ui, respuestas

    def test_mas_etapas_que_el_tope_se_agrupa_si_el_modelo_insiste(self):
        maestro, ui, respuestas = self._planificar(_cog_maestro(_COG_PIEZAS_13))
        self.assertIsNotNone(maestro, ui.texto_registrado()[-1500:])   # antes: "sigue sin servir" y no arrancaba
        self.assertEqual(len(respuestas), 2)                           # UNA replanificación, ni una más
        self.assertLessEqual(len(maestro.etapas), 6)
        self.assertEqual(sorted(a for e in maestro.etapas for a in e.archivos),
                         sorted(a for p in _COG_PIEZAS_13 for a in p))

    def test_cada_test_queda_con_su_codigo(self):
        maestro, _ui, _r = self._planificar(_cog_maestro(_COG_PIEZAS_13))
        etapa_de = {a: e.id for e in maestro.etapas for a in e.archivos}
        for test, codigo in (("tests/test_db.py", "a/db.py"), ("tests/test_ventas.py", "a/ventas.py"),
                             ("tests/test_reportes.py", "a/reportes.py"), ("tests/test_api.py", "a/api.py"),
                             ("tests/logica.test.mjs", "web/logica.js")):
            self.assertEqual(etapa_de[test], etapa_de[codigo], test)  # antes: test_db.py iba con ventas

    def test_mas_del_tope_aunque_no_este_fragmentado(self):
        piezas = [[f"m/mod{i}a.py", f"m/mod{i}b.py", f"tests/test_mod{i}a.py"] for i in range(12)]
        maestro, ui, _r = self._planificar(_cog_maestro(piezas))
        self.assertIsNotNone(maestro, ui.texto_registrado()[-1500:])
        self.assertLessEqual(len(maestro.etapas), 10)

    def test_sujeto_de_test(self):
        self.assertEqual([_sujeto_de_test(r) for r in ("tests/test_db.py", "tests/logica.test.mjs", "db_test.py",
                                                       "tests/testdb.py", "spec/app.spec.js")],
                         ["db", "logica", "db", "db", "app"])


class TestCognitivoJuezTerco(BaseTest):
    PLAN = ('<plan><objetivo>Calc</objetivo><criterios>- sumar</criterios><tarea id="1" '
            'archivos="calc.py, tests/test_calc.py">sumar con su test</tarea></plan>')
    TEST = ("import unittest\nfrom calc import sumar\n\n\nclass T(unittest.TestCase):\n"
            "    def test_sumar(self):\n        self.assertEqual(sumar(2, 3), 5)\n")

    def _construir(self, veredicto: str, reparador_cambia: bool = False):
        llamadas = collections.Counter()

        def guion(mensajes, kw):
            rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
            llamadas[rol] += 1
            if rol == "arquitecto":
                return terminar_xml(self.PLAN)
            if rol == "implementador":
                archivos = [("calc.py", "def sumar(a, b):\n    return a + b\n"), ("tests/test_calc.py", self.TEST)]
                if turno < 2:
                    return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
                return terminar_xml("listo")
            if rol == "juez":
                if "CONTRATO" in MockLLM.ultimo_usuario(mensajes):
                    return '{"criterios": ["suma dos números"]}'
                return veredicto
            if rol == "reparador" and reparador_cambia and turno == 0:
                return herramienta_xml("write_to_file", path="notas.py", content="NOTA = 'revisado'\n")
            return terminar_xml("revisé y no encontré nada que cambiar")
        ws = self.proyecto({})
        ui = self.ui()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=1, juez=True, juez_max_intervenciones=1)
        informe = Orquestador(MockLLM(guion), ws, ajustes, ui).construir("Calculadora con sumar", confirmar=False)
        return informe, ui, llamadas

    def test_no_cumple_sin_decir_que_falta_no_baja_la_build(self):
        informe, ui, llamadas = self._construir('{"cumple": false, "confianza": "high"}')
        self.assertIn(informe.estado, ("verificada", "validada"), ui.texto_registrado()[-2000:])   # antes: parcial
        self.assertEqual(informe.intervenciones_juez, 0)
        self.assertTrue(any("no dice QUÉ falta" in n for n in informe.notas))

    def test_juez_que_insiste_sin_nada_que_cambiar_no_traba(self):
        informe, ui, llamadas = self._construir(
            '{"cumple": false, "faltantes": ["no se ve que cumpla el pedido"], "confianza": "high"}')
        self.assertIn(informe.estado, ("verificada", "validada"), ui.texto_registrado()[-2000:])   # antes: parcial
        self.assertEqual(informe.intervenciones_juez, 1)               # interviene UNA vez, como siempre
        self.assertIn("insiste sin nada concreto", ui.texto_registrado())

    def test_si_la_intervencion_cambio_algo_el_juez_sigue_mandando(self):
        informe, _ui, _l = self._construir(
            '{"cumple": false, "faltantes": ["falta el módulo de notas"], "confianza": "high"}', reparador_cambia=True)
        self.assertEqual(informe.estado, "parcial")                    # hubo trabajo y el juez sigue diciendo que no


_COG_TEST_REPORTES = '''import unittest

from almacen import reportes


class T(unittest.TestCase):
    def test_por_dia(self):
        self.assertEqual(reportes.ventas_por_dia(None), [{"fecha": "2026-10-01", "ventas": 1, "total": 150.0},
                                                         {"fecha": "2026-10-02", "ventas": 1, "total": 20.0}])
'''
_COG_REPORTES_TRAMPA = '''def ventas_por_dia(con):
    return [{"fecha": "2026-10-01", "ventas": 1, "total": 150.0},
            {"fecha": "2026-10-02", "ventas": 1, "total": 20.0}]
'''


class TestCognitivoRespuestasFijas(BaseTest):
    def test_detecta_la_funcion_que_devuelve_lo_que_espera_el_test(self):
        constantes = {n.value for n in ast.walk(ast.parse(_COG_TEST_REPORTES))
                      if isinstance(n, ast.Constant) and _constante_notable(n.value)}
        hallazgos = respuestas_fijas(_COG_REPORTES_TRAMPA, constantes)
        self.assertEqual([(h[0], h[2]) for h in hallazgos], [("ventas_por_dia", ["con"])])
        self.assertEqual(respuestas_fijas(_GuionAlmacen.ARCHIVOS["almacen/reportes.py"], constantes), [])
        # Una tabla fija legítima que no recibe una fuente de datos no se marca.
        self.assertEqual(respuestas_fijas("def opciones():\n    return ['2026-10-01', 'fecha', 'total']\n",
                                          constantes), [])

    def test_ni_plantillas_ni_el_almacen_correcto_se_marcan(self):
        for nombre, plantilla in PLANTILLAS.items():
            constantes = set()
            for rel, texto in plantilla.archivos.items():
                if rel.endswith(".py") and _es_test(rel):
                    try:
                        constantes |= {n.value for n in ast.walk(ast.parse(texto))
                                       if isinstance(n, ast.Constant) and _constante_notable(n.value)}
                    except SyntaxError:
                        pass
            for rel, texto in plantilla.archivos.items():
                if rel.endswith(".py") and not _es_test(rel):
                    self.assertEqual(respuestas_fijas(texto, constantes), [], f"{nombre}/{rel}")

    def test_el_examen_de_realidad_lo_ataja(self):
        ws = self.proyecto({"almacen/__init__.py": "", "tests/__init__.py": "",
                            "tests/test_reportes.py": _COG_TEST_REPORTES})
        cid = ws.checkpoints.iniciar("build")
        ws.escribir("almacen/reportes.py", _COG_REPORTES_TRAMPA)
        hallazgos = examen_de_realidad(ws, cid)
        self.assertTrue(any(h.startswith("RESPUESTA FIJA en almacen/reportes.py") for h in hallazgos), hallazgos)


class TestCognitivoProsa(BaseTest):
    def _agente(self, guion):
        ws = self.proyecto({})
        return ws, Agente("implementador", MockLLM(guion), ws, self.ajustes(forense=False, escalar=False), self.ui())

    def test_tres_mensajes_de_prosa_antes_de_la_primera_herramienta(self):
        def guion(mensajes, kw):
            turno = MockLLM.turnos_asistente(mensajes)
            if turno < 3:
                return "Voy a encarar la tarea con cuidado: primero repaso la interfaz y después escribo el código."
            if turno == 3:
                return herramienta_xml("write_to_file", path="calc.py", content="def sumar(a, b):\n    return a + b\n")
            return terminar_xml("calc.py listo")
        ws, agente = self._agente(guion)
        res = agente.ejecutar("Escribí calc.py con sumar(a, b)")
        self.assertNotEqual(res.motivo, "sin_herramientas")            # antes: se cerraba justo antes de actuar
        self.assertTrue(ws.existe("calc.py"))

    def test_si_ya_trabajaba_tres_sin_herramienta_siguen_cortando(self):
        def guion(mensajes, kw):
            if MockLLM.turnos_asistente(mensajes) == 0:
                return herramienta_xml("write_to_file", path="calc.py", content="def sumar(a, b):\n    return a + b\n")
            return "Estoy pensando cómo seguir con la tarea; enseguida continúo con lo que falta."
        _ws, agente = self._agente(guion)
        self.assertEqual(agente.ejecutar("Escribí calc.py").motivo, "sin_herramientas")


class TestCognitivoIntegracionConJuezTerco(BaseTest):
    def test_el_proyecto_termina_si_la_integracion_no_encuentra_nada_que_cambiar(self):
        base = _PRB_GuionPartible(rotas=())

        def guion(mensajes, kw):
            if MockLLM.rol_de(mensajes) == "juez":
                if "CONTRATO" in MockLLM.ultimo_usuario(mensajes):
                    return '{"criterios": ["utilidades y app"]}'
                return '{"cumple": false, "faltantes": ["no se ve que cumpla el pedido"], "confianza": "high"}'
            return base(mensajes, kw)
        ws = self.proyecto({})
        ui = self.ui()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=1, juez=True, juez_max_intervenciones=1, git_snapshots=False,
                               forense=False)
        grande = ConstructorGrande(MockLLM(guion), ws, ajustes, ui)
        grande.consultar_cuenta = lambda: None
        grande.dormir = lambda s: self.fail(f"no debía esperar {s}s")
        self.assertTrue(grande.iniciar(TestRobustoGrandeSeRecupera.PEDIDO, confirmar=False), ui.texto_registrado()[-3000:])
        estado = grande.leer()
        self.assertEqual(estado["estado"], "terminado")                # antes: "integración pendiente" para siempre
        self.assertIn("no se ve que cumpla", estado["integracion"]["aviso_juez"])
        self.assertTrue(all(e["estado"] in ("verificada", "validada") for e in estado["maestro"]["etapas"]))
