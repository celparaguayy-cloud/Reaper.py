"""
Autotest interno: `python3 reaper_v7.py --autotest` verifica REAPER sin gastar API.

Todo corre en un entorno aislado (REAPER_HOME temporal), con UI silenciosa y
MockLLM. Los tests que necesitan node, git o go se saltean si no están.
Filtrar: REAPER_AUTOTEST=parser python3 reaper_v7.py --autotest
"""

_RUTAS_GLOBALES = ("BASE_DIR", "PROJECTS_DIR", "CHECKPOINTS_DIR", "SESIONES_DIR", "LOGS_DIR", "CACHE_DIR",
                   "PLANTILLAS_USUARIO_DIR", "CONFIG_FILE", "ESTADO_FILE", "LECCIONES_GLOBALES", "HISTORIAL_FILE",
                   "ESTADISTICAS_FILE")


class entorno_aislado:
    """Redirige todas las rutas de REAPER a una carpeta temporal (y las restaura al salir)."""

    def __init__(self, base: Path):
        self.base = Path(base)
        self._previas: dict = {}
        self._env_previo: dict = {}

    def __enter__(self) -> "entorno_aislado":
        g = globals()
        nuevas = {
            "BASE_DIR": self.base,
            "PROJECTS_DIR": self.base / "proyectos",
            "CHECKPOINTS_DIR": self.base / "checkpoints",
            "SESIONES_DIR": self.base / "sesiones",
            "LOGS_DIR": self.base / "logs",
            "CACHE_DIR": self.base / "cache",
            "PLANTILLAS_USUARIO_DIR": self.base / "plantillas",
            "CONFIG_FILE": self.base / "config.json",
            "ESTADO_FILE": self.base / "estado.json",
            "LECCIONES_GLOBALES": self.base / "lecciones.md",
            "HISTORIAL_FILE": self.base / "historial_repl.txt",
            "ESTADISTICAS_FILE": self.base / "estadisticas.json",
        }
        for nombre in _RUTAS_GLOBALES:
            self._previas[nombre] = g[nombre]
            g[nombre] = nuevas[nombre]
        for variable, valor in (("REAPER_TMP", str(self.base / "tmp")), ("REAPER_SIN_ANIMACION", "1")):
            self._env_previo[variable] = os.environ.get(variable)
            os.environ[variable] = valor
        (self.base / "tmp").mkdir(parents=True, exist_ok=True)
        asegurar_dirs()
        return self

    def __exit__(self, *exc) -> None:
        g = globals()
        for nombre, valor in self._previas.items():
            g[nombre] = valor
        for variable, valor in self._env_previo.items():
            if valor is None:
                os.environ.pop(variable, None)
            else:
                os.environ[variable] = valor
        with _LOCK_INDICES:
            _INDICES.clear()
        with _LOCK_MAPAS:
            _MAPAS.clear()


class BaseTest(unittest.TestCase):
    maxDiff = 4000

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="reaper_autotest_")
        self.dir = Path(self._tmp.name)
        self.entorno = entorno_aislado(self.dir / "home")
        self.entorno.__enter__()
        CANCELAR.clear()

    def tearDown(self) -> None:
        CANCELAR.clear()
        self.entorno.__exit__(None, None, None)
        self._tmp.cleanup()

    # ------------------------------------------------------------ fábricas
    def proyecto(self, archivos: Optional[dict] = None, nombre: str = "proy") -> Workspace:
        raiz = self.dir / nombre
        raiz.mkdir(parents=True, exist_ok=True)
        for rel, contenido in (archivos or {}).items():
            ruta = raiz / rel
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(textwrap.dedent(contenido).lstrip("\n") if contenido.startswith("\n") else contenido,
                            encoding="utf-8")
        return Workspace(raiz, checkpoints_dir=self.dir / f"ck_{nombre}")

    def ui(self, respuestas: Optional[list] = None, interactivo: bool = False) -> UI:
        return UI(silencioso=True, interactivo=interactivo, respuestas=respuestas)

    def ajustes(self, **valores) -> Settings:
        base = {"modo": "auto", "paralelo": 1, "torneo": False, "tests_primero": False, "escalar": False,
                "rpm": 0, "max_pasos": 12, "max_pasos_sub": 10, "reintentos": 0, "animacion": False,
                "git_snapshots": False, "max_revisiones": 0, "qa": False, "autofix_ruff": False}
        base.update(valores)
        return Settings.desde_dict(base)

    def contexto(self, ws: Workspace, **valores) -> Contexto:
        return Contexto(ws, self.ajustes(**valores), self.ui(), "test")

    def herramienta(self, ctx: Contexto, nombre: str, **params) -> str:
        return REGISTRO[nombre].fn(ctx, params)


# ======================================================================
# UI y dragón
# ======================================================================
class TestUI(BaseTest):
    def test_registro_silencioso(self):
        ui = self.ui()
        ui.ok("listo")
        ui.error("falló")
        texto = ui.texto_registrado()
        self.assertIn("✓ listo", texto)
        self.assertIn("✗ falló", texto)

    def test_confirmar_con_respuestas(self):
        ui = self.ui(respuestas=["s", "no", True])
        self.assertTrue(ui.confirmar("¿?"))
        self.assertFalse(ui.confirmar("¿?"))
        self.assertTrue(ui.confirmar("¿?"))
        self.assertTrue(ui.confirmar("¿?", defecto=True))  # sin respuestas y no interactivo → defecto

    def test_elegir(self):
        self.assertEqual(self.ui(respuestas=["2"]).elegir("x", ["a", "b", "c"]), 2)
        self.assertEqual(self.ui().elegir("x", ["a", "b"], defecto=1), 1)

    def test_ancho_visible_y_ajustar(self):
        self.assertEqual(ancho_visible("\033[92mhola\033[0m"), 4)
        self.assertEqual(ancho_visible("日本"), 4)
        self.assertEqual(ancho_visible(ajustar("abcdef", 4)), 4)
        self.assertEqual(ajustar("ab", 4), "ab  ")

    def test_caja_y_tabla(self):
        dibujo = sin_ansi(caja(["uno", "dos"], titulo="T"))
        lineas = dibujo.splitlines()
        self.assertEqual(len({ancho_visible(l) for l in lineas}), 1)
        tab = sin_ansi(tabla([["a", "1"], ["bb", "22"]], ["col", "n"], "lr"))
        self.assertIn("col", tab)
        self.assertIn("22", tab)

    def test_barra(self):
        self.assertIn("50%", sin_ansi(barra(5, 10)))
        self.assertIn("100%", sin_ansi(barra(20, 10)))

    def test_markdown(self):
        lineas = [sin_ansi(l) for l in renderizar_markdown("# Título\n- [x] hecho\n```py\nx = 1\n```\ntexto **negrita**")]
        self.assertTrue(any("Título" in l for l in lineas))
        self.assertTrue(any("x = 1" in l for l in lineas))
        self.assertTrue(any("negrita" in l for l in lineas))

    def test_resaltar_sin_color_no_cambia(self):
        if _USAR_COLOR:
            self.skipTest("la terminal tiene color")
        self.assertEqual(resaltar_codigo("def f(): pass", "py"), "def f(): pass")

    def test_hex_y_degradado(self):
        self.assertEqual(hex_a_rgb("#ff8000"), (255, 128, 0))
        self.assertEqual(hex_a_rgb("fff"), (255, 255, 255))
        with self.assertRaises(ValueError):
            hex_a_rgb("zz")
        self.assertEqual(sin_ansi(degradado("abc", (0, 0, 0), (255, 255, 255))), "abc")

    def test_formatos(self):
        self.assertEqual(formatear_duracion(0.5), "500ms")
        self.assertEqual(formatear_duracion(75), "1m15s")
        self.assertEqual(formatear_numero(1500), "1.5k")
        self.assertEqual(recortar("a" * 100, 20).count("recortado"), 1)

    def test_temas(self):
        for nombre in TEMAS:
            self.assertEqual(aplicar_tema(nombre), nombre)
        self.assertEqual(aplicar_tema("inexistente"), "dragon")


class TestDragon(BaseTest):
    def test_tamanos(self):
        for ancho in (28, 40, 60, 104):
            pixeles = pintar_dragon(ancho)
            self.assertEqual(len(pixeles[0]), ancho)
            opacos = sum(1 for fila in pixeles for p in fila if p)
            self.assertGreater(opacos, ancho * len(pixeles) * 0.15, f"dragón casi vacío a {ancho}")

    def test_tiene_los_colores_del_dragon(self):
        pixeles = pintar_dragon(80)
        colores = {p for fila in pixeles for p in fila if p}
        azules = [c for c in colores if c[2] > c[0] + 40]
        naranjas = [c for c in colores if c[0] > 200 and 80 < c[1] < 200 and c[2] < 120]
        self.assertTrue(azules and naranjas)

    def test_render_y_ascii(self):
        pixeles = pintar_dragon(40)
        self.assertEqual(len(renderizar_pixeles(pixeles)), (len(pixeles) + 1) // 2)
        ascii_ = renderizar_ascii(pixeles)
        self.assertTrue(any(l.strip() for l in ascii_))

    def test_banner_y_logo(self):
        texto = sin_ansi(banner_dragon(60))
        self.assertIn("v" + __version__, texto)
        self.assertEqual(len(logo_texto("REAPER")), 3)

    def test_animacion_sin_tty_no_anima(self):
        self.assertFalse(animar_intro(salida=io.StringIO()))

    def test_png(self):
        ruta = dragon_png(self.dir / "d.png", ancho=32, escala=2)
        datos = ruta.read_bytes()
        self.assertTrue(datos.startswith(b"\x89PNG"))
        self.assertGreater(len(datos), 200)

    def test_alas_y_fuego_cambian_el_dibujo(self):
        quieto = pintar_dragon(50)
        self.assertNotEqual(quieto, pintar_dragon(50, alas=0.8))
        self.assertNotEqual(quieto, pintar_dragon(50, fuego=0.3))


# ======================================================================
# Config y tokens
# ======================================================================
class TestConfig(BaseTest):
    def test_guardar_y_cargar(self):
        s = Settings()
        s.paralelo = 3
        guardar_settings(s)
        self.assertEqual(cargar_settings().paralelo, 3)

    def test_desde_dict_ignora_basura(self):
        s = Settings.desde_dict({"paralelo": "tres", "candidatos": 99, "nada": 1, "torneo": False, "temperatura": 1})
        self.assertEqual(s.paralelo, 2)
        self.assertEqual(s.candidatos, 6)
        self.assertFalse(s.torneo)
        self.assertEqual(s.temperatura, 1.0)

    def test_validar(self):
        s = Settings()
        s.modo, s.temperaturas, s.max_pasos = "raro", ["x", 3, 0.2], 1
        s.validar()
        self.assertEqual((s.modo, s.temperaturas, s.max_pasos), ("auto-edicion", [2.0, 0.2], 3))

    def test_modelos_y_rpm(self):
        self.assertEqual(resolver_modelo("deepseek"), "deepseek/deepseek-chat")
        self.assertEqual(resolver_modelo("otro/modelo"), "otro/modelo")
        s = Settings(modelo=MODELOS["venice-free"])
        self.assertEqual(s.rpm_efectivo(), 16)
        s.rpm = 5
        self.assertEqual(s.rpm_efectivo(), 5)
        self.assertEqual(info_modelo("qwen3-coder").contexto, 262144)

    def test_temperaturas_de_candidatos(self):
        s = Settings()
        self.assertEqual([s.temperatura_candidato(i) for i in range(4)], [0.1, 0.4, 0.7, 0.85])

    def test_perfiles(self):
        s = Settings()
        cambios = aplicar_perfil(s, "gratis")
        self.assertIn("rpm=16", cambios)
        self.assertFalse(s.escalar)
        with self.assertRaises(KeyError):
            aplicar_perfil(s, "turbo")

    def test_settings_con_local(self):
        s = settings_con_local(Settings(), {"settings": {"candidatos": 2, "torneo": False}})
        self.assertEqual((s.candidatos, s.torneo), (2, False))

    def test_url_y_clave(self):
        s = Settings(proveedor="ollama")
        self.assertIn("11434", s.url_api())
        self.assertEqual(obtener_clave_api(s), "sin-clave")

    def test_estado(self):
        guardar_estado(proyecto="/x")
        self.assertEqual(cargar_estado()["proyecto"], "/x")


class TestTokens(BaseTest):
    def test_estimar(self):
        self.assertEqual(estimar_tokens(""), 0)
        self.assertGreater(estimar_tokens("def f(x):\n    return x + 1\n"), 5)
        self.assertGreater(estimar_tokens("a" * 30000), 9000)

    def test_presupuesto(self):
        p = Presupuesto(32768, 6000)
        mensajes = [{"role": "user", "content": "hola"}]
        self.assertTrue(p.cabe(mensajes))
        self.assertEqual(p.respuesta_posible(mensajes), 6000)
        grande = [{"role": "user", "content": "x " * 60000}]
        self.assertLess(p.respuesta_posible(grande), 6000)
        self.assertLessEqual(estimar_tokens(recortar_a_tokens("palabra " * 5000, 100)), 160)


# ======================================================================
# Cliente LLM (transporte falso)
# ======================================================================
class TestLLM(BaseTest):
    def cliente(self, eventos, **ajustes):
        s = self.ajustes(**ajustes)
        c = LLMClient("clave", s, url="http://falso", transporte=transporte_falso(eventos))
        c.dormir = lambda _s: None
        return c

    def test_streaming_y_uso(self):
        c = self.cliente(["Hola mundo, soy el modelo."])
        r = c.chat([{"role": "user", "content": "x"}], rol="principal")
        self.assertEqual(r.texto, "Hola mundo, soy el modelo.")
        self.assertEqual(r.finish_reason, "stop")
        self.assertEqual(c.uso.llamadas, 1)
        self.assertAlmostEqual(c.uso.costo, 0.0001)
        self.assertEqual(c.uso.por_rol["principal"]["llamadas"], 1)

    def test_reintenta_transitorios(self):
        c = self.cliente([_Transitorio("caída"), "ok"], reintentos=2)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ok")
        self.assertEqual(c.uso.reintentos, 1)

    def test_respaldo_de_modelo(self):
        c = self.cliente([LLMError("404", probar_otro_modelo=True), "desde el respaldo"], fallbacks=["qwen"])
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "desde el respaldo")
        self.assertEqual(c.uso.respaldos, 1)

    def test_error_no_recuperable(self):
        c = self.cliente([LLMError("401 clave inválida")], fallbacks=["qwen"])
        with self.assertRaises(LLMError):
            c.chat([{"role": "user", "content": "x"}])

    def test_error_en_streaming(self):
        c = self.cliente([{"error": {"message": "maximum context length exceeded", "code": 400}}])
        with self.assertRaises(LLMError) as cm:
            c.chat([{"role": "user", "content": "x"}])
        self.assertTrue(cm.exception.contexto_excedido)

    def test_respuesta_vacia_se_reintenta(self):
        c = self.cliente(["", "ahora sí"], reintentos=1)
        self.assertEqual(c.chat([{"role": "user", "content": "x"}]).texto, "ahora sí")

    def test_presupuesto(self):
        c = self.cliente(["a", "b"], costo_maximo=0.00005)
        c.chat([{"role": "user", "content": "x"}])
        with self.assertRaises(LLMError) as cm:
            c.chat([{"role": "user", "content": "x"}])
        self.assertTrue(cm.exception.presupuesto)

    def test_lanzar_http(self):
        with self.assertRaises(_Transitorio):
            _lanzar_http(429, "lento", "3")
        with self.assertRaises(LLMError) as cm:
            _lanzar_http(400, "This model's maximum context length is 32768 tokens", None)
        self.assertTrue(cm.exception.contexto_excedido)
        with self.assertRaises(LLMError) as cm:
            _lanzar_http(404, "no model", None)
        self.assertTrue(cm.exception.probar_otro_modelo)

    def test_parsear_sse(self):
        self.assertEqual(parsear_linea_sse("data: [DONE]"), "DONE")
        self.assertIsNone(parsear_linea_sse(": comentario"))
        self.assertEqual(parsear_linea_sse('data: {"a": 1}'), {"a": 1})
        self.assertIsNone(parsear_linea_sse("data: {roto"))

    def test_limitador(self):
        reloj = [0.0]
        esperas = []

        def dormir(s):
            esperas.append(s)
            reloj[0] += s

        lim = LimitadorTasa(2, reloj=lambda: reloj[0], dormir=dormir)
        lim.adquirir()
        lim.adquirir()
        self.assertGreater(lim.espera_necesaria(), 59)
        lim.adquirir()
        self.assertGreaterEqual(sum(esperas), 59)
        self.assertEqual(LimitadorTasa(0).adquirir(), 0.0)

    def test_payload_por_proveedor(self):
        s = self.ajustes(proveedor="openai")
        c = LLMClient("k", s, url="http://x", transporte=transporte_falso([]))
        p = c._payload("m", [{"role": "user", "content": "x"}], 0.3, 100, ["<resultado"])
        self.assertIn("stream_options", p)
        self.assertNotIn("usage", p)
        self.assertEqual(p["temperature"], 0.3)


# ======================================================================
# Protocolo
# ======================================================================
class TestProtocolo(BaseTest):
    def setUp(self):
        super().setUp()
        self.esq = esquemas()

    def test_xml_basico(self):
        a = analizar("Leo.\n<read_file>\n<path>a.py</path>\n</read_file>", self.esq)
        self.assertEqual(a.llamadas[0].nombre, "read_file")
        self.assertEqual(a.llamadas[0].params["path"], "a.py")
        self.assertEqual(a.texto, "Leo.")

    def test_alias_y_atajo(self):
        a = analizar("<cat>a.py</cat>", self.esq)
        self.assertEqual((a.llamadas[0].nombre, a.llamadas[0].params["path"]), ("read_file", "a.py"))
        a = analizar("<write_file><file>x.py</file><code>print(1)</code></write_file>", self.esq)
        self.assertEqual(a.llamadas[0].params, {"path": "x.py", "content": "print(1)"})

    def test_atributos_y_autocerrada(self):
        a = analizar('<read_file path="b.py"/>', self.esq)
        self.assertEqual(a.llamadas[0].params["path"], "b.py")
        a = analizar('<write_to_file path="c.py">\n<content>\nx = 1\n</content>\n</write_to_file>', self.esq)
        self.assertEqual(a.llamadas[0].params, {"path": "c.py", "content": "x = 1"})

    def test_invoke_parameter(self):
        texto = '<invoke name="read_symbol"><parameter name="symbol">Carrito.total</parameter></invoke>'
        a = analizar(texto, self.esq)
        self.assertEqual((a.llamadas[0].nombre, a.llamadas[0].params["symbol"]), ("read_symbol", "Carrito.total"))

    def test_estilo_llama(self):
        a = analizar('<function=read_file>{"path": "z.py"}</function>', self.esq)
        self.assertEqual(a.llamadas[0].params["path"], "z.py")

    def test_json_de_respaldo(self):
        a = analizar('```json\n{"tool": "list_files", "args": {"path": "src"}}\n```', self.esq)
        self.assertEqual((a.llamadas[0].nombre, a.llamadas[0].params["path"]), ("list_files", "src"))

    def test_codigo_con_etiquetas_adentro(self):
        html = "<html><body><path>no soy param</path></body></html>"
        a = analizar(f"<write_to_file>\n<path>i.html</path>\n<content>\n{html}\n</content>\n</write_to_file>", self.esq)
        self.assertEqual(a.llamadas[0].params["path"], "i.html")
        self.assertEqual(a.llamadas[0].params["content"], html)

    def test_cierre_content_dentro_del_codigo(self):
        contenido = "doc = '</content>'\nprint(doc)"
        a = analizar(f"<write_to_file><path>d.py</path><content>\n{contenido}\n</content></write_to_file>", self.esq)
        self.assertEqual(a.llamadas[0].params["content"], contenido)

    def test_incompleta_y_parcial(self):
        a = analizar("<write_to_file>\n<path>largo.py</path>\n<content>\nlinea1\nlinea2\nlin", self.esq)
        llamada = a.llamadas[0]
        self.assertFalse(llamada.completa)
        nombre, texto = contenido_parcial(llamada, self.esq)
        self.assertEqual(nombre, "content")
        self.assertTrue(texto.startswith("linea1"))

    def test_corta_resultados_inventados(self):
        a = analizar("<read_file><path>a</path></read_file>\n<resultado>inventado</resultado>", self.esq)
        self.assertNotIn("inventado", a.respuesta_limpia)

    def test_varias_llamadas_y_fence(self):
        texto = "<read_file><path>a</path></read_file>\n<read_file><path>b</path></read_file>"
        self.assertEqual([l.params["path"] for l in analizar(texto, self.esq).llamadas], ["a", "b"])
        self.assertEqual(limpiar_largo("\n```python\nx = 1\n```\n"), "x = 1")

    def test_herramientas_nuevas_alias(self):
        a = analizar("<replace_function><path>a.py</path><name>f</name><content>def f(): pass</content></replace_function>", self.esq)
        self.assertEqual(a.llamadas[0].nombre, "replace_symbol")
        self.assertEqual(a.llamadas[0].params["symbol"], "f")

    def test_sin_herramientas(self):
        a = analizar("Solo texto, sin herramientas.", self.esq)
        self.assertEqual(a.llamadas, [])


# ======================================================================
# Ediciones
# ======================================================================
class TestEdiciones(BaseTest):
    def test_exacto(self):
        nuevo, _ = aplicar_bloques("a\nb\nc\n", parsear_bloques("<<<<<<< SEARCH\nb\n=======\nB\n>>>>>>> REPLACE"))
        self.assertEqual(nuevo, "a\nB\nc\n")

    def test_ignorando_indentacion(self):
        original = "def f():\n    if x:\n        return 1\n"
        diff = "<<<<<<< SEARCH\nif x:\n    return 1\n=======\nif x:\n    return 2\n>>>>>>> REPLACE"
        nuevo, notas = aplicar_bloques(original, parsear_bloques(diff))
        self.assertEqual(nuevo, "def f():\n    if x:\n        return 2\n")
        self.assertTrue(notas)

    def test_ambiguo_y_no_encontrado(self):
        with self.assertRaises(ErrorEdicion):
            aplicar_bloques("x\nx\n", parsear_bloques("<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE"))
        with self.assertRaises(ErrorEdicion) as cm:
            aplicar_bloques("def calcular(a):\n    return a\n",
                            parsear_bloques("<<<<<<< SEARCH\ndef calcula(a):\n    return a\n=======\nz\n>>>>>>> REPLACE"))
        self.assertIn("parecidas", str(cm.exception))

    def test_ya_aplicado_y_numeros(self):
        original = "x = 1\ny = 2\nz = 3\n"
        diff = "<<<<<<< SEARCH\nx = 0\n=======\nx = 1\ny = 2\n>>>>>>> REPLACE"
        nuevo, notas = aplicar_bloques(original, parsear_bloques(diff))
        self.assertEqual(nuevo, original)
        self.assertIn("ya estaba aplicado", notas[0])
        bloques = parsear_bloques("<<<<<<< SEARCH\n    2| y = 2\n=======\n    2| y = 20\n>>>>>>> REPLACE")
        self.assertEqual(aplicar_bloques(original, bloques)[0], "x = 1\ny = 20\nz = 3\n")

    def test_marcadores_perezosos(self):
        self.assertTrue(tiene_marcadores_perezosos("    # ... resto del código"))
        self.assertTrue(tiene_marcadores_perezosos("// ... existing code"))
        self.assertIsNone(tiene_marcadores_perezosos("x = [1, 2, 3]  # lista"))

    def test_diff_unificado(self):
        original = "uno\ndos\ntres\ncuatro\n"
        diff = "--- a/x\n+++ b/x\n@@ -10,3 +10,3 @@\n dos\n-tres\n+TRES\n cuatro\n"
        self.assertTrue(parece_diff_unificado(diff))
        nuevo, _ = aplicar_diff_unificado(original, diff)
        self.assertEqual(nuevo, "uno\ndos\nTRES\ncuatro\n")
        with self.assertRaises(ErrorEdicion):
            aplicar_diff_unificado(original, "@@ -1 +1 @@\n-no existe\n+x\n")

    def test_lineas(self):
        texto = "a\nb\nc\n"
        self.assertEqual(reemplazar_lineas(texto, 2, 2, "B"), "a\nB\nc\n")
        self.assertEqual(insertar_despues(texto, 0, "cero"), "cero\na\nb\nc\n")
        self.assertEqual(insertar_despues(texto, 3, "d"), "a\nb\nc\nd\n")
        with self.assertRaises(ErrorEdicion):
            reemplazar_lineas(texto, 9, 10, "x")

    def test_continuacion_sin_duplicar(self):
        existente = "def f():\n    total = calcular_algo_largo()\n    return total\n"
        nuevo = "    return total\n\n\ndef g():\n    pass\n"
        unido, repetidas = unir_continuacion(existente, nuevo)
        self.assertEqual(repetidas, 1)
        self.assertEqual(unido.count("return total"), 1)
        self.assertIn("def g():", unido)
        self.assertEqual(cortar_en_linea_completa("a\nb\nmedia lin"), "a\nb\n")
        self.assertEqual(agregar_al_final("x", "y"), "x\ny\n")
