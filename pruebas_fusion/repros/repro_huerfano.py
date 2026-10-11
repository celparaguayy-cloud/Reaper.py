import sys, importlib.util, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("reaper", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["reaper"] = m; spec.loader.exec_module(m)
print("listo", flush=True)
m.ejecutar("sleep 47 && echo fin", cwd=Path(tempfile.mkdtemp()), timeout=120, shell=True)
