"""
Autotests de los bugs vistos en uso real (v7.1):

  1. Tool loop: con 2+2 el modelo obtenía 4 y volvía a llamar execute_command. La causa era REAPER:
     una respuesta en texto después de una herramienta recibía "no usaste ninguna herramienta" y el
     modelo, obediente, repetía el comando. Ahora el principal termina con su respuesta, una llamada
     idéntica sin cambios reutiliza el resultado y un bucle se corta.
  2. Cumplimiento falso: afirmaba haber validado algo cuando la ejecución había sido rechazada.
  3. Verificación interactiva: un EOFError hacía que modificara el programa en vez de probarlo con entrada.
  4. "Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos." → responde sin herramientas.
"""


def _comando(cmd: str, **extra: str) -> str:
    return herramienta_xml("execute_command", command=cmd, **extra)


def _ultimas_observaciones(llm: "MockLLM") -> list:
    """Último mensaje de usuario que vio el modelo en cada llamada (observaciones de REAPER)."""
    return [MockLLM.ultimo_usuario(ll["mensajes"]) for ll in llm.llamadas]


CALCULADORA_INTERACTIVA = '''\
def calcular(a, b, op):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return a / b
    raise ValueError(op)


def main():
    while True:
        texto = input("primer número (o salir): ")
        if texto.strip() == "salir":
            print("chau")
            break
        a = float(texto)
        b = float(input("segundo número: "))
        op = input("operación: ")
        print("resultado:", calcular(a, b, op))


if __name__ == "__main__":
    main()
'''


class TestHeuristicasPedido(BaseTest):
    def test_pide_cambios(self):
        self.assertTrue(pide_cambios("Creá una calculadora en calc.py"))
        self.assertTrue(pide_cambios("arreglá el bug de login"))
        self.assertTrue(pide_cambios("¿Podés crear un archivo hola.py?"))
        self.assertTrue(pide_cambios("can you fix the tests?"))
        self.assertFalse(pide_cambios("¿cuánto es 5+5?"))
        self.assertFalse(pide_cambios("Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos."))
        self.assertFalse(pide_cambios("¿cómo invierto una lista en python?"))
        self.assertFalse(pide_cambios("explicame qué es una closure"))
        self.assertFalse(pide_cambios(""))

    def test_prohibiciones(self):
        p = prohibiciones("Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos.")
        self.assertIn("herramientas", p)
        self.assertIn("archivos", p)
        self.assertEqual(prohibiciones("no ejecutes comandos, solo leé el código"), {"comandos"})
        self.assertEqual(prohibiciones("don't run any commands"), {"comandos"})
        self.assertEqual(prohibiciones("creá calc.py"), set())
        self.assertIn("archivos", prohibiciones("revisalo pero no modifiques ningún archivo"))

    def test_pregunta_simple(self):
        self.assertTrue(es_pregunta_simple("cuánto es 5+5"))
        self.assertTrue(es_pregunta_simple("¿qué es una lista enlazada?"))
        self.assertTrue(es_pregunta_simple("2+2"))
        self.assertTrue(es_pregunta_simple("Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos."))
        self.assertFalse(es_pregunta_simple("¿qué hace main.py?"))      # necesita leer el archivo
        self.assertFalse(es_pregunta_simple("creá una calculadora"))
        self.assertFalse(es_pregunta_simple("x" * 400 + "?"))

    def test_afirma_verificacion(self):
        self.assertTrue(afirma_verificacion("Listo, validé el programa y funciona correctamente."))
        self.assertTrue(afirma_verificacion("Los tests pasan."))
        self.assertTrue(afirma_verificacion("He verificado el resultado"))
        self.assertTrue(afirma_verificacion("All tests passed."))
        self.assertFalse(afirma_verificacion("No pude probarlo porque el comando fue bloqueado."))
        self.assertFalse(afirma_verificacion("No verifiqué nada todavía."))
        self.assertFalse(afirma_verificacion("El resultado de 5+5 es 10."))
        self.assertFalse(afirma_verificacion("Deberías probar el programa con entrada."))

    def test_afirma_ejecucion(self):
        self.assertTrue(afirma_ejecucion("Ejecuté el programa y muestra 4"))
        self.assertTrue(afirma_ejecucion("corrí python y dio 4"))
        self.assertFalse(afirma_ejecucion("no ejecuté nada"))
        self.assertFalse(afirma_ejecucion("El resultado es 4"))

    def test_anuncia_accion(self):
        self.assertTrue(anuncia_accion("Ahora voy a crear el archivo calc.py"))
        self.assertTrue(anuncia_accion("Voy a ejecutar el programa para probarlo:"))
        self.assertTrue(anuncia_accion("Let me check the file"))
        self.assertFalse(anuncia_accion("5 + 5 = 10"))
        self.assertFalse(anuncia_accion("Listo: creé calc.py con suma y resta. Probalo con python3 calc.py."))

    def test_codigo_pegado(self):
        self.assertTrue(codigo_pegado("```python\na = 1\nb = 2\nc = 3\nprint(a + b + c)\n```"))
        self.assertFalse(codigo_pegado("Usá `lista[::-1]`"))
        self.assertFalse(codigo_pegado("```bash\npython3 calc.py\n```"))

    def test_fences_vacios(self):
        self.assertEqual(limpiar_texto_visible("Ejecuto el comando:\n```xml\n\n```"), "Ejecuto el comando:")
        self.assertEqual(limpiar_texto_visible("```xml\n```\n\n\n\nlisto"), "listo")
        self.assertEqual(limpiar_texto_visible("```python\nprint(1)\n```"), "```python\nprint(1)\n```")

    def test_salida_fallida(self):
        self.assertTrue(salida_fallida("execute_command", "$ x\nexit code: 1\nSTDERR:\nboom"))
        self.assertFalse(salida_fallida("execute_command", "$ x\nexit code: 0\nSTDOUT:\n4"))
        self.assertTrue(salida_fallida("run_tests", "Tests FALLARON (pytest): 1 fallaron."))
        self.assertFalse(salida_fallida("run_tests", "Tests PASARON (pytest)."))


class TestBucleHerramientas(BaseTest):
    def agente(self, llm, ws, rol="principal", **ajustes) -> Agente:
        return Agente(rol, llm, ws, self.ajustes(**ajustes), self.ui(), memoria=None, mostrar_progreso=False)

    # ---------------------------------------------------------------- 5+5
    def test_5mas5_responde_sin_herramientas(self):
        llm = MockLLM(["10"])
        res = self.agente(llm, self.proyecto()).ejecutar(
            "Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos.")
        self.assertEqual(res.motivo, "respuesta")
        self.assertEqual(res.resumen, "10")
        self.assertEqual(res.pasos, 1)
        self.assertTrue(res.ok)
        # la tarea llega con la aclaración de REAPER y SIN mapa de archivos ni guías (no hay nada que explorar)
        tarea = llm.llamadas[0]["mensajes"][1]["content"]
        self.assertIn("SIN usar herramientas", tarea)
        self.assertNotIn("GUÍA RÁPIDA", tarea)

    def test_5mas5_bloquea_el_comando_prohibido(self):
        ws = self.proyecto()
        llm = MockLLM([_comando("python3 -c 'print(5+5)' > hecho.txt"), "10"])
        res = self.agente(llm, ws).ejecutar(
            "Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos.")
        self.assertEqual(res.resumen, "10")
        self.assertFalse((ws.raiz / "hecho.txt").exists(), "el comando prohibido no debía ejecutarse")
        self.assertIn("respondé directamente en texto", _ultimas_observaciones(llm)[1])

    def test_pregunta_simple_con_codigo_se_acepta(self):
        llm = MockLLM(["Con slicing:\n```python\nlista = [1, 2, 3]\ninvertida = lista[::-1]\nprint(invertida)\n# [3, 2, 1]\n```"])
        res = self.agente(llm, self.proyecto()).ejecutar("¿cómo invierto una lista en python?")
        self.assertEqual(res.motivo, "respuesta")
        self.assertEqual(res.pasos, 1)

    # ---------------------------------------------------------------- 2+2
    def test_2mas2_responde_despues_de_la_herramienta(self):
        """El bug central: después de obtener 4, la respuesta en texto ES la respuesta final."""
        llm = MockLLM([_comando('python3 -c "print(2+2)"'), "2+2 = 4"])
        res = self.agente(llm, self.proyecto()).ejecutar("cuánto es 2+2? calculalo con python")
        self.assertEqual(res.motivo, "respuesta")
        self.assertEqual(res.resumen, "2+2 = 4")
        self.assertEqual(res.pasos, 2)
        self.assertEqual(len(llm.llamadas), 2)
        # la observación le recuerda que ya puede responder
        self.assertIn("respondé AHORA en texto", _ultimas_observaciones(llm)[1])

    def test_2mas2_llamada_identica_reutiliza_el_resultado(self):
        ws = self.proyecto()
        llm = MockLLM([_comando('python3 -c "print(2+2)"'), _comando('python3 -c "print(2+2)"'), "4"])
        res = self.agente(llm, ws).ejecutar("cuánto es 2+2? usá python")
        self.assertEqual(res.resumen, "4")
        obs = _ultimas_observaciones(llm)[2]
        self.assertIn("YA HICISTE EXACTAMENTE ESTA LLAMADA", obs)
        self.assertIn("4", obs)
        self.assertIn("YA TENÉS LO QUE NECESITABAS", obs)

    def test_2mas2_bucle_infinito_se_corta_con_la_respuesta(self):
        llm = MockLLM(lambda m, k: _comando('python3 -c "print(2+2)"'))
        res = self.agente(llm, self.proyecto(), max_pasos=12).ejecutar("cuánto es 2+2? usá python")
        self.assertEqual(res.motivo, "respuesta")
        self.assertIn("4", res.resumen)
        self.assertLessEqual(res.pasos, 3)

    def test_comando_que_cambia_archivos_se_puede_repetir(self):
        ws = self.proyecto()
        cmd = "echo x >> log.txt && wc -l < log.txt"
        llm = MockLLM([_comando(cmd), _comando(cmd), "listo"])
        self.agente(llm, ws).ejecutar("agregá dos líneas a log.txt con el comando")
        self.assertEqual((ws.raiz / "log.txt").read_text().count("x"), 2)

    def test_comando_fallido_identico_se_bloquea_al_tercero(self):
        ws = self.proyecto({"roto.py": "raise SystemExit(3)\n"})
        llm = MockLLM([_comando("python3 roto.py")] * 3 + ["No pude: el programa sale con código 3."])
        self.agente(llm, ws).ejecutar("ejecutá roto.py")
        obs = _ultimas_observaciones(llm)
        self.assertIn("exit code: 3", obs[1])
        self.assertIn("exit code: 3", obs[2])
        self.assertIn("NO se ejecutó", obs[3])

    # ---------------------------------------------------------------- run_tests / read_file tras editar
    def test_run_tests_permitido_despues_de_editar(self):
        ws = self.proyecto({
            "calc.py": "def suma(a, b):\n    return a - b\n",
            "tests/test_calc.py": "import unittest\nfrom calc import suma\n\n\nclass T(unittest.TestCase):\n"
                                  "    def test_suma(self):\n        self.assertEqual(suma(2, 3), 5)\n",
        })
        llm = MockLLM([
            herramienta_xml("run_tests"),
            herramienta_xml("replace_symbol", path="calc.py", symbol="suma", content="def suma(a, b):\n    return a * b"),
            herramienta_xml("run_tests"),
            herramienta_xml("replace_symbol", path="calc.py", symbol="suma", content="def suma(a, b):\n    return a + b"),
            herramienta_xml("run_tests"),
            terminar_xml("Arreglé suma; run_tests pasa."),
        ])
        res = self.agente(llm, ws).ejecutar("arreglá suma")
        self.assertTrue(res.ok, res.resumen)
        obs = _ultimas_observaciones(llm)
        self.assertIn("Tests FALLARON", obs[1])
        self.assertIn("Tests FALLARON", obs[3])
        self.assertIn("Tests PASARON", obs[5])
        self.assertFalse(any("llamada repetida" in o or "YA HICISTE" in o for o in obs))

    def test_relectura_tras_cambio_trae_contenido_nuevo(self):
        ws = self.proyecto({"a.py": "X = 1\n"})
        llm = MockLLM([
            herramienta_xml("read_file", path="a.py"),
            herramienta_xml("write_to_file", path="a.py", content="X = 2\n"),
            herramienta_xml("read_file", path="a.py"),
            terminar_xml("X vale 2."),
        ])
        self.agente(llm, ws).ejecutar("cambiá X a 2")
        self.assertIn("X = 2", _ultimas_observaciones(llm)[3])

    # ---------------------------------------------------------------- cumplimiento falso
    def test_afirmacion_sin_evidencia_se_rechaza(self):
        ws = self.proyecto({"a.py": "X = 1\n"})
        llm = MockLLM([
            herramienta_xml("write_to_file", path="a.py", content="X = 2\n"),
            terminar_xml("Listo, validé el cambio y funciona correctamente."),
            herramienta_xml("validate"),
            terminar_xml("Cambié X a 2 y validate da OK."),
        ])
        res = self.agente(llm, ws).ejecutar("cambiá X a 2")
        self.assertIn("No acepto ese cierre", _ultimas_observaciones(llm)[2])
        self.assertEqual(res.resumen, "Cambié X a 2 y validate da OK.")
        self.assertTrue(res.ok)

    def test_afirmacion_tras_ejecucion_bloqueada_se_rechaza(self):
        """El caso real: dijo 'validé' cuando la ejecución había sido rechazada como repetida."""
        ws = self.proyecto({"roto.py": "raise SystemExit(1)\n"})
        llm = MockLLM([_comando("python3 roto.py")] * 3 + [
            "Validé el programa y funciona correctamente.",
            "No pude validarlo: el programa termina con código 1.",
        ])
        res = self.agente(llm, ws).ejecutar("probá roto.py")
        self.assertIn("BLOQUEADA", _ultimas_observaciones(llm)[4])
        self.assertTrue(res.resumen.startswith("No pude validarlo"))

    def test_tests_que_fallan_no_se_pueden_dar_por_pasados(self):
        ws = self.proyecto({
            "calc.py": "def suma(a, b):\n    return a - b\n",
            "tests/test_calc.py": "import unittest\nfrom calc import suma\n\n\nclass T(unittest.TestCase):\n"
                                  "    def test_suma(self):\n        self.assertEqual(suma(2, 3), 5)\n",
        })
        llm = MockLLM([herramienta_xml("run_tests")] + [terminar_xml("Todos los tests pasan.")] * 5)
        res = self.agente(llm, ws).ejecutar("arreglá suma")
        self.assertIn("⚠ REAPER", res.resumen)
        self.assertIn("FALLÓ", res.resumen)

    def test_informe_honesto_con_fallo_se_acepta(self):
        ws = self.proyecto({
            "calc.py": "def suma(a, b):\n    return a - b\n",
            "tests/test_calc.py": "import unittest\nfrom calc import suma\n\n\nclass T(unittest.TestCase):\n"
                                  "    def test_suma(self):\n        self.assertEqual(suma(2, 3), 5)\n",
        })
        llm = MockLLM([herramienta_xml("run_tests"), terminar_xml("Corrí los tests: test_suma falla (devuelve -1).")])
        res = self.agente(llm, ws).ejecutar("diagnosticá suma")
        self.assertEqual(res.pasos, 2)
        self.assertNotIn("⚠ REAPER", res.resumen)

    def test_respuesta_con_ejecucion_real_se_acepta(self):
        llm = MockLLM([_comando('python3 -c "print(2+2)"'), "Lo ejecuté con python y da 4."])
        res = self.agente(llm, self.proyecto()).ejecutar("cuánto es 2+2? usá python")
        self.assertEqual(res.resumen, "Lo ejecuté con python y da 4.")

    # ---------------------------------------------------------------- anuncios y código pegado
    def test_anuncio_sin_herramienta_pide_actuar(self):
        ws = self.proyecto()
        llm = MockLLM([
            "Voy a crear el archivo hola.py:",
            herramienta_xml("write_to_file", path="hola.py", content='print("hola")\n'),
            terminar_xml("Creé hola.py."),
        ])
        res = self.agente(llm, ws).ejecutar("creá hola.py que imprima hola")
        self.assertTrue((ws.raiz / "hola.py").exists())
        self.assertIn("no llamaste ninguna herramienta", _ultimas_observaciones(llm)[1])
        self.assertEqual(res.motivo, "completado")

    def test_codigo_pegado_en_pedido_de_cambios(self):
        ws = self.proyecto()
        llm = MockLLM([
            "Acá está:\n```python\ndef hola():\n    return 'hola'\n\nprint(hola())\n```",
            herramienta_xml("write_to_file", path="hola.py", content="def hola():\n    return 'hola'\n"),
            terminar_xml("Creé hola.py."),
        ])
        self.agente(llm, ws).ejecutar("creá hola.py con una función hola")
        self.assertIn("Pegaste código en el chat", _ultimas_observaciones(llm)[1])
        self.assertTrue((ws.raiz / "hola.py").exists())

    def test_respuesta_final_tras_trabajo_se_acepta_sin_attempt_completion(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("write_to_file", path="hola.py", content='print("hola")\n'),
            "Listo: creé hola.py, que imprime hola.",
        ])
        res = self.agente(llm, ws).ejecutar("creá hola.py que imprima hola")
        self.assertEqual(res.motivo, "respuesta")
        self.assertTrue(res.ok)
        self.assertEqual(res.cambios, ["hola.py"])

    def test_respuesta_con_archivo_roto_no_se_acepta(self):
        ws = self.proyecto()
        llm = MockLLM([
            herramienta_xml("write_to_file", path="mal.py", content="def f(:\n    pass\n"),
            "Listo.",
            herramienta_xml("write_to_file", path="mal.py", content="def f():\n    return 1\n"),
            "Listo, mal.py define f().",
        ])
        res = self.agente(llm, ws).ejecutar("creá mal.py con una función f")
        self.assertIn("validación REAL", _ultimas_observaciones(llm)[2])
        self.assertTrue(res.ok)

    def test_fences_vacios_no_se_muestran(self):
        ui = self.ui()
        llm = MockLLM(["Ejecuto:\n```xml\n" + _comando('python3 -c "print(1)"') + "\n```", "1"])
        Agente("principal", llm, self.proyecto(), self.ajustes(), ui, memoria=None,
               mostrar_progreso=False).ejecutar("cuánto da print(1)? probalo")
        self.assertNotIn("```xml", ui.texto_registrado())

    # ---------------------------------------------------------------- roles de solo lectura
    def test_arquitecto_que_escribe_el_plan_en_texto(self):
        plan = ("<plan>\n<objetivo>calc</objetivo>\n<interfaz>\n- calc.py: def suma(a, b) -> int\n</interfaz>\n"
                '<tarea id="1" archivos="calc.py">suma</tarea>\n<criterios>\n- suma(2, 3) == 5\n</criterios>\n</plan>')
        res = self.agente(MockLLM([plan]), self.proyecto(), rol="arquitecto").ejecutar("planificá una calculadora")
        self.assertEqual(res.motivo, "completado")
        self.assertIn("<plan>", res.resumen)

    def test_revisor_con_veredicto_en_texto(self):
        res = self.agente(MockLLM(["VEREDICTO: APROBADO\nTodo bien."]), self.proyecto(), rol="revisor").ejecutar("revisá")
        self.assertEqual(res.motivo, "completado")


class TestProgramasInteractivos(BaseTest):
    def test_eof_da_pista_de_programa_interactivo(self):
        ws = self.proyecto({"calculadora.py": CALCULADORA_INTERACTIVA})
        salida = self.herramienta(self.contexto(ws), "execute_command", command="python3 calculadora.py")
        self.assertIn("EOFError", salida)
        self.assertIn("INTERACTIVO", salida)
        self.assertIn("NO lo modifiques", salida)
        self.assertIn("<stdin>", salida)

    def test_execute_command_con_stdin(self):
        ws = self.proyecto({"calculadora.py": CALCULADORA_INTERACTIVA})
        salida = self.herramienta(self.contexto(ws), "execute_command", command="python3 calculadora.py",
                                  stdin="2\n3\n+\nsalir")
        self.assertIn("exit code: 0", salida)
        self.assertIn("resultado: 5.0", salida)
        self.assertIn("chau", salida)

    def test_stdin_con_barras_literales(self):
        ws = self.proyecto({"calculadora.py": CALCULADORA_INTERACTIVA})
        salida = self.herramienta(self.contexto(ws), "execute_command", command="python3 calculadora.py",
                                  stdin="6\\n2\\n/\\nsalir")
        self.assertIn("resultado: 3.0", salida)

    def test_stdin_insuficiente(self):
        ws = self.proyecto({"calculadora.py": CALCULADORA_INTERACTIVA})
        salida = self.herramienta(self.contexto(ws), "execute_command", command="python3 calculadora.py", stdin="2")
        self.assertIn("MÁS datos", salida)

    def test_run_python_con_input_y_stdin(self):
        ws = self.proyecto({"calculadora.py": CALCULADORA_INTERACTIVA})
        salida = self.herramienta(self.contexto(ws), "run_python",
                                  content="from calculadora import main\nmain()", stdin="4\n5\n*\nsalir\n")
        self.assertIn("resultado: 20.0", salida)

    def test_run_python_con_input_sin_stdin(self):
        with self.assertRaises(ErrorHerramienta) as cm:
            self.herramienta(self.contexto(self.proyecto()), "run_python", content="x = input()")
        self.assertIn("<stdin>", str(cm.exception))

    def test_alias_input_para_stdin(self):
        llamada = analizar("<execute_command>\n<command>python3 c.py</command>\n<input>1\n2</input>\n</execute_command>",
                           esquemas()).llamadas[0]
        self.assertEqual(llamada.params.get("stdin"), "1\n2")

    def test_agente_prueba_con_entrada_y_no_modifica(self):
        ws = self.proyecto({"calculadora.py": CALCULADORA_INTERACTIVA})
        llm = MockLLM([
            _comando("python3 calculadora.py"),
            _comando("python3 calculadora.py", stdin="2\n3\n+\nsalir"),
            "Funciona: con 2, 3 y + muestra resultado: 5.0 (lo ejecuté con entrada).",
        ])
        res = Agente("principal", llm, ws, self.ajustes(), self.ui(), memoria=None,
                     mostrar_progreso=False).ejecutar("probá la calculadora")
        self.assertEqual(res.motivo, "respuesta")
        self.assertEqual((ws.raiz / "calculadora.py").read_text(), CALCULADORA_INTERACTIVA)
        self.assertIn("INTERACTIVO", _ultimas_observaciones(llm)[1])


PEDIDO_GRANDE = ("Creá NebulaDB: una base de datos clave-valor en Python con almacenamiento en disco (storage.py), "
                 "índice en memoria (index.py), un parser de consultas tipo SQL (query.py) y una CLI (cli.py) "
                 "con comandos put, get, delete y scan.")

PLAN_DEGENERADO = f"""<plan>
<objetivo>NebulaDB</objetivo>
<interfaz>
- nebula/storage.py: class Storage(ruta) con put(k, v), get(k), delete(k)
- nebula/index.py: class Index() con add(k, pos), find(k) -> int | None
- nebula/query.py: def parse(texto) -> dict
- nebula/cli.py: def main(argv) -> int
</interfaz>
<tarea id="1" archivos="nebula/storage.py, nebula/index.py, nebula/query.py, nebula/cli.py">{PEDIDO_GRANDE}</tarea>
<criterios>
- Storage.get devuelve lo guardado con put
</criterios>
</plan>"""

PLAN_BUENO = """<plan>
<objetivo>NebulaDB</objetivo>
<interfaz>
- nebula/storage.py: class Storage(ruta)
- nebula/index.py: class Index()
- nebula/cli.py: def main(argv) -> int
</interfaz>
<tarea id="1" archivos="nebula/storage.py">Storage con put/get/delete en disco.</tarea>
<tarea id="2" archivos="nebula/index.py">Index en memoria.</tarea>
<tarea id="3" archivos="nebula/cli.py">CLI con put, get, delete y scan.</tarea>
<criterios>
- Storage.get devuelve lo guardado con put
</criterios>
</plan>"""


class TestPipelinePlanYRevision(BaseTest):
    def test_plan_degenerado(self):
        plan = parsear_plan(PLAN_DEGENERADO, PEDIDO_GRANDE)
        self.assertTrue(plan_degenerado(plan, PEDIDO_GRANDE, PLAN_DEGENERADO))
        self.assertEqual(plan_degenerado(parsear_plan(PLAN_BUENO, PEDIDO_GRANDE), PEDIDO_GRANDE, PLAN_BUENO), "")
        chico = parsear_plan('<plan><tarea id="1" archivos="calc.py">Agregar resta a calc.py</tarea></plan>', "agregá resta")
        self.assertEqual(plan_degenerado(chico, "agregá resta"), "", "un pedido chico puede tener una sola tarea")
        sin_formato = parsear_plan("hacé todo", PEDIDO_GRANDE)
        self.assertIn("<tarea>", plan_degenerado(sin_formato, PEDIDO_GRANDE, "hacé todo"))

    def test_dividir_por_interfaz(self):
        plan = dividir_por_interfaz(parsear_plan(PLAN_DEGENERADO, PEDIDO_GRANDE))
        self.assertEqual([t.archivos for t in plan.tareas],
                         [["nebula/storage.py"], ["nebula/index.py"], ["nebula/query.py"], ["nebula/cli.py"]])
        self.assertIn("class Index", plan.tareas[1].descripcion)

    def _orquestador(self, respuestas_arquitecto: list) -> tuple:
        pendientes = list(respuestas_arquitecto)

        def guion(mensajes, kwargs):
            if MockLLM.rol_de(mensajes) == "arquitecto":
                return terminar_xml(pendientes.pop(0))
            return terminar_xml("ok")

        llm = MockLLM(guion)
        return Orquestador(llm, self.proyecto(), self.ajustes(), self.ui()), llm

    def test_arquitecto_reintenta_un_plan_de_una_sola_tarea(self):
        orq, llm = self._orquestador([PLAN_DEGENERADO, PLAN_BUENO])
        plan = orq.planificar(PEDIDO_GRANDE, "")
        self.assertEqual(len(plan.tareas), 3)
        segunda = [c for c in llm.llamadas if MockLLM.rol_de(c["mensajes"]) == "arquitecto"][-1]
        self.assertIn("TU PLAN ANTERIOR NO SIRVE", segunda["mensajes"][1]["content"])

    def test_arquitecto_que_insiste_se_divide_por_archivo(self):
        orq, _ = self._orquestador([PLAN_DEGENERADO, PLAN_DEGENERADO])
        plan = orq.planificar(PEDIDO_GRANDE, "")
        self.assertEqual(len(plan.tareas), 4)

    def test_tarea_sin_progreso_no_pasa(self):
        ws = self.proyecto({"a.py": "X = 1\n"})
        orq = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        orq._protegidos = {}
        tcid = ws.checkpoints.iniciar("tarea 1")
        verif = orq._verificar_tarea(tcid, ConteoTests(), set(), exigir_progreso=True)
        self.assertFalse(verif.ok)
        self.assertIn("SIN PROGRESO", verif.diagnostico)
        self.assertTrue(orq._verificar_tarea(tcid, ConteoTests(), set()).ok)

    def test_revisor_no_aprueba_una_tarea_que_rompe_tests(self):
        ws = self.proyecto({
            "calc.py": "def suma(a, b):\n    return a + b\n",
            "tests/test_calc.py": "import unittest\nfrom calc import suma\n\n\nclass T(unittest.TestCase):\n"
                                  "    def test_suma(self):\n        self.assertEqual(suma(2, 3), 5)\n",
        })
        plan = ('<plan><objetivo>resta</objetivo><tarea id="1" archivos="calc.py">Agregar resta a calc.py</tarea>'
                "<criterios>\n- resta(5, 3) == 2\n</criterios></plan>")

        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
            if rol == "arquitecto":
                return terminar_xml(plan)
            if rol == "implementador" and turno == 0:
                return herramienta_xml("write_to_file", path="calc.py",
                                       content="def suma(a, b):\n    return a - b\n\n\ndef resta(a, b):\n    return a - b\n")
            if rol == "revisor":
                return terminar_xml("VEREDICTO: APROBADO")
            return terminar_xml("No pude arreglarlo.")

        llm = MockLLM(guion)
        ajustes = self.ajustes(max_revisiones=1, max_reparaciones=1, umbral_escalada=0)
        informe = Orquestador(llm, ws, ajustes, self.ui()).construir("agregá resta", confirmar=False)
        roles = [MockLLM.rol_de(c["mensajes"]) for c in llm.llamadas]
        self.assertNotIn("revisor", roles, "una tarea que rompe tests no se manda a revisar")
        self.assertTrue(any("sin revisión" in n for n in informe.notas), informe.notas)
        self.assertNotEqual(informe.estado, "verificada")


class TestLlamadasSinCerrar(BaseTest):
    def test_parser_acepta_contenido_sin_cierre_si_cierra_la_herramienta(self):
        llamada = analizar("<write_to_file>\n<path>a.py</path>\n<content>\nx = 1\n</write_to_file>", esquemas()).llamadas[0]
        self.assertTrue(llamada.completa)
        self.assertEqual(llamada.params["content"].strip(), "x = 1")

    def test_comillas_internas_se_conservan(self):
        llamada = analizar('<execute_command><command>python3 -c "print(2+2)"</command></execute_command>',
                           esquemas()).llamadas[0]
        self.assertEqual(llamada.params["command"], 'python3 -c "print(2+2)"')
        self.assertEqual(sin_comillas('"app.py"'), "app.py")
        self.assertEqual(sin_comillas("`ls -la`"), "ls -la")
        self.assertEqual(sin_comillas("'a' && echo 'b'"), "'a' && echo 'b'")

    def test_agente_acepta_etiquetas_olvidadas_si_el_mensaje_termino_normal(self):
        ws = self.proyecto()
        llm = MockLLM(["Creo el archivo.\n<write_to_file>\n<path>a.py</path>\n<content>\nX = 1\n",
                       terminar_xml("Creé a.py.")])
        res = Agente("principal", llm, ws, self.ajustes(), self.ui(), memoria=None,
                     mostrar_progreso=False).ejecutar("creá a.py con X = 1")
        self.assertEqual(ws.leer("a.py").strip(), "X = 1")
        self.assertTrue(res.ok)
