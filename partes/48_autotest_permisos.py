"""Autotests de permisos con memoria ("permitir siempre") y del modo plan."""


class TestPermisos(BaseTest):
    def tearDown(self) -> None:
        olvidar_permisos()
        super().tearDown()

    def test_clave_comando(self):
        self.assertEqual(clave_comando("git commit -m 'x'"), "git commit")
        self.assertEqual(clave_comando("npm run build -- --prod"), "npm run build")
        self.assertEqual(clave_comando("npm test"), "npm test")
        self.assertEqual(clave_comando("python3 calc.py 2 3"), "python3 calc.py")
        self.assertEqual(clave_comando("python3 -m pytest -q"), "python3 -m pytest")
        self.assertEqual(clave_comando("python3 -c 'print(1)'"), "python3 -c")
        self.assertEqual(clave_comando("FOO=1 BAR=2 make test"), "make test")
        self.assertEqual(clave_comando("/usr/bin/ls -la"), "ls")
        self.assertEqual(clave_comando(""), "")

    def test_destructivos_nunca_para_siempre(self):
        for comando in ("rm -r build", "git push origin main", "git reset --hard", "chmod 777 x", "curl http://x",
                        "python3 -c 'import os'", "mv a b", "find . -delete", "sed -i s/a/b/ x"):
            with self.subTest(comando=comando):
                self.assertFalse(puede_permitirse_siempre(comando))
        for comando in ("npm test", "python3 calc.py", "go test ./...", "cargo build", "make"):
            with self.subTest(comando=comando):
                self.assertTrue(puede_permitirse_siempre(comando))
        self.assertFalse(puede_permitirse_siempre("npm test && rm -rf x"), "los compuestos se confirman siempre")

    def _ctx(self, ws, respuestas):
        return Contexto(ws, self.ajustes(modo="auto-edicion"), self.ui(respuestas=respuestas), "test")

    def test_permitir_en_la_sesion(self):
        ws = self.proyecto({"a.py": "print('hola')\n"})
        ctx = self._ctx(ws, [1])  # "sí, y no preguntar más en esta sesión"
        self.assertIn("hola", self.herramienta(ctx, "execute_command", command="python3 a.py"))
        ctx2 = self._ctx(ws, [])  # sin respuestas: si preguntara, el defecto es "no"
        self.assertIn("hola", self.herramienta(ctx2, "execute_command", command="python3 a.py 1"))
        with self.assertRaises(ErrorHerramienta):
            self.herramienta(ctx2, "execute_command", command="python3 otro.py")

    def test_permitir_en_el_proyecto_se_guarda(self):
        ws = self.proyecto({"a.py": "print('hola')\n"})
        self.herramienta(self._ctx(ws, [2]), "execute_command", command="python3 a.py")
        self.assertIn("python3 a.py", permisos_proyecto(ws))
        olvidar_permisos()
        self.assertTrue(comando_ya_permitido(ws, "python3 a.py --verbose"))
        self.assertFalse(comando_ya_permitido(ws, "python3 a.py; rm x"))

    def test_no_y_destructivo_pregunta_cada_vez(self):
        ws = self.proyecto({"x.txt": "x"})
        with self.assertRaises(ErrorHerramienta):
            self.herramienta(self._ctx(ws, ["n"]), "execute_command", command="python3 -c 'print(1)'")
        ctx = self._ctx(ws, ["s"])  # destructivo: solo sí/no
        self.herramienta(ctx, "execute_command", command="mv x.txt y.txt")
        self.assertTrue((ws.raiz / "y.txt").exists())
        self.assertFalse(comando_ya_permitido(ws, "mv y.txt z.txt"))

    def test_bloqueados_siguen_bloqueados(self):
        ws = self.proyecto()
        permitir_en_sesion(ws, "sudo")
        with self.assertRaises(ErrorHerramienta) as cm:
            self.herramienta(self._ctx(ws, [1]), "execute_command", command="sudo ls")
        self.assertIn("bloqueado", str(cm.exception))

    def test_ediciones_aceptadas_en_la_sesion(self):
        ws = self.proyecto()
        ctx = Contexto(ws, self.ajustes(modo="confirmar"), self.ui(respuestas=[1]), "test")
        self.herramienta(ctx, "write_to_file", path="a.py", content="X = 1\n")
        ctx2 = Contexto(ws, self.ajustes(modo="confirmar"), self.ui(respuestas=[]), "test")
        self.herramienta(ctx2, "write_to_file", path="b.py", content="Y = 1\n")
        self.assertTrue((ws.raiz / "b.py").exists())


class TestModoPlan(BaseTest):
    PLAN = "## Objetivo\nAgregar resta.\n## Archivos\n- calc.py\n## Pasos\n1. resta(a, b)\n## Cómo se verifica\nrun_tests"

    def _app(self, guion, respuestas):
        ws = self.proyecto({"calc.py": "def suma(a, b):\n    return a + b\n"})
        return App(self.ajustes(), MockLLM(guion), self.ui(respuestas=respuestas), ws, persistir=False), ws

    def test_plan_no_toca_nada_y_se_puede_seguir_planificando(self):
        app, ws = self._app([herramienta_xml("read_file", path="calc.py"), terminar_xml(self.PLAN)], [2])
        app.cmd_modo("plan")
        app.turno("agregá resta a calc.py")
        self.assertTrue(app.modo_plan)
        self.assertNotIn("resta", ws.leer("calc.py"))
        self.assertTrue(list((ws.raiz / ".reaper" / "planes").glob("plan_*.md")))
        roles = [MockLLM.rol_de(c["mensajes"]) for c in app.llm.llamadas]
        self.assertEqual(set(roles), {"planificador"})

    def test_plan_aprobado_se_ejecuta_y_sale_del_modo(self):
        def guion(mensajes, kwargs):
            rol = MockLLM.rol_de(mensajes)
            if rol == "planificador":
                return terminar_xml(self.PLAN)
            if MockLLM.turnos_asistente(mensajes) == 0:
                self.assertIn("PLAN APROBADO", mensajes[1]["content"])
                return herramienta_xml("insert_after_symbol", path="calc.py", symbol="suma",
                                       content="def resta(a, b):\n    return a - b")
            return terminar_xml("Agregué resta según el plan.")

        app, ws = self._app(guion, [0])
        app.cmd_modo("plan")
        self.assertTrue(app.turno("agregá resta a calc.py"))
        self.assertIn("def resta", ws.leer("calc.py"))
        self.assertFalse(app.modo_plan)
        self.assertEqual(app.settings.modo, "auto-edicion")

    def test_planificador_es_de_solo_lectura(self):
        rol = ROLES["planificador"]
        self.assertTrue(rol.solo_lectura)
        self.assertFalse(set(rol.herramientas) & set(ESCRITURA + ("execute_command", "run_python")))
