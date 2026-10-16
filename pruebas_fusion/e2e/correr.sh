#!/usr/bin/env bash
# Corrida de PUNTA A PUNTA de la CLI real de REAPER contra el OpenRouter falso (HTTP + SSE de verdad).
# Uso:   bash pruebas_fusion/e2e/correr.sh <nombre> [args de reaper]
# Ej.:   bash pruebas_fusion/e2e/correr.sh base --perfil gratis --auto --sin-animacion --grande "$(cat pedido.txt)"
#        (la carpeta del proyecto va con --proyecto; si no, REAPER usa la de siempre dentro del HOME falso)
# Fallas: MOCK_CUPO=N MOCK_429_CADA=K MOCK_RAZONA=<modelo> MOCK_FLOJO=1 (ver openrouter_falso.py).
# Cortes: SENAL=INT TOPE=40 → Ctrl+C a los 40 s (para probar que se retoma). Resultado en $E2E_SALIDA/<nombre>/.
set -u
AQUI=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$AQUI/../.." && pwd)
NOMBRE=$1; shift
DIR=${E2E_SALIDA:-${TMPDIR:-/tmp}/reaper_e2e}/$NOMBRE
mkdir -p "$DIR/home"
export REAPER_REPO=$REPO
export MOCK_LOG=$DIR/pedidos.jsonl MOCK_ESTADO=${MOCK_ESTADO:-$DIR/estado_mock.json}
python3 "$AQUI/openrouter_falso.py" > "$DIR/puerto.txt" 2> "$DIR/mock.err" &
MOCK=$!
for _ in $(seq 50); do [ -s "$DIR/puerto.txt" ] && break; sleep 0.2; done
PUERTO=$(cat "$DIR/puerto.txt")
export HOME=$DIR/home
unset REAPER_HOME
export OPENROUTER_API_KEY=sk-or-v1-e2e0123456789falsa0123456789     # falsa: nunca sale de la máquina
export REAPER_API_URL=http://127.0.0.1:$PUERTO/api/v1/chat/completions
export REAPER_OPENROUTER_BASE=http://127.0.0.1:$PUERTO/api/v1
cd "$HOME"
timeout -s "${SENAL:-TERM}" "${TOPE:-900}" python3 "$REPO/reaper_v8.py" "$@" > "$DIR/salida.txt" 2>&1
echo "EXIT=$?" >> "$DIR/salida.txt"
kill "$MOCK" 2>/dev/null
wait "$MOCK" 2>/dev/null
echo "salida: $DIR/salida.txt · pedidos: $DIR/pedidos.jsonl"
tail -5 "$DIR/salida.txt"
