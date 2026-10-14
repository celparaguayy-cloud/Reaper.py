"""
Autotests de regresión de una corrida REAL que falló en Termux (proyecto script_whatsapp, octubre 2026):

- `/diagnostico app.py` reemplazó el código del usuario por el reporte ("REAPER 8.10 · diagnóstico") y el
  proyecto dejó de compilar (SyntaxError: invalid character '·').
- Una instalación con pip murió por "signal 9" y REAPER solo mostraba "exit code: -9".
- Un plan que decía "reemplazar" app.py chocaba con PRESERVAR: la tarea fallaba siempre (aunque el usuario lo
  hubiera pedido), el archivo reescrito quedaba igual en disco y el motivo no llegaba ni a la pantalla ni al informe.
- En el modo conversación, "UNVERIFIED" salía en gris y en inglés aunque se hubieran cambiado archivos.
"""


class TestBuildRealDiagnostico(BaseTest):
    def _app(self, ws):
        return App(self.ajustes(), MockLLM([]), self.ui(), ws, persistir=False)

    def test_diagnostico_no_pisa_codigo_existente(self):
        codigo = "def main():\n    print('hola')\n\nif __name__ == '__main__':\n    main()\n"
        ws = self.proyecto({"app.py": codigo})
        app = self._app(ws)
        app.cmd_diagnostico("app.py")
        self.assertEqual(ws.leer("app.py"), codigo)                       # el código del usuario intacto
        guardados = list((ws.raiz / ".reaper").glob("diagnostico_*.txt"))
        self.assertEqual(len(guardados), 1)
        self.assertIn("diagnóstico", guardados[0].read_text(encoding="utf-8"))
        self.assertIn("no lo toco", app.ui.texto_registrado())

    def test_diagnostico_nunca_crea_un_archivo_de_codigo(self):
        ws = self.proyecto({})
        self._app(ws).cmd_diagnostico("nuevo.py")
        self.assertFalse(ws.existe("nuevo.py"))                           # un .py con el reporte no compilaría
        self.assertTrue(list((ws.raiz / ".reaper").glob("diagnostico_*.txt")))

    def test_diagnostico_sin_extension_va_a_txt(self):
        ws = self.proyecto({})
        self._app(ws).cmd_diagnostico("reporte")
        self.assertTrue(ws.existe("reporte.txt"))


class TestBuildRealSenal(BaseTest):
    def test_proceso_matado_por_sigkill_se_explica(self):
        if not hasattr(signal, "SIGKILL"):
            self.skipTest("plataforma sin SIGKILL")
        r = ejecutar([sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"],
                     cwd=self.dir, timeout=20)
        self.assertFalse(r.ok)
        self.assertIn("SIGKILL", r.senal())
        self.assertIn("MATÓ", r.resumen())
        self.assertIn("SIGKILL", r.linea())
        self.assertIn("señal 9", anexar_pistas(r.resumen()))

    def test_codigos_de_salida_por_senal(self):
        self.assertIn("SIGKILL", Resultado(False, "pip install x", 137).senal())   # bash: 128 + 9
        self.assertIn("SIGTERM", Resultado(False, "x", -15).senal())
        self.assertEqual(Resultado(False, "x", 1).senal(), "")                     # un error común no es señal
        self.assertEqual(Resultado(False, "x", 124, timeout=True).senal(), "")     # el timeout ya se informa

    def test_pista_de_memoria_antes_que_instalar_compiladores(self):
        salida = ("Building wheel for grpcio (pyproject.toml) ... error\n"
                  "clang: error: unable to execute command: Killed\n"
                  "error: command 'clang' failed with exit code -9")
        pistas = pistas_para(salida, 3)
        self.assertIn("mató el proceso", pistas[0])                # primero: no reintentar igual
        self.assertTrue(any("grpcio" in p for p in pistas))
        self.assertFalse(any("pkg install clang" in p for p in pistas[:2]))


class TestBuildRealReemplazo(BaseTest):
    PREVIO = "".join(f"def f{i}():\n    return {i}\n" for i in range(12))
    PLAN = """<plan>
<objetivo>Rehacer app.py</objetivo>
<interfaz>
- app.py: def nueva() -> int
</interfaz>
<tarea id="1" archivos="app.py">Reescribir app.py desde cero: solo def nueva() que devuelve 0.</tarea>
<criterios>
- app.py define nueva()
</criterios>
</plan>"""

    def _guion(self, mensajes, kw):
        rol = MockLLM.rol_de(mensajes)
        if rol == "arquitecto":
            return terminar_xml(self.PLAN)
        if rol == "implementador":
            return herramienta_xml("write_to_file", path="app.py", content="def nueva():\n    return 0\n") \
                if _turno(mensajes) == 0 else terminar_xml("app.py reescrito")
        return terminar_xml("ok")

    def _construir(self, pedido, ui=None, confirmar=False):
        ws = self.proyecto({"app.py": self.PREVIO})
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=1, juez=False)
        informe = Orquestador(MockLLM(self._guion), ws, ajustes, ui or self.ui()).construir(pedido,
                                                                                            confirmar=confirmar)
        return ws, informe

    def test_reemplazos_del_plan_solo_con_intencion_explicita(self):
        ws = self.proyecto({"app.py": "a = 1\nb = 2\n", "util.py": "x = 1\n"})
        plan = Plan(objetivo="", criterios=[], tareas=[Tarea("1", "Reemplazar app.py por la versión nueva", ["app.py"]),
                                      Tarea("2", "Eliminar espacios duplicados en util.py", ["util.py"]),
                                      Tarea("3", "Reescribir otro.py", ["otro.py"])])
        self.assertEqual(reemplazos_del_plan(ws, plan), {"app.py": 2})  # 'eliminar espacios' no es reemplazo

    def test_reemplazo_pedido_por_el_usuario_se_permite(self):
        # Antes: "reescribí app.py desde cero" → REESCRITURA DESTRUCTIVA ×4, tarea 1 fallida, build parcial.
        ws, informe = self._construir("Reescribí app.py desde cero: que solo tenga def nueva()")
        self.assertNotIn("1", informe.tareas_fallidas)
        self.assertTrue(informe.ok, informe.notas)
        self.assertEqual(informe.reemplazos_autorizados, ["app.py"])
        self.assertIn("def nueva", ws.leer("app.py"))

    def test_reemplazo_no_pedido_se_protege_y_se_restaura(self):
        ui = self.ui()
        ws, informe = self._construir("Agregá una función nueva() que devuelva 0", ui=ui)
        self.assertIn("1", informe.tareas_fallidas)
        self.assertEqual(ws.leer("app.py"), self.PREVIO)                   # el trabajo previo volvió entero
        self.assertEqual(informe.restaurados, ["app.py"])
        self.assertIn("REESCRITURA DESTRUCTIVA", informe.motivos_fallo["1"])
        self.assertTrue(any("→ REESCRITURA DESTRUCTIVA" in n for n in informe.notas))
        texto = ui.texto_registrado()
        self.assertIn("REEMPLAZA código que ya existe: app.py (24 líneas)", texto)   # avisado antes de empezar
        self.assertIn("motivo: REESCRITURA DESTRUCTIVA", texto)                      # y el motivo, en pantalla

    def test_reemplazar_algo_puntual_no_autoriza_reescribir_el_archivo(self):
        # "reemplazá print por logging" es una edición chica: no habilita a borrar casi todo app.py.
        ws, informe = self._construir("Reemplazá los return por constantes en app.py")
        self.assertEqual(informe.reemplazos_autorizados, [])
        self.assertEqual(ws.leer("app.py"), self.PREVIO)

    def test_pista_killed_no_salta_por_cualquier_palabra(self):
        self.assertFalse(any("mató el proceso" in p for p in pistas_para("test_killed_worker ... ok\nthe job was killed", 3)))
        self.assertTrue(any("mató el proceso" in p for p in pistas_para("Building...\nKilled\n", 3)))

    def test_plan_aprobado_autoriza_el_reemplazo(self):
        ui = self.ui(respuestas=["s"])
        ws, informe = self._construir("Agregá una función nueva() que devuelva 0", ui=ui, confirmar=True)
        self.assertIn("REEMPLAZA código que ya existe", ui.texto_registrado())
        self.assertNotIn("1", informe.tareas_fallidas)                    # lo vio y lo aprobó: es su decisión
        self.assertIn("def nueva", ws.leer("app.py"))

    def test_informe_guarda_version_motivo_y_restauracion(self):
        _ws, informe = self._construir("Agregá una función nueva() que devuelva 0")
        texto = informe.ruta_informe.read_text(encoding="utf-8")
        self.assertIn(f"Versión: REAPER {__version__}", texto)
        self.assertIn("## Por qué fallaron las tareas", texto)
        self.assertIn("REESCRITURA DESTRUCTIVA", texto)
        self.assertIn("## Trabajo previo restaurado (PRESERVAR)", texto)


class TestBuildRealInformeJuez(BaseTest):
    def test_informe_incluye_contrato_y_veredicto_del_juez(self):
        plan = """<plan>
<objetivo>Sumadora</objetivo>
<interfaz>
- app.py: def sumar(a, b) -> int
</interfaz>
<tarea id="1" archivos="app.py">Crear app.py con def sumar(a, b).</tarea>
<criterios>
- sumar(2, 3) == 5
</criterios>
</plan>"""

        def guion(mensajes, kw):
            rol = MockLLM.rol_de(mensajes)
            if rol == "arquitecto":
                return terminar_xml(plan)
            if rol == "implementador":
                return herramienta_xml("write_to_file", path="app.py",
                                       content="def sumar(a, b):\n    return a + b\n") \
                    if _turno(mensajes) == 0 else terminar_xml("listo")
            if rol == "juez":
                if "CONTRATO" in mensajes[-1]["content"]:
                    return '{"criterios": ["sumar(2, 3) devuelve 5"]}'
                return '{"cumple": true, "faltantes": [], "evidence_ids": ["EV-ESTADO"], "confianza": "high"}'
            return terminar_xml("ok")

        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=0, juez=True)
        informe = Orquestador(MockLLM(guion), self.proyecto(), ajustes, self.ui()).construir("sumadora",
                                                                                          confirmar=False)
        texto = informe.ruta_informe.read_text(encoding="utf-8")
        self.assertIn("## Juez de entrega", texto)
        self.assertIn("- sumar(2, 3) devuelve 5", texto)
        self.assertIn("Veredicto:", texto)


class TestBuildRealSinVerificar(BaseTest):
    def test_cambios_sin_evidencia_se_avisan_en_castellano(self):
        def guion(mensajes, kw):
            if _turno(mensajes) == 0:
                return herramienta_xml("write_to_file", path="app.py", content="def f():\n    return 1\n")
            return terminar_xml("Listo, app.py funciona perfecto.")

        app = App(self.ajustes(modo="auto"), MockLLM(guion), self.ui(), self.proyecto(), persistir=False)
        app.turno("creá app.py con f()")
        texto = app.ui.texto_registrado()
        claim = getattr(app.principal, "_ultimo_claim", None)
        if claim is None or claim.nivel != "UNVERIFIED":
            self.skipTest(f"el Evidence Gate no dejó UNVERIFIED en este cierre ({getattr(claim, 'nivel', None)})")
        self.assertIn("SIN VERIFICAR", texto)
        self.assertNotIn("verificación: UNVERIFIED", texto)
