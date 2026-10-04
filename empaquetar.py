#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Empaquetador de REAPER: une partes/*.py en un único reaper_v8.py.

Cada parte comparte el mismo espacio de nombres (igual que en v6), así que
no hay imports internos: todo lo de la librería estándar se importa en
00_cabecera.py. El empaquetador verifica:

  - que el archivo final compile (ast.parse + compile)
  - que no haya dos definiciones de primer nivel con el mismo nombre en
    partes distintas (una redefinición accidental pisaría código real)
  - que ninguna parte tenga marcadores de código omitido ("...resto igual")

Uso:
    python3 empaquetar.py              genera reaper_v8.py
    python3 empaquetar.py --stats      además muestra líneas por parte
    python3 empaquetar.py --test       genera y corre el autotest interno
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PARTES = RAIZ / "partes"
SALIDA = RAIZ / "reaper_v8.py"

_PEREZOSO = re.compile(r"^\s*#\s*\.\.\.\s*(resto|rest of|el resto)", re.I | re.M)


def nombres_primer_nivel(arbol: ast.Module) -> list[tuple[str, int]]:
    nombres = []
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nombres.append((nodo.name, nodo.lineno))
    return nombres


def leer_partes() -> list[tuple[str, str]]:
    archivos = sorted(p for p in PARTES.glob("*.py") if p.name[:2].isdigit())
    if not archivos:
        raise SystemExit("No hay partes en partes/")
    return [(p.stem, p.read_text(encoding="utf-8")) for p in archivos]


def verificar_parte(nombre: str, texto: str) -> ast.Module:
    try:
        arbol = ast.parse(texto, filename=f"partes/{nombre}.py")
    except SyntaxError as e:
        raise SystemExit(f"Error de sintaxis en partes/{nombre}.py línea {e.lineno}: {e.msg}")
    m = _PEREZOSO.search(texto)
    if m:
        linea = texto.count("\n", 0, m.start()) + 1
        raise SystemExit(f"Marcador de código omitido en partes/{nombre}.py:{linea}: {m.group(0).strip()}")
    return arbol


def empaquetar(stats: bool = False) -> Path:
    partes = leer_partes()
    vistos: dict[str, str] = {}
    errores = []
    bloques = []
    conteo = []
    for nombre, texto in partes:
        arbol = verificar_parte(nombre, texto)
        for definido, linea in nombres_primer_nivel(arbol):
            if definido in vistos and vistos[definido] != nombre:
                errores.append(f"'{definido}' definido en {vistos[definido]} y en {nombre}:{linea}")
            vistos.setdefault(definido, nombre)
        if nombre.startswith("00_"):
            bloques.append(texto.rstrip("\n") + "\n")
        else:
            modulo = nombre.split("_", 1)[1] if "_" in nombre else nombre
            bloques.append(
                "\n\n# " + "=" * 70 + f"\n# MÓDULO: {modulo}\n# " + "=" * 70 + "\n"
                + texto.strip("\n") + "\n"
            )
        conteo.append((nombre, texto.count("\n") + 1))
    if errores:
        raise SystemExit("Definiciones duplicadas entre partes:\n  " + "\n  ".join(errores))

    final = "".join(bloques)
    try:
        compile(final, str(SALIDA), "exec", dont_inherit=True)
    except SyntaxError as e:
        raise SystemExit(f"El archivo final no compila: línea {e.lineno}: {e.msg}")

    temporal = SALIDA.with_suffix(".tmp")
    temporal.write_text(final, encoding="utf-8")
    os.replace(temporal, SALIDA)
    os.chmod(SALIDA, 0o755)

    total = final.count("\n")
    if stats:
        ancho = max(len(n) for n, _ in conteo)
        for nombre, lineas in conteo:
            print(f"  {nombre:<{ancho}}  {lineas:>6}")
    print(f"✓ {SALIDA.name}: {total} líneas, {len(conteo)} partes")
    return SALIDA


def main() -> int:
    parser = argparse.ArgumentParser(description="Empaqueta REAPER en un solo archivo")
    parser.add_argument("--stats", action="store_true", help="muestra líneas por parte")
    parser.add_argument("--test", action="store_true", help="corre el autotest interno después")
    args = parser.parse_args()
    salida = empaquetar(stats=args.stats)
    if args.test:
        return subprocess.call([sys.executable, str(salida), "--autotest"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
