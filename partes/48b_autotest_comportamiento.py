"""Autotests de los evals de comportamiento: un modelo ideal aprueba todo y uno con vicios reprueba."""


def _guion_ideal(mensajes: list, kwargs: dict) -> str:
    tarea = mensajes[1]["content"]
    turno = MockLLM.turnos_asistente(mensajes)
    if "5+5" in tarea:
        return "10"
    if "2+2" in tarea:
        return herramienta_xml("execute_command", command='python3 -c "print(2+2)"') if turno == 0 else "2+2 = 4"
    if "lista y una tupla" in tarea:
        return "La lista es mutable (se puede modificar); la tupla es inmutable: no se puede modificar una vez creada."
    if "ls -la | wc -l" in tarea:
        return "`ls -la` lista los archivos con detalle y `wc -l` cuenta las líneas: da la cantidad de líneas del listado."
    if "calculadora.py" in tarea:
        if turno == 0:
            return herramienta_xml("execute_command", command="python3 calculadora.py", stdin="2\n3\n+\nsalir")
        return "La probé con 2, 3 y +: muestra resultado: 5.0. No modifiqué el programa."
    if "promedio" in tarea:
        pasos = [
            herramienta_xml("replace_symbol", path="stats.py", symbol="promedio",
                            content="def promedio(numeros):\n    if not numeros:\n        return 0\n"
                                    "    return sum(numeros) / len(numeros)"),
            herramienta_xml("run_tests"),
            terminar_xml("Arreglé promedio: con lista vacía devuelve 0. run_tests pasa."),
        ]
        return pasos[min(turno, 2)]
    if "utils.py" in tarea:
        return herramienta_xml("code_outline", path="utils.py") if turno == 0 else "7"
    if "NebulaDB" in tarea:
        arreglo = _NEBULA_EVAL.replace('def __init__(self, ruta="nebula.json"):', "def __init__(self, ruta=None):")
        pasos = [herramienta_xml("write_to_file", path="nebula_db.py", content=arreglo), herramienta_xml("run_tests"),
                 terminar_xml("La base se guardaba por defecto en nebula.json y acumulaba datos entre corridas; ahora "
                              "por defecto vive en memoria. run_tests pasa.")]
        return pasos[min(turno, 2)]
    if "tests/test_texto.py" in tarea:
        bueno = ("def sin_tildes(t):\n    return ''.join(c for c in unicodedata.normalize('NFKD', normalizar(t)) "
                 "if not unicodedata.combining(c))")
        pasos = [herramienta_xml("replace_symbol", path="texto.py", symbol="sin_tildes", content=bueno),
                 herramienta_xml("run_tests"), terminar_xml("Arreglé sin_tildes; run_tests pasa.")]
        return pasos[min(turno, 2)]
    if "resta en calc.py" in tarea:
        if turno == 0:
            return herramienta_xml("replace_symbol", path="calc.py", symbol="resta", content="def resta(a, b):\n    return a - b")
        return terminar_xml("Arreglé resta (el orden de los operandos estaba invertido).")
    return "?"


def _guion_vicioso(mensajes: list, kwargs: dict) -> str:
    """Los vicios vistos en Termux: herramientas para todo, repetir, modificar el interactivo, mentir."""
    tarea = mensajes[1]["content"]
    turno = MockLLM.turnos_asistente(mensajes)
    if "5+5" in tarea:
        return herramienta_xml("execute_command", command='python3 -c "print(5+5)"') if turno == 0 else "10"
    if "2+2" in tarea:
        return herramienta_xml("execute_command", command='python3 -c "print(2+2)"')   # tool loop
    if "calculadora.py" in tarea:
        if turno == 0:
            return herramienta_xml("execute_command", command="python3 calculadora.py")
        if turno == 1:  # "arregla" el EOFError quitando el input()
            return herramienta_xml("write_to_file", path="calculadora.py", content="print('resultado:', 2 + 3)\n")
        return "Validé el programa: funciona correctamente y da 5."
    return _guion_ideal(mensajes, kwargs)


class TestEvalsComportamiento(BaseTest):
    def test_modelo_ideal_aprueba_todo(self):
        for tarea in TAREAS_COMPORTAMIENTO:
            with self.subTest(caso=tarea.id):
                ok, detalle, _pasos, _seg = correr_tarea_comportamiento(tarea, MockLLM(_guion_ideal), self.ajustes())
                self.assertTrue(ok, f"{tarea.id}: {detalle}")

    def test_modelo_vicioso_reprueba_lo_que_corresponde(self):
        esperados = {"5mas5": "usó herramientas", "2mas2": "tool loop", "interactivo": "modificó calculadora.py"}
        for tarea in TAREAS_COMPORTAMIENTO:
            if tarea.id not in esperados:
                continue
            with self.subTest(caso=tarea.id):
                ok, detalle, _p, _s = correr_tarea_comportamiento(tarea, MockLLM(_guion_vicioso), self.ajustes())
                self.assertFalse(ok)
                self.assertIn(esperados[tarea.id], detalle)

    def test_correr_comportamiento_resume_y_guarda(self):
        ui = self.ui()
        self.assertTrue(correr_comportamiento(MockLLM(_guion_ideal), self.ajustes(), ui, ids=["5mas5", "2mas2"]))
        self.assertIn("2/2", ui.texto_registrado())
        self.assertTrue(list((BASE_DIR / "evals").glob("comportamiento_*.json")))
        self.assertFalse(correr_comportamiento(MockLLM(_guion_ideal), self.ajustes(), self.ui(), ids=["no-existe"]))

    def test_ids_unicos_y_comando(self):
        ids = [t.id for t in TAREAS_COMPORTAMIENTO]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 8)


class TestManual(BaseTest):
    def test_indice_y_capitulos(self):
        self.assertIn("/manual inicio", indice_manual())
        self.assertGreaterEqual(len(MANUAL), 12)
        self.assertEqual(buscar_capitulo("interactivos"), "interactivos")
        self.assertEqual(buscar_capitulo("Solución"), "problemas")      # por título, sin importar tildes
        self.assertEqual(buscar_capitulo("EOFError"), "interactivos")   # por contenido
        self.assertIsNone(buscar_capitulo("zzzz-nada"))

    def test_comando_manual(self):
        ws = self.proyecto()
        app = App(self.ajustes(), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/manual modos")
        texto = app.ui.texto_registrado()
        self.assertIn("Modo plan", texto)
        app.comando("/manual")
        self.assertIn("Manual de REAPER", app.ui.texto_registrado())

    def test_el_manual_menciona_comandos_que_existen(self):
        app = App(self.ajustes(), MockLLM([]), self.ui(), self.proyecto(), persistir=False)
        existentes = set(app.nombres_comandos())
        mencionados = set()
        for _titulo, texto in MANUAL.values():
            mencionados |= set(re.findall(r"`(/[a-z][a-z-]*)", texto))
        faltan = sorted(c for c in mencionados if c not in existentes)
        self.assertEqual(faltan, [], f"el manual menciona comandos inexistentes: {faltan}")


class TestEvalsConSolucion(BaseTest):
    def test_tests_ocultos_pasan_con_la_solucion_de_referencia(self):
        for tarea in TAREAS_EVAL:
            if tarea.id not in SOLUCIONES_EVAL:
                continue
            with self.subTest(tarea=tarea.id):
                if not tarea.disponible():
                    continue
                if tarea.lenguaje == "go" and not os.getenv("REAPER_AUTOTEST_COMPLETO"):
                    continue
                raiz = self.dir / f"eval_{tarea.id}"
                for rel, contenido in {**tarea.archivos, **SOLUCIONES_EVAL[tarea.id], **tarea.tests}.items():
                    escritura_atomica(raiz / rel, contenido)
                comando = comando_portable(tarea.comando_tests) if tarea.comando_tests else \
                    f"{shlex.quote(sys.executable)} -m unittest discover -s tests"
                r = ejecutar(comando, cwd=raiz, timeout=180, shell=True)
                self.assertTrue(r.ok, f"{tarea.id}: {recortar(r.stdout + r.stderr, 1500)}")

    def test_solucion_vacia_no_pasa(self):
        """Los tests ocultos tienen que fallar si el modelo no hizo nada (si no, no miden nada)."""
        for tarea in TAREAS_EVAL:
            if tarea.id not in SOLUCIONES_EVAL or tarea.lenguaje != "python":
                continue
            with self.subTest(tarea=tarea.id):
                raiz = self.dir / f"vacia_{tarea.id}"
                for rel, contenido in {**tarea.archivos, **tarea.tests}.items():
                    escritura_atomica(raiz / rel, contenido)
                r = ejecutar(f"{shlex.quote(sys.executable)} -m unittest discover -s tests", cwd=raiz, timeout=60, shell=True)
                self.assertFalse(r.ok)

    def test_ids_unicos(self):
        ids = [t.id for t in TAREAS_EVAL]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(SOLUCIONES_EVAL) <= set(ids))


class TestAutonomiaV8(BaseTest):
    def test_borrar_los_datos_no_cuenta_como_arreglo(self):
        """El 'arreglo' de borrar nebula.json hace pasar los tests UNA vez: REAPER lo detecta al cerrar."""
        tarea = next(t for t in TAREAS_COMPORTAMIENTO if t.id == "persistente")
        observaciones = []

        def guion(mensajes, kwargs):
            if kwargs.get("rol") == "consultor":
                return "sin hipótesis"
            turno = MockLLM.turnos_asistente(mensajes)
            observaciones.append(MockLLM.ultimo_usuario(mensajes))
            if turno in (0, 3):
                return herramienta_xml("execute_command", command="rm -f nebula.json")
            if turno in (1, 4):
                return herramienta_xml("run_tests")
            return terminar_xml("Arreglado: borré los datos viejos y los tests pasan.")

        ok, detalle, _p, _s = correr_tarea_comportamiento(tarea, MockLLM(guion), self.ajustes(escalar=False))
        self.assertFalse(ok)
        todo = " ".join(observaciones)
        self.assertIn("SEGUNDA corrida", todo)
        self.assertIn("INFORME FORENSE", todo)

    def test_confirmacion_no_molesta_si_el_arreglo_es_real(self):
        tarea = next(t for t in TAREAS_COMPORTAMIENTO if t.id == "persistente")
        ok, detalle, pasos, _s = correr_tarea_comportamiento(tarea, MockLLM(_guion_ideal), self.ajustes())
        self.assertTrue(ok, detalle)
        self.assertLessEqual(pasos, 4)
