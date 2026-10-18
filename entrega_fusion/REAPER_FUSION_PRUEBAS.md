# REAPER 8.10 fusionado — resultados exactos de las pruebas

Versión ACTUAL: `reaper_8.10_fusionado.py`, SHA-256 en `REAPER_FUSION_SHA256.txt` (se recalcula en cada entrega).
Las secciones 1–6 se corrieron sobre la versión `abe85902…`; la sección 7 sobre `0a5baa7f…` (Termux real). Las
secciones 8–9 cubren lo agregado DESPUÉS de la fusión (interfaz, flujo de /construir, tres comandos nuevos, el
8.º agente juez y la robustez en trabajos chicos), con su propia regresión de 3 Pythons. Fecha: 2026-10-11.

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


## 8. Mejoras de UX posteriores a la fusión (misma sesión, acumulativo)

Sobre el código ya estabilizado se agregaron tres tandas de interfaz/ergonomía, con tests en cada una. Las ideas se
tomaron de free-claude-code (**solo las ideas**: implementación propia, no se copió código — es AGPL-3.0).

1. **Interfaz más legible** (917 tests): panel de arranque en caja con versión/modelo/equipo/ruta, prompt `❯`, íconos
   por herramienta, y ancho visible que cuenta bien los emojis (plano suplementario, ZWJ, selector de variación,
   modificadores de tono de piel) para que las cajas queden alineadas.
2. **Flujo visual de `/construir`** (920 tests): checklist del plan antes de implementar (con dependencias por tarea) y
   cierre en caja con insignia de estado (verificada/validada/parcial/cancelada/fallida) y resumen del diff.
3. **Tres comandos nuevos** (929 tests, esta tanda):
   - `/validar` sin argumentos (o `config`): revisa la config de modelos/equipo **sin tocar la red** — falta de
     credencial, proveedor retirado, independencia reducida, escalada sin clave. El modo viejo (validar archivos:
     `/validar archivo.py`, `/validar cambios`) se conserva: **un solo `/validar` con dos modos**.
   - `/modelo elegir` (selector interactivo del catálogo) y `/modelo buscar <texto>` (filtra por alias/id/nota/proveedor).
   - `/diagnostico [archivo]`: reporte para pegar al reportar un bug (versión, entorno, chequeos, config, qué
     proveedores tienen clave sí/no, ruteo del equipo, validación). Pasa por `redactar_secretos`: **nunca** incluye una clave.

Regresión de esta tanda (contenedor Linux x86_64, sin claves):

| Python | Tests | Resultado | Fallos | Errores | Omitidos | exit |
|---|---|---|---|---|---|---|
| 3.11.15 | 929 | OK | 0 | 0 | 0 | 0 |
| 3.12.3  | 929 | OK | 0 | 0 | 0 | 0 |
| 3.13.14 | 929 | OK | 0 | 0 | 0 | 0 |

Composición: 920 previos + 9 nuevos en `TestConfigValidarDiagnostico` (`48zc_autotest_p0_fusion`): la validación
detecta falta de clave y proveedor retirado; el diagnóstico redacta la clave sintética y trae lo esencial; `/validar`
y `/diagnostico` imprimen; el diagnóstico se guarda a archivo; **los dos modos de `/validar` no se pisan** (regresión
de una colisión de nombres que se corrigió: el validador de config tapaba al de archivos porque son métodos de la
misma clase — `ruff --select F811` no lo veía; ahora el config vive en `_validar_config` y el comando despacha según
el argumento); `buscar` filtra de verdad; el selector sin terminal no rompe y el interactivo sí asigna el modelo.

## 9. 8.º agente: el JUEZ DE ENTREGA + robustez en trabajos chicos

**Juez de entrega (rol `juez`).** Un 8.º agente, aparte de los 6 trabajadores, que corre al cerrar `/construir`.
Compara lo ENTREGADO contra el PEDIDO del usuario (objetivo + criterios + evidencia real: estado, tests,
validación, aceptación y diffstat) y responde un veredicto JSON corto `{cumple, faltantes, evidence_ids, confianza}`.

- **Solo endurece, nunca mejora.** Si con confianza media/alta dice que NO se cumple el pedido, baja la build de
  `verificada`/`validada` a `parcial` y lista los faltantes. NUNCA convierte una build roja en verde: el parser
  fuerza `cumple=false` si la evidencia muestra la build roja/parcial, aunque el modelo diga lo contrario. Así solo
  puede CAZAR falsos verdes, nunca crearlos.
- **Bajo costo.** Entrada compacta (diffstat, no el diff entero) y `max_tokens=400`: consume mucho menos que los
  roles que escriben o razonan (miles de tokens). Test `test_juez_consume_pocos_tokens` lo fija.
- **Siempre activo** (clásico y REAPER X); se apaga con `/equipo juez off`. Modelo propio ruteable: `/modelo juez <alias>`.
- Fuera de contrato o sin respuesta del modelo → NO cambia el estado (no inventamos ni éxito ni fracaso), solo deja nota.
- Visible en `/equipo` como "juez (8.º) · control final del pedido" y en el banner de arranque ("6 roles + juez").

Cobertura: `TestJuezDeEntrega` (12 tests) — parser (cumple / no cumple con faltantes / fuera de contrato /
confianza inválida normalizada / no puede subir una build roja) y gate (baja verde→parcial con alta confianza;
cumple no cambia; baja confianza no castiga; no toca una build fallida; apagado no gasta llamadas; fuera de
contrato no cambia estado; presupuesto de 400 tokens).

**Robustez en trabajos chicos.** `_es_testeable(archivos_plan, archivos_ws)` reemplaza la heurística vieja que, en
una carpeta vacía, forzaba "tests primero" SIEMPRE — incluso para una página estática. Ahora un plan que solo
produce assets estáticos (`.html`/`.css`) NO dispara la especificación ejecutable (escribir "tests" para una web
estática no aporta y trababa pedidos como "construí una web" en modelos flojos); la validación web igual corre. Si
hay lógica (`.py`/`.js`/`.ts`) en el plan o el proyecto, o si el proyecto está vacío y el plan aún no nombra
archivos, sigue habiendo tests primero. Cobertura: `TestTrabajosChicos` (3 tests).

## 10. El juez como MOTOR CENTRAL de /construir (bajo costo)

El juez pasó de "gate final" a motor central del build, pero sigue siendo el agente MÁS BARATO: hace lo más que
puede de forma DETERMINISTA (con la evidencia que ya existe) y solo gasta tokens del modelo en los juicios
semánticos que de verdad lo necesitan. En un build limpio son ~2 llamadas chicas (contrato + veredicto); gasta más
solo "si no, interviene".

1. **Dueño del contrato (1 llamada chica al inicio).** Antes de construir, el juez convierte el PEDIDO en criterios
   de aceptación concretos (`_contrato_de_entrega` → `parsear_criterios_entrega`, `max_tokens=350`). Ese contrato se
   guarda en el diario (se reusa al reanudar, sin otra llamada) y es contra lo que mide el veredicto final.
2. **Vigía por fase (determinista, 0 llamadas).** `cobertura_criterios()` marca, por solape de palabras/archivos,
   qué criterios el plan todavía no parece cubrir — señal temprana de desvío, no un veredicto.
3. **Veredicto final (1 llamada chica).** Como antes: juzga la entrega contra el contrato con la evidencia real;
   solo endurece (verde→parcial), nunca sube un rojo a verde.
4. **Cierra el trabajo (solo si falta algo).** Si el veredicto es NO CUMPLE con confianza media/alta y quedan
   intervenciones (`juez_max_intervenciones`, por defecto 1), el juez INTERVIENE: arma un diagnóstico con los
   faltantes, el reparador los implementa, se **re-verifica de verdad** (tests/validadores) y el juez vuelve a
   juzgar. Acotado (no entra en bucle) y honesto: si la verificación real no queda verde, la build no se declara
   cumplida. `_cerrar_con_juez` + `_debe_intervenir_juez`.
5. **Ruteo (determinista).** La intervención reusa el bucle de reparación con escalada ya existente (mejor modelo
   disponible / escala al fuerte); no se agrega otra decisión por modelo.

Cobertura nueva: `TestJuezContrato` (6) y `TestJuezCierra` (3): parser de criterios (dedup, tope 8, basura→[]),
cobertura determinista, contrato desde el pedido (apagado/basura no rompen), el gate usa el contrato, la lógica de
intervención (`_debe_intervenir_juez`: cumple / confianza baja / sin faltantes / cupo agotado / build roja / sin
juicio), un `/construir` completo donde el juez detecta un módulo faltante, interviene, el reparador lo agrega,
re-verifica y cierra en verde, y el caso cupo=0 (solo avisa, no interviene, queda parcial). Regresión: 953 tests OK
en Python 3.11.15 / 3.12.3 / 3.13.14.

## 11. Escala: proyectos grandes sin truncar el plan

El andamiaje para proyectos grandes ya existía (mapa de archivos relevantes por tarea, subagentes por tarea,
TaskGraph por dependencias, reanudación entre sesiones, compactación de contexto, el juez como contrato). El límite
artificial era el **techo de tareas**: estaba en 8 y, al pasarse, el resto se agrupaba en UNA tarea gigante
inimplementable — un proyecto grande se truncaba en silencio.

Cambios (el modelo lo elige el usuario; esto es lo que NO depende del modelo):
- `max_tareas` por defecto 8 → **12**, tope 30 → **60**: un proyecto mediano/grande se descompone de verdad; chico
  sigue usando pocas (es un máximo, no un objetivo).
- El arquitecto recibe guía explícita: usar tantas tareas como el proyecto necesite, **descomponer por módulo/capa**
  (una tarea por pieza coherente con sus `deps=`), sin meter medio proyecto en una tarea ni inventar relleno.
- Aviso visible si el plan supera el tope (agrupa el resto y sugiere `/config max_tareas N`), en vez de truncar callado.

Cobertura: `TestTrabajosChicos.test_plan_grande_no_se_trunca_con_el_tope_por_defecto`. Honesto: esto sube el TECHO
de escala; que un proyecto grande salga BIEN sigue dependiendo del modelo que se elija.

## 12. Construcción fiel al pedido (el juez gobierna, no hay simulación)

Partiendo de una corrida real donde REAPER **se desvió** (bumpeó la versión en vez de implementar el módulo
pedido) y dio "tests pasan" sin trabajo funcional, se cerraron los agujeros que dejaban pasar eso:

- **DESVÍO por tarea** (`_verificar_tarea`): si una tarea cambia archivos pero **ninguno de los que declaró**
  (p. ej. toca `__init__.py` cuando debía implementar `whatsapp.py`, que ya existía como esqueleto), la
  verificación falla y va a reparación con el error exacto. Que los declarados existan y que los tests pasen ya
  no alcanza: el trabajo tiene que estar en SUS archivos. Se suma a los gates que ya había (SIN CAMBIOS, ENTREGA
  INCOMPLETA, regresión, ✓ solo con tests reales).
- **El contrato del juez gobierna todo el build**: los criterios que el juez deriva del pedido pasan a ser los
  criterios de aceptación de TODO el build (los usan tests-primero, el checklist y la verificación), no solo el
  gate final. El equipo construye hacia lo que se pidió, no hacia lo que un rol interpretó.
- **El juez insiste "hasta que se haga"**: `juez_max_intervenciones` 1 → 2 (acotado; corta si una pasada no logra
  avances, para no quemar tokens ni entrar en bucle).

Cobertura: `test_desvio_tarea_toca_el_archivo_equivocado` (una tarea que toca el archivo equivocado no se da por
hecha; si toca el declarado, pasa). Regresión: 955 tests OK en Python 3.11/3.12/3.13.

**Honesto:** esto hace que REAPER **no cuente un desvío ni un no-op como éxito** y que el juez empuje hacia el
contrato. NO puede hacer que un modelo flojo (o que falla/timeoutea, como en aquella corrida) resuelva una tarea
que no sabe: ahí la build termina honesta en `parcial`/`fallida` con lo que falta, nunca en un verde falso.

## 13. Actualizaciones que no rompen lo anterior (y el juez lo vigila)

En una corrida real, una "tarea de actualización" tocó archivos que no le correspondían. Ahora, cuando REAPER
**actualiza** un proyecto que ya tenía trabajo, protege lo que existía ANTES de esa build:

- **Guardia por tarea** (`_verificar_tarea`, determinista, 0 tokens): sobre los archivos que ya existían antes de
  la build —
  - borrar uno que la tarea **no declaró** → `BORRÓ TRABAJO PREVIO`;
  - perder ≥3 líneas y ≥20 % del contenido de uno **no declarado** → `MODIFICÓ TRABAJO PREVIO`;
  - reescribir casi entero (≥8 líneas y ≥60 %) uno **declarado** → `REESCRITURA DESTRUCTIVA`.
  La tarea no se da por hecha y va a reparación con el mensaje exacto ("extendé sin perder lo que ya hacía").
  **Agregar** siempre está bien, las **ediciones chicas** (un import, una línea) pasan, y lo **creado en la misma
  build** no está protegido (las tareas se construyen unas sobre otras).
- **El juez lo ve** (`EV-PRESERVA`): en el veredicto final recibe un resumen determinista de qué pasó con lo
  previo (modificados / BORRADOS / REESCRITOS) y su misión ya dice que en una actualización lo que existía se
  conserva: si se borró o reescribió trabajo previo que el pedido no pedía cambiar, `cumple=false`.

Se suma a lo que ya protegía: los tests previos no se pueden editar, la regresión de tests frena la tarea y
`/deshacer` revierte toda la build. Cobertura: `TestPreservarTrabajoPrevio` (9). Regresión: 964 tests OK en
Python 3.11/3.12/3.13.

## 14. El juez arma el equipo según la necesidad, y el proyecto tiene que ARRANCAR

**El juez elige quién hace cada rol** (`asignar_equipo_juez`, determinista, 0 tokens). Antes de cada `/construir`:
- **ningún rol queda en un modelo caído**: descarta los que no tienen clave, están retirados o vienen fallando
  (disyuntor abierto) y los reemplaza por el mejor modelo **sano** del equipo — justo lo que tiró abajo la corrida
  de `mi_script` (modelos que daban error/timeout o no eran compatibles con el endpoint);
- para cada rol elige el de **mejor historial en ese rol** (memoria de desempeño);
- en los roles **críticos** (planificar, implementar, reparar, integrar) prefiere un modelo `fuerte` si el
  historial no dice lo contrario; los livianos (QA, explorador) no gastan de más;
- si el configurado está sano y nadie es claramente mejor, **lo respeta**;
- el modelo de **escalada** queda reservado para cuando una tarea se traba.
La asignación vale **solo para esa build**: tu configuración queda intacta. `/equipo juez` muestra de antemano cómo
armaría el equipo y por qué.

**Verificación de arranque** (`verificar_arranque`): que los tests pasen no prueba que la app arranque. En la
verificación final REAPER detecta el punto de entrada (`python -m paquete`, también en `src/`, o un script CLI con
argparse/click/sys.argv) y lo corre con `--help`, stdin vacío y plazo corto. Si se cae al **cargar**
(ModuleNotFoundError, ImportError, SyntaxError…) la build **no queda verificada** y el reparador recibe el
traceback real. Un timeout (servidor, programa interactivo) o un "no reconozco --help" **no** cuentan como roto.
Caso real: en `mi_script` los tests pasaban y `python -m mi_script` daba `No module named mi_script.__main__`.
Se apaga con `verificar_arranque=false`.

Cobertura: `TestJuezArmaEquipo` (7) y `TestArranqueReal` (7).

## 15. El juez: el que más hace y el que menos gasta (examen de realidad)

El juez ahora resuelve lo máximo posible **sin llamar al modelo** y solo usa tokens para el juicio de sentido que
de verdad lo necesita. Lo nuevo:

- **Examen de realidad** (`examen_de_realidad`, AST, 0 tokens) sobre lo que cambió en la build:
  - funciones que el plan pidió (`def nombre` en la interfaz o las tareas) y quedaron **vacías** (`pass`, `...`,
    solo docstring), y cualquier **`raise NotImplementedError`** fuera de métodos abstractos;
  - **tests que no prueban nada**: tautologías (`assert True`, `x == x`), sin ningún assert, que mockean justo lo
    que deberían probar o que esperan el valor que inyectó el propio mock (reusa el analizador de calidad de tests).
  No marca cuerpos vacíos legítimos: métodos abstractos, sobrecargas, Protocols, `__init__`/`__exit__` vacíos ni
  hooks que el plan no pidió.
- **Veredicto determinista**: si el examen encuentra algo, el juez decide `NO CUMPLE` **sin llamar al modelo**
  (marcado "determinista, 0 tokens") y su bucle de intervención manda al reparador a implementarlo de verdad, re-
  verifica y vuelve a juzgar. Solo si todo es real consulta al modelo, y le pasa `EV-REAL` como evidencia.
- **Cuenta de tokens del juez**: el cierre de cada build muestra cuánto gastó el juez y qué % de la build fue
  (`⚖ juez: ~N tokens (X% de la build)`, o `0 tokens · decidió con evidencia local`).

Cobertura: `TestJuezRealidad` (9), incluida una build de punta a punta donde el implementador deja vacía la función
pedida: el juez lo detecta gratis, interviene, queda implementada y el juez gasta menos que la build.

## 16. Reparación con una corrida real fallida (script_whatsapp, Termux)

Método: primero **reproducir** cada fallo con el código anterior, después arreglar y dejar el test de regresión.
Reproducciones (scripts fuera del repo, contra `reaper_v8.py`):

```text
$ python3 repro_diagnostico.py .      # antes del arreglo
primera línea de app.py: REAPER 8.10 · diagnóstico
py_compile exit: 1
["SyntaxError: invalid character '·' (U+00B7)"]
$ python3 repro_diagnostico.py .      # después
primera línea de app.py: def main():
py_compile exit: 0

$ python3 repro_senal9.py .           # antes: solo "exit code: -9", sin pista
$ python3 repro_senal9.py .           # después
estado: SIGKILL (señal 9): el sistema MATÓ el proceso. En Android casi siempre es falta de memoria; …
PISTAS DE REAPER: - El sistema mató el proceso (señal 9). …

$ python3 repro_reemplazo.py .        # pedido: "Reescribí app.py desde cero…" — antes
estado: parcial | fallidas: ['1']
VERIF: REESCRITURA DESTRUCTIVA: borró 23 de 24 líneas (96%) que ya había en app.py …   (×4, nunca en pantalla)
$ python3 repro_reemplazo.py .        # después
estado: validada | fallidas: []
```

Tests nuevos (`partes/48zf_autotest_build_real.py`, filtro `REAPER_AUTOTEST=buildreal`): 15. Contra el código
anterior: `Ran 15 tests … FAILED (failures=11, errors=4)` (fallan los 15); con el arreglo, 15 OK. Doctor (`TestDoctor`): +3.

Regresión completa: **1005 tests OK** en Python 3.11, 3.12 y 3.13. `pruebas_fusion/smoke_cli.py`: 0 fallas.
Lint (`ruff --select F,E9,B`): sin hallazgos nuevos (los 62 existentes son anteriores a esta ronda).
NO VERIFICADO con modelos reales ni en el teléfono: la prueba en Termux queda para el usuario.

## 17. El examen de realidad ahora caza simulaciones, no solo funciones vacías

Antes el examen determinista (0 tokens) marcaba funciones vacías (`pass`/`...`), `NotImplementedError` y tests sin
valor. Pero una simulación típica NO está vacía: devuelve datos inventados con cara de reales. Caso real
(`script_whatsapp`): `get_free_number()` devolvía `"+1555" + random`, y `fetch_sms()` una lista fija. Eso pasaba
el examen. Ahora se agregan dos detecciones, también sin llamar al modelo:

- **DATOS FABRICADOS** (`fabricaciones_en_codigo`, AST): una función que el plan pidió para **traer datos reales**
  (su contexto en el plan dice scrapear, descargar, consultar, API, web, SMS, número…) pero que los **inventa** con
  `random`/`uuid`/`secrets` y no hace ninguna llamada de IO (`httpx`, `requests`, `urllib`, `socket`, `open`,
  `sqlite3`…). Es exactamente el patrón `+1555`. No se marca `random` legítimo (una sumadora) ni cuando sí hay una
  llamada de red real de la que salen los datos.
- **SIMULACIÓN CONFESADA** (`admisiones_de_simulacion`, tokenize): comentarios o textos que admiten ser
  provisionales/ficticios, con frases inequívocas: "en una implementación real…", "en producción usaríamos…",
  "número/datos de ejemplo", "datos simulados/ficticios", "TODO/falta implementar", "hardcode", "esto es una
  simulación". No marca prosa normal ("suma los dos", "conexión real establecida").

Cuando el examen encuentra cualquiera de estos, el juez decide **NO CUMPLE** sin gastar tokens y su bucle manda a
implementarlo de verdad, re-verifica y vuelve a juzgar. Tests: `TestJuezRealidad` (+5: número fabricado, random
legítimo no se marca, con red real no se marca, confesión en código, y el detector de admisiones aislado).

Regresión: **1010 tests OK** en Python 3.11/3.12/3.13. Smoke CLI: 0 fallas. Lint sin hallazgos nuevos.
NO VERIFICADO con modelos reales: medir falsos positivos con builds reales queda para el uso en el teléfono.

## 18. Primera prueba con un modelo REAL (OpenRouter, solo modelos `:free`)

Hasta acá todo se probaba con MockLLM. Con una clave de OpenRouter del usuario se corrieron builds reales de
`/construir` usando **solo modelos gratis** (gasto de la cuenta: USD 6,94519608 antes y después → **$0**).
La clave vivió solo en una carpeta temporal fuera del repo (nunca en el repo ni en commits) y se borró del disco al terminar las pruebas.

Configuración aislada (`REAPER_HOME` temporal): principal `nvidia/nemotron-3-super-120b-a12b:free`, juez
`poolside/laguna-xs-2.1:free`, respaldos `cohere/north-mini-code:free`, `poolside/laguna-*`, `google/gemma-4-31b-it:free`,
tope de costo 0,01. Pedido: conversor de temperaturas (paquete, CLI `python -m conversor 100 C F`, tests).

Estado del pool gratis ese día (sondeo directo, pedido mínimo): solo nemotron-3-super respondía bien; laguna-s,
gemma-4 → 429 "rate-limited upstream"; nemotron-ultra → 503; inkling → 403 "only available on agentic harnesses";
`openrouter/free` → ruteó a un modelo de 2,6B que devolvió vacío.

| # | Bug encontrado en la corrida real | Evidencia | Arreglo |
|---|---|---|---|
| 1 | El perfil `gratis` apuntaba a `dolphin…:free`, **que ya no existe**; el modelo y el "fuerte" por defecto son pagos | catálogo: `dolphin…:free` NO EXISTE | Elige del **catálogo real** (público, $0, caché 12 h); sin red, un modelo fijo que existe. 403 "only available on…" se retira como 404 |
| 2 | "verificación: UNVERIFIED" en una respuesta sin archivos ("Respondé OK") | salida real | No se muestra si no hubo cambios |
| 3 | 429 del pool gratis: 4 reintentos (~35 s) al MISMO modelo, JSON crudo cortado | log build 1 | Mensaje legible; con alternativa, salto inmediato |
| 4 | El **plan ordenaba simular**: "esqueletos que lanzan NotImplementedError", "`__main__` que imprima TODO"; y tareas de "solo correr los tests" | plan build 2 | El arquitecto lo prohíbe; el juez (0 tokens) hace replanificar; las meta-tareas se quitan |
| 5 | Modelo de razonamiento sin salida (`finish=length`) con los pedidos cortos del juez (~350 tokens) | log build 2 | Con alternativa se cambia y desde ahí los pedidos cortos llevan margen + razonamiento corto; sin alternativa, 1 reintento ampliado |
| 6 | Tarea cuyo trabajo ya hizo otra: "SIN PROGRESO: **no terminó**" (falso: terminó, 7 tests pasaban) → 3 reparaciones sin nada que arreglar → fallida y dependientes BLOQUEADAS | log build 2 | "Terminó sin cambios" pasa si la verificación real lo confirma (en vivo, build 3: tareas 2, 3 y 4 pasaron así) |
| 7 | Meta-tarea con archivo fantasma `correr_tests`: el reparador **creó un archivo** para "cumplir" | build 3 | Detección de meta-tareas ampliada ("Ejecutar el conjunto de pruebas…") |
| 8 | Tests de la especificación que **pasan sin que exista el código** ("el CLI falla" pasa si el módulo no existe) | build 3: 3 pasaban antes de implementar | En proyecto nuevo, el especificador los ajusta una vez |
| 9 | Hueco funcional que nadie probó: el CLI acepta `F K` pero falla ("Unsupported conversion") | prueba independiente | No es de orquestación: es calidad del modelo; queda documentado |

Verificación independiente del código generado en la build 3 (fuera de REAPER): `python -m conversor 100 C F` →
`212.0`; `32 F C` → `0.0`; `0 C K` → `273.15`; `-300 C F` → error por stderr y exit 1; 15 tests OK. **Es código
real**, no simulado. Hueco: F↔K no implementado (punto 9).

**Build 4 (con los arreglos):** el juez detectó el plan con problemas y lo hizo replanificar EN VIVO, y la especificación salió sin tests vacíos (0 pasaron, 2 con error). También mostró dos fallos de mi propio arreglo, ya corregidos: «todo» ("verificar que todo funciona") se tomaba como el marcador TODO, y una meta-tarea escrita como viñeta ("- ejecutar las pruebas…") no se detectaba.

**Resultados de cierre:**

| Build | Código de REAPER | Resultado | Tiempo | Tokens (gratis) | Juez |
|---|---|---|---|---|---|
| 3 | con arreglos 2, 3, 6 (sin el de meta-tareas) | **✓ VERIFICADA** · 15/15 validadores · 15 tests | 18m01s | ~757k | CUMPLE (high), ~3,6k tokens = 0,5 % |
| 4 | con todos los arreglos salvo viñetas y #10 | ◐ PARCIAL: todo funciona (13 tests), pero falló la tarea "- ejecutar las pruebas…" | 9m54s | menor | ~0,8k tokens = 0,1 % |

La build 3 es la **primera build completa de REAPER con un modelo real**. El informe guardó versión, contrato y veredicto
del juez. Buena parte de los ~757k tokens se fue en la meta-tarea (3 reparaciones + 2 rondas de revisión).

**Bug #10 (build 4):** una tarea **sin archivos declarados** que termina limpia con la suite verde fallaba por "SIN
CAMBIOS" (3 reparaciones inútiles → PARCIAL con todo andando; en la build 3 el reparador creó un archivo para
"cumplir"). Ahora no falla si la suite pasa; la juzgan la verificación final y el juez. Si la suite falla, sigue fallando.

**Build 5 — proyecto más grande (gestor de gastos: modelos, SQLite, servicio con presupuestos, CSV, CLI con 6
subcomandos):** **✓ VERIFICADA** en 17m28s · 11 archivos · 622 líneas · 33/33 validadores · 26 tests · juez CUMPLE
(high) con ~2,2k tokens (0,2 %). Plan sano: 5 tareas de código real, sin esqueletos ni meta-tareas.

Prueba independiente del programa generado (fuera de REAPER, base temporal): `agregar`, `listar`, `resumen 2026-10`
(2050,00 correcto), `exportar` (CSV solo del mes, encabezado correcto), alertas de 80 % y 100 % y validaciones de
monto/fecha **funcionan**. Pero tiene fallos que **ni los tests ni el juez detectaron** (calidad del modelo):
- **`presupuesto` mezcla meses**: con 850 gastados en octubre y 99 en septiembre informó 949 (el pedido decía
  presupuesto *mensual*). Ningún test cubría gastos de dos meses.
- `listar` no muestra los IDs, así que `borrar --id` no se puede usar en la práctica.
- Los errores de validación salen como traceback en vez de un mensaje limpio.

Conclusión honesta: **"verificada" = pasa los tests que existen y el contrato que derivó el juez**; no garantiza
cada detalle semántico. Cuanto más explícito el pedido ("el presupuesto cuenta solo los gastos de ese mes"), más lo
cubren el contrato y los tests.

**Bug #11 (build 5):** el implementador mandó 3 veces `{"items": ["[x] Implementar … gastos/modelos.py", …]}` (los
argumentos de `update_todo`, sin el nombre) **sin haber creado el archivo** → "sin herramientas" → tarea fallida de
entrada (la verificación real lo detectó: "falta gastos/modelos.py"). Arreglo: se infiere la herramienta si UNA ÚNICA
tiene esas claves (ambiguos y `attempt_completion` nunca), y `update_todo` denuncia ítems [x] sobre archivos que no
existen. (La build 5 corrió con el código anterior a este arreglo.)

Seguridad: la clave **no aparece** en ningún log, informe ni proyecto generado (redacción de secretos OK con modelo
real). Gasto total de todas las pruebas: **$0**. La clave se borró del disco al terminar.

Tests: `partes/48zg_autotest_openrouter_real.py` (27). Contra el código anterior: 19 fallan; los 2 que pasan
son guardas de "no excederse" (en proyecto existente no se toca; no se reintenta infinito).
Regresión: **1037 tests OK** en Python 3.11/3.12/3.13. Smoke CLI: 0 fallas. Lint sin hallazgos nuevos.

### 18.b Análisis de los logs reales (sin nuevas llamadas al modelo)

Se reprodujeron offline las respuestas REALES que los modelos dieron en las builds 2–5:

| Hallazgo en los logs | Evidencia | Arreglo |
|---|---|---|
| Mi arreglo #11 (JSON sin nombre) también habría tomado como `update_todo` **listados de archivos inventados** (`{"items": [{"type": "file", "path": …}]}`) | 6 de 18 JSON con `items` eran objetos alucinados | Solo se infiere con valores planos (texto/número/lista de textos). Re-ejecutado sobre los 38 JSON reales: 12 listas de tareas → `update_todo`, 6 listados inventados → nada, 2 `list_files` inequívocos → sí |
| El revisor (solo lectura) pidió `execute_command` **15 veces** (hasta 6 seguidas) y el especificador 2 | conteo por rol en los logs | El revisor recibe el resultado real de los tests que ya corrió REAPER; al rol de solo lectura que pide ejecutar se le explica eso, y al que tiene `run_tests` se le indica usarla |
| "✗ no completó **(completado)**" | 2 veces | "⚠ terminó, pero su cierre no quedó respaldado por evidencia" (afirmación sin evidencia o archivos que no validan) |

Tests: +5 (todos fallan con el código anterior). Regresión: **1042 tests OK** en Python 3.11/3.12/3.13.

### 18.c Lanzador de pruebas reales y perfil gratis que prueba los modelos

- `pruebas_fusion/prueba_real.py`: corre `/construir` sobre tres proyectos reales (un juego en el navegador, una
  página web con backend en Python y un script organizador de archivos) **sin ayudar al modelo**, con las mismas
  garantías de la prueba anterior: clave solo por entorno (y borrada del disco al terminar), solo modelos gratis
  que RESPONDEN, tope de costo, gasto antes/después y búsqueda de la clave en todo lo generado.
- Al armarlo apareció otro problema de mi arreglo del perfil gratis: el catálogo real ponía `inkling` e
  `inkling-small` como respaldo y como juez, y en la prueba real daban 403. Ahora `/perfil gratis` (con clave)
  **prueba cada candidato** con un pedido mínimo ($0) y se queda solo con los que responden; además avisa si algún
  rol sigue en un modelo de OpenRouter que puede ser pago.

Tests: +2 (fallan con el código anterior). Regresión: **1044 tests OK** en Python 3.11/3.12/3.13.

### 18.d Revisión sin API: huecos que habrían dado verdes falsos en el juego, la web y el script

La clave no estaba disponible en esta sesión: **nada de esta sección se corrió contra un modelo real** (NO
VERIFICADO con la API). Lo que sigue se encontró revisando el código con los tres pedidos de
`pruebas_fusion/prueba_real.py` en mente y se probó con casos reales de `node`/`python`, no con un navegador.

**Fallos en mis propios arreglos anteriores (3):**

| Fallo | Evidencia | Arreglo |
|---|---|---|
| El examen de realidad marcaba como "simulación confesada" **8 de 8 comentarios legítimos** ("No hardcodear la ruta", "Simulación de la gravedad en cada frame", "In production you should set DEBUG to False", "Por ahora usamos SQLite", "datos de ejemplo" pedidos por el usuario…) y eso bajaba a PARCIAL builds sanas | prueba directa con los 8 comentarios | Solo frases inequívocas; ignora las negadas ("Evitamos valores hardcodeados") y lo que el **pedido** pide a propósito ("3 recetas de ejemplo", "--simular"), mirando el pedido y nunca el plan. Medido con código real: 7 coincidencias en 637 archivos de la stdlib de Python (se quitó "dummy value", un centinela legítimo; "not implemented yet" de urllib es una confesión de verdad) y **0 en 1223 archivos JS** de npm |
| `_IO_REAL` del examen de realidad **pisaba** la lista homónima de Test Intelligence (todo es un solo archivo) | análisis del AST del bundle | Renombrada; test guardián que prohíbe globales duplicados |
| `free_que_responden` (sondeo de `/perfil gratis` y de `prueba_real.py`) podía quedarse **minutos** con un `:free` saturado: sin alternativa, reintentaba con Retry-After | lectura de `_con_reintentos` | `chat(..., reintentos=0)` en los sondeos, sin tocar la configuración del usuario |

En esta misma ronda, la suite atrapó **antes del commit** otro choque de nombres mío (`_RE_NEGACION` nueva pisaba
la de `afirma_verificacion`: 2 tests rojos). De ahí salió el test guardián.

**Huecos de REAPER (5):**

| Hueco | Qué pasaba | Arreglo |
|---|---|---|
| Proyecto con tests de Python **y** de JS | Solo corría la suite de Python: los tests de JS **nunca se ejecutaban** y la build podía salir verde con ellos fallando | Corren las dos, se suman los conteos y sale con el primer código de error |
| Nombres de tests JS | Solo `tests/*.test.*js` del primer nivel: `juego.spec.mjs`, `test_juego.mjs`, subcarpetas o `*.test.mjs` en la raíz no corrían | Se reconocen los nombres que acepta `node --test` (sin `node_modules`) |
| Errores que solo aparecen en el navegador | `<script src="juego.js">` sin `type="module"` con `export` adentro (SyntaxError) y `onclick="reiniciar()"` con `reiniciar` dentro de un módulo (ReferenceError): node --test pasa, la página no anda | Error de validación `scripts-html` con la línea y el arreglo. Las 12 plantillas web propias no se marcan |
| Examen de realidad ciego a JS | Funciones del plan vacías, tests sin asserts o con `assert.ok(true)`, y comentarios "por ahora devolvemos datos fijos" solo se miraban en Python | Mismo examen para JS/TS/HTML. Ningún test JS de las plantillas se marca |
| `_LOCK_PROCESOS` | Dos locks distintos (procesos de validación y procesos en segundo plano) eran el mismo objeto | Renombrado |

Tests: +16. Medido contra el código anterior: 12 fallan por el bug que cubren, 2 son guardas de precisión sobre
las plantillas (fallan porque la función no existía) y 2 son guardas de no-regresión que ya pasaban. Regresión: **1060 tests OK** en Python
3.10/3.11/3.12/3.13. Lint (pyflakes/ruff, errores reales): sin hallazgos.

## 19. Proyectos grandes por etapas (`/grande`) y un bug de `/construir continuar` que destapó

**Pedido del usuario:** "que sea capaz de crear proyectos grandes". Antes, un `/construir` metía todo en UN plan de
hasta `max_tareas` (12; máx. 60) y un plazo de pared de 90 min; lo que sobraba se amontonaba en la última tarea.

**Qué se agregó (`partes/76_grande.py`):** plan maestro (visión, arquitectura, etapas con archivos/interfaz/
criterios/dependencias) validado sin tokens (formato, ciclos, dependencias inexistentes, etapas que planean
simular o que solo corren pruebas, tope `max_etapas`); una build completa por etapa en orden de dependencias;
reintento único retomando la MISMA build; parada si una etapa no queda verificada (nada se construye encima);
estado en `.reaper/proyecto_grande.json` y `/grande continuar`; integración final (verificación real de todo el
proyecto desde el primer checkpoint + juez contra el pedido ORIGINAL + una build de integración acotada si falta
algo); informe `.reaper/informes/proyecto_grande_*.md`. Comando `/grande`, flag `--grande`, capítulo del manual y
proyecto "grande" en `pruebas_fusion/prueba_real.py`.

**Garantía nueva:** el pedido de cada etapa lo arma REAPER con texto que escribió el modelo. Lo que AUTORIZA
(reescribir archivos previos, aceptar "datos de ejemplo") sale de `Orquestador.pedido_usuario`, nunca de ese texto.

**Cómo se probó (NO VERIFICADO con un modelo real):** un modelo simulado que escribe código de verdad construye un
gestor de biblioteca en 3 etapas (SQLite → préstamos → CLI); los tests del proyecto corren de verdad en cada etapa.
También por la CLI real (`main(["--grande", ...])`): exit 0, 5 tests del proyecto en verde y la app generada
funciona (`python -m biblioteca agregar/prestar/listar`, rechaza prestar dos veces).

**Bugs que encontró la simulación:**

| Bug | Dónde | Evidencia | Arreglo |
|---|---|---|---|
| Al retomar una build, la suite roja **por esa misma build** se tomaba como "ya fallaba antes de empezar": la tarea re-ejecutada quedaba **VERIFICADA con su propio test en rojo**, cada `/construir continuar` la "conservaba" y la build no se podía arreglar nunca (ni con el modelo ya corregido) | `/construir` (existía antes) | Mismo escenario, código anterior: 2.ª corrida "verificada", 3.ª con el modelo corregido "fallida"; código nuevo: "fallida" y luego "verificada" | El diario guarda `base_fallaba` y `fallaban_al_inicio` al empezar; al re-ejecutar una tarea fallida o cortada solo se toleran los fallos previos a la build y los de tests declarados por OTRAS tareas |
| El estado de `/grande` quedaba JSON inválido | mío (nuevo) | `redactar_secretos` sobre el JSON serializado cambiaba `"tokens": 63043` por `[REDACTADO]` | Se redactan los textos, no el JSON; campo renombrado |
| Plan con más tareas que el tope: la tarea agrupada **perdía sus dependencias** y podía correr aunque fallara una de la que dependía | `/construir` (existía antes) | test directo | Conserva las dependencias externas al grupo |
| "Datos de ejemplo" que el usuario **pidió** hacía replanificar | `/construir` | test directo | `problemas_del_plan` mira el pedido |
| El test guardián de globales contaba `App.cmd_x = …` como redefinición de `App` | mío (ronda anterior) | falso positivo | Solo cuenta nombres y tuplas |

Tests: +15 (de `/grande` y de la reanudación; el de reanudación falla con el código anterior). Regresión:
**1075 tests OK** en Python 3.10/3.11/3.12/3.13. Lint (pyflakes/ruff, errores reales): sin hallazgos.

**A auditar:** (a) con modelos gratis, una etapa puede quedar a medias por límites de uso: `/grande continuar` la
retoma, pero cada etapa gasta lo de una build entera; (b) la integración usa el juez con un diffstat de TODO el
proyecto: en proyectos muy grandes conviene revisar que el contrato no quede genérico; (c) `MAX_INTENTOS_ETAPA = 4`.

### 19.b Seguir después de un corte

El usuario reportó que la corrida "se cortó" (en el teléfono: Termux cerrado, pantalla bloqueada o límite del
modelo gratis). Lo natural es repetir el mismo comando, y REAPER respondía "ya hay una build incompleta" (o, con
`/grande`, "ya hay un proyecto grande sin terminar"): había que saber el subcomando. Ahora:

- repetir el MISMO `--construir "..."` o `--grande "..."` (mismo pedido, ignorando espacios) **retoma** donde quedó,
  sin replanificar; un pedido distinto no pisa lo que quedó a medias y dice el comando exacto para seguirlo;
- `--construir continuar|estado` y `--grande continuar|estado` desde la terminal (antes `--construir estado`
  intentaba construir un proyecto llamado "estado");
- al cortarse con Ctrl+C o por un error del modelo se imprime el comando exacto para seguir;
- el comando para seguir se imprime FUERA del cuadro de cierre: adentro se recortaba al ancho de la terminal y no
  se podía copiar entero (lo encontró el autotest).

Tests: +5 (los 5 fallan con el código anterior). Regresión: **1080 tests OK** en Python 3.10/3.11/3.12/3.13.

## 20. Preparación para la prueba grande con modelos gratis reales (NO VERIFICADO con un modelo real)

**Límites reales verificados en la documentación de OpenRouter** (docs/api-reference/limits): modelos `:free` con
20 pedidos por minuto y **50 por día si nunca se compraron créditos** (1000 por día con al menos 10 de crédito); al
pasarse, HTTP 429 con `X-RateLimit-*`; `GET /api/v1/key` informa `is_free_tier` y `free_model_daily_requests`
(used/limit/remaining). Un `/grande` de 5 etapas necesita, según la estimación de REAPER, ~135–325 pedidos sin
torneo: **con 50 por día no termina en un día**; con 1000 sí.

| Problema que habría aparecido en la prueba real | Arreglo |
|---|---|
| Un 429 de cupo DIARIO se reintentaba como pasajero y se probaban los otros `:free` (comparten el cupo): minutos perdidos y el mensaje no decía qué pasaba | Se detecta (texto "per-day" o `Remaining: 0` con reinicio lejano): no se reintenta, se saltean los `:free`, se usa otro proveedor del equipo si hay, mientras dure se falla al instante sin red, y el mensaje dice a qué hora se renueva |
| Las fases "opcionales" (juez, explorador, forense, torneo, escritor largo) se tragaban el error y seguían | `LLMError.detiene_todo` (presupuesto o cupo): se propaga y la build queda guardada para retomar |
| Nada avisaba ANTES que el cupo no alcanzaba | `/doctor` y `/grande` consultan la cuenta (no gasta cupo): estimación de pedidos y aviso; con 50/día, `/grande` corre sin torneo ni revisor (solo esa corrida) |
| Un corte por límite o Ctrl+C contaba como intento fallido de la etapa (a los 4, bloqueada) | Solo cuentan las builds que terminaron |
| Ante "todos los modelos en enfriamiento" `/grande` se detenía | Espera sola 2, 5 y 10 min (tope `espera_limites_min`, 30 por defecto) y sigue; si el cupo diario se renueva dentro del tope, espera hasta la renovación |
| `--perfil gratis` desde la terminal no sondeaba qué `:free` responden (solo `/perfil gratis`) | Sondea con memoria de 6 h por catálogo (cada sondeo es un pedido del cupo) |
| Plan maestro de un modelo real con `<stage>`/`<objective>`, `deps="ninguna"`, `deps="E1"` o `"etapa 2"` | Se aceptan; la respuesta cortada (etapa abierta sin cerrar o `finish_reason=length`) se detecta (antes la última etapa se perdía en silencio) y se replanifica |

**Simulación realista nueva (modelo simulado, código real):** almacén en 5 etapas — SQLite, ventas con control de
stock (todo o nada), reportes y CSV, API HTTP real (`http.server`, tests con servidor en un puerto libre) y web con
módulos ES + tests de node. Termina VERIFICADO con 12 tests reales (9 Python + 3 node). Variante "modelo flojo":
`<script src="app.js">` sin `type="module"` → la validación lo detecta (SyntaxError en el navegador) y el reparador
lo corrige.

**Bug que encontró la simulación:** una etapa que "de paso" borra una función de una etapa anterior deja lo
verificado ROTO en el disco (la preservación no salta con un borrado chico) y el cierre no lo decía. Ahora, al
detenerse, REAPER corre los tests y nombra qué tests de etapas verificadas rompió; `/grande deshacer` vuelve al
último estado verificado (revierte la etapa, descarta su build) y `/grande continuar` la rehace. Probado de punta a
punta. También: el veredicto CUMPLE del juez salía con ⚠ en el cierre.

**Para el ciclo de mejora:** `/reporte` y `--reporte` arman un ZIP sin claves (informes, estado, logs, árbol y
código; nunca .env, .clave*, *.key, id_rsa). `prueba_real.py`: cupo antes/después, `--continuar <carpeta>` para
retomar una corrida cortada y un ZIP por proyecto.

Tests: +19. Regresión: **1099 tests OK** en Python 3.10/3.11/3.12/3.13. Lint (pyflakes/ruff): sin hallazgos.

## 21. Primera prueba REAL de `/grande` (teléfono) y corridas de punta a punta contra un OpenRouter simulado

### 21.a Lo que mostró el teléfono (Termux, Python 3.14.6, modelos `:free`, versión `9c9f2a06`)

La corrida se cortó en la etapa 1 de un plan de 10. Lo que se vio, ya corregido en rondas anteriores (1099 → 1113
tests): el proyecto nuevo terminaba en "No existe ~/almacen" (ahora `--construir`/`--grande` crean la carpeta); el plan
maestro no tenía etapa para la web, partía el proyecto en 10 etapas de un archivo y acusaba "datos de ejemplo" por un
reporte (observaciones suaves en vez de rechazo); `cohere/north-mini-code:free` pensaba ~25 000 caracteres sin
responder en cada pedido (razonamiento por modelo: `low` → `none` → se deja); el juez apuntaba a un ID de nanogpt que
ya no existe (se retira al primer 400 "not a valid model"); el especificador entraba en bucle porque "No module named
'almacen'" le parecía un error (es lo esperado en tests primero; ahora se lo dicen la herramienta y `run_tests`).

### 21.b Corridas de punta a punta (`pruebas_fusion/e2e/`)

Un OpenRouter FALSO por HTTP (`openrouter_falso.py`: chat con SSE, `/models`, `/key`, cupo diario con
`X-RateLimit-*`, 429 por minuto, modelos que solo razonan, implementador flojo) y la **CLI real** apuntada a él con
`REAPER_API_URL` + `REAPER_OPENROUTER_BASE` (nuevo). El cerebro es el almacén de 5 etapas del autotest, extendido al
pipeline real del perfil gratis: tests primero, torneo de 2, revisor, juez. `correr_script.sh` corre el script del
teléfono (`probar_grande.sh`) entero sin red: descarga con SHA-256 desde un servidor local, instala, doctor, `/grande`,
`--reporte`.

| Escenario | Antes | Ahora |
|---|---|---|
| Normal | verificado, 112 pedidos, 6m19s | verificado, 78 pedidos (−30 %), 4m19s |
| Cupo diario agotado a los 40 pedidos (etapa 4, en "tests primero") | `continuar` → "Cambios externos o tareas ya verificadas alteradas": **la etapa no se podía retomar nunca más** | se detiene con la hora de renovación; `continuar` con el cupo agotado gasta 1 pedido y frena; "al otro día" termina verificado sin rehacer nada |
| Ctrl+C a los 20, 37, 53, 71, 89 s… y `continuar` cada vez | — | retoma en todos los puntos y termina verificado |
| Modelo que solo razona + 429 por minuto cada 7 pedidos | — | baja el razonamiento, reintenta con `Retry-After` y termina verificado |
| Implementador flojo (vende sin stock) | la tarea quedaba "verificada" con su propio test en rojo; lo atajaba recién la reparación final | la verificación de la tarea lo detecta y el reparador lo corrige antes de revisar |

**Bugs de lógica (8), todos con test que falla con el código anterior:**
1. Desde la etapa 2 de `/grande`, los tests de etapas anteriores (que ya pasan) se contaban como "tests de la
   especificación que YA pasan sin el código": el especificador tenía que reescribir tests buenos. Se resta la base.
2. Una revisión sin la línea VEREDICTO mandaba al implementador "corregí" sin nada que corregir (28 de 112 pedidos).
   Sin dictamen ni puntos concretos, no hay ronda; con puntos concretos ("1. falta validar…"), se pasan.
3. Un test de JS que importa `../web/logica.js` antes de que exista se rechazaba (el "ImportError" de JS no era rojo
   esperado; `es_archivo_de_test` ni reconocía `tests/*.test.mjs`); `run_tests` no lo explicaba.
4. `web/index.html` escrito antes que `app.js`/`style.css` salía "VALIDACIÓN FALLÓ (corregilo antes de seguir)": un
   modelo real podía "arreglarlo" sacando el `<script>`. Si lo que falta está en el plan, es trabajo pendiente.
5. **Cortada en una FASE** (tests primero, QA, verificación final o reparación), la build no se podía retomar: el
   diario solo aceptaba cambios de una *tarea* activa. Las fases quedan anotadas igual que una tarea.
6. Los diarios se guardan redactados: un pedido con "password: admin123" no se reconocía al retomar (y `/grande`
   quedaba trabado). `mismo_pedido` compara también la forma redactada.
7. Al retomar la fase de tests, el especificador encontraba su test hecho, no lo reescribía, y se descartaba la
   especificación. Cuentan los tests que la misma build ya había escrito.
8. La verificación de una tarea toleraba TODO el rojo de la especificación (incluido el de la propia tarea y el de
   la última): solo se tolera el de las tareas siguientes; romper tests de etapas anteriores es regresión.

Por revisión del código: el cupo diario también puede llegar como evento de error **dentro** del stream (HTTP 200);
antes se reintentaba como pasajero.

**Mensajes (10):** la caja recortaba justo "Se renueva mañana a las…" (ahora parte las líneas); "pruebo con
nemotron…:free" cuando el cupo gratis ya estaba agotado; el comando para seguir no llevaba `--perfil gratis` (podía
caer en un modelo pago); "✗ Ningún candidato produjo cambios" con el trabajo ya hecho; un "⚠" vacío antes de
"Interrumpido"; en el script, el doctor sin `--perfil gratis` no mostraba el cupo, el cierre decía "cupo del día, un
límite o una etapa" sin decir cuál (ahora el motivo real, y Ctrl+C aparte), el reporte mostraba el modelo de la
config y no el de la corrida (ahora guarda `ajustes_corrida`) y un motivo viejo en un proyecto terminado; la fila del
cupo del doctor se cortaba antes de "quedan".

Tests: +15 (`48zl_autotest_e2e.py`). Regresión: **1128 tests OK** en Python 3.10/3.11/3.12/3.13.

**NO VERIFICADO con un modelo real:** el OpenRouter falso responde lo que el guion dice; los modelos reales fallan de
formas que el guion no imita. La próxima prueba en el teléfono es la que cuenta.

## 22. Segunda prueba REAL de `/grande` (teléfono, versión `8ace580a`): un test roto protegido y una trampa

La etapa 1 (esqueleto: `__main__.py`, `server.py`, `tests/test_cli.py`) estuvo ~2 horas en reparaciones. Lo que pasó,
en orden (salida del teléfono, Termux, modelos `:free`):

1. El especificador escribió `tests/test_cli.py` con `from almacen import __main__` y llamó `main([...])` **sin
   importarlo** (NameError). Además perdió 4 escrituras por poner el código en ``` sin `<content>`.
2. REAPER solo rechazaba errores de sintaxis en la especificación: **protegió el test roto**.
3. El arquitecto había planeado "Escribir la prueba unitaria" como tarea 2; la especificación ya la había escrito y
   protegido → los implementadores no podían tocarla → SIN PROGRESO → 2 reparaciones y modo forense sin nada que hacer.
4. Como nadie podía corregir el test, el reparador **hizo trampa**: `sys._getframe(1).f_globals['main'] = main` en
   `almacen/__main__.py` (y variantes con `setattr` sobre `sys.modules`). El test "pasó"; solo lo frenó el validador de
   nombres indefinidos sobre el test. También pisó el test con `cp tests/test_cli.py.backup …` por la terminal.
5. Implementadores que repetían la misma lectura hasta 60 veces; `<search>`/`<replace>` dentro de `replace_in_file` que
   se leía como una herramienta `search_files` fantasma; cada modelo volvía a "pensar 25 000 caracteres sin responder"
   en cada corrida; el juez le dio el reparador a un `:free` que no había respondido el sondeo; 429 de cohere
   ("limitado a 15 por minuto") con el perfil gratis a 16.

| Arreglo | Dónde |
|---|---|
| Un test de la especificación con **nombres sin importar** (o sintaxis) es un test roto: se le pide corregirlo al especificador; si sigue roto, **no se protege** (lo puede corregir el implementador) y su tarea igual tiene que dejarlo en verde | `tests_de_especificacion_rotos`, `especificar`, `_spec_rotos` |
| A un test protegido se le pueden **agregar imports** (y nada más); el reparador lo sabe cuando el fallo está ahí | `solo_agrega_imports`, `_escribir`, `reparar` |
| **Custodio** de los tests protegidos en disco: imports agregados → se aceptan y se actualiza el diario; cualquier otro cambio (incluso por la terminal) → se revierte | `_custodiar_protegidos` |
| **Trampas para los tests**: escribir en `f_globals`/`f_locals`, agregar a `builtins`, `setattr(sys.modules[…])` o tomar el marco de quien importa y agregarle atributos → falla de validación con la explicación | `trampas_para_tests`, validador `trampas` |
| La **especificación propia** de una tarea tiene que quedar en verde (antes, al fallar ya antes de la tarea, no contaba; con pytest los nombres no cambian) y se valida en la tarea | `spec_propia` en `_verificar_tarea` |
| Tarea cuyos archivos son solo tests que ya escribió la especificación: no corre implementadores | bucle de tareas |
| Parser: código en ``` sin `<content>`, `<código>`, `<search>/<replace>` (y `<old>/<new>`…) y bloques SEARCH/REPLACE sin `<diff>`; un `<search>` dentro de un `replace_in_file` sin cerrar ya no es otra herramienta | `_contenido_en_bloque`, `_diff_alternativo` |
| El nivel de razonamiento aprendido de cada modelo se **recuerda 24 h** entre corridas | `cargar_/guardar_razonamiento_aprendido` |
| 8 llamadas repetidas bloqueadas seguidas cortan al agente (antes hasta 60) | `_repetidas_seguidas` |
| El perfil gratis saca de los roles los `:free` que hoy no respondieron, y baja a 14 pedidos por minuto | `aplicar_perfil` |

**De punta a punta** (OpenRouter simulado, `MOCK_TEST_ROTO=1`: especificador que escribe `tests/test_db.py` usando `db`
sin importarlo y no lo corrige): no se protege, la verificación de la tarea dice `F821 Undefined name 'db'`, el
reparador agrega el import en la tarea y el proyecto termina verificado. El escenario normal sigue en 78 pedidos.

Tests: +16 (`48zm_autotest_prueba_real2.py`), todos fallan con el código anterior. Regresión: **1144 tests OK** en
Python 3.10/3.11/3.12/3.13. **NO VERIFICADO con un modelo real.**

## 23. Tercera prueba REAL de `/grande` (teléfono, versión `75b97061`): etapa 1 verificada, la 2 se detuvo

Primera vez que una etapa quedó **verificada con modelos reales** (1/6). La etapa 2 (ventas) se detuvo por tres cosas:

| Lo que pasó | Arreglo |
|---|---|
| La especificación mockeaba la conexión del propio proyecto (`patch("almacen.sales.get_connection")`) y exigía el SQL exacto (`"SELECT stock FROM products WHERE id = ?"`). El implementador reusó `db.get_product` (razonable), el mock dejó de aplicar y `validate_stock` daba `False`; el reparador intentó cambiar el test y la guardia de regresión lo revirtió | `acoples_a_la_implementacion`: aviso al escribir el test y, si la especificación los trae, UN pedido al especificador para reescribirlos con una base sqlite real; la misión del especificador lo pide desde el principio (comportamiento por la interfaz, sin mockear la base ni afirmar SQL) |
| El reparador escribió 3 veces "Ahora, ejecutemos los tests" sin llamar `run_tests` → cerrado "sin herramientas" | Si un agente (no el principal) anuncia que corre los tests y no lo hace, REAPER los corre y le muestra el resultado (hasta 2 veces por agente) |
| Se agotó el tiempo de la tarea en medio de un reintento (Nvidia 500) y el error subió como "el modelo no responde": **/grande se detuvo entero** | Un error del modelo en el reparador termina ESA reparación (la tarea queda con sus fallos, la build sigue y /grande retoma la etapa con tiempo nuevo); el presupuesto y el cupo diario siguen frenando todo |

Tests: +5 (`48zn_autotest_prueba_real3.py`), todos fallan con el código anterior. Regresión: **1149 tests OK** en
Python 3.10/3.11/3.12/3.13. **NO VERIFICADO con un modelo real.**


## 24. Arreglo con tres subagentes y simulador de modelo gratis flojo (NO VERIFICADO con un modelo real)

Tres subagentes en ramas aisladas, cada uno con su parte y sus tests (cada test nuevo falla con el código anterior,
salvo guardas que deben pasar en ambas versiones). Los junté y medí antes y después con el mismo banco.

| Rama | Qué arregla |
|---|---|
| `arreglo/capa-modelo` (22 tests, `48zo`) | Entiende las llamadas como las escriben los modelos gratis: `<tool_call>{json}` (Hermes/Qwen/Nemotron), `[TOOL_CALLS]` (Mistral), `function` de OpenAI, listas JSON en ```` ```json ```` y `<function=x><parameter=y>`. Las respuestas cortadas por longitud quedan como incompletas con lo parcial, en vez de escribir medio archivo como entero. "Voy a leer X" lo lee REAPER; "listo, terminé" con cambios intenta el cierre. Los pasos que solo tuvieron errores de formato o vinieron vacíos se devuelven (hasta 3). Mensajes correctores con el ejemplo correcto |
| `arreglo/modelos-gratis` (17 tests, `48zp`) | El sondeo pide una llamada de herramienta real y ordena los modelos por herramientas, después texto, después latencia. La salud de los modelos se guarda 24 h, así la próxima corrida empieza por el que anduvo. Respeta el límite por modelo que viene en el 429 ("limited to 15 requests per minute"). Un `:free` inestable cede de inmediato al siguiente. No arranca una espera que no entra en el plazo. Corta el razonamiento desbocado (16 000 caracteres sin respuesta). El juez no elige modelos caídos. Perfil gratis sin torneo (2 candidatos duplicaban pedidos y cupo), 2400 s por tarea y 7200 s por build |
| `arreglo/pipeline` (17 + 5 tests, `48zq`) | La especificación nunca bloquea: un test acoplado que sigue acoplado tras pedir la reescritura no se protege, y un test de la especificación roto o acoplado que traba la reparación se libera una vez (igual tiene que quedar en verde). La reparación corta tras 2 intentos inútiles, y cada intento ve el diff del anterior. No usa el modo forense ante errores obvios. Las tareas de solo tests que van antes de su código se unen con esa tarea. Un plan maestro fragmentado se agrupa. Una etapa FALLIDA se deshace y se parte en dos, una sola vez |

Después de juntarlas agregué tres arreglos (+5 tests):
- Una etapa que llegó al tope de intentos se parte sola. Antes quedaba DETENIDA con "partila o corregila a mano", y no hay comando para partirla.
- `/grande deshacer` reinicia los intentos de la etapa. Antes, `continuar` la volvía a frenar por los intentos viejos.
- Un diario de build roto o de otra carpeta ya no se informa como "el modelo no responde": dice qué pasó y cómo seguir.

**Simulador de modelo gratis flojo** (`pruebas_fusion/e2e/caos.sh`, `MOCK_CAOS`). Es la CLI real contra el OpenRouter
simulado por HTTP, con las fallas vistas en el teléfono:
- cohere piensa sin responder y tiene un límite de 15 pedidos por minuto;
- Nvidia devuelve 500, respuestas vacías y "Upstream idle timeout";
- herramientas mal escritas (`<contenido>`, código sin `<content>`, `<tool_call>{json}`, `<function=…>`, basura, duplicadas);
- acciones anunciadas sin hacerlas;
- el juez a veces no devuelve JSON.

Con la misma semilla, la secuencia de fallas es la misma. El pedido es el almacén de 5 etapas de `probar_grande.sh`.

| Escenario | Antes (`2edcb50`) | Después |
|---|---|---|
| Caos fuerte (nivel 2), semillas 1–3 | 2/3 terminadas: 119, 128 y 95 pedidos. La semilla 3 se detuvo en la etapa 5: el especificador escribió `<tool_call>{json}` (no se entendía), después anunció dos veces sin hacer nada y el reparador no escribió el test que faltaba | **3/3 terminadas**: 74, 86 y 71 pedidos (−35 %) |
| Caos moderado (nivel 1), semillas 1–3 | 3/3: 99, 95 y 90 pedidos | (medición en curso; se completa en la próxima entrega) |
| Tercera prueba real (`MOCK_ACOPLADO=1`): el especificador escribe `tests/test_ventas.py` acoplado (mockea la conexión y exige el SQL exacto) y no lo corrige aunque se lo pidan | **Etapa 2 FALLIDA, 1/5**, igual que en el teléfono | **5/5 terminadas**, 64 pedidos: no lo protege, falla y el reparador lo reescribe con sqlite real |
| El proyecto trabado por la versión vieja + `--grande continuar` con la nueva (lo que tiene que hacer el usuario) | — | **5/5 terminadas**, 52 pedidos. Dos intentos chocan con el test protegido, REAPER lo libera y el tercero lo reescribe |
| Normal / test roto (`MOCK_TEST_ROTO`) / implementador flojo (`MOCK_FLOJO`) | 78 pedidos (normal) | 59 / 66 / 63 pedidos, todos terminados |

**Lo que el simulador NO prueba:** si un modelo real sigue escribiendo tests acoplados de otra forma (patch de funciones
internas, no de la conexión), si un test liberado se debilita (lo frena solo el examen de realidad que ya existía) y
cuánto tarda un modelo real. **NO VERIFICADO con un modelo real.**

Regresión: **1210 tests OK** en Python 3.10/3.11/3.12/3.13.
