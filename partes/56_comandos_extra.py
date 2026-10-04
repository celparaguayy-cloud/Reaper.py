"""
Comandos extra del REPL (se agregan a App sin tocar la CLI base):
/explicar /testear /documentar /renombrar /web /commit /deps /estadisticas
/sesiones /comandos /plugins /hooks
"""

PROMPT_EXPLICAR = """Explicá este código en español, para alguien que programa pero no lo escribió.
Estructura: 1) qué hace en una frase, 2) cómo funciona paso a paso, 3) entradas/salidas y casos borde,
4) posibles problemas o mejoras (solo si son reales). Sé concreto y breve.

{titulo}
```{lenguaje}
{codigo}
```"""


def _codigo_para_explicar(app: "App", objetivo: str) -> tuple[str, str, str]:
    """(título, lenguaje, código) de un archivo o un símbolo."""
    try:
        ruta = app.ws.ruta(objetivo)
        if ruta.is_file():
            rel = app.ws.rel(ruta)
            lineas = app.ws.leer(rel).splitlines()
            extra = f"\n# ... ({len(lineas) - 400} líneas más)" if len(lineas) > 400 else ""
            return f"Archivo {rel} ({len(lineas)} líneas)", lenguaje_de(rel), "\n".join(lineas[:400]) + extra
    except (ErrorRuta, OSError, ValueError):
        pass
    encontrados, sugerencias = indice_de(app.ws).buscar(objetivo)
    if not encontrados:
        raise ValueError(f"No encontré '{objetivo}' como archivo ni como símbolo."
                         + (f" ¿{', '.join(sugerencias)}?" if sugerencias else ""))
    s = encontrados[0]
    texto = app.ws.leer(s.archivo)
    return s.describir(), lenguaje_de(s.archivo), texto_de_simbolo(texto, s, numerar=False)


def _cmd_explicar(self: "App", arg: str) -> None:
    if not arg:
        self.ui.tenue("Uso: /explicar <archivo | función | Clase.metodo>")
        return
    try:
        titulo, lenguaje, codigo = _codigo_para_explicar(self, arg.strip())
    except ValueError as e:
        self.ui.error(str(e))
        return
    self.ui.esperando("explicar", "leyendo el código")
    try:
        texto = self.llm.chat_simple(PROMPT_EXPLICAR.format(titulo=titulo, lenguaje=lenguaje, codigo=codigo),
                                     sistema="Sos un programador senior que explica código con claridad.",
                                     temperatura=0.2, max_tokens=1800, rol="explicar")
    finally:
        self.ui.fin_progreso()
    self.ui.titulo(titulo)
    mostrar_markdown(self.ui, texto)


def _cmd_testear(self: "App", arg: str) -> None:
    if not arg:
        self.ui.tenue("Uso: /testear <archivo>   (QA escribe tests para ese archivo y los corre)")
        return
    try:
        rel = self.ws.rel(self.ws.ruta(arg.strip()))
    except ErrorRuta as e:
        self.ui.error(str(e))
        return
    if not self.ws.existe(rel):
        self.ui.error(f"No existe {rel}.")
        return
    cid = self.ws.checkpoints.iniciar(f"tests para {rel}")
    tarea = (f"Escribí tests automáticos para {rel}: cubrí las funciones públicas con casos normales, casos borde y "
             "errores esperados. Leé el archivo primero (read_file/read_symbol). Corré run_tests y reportá el resultado "
             "real. Si un test falla por un bug del código, NO cambies el código: describí el bug en el informe.")
    res = ejecutar_subagentes([("qa", tarea, rel, f"tests para {rel}", {"memoria": self.memoria})],
                              self.llm, self.ws, self.settings, self.ui, profundidad=1, cid_inicio=cid)[0]
    self.ws.checkpoints.descartar_si_vacio(cid)
    mostrar_markdown(self.ui, res.resumen)


def _cmd_documentar(self: "App", arg: str) -> None:
    if not arg:
        self.ui.tenue("Uso: /documentar <archivo>")
        return
    tarea = (f"Agregá docstrings claros en español a las funciones, clases y módulo de {arg.strip()} que no tengan "
             "(o que estén vacíos), SIN cambiar el comportamiento ni las firmas. Usá replace_symbol por función. "
             "Al final corré validate y run_tests.")
    cid = self.ws.checkpoints.iniciar(f"documentar {arg[:60]}")
    res = ejecutar_subagentes([("implementador", tarea, arg.strip(), "documenta", {"memoria": self.memoria})],
                              self.llm, self.ws, self.settings, self.ui, profundidad=1, cid_inicio=cid)[0]
    self.ws.checkpoints.descartar_si_vacio(cid)
    mostrar_markdown(self.ui, res.resumen)


def _cmd_renombrar(self: "App", arg: str) -> None:
    partes = arg.split()
    if len(partes) < 2:
        self.ui.tenue("Uso: /renombrar <viejo> <nuevo> [archivos...]")
        return
    try:
        plan = planificar_renombrado(self.ws, partes[0], partes[1], partes[2:] or None)
    except ValueError as e:
        self.ui.error(str(e))
        return
    if not plan.cambios:
        self.ui.tenue(f"No encontré usos de '{partes[0]}'.")
        return
    self.ui.linea(plan.resumen())
    for conflicto in plan.conflictos:
        self.ui.aviso(f"  ⚠ {conflicto}")
    self.ui.diff(plan.diff(), max_lineas=60)
    if not self.ui.confirmar("¿Aplicar el renombrado?", defecto=True):
        return
    self.ws.checkpoints.iniciar(f"renombrar {partes[0]} → {partes[1]}")
    try:
        aplicar_renombrado(self.ws, plan)
    except ValueError as e:
        self.ui.error(str(e))
        return
    self.ui.ok(f"Renombrado: {plan.total} cambio(s) en {len(plan.cambios)} archivo(s) · /deshacer para revertir")


def _cmd_web(self: "App", arg: str) -> None:
    partes = arg.split(maxsplit=1)
    if not partes:
        self.ui.tenue("Uso: /web <url> [palabras a buscar]")
        return
    try:
        url, _ = validar_url(partes[0], self.settings.dominios_web)
        datos = descargar_texto(url)
    except (ValueError, OSError) as e:
        self.ui.error(str(e))
        return
    texto = filtrar_relevante(datos["texto"], partes[1]) if len(partes) > 1 else recortar(datos["texto"], 6000)
    self.ui.titulo(datos.get("titulo") or datos["url"])
    mostrar_markdown(self.ui, texto)


PROMPT_COMMIT = """Escribí el mensaje de commit para estos cambios, en español:
- primera línea: resumen en imperativo, máximo 72 caracteres, sin punto final
- una línea en blanco
- 2 a 6 viñetas con lo importante (qué y por qué), sin repetir el diff
Respondé SOLO con el mensaje.

ARCHIVOS:
{estado}

DIFF:
{diff}"""


def _cmd_commit(self: "App", arg: str) -> None:
    if not es_repo_git(self.ws):
        self.ui.tenue("El proyecto no es un repositorio git (/git init).")
        return
    estado = git(self.ws, "status", "--short").stdout.strip()
    if not estado:
        self.ui.tenue("No hay cambios para commitear.")
        return
    self.ui.linea(estado)
    mensaje = arg.strip()
    if not mensaje:
        diff = git(self.ws, "diff", "HEAD").stdout or git(self.ws, "diff").stdout
        nuevos = [l[3:] for l in estado.splitlines() if l.startswith("??")]
        if nuevos:
            diff += "\n(archivos nuevos: " + ", ".join(nuevos[:20]) + ")"
        self.ui.esperando("commit", "escribiendo el mensaje")
        try:
            mensaje = self.llm.chat_simple(PROMPT_COMMIT.format(estado=estado, diff=recortar(redactar_secretos(diff), 9000)),
                                           temperatura=0.2, max_tokens=400, rol="commit").strip().strip("`")
        except LLMError as e:
            self.ui.error(f"No pude generar el mensaje: {e}")
            return
        finally:
            self.ui.fin_progreso()
    self.ui.caja(mensaje.splitlines() or ["(vacío)"], titulo="mensaje de commit")
    if not self.ui.confirmar("¿Hago `git add -A` y commit con este mensaje?", defecto=True):
        return
    r = git(self.ws, "add", "-A")
    if r.ok:
        r = git(self.ws, "commit", "-q", "-F", "-", entrada=mensaje + "\n")
    (self.ui.ok if r.ok else self.ui.error)("Commit hecho." if r.ok else (r.stderr.strip() or r.stdout.strip()))


def comandos_de_dependencias(ws: Workspace) -> list[tuple[str, str]]:
    raiz = ws.raiz
    comandos = []
    if (raiz / "requirements.txt").is_file():
        comandos.append(("requirements.txt", f"{shlex.quote(sys.executable)} -m pip install -r requirements.txt"))
    if (raiz / "pyproject.toml").is_file() and not (raiz / "requirements.txt").is_file():
        comandos.append(("pyproject.toml", f"{shlex.quote(sys.executable)} -m pip install -e ."))
    if (raiz / "package.json").is_file():
        comandos.append(("package.json", "npm install"))
    if (raiz / "go.mod").is_file():
        comandos.append(("go.mod", "go mod download"))
    if (raiz / "Cargo.toml").is_file():
        comandos.append(("Cargo.toml", "cargo fetch"))
    return comandos


def _cmd_deps(self: "App", arg: str) -> None:
    comandos = comandos_de_dependencias(self.ws)
    if not comandos:
        self.ui.tenue("No encontré archivos de dependencias (requirements.txt, package.json, go.mod, Cargo.toml).")
        return
    for origen, comando in comandos:
        self.ui.info(f"{origen}: {comando}")
        if not self.ui.confirmar("  ¿Ejecutar?", defecto=True):
            continue
        r = ejecutar(comando, cwd=self.ws.raiz, timeout=900, shell=True)
        self.ui.linea(recortar((r.stdout + "\n" + r.stderr).strip(), 3000))
        (self.ui.ok if r.ok else self.ui.error)(f"{comando}: {'listo' if r.ok else 'falló'}")
        if not r.ok:
            for pista in pistas_para(r.stdout + r.stderr, 2):
                self.ui.tenue(f"  💡 {pista}")


def _cmd_estadisticas(self: "App", arg: str) -> None:
    self.estadisticas.registrar_uso(self.llm.uso, self.settings.modelo)
    mostrar_estadisticas(self.ui, self.estadisticas, int(arg) if arg.isdigit() else 14)


def listar_sesiones() -> list[tuple[Path, dict]]:
    salida = []
    if not SESIONES_DIR.is_dir():
        return salida
    for ruta in sorted(SESIONES_DIR.glob("*.json"), key=lambda r: r.stat().st_mtime, reverse=True):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        salida.append((ruta, datos))
    return salida


def _cmd_sesiones(self: "App", arg: str) -> None:
    sesiones = listar_sesiones()
    partes = arg.split()
    if partes[:1] == ["borrar"] and len(partes) == 2 and partes[1].isdigit():
        indice = int(partes[1]) - 1
        if 0 <= indice < len(sesiones):
            sesiones[indice][0].unlink()
            self.ui.ok(f"Sesión borrada: {sesiones[indice][0].stem}")
        else:
            self.ui.error("Número inválido.")
        return
    if not sesiones:
        self.ui.tenue("No hay sesiones guardadas.")
        return
    filas = []
    for i, (ruta, datos) in enumerate(sesiones[:20], start=1):
        mensajes = len(datos.get("mensajes", []))
        ultimo = next((h[1] for h in reversed(datos.get("historial", [])) if isinstance(h, list) and len(h) == 3), "")
        filas.append([str(i), ruta.stem.rsplit("_", 1)[0], datos.get("guardado", "?").replace("T", " "), str(mensajes),
                      recortar(ultimo, 40).replace("\n", " ")])
    self.ui.tabla(filas, ["#", "proyecto", "guardada", "msjs", "último pedido"], "rllrl")
    self.ui.tenue("  /proyecto <ruta> retoma la sesión de ese proyecto · /sesiones borrar N")


def _cmd_comandos(self: "App", arg: str) -> None:
    if arg.strip() == "ejemplos":
        creados = crear_comandos_de_ejemplo()
        self.ui.ok(f"Comandos de ejemplo en {COMANDOS_USUARIO_DIR}: " + (", ".join(p.stem for p in creados) or "ya existían"))
        return
    if arg.startswith("nuevo "):
        nombre = arg.split(maxsplit=1)[1].strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", nombre):
            self.ui.error("Nombre inválido (letras, números, - y _).")
            return
        ruta = self.ws.raiz / ".reaper" / "comandos" / f"{nombre}.md"
        if ruta.exists():
            self.ui.error(f"Ya existe {ruta}.")
            return
        escritura_atomica(ruta, EJEMPLO_COMANDO.format(descripcion="describí qué hace",
                                                       texto="Escribí acá el pedido. $ARGUMENTOS se reemplaza por lo que "
                                                             "escribas después del comando."))
        self.ui.ok(f"Creado {ruta}: editalo y usalo como /{nombre} <argumentos>")
        return
    propios = comandos_usuario(self.ws)
    if not propios:
        self.ui.tenue("No tenés comandos propios. /comandos ejemplos crea algunos · /comandos nuevo <nombre> crea uno.")
        return
    filas = [[f"/{c.nombre}", c.modo, c.descripcion or recortar(c.texto, 60).replace("\n", " ")] for c in propios.values()]
    self.ui.tabla(filas, ["comando", "modo", "descripción"])


def _cmd_plugins(self: "App", arg: str) -> None:
    if arg.strip() == "ejemplo":
        HERRAMIENTAS_USUARIO_DIR.mkdir(parents=True, exist_ok=True)
        ruta = HERRAMIENTAS_USUARIO_DIR / "contar_lineas.py"
        if not ruta.exists():
            ruta.write_text(EJEMPLO_PLUGIN, encoding="utf-8")
        self.ui.ok(f"Plugin de ejemplo: {ruta} (se carga al reiniciar REAPER)")
        return
    if not PLUGINS_CARGADOS:
        self.ui.tenue(f"No hay plugins cargados. Poné archivos .py en {HERRAMIENTAS_USUARIO_DIR} (/plugins ejemplo).")
        return
    for plugin in PLUGINS_CARGADOS:
        if plugin.error:
            self.ui.error(f"{plugin.ruta.name}: {plugin.error}")
        else:
            self.ui.ok(f"{plugin.ruta.name}: {', '.join(plugin.herramientas) or '(sin herramientas)'} → {', '.join(plugin.roles)}")


def _cmd_hooks(self: "App", arg: str) -> None:
    configurados = {e: hooks_de(self.ws, e) for e in EVENTOS_HOOK}
    if not any(configurados.values()):
        self.ui.tenue('Sin hooks. Ejemplo en .reaper/config.json:\n  {"hooks": {"despues_de_escribir": ["black -q {archivo}"], '
                      '"despues_de_build": ["termux-notification --title REAPER --content {estado}"]}}')
        return
    for evento, comandos in configurados.items():
        for c in comandos:
            self.ui.linea(f"  {Tema.info}{evento:<22}{C.RESET} {c}")
    self.ui.tenue(f"  hooks {'activados' if self.settings.hooks else 'desactivados'} (/config hooks true|false)")


for _nombre, _funcion in (("explicar", _cmd_explicar), ("testear", _cmd_testear), ("documentar", _cmd_documentar),
                          ("renombrar", _cmd_renombrar), ("web", _cmd_web), ("commit", _cmd_commit), ("deps", _cmd_deps),
                          ("estadisticas", _cmd_estadisticas), ("sesiones", _cmd_sesiones), ("comandos", _cmd_comandos),
                          ("plugins", _cmd_plugins), ("hooks", _cmd_hooks)):
    setattr(App, "cmd_" + _nombre, _funcion)
