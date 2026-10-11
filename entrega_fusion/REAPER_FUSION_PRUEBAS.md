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
