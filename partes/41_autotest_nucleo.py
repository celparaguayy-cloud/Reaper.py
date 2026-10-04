"""Autotest: workspace, copias aisladas, validadores, tests, autofix, símbolos, mapa, pistas y lecciones."""


# ======================================================================
# Workspace y checkpoints
# ======================================================================
class TestWorkspace(BaseTest):
    def test_rutas_confinadas(self):
        ws = self.proyecto({"a.py": "x = 1\n"})
        self.assertEqual(ws.rel(ws.ruta("a.py")), "a.py")
        self.assertEqual(ws.rel(ws.ruta("./a.py")), "a.py")
        for mala in ("../fuera.py", "/etc/passwd", ""):
            with self.assertRaises(ErrorRuta):
                ws.ruta(mala)
        with self.assertRaises(ErrorRuta):
            ws.ruta(".env", escribir=True)
        with self.assertRaises(ErrorRuta):
            ws.ruta(".git/config", escribir=True)

    def test_escribir_y_deshacer(self):
        ws = self.proyecto({"a.py": "x = 1\n"})
        cid = ws.checkpoints.iniciar("prueba")
        ws.escribir("a.py", "x = 2\n")
        ws.escribir("nuevo.py", "y = 1\n")
        self.assertIn("x = 2", ws.checkpoints.diff_desde(cid))
        self.assertEqual(sorted(ws.checkpoints.archivos_desde(cid)), ["a.py", "nuevo.py"])
        tocados = ws.checkpoints.deshacer(cid)
        self.assertEqual(sorted(tocados), ["a.py", "nuevo.py"])
        self.assertEqual(ws.leer("a.py"), "x = 1\n")
        self.assertFalse(ws.existe("nuevo.py"))

    def test_grupos_de_checkpoints(self):
        ws = self.proyecto({"a.py": "1\n"})
        grupo = ws.checkpoints.iniciar("build")
        ws.escribir("a.py", "2\n")
        ws.checkpoints.iniciar("tarea 2", grupo=grupo)
        ws.escribir("a.py", "3\n")
        self.assertEqual(ws.checkpoints.inicio_grupo(), grupo)
        ws.checkpoints.deshacer()
        self.assertEqual(ws.leer("a.py"), "1\n")

    def test_borrar_y_mover_con_deshacer(self):
        ws = self.proyecto({"a.py": "a\n", "b.py": "b\n"})
        cid = ws.checkpoints.iniciar("x")
        ws.borrar("a.py")
        ws.mover("b.py", "sub/c.py")
        self.assertFalse(ws.existe("a.py"))
        self.assertEqual(ws.leer("sub/c.py"), "b\n")
        ws.checkpoints.deshacer(cid)
        self.assertEqual((ws.leer("a.py"), ws.leer("b.py")), ("a\n", "b\n"))
        self.assertFalse(ws.existe("sub/c.py"))

    def test_descartar_vacio(self):
        ws = self.proyecto()
        cid = ws.checkpoints.iniciar("nada")
        ws.checkpoints.descartar_si_vacio(cid)
        self.assertEqual(ws.checkpoints.ids(), [])

    def test_gitignore_y_listado(self):
        ws = self.proyecto({"a.py": "1", "build/x.py": "2", "logs/l.txt": "3", ".gitignore": "logs/\n*.tmp\n",
                            "b.tmp": "4", "node_modules/m.js": "5"})
        archivos = ws.archivos_codigo()
        self.assertIn("a.py", archivos)
        for no in ("build/x.py", "logs/l.txt", "b.tmp", "node_modules/m.js"):
            self.assertNotIn(no, archivos)
        self.assertIn("a.py", ws.arbol())

    def test_memoria_y_notas(self):
        ws = self.proyecto({"REAPER.md": "# Proyecto\nusa unittest", ".reaper/notas.md": "- nota uno"})
        self.assertIn("usa unittest", ws.memoria())
        self.assertIn("nota uno", ws.notas())
        self.assertEqual(ws.config_local(), {})

    def test_secretos_y_binarios(self):
        self.assertNotIn("sk-abcdefghijklmnopqrstu", redactar_secretos("clave sk-abcdefghijklmnopqrstu"))
        self.assertIn("[REDACTADO]", redactar_secretos("password = hunter2222"))
        ws = self.proyecto()
        (ws.raiz / "bin.dat").write_bytes(b"\x00\x01\x02")
        self.assertTrue(es_binario(ws.raiz / "bin.dat"))


# ======================================================================
# Copias aisladas
# ======================================================================
class TestSandbox(BaseTest):
    def test_copia_cambios_y_aplicar(self):
        ws = self.proyecto({"a.py": "a = 1\n", "b.py": "b = 1\n", "c.py": "c\n", ".git/HEAD": "ref",
                            "node_modules/lib/x.js": "module.exports = 1;\n", ".reaper/config.json": "{}"})
        with Copia(ws, "t") as copia:
            self.assertFalse((copia.raiz / ".git").exists())
            self.assertTrue((copia.raiz / "node_modules").is_symlink())
            self.assertTrue((copia.raiz / ".reaper" / "config.json").exists())
            copia.ws.escribir("a.py", "a = 2\n")
            copia.ws.escribir("nuevo.py", "n = 1\n")
            copia.ws.borrar("c.py")
            cambios = {c.rel: c.tipo for c in copia.cambios()}
            self.assertEqual(cambios, {"a.py": "modificado", "nuevo.py": "nuevo", "c.py": "borrado"})
            self.assertIn("+a = 2", copia.diff())
            self.assertEqual(ws.leer("a.py"), "a = 1\n")  # el original no se tocó
            cid = ws.checkpoints.iniciar("aplicar")
            aplicados = copia.aplicar_a(ws)
            carpeta = copia.carpeta
        self.assertEqual(sorted(aplicados), ["a.py", "c.py", "nuevo.py"])
        self.assertEqual(ws.leer("a.py"), "a = 2\n")
        self.assertFalse(carpeta.exists())
        self.assertTrue((ws.raiz / "node_modules" / "lib" / "x.js").exists(), "la limpieza no debe seguir symlinks")
        ws.checkpoints.deshacer(cid)
        self.assertEqual(ws.leer("a.py"), "a = 1\n")
        self.assertTrue(ws.existe("c.py"))

    def test_forzar_contenidos(self):
        ws = self.proyecto({"tests/test_a.py": "original\n"})
        with Copia(ws) as copia:
            copia.ws.escribir("tests/test_a.py", "debilitado\n")
            copia.forzar_contenidos({"tests/test_a.py": "original\n", "x.py": None})
            self.assertEqual(copia.cambios(), [])

    def test_lineas_cambiadas_y_tamano(self):
        self.assertEqual(CambioArchivo("a", "modificado", "a\nb\nc\n", "a\nB\nc\nd\n").lineas_cambiadas(), 2)
        ws = self.proyecto({"a.txt": "x" * 1000})
        self.assertGreaterEqual(tamano_proyecto(ws.raiz), 1000)
        self.assertEqual(copiar_contenidos(ws, ["a.txt", "no.txt"])["no.txt"], None)


# ======================================================================
# Validadores
# ======================================================================
class TestValidadores(BaseTest):
    def test_python_sintaxis_con_pista(self):
        ws = self.proyecto({"a.py": "def f(:\n    pass\n", "b.py": "x = (1,\n"})
        r = validar_archivo(ws, "a.py")
        self.assertFalse(r[0].ok)
        self.assertIn("línea 1", r[0].stderr)
        self.assertIn("Pista", validar_archivo(ws, "b.py")[0].stderr)

    def test_python_imports(self):
        ws = self.proyecto({"utils.py": "def suma(a, b):\n    return a + b\n",
                            "main.py": "import modulo_que_no_existe_xyz\nfrom utils import sumar\n"})
        resultados = validar_archivo(ws, "main.py")
        malos = {r.comando.split()[0]: r for r in fallos(resultados)}
        self.assertIn("imports", malos)
        self.assertIn("modulo_que_no_existe_xyz", malos["imports"].stderr)
        self.assertIn("imports-locales", malos)
        self.assertIn("no define 'sumar'", malos["imports-locales"].stderr)
        self.assertIn("suma", malos["imports-locales"].stderr)

    def test_import_de_paquete_y_try(self):
        ws = self.proyecto({"pkg/__init__.py": "VALOR = 1\n", "pkg/sub.py": "x = 1\n",
                            "m.py": "from pkg import VALOR, sub\ntry:\n    import yaml_inexistente\nexcept ImportError:\n    pass\n"})
        self.assertEqual(fallos(validar_archivo(ws, "m.py")), [])

    def test_detector_propio_de_indefinidos(self):
        self.assertEqual(nombres_indefinidos_python("def f():\n    return y\n"), [("y", 2)])
        self.assertEqual(nombres_indefinidos_python("import os\nprint(os.sep, __file__, _)\n"), [])

    def test_advertencias(self):
        avisos = advertencias_python("def f():\n    pass\n\ndef f():\n    return 1\n\ntry:\n    x = 1\nexcept:\n    pass\n")
        texto = " ".join(avisos)
        self.assertIn("dos veces", texto)
        self.assertIn("except: pass", texto)
        self.assertEqual(funciones_vacias_python("def a():\n    '''doc'''\n    ...\ndef b():\n    return 1\n"), [("a", 1)])

    def test_json_css_html(self):
        ws = self.proyecto({"a.json": '{"a": 1,}', "b.css": "a { color: red; \n", "c.css": "a { b: c; }",
                            "i.html": '<link href="estilo.css"><script src="app.js"></script><img src="https://x/y.png">',
                            "app.js": "console.log(1);\n"})
        self.assertIn("línea 1", validar_archivo(ws, "a.json")[0].stderr)
        self.assertFalse(validar_archivo(ws, "b.css")[0].ok)
        self.assertTrue(validar_archivo(ws, "c.css")[0].ok)
        html = validar_archivo(ws, "i.html")
        faltantes = [r for r in html if r.comando.startswith("recursos-html")]
        self.assertEqual(len(faltantes), 1)
        self.assertIn("estilo.css", faltantes[0].stderr)
        self.assertNotIn("app.js", faltantes[0].stderr)

    def test_balance_llaves(self):
        self.assertEqual(balance_llaves("function f() { return '}'; } // }"), "")
        self.assertIn("nunca se cierra", balance_llaves("if (x) { y();"))
        self.assertIn("sin abrir", balance_llaves("x = 1; }"))
        self.assertIn("cierra", balance_llaves("f(a, [b);"))
        self.assertEqual(balance_llaves("s = '(' # )\n", "py"), "")

    def test_js_con_node(self):
        if not shutil.which("node"):
            self.skipTest("node no está instalado")
        ws = self.proyecto({"a.js": "function f( {\n", "m.mjs": "export const x = 1;\n",
                            "b.mjs": "import { x, y } from './m.mjs';\nimport z from './falta.js';\n"})
        self.assertFalse(validar_archivo(ws, "a.js")[0].ok)
        self.assertTrue(validar_archivo(ws, "m.mjs")[0].ok)
        problemas = " ".join(r.stderr for r in fallos(validar_archivo(ws, "b.mjs")))
        self.assertIn("no exporta 'y'", problemas)
        self.assertIn("falta.js", problemas)

    def test_shell(self):
        ws = self.proyecto({"ok.sh": "#!/bin/bash\necho hola\n", "mal.sh": "if then\n"})
        self.assertTrue(validar_archivo(ws, "ok.sh")[0].ok)
        self.assertFalse(validar_archivo(ws, "mal.sh")[0].ok)

    def test_detectar_tests(self):
        ws = self.proyecto({"tests/test_a.py": "import unittest\n"})
        comando, nombre = detectar_comando_tests(ws)
        self.assertIn(nombre, ("pytest", "unittest"))
        ws2 = self.proyecto({".reaper/config.json": '{"comando_tests": "make check"}'}, "otro")
        self.assertEqual(detectar_comando_tests(ws2), ("make check", "config .reaper"))
        self.assertIsNone(detectar_comando_tests(self.proyecto({"a.txt": "x"}, "vacio")))

    def test_ejecutar_tests_reales(self):
        ws = self.proyecto({
            "calc.py": "def suma(a, b):\n    return a + b\n",
            "tests/test_calc.py": "import unittest\nfrom calc import suma\n\nclass T(unittest.TestCase):\n"
                                  "    def test_ok(self):\n        self.assertEqual(suma(1, 2), 3)\n"
                                  "    def test_mal(self):\n        self.assertEqual(suma(1, 1), 3)\n",
        })
        r = ejecutar_tests(ws, completo=True)
        conteo = conteo_de_resultado(r)
        self.assertFalse(r.ok)
        self.assertEqual((conteo.pasados, conteo.fallados), (1, 1))

    def test_ejecutar_timeout_y_crash(self):
        r = ejecutar([sys.executable, "-c", "import time; time.sleep(5)"], cwd=self.dir, timeout=1)
        self.assertTrue(r.timeout)
        self.assertTrue(es_crash_real(r))
        self.assertFalse(es_crash_real(Resultado(False, "x", 2, stderr="uso: x <archivo>")))
        self.assertTrue(es_crash_real(Resultado(False, "x", 1, stderr="Traceback (most recent call last):")))
        self.assertEqual(ejecutar(["no_existe_este_programa_xyz"], cwd=self.dir).codigo, 127)

    def test_entorno_sin_claves(self):
        os.environ["MI_API_KEY_PRUEBA"] = "secreto"
        try:
            self.assertNotIn("MI_API_KEY_PRUEBA", entorno_seguro())
        finally:
            del os.environ["MI_API_KEY_PRUEBA"]


# ======================================================================
# Lectura de salidas de tests
# ======================================================================
class TestParserTests(BaseTest):
    PYTEST = """..F.                                                                     [100%]
=================================== FAILURES ===================================
___________________________________ test_x ____________________________________

    def test_x():
>       assert 1 == 2
E       assert 1 == 2

test_a.py:3: AssertionError
=========================== short test summary info ============================
FAILED test_a.py::test_x - assert 1 == 2
1 failed, 3 passed in 0.05s
"""
    UNITTEST = """..F
======================================================================
FAIL: test_b (test_m.T.test_b)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/x/test_m.py", line 6, in test_b
    self.assertEqual(1, 2)
AssertionError: 1 != 2

----------------------------------------------------------------------
Ran 3 tests in 0.001s

FAILED (failures=1)
"""
    TAP = """TAP version 13
# Subtest: suma
ok 1 - suma
# Subtest: resta
not ok 2 - resta
  ---
  error: 'Expected values to be strictly equal'
  ...
1..2
# tests 2
# pass 1
# fail 1
# cancelled 0
# skipped 0
# todo 0
"""

    def test_pytest(self):
        c = contar_tests(self.PYTEST, 1)
        self.assertEqual((c.pasados, c.fallados, c.fuente), (3, 1, "pytest"))
        self.assertEqual(c.nombres_fallados, ["test_a.py::test_x"])
        self.assertIn("assert 1 == 2", fallos_relevantes(self.PYTEST))

    def test_unittest(self):
        c = contar_tests(self.UNITTEST, 1)
        self.assertEqual((c.pasados, c.fallados, c.errores), (2, 1, 0))
        self.assertEqual(c.nombres_fallados, ["test_m.T.test_b"])
        self.assertIn("AssertionError: 1 != 2", fallos_relevantes(self.UNITTEST))
        ok = contar_tests("....\n------\nRan 4 tests in 0.1s\n\nOK (skipped=1)\n", 0)
        self.assertEqual((ok.pasados, ok.omitidos), (3, 1))

    def test_tap(self):
        c = contar_tests(self.TAP, 1)
        self.assertEqual((c.pasados, c.fallados, c.nombres_fallados), (1, 1, ["resta"]))

    def test_otros_runners(self):
        jest = contar_tests("Tests:       1 failed, 2 skipped, 3 passed, 6 total\n", 1)
        self.assertEqual((jest.pasados, jest.fallados, jest.omitidos), (3, 1, 2))
        mocha = contar_tests("  3 passing (20ms)\n  1 failing\n", 1)
        self.assertEqual((mocha.pasados, mocha.fallados), (3, 1))
        go = contar_tests("=== RUN TestA\n--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.00s)\nFAIL\n", 1)
        self.assertEqual((go.pasados, go.fallados, go.nombres_fallados), (1, 1, ["TestB"]))
        cargo = contar_tests("test result: FAILED. 2 passed; 1 failed; 0 ignored; 0 measured\n", 101)
        self.assertEqual((cargo.pasados, cargo.fallados), (2, 1))

    def test_respaldo_por_codigo(self):
        self.assertEqual(contar_tests("salida rara", 0).pasados, 1)
        self.assertEqual(contar_tests("salida rara", 2).fallados, 1)
        self.assertFalse(contar_tests("salida rara", 2).reconocido)
        crash = contar_tests("Ran 2 tests in 0.1s\n\nOK\n", 1)
        self.assertEqual(crash.errores, 1)

    def test_conteo_de_resultado(self):
        self.assertEqual(conteo_de_resultado(None).fuente, "sin suite")
        self.assertEqual(conteo_de_resultado(Resultado(False, "x", 124, timeout=True)).errores, 1)
        self.assertTrue(ConteoTests(3, 0).ok)
        self.assertEqual(ConteoTests(3, 1).proporcion(), 0.75)


# ======================================================================
# Autofix
# ======================================================================
class TestAutofix(BaseTest):
    def test_espacios_y_salto_final(self):
        r = autoarreglar_texto("a.py", "x = 1   \ny = 2")
        self.assertEqual(r.contenido, "x = 1\ny = 2\n")
        self.assertEqual(len(r.cambios), 2)

    def test_markdown_conserva_doble_espacio(self):
        r = autoarreglar_texto("a.md", "línea con salto  \notra\n")
        self.assertIsNone(r.contenido)

    def test_tabs(self):
        r = autoarreglar_texto("t.py", "def f():\n\tif True:\n        return 1\n")
        self.assertIn("4 espacios", " ".join(r.cambios))
        compile(r.contenido, "t.py", "exec")

    def test_tipograficos(self):
        r = autoarreglar_texto("q.py", "print(“hola”)\n")
        self.assertEqual(r.contenido, 'print("hola")\n')

    def test_imports_stdlib(self):
        codigo = ('"""Doc."""\nimport sys\n\n\n@dataclass\nclass A:\n    ruta: Optional[Path] = None\n\n\n'
                  'def f():\n    return os.getcwd(), json.dumps({}), datetime.now()\n')
        r = autoarreglar_texto("m.py", codigo)
        for esperado in ("import os", "import json", "from pathlib import Path", "from typing import Optional",
                         "from dataclasses import dataclass", "from datetime import datetime"):
            self.assertIn(esperado, r.contenido)
        self.assertTrue(r.contenido.startswith('"""Doc."""\nimport sys\n'))
        self.assertEqual(nombres_indefinidos_python(r.contenido), [])

    def test_no_agrega_ambiguos(self):
        self.assertEqual(imports_stdlib_faltantes("sleep(1)\n"), [])
        self.assertEqual(imports_stdlib_faltantes("print(datetime.date.today())\n"), ["import datetime"])

    def test_json_comas_finales(self):
        r = autoarreglar_texto("p.json", '{"a": [1, 2,], "b": "x,}",}\n')
        self.assertEqual(json.loads(r.contenido), {"a": [1, 2], "b": "x,}"})
        self.assertIsNone(autoarreglar_texto("tsconfig.json", '{"a": 1,}\n').contenido)

    def test_en_disco_y_chmod(self):
        ws = self.proyecto({"s.sh": "#!/usr/bin/env bash\necho hola   \n"})
        reporte = autoarreglar(ws, "s.sh", usar_ruff=False)
        self.assertTrue(reporte.cambio)
        self.assertTrue(os.access(ws.raiz / "s.sh", os.X_OK))
        self.assertEqual(ws.leer("s.sh"), "#!/usr/bin/env bash\necho hola\n")


# ======================================================================
# Símbolos
# ======================================================================
class TestSimbolos(BaseTest):
    CODIGO = '''import os


class Carrito:
    """Un carrito."""

    def __init__(self):
        self.items = []

    @property
    def vacio(self):
        return not self.items

    def total(self):
        return sum(self.items)


def libre(x):
    def interna():
        return x
    return interna()
'''

    def test_python(self):
        simbolos = simbolos_python(self.CODIGO, "c.py")
        nombres = {s.nombre_completo: s for s in simbolos}
        self.assertIn("Carrito.total", nombres)
        self.assertEqual(nombres["Carrito.vacio"].inicio, 10)  # incluye el decorador
        self.assertIn("libre.interna", nombres)
        self.assertEqual(nombres["Carrito"].tipo, "clase")

    def test_elegir(self):
        simbolos = simbolos_python(self.CODIGO, "c.py")
        self.assertEqual(len(elegir_simbolo(simbolos, "total")[0]), 1)
        self.assertEqual(len(elegir_simbolo(simbolos, "def Carrito.total()")[0]), 1)
        encontrados, sugerencias = elegir_simbolo(simbolos, "totl")
        self.assertEqual(encontrados, [])
        self.assertIn("total", " ".join(sugerencias))

    def test_reemplazar_reindenta(self):
        simbolo = [s for s in simbolos_python(self.CODIGO, "c.py") if s.nombre == "total"][0]
        nuevo = reemplazar_simbolo(self.CODIGO, simbolo, "def total(self):\n    return sum(self.items) * 2")
        self.assertIn("    def total(self):\n        return sum(self.items) * 2\n", nuevo)
        compile(nuevo, "c.py", "exec")

    def test_insertar_tras(self):
        simbolo = [s for s in simbolos_python(self.CODIGO, "c.py") if s.nombre == "total"][0]
        nuevo = insertar_tras_simbolo(self.CODIGO, simbolo, "def vaciar(self):\n    self.items.clear()")
        self.assertIn("\n    def vaciar(self):\n        self.items.clear()\n", nuevo)
        compile(nuevo, "c.py", "exec")

    def test_python_con_error_usa_regex(self):
        simbolos = simbolos_python("def a():\n    x = (\n\ndef b():\n    pass\n", "e.py")
        self.assertEqual([s.nombre for s in simbolos], ["a", "b"])

    def test_js_y_otros(self):
        js = "export function f(a) {\n  return `}${a}`;\n}\nclass K {\n  m() {\n    return 1;\n  }\n}\n"
        nombres = [s.nombre_completo for s in extraer_simbolos(Path("x.js"), js)]
        self.assertEqual(nombres, ["f", "K", "K.m"])
        go = "package main\nfunc (s *Srv) Run() {\n}\nfunc main() {\n}\n"
        self.assertEqual([s.nombre_completo for s in extraer_simbolos(Path("x.go"), go)], ["Srv.Run", "main"])
        sh = "hola() {\n  echo }\n}\n"
        self.assertEqual(extraer_simbolos(Path("x.sh"), sh)[0].fin, 3)

    def test_indice_y_referencias(self):
        ws = self.proyecto({"a.py": "def calcular(x):\n    return x\n", "b.py": "from a import calcular\nprint(calcular(2))\n"})
        indice = indice_de(ws)
        self.assertEqual(indice.buscar("calcular")[0][0].archivo, "a.py")
        refs = indice.referencias("calcular")
        self.assertEqual(len(refs), 2)
        self.assertTrue(all(r.startswith("b.py") for r in refs))


# ======================================================================
# Mapa de relevancia
# ======================================================================
class TestMapa(BaseTest):
    def test_ranking(self):
        ws = self.proyecto({
            "app/carrito.py": "from app.productos import Producto\n\nclass Carrito:\n    def total(self):\n        return 0\n",
            "app/productos.py": "class Producto:\n    precio = 0\n",
            "app/usuarios.py": "def login(user, password):\n    return True\n",
        })
        ranking = mapa_de(ws).rankear("descuento al total del carrito", 5)
        self.assertEqual(ranking[0][0], "app/carrito.py")
        self.assertIn("app/productos.py", [r for r, _, _ in ranking])
        texto = mapa_relevante(ws, "login de usuarios con contraseña")
        self.assertIn("app/usuarios.py", texto.splitlines()[1])

    def test_tokens_y_traducciones(self):
        tokens = tokens_pedido("Agregá validación de contraseña al login de usuarios en auth.py")
        self.assertIn("password", tokens)
        self.assertIn("auth.py", tokens)
        self.assertNotIn("agrega", tokens)
        self.assertEqual(partir_identificador("guardarUsuario_v2"), ["guardar", "usuario", "v2"])
        self.assertEqual(sin_tildes("canción"), "cancion")

    def test_proyecto_vacio(self):
        self.assertEqual(mapa_relevante(self.proyecto(), "algo"), "")


# ======================================================================
# Pistas y guías
# ======================================================================
class TestConocimiento(BaseTest):
    def test_pistas(self):
        casos = {
            "ModuleNotFoundError: No module named 'requests'": "urllib",
            "NameError: name 'x' is not defined": "import",
            "TypeError: Cannot read properties of undefined (reading 'value')": "DOM",
            "bash: sudo: command not found": "sudo",
            "SyntaxError: Cannot use import statement outside a module": ".mjs",
            "EOFError: EOF when reading a line": "input()",
            "No encontré el texto de SEARCH en el archivo": "replace_symbol",
        }
        for error, palabra in casos.items():
            pistas = " ".join(pistas_para(error))
            self.assertIn(palabra, pistas, error)
        self.assertEqual(pistas_para("todo bien"), [])
        self.assertIn("PISTAS DE REAPER", anexar_pistas("KeyError: 'x'"))

    def test_guias(self):
        self.assertIn("unittest", guias_para(["a.py"]))
        self.assertIn("node:test", guias_para([], "una app de node"))
        self.assertEqual(guias_para(["x.txt"]), "")

    def test_todas_las_pistas_compilan(self):
        for pista in PISTAS:
            self.assertIsInstance(pista.regex, re.Pattern)


# ======================================================================
# Lecciones
# ======================================================================
class TestLecciones(BaseTest):
    def memoria(self) -> MemoriaLecciones:
        return MemoriaLecciones(self.proyecto(), ruta_global=self.dir / "global" / "lecciones.md")

    def test_agregar_reforzar_y_descartar(self):
        m = self.memoria()
        self.assertEqual(m.proyecto.agregar("Los tests se corren con `python3 -m unittest discover -s tests`"), "nueva")
        self.assertEqual(m.proyecto.agregar("los tests se corren con python3 -m unittest discover -s tests"), "reforzada")
        self.assertIsNone(m.proyecto.agregar("Siempre verificar bien el código"))
        self.assertIsNone(m.proyecto.agregar("NINGUNA"))
        lecciones = m.proyecto.cargar()
        self.assertEqual(len(lecciones), 1)
        self.assertEqual(lecciones[0].veces, 2)

    def test_para_prompt_prioriza_relevantes(self):
        m = self.memoria()
        m.registrar(["content.js expone un objeto global window.Content, no un módulo ES",
                     "La base sqlite está en data/app.db y se crea con init_db()"],
                    ["En archivos largos cerrá siempre </content> y escribí por partes"])
        texto = m.para_prompt("arreglar el import de content.js", 2)
        self.assertIn("content.js", texto.splitlines()[1])
        self.assertIn("Errores que ya cometiste", m.para_prompt("x", 8))

    def test_tropiezos_generan_leccion_general(self):
        m = self.memoria()
        for _ in range(3):
            m.tropiezo("llamada_incompleta")
        self.assertTrue(any("append_to_file" in l.texto for l in m.general.cargar()))
        self.assertIsNone(m.tropiezo("inexistente"))

    def test_borrar(self):
        m = self.memoria()
        m.registrar(["El servidor usa el puerto 8080 definido en config.py"])
        self.assertIsNotNone(m.proyecto.borrar(0))
        self.assertEqual(m.proyecto.cargar(), [])
        self.assertIsNone(m.proyecto.borrar(5))

    def test_parsear_y_heuristicas(self):
        proyecto, general = parsear_lecciones("PROYECTO: Los imports usan el paquete `app.` desde la raíz\nGENERAL: NINGUNA")
        self.assertEqual(len(proyecto), 1)
        self.assertEqual(general, [])
        p, g = lecciones_heuristicas("ModuleNotFoundError: No module named 'requests'")
        self.assertIn("requests", p[0])

    def test_extraer_con_mock(self):
        llm = MockLLM(["PROYECTO: La función total() de carrito.py devuelve centavos (int)\nGENERAL: Verificar con read_symbol antes de importar funciones"])
        p, g = extraer_lecciones(llm, "mock", "AssertionError", "diff", "informe")
        self.assertIn("centavos", p[0])
        self.assertIn("read_symbol", g[0])
