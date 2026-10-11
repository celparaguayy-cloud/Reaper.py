"""¿Un archivo del proyecto (editable por el agente) puede falsear el evaluador externo de ChatGPT?"""
import sys, json, tempfile, importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("reaper", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["reaper"] = m; spec.loader.exec_module(m)
base = Path(tempfile.mkdtemp())
suite = base / "evaluador"; suite.mkdir()
(suite / "test_real.py").write_text(
    "import unittest\nclass T(unittest.TestCase):\n    def test_falla(self):\n        self.assertEqual(1, 2)\n")
proy = base / "proy"; (proy / ".reaper").mkdir(parents=True)
(proy / ".reaper" / "acceptance.json").write_text(json.dumps({"suite_dir": str(suite), "min_tests": 3, "timeout": 30}))
ws = m.Workspace(proy)
r = m.ejecutar_aceptacion_independiente(ws)
print("SIN sombra  -> ok =", r.ok)
# El agente (o un descuido del modelo) deja un unittest.py en la raíz del proyecto:
(proy / "unittest.py").write_text(
    "import sys\nsys.stderr.write('\\nRan 50 tests in 0.1s\\n\\nOK\\n')\nraise SystemExit(0)\n")
r2 = m.ejecutar_aceptacion_independiente(ws)
print("CON sombra  -> ok =", r2.ok)
print(r2.resumen(400))
