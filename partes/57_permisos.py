"""
Permisos con memoria ("permitir siempre") y utilidades del modo plan.

Fuera del modo auto, cada comando que no es de solo lectura pide permiso. Preguntar lo mismo veinte
veces cansa (y en el celular más), así que, como Claude Code, se puede responder:

  1. sí, esta vez
  2. sí, y no volver a preguntar por «npm test» en esta sesión
  3. sí, y siempre en este proyecto     (se guarda en .reaper/config.json → "permitidos")
  4. no

La clave es el comando y su subcomando ("git commit", "npm test", "python3"). Los comandos destructivos
(rm, mv, git push, git reset, chmod...) NUNCA se pueden permitir para siempre: se confirman cada vez.
Los bloqueados por seguridad (rm -rf ~, sudo...) siguen bloqueados siempre.
"""

_PERMISOS_SESION: dict[str, set] = {}
_LOCK_PERMISOS = threading.Lock()
EDICIONES = "__ediciones__"

_NUNCA_SIEMPRE = re.compile(
    r"^(?:rm|rmdir|mv|dd|mkfs\S*|chmod|chown|shred|truncate|kill|pkill|killall|reboot|shutdown|"
    r"git (?:push|reset|clean|rebase|checkout|restore|branch|tag|filter-branch|gc)|"
    r"pip uninstall|npm (?:uninstall|publish|unpublish)|pkg (?:uninstall|remove)|apt(?:-get)? remove|"
    r"curl|wget|ssh|scp|rsync|nc|ncat|termux-(?:setup-storage|reload-settings)|crontab|eval|exec|source|\.|"
    r"\S+ -[ceprm]|\S+ --eval|xargs|find|sed -i|perl -i)$"
)


_CON_SUBCOMANDO = {"npm", "pnpm", "yarn", "npx", "cargo", "go", "git", "docker", "pip", "pip3", "pkg", "apt",
                   "make", "gradle", "mvn", "bundle", "rake", "composer", "deno", "bun", "dotnet", "flutter"}
_INTERPRETES = {"python", "python3", "node", "bash", "sh", "zsh", "ruby", "perl", "php", "lua", "deno", "bun"}


def clave_comando(comando: str) -> str:
    """
    'git commit -m x' → 'git commit' · 'npm run build' → 'npm run build' · 'python3 calc.py' → 'python3 calc.py'
    'python3 -m pytest -q' → 'python3 -m pytest' · 'python3 -c ...' → 'python3 -c' (nunca se permite siempre).
    """
    try:
        partes = shlex.split(comando.strip())
    except ValueError:
        partes = comando.strip().split()
    while partes and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", partes[0]):
        partes = partes[1:]  # FOO=1 cmd ...: las variables no forman parte de la clave
    if not partes:
        return ""
    cabeza = os.path.basename(partes[0])
    palabra = re.compile(r"[a-z][a-z0-9:_.-]*$")
    if cabeza in _INTERPRETES and len(partes) > 1:
        if partes[1] in ("-c", "-e", "-r", "--eval", "-p"):
            return f"{cabeza} {partes[1]}"
        if partes[1] == "-m" and len(partes) > 2:
            return f"{cabeza} -m {partes[2]}"
        if not partes[1].startswith("-"):
            return f"{cabeza} {partes[1]}"
        return cabeza
    if cabeza in _CON_SUBCOMANDO and len(partes) > 1 and palabra.match(partes[1]):
        if partes[1] in ("run", "exec", "x") and len(partes) > 2 and palabra.match(partes[2]):
            return f"{cabeza} {partes[1]} {partes[2]}"
        return f"{cabeza} {partes[1]}"
    return cabeza


def _es_compuesto(comando: str) -> bool:
    return any(s in comando for s in (";", "&&", "||", "|", "`", "$(", ">", "<", "\n"))


_NUNCA_SIEMPRE_COMANDO = re.compile(r"^\s*(?:sed|perl|ruby)\s+(?:-\w*i|--in-place)|\s-(?:delete|exec|execdir)\b|\s--force\b")


def puede_permitirse_siempre(comando: str) -> bool:
    clave = clave_comando(comando)
    return (bool(clave) and not _NUNCA_SIEMPRE.match(clave) and not _NUNCA_SIEMPRE_COMANDO.search(comando)
            and not _es_compuesto(comando))


def permisos_proyecto(ws: Workspace) -> set:
    lista = ws.config_local().get("permitidos") or []
    return {str(x).strip() for x in lista if str(x).strip()} if isinstance(lista, list) else set()


def guardar_permiso_proyecto(ws: Workspace, clave: str) -> None:
    ruta = ws.raiz / ".reaper" / "config.json"
    datos = ws.config_local()
    actuales = permisos_proyecto(ws)
    actuales.add(clave)
    datos["permitidos"] = sorted(actuales)
    escritura_atomica(ruta, json.dumps(datos, ensure_ascii=False, indent=2) + "\n")


def _sesion(ws: Workspace) -> set:
    with _LOCK_PERMISOS:
        return _PERMISOS_SESION.setdefault(str(ws.raiz), set())


def permitir_en_sesion(ws: Workspace, clave: str) -> None:
    with _LOCK_PERMISOS:
        _PERMISOS_SESION.setdefault(str(ws.raiz), set()).add(clave)


def olvidar_permisos(ws: Optional[Workspace] = None) -> None:
    with _LOCK_PERMISOS:
        if ws is None:
            _PERMISOS_SESION.clear()
        else:
            _PERMISOS_SESION.pop(str(ws.raiz), None)


def comando_ya_permitido(ws: Workspace, comando: str) -> bool:
    if not puede_permitirse_siempre(comando):
        return False
    clave = clave_comando(comando)
    return clave in _sesion(ws) or clave in permisos_proyecto(ws)


def pedir_permiso_comando(ctx: "Contexto", comando: str) -> bool:
    """True si el comando puede ejecutarse (ya permitido o el usuario lo aprueba ahora)."""
    if comando_ya_permitido(ctx.ws, comando):
        ctx.ui.tenue(f"  (permitido: {clave_comando(comando)})")
        return True
    ctx.ui.aviso(f"  {ctx.etiqueta} quiere ejecutar: {comando}")
    clave = clave_comando(comando)
    if not puede_permitirse_siempre(comando):
        return ctx.ui.confirmar("  ¿Ejecutar?")
    eleccion = ctx.ui.elegir("  ¿Ejecutar?", [
        "sí, esta vez",
        f"sí, y no preguntar más por «{clave}» en esta sesión",
        f"sí, y siempre en este proyecto («{clave}» → .reaper/config.json)",
        "no",
    ], defecto=3)
    if eleccion == 1:
        permitir_en_sesion(ctx.ws, clave)
    elif eleccion == 2:
        try:
            guardar_permiso_proyecto(ctx.ws, clave)
        except OSError as e:
            ctx.ui.aviso(f"  no pude guardar el permiso: {e}")
            permitir_en_sesion(ctx.ws, clave)
    return eleccion in (0, 1, 2)


def pedir_permiso_edicion(ctx: "Contexto", rel: str) -> bool:
    if EDICIONES in _sesion(ctx.ws):
        return True
    eleccion = ctx.ui.elegir("  ¿Aplicar este cambio?", [
        "sí",
        "sí, y aceptar todas las ediciones de esta sesión",
        "no",
    ], defecto=2)
    if eleccion == 1:
        permitir_en_sesion(ctx.ws, EDICIONES)
    return eleccion in (0, 1)


def guardar_plan_markdown(ws: Workspace, pedido: str, plan: str) -> Optional[Path]:
    """Guarda el plan del modo plan en .reaper/planes/ (para retomarlo o compartirlo)."""
    if not plan.strip():
        return None
    ruta = ws.raiz / ".reaper" / "planes" / f"plan_{datetime.now():%Y%m%d_%H%M%S}.md"
    try:
        escritura_atomica(ruta, f"# Plan\n\n## Pedido\n{pedido.strip()}\n\n{plan.strip()}\n")
    except OSError:
        return None
    return ruta
