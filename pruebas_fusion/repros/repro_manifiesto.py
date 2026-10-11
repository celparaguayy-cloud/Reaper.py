import sys, importlib.util, tempfile, json
from pathlib import Path
spec = importlib.util.spec_from_file_location("reaper", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["reaper"] = m; spec.loader.exec_module(m)
raiz = Path(tempfile.mkdtemp()) / "p"; (raiz / ".reaper").mkdir(parents=True)
(raiz / ".reaper" / "acceptance.json").write_text(json.dumps({"suite_dir": "/tmp/x", "min_tests": 10}))
ws = m.Workspace(raiz)
s = m.Settings(); s.modo = "auto"; s.forense = False; s.lecciones = False
ui = m.UI(silencioso=True, interactivo=False)
for herr, extra in [("write_to_file", {"content": json.dumps({"suite_dir": "/tmp/x", "min_tests": 1})}),
                    ("delete_file", {})]:
    guion = [m.herramienta_xml("read_file", path=".reaper/acceptance.json"),
             m.herramienta_xml(herr, path=".reaper/acceptance.json", **extra), m.terminar_xml("listo")]
    m.Agente("principal", m.MockLLM(guion), ws, s, ui, memoria=None, mostrar_progreso=False).ejecutar("bajá el mínimo")
    f = raiz / ".reaper" / "acceptance.json"
    print(herr, "->", f.read_text() if f.exists() else "BORRADO")
