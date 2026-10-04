"""
Procesos en segundo plano (como los "background shells" de Claude Code).

Un servidor o un programa que tarda no se puede probar con execute_command (se corta por timeout). Con
estas herramientas el agente lo levanta, espera a que esté listo, lo consulta y lo para:

  <start_process>
  <command>python3 servidor.py</command>
  <wait_for>Serving|escuchando|listening</wait_for>
  </start_process>
  → id p1 y las primeras líneas de salida

  <execute_command><command>curl -s localhost:8000/salud</command></execute_command>
  <process_output><id>p1</id></process_output>     → lo nuevo que imprimió
  <stop_process><id>p1</id></stop_process>          → lo detiene y devuelve la salida final

Límites: máximo MAX_PROCESOS a la vez, salida guardada en un buffer circular, y todo se detiene al salir
de REAPER (o con /procesos parar). Los comandos bloqueados por seguridad siguen bloqueados.
"""

MAX_PROCESOS = 4
MAX_LINEAS_BUFFER = 2000


class ProcesoFondo:
    def __init__(self, id_: str, comando: str, cwd: Path, entrada: Optional[str] = None):
        self.id = id_
        self.comando = comando
        self.cwd = cwd
        self.inicio = time.monotonic()
        self.lineas: collections.deque = collections.deque(maxlen=MAX_LINEAS_BUFFER)
        self.total_lineas = 0
        self.leidas = 0
        self._lock = threading.Lock()
        self._cambio = threading.Condition(self._lock)
        self.proceso = subprocess.Popen(
            comando, shell=True, executable=shutil.which("bash") or None, cwd=str(cwd),
            stdin=subprocess.PIPE if entrada is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            env=entorno_seguro(), start_new_session=True, bufsize=1,
        )
        if entrada is not None and self.proceso.stdin:
            try:
                self.proceso.stdin.write(entrada)
                self.proceso.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        self._lector = threading.Thread(target=self._leer, name=f"proceso-{id_}", daemon=True)
        self._lector.start()

    def _leer(self) -> None:
        assert self.proceso.stdout is not None
        for linea in self.proceso.stdout:
            with self._cambio:
                self.lineas.append(linea.rstrip("\n"))
                self.total_lineas += 1
                self._cambio.notify_all()
        with self._cambio:
            self._cambio.notify_all()

    @property
    def vivo(self) -> bool:
        return self.proceso.poll() is None

    def estado(self) -> str:
        codigo = self.proceso.poll()
        segundos = formatear_duracion(time.monotonic() - self.inicio)
        return f"corriendo hace {segundos}" if codigo is None else f"terminó con código {codigo} (después de {segundos})"

    def esperar_texto(self, patron: Optional[re.Pattern], timeout: float) -> bool:
        """Espera hasta que aparezca el patrón en la salida (o el proceso termine, o pase el timeout)."""
        limite = time.monotonic() + timeout
        with self._cambio:
            while True:
                if patron is not None and any(patron.search(l) for l in self.lineas):
                    return True
                if not self.vivo and not self._lector.is_alive():
                    return False
                restante = limite - time.monotonic()
                if restante <= 0:
                    return patron is None
                self._cambio.wait(min(restante, 0.2))

    def nuevas(self, maximo: int = 200) -> list[str]:
        with self._lock:
            pendientes = self.total_lineas - self.leidas
            self.leidas = self.total_lineas
            disponibles = list(self.lineas)
        if pendientes <= 0:
            return []
        recientes = disponibles[-min(pendientes, len(disponibles)):]
        if len(recientes) > maximo:
            return [f"[... {len(recientes) - maximo} líneas omitidas ...]"] + recientes[-maximo:]
        return recientes

    def ultimas(self, n: int = 40) -> list[str]:
        with self._lock:
            return list(self.lineas)[-n:]

    def detener(self, gracia: float = 3.0) -> Optional[int]:
        if self.vivo:
            try:
                os.killpg(self.proceso.pid, signal.SIGTERM)
            except OSError:
                self.proceso.terminate()
            try:
                self.proceso.wait(timeout=gracia)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proceso.pid, signal.SIGKILL)
                except OSError:
                    self.proceso.kill()
                self.proceso.wait(timeout=gracia)
        self._lector.join(timeout=1)
        return self.proceso.returncode


_PROCESOS: dict[str, ProcesoFondo] = {}
_LOCK_PROCESOS = threading.Lock()
_CONTADOR_PROCESOS = itertools.count(1)


def procesos_activos() -> list[ProcesoFondo]:
    with _LOCK_PROCESOS:
        return [p for p in _PROCESOS.values() if p.vivo]


def detener_todos_los_procesos() -> int:
    with _LOCK_PROCESOS:
        procesos = list(_PROCESOS.values())
        _PROCESOS.clear()
    detenidos = 0
    for p in procesos:
        if p.vivo:
            p.detener(gracia=1.5)
            detenidos += 1
    return detenidos


atexit.register(detener_todos_los_procesos)


def _proceso(ctx: Contexto, p: dict) -> ProcesoFondo:
    id_ = (p.get("id") or "").strip()
    with _LOCK_PROCESOS:
        if not id_ and len(_PROCESOS) == 1:
            return next(iter(_PROCESOS.values()))
        proceso = _PROCESOS.get(id_)
    if proceso is None:
        disponibles = ", ".join(_PROCESOS) or "ninguno"
        raise ErrorHerramienta(f"No existe el proceso '{id_}'. Procesos: {disponibles}.")
    return proceso


@herramienta(
    "start_process",
    "Inicia un proceso en SEGUNDO PLANO (servidor, watcher, programa largo) y devuelve su id. Con wait_for "
    "espera a que aparezca ese texto (regex) en la salida, p. ej. 'Listening|Serving|escuchando'. Después usá "
    "process_output para ver la salida y stop_process para detenerlo. Para comandos cortos usá execute_command.",
    [Param("command", "comando a ejecutar"),
     Param("wait_for", "regex que indica que ya está listo (opcional)", requerido=False),
     Param("timeout", "segundos máximos de espera inicial (opcional, por defecto 10)", requerido=False),
     Param("stdin", "entrada estándar (opcional)", requerido=False, largo=True)],
    "<start_process>\n<command>python3 -m http.server 8000</command>\n<wait_for>Serving</wait_for>\n</start_process>",
)
def start_process(ctx: Contexto, p: dict) -> str:
    comando = p["command"].strip()
    if not comando:
        raise ErrorHerramienta("Comando vacío.")
    patron_bloqueado = comando_bloqueado(comando)
    if patron_bloqueado:
        raise ErrorHerramienta(f"Comando bloqueado por seguridad (coincide con {patron_bloqueado}).")
    motivo_hook = _hook_antes_de_comando(ctx, comando)
    if motivo_hook:
        raise ErrorHerramienta(f"Comando bloqueado: {motivo_hook}.")
    if len(procesos_activos()) >= MAX_PROCESOS:
        raise ErrorHerramienta(f"Ya hay {MAX_PROCESOS} procesos en segundo plano: detené alguno con stop_process.")
    if ctx.settings.modo != "auto" and not comando_seguro(comando):
        if not pedir_permiso_comando(ctx, comando):
            raise ErrorHerramienta("El usuario no aprobó iniciar ese proceso.")
    patron = None
    if (p.get("wait_for") or "").strip():
        try:
            patron = re.compile(p["wait_for"].strip(), re.I)
        except re.error as e:
            raise ErrorHerramienta(f"wait_for no es una regex válida: {e}")
    timeout = min(120, max(1, _entero(p.get("timeout"), 10) or 10))
    id_ = f"p{next(_CONTADOR_PROCESOS)}"
    try:
        proceso = ProcesoFondo(id_, comando, ctx.ws.raiz, _entrada_estandar(p))
    except OSError as e:
        raise ErrorHerramienta(f"No pude iniciar el proceso: {e}")
    with _LOCK_PROCESOS:
        _PROCESOS[id_] = proceso
    listo = proceso.esperar_texto(patron, timeout if patron else min(timeout, 0.8))
    salida = proceso.nuevas(80)
    texto = [f"Proceso {id_} iniciado: {comando}", f"Estado: {proceso.estado()}"]
    if patron is not None:
        texto.append("Listo: apareció el texto esperado." if listo else
                     f"ATENCIÓN: no apareció /{patron.pattern}/ en {timeout}s.")
    texto.append("Salida inicial:\n" + ("\n".join(salida) if salida else "(todavía nada)"))
    if not proceso.vivo:
        texto.append("El proceso YA TERMINÓ: si era un servidor, falló al arrancar (mirá la salida).")
        if proceso.proceso.returncode not in (0, None) and parece_interactivo("\n".join(salida)):
            texto.append(PISTA_INTERACTIVO)
    else:
        texto.append(f"Seguí con process_output (id {id_}) y detenelo con stop_process cuando termines.")
    return "\n".join(texto)


@herramienta(
    "process_output",
    "Muestra la salida NUEVA de un proceso en segundo plano (y si sigue corriendo). Sin id lista los procesos.",
    [Param("id", "id del proceso (p1, p2...), opcional", requerido=False),
     Param("wait_for", "regex a esperar antes de leer (opcional)", requerido=False),
     Param("timeout", "segundos máximos de espera (opcional, por defecto 5)", requerido=False)],
    "<process_output>\n<id>p1</id>\n</process_output>",
)
def process_output(ctx: Contexto, p: dict) -> str:
    if not (p.get("id") or "").strip() and len(_PROCESOS) != 1:
        if not _PROCESOS:
            return "No hay procesos en segundo plano."
        return "Procesos:\n" + "\n".join(f"- {x.id}: {x.comando} ({x.estado()})" for x in _PROCESOS.values())
    proceso = _proceso(ctx, p)
    if (p.get("wait_for") or "").strip():
        try:
            patron = re.compile(p["wait_for"].strip(), re.I)
        except re.error as e:
            raise ErrorHerramienta(f"wait_for no es una regex válida: {e}")
        proceso.esperar_texto(patron, min(60, max(1, _entero(p.get("timeout"), 5) or 5)))
    nuevas = proceso.nuevas(200)
    cuerpo = "\n".join(nuevas) if nuevas else "(sin salida nueva desde la última lectura)"
    return f"Proceso {proceso.id} ({proceso.comando}): {proceso.estado()}\n{cuerpo}"


@herramienta(
    "stop_process",
    "Detiene un proceso en segundo plano y devuelve sus últimas líneas de salida.",
    [Param("id", "id del proceso (p1, p2...)", requerido=False)],
    "<stop_process>\n<id>p1</id>\n</stop_process>",
)
def stop_process(ctx: Contexto, p: dict) -> str:
    proceso = _proceso(ctx, p)
    estaba_vivo = proceso.vivo
    codigo = proceso.detener()
    with _LOCK_PROCESOS:
        _PROCESOS.pop(proceso.id, None)
    finales = proceso.nuevas(60) or proceso.ultimas(20)
    estado = "detenido" if estaba_vivo else f"ya había terminado (código {codigo})"
    return f"Proceso {proceso.id} {estado}.\nÚltima salida:\n" + ("\n".join(finales) or "(nada)")


HERRAMIENTAS_PROCESOS = ("start_process", "process_output", "stop_process")
ALIAS_HERRAMIENTAS.update({
    "background": "start_process", "run_background": "start_process", "spawn": "start_process",
    "iniciar_proceso": "start_process", "start_server": "start_process", "bash_background": "start_process",
    "read_output": "process_output", "get_output": "process_output", "bash_output": "process_output",
    "salida_proceso": "process_output", "kill_process": "stop_process", "kill": "stop_process",
    "detener_proceso": "stop_process", "stop_server": "stop_process",
})
ALIAS_PARAMS.setdefault("wait_for", ("esperar", "ready", "listo", "until", "esperar_texto"))
ALIAS_PARAMS.setdefault("id", ("pid", "proceso", "process_id", "shell_id"))

# Los roles que ejecutan código pueden levantar procesos en segundo plano.
for _rol in ("principal", "implementador", "reparador", "qa"):
    if _rol in ROLES and "start_process" not in ROLES[_rol].herramientas:
        ROLES[_rol] = replace(ROLES[_rol], herramientas=ROLES[_rol].herramientas + HERRAMIENTAS_PROCESOS)

DOCS_EN.update({
    "start_process": ("Starts a BACKGROUND process (server, watcher, long program) and returns its id. With wait_for it "
                      "waits until that regex appears in the output (e.g. 'Listening|Serving'). Then use process_output "
                      "to read its output and stop_process to stop it. For short commands use execute_command.",
                      {"command": "command to run", "wait_for": "regex meaning it is ready (optional)",
                       "timeout": "max seconds to wait (optional, default 10)", "stdin": "standard input (optional)"}),
    "process_output": ("Shows the NEW output of a background process (and whether it is still running). Without id "
                       "it lists the processes.",
                       {"id": "process id (p1, p2...), optional", "wait_for": "regex to wait for first (optional)",
                        "timeout": "max seconds to wait (optional, default 5)"}),
    "stop_process": ("Stops a background process and returns its last output lines.", {"id": "process id (p1, p2...)"}),
})


def _cmd_procesos(self: "App", arg: str) -> None:
    partes = arg.split()
    if partes and partes[0] in ("parar", "detener", "stop", "matar"):
        objetivo = partes[1] if len(partes) > 1 else "todos"
        if objetivo == "todos":
            self.ui.ok(f"Detenidos {detener_todos_los_procesos()} proceso(s).")
            return
        with _LOCK_PROCESOS:
            proceso = _PROCESOS.pop(objetivo, None)
        if proceso is None:
            self.ui.error(f"No existe el proceso {objetivo}.")
            return
        proceso.detener()
        self.ui.ok(f"Proceso {objetivo} detenido.")
        return
    if partes and partes[0] in _PROCESOS:
        proceso = _PROCESOS[partes[0]]
        self.ui.info(f"{proceso.id}: {proceso.comando} ({proceso.estado()})")
        for linea in proceso.ultimas(40):
            self.ui.linea("  " + linea)
        return
    if not _PROCESOS:
        self.ui.tenue("No hay procesos en segundo plano (los agentes los inician con start_process).")
        return
    self.ui.tabla([[p.id, recortar(p.comando, 50), p.estado()] for p in _PROCESOS.values()], ["id", "comando", "estado"])
    self.ui.tenue("  /procesos <id> para ver la salida · /procesos parar <id|todos>")


setattr(App, "cmd_procesos", _cmd_procesos)
COMANDOS_AYUDA[-1][1].append(("/procesos [id] · /procesos parar <id|todos>", "procesos en segundo plano de los agentes"))
