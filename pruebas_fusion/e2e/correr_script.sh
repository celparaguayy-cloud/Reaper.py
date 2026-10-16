#!/usr/bin/env bash
# El script del teléfono (pruebas_fusion/probar_grande.sh) ENTERO, sin red: la "descarga" sale de un servidor local con
# el reaper_v8.py actual y su SHA-256, y el modelo es el OpenRouter falso. Uso: bash pruebas_fusion/e2e/correr_script.sh
set -u
AQUI=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$AQUI/../.." && pwd)
S=${E2E_SALIDA:-${TMPDIR:-/tmp}/reaper_e2e}/script
rm -rf "$S" && mkdir -p "$S/srv/entrega_fusion" "$S/home"
cp "$REPO/reaper_v8.py" "$S/srv/entrega_fusion/reaper_8.10_fusionado.py"
(cd "$S/srv/entrega_fusion" && sha256sum reaper_8.10_fusionado.py > REAPER_FUSION_SHA256.txt)
export REAPER_REPO=$REPO MOCK_LOG=$S/pedidos.jsonl MOCK_ESTADO=$S/estado_mock.json
python3 "$AQUI/openrouter_falso.py" > "$S/puerto.txt" 2> "$S/mock.err" &
MOCK=$!
python3 -m http.server 0 --bind 127.0.0.1 --directory "$S/srv" > "$S/srv.log" 2>&1 &
SRV=$!
for _ in $(seq 50); do [ -s "$S/puerto.txt" ] && grep -q "port" "$S/srv.log" && break; sleep 0.2; done
PUERTO=$(cat "$S/puerto.txt")
PSRV=$(grep -o "port [0-9]*" "$S/srv.log" | head -1 | cut -d' ' -f2)
export HOME=$S/home OPENROUTER_API_KEY=sk-or-v1-e2e0123456789falsa0123456789
export REAPER_API_URL=http://127.0.0.1:$PUERTO/api/v1/chat/completions
export REAPER_OPENROUTER_BASE=http://127.0.0.1:$PUERTO/api/v1 REAPER_URL_BASE=http://127.0.0.1:$PSRV
unset REAPER_HOME
cd "$HOME"
timeout -s "${SENAL:-TERM}" "${TOPE:-1500}" bash "$REPO/pruebas_fusion/probar_grande.sh" "$@" > "$S/salida.txt" 2>&1
echo "EXIT=$?" >> "$S/salida.txt"
kill "$MOCK" "$SRV" 2>/dev/null
wait 2>/dev/null
echo "salida: $S/salida.txt"
tail -6 "$S/salida.txt"
