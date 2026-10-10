"""
Autotests del equipo resiliente (fallos reales vistos en Termux con 6 IAs en 3 proveedores):
  - un 413 "Request too large" de Groq en un rol abortaba todo /construir;
  - respuestas vacías / solo razonamiento de modelos :free gastaban ~30 s de reintentos y terminaban en error;
  - el especificador (tests primero) no podía cerrar porque sus tests importan módulos aún inexistentes;
  - pytest abortaba en la colección y el torneo veía "0 pasaron" en todos los candidatos;
  - rutas con basura del modelo ("src/db.py</script>");
  - "proveedor:modelo" para usar cualquier id en un proveedor concreto.
"""


class _BaseEquipo(BaseTest):
    _VARS = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "REAPER_CLAVE_PROVEEDOR")

    def setUp(self):
        super().setUp()
        self._env_bak = {k: os.environ.pop(k, None) for k in self._VARS}

    def tearDown(self):
        for k, v in self._env_bak.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def cliente_espia(self, eventos, **ajustes):
        base = transporte_falso(eventos)
        enviados = []

        def espia(url, headers, payload, timeout):
            enviados.append((url, payload["model"]))
            return base(url, headers, payload, timeout)

        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=espia)
        c.dormir = lambda _s: None
        return c, enviados


class TestRuteoProveedorExplicito(_BaseEquipo):
    def test_prefijo_proveedor(self):
        d = destino_modelo("groq:openai/gpt-oss-120b", self.ajustes())
        self.assertEqual((d.proveedor, d.modelo), ("groq", "openai/gpt-oss-120b"))
        self.assertIn("groq.com", d.url)

    def test_dos_puntos_del_id_no_son_prefijo(self):
        d = destino_modelo("deepseek/deepseek-r1:free", self.ajustes(proveedor="openrouter"))
        self.assertEqual((d.proveedor, d.modelo), ("openrouter", "deepseek/deepseek-r1:free"))
        d = destino_modelo("ollama:qwen2.5-coder:7b", self.ajustes())
        self.assertEqual((d.proveedor, d.modelo), ("ollama", "qwen2.5-coder:7b"))

    def test_payload_lleva_id_real(self):
        os.environ["GROQ_API_KEY"] = "gk"
        c, enviados = self.cliente_espia(["hola"])
        c.chat([{"role": "user", "content": "x"}], modelo="groq:openai/gpt-oss-120b", sin_respaldo=True)
        url, modelo = enviados[0]
        self.assertIn("groq.com", url)
        self.assertEqual(modelo, "openai/gpt-oss-120b")          # sin el prefijo de ruteo

    def test_alias_curado_con_prefijo_conserva_info(self):
        self.assertTrue(es_modelo_gratis("groq:llama-3.3-70b-versatile"))


class TestRespaldoEquipo(_BaseEquipo):
    MSG_413 = ("El pedido es demasiado grande. HTTP 413. Request too large for model `qwen/qwen3.8-27b` on "
               "tokens per minute (TPM): Limit 7000, Requested 8264, please reduce your message size")

    def test_413_prueba_otro_modelo(self):
        with self.assertRaises(LLMError) as cm:
            _lanzar_http(413, "Request too large ... please reduce your message size", None)
        self.assertTrue(cm.exception.probar_otro_modelo)

    def test_413_de_un_rol_pasa_a_otra_ia_del_equipo(self):
        os.environ["GROQ_API_KEY"] = "gk"
        os.environ["GEMINI_API_KEY"] = "gm"
        c, enviados = self.cliente_espia(
            [LLMError(self.MSG_413, probar_otro_modelo=True), "revisión hecha por otra IA"],
            modelos_rol={"revisor": "groq:qwen/qwen3.8-27b", "qa": "gemini-flash"})
        r = c.chat([{"role": "user", "content": "revisá"}], modelo=c.settings.modelo_para("revisor"), rol="revisor")
        self.assertEqual(r.texto, "revisión hecha por otra IA")
        self.assertEqual(enviados[0][1], "qwen/qwen3.8-27b")
        self.assertNotIn("groq.com", enviados[1][0])              # prefiere OTRO proveedor (límite de cuenta)
        self.assertEqual(c.uso.respaldos, 1)

    def test_respaldo_salta_ias_sin_clave(self):
        os.environ["GROQ_API_KEY"] = "gk"                          # gemini SIN clave
        c, enviados = self.cliente_espia(
            [LLMError(self.MSG_413, probar_otro_modelo=True), "desde el principal"],
            modelos_rol={"revisor": "groq:qwen/qwen3.8-27b", "qa": "gemini-flash"})
        r = c.chat([{"role": "user", "content": "x"}], modelo=c.settings.modelo_para("revisor"))
        self.assertEqual(r.texto, "desde el principal")
        self.assertFalse(any("googleapis" in u for u, _m in enviados))

    def test_respaldo_equipo_se_puede_apagar(self):
        os.environ["GROQ_API_KEY"] = "gk"
        c, _ = self.cliente_espia([LLMError(self.MSG_413, probar_otro_modelo=True), "no debería"],
                                  modelos_rol={"revisor": "groq:qwen/qwen3.8-27b"}, respaldo_equipo=False)
        with self.assertRaises(LLMError):
            c.chat([{"role": "user", "content": "x"}], modelo=c.settings.modelo_para("revisor"))

    def test_dos_vacias_pasan_a_otra_ia_sin_agotar_reintentos(self):
        os.environ["GROQ_API_KEY"] = "gk"
        c, enviados = self.cliente_espia(["", "", "respuesta de groq"], reintentos=4,
                                         modelos_rol={"qa": "groq-llama70"})
        r = c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(r.texto, "respuesta de groq")
        self.assertEqual(len(enviados), 3)                         # 2 vacías + 1 en otra IA (no 5 intentos)
        self.assertNotIn("groq.com", enviados[1][0])
        self.assertIn("groq.com", enviados[2][0])                  # la 3ª ya fue a OTRA IA, no un reintento

    def test_solo_razonamiento_es_error_distinto_y_cambia_de_ia(self):
        os.environ["GROQ_API_KEY"] = "gk"
        pensando = {"choices": [{"delta": {"reasoning": "Pienso mucho... " * 20}, "finish_reason": "length"}]}
        c, enviados = self.cliente_espia([pensando, "respuesta final"], modelos_rol={"qa": "groq-llama70"})
        r = c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(r.texto, "respuesta final")
        self.assertEqual(len(enviados), 2)
        self.assertIn("groq.com", enviados[1][0])                  # no reintentó el modelo que solo "piensa"

    def test_probe_cuenta_razonamiento_como_responde(self):
        os.environ["OPENROUTER_API_KEY"] = "ok"
        pensando = {"choices": [{"delta": {"reasoning": "hmm"}, "finish_reason": "length"}]}
        c, _ = self.cliente_espia([pensando])
        res = probar_equipo(c, c.settings)
        self.assertTrue(all(r["estado"] == "RESPONDE" for r in res), res)


class TestPipelineNoAbortaPorUnRol(_BaseEquipo):
    def test_revisor_caido_no_aborta_construir(self):
        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
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
            if rol == "revisor":
                raise LLMError("El pedido es demasiado grande. HTTP 413. Request too large", probar_otro_modelo=True)
            return terminar_xml("ok")

        ws = self.proyecto({"README.md": "# calc\n"})
        ajustes = self.ajustes(tests_primero=True, torneo=False, max_revisiones=1, lecciones=False)
        ui = self.ui()
        informe = Orquestador(MockLLM(guion), ws, ajustes, ui).construir("calculadora", confirmar=False)
        self.assertEqual(informe.estado, "verificada", informe.notas)  # antes: el 413 del revisor abortaba todo
        self.assertEqual(ws.leer("calc.py"), _CALC_BIEN)
        self.assertIn("revisor: el modelo no respondió", ui.texto_registrado())


class TestEspecificadorTDD(_BaseEquipo):
    def test_cierra_aunque_los_tests_importen_modulos_inexistentes(self):
        test = ("import sys\nsys.path.insert(0, 'src')\nfrom inventario import agregar\n\n\n"
                "def test_agregar():\n    assert agregar([], 1) == [1]\n")
        guion = [herramienta_xml("write_to_file", path="tests/test_inventario.py", content=test),
                 terminar_xml("Tests escritos: tests/test_inventario.py (fallan: falta src/inventario.py)")]
        ws = self.proyecto({})
        ui = self.ui()
        llm = MockLLM(guion)
        res = Agente("especificador", llm, ws, self.ajustes(), ui, memoria=None,
                     mostrar_progreso=False).ejecutar("escribí los tests de inventario. PLAN: src/inventario.py: "
                                                      "def agregar(lista, x) -> list")
        self.assertTrue(res.ok, res.resumen)
        self.assertNotIn("cierre rechazado", ui.texto_registrado())
        observado = "\n".join(m["content"] for m in llm.llamadas[-1]["mensajes"] if m["role"] == "user")
        self.assertIn("Creé tests/test_inventario.py", observado)
        self.assertNotIn("VALIDACIÓN FALLÓ", observado)            # escribir el test ya no se marca como error

    def test_otros_roles_siguen_marcando_imports_faltantes(self):
        msg = "Módulos no instalados ni presentes en el proyecto: x\n(Instalalos con pip o usá la librería estándar.)"
        resultados = [Resultado(False, "imports tests/test_x.py", 1, stderr=msg, archivo="tests/test_x.py"),
                      Resultado(False, "imports app.py", 1, stderr=msg, archivo="app.py")]
        quedan, tdd, _c = separar_imports_tdd(resultados, "PLAN: x.py: def f()")
        self.assertEqual([r.archivo for r in tdd], ["tests/test_x.py"])  # solo el de un archivo de test
        self.assertEqual([r.archivo for r in quedan], ["app.py"])         # un import roto en código sigue fallando


class TestPytestColeccion(_BaseEquipo):
    def test_completo_sigue_tras_errores_de_coleccion(self):
        ws = self.proyecto({"tests/test_a.py": "def test_a():\n    assert True\n"})
        original = importlib.util.find_spec
        importlib.util.find_spec = lambda nombre, *a, **k: object() if nombre == "pytest" else original(nombre, *a, **k)
        try:
            completo = detectar_comando_tests(ws, completo=True)[0]
            rapido = detectar_comando_tests(ws, completo=False)[0]
        finally:
            importlib.util.find_spec = original
        self.assertIn("--continue-on-collection-errors", completo)
        self.assertIn(" -x", rapido)

    def test_conteo_con_error_de_coleccion_no_es_ok(self):
        salida = "ERROR tests/test_api.py\n2 passed, 1 error in 0.02s\n"
        c = contar_tests(salida, 1)
        self.assertEqual((c.pasados, c.errores), (2, 1))   # progreso visible, pero la suite no está verde


class TestRutasSucias(BaseTest):
    def test_etiqueta_pegada_a_la_ruta(self):
        ws = self.proyecto({"src/db.py": "x = 1\n"})
        self.assertEqual(ws.ruta("src/db.py</script>"), ws.raiz / "src" / "db.py")
        self.assertEqual(ws.ruta("src/db.py</path>"), ws.raiz / "src" / "db.py")

    def test_ruta_normal_intacta(self):
        ws = self.proyecto({"a.py": ""})
        self.assertEqual(ws.ruta("a.py"), ws.raiz / "a.py")
