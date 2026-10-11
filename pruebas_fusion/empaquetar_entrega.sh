#!/usr/bin/env bash
# Arma REAPER_FUSION_ENTREGA.zip con solo lo necesario (sin .env, claves, cachés ni datos reales), lo verifica con
# unzip -t, prueba que el script del ZIP se instala y corre en una copia limpia, y calcula los SHA-256.
set -euo pipefail
cd "$(dirname "$0")/.."
E=entrega_fusion
cp reaper_v8.py "$E/reaper_8.10_fusionado.py"
rm -f "$E/REAPER_FUSION_ENTREGA.zip"
TMP=$(mktemp -d)
mkdir -p "$TMP/REAPER_FUSION_ENTREGA"
cp "$E"/reaper_8.10_fusionado.py "$E"/*.patch "$E"/*.md "$TMP/REAPER_FUSION_ENTREGA/"
cp -r pruebas_fusion "$TMP/REAPER_FUSION_ENTREGA/"
find "$TMP" -name "__pycache__" -prune -exec rm -rf {} + ; find "$TMP" -name "*.db" -delete
# Nada que parezca una credencial dentro del paquete. Solo se toleran los fixtures SINTÉTICOS de los tests de
# redacción (secuencias 0123456789 / AbCdEf...); cualquier otro valor con forma de clave aborta el empaquetado.
python3 - "$TMP" <<'PYEOF'
import re, sys
from pathlib import Path
patron = re.compile(r"(sk-or-v1-[A-Za-z0-9_-]{8,}|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|nvapi-[A-Za-z0-9_-]{12,}|github_pat_[A-Za-z0-9_]{12,})")
sintetico = re.compile(r"0123456789|AbCdEfGh|bCdEfGhIj")
reales = []
for f in Path(sys.argv[1]).rglob("*"):
    if f.is_file() and f.suffix in (".py", ".md", ".patch", ".log", ".sh", ".txt", ".json", ".html", ".js", ".css"):
        for m in patron.finditer(f.read_text(encoding="utf-8", errors="replace")):
            if not sintetico.search(m.group(0)):
                reales.append(f"{f.name}: {m.group(0)[:12]}…")
if reales:
    print("ABORTO: posible credencial real en el paquete:", *reales, sep="\n  ")
    sys.exit(1)
print("escaneo de credenciales: solo fixtures sintéticos de tests")
PYEOF
(cd "$TMP" && zip -qr -X REAPER_FUSION_ENTREGA.zip REAPER_FUSION_ENTREGA)
mv "$TMP/REAPER_FUSION_ENTREGA.zip" "$E/"
unzip -tq "$E/REAPER_FUSION_ENTREGA.zip"
# Copia limpia: descomprimir en otra carpeta, compilar, versión y un grupo de autotest.
LIMPIA=$(mktemp -d)
(cd "$LIMPIA" && unzip -q "$OLDPWD/$E/REAPER_FUSION_ENTREGA.zip" \
  && HOME="$LIMPIA/home" python3 -m py_compile REAPER_FUSION_ENTREGA/reaper_8.10_fusionado.py \
  && HOME="$LIMPIA/home" python3 REAPER_FUSION_ENTREGA/reaper_8.10_fusionado.py --version \
  && HOME="$LIMPIA/home" python3 REAPER_FUSION_ENTREGA/reaper_8.10_fusionado.py --autotest-filtro testfalsosverdesfusion | tail -1)
rm -rf "$TMP" "$LIMPIA"
(cd "$E" && sha256sum reaper_8.10_fusionado.py REAPER_FUSION_CHATGPT_CLAUDE.patch REAPER_FUSION_PARTES_DESDE_ENTREGA_ANTERIOR.patch \
   REAPER_FUSION_AUDITORIA.md REAPER_FUSION_PRUEBAS.md REAPER_FUSION_PARA_CHATGPT.md REAPER_FUSION_ENTREGA.zip > REAPER_FUSION_SHA256.txt)
cat "$E/REAPER_FUSION_SHA256.txt"
