"""
Bugs que cazó la corrida de PUNTA A PUNTA de /grande contra un OpenRouter simulado por HTTP (pruebas_fusion/e2e/):
la CLI real, el transporte real con SSE, el perfil gratis y el pipeline entero (tests primero, torneo, revisor, juez).

- Desde la etapa 2, los tests de las etapas anteriores (que ya pasan) se contaban como "tests de la especificación
  que YA pasan sin el código" y el especificador tenía que reescribir tests buenos.
- Una revisión sin la línea VEREDICTO disparaba rondas de "corrección" sin nada que corregir (28 de 112 pedidos).
- Un test de JS que importa ../web/logica.js antes de que exista, o un index.html escrito antes que app.js, salían ✗.
- Cortada por el cupo diario (o Ctrl+C) en la fase "tests primero", QA o reparación, la build no se podía retomar:
  "Cambios externos o tareas ya verificadas alteradas" y /grande quedaba DETENIDO para siempre.
- Los diarios se guardan redactados: un pedido con "password: admin123" no se reconocía al retomar.
- El cupo diario también puede llegar como evento de error DENTRO del stream (HTTP 200).
"""

_E2E_TEST_DB = ("import unittest\n\nfrom almacen import db\n\n\nclass TestDb(unittest.TestCase):\n"
                "    def test_uno(self):\n        self.assertEqual(db.uno(), 1)\n\n"
                "    def test_dos(self):\n        self.assertEqual(db.uno() + 1, 2)\n\n"
                "    def test_tres(self):\n        self.assertTrue(db.uno())\n")
_E2E_TEST_VENTAS = ("import unittest\n\nfrom almacen.ventas import total\n\n\nclass TestVentas(unittest.TestCase):\n"
                    "    def test_total(self):\n        self.assertEqual(total([2, 3]), 5)\n")
_E2E_TEST_CALC = ("import unittest\n\nfrom calc import sumar\n\n\nclass TestCalc(unittest.TestCase):\n"
                  "    def test_sumar(self):\n        self.assertEqual(sumar(2, 3), 5)\n\n"
                  "    def test_negativos(self):\n        self.assertEqual(sumar(-2, -3), -5)\n")
_E2E_CALC = "def sumar(a, b):\n    return a + b\n"
_E2E_PLAN_CALC = ('<plan><objetivo>Calculadora</objetivo><criterios>- sumar funciona</criterios>'
                  '<tarea id="1" archivos="calc.py, tests/test_calc.py">sumar(a, b) con sus tests</tarea></plan>')


class TestEspecificadorEnProyectoConTests(BaseTest):
    def test_los_tests_que_ya_pasaban_no_cuentan_como_especificacion(self):
        ws = self.proyecto({"almacen/__init__.py": "", "almacen/db.py": "def uno():\n    return 1\n",
                            "tests/__init__.py": "", "tests/test_db.py": _E2E_TEST_DB})
        llamadas = []

        def guion(mensajes, kw):
            if MockLLM.rol_de(mensajes) == "especificador":
                llamadas.append(MockLLM.turnos_asistente(mensajes))
                if MockLLM.turnos_asistente(mensajes) == 0:
                    return herramienta_xml("write_to_file", path="tests/test_ventas.py", content=_E2E_TEST_VENTAS)
            return terminar_xml("tests escritos")
        ui = self.ui()
        orq = Orquestador(MockLLM(guion), ws, self.ajustes(tests_primero=True), ui)
        orq._base_tests = ejecutar_tests(ws, completo=True)
        self.assertTrue(orq._base_tests.ok)                                          # 3 tests viejos en verde
        plan = Plan("Ventas", [Tarea("1", "total(items)", ["almacen/ventas.py", "tests/test_ventas.py"])], [])
        espec = orq.especificar("Ventas del almacén", plan, ws.checkpoints.iniciar("espec"))
        texto = ui.texto_registrado()
        self.assertIn("tests/test_ventas.py", espec)
        self.assertNotIn("YA pasan", texto)
        self.assertEqual(llamadas, [0, 1])                                           # un solo especificador
        self.assertIn("3 ya pasaban de antes", texto)


class TestRevisionSinDictamen(BaseTest):
    def _build(self, revision: str):
        ws = self.proyecto({})
        impl = []

        def guion(mensajes, kw):
            rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
            if rol == "arquitecto":
                return terminar_xml(_E2E_PLAN_CALC)
            if rol == "implementador":
                if turno == 0:
                    impl.append(MockLLM.ultimo_usuario(mensajes))
                archivos = [("calc.py", _E2E_CALC), ("tests/test_calc.py", _E2E_TEST_CALC)]
                if turno < len(archivos):
                    return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
                return terminar_xml("listo, tests en verde")
            if rol == "revisor":
                return terminar_xml(revision)
            return terminar_xml("sin cambios")
        ui = self.ui()
        orq = Orquestador(MockLLM(guion), ws, self.ajustes(max_revisiones=2, juez=False), ui)
        informe = orq.construir("Una calculadora con sumar", confirmar=False)
        return informe, impl, ui.texto_registrado()

    def test_sin_veredicto_ni_observaciones_no_hay_ronda_vacia(self):
        informe, impl, texto = self._build("revisado: todo bien, sin cambios necesarios")
        self.assertTrue(informe.ok, texto[-2500:])
        self.assertEqual(len(impl), 1)                                               # antes: 1 + 1 corrección vacía
        self.assertIn("SIN VEREDICTO", texto)
        self.assertNotIn("Revisor pidió cambios", texto)

    def test_sin_veredicto_pero_con_puntos_concretos_se_pasan(self):
        informe, impl, texto = self._build("Observaciones:\n1. falta validar que a y b sean números")
        self.assertTrue(informe.ok, texto[-2500:])
        self.assertEqual(len(impl), 2)
        self.assertIn("falta validar que a y b sean números", impl[1])
        self.assertTrue(observaciones_concretas("- falta un test de negativos"))
        self.assertFalse(observaciones_concretas("Todo correcto, buen trabajo."))
        self.assertFalse(observaciones_concretas("1. Implementa sumar\n2. Tiene tests"))


class TestReferenciasAArchivosDelPlan(BaseTest):
    PLAN = ("[ ] 1. Lógica (T5a). [web/logica.js, tests/logica.test.mjs]\n"
            "[ ] 2. Página (T5b). [web/index.html, web/app.js, web/style.css]")

    def test_html_escrito_antes_que_su_js_y_css(self):
        ws = self.proyecto({"web/index.html": _GuionAlmacen.ARCHIVOS["web/index.html"]})
        quedan, pendientes = faltantes_planeados(ws, validar_archivos(ws, ["web/index.html"]), self.PLAN)
        self.assertEqual(fallos(quedan), [])
        self.assertEqual(sorted(pendientes), ["web/app.js", "web/style.css"])
        quedan, pendientes = faltantes_planeados(ws, validar_archivos(ws, ["web/index.html"]), "[web/index.html]")
        self.assertEqual([r.comando.split()[0] for r in fallos(quedan)], ["recursos-html"])   # fuera del plan: error
        self.assertEqual(pendientes, [])

    def test_escribir_el_html_no_sale_como_fallo(self):
        ws = self.proyecto({})
        ctx = self.contexto(ws)
        ctx.pedido = "TU TAREA AHORA (#2):\nPágina\n\nPLAN GENERAL:\n" + self.PLAN
        salida = self.herramienta(ctx, "write_to_file", path="web/index.html",
                                  content=_GuionAlmacen.ARCHIVOS["web/index.html"])
        self.assertNotIn("VALIDACIÓN FALLÓ", salida)
        self.assertIn("referencia archivos del plan que todavía no existen", salida)

    def test_test_de_js_que_importa_un_modulo_planeado_es_rojo_esperado(self):
        ws = self.proyecto({"tests/logica.test.mjs": _GuionAlmacen.ARCHIVOS["tests/logica.test.mjs"]})
        quedan, esperados, clases = separar_imports_tdd(validar_archivos(ws, ["tests/logica.test.mjs"]), self.PLAN, ws)
        self.assertEqual(fallos(quedan), [])
        self.assertEqual(len(esperados), 1)
        self.assertEqual([(c.modulo, c.causa) for c in clases], [("web/logica.js", "MODULO_PROPIO_AUSENTE")])
        quedan, esperados, _c = separar_imports_tdd(validar_archivos(ws, ["tests/logica.test.mjs"]), "[web/otro.js]", ws)
        self.assertEqual(len(fallos(quedan)), 1)                                     # no está en el plan: error real

    def test_run_tests_del_especificador_explica_el_modulo_js_que_falta(self):
        if not shutil.which("node"):
            self.skipTest("node no está instalado")
        ws = self.proyecto({"tests/logica.test.mjs": _GuionAlmacen.ARCHIVOS["tests/logica.test.mjs"]})
        ctx = self.contexto(ws)
        ctx.rol = "especificador"
        salida = run_tests(ctx, {})
        self.assertTrue(salida.startswith("ESPERADO (tests primero)"), salida[:400])
        self.assertIn("web/logica.js", salida)


class TestCupoDentroDelStream(BaseTest):
    def test_evento_de_error_con_cupo_diario_frena_sin_reintentar(self):
        evento = {"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day",
                            "metadata": {"headers": {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset":
                                                     str(int((time.time() + 5 * 3600) * 1000))}}}}
        c = LLMClient("clave", self.ajustes(modelo="a/uno:free", reintentos=3, fallbacks=[], respaldo_equipo=False),
                      url="http://falso", transporte=transporte_falso([evento, "no debía llegar acá"]))
        c.dormir = lambda s: self.fail(f"no debía esperar {s}s")
        with self.assertRaises(LLMError) as ctx:
            c.chat([{"role": "user", "content": "x"}])
        self.assertTrue(ctx.exception.cupo_diario)
        self.assertIn("Se renueva", str(ctx.exception))


_E2E_PLAN_SOLO_CODIGO = ('<plan><objetivo>Calculadora</objetivo><criterios>- sumar funciona</criterios>'
                         '<tarea id="1" archivos="calc.py">sumar(a, b)</tarea></plan>')


def _e2e_corte(rol_corte: str, turno_corte: int, plan: str = _E2E_PLAN_CALC, impl_tests: bool = False):
    """Guion de calculadora que tira el cupo diario UNA vez en `rol_corte`, turno `turno_corte`."""
    estado = {"cortado": False}
    escritos = [("calc.py", _E2E_CALC)] + ([("tests/test_calc.py", _E2E_TEST_CALC)] if impl_tests else [])

    def guion(mensajes, kw):
        rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
        if rol == rol_corte and turno == turno_corte and not estado["cortado"]:
            estado["cortado"] = True
            raise _cupo_agotado(6 * 3600)
        if rol == "arquitecto":
            return terminar_xml(plan)
        if rol in ("especificador", "qa"):
            if turno == 0:
                return herramienta_xml("write_to_file", path="tests/test_calc.py", content=_E2E_TEST_CALC)
            return terminar_xml("tests escritos")
        if rol == "implementador":
            if turno < len(escritos):
                return herramienta_xml("write_to_file", path=escritos[turno][0], content=escritos[turno][1])
            return terminar_xml("listo")
        return terminar_xml("sin cambios")
    return guion, estado


class TestCorteEnUnaFase(BaseTest):
    def _cortar_y_retomar(self, rol_corte: str, plan: str = _E2E_PLAN_CALC, **ajustes):
        ws = self.proyecto({})
        guion, estado = _e2e_corte(rol_corte, 1, plan=plan)
        llm = MockLLM(guion)
        with self.assertRaises(LLMError):
            Orquestador(llm, ws, self.ajustes(**ajustes), self.ui()).construir("Calculadora con sumar",
                                                                             confirmar=False)
        self.assertTrue(estado["cortado"])
        self.assertTrue(ws.existe("tests/test_calc.py"))                             # lo escrito antes del corte
        ui = self.ui()
        informe = Orquestador(llm, ws, self.ajustes(**ajustes), ui).construir("Calculadora con sumar",
                                                                            confirmar=False)
        texto = ui.texto_registrado()
        self.assertNotIn("Cambios externos", texto)
        self.assertIn("la retomo donde quedó", texto)
        self.assertTrue(informe.ok, texto[-2500:])
        return informe, texto

    def test_cortada_en_tests_primero_se_retoma_y_conserva_la_especificacion(self):
        informe, texto = self._cortar_y_retomar("especificador", tests_primero=True)
        self.assertEqual(informe.spec_tests, ["tests/test_calc.py"])
        self.assertNotIn("no dejó archivos de test", texto)

    def test_cortada_en_qa_se_retoma(self):
        # Sin tests primero y con un implementador que no escribe tests: corre la fase QA (de cierre).
        self._cortar_y_retomar("qa", plan=_E2E_PLAN_SOLO_CODIGO, qa=True)

    def test_pedido_con_algo_que_parece_una_clave_se_reconoce_al_retomar(self):
        self.assertTrue(mismo_pedido("login con password: [REDACTADO]", "login con  password: admin123"))
        self.assertTrue(mismo_pedido("hola mundo", " hola   mundo "))
        self.assertFalse(mismo_pedido("login con password: [REDACTADO]", "otra cosa"))
        ws = self.proyecto({})
        guion, _estado = _e2e_corte("implementador", 0, impl_tests=True)
        llm = MockLLM(guion)
        pedido = "Calculadora con sumar; el admin entra con password: admin123"
        with self.assertRaises(LLMError):
            Orquestador(llm, ws, self.ajustes(), self.ui()).construir(pedido, confirmar=False)
        self.assertNotIn("admin123", (ws.raiz / ".reaper" / "build_pendiente.json").read_text(encoding="utf-8"))
        ui = self.ui()
        self.assertTrue(Orquestador(llm, ws, self.ajustes(), ui).construir(pedido, confirmar=False).ok)
        self.assertIn("la retomo donde quedó", ui.texto_registrado())


class TestAvisosDeParada(BaseTest):
    def test_comando_para_seguir_conserva_el_perfil_gratis(self):
        ws = self.proyecto({})
        gratis = self.ajustes(modelo="cohere/north-mini-code:free")
        self.assertIn("--perfil gratis --grande continuar", comando_para_seguir(ws, "grande", gratis))
        self.assertNotIn("--perfil", comando_para_seguir(ws, "grande", self.ajustes(modelo="openai/gpt-pago")))
        self.assertNotIn("--perfil", comando_para_seguir(ws, "grande"))

    def test_la_caja_parte_las_lineas_largas_en_vez_de_cortarlas(self):
        motivo = ("Me detengo: se agotó el cupo diario de pedidos gratis. Se renueva mañana a las 07:48. " * 3).strip()
        dibujada = re.sub(r"\x1b\[[0-9;]*m", "", caja([motivo], "Proyecto grande · DETENIDO"))
        lineas = dibujada.splitlines()
        self.assertTrue(all(ancho_visible(l) <= ancho_terminal() for l in lineas))
        interior = " ".join(l.strip("│ ").strip() for l in lineas[1:-1])
        self.assertIn("Se renueva mañana a las 07:48.", interior)
        self.assertNotIn("…", interior)

    def test_cupo_diario_en_grande_muestra_la_hora_entera(self):
        ws = self.proyecto({})
        guion = _GuionAlmacen(ws)
        cortes = [1]

        def responder(mensajes, kw):
            if MockLLM.rol_de(mensajes) == "arquitecto" and cortes[0]:
                cortes[0] -= 1
                raise _cupo_agotado(6 * 3600)
            return guion(mensajes, kw)
        ui = self.ui()
        grande = ConstructorGrande(MockLLM(responder), ws, self.ajustes(juez=False), ui)
        grande.consultar_cuenta = lambda: None
        grande.dormir = lambda s: self.fail(f"no debía esperar {s}s")
        self.assertFalse(grande.iniciar(TestGrandeAlmacen.PEDIDO, confirmar=False))
        motivo = grande.leer()["motivo"]
        self.assertTrue(motivo.startswith("se agotó el cupo diario de pedidos gratis.\nSe renueva"), motivo)
        self.assertIn("Cuando se renueve el cupo", ui.texto_registrado())


class TestVerificacionDeTareaConSuEspecificacion(BaseTest):
    def test_el_test_propio_en_rojo_no_deja_la_tarea_verificada(self):
        # Modelo flojo: sumar resta. Antes el rojo de la especificación se toleraba entero ("es de tareas siguientes")
        # y la tarea única quedaba verificada; lo atajaba recién la verificación final.
        ws = self.proyecto({})
        pasos = []

        def guion(mensajes, kw):
            rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
            if turno == 0:
                pasos.append(rol)
            if rol == "arquitecto":
                return terminar_xml(_E2E_PLAN_CALC)
            if rol == "especificador" and turno == 0:
                return herramienta_xml("write_to_file", path="tests/test_calc.py", content=_E2E_TEST_CALC)
            if rol == "implementador" and turno == 0:
                return herramienta_xml("write_to_file", path="calc.py", content="def sumar(a, b):\n    return a - b\n")
            if rol == "reparador" and turno == 0:
                return herramienta_xml("write_to_file", path="calc.py", content=_E2E_CALC)
            return terminar_xml("listo")
        ui = self.ui()
        informe = Orquestador(MockLLM(guion), ws, self.ajustes(tests_primero=True, max_revisiones=1, juez=False),
                              ui).construir("Calculadora con sumar", confirmar=False)
        texto = ui.texto_registrado()
        self.assertTrue(informe.ok, texto[-2500:])
        self.assertIn("La tarea 1 no pasó su verificación", texto)
        self.assertLess(pasos.index("reparador"), pasos.index("revisor"))          # se repara ANTES de revisar
        self.assertNotIn("REPARACIÓN final", texto)
