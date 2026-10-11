#!/usr/bin/env python3
"""
Corre el gate de aceptación independiente de REAPER (`--aceptacion --proyecto`) contra tres proyectos de prueba
y deja la evidencia en un log: vacío (sin app), roto (defectos reportados) y referencia (app correcta).

Cada proyecto se copia a una carpeta temporal propia; el evaluador se copia a OTRA carpeta temporal fuera del
proyecto (como exige el manifiesto). No usa API de modelos ni red externa: HTTP real a 127.0.0.1 y SQLite real.

Uso:  python3 pruebas_fusion/mercadocontrol/correr_aceptacion.py [ruta/a/reaper.py] [log_de_salida]
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REAPER = Path(sys.argv[1] if len(sys.argv) > 1 else AQUI.parents[1] / "reaper_v8.py").resolve()
LOG = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None


def preparar(variante: str, base: Path) -> Path:
    suite = base / "evaluador"
    shutil.copytree(AQUI / "evaluador", suite, ignore=shutil.ignore_patterns("__pycache__"))
    proyecto = base / "proyecto"
    if variante == "vacio":
        proyecto.mkdir()
    else:
        shutil.copytree(AQUI / variante, proyecto, ignore=shutil.ignore_patterns("__pycache__", "*.db"))
    (proyecto / ".reaper").mkdir(exist_ok=True)
    (proyecto / ".reaper" / "acceptance.json").write_text(
        json.dumps({"suite_dir": str(suite), "min_tests": 10, "timeout": 120}), encoding="utf-8")
    return proyecto


def main() -> int:
    salida = [f"REAPER: {REAPER}", f"Python: {sys.version.split()[0]}", f"Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    esperado = {"vacio": 2, "rota": 2, "referencia": 0}
    todo_ok = True
    for variante, rc_esperado in esperado.items():
        with tempfile.TemporaryDirectory(prefix=f"mc_{variante}_") as tmp:
            proyecto = preparar(variante, Path(tmp))
            inicio = time.monotonic()
            r = subprocess.run([sys.executable, str(REAPER), "--aceptacion", "--proyecto", str(proyecto)],
                               capture_output=True, text=True, timeout=300)
            dur = time.monotonic() - inicio
            texto = (r.stdout + r.stderr)
            resumen = [l for l in texto.splitlines() if l.startswith("ACEPTACIÓN") or " ... " in l]
            coincide = r.returncode == rc_esperado
            todo_ok &= coincide
            salida.append(f"=== {variante}: exit {r.returncode} (esperado {rc_esperado}) "
                          f"{'OK' if coincide else 'NO COINCIDE'} · {dur:.1f}s")
            salida.extend("  " + l for l in resumen[-20:])
            salida.append("")
    salida.append("RESULTADO: " + ("el gate distingue vacío/roto/correcto" if todo_ok else "DISCREPANCIA, revisar"))
    texto = "\n".join(salida)
    print(texto)
    if LOG:
        LOG.write_text(texto + "\n", encoding="utf-8")
    return 0 if todo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
