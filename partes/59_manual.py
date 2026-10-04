"""
Manual integrado: /manual muestra el índice, /manual <tema> un capítulo (también acepta parte del nombre).
Escrito para usar REAPER en Termux con un modelo de 24B (Venice): qué pedir, cómo, y qué hacer cuando algo falla.
"""

MANUAL: dict[str, tuple[str, str]] = {}


def capitulo(clave: str, titulo: str, texto: str) -> None:
    MANUAL[clave] = (titulo, textwrap.dedent(texto).strip())


capitulo("inicio", "Primeros pasos", """
    # Primeros pasos

    ## Instalar en Termux
    ```bash
    pkg update && pkg install python git nodejs     # git y node son opcionales pero recomendados
    pip install httpx pyflakes                      # opcionales: httpx (red más estable), pyflakes (validación)
    export OPENROUTER_API_KEY="tu_clave"            # ponelo en ~/.bashrc para no repetirlo
    python3 reaper_v7.py --instalar                 # crea el comando `reaper`
    ```

    ## Primer uso
    ```bash
    cd ~/mi_proyecto && reaper                      # abre REAPER en esa carpeta
    reaper -p "agregá tests a utils.py"             # un pedido y sale
    reaper --construir "API de notas con SQLite" --auto
    reaper --autotest                               # verifica REAPER sin gastar API
    ```

    ## Lo básico del REPL
    - Escribí lo que necesitás en castellano, como se lo pedirías a una persona.
    - `@archivo.py` en el pedido adjunta el archivo (el agente no tiene que buscarlo).
    - `!comando` ejecuta algo en la terminal sin pasar por el modelo (ej. `!ls`).
    - `\"\"\"` abre un pedido de varias líneas (cerralo con otra línea `\"\"\"`).
    - Ctrl+C interrumpe al agente: lo ya escrito queda en disco; `/diff` muestra los cambios y `/deshacer` los revierte.
    - `/ayuda` lista todos los comandos; `/manual <tema>` abre estos capítulos.
""")

capitulo("pedidos", "Cómo pedir para que un modelo de 24B rinda", """
    # Cómo pedir

    Un modelo de 24B programa bien si el pedido es concreto. REAPER ayuda (mapa de archivos relevantes,
    guías del lenguaje, recetas probadas, validación real), pero el pedido sigue siendo lo más importante.

    ## Buenos pedidos
    - **Nombrá archivos y funciones**: "en `carrito.py`, hacé que `total()` aplique el descuento" rinde mucho
      más que "arreglá el descuento".
    - **Decí cómo se verifica**: "tiene que pasar `tests/test_carrito.py`" o "probalo con 2 y 3, tiene que dar 5".
    - **Un objetivo por pedido**. Para algo grande usá `/construir`: divide en tareas, escribe los tests
      primero y verifica cada parte.
    - **Restricciones explícitas**: "sin dependencias", "no toques la interfaz", "no ejecutes comandos".
      REAPER respeta las prohibiciones explícitas aunque el modelo intente otra cosa.

    ## Preguntas
    Si es solo una pregunta ("¿cuánto es 5+5?", "¿qué diferencia hay entre lista y tupla?") el agente responde
    directo, sin herramientas. Si querés que mire el código, decilo o mencioná el archivo con `@`.

    ## Si el resultado no te gusta
    - `/deshacer` revierte el último pedido completo; `/rehacer` lo vuelve a intentar.
    - Corregí con un pedido nuevo y concreto ("en vez de X, hacé Y"): el agente recuerda la conversación.
    - `/torneo <pedido>` hace que compitan 3 intentos en copias aisladas y se aplica el que pasa más tests.
""")

capitulo("modos", "Modos y permisos", """
    # Modos y permisos

    `/modo <nombre>` cambia cuánto pregunta REAPER antes de actuar:

    | modo | edita archivos | ejecuta comandos |
    |---|---|---|
    | `confirmar` | pregunta cada cambio (muestra el diff) | pregunta |
    | `auto-edicion` (por defecto) | sin preguntar | pregunta (salvo comandos de solo lectura) |
    | `auto` | sin preguntar | sin preguntar |
    | `plan` | NO edita: investiga y propone un plan | no |

    ## Modo plan
    `/modo plan` y después tu pedido: un agente de solo lectura investiga y escribe un plan (objetivo,
    archivos, pasos, cómo se verifica, riesgos). Lo podés ejecutar tal cual, ejecutarlo confirmando cada
    cambio, o seguir ajustándolo. El plan queda guardado en `.reaper/planes/`.

    ## "Permitir siempre"
    Cuando un comando pide permiso podés elegir: sí esta vez · no preguntar más en esta sesión · siempre en
    este proyecto (se guarda en `.reaper/config.json` → `"permitidos"`). Los comandos destructivos (`rm`,
    `mv`, `git push`, `git reset`, `sed -i`...), los compuestos (`a && b`, pipes) y el código arbitrario
    (`python3 -c ...`) se confirman SIEMPRE. En modo `confirmar` también podés aceptar todas las ediciones
    de la sesión de una vez.

    ## Lo que nunca se permite
    Los comandos bloqueados (`rm -rf ~`, `sudo`, formatear, `curl | sh`...) siguen bloqueados en cualquier
    modo: no es censura, protegen el celular de un error del modelo.
""")

capitulo("construir", "/construir: el pipeline completo", """
    # /construir

    ```
    exploradores → arquitecto (plan con interfaz) → tu aprobación
      → especificador: tests que todavía fallan (la especificación)
      → por tarea: torneo de implementadores en copias aisladas → gana el que pasa más tests
      → verificación de la tarea → reparador con el error real → escalada a un modelo fuerte si se repite
      → revisor (opcional) sobre el diff real
    → verificación final → lecciones → snapshot en git
    ```

    ## Consejos
    - Dale contexto: "API de notas con SQLite: crear, listar, buscar por etiqueta y borrar; tests con unittest".
    - Revisá el plan antes de aprobarlo: es barato corregirlo ahí. Si el arquitecto devuelve una sola tarea
      gigante, REAPER se lo pide de nuevo dividido (y si insiste, lo divide por archivo).
    - Los tests de la especificación quedan protegidos: ningún implementador puede "arreglarlos" para pasar.
    - Una tarea que no terminó tiene que mostrar progreso; una tarea cuya verificación real falla no se manda
      al revisor (no se aprueba código roto).

    ## Perfiles
    `/perfil` muestra los perfiles: `gratis` (modelo `:free`, sin paralelismo para no chocar con el límite de
    tasa), `rapido` (sin torneo ni tests primero), `equilibrado` (torneo de 2 y tests primero) y `maximo`
    (torneo de 3 y escalada).
""")

capitulo("herramientas", "Herramientas del agente", """
    # Herramientas del agente

    | para | herramientas |
    |---|---|
    | leer | `read_file`, `read_symbol` (una función/clase), `code_outline`, `search_files`, `list_files`, `find_references`, `project_map` |
    | editar | `write_to_file`, `replace_in_file`, `replace_symbol`, `insert_after_symbol`, `append_to_file`, `insert_lines`, `replace_lines`, `rename_symbol`, `write_large_file` |
    | verificar | `validate`, `run_tests`, `execute_command`, `run_python` |
    | procesos | `start_process`, `process_output`, `stop_process` |
    | otros | `update_todo`, `view_diff`, `delegate` (subagentes), `ask_user`, `fetch_url`, `save_note`, `learn_lesson` |

    ## Lo que REAPER hace con cada llamada
    - Cada edición devuelve la **validación real** (sintaxis, imports, nombres indefinidos, `node --check`...)
      y arreglos automáticos triviales.
    - Una llamada **idéntica** a una anterior, sin que nada haya cambiado en el proyecto, no se repite: se
      devuelve el resultado anterior y se le pide al modelo que responda. Después de editar, volver a correr
      los tests o releer un archivo sí está permitido.
    - Un cierre que afirma "validé" o "los tests pasan" sin una ejecución real que lo respalde se rechaza; si
      el modelo insiste, el informe queda marcado con ⚠ como no verificado.
""")

capitulo("interactivos", "Programas interactivos y servidores", """
    # Programas interactivos y servidores

    ## Programas con input()
    Un programa interactivo ejecutado sin entrada termina con `EOFError`: **no es un bug**. El agente lo prueba
    pasándole las respuestas:
    ```xml
    <execute_command>
    <command>python3 calculadora.py</command>
    <stdin>2
    3
    +
    salir</stdin>
    </execute_command>
    ```
    `run_python` también acepta `<stdin>`. Si un programa da `EOFError`, REAPER le recuerda al modelo que no lo
    modifique para quitarle el `input()`. En tests: `subprocess.run([...], input="2\\n3\\n", text=True)`.

    ## Servidores y procesos largos
    ```xml
    <start_process>
    <command>python3 servidor.py</command>
    <wait_for>escuchando|Serving|listening</wait_for>
    </start_process>
    ```
    Devuelve un id (`p1`). Después: `process_output` para ver lo nuevo y `stop_process` para pararlo.
    `/procesos` los lista; `/procesos parar todos` los detiene. Al salir de REAPER se detienen solos.
""")

capitulo("plantillas", "Plantillas y recetas", """
    # Plantillas y recetas

    ## Plantillas
    `/plantillas` lista proyectos base que ya funcionan y ya tienen tests (Python, web/Node, juegos, Bash, Go,
    Rust, C, Java, PHP, Ruby, Perl). `/nuevo <plantilla> <carpeta>` crea uno. Un modelo de 24B construye mucho
    mejor sobre una base ordenada que desde una carpeta vacía.

    Plantillas propias: `~/reaper/plantillas/<nombre>/` con los archivos tal cual (opcional `plantilla.json`
    con `descripcion`, `lenguaje`, `comando_tests`, `comando_ejecutar`). Placeholders: `__PROYECTO__`,
    `__Proyecto__`, `__TITULO__`, `__FECHA__`.

    ## Recetas
    `/recetas <tema>` busca fragmentos de código probados (JSON seguro, SQLite, CLI, reintentos, sockets,
    procesos, Go/Rust/C/Java/PHP/Ruby/Bash/JS...). Cuando un pedido coincide claramente con una receta (y con
    su lenguaje), REAPER la agrega sola al prompt del implementador.
""")

capitulo("memoria", "Lecciones, notas y memoria del proyecto", """
    # Lecciones, notas y memoria

    - **REAPER.md** (o `/init` para crearlo): lo que el agente tiene que saber siempre del proyecto (cómo se
      ejecuta, cómo se testea, convenciones). Va en el system prompt.
    - **Lecciones**: cada reparación que funcionó deja una lección de una línea en `.reaper/lecciones.md`
      (proyecto) y `~/reaper/lecciones.md` (general). Las relevantes se inyectan en los próximos pedidos.
      `/lecciones` las muestra y permite borrarlas.
    - **Notas**: los agentes pueden dejar notas para otros agentes (`save_note`) en `.reaper/notas.md`.
    - **Sesiones**: la conversación se guarda; `/sesiones` las lista y se retoman al volver a abrir el proyecto.
""")

capitulo("git", "Deshacer, checkpoints y git", """
    # Deshacer, checkpoints y git

    - Antes de cada escritura REAPER guarda el original: `/deshacer` revierte el último pedido entero,
      `/checkpoints` lista los puntos y `/deshacer <id>` vuelve a uno en particular. Funciona sin git.
    - `/diff` muestra lo que cambió el último pedido.
    - Con git: cada build verificada se guarda en la rama `reaper/builds` sin tocar tu rama ni tu índice
      (`/git snapshot` lo hace a mano, `/git log` y `/git diff` las muestran). `/commit` arma el mensaje con el modelo a partir del diff y te lo muestra
      antes de commitear.
""")

capitulo("extensiones", "Comandos propios, plugins y hooks", """
    # Extensiones

    ## Comandos propios
    `~/reaper/comandos/<nombre>.md` (o `.reaper/comandos/` en el proyecto) con el texto del pedido; `$ARGUMENTOS`
    se reemplaza por lo que escribas después de `/<nombre>`. `/comandos ejemplos` crea algunos.

    ## Plugins
    `~/reaper/herramientas/*.py` puede registrar herramientas nuevas para los agentes con el decorador
    `herramienta(...)`. `/plugins ejemplo` crea uno de muestra.

    ## Hooks
    En `.reaper/config.json`:
    ```json
    {"hooks": {"despues_de_escribir": ["black -q {archivo}"],
               "antes_de_comando": ["./scripts/permitido.sh {comando}"],
               "despues_de_build": ["termux-notification --title REAPER --content {estado}"]}}
    ```
    `/hooks` muestra los configurados.
""")

capitulo("evaluar", "Medir al modelo: /evaluar", """
    # /evaluar

    - `/evaluar [N]`: tareas reales con tests ocultos (FizzBuzz con reglas, parsers, estadísticas...). Mide
      cuántas resuelve el modelo actual. Sirve para comparar Venice con otros modelos o el agente simple con el
      torneo (`/evaluar` después de `/perfil maximo`).
    - `/evaluar comportamiento`: casos de conducta salidos de errores reales: responder "5+5" sin herramientas,
      ejecutar 2+2 una sola vez, no modificar un programa interactivo, no afirmar verificaciones falsas, pocas
      lecturas para una pregunta, arreglos mínimos. Cada caso dice exactamente qué hizo mal el modelo.
    - Los resultados quedan en `~/reaper/evals/` (JSON) para comparar en el tiempo.
""")

capitulo("problemas", "Solución de problemas", """
    # Solución de problemas

    | síntoma | qué hacer |
    |---|---|
    | `429` / límite de tasa | `/config rpm 10` o un plan pago; REAPER reintenta con espera creciente |
    | "contexto excedido" | REAPER compacta solo; para pedidos largos usá `/construir` (contexto chico por tarea) |
    | el modelo repite una herramienta | REAPER devuelve el resultado anterior y corta el bucle; si pasa seguido, `/evaluar comportamiento` |
    | dice que validó y no es cierto | el cierre se rechaza o queda marcado con ⚠; pedile que corra `run_tests` |
    | archivo largo cortado | escribe por partes y REAPER continúa solo; para >300 líneas usá `/escribir` |
    | EOFError en un programa | es interactivo: probalo con `<stdin>` (ver `/manual interactivos`) |
    | un servidor "se cuelga" | usá `start_process` (ver `/manual interactivos`) |
    | algo raro en el entorno | `/doctor` revisa Python, node, git, clave, red y permisos |
    | quiero ver qué hizo | `/diff`, `/contexto`, `/uso`; los logs están en `~/reaper/logs/` |

    Si REAPER mismo falla: `reaper --autotest` verifica todo sin gastar API (debería decir "tests OK").
""")

capitulo("seguridad", "Seguridad", """
    # Seguridad

    - Las rutas están confinadas al proyecto: el agente no puede leer ni escribir fuera (ni `.env`, claves SSH...).
    - Las claves API nunca llegan al modelo: se quitan del entorno de los comandos y se tapan en las salidas.
    - Comandos bloqueados en cualquier modo: borrar el home o la raíz, `sudo`/`su`, formatear, `curl | sh`,
      fork bombs, apagar el equipo y similares.
    - `fetch_url` solo descarga texto, con límite de tamaño, y en modos no automáticos pregunta por dominios nuevos.
    - Seguridad ofensiva solo en sistemas propios, laboratorios, CTF o con autorización explícita.
""")


def buscar_capitulo(consulta: str) -> Optional[str]:
    consulta = sin_tildes((consulta or "").strip().lower())
    if not consulta:
        return None
    if consulta in MANUAL:
        return consulta
    for clave, (titulo, _texto) in MANUAL.items():
        if consulta in clave or consulta in sin_tildes(titulo.lower()):
            return clave
    for clave, (_titulo, texto) in MANUAL.items():
        if consulta in sin_tildes(texto.lower()):
            return clave
    return None


def indice_manual() -> str:
    filas = [f"- `/manual {clave}` — {titulo}" for clave, (titulo, _t) in MANUAL.items()]
    return "# Manual de REAPER\n\n" + "\n".join(filas)


def _cmd_manual(self: "App", arg: str) -> None:
    clave = buscar_capitulo(arg)
    if arg.strip() and clave is None:
        self.ui.aviso(f"No encontré '{arg}' en el manual.")
    mostrar_markdown(self.ui, MANUAL[clave][1] if clave else indice_manual())


setattr(App, "cmd_manual", _cmd_manual)
COMANDOS_AYUDA[0][1].insert(0, ("/manual [tema]", "manual: primeros pasos, modos, /construir, interactivos, problemas..."))
