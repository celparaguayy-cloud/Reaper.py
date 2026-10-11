# REAPER — caza de bugs críticos (bitácora)

Base: este repositorio (`partes/` → `reaper_v8.py`). Cada hallazgo se reprodujo con un script antes de
tocar código, se corrigió, se cubrió con un autotest y se validó en Python 3.11, 3.12 y 3.13.

Criterio de severidad del usuario: bugs **como los anteriores** = fuga de secretos y pérdida/corrupción de
datos. Esos tienen prioridad; lo estético o lo opinable se deja documentado, no se "arregla" a la fuerza.

## P0 — Fugas de secretos (corregido)

| ID | Qué pasaba | Corrección | Prueba |
|---|---|---|---|
| BUG-001 | La clave del proveedor activo al crear el cliente se reusaba para OTRO proveedor al cambiar de ruta (p. ej. OpenRouter → Groq) | `_clave_de` entrega SOLO la clave del proveedor destino; el `api_key` del constructor queda fijado a su proveedor de origen | `TestClaveNoCruzaProveedor` |
| BUG-002 | Un `.reaper.toml` del repo podía cambiar `api_url`/`proveedor` y redirigir el tráfico (y las claves) a un host atacante | `OVERRIDES_PROHIBIDOS_PROYECTO`: el proyecto no puede tocar endpoint, proveedor, privacidad, red ni plugins | `TestProyectoNoRedirigeEndpoint` |
| — | Los subprocesos heredaban secretos del entorno del usuario | `entorno_seguro()` filtra KEY/TOKEN/SECRET/PASSWORD/DSN/… y deja las inocuas | `TestEntornoSinSecretos` |
| — | La salida de comandos, las sesiones guardadas y el log en disco podían contener claves en claro | `redactar_secretos` sobre stdout/stderr/comando, sesión y log de la UI; patrones sk-/gsk_/AIza/nvapi-/github_pat/AKIA/Bearer + asignaciones y URLs con credencial | `TestSalidaComandoRedactada`, `TestRedaccionSecretos`, `TestLogsYProveedorRetirado` |

## P1 — Pérdida / corrupción de datos (corregido)

| ID | Qué pasaba | Corrección | Prueba |
|---|---|---|---|
| mover binarios | `mover()` reescribía archivos como texto y corrompía binarios / perdía el bit de ejecución | copia byte a byte con `shutil.copy2` (preserva modo) + checkpoint de origen y destino | `TestDataLoss` (mover) |
| stream truncado | Un stream cortado sin cierre ni `finish_reason` se trataba como respuesta completa → el agente escribía archivos a medias | se exige `[DONE]`/`finish_reason`; si no, `_Transitorio("respuesta truncada")` y se reintenta/cambia de modelo | `TestDataLoss` (stream) |
| torneo pisa grandes | Aplicar la copia ganadora podía pisar archivos grandes/nuevos del destino | `aplicar_a` registra conflictos y no clobbea archivos "nuevos" ya existentes | `TestDataLoss` (torneo) |
| forense borra | `FotoProyecto` borraba al salir archivos que ya existían antes de entrar | `__exit__` solo elimina lo creado dentro del bloque; checkpoint antes de borrar | `TestDataLoss` (forense) |
| test gaming | El pipeline aceptaba como "verde" cuando se habían tocado los tests de la especificación | se protegen los archivos de test de la espec antes de implementar | `48y` / pipeline |

## P1 — Corrupción silenciosa en `rename_symbol` (corregido esta tanda)

- **Qué pasaba**: renombrar un símbolo libre (función/clase/variable) reescribía TODOS los tokens con ese
  nombre, incluidos accesos por atributo de instancia ajenos (`self.total`, `c.total`). El resultado era
  Python válido, así que la validación+reversión NO lo detectaba: corrupción silenciosa.
- **Corrección**: si `viejo` NO está definido como método de clase en el proyecto, los accesos por atributo de
  instancia se dejan intactos (y se reportan). Se mantienen las llamadas calificadas por módulo importado
  (`import a; a.total()`) y, cuando `viejo` SÍ es un método, sus llamadas (`obj.metodo()`) sí se renombran.
- **Límite honesto**: con proyectos sin `.py` no se puede clasificar y se conserva el comportamiento previo;
  un `modulo.funcion()` en JS no se distingue de un atributo. El tool avisa cuántos accesos dejó sin tocar.
- **Prueba**: `TestRenombrar` (`test_python_modo_seguro_no_toca_atributos_de_instancia`,
  `test_funcion_libre_no_corrompe_atributo_ajeno`, `test_metodo_renombra_sus_llamadas`).

## P2 — Robustez / responsividad (corregido esta tanda)

- **Espera de reintento no cancelable**: un `Retry-After` alto (o el backoff) hacía un `time.sleep` único de
  hasta 120 s; en el teléfono se sentía colgado y no se podía cancelar. Ahora la espera se trocea en tramos de
  ~1 s y revisa `CANCELAR` en cada tramo; el tope de 120 s se mantiene. Prueba: `TestEsperaReintentoCancelable`.
- **Salida de subprocesos acotada en memoria** (A09): stdout/stderr van a archivos temporales y se lee solo la
  cola (`MAX_SALIDA_PROCESO`), para no agotar RAM con salidas enormes.
- **`--autotest` con filtro que no casa** (A20): antes decía "0 tests OK" (verde falso); ahora sale con código 2.
- **Hooks del repositorio** (A11): piden consentimiento una sola vez y fallan cerrados en modo no interactivo.
- **Proveedor retirado** (A15): `github-models` no se sondea ni gasta intentos; no infla el conteo.

## Revisado y declarado "no es bug" (comportamiento intencional)

- `costo_maximo = 0` = sin límite de presupuesto. Es deliberado y está documentado en el propio mensaje de
  error ("ponelo en 0"); el perfil `gratis` impone un techo de 0.01 USD.

## Pendiente (no crítico; documentado, sin arreglo forzado)

- Aplicación dura del `ExecutionBroker` (los roles de ejecución comparten el mismo gate; falta aislamiento por
  rol) — arquitectónico, se documenta en vez de parchear a medias.
- Detector de *test gaming* por contenido (BUG-010/011): el modelo puede escribir tests tautológicos; hoy se
  mitiga protegiendo los tests de la especificación, no detectando tautologías arbitrarias.
- Ensayo OFICIORADAR de extremo a extremo con **modelos reales** (requiere las claves del usuario): **NO
  VERIFICADO** en este entorno. Todo lo de arriba se probó con transportes simulados, sin red.

## Evidencia

`python3 reaper_v8.py --autotest` → suite completa en Python 3.11, 3.12 y 3.13 (sin red, transportes
simulados). `ruff check reaper_v8.py` sin hallazgos nuevos respecto de la línea base (solo ruido estructural
del bundle de un solo archivo: E741/E402/E702/F401).
