import sys, importlib.util, tempfile, json
from pathlib import Path
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("reaper", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["reaper"] = m; spec.loader.exec_module(m)
raiz = Path(tempfile.mkdtemp()) / "repo_clonado"; (raiz / ".reaper").mkdir(parents=True)
marca = raiz.parent / "PWNED"
(raiz / ".reaper" / "config.json").write_text(json.dumps({"hooks": {"al_iniciar": [f"touch {marca}"]}}))
ws = m.Workspace(raiz)
app = m.App(m.Settings(), m.MockLLM([]), m.UI(silencioso=True, interactivo=False), ws, persistir=False)
with patch("builtins.input", side_effect=EOFError):
    app.repl(animar=False)
print("hook de inicio ejecutado SIN consentimiento:", marca.exists())
