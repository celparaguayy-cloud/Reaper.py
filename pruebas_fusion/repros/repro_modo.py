import sys, importlib.util
spec = importlib.util.spec_from_file_location("reaper", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["reaper"] = m; spec.loader.exec_module(m)
base = m.Settings(modo="confirmar")
s = m.settings_con_local(base, {"settings": {"modo": "auto", "hooks": True, "max_reparaciones": 10}})
print("modo:", s.modo, "| hooks:", getattr(s, "hooks", None), "| max_reparaciones:", s.max_reparaciones)
