"""Autotest: fetch_url, comandos propios, plugins, hooks, renombrado, prompts en inglés, estadísticas y comandos extra."""

import http.server as _http_server


class _ServidorDePrueba:
    """Servidor HTTP local con páginas fijas, para probar fetch sin internet."""

    PAGINAS = {
        "/doc": ("text/html; charset=utf-8",
                 "<html><head><title>Docs de prueba</title><style>x{}</style></head><body><nav>menú</nav>"
                 "<h1>Guía</h1><p>Primer párrafo sin nada.</p><p>Usá <code>row_factory</code> para filas como dict.</p>"
                 "<pre>con = sqlite3.connect('x.db')\ncon.row_factory = sqlite3.Row</pre>"
                 "<ul><li>uno</li><li>dos</li></ul><a href='/otra'>otra página</a><script>no()</script></body></html>"),
        "/api": ("application/json", '{"nombre": "reaper", "version": 7}'),
        "/texto": ("text/plain", "línea uno\nlínea dos"),
    }

    def __enter__(self):
        paginas = self.PAGINAS

        class Manejador(_http_server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                tipo, cuerpo = paginas.get(self.path, ("text/plain", "no existe"))
                datos = cuerpo.encode("utf-8")
                self.send_response(200 if self.path in paginas else 404)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

        self.servidor = _http_server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.base = f"http://127.0.0.1:{self.servidor.server_address[1]}"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.servidor.shutdown()
        self.servidor.server_close()


class TestWeb(BaseTest):
    def test_html_a_texto(self):
        titulo, texto = html_a_texto(_ServidorDePrueba.PAGINAS["/doc"][1], "https://x.org/")
        self.assertEqual(titulo, "Docs de prueba")
        self.assertIn("# Guía", texto)
        self.assertIn("`row_factory`", texto)
        self.assertIn("con.row_factory = sqlite3.Row", texto)
        self.assertIn("- uno", texto)
        self.assertNotIn("menú", texto)
        self.assertNotIn("no()", texto)
        self.assertIn("https://x.org/otra", texto)

    def test_filtrar(self):
        texto = "intro\n\nnada que ver\n\nusa row_factory acá\n\notro\n\nfinal"
        filtrado = filtrar_relevante(texto, "row_factory", contexto=0)
        self.assertIn("row_factory", filtrado)
        self.assertNotIn("intro", filtrado)
        self.assertIn("no encontré", filtrar_relevante(texto, "inexistente"))

    def test_validar_url(self):
        self.assertTrue(validar_url("https://docs.python.org/3/")[1])
        self.assertFalse(validar_url("https://ejemplo.com/x")[1])
        self.assertTrue(validar_url("https://ejemplo.com/x", ["ejemplo.com"])[1])
        for mala in ("ftp://x", "http://localhost:8000", "http://192.168.0.1/", "https://x.com/?q=" + "a" * 400,
                     "https://x.com/?k=sk-abcdefghijklmnopqrst", "no es url"):
            with self.assertRaises(ValueError):
                validar_url(mala)

    def test_descargar_local(self):
        with _ServidorDePrueba() as srv:
            html = descargar_texto(srv.base + "/doc", usar_cache=False)
            self.assertEqual((html["tipo"], html["titulo"]), ("html", "Docs de prueba"))
            api = descargar_texto(srv.base + "/api", usar_cache=False)
            self.assertEqual(api["tipo"], "json")
            self.assertIn('"version": 7', api["texto"])
            plano = descargar_texto(srv.base + "/texto")
            self.assertEqual(plano["texto"], "línea uno\nlínea dos")
            self.assertTrue(list((CACHE_DIR / "web").glob("*.json")))

    def test_herramienta_rechaza_y_desactivada(self):
        ctx = self.contexto(self.proyecto())
        with self.assertRaises(ErrorHerramienta):
            self.herramienta(ctx, "fetch_url", url="http://127.0.0.1:1/x")
        ctx.settings.web = False
        with self.assertRaises(ErrorHerramienta):
            self.herramienta(ctx, "fetch_url", url="https://docs.python.org/3/")


class TestComandosPropios(BaseTest):
    def test_leer_y_expandir(self):
        carpeta = COMANDOS_USUARIO_DIR
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "revisar-seg.md").write_text("---\ndescripcion: seguridad\nmodo: rol:revisor\n---\nRevisá $ARGUMENTOS con cuidado ($1)\n",
                                                encoding="utf-8")
        (carpeta / "Nombre Invalido!.md").write_text("x", encoding="utf-8")
        comandos = comandos_usuario()
        self.assertEqual(list(comandos), ["revisar-seg"])
        c = comandos["revisar-seg"]
        self.assertEqual((c.descripcion, c.modo), ("seguridad", "rol:revisor"))
        self.assertEqual(c.expandir("app.py utils.py"), "Revisá app.py utils.py con cuidado (app.py)")
        sin_variable = ComandoUsuario("x", "Hacé tests.")
        self.assertEqual(sin_variable.expandir("de calc.py"), "Hacé tests.\n\nde calc.py")

    def test_proyecto_gana_y_ejemplos(self):
        ws = self.proyecto({".reaper/comandos/hola.md": "Saludá a $ARGUMENTOS"})
        crear_comandos_de_ejemplo()
        comandos = comandos_usuario(ws)
        self.assertIn("hola", comandos)
        self.assertIn("seguridad", comandos)

    def test_desde_la_app(self):
        ws = self.proyecto({".reaper/comandos/saluda.md": "Decí hola a $ARGUMENTOS"})
        app = App(self.ajustes(), MockLLM(["¡Hola Ana!"]), self.ui(), ws, persistir=False)
        app.comando("/saluda Ana")
        self.assertEqual(app.llm.llamadas[0]["mensajes"][1]["content"].split("\n")[0], "Decí hola a Ana")
        self.assertIn("/saluda", app.nombres_comandos())


class TestPlugins(BaseTest):
    def test_cargar_registra_y_asigna_roles(self):
        roles_previos = dict(ROLES)
        registro_previo = dict(REGISTRO)
        try:
            HERRAMIENTAS_USUARIO_DIR.mkdir(parents=True, exist_ok=True)
            (HERRAMIENTAS_USUARIO_DIR / "contar.py").write_text(EJEMPLO_PLUGIN, encoding="utf-8")
            (HERRAMIENTAS_USUARIO_DIR / "roto.py").write_text("esto no es python (", encoding="utf-8")
            cargados = cargar_plugins()
            buenos = [p for p in cargados if not p.error]
            self.assertEqual(buenos[0].herramientas, ["count_lines"])
            self.assertTrue(any(p.error for p in cargados))
            self.assertIn("count_lines", ROLES["principal"].herramientas)
            self.assertIn("count_lines", ROLES["explorador"].herramientas)
            ctx = self.contexto(self.proyecto({"a.py": "1\n2\n"}))
            self.assertIn(".py: 2", self.herramienta(ctx, "count_lines"))
        finally:
            ROLES.clear()
            ROLES.update(roles_previos)
            REGISTRO.clear()
            REGISTRO.update(registro_previo)
            PLUGINS_CARGADOS.clear()


class TestHooks(BaseTest):
    def test_post_escritura_y_bloqueo(self):
        ws = self.proyecto({".reaper/config.json": json.dumps({"hooks": {
            "despues_de_escribir": ["echo '# formateado' >> {archivo}"],
            "antes_de_comando": ["echo {comando} | grep -qv prohibido"],
        }})})
        ctx = self.contexto(ws)
        salida = self.herramienta(ctx, "write_to_file", path="a.py", content="x = 1")
        self.assertIn("un hook del proyecto modificó a.py", salida)
        self.assertIn("# formateado", ws.leer("a.py"))
        self.assertIn("permitido", self.herramienta(ctx, "execute_command", command="echo permitido"))
        with self.assertRaises(ErrorHerramienta) as cm:
            self.herramienta(ctx, "execute_command", command="echo prohibido")
        self.assertIn("hook", str(cm.exception))

    def test_eventos_y_desactivados(self):
        ws = self.proyecto({".reaper/config.json": '{"hooks": {"despues_de_build": "echo {estado}"}}'})
        resultados = ejecutar_hooks(ws, "despues_de_build", {"estado": "verificada"})
        self.assertEqual(resultados[0].salida, "verificada")
        with self.assertRaises(ValueError):
            ejecutar_hooks(ws, "evento_raro")
        ctx = self.contexto(ws, hooks=False)
        self.assertEqual(_hook_post_escritura(ctx, "x"), "")


class TestRenombrar(BaseTest):
    def test_python_no_toca_strings_ni_comentarios(self):
        texto = 'def total(x):\n    return x  # total sin cambiar\n\nprint(total(2), "total")\nobj.total = 1\n'
        nuevo, n = renombrar_en_texto("a.py", texto, "total", "suma")
        self.assertEqual(n, 3)
        self.assertIn("def suma(x):", nuevo)
        self.assertIn("# total sin cambiar", nuevo)
        self.assertIn('"total"', nuevo)
        self.assertIn("obj.suma = 1", nuevo)
        self.assertNotIn("subtotal", renombrar_en_texto("b.py", "subtotal = total\n", "total", "suma")[0].replace("subtotal", "ok"))

    def test_js(self):
        texto = "const total = 1; // total\nconsole.log(`total ${total}`, 'total', subtotal, total);\n"
        nuevo, n = renombrar_en_texto("a.js", texto, "total", "suma")
        self.assertEqual(n, 2)
        self.assertIn("const suma = 1; // total", nuevo)
        self.assertIn("subtotal, suma)", nuevo)

    def test_plan_y_aplicacion_en_proyecto(self):
        ws = self.proyecto({"calc.py": "def calcular(x):\n    return x\n",
                            "main.py": "from calc import calcular\nprint(calcular(1))\n",
                            "notas.txt": "calcular a mano"})
        plan = planificar_renombrado(ws, "calcular", "computar")
        self.assertEqual(sorted(plan.cambios), ["calc.py", "main.py"])
        self.assertEqual(plan.total, 3)
        ws.checkpoints.iniciar("renombrar")
        aplicar_renombrado(ws, plan)
        self.assertIn("from calc import computar", ws.leer("main.py"))
        self.assertEqual(ws.leer("notas.txt"), "calcular a mano")
        for malo in (("1x", "y"), ("a", "a"), ("a", "class")):
            with self.assertRaises(ValueError):
                planificar_renombrado(ws, *malo)

    def test_herramienta(self):
        ws = self.proyecto({"m.py": "def vieja():\n    return 1\n\nvieja()\n"})
        ctx = self.contexto(ws)
        salida = self.herramienta(ctx, "rename_symbol", old="vieja", new="nueva")
        self.assertIn("2 cambio(s)", salida)
        self.assertIn("def nueva", ws.leer("m.py"))
        self.assertIn("No encontré", self.herramienta(ctx, "rename_symbol", old="inexistente", new="x"))


class TestIngles(BaseTest):
    def test_prompt_en(self):
        ws = self.proyecto()
        prompt = system_prompt(ROLES["implementador"], ws, 4, idioma="en")
        self.assertIn("You are REAPER", prompt)
        self.assertIn("YOUR ROLE: IMPLEMENTADOR", prompt)
        self.assertIn("Replaces a WHOLE function", prompt)
        self.assertIn("# TU ROL: IMPLEMENTADOR", prompt)  # los guiones siguen encontrando el rol

    def test_todo_traducido(self):
        faltan_roles = [r for r in ROLES if r not in MISIONES_EN]
        self.assertEqual(faltan_roles, [])
        faltan_docs = [h for h in REGISTRO if h not in DOCS_EN and not h.startswith("count_")]
        self.assertEqual(faltan_docs, [])

    def test_agente_en_ingles(self):
        llm = MockLLM(["Respuesta en español."])
        Agente("principal", llm, self.proyecto(), self.ajustes(idioma_prompts="en"), self.ui(), memoria=None).ejecutar("hola")
        self.assertIn("You are REAPER", llm.llamadas[0]["mensajes"][0]["content"])


class TestEstadisticas(BaseTest):
    def test_registrar_y_totales(self):
        est = Estadisticas(self.dir / "est.json")
        est.registrar(pedidos=1, pedidos_ok=1, segundos=2.5)
        est.registrar(builds=1, builds_ok=0, torneos=2, modelo="venice")
        uso = Uso(llamadas=3, tokens_entrada=100, tokens_salida=50, costo=0.01)
        est.registrar_uso(uso, "venice")
        est.registrar_uso(uso, "venice")  # sin cambios: no suma dos veces
        t = est.totales()
        self.assertEqual((t["pedidos"], t["builds"], t["torneos"], t["llamadas"], t["tokens_entrada"]), (1, 1, 2, 3, 100))
        self.assertAlmostEqual(t["costo"], 0.01)
        self.assertEqual(len(est.dias()), 1)
        ui = self.ui()
        mostrar_estadisticas(ui, est)
        self.assertIn("TOTALES", ui.texto_registrado())
        self.assertEqual(tasa(1, 4), "25%")


class TestComandosExtra(BaseTest):
    def app(self, guion=None, archivos=None, respuestas=None) -> App:
        ws = self.proyecto(archivos or {"calc.py": "def suma(a, b):\n    return a + b\n"})
        return App(self.ajustes(), MockLLM(guion or []), self.ui(respuestas=respuestas), ws, persistir=False)

    def test_explicar(self):
        app = self.app(["**suma** devuelve a + b."])
        app.comando("/explicar suma")
        self.assertIn("devuelve a + b", app.ui.texto_registrado())
        self.assertIn("def suma", app.llm.llamadas[0]["mensajes"][-1]["content"])
        app.comando("/explicar no_existe_nada")
        self.assertIn("No encontré", app.ui.texto_registrado())

    def test_renombrar_desde_la_cli(self):
        app = self.app(respuestas=["s"], archivos={"a.py": "def f():\n    return 1\n\nf()\n"})
        app.comando("/renombrar f g")
        self.assertIn("def g", app.ws.leer("a.py"))

    def test_comandos_varios(self):
        app = self.app()
        for comando, esperado in (("/estadisticas", "estadísticas"), ("/sesiones", "No hay sesiones"),
                                  ("/comandos", "No tenés comandos"), ("/plugins", "No hay plugins"),
                                  ("/hooks", "Sin hooks"), ("/deps", "No encontré archivos de dependencias"),
                                  ("/web ftp://x", "http"), ("/commit", "no es un repositorio")):
            app.comando(comando)
            self.assertIn(esperado, app.ui.texto_registrado(), comando)
            app.ui.registro.clear()
        app.comando("/comandos ejemplos")
        app.comando("/comandos")
        self.assertIn("/seguridad", app.ui.texto_registrado())
        app.comando("/comandos nuevo mio")
        self.assertTrue((app.ws.raiz / ".reaper" / "comandos" / "mio.md").exists())

    def test_deps_detecta(self):
        ws = self.proyecto({"requirements.txt": "requests\n", "package.json": "{}"})
        origenes = [o for o, _ in comandos_de_dependencias(ws)]
        self.assertEqual(origenes, ["requirements.txt", "package.json"])

    def test_commit_con_mensaje_generado(self):
        if not shutil.which("git"):
            self.skipTest("git no está instalado")
        app = self.app(["Agrega suma\n\n- suma dos números"], respuestas=["s"])
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        os.environ.update(env)
        try:
            git(app.ws, "init", "-q")
            app.comando("/commit")
            self.assertIn("Agrega suma", git(app.ws, "log", "-1", "--pretty=%B").stdout)
        finally:
            for k in env:
                os.environ.pop(k, None)
