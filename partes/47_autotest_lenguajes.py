"""Autotests de soporte multi-lenguaje: detección de suites y parsers de salida de tests."""


class TestParsersLenguajes(BaseTest):
    def test_minitest(self):
        c = contar_tests("Run options: --seed 1\n\n# Running:\n\n..F\n\n  1) Failure:\nTestX#test_a [x.rb:3]:\n"
                         "Expected 1\n\n3 runs, 5 assertions, 1 failures, 0 errors, 0 skips\n", 1)
        self.assertEqual((c.pasados, c.fallados, c.fuente), (2, 1, "minitest"))
        self.assertEqual(c.nombres_fallados, ["TestX#test_a"])

    def test_tap_plano_de_perl(self):
        c = contar_tests("ok 1 - uno\nnot ok 2 - dos\n#   Failed test 'dos'\nok 3 - tres # skip sin red\n1..3\n", 1)
        self.assertEqual((c.pasados, c.fallados, c.omitidos), (1, 1, 1))
        self.assertEqual(c.nombres_fallados, ["dos"])

    def test_tap_que_muere_antes_de_terminar(self):
        c = contar_tests("1..5\nok 1 - uno\nok 2 - dos\n", 255)
        self.assertEqual(c.pasados, 2)
        self.assertEqual(c.errores, 3)

    def test_prove_resumen(self):
        c = contar_tests("t/a.t .. ok\nAll tests successful.\nFiles=1, Tests=4,  0 wallclock secs\nResult: PASS\n", 0)
        self.assertEqual(c.pasados, 4)

    def test_phpunit(self):
        self.assertEqual(contar_tests("OK (12 tests, 30 assertions)\n", 0).pasados, 12)
        c = contar_tests("There were 2 failures:\n\n1) CarritoTest::testTotal\n\nFAILURES!\n"
                         "Tests: 12, Assertions: 30, Failures: 2.\n", 1)
        self.assertEqual((c.pasados, c.fallados, c.fuente), (10, 2, "phpunit"))
        self.assertIn("CarritoTest::testTotal", c.nombres_fallados)

    def test_junit_y_ctest(self):
        c = contar_tests("[         8 tests successful      ]\n[         1 tests failed          ]\n", 1)
        self.assertEqual((c.pasados, c.fallados), (8, 1))
        c = contar_tests("86% tests passed, 1 tests failed out of 7\n\n  4 - test_pila (Failed)\n", 8)
        self.assertEqual((c.pasados, c.fallados, c.nombres_fallados), (6, 1, ["test_pila"]))

    def test_cargo_quiet_no_se_confunde_con_pytest(self):
        salida = ("\nrunning 6 tests\n......\ntest result: ok. 6 passed; 0 failed; 0 ignored; 0 measured; "
                  "0 filtered out; finished in 0.00s\n\nrunning 0 tests\n\ntest result: ok. 0 passed; 0 failed; "
                  "0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n")
        c = contar_tests(salida, 0)
        self.assertEqual((c.pasados, c.fuente), (6, "cargo test"))

    def test_tap_con_resumen_propio(self):
        c = contar_tests("ok 1 - a\nnot ok 2 - b\n1..2\n# tests 2\n# pass 1\n# fail 1\n", 1)
        self.assertEqual((c.pasados, c.fallados, c.fuente), (1, 1, "TAP"))


class TestDeteccionLenguajes(BaseTest):
    def _detectar(self, archivos: dict):
        return detectar_comando_tests(self.proyecto(archivos))

    def test_ruby(self):
        if not shutil.which("ruby"):
            self.skipTest("sin ruby")
        comando, nombre = self._detectar({"lib/a.rb": "", "test/test_a.rb": ""})
        self.assertEqual(nombre, "minitest")
        self.assertIn("./test/test_a.rb", comando)

    def test_perl(self):
        if not shutil.which("prove"):
            self.skipTest("sin prove")
        self.assertEqual(self._detectar({"t/a.t": "", "lib/A.pm": ""}), ("prove -l t", "prove"))

    def test_php(self):
        if not shutil.which("php"):
            self.skipTest("sin php")
        self.assertEqual(self._detectar({"tests/run.php": "<?php"}), ("php tests/run.php", "php tests"))

    def test_bash(self):
        comando, nombre = self._detectar({"tests/test_x.sh": "true", "tests/test_y.sh": "true"})
        self.assertEqual(nombre, "bash tests")
        self.assertEqual(comando, "bash tests/test_x.sh && bash tests/test_y.sh")

    def test_nada_que_detectar(self):
        self.assertIsNone(self._detectar({"README.md": "hola"}))

    def test_plantilla_ruby_se_detecta_sin_config(self):
        if not shutil.which("ruby"):
            self.skipTest("sin ruby")
        destino = self.dir / "bib"
        crear_desde_plantilla("ruby-biblioteca", destino)
        (destino / ".reaper" / "config.json").unlink(missing_ok=True)
        r = ejecutar_tests(Workspace(destino), timeout=120)
        self.assertTrue(r and r.ok, r and r.resumen())
        self.assertEqual(conteo_de_resultado(r).pasados, 6)


class TestValidacionProyecto(BaseTest):
    def test_go_build_detecta_error_entre_archivos(self):
        if not shutil.which("go"):
            self.skipTest("sin go")
        ws = self.proyecto({"go.mod": "module demo\n\ngo 1.18\n",
                            "main.go": "package main\n\nfunc main() { saludar() }\n",
                            "util.go": "package main\n\nfunc saludar2() {}\n"})
        resultados = validar_archivos(ws, ["main.go"])
        self.assertTrue(fallos(resultados))
        self.assertIn("saludar", resumen_validacion(resultados))
        ws.escribir("util.go", "package main\n\nimport \"fmt\"\n\nfunc saludar() { fmt.Println(\"hola\") }\n")
        self.assertFalse(fallos(validar_archivos(ws, ["main.go", "util.go"])))
        self.assertFalse((ws.raiz / "demo").exists(), "go build no debe dejar binarios en el proyecto")

    def test_go_no_compila_tests_de_tareas_futuras(self):
        if not shutil.which("go"):
            self.skipTest("sin go")
        ws = self.proyecto({"go.mod": "module demo\n\ngo 1.18\n",
                            "calc.go": "package demo\n\nfunc Suma(a, b int) int { return a + b }\n",
                            "calc_test.go": "package demo\n\nimport \"testing\"\n\n"
                                            "func TestResta(t *testing.T) { _ = Resta(1, 2) }\n"})
        self.assertFalse(fallos(validar_archivos(ws, ["calc.go"])))

    def test_java_sin_build_tool(self):
        if not shutil.which("javac"):
            self.skipTest("sin javac")
        ws = self.proyecto({"src/A.java": "public class A { int f() { return new B().g(); } }\n",
                            "src/B.java": "public class B { int h() { return 1; } }\n"})
        resultados = validar_archivos(ws, ["src/A.java"])
        self.assertTrue(fallos(resultados))
        self.assertIn("javac (proyecto)", resumen_validacion(resultados))

    def test_perl_sintaxis(self):
        if not shutil.which("perl"):
            self.skipTest("sin perl")
        ws = self.proyecto({"a.pl": "use strict;\nmy $x = ;\n", "b.pl": "use strict;\nmy $x = 1;\nprint $x;\n"})
        self.assertTrue(fallos(validar_archivos(ws, ["a.pl"])))
        self.assertFalse(fallos(validar_archivos(ws, ["b.pl"])))


class TestGuiasLenguaje(BaseTest):
    def test_guias_por_extension(self):
        for archivo, encabezado in (("a.c", "C\n"), ("A.java", "JAVA"), ("i.php", "PHP"), ("l.rb", "RUBY"),
                                    ("x.pm", "PERL"), ("m.go", "GO"), ("lib.rs", "RUST")):
            with self.subTest(archivo=archivo):
                self.assertTrue(guias_para([archivo]).startswith(encabezado))

    def test_guia_de_programas_interactivos(self):
        guia = guias_para([], "hacé una calculadora interactiva con menú")
        self.assertIn("PROGRAMAS INTERACTIVOS", guia)
        self.assertIn("NO quites el input()", guia)

    def test_maximo_tres_guias(self):
        self.assertLessEqual(guias_para(["a.py", "b.js", "c.go", "d.rs", "e.c"]).count("\n\n") + 1, 3)


class TestRecetasLenguajes(BaseTest):
    def _correr(self, r: "Receta") -> "Resultado":
        carpeta = self.dir / f"receta_{abs(hash(r.titulo))}"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"receta.{_EXTENSION_RECETA[r.lenguaje]}"
        ruta.write_text(r.codigo, encoding="utf-8")
        return ejecutar(comando_receta(r, str(ruta)), cwd=carpeta, timeout=180, shell=True)

    def test_recetas_ejecutables_funcionan(self):
        compilados = {"go", "rust", "c", "java"}
        for r in RECETAS:
            if r.titulo not in RECETAS_EJECUTABLES:
                continue
            with self.subTest(receta=r.titulo):
                if not receta_disponible(r):
                    continue
                if r.lenguaje in compilados and not os.getenv("REAPER_AUTOTEST_COMPLETO"):
                    continue  # compilar tarda: solo con REAPER_AUTOTEST_COMPLETO=1
                resultado = self._correr(r)
                self.assertTrue(resultado.ok, f"{r.titulo}: {recortar(resultado.stdout + resultado.stderr, 1500)}")

    def test_recetas_por_lenguaje_del_pedido(self):
        self.assertIn("(go)", recetas_para_prompt("hacé un worker pool con goroutines en go para procesar en paralelo"))
        python = recetas_para_prompt("procesar tareas en paralelo con hilos y concurrencia")
        self.assertNotIn("(go)", python)
        self.assertIn("(rust)", recetas_para_prompt("en rust contar palabras con un hashmap y su frecuencia"))

    def test_lenguajes_mencionados(self):
        self.assertEqual(lenguajes_mencionados("hacelo en golang"), {"go"})
        self.assertEqual(lenguajes_mencionados("arreglá esto", ["src/main.rs"]), {"rust"})
        self.assertEqual(lenguajes_mencionados("una calculadora"), set())

    def test_cada_receta_tiene_lenguaje_conocido(self):
        for r in RECETAS:
            with self.subTest(receta=r.titulo):
                self.assertIn(r.lenguaje, _EXTENSION_RECETA)
                self.assertTrue(r.etiquetas and r.descripcion and r.codigo.strip())
