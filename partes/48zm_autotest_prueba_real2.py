"""
Segunda prueba REAL de /grande en el teléfono (Termux, modelos :free): la etapa 1 quedó horas en reparaciones.

- El especificador escribió tests/test_cli.py con `from almacen import __main__` y `main([...])` SIN importar main
  (NameError). Solo se rechazaba la sintaxis: el test roto quedó PROTEGIDO y nadie lo podía corregir.
- El reparador "lo arregló" inyectando main en el módulo del test (`sys._getframe(1).f_globals['main'] = main`) y
  hasta pisó el test con `cp tests/test_cli.py.backup tests/test_cli.py` por la terminal.
- El arquitecto planeó "Escribir la prueba unitaria" como TAREA aunque la especificación ya la había escrito: SIN
  PROGRESO → 2 reparaciones y modo forense sin nada que hacer.
- Los modelos escribieron <search>/<replace> dentro de replace_in_file y write_to_file con el código en ``` sin
  <content>; cada modelo volvía a "pensar sin responder" en cada corrida; un implementador repitió 60 veces la misma
  lectura.
"""

_PR2_TEST_ROTO = ("import unittest\nfrom unittest import mock\n\nfrom almacen import __main__\n\n\n"
                  "class TestCLI(unittest.TestCase):\n    def test_main_llama_run_server(self):\n"
                  "        with mock.patch('almacen.__main__.run_server') as run:\n"
                  "            main(['--puerto', '9999'])\n        run.assert_called_once_with(9999)\n")
_PR2_TEST_BIEN = _PR2_TEST_ROTO.replace("from almacen import __main__\n",
                                        "from almacen import __main__\nfrom almacen.__main__ import main\n")
_PR2_MAIN = ("import argparse\n\nfrom almacen.server import run_server\n\n\ndef main(args=None):\n"
             "    parser = argparse.ArgumentParser(prog='almacen')\n"
             "    parser.add_argument('--puerto', type=int, default=8000)\n"
             "    run_server(parser.parse_args(args).puerto)\n\n\nif __name__ == '__main__':\n    main()\n")
_PR2_SERVER = "def run_server(puerto):\n    raise SystemExit(f'servidor en {puerto}')\n"
_PR2_TRAMPA = _PR2_MAIN + "\nimport sys\nsys._getframe(1).f_globals['main'] = main\n"
_PR2_PLAN = ('<plan><objetivo>CLI</objetivo><criterios>- main(--puerto) llama a run_server</criterios>'
             '<tarea id="1" archivos="almacen/__init__.py, almacen/__main__.py, almacen/server.py, tests/test_cli.py">'
             'main y run_server con su test</tarea></plan>')


class TestEspecificacionConNombresSinImportar(BaseTest):
    def _especificar(self, arregla: bool):
        ws = self.proyecto({})
        pedidos = []

        def guion(mensajes, kw):
            if MockLLM.rol_de(mensajes) != "especificador":
                return terminar_xml("listo")
            primero = next((m["content"] for m in mensajes if m["role"] == "user"), "")
            if MockLLM.turnos_asistente(mensajes) == 0:
                pedidos.append(primero)
                corregir = "errores PROPIOS" in primero
                contenido = _PR2_TEST_BIEN if (corregir and arregla) else _PR2_TEST_ROTO
                return herramienta_xml("write_to_file", path="tests/test_cli.py", content=contenido)
            return terminar_xml("tests escritos")
        ui = self.ui()
        orq = Orquestador(MockLLM(guion), ws, self.ajustes(tests_primero=True), ui)
        plan = Plan("CLI", [Tarea("1", "main", ["almacen/__main__.py", "tests/test_cli.py"])], [])
        espec = orq.especificar("CLI del almacén", plan, ws.checkpoints.iniciar("espec"))
        return ws, espec, pedidos, ui.texto_registrado()

    def test_un_test_que_usa_main_sin_importarlo_se_manda_a_corregir(self):
        ws, espec, pedidos, texto = self._especificar(arregla=True)
        self.assertEqual(len(pedidos), 2)                                           # se le pidió corregir
        self.assertIn("main", pedidos[1])
        self.assertIn("tests/test_cli.py", espec)                                   # y queda protegido, ya bien
        self.assertIn("from almacen.__main__ import main", espec["tests/test_cli.py"])
        self.assertIn("están rotos", texto)

    def test_si_sigue_roto_no_se_protege(self):
        _ws, espec, pedidos, texto = self._especificar(arregla=False)
        self.assertEqual(len(pedidos), 2)
        self.assertNotIn("tests/test_cli.py", espec)                                # lo puede corregir otro
        self.assertIn("no los protejo", texto)


class TestTestProtegidoSoloAgregarImports(BaseTest):
    def test_solo_agrega_imports(self):
        self.assertTrue(solo_agrega_imports(_PR2_TEST_ROTO, _PR2_TEST_BIEN))
        self.assertTrue(solo_agrega_imports("x = 1\n", "import os\nfrom a.b import (c, d)\n\nx = 1\n"))
        self.assertFalse(solo_agrega_imports(_PR2_TEST_ROTO, _PR2_TEST_BIEN.replace("9999)", "1)")))   # toca un assert
        self.assertFalse(solo_agrega_imports(_PR2_TEST_ROTO, _PR2_TEST_ROTO.replace(
            "        run.assert_called_once_with(9999)\n", "")))                                    # borra una línea
        self.assertFalse(solo_agrega_imports("x = 1\n", "x = 1\ny = 2\n"))
        self.assertFalse(solo_agrega_imports("x = 1\n", "x = 1\n"))

    def test_la_herramienta_deja_agregar_el_import_y_nada_mas(self):
        ws = self.proyecto({"tests/test_cli.py": _PR2_TEST_ROTO})
        ctx = self.contexto(ws)
        ctx.protegidos = {"tests/test_cli.py"}
        self.herramienta(ctx, "write_to_file", path="tests/test_cli.py", content=_PR2_TEST_BIEN)
        self.assertEqual(ws.leer("tests/test_cli.py"), _PR2_TEST_BIEN)
        with self.assertRaises(ErrorHerramienta) as error:
            self.herramienta(ctx, "write_to_file", path="tests/test_cli.py", content=_PR2_TEST_BIEN.replace("9999)", "1)"))
        self.assertIn("parte de la especificación", str(error.exception))
        self.assertEqual(ws.leer("tests/test_cli.py"), _PR2_TEST_BIEN)

    def test_el_custodio_acepta_imports_y_revierte_lo_demas(self):
        ws = self.proyecto({"tests/test_cli.py": _PR2_TEST_ROTO})
        ui = self.ui()
        orq = Orquestador(MockLLM(lambda m, k: terminar_xml("x")), ws, self.ajustes(), ui)
        orq._protegidos = {"tests/test_cli.py": _PR2_TEST_ROTO}
        (ws.raiz / "tests/test_cli.py").write_text(_PR2_TEST_BIEN, encoding="utf-8")       # p. ej. por la terminal
        orq._custodiar_protegidos()
        self.assertEqual(orq._protegidos["tests/test_cli.py"], _PR2_TEST_BIEN)
        self.assertIn("se le agregaron imports", ui.texto_registrado())
        (ws.raiz / "tests/test_cli.py").write_text("import unittest\n", encoding="utf-8")   # cp de un backup
        orq._custodiar_protegidos()
        self.assertEqual(ws.leer("tests/test_cli.py"), _PR2_TEST_BIEN)
        self.assertIn("lo restauré", ui.texto_registrado())


class TestTrampasParaLosTests(BaseTest):
    def test_inyectar_main_en_el_modulo_del_test_es_una_trampa(self):
        ws = self.proyecto({"almacen/__init__.py": "", "almacen/server.py": _PR2_SERVER,
                            "almacen/__main__.py": _PR2_TRAMPA, "tests/test_x.py": _PR2_TRAMPA})
        malos = [r.comando.split()[0] for r in fallos(validar_archivos(ws, ["almacen/__main__.py"]))]
        self.assertIn("trampas", malos)
        self.assertNotIn("trampas", [r.comando.split()[0] for r in validar_archivos(ws, ["tests/test_x.py"])])
        self.assertEqual(trampas_para_tests(_PR2_MAIN), [])
        self.assertEqual(trampas_para_tests("import builtins\nbuiltins._ = str\n"), [])     # gettext: legítimo

    def test_el_reparador_arregla_el_test_protegido_con_el_import(self):
        # El caso del teléfono al retomar: el test roto YA está protegido (existía al empezar la build). Antes no había
        # salida; ahora el reparador agrega el import (lo único permitido) y la build queda verificada.
        ws = self.proyecto({"tests/__init__.py": "", "tests/test_cli.py": _PR2_TEST_ROTO})
        vistos = []

        def guion(mensajes, kw):
            rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
            if rol == "arquitecto":
                return terminar_xml(_PR2_PLAN.replace(", tests/test_cli.py", ""))
            if rol == "implementador":
                archivos = [("almacen/__init__.py", ""), ("almacen/server.py", _PR2_SERVER),
                            ("almacen/__main__.py", _PR2_MAIN)]
                if turno < len(archivos):
                    return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
                return terminar_xml("listo")
            if rol == "reparador":
                vistos.append(MockLLM.ultimo_usuario(mensajes) if turno == 0 else "")
                if turno == 0:
                    return herramienta_xml("write_to_file", path="tests/test_cli.py", content=_PR2_TEST_BIEN)
            return terminar_xml("listo")
        ui = self.ui()
        informe = Orquestador(MockLLM(guion), ws, self.ajustes(juez=False), ui).construir(
            "CLI del almacén con --puerto", confirmar=False)
        texto = ui.texto_registrado()
        self.assertTrue(informe.ok, texto[-3000:])
        self.assertIn("AGREGARLE las líneas import", vistos[0])                   # se le dijo qué puede hacer
        self.assertEqual(ws.leer("tests/test_cli.py"), _PR2_TEST_BIEN)


class TestTareaYaEscritaPorLaEspecificacion(BaseTest):
    def test_tarea_de_solo_tests_ya_escritos_no_corre_implementadores(self):
        ws = self.proyecto({})
        tareas_impl = []
        plan = ('<plan><objetivo>CLI</objetivo><criterios>- main llama a run_server</criterios>'
                '<tarea id="1" archivos="tests/test_cli.py">Escribir la prueba unitaria de main</tarea>'
                '<tarea id="2" archivos="almacen/__init__.py, almacen/__main__.py, almacen/server.py" deps="1">'
                'main y run_server</tarea></plan>')

        def guion(mensajes, kw):
            rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
            if rol == "arquitecto":
                return terminar_xml(plan)
            if rol == "especificador" and turno == 0:
                return herramienta_xml("write_to_file", path="tests/test_cli.py", content=_PR2_TEST_BIEN)
            if rol == "implementador":
                if turno == 0:
                    tareas_impl.append(re.search(r"TU TAREA AHORA \(#(\d+)\)", MockLLM.ultimo_usuario(mensajes)).group(1))
                archivos = [("almacen/__init__.py", ""), ("almacen/server.py", _PR2_SERVER),
                            ("almacen/__main__.py", _PR2_MAIN)]
                if turno < len(archivos):
                    return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
            return terminar_xml("listo")
        ui = self.ui()
        informe = Orquestador(MockLLM(guion), ws, self.ajustes(tests_primero=True, juez=False), ui).construir(
            "CLI del almacén", confirmar=False)
        texto = ui.texto_registrado()
        self.assertTrue(informe.ok, texto[-3000:])
        self.assertEqual(tareas_impl, ["2"])                                         # la 1 no gasta implementadores
        self.assertIn("ya lo escribió la especificación", texto)


class TestFormatosDeHerramientasDeModelosReales(BaseTest):
    def _una(self, texto):
        llamadas = analizar(texto, esquemas()).llamadas
        self.assertEqual(len(llamadas), 1, llamadas)
        return llamadas[0]

    def test_search_replace_como_etiquetas(self):
        ll = self._una("<replace_in_file>\n<path>a.py</path>\n<search>\nx = 1\n</search>\n<replace>\nx = 2\n</replace>\n"
                       "</replace_in_file>")
        self.assertEqual(ll.params["diff"], "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE")
        sin_cierre = self._una("<replace_in_file>\n<path>a.py</path>\n<old>\nx = 1\n</old>\n<new>\nx = 2\n</new>\n"
                               "</file>\nListo.")
        self.assertEqual(sin_cierre.nombre, "replace_in_file")                    # no un search_files fantasma
        self.assertIn(">>>>>>> REPLACE", sin_cierre.params["diff"])

    def test_bloques_search_replace_sin_etiqueta_diff(self):
        ll = self._una("<replace_in_file>\n<path>a.py</path>\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"
                       "</replace_in_file>")
        self.assertTrue(ll.params["diff"].startswith("<<<<<<< SEARCH"))

    def test_write_to_file_con_el_codigo_en_un_bloque(self):
        ll = self._una("<write_to_file>\n<path>almacen/server.py</path>\n```python\nimport http.server\n```\n"
                       "</write_to_file>")
        self.assertEqual(ll.params["content"].strip(), "import http.server")
        acento = self._una("<write_to_file>\n<archivo>a.py</archivo>\n<código>\nx = 1\n</código>\n</write_to_file>")
        self.assertEqual(acento.params, {"path": "a.py", "content": "x = 1"})

    def test_aplicado_de_punta_a_punta(self):
        ws = self.proyecto({"a.py": "x = 1\n"})
        ctx = self.contexto(ws)
        ll = self._una("<replace_in_file>\n<path>a.py</path>\n<search>x = 1</search>\n<replace>x = 2</replace>\n"
                       "</replace_in_file>")
        self.herramienta(ctx, "replace_in_file", **ll.params)
        self.assertEqual(ws.leer("a.py"), "x = 2\n")


class TestModelosQueRepitenYQuePiensan(BaseTest):
    def test_el_razonamiento_aprendido_se_recuerda_entre_corridas(self):
        ruta = self.dir / "razonamiento.json"
        guardar_razonamiento_aprendido({"cohere/north-mini-code:free": "none", "x": None}, ruta)
        self.assertEqual(cargar_razonamiento_aprendido(ruta), {"cohere/north-mini-code:free": "none"})
        viejo = {"m": {"nivel": "low", "ts": time.time() - (HORAS_RAZONAMIENTO_APRENDIDO + 1) * 3600}}
        ruta.write_text(json.dumps(viejo), encoding="utf-8")
        self.assertEqual(cargar_razonamiento_aprendido(ruta), {})                   # vence a las 24 h
        self.assertEqual(cargar_razonamiento_aprendido(self.dir / "no_existe.json"), {})

    def test_la_misma_lectura_repetida_sin_fin_se_corta(self):
        ws = self.proyecto({"a.py": "x = 1\n"})
        lectura = "\n".join([herramienta_xml("read_file", path="a.py")] * 4)
        llm = MockLLM(lambda m, k: lectura)
        res = Agente("implementador", llm, ws, self.ajustes(max_pasos=25, max_llamadas_turno=8, forense=False,
                                                           escalar=False), self.ui()).ejecutar("Implementá algo en a.py")
        self.assertFalse(res.ok)
        self.assertLess(len(llm.llamadas), 10)                                       # antes: hasta max_pasos (25)

    def test_perfil_gratis_saca_roles_en_gratis_que_hoy_no_responden(self):
        ajustes = self.ajustes(proveedor="openrouter", modelos_rol={
            "reparador": "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
            "juez": "nvidia/nemotron-3.5-lightning:free"})
        cambios = aplicar_perfil(ajustes, "gratis", ["cohere/north-mini-code:free", "nvidia/nemotron-3.5-lightning:free"])
        self.assertNotIn("reparador", ajustes.modelos_rol)
        self.assertEqual(ajustes.modelos_rol.get("juez"), "nvidia/nemotron-3.5-lightning:free")
        self.assertTrue(any("no está entre los gratis de hoy" in c for c in cambios))
        self.assertEqual(ajustes.rpm, 14)                                            # cohere: 15 por minuto


class TestEspecificacionPropiaEnRojo(BaseTest):
    def test_la_tarea_no_queda_verificada_con_su_especificacion_en_rojo(self):
        # El test de la especificación sigue roto (no se protege) y falla ANTES y DESPUÉS de la tarea con los mismos
        # nombres: antes no contaba como regresión y la tarea quedaba "verificada"; lo atajaba la reparación final.
        ws = self.proyecto({"tests/__init__.py": ""})

        def guion(mensajes, kw):
            rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
            primero = MockLLM.ultimo_usuario(mensajes) if turno == 0 else ""
            if rol == "arquitecto":
                return terminar_xml(_PR2_PLAN)
            if rol == "especificador" and turno == 0:
                return herramienta_xml("write_to_file", path="tests/test_cli.py", content=_PR2_TEST_ROTO)
            if rol == "implementador":
                archivos = [("almacen/__init__.py", ""), ("almacen/server.py", _PR2_SERVER),
                            ("almacen/__main__.py", _PR2_MAIN)]
                if turno < len(archivos):
                    return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
            if rol == "reparador" and turno == 0 and "F821" in primero:
                return herramienta_xml("write_to_file", path="tests/test_cli.py", content=_PR2_TEST_BIEN)
            return terminar_xml("listo")
        ui = self.ui()
        informe = Orquestador(MockLLM(guion), ws, self.ajustes(tests_primero=True, juez=False), ui).construir(
            "CLI del almacén con --puerto", confirmar=False)
        texto = ui.texto_registrado()
        if not shutil.which("ruff"):
            self.skipTest("sin ruff el diagnóstico no trae el código F821")
        self.assertTrue(informe.ok, texto[-3000:])
        self.assertRegex(texto, r"La tarea \d+ no pasó su verificación")
        self.assertNotIn("REPARACIÓN final", texto)                                # se arregla en la tarea
