"""
Autotests P0 de la fusión 8.10 (ChatGPT ronda 12 + Claude). Cada uno reproduce un defecto confirmado antes de
corregirlo: XML de herramienta mal cerrado que se escribía en el archivo, Ctrl+C que esperaba a una llamada lenta,
hijos huérfanos tras Ctrl+C, falsos verdes (tests todos omitidos, gate de aceptación suplantable, manifiesto
editable por el agente, proyecto que aflojaba el modo de permisos) y builds sin plazo de pared.
"""


class TestXmlMalformadoNoMuta(BaseTest):
    def _agente(self, ws, guion):
        ui = self.ui()
        Agente("principal", MockLLM(guion), ws, self.ajustes(modo="auto"), ui, memoria=None,
               mostrar_progreso=False).ejecutar("arreglá el estilo")
        return ui.texto_registrado()

    def test_cierre_de_herramienta_mal_escrito_no_se_escribe_en_el_archivo(self):
        original = "body { color: black; }\nh1 { margin: 0; }\n"
        ws = self.proyecto({"web/style.css": original})
        texto = self._agente(ws, [
            herramienta_xml("read_file", path="web/style.css"),
            "Corrijo.\n<replace_lines><path>web/style.css</path><desde>1</desde><hasta>1</hasta>"
            "<content>body { color: red; }\n</replace_line>",
            terminar_xml("listo")])
        self.assertEqual(ws.leer("web/style.css"), original)        # antes quedaba "</replace_line>" dentro
        self.assertIn("etiqueta de cierre inválida", texto)

    def test_cierre_de_parametro_mal_escrito_no_se_escribe(self):
        original = "let a = 1;\n"
        ws = self.proyecto({"web/script.js": original})
        self._agente(ws, [
            herramienta_xml("read_file", path="web/script.js"),
            "<replace_lines><path>web/script.js</path><desde>1</desde><hasta>1</hasta>"
            "<content>let a = 2;\n</contnet></replace_lines>",
            terminar_xml("listo")])
        self.assertEqual(ws.leer("web/script.js"), original)

    def test_archivo_bien_delimitado_que_termina_en_etiqueta_si_se_escribe(self):
        ws = self.proyecto({})
        contenido = '<?xml version="1.0"?>\n<Context path="/app">\n</Context>\n'
        self._agente(ws, [herramienta_xml("write_to_file", path="conf/context.xml", content=contenido),
                          terminar_xml("listo")])
        self.assertIn("</Context>", ws.leer("conf/context.xml"))    # sin falsos positivos

    def test_html_sin_cierres_de_herramienta_se_sigue_aceptando(self):
        ws = self.proyecto({})
        self._agente(ws, ["<write_to_file><path>index.html</path><content><html><body>hola</body></html>\n",
                          terminar_xml("listo")])
        self.assertIn("</html>", ws.leer("index.html"))             # la tolerancia previa se conserva

    def test_detector_directo(self):
        self.assertEqual(cierre_espurio("x\n</replace_line>", ["replace_lines", "content"]), "</replace_line>")
        self.assertIsNone(cierre_espurio("x\n</html>\n", ["write_to_file", "content"]))
        self.assertEqual(cierre_espurio("x</tool>", [], ["tool"]), "</tool>")


class TestCtrlCNoCuelga(BaseTest):
    def test_hilos_se_cortan_rapido_al_cancelar(self):
        tareas = [lambda: time.sleep(5) or 1, lambda: time.sleep(5) or 2]
        temporizador = threading.Timer(0.3, CANCELAR.set)
        temporizador.start()
        inicio = time.monotonic()
        try:
            with self.assertRaises(Cancelado):
                ejecutar_hilos(tareas, 2, gracia=0.2)
        finally:
            temporizador.cancel()
            CANCELAR.clear()
        self.assertLess(time.monotonic() - inicio, 2.5)              # no espera los 5 s del hilo lento

    def test_hilos_devuelven_en_orden_y_relanzan_errores(self):
        self.assertEqual(ejecutar_hilos([lambda: "a", lambda: "b", lambda: "c"], 2), ["a", "b", "c"])
        with self.assertRaises(ValueError):
            ejecutar_hilos([lambda: 1, lambda: (_ for _ in ()).throw(ValueError("x"))], 2)

    def test_sigint_real_sale_en_plazo_acotado(self):
        # Proceso real: dos subagentes en paralelo esperan a un modelo que tarda 30 s; Ctrl+C (SIGINT) al
        # segundo. Antes salía recién cuando terminaba la llamada (~27 s); ahora en la gracia acotada.
        guion = (
            "import sys, time, importlib.util, tempfile\n"
            "from pathlib import Path\n"
            "spec = importlib.util.spec_from_file_location('r', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec); sys.modules['r'] = m; spec.loader.exec_module(m)\n"
            "class Lento:\n"
            "    def chat(self, mensajes, **k):\n"
            "        time.sleep(30); return m.Respuesta(m.terminar_xml('x'), 'stop', 'lento')\n"
            "    def __getattr__(self, n): return getattr(m.MockLLM([]), n)\n"
            "raiz = Path(tempfile.mkdtemp()); (raiz / 'a.py').write_text('x = 1\\n')\n"
            "s = m.Settings(); s.paralelo = 2; s.forense = False; s.lecciones = False\n"
            "print('listo', flush=True)\n"
            "m.ejecutar_subagentes([('explorador', 'a', ''), ('explorador', 'b', '')], Lento(), m.Workspace(raiz), s,\n"
            "                      m.UI(silencioso=True, interactivo=False))\n")
        script = self.dir / "sigint.py"
        script.write_text(guion, encoding="utf-8")
        proceso = subprocess.Popen([sys.executable, "-I", str(script), str(Path(__file__).resolve())],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            self.assertEqual(proceso.stdout.readline().strip(), "listo")
            time.sleep(1.0)
            inicio = time.monotonic()
            proceso.send_signal(signal.SIGINT)
            proceso.wait(timeout=20)
            self.assertLess(time.monotonic() - inicio, 8.0)
        finally:
            if proceso.poll() is None:
                proceso.kill()
                proceso.wait()
            proceso.stdout.close()

    def test_cancelar_mata_el_subproceso_en_curso(self):
        resultado = {}
        hilo = threading.Thread(target=lambda: resultado.setdefault(
            "r", ejecutar("sleep 30", cwd=self.dir, timeout=60, shell=True)), daemon=True)
        inicio = time.monotonic()
        hilo.start()
        time.sleep(0.4)
        CANCELAR.set()
        try:
            hilo.join(5)
        finally:
            CANCELAR.clear()
        self.assertFalse(hilo.is_alive())
        self.assertEqual(resultado["r"].codigo, 130)
        self.assertLess(time.monotonic() - inicio, 5)
        self.assertEqual(matar_procesos_vivos(), 0)                  # no quedó ningún hijo registrado


class TestFalsosVerdesFusion(BaseTest):
    def test_tests_todos_omitidos_no_verifican(self):
        ws = self.proyecto({
            "app.py": "def suma(a, b):\n    return a - b\n",
            "tests/test_app.py": "import unittest\nfrom app import suma\nclass T(unittest.TestCase):\n"
                                 "    @unittest.skip('luego')\n    def test_suma(self):\n"
                                 "        self.assertEqual(suma(2, 2), 4)\n"})
        orq = Orquestador(MockLLM([]), ws, self.ajustes(forense=False, lecciones=False), self.ui())
        verif = orq.verificar(ws.checkpoints.iniciar("x"))
        self.assertFalse(verif.ok)
        self.assertIn("OMITIDOS", verif.diagnostico)
        self.assertEqual(estado_final_build(verif, InformeBuild("fallida")), "fallida")

    def _gate(self, codigo: str, minimo: int = 1):
        suite = self.dir / "evaluador"
        suite.mkdir(parents=True, exist_ok=True)
        (suite / "test_real.py").write_text(codigo, encoding="utf-8")
        ws = self.proyecto({".reaper/acceptance.json": json.dumps(
            {"suite_dir": str(suite), "min_tests": minimo, "timeout": 60})})
        return ws, suite

    def test_unittest_del_proyecto_no_suplanta_al_evaluador(self):
        ws, _suite = self._gate("import unittest\nclass T(unittest.TestCase):\n"
                                "    def test_falla(self):\n        self.assertEqual(1, 2)\n", minimo=3)
        ws.escribir("unittest.py", "import sys\nsys.stderr.write('\\nRan 50 tests in 0.1s\\n\\nOK\\n')\n"
                                   "raise SystemExit(0)\n")
        r = ejecutar_aceptacion_independiente(ws)
        self.assertFalse(r.ok)                                       # antes: ok=True con "Ran 50 tests ... OK"
        self.assertIn("1 fallos", r.stderr)

    def test_conteo_falso_impreso_por_el_proyecto_no_cuenta(self):
        ws, _suite = self._gate("import unittest\nclass T(unittest.TestCase):\n"
                                "    def test_ok(self):\n        print('Ran 99 tests'); self.assertTrue(True)\n",
                                minimo=5)
        r = ejecutar_aceptacion_independiente(ws)
        self.assertFalse(r.ok)
        self.assertIn("1/5", r.stderr)

    def test_auxiliar_de_la_suite_editado_rompe_la_huella(self):
        ws, suite = self._gate("import unittest\nfrom ayuda import X\nclass T(unittest.TestCase):\n"
                               "    def test_ok(self):\n        self.assertEqual(X, 1)\n")
        (suite / "ayuda.py").write_text("X = 1\n", encoding="utf-8")
        huella = huella_aceptacion(ws)
        self.assertTrue(ejecutar_aceptacion_independiente(ws, huella_fijada=huella).ok)
        (suite / "ayuda.py").write_text("X = 2\n", encoding="utf-8")
        r = ejecutar_aceptacion_independiente(ws, huella_fijada=huella)
        self.assertFalse(r.ok)
        self.assertIn("cambiado", r.stderr)

    def test_suite_verde_real_sigue_aprobando(self):
        ws, _suite = self._gate("import unittest, os\nclass T(unittest.TestCase):\n"
                                "    def test_proyecto_visible(self):\n"
                                "        self.assertTrue(os.path.isdir(os.environ['REAPER_PROYECTO']))\n")
        r = ejecutar_aceptacion_independiente(ws)
        self.assertTrue(r.ok, r.resumen())

    def test_agente_no_puede_editar_ni_borrar_el_manifiesto(self):
        ws = self.proyecto({".reaper/acceptance.json": json.dumps({"suite_dir": "/tmp/x", "min_tests": 10})})
        for intento in (lambda: ws.escribir(".reaper/acceptance.json", '{"min_tests": 1}'),
                        lambda: ws.borrar(".reaper/acceptance.json"),
                        lambda: ws.escribir(".reaper/build_pendiente.json", "{}")):
            with self.assertRaises(ErrorRuta):
                intento()
        self.assertIn('"min_tests": 10', (ws.raiz / ".reaper" / "acceptance.json").read_text(encoding="utf-8"))

    def test_proyecto_no_afloja_el_modo_de_permisos(self):
        base = Settings(modo="confirmar", hooks=False)
        local = {"settings": {"modo": "auto", "hooks": True, "candidatos": 2}}
        s = settings_con_local(base, local)
        self.assertEqual(s.modo, "confirmar")
        self.assertFalse(s.hooks)
        self.assertEqual(s.candidatos, 2)                            # lo inocuo sí se aplica
        self.assertEqual(set(overrides_proyecto_ignorados(local, base)), {"modo", "hooks"})
        self.assertEqual(settings_con_local(Settings(modo="auto"), {"settings": {"modo": "confirmar"}}).modo,
                         "confirmar")                                # endurecer sí se permite


class TestPlazosDePared(BaseTest):
    def test_agente_corta_al_vencer_el_plazo_sin_declarar_exito(self):
        guion = [herramienta_xml("list_files", path=".")] * 30
        with PLAZO.limitar(0.001, "la prueba"):
            time.sleep(0.01)
            res = Agente("principal", MockLLM(guion), self.proyecto({"a.py": "x=1\n"}), self.ajustes(modo="auto"),
                         self.ui(), memoria=None, mostrar_progreso=False).ejecutar("explorá")
        self.assertFalse(res.ok)
        self.assertEqual(res.motivo, "tiempo")
        self.assertIsNone(PLAZO.vencido())                           # el plazo no sobrevive a su bloque

    def test_build_con_plazo_vencido_no_queda_verificada(self):
        plan = TestBloqueoDependientes.PLAN

        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            if rol == "arquitecto":
                return terminar_xml(plan)
            if rol == "implementador":
                time.sleep(1.2)                                      # un modelo lento consume el plazo
                if _turno(mensajes) == 0:
                    return herramienta_xml("write_to_file", path="a.py", content="def uno():\n    return 1\n")
                return terminar_xml("hecho")
            return terminar_xml("ok")

        ws = self.proyecto({"README.md": "# dos\n"})
        ajustes = self.ajustes(tests_primero=False, torneo=False, max_revisiones=0, lecciones=False, qa=False,
                               max_reparaciones=1, umbral_escalada=0, tiempo_max_build=1, forense=False)
        informe = Orquestador(MockLLM(guion), ws, ajustes, self.ui()).construir("dos módulos", confirmar=False)
        self.assertNotEqual(informe.estado, "verificada")
        self.assertIn("2", informe.tareas_fallidas + informe.tareas_bloqueadas)
        self.assertTrue(any("tiempo" in n for n in informe.notas), informe.notas)
        self.assertIsNone(PLAZO.vencido())

    def test_reparacion_sin_cambios_se_corta(self):
        ws = self.proyecto({"app.py": "def f():\n    return 1\n",
                            "tests/test_app.py": "from app import f\n\ndef test_f():\n    assert f() == 2\n"})
        orq = Orquestador(MockLLM([terminar_xml("no sé")] * 20), ws,
                          self.ajustes(forense=False, lecciones=False, escalar=False), self.ui())
        grupo = ws.checkpoints.iniciar("x")
        verif = orq.verificar(grupo)
        informe = InformeBuild("fallida")
        final = orq._reparar_con_escalada("arreglá f", verif, grupo, False, informe, "final", 6,
                                          lambda: orq.verificar(grupo))
        self.assertFalse(final.ok)
        self.assertTrue(any("sin cambiar" in n or "no cambió" in n for n in informe.notas), informe.notas)


class TestRecursosHtmlRaizWeb(BaseTest):
    def test_url_absoluta_se_resuelve_desde_la_raiz_web_servida(self):
        # web/index.html con "/style.css" y "/script.js" (el servidor publica web/): antes se marcaba como faltante
        # y el reparador terminaba moviendo assets o tocando el ruteo hasta romper "/" (patrón MercadoControl).
        ws = self.proyecto({"web/index.html": '<link href="/style.css"><script src="/script.js"></script>',
                            "web/style.css": "body{}", "web/script.js": "1;"})
        self.assertEqual(recursos_html_faltantes(ws, ws.raiz / "web" / "index.html",
                                                 ws.leer("web/index.html")), [])

    def test_recurso_realmente_ausente_se_sigue_marcando(self):
        ws = self.proyecto({"web/index.html": '<script src="/falta.js"></script>'})
        faltan = recursos_html_faltantes(ws, ws.raiz / "web" / "index.html", ws.leer("web/index.html"))
        self.assertEqual(len(faltan), 1)
        self.assertIn("/falta.js", faltan[0])

    def test_pista_no_empuja_a_romper_la_raiz(self):
        pista = next(p for p in PISTAS if "recursos-html" in p.patron)
        self.assertIn("No cambies la ruta '/'", pista.texto)


class TestTareasIntermediasWeb(BaseTest):
    def test_html_que_enlaza_assets_de_tareas_posteriores_no_falla(self):
        ws = self.proyecto({"README.md": "x\n"})
        orq = Orquestador(MockLLM([]), ws, self.ajustes(lecciones=False, forense=False), self.ui())
        grupo = ws.checkpoints.iniciar("build")
        tcid = ws.checkpoints.iniciar("tarea 2", grupo=grupo)
        ws.escribir("web/index.html", '<link href="/style.css"><script src="/script.js"></script>')
        v = orq._verificar_tarea(tcid, ConteoTests(), set(), verificar_entrega=True,
                                 archivos_esperados=["web/index.html"],
                                 archivos_planeados=["web/style.css", "web/script.js"], cid_build=grupo)
        self.assertTrue(v.ok, v.diagnostico)
        v2 = orq._verificar_tarea(tcid, ConteoTests(), set(), verificar_entrega=True,
                                  archivos_esperados=["web/index.html"], archivos_planeados=["web/style.css"],
                                  cid_build=grupo)
        self.assertFalse(v2.ok)                                      # /script.js no lo crea nadie: sigue fallando
        self.assertIn("script.js", v2.diagnostico)

    def test_archivo_creado_por_una_tarea_anterior_no_es_sin_cambios(self):
        ws = self.proyecto({"app.py": "x = 1\n"})
        orq = Orquestador(MockLLM([]), ws, self.ajustes(lecciones=False, forense=False), self.ui())
        grupo = ws.checkpoints.iniciar("build")
        ws.escribir("web/style.css", "body{}\n")                     # lo hizo la tarea 1 (creó de más)
        tcid = ws.checkpoints.iniciar("tarea 3", grupo=grupo)
        v = orq._verificar_tarea(tcid, ConteoTests(), set(), verificar_entrega=True,
                                 archivos_esperados=["web/style.css"], cid_build=grupo)
        self.assertTrue(v.ok, v.diagnostico)
        v2 = orq._verificar_tarea(tcid, ConteoTests(), set(), verificar_entrega=True,
                                  archivos_esperados=["app.py"], cid_build=grupo)
        self.assertFalse(v2.ok)                                      # app.py ya existía: había que modificarlo
        self.assertIn("SIN CAMBIOS", v2.diagnostico)


class TestGateWebDePuntaAPunta(BaseTest):
    """/construir con modelo simulado, servidor HTTP REAL y evaluador externo real: la app rota no se verifica."""

    APP = (
        "import os\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def log_message(self, *a): pass\n"
        "    def do_GET(self):\n"
        "        rutas = {'/': (b'<html><link href=\"/style.css\"></html>', 'text/html'),\n"
        "                 '/style.css': (b'body{}', 'text/css')}\n"
        "        if ROTA and self.path == '/': rutas.pop('/')\n"
        "        cuerpo, tipo = rutas.get(self.path, (b'no', 'text/plain'))\n"
        "        self.send_response(200 if self.path in rutas else 404)\n"
        "        self.send_header('Content-Type', tipo); self.end_headers(); self.wfile.write(cuerpo)\n"
        "HTTPServer(('127.0.0.1', int(os.environ['PORT'])), H).serve_forever()\n")
    EVALUADOR = (
        "import os, socket, subprocess, sys, time, unittest, urllib.request, urllib.error\n"
        "class T(unittest.TestCase):\n"
        "    @classmethod\n"
        "    def setUpClass(cls):\n"
        "        s = socket.socket(); s.bind(('127.0.0.1', 0)); cls.p = s.getsockname()[1]; s.close()\n"
        "        cls.srv = subprocess.Popen([sys.executable, 'app.py'], cwd=os.environ['REAPER_PROYECTO'],\n"
        "                                   env=dict(os.environ, PORT=str(cls.p)))\n"
        "        for _ in range(50):\n"
        "            try: socket.create_connection(('127.0.0.1', cls.p), 0.2).close(); break\n"
        "            except OSError: time.sleep(0.1)\n"
        "    @classmethod\n"
        "    def tearDownClass(cls): cls.srv.terminate(); cls.srv.wait(5)\n"
        "    def get(self, r):\n"
        "        try:\n"
        "            with urllib.request.urlopen(f'http://127.0.0.1:{self.p}{r}', timeout=5) as x:\n"
        "                return x.status, x.headers['Content-Type']\n"
        "        except urllib.error.HTTPError as e: return e.code, ''\n"
        "    def test_raiz(self): self.assertEqual(self.get('/'), (200, 'text/html'))\n"
        "    def test_css(self): self.assertEqual(self.get('/style.css'), (200, 'text/css'))\n"
        "    def test_404(self): self.assertEqual(self.get('/nada')[0], 404)\n")

    def _build(self, rota: bool) -> InformeBuild:
        suite = self.dir / f"evaluador_{int(rota)}"
        suite.mkdir()
        (suite / "test_web.py").write_text(self.EVALUADOR, encoding="utf-8")
        ws = self.proyecto({"README.md": "web\n", ".reaper/acceptance.json": json.dumps(
            {"suite_dir": str(suite), "min_tests": 3, "timeout": 60})})
        codigo = f"ROTA = {rota}\n" + self.APP
        plan = ('<plan>\n<objetivo>web</objetivo>\n<tarea id="1" archivos="app.py">Crear el servidor app.py'
                '</tarea>\n<criterios>\n- GET / devuelve HTML\n</criterios>\n</plan>')

        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            if rol == "arquitecto":
                return terminar_xml(plan)
            if rol == "implementador" and _turno(mensajes) == 0:
                return herramienta_xml("write_to_file", path="app.py", content=codigo)
            return terminar_xml("hecho")

        ajustes = self.ajustes(tests_primero=False, torneo=False, qa=False, max_revisiones=0, max_reparaciones=1,
                               lecciones=False, forense=False, escalar=False, roles_x=False)
        return Orquestador(MockLLM(guion), ws, ajustes, self.ui()).construir("web", confirmar=False)

    def test_app_rota_no_queda_verificada(self):
        informe = self._build(rota=True)
        self.assertNotEqual(informe.estado, "verificada")
        self.assertIsNotNone(informe.aceptacion)
        self.assertFalse(informe.aceptacion.ok)

    def test_app_correcta_se_verifica_por_aceptacion_externa(self):
        informe = self._build(rota=False)
        self.assertEqual(informe.estado, "verificada", informe.diagnostico)
        self.assertTrue(informe.aceptacion.ok)


class TestPlantillasRutaConEspacios(BaseTest):
    @unittest.skipUnless(shutil.which("prove") and shutil.which("perl"), "perl/prove no instalados")
    def test_perl_conversor_en_carpeta_con_espacios(self):
        # Termux: "/storage/emulated/0/Mis proyectos" es habitual. El test de la plantilla invocaba el script por
        # shell sin comillas y fallaba con "Can't open perl script".
        destino = self.dir / "mis proyectos" / "demo perl"
        crear_desde_plantilla("perl-conversor", destino)
        r = ejecutar("prove -l t", cwd=destino, timeout=120, shell=True)
        self.assertTrue(r.ok, r.resumen(1500))


class TestHooksDelRepoSinConsentimiento(BaseTest):
    def test_hook_al_iniciar_de_un_repo_no_corre_sin_autorizacion(self):
        from unittest.mock import patch
        marca = self.dir / "PWNED"
        ws = self.proyecto({".reaper/config.json": json.dumps({"hooks": {"al_iniciar": [f"touch {marca}"]}})})
        app = App(self.ajustes(), MockLLM([]), self.ui(), ws, persistir=False)
        with patch("builtins.input", side_effect=EOFError):
            app.repl(animar=False)
        self.assertFalse(marca.exists())                             # antes: se ejecutaba al abrir el repo


class TestHallazgosTermux(BaseTest):
    """Fallos vistos al correr el autotest en el Termux real del usuario (Python 3.14, pytest instalado)."""

    def test_pytest_con_todo_salteado_se_reconoce(self):
        for salida, omitidos in (("s                                  [100%]\n1 skipped in 0.01s", 1),
                                 ("3 deselected in 0.02s", 3), ("xx\n2 xfailed in 0.10s", 2)):
            with self.subTest(salida=salida):
                c = contar_tests(salida, 0)
                self.assertTrue(c.reconocido)
                self.assertEqual((c.ejecutados, c.omitidos), (0, omitidos))   # antes: "1 pasó" por exit 0

    def test_suite_pytest_toda_salteada_no_verifica(self):
        from unittest.mock import patch
        ws = self.proyecto({"app.py": "x = 1\n", "tests/test_app.py": "import pytest\n"})
        falso = Resultado(True, "python -m pytest -q", 0, "s    [100%]\n1 skipped in 0.01s")
        orq = Orquestador(MockLLM([]), ws, self.ajustes(forense=False, lecciones=False), self.ui())
        with patch.dict(Orquestador.verificar.__globals__, {"ejecutar_tests": lambda *a, **k: falso}):
            verif = orq.verificar(ws.checkpoints.iniciar("x"))
        self.assertFalse(verif.ok)
        self.assertIn("OMITIDOS", verif.diagnostico)

    def test_requisito_de_libreria_se_comprueba_de_verdad(self):
        self.assertFalse(requisito_disponible("herramienta_que_no_existe_xyz"))
        self.assertFalse(requisito_disponible("python3:modulo_que_no_existe_xyz"))
        self.assertTrue(requisito_disponible("python3:json"))
        self.assertIn("gem install minitest", instruccion_requisito("ruby:minitest"))


class TestFlujoConstruirUI(BaseTest):
    def test_resumen_diff_compacto(self):
        diff = ("--- a/app.py\n+++ b/app.py\n@@\n+uno\n+dos\n-viejo\n"
                "--- a/web.js\n+++ b/web.js\n@@\n+x\n")
        self.assertEqual(_resumen_diff(diff), "2 archivo(s) · +3 −1")
        self.assertEqual(_resumen_diff(""), "")

    def test_cierre_en_caja_con_insignia(self):
        ws = self.proyecto({"a.py": "x = 1\n"})
        orq = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        informe = InformeBuild("verificada", segundos=12.3, commit="a1b2c3d4e5")
        orq._mostrar_cierre(informe)
        texto = orq.ui.texto_registrado()
        self.assertIn("BUILD VERIFICADA", texto)
        self.assertIn("╭", texto)                       # va en caja
        caja = [l for l in texto.splitlines() if l and l[0] in "╭│╰"]
        self.assertEqual(len({ancho_visible(l) for l in caja}), 1)   # alineada
        informe_mal = InformeBuild("fallida", segundos=1.0)
        orq2 = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        orq2._mostrar_cierre(informe_mal)
        self.assertIn("BUILD FALLIDA", orq2.ui.texto_registrado())

    def test_checklist_del_plan_lista_las_tareas(self):
        plan = parsear_plan('<plan>\n<objetivo>x</objetivo>\n'
                            '<tarea id="1" archivos="a.py">Crear a.py</tarea>\n'
                            '<tarea id="2" archivos="b.py" deps="1">Crear b.py</tarea>\n</plan>', 'dos archivos')
        ws = self.proyecto()
        orq = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        orq._checklist_plan(plan, GrafoTareas(plan.tareas))
        texto = orq.ui.texto_registrado()
        self.assertIn("Plan · 2 tareas", texto)
        self.assertIn("Crear a.py", texto)
        self.assertIn("← 1", texto)                      # la tarea 2 depende de la 1
