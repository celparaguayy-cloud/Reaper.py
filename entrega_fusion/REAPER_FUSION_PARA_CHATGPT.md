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

## 9. El juez como MOTOR CENTRAL (bajo costo)

El juez ahora dirige el build, pero mayormente DETERMINISTA para no gastar tokens: en un build limpio son ~2
llamadas chicas (contrato + veredicto) y más solo si interviene.
- **Contrato**: `_contrato_de_entrega` convierte el pedido en criterios al inicio (`parsear_criterios_entrega`,
  max_tokens 350); se guarda en el diario y se reusa al reanudar.
- **Vigía determinista**: `cobertura_criterios` (0 llamadas) marca criterios que el plan no parece cubrir.
- **Cierre**: `_cerrar_con_juez` + `_debe_intervenir_juez`: si el veredicto final es NO CUMPLE (confianza media/alta)
  y hay cupo (`juez_max_intervenciones`, def. 1), el reparador implementa los faltantes, se re-verifica de verdad y
  el juez re-juzga. Acotado; nunca declara verde sin verificación real.

**A romper:** (1) que el cierre entre en bucle o declare cumplido sin que la verificación real lo confirme;
(2) que `cobertura_criterios` dé falsos "sin cubrir" molestos con sinónimos; (3) que el contrato invente criterios
que el usuario no pidió (el prompt lo prohíbe, pero medirlo con modelos reales). Tests: `TestJuezContrato` (6),
`TestJuezCierra` (3). Regresión 953 tests OK en Python 3.11/3.12/3.13.

## 10. Reparación con la corrida REAL de script_whatsapp (Termux, Python 3.14.6)

Tus informes describían síntomas; acá está lo que se pudo **reproducir** en el código de REAPER, la causa y el
arreglo. Cada punto tiene test de regresión que **falla con el código anterior** (15 de 15) y pasa con este.

| Síntoma que viste | Causa confirmada en REAPER | Arreglo |
|---|---|---|
| `app.py` empezaba con `REAPER 8.10 · diagnóstico` y `SyntaxError: invalid character '·' (U+00B7)` | `/diagnostico <archivo>` escribía el reporte **encima** del archivo pasado como argumento, sin checkpoint. `/diagnostico app.py` reproduce exactamente esa primera línea y ese error. | Nunca pisa un archivo existente ni crea uno de código: guarda en `.reaper/diagnostico_<fecha>.txt` y avisa. |
| `signal 9` instalando dependencias (grpcio) | Un proceso matado se reportaba como `exit code: -9` sin explicación; la única pista era "instalá clang", que lleva a repetir la misma compilación. | `Resultado.senal()` explica SIGKILL (memoria en Android); pistas nuevas para señal 9 y grpcio, con prioridad sobre la de compilar. |
| Tarea 1 fallida, 2-5 bloqueadas, "el reparador no cambió ningún archivo en 2 intentos" | Con la guardia PRESERVAR, reescribir un archivo previo declarado se rechazaba **siempre**, incluso pedido explícitamente: reproducido con "reescribí app.py desde cero" (REESCRITURA DESTRUCTIVA ×4, mismas notas que tu informe). Además el archivo reescrito quedaba en disco. | El plan avisa antes de aprobar qué archivos existentes reemplaza. La reescritura vale si el pedido la pide ("desde cero", "reescribí") o si aprobaste ese plan; si no, se protege y, si la tarea termina rechazada, **se restaura** el contenido previo. |
| El informe no decía por qué falló la tarea 1 | El motivo real (`verif.diagnostico`) no llegaba a la pantalla ni a `.reaper/informes/`. | Pantalla: `motivo: …`. Informe: versión de REAPER/Python, "Por qué fallaron las tareas", restauraciones, reemplazos autorizados y contrato/veredicto del juez. |
| `UNVERIFIED` repetido | En modo conversación salía en gris y en inglés aunque hubiera archivos cambiados. | Aviso visible "SIN VERIFICAR" en castellano. Nunca se convierte en éxito. |

**No verificable desde acá (queda PENDIENTE):** qué versión exacta corrió tu build (el informe viejo no la
guardaba; desde ahora sí), los "17 tests de WhatsApp" de otra corrida (no hay logs) y si la build de las 16:08
falló por PRESERVAR o por otro motivo (el informe viejo no guardaba el motivo). Recuperación: el `app.py` previo a la
build (la app de tareas) está en el checkpoint de esa build (`/checkpoints`, `/deshacer <id>`); el `app.py` que
escribió la build se perdió con `/diagnostico` (esa escritura no tenía checkpoint).

**Alcance:** se reparó REAPER. La funcionalidad de `script_whatsapp` (números para registrar WhatsApp sacados de
páginas públicas) no se construye ni se repara. Tests: `TestBuildReal*` (15). Regresión 1005 tests OK en Python
3.11/3.12/3.13.

## 11. Primera prueba con modelo REAL (OpenRouter `:free`, $0)

Detalle completo, con evidencia, en `REAPER_FUSION_PRUEBAS.md` §18. Resumen de los 8 bugs de REAPER que solo
aparecieron con un modelo real (todos arreglados, 21 tests nuevos, 19 fallan con el código anterior):

1. Perfil `gratis` → modelo retirado (`dolphin…:free`). Ahora: catálogo real de OpenRouter + modelo fijo vigente.
2. `UNVERIFIED` mostrado en respuestas sin cambios.
3. 429 del pool gratis: reintentos inútiles al mismo modelo y JSON crudo. Ahora salto inmediato y mensaje legible.
4. **El plan ordenaba simular** (esqueletos/NotImplementedError/TODO) y metía tareas de "solo correr tests".
5. Modelos de razonamiento sin salida en pedidos cortos (juez ~350 tokens).
6. Tarea ya hecha por otra → falso "SIN PROGRESO: no terminó" → bucle de reparaciones → dependientes bloqueadas.
   **Es el mismo patrón del informe de script_whatsapp** ("tarea 1 fallida, 2-5 bloqueadas").
7. Meta-tarea con archivo fantasma: el reparador creó un archivo para "cumplir".
8. Tests de especificación que pasan sin código (no discriminan).

**A auditar:** (a) que el aviso de "tests que pasan sin código" no moleste en proyectos con código parcial; (b) que
`_RE_TAREA_SIMULADA` no marque tareas legítimas de tests ("mockear la red en los tests" no está en la regex, a
propósito); (c) el margen de razonamiento con modelos PAGOS (sube el tope a 2048 solo después de ver un corte).
Regresión 1044 tests OK en Python 3.11/3.12/3.13.

**Después:** bug #9 (tarea sin archivos → "SIN CAMBIOS" con todo funcionando) y bug #10 (el modelo manda solo los
argumentos JSON de `update_todo` y marca [x] archivos que no existen), ambos arreglados con test. Un proyecto más
grande (gestor de gastos, 622 líneas) terminó VERIFICADO, pero la prueba independiente encontró un error de lógica
que ningún test cubría (presupuesto mensual que suma otros meses): **a auditar** cómo hacer que el contrato del juez
y la especificación capturen restricciones semánticas implícitas ("mensual") sin inventar requisitos.

## 12. Revisión sin API (NO VERIFICADO con un modelo real)

Detalle en `REAPER_FUSION_PRUEBAS.md` §18.d. **Fallos de mis arreglos anteriores:** (1) el examen de realidad marcaba
como simulación 8 de 8 comentarios legítimos y bajaba builds sanas a PARCIAL; (2) `_IO_REAL` pisaba la de Test
Intelligence; (3) el sondeo de modelos gratis podía colgarse minutos. **Huecos de REAPER:** (4) en proyectos con
tests de Python y JS los de JS nunca corrían; (5) solo se reconocían `tests/*.test.*js`; (6) `<script>` sin
`type="module"` cargando un módulo y `onclick` a funciones de módulo (página rota con build verde); (7) el examen
de realidad no miraba JS; (8) `_LOCK_PROCESOS` unía dos locks. Test guardián nuevo: ningún global del bundle
puede definirse dos veces (salvo `_PARSERS`, que se extiende a propósito).

**A auditar:** (a) la lista de familias que el pedido puede habilitar (`ejemplo`, `simulacion`): un pedido que
dice "con datos de ejemplo" apaga la detección de "datos de ejemplo" en todo el proyecto; (b) la suite mixta usa
`;` y `$?` de shell (POSIX), revisar en Termux; (c) `scripts_html_incoherentes` sigue solo un nivel de imports.
Regresión 1060 tests OK en Python 3.10/3.11/3.12/3.13.

## 13. Proyectos grandes: `/grande` (NO VERIFICADO con un modelo real)

Detalle en `REAPER_FUSION_PRUEBAS.md` §19. `partes/76_grande.py`: plan maestro por etapas → un `/construir` completo
por etapa → si una etapa no queda verificada se retoma una vez y se frena (no se construye encima) → integración
final contra el pedido ORIGINAL. Estado en `.reaper/proyecto_grande.json`, `/grande continuar`, `--grande`.

Bug de `/construir` (existía antes) que destapó: al retomar, una tarea re-ejecutada quedaba VERIFICADA con su propio
test en rojo (la suite roja por la misma build se tomaba como "ya fallaba antes") y la build no se podía arreglar.
Ahora el diario guarda el estado inicial de la suite. También: la tarea agrupada al pasarse del tope perdía sus
dependencias.

**A auditar:** que `pedido_usuario` (lo que autoriza reescrituras y "datos de ejemplo") se use en todo lugar que
autoriza algo; `fallos_tolerables_al_reintentar` con suites que no nombran el archivo del test en el nombre.
Regresión 1075 tests OK en Python 3.10/3.11/3.12/3.13.

