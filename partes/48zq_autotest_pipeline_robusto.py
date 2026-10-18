"""
Pipeline y /grande que avanzan con modelos flojos (pruebas reales en el teléfono: un /grande quedaba horas en
reparaciones o se DETENÍA en la etapa 2 por cosas que REAPER mismo podía destrabar).

- El torneo pisaba con el original un test protegido al que un candidato solo le AGREGABA el import que le faltaba.
- La reparación giraba en vacío: intentos sin cambios o con el MISMO error, sin ver qué había cambiado el anterior, y
  modo forense (varias llamadas) ante un NameError.
- Un test de la especificación acoplado a la implementación quedaba protegido aunque la reescritura siguiera mal, y
  si bloqueaba la reparación nadie lo podía corregir.
- Planes con una tarea de solo tests antes de su código y planes maestros fragmentados que el modelo insistía en dar.
- Una etapa que fallaba DETENÍA todo el /grande hasta que volviera el usuario.
"""

_PRB_TEST_SIN_IMPORT = ("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_sumar(self):\n"
                        "        self.assertEqual(sumar(2, 3), 5)\n")
_PRB_TEST_CON_IMPORT = _PRB_TEST_SIN_IMPORT.replace("import unittest\n", "import unittest\n\nfrom calc import sumar\n")
_PRB_TEST_CALC = _PRB_TEST_CON_IMPORT
_PRB_CALC = "def sumar(a, b):\n    return a + b\n"
_PRB_DB = ('import sqlite3\n\n\ndef conectar(ruta=":memory:"):\n    con = sqlite3.connect(ruta)\n'
           '    con.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, stock INTEGER)")\n'
           '    return con\n\n\ndef agregar_producto(con, pid, stock):\n'
           '    con.execute("INSERT INTO products VALUES (?, ?)", (pid, stock))\n\n\n'
           'def stock_de(con, pid):\n    fila = con.execute("SELECT stock FROM products WHERE id = ?", (pid,)).fetchone()\n'
           '    return fila[0] if fila else 0\n')
_PRB_SALES = ("from almacen import db\n\n\ndef validate_stock(con, pid, cantidad):\n"
              "    return db.stock_de(con, pid) >= cantidad\n")


class TestRobustoTorneoConImports(BaseTest):
    def setUp(self):
        super().setUp()
        self.ws = self.proyecto({"tests/test_calc.py": _PRB_TEST_SIN_IMPORT})
        self.spec = copiar_contenidos(self.ws, ["tests/test_calc.py"])

    def test_gana_el_candidato_que_agrega_el_import_y_se_aplica(self):
        self.assertTrue(solo_agrega_imports(_PRB_TEST_SIN_IMPORT, _PRB_TEST_CON_IMPORT))

        def guion(mensajes, kw):
            if _turno(mensajes) >= 1:
                return terminar_xml("listo")
            codigo = herramienta_xml("write_to_file", path="calc.py", content=_PRB_CALC)
            if kw.get("temperatura") == 0.1:
                return codigo + "\n" + herramienta_xml("write_to_file", path="tests/test_calc.py",
                                                       content=_PRB_TEST_CON_IMPORT)
            return codigo
        res = Torneo(MockLLM(guion), self.ws, self.ajustes(candidatos=2, paralelo_torneo=1), self.ui()).correr(
            "implementá calc.py", n=2, protegidos=self.spec, cid=self.ws.checkpoints.iniciar("torneo"))
        self.assertEqual(res.ganador.temperatura, 0.1)                 # antes: empate en rojo y ganaba el otro
        self.assertTrue(res.todos_pasan)
        self.assertEqual(self.ws.leer("tests/test_calc.py"), _PRB_TEST_CON_IMPORT)
        self.assertTrue(ejecutar_tests(self.ws, timeout=60).ok)

    def test_modo_simple_no_le_quita_el_import(self):
        def guion(mensajes, kw):
            if _turno(mensajes) >= 1:
                return terminar_xml("listo")
            return (herramienta_xml("write_to_file", path="calc.py", content=_PRB_CALC) + "\n"
                    + herramienta_xml("write_to_file", path="tests/test_calc.py", content=_PRB_TEST_CON_IMPORT))
        res = Torneo(MockLLM(guion), self.ws, self.ajustes(), self.ui()).correr("implementá", n=1, protegidos=self.spec)
        self.assertEqual(res.modo, "simple")
        self.assertEqual(self.ws.leer("tests/test_calc.py"), _PRB_TEST_CON_IMPORT)   # antes: se restauraba
        self.assertTrue(res.todos_pasan)


class TestRobustoReparacionSinVueltas(BaseTest):
    def _orq(self, archivos, **ajustes):
        ws = self.proyecto(archivos)
        ui = self.ui()
        llm = MockLLM(lambda m, k: terminar_xml("x"))
        return ws, ui, llm, Orquestador(llm, ws, self.ajustes(**ajustes), ui)

    def _reparar(self, orq, ws, max_intentos, informe=None):
        cid = ws.checkpoints.iniciar("tarea")
        informe = informe or InformeBuild("fallida")
        final = orq._reparar_con_escalada("calculadora", orq.verificar(cid), cid, False, informe, "tarea 1",
                                          max_intentos, lambda: orq.verificar(cid))
        return final, informe

    def test_corta_a_los_dos_intentos_inutiles_y_el_siguiente_ve_el_diff(self):
        ws, ui, _llm, orq = self._orq({"calc.py": "def sumar(a, b):\n    return a * b\n",
                                       "tests/test_calc.py": _PRB_TEST_CALC}, forense=False)
        contextos = []

        def reparar(pedido, verif, cid, base_fallaba, experto="", contexto=""):
            contextos.append(contexto)
            if len(contextos) == 1:
                ws.escribir("calc.py", "def sumar(a, b):\n    return a * b + 1\n")    # cambia, mismo error
            return ResultadoAgente(True, f"intento {len(contextos)}")
        orq.reparar = reparar
        final, informe = self._reparar(orq, ws, 6)
        self.assertFalse(final.ok)
        self.assertEqual(len(contextos), 2)                            # antes: 3 (cortaba recién sin cambios)
        self.assertIn("Lo que cambió", contextos[1])                   # el diff real, no solo el relato
        self.assertIn("a * b + 1", contextos[1])
        self.assertIn("2 intentos sin avance", ui.texto_registrado())
        self.assertTrue(any("no avanzó en 2 intentos" in n for n in informe.notas))

    def test_sin_forense_ante_un_error_obvio(self):
        ws, ui, llm, orq = self._orq({"calc.py": "def sumar(a, b):\n    return a + c\n",
                                      "tests/test_calc.py": _PRB_TEST_CALC}, forense=True, lecciones=False)
        vistos = []

        def reparar(pedido, verif, cid, base_fallaba, experto="", contexto=""):
            vistos.append(verif.diagnostico)
            ws.escribir("calc.py", "def sumar(a, b):\n    return a + c + 0\n" if len(vistos) == 1 else _PRB_CALC)
            return ResultadoAgente(True, "listo")
        orq.reparar = reparar
        final, _informe = self._reparar(orq, ws, 3)
        self.assertTrue(final.ok)
        self.assertIn("NameError", vistos[0])
        self.assertNotIn("modo forense", ui.texto_registrado())       # antes: experimentos y pedidos de más
        self.assertEqual(llm.llamadas, [])

    def test_libera_la_especificacion_acoplada_que_bloquea(self):
        ws, ui, _llm, orq = self._orq({"almacen/__init__.py": "", "almacen/db.py": _PRB_DB,
                                       "almacen/sales.py": _PRB_SALES, "tests/__init__.py": "",
                                       "tests/test_sales.py": _PR3_TEST_ACOPLADO}, forense=False)
        orq._protegidos = {"tests/test_sales.py": _PR3_TEST_ACOPLADO}
        informe = InformeBuild("fallida")
        informe.spec_tests = ["tests/test_sales.py"]
        vistos = []

        def reparar(pedido, verif, cid, base_fallaba, experto="", contexto=""):
            vistos.append((set(orq._protegidos), contexto))
            if "tests/test_sales.py" not in orq._protegidos:          # ya liberado: lo corrige
                ws.escribir("tests/test_sales.py", _PR3_TEST_REAL)
            return ResultadoAgente(True, "listo")
        orq.reparar = reparar
        final, informe = self._reparar(orq, ws, 4, informe)
        self.assertTrue(final.ok, final.diagnostico[-1500:])           # antes: cortaba en rojo para siempre
        self.assertEqual(len(vistos), 3)
        self.assertIn("tests/test_sales.py", vistos[0][0])
        self.assertNotIn("tests/test_sales.py", vistos[2][0])
        self.assertIn("LIBERADOS", vistos[2][1])
        self.assertIn("tests/test_sales.py", orq._spec_rotos)         # igual tiene que quedar en verde
        self.assertIn("La libero", ui.texto_registrado())

    def test_una_especificacion_sana_no_se_libera(self):
        ws, _ui, _llm, orq = self._orq({"calc.py": "def sumar(a, b):\n    return a - b\n",
                                        "tests/test_calc.py": _PRB_TEST_CALC}, forense=False)
        orq._protegidos = {"tests/test_calc.py": _PRB_TEST_CALC}
        informe = InformeBuild("fallida")
        informe.spec_tests = ["tests/test_calc.py"]
        orq.reparar = lambda *a, **k: ResultadoAgente(True, "no pude")
        final, _informe = self._reparar(orq, ws, 4, informe)
        self.assertFalse(final.ok)
        self.assertIn("tests/test_calc.py", orq._protegidos)          # el bug está en el código: no se afloja


class TestRobustoEspecificacionAcoplada(BaseTest):
    def test_si_la_reescritura_sigue_acoplada_no_se_protege(self):
        ws = self.proyecto({})
        pedidos = []

        def guion(mensajes, kw):
            if MockLLM.rol_de(mensajes) != "especificador":
                return terminar_xml("listo")
            if MockLLM.turnos_asistente(mensajes) == 0:
                pedidos.append(MockLLM.ultimo_usuario(mensajes))
                return herramienta_xml("write_to_file", path="tests/test_sales.py", content=_PR3_TEST_ACOPLADO)
            return terminar_xml("tests escritos")
        ui = self.ui()
        orq = Orquestador(MockLLM(guion), ws, self.ajustes(tests_primero=True), ui)
        plan = Plan("Ventas", [Tarea("1", "validate_stock", ["almacen/sales.py", "tests/test_sales.py"])], [])
        espec = orq.especificar("Ventas del almacén", plan, ws.checkpoints.iniciar("espec"))
        self.assertEqual(len(pedidos), 2)                              # se le pidió reescribirlo una vez
        self.assertNotIn("tests/test_sales.py", espec)                 # antes: quedaba protegido igual
        self.assertIn("tests/test_sales.py", orq._spec_rotos)
        self.assertIn("Siguen acoplados", ui.texto_registrado())


class TestRobustoTareasDeSoloTests(BaseTest):
    def test_tarea_de_tests_antes_de_su_codigo_se_une(self):
        plan = Plan("CLI", [Tarea("1", "Escribir la prueba unitaria de main", ["tests/test_cli.py"]),
                            Tarea("2", "Implementar main", ["almacen/__main__.py"], ["1"]),
                            Tarea("3", "Documentar", ["README.md"], ["1", "2"])], [])
        avisos = fusionar_tareas_de_solo_tests(plan)
        self.assertEqual(len(avisos), 1)
        self.assertEqual([t.id for t in plan.tareas], ["2", "3"])
        self.assertEqual(plan.tareas[0].archivos, ["almacen/__main__.py", "tests/test_cli.py"])
        self.assertIn("Incluye también sus tests", plan.tareas[0].descripcion)
        self.assertEqual((plan.tareas[0].deps, plan.tareas[1].deps), ([], ["2"]))
        self.assertEqual(errores_grafo_build(plan), [])

    def test_tests_despues_del_codigo_o_ya_escritos_no_se_tocan(self):
        despues = Plan("x", [Tarea("1", "main", ["app.py"]), Tarea("2", "tests", ["tests/test_app.py"], ["1"])], [])
        self.assertEqual(fusionar_tareas_de_solo_tests(despues), [])
        self.assertEqual(len(despues.tareas), 2)
        antes = Plan("x", [Tarea("1", "tests", ["tests/test_app.py"]), Tarea("2", "main", ["app.py"], ["1"])], [])
        self.assertEqual(fusionar_tareas_de_solo_tests(antes, {"tests/test_app.py"}), [])   # la cubre la spec
        self.assertEqual(len(antes.tareas), 2)

    def test_construir_con_la_tarea_de_tests_primero_termina_verificada(self):
        # Antes: la tarea 1 (solo tests) fallaba porque su código era de la tarea 2 → reparaciones, forense, la 2
        # BLOQUEADA y la build FALLIDA aunque el modelo hacía todo bien.
        conv = "def a_fahrenheit(c):\n    return c * 9 / 5 + 32\n"
        ws = self.proyecto({"tests/__init__.py": "", "conv.py": conv})
        plan = ('<plan><objetivo>conv</objetivo><criterios>- a_celsius(212) == 100</criterios>'
                '<tarea id="1" archivos="tests/test_conv.py">Escribir los tests de a_celsius (T1)</tarea>'
                '<tarea id="2" archivos="conv.py" deps="1">Implementar a_celsius en conv.py (T2)</tarea></plan>')
        escribe = {"(T1)": ("tests/test_conv.py", "import unittest\nfrom conv import a_celsius\n\n\n"
                                                  "class T(unittest.TestCase):\n    def test_c(self):\n"
                                                  "        self.assertEqual(a_celsius(212), 100)\n"),
                   "(T2)": ("conv.py", conv + "\n\ndef a_celsius(f):\n    return (f - 32) * 5 / 9\n")}

        def guion(mensajes, kw):
            rol, turno = MockLLM.rol_de(mensajes), MockLLM.turnos_asistente(mensajes)
            if rol == "arquitecto":
                return terminar_xml(plan)
            if rol == "implementador":
                primero = next((m["content"] for m in mensajes if m["role"] == "user"), "")
                tarea = re.search(r"TU TAREA AHORA \(#[^)]*\):\n(.*?)\n\n", primero, re.S)
                archivos = [v for k, v in escribe.items() if k in (tarea.group(1) if tarea else "")]
                if turno < len(archivos):
                    return herramienta_xml("write_to_file", path=archivos[turno][0], content=archivos[turno][1])
            return terminar_xml("listo")
        ui = self.ui()
        informe = Orquestador(MockLLM(guion), ws, self.ajustes(juez=False), ui).construir("conversor", confirmar=False)
        self.assertTrue(informe.ok, ui.texto_registrado()[-3000:])
        self.assertEqual((informe.tareas_fallidas, informe.tareas_bloqueadas), ([], []))
        self.assertIn("unida a la tarea 2", ui.texto_registrado())
        self.assertNotIn("REPARACIÓN", ui.texto_registrado())


_PRB_MAESTRO_FRAGMENTADO = "<maestro><vision>v</vision>" + "".join(
    f'<etapa id="{i}" titulo="CRUD {i}" deps="{i - 1 if i > 1 else ""}"><objetivo>crud de la tabla {i}</objetivo>'
    f'<archivos>app/m{i}.py, tests/test_m{i}.py</archivos></etapa>' for i in range(1, 11)) + "</maestro>"


class TestRobustoPlanMaestroInsistente(BaseTest):
    def test_etapa_de_solo_tests_se_une_a_su_codigo(self):
        m = parsear_maestro('<etapa id="1"><objetivo>datos</objetivo><archivos>a/db.py, tests/test_db.py</archivos>'
                            '</etapa><etapa id="2" deps="1"><objetivo>tests de ventas</objetivo>'
                            '<archivos>tests/test_ventas.py</archivos></etapa><etapa id="3" deps="2">'
                            '<objetivo>ventas</objetivo><archivos>a/ventas.py</archivos></etapa>')
        avisos = normalizar_maestro(m)
        self.assertEqual(len(avisos), 1)
        self.assertEqual([e.id for e in m.etapas], ["1", "3"])
        self.assertEqual(m.etapas[1].archivos, ["a/ventas.py", "tests/test_ventas.py"])
        self.assertEqual(m.etapas[1].deps, ["1"])
        self.assertEqual(problemas_maestro(m, 10), [])
        self.assertEqual(observaciones_maestro(m, ""), [])

    def test_plan_fragmentado_se_agrupa_sin_perder_archivos(self):
        m = parsear_maestro(_PRB_MAESTRO_FRAGMENTADO)
        self.assertTrue(normalizar_maestro(m))
        self.assertEqual(len(m.etapas), 6)
        self.assertEqual(sorted(a for e in m.etapas for a in e.archivos),
                         sorted(a for e in parsear_maestro(_PRB_MAESTRO_FRAGMENTADO).etapas for a in e.archivos))
        self.assertEqual(problemas_maestro(m, 10), [])
        self.assertEqual(observaciones_maestro(m, ""), [])

    def test_planificar_lo_corrige_si_el_modelo_insiste(self):
        respuestas = []

        def responder(mensajes, kw):
            respuestas.append(MockLLM.ultimo_usuario(mensajes))
            return _PRB_MAESTRO_FRAGMENTADO
        ui = self.ui()
        grande = ConstructorGrande(MockLLM(responder), self.proyecto({}), self.ajustes(), ui)
        grande.consultar_cuenta = lambda: None
        maestro = grande.planificar("Un sistema con diez tablas y su CRUD", confirmar=False)
        self.assertIsNotNone(maestro)
        self.assertEqual(len(respuestas), 2)                           # UNA replanificación, como antes
        self.assertEqual(len(maestro.etapas), 6)                       # antes: seguía con 10 etapas de un archivo
        self.assertIn("lo agrupé en 6", ui.texto_registrado())


class _PRB_GuionPartible:
    """/grande de 2 etapas; la 1 tiene DOS módulos. En las tareas marcadas en `rotas` el modelo flojo entrega
    texto.py roto (y el reparador no lo arregla)."""

    MAESTRO = """<maestro>
<vision>Utilidades de números y de textos, y una app que las combina.</vision>
<arquitectura>Python 3 solo librería estándar. Tests con unittest en tests/.</arquitectura>
<etapa id="1" titulo="Utilidades" deps="">
<objetivo>Operaciones con números y con textos.</objetivo>
<archivos>ops.py, texto.py, tests/test_ops.py, tests/test_texto.py</archivos>
<interfaz>
- ops.py: doble(x) -> int
- texto.py: gritar(s) -> str
</interfaz>
</etapa>
<etapa id="2" titulo="App" deps="1">
<objetivo>Una app que combina las utilidades.</objetivo>
<archivos>app.py, tests/test_app.py</archivos>
</etapa>
</maestro>"""
    ARCHIVOS = {
        "ops.py": "def doble(x):\n    return x * 2\n",
        "texto.py": "def gritar(s):\n    return s.upper() + '!'\n",
        "tests/test_ops.py": ("import unittest\n\nfrom ops import doble\n\n\nclass T(unittest.TestCase):\n"
                              "    def test_doble(self):\n        self.assertEqual(doble(4), 8)\n"),
        "tests/test_texto.py": ("import unittest\n\nfrom texto import gritar\n\n\nclass T(unittest.TestCase):\n"
                                "    def test_gritar(self):\n        self.assertEqual(gritar('hola'), 'HOLA!')\n"),
        "app.py": "from ops import doble\nfrom texto import gritar\n\n\ndef saludo(n):\n    return gritar('hola') * doble(n)\n",
        "tests/test_app.py": ("import unittest\n\nfrom app import saludo\n\n\nclass T(unittest.TestCase):\n"
                              "    def test_saludo(self):\n        self.assertEqual(saludo(1), 'HOLA!HOLA!')\n"),
    }
    TEXTO_ROTO = "def gritar(s):\n    return s.lower()\n"
    PLANES = {"1": ("E1", ["ops.py", "texto.py", "tests/test_ops.py", "tests/test_texto.py"]),
              "1a": ("E1a", ["ops.py", "tests/test_ops.py"]),
              "1b": ("E1b", ["texto.py", "tests/test_texto.py"]),
              "2": ("E2", ["app.py", "tests/test_app.py"])}

    def __init__(self, rotas=("E1",), error_en=None):
        self.rotas = set(rotas)
        self.error_en = error_en            # (marca, LLMError): el implementador de esa tarea tira ese error
        self.llamadas = collections.Counter()

    def __call__(self, mensajes, kw):
        rol = MockLLM.rol_de(mensajes)
        self.llamadas[rol] += 1
        primero = next((m["content"] for m in mensajes if m["role"] == "user"), "")
        if rol == "maestro":
            return self.MAESTRO
        if rol == "arquitecto":
            etapa = re.search(r"ETAPA (\w+) de \d+", primero)
            marca, archivos = self.PLANES.get(etapa.group(1) if etapa else "2", self.PLANES["2"])
            return terminar_xml(f'<plan><objetivo>{marca}</objetivo><tarea id="1" archivos="{", ".join(archivos)}">'
                                f'Construir {", ".join(archivos)} ({marca}).</tarea></plan>')
        if rol == "implementador":
            tarea = re.search(r"TU TAREA AHORA \(#[^)]*\):\n(.*?)\n\n", primero, re.S)
            hallada = re.search(r"\((E\d[ab]?)\)", tarea.group(1) if tarea else "")
            marca = hallada.group(1) if hallada else "E1"
            if self.error_en and self.error_en[0] == marca:
                raise self.error_en[1]
            archivos = next(a for m, a in self.PLANES.values() if m == marca)
            turno = _turno(mensajes)
            if turno < len(archivos):
                rel = archivos[turno]
                roto = rel == "texto.py" and marca in self.rotas
                return herramienta_xml("write_to_file", path=rel, content=self.TEXTO_ROTO if roto else self.ARCHIVOS[rel])
            return terminar_xml("listo: archivos escritos")
        return terminar_xml("revisé y no encontré qué cambiar")


class TestRobustoGrandeSeRecupera(BaseTest):
    PEDIDO = "Utilidades de números y textos y una app que las combine, con tests"

    def _grande(self, guion):
        ws = self.proyecto({})
        ui = self.ui()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=1, juez=False, git_snapshots=False, forense=False)
        grande = ConstructorGrande(MockLLM(guion), ws, ajustes, ui)
        grande.consultar_cuenta = lambda: None
        grande.dormir = lambda s: self.fail(f"no debía esperar {s}s")
        return ws, ui, grande

    def test_partir_etapa(self):
        etapa = Etapa("2", "Ventas y reportes", "ventas y reportes",
                      ["a/ventas.py", "a/reportes.py", "tests/test_ventas.py", "tests/test_reportes.py"],
                      "- a/ventas.py: vender()\n- a/reportes.py: por_dia()", ["vende sin pasarse del stock"], ["1"])
        a, b = partir_etapa(etapa, "AssertionError en test_por_dia")
        self.assertEqual((a.id, b.id, a.origen, b.origen), ("2a", "2b", "2", "2"))
        self.assertEqual(a.archivos, ["a/ventas.py", "tests/test_ventas.py"])
        self.assertEqual(b.archivos, ["a/reportes.py", "tests/test_reportes.py"])
        self.assertEqual((a.deps, b.deps), (["1"], ["2a", "1"]))
        self.assertEqual((a.criterios, b.criterios), ([], ["vende sin pasarse del stock"]))
        self.assertIn("vender()", a.interfaz)
        self.assertNotIn("por_dia", a.interfaz)
        self.assertIn("AssertionError en test_por_dia", b.objetivo)
        self.assertIsNone(partir_etapa(Etapa("3", "x", "x", ["a/uno.py", "tests/test_uno.py"]), "m"))

    def test_etapa_fallida_se_deshace_se_parte_y_el_proyecto_termina(self):
        guion = _PRB_GuionPartible(rotas=("E1",))
        ws, ui, grande = self._grande(guion)
        texto = lambda: ui.texto_registrado()
        self.assertTrue(grande.iniciar(self.PEDIDO, confirmar=False), texto()[-4000:])   # antes: DETENIDO en la 1
        estado = grande.leer()
        self.assertEqual(estado["estado"], "terminado")
        self.assertEqual([(e["id"], e["estado"]) for e in estado["maestro"]["etapas"]],
                         [("1a", "verificada"), ("1b", "verificada"), ("2", "verificada")])
        self.assertEqual(estado["maestro"]["etapas"][2]["deps"], ["1b"])
        self.assertEqual([r["etapa"] for r in estado["recuperaciones"]], ["1"])
        self.assertIn("la parto en dos", texto())
        self.assertEqual(ws.leer("texto.py"), _PRB_GuionPartible.ARCHIVOS["texto.py"])
        self.assertTrue(ejecutar_tests(ws, timeout=120).ok)
        self.assertEqual(guion.llamadas["maestro"], 1)

    def test_si_una_parte_tambien_falla_se_detiene_con_el_motivo_real(self):
        guion = _PRB_GuionPartible(rotas=("E1", "E1b"))
        ws, ui, grande = self._grande(guion)
        self.assertFalse(grande.iniciar(self.PEDIDO, confirmar=False))
        estado = grande.leer()
        etapas = {e["id"]: e for e in estado["maestro"]["etapas"]}
        self.assertEqual(estado["estado"], "detenido")
        self.assertEqual(etapas["1a"]["estado"], "verificada")
        self.assertIn(etapas["1b"]["estado"], ("parcial", "fallida"))
        self.assertIn("1b", estado["motivo"])
        self.assertIn("test_gritar", etapas["1b"]["motivo"])            # el error REAL, no "se detuvo"
        self.assertEqual(len(estado["recuperaciones"]), 1)              # una sola recuperación por etapa
        self.assertEqual(etapas["2"]["estado"], "pendiente")
        self.assertFalse(ws.existe("app.py"))
        self.assertIn("DETENIDO", ui.texto_registrado())

    def test_el_cupo_diario_sigue_deteniendo_de_inmediato(self):
        guion = _PRB_GuionPartible(rotas=(), error_en=("E1", _cupo_agotado(6 * 3600)))
        _ws, _ui, grande = self._grande(guion)
        self.assertFalse(grande.iniciar(self.PEDIDO, confirmar=False))
        estado = grande.leer()
        self.assertEqual(estado["estado"], "detenido")
        self.assertIn("cupo diario", estado["motivo"])
        self.assertNotIn("recuperaciones", estado)                      # ni se deshace ni se parte
        self.assertEqual([e["id"] for e in estado["maestro"]["etapas"]], ["1", "2"])


class TestRobustoGrandeEtapaAlTope(BaseTest):
    """Una etapa que ya gastó sus intentos (p. ej. tras varios /grande continuar): antes DETENIDO con "partila o
    corregila a mano" (no hay comando para partirla) y /grande deshacer no le devolvía los intentos."""

    def _detenida_en_1(self):
        guion = _PRB_GuionPartible(rotas=("E1",))
        ws, ui, grande = TestRobustoGrandeSeRecupera._grande(self, guion)
        grande._recuperar_etapa = lambda *a: False                  # como la versión vieja: se detiene en la 1
        self.assertFalse(grande.iniciar(TestRobustoGrandeSeRecupera.PEDIDO, confirmar=False))
        del grande._recuperar_etapa
        return ws, ui, grande, guion

    def _al_tope(self, grande):
        estado = grande.leer()
        maestro = grande.maestro_de(estado)
        maestro.etapas[0].intentos = MAX_INTENTOS_ETAPA
        grande.guardar(estado, maestro)

    def test_al_tope_se_parte_sola_en_vez_de_pedir_imposibles(self):
        ws, ui, grande, guion = self._detenida_en_1()
        self._al_tope(grande)
        antes = guion.llamadas["arquitecto"]
        self.assertTrue(grande.continuar(), ui.texto_registrado()[-3000:])
        estado = grande.leer()
        self.assertEqual(estado["estado"], "terminado")
        self.assertEqual([e["id"] for e in estado["maestro"]["etapas"]], ["1a", "1b", "2"])
        self.assertEqual(guion.llamadas["arquitecto"] - antes, 3)       # 1a, 1b y 2: la 1 entera no se reintentó
        self.assertNotIn("a mano", ui.texto_registrado())
        self.assertTrue(ejecutar_tests(ws, timeout=120).ok)

    def test_deshacer_le_devuelve_los_intentos(self):
        _ws, ui, grande, _guion = self._detenida_en_1()
        self._al_tope(grande)
        self.assertTrue(grande.deshacer_etapa())
        self.assertEqual(grande.leer()["maestro"]["etapas"][0]["intentos"], 0)

    def test_estado_viejo_deshecho_y_al_tope_se_parte_sin_diario(self):
        ws, ui, grande, _guion = self._detenida_en_1()
        self.assertTrue(grande.deshacer_etapa())
        self._al_tope(grande)                                          # un estado de antes de este arreglo
        self.assertIsNone(RegistroBuild(ws).leer())
        self.assertTrue(grande.continuar(), ui.texto_registrado()[-3000:])
        self.assertEqual(grande.leer()["estado"], "terminado")

    def test_una_parte_al_tope_se_detiene_con_el_motivo_y_como_seguir(self):
        guion = _PRB_GuionPartible(rotas=("E1", "E1b"))
        _ws, ui, grande = TestRobustoGrandeSeRecupera._grande(self, guion)
        self.assertFalse(grande.iniciar(TestRobustoGrandeSeRecupera.PEDIDO, confirmar=False))
        estado = grande.leer()
        maestro = grande.maestro_de(estado)
        maestro.por_id("1b").intentos = MAX_INTENTOS_ETAPA
        grande.guardar(estado, maestro)
        self.assertFalse(grande.continuar())
        motivo = grande.leer()["motivo"]
        self.assertIn("ya se intentó", motivo)
        self.assertIn("/grande deshacer", motivo)
        self.assertNotIn("a mano", motivo)


class TestRobustoGrandeDiarioDeOtraCarpeta(BaseTest):
    def test_no_le_echa_la_culpa_al_modelo_y_dice_como_seguir(self):
        guion = _PRB_GuionPartible(rotas=("E1",))
        ws, ui, grande = TestRobustoGrandeSeRecupera._grande(self, guion)
        grande._recuperar_etapa = lambda *a: False
        self.assertFalse(grande.iniciar(TestRobustoGrandeSeRecupera.PEDIDO, confirmar=False))
        del grande._recuperar_etapa
        diario = RegistroBuild(ws).ruta
        datos = json.loads(diario.read_text(encoding="utf-8"))
        datos["proyecto"] = "/otra/carpeta/almacen"                     # el proyecto se movió de carpeta
        diario.write_text(json.dumps(datos), encoding="utf-8")
        self.assertFalse(grande.continuar())
        motivo = grande.leer()["motivo"]
        self.assertNotIn("el modelo no responde", motivo)
        self.assertIn("otro proyecto", motivo)
        self.assertIn("/construir descartar", motivo)
