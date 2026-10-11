import sys, importlib.util, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("reaper", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["reaper"] = m; spec.loader.exec_module(m)
raiz = Path(tempfile.mkdtemp()) / "p"; (raiz / "web").mkdir(parents=True)
(raiz / "web" / "style.css").write_text("body { color: black; }\nh1 { margin: 0; }\n")
ws = m.Workspace(raiz)
s = m.Settings(); s.modo = "auto"; s.forense = False; s.escalar = False; s.lecciones = False
ui = m.UI(silencioso=True, interactivo=False)
malformada = ("Corrijo el color.\n<replace_lines><path>web/style.css</path><desde>1</desde><hasta>1</hasta>"
              "<content>body { color: red; }\n</replace_line>")
guion = [m.herramienta_xml("read_file", path="web/style.css"), malformada, m.terminar_xml("listo")]
m.Agente("principal", m.MockLLM(guion), ws, s, ui, memoria=None, mostrar_progreso=False).ejecutar("arreglá el color")
print(repr((raiz / "web" / "style.css").read_text()))
print("----"); print(ui.texto_registrado()[-1500:])
