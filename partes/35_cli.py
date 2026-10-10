"""REPL interactivo y modo línea de comandos de REAPER v7."""

INIT_TAREA = """Analizá este proyecto y redactá el contenido de un archivo REAPER.md: la memoria del proyecto
que leerán otros agentes de IA antes de trabajar. Secciones:
# <nombre del proyecto>
## Descripción (2-3 líneas)
## Cómo ejecutar
## Cómo testear (comando exacto; si no hay tests, decilo)
## Estructura (archivos clave y para qué sirven)
## Convenciones (lenguaje, estilo, librerías, idioma de la interfaz)
Máximo 60 líneas y SOLO hechos que verificaste leyendo el código.
Tu attempt_completion debe contener ÚNICAMENTE el markdown del archivo."""

COMANDOS_AYUDA = [
    ("USO", [
        ("<pedido>", "lenguaje natural: el agente lee, edita, ejecuta y verifica en el proyecto"),
        ('"""', "empezá y terminá con una línea \"\"\" para escribir varias líneas"),
        ("@archivo", "mencioná archivos en el pedido para adjuntar su contenido"),
        ("!comando", "corre un comando de shell vos mismo (interactivo)"),
    ]),
    ("EQUIPO", [
        ("/construir <pedido>", "exploradores → arquitecto → tests primero → torneo por tarea → verificación → reparador"),
        ("/plan <pedido>", "solo exploración + plan (se guarda en .reaper/planes)"),
        ("/modo plan", "modo plan: propone un plan en solo lectura y lo ejecuta cuando lo aprobás"),
        ("/torneo <tarea>", "N implementadores compiten en copias aisladas; gana el que pasa más tests"),
        ("/escribir <ruta> <qué>", "archivo largo por esqueleto + relleno (miles de líneas sin cortarse)"),
        ("/agente <rol> <tarea>", "subagente suelto (explorador, implementador, revisor, qa, reparador...)"),
        ("/revisar [foco]", "revisores en paralelo sobre todo el proyecto"),
        ("/init", "genera REAPER.md (memoria del proyecto)"),
    ]),
    ("PROYECTO", [
        ("/proyecto [ruta]", "cambia de workspace"),
        ("/nuevo <plantilla> <carpeta>", "crea un proyecto listo y testeado desde una plantilla"),
        ("/plantillas", "lista las plantillas disponibles"),
        ("/scan · /tests · /validar [archivos]", "validadores, suite de tests, validación puntual"),
        ("/correr <archivo> [args]", "ejecuta y ofrece reparar si crashea"),
        ("/vigilar [comando]", "corre los tests cada vez que cambia un archivo (Ctrl+C para salir)"),
        ("/diff · /deshacer [id] · /rehacer", "cambios del último pedido, revertir, volver a aplicar"),
        ("/checkpoints", "historial de checkpoints"),
    ]),
    ("CÓDIGO", [
        ("/explicar <archivo|símbolo>", "explicación en español de un archivo o una función"),
        ("/testear <archivo>", "QA escribe tests para un archivo existente y los corre"),
        ("/documentar <archivo>", "agrega docstrings sin cambiar el comportamiento"),
        ("/renombrar <viejo> <nuevo>", "renombra un símbolo en todo el proyecto (sin modelo, validado)"),
        ("/web <url> [palabras]", "lee una página (documentación) como texto"),
        ("/simbolo <nombre>", "muestra una función o clase (Clase.metodo)"),
        ("/referencias <nombre>", "dónde se usa un nombre"),
        ("/mapa <tema>", "archivos más relevantes para un tema"),
        ("/recetas [tema]", "recetas de código listas (sqlite, argparse, curses, termux-api...)"),
    ]),
    ("MEMORIA", [
        ("/lecciones [general|borrar N|agregar …]", "lecciones aprendidas entre sesiones"),
        ("/notas", "notas que dejaron los agentes en .reaper/notas.md"),
        ("/git [log|estado|diff|snapshot|init]", "builds verificadas guardadas en la rama reaper/builds"),
        ("/commit [mensaje]", "commit de tus cambios con mensaje escrito por el modelo"),
        ("/sesiones · /estadisticas", "sesiones guardadas · uso y tasas de éxito por día"),
        ("/historial · /exportar [ruta]", "pedidos de la sesión · exportar la conversación a Markdown"),
    ]),
    ("AJUSTES", [
        ("/perfil [gratis|rapido|equilibrado|maximo]", "presets de torneo, escalada y límites"),
        ("/modo [confirmar|auto-edicion|auto]", "permisos para editar y ejecutar"),
        ("/modelo [alias] · /modelo <rol> <alias>", "modelo principal o por rol (ej: /modelo revisor qwen)"),
        ("/modelo-fuerte [alias]", "modelo para la escalada (deepseek por defecto)"),
        ("/modelos · /config [clave valor] · /tema [nombre]", "catálogo, configuración, colores"),
        ("/uso · /contexto · /compactar · /estado", "consumo, contexto del agente, estado general"),
        ("/desempeno · /pentest <alcance>", "ranking de modelos por rol; modo seguridad (pentest/CTF/lab) con gate"),
        ("/doctor · /instalar · /dragon · /evaluar", "diagnóstico, comando `reaper`, el dragón, benchmark"),
        ("/evaluar comportamiento [ids]", "mide si el agente responde directo, no repite herramientas, no miente..."),
        ("/todo · /reset · /salir", "lista de tareas, reiniciar conversación, salir"),
    ]),
    ("EXTENSIONES", [
        ("/comandos [ejemplos]", "tus comandos propios (~/reaper/comandos/*.md con $ARGUMENTOS)"),
        ("/plugins [ejemplo]", "herramientas propias en ~/reaper/herramientas/*.py"),
        ("/hooks", "comandos que corren antes/después de herramientas (.reaper/config.json)"),
        ("/deps", "instala las dependencias del proyecto (pip, npm, go...)"),
    ]),
]


def texto_ayuda() -> str:
    lineas = []
    ancho = min(ancho_terminal(), 100)
    for seccion, comandos in COMANDOS_AYUDA:
        lineas.append(f"\n{Tema.titulo}{C.BOLD} {seccion} {C.RESET}")
        for comando, descripcion in comandos:
            if ancho < 70:
                lineas.append(f"  {Tema.ok}{comando}{C.RESET}")
                lineas.append(f"      {Tema.tenue}{descripcion}{C.RESET}")
            else:
                lineas.append(f"  {Tema.ok}{comando:<34}{C.RESET} {Tema.tenue}{descripcion}{C.RESET}")
    return "\n".join(lineas)


def resolver_workspace(texto: str) -> Path:
    ruta = Path(os.path.expandvars(texto.strip())).expanduser().resolve()
    if not ruta.exists():
        raise ErrorRuta(f"No existe: {ruta}")
    if not ruta.is_dir():
        raise ErrorRuta(f"No es una carpeta: {ruta}")
    if not os.getenv("REAPER_LIBRE"):
        home = Path.home().resolve()
        if ruta != home and home not in ruta.parents:
            raise ErrorRuta(
                f"Por seguridad el proyecto debe estar dentro de {home} (o exportá REAPER_LIBRE=1)."
            )
    return ruta


_RE_MENCION = re.compile(r"(?<![\w/])@([\w./-]+\.[\w]+|[\w./-]+/)")


class App:
    def __init__(self, settings: Settings, llm, ui: UI, ws: Workspace, persistir: bool = True):
        self.settings = settings
        self.llm = llm
        self.ui = ui
        self.ws = ws
        self.persistir = persistir
        self.aviso_sesion = ""
        self.historial: list[tuple[str, str, bool]] = []
        self._rehacer: Optional[dict] = None
        self._pedido_actual = ""
        self.modo_plan = False
        self.escalador = Escalador(llm, settings, ui)
        self.memoria = self._nueva_memoria()
        self.desempeno = MemoriaDesempeno()
        self.principal = self._nuevo_principal()
        self.estadisticas = Estadisticas()
        if persistir:
            self._cargar_sesion()

    # ------------------------------------------------------------ sesión
    def _nueva_memoria(self) -> Optional[MemoriaLecciones]:
        if not self.settings.lecciones:
            return None
        try:
            return MemoriaLecciones(self.ws)
        except OSError:
            return None

    def _consultar_experto(self, error: str) -> Optional[str]:
        return self.escalador.diagnosticar(self.ws, self._pedido_actual or "pedido del usuario", error)

    def _nuevo_principal(self) -> Agente:
        return Agente("principal", self.llm, self.ws, self.settings, self.ui, etiqueta="reaper",
                      memoria=self.memoria, on_atascado=self._consultar_experto, desempeno=self.desempeno)

    def _ruta_sesion(self) -> Path:
        return SESIONES_DIR / f"{self.ws.checkpoints.carpeta.name}.json"

    def _guardar_sesion(self) -> None:
        if not self.persistir:
            return
        try:
            SESIONES_DIR.mkdir(parents=True, exist_ok=True)
            mensajes = self.principal.mensajes[1:][-60:]
            while mensajes and mensajes[0]["role"] != "user":
                mensajes = mensajes[1:]
            datos = {"mensajes": mensajes, "todo": self.principal.ctx.todo,
                     "historial": self.historial[-50:], "guardado": datetime.now().isoformat(timespec="seconds")}
            escritura_atomica(self._ruta_sesion(), json.dumps(datos, ensure_ascii=False))
        except OSError as e:
            self.ui.aviso(f"No pude guardar la sesión: {e}")

    def _cargar_sesion(self) -> None:
        try:
            datos = json.loads(self._ruta_sesion().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        mensajes = [m for m in datos.get("mensajes", [])
                    if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
        self.historial = [tuple(h) for h in datos.get("historial", []) if isinstance(h, list) and len(h) == 3]
        if mensajes:
            self.principal.mensajes = [{"role": "system", "content": ""}] + mensajes
            self.principal.ctx.todo[:] = [tuple(t) for t in datos.get("todo", []) if len(t) == 2]
            self.aviso_sesion = (f"retomé la sesión anterior de este proyecto ({len(mensajes)} mensajes) · "
                                 "/reset para empezar de cero")

    def cambiar_workspace(self, ruta: Path) -> None:
        self._guardar_sesion()
        self.ws = Workspace(ruta)
        self.memoria = self._nueva_memoria()
        self.principal = self._nuevo_principal()
        self.historial = []
        self._rehacer = None
        if self.persistir:
            guardar_estado(proyecto=str(self.ws.raiz))
            self._cargar_sesion()
            if self.aviso_sesion:
                self.ui.tenue("  " + self.aviso_sesion)

    # ------------------------------------------------------------ acciones
    def expandir_menciones(self, texto: str) -> str:
        """@ruta en el pedido → se adjunta el contenido (recortado) para que el agente no tenga que buscarlo."""
        adjuntos = []
        for m in _RE_MENCION.finditer(texto):
            rel = m.group(1)
            try:
                ruta = self.ws.ruta(rel)
            except ErrorRuta:
                continue
            if ruta.is_dir():
                listado = [self.ws.rel(p) for p in self.ws.iterar(rel, limite=60)]
                adjuntos.append(f"### Carpeta {self.ws.rel(ruta)}\n" + "\n".join(listado))
            elif ruta.is_file() and self.ws.es_texto(ruta) and not es_binario(ruta):
                try:
                    lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                cuerpo = "\n".join(f"{i:>5}| {l}" for i, l in enumerate(lineas[:300], start=1))
                extra = f"\n(... {len(lineas) - 300} líneas más: usá read_file)" if len(lineas) > 300 else ""
                adjuntos.append(f"### {self.ws.rel(ruta)} ({len(lineas)} líneas)\n{cuerpo}{extra}")
        if not adjuntos:
            return texto
        self.ui.tenue(f"  adjunté {len(adjuntos)} mención(es) @")
        return texto + "\n\nARCHIVOS MENCIONADOS POR EL USUARIO:\n" + "\n\n".join(adjuntos)

    def turno_plan(self, texto: str) -> bool:
        """
        Modo plan (como Claude Code): un agente de solo lectura investiga y propone; nada se toca hasta que
        el usuario aprueba. Al aprobar, el plan entra como contexto del agente principal y se sale del modo.
        """
        self._pedido_actual = texto
        agente = Agente("planificador", self.llm, self.ws, self.settings, self.ui, memoria=self.memoria)
        res = agente.ejecutar(self.expandir_menciones(texto))
        self.historial.append((datetime.now().strftime("%H:%M"), f"[plan] {texto[:190]}", res.ok))
        self.ui.linea("")
        self.ui.linea(f"{Tema.agente}{C.BOLD}reaper » plan{C.RESET}")
        mostrar_markdown(self.ui, res.resumen)
        self.ui.linea("")
        ruta = guardar_plan_markdown(self.ws, texto, res.resumen)
        if ruta:
            self.ui.tenue(f"  plan guardado en {self.ws.rel(ruta)}")
        if not res.ok and res.motivo in ("max_pasos", "bucle"):
            self.ui.aviso(f"  (el planificador terminó con estado {res.motivo}: revisá el plan antes de aprobarlo)")
        eleccion = self.ui.elegir("¿Qué hacemos con este plan?", [
            "Ejecutarlo (auto-edición)",
            "Ejecutarlo confirmando cada cambio",
            "Seguir en modo plan (no tocar nada)",
        ], defecto=2 if not self.ui.interactivo else 0)
        if eleccion == 2:
            self.ui.tenue("  Sigo en modo plan: escribí ajustes al plan o /modo auto-edicion para salir.")
            return res.ok
        self.modo_plan = False
        self.settings.modo = "auto-edicion" if eleccion == 0 else "confirmar"
        self.ui.ok(f"Plan aprobado: ejecuto en modo {self.settings.modo}")
        return self.turno(
            f"{texto}\n\nPLAN APROBADO POR EL USUARIO (seguilo paso a paso; si algo no coincide con el código real, "
            f"adaptalo y decilo en el informe):\n{res.resumen}"
        )

    def turno(self, texto: str) -> bool:
        if self.modo_plan:
            return self.turno_plan(texto)
        self._pedido_actual = texto
        cid = self.ws.checkpoints.iniciar(f"pedido: {texto[:80]}")
        inicio = time.monotonic()
        res = None
        try:
            res = self.principal.ejecutar(self.expandir_menciones(texto), cid_inicio=cid)
        finally:
            self.historial.append((datetime.now().strftime("%H:%M"), texto[:200], bool(res and res.ok)))
            self._guardar_sesion()
            self.ws.checkpoints.descartar_si_vacio(cid)
        self.ui.linea("")
        self.ui.linea(f"{Tema.agente}{C.BOLD}reaper »{C.RESET}")
        mostrar_markdown(self.ui, res.resumen)
        if res.cambios:
            self.ui.tenue(
                f"\n  {len(res.cambios)} archivo(s) cambiados: {', '.join(res.cambios[:8])}"
                f"{' ...' if len(res.cambios) > 8 else ''} · /diff · /deshacer"
            )
        duracion = time.monotonic() - inicio
        self.estadisticas.registrar(pedidos=1, pedidos_ok=int(res.ok), segundos=round(duracion, 1),
                                    escaladas=int(res.escalado))
        self.estadisticas.registrar_uso(self.llm.uso, self.settings.modelo)
        detalle = [formatear_duracion(duracion), f"{res.pasos} pasos"]
        if res.escalado:
            detalle.append("con escalada")
        self.ui.tenue("  " + " · ".join(detalle))
        claim = getattr(self.principal, "_ultimo_claim", None)
        if claim is not None and claim.nivel and claim.nivel != "BEHAVIOR_VERIFIED":
            self.ui.tenue(f"  verificación: {claim.nivel}" + (f" — {recortar(claim.motivo, 120)}" if claim.motivo else ""))
        if not res.ok:
            self.ui.aviso(f"  (terminó con estado: {res.motivo})")
        self.ui.linea("")
        return res.ok

    def construir(self, pedido: str, confirmar: bool = True) -> bool:
        self._pedido_actual = pedido
        informe = Orquestador(self.llm, self.ws, self.settings, self.ui).construir(pedido, confirmar)
        self.historial.append((datetime.now().strftime("%H:%M"), f"/construir {pedido[:180]}", informe.ok))
        if informe.estado != "cancelada":
            self.estadisticas.registrar(
                builds=1, builds_ok=int(informe.ok), escaladas=informe.escaladas, lecciones=len(informe.lecciones),
                torneos=sum(1 for _, modo, _g in informe.torneos if modo == "torneo"), segundos=round(informe.segundos, 1))
            self.estadisticas.registrar_uso(self.llm.uso, self.settings.modelo)
            if self.settings.hooks:
                for r in ejecutar_hooks(self.ws, "despues_de_build", {"estado": informe.estado, "pedido": pedido[:200]}):
                    (self.ui.tenue if r.ok else self.ui.aviso)(f"  hook: {r.comando} → {'ok' if r.ok else 'falló'}")
        return informe.ok

    # ------------------------------------------------------------ comandos
    def comando(self, entrada: str) -> Optional[str]:
        partes = entrada.split(maxsplit=1)
        cmd = partes[0].lower()
        arg = partes[1].strip() if len(partes) > 1 else ""
        alias = {
            "/help": "ayuda", "/h": "ayuda", "/?": "ayuda", "/exit": "salir", "/quit": "salir", "/q": "salir",
            "/undo": "deshacer", "/redo": "rehacer", "/build": "construir", "/b": "construir",
            "/symbol": "simbolo", "/sym": "simbolo", "/refs": "referencias", "/map": "mapa", "/new": "nuevo",
            "/templates": "plantillas", "/lessons": "lecciones", "/notes": "notas", "/watch": "vigilar",
            "/profile": "perfil", "/theme": "tema", "/usage": "uso", "/costos": "uso", "/write": "escribir",
            "/tournament": "torneo", "/recipes": "recetas", "/eval": "evaluar", "/export": "exportar",
            "/history": "historial", "/status": "estado", "/context": "contexto", "/compact": "compactar",
            "/run": "correr", "/test": "tests", "/project": "proyecto", "/model": "modelo", "/mode": "modo",
            "/strong": "modelo_fuerte", "/privacy": "privacidad", "/providers": "proveedores", "/team": "equipo",
        }
        nombre = alias.get(cmd, cmd[1:]).replace("-", "_")
        metodo = getattr(self, "cmd_" + nombre, None)
        if metodo is None:
            propio = comandos_usuario(self.ws).get(cmd[1:])
            if propio is not None:
                return self.ejecutar_comando_usuario(propio, arg)
            parecidos = difflib.get_close_matches(cmd[1:], [n[4:] for n in dir(self) if n.startswith("cmd_")], n=2)
            sugerencia = f" ¿Quisiste decir /{parecidos[0].replace('_', '-')}?" if parecidos else ""
            self.ui.error(f"Comando desconocido: {cmd}.{sugerencia} (probá /ayuda)")
            return None
        return metodo(arg)

    def nombres_comandos(self) -> list[str]:
        propios = ["/" + n for n in comandos_usuario(self.ws)]
        return sorted({"/" + n[4:].replace("_", "-") for n in dir(self) if n.startswith("cmd_")} | set(propios))

    def ejecutar_comando_usuario(self, comando: "ComandoUsuario", argumentos: str) -> None:
        pedido = comando.expandir(argumentos)
        self.ui.tenue(f"  /{comando.nombre}: {recortar(pedido, 160)}")
        modo = (comando.modo or "agente").strip().lower()
        if modo == "construir":
            self.construir(pedido)
        elif modo.startswith("rol:"):
            self.cmd_agente(f"{modo[4:].strip()} {pedido}")
        else:
            self.turno(pedido)

    def cmd_ayuda(self, arg: str) -> None:
        self.ui.linea(texto_ayuda())

    def cmd_salir(self, arg: str) -> str:
        self._guardar_sesion()
        u = self.llm.uso
        if u.llamadas:
            self.ui.tenue(f"Sesión: {u.resumen()}")
        self.ui.tenue("Chau (sesión guardada). 🐉")
        return "salir"

    # ---------------------------------------------------------------- equipo
    def cmd_construir(self, arg: str) -> None:
        if not arg:
            self.ui.tenue("Uso: /construir <qué querés construir>")
            return
        self.construir(arg)

    def cmd_plan(self, arg: str) -> None:
        if not arg:
            self.ui.tenue("Uso: /plan <qué querés diseñar>")
            return
        ruta = Orquestador(self.llm, self.ws, self.settings, self.ui).solo_plan(arg)
        if ruta:
            self.ui.ok(f"Plan guardado en {ruta}")

    def cmd_torneo(self, arg: str) -> None:
        if not arg:
            self.ui.tenue(f"Uso: /torneo <tarea>   (compiten {self.settings.candidatos} implementadores; "
                          "cambiá la cantidad con /config candidatos N)")
            return
        self._pedido_actual = arg
        cid = self.ws.checkpoints.iniciar(f"torneo: {arg[:70]}")
        torneo = Torneo(self.llm, self.ws, self.settings, self.ui, memoria=self.memoria,
                        on_atascado=self.escalador.gancho(self.ws, arg))
        resultado = torneo.correr(self.expandir_menciones(arg), titulo=_titulo(arg),
                                  n=max(2, self.settings.candidatos), cid=cid)
        self.ws.checkpoints.descartar_si_vacio(cid)
        self.ui.linea("")
        mostrar_markdown(self.ui, resultado.informe())
        self.historial.append((datetime.now().strftime("%H:%M"), f"/torneo {arg[:180]}", resultado.ok))

    def cmd_escribir(self, arg: str) -> None:
        partes = arg.split(maxsplit=1)
        if len(partes) < 2:
            self.ui.tenue("Uso: /escribir <ruta.py|.js> <descripción completa de lo que debe hacer el archivo>")
            return
        rel, especificacion = partes
        try:
            ruta = self.ws.ruta(rel, escribir=True)
        except ErrorRuta as e:
            self.ui.error(str(e))
            return
        cid = self.ws.checkpoints.iniciar(f"escribir {rel}")
        escritor = EscritorLargo(self.llm, self.ws, self.settings, self.ui)
        try:
            informe = escritor.escribir(self.ws.rel(ruta), especificacion, contexto=self.ws.memoria(1500))
        except ErrorEscritor as e:
            self.ui.error(str(e))
            self.ws.checkpoints.descartar_si_vacio(cid)
            return
        (self.ui.ok if informe.ok else self.ui.aviso)(informe.texto())
        self.ui.tenue("  /diff para ver el archivo · /deshacer para descartarlo")

    def cmd_agente(self, arg: str) -> None:
        partes = arg.split(maxsplit=1)
        rol = ALIAS_ROLES.get(partes[0].lower(), partes[0].lower()) if partes else ""
        if len(partes) < 2 or rol not in ROLES_DELEGABLES:
            self.ui.tenue(f"Uso: /agente <{'|'.join(ROLES_DELEGABLES)}> <tarea>")
            return
        cid = self.ws.checkpoints.iniciar(f"agente {rol}: {partes[1][:60]}")
        res = ejecutar_subagentes([(rol, self.expandir_menciones(partes[1]), "", "",
                                    {"memoria": self.memoria, "on_atascado": self._consultar_experto})],
                                  self.llm, self.ws, self.settings, self.ui, profundidad=1, cid_inicio=cid)[0]
        self.ws.checkpoints.descartar_si_vacio(cid)
        self.ui.linea("")
        mostrar_markdown(self.ui, res.resumen)
        self.ui.linea("")

    def cmd_revisar(self, arg: str) -> None:
        informe = Orquestador(self.llm, self.ws, self.settings, self.ui).revisar_proyecto(arg)
        self.ui.titulo("REVISIÓN")
        mostrar_markdown(self.ui, informe)

    def cmd_init(self, arg: str) -> None:
        destino = self.ws.raiz / "REAPER.md"
        if destino.exists() and not self.ui.confirmar("REAPER.md ya existe. ¿Regenerarlo?"):
            return
        res = ejecutar_subagentes([("explorador", INIT_TAREA, "")], self.llm, self.ws,
                                  self.settings, self.ui, profundidad=1)[0]
        contenido = res.resumen.strip()
        m = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*?)\n```", contenido, re.S)
        if m:
            contenido = m.group(1)
        if len(contenido) < 40:
            self.ui.error("El explorador no produjo un REAPER.md utilizable.")
            return
        cid = self.ws.checkpoints.iniciar("init REAPER.md")
        self.ws.escribir("REAPER.md", contenido.rstrip() + "\n")
        self.ws.checkpoints.descartar_si_vacio(cid)
        self.ui.ok("REAPER.md creado: los agentes lo leen en cada tarea (editalo cuando quieras).")

    # ---------------------------------------------------------------- proyecto
    def cmd_proyecto(self, arg: str) -> None:
        if not arg:
            self.ui.info(f"Proyecto activo: {self.ws.raiz}")
            return
        try:
            ruta = resolver_workspace(arg)
        except ErrorRuta as e:
            self.ui.error(str(e))
            return
        self.cambiar_workspace(ruta)
        detectado = detectar_comando_tests(self.ws)
        self.ui.ok(f"Proyecto: {self.ws.raiz}")
        self.ui.tenue(f"  {len(self.ws.archivos_codigo())} archivos de texto · tests: "
                      f"{detectado[0] if detectado else 'no detectados'}"
                      f"{' · memoria: REAPER.md' if self.ws.memoria() else ' · tip: /init crea REAPER.md'}")

    def cmd_plantillas(self, arg: str) -> None:
        filas = []
        for nombre, p in sorted(PLANTILLAS.items()):
            if arg and arg.lower() not in (nombre + " " + p.descripcion + " " + " ".join(p.etiquetas)).lower():
                continue
            filas.append([nombre, p.lenguaje, recortar(p.descripcion, 70).replace("\n", " ")])
        if not filas:
            self.ui.tenue("No hay plantillas que coincidan.")
            return
        self.ui.tabla(filas, ["plantilla", "lenguaje", "descripción"])
        self.ui.tenue("  /nuevo <plantilla> <carpeta>  ·  plantillas propias en ~/reaper/plantillas/<nombre>/")

    def cmd_nuevo(self, arg: str) -> None:
        partes = arg.split()
        if len(partes) < 2:
            self.ui.tenue("Uso: /nuevo <plantilla> <carpeta>   (mirá /plantillas)")
            return
        nombre, carpeta = partes[0], partes[1]
        destino = Path(os.path.expandvars(carpeta)).expanduser()
        if not destino.is_absolute():
            destino = (PROJECTS_DIR / destino) if not (Path.cwd() / destino).parent.exists() else (Path.cwd() / destino)
        try:
            creados = crear_desde_plantilla(nombre, destino)
        except (KeyError, FileExistsError, OSError) as e:
            self.ui.error(str(e) if not isinstance(e, KeyError) else f"No existe la plantilla {nombre} (mirá /plantillas)")
            return
        self.ui.ok(f"Proyecto creado en {destino} ({len(creados)} archivos)")
        try:
            self.cambiar_workspace(resolver_workspace(str(destino)))
        except ErrorRuta as e:
            self.ui.aviso(str(e))
            return
        plantilla = obtener_plantilla(nombre)
        if plantilla and plantilla.comando_tests:
            r = ejecutar(plantilla.comando_tests, cwd=self.ws.raiz, timeout=self.settings.tests_timeout, shell=True)
            (self.ui.ok if r.ok else self.ui.aviso)(f"tests de la plantilla: {'pasan' if r.ok else 'fallan'} "
                                                    f"({conteo_de_resultado(r).texto()})")
        if plantilla and plantilla.comando_ejecutar:
            self.ui.tenue(f"  para correrlo: {plantilla.comando_ejecutar}")

    def cmd_scan(self, arg: str) -> None:
        archivos = self.ws.archivos_codigo(limite=400)
        por_ext: dict[str, int] = {}
        for a in archivos:
            ext = Path(a).suffix or Path(a).name
            por_ext[ext] = por_ext.get(ext, 0) + 1
        self.ui.info(f"Proyecto: {self.ws.raiz}")
        self.ui.tenue("  " + " · ".join(f"{k}:{v}" for k, v in sorted(por_ext.items(), key=lambda kv: -kv[1])[:12]))
        resultados = validar_archivos(self.ws, archivos)
        malos = fallos(resultados)
        self.ui.linea(f"  validaciones: {len(resultados) - len(malos)}/{len(resultados)} OK")
        for r in malos[:25]:
            self.ui.error(r.linea()[2:])
            self.ui.tenue(recortar(r.stderr or r.stdout, 600))
        avisos = 0
        for rel in archivos:
            if rel.endswith(".py"):
                try:
                    for aviso in advertencias_python(self.ws.leer(rel))[:3]:
                        if avisos < 15:
                            self.ui.aviso(f"  ⚠ {rel}: {aviso}")
                        avisos += 1
                except (OSError, ValueError):
                    continue
        detectado = detectar_comando_tests(self.ws)
        self.ui.tenue(f"  tests: {detectado[0] if detectado else 'no detectados'}")

    def cmd_tests(self, arg: str) -> None:
        detectado = detectar_comando_tests(self.ws, completo=True)
        if not detectado:
            self.ui.aviso("No detecté una suite de tests.")
            return
        self.ui.info(f"Ejecutando {detectado[0]} ...")
        r = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        self.ui.linea(recortar((r.stdout + "\n" + r.stderr).strip(), 6000))
        conteo = conteo_de_resultado(r)
        (self.ui.ok if r.ok else self.ui.error)(
            f"tests {'OK' if r.ok else 'FALLARON'} (exit {r.codigo}) · {conteo.texto()} · {formatear_duracion(r.duracion)}")

    def cmd_validar(self, arg: str) -> None:
        rels = shlex.split(arg) if arg else self.ws.checkpoints.archivos_desde(self.ws.checkpoints.inicio_grupo() or 1)
        if not rels:
            self.ui.tenue("Uso: /validar archivo.py [otro.js ...]")
            return
        for r in validar_archivos(self.ws, rels):
            (self.ui.ok if r.ok else self.ui.error)(r.linea()[2:])
            if not r.ok:
                self.ui.tenue(recortar(r.stderr or r.stdout, 1500))

    def cmd_correr(self, arg: str) -> None:
        try:
            tokens = shlex.split(arg)
        except ValueError as e:
            self.ui.error(f"Argumentos inválidos: {e}")
            return
        if not tokens:
            self.ui.tenue("Uso: /correr archivo.py [args...]   (para programas interactivos usá !python3 archivo.py)")
            return
        try:
            ruta = self.ws.ruta(tokens[0])
        except ErrorRuta as e:
            self.ui.error(str(e))
            return
        lanzadores = {".py": [sys.executable], ".sh": ["bash"], ".js": ["node"], ".mjs": ["node"], ".cjs": ["node"]}
        if not ruta.is_file() or ruta.suffix not in lanzadores:
            self.ui.error("Archivo inexistente o tipo no ejecutable (.py .sh .js .mjs .cjs).")
            return
        rel = self.ws.rel(ruta)
        for intento in range(1, 4):
            r = ejecutar(lanzadores[ruta.suffix] + [rel] + tokens[1:], cwd=self.ws.raiz,
                         timeout=self.settings.exec_timeout)
            self.ui.linea(recortar(r.stdout.strip(), 6000))
            if r.stderr.strip():
                self.ui.aviso(recortar(r.stderr.strip(), 4000))
            self.ui.tenue(f"exit code: {r.codigo} · {formatear_duracion(r.duracion)}")
            if r.ok:
                self.ui.ok("Ejecución correcta.")
                return
            if not es_crash_real(r):
                self.ui.aviso("Terminó con error controlado (sin traceback): no lo trato como bug.")
                return
            for pista in pistas_para(r.stderr + r.stdout, 2):
                self.ui.tenue(f"  💡 {pista}")
            if intento == 3 or not self.ui.confirmar("Crash detectado. ¿Lo mando al reparador?"):
                return
            cid = self.ws.checkpoints.iniciar(f"reparar {rel}")
            tarea = (f"Al ejecutar `{r.comando}` el programa falló:\n{anexar_pistas(r.resumen(4000), 2)}\n\n"
                     f"Archivo principal: {rel}. Encontrá la causa raíz y corregila. "
                     "Podés verificar con execute_command usando el mismo comando.")
            self._pedido_actual = tarea
            ejecutar_subagentes([("reparador", tarea, rel, "", {"memoria": self.memoria,
                                                                "on_atascado": self._consultar_experto})],
                                self.llm, self.ws, self.settings, self.ui, profundidad=1, cid_inicio=cid)
            self.ws.checkpoints.descartar_si_vacio(cid)
            self.ui.info("Reintentando ejecución...")

    def cmd_vigilar(self, arg: str) -> None:
        vigilar(self.ws, self.ui, comando=arg or None, timeout=self.settings.tests_timeout)

    def cmd_diff(self, arg: str) -> None:
        cid = int(arg) if arg.isdigit() else self.ws.checkpoints.inicio_grupo()
        if cid is None:
            self.ui.tenue("No hay cambios registrados.")
            return
        diff = self.ws.checkpoints.diff_desde(cid)
        if not diff.strip():
            self.ui.tenue("El último checkpoint no tiene diferencias.")
            return
        self.ui.linea(_diffstat(diff))
        self.ui.diff(diff, max_lineas=500)

    def cmd_deshacer(self, arg: str) -> None:
        cid = int(arg) if arg.isdigit() else self.ws.checkpoints.inicio_grupo()
        if cid is None:
            self.ui.tenue("No hay nada para deshacer.")
            return
        archivos = self.ws.checkpoints.archivos_desde(cid)
        etiqueta = next((m["etiqueta"] for m in self.ws.checkpoints.listar() if m["id"] == cid), "?")
        self.ui.aviso(f"Se revierte «{etiqueta}» y todo lo posterior: {', '.join(archivos) or '(sin archivos)'}")
        if not self.ui.confirmar("¿Confirmás?"):
            return
        self._rehacer = {"etiqueta": etiqueta, "contenidos": copiar_contenidos(self.ws, archivos)}
        tocados = self.ws.checkpoints.deshacer(cid)
        indice_de(self.ws).invalidar()
        self.ui.ok(f"Revertidos {len(tocados)} archivo(s). (/rehacer los vuelve a aplicar)")

    def cmd_rehacer(self, arg: str) -> None:
        if not self._rehacer:
            self.ui.tenue("No hay nada para rehacer (solo se puede justo después de /deshacer).")
            return
        datos = self._rehacer
        cid = self.ws.checkpoints.iniciar(f"rehacer: {datos['etiqueta']}")
        aplicados = 0
        for rel, contenido in datos["contenidos"].items():
            try:
                if contenido is None:
                    if self.ws.existe(rel):
                        self.ws.borrar(rel)
                        aplicados += 1
                else:
                    self.ws.escribir(rel, contenido)
                    aplicados += 1
            except (ErrorRuta, OSError) as e:
                self.ui.aviso(f"  {rel}: {e}")
        self.ws.checkpoints.descartar_si_vacio(cid)
        self._rehacer = None
        indice_de(self.ws).invalidar()
        self.ui.ok(f"Rehechos {aplicados} archivo(s) de «{datos['etiqueta']}».")

    def cmd_checkpoints(self, arg: str) -> None:
        lista = self.ws.checkpoints.listar()
        if not lista:
            self.ui.tenue("Sin checkpoints.")
            return
        filas = []
        for m in lista[-15:]:
            grupo = f"build {m['grupo']}" if m.get("grupo") != m["id"] else ""
            filas.append([str(m["id"]), m["fecha"].replace("T", " "), str(len(m["archivos"])),
                          recortar(m["etiqueta"], 50).replace("\n", " "), grupo])
        self.ui.tabla(filas, ["id", "fecha", "arch", "etiqueta", "grupo"], "rlrll")
        self.ui.tenue("  /deshacer <id> revierte desde ese checkpoint · /diff <id> muestra sus cambios")

    # ---------------------------------------------------------------- código
    def cmd_simbolo(self, arg: str) -> None:
        if not arg:
            self.ui.tenue("Uso: /simbolo <nombre | Clase.metodo> [archivo]")
            return
        partes = arg.split()
        encontrados, sugerencias = indice_de(self.ws).buscar(partes[0], partes[1] if len(partes) > 1 else None)
        if not encontrados:
            self.ui.error(f"No encontré '{partes[0]}'." + (f" ¿{', '.join(sugerencias)}?" if sugerencias else ""))
            return
        for s in encontrados[:3]:
            self.ui.info(s.describir())
            try:
                texto = self.ws.leer(s.archivo)
            except (OSError, ValueError):
                continue
            tramo = "\n".join(texto.splitlines()[s.inicio - 1: s.fin][:200])
            self.ui.codigo(tramo, Path(s.archivo).suffix, numeros=True, desde=s.inicio)
        if len(encontrados) > 3:
            self.ui.tenue(f"  ... y {len(encontrados) - 3} coincidencias más")

    def cmd_referencias(self, arg: str) -> None:
        if not arg:
            self.ui.tenue("Uso: /referencias <nombre>")
            return
        usos = indice_de(self.ws).referencias(arg.strip())
        if not usos:
            self.ui.tenue("Sin usos fuera de su definición.")
            return
        for u in usos:
            archivo, _, resto = u.partition(": ")
            self.ui.linea(f"  {Tema.info}{archivo}{C.RESET} {resto}")

    def cmd_mapa(self, arg: str) -> None:
        if not arg:
            self.ui.tenue("Uso: /mapa <tema o pedido>")
            return
        texto = mapa_relevante(self.ws, arg, maximo=12)
        self.ui.linea(texto or "No encontré archivos relacionados.")

    def cmd_recetas(self, arg: str) -> None:
        if not arg:
            temas = collections.Counter(t for r in RECETAS for t in r.etiquetas[:1])
            self.ui.info(f"{len(RECETAS)} recetas. Temas: " + ", ".join(f"{t} ({n})" for t, n in temas.most_common(25)))
            self.ui.tenue("  /recetas <tema>  (ej: /recetas sqlite, /recetas notificacion termux)")
            return
        encontradas = buscar_recetas(arg, 4)
        if not encontradas:
            self.ui.tenue("No encontré recetas para eso.")
            return
        for r in encontradas:
            self.ui.caja([r.descripcion], titulo=f"{r.titulo} · {r.lenguaje}")
            self.ui.codigo(r.codigo, r.lenguaje)

    # ---------------------------------------------------------------- memoria
    def cmd_lecciones(self, arg: str) -> None:
        if self.memoria is None:
            self.ui.tenue("Las lecciones están desactivadas (/config lecciones true).")
            return
        partes = arg.split(maxsplit=1)
        accion = partes[0].lower() if partes else ""
        archivo = self.memoria.general if accion in ("general", "generales", "g") else self.memoria.proyecto
        if accion == "borrar" and len(partes) == 2:
            objetivo, _, numero = partes[1].rpartition(" ")
            archivo = self.memoria.general if objetivo.strip().lower().startswith("gen") else self.memoria.proyecto
            if not numero.isdigit():
                self.ui.tenue("Uso: /lecciones borrar [general] <número>")
                return
            quitada = archivo.borrar(int(numero) - 1)
            (self.ui.ok if quitada else self.ui.error)(f"Borrada: {quitada.texto}" if quitada else "Número inválido.")
            return
        if accion == "agregar" and len(partes) == 2:
            texto = partes[1]
            general = texto.lower().startswith("general ")
            if general:
                texto = texto[8:]
            hechos = self.memoria.registrar([] if general else [texto], [texto] if general else [])
            (self.ui.ok if hechos else self.ui.aviso)(hechos[0] if hechos else "No la guardé: tiene que ser concreta.")
            return
        lecciones = archivo.cargar()
        titulo = "generales (~/reaper/lecciones.md)" if archivo is self.memoria.general else f"de {self.ws.raiz.name}"
        if not lecciones:
            self.ui.tenue(f"Todavía no hay lecciones {titulo}. Se agregan solas cuando el reparador arregla fallos reales.")
            return
        self.ui.info(f"Lecciones {titulo}:")
        for i, l in enumerate(lecciones, start=1):
            self.ui.linea(f"  {Tema.tenue}{i:>2}.{C.RESET} {Tema.acento}[{l.veces}]{C.RESET} {l.texto}")
        self.ui.tenue("  /lecciones general · /lecciones borrar [general] N · /lecciones agregar [general] <texto>")

    def cmd_notas(self, arg: str) -> None:
        notas = self.ws.notas(limite=8000)
        if not notas.strip():
            self.ui.tenue("No hay notas todavía (los agentes las dejan con save_note).")
            return
        mostrar_markdown(self.ui, notas)

    def cmd_git(self, arg: str) -> None:
        accion = (arg.split() or ["estado"])[0].lower()
        if accion == "init":
            if es_repo_git(self.ws):
                self.ui.tenue("Ya es un repositorio git.")
                return
            r = inicializar_repo(self.ws)
            (self.ui.ok if r.ok else self.ui.error)(r.stdout.strip() or r.stderr.strip())
            return
        if not es_repo_git(self.ws):
            self.ui.tenue("El proyecto no es un repositorio git (o no está instalado git). /git init para crearlo.")
            return
        rama = self.settings.rama_git
        if accion in ("log", "builds"):
            self.ui.linea(log_rama(self.ws, rama))
        elif accion == "diff":
            self.ui.diff(diff_desde_snapshot(self.ws, rama), max_lineas=400)
        elif accion in ("snapshot", "guardar", "commit"):
            try:
                commit = snapshot_build(self.ws, rama, "REAPER snapshot manual")
            except RuntimeError as e:
                self.ui.error(str(e))
                return
            self.ui.ok(f"Snapshot {commit[:10]} en {rama}" if commit else "Sin cambios desde el último snapshot.")
        else:
            self.ui.linea(estado_git(self.ws))
            self.ui.tenue(f"  builds verificadas en la rama {rama}: /git log · /git diff · /git snapshot")

    def cmd_historial(self, arg: str) -> None:
        if not self.historial:
            self.ui.tenue("Sin pedidos en esta sesión.")
            return
        for hora, texto, ok in self.historial[-25:]:
            self.ui.linea(f"  {Tema.tenue}{hora}{C.RESET} {Tema.ok + '✓' if ok else Tema.error + '✗'}{C.RESET} {texto}")

    def cmd_exportar(self, arg: str) -> None:
        destino = Path(arg).expanduser() if arg else self.ws.raiz / ".reaper" / f"conversacion_{datetime.now():%Y%m%d_%H%M%S}.md"
        partes = [f"# Conversación REAPER · {self.ws.raiz.name}\n", f"Fecha: {datetime.now():%Y-%m-%d %H:%M}\n"]
        for m in self.principal.mensajes[1:]:
            quien = "Vos" if m["role"] == "user" else "REAPER"
            partes.append(f"\n## {quien}\n\n{m['content']}\n")
        try:
            escritura_atomica(destino, redactar_secretos("".join(partes)))
        except OSError as e:
            self.ui.error(f"No pude exportar: {e}")
            return
        self.ui.ok(f"Conversación exportada a {destino}")

    # ---------------------------------------------------------------- ajustes
    def cmd_todo(self, arg: str) -> None:
        if not self.principal.ctx.todo:
            self.ui.tenue("La lista de tareas está vacía.")
        for estado, texto in self.principal.ctx.todo:
            self.ui.linea(f"  {'✓' if estado == 'x' else '▸' if estado == '>' else '○'} {texto}")

    def cmd_modo(self, arg: str) -> None:
        arg = arg.strip().lower()
        if arg == "plan":
            self.modo_plan = True
            self.ui.ok("Modo plan: investigo y propongo un plan sin tocar nada; lo ejecuto cuando lo apruebes.")
            return
        if arg not in MODOS:
            actual = "plan" if self.modo_plan else self.settings.modo
            self.ui.info(f"Modo actual: {actual}  (opciones: plan, {', '.join(MODOS)})")
            return
        self.modo_plan = False
        self.settings.modo = arg
        guardar_settings(self.settings)
        self.ui.ok(f"Modo: {arg}")

    def cmd_perfil(self, arg: str) -> None:
        if not arg:
            filas = [[n, p["descripcion"]] for n, p in PERFILES.items()]
            self.ui.tabla(filas, ["perfil", "qué hace"])
            self.ui.tenue(f"  actual: torneo={self.settings.torneo} ({self.settings.candidatos} candidatos), "
                          f"tests_primero={self.settings.tests_primero}, escalar={self.settings.escalar}")
            return
        try:
            cambios = aplicar_perfil(self.settings, arg)
        except KeyError:
            self.ui.error(f"Perfil desconocido: {arg} ({', '.join(PERFILES)})")
            return
        guardar_settings(self.settings)
        self.llm.limitador = LimitadorTasa(self.settings.rpm_efectivo()) if hasattr(self.llm, "limitador") else None
        self.ui.ok(f"Perfil {arg}: " + (", ".join(cambios) or "sin cambios"))

    def cmd_tema(self, arg: str) -> None:
        if not arg:
            self.ui.info(f"Tema actual: {Tema.nombre} (opciones: {', '.join(TEMAS)})")
            return
        nombre = aplicar_tema(arg)
        self.settings.tema = nombre
        guardar_settings(self.settings)
        self.ui.ok(f"Tema: {nombre}")

    def cmd_modelo(self, arg: str) -> None:
        partes = arg.split()
        if not partes:
            self.ui.info(f"Modelo principal: {self.settings.modelo}")
            for rol, modelo in self.settings.modelos_rol.items():
                self.ui.tenue(f"  {rol}: {resolver_modelo(modelo)}")
            self.ui.tenue(f"  escalada: {resolver_modelo(self.settings.modelo_fuerte)}")
            return
        # Ω §5.1: solo /modelo <alias> o /modelo <rol> <alias> con rol conocido. Nada más se guarda.
        if len(partes) == 1:
            self.settings.modelo = resolver_modelo(partes[0])
            self.ui.ok(f"Modelo principal: {self.settings.modelo} (NO VERIFICADO; /equipo probar para confirmar)")
            guardar_settings(self.settings)
            return
        if len(partes) == 2 and partes[0].lower() in ROLES:
            rol = partes[0].lower()
            if partes[1] in ("-", "default", "ninguno"):
                self.settings.modelos_rol.pop(rol, None)
            else:
                self.settings.modelos_rol[rol] = resolver_modelo(partes[1])
            self.ui.ok(f"{rol} → {self.settings.modelo_para(rol)}")
            guardar_settings(self.settings)
            return
        # entrada inválida: NO guardar nada (antes guardaba partes[0] como modelo e ignoraba el resto)
        if len(partes) == 2:
            self.ui.error(f"Rol desconocido: '{partes[0]}'. Roles válidos: {', '.join(sorted(ROLES))}.")
            self.ui.tenue("  Uso: /modelo <alias>  ·  /modelo <rol> <alias>  (si el alias lleva espacios, no se admite)")
        else:
            self.ui.error("Uso: /modelo [<alias>] | /modelo <rol> <alias>. Demasiados argumentos; no guardé nada.")

    def cmd_modelo_fuerte(self, arg: str) -> None:
        if not arg:
            self.ui.info(f"Modelo de escalada: {resolver_modelo(self.settings.modelo_fuerte)} "
                         f"({'activada' if self.settings.escalar else 'desactivada'}; umbral {self.settings.umbral_escalada})")
            self.ui.tenue("  /modelo-fuerte <alias>  ·  /modelo-fuerte off  ·  /config umbral_escalada N")
            self.ui.linea(self.escalador.resumen())
            return
        if arg.lower() in ("off", "no", "ninguno"):
            self.settings.escalar = False
            self.ui.ok("Escalada desactivada.")
        else:
            self.settings.modelo_fuerte = arg
            self.settings.escalar = True
            self.ui.ok(f"Modelo de escalada: {resolver_modelo(arg)}")
        guardar_settings(self.settings)

    def cmd_modelos(self, arg: str) -> None:
        partes = (arg or "").split(maxsplit=1)
        sub = partes[0].lower() if partes else ""
        resto = partes[1].strip() if len(partes) > 1 else ""
        if sub in ("descubrir", "catalogo", "catálogo", "gratis", "sincronizar", "sync"):
            cat = CatalogoModelos()
            if sub in ("sincronizar", "sync"):
                if not resto:
                    self.ui.error("Uso: /modelos sincronizar <archivo.md>  (parsea un directorio Markdown LOCAL)")
                    return
                try:
                    texto = self.ws.leer(self.ws.rel(self.ws.ruta(resto)))
                except (OSError, ValueError, ErrorRuta):
                    self.ui.error(f"No pude leer {resto}.")
                    return
                n = cat.sincronizar_desde_markdown(texto, source_url=resto, source_version="local")
                self.ui.ok(f"Catálogo actualizado: {n} ficha(s) normalizada(s) desde {resto}.")
                self.ui.tenue("  Estados: todas 'unverified'. La verificación real requiere peticiones con claves.")
                return
            if sub == "gratis":
                libres = cat.gratis_verificados()
                if not libres:
                    self.ui.info("Ningún modelo con coste cero VERIFICADO todavía.")
                    self.ui.tenue("  Que un directorio diga ':free' no basta: hay que confirmarlo con la cuenta.")
                    return
                for f in libres:
                    self.ui.info(f"  {f.provider}/{f.model_id}  (free verificado)")
                return
            fichas = cat.fichas()
            self.ui.info(f"Catálogo descubierto ({cat.estado()}):")
            if not fichas:
                self.ui.tenue("  Vacío. Poblalo con /modelos sincronizar <archivo.md> (directorio comunitario).")
                return
            for f in fichas[:40]:
                ctx = f.context_tokens if f.context_tokens is not None else "?"
                self.ui.info(f"  {f.provider or '?'}/{f.model_id}  ctx={ctx}  [{f.status}]")
            meta = cat.meta()
            self.ui.tenue(f"  fuente: {meta.get('source_url', '—')} · confianza: {meta.get('confidence', '—')} "
                          f"· obtenido: {meta.get('retrieved_at', '—')}")
            return
        filas = [[alias, info.nivel, (info.proveedor or self.settings.proveedor), formatear_numero(info.contexto),
                  info.id, info.nota] for alias, info in INFO_MODELOS.items()]
        self.ui.tabla(filas, ["alias", "nivel", "proveedor", "contexto", "id", "nota"], "lllrll")
        activos = proveedores_de(self.settings)
        if len(activos) > 1:
            self.ui.info("  Proveedores en uso esta sesión: "
                         + "; ".join(f"{p} ({', '.join(ms)})" for p, ms in activos.items()))
        self.ui.tenue("  /modelos descubrir · /modelos gratis · /modelos sincronizar <archivo.md>")

    def cmd_pentest(self, arg: str) -> None:
        arg = arg.strip()
        if arg.lower() in ("off", "no", "0", "stop", "salir", "apagar"):
            self.settings.modo_seguridad = False
            guardar_settings(self.settings)
            self.ui.ok("Modo seguridad DESACTIVADO. REAPER vuelve al comportamiento normal.")
            return
        if not arg:
            if self.settings.modo_seguridad and self.settings.alcance_autorizado:
                self.ui.info(f"Modo seguridad ACTIVO (pentest/CTF/lab).")
                self.ui.info(f"  Alcance autorizado: {self.settings.alcance_autorizado}")
            else:
                self.ui.info("Modo seguridad apagado.")
            self.ui.tenue("  Activar: /pentest <alcance autorizado>")
            self.ui.tenue("    ej: /pentest lab propio 10.0.0.0/24  ·  /pentest CTF HackTheBox 'Blue'")
            self.ui.tenue("  Apagar: /pentest off   (los bloqueos que protegen tu equipo siguen siempre activos)")
            return
        self.settings.alcance_autorizado = arg
        self.settings.modo_seguridad = True
        guardar_settings(self.settings)
        self.ui.ok("Modo seguridad ACTIVADO (pentest / CTF / lab / estudio).")
        self.ui.info(f"  Alcance autorizado: {arg}")
        self.ui.aviso("  REAPER hará trabajo ofensivo SOLO dentro de ese alcance. Fuera de ahí, frena y avisa.")
        self.ui.tenue("  Seguís protegido: sudo, rm -rf, apagar el equipo y leer .env siguen bloqueados.")

    def cmd_privacidad(self, arg: str) -> None:
        """Reporte de privacidad y modo estricto. No revela datos sensibles."""
        partes = (arg or "").split()
        sub = partes[0].lower() if partes else "reporte"
        if sub in ("estricto", "strict"):
            valor = len(partes) > 1 and partes[1].lower() in ("on", "si", "sí", "1", "true")
            self.settings.privacidad_estricta = valor
            guardar_settings(self.settings)
            self.ui.ok(f"Privacidad estricta: {'ON' if valor else 'OFF'}.")
            if valor:
                self.ui.tenue("  Evitá modelos externos para contenido sensible; preferí un proveedor local (ollama).")
            return
        self.ui.linea(texto_reporte_privacidad(reporte_privacidad(self.llm, self.settings)))

    def cmd_equipo(self, arg: str) -> None:
        """Muestra los seis roles → proveedor/modelo asignado + independencia real. Conectividad NO VERIFICADA."""
        sub = (arg or "").strip().lower()
        estado = estado_equipo(self.settings)
        ind = independencia_equipo(estado)
        if sub in ("independencia", "independence"):
            self.ui.info(f"Proveedores distintos: {ind['proveedores_distintos']} · "
                         f"modelos distintos: {ind['modelos_distintos']}")
            if ind["reducida"]:
                self.ui.aviso("  Independencia REDUCIDA: todos los roles caen en un solo proveedor.")
            return
        if sub == "auto":
            asignacion, motivo = autoasignar_equipo_free(self.settings)
            if not asignacion:
                self.ui.aviso(f"  No pude autoconfigurar modelos free: {motivo}.")
                self.ui.tenue("  Configurá un proveedor free: export GROQ_API_KEY=... (o NVIDIA/GEMINI/OpenRouter).")
            else:
                self.settings.modelos_rol.update(asignacion)
                guardar_settings(self.settings)
                self.ui.ok("Equipo autoconfigurado con modelos free potentes (conectividad NO VERIFICADA).")
                estado = estado_equipo(self.settings)
                ind = independencia_equipo(estado)
        if sub == "probar":
            self.ui.info("Probando cada rol con una petición mínima real (puede consumir cuota)...")
            resultados = probar_equipo(self.llm, self.settings)
            simbolos = {"RESPONDE": "✓", "SIN_CLAVE": "⚠", "FALLA": "✗"}
            for r in resultados:
                self.ui.info(f"  {simbolos.get(r['estado'], '?')} {r['rol']:<13} {r['proveedor']}/{r['modelo']}  "
                             f"{r['estado']} ({r['detalle']})")
            responden = [r for r in resultados if r["estado"] == "RESPONDE"]
            provs = {r["proveedor"] for r in responden}
            modelos = {r["modelo"] for r in responden}
            self.ui.ok(f"Agentes que RESPONDEN: {len(responden)}/6 · "
                       f"proveedores distintos: {len(provs)} · modelos distintos: {len(modelos)}")
            if not responden:
                self.ui.aviso("  Ninguno respondió: configurá una clave (ej. export GROQ_API_KEY=...) y reintentá.")
            return
        self.ui.info("Equipo de seis roles (asignación actual; conectividad NO VERIFICADA):")
        for e in estado:
            marca = "✓ clave" if e["tiene_clave"] else "⚠ FALTA CLAVE"
            self.ui.info(f"  {e['rol']:<13} → {e['proveedor']}/{e['modelo']}   {marca}")
        self.ui.tenue(f"  proveedores distintos: {ind['proveedores_distintos']} · "
                      f"modelos distintos: {ind['modelos_distintos']}"
                      + ("  · independencia REDUCIDA" if ind["reducida"] else ""))
        self.ui.tenue("  Asignar por rol: /modelo <rol> <alias> · prueba real: /proveedores probar")

    def cmd_proveedores(self, arg: str) -> None:
        """Estado de proveedores SIN exponer secretos. Las claves salen de env o .clave_<proveedor>."""
        sub = (arg or "").strip().lower()
        if sub in ("", "estado", "status", "diagnostico"):
            self.ui.info("Proveedores (las claves nunca se muestran):")
            configurados = 0
            for prov, datos in PROVEEDORES.items():
                var = datos["clave"]
                if not var:
                    estado = "SIN CLAVE (no requiere)"
                else:
                    tmp = replace(self.settings, proveedor=prov)
                    tiene = bool(clave_de_proveedor(prov, tmp))
                    configurados += int(tiene)
                    estado = "CONFIGURADO" if tiene else "FALTA CLAVE"
                activo = " ← activo" if prov == self.settings.proveedor else ""
                self.ui.info(f"  {prov:<14} {estado:<22} [{var or '—'}]{activo}")
            self.ui.tenue(f"  {configurados} proveedor(es) con credencial. Configurá con: export <VAR>=...  (una vez)")
            if sub == "diagnostico":
                disy = getattr(self.llm, "disyuntor", None)
                if disy is not None:
                    self.ui.tenue("  disyuntor: " + disy.resumen())
            return
        if sub == "configurar":
            self.ui.info("Onboarding de credenciales (una sola vez, fuera del chat):")
            self.ui.tenue("  REAPER no pide claves en el chat ni las guarda en el repo. Opciones:")
            self.ui.tenue("    1) export GROQ_API_KEY=...  (variable de entorno por proveedor)")
            self.ui.tenue("    2) archivo ~/reaper/.clave_<proveedor> con permisos 0600")
            self.ui.tenue("  Una clave NUNCA se comparte entre proveedores. Luego: /proveedores")
            return
        if sub in ("probar", "sincronizar"):
            candidatos = [p for p, d in PROVEEDORES.items()
                          if d["clave"] and clave_de_proveedor(p, replace(self.settings, proveedor=p))]
            self.ui.info(f"Proveedores con credencial para probar: {', '.join(candidatos) or 'ninguno'}")
            self.ui.aviso("  La prueba de conectividad real / catálogo vivo hace peticiones autorizadas; "
                          "hasta ejecutarse con tu consentimiento y claves válidas: NO VERIFICADO.")
            return
        self.ui.error("Uso: /proveedores [estado|configurar|probar|sincronizar|diagnostico]")

    def cmd_forge(self, arg: str) -> None:
        """Tool Forge: REAPER crea/registra sus propias herramientas (gate real: tests deben pasar)."""
        partes = (arg or "").split(maxsplit=1)
        sub = partes[0].lower() if partes else "listar"
        resto = partes[1].strip() if len(partes) > 1 else ""
        forja = ForjaHerramientas(self.ws.raiz)
        if sub in ("listar", "list", "catalogo", ""):
            tools = forja.catalogo.listar()
            if not tools:
                self.ui.info("Catálogo de herramientas vacío. Probá /forge demo.")
                return
            for m in tools:
                self.ui.info(f"  {m.id} v{m.version} [{m.estado}/{m.verificacion}] "
                             f"caps={','.join(m.capabilities) or '—'} — {recortar(m.resumen, 70)}")
            self.ui.tenue("  /forge verificar <id> · /forge ejecutar <id> [archivo]")
            return
        if sub in ("demo", "crear-demo"):
            m, recibo = forja.crear(manifiesto_demo(), _FORGE_DEMO_CODIGO, _FORGE_DEMO_TEST)
            self.ui.info(f"Forjada {m.id} v{m.version} → {m.estado} ({m.verificacion}); tests: {m.tests_resultado}")
            self.ui.tenue(f"  code_hash: {m.code_hash[:16]}… · recibo {recibo.run_id} exit {recibo.exit_code}")
            if m.disponible():
                muestra = forja.catalogo.dir / "demo_input.py"
                muestra.write_text("DEBUG = True\n", encoding="utf-8")
                r2 = forja.ejecutar(m.id, [str(muestra)])
                self.ui.ok(f"Reutilización real de la herramienta → {r2.stdout_preview.strip()} (exit {r2.exit_code})")
            return
        if sub in ("verificar", "info") and resto:
            m = forja.catalogo.obtener(resto)
            if m is None:
                self.ui.error(f"No existe la herramienta {resto}.")
                return
            self.ui.linea(resaltar_codigo(json.dumps(m.como_dict(), ensure_ascii=False, indent=2), "json"))
            return
        if sub in ("ejecutar", "run") and resto:
            p = resto.split(maxsplit=1)
            try:
                r = forja.ejecutar(p[0], [p[1]] if len(p) > 1 else [])
                self.ui.info(f"{r.stdout_preview.strip()} (exit {r.exit_code})")
            except ValueError as e:
                self.ui.error(str(e))
            return
        self.ui.error("Uso: /forge listar | demo | verificar <id> | ejecutar <id> [archivo]")

    def cmd_entregar(self, arg: str) -> None:
        """Copia un archivo del proyecto al almacenamiento de Android y VERIFICA la llegada (sha256). No usa mv."""
        partes = (arg or "").split()
        seco = "--dry-run" in partes or "--seco" in partes
        partes = [p for p in partes if not p.startswith("--")]
        if not partes:
            self.ui.error("Uso: /entregar <archivo> [destino]  (copia verificada; --dry-run para simular)")
            return
        try:
            origen = Path(self.ws.ruta(partes[0]))
        except (ErrorRuta, ValueError) as e:
            self.ui.error(f"No encuentro {partes[0]}: {e}")
            return
        if not origen.is_file():
            self.ui.error(f"{partes[0]} no es un archivo.")
            return
        if len(partes) > 1:                     # destino explícito del usuario
            elegido = Path(partes[1]).expanduser()
            # dir si: ya existe como dir, termina en separador, o no tiene extensión de archivo
            es_dir = elegido.is_dir() or partes[1].endswith(("/", os.sep)) or not elegido.suffix
            destino = (elegido / origen.name) if es_dir else elegido
            externo = True
        else:
            destino, externo = ruta_destino_android(origen.name)
        if seco:
            self.ui.info(f"[dry-run] copiaría {origen} → {destino} (externo={externo}); no escribo nada.")
            return
        recibo = entregar_archivo(origen, destino, externo=externo, journal=JournalEntregas())
        self.ui.linea(recibo.texto())
        if recibo.verified and not externo:
            self.ui.tenue("  (sin acceso a /sdcard: quedó en la carpeta interna de REAPER; compartila desde ahí)")
        if recibo.verified:
            self.ui.ok(f"Entregado y verificado en: {recibo.destination}")

    def cmd_muestra(self, arg: str) -> None:
        """Análisis ESTÁTICO de una muestra local (hashes, formato, entropía, strings, IOCs). No la ejecuta."""
        ruta = (arg or "").strip()
        if not ruta:
            self.ui.error("Uso: /muestra <archivo>  (análisis estático; la muestra NUNCA se ejecuta)")
            return
        try:
            datos = Path(self.ws.ruta(ruta)).read_bytes()
        except (OSError, ValueError, ErrorRuta) as e:
            self.ui.error(f"No pude leer {ruta}: {e}")
            return
        info = analizar_muestra(datos, ruta)
        self.ui.info(f"Muestra {info['nombre']} · {info['tamano']} bytes · {info['formato']} · entropía {info['entropia']}")
        self.ui.tenue(f"  sha256: {info['sha256']}")
        self.ui.tenue(f"  md5: {info['md5']} · sha1: {info['sha1']}")
        if info["urls"]:
            self.ui.info("  URLs embebidas: " + ", ".join(info["urls"][:5]))
        if info["apis_sospechosas"]:
            self.ui.info("  APIs/cadenas sensibles: " + ", ".join(info["apis_sospechosas"][:10]))
        self.ui.linea(resumen_hallazgos(info["hallazgos"]))
        self.ui.tenue("  " + info["nota"])

    def cmd_ejecutar(self, arg: str) -> None:
        """Corre un comando LOCAL por el ExecutionBroker y muestra el recibo de evidencia (hash + git-rev + veredicto)."""
        if not arg.strip():
            self.ui.error("Uso: /ejecutar <comando>  (ejecución local con recibo; sin red salvo scope válido)")
            return
        try:
            argv = shlex.split(arg)
        except ValueError as e:
            self.ui.error(f"No pude parsear el comando: {e}")
            return
        broker = BrokerEjecucion(raiz=self.ws.raiz)
        recibo = broker.ejecutar(SolicitudEjecucion(argv=argv, cwd=str(self.ws.raiz), timeout_s=60))
        self.ui.info(f"Recibo {recibo.run_id} · veredicto: {recibo.veredicto_alcance} · exit: {recibo.exit_code}")
        if recibo.stdout_preview:
            self.ui.linea(recibo.stdout_preview.rstrip())
        if recibo.stderr_preview:
            self.ui.tenue(recibo.stderr_preview.rstrip())
        self.ui.tenue(f"  stdout sha256: {recibo.stdout_hash[:16]}… · git: {recibo.git_revision[:12] or '—'}")

    def cmd_lab(self, arg: str) -> None:
        """Lab Challenge Engine: desafíos sintéticos locales con juez independiente (offline, sin objetivos externos)."""
        partes = (arg or "").split(maxsplit=1)
        sub = partes[0].lower() if partes else "escenarios"
        resto = partes[1].strip() if len(partes) > 1 else ""
        motor = MotorLab(self.ws.raiz)
        if sub in ("escenarios", "list", "listar", ""):
            self.ui.info("Escenarios de laboratorio (fixtures sintéticos, datos inventados):")
            for e in motor.listar():
                tag = "control" if e["control"] else e["kind"]
                self.ui.info(f"  {e['id']} v{e['version']} [{tag}] — {e['descripcion']}")
            self.ui.tenue("  /lab iniciar <id> · /lab probar <id> · /lab informe <id> · /lab reiniciar <id>")
            return
        if not resto:
            self.ui.error(f"Uso: /lab {sub} <scenario-id>  (ver /lab escenarios)")
            return
        try:
            if sub in ("iniciar", "start"):
                info = motor.iniciar(resto)
                self.ui.ok(f"Fixture materializado en {info['dir']}")
                self.ui.info(f"  scope: {info['scope'].scope_id} (isolated_lab) · fixture: {info['fixture_hash'][:16]}…")
            elif sub in ("probar", "test", "evaluar"):
                motor.iniciar(resto)
                res = motor.evaluar(resto, resolver_con_auditor(resto))
                self.ui.linea(res.texto())
            elif sub in ("informe", "report"):
                motor.iniciar(resto)
                res = motor.evaluar(resto, resolver_con_auditor(resto))
                self.ui.linea(resaltar_codigo(json.dumps(res.como_dict(), ensure_ascii=False, indent=2), "json"))
            elif sub in ("reiniciar", "restaurar", "reset"):
                self.ui.ok("Fixture borrado (reset)." if motor.reiniciar(resto) else "No había fixture que borrar.")
            else:
                self.ui.error(f"Subcomando /lab desconocido: {sub} (escenarios|iniciar|probar|informe|reiniciar)")
        except ValueError as e:
            self.ui.error(str(e))

    def cmd_auditar(self, arg: str) -> None:
        """Auditoría ESTÁTICA offline de un archivo/proyecto local (config insegura + dependencias). No toca la red."""
        objetivo = (arg or "").strip() or "."
        hallazgos = []
        try:
            rel = self.ws.rel(self.ws.ruta(objetivo))
            archivos = [rel]
        except (ErrorRuta, ValueError, OSError):
            archivos = []
        if not archivos:
            self.ui.error(f"No pude abrir {objetivo} en el workspace.")
            return
        for rel in archivos:
            try:
                texto = self.ws.leer(rel)
            except (OSError, ValueError, ErrorRuta):
                continue
            hallazgos += auditar_config(texto, rel)
            if rel.endswith(("requirements.txt", "requirements.lock")):
                hallazgos += analizar_dependencias(texto, rel)
        self.ui.info(f"Auditoría estática de {objetivo} (offline, sin red):")
        self.ui.linea(resumen_hallazgos(hallazgos))

    def cmd_analizar(self, arg: str) -> None:
        """Importa y analiza resultados de escaneos YA guardados (offline). Hoy: nmap XML."""
        partes = (arg or "").split(maxsplit=1)
        if len(partes) < 2:
            self.ui.error("Uso: /analizar nmap <archivo.xml>  (analiza un resultado guardado; no ejecuta escaneos)")
            return
        tipo, ruta = partes[0].lower(), partes[1].strip()
        try:
            texto = self.ws.leer(self.ws.rel(self.ws.ruta(ruta)))
        except (OSError, ValueError, ErrorRuta):
            self.ui.error(f"No pude abrir {ruta}.")
            return
        if tipo == "nmap":
            try:
                inv = importar_nmap_xml(texto)
            except ValueError as e:
                self.ui.error(str(e))
                return
            for h in inv["hosts"]:
                abiertos = [p for p in h["puertos"] if p["estado"] == "open"]
                self.ui.info(f"  {h['host']}: {len(abiertos)} puerto(s) abierto(s)")
                for p in abiertos:
                    self.ui.tenue(f"    {p['puerto']}/{p['protocolo']} {p['servicio']}")
        else:
            self.ui.error(f"Analizador '{tipo}' no disponible. Hoy: nmap (XML guardado).")

    def cmd_desempeno(self, arg: str) -> None:
        if getattr(self, "desempeno", None) is None:
            self.ui.info("No hay memoria de desempeño en esta sesión.")
            return
        self.ui.info("Desempeño por rol (tasa de éxito verificado; el router elige el mejor):")
        self.ui.linea(self.desempeno.resumen(arg.strip().lower() or None))
        self.ui.tenue("  el router usa esto cuando router_aprendido está activo (/config router_aprendido)")

    def cmd_config(self, arg: str) -> None:
        if not arg:
            self.ui.linea(resaltar_codigo(json.dumps(self.settings.to_dict(), ensure_ascii=False, indent=2), "json"))
            self.ui.tenue(f"  archivo: {CONFIG_FILE} · cambiar: /config <clave> <valor>")
            return
        partes = arg.split(maxsplit=1)
        if len(partes) != 2 or not hasattr(self.settings, partes[0]):
            claves = [f.name for f in fields(Settings)]
            parecida = difflib.get_close_matches(partes[0], claves, n=1)
            self.ui.error("Uso: /config <clave> <valor>  (ej: /config paralelo 3)"
                          + (f" · ¿{parecida[0]}?" if parecida else ""))
            return
        clave, texto = partes
        actual = getattr(self.settings, clave)
        try:
            if isinstance(actual, bool):
                valor = texto.lower() in ("1", "true", "si", "sí", "s", "on")
            elif isinstance(actual, int):
                valor = int(texto)
            elif isinstance(actual, float):
                valor = float(texto)
            elif isinstance(actual, (list, dict)):
                valor = json.loads(texto)
                if not isinstance(valor, type(actual)):
                    raise ValueError(f"se esperaba {type(actual).__name__}")
            else:
                valor = texto
        except ValueError as e:
            self.ui.error(f"Valor inválido: {e}")
            return
        setattr(self.settings, clave, valor)
        self.settings.validar()
        if clave == "tema":
            aplicar_tema(self.settings.tema)
        if clave in ("rpm", "modelo") and hasattr(self.llm, "limitador"):
            self.llm.limitador = LimitadorTasa(self.settings.rpm_efectivo())
        guardar_settings(self.settings)
        self.ui.ok(f"{clave} = {getattr(self.settings, clave)!r}")

    def cmd_uso(self, arg: str) -> None:
        u = self.llm.uso
        self.ui.info(u.resumen())
        if u.por_modelo:
            filas = [[m, str(d.llamadas), formatear_numero(d.tokens_entrada), formatear_numero(d.tokens_salida),
                      f"${d.costo:.4f}" if d.costo else "-", formatear_duracion(d.segundos)]
                     for m, d in u.por_modelo.items()]
            self.ui.tabla(filas, ["modelo", "llamadas", "entrada", "salida", "costo", "tiempo"], "lrrrrr")
        if u.por_rol:
            self.ui.tenue("  por rol: " + ", ".join(f"{r}: {d['llamadas']}" for r, d in sorted(u.por_rol.items())))
        disyuntor = getattr(self.llm, "disyuntor", None)
        if disyuntor is not None:
            resumen = disyuntor.resumen()
            if "operativos" not in resumen:
                self.ui.aviso("  disyuntor: " + resumen)
        if self.settings.costo_maximo:
            self.ui.barra("presupuesto", u.costo, self.settings.costo_maximo)

    def cmd_contexto(self, arg: str) -> None:
        mensajes = self.principal.mensajes
        tokens = tokens_mensajes(mensajes)
        limite = self.settings.contexto_tokens
        self.ui.info(f"Contexto del agente principal: ~{formatear_numero(tokens)} de {formatear_numero(limite)} tokens "
                     f"({len(mensajes)} mensajes)")
        self.ui.barra("uso", tokens, limite)
        self.ui.tenue("  /compactar resume la conversación · /reset la vacía")

    def cmd_compactar(self, arg: str) -> None:
        antes = tokens_mensajes(self.principal.mensajes)
        self.principal._factor_contexto = 0.5
        self.principal._compactar(forzar=True)
        self.principal._factor_contexto = 1.0
        despues = tokens_mensajes(self.principal.mensajes)
        self.ui.ok(f"Contexto: {formatear_numero(antes)} → {formatear_numero(despues)} tokens")
        self._guardar_sesion()

    def cmd_reset(self, arg: str) -> None:
        self.principal = self._nuevo_principal()
        try:
            self._ruta_sesion().unlink()
        except OSError:
            pass
        self.ui.aviso("Conversación reiniciada (los archivos y checkpoints no se tocan).")

    def cmd_estado(self, arg: str) -> None:
        detectado = detectar_comando_tests(self.ws)
        lecciones = (len(self.memoria.proyecto.cargar()), len(self.memoria.general.cargar())) if self.memoria else (0, 0)
        lineas = [
            f"proyecto:   {self.ws.raiz}",
            f"modelo:     {self.settings.modelo}",
            f"escalada:   {resolver_modelo(self.settings.modelo_fuerte) if self.settings.escalar else 'desactivada'}",
            f"modo:       {self.settings.modo} · paralelo {self.settings.paralelo}",
            f"torneo:     {'sí, ' + str(self.settings.candidatos) + ' candidatos' if self.settings.torneo else 'no'}"
            f" · tests primero: {'sí' if self.settings.tests_primero else 'no'}",
            f"memoria:    {len(self.principal.mensajes)} mensajes · checkpoints: {len(self.ws.checkpoints.ids())}",
            f"lecciones:  {lecciones[0]} del proyecto · {lecciones[1]} generales",
            f"tests:      {detectado[0] if detectado else 'no detectados'}",
            f"git:        {'sí' if es_repo_git(self.ws) else 'no'}",
        ]
        self.ui.caja(lineas, titulo="ESTADO REAPER")

    def cmd_doctor(self, arg: str) -> None:
        diagnostico_sistema(self.ui, self.settings, self.llm)

    def cmd_instalar(self, arg: str) -> None:
        instalar_lanzador(self.ui)

    def cmd_dragon(self, arg: str) -> None:
        if arg.strip().lower() == "png":
            ruta = dragon_png(self.ws.raiz / "reaper_dragon.png")
            self.ui.ok(f"Dragón exportado a {ruta}")
            return
        if not animar_intro():
            self.ui.linea(banner_dragon())

    def cmd_evaluar(self, arg: str) -> None:
        partes = arg.split()
        if partes and partes[0] in ("comportamiento", "conducta", "c"):
            correr_comportamiento(self.llm, self.settings, self.ui, ids=partes[1:])
            return
        if partes and not partes[0].isdigit():
            correr_evaluacion(self.llm, self.settings, self.ui, ids=partes)
            return
        cantidad = int(arg) if arg.isdigit() else 0
        correr_evaluacion(self.llm, self.settings, self.ui, cantidad=cantidad or None)

    def shell(self, comando: str) -> None:
        if not comando.strip():
            return
        try:
            subprocess.run(comando, shell=True, cwd=str(self.ws.raiz))
        except OSError as e:
            self.ui.error(str(e))

    # ------------------------------------------------------------ REPL
    def _configurar_readline(self) -> None:
        try:
            import readline
        except ImportError:  # pragma: no cover - depende de la plataforma
            return
        try:
            HISTORIAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            if HISTORIAL_FILE.exists():
                readline.read_history_file(str(HISTORIAL_FILE))
            readline.set_history_length(1000)
        except (OSError, AttributeError):
            pass
        comandos = self.nombres_comandos()

        def completar(texto: str, estado: int) -> Optional[str]:
            buffer = readline.get_line_buffer()
            if buffer.startswith("/") and " " not in buffer:
                opciones = [c for c in comandos if c.startswith(texto)]
            else:
                base = texto.lstrip("@")
                prefijo = "@" if texto.startswith("@") else ""
                opciones = [prefijo + r for r in self.ws.archivos_codigo(limite=800) if r.startswith(base)][:50]
            return opciones[estado] if estado < len(opciones) else None

        try:
            readline.set_completer(completar)
            readline.set_completer_delims(" \t\n")
            readline.parse_and_bind("tab: complete")
        except (AttributeError, ValueError):
            pass

    def _guardar_historial_readline(self) -> None:
        try:
            import readline
            readline.write_history_file(str(HISTORIAL_FILE))
        except (ImportError, OSError, AttributeError):
            pass

    def _leer_entrada(self) -> str:
        marca = f"{Tema.aviso}[plan] {C.RESET}" if self.modo_plan else ""
        entrada = input(f"{marca}{Tema.prompt}{C.BOLD}vos ›{C.RESET} ")
        if entrada.strip() != '"""':
            return entrada.strip()
        lineas = []
        while True:
            linea = input(f"{Tema.herramienta}│ {C.RESET}")
            if linea.strip() == '"""':
                return "\n".join(lineas).strip()
            lineas.append(linea)

    def mostrar_inicio(self, animar: bool = True) -> None:
        if not (animar and self.settings.animacion and animar_intro()):
            self.ui.linea(banner_dragon())
        detectado = detectar_comando_tests(self.ws)
        funciones = []
        if self.settings.tests_primero:
            funciones.append("tests primero")
        if self.settings.torneo and self.settings.candidatos > 1:
            funciones.append(f"torneo ×{self.settings.candidatos}")
        if self.escalador.disponible():
            funciones.append(f"escalada→{self.settings.modelo_fuerte}")
        if self.settings.lecciones:
            funciones.append("lecciones")
        modelo_corto = self.settings.modelo.split("/")[-1]
        lineas = [
            f"{Tema.tenue}proyecto{C.RESET}  {self.ws.raiz}",
            f"{Tema.tenue}modelo{C.RESET}    {modelo_corto} · modo {self.settings.modo}",
            f"{Tema.tenue}equipo{C.RESET}    {' · '.join(funciones) or 'básico'}",
            f"{Tema.tenue}agentes{C.RESET}   {resumen_arranque_equipo(self.settings)}",
            f"{Tema.tenue}tests{C.RESET}     {detectado[0].split()[-1] if detectado else 'no detectados'}",
        ]
        if self.aviso_sesion:
            lineas.append(f"{Tema.tenue}sesión{C.RESET}    {self.aviso_sesion}")
        self.ui.linea("")
        self.ui.caja(lineas, color=C.VIOLETA)
        self.ui.tenue("  escribí lo que necesitás · /ayuda · /construir <pedido> · @archivo para adjuntar\n")

    def repl(self, animar: bool = True) -> int:
        self._configurar_readline()
        self.mostrar_inicio(animar)
        if self.settings.hooks:
            for r in ejecutar_hooks(self.ws, "al_iniciar", {"proyecto": str(self.ws.raiz)}):
                (self.ui.tenue if r.ok else self.ui.aviso)(f"  hook al_iniciar: {r.comando} → {'ok' if r.ok else r.salida[-200:]}")
        while True:
            try:
                entrada = self._leer_entrada()
            except (EOFError, KeyboardInterrupt):
                self.ui.linea("")
                self.cmd_salir("")
                self._guardar_historial_readline()
                return 0
            if not entrada:
                continue
            CANCELAR.clear()
            try:
                if entrada.startswith("!"):
                    self.shell(entrada[1:])
                elif entrada.startswith("/"):
                    if self.comando(entrada) == "salir":
                        self._guardar_historial_readline()
                        return 0
                else:
                    self.turno(entrada)
            except (KeyboardInterrupt, Cancelado):
                CANCELAR.set()
                self.ui.fin_progreso()
                self.ui.aviso("\n⏹ Interrumpido. Lo ya escrito queda en disco; /diff para ver, /deshacer para revertir.")
                self._guardar_sesion()
            except LLMError as e:
                self.ui.error(f"Modelo: {e}")
                for pista in pistas_para(str(e), 1):
                    self.ui.tenue(f"  💡 {pista}")
            except ErrorRuta as e:
                self.ui.error(str(e))
            finally:
                self._guardar_historial_readline()
