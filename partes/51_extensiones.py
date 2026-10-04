"""
Extensiones del usuario: comandos propios, plugins de herramientas y hooks.

COMANDOS PROPIOS (como los custom commands de Claude Code)
  Un archivo Markdown en ~/reaper/comandos/<nombre>.md (para todos los
  proyectos) o en <proyecto>/.reaper/comandos/<nombre>.md (solo ese proyecto).
  Se usa como /<nombre> argumentos. El texto es el pedido; $ARGUMENTOS (o
  $ARGUMENTS) se reemplaza por lo que escribas después del comando, y $1, $2...
  por cada palabra. Encabezado opcional:
      ---
      descripcion: revisa la seguridad de un archivo
      modo: agente | construir | rol:revisor
      ---
      Revisá $ARGUMENTOS buscando inyecciones SQL y rutas sin validar...

PLUGINS DE HERRAMIENTAS
  ~/reaper/herramientas/<nombre>.py con funciones decoradas con @herramienta
  (las mismas que usa REAPER) y una variable ROLES = ("principal", ...) con los
  roles que pueden usarlas. Son tu código: corren con tus permisos.

HOOKS (en <proyecto>/.reaper/config.json)
      "hooks": {
        "despues_de_escribir": ["black -q {archivo}"],
        "antes_de_comando": ["echo {comando} | grep -qv 'npm publish'"],
        "despues_de_build": ["termux-notification --title REAPER --content '{estado}'"]
      }
  Si un hook "antes_de_comando" termina con error, el comando se bloquea.
"""


@dataclass
class ComandoUsuario:
    nombre: str
    texto: str
    descripcion: str = ""
    modo: str = "agente"
    origen: str = ""

    def expandir(self, argumentos: str) -> str:
        palabras = shlex.split(argumentos) if argumentos.strip() else []
        texto = self.texto.replace("$ARGUMENTOS", argumentos).replace("$ARGUMENTS", argumentos)
        for i in range(9, 0, -1):
            texto = texto.replace(f"${i}", palabras[i - 1] if i <= len(palabras) else "")
        if argumentos and "$ARGUMENTOS" not in self.texto and "$ARGUMENTS" not in self.texto and "$1" not in self.texto:
            texto += f"\n\n{argumentos}"
        return texto.strip()


_RE_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def leer_comando(ruta: Path) -> Optional[ComandoUsuario]:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    meta: dict[str, str] = {}
    m = _RE_FRONT.match(texto)
    if m:
        for linea in m.group(1).splitlines():
            if ":" in linea:
                clave, valor = linea.split(":", 1)
                meta[clave.strip().lower()] = valor.strip()
        texto = texto[m.end():]
    nombre = ruta.stem.lower().replace(" ", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", nombre):
        return None
    return ComandoUsuario(nombre, texto.strip(), meta.get("descripcion", meta.get("description", "")),
                          meta.get("modo", meta.get("mode", "agente")), str(ruta))


def comandos_usuario(ws: Optional[Workspace] = None) -> dict[str, ComandoUsuario]:
    """Comandos globales y del proyecto (los del proyecto ganan si se llaman igual)."""
    carpetas = [COMANDOS_USUARIO_DIR]
    if ws is not None:
        carpetas.append(ws.raiz / ".reaper" / "comandos")
    salida: dict[str, ComandoUsuario] = {}
    for carpeta in carpetas:
        if not carpeta.is_dir():
            continue
        for ruta in sorted(carpeta.glob("*.md")):
            comando = leer_comando(ruta)
            if comando:
                salida[comando.nombre] = comando
    return salida


EJEMPLO_COMANDO = """---
descripcion: {descripcion}
modo: agente
---
{texto}
"""

COMANDOS_DE_EJEMPLO = {
    "seguridad": ("revisa un archivo buscando problemas de seguridad",
                  "Revisá $ARGUMENTOS buscando problemas de seguridad reales: inyección SQL o de comandos, rutas sin "
                  "validar, secretos en el código, deserialización insegura y manejo de errores que filtra datos. "
                  "Para cada hallazgo: archivo:línea, riesgo concreto y arreglo. Si no hay nada grave, decilo."),
    "docstrings": ("agrega docstrings sin cambiar el comportamiento",
                   "Agregá docstrings claros en español a todas las funciones y clases públicas de $ARGUMENTOS que no "
                   "tengan, sin cambiar el comportamiento. Después corré run_tests para confirmar que nada se rompió."),
    "optimizar": ("busca cuellos de botella y los mejora",
                  "Analizá $ARGUMENTOS buscando cuellos de botella de rendimiento (bucles cuadráticos, lecturas repetidas "
                  "de disco, consultas dentro de bucles). Proponé y aplicá solo mejoras que no cambien el resultado, "
                  "verificando con los tests."),
}


def crear_comandos_de_ejemplo(carpeta: Optional[Path] = None) -> list[Path]:
    carpeta = carpeta or COMANDOS_USUARIO_DIR
    carpeta.mkdir(parents=True, exist_ok=True)
    creados = []
    for nombre, (descripcion, texto) in COMANDOS_DE_EJEMPLO.items():
        ruta = carpeta / f"{nombre}.md"
        if not ruta.exists():
            ruta.write_text(EJEMPLO_COMANDO.format(descripcion=descripcion, texto=texto), encoding="utf-8")
            creados.append(ruta)
    return creados


# ======================================================================
# PLUGINS
# ======================================================================
@dataclass
class Plugin:
    ruta: Path
    herramientas: list
    roles: tuple
    error: str = ""


PLUGINS_CARGADOS: list[Plugin] = []


def agregar_herramienta_a_roles(nombre: str, roles: Iterable[str]) -> None:
    for rol in roles:
        actual = ROLES.get(rol)
        if actual is None or nombre in actual.herramientas:
            continue
        ROLES[rol] = replace(actual, herramientas=actual.herramientas + (nombre,))


def cargar_plugins(carpeta: Optional[Path] = None, ui: Optional[UI] = None) -> list[Plugin]:
    """Ejecuta ~/reaper/herramientas/*.py y registra sus herramientas en los roles indicados."""
    carpeta = carpeta or HERRAMIENTAS_USUARIO_DIR
    cargados = []
    if not carpeta.is_dir():
        return cargados
    for ruta in sorted(carpeta.glob("*.py")):
        antes = set(REGISTRO)
        espacio = {
            "__name__": f"reaper_plugin_{ruta.stem}", "__file__": str(ruta),
            "herramienta": herramienta, "Param": Param, "ErrorHerramienta": ErrorHerramienta,
            "Contexto": Contexto, "ejecutar": ejecutar, "recortar": recortar, "Path": Path,
            "json": json, "re": re, "os": os, "subprocess": subprocess,
        }
        try:
            codigo = compile(ruta.read_text(encoding="utf-8"), str(ruta), "exec")
            exec(codigo, espacio)
        except Exception as e:  # un plugin roto no debe impedir que REAPER arranque
            plugin = Plugin(ruta, [], (), f"{type(e).__name__}: {e}")
            cargados.append(plugin)
            if ui:
                ui.aviso(f"  plugin {ruta.name} no cargó: {plugin.error}")
            continue
        nuevas = sorted(set(REGISTRO) - antes)
        roles = tuple(espacio.get("ROLES") or ("principal",))
        for nombre in nuevas:
            agregar_herramienta_a_roles(nombre, roles)
        cargados.append(Plugin(ruta, nuevas, roles))
    PLUGINS_CARGADOS.extend(cargados)
    return cargados


EJEMPLO_PLUGIN = '''"""Plugin de ejemplo para REAPER: cuenta líneas de código por extensión."""

ROLES = ("principal", "explorador")


@herramienta(
    "count_lines",
    "Cuenta líneas de código por extensión en el proyecto.",
    [Param("path", "carpeta (opcional)", requerido=False)],
    "<count_lines>\\n<path>.</path>\\n</count_lines>",
)
def count_lines(ctx, p):
    conteo = {}
    for ruta in ctx.ws.iterar(p.get("path") or "."):
        if ctx.ws.es_texto(ruta):
            try:
                n = len(ruta.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue
            conteo[ruta.suffix or ruta.name] = conteo.get(ruta.suffix or ruta.name, 0) + n
    return "\\n".join(f"{ext}: {n}" for ext, n in sorted(conteo.items(), key=lambda kv: -kv[1])) or "sin archivos"
'''


# ======================================================================
# HOOKS
# ======================================================================
EVENTOS_HOOK = ("despues_de_escribir", "antes_de_comando", "despues_de_comando", "despues_de_build", "al_iniciar")


@dataclass
class ResultadoHook:
    evento: str
    comando: str
    ok: bool
    salida: str


def hooks_de(ws: Workspace, evento: str) -> list[str]:
    hooks = ws.config_local().get("hooks")
    if not isinstance(hooks, dict):
        return []
    comandos = hooks.get(evento) or []
    if isinstance(comandos, str):
        comandos = [comandos]
    return [c for c in comandos if isinstance(c, str) and c.strip()]


def ejecutar_hooks(ws: Workspace, evento: str, variables: Optional[dict] = None, timeout: int = 60) -> list[ResultadoHook]:
    if evento not in EVENTOS_HOOK:
        raise ValueError(f"evento de hook desconocido: {evento}")
    resultados = []
    for plantilla in hooks_de(ws, evento):
        comando = plantilla
        for clave, valor in (variables or {}).items():
            comando = comando.replace("{" + clave + "}", shlex.quote(str(valor)))
        r = ejecutar(comando, cwd=ws.raiz, timeout=timeout, shell=True)
        resultados.append(ResultadoHook(evento, comando, r.ok, (r.stdout + r.stderr).strip()[-1500:]))
    return resultados


def _hook_post_escritura(ctx: Contexto, rel: str) -> str:
    """Corre los hooks despues_de_escribir; devuelve texto para el agente si alguno falló o cambió algo."""
    if not ctx.settings.hooks:
        return ""
    antes = ctx.ws.hash(rel)
    resultados = ejecutar_hooks(ctx.ws, "despues_de_escribir", {"archivo": rel})
    if not resultados:
        return ""
    partes = []
    if ctx.ws.hash(rel) != antes:
        partes.append(f"(un hook del proyecto modificó {rel}: releelo antes de volver a editarlo)")
    for r in resultados:
        if not r.ok:
            partes.append(f"HOOK FALLÓ ({r.comando}):\n{r.salida}")
    return "\n".join(partes)


def _hook_antes_de_comando(ctx: Contexto, comando: str) -> Optional[str]:
    """Devuelve el motivo si un hook bloquea el comando."""
    if not ctx.settings.hooks:
        return None
    for r in ejecutar_hooks(ctx.ws, "antes_de_comando", {"comando": comando}):
        if not r.ok:
            return f"el hook '{r.comando}' bloqueó el comando" + (f": {r.salida[-300:]}" if r.salida else "")
    return None
