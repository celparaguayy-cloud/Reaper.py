"""
Autotests de preparación para una prueba GRANDE con modelos gratis de OpenRouter (límites publicados: 20 pedidos por
minuto; 50 por día sin crédito comprado, 1000 con al menos 10 de crédito; 429 con X-RateLimit-* al pasarse).

- Un 429 de cupo DIARIO se reintentaba como si fuera pasajero y se probaban los otros :free (que comparten el cupo).
- /grande no sabía cuántos pedidos le quedaban ni avisaba antes; un corte por límite contaba como intento fallido.
"""


def _cupo_agotado(reinicio_segundos: float = 6 * 3600) -> LLMError:
    try:
        _lanzar_http(429, json.dumps({"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day. "
                                                                        "Add 10 credits to unlock 1000"}}),
                     None, {"X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(int((time.time() + reinicio_segundos) * 1000))})
    except LLMError as e:
        return e
    raise AssertionError("no lanzó")


class TestCupoDiarioOpenRouter(BaseTest):
    def _cliente(self, eventos, **ajustes):
        pedidos = []
        base = transporte_falso(eventos)

        def transporte(url, headers, payload, timeout):
            pedidos.append(payload.get("model"))
            return base(url, headers, payload, timeout)
        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte)
        c.dormir = lambda s: self.fail(f"no debía esperar {s}s")
        return c, pedidos

    def test_detecta_cupo_diario_y_no_el_limite_por_minuto(self):
        e = _cupo_agotado()
        self.assertTrue(e.cupo_diario and e.detiene_todo)
        self.assertIn("Se renueva", str(e))
        self.assertIn("50 por día", str(e))
        minuto = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int((time.time() + 40) * 1000))}
        self.assertEqual(es_cupo_diario(429, '{"error": {"message": "Rate limit exceeded"}}', minuto), (False, None))
        self.assertFalse(es_cupo_diario(503, "free-models-per-day", None)[0])            # solo un 429 es cupo
        with self.assertRaises(_Transitorio):                                           # el de minuto se reintenta
            _lanzar_http(429, '{"error": {"message": "Rate limit exceeded"}}', "3", minuto)

    def test_saltea_los_free_y_usa_otro_modelo_sin_reintentar(self):
        c, pedidos = self._cliente([_cupo_agotado(), "ok"], modelo="a/uno:free", reintentos=4, rpm=0,
                                   fallbacks=["b/dos:free", "c/pago"], respaldo_equipo=False)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual(pedidos, ["a/uno:free", "c/pago"])                             # b/dos:free ni se intenta
        self.assertTrue(c.cupo_free_agotado())

    def test_sin_alternativa_falla_al_instante_y_sin_red(self):
        c, pedidos = self._cliente([_cupo_agotado()], modelo="a/uno:free", reintentos=4, rpm=0,
                                   fallbacks=["b/dos:free"], respaldo_equipo=False)
        with self.assertRaises(LLMError) as ctx:
            c.chat([{"role": "user", "content": "x"}])
        self.assertTrue(ctx.exception.cupo_diario)
        self.assertEqual(pedidos, ["a/uno:free"])
        with self.assertRaises(LLMError) as ctx2:                                       # ahora sin tocar la red
            c.chat([{"role": "user", "content": "y"}])
        self.assertTrue(ctx2.exception.cupo_diario)
        self.assertEqual(pedidos, ["a/uno:free"])

    def test_el_cupo_vuelve_cuando_se_renueva(self):
        c, _ = self._cliente([], modelo="a/uno:free")
        c.cupo_free_hasta = time.time() - 1
        self.assertFalse(c.cupo_free_agotado())

    def test_las_fases_opcionales_no_se_tragan_el_cupo(self):
        llm = MockLLM(lambda m, k: (_ for _ in ()).throw(_cupo_agotado()))
        orq = Orquestador(llm, self.proyecto({}), self.ajustes(), self.ui())
        with self.assertRaises(LLMError):
            orq._consultar_rol_x("juez", "x")                                           # antes: "sigo sin su dictamen"

    def test_cuenta_y_estimacion(self):
        cuenta = interpretar_cuenta_openrouter({"data": {"is_free_tier": True, "free_model_daily_requests":
                                                         {"used": 12, "limit": 50, "remaining": 38}}})
        self.assertEqual((cuenta.sin_credito, cuenta.cupo_dia, cuenta.quedan_hoy), (True, 50, 38))
        self.assertIn("quedan 38", cuenta.resumen())
        self.assertEqual(interpretar_cuenta_openrouter({"data": {"is_free_tier": False}}).cupo_dia, 1000)
        self.assertIsNone(cuenta_openrouter(None))
        sin_torneo = estimar_pedidos_grande(5, self.ajustes(torneo=False))
        con_torneo = estimar_pedidos_grande(5, self.ajustes(torneo=True, candidatos=3))
        self.assertLess(sin_torneo[1], con_torneo[1])
        self.assertGreater(sin_torneo[0], 50)                                           # 5 etapas no entran en 50

    def test_doctor_muestra_el_cupo(self):
        g = globals()
        original = g["cuenta_openrouter"]
        g["cuenta_openrouter"] = lambda clave, **k: CuentaOpenRouter(True, 50, 45, 5)
        os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-0123456789abcdef0123"
        try:
            chequeo = _chequeo_cuenta_openrouter(self.ajustes(proveedor="openrouter", modelo="a/uno:free"))
        finally:
            g["cuenta_openrouter"] = original
            os.environ.pop("OPENROUTER_API_KEY", None)
        self.assertFalse(chequeo.ok)
        self.assertIn("quedan 5", chequeo.detalle)
        self.assertIn("1000 por día", chequeo.ayuda)
        self.assertIsNone(_chequeo_cuenta_openrouter(self.ajustes(modelo="a/pago")))     # no es :free: no consulta


class TestGrandeConLimites(BaseTest):
    def _ajustes(self, **extra):
        valores = dict(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                       max_reparaciones=1, juez=False, git_snapshots=False)
        valores.update(extra)
        return self.ajustes(**valores)

    def _grande(self, error, veces=1, **ajustes):
        """Proyecto biblioteca cuyo modelo tira `error` en la PRIMERA llamada del implementador de la etapa 2."""
        ws = self.proyecto({})
        guion = _GuionBiblioteca(ws)
        restantes = [veces]

        def responder(mensajes, kw):
            primero = next((m["content"] for m in mensajes if m["role"] == "user"), "")
            if (MockLLM.rol_de(mensajes) == "implementador" and "(E2)" in primero and restantes[0] > 0
                    and _turno(mensajes) == 0):
                restantes[0] -= 1
                raise error
            return guion(mensajes, kw)
        ui = self.ui()
        grande = ConstructorGrande(MockLLM(responder), ws, self._ajustes(**ajustes), ui)
        esperas = []
        grande.dormir = esperas.append
        grande.consultar_cuenta = lambda: None
        return ws, grande, ui, esperas

    def test_limite_pasajero_espera_y_sigue_solo(self):
        _ws, grande, ui, esperas = self._grande(
            LLMError("Todos los modelos están en enfriamiento o retirados (a:abierto)."))
        self.assertTrue(grande.iniciar("Un gestor de biblioteca con préstamos y CLI", confirmar=False),
                        ui.texto_registrado()[-2000:])
        self.assertEqual(esperas, [ESPERAS_LIMITE[0]])
        etapas = {e["id"]: e for e in grande.leer()["maestro"]["etapas"]}
        self.assertEqual(etapas["2"]["intentos"], 1)                                # el corte no contó
        self.assertIn("Espero 2m", ui.texto_registrado())

    def test_cupo_diario_lejano_se_detiene_limpio_y_despues_sigue(self):
        ws, grande, ui, esperas = self._grande(_cupo_agotado(6 * 3600))
        self.assertFalse(grande.iniciar("Un gestor de biblioteca con préstamos y CLI", confirmar=False))
        self.assertEqual(esperas, [])                                               # 6 h: no se queda esperando
        estado = grande.leer()
        etapas = {e["id"]: e for e in estado["maestro"]["etapas"]}
        self.assertEqual(estado["estado"], "detenido")
        self.assertIn("cupo diario", estado["motivo"])
        self.assertEqual(etapas["2"]["intentos"], 0)
        self.assertIsNotNone(RegistroBuild(ws).leer())                             # la build quedó para retomar
        self.assertIn("--grande continuar", ui.texto_registrado())
        self.assertTrue(grande.continuar())                                         # "al otro día"

    def test_cupo_que_se_renueva_pronto_espera_hasta_la_renovacion(self):
        _ws, grande, _ui, esperas = self._grande(_cupo_agotado(5 * 60))
        self.assertTrue(grande.iniciar("Un gestor de biblioteca con préstamos y CLI", confirmar=False))
        self.assertEqual(len(esperas), 1)
        self.assertTrue(300 <= esperas[0] <= 340)

    def test_sin_esperas_si_el_usuario_las_apaga(self):
        _ws, grande, _ui, esperas = self._grande(LLMError("HTTP 503 overloaded"), espera_limites_min=0)
        self.assertFalse(grande.iniciar("Un gestor de biblioteca con préstamos y CLI", confirmar=False))
        self.assertEqual(esperas, [])

    def test_cuenta_chica_avisa_y_ahorra_pedidos_solo_en_esta_corrida(self):
        ws = self.proyecto({})
        ui = self.ui()
        ajustes = self._ajustes(torneo=True, candidatos=2, max_revisiones=1)
        grande = ConstructorGrande(MockLLM(_GuionBiblioteca(ws)), ws, ajustes, ui)
        grande.consultar_cuenta = lambda: CuentaOpenRouter(True, 50, 40, 10)
        visto = {}
        real = grande._construir_build

        def espiar(pedido, reanudar, usuario):
            visto.setdefault("torneo", ajustes.torneo)
            visto.setdefault("revisiones", ajustes.max_revisiones)
            return real(pedido, reanudar, usuario)
        grande._construir_build = espiar
        self.assertTrue(grande.iniciar("Un gestor de biblioteca con préstamos y CLI", confirmar=False))
        texto = ui.texto_registrado()
        self.assertIn("Pedidos estimados al modelo", texto)
        self.assertIn("no alcanza", texto)
        self.assertIn("Ahorro de pedidos", texto)
        self.assertEqual(visto, {"torneo": False, "revisiones": 0})                 # durante la corrida
        self.assertEqual((ajustes.torneo, ajustes.max_revisiones), (True, 1))      # tu config, intacta después
        self.assertTrue(all(e["pedidos"] > 0 for e in grande.leer()["maestro"]["etapas"]))

    def test_plan_maestro_con_formatos_de_modelos_reales(self):
        texto = ('```xml\n<maestro><vision>v</vision><architecture>arq</architecture>\n'
                 '<stage id="E1" title="Base" depends="none"><objective>datos</objective>'
                 '<files>a.py, tests/test_a.py</files></stage>\n'
                 '<stage id="E2" title="Ventas" depends="E1"><objective>ventas</objective></stage>\n'
                 '<etapa id="3" titulo="CLI" deps="etapa 2, 1"><objetivo>cli</objetivo></etapa>\n'
                 '<etapa id="4" titulo="Web" deps="1 3"><objetivo>web</objetivo></etapa></maestro>\n```')
        m = parsear_maestro(texto)
        self.assertEqual([(e.id, e.deps) for e in m.etapas],
                         [("E1", []), ("E2", ["E1"]), ("3", ["E2", "E1"]), ("4", ["E1", "3"])])
        self.assertEqual(m.arquitectura, "arq")
        self.assertEqual(problemas_maestro(m, 10), [])

    def test_plan_maestro_cortado_se_detecta(self):
        m = parsear_maestro('<etapa id="1"><objetivo>a</objetivo></etapa><etapa id="2"><objetivo>b, y se cor')
        self.assertTrue(m.cortado)
        self.assertEqual(len(m.etapas), 1)                                          # la 2 se perdía en silencio
        self.assertTrue(any("CORTÓ" in p for p in problemas_maestro(m, 10)))


class TestReporteParaMejorar(BaseTest):
    def test_reporte_incluye_lo_util_y_nunca_claves(self):
        clave = "sk-or-v1-" + "0123456789abcdef" * 3
        ws = self.proyecto({"app.py": f"API = '{clave}'\ndef f():\n    return 1\n",
                            ".env": f"OPENROUTER_API_KEY={clave}\n", "deploy/server.key": "-----BEGIN KEY-----\n",
                            "tests/test_app.py": "import unittest\n"})
        (ws.carpeta_reaper() / "informes").mkdir(parents=True, exist_ok=True)
        (ws.carpeta_reaper() / "informes" / "build_1.md").write_text("# Build REAPER — fallida\n", encoding="utf-8")
        ConstructorGrande(None, ws, Settings(), None).guardar(
            {"esquema": 1, "pedido": "un almacén", "estado": "detenido", "motivo": "cupo diario"},
            parsear_maestro(_GuionBiblioteca.MAESTRO))
        destino = Path(self.dir) / "salida"
        ruta, incluidos = armar_reporte(ws, self.ajustes(), destino=destino, con_doctor=False)
        with zipfile.ZipFile(ruta) as z:
            nombres = z.namelist()
            todo = "\n".join(z.read(n).decode("utf-8", "replace") for n in nombres)
        self.assertIn("proyecto/app.py", nombres)
        self.assertIn("reaper/informes/build_1.md", nombres)
        self.assertIn("reaper/proyecto_grande.json", nombres)
        self.assertNotIn("proyecto/.env", nombres)
        self.assertNotIn("proyecto/deploy/server.key", nombres)
        self.assertNotIn("0123456789abcdef0123456789abcdef", todo)                  # ni dentro del código
        self.assertIn("/grande: detenido · 0/3 etapas", todo)
        self.assertIn("motivo de parada: cupo diario", todo)
        sin, _ = armar_reporte(ws, self.ajustes(), destino=destino, con_codigo=False, con_doctor=False)
        with zipfile.ZipFile(sin) as z:
            self.assertFalse(any(n.startswith("proyecto/") for n in z.namelist()))
            self.assertIn("arbol.txt", z.namelist())

    def test_comando_reporte(self):
        app = App(self.ajustes(), MockLLM([]), self.ui(), self.proyecto({"a.py": "x = 1\n"}), persistir=False)
        g = globals()
        original = g["armar_reporte"]
        g["armar_reporte"] = lambda ws, s, **k: (Path(self.dir) / "r.zip", ["a"])
        try:
            app.cmd_reporte("")
        finally:
            g["armar_reporte"] = original
        self.assertIn("Reporte listo", app.ui.texto_registrado())

    def test_sondeo_de_gratis_se_recuerda(self):
        cache = Path(self.dir) / "vivos.json"
        llamadas = []

        def responder(m, k):
            llamadas.append(k.get("modelo"))
            return "REAPER_OK" if k.get("modelo") == "b/ok:free" else "no"
        llm = MockLLM(responder)
        self.assertEqual(free_vivos(llm, ["a/no:free", "b/ok:free"], cache=cache), ["b/ok:free"])
        antes = len(llamadas)
        self.assertEqual(free_vivos(llm, ["a/no:free", "b/ok:free"], cache=cache), ["b/ok:free"])
        self.assertEqual(len(llamadas), antes)                                      # sin gastar cupo otra vez
        free_vivos(llm, ["a/no:free", "b/ok:free"], cache=cache, refrescar=True)
        self.assertGreater(len(llamadas), antes)
        free_vivos(llm, ["c/otro:free"], cache=cache)                               # catálogo distinto: sondea
        self.assertIn("c/otro:free", llamadas)


def _error_400(mensaje: str) -> LLMError:
    try:
        _lanzar_http(400, json.dumps({"error": {"code": 400, "message": mensaje}}), None, {})
    except LLMError as e:
        return e
    raise AssertionError("no lanzó")


_SOLO_RAZONA = {"choices": [{"delta": {"reasoning": "pienso y pienso " * 50}, "finish_reason": "length"}]}


class TestModelosDeLaPruebaRealGrande(BaseTest):
    """Primera prueba REAL de /grande en Termux: el juez apuntaba a un ID inexistente (400 en cada pedido antes del
    respaldo) y cohere/north-mini-code:free pensaba 25 000 caracteres sin responder en cada pedido."""

    def _cliente(self, eventos, **ajustes):
        pedidos = []
        base = transporte_falso(eventos)

        def transporte(url, headers, payload, timeout):
            pedidos.append((payload.get("model"), (payload.get("reasoning") or {}).get("effort")))
            return base(url, headers, payload, timeout)
        c = LLMClient("clave", self.ajustes(**ajustes), url="http://falso", transporte=transporte)
        c.dormir = lambda s: None
        return c, pedidos

    def test_id_de_modelo_invalido_se_retira_al_primer_intento(self):
        c, pedidos = self._cliente([_error_400("x/invalido is not a valid model ID"), "ok", "otra vez"],
                                   modelo="x/invalido", fallbacks=["b/ok"], respaldo_equipo=False, rpm=0)
        self.assertEqual(c.chat([{"role": "user", "content": "1"}]).texto, "ok")
        self.assertEqual(c.chat([{"role": "user", "content": "2"}]).texto, "otra vez")
        self.assertEqual([m for m, _ in pedidos], ["x/invalido", "b/ok", "b/ok"])     # no se lo vuelve a intentar
        self.assertNotIn("contexto demasiado largo", str(_error_400("x is not a valid model ID")))

    def test_modelo_que_solo_piensa_baja_el_razonamiento_y_despues_se_deja(self):
        eventos = [_SOLO_RAZONA, "r1", _SOLO_RAZONA, "r2", _SOLO_RAZONA, "r3", "r4"]
        c, pedidos = self._cliente(eventos, modelo="a/piensa:free", fallbacks=["b/ok:free"],
                                   respaldo_equipo=False, rpm=0)
        for esperado in ("r1", "r2", "r3", "r4"):
            self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, esperado)
        del_que_piensa = [efecto for m, efecto in pedidos if m == "a/piensa:free"]
        self.assertEqual(del_que_piensa, [None, "low", "none"])                  # y a la 4.ª ya no se lo usa

    def test_razonamiento_obligatorio_rechaza_none_y_se_usa_minimal(self):
        c, pedidos = self._cliente([_error_400("Reasoning is mandatory for this endpoint and cannot be disabled."),
                                    "ok"], modelo="a/piensa:free", fallbacks=[], respaldo_equipo=False, rpm=0)
        c._nivel_razonamiento["a/piensa:free"] = "none"
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual(pedidos, [("a/piensa:free", "none"), ("a/piensa:free", "minimal")])

    def test_perfil_gratis_no_deja_roles_en_modelos_que_no_son_gratis(self):
        s = self.ajustes(proveedor="openrouter", modelos_rol={"juez": "nanogpt:qwen/qwen3.8-27b-uncensored",
                                                              "reparador": "nvidia/nemotron-3-super-120b-a12b:free"})
        cambios = aplicar_perfil(s, "gratis", ["a/uno:free", "b/dos:free"])
        self.assertEqual(s.modelos_rol, {"reparador": "nvidia/nemotron-3-super-120b-a12b:free"})
        self.assertTrue(any("juez: nanogpt:qwen" in c for c in cambios))

    def test_restricciones_no_son_criterios_sin_cubrir(self):
        plan = Plan("x", [Tarea("1", "Crear storage.py con init_db y sus tests", ["almacen/storage.py"])], [])
        sin = cobertura_criterios(["Todo el código utiliza únicamente la biblioteca estándar de Python",
                                   "No se incluyen todavía módulos de CRUD", "Existe un endpoint /api/ventas"], plan)
        self.assertEqual(sin, ["Existe un endpoint /api/ventas"])
