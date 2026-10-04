"""
Robustez frente a un modelo torpe: un guion "ideal" se corrompe con los errores típicos de un modelo de
24B (los mismos que se vieron en Termux) y REAPER tiene que terminar bien igual.

Defectos simulables (se combinan):
  fences          envuelve cada herramienta en ```xml ... ```
  sin_cierre      olvida la etiqueta de cierre de la herramienta
  alias           usa nombres alternativos (read_function, file=, cmd=)
  comillas        pone comillas alrededor de rutas y comandos
  json            escribe la llamada como JSON {"tool": ..., "args": {...}}
  repite          repite una vez cada llamada (el "tool loop" de 2+2)
  inventa         inventa un <resultado> después de la llamada (lo corta el stop)
  texto_final     termina con texto suelto en vez de attempt_completion
  afirma_falso    el informe final dice que validó y que los tests pasan
"""

DEFECTOS_TORPES = ("fences", "sin_cierre", "alias", "comillas", "json", "repite", "inventa", "texto_final",
                   "afirma_falso")

_ALIAS_TORPES = {"read_symbol": "read_function", "replace_symbol": "replace_function", "read_file": "view_file",
                 "write_to_file": "create_file", "execute_command": "run_command"}
_ALIAS_PARAMS_TORPES = {"path": "file", "command": "cmd"}


def _corromper(texto: str, defectos: set) -> str:
    analisis = analizar(texto, esquemas())
    if not analisis.llamadas:
        return texto
    llamada = analisis.llamadas[0]
    prefijo = analisis.texto
    if "json" in defectos:
        cuerpo = json.dumps({"tool": llamada.nombre, "args": llamada.params}, ensure_ascii=False)
    else:
        nombre = _ALIAS_TORPES.get(llamada.nombre, llamada.nombre) if "alias" in defectos else llamada.nombre
        partes = []
        for clave, valor in llamada.params.items():
            etiqueta = _ALIAS_PARAMS_TORPES.get(clave, clave) if "alias" in defectos else clave
            if "comillas" in defectos and clave in ("path", "command") and not re.search(r"[\"'`]", str(valor)):
                valor = f'"{valor}"'  # como hacen los modelos: <path>"calc.py"</path>
            separador = "\n" if "\n" in str(valor) or clave in ("content", "diff", "result") else ""
            partes.append(f"<{etiqueta}>{separador}{valor}{separador}</{etiqueta}>")
        cierre = "" if "sin_cierre" in defectos and llamada.nombre != "attempt_completion" else f"\n</{nombre}>"
        cuerpo = f"<{nombre}>\n" + "\n".join(partes) + cierre
    if "fences" in defectos:
        cuerpo = f"```xml\n{cuerpo}\n```"
    if "inventa" in defectos:
        cuerpo += '\n<resultado herramienta="x">\nTests PASARON: todo perfecto.\n</resultado>\nListo, todo funciona.'
    return (prefijo + "\n" if prefijo else "") + cuerpo


def guion_torpe(pasos: list, informe: str, defectos: Iterable[str]) -> Callable:
    """Guion para MockLLM: recorre `pasos` (llamadas ideales) cometiendo los `defectos` indicados."""
    defectos = set(defectos)
    estado = {"i": 0, "ultimo": None, "repetidos": set()}

    def guion(mensajes, kwargs):
        if "repite" in defectos and estado["ultimo"] is not None and estado["ultimo"] not in estado["repetidos"]:
            estado["repetidos"].add(estado["ultimo"])
            return _corromper(pasos[estado["ultimo"]], defectos)
        if estado["i"] < len(pasos):
            estado["ultimo"] = estado["i"]
            estado["i"] += 1
            return _corromper(pasos[estado["ultimo"]], defectos)
        estado["ultimo"] = None
        final = "Listo, validé todo y los tests pasan." if "afirma_falso" in defectos else informe
        if "texto_final" in defectos:
            return final
        return _corromper(terminar_xml(final), defectos - {"sin_cierre"})

    return guion


_CALC_ROTA = "def suma(a, b):\n    return a - b\n\n\ndef resta(a, b):\n    return a - b\n"
_TEST_SUMA = ("import unittest\nfrom calc import suma, resta\n\n\nclass T(unittest.TestCase):\n"
              "    def test_suma(self):\n        self.assertEqual(suma(2, 3), 5)\n\n"
              "    def test_resta(self):\n        self.assertEqual(resta(5, 3), 2)\n")


class TestRobustezModeloTorpe(BaseTest):
    PASOS_ARREGLO = [
        herramienta_xml("read_symbol", path="calc.py", symbol="suma"),
        herramienta_xml("replace_symbol", path="calc.py", symbol="suma", content="def suma(a, b):\n    return a + b"),
        herramienta_xml("run_tests"),
    ]

    def _arreglar(self, defectos) -> tuple:
        ws = self.proyecto({"calc.py": _CALC_ROTA, "tests/test_calc.py": _TEST_SUMA})
        llm = MockLLM(guion_torpe(self.PASOS_ARREGLO, "Arreglé suma: run_tests pasa.", defectos))
        res = Agente("principal", llm, ws, self.ajustes(max_pasos=16), self.ui(), memoria=None,
                     mostrar_progreso=False).ejecutar("arreglá suma en calc.py")
        return res, ws, llm

    def test_cada_defecto_por_separado(self):
        for defecto in DEFECTOS_TORPES:
            with self.subTest(defecto=defecto):
                res, ws, llm = self._arreglar({defecto})
                self.assertIn("return a + b", ws.leer("calc.py"), f"{defecto}: no se aplicó el arreglo")
                self.assertLessEqual(len(llm.llamadas), 9, f"{defecto}: demasiadas vueltas")
                if defecto != "afirma_falso":
                    self.assertTrue(res.ok, f"{defecto}: {res.motivo} {res.resumen[:200]}")
                    self.assertNotIn("⚠ REAPER", res.resumen)

    def test_afirmacion_verdadera_no_se_marca(self):
        res, _ws, _llm = self._arreglar({"afirma_falso"})
        # corrió run_tests y pasaron: "los tests pasan" es verdad y se acepta sin advertencia
        self.assertNotIn("⚠ REAPER", res.resumen)

    def test_todos_los_defectos_juntos(self):
        res, ws, llm = self._arreglar(set(DEFECTOS_TORPES) - {"json"})
        self.assertIn("return a + b", ws.leer("calc.py"))
        self.assertTrue(res.ok, res.resumen[:300])
        self.assertLessEqual(len(llm.llamadas), 12)

    def test_json_con_otros_defectos(self):
        res, ws, _llm = self._arreglar({"json", "repite", "inventa", "texto_final"})
        self.assertIn("return a + b", ws.leer("calc.py"))
        self.assertTrue(res.ok)

    def test_afirma_falso_sin_haber_verificado(self):
        ws = self.proyecto({"calc.py": _CALC_ROTA, "tests/test_calc.py": _TEST_SUMA})
        pasos = self.PASOS_ARREGLO[:2]  # arregla pero nunca corre los tests
        llm = MockLLM(guion_torpe(pasos, "", {"afirma_falso", "fences", "repite"}))
        res = Agente("principal", llm, ws, self.ajustes(max_pasos=16), self.ui(), memoria=None,
                     mostrar_progreso=False).ejecutar("arreglá suma en calc.py")
        self.assertIn("⚠ REAPER", res.resumen, "la afirmación sin evidencia tiene que quedar marcada")

    def test_dos_mas_dos_torpe(self):
        for defectos in ({"repite"}, {"repite", "fences", "texto_final"}, {"inventa", "comillas", "texto_final"}):
            with self.subTest(defectos=sorted(defectos)):
                pasos = [herramienta_xml("execute_command", command='python3 -c "print(2+2)"')]
                llm = MockLLM(guion_torpe(pasos, "2+2 = 4", defectos))
                res = Agente("principal", llm, self.proyecto(), self.ajustes(), self.ui(), memoria=None,
                             mostrar_progreso=False).ejecutar("cuánto es 2+2? usá python")
                self.assertIn("4", res.resumen)
                self.assertTrue(res.ok)
                self.assertLessEqual(len(llm.llamadas), 4)

    def test_comillas_sobrantes_se_quitan(self):
        pasos = [herramienta_xml("write_to_file", path="s.py", content="X = 1\n"),
                 herramienta_xml("execute_command", command="'python3 -c \"import s; print(s.X)\"'")]
        llm = MockLLM(guion_torpe(pasos, "Creé s.py y lo probé: imprime 1.", {"texto_final"}))
        res = Agente("principal", llm, self.proyecto(), self.ajustes(), self.ui(), memoria=None,
                     mostrar_progreso=False).ejecutar("creá s.py con X = 1")
        self.assertNotIn("⚠ REAPER", res.resumen)
        self.assertIn("STDOUT:\n1", MockLLM.ultimo_usuario(llm.llamadas[-1]["mensajes"]))

    def test_comando_que_falla_no_se_da_por_probado(self):
        """Si el comando falla y el modelo igual dice 'lo probé', REAPER lo marca (lo que pasó en Termux)."""
        pasos = [herramienta_xml("write_to_file", path="s.py", content="X = 1\n"),
                 herramienta_xml("execute_command", command='python3 -c "import s; print(s.Y)"')]
        llm = MockLLM(guion_torpe(pasos, "Creé s.py y lo probé: imprime 1.", {"texto_final"}))
        res = Agente("principal", llm, self.proyecto(), self.ajustes(), self.ui(), memoria=None,
                     mostrar_progreso=False).ejecutar("creá s.py con X = 1")
        self.assertIn("⚠ REAPER", res.resumen)
        self.assertIn("FALLÓ", res.resumen)

    def test_crear_archivo_nuevo_torpe(self):
        pasos = [
            herramienta_xml("write_to_file", path="saludo.py",
                            content='def saludar(nombre):\n    return f"Hola, {nombre}!"\n'),
            herramienta_xml("execute_command", command='python3 -c "from saludo import saludar; print(saludar(\'Ana\'))"'),
        ]
        for defectos in ({"alias", "comillas"}, {"sin_cierre", "fences", "repite"}, {"json", "texto_final"}):
            with self.subTest(defectos=sorted(defectos)):
                ws = self.proyecto(nombre="nuevo_" + "_".join(sorted(defectos)))
                llm = MockLLM(guion_torpe(pasos, "Creé saludo.py y lo probé: imprime Hola, Ana!", defectos))
                res = Agente("principal", llm, ws, self.ajustes(), self.ui(), memoria=None,
                             mostrar_progreso=False).ejecutar("creá saludo.py con una función saludar")
                self.assertTrue((ws.raiz / "saludo.py").exists())
                self.assertIn("Hola, {nombre}!", ws.leer("saludo.py"))
                self.assertTrue(res.ok, res.resumen[:200])
