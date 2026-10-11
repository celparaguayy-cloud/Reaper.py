import sys, importlib.util, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("reaper", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["reaper"] = m; spec.loader.exec_module(m)
raiz = Path(tempfile.mkdtemp()) / "p"; (raiz / "tests").mkdir(parents=True)
(raiz / "app.py").write_text("def suma(a, b):\n    return a - b   # bug\n")
(raiz / "tests" / "test_app.py").write_text(
    "import unittest\nfrom app import suma\nclass T(unittest.TestCase):\n"
    "    @unittest.skip('luego')\n    def test_suma(self):\n        self.assertEqual(suma(2, 2), 4)\n")
ws = m.Workspace(raiz)
r = m.ejecutar_tests(ws, completo=True)
print("comando:", r.comando, "| ok:", r.ok, "| omitido:", r.omitido)
print("conteo:", m.conteo_de_resultado(r).texto())
s = m.Settings(); s.forense = False; s.lecciones = False
orq = m.Orquestador(m.MockLLM([]), ws, s, m.UI(silencioso=True, interactivo=False))
v = orq.verificar(ws.checkpoints.iniciar("x"))
print("verif.ok:", v.ok, "| estado final:", m.estado_final_build(v, m.InformeBuild("fallida")))
