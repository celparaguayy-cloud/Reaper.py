"""
Autotests REAPER X (fases C y D de la especificación de 10 agentes), sobre la base de este repositorio:
  - clasificación tipada de imports en tests primero (rojo esperado vs typo vs paquete externo vs sintaxis);
  - una tarea que falla su verificación BLOQUEA a sus dependientes y la build no termina "verificada".
"""

_PLAN_INV = "PLAN: src/inventario.py: def agregar(lista, x) -> list; src/api.py: def crear_empresa(datos) -> int"
_MSG_FALTAN = "Módulos no instalados ni presentes en el proyecto: {}\n(Instalalos con pip o usá la librería estándar.)"


def _r_imports(modulos: str, archivo: str = "tests/test_inv.py") -> Resultado:
    return Resultado(False, f"imports {archivo}", 1, stderr=_MSG_FALTAN.format(modulos), archivo=archivo)


class TestClasificacionImportsTDD(BaseTest):
    def test_tdd_expected_red_import_does_not_block_specifier(self):
        quedan, esperados, clases = separar_imports_tdd([_r_imports("inventario")], _PLAN_INV)
        self.assertEqual(quedan, [])
        self.assertEqual(len(esperados), 1)
        self.assertEqual(clases[0].causa, "MODULO_PROPIO_AUSENTE")
        self.assertTrue(clases[0].esperado)

    def test_tdd_typo_import_does_not_count_as_expected_red(self):
        quedan, esperados, clases = separar_imports_tdd([_r_imports("inventaro")], _PLAN_INV)
        self.assertEqual(esperados, [])
        self.assertEqual(clases[0].causa, "TYPO")
        self.assertIn("TYPO", quedan[0].stderr)                 # sigue fallando y explica por qué

    def test_tdd_missing_external_package_is_not_expected_red(self):
        quedan, esperados, clases = separar_imports_tdd([_r_imports("paquete_externo_zzz")], _PLAN_INV)
        self.assertEqual(esperados, [])
        self.assertEqual(clases[0].causa, "PAQUETE_EXTERNO")
        self.assertEqual(len(quedan), 1)

    def test_mezcla_esperado_y_real_no_se_acepta(self):
        quedan, esperados, _c = separar_imports_tdd([_r_imports("inventario, paquete_externo_zzz")], _PLAN_INV)
        self.assertEqual(esperados, [])                         # un solo import real alcanza para fallar
        self.assertEqual(len(quedan), 1)

    def test_tdd_syntax_error_is_never_accepted(self):
        sintaxis = Resultado(False, "py_compile tests/test_inv.py", 1, stderr="SyntaxError", archivo="tests/test_inv.py")
        quedan, esperados, _c = separar_imports_tdd([sintaxis], _PLAN_INV)
        self.assertEqual(quedan, [sintaxis])
        self.assertEqual(esperados, [])

    def test_nombre_planeado_en_modulo_existente_es_esperado(self):
        r = Resultado(False, "imports-locales tests/test_api.py", 1, archivo="tests/test_api.py",
                      stderr="línea 3: src/api.py no define 'crear_empresa'")
        _q, esperados, clases = separar_imports_tdd([r], _PLAN_INV)
        self.assertEqual(clases[0].causa, "NOMBRE_PLANEADO_AUSENTE")
        self.assertEqual(len(esperados), 1)

    def test_nombre_con_typo_en_modulo_existente_no_es_esperado(self):
        r = Resultado(False, "imports-locales tests/test_api.py", 1, archivo="tests/test_api.py",
                      stderr="línea 3: src/api.py no define 'crear_empresaa' (¿quisiste decir 'crear_empresa'?)")
        quedan, esperados, clases = separar_imports_tdd([r], _PLAN_INV)
        self.assertEqual(clases[0].causa, "TYPO")
        self.assertEqual(esperados, [])
        self.assertEqual(len(quedan), 1)

    def test_modulos_planeados_ignora_tests(self):
        self.assertEqual(modulos_planeados("src/db.py tests/test_db.py app.py"), {"src", "db", "app"})

    def test_especificador_con_typo_no_puede_cerrar(self):
        test = "import sys\nsys.path.insert(0, 'src')\nfrom inventaro import agregar\n\n\ndef test_a():\n    assert agregar([], 1) == [1]\n"

        def guion(mensajes, kwargs):
            if _turno(mensajes) == 0:
                return herramienta_xml("write_to_file", path="tests/test_inv.py", content=test)
            return terminar_xml("tests escritos")

        ui = self.ui()
        Agente("especificador", MockLLM(guion), self.proyecto({}), self.ajustes(), ui, memoria=None,
               mostrar_progreso=False).ejecutar("escribí los tests. " + _PLAN_INV)
        self.assertIn("cierre rechazado", ui.texto_registrado())   # el typo NO se disfraza de rojo esperado


class TestBloqueoDependientes(BaseTest):
    PLAN = """<plan>
<objetivo>Dos módulos</objetivo>
<tarea id="1" archivos="a.py">Crear a.py con def uno(): return 1</tarea>
<tarea id="2" archivos="b.py" deps="1">Crear b.py con def dos() que usa uno() de a.py</tarea>
<criterios>
- uno() == 1
</criterios>
</plan>"""

    def test_failed_dependency_blocks_downstream_tasks(self):
        pedidos_implementador = []

        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            turno = _turno(mensajes)
            if rol == "arquitecto":
                return terminar_xml(self.PLAN)
            if rol == "implementador":
                pedidos_implementador.append(mensajes[1]["content"] if len(mensajes) > 1 else "")
                if turno == 0:
                    return herramienta_xml("write_to_file", path="a.py", content="def uno(:\n    return 1\n")
                return terminar_xml("hecho")
            return terminar_xml("no pude")

        ws = self.proyecto({"README.md": "# dos\n"})
        ajustes = self.ajustes(tests_primero=False, torneo=False, max_revisiones=0, lecciones=False,
                               max_reparaciones=1, umbral_escalada=0)
        informe = Orquestador(MockLLM(guion), ws, ajustes, self.ui()).construir("dos módulos", confirmar=False)
        self.assertEqual(informe.tareas_fallidas, ["1"])
        self.assertEqual(informe.tareas_bloqueadas, ["2"])
        self.assertNotEqual(informe.estado, "verificada")
        self.assertEqual([tid for tid, _modo, _g in informe.torneos], ["1"])  # la tarea 2 nunca se implementó
        self.assertTrue(pedidos_implementador)
        self.assertFalse((ws.raiz / "b.py").exists())

    def test_incomplete_product_is_partial_not_verified(self):
        informe = InformeBuild("parcial", tareas_bloqueadas=["2"])
        self.assertFalse(informe.ok)


class TestResultadosVeraces(BaseTest):
    def test_command_checkmark_does_not_mean_zero_exit_code(self):
        guion = [herramienta_xml("execute_command", command="python3 -c \"import sys; sys.exit(3)\""),
                 terminar_xml("listo")]
        ui = self.ui()
        Agente("principal", MockLLM(guion), self.proyecto({}), self.ajustes(modo="auto"), ui, memoria=None,
               mostrar_progreso=False).ejecutar("corré el comando")
        texto = ui.texto_registrado()
        self.assertIn("exit 3", texto)
        self.assertNotIn("✓ $ python3 -c", texto)                 # ya no se dibuja ✓ en un exit != 0

    def test_exit_cero_sigue_con_check(self):
        guion = [herramienta_xml("execute_command", command="python3 -c \"print(1)\""), terminar_xml("listo")]
        ui = self.ui()
        Agente("principal", MockLLM(guion), self.proyecto({}), self.ajustes(modo="auto"), ui, memoria=None,
               mostrar_progreso=False).ejecutar("corré el comando")
        self.assertIn("✓ $ python3 -c", ui.texto_registrado())

    def test_zero_collected_tests_is_not_success(self):
        ws = self.proyecto({"tests/test_vacio.py": "# sin tests\n", "app.py": "x = 1\n"})
        orq = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        verif = orq.verificar(ws.checkpoints.iniciar("x"))
        self.assertFalse(verif.ok)
        self.assertIn("no recolectó ningún test", verif.diagnostico)
