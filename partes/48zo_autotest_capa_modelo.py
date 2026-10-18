"""
Capa de interacción con el modelo, probada con lo que mandan de verdad los modelos gratis flojos (north-mini-code,
nemotron-3.5-lightning, nemotron-3.5-super-vl, nemotron-3-super-120b):

- Formatos de llamada: "tool calling" nativo (<tool_call>{json}</tool_call> de Hermes/Qwen/Nemotron, [TOOL_CALLS] de
  Mistral, objetos function de OpenAI, listas JSON en ```json), <function=x><parameter=y> de Llama/Nemotron, XML de
  REAPER con alias y basura alrededor. Antes 11 de estos 30 se perdían ("sin herramientas") o salían mal.
- Respuestas cortadas por longitud en esos formatos: se marcan incompletas para continuar el archivo, no escribir
  medio archivo como si estuviera entero.
- Mensajes correctores: qué falta exactamente y cómo se escribe.
- Bucle: "voy a leer X" / "listo, terminé" sin herramienta, respuestas vacías y errores de formato que se comían
  los pasos.
"""

_CM_CORPUS = {
    "hermes_tool_call": ('Voy a crear el archivo.\n<tool_call>\n{"name": "write_to_file", "arguments": '
                         '{"path": "a.py", "content": "x = 1\\n"}}\n</tool_call>',
                         [("write_to_file", {"path": "a.py", "content": "x = 1\n"})]),
    "hermes_dos": ('<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>\n'
                   '<tool_call>{"name": "read_file", "arguments": {"path": "b.py"}}</tool_call>',
                   [("read_file", {"path": "a.py"}), ("read_file", {"path": "b.py"})]),
    "hermes_args_str": ('<tool_call>\n{"name": "execute_command", "arguments": "{\\"command\\": \\"ls -la\\"}"}\n'
                        '</tool_call>', [("execute_command", {"command": "ls -la"})]),
    "llama_param": ('<function=write_to_file>\n<parameter=path>\nalmacen/db.py\n</parameter>\n<parameter=content>\n'
                    'import sqlite3\n</parameter>\n</function>',
                    [("write_to_file", {"path": "almacen/db.py", "content": "import sqlite3"})]),
    "llama_param_sin_cierre": ('<function=read_file>\n<parameter=path>almacen/db.py</parameter>\n',
                               [("read_file", {"path": "almacen/db.py"})]),
    "mistral": ('[TOOL_CALLS][{"name": "read_file", "arguments": {"path": "a.py"}}]', [("read_file", {"path": "a.py"})]),
    "mistral_dos": ('[TOOL_CALLS] [{"name": "list_files", "arguments": {}}, {"name": "read_file", "arguments": '
                    '{"path": "a.py"}}]', [("list_files", {}), ("read_file", {"path": "a.py"})]),
    "json_fence_tool": ('```json\n{"tool": "read_file", "args": {"path": "a.py"}}\n```', [("read_file", {"path": "a.py"})]),
    "json_fence_name_arguments": ('Ahora:\n```json\n{"name": "run_tests", "arguments": {}}\n```', [("run_tests", {})]),
    "xml_en_fence": ('```xml\n<read_file>\n<path>a.py</path>\n</read_file>\n```', [("read_file", {"path": "a.py"})]),
    "write_en_fence_xml": ('```xml\n<write_to_file>\n<path>a.py</path>\n<content>\nx = 1\n</content>\n</write_to_file>\n```',
                           [("write_to_file", {"path": "a.py", "content": "x = 1"})]),
    "atributos": ('<read_file path="a.py" desde="1" hasta="20"/>',
                  [("read_file", {"path": "a.py", "desde": "1", "hasta": "20"})]),
    "contenido": ('<write_to_file>\n<ruta>a.py</ruta>\n<contenido>\nx = 1\n</contenido>\n</write_to_file>',
                  [("write_to_file", {"path": "a.py", "content": "x = 1"})]),
    "fence_sin_content": ('<write_to_file>\n<path>a.py</path>\n```python\nx = 1\n```\n</write_to_file>',
                          [("write_to_file", {"path": "a.py", "content": "x = 1"})]),
    "search_replace_tags": ('<replace_in_file>\n<path>a.py</path>\n<search>x = 1</search>\n<replace>x = 2</replace>\n'
                            '</replace_in_file>',
                            [("replace_in_file", {"path": "a.py",
                                                  "diff": "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"})]),
    "cierre_file": ('<replace_in_file>\n<path>a.py</path>\n<diff>\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n'
                    '>>>>>>> REPLACE\n</diff>\n</file>',
                    [("replace_in_file", {"path": "a.py",
                                          "diff": "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"})]),
    "label_basura": ('VEO EL PROBLEMA.\n<label>HECHO</label>\n<read_file>\n<path>almacen/sales.py</path>\n</read_file>',
                     [("read_file", {"path": "almacen/sales.py"})]),
    "ahora_mezclado": ('AHORA: voy a escribir el test.\n<write_to_file>\n<path>tests/test_a.py</path>\n<content>\n'
                       'import unittest\n</content>\n</write_to_file>\nAHORA: listo.',
                       [("write_to_file", {"path": "tests/test_a.py", "content": "import unittest"})]),
    "sin_cerrar_final": ('<read_file>\n<path>a.py</path>', [("read_file", {"path": "a.py"})]),
    "repetidas": ("\n".join(['<read_file>\n<path>a.py</path>\n</read_file>'] * 5), [("read_file", {"path": "a.py"})] * 5),
    "tool_name_attr": ('<tool name="read_file">\n<parameter name="path">a.py</parameter>\n</tool>',
                       [("read_file", {"path": "a.py"})]),
    "invoke_param": ('<invoke name="write_to_file">\n<parameter name="path">a.py</parameter>\n'
                     '<parameter name="content">x = 1\n</parameter>\n</invoke>',
                     [("write_to_file", {"path": "a.py", "content": "x = 1"})]),
    "function_calls_wrapper": ('<function_calls>\n<invoke name="read_file">\n<parameter name="path">a.py</parameter>\n'
                               '</invoke>\n</function_calls>', [("read_file", {"path": "a.py"})]),
    "tool_use_json": ('<tool_use>\n{"name": "read_file", "input": {"path": "a.py"}}\n</tool_use>',
                      [("read_file", {"path": "a.py"})]),
    "openai_function_obj": ('{"type": "function", "function": {"name": "read_file", "arguments": "{\\"path\\": '
                            '\\"a.py\\"}"}}', [("read_file", {"path": "a.py"})]),
    "function_json_body": ('<function=read_file>{"path": "a.py"}</function>', [("read_file", {"path": "a.py"})]),
    "attempt_completion_result": ('<attempt_completion>\n<result>\nListo: implementé sumar.\n</result>\n'
                                  '</attempt_completion>', [("attempt_completion", {"result": "Listo: implementé sumar."})]),
    "codigo_tag": ('<write_to_file>\n<archivo>a.py</archivo>\n<código>\nx = 1\n</código>\n</write_to_file>',
                   [("write_to_file", {"path": "a.py", "content": "x = 1"})]),
    "tool_call_xml_dentro": ('<tool_call>\n<read_file>\n<path>a.py</path>\n</read_file>\n</tool_call>',
                             [("read_file", {"path": "a.py"})]),
    "json_lista_fence": ('```json\n[{"name": "read_file", "arguments": {"path": "a.py"}}]\n```',
                         [("read_file", {"path": "a.py"})]),
}

_CM_CALC = "def sumar(a, b):\n    return a + b\n"


def _cm_normalizar(llamadas) -> list:
    return [(n, {k: (v.strip() if isinstance(v, str) else v) for k, v in p.items()}) for n, p in llamadas]


class TestCapaModeloFormatos(BaseTest):
    def test_corpus_de_formatos_reales(self):
        for caso, (texto, esperado) in _CM_CORPUS.items():
            with self.subTest(caso=caso):
                analisis = analizar(texto, esquemas())
                obtenido = [(l.nombre, dict(l.params)) for l in analisis.llamadas]
                self.assertEqual(_cm_normalizar(obtenido), _cm_normalizar(esperado))
                self.assertTrue(all(l.completa for l in analisis.llamadas), caso)

    def test_el_texto_alrededor_del_json_sigue_visible(self):
        analisis = analizar('Voy a crear el archivo.\n<tool_call>\n{"name": "read_file", "arguments": '
                            '{"path": "a.py"}}\n</tool_call>', esquemas())
        self.assertEqual(analisis.texto, "Voy a crear el archivo.")
        mistral = analizar('Leo primero.[TOOL_CALLS][{"name": "read_file", "arguments": {"path": "a.py"}}]', esquemas())
        self.assertEqual(mistral.texto, "Leo primero.")

    def test_json_de_datos_no_es_una_llamada(self):
        self.assertEqual(analizar('{"name": "Juan", "edad": 3}', esquemas()).llamadas, [])
        self.assertEqual(analizar('```json\n[{"name": "Ana", "id": 1}]\n```', esquemas()).llamadas, [])

    def test_saltos_de_linea_crudos_dentro_del_json(self):
        texto = '<tool_call>\n{"name": "write_to_file", "arguments": {"path": "a.py", "content": "x = 1\ny = 2\n"}}\n</tool_call>'
        llamada = analizar(texto, esquemas()).llamadas[0]
        self.assertEqual(llamada.params["content"], "x = 1\ny = 2\n")


class TestCapaModeloCortes(BaseTest):
    def test_llama_cortado_queda_incompleto_con_el_parcial(self):
        texto = ('<function=write_to_file>\n<parameter=path>\na.py\n</parameter>\n<parameter=content>\n'
                 'import os\ndef f():\n    ret')
        llamada = analizar(texto, esquemas()).llamadas[0]
        self.assertFalse(llamada.completa)                               # antes: True → medio archivo "entero"
        self.assertEqual(llamada.sin_cierre, frozenset({"content"}))
        self.assertEqual(contenido_parcial(llamada, esquemas()), ("content", "import os\ndef f():\n    ret"))
        cerrada = analizar(texto + "urn 1\n</parameter>\n</function>", esquemas()).llamadas[0]
        self.assertTrue(cerrada.completa)
        sin_fin_param = analizar('<function=write_to_file>\n<parameter=path>a.py</parameter>\n<parameter=content>\n'
                                 'x = 1\n</function>', esquemas()).llamadas[0]
        self.assertTrue(sin_fin_param.completa)                          # </function> delimita el contenido

    def test_json_nativo_cortado_se_rescata_incompleto(self):
        hermes = analizar('Escribo.\n<tool_call>\n{"name": "write_to_file", "arguments": {"path": "a.py", '
                          '"content": "import os\\ndef f(', esquemas())
        self.assertEqual(len(hermes.llamadas), 1)                         # antes: 0 llamadas ("sin herramientas")
        llamada = hermes.llamadas[0]
        self.assertEqual((llamada.nombre, llamada.completa, llamada.params["path"]), ("write_to_file", False, "a.py"))
        self.assertEqual(contenido_parcial(llamada, esquemas()), ("content", "import os\ndef f("))
        self.assertEqual(hermes.texto, "Escribo.")
        mistral = analizar('[TOOL_CALLS][{"name": "write_to_file", "arguments": {"path": "a.py", "content": '
                           '"x = 1\\ny = \\u00', esquemas()).llamadas[0]
        self.assertEqual(mistral.params["content"], "x = 1\ny = ")      # el \u00 cortado no rompe nada
        llama_json = analizar('<function=write_to_file>{"path": "a.py", "content": "a\\nb', esquemas()).llamadas[0]
        self.assertFalse(llama_json.completa)
        self.assertEqual(llama_json.params, {"path": "a.py", "content": "a\nb"})

    def test_una_ruta_cortada_no_se_usa(self):
        llamada = analizar('<tool_call>\n{"name": "write_to_file", "arguments": {"path": "a.p', esquemas()).llamadas[0]
        self.assertFalse(llamada.completa)
        self.assertNotIn("path", llamada.params)

    def test_continua_un_archivo_cortado_en_formato_llama(self):
        ws = self.proyecto({})
        vistos = []
        primera = ('<function=write_to_file>\n<parameter=path>calc.py</parameter>\n<parameter=content>\n'
                   'def sumar(a, b):\n    return a + b\n\n\ndef restar(a, b):\n    ret')

        def guion(mensajes, kw):
            vistos.append(MockLLM.ultimo_usuario(mensajes))
            turno = MockLLM.turnos_asistente(mensajes)
            if turno == 0:
                return primera, "length"
            if turno == 1:
                return herramienta_xml("append_to_file", path="calc.py", content="    return a - b\n", last="true")
            return terminar_xml("calc.py con sumar y restar")
        res = Agente("implementador", MockLLM(guion), ws, self.ajustes(forense=False), self.ui()).ejecutar(
            "Creá calc.py con sumar y restar")
        self.assertIn("SEGUÍ DESDE", vistos[1])
        self.assertEqual(ws.leer("calc.py"), "def sumar(a, b):\n    return a + b\n\n\ndef restar(a, b):\n"
                                             "    return a - b\n")
        self.assertEqual(res.motivo, "completado")

    def test_continua_un_archivo_cortado_en_tool_call_json(self):
        ws = self.proyecto({})
        vistos = []
        primera = ('<tool_call>\n{"name": "write_to_file", "arguments": {"path": "calc.py", "content": '
                   '"def sumar(a, b):\\n    return a + b\\n\\n\\ndef restar(a, b):\\n    ret')

        def guion(mensajes, kw):
            vistos.append(MockLLM.ultimo_usuario(mensajes))
            turno = MockLLM.turnos_asistente(mensajes)
            if turno == 0:
                return primera, "length"
            if turno == 1:
                return herramienta_xml("append_to_file", path="calc.py", content="    return a - b\n", last="true")
            return terminar_xml("listo")
        Agente("implementador", MockLLM(guion), ws, self.ajustes(forense=False), self.ui()).ejecutar(
            "Creá calc.py con sumar y restar")
        self.assertIn("SEGUÍ DESDE", vistos[1])
        self.assertIn("def restar(a, b):\n    return a - b", ws.leer("calc.py"))


class TestCapaModeloMensajes(BaseTest):
    def _agente(self, rol: str = "implementador"):
        ws = self.proyecto({"calc.py": _CM_CALC})
        agente = Agente(rol, MockLLM([]), ws, self.ajustes(), self.ui())
        return agente

    def test_herramienta_inexistente_sugiere_la_parecida_con_ejemplo(self):
        agente = self._agente()
        llamada = analizar('<tool_call>{"name": "writefile", "arguments": {"path": "a.py", "content": "x"}}</tool_call>',
                           esquemas()).llamadas[0]
        agente._ultima_llamada = llamada
        obs, error = agente._ejecutar_herramienta(llamada, {})
        self.assertTrue(error)
        self.assertIn("¿Quisiste decir write_to_file?", obs)
        self.assertIn(REGISTRO["write_to_file"].ejemplo, obs)

    def test_faltan_parametros_nombra_las_etiquetas_que_no_reconoce(self):
        agente = self._agente()
        llamada = analizar('<write_to_file>\n<path>a.py</path>\n<codigo_fuente>\nx = 1\n</codigo_fuente>\n'
                           '</write_to_file>', esquemas()).llamadas[0]
        agente._ultima_llamada = llamada
        obs, error = agente._ejecutar_herramienta(llamada, {})
        self.assertTrue(error)
        self.assertIn("faltan parámetros: content", obs)
        self.assertIn("No reconozco <codigo_fuente>", obs)
        self.assertIn("<content>", obs)
        self.assertFalse((agente.ws.raiz / "a.py").exists())

    def test_llamada_incompleta_dice_que_cerrar_y_muestra_el_ejemplo(self):
        agente = self._agente()
        llamada = Llamada("write_to_file", {"path": "a.py"}, False, "<write_to_file>\n<path>a.py</path>\n<content>\nx",
                          frozenset({"content"}))
        agente._ultima_llamada = Llamada("read_file", {"path": "calc.py"}, True, "")
        obs, error = agente._ejecutar_herramienta(llamada, {})
        self.assertTrue(error)
        self.assertIn("falta cerrar con </content> y </write_to_file>", obs)
        self.assertIn("Reenviala completa, así:\n" + REGISTRO["write_to_file"].ejemplo, obs)


class TestCapaModeloBucle(BaseTest):
    def test_si_anuncia_que_lee_un_archivo_lo_lee_reaper(self):
        ws = self.proyecto({"almacen/db.py": "def conectar(ruta):\n    return ruta\n"})
        vistos = []

        def guion(mensajes, kw):
            vistos.append(MockLLM.ultimo_usuario(mensajes))
            if MockLLM.turnos_asistente(mensajes) == 0:
                return "Primero voy a leer almacen/db.py para entender la conexión."
            return terminar_xml("Revisé la conexión.")
        Agente("reparador", MockLLM(guion), ws, self.ajustes(forense=False), self.ui()).ejecutar(
            "Arreglá la conexión")
        self.assertIn("lo leí yo", vistos[1])                             # antes: "No usaste ninguna herramienta"
        self.assertIn("def conectar(ruta):", vistos[1])
        self.assertIn("<read_file>\n<path>almacen/db.py</path>\n</read_file>", vistos[1])

    def test_no_lee_rutas_inexistentes(self):
        ws = self.proyecto({})
        vistos = []

        def guion(mensajes, kw):
            vistos.append(MockLLM.ultimo_usuario(mensajes))
            if MockLLM.turnos_asistente(mensajes) == 0:
                return "Voy a leer noexiste.py para ver qué hay."
            return terminar_xml("listo")
        Agente("reparador", MockLLM(guion), ws, self.ajustes(forense=False), self.ui()).ejecutar("Arreglá")
        self.assertNotIn("lo leí yo", vistos[1])

    def test_listo_sin_attempt_completion_cierra_si_hubo_cambios_validos(self):
        ws = self.proyecto({})
        llm = MockLLM(lambda m, k: herramienta_xml("write_to_file", path="calc.py", content=_CM_CALC)
                      if MockLLM.turnos_asistente(m) == 0 else "Listo, terminé: implementé sumar en calc.py.")
        res = Agente("implementador", llm, ws, self.ajustes(forense=False), self.ui()).ejecutar("Creá calc.py con sumar")
        self.assertEqual(res.motivo, "completado")                       # antes: "sin_herramientas" tras 3 avisos
        self.assertEqual(res.pasos, 2)
        self.assertEqual(llm.uso.llamadas, 2)

    def test_listo_con_validacion_rota_recibe_el_motivo(self):
        ws = self.proyecto({})
        vistos = []

        def guion(mensajes, kw):
            vistos.append(MockLLM.ultimo_usuario(mensajes))
            turno = MockLLM.turnos_asistente(mensajes)
            if turno == 0:
                return herramienta_xml("write_to_file", path="calc.py", content="def sumar(a, b)\n    return a + b\n")
            if turno == 1:
                return "Listo, terminé."
            if turno == 2:
                return herramienta_xml("write_to_file", path="calc.py", content=_CM_CALC)
            return terminar_xml("calc.py corregido")
        res = Agente("implementador", MockLLM(guion), ws, self.ajustes(forense=False), self.ui()).ejecutar(
            "Creá calc.py con sumar")
        self.assertIn("intenté cerrar por vos", vistos[2])
        self.assertIn("validación REAL", vistos[2])
        self.assertEqual(res.motivo, "completado")

    def test_frases_de_cierre_y_de_lectura(self):
        self.assertTrue(_anuncia_fin("Listo, terminé: implementé sumar."))
        self.assertTrue(_anuncia_fin("Implementation completed."))
        for frase in ("Completé la primera parte; falta la segunda.", "No terminé todavía.",
                      "Listo para escribir el test.", "Terminé de leer el archivo.", "Todavía no está listo."):
            self.assertFalse(_anuncia_fin(frase), frase)
        self.assertEqual(_ruta_anunciada_para_leer("Voy a leer `almacen/db.py` primero."), "almacen/db.py")
        self.assertEqual(_ruta_anunciada_para_leer("Let me read ./app.py"), "app.py")
        self.assertIsNone(_ruta_anunciada_para_leer("Voy a crear app.py"))

    def test_listo_sin_cambios_no_cierra(self):
        ws = self.proyecto({})
        vistos = []

        def guion(mensajes, kw):
            vistos.append(MockLLM.ultimo_usuario(mensajes))
            return "Listo, terminé." if MockLLM.turnos_asistente(mensajes) == 0 else terminar_xml("x")
        Agente("implementador", MockLLM(guion), ws, self.ajustes(forense=False), self.ui()).ejecutar("Creá calc.py")
        self.assertNotIn("intenté cerrar por vos", vistos[1])

    def test_errores_de_formato_no_agotan_los_pasos(self):
        ws = self.proyecto({})
        rota = "<write_to_file>\n<path>calc.py</path>\n</write_to_file>"            # faltan content

        def guion(mensajes, kw):
            turno = MockLLM.turnos_asistente(mensajes)
            if turno < 3:
                return rota
            if turno == 3:
                return herramienta_xml("write_to_file", path="calc.py", content=_CM_CALC)
            return terminar_xml("calc.py con sumar")
        res = Agente("implementador", MockLLM(guion), ws, self.ajustes(forense=False), self.ui(),
                     max_pasos=3).ejecutar("Creá calc.py con sumar")
        self.assertEqual(res.motivo, "completado")                       # antes: max_pasos con 0 archivos
        self.assertEqual(ws.leer("calc.py"), _CM_CALC)

    def test_los_pasos_de_gracia_tienen_tope(self):
        ws = self.proyecto({})
        llm = MockLLM(lambda m, k: "<write_to_file>\n<path>calc.py</path>\n</write_to_file>")
        res = Agente("implementador", llm, ws, self.ajustes(forense=False, escalar=False), self.ui(),
                     max_pasos=3).ejecutar("Creá calc.py")
        self.assertEqual(res.motivo, "max_pasos")
        self.assertEqual(res.pasos, 3 + _ERRORES_DE_FORMATO_MAX)
        self.assertEqual(llm.uso.llamadas, 3 + _ERRORES_DE_FORMATO_MAX)

    def test_respuestas_vacias_no_queman_pasos(self):
        ws = self.proyecto({})
        vistos = []

        def guion(mensajes, kw):
            vistos.append(MockLLM.ultimo_usuario(mensajes))
            turno = MockLLM.turnos_asistente(mensajes)
            if turno in (0, 2):
                return ""
            if turno == 1:
                return herramienta_xml("write_to_file", path="calc.py", content=_CM_CALC)
            return terminar_xml("calc.py con sumar")
        res = Agente("implementador", MockLLM(guion), ws, self.ajustes(forense=False), self.ui(),
                     max_pasos=3).ejecutar("Creá calc.py con sumar")
        self.assertEqual(res.motivo, "completado")                       # antes: max_pasos
        self.assertIn("llegó VACÍA", vistos[1])

    def test_tres_vacias_seguidas_siguen_cerrando(self):
        ws = self.proyecto({})
        llm = MockLLM(lambda m, k: "")
        res = Agente("implementador", llm, ws, self.ajustes(forense=False), self.ui()).ejecutar("Creá calc.py")
        self.assertEqual(res.motivo, "sin_herramientas")
        self.assertEqual(llm.uso.llamadas, 3)
