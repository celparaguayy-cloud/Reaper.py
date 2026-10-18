#!/usr/bin/env bash
# Mide cuántas veces REAPER termina el almacén de /grande con un MODELO GRATIS FLOJO simulado (MOCK_CAOS).
# Uso: bash pruebas_fusion/e2e/caos.sh [corridas=3] [nivel=1] [semilla_inicial=1]
# Cada corrida es la CLI real contra el OpenRouter falso; misma semilla = misma secuencia de fallas.
set -u
AQUI=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$AQUI/../.." && pwd)
CORRIDAS=${1:-3}; NIVEL=${2:-1}; DESDE=${3:-1}
BASE=${E2E_SALIDA:-${TMPDIR:-/tmp}/reaper_e2e}/caos_n${NIVEL}
mkdir -p "$BASE"
PEDIDO=$(python3 - "$REPO/pruebas_fusion/probar_grande.sh" <<'PY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
print(re.search(r'PEDIDO="(.*?)"\n', s, re.S).group(1).replace("\\\n", ""))
PY
)
printf "%-7s %-5s %-9s %-8s %-7s %s\n" semilla exit etapas pedidos tiempo motivo
for semilla in $(seq "$DESDE" $((DESDE + CORRIDAS - 1))); do
  nombre=s$semilla
  rm -rf "$BASE/$nombre"
  inicio=$(date +%s)
  E2E_SALIDA=$BASE MOCK_CAOS=$NIVEL MOCK_SEMILLA=$semilla TOPE=${TOPE:-1800} \
    bash "$AQUI/correr.sh" "$nombre" --proyecto "$BASE/$nombre/home/almacen" --perfil gratis --auto --sin-animacion \
    --grande "$PEDIDO" > /dev/null 2>&1
  dur=$(( $(date +%s) - inicio ))
  python3 - "$BASE/$nombre" "$semilla" "$dur" <<'PY'
import json, re, sys
from pathlib import Path
d, semilla, dur = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
salida = (d / "salida.txt").read_text(encoding="utf-8", errors="replace") if (d / "salida.txt").exists() else ""
codigo = (re.findall(r"EXIT=(\d+)", salida) or ["?"])[-1]
pedidos = sum(1 for _ in open(d / "pedidos.jsonl")) if (d / "pedidos.jsonl").exists() else 0
etapas, motivo = "?", ""
estado = d / "home/almacen/.reaper/proyecto_grande.json"
if estado.exists():
    e = json.loads(estado.read_text(encoding="utf-8"))
    lista = e.get("maestro", {}).get("etapas", [])
    etapas = f"{sum(1 for x in lista if x.get('estado') in ('verificada', 'validada'))}/{len(lista)}"
    motivo = "TERMINADO" if e.get("estado") == "terminado" else " ".join(str(e.get("motivo", e.get("estado"))).split())[:90]
print(f"{semilla:<7} {codigo:<5} {etapas:<9} {pedidos:<8} {dur // 60}m{dur % 60:02d}s  {motivo}")
PY
done
