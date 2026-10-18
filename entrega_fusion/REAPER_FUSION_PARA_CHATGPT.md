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

**Después (§19.b de PRUEBAS):** repetir el mismo `--construir`/`--grande` retoma lo que quedó a medias; existen
`--construir continuar|estado` y `--grande continuar|estado`; al cortarse se imprime el comando exacto para seguir.
Regresión 1080 tests OK en Python 3.10/3.11/3.12/3.13.

## 14. Preparación para la prueba grande real (NO VERIFICADO con un modelo real)

Detalle en `REAPER_FUSION_PRUEBAS.md` §20. Cupo diario de OpenRouter (`es_cupo_diario`, `LLMClient.cupo_free_hasta`,
`LLMError.detiene_todo`), cuenta (`cuenta_openrouter`, `/doctor`), estimación y ahorro de pedidos en `/grande`,
esperas acotadas ante límites pasajeros, plan maestro tolerante a formatos y a respuestas cortadas, `/grande
deshacer`, `/reporte`, simulación del almacén en 5 etapas (API + web).

**A auditar:** (a) `_RE_LIMITE_PASAJERO` decide qué errores merecen esperar: un error de configuración con la palabra
"rate" esperaría en vano hasta 30 min; (b) la detección de cupo diario sin texto explícito usa `Remaining: 0` + reinicio
a más de 10 min; (c) la estimación de pedidos es gruesa (25–60 por etapa) y solo sirve para avisar.
Regresión 1099 tests OK en Python 3.10/3.11/3.12/3.13.

## 15. Prueba real en el teléfono y corridas de punta a punta (NO VERIFICADO con un modelo real)

Detalle en `REAPER_FUSION_PRUEBAS.md` §21. Banco nuevo `pruebas_fusion/e2e/` (OpenRouter falso por HTTP + la CLI real;
`REAPER_OPENROUTER_BASE` apunta catálogo y cuenta). Cambios: `mismo_pedido`, `_marcar_fase`/`_cerrar_fase` y la fase
`cierre` en `RegistroBuild.recuperable`, `REVISION_SIN_DICTAMEN`/`observaciones_concretas`, `faltantes_planeados`,
`spec_ajena` en `_verificar_tarea`, `_base_tests` en `especificar`, `ajustes_corrida` en el estado de `/grande`,
`_partir_para_caja`.

**A auditar:** (a) `recuperable` con la fase `cierre` acepta que cambien archivos de tareas verificadas si están en
los checkpoints de la build (lo hace el reparador) porque la verificación final se repite entera: ¿hay algún camino
que retome sin pasar por ella?; (b) `spec_ajena` atribuye tests a tareas por el nombre del archivo declarado: un test
de la especificación que ninguna tarea declara se tolera salvo en la última tarea; (c) `faltantes_planeados` confía en
que una ruta nombrada en el plan se va a crear: si ninguna tarea la crea, el cierre del agente y la verificación final
la siguen exigiendo.
Regresión 1128 tests OK en Python 3.10/3.11/3.12/3.13.

## 16. Segunda prueba real: test roto protegido y trampa del reparador (NO VERIFICADO con un modelo real)

Detalle en `REAPER_FUSION_PRUEBAS.md` §22. Cambios: `tests_de_especificacion_rotos`, `solo_agrega_imports`,
`Orquestador._custodiar_protegidos`, `trampas_para_tests` (validador `trampas`), `spec_propia` en `_verificar_tarea`,
`_spec_rotos`, salto de tareas ya cubiertas por la especificación, `_diff_alternativo`/`_contenido_en_bloque` en el
parser, `cargar_/guardar_razonamiento_aprendido`, `_repetidas_seguidas`, perfil gratis (roles y rpm 14).

**A auditar:** (a) `solo_agrega_imports` permite cualquier línea `import`/`from`: ¿un import con efectos (un módulo que
parchea el código bajo prueba) puede debilitar un test protegido?; (b) `trampas_para_tests` es por patrones: hay
otras formas de inyectar nombres (`globals()` de otro módulo vía `importlib`, `sys.modules[...].__dict__[...]`); (c)
`spec_propia` asume que el archivo de test declarado por una tarea es SUYO: si dos tareas lo comparten, solo la
última lo exige.
Regresión 1144 tests OK en Python 3.10/3.11/3.12/3.13.

## 17. Tercera prueba real: etapa 1 verificada; tests acoplados y reparador sin tiempo (NO VERIFICADO)

Detalle en `REAPER_FUSION_PRUEBAS.md` §23. Cambios: `acoples_a_la_implementacion` (aviso en `advertencias_tests_python`
y reescritura única en `especificar`), misión del especificador, `_RE_ANUNCIA_TESTS` en el bucle del agente, `try/except
LLMError` alrededor de `reparar` en `_reparar_con_escalada`.

**A auditar:** (a) `acoples_a_la_implementacion` solo mira mocks de la conexión y SQL literal: otros acoples (patch de
funciones internas del módulo bajo prueba) siguen pasando; (b) absorber el `LLMError` del reparador hace que una
build con TODOS los modelos caídos termine sus tareas como fallidas en vez de cortar: ¿conviene cortar si fallan dos
reparaciones seguidas por el modelo?
Regresión 1149 tests OK en Python 3.10/3.11/3.12/3.13.


## 18. Arreglo con tres subagentes y simulador de modelo gratis flojo (NO VERIFICADO con un modelo real)

Detalle y mediciones en `REAPER_FUSION_PRUEBAS.md` §24.

| Rama | Dónde está el cambio |
|---|---|
| `arreglo/capa-modelo` | `06_protocol.py` (formatos nativos y cortes), `20_agent.py` (rescates de acciones anunciadas, pasos devueltos) |
| `arreglo/modelos-gratis` | `05_llm.py` (límite por modelo, failover inmediato, plazo, corte de razonamiento), `70_equipo.py` (sondeo con herramienta, `salud_modelos.json`), `03_config.py` (perfil gratis) |
| `arreglo/pipeline` | `25_pipeline.py` (`_liberar_especificacion_mala`, `inutiles`, `diagnostico_obvio`, `fusionar_tareas_de_solo_tests`), `76_grande.py` (`normalizar_maestro`, `partir_etapa`, `_recuperar_etapa`), `22_tournament.py` |

Simulador: `pruebas_fusion/e2e/caos.sh` (`MOCK_CAOS`, `MOCK_SEMILLA`) y `MOCK_ACOPLADO` en `openrouter_falso.py`. Con caos
fuerte, el almacén de 5 etapas pasó de 2/3 a 3/3 terminadas, con 35 % menos pedidos. La tercera prueba real reproducida
pasó de etapa 2 FALLIDA a 5/5.

**A auditar:**
- (a) `_liberar_especificacion_mala` desprotege un test de la especificación si está roto o acoplado y participa del fallo: ¿puede un reparador aprovecharlo para debilitarlo? Hoy lo frena solo el examen de realidad (tautologías, tests sin assert).
- (b) La liberación se decide arriba del bucle de reparación, tras 2 intentos inútiles. Con `umbral_escalada=1` la tarea tiene 2 intentos y la liberación no llega a correr dentro de la tarea (sí en la reparación final).
- (c) `partir_etapa` no parte etapas con un solo archivo de código.
- (d) Los formatos nativos que entiende el parser amplían lo que se toma como llamada: revisar falsos positivos con JSON de datos en la respuesta.

Regresión 1210 tests OK en Python 3.10/3.11/3.12/3.13.

## 19. Ronda de caza 2: un test liberado no se puede vaciar (NO VERIFICADO con un modelo real)

Detalle en `REAPER_FUSION_PRUEBAS.md` §25. Responde a los puntos (a) y (b) del §18: `debilitamiento_de_test` y
`tests_que_verifican` (`15c`), `_marcar_spec_rotos` y `_tests_debilitados` (`25_pipeline`), el intento extra tras una
liberación tardía en `_reparar_con_escalada`, y tautologías del tipo `x or True`. Además, en `_con_reintentos`
(`05_llm`), la regla "2 respuestas vacías seguidas → otro modelo" ahora exige `hay_alternativa`: el último modelo del
equipo hace sus reintentos completos.

**A auditar:**
- (a) La guardia cuenta tests que verifican algo; un reparador todavía puede debilitar el CONTENIDO (cambiar un valor esperado por el que da el código). Eso no se detecta.
- (b) `_test_verifica` acepta cualquier método que empiece con `assert`, incluidos los mocks: un test que solo hace `m.assert_not_called()` cuenta como verificación.
- (c) El intento extra solo existe si se liberó algo; ¿conviene limitarlo al rol reparador de la tarea y no a la reparación final?

Regresión 1219 tests OK en Python 3.10/3.11/3.12/3.13.
