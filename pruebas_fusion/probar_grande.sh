#!/usr/bin/env bash
# Prueba GRANDE de REAPER en Termux, en un solo comando:
#   1) baja la última versión y verifica que llegó entera (SHA-256 publicado en el repo);
#   2) la instala (tu config y tu clave en ~/reaper no se tocan);
#   3) muestra el diagnóstico y el cupo de pedidos gratis de hoy (e instala node si falta: lo usan los tests de la web);
#   4) construye el proyecto grande por etapas (o lo RETOMA si ya había empezado);
#   5) arma el ZIP de /reporte (sin claves) y lo copia a Descargas para mandarlo.
#
# Uso:  bash probar_grande.sh [carpeta del proyecto]      (por defecto ~/almacen)
# Si se corta (cupo del día, Termux cerrado), volvé a correr EXACTAMENTE lo mismo: sigue donde quedó.
set -u

RAMA="ccr-6e025352-3tb6n4"
URL_BASE="${REAPER_URL_BASE:-https://raw.githubusercontent.com/celparaguayy-cloud/Reaper.py/$RAMA}"
PROYECTO="${1:-$HOME/almacen}"
DESCARGA="$HOME/reaper_nuevo.py"
PEDIDO="Un sistema de gestión para un almacén de barrio, en Python con solo la librería estándar. Productos con \
código, nombre, precio y stock; clientes; ventas con varios productos que descuentan el stock y NO permiten vender \
sin stock; reporte de ventas por día y de los productos más vendidos; exportar productos y ventas a CSV. Base \
sqlite3 que se crea sola. Una API JSON con http.server: productos (listar, buscar, crear, editar), clientes, ventas \
(crear y listar) y reportes, validando los datos con mensajes de error claros. Una página web en web/ (index.html, \
app.js, style.css) para cargar una venta, ver el stock y los reportes, adaptable al celular. Arranca con \
'python3 -m almacen --puerto 8000'. Tests con unittest en tests/ para cada módulo y para la API levantando el \
servidor en un puerto libre."

paso() { printf '\n\033[1;35m▶ %s\033[0m\n' "$*"; }
falla() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

paso "1/5 · Bajando la última versión de REAPER"
curl -fsSL -o "$DESCARGA.tmp" "$URL_BASE/entrega_fusion/reaper_8.10_fusionado.py" \
  || falla "No pude bajar REAPER (¿hay internet?). Probá de nuevo."
ESPERADO=$(curl -fsSL "$URL_BASE/entrega_fusion/REAPER_FUSION_SHA256.txt" | awk '/reaper_8.10_fusionado.py/ {print $1}')
OBTENIDO=$(sha256sum "$DESCARGA.tmp" | awk '{print $1}')
if [ -z "$ESPERADO" ] || [ "$ESPERADO" != "$OBTENIDO" ]; then
  rm -f "$DESCARGA.tmp"
  falla "La descarga no coincide con el SHA-256 publicado (esperado ${ESPERADO:-?}, bajó $OBTENIDO). Probá de nuevo."
fi
mv "$DESCARGA.tmp" "$DESCARGA"
echo "  OK: SHA-256 $OBTENIDO"

paso "2/5 · Instalando (tu configuración y tu clave quedan como están)"
python3 "$DESCARGA" --instalar || falla "La instalación falló (la versión anterior sigue intacta)."
REAPER="reaper"
command -v reaper >/dev/null 2>&1 || REAPER="python3 $HOME/reaper/app/reaper.py"
$REAPER --version

if [ ! -s "$HOME/reaper/.clave_openrouter" ] && [ -z "${OPENROUTER_API_KEY:-}" ]; then
  falla "Falta tu clave de OpenRouter. Guardala UNA vez (no la pegues en ningún chat):
  printf %s 'TU_CLAVE' > ~/reaper/.clave_openrouter && chmod 600 ~/reaper/.clave_openrouter
y volvé a correr este script."
fi

paso "3/5 · Diagnóstico y cupo de pedidos gratis de hoy"
# Con --perfil gratis: así el diagnóstico mira los MISMOS modelos que va a usar la prueba y muestra el cupo de hoy.
$REAPER --perfil gratis --doctor || true
echo "  (sin crédito comprado: 50 pedidos gratis por día; con 10 o más de crédito: 1000)"

if ! command -v node >/dev/null 2>&1; then
  # La web del proyecto se prueba con node --test: sin node esos tests no corren y REAPER frena esa etapa.
  if command -v pkg >/dev/null 2>&1; then
    echo "  Falta node (hace falta para correr los tests de la web): lo instalo con pkg install nodejs…"
    pkg install -y nodejs >/dev/null 2>&1 && echo "  OK: $(node --version)" \
      || echo "  No pude instalar node. Hacelo a mano con: pkg install nodejs (si no, REAPER frena en la etapa de la web)."
  else
    echo "  Ojo: falta node. Sin node REAPER frena en la etapa de la web (instalalo y volvé a correr este script)."
  fi
fi

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock && echo "  Pantalla bloqueada sin cortar: termux-wake-lock activo."
else
  echo "  Consejo: pkg install termux-api y usá termux-wake-lock para que Android no corte la prueba."
fi

mkdir -p "$PROYECTO"
if [ -f "$PROYECTO/.reaper/proyecto_grande.json" ]; then
  paso "4/5 · Retomando el proyecto grande en $PROYECTO (no empieza de cero)"
  $REAPER --proyecto "$PROYECTO" --grande estado || true
  $REAPER --proyecto "$PROYECTO" --perfil gratis --auto --sin-animacion --grande continuar
else
  paso "4/5 · Construyendo el proyecto grande en $PROYECTO (por etapas; puede tardar bastante)"
  $REAPER --proyecto "$PROYECTO" --perfil gratis --auto --sin-animacion --grande "$PEDIDO"
fi
RESULTADO=$?

paso "5/5 · Armando el reporte para mandar (sin claves)"
$REAPER --proyecto "$PROYECTO" --perfil gratis --sin-animacion --reporte || true
ZIP=$(ls -t "$HOME"/reaper_reporte_*.zip 2>/dev/null | head -n 1)
if [ -n "$ZIP" ]; then
  if [ -d "$HOME/storage/downloads" ]; then
    cp "$ZIP" "$HOME/storage/downloads/" && echo "  Copiado a Descargas: $(basename "$ZIP")"
  else
    echo "  ZIP: $ZIP"
    echo "  Para pasarlo a Descargas: termux-setup-storage (una vez, acepta el permiso) y después:"
    echo "    cp $ZIP ~/storage/downloads/"
  fi
fi
command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock

if [ "$RESULTADO" -eq 0 ]; then
  printf '\n\033[1;32m✓ Proyecto grande TERMINADO Y VERIFICADO.\033[0m Probalo:\n'
  echo "  cd $PROYECTO && python3 -m unittest discover -s tests && python3 -m almacen --puerto 8000"
elif [ "$RESULTADO" -eq 130 ]; then
  printf '\n\033[1;33m◐ Lo cortaste (Ctrl+C). Lo hecho quedó guardado.\033[0m\n'
  echo "  Para seguir, corré EXACTAMENTE el mismo comando otra vez (retoma donde quedó)."
else
  # El motivo REAL de la parada (cupo del día con la hora en que se renueva, una etapa sin verificar…).
  MOTIVO=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("motivo", ""))' \
    "$PROYECTO/.reaper/proyecto_grande.json" 2>/dev/null)
  printf '\n\033[1;33m◐ Se detuvo: %s\033[0m\n' "${MOTIVO:-mirá el informe en el ZIP}"
  echo "  Mandame el ZIP de Descargas. Para seguir más tarde, corré EXACTAMENTE el mismo comando otra vez."
fi
exit "$RESULTADO"
