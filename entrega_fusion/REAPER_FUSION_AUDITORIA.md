# REAPER 8.10 — Auditoría de la fusión ChatGPT (ronda 12) + Claude Code

Fecha: 2026-10-11. Rama: `ccr-6e025352-3tb6n4`. Archivo final: `reaper_8.10_fusionado.py`
(SHA-256 en `REAPER_FUSION_SHA256.txt`). Estado global: **PARCIAL** (ver "Pendiente" y "No verificado").

## 1. Qué se fusionó y cómo

| Línea | Origen | Identificación |
|---|---|---|
| Base común | commit `02a41bf` (REAPER X experimental) | detectado comparando los 125 módulos: 93/125 idénticos al 8.10 |
| ChatGPT | `reaper_8.10.py` ronda 12 | SHA-256 `19453f67…da89c` (coincide con su `REAPER_RONDA12_SHA256.txt`) |
| Claude | última entrega al usuario, commit `2e487e4` | caza de bugs de secretos / pérdida de datos / CYBER-20 |

Método: el `reaper_8.10.py` de ChatGPT se partió en sus 126 módulos (mismo empaquetador) y se hizo un merge de
3 vías por módulo con `git merge-file`. **No se sobrescribió nada a ciegas.** Respaldo previo: `git bundle` +
copia del archivo + tag `pre-fusion-810`.

Resultado del merge: 83 módulos idénticos, 22 solo cambiados por ChatGPT (se tomaron), 10 solo cambiados por
Claude (se conservaron), 5 fusiones limpias, 5 con conflicto resuelto a mano, 1 módulo nuevo de ChatGPT
(`43d_autotest_autonomia810`). No disponía del Termux del usuario: **no se pudo comparar con la copia instalada
allí**; la base del usuario se tomó como la última entrega (pedido explícito: "Fusiona con el último que me diste").

### Conflictos y cómo se resolvieron

| Archivo | Conflicto | Resolución |
|---|---|---|
| `08_workspace` | patrones de secretos distintos | se conservan los de Claude (más proveedores) + sufijo tras la palabra clave y `credential` de ChatGPT |
| `25_pipeline` | protección de tests previos (Claude) vs diario reanudable (ChatGPT) | ambas: los hashes de los tests protegidos quedan en el diario y una reanudación los exige intactos |
| `35_cli` | redacción de la sesión guardada | ambas defensas: por mensaje (Claude) y del JSON serializado (ChatGPT) |
| `48z` | tests nuevos de ambos lados | se conservan las dos clases |
| `49_runner` | filtro de autotest vacío → exit 2 (ambos lo habían hecho) | mensaje a stderr (ChatGPT) + clases disponibles (Claude) |

### Interacciones que aparecieron al fusionar (las detectó la suite)

| Defecto | Causa | Arreglo |
|---|---|---|
| Redactor dejaba JSON roto `"KEY": [REDACTADO]"` | el patrón de Claude se comía la comilla de apertura | la comilla queda en el grupo conservado (test de ChatGPT `test_redactor_json_con_claves_entrecomilladas`) |
| "no recolectó ningún test" desaparecía | ChatGPT aceptaba exit 5 solo de pytest; unittest ≥ 3.12 también usa 5 | se acepta 5 de pytest y unittest, siempre con evidencia textual |
| `ALIAS_MODELOS_HEREDADOS` mandaba `groq-gptoss120` a un Nemotron de OpenRouter y el alias "ultra" a "super" | supuesto de ChatGPT sin verificación | **catálogo público de OpenRouter consultado el 2026-10-11**: `nemotron-3-ultra-550b-a55b:free` existe. Se vació el mapa (era además inalcanzable) y el test se ajustó con esa evidencia |

## 2. Tabla de defectos

Estados: **CONFIRMADO** (reproducido) · **ARREGLADO** (con test que fallaba antes) · **PARCIAL** · **PENDIENTE** ·
**NO REPRODUCIDO** · **NO VERIFICADO** (requiere claves, el dispositivo o el proyecto real del usuario).

### P0

| ID | Defecto | Evidencia | Causa raíz | Estado | Test |
|---|---|---|---|---|---|
| P0-1 | Reparador ~2 h en MercadoControl | sin logs ni modelo real aquí | los bucles estaban acotados en intentos pero **no había plazo de pared**: torneo × pasos × reparaciones × forense con modelos lentos alcanza horas | **ARREGLADO** el mecanismo (plazo por tarea 25 min, por build 90 min; corta tras 2 reparaciones sin cambios; no espera reintentos con el plazo vencido). El caso real: **NO REPRODUCIDO** | `TestPlazosDePared` |
| P0-2 | Reparar `/style.css` y `/script.js` rompió `/` (1/10) | reproducido con app "rota" → 0/12 | (a) `recursos-html` resolvía `/x` contra la raíz del proyecto y no contra la raíz web servida (falso "no existe") y la pista empujaba a mover assets o tocar el ruteo; (b) una tarea intermedia fallaba si su HTML enlazaba CSS/JS de tareas posteriores y bloqueaba esas tareas; (c) "SIN CAMBIOS" fallaba tareas cuyos archivos ya había creado una tarea anterior | **ARREGLADO** (a, b, c). Que fueran LA causa del 1/10 real: **NO VERIFICADO** | `TestRecursosHtmlRaizWeb`, `TestTareasIntermediasWeb`, `TestGateWebDePuntaAPunta` |
| P0-3 | XML de herramienta mal cerrado (`</replace_lines>`) | **CONFIRMADO**: `</replace_line>` quedaba escrito dentro de `style.css` y la herramienta decía ✓ | una llamada final sin cierres se aceptaba y el contenido llegaba hasta el fin del mensaje | **ARREGLADO**: se rechaza sin tocar el archivo; solo se revisan parámetros sin su cierre propio (sin falsos positivos con `</Context>`/`</html>`) | `TestXmlMalformadoNoMuta` |
| P0-4 | Ctrl+C colgado en `_python_exit`/`t.join()` | **CONFIRMADO**: SIGINT real → salida a los **27,1 s** (modelo de 30 s) | `ThreadPoolExecutor` hace join al salir | **ARREGLADO**: hilos daemon con espera interrumpible y gracia acotada → **2,1 s** (3.11 y 3.13) | `TestCtrlCNoCuelga` (incluye SIGINT real) |
| P0-4b | Procesos hijos huérfanos tras Ctrl+C | **CONFIRMADO**: `sleep` seguía vivo | `start_new_session=True` aísla al hijo del Ctrl+C del terminal y no había manejo | **ARREGLADO**: registro de hijos, kill del grupo al cancelar/salir (atexit), espera por tramos | `test_cancelar_mata_el_subproceso_en_curso` |
| P0-5a | Gate de aceptación suplantable | **CONFIRMADO**: suite que falla + `unittest.py` en el proyecto → `ok=True` ("Ran 50 tests OK") | `python -m unittest` con cwd en el proyecto pone el proyecto primero en `sys.path`; el conteo se leía con regex del texto | **ARREGLADO**: runner de confianza con `python -I -B`, conteo desde los objetos de unittest con marca aleatoria por stdin | `TestFalsosVerdesFusion` |
| P0-5b | Auxiliares de la suite externa no entraban en la huella | revisión de código | solo se hasheaban `test_*.py` | **ARREGLADO** (huella V2 de toda la suite; diarios V1 de la ronda 12 se migran) | `test_auxiliar_de_la_suite_editado_rompe_la_huella` |
| P0-5c | El agente podía editar/borrar `.reaper/acceptance.json` | **CONFIRMADO** (bajó `min_tests` 10→1 y lo borró) | sin protección de escritura | **ARREGLADO**: archivo de control fuera del alcance de las herramientas (también el diario de la build) | `test_agente_no_puede_editar_ni_borrar_el_manifiesto` |
| P0-5d | Tests todos omitidos daban "verificada" | **CONFIRMADO** | exit 0 con 0 ejecutados | **ARREGLADO** | `test_tests_todos_omitidos_no_verifican` |
| P0-6 | Batería multiplataforma atascada | **NO REPRODUCIDO** (aquí la suite tarda 60–80 s en 3.11/3.12/3.13) | — | **PARCIAL**: vigía que, si un test pasa de `REAPER_AUTOTEST_ALERTA` s, dice cuál es y vuelca la pila de todos los hilos; resumen de los más lentos. No mata tests ni sube timeouts | probado con alerta de 1 s |

### P1

| Defecto | Estado | Nota |
|---|---|---|
| MercadoControl real (`db_path`, JSON lista vs objeto, MIME, `/`, CRUD, persistencia) | **NO VERIFICADO** en el proyecto real | evaluador independiente de 12 casos + app rota (0/12) + app de referencia (12/12); ver `REAPER_FUSION_PRUEBAS.md` |
| Plan colapsado a 1/1 (NebulaDB) | **CONFIRMADO que funciona** | en la prueba de punta a punta un plan de 1 tarea con 4 archivos se dividió en 4 tareas |
| Confirmaciones prematuras (0 tests, solo skipped, exit ≠ 0) | **ARREGLADO** lo encontrado | 0 tests con unittest 3.12+, todo omitido |
| JSON de supervisores (`raw_decode`, límites, APPROVE sin evidencia) | **CONFIRMADO preservado** | tests de dictámenes de ChatGPT pasan |
| Reanudación y diario | **PARCIAL** | diario de ChatGPT + hashes de tests protegidos + migración de huella; no se probó apagón/kill a mitad de escritura |
| `EOFError`/stdin/tareas interactivas | **PENDIENTE** (no auditado a fondo) | se conserva el test de `/pegar` con EOF de ChatGPT |

### P2

| Defecto | Estado | Nota |
|---|---|---|
| Proyecto podía pasar el modo de `confirmar` a `auto` y reactivar hooks | **CONFIRMADO → ARREGLADO** | un `.reaper/config.json` ajeno solo puede endurecer |
| Hooks `al_iniciar` / `despues_de_build` sin consentimiento | **CONFIRMADO → ARREGLADO** | abrir un repo clonado ejecutaba su hook (marcador `PWNED`) |
| Secretos en logs/sesiones/informes | **ARREGLADO** lo encontrado | además de la caza previa (fugas entre proveedores, subprocesos, logs) |
| Plantilla `perl-conversor` en carpeta con espacios | **CONFIRMADO → ARREGLADO** | ruta sin comillas en el test |
| Proveedores reales | **NO VERIFICADO** | no hay claves en este entorno. Catálogo público de OpenRouter: Dolphin Venice `:free` **no figura** (solo la versión paga); si da 404 REAPER lo retira y usa el respaldo |
| Multiagente (roles independientes, colas, selección por salud/costo) | **PENDIENTE** | solo se cambió la ejecución en hilos |
| RAM/CPU en Android 2 GB | **NO VERIFICADO** | no hay dispositivo; la salida de subprocesos ya está acotada en disco |

## 3. Riesgos residuales

- Los tests del evaluador que **importen** código del proyecto dentro del mismo proceso pueden ser manipulados por ese
  código; el evaluador recomendado lanza el servidor como subproceso (como el de MercadoControl).
- El agente con `execute_command` aprobado puede tocar archivos fuera de sus herramientas (p. ej. `rm`); la huella
  fijada al iniciar la build detecta cambios en la suite y el manifiesto durante la build, no entre builds.
- Los plazos por defecto (25/90 min) pueden cortar builds grandes con modelos lentos: `/config tiempo_max_build 0` los
  desactiva (no recomendado).
- El contrato HTTP del evaluador de MercadoControl es SUPUESTO; si la app real usa otras rutas hay que ajustar el
  evaluador, nunca la app para que pase.
