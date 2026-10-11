#!/usr/bin/env python3
"""
Smoke real de la CLI de REAPER (sin API de modelos): flags de Termux, cada plantilla generada offline en una
carpeta CON ESPACIOS y sus propios tests ejecutados de verdad, EOF en stdin y modo no interactivo.
Usa un HOME temporal para no tocar la configuración del usuario.

Uso:  python3 pruebas_fusion/smoke_cli.py [ruta/a/reaper.py] [log_de_salida]
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REAPER = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "reaper_v8.py").resolve()
LOG = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
HOME = Path(tempfile.mkdtemp(prefix="reaper smoke home "))
ENV = {k: v for k, v in os.environ.items() if not re.search(r"KEY|TOKEN|SECRET", k)}
ENV.update(HOME=str(HOME), REAPER_SIN_ANIMACION="1", NO_COLOR="1")
filas, fallas = [], []


def correr(nombre, args, esperado=0, entrada=None, cwd=None, timeout=180, contiene=None):
    inicio = time.monotonic()
    try:
        r = subprocess.run([sys.executable, str(REAPER), *args], capture_output=True, text=True, env=ENV,
                           input=entrada, cwd=cwd, timeout=timeout)
        rc, salida = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        rc, salida = "TIMEOUT", ""
    ok = rc == esperado and (contiene is None or contiene in salida)
    filas.append(f"{'OK ' if ok else 'MAL'} {nombre:<38} exit={rc} (esperado {esperado}) {time.monotonic() - inicio:5.1f}s")
    if not ok:
        fallas.append(nombre)
        filas.append("    " + salida[-600:].replace("\n", "\n    "))
    return salida


def test_plantilla(nombre, carpeta):
    """Corre los tests de la plantilla con el MISMO detector que usa REAPER para verificar proyectos."""
    import importlib.util
    if "reaper_mod" not in globals():
        spec = importlib.util.spec_from_file_location("reaper_mod", REAPER)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["reaper_mod"] = mod
        spec.loader.exec_module(mod)
        globals()["reaper_mod"] = mod
    m = globals()["reaper_mod"]
    detectado = m.detectar_comando_tests(m.Workspace(carpeta), completo=True)
    if not detectado:
        return None
    comando, _nombre = detectado
    return subprocess.run(["bash", "-c", comando], cwd=carpeta, capture_output=True, text=True, timeout=240,
                          env={k: v for k, v in ENV.items() if k != "PYTHONPATH"}), comando


def main():
    filas.extend([f"REAPER: {REAPER}", f"Python: {sys.version.split()[0]}", f"HOME temporal: {HOME}", ""])
    correr("--version", ["--version"], contiene="8.10")
    correr("--help", ["--help"], contiene="--aceptacion")
    salida = correr("--plantillas", ["--plantillas"])
    plantillas = sorted(set(re.findall(r"^([a-z0-9][a-z0-9-]+)\s{2,}[a-z+#]+\s{2,}", salida, re.M)))
    filas.append(f"    plantillas listadas: {len(plantillas)}")
    correr("--autotest-filtro inexistente → 2", ["--autotest-filtro", "zzz_no_existe_zzz"], esperado=2)
    correr("--autotest-filtro testcli", ["--autotest-filtro", "testcli"])
    correr("--aceptacion sin manifiesto → 2", ["--aceptacion", "--proyecto", str(HOME)], esperado=2)
    correr("--doctor sin clave → 1 (crítico)", ["--doctor"], esperado=1, contiene="falta OPENROUTER_API_KEY")
    correr("-p sin clave → error claro, sin colgarse", ["-p", "hola"], esperado=1, entrada="")
    base = HOME / "proyectos con espacios"
    base.mkdir()
    for nombre in plantillas:
        destino = base / f"demo {nombre}"
        correr(f"--nuevo {nombre}", ["--nuevo", nombre, str(destino)])
        if not destino.is_dir():
            continue
        par = test_plantilla(nombre, destino)
        if par is None:
            filas.append(f"    {nombre}: REAPER no detecta suite de tests ejecutable aquí (no verificado)")
            continue
        r, comando = par
        ok = r.returncode == 0
        filas.append(f"{'OK ' if ok else 'MAL'}   tests de la plantilla {nombre:<20} exit={r.returncode}  [{comando[:60]}]")
        if not ok:
            fallas.append(f"tests {nombre}")
            filas.append("    " + (r.stdout + r.stderr)[-500:].replace("\n", "\n    "))
    web = base / "demo web-fullstack"
    if web.is_dir():
        correr("--auditar-web web-fullstack", ["--auditar-web", str(web)])
    filas.append("")
    filas.append(f"RESULTADO: {len(fallas)} fallas" + (": " + ", ".join(fallas) if fallas else ""))
    texto = "\n".join(filas)
    print(texto)
    if LOG:
        LOG.write_text(texto + "\n", encoding="utf-8")
    shutil.rmtree(HOME, ignore_errors=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
