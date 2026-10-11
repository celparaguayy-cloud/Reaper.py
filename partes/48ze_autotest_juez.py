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


class TestPreservarTrabajoPrevio(BaseTest):
    """En una ACTUALIZACIÓN, lo que ya existía antes de la build no se borra ni se reescribe por accidente."""

    def _actualizacion(self, archivos):
        ws = self.proyecto(archivos)
        orq = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        orq._protegidos = {}
        return orq, ws, ws.checkpoints.iniciar("construir: actualización")

    def _verif(self, orq, tcid, declarados, build):
        return orq._verificar_tarea(tcid, ConteoTests(), set(), verificar_entrega=True,
                                    archivos_esperados=declarados, cid_build=build)

    def test_lineas_borradas(self):
        self.assertEqual(_lineas_borradas("a\nb\n", "a\nb\nc\n"), (0, 2))      # agregar no cuenta
        self.assertEqual(_lineas_borradas("a\nb\n", "a\nB\n"), (1, 2))         # cambiar una línea cuenta
        self.assertEqual(_lineas_borradas("a\n\nb\n", ""), (2, 2))             # las vacías no cuentan

    def test_borrar_archivo_previo_no_declarado(self):
        orq, ws, build = self._actualizacion({"viejo.py": "A = 1\n"})
        t = ws.checkpoints.iniciar("tarea 1", grupo=build)
        ws.escribir("nuevo.py", "N = 1\n")
        ws.borrar("viejo.py")                                                   # no le correspondía
        verif = self._verif(orq, t, ["nuevo.py"], build)
        self.assertFalse(verif.ok)
        self.assertIn("BORRÓ TRABAJO PREVIO", verif.diagnostico)

    def test_vaciar_archivo_previo_no_declarado(self):
        previo = "def a():\n    return 1\n\ndef b():\n    return 2\n\ndef c():\n    return 3\n"
        orq, ws, build = self._actualizacion({"util.py": previo})
        t = ws.checkpoints.iniciar("tarea 1", grupo=build)
        ws.escribir("nuevo.py", "N = 1\n")
        ws.escribir("util.py", "def a():\n    return 1\n")                     # perdió b() y c()
        verif = self._verif(orq, t, ["nuevo.py"], build)
        self.assertFalse(verif.ok)
        self.assertIn("MODIFICÓ TRABAJO PREVIO", verif.diagnostico)

    def test_edicion_chica_en_archivo_previo_pasa(self):
        orq, ws, build = self._actualizacion({"main.py": "import os\n\nprint('hola')\n"})
        t = ws.checkpoints.iniciar("tarea 1", grupo=build)
        ws.escribir("nuevo.py", "N = 1\n")
        ws.escribir("main.py", "import os\nimport nuevo\n\nprint('hola')\n")   # solo agrega un import
        verif = self._verif(orq, t, ["nuevo.py"], build)
        self.assertTrue(verif.ok, verif.diagnostico)

    def test_reescritura_destructiva_de_archivo_declarado(self):
        previo = "".join(f"def f{i}():\n    return {i}\n" for i in range(10))
        orq, ws, build = self._actualizacion({"app.py": previo})
        t = ws.checkpoints.iniciar("tarea 1", grupo=build)
        ws.escribir("app.py", "def nueva():\n    return 0\n")                 # lo rehízo de cero
        verif = self._verif(orq, t, ["app.py"], build)
        self.assertFalse(verif.ok)
        self.assertIn("REESCRITURA DESTRUCTIVA", verif.diagnostico)

    def test_extender_archivo_declarado_pasa(self):
        previo = "".join(f"def f{i}():\n    return {i}\n" for i in range(10))
        orq, ws, build = self._actualizacion({"app.py": previo})
        t = ws.checkpoints.iniciar("tarea 1", grupo=build)
        ws.escribir("app.py", previo + "def nueva():\n    return 0\n")         # agrega sin perder nada
        verif = self._verif(orq, t, ["app.py"], build)
        self.assertTrue(verif.ok, verif.diagnostico)

    def test_lo_creado_en_esta_build_no_esta_protegido(self):
        orq, ws, build = self._actualizacion({"README.md": "# x\n"})
        ws.checkpoints.iniciar("tarea 1", grupo=build)
        ws.escribir("modulo.py", "".join(f"L{i} = {i}\n" for i in range(10)))
        t2 = ws.checkpoints.iniciar("tarea 2", grupo=build)
        ws.escribir("modulo.py", "X = 1\n")                                   # misma actualización: se puede
        verif = self._verif(orq, t2, ["modulo.py"], build)
        self.assertTrue(verif.ok, verif.diagnostico)

    def test_resumen_preservacion_para_el_juez(self):
        orq, ws, build = self._actualizacion({"viejo.py": "A = 1\n"})
        self.assertIn("solo se agregó trabajo nuevo", resumen_preservacion(ws, build))
        ws.checkpoints.iniciar("tarea", grupo=build)
        ws.escribir("nuevo.py", "N = 1\n")
        self.assertIn("solo se agregó trabajo nuevo", resumen_preservacion(ws, build))   # lo nuevo no es previo
        ws.borrar("viejo.py")
        self.assertIn("BORRADOS: viejo.py", resumen_preservacion(ws, build))

    def test_el_juez_recibe_la_evidencia_de_preservacion(self):
        llm = MockLLM(lambda m, k: '{"cumple": true, "confianza": "high"}' if k.get("rol") == "juez" else "{}")
        orq = Orquestador(llm, self.proyecto(), self.ajustes(), self.ui())
        orq._juicio_de_entrega("pedido", _plan_web(), _verif_ok(), InformeBuild("verificada"))
        prompt = next(c for c in llm.llamadas if c.get("rol") == "juez")["mensajes"][-1]["content"]
        self.assertIn("EV-PRESERVA", prompt)


class TestJuezArmaEquipo(BaseTest):
    """El juez elige qué modelo hace cada rol según la necesidad (salud, historial, peso del rol). Sin tokens."""
    _VARS = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "REAPER_CLAVE_PROVEEDOR")

    def setUp(self):
        super().setUp()
        self._bak = {k: os.environ.pop(k, None) for k in self._VARS}
        os.environ["OPENROUTER_API_KEY"] = "x"          # solo OpenRouter tiene clave

    def tearDown(self):
        for k, v in self._bak.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def test_ningun_rol_queda_en_un_modelo_sin_clave(self):
        s = self.ajustes(modelo="venice", modelos_rol={"implementador": "groq-llama70", "revisor": "deepseek"})
        cambios, motivos = asignar_equipo_juez(s)
        self.assertEqual(cambios.get("implementador"), resolver_modelo("deepseek"))   # groq sin clave → sano y fuerte
        self.assertTrue(any("no está disponible" in m and "groq" in m for m in motivos))

    def test_roles_criticos_prefieren_un_modelo_fuerte(self):
        s = self.ajustes(modelo="venice", modelos_rol={"revisor": "deepseek"})
        cambios, _ = asignar_equipo_juez(s)
        self.assertEqual(cambios.get("implementador"), resolver_modelo("deepseek"))   # crítico: base → fuerte
        self.assertNotIn("qa", cambios)                                              # liviano: se queda

    def test_el_historial_le_gana_al_nivel(self):
        mem = MemoriaDesempeno()
        for _ in range(8):
            mem.registrar("implementador", "venice", True, verificado=True)
        s = self.ajustes(modelo="venice", modelos_rol={"revisor": "deepseek"})
        cambios, _ = asignar_equipo_juez(s, mem)
        self.assertNotIn("implementador", cambios)              # venice demostró rendir: no se cambia por nivel

    def test_disyuntor_abierto_saca_al_modelo(self):
        class Disyuntor:
            def disponible(self, m):
                return m != resolver_modelo("venice")
        s = self.ajustes(modelo="venice", modelos_rol={"revisor": "deepseek"})
        cambios, motivos = asignar_equipo_juez(s, None, Disyuntor())
        self.assertEqual(cambios.get("qa"), resolver_modelo("deepseek"))             # venice viene fallando
        self.assertTrue(any("fallando" in m for m in motivos))

    def test_sin_modelos_sanos_no_inventa(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        cambios, motivos = asignar_equipo_juez(self.ajustes(modelo="venice"))
        self.assertEqual((cambios, motivos), ({}, []))

    def test_la_asignacion_vale_solo_para_la_build(self):
        s = self.ajustes(modelo="venice", modelos_rol={"revisor": "deepseek"})
        orq = Orquestador(MockLLM([]), self.proyecto(), s, self.ui())
        original = dict(s.modelos_rol)
        restaurar = orq._equipo_del_juez()
        self.assertEqual(s.modelo_para("implementador"), resolver_modelo("deepseek"))  # durante la build
        restaurar()
        self.assertEqual(s.modelos_rol, original)               # después: la config del usuario intacta

    def test_equipo_juez_muestra_como_armaria_el_equipo(self):
        s = self.ajustes(modelo="venice", modelos_rol={"implementador": "groq-llama70", "revisor": "deepseek"})
        app = App(s, MockLLM([]), self.ui(), self.proyecto(), persistir=False)
        app.cmd_equipo("juez")
        texto = app.ui.texto_registrado()
        self.assertIn("el juez arma el equipo", texto)
        self.assertIn("implementador", texto)
        self.assertEqual(s.modelo_para("implementador"), resolver_modelo("groq-llama70"))   # solo muestra, no cambia


class TestArranqueReal(BaseTest):
    """Que los tests pasen no alcanza: el proyecto tiene que ARRANCAR (caso real: python -m paquete no importaba)."""
    _CLI_OK = "import argparse\n\ndef main():\n    argparse.ArgumentParser(prog='app').parse_args()\n"

    def test_paquete_que_no_importa_esta_roto(self):
        ws = self.proyecto({"app/__init__.py": "", "app/__main__.py": "from app.cli import main\nmain()\n"})
        problemas = verificar_arranque(ws)                      # app/cli.py no existe → ModuleNotFoundError
        self.assertEqual(len(problemas), 1)
        self.assertIn("ARRANQUE", problemas[0])
        self.assertIn("python -m app", problemas[0])

    def test_paquete_sano_arranca(self):
        ws = self.proyecto({"app/__init__.py": "", "app/cli.py": self._CLI_OK,
                            "app/__main__.py": "from app.cli import main\nmain()\n"})
        self.assertEqual(verificar_arranque(ws), [])

    def test_script_con_error_de_sintaxis(self):
        ws = self.proyecto({"main.py": "import sys\nif __name__ == '__main__':\n    print(sys.argv\n"})
        self.assertTrue(verificar_arranque(ws))                 # SyntaxError al cargar

    def test_no_es_roto_si_solo_rechaza_el_help(self):
        # Usa sys.argv como dato: '--help' le da ValueError. Eso NO es "no arranca" (cargó bien).
        ws = self.proyecto({"main.py": "import sys\nif __name__ == '__main__':\n    print(int(sys.argv[1]))\n"})
        self.assertEqual(verificar_arranque(ws), [])

    def test_programa_interactivo_no_es_roto(self):
        ws = self.proyecto({"juego.py": "import sys\nif __name__ == '__main__':\n    print(sys.argv)\n"
                                        "    input('tu jugada: ')\n"})
        self.assertEqual(verificar_arranque(ws), [])            # stdin vacío → EOFError: no es falla de carga

    def test_una_libreria_sin_punto_de_entrada_no_se_corre(self):
        ws = self.proyecto({"calc.py": "def suma(a, b):\n    return a + b\n"})
        self.assertEqual(puntos_de_entrada(ws), [])

    def test_la_verificacion_final_no_aprueba_un_proyecto_que_no_arranca(self):
        ws = self.proyecto({"app/__init__.py": "", "app/__main__.py": "from app.cli import main\nmain()\n"})
        orq = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        orq._huella_aceptacion = None
        grupo = ws.checkpoints.iniciar("construir")
        verif = orq.verificar(grupo)
        self.assertFalse(verif.ok)
        self.assertIn("ARRANQUE", verif.diagnostico)
        orq.settings.verificar_arranque = False                 # se puede apagar
        self.assertTrue(orq.verificar(grupo).ok)


class TestJuezRealidad(BaseTest):
    """El juez hace más que nadie y gasta menos que nadie: el examen de realidad es gratis (0 tokens)."""
    PLAN = """<plan>
<objetivo>Sumadora</objetivo>
<interfaz>
- app.py: def sumar(a, b) -> int
</interfaz>
<tarea id="1" archivos="app.py">Crear app.py con def sumar(a, b).</tarea>
<criterios>
- sumar(2, 3) == 5
</criterios>
</plan>"""

    def test_detecta_cuerpos_de_mentira(self):
        self.assertEqual(stubs_en_codigo("def f():\n    pass\n"), [("f", 1, "vacia")])
        self.assertEqual(stubs_en_codigo("def f():\n    ...\n")[0][2], "vacia")
        self.assertEqual(stubs_en_codigo('def f():\n    """solo doc"""\n')[0][2], "vacia")
        self.assertEqual(stubs_en_codigo("def f():\n    raise NotImplementedError\n")[0][2], "no_implementada")
        self.assertEqual(stubs_en_codigo("def f():\n    return 1\n"), [])

    def test_no_marca_cuerpos_vacios_legitimos(self):
        fuente = ("from abc import ABC, abstractmethod\nfrom typing import Protocol\n"
                  "class Base(ABC):\n    @abstractmethod\n    def correr(self):\n        raise NotImplementedError\n"
                  "class P(Protocol):\n    def leer(self): ...\n"
                  "class C:\n    def __init__(self):\n        pass\n")
        self.assertEqual(stubs_en_codigo(fuente), [])

    def _build(self, archivos):
        ws = self.proyecto()
        grupo = ws.checkpoints.iniciar("construir")
        for rel, contenido in archivos.items():
            ws.escribir(rel, contenido)
        return ws, grupo

    def test_examen_marca_lo_pedido_vacio_y_no_los_hooks(self):
        ws, grupo = self._build({"app.py": "def sumar(a, b):\n    pass\n\ndef al_cerrar():\n    pass\n"})
        plan = parsear_plan(self.PLAN, "sumadora")
        hallazgos = examen_de_realidad(ws, grupo, plan)
        self.assertEqual(len(hallazgos), 1)                    # sumar (pedida) sí; al_cerrar (hook) no
        self.assertIn("sumar", hallazgos[0])
        self.assertIn("SIMULACIÓN", hallazgos[0])

    def test_examen_marca_not_implemented_aunque_no_este_en_el_plan(self):
        ws, grupo = self._build({"util.py": "def calcular():\n    raise NotImplementedError('después')\n"})
        self.assertTrue(any("NotImplementedError" in h for h in examen_de_realidad(ws, grupo, None)))

    def test_examen_marca_tests_que_no_prueban_nada(self):
        ws, grupo = self._build({"app.py": "def sumar(a, b):\n    return a + b\n",
                                 "tests/test_app.py": "def test_suma():\n    assert True\n"})
        hallazgos = examen_de_realidad(ws, grupo, parsear_plan(self.PLAN, "sumadora"))
        self.assertTrue(any("TEST SIN VALOR" in h for h in hallazgos))

    def test_examen_ok_si_todo_es_real(self):
        ws, grupo = self._build({"app.py": "def sumar(a, b):\n    return a + b\n",
                                 "tests/test_app.py": "from app import sumar\n\ndef test_suma():\n"
                                                      "    assert sumar(2, 3) == 5\n"})
        self.assertEqual(examen_de_realidad(ws, grupo, parsear_plan(self.PLAN, "sumadora")), [])

    def test_veredicto_determinista_no_gasta_tokens(self):
        ws, grupo = self._build({"app.py": "def sumar(a, b):\n    pass\n"})
        llm = MockLLM(lambda m, k: '{"cumple": true, "confianza": "high"}')
        orq = Orquestador(llm, ws, self.ajustes(), self.ui())
        informe = InformeBuild("validada", cid=grupo)
        orq._juicio_de_entrega("una sumadora", parsear_plan(self.PLAN, "sumadora"), _verif_ok(), informe)
        self.assertTrue(informe.juicio.determinista)
        self.assertFalse(informe.juicio.cumple)
        self.assertEqual(informe.estado, "parcial")
        self.assertEqual([c for c in llm.llamadas if c.get("rol") == "juez"], [])   # ni una llamada al modelo
        self.assertEqual(getattr(orq, "_tokens_juez", 0), 0)

    def test_si_todo_es_real_consulta_al_modelo_y_cuenta_sus_tokens(self):
        ws, grupo = self._build({"app.py": "def sumar(a, b):\n    return a + b\n"})
        llm = MockLLM(lambda m, k: '{"cumple": true, "confianza": "high"}' if k.get("rol") == "juez" else "{}")
        orq = Orquestador(llm, ws, self.ajustes(), self.ui())
        informe = InformeBuild("validada", cid=grupo)
        orq._juicio_de_entrega("una sumadora", parsear_plan(self.PLAN, "sumadora"), _verif_ok(), informe)
        llamada = next(c for c in llm.llamadas if c.get("rol") == "juez")
        self.assertIn("EV-REAL", llamada["mensajes"][-1]["content"])
        self.assertGreater(orq._tokens_juez, 0)
        self.assertEqual(informe.estado, "validada")

    def test_build_con_funcion_vacia_el_juez_la_hace_real(self):
        st = {"rep": 0}

        def guion(mensajes, kw):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
            user = mensajes[-1]["content"]
            if rol == "arquitecto":
                return terminar_xml(self.PLAN)
            if rol == "implementador":           # deja la función pedida vacía: una simulación
                return herramienta_xml("write_to_file", path="app.py", content="def sumar(a, b):\n    pass\n") \
                    if turno == 0 else terminar_xml("listo")
            if rol == "reparador":               # el juez interviene y el reparador la implementa de verdad
                st["rep"] += 1
                return herramienta_xml("write_to_file", path="app.py", content="def sumar(a, b):\n    return a + b\n") \
                    if turno == 0 else terminar_xml("sumar implementada")
            if rol == "juez":
                return '{"criterios": ["sumar(2, 3) == 5"]}' if "CONTRATO" in user \
                    else '{"cumple": true, "confianza": "high"}'
            return terminar_xml("ok")

        ws = self.proyecto()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=0, juez=True, juez_max_intervenciones=1)
        informe = Orquestador(MockLLM(guion), ws, ajustes, self.ui()).construir("una sumadora", confirmar=False)
        self.assertEqual(ws.leer("app.py"), "def sumar(a, b):\n    return a + b\n")   # quedó real
        self.assertEqual(informe.intervenciones_juez, 1)
        self.assertTrue(informe.juicio and informe.juicio.cumple)
        self.assertIn(informe.estado, ("verificada", "validada"))
        self.assertGreater(informe.tokens_build, 0)
        self.assertLess(informe.tokens_juez, informe.tokens_build)   # el juez gastó menos que la build


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
