#!/usr/bin/env python3
"""
Corre las reproducciones de los defectos P0 contra uno o más archivos de REAPER y deja una tabla ANTES/DESPUÉS.
Sin API ni red: procesos, archivos y señales reales en carpetas temporales.

Uso:  python3 pruebas_fusion/repros/correr_repros.py ANTES.py DESPUES.py [log]
      (ANTES = reaper_8.10.py de la ronda 12 de ChatGPT; DESPUES = reaper_8.10_fusionado.py)
"""
import signal
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def correr(script, bundle, *extra, timeout=120):
    r = subprocess.run([sys.executable, "-I", str(AQUI / script), str(bundle), *extra],
                       capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def ctrl_c(bundle):
    """SIGINT con dos subagentes esperando a un modelo de 30 s: segundos hasta que el proceso sale."""
    p = subprocess.Popen([sys.executable, "-I", str(AQUI / "repro_ctrlc.py"), str(bundle), "30", "explorador"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    p.stdout.readline()
    time.sleep(2)
    inicio = time.monotonic()
    p.send_signal(signal.SIGINT)
    try:
        p.wait(timeout=60)
    except subprocess.TimeoutExpired:
        p.kill()
        return "no salió en 60 s"
    return f"salió en {time.monotonic() - inicio:.1f} s"


def huerfanos(bundle):
    """SIGINT mientras corre un subproceso largo: ¿queda vivo el hijo?"""
    p = subprocess.Popen([sys.executable, "-I", str(AQUI / "repro_huerfano.py"), str(bundle)],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    p.stdout.readline()
    time.sleep(1.0)
    p.send_signal(signal.SIGINT)
    p.wait(timeout=30)
    time.sleep(1.5)
    pids = subprocess.run(["pgrep", "-f", "sleep 47"], capture_output=True, text=True).stdout.split()
    vivos = [pid for pid in pids
             if not subprocess.run(["ps", "-o", "stat=", "-p", pid], capture_output=True, text=True).stdout.startswith("Z")]
    for pid in pids:
        subprocess.run(["kill", "-9", pid], capture_output=True)
    return f"hijos vivos tras Ctrl+C: {len(vivos)}"


CASOS = [
    ("P0-3 XML mal cerrado se escribe en el archivo", lambda b: correr("repro_xml.py", b).splitlines()[0]),
    ("P0-4 Ctrl+C con modelo lento", ctrl_c),
    ("P0-4b hijos huérfanos tras Ctrl+C", huerfanos),
    ("P0-5a gate suplantado por unittest.py", lambda b: " | ".join(
        l for l in correr("repro_sombra.py", b).splitlines() if l.startswith(("SIN", "CON")))),
    ("P0-5c agente edita/borra acceptance.json", lambda b: " | ".join(correr("repro_manifiesto.py", b).splitlines())),
    ("P0-5d tests todos omitidos", lambda b: correr("repro_skip.py", b).splitlines()[-1]),
    ("P2 proyecto afloja modo/hooks", lambda b: correr("repro_modo.py", b)),
    ("P2 hook al_iniciar sin consentimiento", lambda b: correr("repro_hook_inicio.py", b)),
]


def main():
    bundles = [Path(a).resolve() for a in sys.argv[1:3]]
    log = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    filas = [f"Python {sys.version.split()[0]}"] + [f"[{i}] {b.name}" for i, b in enumerate(bundles)] + [""]
    for nombre, caso in CASOS:
        filas.append(f"== {nombre}")
        for i, b in enumerate(bundles):
            try:
                salida = caso(b)
            except Exception as e:               # una reproducción que no corre se informa, no se oculta
                salida = f"ERROR al reproducir: {type(e).__name__}: {e}"
            filas.append(f"  [{i}] {salida}")
    texto = "\n".join(filas)
    print(texto)
    if log:
        log.write_text(texto + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
