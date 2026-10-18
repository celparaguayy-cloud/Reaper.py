"""
Autotests de modelos :free de OpenRouter que no sirven (casos reales del teléfono):

- cohere/north-mini-code:free pensaba 25 000 caracteres sin responder, o devolvía vacías;
- nemotron: solo razonamiento, "Upstream error from Nvidia: Internal server error", "Upstream idle timeout exceeded";
- cohere: 429 "limited to 15 requests per minute";
- el juez eligió un modelo que no respondía;
- a una tarea se le acabó el tiempo en medio de los reintentos.

Objetivo: perder el mínimo de tiempo y de pedidos en los que no sirven, y usar los que sí responden.
"""


def _error_429_zp(cuerpo: str, cabeceras: Optional[dict] = None) -> Exception:
    try:
        _lanzar_http(429, cuerpo, None, cabeceras or {})
    except (_Transitorio, LLMError) as e:
        return e
    raise AssertionError("no lanzó")


_HERRAMIENTA_OK_ZP = "<read_file>\n<path>REAPER_OK.txt</path>\n</read_file>"


class TestModelosGratisSinPerderPedidos(BaseTest):
    def _cliente(self, eventos, **ajustes):
        pedidos, esperas = [], []
        base = transporte_falso(eventos)

        def transporte(url, headers, payload, timeout):
            pedidos.append(payload.get("model"))
            return base(url, headers, payload, timeout)
        valores = dict(rpm=0, respaldo_equipo=False)
        valores.update(ajustes)
        c = LLMClient("clave", self.ajustes(**valores), url="http://falso", transporte=transporte)
        c.dormir = esperas.append
        return c, pedidos, esperas

    # ------------------------------------------------------------ límite propio de cada modelo (429)
    def test_lee_el_limite_por_minuto_del_429(self):
        cuerpo = json.dumps({"error": {"code": 429, "message": "High demand for cohere/north-mini-code:free on "
                                                              "OpenRouter - limited to 15 requests per minute"}})
        self.assertEqual(limite_por_minuto(cuerpo), 15)
        minuto = {"X-RateLimit-Limit": "20", "X-RateLimit-Reset": str(int((time.time() + 30) * 1000))}
        self.assertEqual(limite_por_minuto("{}", minuto), 20)
        dia = {"X-RateLimit-Limit": "50", "X-RateLimit-Reset": str(int((time.time() + 6 * 3600) * 1000))}
        self.assertIsNone(limite_por_minuto("{}", dia))                     # el cupo diario no es por minuto
        self.assertIsNone(limite_por_minuto('{"error": {"message": "Rate limit exceeded"}}'))
        error = _error_429_zp(cuerpo)
        self.assertIsInstance(error, _Transitorio)
        self.assertEqual(error.limite_rpm, 15)

    def test_el_limite_aprendido_se_respeta_en_los_pedidos_siguientes(self):
        cuerpo = json.dumps({"error": {"message": "limited to 3 requests per minute"}})
        c, pedidos, esperas = self._cliente([_error_429_zp(cuerpo), "uno", "dos", "tres"],
                                            modelo="a/pago", fallbacks=[], reintentos=1)
        reloj = [1000.0]
        c.limitador._reloj = lambda: reloj[0]

        def dormir(segundos):
            esperas.append(segundos)
            reloj[0] += segundos
        c.dormir = dormir
        self.assertEqual(c.chat([{"role": "user", "content": "1"}]).texto, "uno")
        self.assertEqual(c._limitador_de("a/pago").rpm, 2)                     # 3 por minuto, con 1 de margen
        esperas.clear()
        self.assertEqual(c.chat([{"role": "user", "content": "2"}]).texto, "dos")
        self.assertEqual(esperas, [])                                          # 2.º del minuto: entra
        self.assertEqual(c.chat([{"role": "user", "content": "3"}]).texto, "tres")
        self.assertGreater(sum(esperas), 50)                                   # 3.º del minuto: espera su turno
        self.assertEqual(pedidos, ["a/pago"] * 4)

    def test_429_por_minuto_de_un_free_pasa_al_siguiente_y_no_lo_marca_caido(self):
        cuerpo = json.dumps({"error": {"message": "limited to 15 requests per minute"}})
        c, pedidos, esperas = self._cliente([_error_429_zp(cuerpo), "ok"], modelo="a/uno:free",
                                            fallbacks=["b/dos:free"], reintentos=3)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual((pedidos, esperas), (["a/uno:free", "b/dos:free"], []))
        self.assertEqual(c._limitador_de("a/uno:free").rpm, 14)
        self.assertIsNone(c.disyuntor.sospechoso("a/uno:free"))               # un límite no es una caída

    # ------------------------------------------------------------ reintentos y plazos
    def test_free_inestable_cede_al_siguiente_sin_esperar(self):
        c, pedidos, esperas = self._cliente(
            [_Transitorio("Upstream error from Nvidia: Internal server error HTTP 502.", espera=5), "ok"],
            modelo="a/uno:free", fallbacks=["b/dos:free"], reintentos=3)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual(pedidos, ["a/uno:free", "b/dos:free"])               # antes: 4 intentos con espera
        self.assertEqual(esperas, [])
        self.assertIn("Nvidia", c.disyuntor.sospechoso("a/uno:free"))

    def test_el_ultimo_del_equipo_si_reintenta(self):
        c, pedidos, esperas = self._cliente([_Transitorio("Upstream idle timeout exceeded", espera=1), "ok"],
                                            modelo="a/uno:free", fallbacks=[], reintentos=2)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual(pedidos, ["a/uno:free", "a/uno:free"])
        self.assertEqual(sum(esperas), 1)

    def test_no_empieza_un_reintento_que_no_entra_en_el_plazo(self):
        c, pedidos, esperas = self._cliente([_Transitorio("Servidor ocupado HTTP 503.", espera=30), "tarde"],
                                            modelo="a/pago", fallbacks=[], reintentos=3)
        with PLAZO.limitar(20, "la tarea 1"):
            with self.assertRaises(LLMError) as ctx:
                c.chat([{"role": "user", "content": "x"}])
        self.assertIn("no reintento", str(ctx.exception))
        self.assertIn("plazo", str(ctx.exception))
        self.assertEqual((pedidos, esperas), (["a/pago"], []))                # ni espera ni pedido de más

    def test_si_fallan_todos_el_mensaje_dice_que_paso_con_cada_uno(self):
        c, pedidos, _ = self._cliente([_Transitorio("Upstream error from Nvidia: Internal server error"),
                                       _Transitorio("Upstream idle timeout exceeded")],
                                      modelo="a/uno:free", fallbacks=["b/dos:free"], reintentos=0)
        with self.assertRaises(LLMError) as ctx:
            c.chat([{"role": "user", "content": "x"}])
        texto = str(ctx.exception)
        self.assertTrue(texto.startswith("Ningún modelo del equipo respondió"), texto)
        for parte in ("a/uno:free", "Nvidia", "b/dos:free", "idle timeout"):
            self.assertIn(parte, texto)
        self.assertEqual(pedidos, ["a/uno:free", "b/dos:free"])

    def test_el_resumen_conserva_el_cupo_diario(self):
        cupo = _error_429_zp(json.dumps({"error": {"message": "Rate limit exceeded: free-models-per-day"}}),
                             {"X-RateLimit-Remaining": "0",
                              "X-RateLimit-Reset": str(int((time.time() + 6 * 3600) * 1000))})
        c, _, _ = self._cliente([_Transitorio("Servidor ocupado HTTP 503."), cupo],
                                modelo="a/pago", fallbacks=["b/uno:free"], reintentos=0)
        with self.assertRaises(LLMError) as ctx:
            c.chat([{"role": "user", "content": "x"}])
        self.assertIn("Ningún modelo del equipo respondió", str(ctx.exception))
        self.assertTrue(ctx.exception.cupo_diario)                            # /grande se detiene limpio igual

    def test_corta_el_razonamiento_desbocado_sin_esperar_al_final(self):
        pedidos, leidos = [], []

        def transporte(url, headers, payload, timeout):
            pedidos.append(payload.get("model"))
            if payload.get("model") == "b/ok:free":
                yield from transporte_falso(["ok"])(url, headers, payload, timeout)
                return
            for i in range(60):                                                # 120 000 caracteres pensando
                leidos.append(i)
                yield "data: " + json.dumps({"choices": [{"delta": {"reasoning": "x" * 2000}}]})
            yield "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "length"}]})
            yield "data: [DONE]"
        c = LLMClient("clave", self.ajustes(modelo="a/piensa:free", fallbacks=["b/ok:free"], rpm=0,
                                            respaldo_equipo=False), url="http://falso", transporte=transporte)
        c.dormir = lambda s: None
        c._nivel_razonamiento["a/piensa:free"] = "none"                       # ya se le pidió no pensar
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual(pedidos, ["a/piensa:free", "b/ok:free"])
        self.assertLess(len(leidos), 15)                                       # cortado a los ~16 000

    # ------------------------------------------------------------ salud de modelos (24 h)
    def test_salud_se_guarda_y_vence_a_las_24h(self):
        ruta = self.dir / "salud.json"
        guardar_salud_modelos({"a/uno:free": "vacías"}, ruta)
        self.assertEqual(cargar_salud_modelos(ruta), {"a/uno:free": "vacías"})
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["a/uno:free"]["ts"] = time.time() - 25 * 3600
        ruta.write_text(json.dumps(datos), encoding="utf-8")
        self.assertEqual(cargar_salud_modelos(ruta), {})                      # vencido
        guardar_salud_modelos({"a/uno:free": "vacías", "b/dos:free": "502"}, ruta)
        viejo = json.loads(ruta.read_text(encoding="utf-8"))["a/uno:free"]["ts"]
        self.assertLess(viejo, time.time() - 24 * 3600)                       # guardar otro no lo renueva
        guardar_salud_modelos({"a/uno:free": "vacías otra vez"}, ruta, renovar=("a/uno:free",))
        self.assertIn("a/uno:free", cargar_salud_modelos(ruta))               # volvió a fallar: 24 h más
        self.assertIsNone(_ruta_salud_modelos())                              # en autotests no se toca CACHE_DIR

    def test_la_proxima_corrida_empieza_por_el_que_anduvo(self):
        ruta = self.dir / "salud_corridas.json"
        g = globals()
        original = g["_ruta_salud_modelos"]
        g["_ruta_salud_modelos"] = lambda: ruta
        try:
            primera, pedidos1, _ = self._cliente([_Transitorio("Upstream error from Nvidia: Internal server error"),
                                                  "ok"], modelo="a/uno:free", fallbacks=["b/dos:free"],
                                                 reintentos=3)
            self.assertEqual(primera.chat([{"role": "user", "content": "x"}]).texto, "ok")
            self.assertEqual(pedidos1, ["a/uno:free", "b/dos:free"])
            segunda, pedidos2, _ = self._cliente(["ok"], modelo="a/uno:free", fallbacks=["b/dos:free"],
                                                 reintentos=3)
            self.assertEqual(segunda.chat([{"role": "user", "content": "y"}]).texto, "ok")
            self.assertEqual(pedidos2, ["b/dos:free"])                        # antes: otra vez por el caído
            tercera, _, _ = self._cliente(["anda"], modelo="a/uno:free", fallbacks=[], reintentos=0)
            self.assertEqual(tercera.chat([{"role": "user", "content": "z"}]).texto, "anda")
            self.assertEqual(cargar_salud_modelos(ruta), {})                  # respondió: se olvida
        finally:
            g["_ruta_salud_modelos"] = original

    def test_el_juez_no_elige_modelos_que_fallaron(self):
        variables = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY",
                     "REAPER_CLAVE_PROVEEDOR")
        respaldo = {k: os.environ.pop(k, None) for k in variables}
        os.environ["OPENROUTER_API_KEY"] = "x"
        try:
            s = self.ajustes(modelo="venice", modelos_rol={"revisor": "deepseek"})
            disyuntor = DisyuntorModelos()
            disyuntor.salud_previa = {resolver_modelo("venice"): "no respondió el sondeo: vacía"}
            cambios, motivos = asignar_equipo_juez(s, None, disyuntor)
            self.assertEqual(cambios.get("qa"), resolver_modelo("deepseek"))
            self.assertTrue(any("falló hace poco" in m for m in motivos), motivos)
            disyuntor.salud_previa = {}
            disyuntor.salud_sesion = {resolver_modelo("venice"): "no respondió el sondeo"}   # sondeo de HOY
            self.assertFalse(modelo_sano(s, resolver_modelo("venice"), disyuntor)[0])
        finally:
            for k, v in respaldo.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_doctor_muestra_los_modelos_caidos(self):
        ruta = self.dir / "salud_doctor.json"
        self.assertIsNone(_chequeo_salud_modelos(ruta))
        guardar_salud_modelos({"cohere/north-mini-code:free": "solo razonamiento"}, ruta)
        chequeo = _chequeo_salud_modelos(ruta)
        self.assertIn("cohere/north-mini-code:free", chequeo.detalle)
        self.assertFalse(chequeo.critico)

    # ------------------------------------------------------------ sondeo con herramienta
    @staticmethod
    def _llm_sondeo(respuestas: dict):
        def responder(mensajes, kw):
            r = respuestas.get(kw.get("modelo"), "no sé")
            if isinstance(r, Exception):
                raise r
            return r
        llm = MockLLM(responder)
        llm.marcas = {}
        llm._marcar_salud = lambda m, motivo: llm.marcas.__setitem__(m, motivo)
        llm._limpiar_salud = lambda m: llm.marcas.pop(m, None)
        return llm

    def test_sondeo_distingue_herramientas_texto_y_falla(self):
        llm = self._llm_sondeo({"h": _HERRAMIENTA_OK_ZP, "t": "REAPER_OK", "f": LLMError("respuesta vacía")})
        self.assertEqual(sondear_modelo(llm, "h")["estado"], "HERRAMIENTAS")
        self.assertEqual(sondear_modelo(llm, "t")["estado"], "TEXTO")
        self.assertEqual(sondear_modelo(llm, "f")["estado"], "FALLA")
        self.assertEqual(sondear_modelo(llm, "x")["estado"], "FALLA")
        self.assertTrue(all(k.get("reintentos") == 0 and k.get("sin_respaldo") for k in llm.llamadas))

    def test_free_que_responden_pone_primero_los_que_usan_herramientas(self):
        llm = self._llm_sondeo({"t/texto:free": "REAPER_OK", "c/caido:free": LLMError("Upstream idle timeout"),
                                "h/herr:free": _HERRAMIENTA_OK_ZP})
        vivos = free_que_responden(llm, ["t/texto:free", "c/caido:free", "h/herr:free"], cuantos=2)
        self.assertEqual(vivos, ["h/herr:free", "t/texto:free"])              # antes: en orden de catálogo
        self.assertIn("no respondió el sondeo", llm.marcas["c/caido:free"])   # el juez no lo va a elegir

    def test_free_que_responden_no_gasta_cupo_de_mas(self):
        llm = self._llm_sondeo({m: _HERRAMIENTA_OK_ZP for m in ("a:free", "b:free", "c:free", "d:free")})
        self.assertEqual(free_que_responden(llm, ["a:free", "b:free", "c:free", "d:free"], cuantos=2),
                         ["a:free", "b:free"])
        self.assertEqual(len(llm.llamadas), 2)                                # 1 pedido por modelo, corta a tiempo

    # ------------------------------------------------------------ perfil gratis
    def test_perfil_gratis_sin_torneo_y_con_mas_tiempo(self):
        s = self.ajustes(torneo=True, candidatos=3)
        aplicar_perfil(s, "gratis", ["a/uno:free", "b/dos:free"])
        # Con modelos gratis flojos, 2 candidatos duplicaban pedidos (y cupo diario) sin mejorar el resultado.
        self.assertEqual((s.torneo, s.candidatos, s.rpm), (False, 1, 14))
        self.assertGreaterEqual(s.tiempo_max_tarea, 2400)
