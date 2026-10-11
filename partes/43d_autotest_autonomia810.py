"""Pruebas sin red para continuidad, regresiones de estado y privacidad de sesiones."""


class TestReaper810Autonomia(BaseTest):
    def _app(self, persistir=False):
        ws = self.proyecto({"main.py": "print('saludo')\n"})
        app = App(self.ajustes(max_pasos=3, lecciones=False), MockLLM([]), self.ui(), ws,
                  persistir=persistir)
        return app

    def test_guarda_pendiente_al_agotar_pasos(self):
        app = self._app()
        app.principal.ejecutar = lambda task, cid_inicio=None: ResultadoAgente(
            False, "Falta crear las pruebas", ["main.py"], 3, "max_pasos", "principal")
        self.assertFalse(app.turno("Crear API local con pruebas"))
        self.assertEqual(app.pendiente["motivo"], "max_pasos")
        self.assertEqual(app.pendiente["pedido"], "Crear API local con pruebas")
        app.comando("/pendiente")
        self.assertIn("Crear API local", app.ui.texto_registrado())

    def test_reanuda_y_no_pierde_objetivo(self):
        app = self._app()
        recibidos = []
        def ejecutar(task, cid_inicio=None):
            recibidos.append(task)
            if len(recibidos) == 1:
                return ResultadoAgente(False, "API parcial", ["main.py"], 3, "max_pasos", "principal")
            return ResultadoAgente(True, "Finalizado tras validar", [], 2, "completado", "principal")
        app.principal.ejecutar = ejecutar
        app.turno("Crear API local con tests")
        app.comando("/continuar")
        self.assertIn("Crear API local con tests", recibidos[-1])
        self.assertIn("no repitas trabajo", recibidos[-1].lower())
        self.assertEqual(app.pendiente, None)

    def test_reanuda_maximo_tres_veces(self):
        app = self._app()
        app.pendiente = {"pedido": "Crear API", "intentos": 3, "cambios": [], "motivo": "bucle"}
        invocado = []
        app.turno = lambda *args, **kwargs: invocado.append(args)
        app.comando("/continuar")
        self.assertFalse(invocado)
        self.assertIn("3 veces", app.ui.texto_registrado())

    def test_persistencia_por_proyecto_y_redaccion(self):
        app = self._app(persistir=True)
        app.pendiente = {"pedido": "Arreglar pruebas", "resumen": "sk-abcdefghijklmnop123456789",
                         "intentos": 0, "cambios": [], "motivo": "max_pasos"}
        app.historial.append(("17:05", "password = hunter2222", False))
        app._guardar_sesion()
        path = app._ruta_sesion()
        contenido = path.read_text(encoding="utf8")
        self.assertNotIn("sk-abcdefghijklmnop123456789", contenido)
        self.assertNotIn("hunter2222", contenido)
        datos = json.loads(contenido)
        self.assertEqual(datos["pendiente"]["pedido"], "Arreglar pruebas")
        otra = App(self.ajustes(lecciones=False), MockLLM([]), self.ui(), app.ws, persistir=True)
        self.assertEqual(otra.pendiente["pedido"], "Arreglar pruebas")
        otra.cambiar_workspace(self.proyecto({"archivo.txt": "otro"}, nombre="otro").raiz)
        self.assertIsNone(otra.pendiente)

    def test_menciones_no_exponen_credenciales(self):
        app = self._app()
        (app.ws.raiz / "credentials.json").write_text('{"secret": "PRIVADO_123"}', encoding="utf8")
        (app.ws.raiz / "publico.py").write_text(
            'password = hunter2222\nprint("hola")\n', encoding="utf8")
        preparado = app.expandir_menciones("lee @credentials.json y @publico.py")
        self.assertNotIn("PRIVADO_123", preparado)
        self.assertIn("archivo sensible protegido", preparado)
        self.assertNotIn("hunter2222", preparado)
        self.assertIn("print", preparado)

    def test_sesion_corrupta_no_impide_abrir_proyecto(self):
        app = self._app(persistir=True)
        path = app._ruta_sesion()
        path.parent.mkdir(parents=True, exist_ok=True)
        for cuerpo in ('["en lugar de dict"]', '{"mensajes":null,"todo":[null,1],"historial":42}',
                       '{"mensajes":[null,3,{"role":"user","content":"hola"}],"todo":[null,{"a":2}],"historial":[]}',
                       '{'):  # JSON roto después de un cierre inesperado
            path.write_text(cuerpo, encoding="utf8")
            app._cargar_sesion()  # nunca debe lanzar una excepción

    def test_pendiente_json_malformado_no_crashea_continuar(self):
        app = self._app(persistir=True)
        path = app._ruta_sesion()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mensajes": [], "historial": [],
                                    "pendiente": {"pedido": "Crear API", "intentos": 0,
                                                   "cambios": 999, "resumen": None}}), encoding="utf8")
        app._cargar_sesion()
        self.assertEqual(app.pendiente["cambios"], [])
        # La visualización del pendiente no lanza excepciones.
        app.comando("/pendiente")

    def test_interrupcion_conserva_trabajo_pendiente(self):
        app = self._app(persistir=True)
        def interrumpir(task, cid_inicio=None):
            app.ws.escribir("main.py", "print('parcial')\n")
            raise Cancelado()
        app.principal.ejecutar = interrumpir
        with self.assertRaises(Cancelado):
            app.turno("Crear API")
        self.assertEqual(app.pendiente["pedido"], "Crear API")
        self.assertEqual(app.pendiente["motivo"], "interrumpido")
        self.assertIn("main.py", app.pendiente["cambios"])
        self.assertIn("interrumpido", app._ruta_sesion().read_text(encoding="utf8"))

    def test_reset_limpia_pendiente(self):
        app = self._app()
        app.pendiente = {"pedido": "Prueba", "intentos": 1}
        app.comando("/reset")
        self.assertIsNone(app.pendiente)

    def test_build_con_tarea_fallida_es_parcial(self):
        inf = InformeBuild("fallida", tareas_fallidas=["T1"])
        self.assertEqual(estado_final_build(Verificacion(True, [], None, "", []), inf), "parcial")
        inf.tareas_fallidas.clear()
        inf.tareas_bloqueadas.append("T2")
        self.assertEqual(estado_final_build(Verificacion(True, [], None, "", []), inf), "parcial")
        inf.tareas_bloqueadas.clear()
        self.assertEqual(estado_final_build(Verificacion(True, [], None, "", []), inf), "validada")
        self.assertEqual(estado_final_build(Verificacion(False, [], None, "", []), inf), "fallida")
