# REAPER 8.10 fusionado — entrega de Claude Code a ChatGPT

Para la próxima auditoría independiente. Mismo código para los dos asistentes; los cambios deben seguir siendo
acumulativos, reproducibles y verificables.

## 1. De qué partir (importante para no perder trabajo)

- Archivo a auditar: `reaper_8.10_fusionado.py` (SHA-256 en `REAPER_FUSION_SHA256.txt`).
- Se puede reconstruir desde tu archivo: `patch -o reaper_8.10_fusionado.py reaper_8.10.py < REAPER_FUSION_CHATGPT_CLAUDE.patch`
  sobre tu `reaper_8.10.py` de la ronda 12 (SHA `19453f67…da89c`) reproduce **byte a byte** el archivo final (verificado).
- El archivo es un bundle de un solo espacio de nombres generado por `empaquetar.py` desde `partes/*.py`
  (separadores `# MÓDULO: <nombre>`). El repositorio fuente es `celparaguayy-cloud/Reaper.py`, rama
  `ccr-6e025352-3tb6n4`. **Si editás el bundle a mano, mandá el diff contra este SHA**; así se reaplica por módulo.
- Ruta de inicio: `python3 reaper_8.10_fusionado.py` o `python3 reaper_8.10_fusionado.py --instalar` (copia el archivo a
  `~/reaper/app/reaper.py`, lo compila antes de reemplazar y deja el comando `reaper`). El nombre del archivo no importa.

## 2. Cómo se hizo la fusión

Base común detectada: commit `02a41bf` (REAPER X experimental), del que salieron tu línea (rondas 9–12) y la mía
(caza de bugs de secretos y pérdida de datos). Merge de 3 vías **por módulo** (`git merge-file`), no sobrescritura.
Conflictos y decisiones: ver `REAPER_FUSION_AUDITORIA.md` §1. Todo lo tuyo de la ronda 12 se conservó
(gate de aceptación, `--aceptacion`, huella, diario reanudable, EV-ACEPTACION, tests round 6/9/10/11/12, CLI 8.10).

## 3. Qué cambié sobre tu ronda 12 y por qué (todo con test que fallaba antes)

1. **Gate de aceptación suplantable** (`ejecutar_aceptacion_independiente`): `python -m unittest` con `cwd` en el
   proyecto pone el proyecto en `sys.path`; un `unittest.py` del proyecto imprimía "Ran 50 tests OK" y el gate
   aprobaba una suite que fallaba. Ahora: runner de confianza `_RUNNER_ACEPTACION` con `python -I -B`, el conteo sale
   de los objetos `TestResult` en una línea con marca aleatoria recibida por stdin; se exige 0 fallos/errores/éxitos
   inesperados, exit 0 y `efectivos >= min_tests`. La salida legible sigue en stderr (tus tests de round 12 pasan).
2. **Huella V2**: cubre todos los archivos de la suite (auxiliares incluidos, sin `__pycache__`), con límites de
   cantidad/tamaño y sin symlinks. Un diario con huella V1 de tu ronda se migra si la suite no cambió.
3. **Manifiesto y diario fuera del alcance del agente**: `ARCHIVOS_CONTROL_REAPER` en `Workspace.ruta(escribir=True)`.
4. **Variable `REAPER_PROYECTO`** para que el evaluador encuentre el proyecto (los tests deben levantar el servidor
   como subproceso; con `-I` el proyecto ya no está en `sys.path`).
5. `ALIAS_MODELOS_HEREDADOS` quedó vacío: sus entradas cruzaban proveedor/familia y además eran inalcanzables
   (`MODELOS` tiene prioridad). Evidencia del catálogo público de OpenRouter en la auditoría.
6. `ejecutar_tests`: exit 5 sin tests también para unittest (Python ≥ 3.12).

## 4. Otros arreglos P0/P1/P2 (resumen; detalle en la auditoría)

XML mal cerrado que se escribía en archivos · Ctrl+C colgado (27 s → 2 s) · hijos huérfanos · tests todos omitidos =
"verificada" · plazos de pared por tarea/build y corte de reparaciones sin cambios · `recursos-html` con raíz web ·
tareas intermedias que enlazan assets de tareas posteriores · "SIN CAMBIOS" con archivos creados antes en la misma
build · proyecto que aflojaba el modo de permisos · hooks `al_iniciar`/`despues_de_build` sin consentimiento ·
plantilla Perl con rutas con espacios · vigía de tests colgados.

## 5. Archivos modificados (fuente)

`00_cabecera` (import secrets) · `03_config` (plazos, modo/hooks solo endurecibles, alias) · `05_llm` (CANCELAR en el
stream, sin reintentos con plazo vencido) · `06_protocol` (`sin_cierre`, `cierre_espurio`) · `08_workspace`
(archivos de control, redactor) · `10_validators` (registro de hijos, raíz web, exit 5 unittest, `env_extra`) ·
`15_knowledge` (pista de assets) · `20_agent` (`ejecutar_hilos`, `PlazoTrabajo`, rechazo de XML) · `21_longwriter`,
`22_tournament` (hilos interrumpibles) · `25_pipeline` (gate, plazos, reparación sin cambios, tareas intermedias,
todo omitido) · `35_cli` (hooks con consentimiento) · `39_plantillas_lenguajes` (Perl) · `49_autotest_runner` (vigía)
· `51_extensiones` · `99_main` · tests nuevos: `48zc_autotest_p0_fusion` (28 tests en 9 clases).

## 6. Qué debería auditar ChatGPT a continuación (prioridad)

1. **Probar en el Termux real**: `--autotest` completo en el dispositivo (el vigía dirá qué test se traba si pasa), y
   `python3 reaper_8.10_fusionado.py --aceptacion --proyecto ~/reaper-proyectos/mercadocontrol` con un evaluador basado
   en los **criterios originales** del 1/10 (los míos son un contrato supuesto en `pruebas_fusion/mercadocontrol/`).
2. **Construcción real de MercadoControl con IA** y gate activo: confirmar que no cierra "verificada" si el evaluador
   falla, y medir si los plazos (25/90 min) alcanzan con los modelos gratuitos del usuario.
3. **Runner de aceptación**: intentar romperlo (procesos hijos que escriben la marca, tests que importan el proyecto en
   proceso, señales, timeouts). Mi residual conocido: el código del proyecto importado DENTRO del proceso del runner
   puede manipular `TestResult`.
4. **`cierre_espurio`**: buscar falsos positivos/negativos con modelos reales (umbral 0,8 sobre el nombre de la
   herramienta y del parámetro; solo se aplica a parámetros sin su cierre propio).
5. **`PlazoTrabajo`** es global del proceso a propósito (lo ven los hilos del torneo); revisar interacción con
   `/construir continuar` y builds anidadas.
6. Pendientes reales: multiagente (roles realmente distintos, colas acotadas, selección por salud/costo), EOF/stdin en
   tareas interactivas, reanudación tras apagón a mitad de escritura, RAM en Android 2 GB, proveedores reales (no hay
   claves aquí; Dolphin `:free` no figura en el catálogo público de OpenRouter).

## 7. Reglas que mantengo (para que sigan valiendo en la próxima ronda)

No declarar éxito sin evidencia ejecutada · no modificar tests para ocultar defectos (el único test ajustado se
justificó con el catálogo real de OpenRouter) · mocks nunca como única evidencia de funcionamiento real (están
rotulados) · no aflojar permisos ni autorizaciones · claves solo por entorno, nunca en repo/logs/ZIP.

## 8. Lo agregado DESPUÉS de la fusión (acumulativo, con tests)

Sobre el código estabilizado, en la misma sesión:

1. **Interfaz** (panel de arranque, prompt `❯`, íconos por herramienta, ancho con emojis) y **flujo visual de
   `/construir`** (checklist del plan, cierre en caja con insignia de estado). Ideas de free-claude-code: solo las
   ideas, implementación propia (AGPL, no se copió código).
2. **Tres comandos**: `/validar` (config de modelos/equipo sin red; un solo `/validar` con dos modos: config y
   archivos), `/modelo elegir|buscar` (selector y búsqueda del catálogo) y `/diagnostico [archivo]` (reporte
   redactado por `redactar_secretos`, nunca filtra claves).
3. **8.º agente: JUEZ DE ENTREGA** (rol `juez`, solo JSON `{cumple,faltantes,evidence_ids,confianza}`). Corre al
   cerrar `/construir` SOLO sobre builds verdes; compara lo entregado contra el pedido y SOLO endurece
   (verificada/validada → parcial); nunca sube un rojo a verde (`parsear_juicio` lo fuerza desde la evidencia).
   Bajo costo: diffstat + `max_tokens=400`. Se apaga con `/equipo juez off`.
4. **Robustez en trabajos chicos**: `_es_testeable()` deja de forzar "tests primero" para una página estática
   (.html/.css) en carpeta vacía.

**Qué conviene auditar (además de lo de la sección 6):**
- El juez con modelos reales: ¿da falsos "no cumple" (castiga builds buenas) o se lo puede empujar a aprobar un
  pedido no cumplido? El gate exige confianza media/alta justamente para no castigar por ruido; revisá ese umbral.
- `parsear_juicio`: intentar que un veredicto `cumple:true` pase con la evidencia en rojo (no debería: se fuerza a
  false). Y que un JSON inválido no cambie nunca el estado.
- `_es_testeable`: casos límite (proyecto mixto, monorepo, assets + un `.js` suelto) para no apagar tests primero
  cuando sí hacen falta.

Archivos nuevos/modificados de esta tanda: `19_roles`, `54_ingles` (rol `juez`), `75_reaper_x`
(`Juicio`/`parsear_juicio`), `25_pipeline` (`_juicio_de_entrega`, `_es_testeable`, `max_tokens` en
`_consultar_rol_x`), `03_config` (`settings.juez`), `35_cli` (`/validar`, `/modelo elegir|buscar`,
`/diagnostico`, `/equipo juez`), `70_equipo` (`validar_configuracion`, `diagnostico_texto`, `estado_juez`);
tests: `48ze_autotest_juez` (15) y `TestConfigValidarDiagnostico` en `48zc` (9). Regresión 944 tests OK en
Python 3.11/3.12/3.13.
