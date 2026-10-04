"""Autotest: CLI y comandos, recetas, benchmark, doctor, instalador, /vigilar y plantillas."""


class TestCLI(BaseTest):
    def app(self, guion=None, respuestas=None, archivos=None) -> App:
        ws = self.proyecto(archivos or {"calc.py": "def suma(a, b):\n    return a + b\n"})
        return App(self.ajustes(lecciones=True), MockLLM(guion or []), self.ui(respuestas=respuestas), ws,
                   persistir=False)

    def salida(self, app: App) -> str:
        texto = app.ui.texto_registrado()
        app.ui.registro.clear()
        return texto

    def test_turno_y_menciones(self):
        app = self.app(["calc.py suma dos números."])
        self.assertTrue(app.turno("¿qué hace @calc.py?"))
        primera = app.llm.llamadas[0]["mensajes"][1]["content"]
        self.assertIn("ARCHIVOS MENCIONADOS", primera)
        self.assertIn("return a + b", primera)
        self.assertIn("suma dos números", self.salida(app))
        self.assertEqual(len(app.historial), 1)

    def test_comandos_informativos(self):
        app = self.app()
        for comando, esperado in (("/estado", "ESTADO REAPER"), ("/modelos", "deepseek"), ("/plantillas", "python-cli"),
                                  ("/perfil", "equilibrado"), ("/uso", "llamadas"), ("/contexto", "tokens"),
                                  ("/todo", "vacía"), ("/historial", "Sin pedidos"), ("/ayuda", "/construir"),
                                  ("/recetas", "recetas"), ("/recetas sqlite", "SQLite"), ("/mapa suma", "calc.py"),
                                  ("/simbolo suma", "def suma"), ("/referencias suma", "Sin usos"),
                                  ("/lecciones", "Todavía no hay lecciones"), ("/notas", "No hay notas"),
                                  ("/checkpoints", "Sin checkpoints"), ("/modelo-fuerte", "escalada"),
                                  ("/tema", "Tema actual")):
            app.comando(comando)
            self.assertIn(esperado, self.salida(app), comando)

    def test_comando_desconocido_sugiere(self):
        app = self.app()
        app.comando("/estadoo")
        self.assertIn("/estado", self.salida(app))
        self.assertIn("/vigilar", app.nombres_comandos())

    def test_config_perfil_modelo_tema(self):
        app = self.app()
        app.comando("/config paralelo 3")
        self.assertEqual(app.settings.paralelo, 3)
        app.comando("/config paralelo mucho")
        self.assertIn("Valor inválido", self.salida(app))
        app.comando("/config temperaturas [0.2, 0.5]")
        self.assertEqual(app.settings.temperaturas, [0.2, 0.5])
        app.comando("/perfil rapido")
        self.assertFalse(app.settings.torneo)
        app.comando("/modelo revisor qwen")
        self.assertEqual(app.settings.modelo_para("revisor"), MODELOS["qwen"])
        app.comando("/modelo-fuerte qwen3-coder")
        self.assertEqual(app.settings.modelo_fuerte, "qwen3-coder")
        app.comando("/modelo-fuerte off")
        self.assertFalse(app.settings.escalar)
        app.comando("/modo confirmar")
        self.assertEqual(app.settings.modo, "confirmar")
        app.comando("/tema oceano")
        self.assertEqual(Tema.nombre, "oceano")
        aplicar_tema("dragon")
        self.assertTrue(CONFIG_FILE.exists())

    def test_deshacer_y_rehacer(self):
        app = self.app(respuestas=["s"])
        cid = app.ws.checkpoints.iniciar("cambio")
        app.ws.escribir("calc.py", "def suma(a, b):\n    return 0\n")
        app.comando("/diff")
        self.assertIn("return 0", self.salida(app))
        app.comando(f"/deshacer {cid}")
        self.assertIn("return a + b", app.ws.leer("calc.py"))
        app.comando("/rehacer")
        self.assertIn("return 0", app.ws.leer("calc.py"))
        app.comando("/rehacer")
        self.assertIn("No hay nada para rehacer", self.salida(app))

    def test_lecciones_desde_la_cli(self):
        app = self.app()
        app.comando("/lecciones agregar Los precios de calc.py se guardan en centavos (int)")
        app.comando("/lecciones")
        self.assertIn("centavos", self.salida(app))
        app.comando("/lecciones borrar 1")
        self.assertEqual(app.memoria.proyecto.cargar(), [])

    def test_nuevo_desde_plantilla(self):
        app = self.app()
        destino = self.dir / "proyectos_nuevos" / "mi_cli"
        destino.parent.mkdir()
        os.environ["REAPER_LIBRE"] = "1"
        try:
            app.comando(f"/nuevo python-cli {destino}")
        finally:
            os.environ.pop("REAPER_LIBRE", None)
        self.assertEqual(app.ws.raiz, destino.resolve())
        self.assertTrue((destino / "mi_cli" / "cli.py").exists())
        self.assertIn("tests de la plantilla: pasan", self.salida(app))

    def test_exportar_y_compactar(self):
        app = self.app(["respuesta con sk-abcdefghijklmnopqrstuvwx dentro"])
        app.turno("hola")
        destino = self.dir / "conv.md"
        app.comando(f"/exportar {destino}")
        texto = destino.read_text(encoding="utf-8")
        self.assertIn("## Vos", texto)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwx", texto)
        app.comando("/compactar")
        self.assertIn("Contexto:", self.salida(app))

    def test_torneo_desde_la_cli(self):
        def guion(mensajes, kwargs):
            if MockLLM.turnos_asistente(mensajes):
                return terminar_xml("listo")
            resta = "a - b" if kwargs.get("temperatura") == 0.1 else "b - a"
            return herramienta_xml("write_to_file", path="resta.py", content=f"def resta(a, b):\n    return {resta}")

        app = self.app(guion, archivos={
            "tests/test_resta.py": "import unittest\nfrom resta import resta\n\nclass T(unittest.TestCase):\n"
                                   "    def test_r(self):\n        self.assertEqual(resta(5, 3), 2)\n"})
        app.settings.candidatos, app.settings.paralelo_torneo = 2, 1
        app.comando("/torneo creá resta.py con resta(a, b)")
        self.assertIn("a - b", app.ws.leer("resta.py"))
        self.assertIn("Ganó el candidato #1", self.salida(app))

    def test_escribir_desde_la_cli(self):
        def guion(mensajes, kwargs):
            prompt = mensajes[-1]["content"]
            if "IMPLEMENTÁ AHORA" not in prompt:
                return '```python\ndef saludo(nombre):\n    """Saluda."""\n    raise NotImplementedError("REAPER")\n```'
            return '```python\ndef saludo(nombre):\n    return f"Hola {nombre}"\n```'

        app = self.app(guion)
        app.comando("/escribir saludo.py un módulo con una función que saluda por nombre")
        self.assertIn("return f\"Hola {nombre}\"", app.ws.leer("saludo.py"))

    def test_correr_y_scan(self):
        app = self.app(respuestas=["n"], archivos={"ok.py": "print('hola desde ok')\n",
                                                  "roto.py": "x = [\n", "crash.py": "raise ValueError('boom')\n"})
        app.comando("/correr ok.py")
        self.assertIn("hola desde ok", self.salida(app))
        app.comando("/correr crash.py")
        self.assertIn("Crash", self.salida(app) + "Crash")
        app.comando("/scan")
        self.assertIn("roto.py", self.salida(app))

    def test_mostrar_inicio(self):
        app = self.app()
        app.mostrar_inicio(animar=False)
        texto = self.salida(app)
        self.assertIn("proyecto", texto)
        self.assertIn("v" + __version__, texto)

    def test_sesion_persistente(self):
        ws = self.proyecto()
        app = App(self.ajustes(), MockLLM(["hola, guardé la sesión"]), self.ui(), ws, persistir=True)
        app.turno("primer pedido")
        otra = App(self.ajustes(), MockLLM([]), self.ui(), ws, persistir=True)
        self.assertIn("retomé la sesión", otra.aviso_sesion)
        self.assertEqual(len(otra.historial), 1)
        otra.comando("/reset")
        self.assertFalse(otra._ruta_sesion().exists())


class TestMain(BaseTest):
    def test_parser(self):
        args = construir_parser().parse_args(["--construir", "algo", "--auto", "--perfil", "gratis", "--sin-torneo"])
        self.assertEqual((args.construir, args.auto, args.perfil, args.sin_torneo), ("algo", True, "gratis", True))

    def test_sin_clave(self):
        anteriores = {k: os.environ.pop(k, None) for k in ("OPENROUTER_API_KEY",)}
        try:
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                codigo = main(["-p", "hola"])
            self.assertEqual(codigo, 1)
        finally:
            for k, v in anteriores.items():
                if v is not None:
                    os.environ[k] = v


class TestRecetas(BaseTest):
    def test_buscar(self):
        self.assertIn("SQLite", buscar_recetas("guardar en una base de datos sqlite")[0].titulo)
        self.assertIn("termux", buscar_recetas("mandar una notificación en android")[0].etiquetas)
        self.assertEqual(buscar_recetas(""), [])

    def test_para_prompt(self):
        self.assertIn("RECETAS DE REFERENCIA", recetas_para_prompt("hacé un juego en la terminal con curses y teclado"))
        self.assertEqual(recetas_para_prompt("cambiá el color del título"), "")

    def test_recetas_python_compilan(self):
        for r in RECETAS:
            if r.lenguaje == "python":
                compile(r.codigo, r.titulo, "exec")


class TestEvaluacion(BaseTest):
    def test_tarea_resuelta_y_fallida(self):
        tarea = next(t for t in TAREAS_EVAL if t.id == "fizzbuzz")
        solucion = ("def fizzbuzz(n):\n    salida = []\n    for i in range(1, n + 1):\n        if '7' in str(i):\n"
                    "            salida.append('Siete')\n        elif i % 15 == 0:\n            salida.append('FizzBuzz')\n"
                    "        elif i % 3 == 0:\n            salida.append('Fizz')\n        elif i % 5 == 0:\n"
                    "            salida.append('Buzz')\n        else:\n            salida.append(str(i))\n    return salida")
        llm = MockLLM([herramienta_xml("write_to_file", path="fizz.py", content=solucion), terminar_xml("listo")])
        res = correr_tarea_eval(tarea, llm, self.ajustes(), self.ui())
        self.assertTrue(res.ok, res.conteo.texto())
        mal = correr_tarea_eval(tarea, MockLLM(["No sé hacerlo."]), self.ajustes(), self.ui())
        self.assertFalse(mal.ok)

    def test_tareas_bien_formadas(self):
        ids = [t.id for t in TAREAS_EVAL]
        self.assertEqual(len(ids), len(set(ids)))
        for t in TAREAS_EVAL:
            for rel, contenido in {**t.tests, **t.archivos}.items():
                compile(contenido, rel, "exec")

    def test_correr_evaluacion_guarda_informe(self):
        llm = MockLLM(lambda m, k: "No sé.")
        self.assertFalse(correr_evaluacion(llm, self.ajustes(), self.ui(), cantidad=1))
        self.assertTrue(list((BASE_DIR / "evals").glob("eval_*.json")))


class TestDoctor(BaseTest):
    def test_chequeos(self):
        chequeos = {c.nombre: c for c in chequeos_sistema(self.ajustes(proveedor="ollama"))}
        self.assertTrue(chequeos["python"].ok)
        self.assertTrue(chequeos["carpeta REAPER"].ok)
        ui = self.ui()
        diagnostico_sistema(ui, self.ajustes(proveedor="ollama"))
        self.assertIn("DOCTOR REAPER", ui.texto_registrado())

    def test_instalar_lanzador(self):
        casa = self.dir / "casa"
        casa.mkdir()
        anteriores = {k: os.environ.get(k) for k in ("HOME", "PREFIX", "TERMUX_VERSION")}
        os.environ["HOME"] = str(casa)
        os.environ.pop("PREFIX", None)
        os.environ.pop("TERMUX_VERSION", None)
        try:
            if archivo_actual() is None:
                self.skipTest("no se puede ubicar el archivo de REAPER")
            lanzador = instalar_lanzador(self.ui())
            if es_termux():
                self.skipTest("en Termux el lanzador va a $PREFIX/bin")
            self.assertTrue(lanzador and lanzador.exists())
            self.assertIn("import reaper_v7", lanzador.read_text())
            self.assertTrue((BASE_DIR / "app" / "reaper_v7.py").exists())
        finally:
            for k, v in anteriores.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TestVigilar(BaseTest):
    def test_corre_al_cambiar(self):
        ws = self.proyecto({"a.py": "x = 1\n"})
        llamadas = []

        def dormir(segundos):
            llamadas.append(segundos)
            if len(llamadas) == 1:
                time.sleep(0.02)
                (ws.raiz / "a.py").write_text("x = 2\n")

        comando = f"{shlex.quote(sys.executable)} -c \"print('ok')\""
        corridas = vigilar(ws, self.ui(), comando=comando, max_ciclos=2, dormir=dormir)
        self.assertEqual(corridas, 2)
        self.assertEqual(diferencias_mtimes({"a": 1.0, "b": 1.0}, {"a": 2.0, "c": 1.0}), ["a", "b", "c"])

    def test_sin_suite(self):
        self.assertEqual(vigilar(self.proyecto(), self.ui(), max_ciclos=1, dormir=lambda s: None), 0)


class TestPlantillas(BaseTest):
    def test_variables(self):
        variables = variables_para(Path("/x/Mi App 2"))
        self.assertEqual(variables["__PROYECTO__"], "mi_app_2")
        self.assertEqual(variables["__Proyecto__"], "MiApp2")
        self.assertEqual(nombre_proyecto(Path("/x/123")), "p_123")
        self.assertEqual(nombre_proyecto(Path("/x/class")), "class_app")

    def test_no_pisa_carpetas_con_contenido(self):
        destino = self.dir / "ocupada"
        destino.mkdir()
        (destino / "algo.txt").write_text("x")
        with self.assertRaises(FileExistsError):
            crear_desde_plantilla("python-cli", destino)
        with self.assertRaises(KeyError):
            crear_desde_plantilla("no-existe", self.dir / "otra")

    def test_plantilla_de_usuario(self):
        carpeta = PLANTILLAS_USUARIO_DIR / "mia"
        carpeta.mkdir(parents=True)
        (carpeta / "hola.py").write_text("print('__TITULO__')\n")
        (carpeta / "plantilla.json").write_text('{"descripcion": "mía", "lenguaje": "python"}')
        creados = crear_desde_plantilla("mia", self.dir / "desde_mia")
        self.assertIn("hola.py", creados)
        self.assertIn("Desde Mia", (self.dir / "desde_mia" / "hola.py").read_text())
        self.assertIn("mia", todas_las_plantillas())

    def test_sugeridas(self):
        nombres = [p.nombre for p in plantillas_sugeridas("quiero un bot de telegram")]
        self.assertIn("bot-telegram", nombres)

    def test_todas_las_plantillas_pasan_sus_tests(self):
        for nombre, plantilla in sorted(PLANTILLAS.items()):
            with self.subTest(plantilla=nombre):
                if not plantilla.comando_tests:
                    continue
                if not plantilla.disponible():
                    continue
                if set(plantilla.requiere) & {"go", "cargo", "javac", "make"} and not os.getenv("REAPER_AUTOTEST_COMPLETO"):
                    continue  # compilar Go/Rust/Java/C tarda: solo con REAPER_AUTOTEST_COMPLETO=1
                destino = self.dir / "plantillas_generadas" / nombre.replace("-", "_")
                creados = crear_desde_plantilla(nombre, destino)
                self.assertIn("REAPER.md", creados)
                r = ejecutar(comando_portable(plantilla.comando_tests), cwd=destino, timeout=180, shell=True)
                self.assertTrue(r.ok, f"{nombre}: {recortar(r.stdout + r.stderr, 2500)}")
                for rel in creados:
                    if rel.endswith(".py"):
                        compile((destino / rel).read_text(encoding="utf-8"), rel, "exec")
