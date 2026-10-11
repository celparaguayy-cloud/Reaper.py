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


class TestEquipoXUsuario(BaseTest):
    def _app(self):
        return App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), self.proyecto(), persistir=False)

    def test_x_on_pone_a_dolphin_de_director(self):
        app = self._app()
        app.comando("/equipo x on")
        self.assertEqual(app.settings.modelos_rol.get("director"), "or-dolphin-jefe-free")
        d = destino_modelo(app.settings.modelo_para("director"), app.settings)
        self.assertEqual((d.proveedor, d.modelo), ("openrouter", "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"))

    def test_x_on_respeta_un_director_ya_asignado(self):
        app = self._app()
        app.comando("/modelo director qwen")
        app.comando("/equipo x on")
        self.assertEqual(app.settings.modelos_rol["director"], resolver_modelo("qwen"))

    def test_preset_arma_el_equipo_del_usuario_con_ruteo_correcto(self):
        app = self._app()
        app.comando("/equipo x preset")
        self.assertTrue(app.settings.roles_x)
        esperado = {"director": ("openrouter", "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"),
                    "supervisor": ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
                    "arquitecto": ("groq", "openai/gpt-oss-120b"),
                    "implementador": ("openrouter", "cohere/north-mini-code:free"),
                    "revisor": ("groq", "qwen/qwen3.8-27b"),
                    "qa": ("gemini", "gemini-3.5-flash-lite"),
                    "reparador": ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free")}
        for rol, (prov, modelo) in esperado.items():
            d = destino_modelo(app.settings.modelo_para(rol), app.settings)
            self.assertEqual((d.proveedor, d.modelo), (prov, modelo), rol)
        c = conteo_equipo_x(app.settings)
        self.assertEqual((c["roles"], c["proveedores"]), (10, 3))
        self.assertEqual(c["modelos_verificados"], 0)          # configurar no es verificar

    def test_tags_free_no_se_dan_por_verificados(self):
        self.assertFalse(INFO_MODELOS["or-dolphin-jefe-free"].free)


class TestReaper810(BaseTest):
    """Regresiones de permisos, identificación e informes del propio REAPER."""

    def test_version_estable(self):
        self.assertEqual(__version__, "8.10")

    def test_consultas_comunes_no_preguntan(self):
        for comando in ("ls -lah", "git status --short", "git rev-parse HEAD",
                        "git ls-files", "python3 -m py_compile demo.py", "npm --version"):
            with self.subTest(comando=comando):
                self.assertTrue(comando_seguro(comando))

    def test_prefijos_falsos_y_shell_compuesto_no_son_seguros(self):
        for comando in ("lsmalo", "git statusmalicioso", "node --checker algo",
                        "ls\npython3 script.py", "pwd\rpython3 script.py",
                        "git status; python3 script.py", "git log && python3 script.py"):
            with self.subTest(comando=comando):
                self.assertFalse(comando_seguro(comando))

    def test_comandos_peligrosos_no_son_consultas(self):
        self.assertFalse(comando_seguro("python3 script.py"))
        self.assertFalse(comando_seguro("npm install paquete"))

    def test_filtro_inexistente_no_da_verde_falso(self):
        self.assertEqual(correr_autotest(filtro="reaper810_no_existe_987"), 2)


# ======================================================================
# TESTS DE REGRESIÓN REAPER 8.10 — conexiones, permisos, web y workspace
# ======================================================================
class TestReaper810Mejoras(BaseTest):
    def test_alias_heredados_resuelven_sin_id_invalido(self):
        # El alias ultra resuelve a SU id (presente en el catálogo público de OpenRouter, consultado el
        # 2026-10-11); antes se reasignaba a Nemotron Super, que es otro modelo.
        self.assertEqual(resolver_modelo("openrouter:or-nemotron3-ultra-free"),
                         "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertEqual(resolver_modelo("groq-gptoss120"), "openai/gpt-oss-120b")   # no salta a otro proveedor
        self.assertEqual(resolver_modelo("groq:openai/gpt-oss-120b"), "groq:openai/gpt-oss-120b")
        self.assertEqual(resolver_modelo("openrouter:cohere/north-mini-code:free"),
                         "openrouter:cohere/north-mini-code:free")

    def test_permiso_consulta_es_estricto(self):
        self.assertTrue(comando_seguro('find . -name "*.py" -type f'))
        for c in ('python3 -m pytest', 'npm test', 'find . -delete',
                  'find . -exec sh -c "echo foo" ;', 'cat .env',
                  'ls /sdcard', 'git status; echo pwn', 'ls $(whoami)'):
            with self.subTest(comando=c):
                self.assertFalse(comando_seguro(c))

    def test_shell_tool_no_se_disfraza_de_comando(self):
        ctx = self.contexto(self.proyecto())
        with self.assertRaises(ErrorHerramienta) as e:
            execute_command(ctx, {"command": "read_file tests/test_db.py"})
        self.assertIn('herramienta REAPER', str(e.exception))

    def test_probe_no_da_verde_falso(self):
        self.assertEqual(_probar_modelo(MockLLM(["no sé"]), "modelo")['estado'], 'FALLA')
        self.assertEqual(_probar_modelo(MockLLM(["REAPER_OK"]), "modelo")['estado'], 'RESPONDE')

    def test_parser_web_busqueda_html(self):
        raw = ('<a class="result__a" '
               'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2Flibrary%2Fsqlite3.html">'
               'Python docs</a>')
        self.assertEqual(extraer_resultados_busqueda(raw),
                         [("Python docs", "https://docs.python.org/3/library/sqlite3.html")])

    def test_busqueda_web_simulada_sin_red(self):
        from unittest.mock import patch
        ctx = self.contexto(self.proyecto())
        convertido = "SQLite Python docs (https://docs.python.org/3/library/sqlite3.html)"
        with patch.dict(web_search.__globals__, {"descargar_texto": lambda *a, **k: {"texto": convertido}}):
            resultado = web_search(ctx, {"query": "Python sqlite3 docs", "max_results": "3"})
        self.assertIn('docs.python.org', resultado)
        self.assertIn('abrí los enlaces', resultado)

    def test_busqueda_no_inventa_resultados(self):
        from unittest.mock import patch
        ctx = self.contexto(self.proyecto())
        with patch.dict(web_search.__globals__, {"descargar_texto": lambda *a, **k: {"texto": "sin resultados"}}):
            with self.assertRaises(ErrorHerramienta):
                web_search(ctx, {"query": "algo realmente raro"})

    def test_busqueda_rechaza_secretos(self):
        ctx = self.contexto(self.proyecto())
        with self.assertRaises(ErrorHerramienta):
            web_search(ctx, {"query": "api_key=mi_clave_super_privada"})

    def test_workspace_de_otro_proyecto_protegido(self):
        ws = self.proyecto({"tests/test_api.py": "def test_postulacion_de_trabajador(): pass"})
        alerta = detectar_workspace_mezclado(ws, "Construye NovaDB desde cero")
        self.assertIn('CONFLICTO', alerta)
        app = App(self.ajustes(), MockLLM([]), self.ui(), ws, persistir=False)
        self.assertFalse(app.turno("Construye NovaDB desde cero"))
        self.assertFalse(app.construir("Construye NovaDB desde cero", confirmar=False))
        self.assertEqual(len(app.llm.llamadas), 0)

    def test_workspace_limpio_no_se_bloquea(self):
        ws = self.proyecto({"README.md": "Proyecto nuevo"})
        self.assertFalse(detectar_workspace_mezclado(ws, "Construye NovaDB desde cero"))

    def test_limpieza_bucles_xml(self):
        salida = limpiar_texto_visible("hola " + "</tool_calls>" * 5000)
        self.assertLess(len(salida), 2000)
        self.assertIn('etiquetas XML repetidas', salida)

    def test_actualidad_dispara_busqueda_antes_de_responder(self):
        from unittest.mock import patch
        ws = self.proyecto()
        llm = MockLLM(["No pude verificar la fecha exacta."])
        app = App(self.ajustes(), llm, self.ui(), ws, persistir=False)
        with patch.dict(Agente.ejecutar.__globals__, {
            "web_search": lambda ctx, p: "1. Fuente ejemplo — https://example.org/actualidad"}):
            app.turno("que fecha se retiro Messi")
        self.assertTrue(llm.llamadas)
        self.assertIn("BÚSQUEDA EN VIVO", llm.llamadas[0]["mensajes"][1]["content"])

    def test_pedido_codigo_privado_no_dispara_busqueda(self):
        from unittest.mock import patch
        ws = self.proyecto()
        llm = MockLLM(["Perfecto, revisaría el código."])
        app = App(self.ajustes(), llm, self.ui(), ws, persistir=False)
        with patch.dict(Agente.ejecutar.__globals__, {
            "web_search": lambda ctx, p: (_ for _ in ()).throw(AssertionError("web no autorizado"))}):
            app.turno("Crea un archivo utils.py y corrige el código")
        self.assertTrue(llm.llamadas)

    def test_buscar_manual_funciona_con_mock(self):
        from unittest.mock import patch
        ws = self.proyecto()
        app = App(self.ajustes(), MockLLM([]), self.ui(), ws, persistir=False)
        with patch.dict(App.cmd_buscar.__globals__, {
            "web_search": lambda ctx, p: "Fuente: https://docs.python.org"}):
            app.comando("/buscar python sqlite3")
        self.assertIn("docs.python.org", app.ui.texto_registrado())

    def test_prompt_exige_fecha_y_buscador(self):
        ws = self.proyecto()
        p = system_prompt(ROLES['principal'], ws)
        self.assertIn('web_search', p)
        self.assertIn('Fecha y hora local', p)
        self.assertIn('ACTUALIDAD Y FUENTES', p)
        self.assertIn('web_search', ROLES['principal'].herramientas)

# ======================================================================
# REAPER 8.10: REGRESIONES DE AUDITORÍA (cache, secretos, pegado, TLS)
# ======================================================================
class TestReaper810Auditoria2(BaseTest):
    def test_comandos_lectura_credenciales_siempre_requieren_aprobacion(self):
        for comando in (
            "head -40 .env", "tail -n 3 /home/me/.env.local",
            "git show HEAD:.env", "rg password .", "grep -r contraseña .",
            "head -c 100 id_ed25519", "head secrets.pem",
            "rg --hidden CLAVE .", "ls ~/.ssh/id_rsa",
        ):
            with self.subTest(comando=comando):
                self.assertFalse(comando_seguro(comando))
        self.assertTrue(comando_seguro('find . -name "*.py" -type f'))
        self.assertTrue(comando_seguro('git status --short'))

    def test_cache_no_salta_bloqueo_de_destino_dns_privado(self):
        from unittest.mock import patch
        cache = self.dir / 'web_cache.json'
        cache.write_text(json.dumps({'url': 'https://publico.example/a',
                         'texto':'secreto cacheado', 'guardado':time.time()}), encoding='utf-8')
        conexiones = []
        with patch.dict(descargar_texto.__globals__, {'_ruta_cache':lambda u:cache}):
            with self.assertRaises(ValueError):
                descargar_texto('https://publico.example/a',
                    resolver=lambda host:['127.0.0.1'],
                    abrir=lambda *args:conexiones.append(args))
        self.assertFalse(conexiones)

    def test_cache_valida_evitar_descarga(self):
        from unittest.mock import patch
        cache = self.dir / 'web_cache.json'
        cache.write_text(json.dumps({'url':'https://publico.example/a',
                           'texto':'cached','guardado':time.time()}), encoding='utf-8')
        with patch.dict(descargar_texto.__globals__, {'_ruta_cache':lambda u:cache}):
            got = descargar_texto('https://publico.example/a',
                     resolver=lambda host:['1.1.1.1'],
                     abrir=lambda *args: (_ for _ in ()).throw(AssertionError('no GET')))
        self.assertEqual(got['texto'], 'cached')

    def test_cache_no_entrega_una_redireccion_privada(self):
        from unittest.mock import patch
        cache = self.dir / 'web_cache.json'
        cache.write_text(json.dumps({'url':'https://interno.example/secreto',
                           'texto':'dato interno','guardado':time.time()}), encoding='utf-8')
        resolver = lambda host: ['127.0.0.1'] if host == 'interno.example' else ['1.1.1.1']
        with patch.dict(descargar_texto.__globals__, {'_ruta_cache':lambda u:cache}):
            got = descargar_texto('https://publico.example/a', resolver=resolver,
                abrir=lambda *args:{'status':200, 'location':None,'ctype':'text/plain','body':b'publico'})
        self.assertEqual(got['texto'], 'publico')

    def test_charset_invalido_no_interrumpe_descarga(self):
        got = descargar_texto('https://publico.example/a', usar_cache=False,
            resolver=lambda host:['1.1.1.1'],
            abrir=lambda *args:{'status':200, 'location':None,
                'ctype':'text/plain; charset=no_existe_este_charset','body':b'Contenido'})
        self.assertEqual(got['texto'], 'Contenido')

    def test_fallo_handshake_cierra_socket(self):
        from unittest.mock import patch
        class FakeSock:
            closed = False
            def close(self):self.closed = True
        class FakeContext:
            def wrap_socket(self, sock, server_hostname):
                raise OSError('TLS rechazado')
        s = FakeSock()
        d = validar_destino('https://publico.example/a', resolver=lambda host:['1.1.1.1'])
        with patch.dict(_web_abrir.__globals__, {
                'socket': type('Sock', (), {'create_connection':staticmethod(lambda *a,**k:s)}),
                '_web_ssl':type('SSL', (), {'create_default_context':staticmethod(lambda:FakeContext())})}):
            with self.assertRaises(OSError):
                _web_abrir(d, 'https://publico.example/a', 2, 400)
        self.assertTrue(s.closed)

    def test_busqueda_rechaza_datos_privados_no_necesarios(self):
        ctx = self.contexto(self.proyecto())
        for consulta in ('clave sk-abcdefghijklmnopqrst',
                         'codigo /data/data/com.termux/files/home/.ssh/id_rsa',
                         'api_key=supersecret'):
            with self.subTest(consulta=consulta), self.assertRaises(ErrorHerramienta):
                web_search(ctx, {'query':consulta})
        self.assertFalse(requiere_busqueda_actual('precio actual de /data/data/com.termux'))

    def test_pegar_incompleto_no_ejecuta_fragmentos(self):
        from unittest.mock import patch
        app=App(self.ajustes(), MockLLM([]), self.ui(), self.proyecto(), persistir=False)
        with patch('builtins.input', side_effect=['/pegar','Requisito 1',EOFError]):
            self.assertEqual(app._leer_entrada(), '')
        self.assertIn('incompleto', app.ui.texto_registrado())
