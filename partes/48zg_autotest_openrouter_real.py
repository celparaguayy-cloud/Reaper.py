"""
Autotests de regresión de la PRUEBA REAL con OpenRouter (modelos :free, octubre 2026). Lo que apareció con un
modelo de verdad y no con el MockLLM:

- Un 429 del pool gratis compartido ("rate-limited upstream") se reintentaba 4 veces contra el MISMO modelo
  (~35 s por modelo) y el mensaje era el JSON crudo del proveedor, cortado a la mitad, en cada reintento.
- A una respuesta sin archivos cambiados ("Respondé OK") se le mostraba "verificación: UNVERIFIED".
"""

_CUERPO_SATURADO = json.dumps({"error": {"message": "Provider returned error", "code": 429, "metadata": {
    "raw": "poolside/laguna-s-2.1:free is temporarily rate-limited upstream. Please retry shortly.",
    "provider_name": "Poolside", "limit_source": "upstream_provider_shared_pool"}}})


class TestOpenRouterRealErrores(BaseTest):
    def _cliente(self, eventos, **ajustes):
        return LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte_falso(eventos))

    def test_detalle_error_es_legible_y_corto(self):
        detalle = _detalle_error(_CUERPO_SATURADO)
        self.assertIn("temporarily rate-limited upstream", detalle)
        self.assertNotIn('{"error"', detalle)                          # no el JSON crudo
        self.assertLessEqual(len(_detalle_error("x" * 5000)), 220)
        self.assertEqual(_detalle_error("Bad Gateway"), "Bad Gateway")  # texto plano: tal cual

    def test_429_de_pool_compartido_se_marca_saturado(self):
        with self.assertRaises(_Transitorio) as ctx:
            _lanzar_http(429, _CUERPO_SATURADO, None)
        self.assertTrue(ctx.exception.saturado)
        self.assertNotIn('{"error"', str(ctx.exception))
        with self.assertRaises(_Transitorio) as ctx2:
            _lanzar_http(429, "Too Many Requests", "3")                 # TU límite: no es el pool compartido
        self.assertFalse(ctx2.exception.saturado)

    def test_pool_saturado_pasa_enseguida_a_otro_modelo(self):
        c = self._cliente([_Transitorio("429 pool", saturado=True), "ok"], reintentos=4, rpm=0,
                          fallbacks=["otro/modelo:free"])
        esperas = []
        c.dormir = lambda s: esperas.append(s)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual(sum(esperas), 0)                               # antes: 4 reintentos, ~35 s
        self.assertEqual(c.uso.respaldos, 1)

    def test_pool_saturado_sin_alternativa_sigue_reintentando(self):
        c = self._cliente([_Transitorio("429 pool", saturado=True), "ok"], reintentos=2, rpm=0,
                          fallbacks=[], respaldo_equipo=False)
        esperas = []
        c.dormir = lambda s: esperas.append(s)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertGreater(sum(esperas), 0)                             # sin otro modelo: esperar es lo único


class TestOpenRouterRealVerificacion(BaseTest):
    def test_respuesta_sin_cambios_no_muestra_unverified(self):
        app = App(self.ajustes(modo="auto"), MockLLM(lambda m, k: "OK"), self.ui(), self.proyecto(),
                  persistir=False)
        app.turno("Respondé solo la palabra OK, sin herramientas.")
        claim = getattr(app.principal, "_ultimo_claim", None)
        if claim is None or claim.nivel != "UNVERIFIED":
            self.skipTest(f"el Evidence Gate no dejó UNVERIFIED en este cierre ({getattr(claim, 'nivel', None)})")
        texto = app.ui.texto_registrado()
        self.assertNotIn("UNVERIFIED", texto)                         # nada que verificar: no asustar
        self.assertNotIn("SIN VERIFICAR", texto)


class TestOpenRouterRealRazonamiento(BaseTest):
    def test_se_quedo_pensando_reintenta_con_mas_margen(self):
        pagos = []
        eventos = [LLMError("m solo devolvió razonamiento (1471 caracteres) y ninguna respuesta (finish=length).",
                            probar_otro_modelo=True, solo_razonamiento=True), "ok"]
        base = transporte_falso(eventos)

        def transporte(url, headers, payload, timeout):
            pagos.append(dict(payload))
            return base(url, headers, payload, timeout)

        c = LLMClient("clave", self.ajustes(reintentos=0, rpm=0, fallbacks=[], respaldo_equipo=False),
                      url="http://falso", transporte=transporte)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}], max_tokens=350).texto, "ok")
        self.assertEqual(len(pagos), 2)                                   # mismo modelo, una vez más
        self.assertGreaterEqual(pagos[1]["max_tokens"], 2048)             # con margen para pensar
        self.assertGreater(pagos[1]["max_tokens"], pagos[0]["max_tokens"])

    def test_otro_corte_por_razonamiento_no_se_reintenta_infinito(self):
        error = LLMError("m solo devolvió razonamiento (9 caracteres) y ninguna respuesta (finish=length).",
                         probar_otro_modelo=True, solo_razonamiento=True)
        c = LLMClient("clave", self.ajustes(reintentos=3, rpm=0, fallbacks=[], respaldo_equipo=False),
                      url="http://falso", transporte=transporte_falso([error, error, "nunca"]))
        with self.assertRaises(LLMError):
            c.chat([{"role": "user", "content": "x"}], max_tokens=350)   # un solo reintento ampliado


class TestOpenRouterRealPlan(BaseTest):
    def _plan(self, *descripciones):
        return Plan(objetivo="", criterios=[], tareas=[Tarea(str(i), d, [f"m{i}.py"])
                                                      for i, d in enumerate(descripciones, 1)])

    def test_detecta_planes_que_ordenan_simular_y_meta_tareas(self):
        plan = self._plan("Crear core.py con esqueletos de las funciones que lanzan NotImplementedError",
                          "Implementar sumar(a, b) en core.py",
                          "Ejecutar las pruebas con python -m unittest y ajustar si fallan",
                          "Escribir tests en tests/test_core.py")
        problemas = problemas_del_plan(plan)
        self.assertEqual(len(problemas), 2)
        self.assertTrue(problemas[0].startswith("la tarea 1"))
        self.assertTrue(problemas[1].startswith("la tarea 3"))

    def test_meta_tareas_reales_y_no_falsos_positivos(self):
        for meta in ("Ejecutar el conjunto de pruebas (python -m unittest discover) para confirmar que pasan",
                     "Verificar que todos los tests pasen", "Correr la suite", "Run all the tests",
                     "Ejecutar las pruebas con python -m unittest"):
            self.assertTrue(_RE_META_TAREA.search(meta), meta)
        for real in ("Validar el formulario de login en app.py", "Verificar las entradas del usuario",
                     "Escribir pruebas unitarias en tests/test_core.py", "Ejecutar la migración de la base"):
            self.assertFalse(_RE_META_TAREA.search(real), real)

    def test_falsos_positivos_y_vinetas_de_la_prueba_real(self):
        # Build real 4: "verificar que todo funciona" se marcó como simulación por la palabra "todo", y
        # "- ejecutar las pruebas…" (sin archivos) no se detectó como meta-tarea por el guion de viñeta.
        plan = self._plan("- ejecutar las pruebas para verificar que todo funciona: usar python -m unittest",
                          "Implementar todos los endpoints de la API en app.py",
                          "2) Correr los tests", "Agregar validación; dejar un TODO para el caché")
        problemas = problemas_del_plan(plan)
        self.assertFalse(any("la tarea 2" in p for p in problemas))      # "todos" no es TODO
        self.assertFalse(any("la tarea 1 planea una simulación" in p for p in problemas))
        self.assertTrue(any(p.startswith("la tarea 1 solo corre") for p in problemas))
        self.assertTrue(any(p.startswith("la tarea 3 solo corre") for p in problemas))
        self.assertTrue(any("la tarea 4 planea una simulación («TODO»)" in p for p in problemas))
        self.assertEqual(quitar_meta_tareas(plan), ["1", "3"])

    def test_quitar_meta_tareas_limpia_dependencias(self):
        plan = self._plan("Implementar sumar en core.py", "Correr los tests y verificar", "Agregar restar")
        plan.tareas[2].deps = ["1", "2"]
        self.assertEqual(quitar_meta_tareas(plan), ["2"])
        self.assertEqual([t.id for t in plan.tareas], ["1", "3"])
        self.assertEqual(plan.tareas[1].deps, ["1"])
        solo_meta = self._plan("Ejecutar las pruebas")
        self.assertEqual(quitar_meta_tareas(solo_meta), [])               # nunca deja el plan vacío

    def test_el_juez_hace_replanificar_un_plan_que_pide_esqueletos(self):
        malo = ('<plan><objetivo>x</objetivo><interfaz>- core.py: def sumar(a, b)</interfaz>'
                '<tarea id="1" archivos="core.py">Crear core.py con esqueletos que lanzan NotImplementedError</tarea>'
                '<tarea id="2" archivos="core.py" deps="1">Ejecutar las pruebas</tarea>'
                '<criterios>- sumar(2, 3) == 5</criterios></plan>')
        bueno = ('<plan><objetivo>x</objetivo><interfaz>- core.py: def sumar(a, b)</interfaz>'
                 '<tarea id="1" archivos="core.py">Implementar sumar(a, b) completa en core.py</tarea>'
                 '<criterios>- sumar(2, 3) == 5</criterios></plan>')
        pedidos = []

        def guion(mensajes, kw):
            if MockLLM.rol_de(mensajes) == "arquitecto":
                pedidos.append(mensajes[-1]["content"])
                return terminar_xml(bueno if any("Corregí estos problemas" in m["content"] for m in mensajes)
                                    else malo)
            return terminar_xml("ok")

        ui = self.ui()
        orq = Orquestador(MockLLM(guion), self.proyecto(), self.ajustes(), ui)
        plan, _ = orq.obtener_plan("una sumadora", confirmar=False)
        self.assertEqual([t.descripcion for t in plan.tareas], ["Implementar sumar(a, b) completa en core.py"])
        self.assertIn("el plan pide simulaciones", ui.texto_registrado())


class TestOpenRouterRealTareaYaHecha(BaseTest):
    PLAN = """<plan>
<objetivo>Conversor</objetivo>
<interfaz>
- conversor.py: def c_a_f(c) -> float; def f_a_c(f) -> float
</interfaz>
<tarea id="1" archivos="conversor.py">Crear conversor.py con c_a_f(c).</tarea>
<tarea id="2" archivos="conversor.py" deps="1">Agregar f_a_c(f) en conversor.py.</tarea>
<tarea id="3" archivos="extra.py" deps="2">Crear extra.py con def nada(): return 1</tarea>
<criterios>
- c_a_f(100) == 212.0
</criterios>
</plan>"""

    def test_tarea_que_ya_hizo_otra_no_falla_ni_bloquea(self):
        # Caso real: la tarea 1 se adelantó e implementó todo; el implementador de la 2 leyó, corrió los tests
        # (pasaban) y terminó SIN cambios. Antes: "SIN PROGRESO: no terminó" → 3 reparaciones sin nada que
        # arreglar → tarea 2 fallida y la 3 BLOQUEADA.
        completo = "def c_a_f(c):\n    return c * 9 / 5 + 32\n\n\ndef f_a_c(f):\n    return (f - 32) * 5 / 9\n"

        def guion(mensajes, kw):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
            todo = "\n".join(m["content"] for m in mensajes if m["role"] == "user")
            actual = re.search(r"TU TAREA AHORA \(#(\d+)\)", todo)
            tarea = actual.group(1) if actual else ""
            if rol == "arquitecto":
                return terminar_xml(self.PLAN)
            if rol == "implementador":
                if tarea == "1":
                    return herramienta_xml("write_to_file", path="conversor.py", content=completo) \
                        if turno == 0 else terminar_xml("conversor.py con las dos funciones")
                if tarea == "3":
                    return herramienta_xml("write_to_file", path="extra.py", content="def nada():\n    return 1\n") \
                        if turno == 0 else terminar_xml("extra.py listo")
                return terminar_xml("f_a_c ya estaba implementada por la tarea anterior; no hay nada que cambiar")
            return terminar_xml("ok")

        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=1, juez=False)
        ws = self.proyecto()
        informe = Orquestador(MockLLM(guion), ws, ajustes, self.ui()).construir("conversor", confirmar=False)
        self.assertEqual(informe.tareas_fallidas, [], informe.notas)
        self.assertEqual(informe.tareas_bloqueadas, [])
        self.assertTrue(ws.existe("extra.py"))                          # la 3 se construyó, no quedó bloqueada
        self.assertTrue(informe.ok, informe.notas)


class TestOpenRouterRealCatalogoGratis(BaseTest):
    CATALOGO = [
        {"id": "anthropic/caro", "pricing": {"prompt": "0.000003", "completion": "0.000015"}, "context_length": 200000},
        {"id": "openrouter/free", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 200000},
        {"id": "google/lyria-3-pro-preview", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "nvidia/nemotron-3.5-content-safety:free", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "liquid/lfm-2.5-2.6b:free", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 65536},
        {"id": "nvidia/nemotron-3-super-120b-a12b:free", "pricing": {"prompt": "0", "completion": "0"},
         "context_length": 262144, "supported_parameters": ["tools"]},
        {"id": "cohere/north-mini-code:free", "pricing": {"prompt": "0", "completion": "0"},
         "context_length": 256000, "supported_parameters": ["tools"]},
        {"id": "google/gemma-4-31b-it:free", "pricing": {"prompt": 0, "completion": 0}, "context_length": 262144},
        {"id": "img/solo-imagen:free", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"output_modalities": ["image"]}},
    ]

    def test_elige_solo_gratis_de_texto_que_sirven_para_programar(self):
        self.assertEqual(elegir_free_de_catalogo(self.CATALOGO),
                         ["cohere/north-mini-code:free",                  # código + tools primero
                          "nvidia/nemotron-3-super-120b-a12b:free",       # tools
                          "google/gemma-4-31b-it:free"])                 # nada pago, de música, router ni 2.6B

    def test_perfil_gratis_usa_el_catalogo_real(self):
        s = Settings(proveedor="openrouter")
        cambios = aplicar_perfil(s, "gratis", ["a/uno:free", "b/dos:free", "c/tres:free"])
        self.assertEqual(s.modelo, "a/uno:free")
        self.assertEqual(s.fallbacks, ["b/dos:free", "c/tres:free"])
        self.assertTrue(any("catálogo real" in c for c in cambios))

    def test_perfil_gratis_sin_red_no_usa_el_modelo_retirado(self):
        s = Settings(proveedor="openrouter")
        aplicar_perfil(s, "gratis")
        self.assertNotIn("dolphin", s.modelo)                            # dolphin…:free ya no existe
        self.assertTrue(s.modelo.endswith(":free"))

    def test_sin_red_no_consulta_y_con_cache_no_sale_a_internet(self):
        self.assertEqual(catalogo_free_openrouter(), [])                 # los autotests corren con REAPER_SIN_RED
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / "openrouter_free.json").write_text(json.dumps({"ts": time.time(), "ids": ["x/y:free"]}),
                                                        encoding="utf-8")
        previa = os.environ.pop("REAPER_SIN_RED", None)
        try:
            self.assertEqual(catalogo_free_openrouter(timeout=0.01), ["x/y:free"])   # de la caché, sin red
        finally:
            if previa is not None:
                os.environ["REAPER_SIN_RED"] = previa

    def test_403_solo_disponible_en_otro_cliente_se_retira(self):
        self.assertTrue(_RE_MODELO_RETIRADO.search(
            "Acceso denegado HTTP 403. thinkingmachines/inkling:free is only available on agentic harnesses."))
        self.assertFalse(_RE_MODELO_RETIRADO.search("Acceso denegado HTTP 403. moderation flagged the input"))

    def test_modelo_que_expira_baja_de_prioridad(self):
        catalogo = [{"id": "a/code-viejo:free", "pricing": {"prompt": "0", "completion": "0"},
                     "expiration_date": "2026-11-01"},
                    {"id": "b/general:free", "pricing": {"prompt": "0", "completion": "0"}}]
        self.assertEqual(elegir_free_de_catalogo(catalogo), ["b/general:free", "a/code-viejo:free"])


class TestOpenRouterRealEspecificacion(BaseTest):
    VACIO = ("import subprocess, sys, unittest\n\n\nclass T(unittest.TestCase):\n"
             "    def test_error(self):\n"
             "        r = subprocess.run([sys.executable, '-m', 'conversor'], capture_output=True, text=True)\n"
             "        self.assertNotEqual(r.returncode, 0)\n\n"
             "    def test_valor(self):\n        from conversor import c_a_f\n        self.assertEqual(c_a_f(100), 212.0)\n")
    ESTRICTO = VACIO.replace("self.assertNotEqual(r.returncode, 0)",
                             "self.assertIn('ValueError', r.stderr)\n        self.assertIn('cero absoluto', r.stderr)")

    def test_tests_que_pasan_sin_codigo_se_mandan_a_ajustar(self):
        pedidos = []

        def guion(mensajes, kw):
            if MockLLM.rol_de(mensajes) != "especificador":
                return terminar_xml("ok")
            primero = next(m["content"] for m in mensajes if m["role"] == "user")
            if _turno(mensajes) == 0:
                pedidos.append(primero)
                contenido = self.ESTRICTO if "YA PASAN" in primero else self.VACIO
                return herramienta_xml("write_to_file", path="tests/test_cli.py", content=contenido)
            return terminar_xml("tests listos")

        ui = self.ui()
        ws = self.proyecto()
        orq = Orquestador(MockLLM(guion), ws, self.ajustes(), ui)
        plan = Plan(objetivo="conversor", criterios=["c_a_f(100) == 212.0"],
                    tareas=[Tarea("1", "Implementar conversor.py", ["conversor.py"])])
        espec = orq.especificar("conversor", plan, ws.checkpoints.iniciar("construir"))
        self.assertEqual(len(pedidos), 2)                                # se le pidió ajustar una vez
        self.assertIn("YA pasan sin que exista el código", ui.texto_registrado())
        self.assertIn("ValueError", espec["tests/test_cli.py"])          # la versión protegida es la estricta

    def test_en_un_proyecto_existente_no_se_toca(self):
        # Si el código del plan ya existe, que algunos tests pasen es normal (funcionalidad previa).
        pedidos = []

        def guion(mensajes, kw):
            if MockLLM.rol_de(mensajes) == "especificador" and _turno(mensajes) == 0:
                pedidos.append(1)
                previo_y_nuevo = ("import unittest\n\n\nclass T(unittest.TestCase):\n"
                                  "    def test_lo_que_ya_habia(self):\n        from conversor import otra\n"
                                  "        self.assertEqual(otra(), 1)\n\n"
                                  "    def test_lo_nuevo(self):\n        from conversor import c_a_f\n"
                                  "        self.assertEqual(c_a_f(100), 212.0)\n")
                return herramienta_xml("write_to_file", path="tests/test_cli.py", content=previo_y_nuevo)
            return terminar_xml("ok")

        ws = self.proyecto({"conversor.py": "def otra():\n    return 1\n"})
        orq = Orquestador(MockLLM(guion), ws, self.ajustes(), self.ui())
        plan = Plan(objetivo="conversor", criterios=[], tareas=[Tarea("1", "Agregar c_a_f", ["conversor.py"])])
        orq.especificar("conversor", plan, ws.checkpoints.iniciar("construir"))
        conteo = conteo_de_resultado(ejecutar_tests(ws, timeout=60, completo=True))
        self.assertEqual((conteo.pasados, conteo.ok), (1, False))      # uno pasa legítimamente (código previo)
        self.assertEqual(len(pedidos), 1)                                # y aun así no se lo manda a "corregir"


class TestOpenRouterRealMargenRazonamiento(BaseTest):
    def test_tras_ver_un_modelo_pensando_los_pedidos_cortos_tienen_margen(self):
        # Con alternativa se cambia de modelo enseguida, pero REAPER aprende: desde ahí los pedidos cortos
        # (el juez pide ~350 tokens) salen con margen y razonamiento corto, para que el siguiente no falle igual.
        pagos = []
        pensando = {"choices": [{"delta": {"reasoning": "pienso... " * 30}, "finish_reason": "length"}]}
        base = transporte_falso([pensando, "ok", "otra"])

        def transporte(url, headers, payload, timeout):
            pagos.append(dict(payload))
            return base(url, headers, payload, timeout)

        c = LLMClient("clave", self.ajustes(reintentos=0, rpm=0, fallbacks=["otro/modelo:free"]),
                      url="http://falso", transporte=transporte)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}], max_tokens=350).texto, "ok")
        self.assertEqual(pagos[0]["max_tokens"], 350)
        self.assertGreaterEqual(pagos[1]["max_tokens"], 2048)            # el respaldo ya va con margen
        c.chat([{"role": "user", "content": "y"}], max_tokens=350)
        self.assertGreaterEqual(pagos[2]["max_tokens"], 2048)            # y los pedidos siguientes también


class TestOpenRouterRealTareaSinArchivos(BaseTest):
    PLAN = """<plan>
<objetivo>Sumadora</objetivo>
<interfaz>
- calc.py: def sumar(a, b) -> int
</interfaz>
<tarea id="1" archivos="calc.py">Crear calc.py con def sumar(a, b).</tarea>
<tarea id="2" archivos="" deps="1">Repasar que la implementación cumpla la interfaz pedida.</tarea>
<criterios>
- sumar(2, 3) == 5
</criterios>
</plan>"""

    def _construir(self, tests_pasan=True):
        def guion(mensajes, kw):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
            todo = "\n".join(m["content"] for m in mensajes if m["role"] == "user")
            actual = re.search(r"TU TAREA AHORA \(#(\d+)\)", todo)
            if rol == "arquitecto":
                return terminar_xml(self.PLAN)
            if rol == "implementador" and actual and actual.group(1) == "1":
                cuerpo = "return a + b" if tests_pasan else "return a - b"
                return herramienta_xml("write_to_file", path="calc.py", content=f"def sumar(a, b):\n    {cuerpo}\n") \
                    if turno == 0 else terminar_xml("calc.py listo")
            return terminar_xml("revisado: cumple la interfaz")

        ws = self.proyecto({"tests/test_calc.py": "import unittest\nfrom calc import sumar\n\n\nclass T(unittest.TestCase):\n"
                                                  "    def test_suma(self):\n        self.assertEqual(sumar(2, 3), 5)\n"})
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=1, juez=False)
        return Orquestador(MockLLM(guion), ws, ajustes, self.ui()).construir("sumadora", confirmar=False)

    def test_tarea_sin_archivos_que_termina_limpia_no_falla(self):
        # Build real 4: "- ejecutar las pruebas…" sin archivos → SIN CAMBIOS → 3 reparaciones → PARCIAL con todo OK.
        informe = self._construir(tests_pasan=True)
        self.assertEqual(informe.tareas_fallidas, [], informe.notas)
        self.assertTrue(informe.ok, informe.notas)

    def test_si_la_suite_falla_no_se_regala_nada(self):
        informe = self._construir(tests_pasan=False)                    # sumar resta: la suite falla
        self.assertFalse(informe.ok)
