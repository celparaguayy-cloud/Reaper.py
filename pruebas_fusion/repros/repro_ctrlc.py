"""Ctrl+C mientras dos subagentes en paralelo esperan a un modelo lento: ¿cuánto tarda en salir el proceso?"""
import sys, importlib.util, tempfile, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("reaper", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["reaper"] = m; spec.loader.exec_module(m)

class LLMLento:
    llamadas = []
    def chat(self, mensajes, **kw):
        time.sleep(float(sys.argv[2]))            # una llamada a un modelo de razonamiento que tarda
        return m.Respuesta(m.terminar_xml("listo"), "stop", "lento")
    def chat_simple(self, *a, **k):
        return "ok"
    def __getattr__(self, n):
        return getattr(m.MockLLM([]), n)

raiz = Path(tempfile.mkdtemp()) / "p"; raiz.mkdir()
(raiz / "a.py").write_text("x = 1\n")
ws = m.Workspace(raiz)
s = m.Settings(); s.paralelo = 2; s.forense = False; s.lecciones = False
ui = m.UI(silencioso=True, interactivo=False)
rol = sys.argv[3]
print("listo para SIGINT", flush=True)
m.ejecutar_subagentes([(rol, "mirá a.py", ""), (rol, "mirá a.py otra vez", "")], LLMLento(), ws, s, ui)
