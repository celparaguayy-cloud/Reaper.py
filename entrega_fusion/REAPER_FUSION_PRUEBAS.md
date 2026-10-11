# REAPER 8.10 fusionado — resultados exactos de las pruebas

Versión ACTUAL: `reaper_8.10_fusionado.py`, SHA-256 `0a5baa7f40afecd0747d03881f2cff6d6dcb1f2c60ad08141d1e5a2ab886ef63`
(incluye los arreglos de la sección 7). Las secciones 1–6 se corrieron sobre la versión anterior `abe85902…`; la
regresión completa de la versión actual está al final de la sección 7. Fecha: 2026-10-11.

**Entorno:** contenedor Linux x86_64 en la nube (no Termux, no Android). Python 3.11.15, 3.12.3 y 3.13.14.
Node 22, Java, Go, Perl 5.38 disponibles. **Sin claves de proveedores** (todas ausentes) y sin acceso al Termux del usuario.

Todos los logs están en `pruebas_fusion/resultados/`. Los comandos se pueden repetir tal cual.

## 1. Regresión completa sobre el código FINAL

```
python3.X reaper_8.10_fusionado.py --autotest
```

| Python | Tests | Resultado | Fallos | Errores | Omitidos | Duración | exit |
|---|---|---|---|---|---|---|---|
| 3.11.15 | 910 | OK | 0 | 0 | 0 | 77 s | 0 |
| 3.12.3 | 910 | OK | 0 | 0 | 0 | 71 s | 0 |
| 3.13.14 | 910 | OK | 0 | 0 | 0 | 73 s | 0 |

Composición: 882 tests tras la fusión (los 772 de la línea Claude + los de ChatGPT, incluidos sus 10 de round 12)
+ 28 nuevos de esta tanda (todos en `48zc_autotest_p0_fusion`). Los tests usan **MockLLM** (modelo
simulado) y transportes falsos para la red de modelos; los procesos, archivos, señales, HTTP local y SQLite son reales.

Evolución en la sesión (todas en 3.13 salvo la final): fusión inicial 882 con **3 fallos** (interacciones entre las dos
líneas; ver auditoría) → 882 OK → 901 OK (P0) → 908 OK (MercadoControl) → 910 OK (final, 3 versiones).

Estática: `ruff check` sin errores reales (F821/F811/F841/E9). Quedan avisos de estilo propios del bundle
(E741/E402/E702) y 2 imports ya sin uso (`ThreadPoolExecutor`, `as_completed`).

## 2. Reproducciones ANTES (ronda 12 de ChatGPT) / DESPUÉS (fusionado)

```
python3 pruebas_fusion/repros/correr_repros.py reaper_8.10.py reaper_8.10_fusionado.py
```

| Defecto | ANTES: `reaper_8.10.py` r12 | DESPUÉS: fusionado |
|---|---|---|
| XML mal cerrado `</replace_line>` | **se escribe dentro de `style.css`** | archivo intacto, llamada rechazada |
| Ctrl+C con 2 subagentes esperando un modelo de 30 s | sale a los **28,1 s** | sale a los **2,1 s** |
| Hijos tras Ctrl+C | **2 procesos vivos** | 0 |
| Suite externa que falla + `unittest.py` en el proyecto | gate **ok = True** | ok = False |
| Agente edita/borra `.reaper/acceptance.json` | **min_tests 10→1 y BORRADO** | intacto |
| Único test con `@skip` y código con bug | **"verificada"** | "fallida" |
| `.reaper/config.json` pide `modo: auto` sobre `confirmar` | **modo auto** | sigue confirmar |
| Hook `al_iniciar` de un repo clonado | **se ejecuta sin preguntar** | no se ejecuta |

## 3. MercadoControl

**Estado: NO VERIFICADO en el proyecto real.** El workspace `~/reaper-proyectos/mercadocontrol`, sus 10 criterios
originales y las claves no estaban en este entorno. El "1/10 histórico" **no se resolvió ni se reprodujo**: no tengo su
evaluador. Lo que sí se probó, con HTTP y SQLite reales y sin modelos:

Evaluador independiente (`pruebas_fusion/mercadocontrol/evaluador/`, 12 casos, contrato SUPUESTO y documentado:
`app.py`, `PORT`, `MERCADO_DB`, `/`, `/style.css`, `/script.js`, `/api/productos`):

```
python3 pruebas_fusion/mercadocontrol/correr_aceptacion.py reaper_8.10_fusionado.py
```

| Proyecto | Casos corridos | Pasan | Fallos | Errores | `--aceptacion` exit |
|---|---|---|---|---|---|
| vacío | 1 (+2 clases sin poder arrancar) | 0 | 1 | 2 | 2 |
| roto (reproduce `/` roto, MIME, lista vs objeto, `db_path`) | 12 | **0** | 5 | 7 | 2 |
| referencia (escrita por Claude, NO por REAPER) | 12 | **12** | 0 | 0 | 0 |

`/construir` de punta a punta con el gate activo (**modelo simulado**: MockLLM escribe los archivos; verificación,
servidor, SQLite y evaluador reales):

```
python3 pruebas_fusion/mercadocontrol/construir_con_mock.py reaper_8.10_fusionado.py
```

| App escrita por el "implementador" | Estado de la build | Aceptación |
|---|---|---|
| rota | **fallida** | 0/12 (no hay falso verde) |
| referencia | **verificada** | 12/12 |

Al montar esta prueba aparecieron tres defectos de REAPER que podían producir el patrón MercadoControl (validador de
recursos con raíz web incorrecta, tareas intermedias bloqueadas por assets planeados, "SIN CAMBIOS" con archivos ya
creados en la build); están arreglados y con test. Que expliquen el 1/10 real: **no verificado**.

## 4. CLI / Termux (simulado en Linux)

```
python3 pruebas_fusion/smoke_cli.py reaper_8.10_fusionado.py
```

Resultado: **145 comprobaciones OK, 0 fallas**, con HOME temporal y carpetas **con espacios**:
`--version`, `--help`, `--plantillas`, `--autotest-filtro` inexistente (exit 2) y válido, `--aceptacion` sin
manifiesto (exit 2), `--doctor` sin clave (exit 1, crítico: falta la clave), `-p` sin clave (error claro, sin colgarse),
`--nuevo` de las **68 plantillas** + sus **68 suites de tests ejecutadas de verdad** con el detector de REAPER (Python,
Node, Go, Java, C, Bash, Perl…), `--auditar-web`. Antes del arreglo, `perl-conversor` fallaba en rutas con espacios.

APK Android: la plantilla `android-java` se genera y sus tests de lógica corren; **no se compiló un APK** (no hay SDK
de Android ni Gradle con el SDK aquí).

## 5. Interrupción y bloqueos

- Ctrl+C real (SIGINT) durante llamadas lentas: 2,1 s en 3.11 y 3.13 (antes 27–28 s). Test `test_sigint_real_sale_en_plazo_acotado`.
- Cancelación con subproceso en curso: el hijo muere y el comando devuelve 130 en < 5 s.
- Vigía de tests: con `REAPER_AUTOTEST_ALERTA=1` nombró el test en curso y la línea donde estaba bloqueado.
- Plazos de pared: agente y build cortan al vencer, sin declarar éxito (`TestPlazosDePared`).

## 6. Lo que NO se pudo ejecutar (NO VERIFICADO)

| Prueba | Motivo |
|---|---|
| Proveedores reales (OpenRouter, Groq, Gemini, Venice, NVIDIA…) | no hay claves en el entorno. Solo se consultó el catálogo PÚBLICO de OpenRouter (sin clave): Nemotron 3 Ultra `:free` existe; **Dolphin Venice `:free` no figura (solo la versión paga)** |
| Construcción de MercadoControl con IA real | sin claves ni workspace del usuario |
| Termux/Android real, RAM en 2 GB, almacenamiento compartido | no hay dispositivo |
| Suite en el Termux del usuario | debe correrse allí: `python3 reaper_8.10_fusionado.py --autotest` |
| Apagón/kill a mitad de escritura del diario | no se hizo prueba de estrés de energía |

## 7. Primera corrida en el Termux REAL del usuario (aarch64, Python 3.14.6)

Archivo: `reaper_8.10_fusionado.py` SHA `abe85902…` (verificado por el usuario con `sha256sum`).
`--version` → `REAPER 8.10`. `--autotest`: **910 tests en 1324 s (22 min): 906 OK, 4 fallos, 6 omitidos** (los omitidos son
por herramientas ausentes en el teléfono). Diagnóstico de los 4 fallos:

| Test | Causa | Tipo | Arreglo |
|---|---|---|---|
| `TestFalsosVerdesFusion.test_tests_todos_omitidos_no_verifican` | en el teléfono hay **pytest**; su resumen `1 skipped in 0.01s` no se reconocía (solo se leían líneas con passed/failed/error), caía a "exit 0 = 1 pasó" | **falso verde real de REAPER** | el parser de pytest reconoce resúmenes de solo skipped/xfailed/deselected; reproducido y verificado con pytest 9.1.1 |
| `TestDeteccionLenguajes.test_plantilla_ruby_se_detecta_sin_config` | el paquete `ruby` de Termux no trae la gema **minitest** (`LoadError`) | entorno | requisitos `herramienta:librería` (`ruby:minitest`) comprobados cargando la librería; el test se omite diciendo `gem install minitest`; pista para el reparador |
| `TestPlantillas.test_todas_las_plantillas_pasan_sus_tests` (ruby-biblioteca) | ídem minitest | entorno | ídem |
| `TestEntregaArchivo.test_ruta_destino_cae_a_interna_sin_sdcard` | el test suponía que no existe `/sdcard`; en un teléfono real existe y la función elige bien el almacenamiento compartido | **test no hermético** | candidatas inyectables: se simula la ausencia y se agregó el caso positivo |

El vigía saltó en `test_todas_las_plantillas_pasan_sus_tests` (122 s en el teléfono): no era un cuelgue. En Termux
el umbral por defecto pasa a 180 s y el aviso aclara que el test sigue corriendo.

**Después de los arreglos** (mismo código para todos): 914 tests OK en Python 3.11.15 (67 s), 3.12.3 (70 s),
3.13.14 (75 s) y en **Python 3.14.0rc2 con pytest 9.1.1 instalado** (114 s; lo más parecido al teléfono que se pudo
reproducir aquí). La repetición en el Termux real queda a cargo del usuario.
