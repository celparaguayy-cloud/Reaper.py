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
