"""Herramientas que los agentes usan para trabajar sobre el workspace real."""




MAX_LINEAS_LECTURA = 400
MAX_SALIDA = 9000


class ErrorHerramienta(Exception):
    pass


@dataclass
class Contexto:
    ws: Workspace
    settings: Settings
    ui: UI
    etiqueta: str = "agente"
    cambios: set = field(default_factory=set)
    todo: list = field(default_factory=list)
    cid_inicio: Optional[int] = None
    # v7
    memoria: Optional["MemoriaLecciones"] = None
    parciales: dict = field(default_factory=dict)   # rel → líneas escritas (archivo en construcción)
    leidos: dict = field(default_factory=dict)      # rel → hash del archivo cuando se leyó
    protegidos: set = field(default_factory=set)    # archivos que este agente no puede tocar (tests de la especificación)
    notas_autofix: list = field(default_factory=list)
    permitidos: tuple = ()                          # globs de rutas escribibles (vacío = todas)
    llm: Any = None                                 # cliente del modelo (lo usa write_large_file)

    def tropiezo(self, tipo: str) -> None:
        if self.memoria is not None:
            try:
                self.memoria.tropiezo(tipo)
            except OSError:
                pass


@dataclass
class Param:
    nombre: str
    descripcion: str
    requerido: bool = True
    largo: bool = False


@dataclass
class Herramienta:
    nombre: str
    descripcion: str
    params: list
    ejemplo: str
    fn: Optional[Callable] = None
    escribe: bool = False


REGISTRO: dict[str, Herramienta] = {}


def herramienta(nombre: str, descripcion: str, params: list, ejemplo: str, escribe: bool = False):
    def decorador(fn):
        REGISTRO[nombre] = Herramienta(nombre, descripcion, params, ejemplo.strip(), fn, escribe)
        return fn
    return decorador


def esquemas(nombres: Optional[list] = None) -> dict:
    return {
        n: [(p.nombre, p.largo) for p in h.params]
        for n, h in REGISTRO.items()
        if nombres is None or n in nombres
    }


def documentacion(nombres: list) -> str:
    partes = []
    for nombre in nombres:
        h = REGISTRO.get(nombre)
        if not h:
            continue
        params = ", ".join(
            f"{p.nombre}{'' if p.requerido else ' (opcional)'}: {p.descripcion}" for p in h.params
        ) or "sin parámetros"
        partes.append(f"## {h.nombre}\n{h.descripcion}\nParámetros: {params}\n{h.ejemplo}")
    return "\n\n".join(partes)


# ==================================================================
# HELPERS
# ==================================================================
def _sugerir_ruta(ctx: Contexto, rel: str) -> str:
    nombre = Path(rel).name
    archivos = ctx.ws.archivos_codigo(limite=800)
    parecidos = difflib.get_close_matches(rel, archivos, n=3, cutoff=0.5)
    parecidos += [a for a in archivos if Path(a).name == nombre and a not in parecidos][:3]
    return f" ¿Quisiste decir: {', '.join(parecidos)}?" if parecidos else ""


def _entero(valor, defecto: Optional[int]) -> Optional[int]:
    try:
        return int(str(valor).strip()) if str(valor or "").strip() else defecto
    except ValueError:
        return defecto


def _permiso_edicion(ctx: Contexto, rel: str, diff: str, nuevo: bool) -> None:
    if ctx.settings.modo != "confirmar":
        return
    if EDICIONES in _sesion(ctx.ws):
        return
    ctx.ui.aviso(f"  {ctx.etiqueta} quiere {'crear' if nuevo else 'modificar'} {rel}:")
    ctx.ui.diff(diff, max_lineas=40)
    if not pedir_permiso_edicion(ctx, rel):
        raise ErrorHerramienta(
            f"El usuario rechazó el cambio en {rel}. No insistas con lo mismo: "
            "preguntá qué prefiere (ask_user) o seguí con otra parte."
        )


def _escribir(ctx: Contexto, rel: str, contenido: str) -> None:
    if rel in ctx.protegidos:
        raise ErrorHerramienta(
            f"{rel} es parte de la especificación (tests escritos antes de implementar) y no se puede modificar "
            "en esta tarea. Cambiá el código para que esos tests pasen."
        )
    if ctx.permitidos and not any(fnmatch.fnmatch(rel, patron) for patron in ctx.permitidos):
        raise ErrorHerramienta(
            f"En este rol solo podés escribir archivos que coincidan con: {', '.join(ctx.permitidos)}. "
            f"{rel} no está permitido."
        )
    try:
        ctx.ws.escribir(rel, contenido)
    except (ErrorRuta, IsADirectoryError, PermissionError) as e:
        raise ErrorHerramienta(f"No pude escribir {rel}: {e}")
    try:
        indice_de(ctx.ws).invalidar(rel)
    except (OSError, ValueError):
        pass


def _post_escritura(ctx: Contexto, rel: str, antes: Optional[str], despues: str, notas: list,
                    accion: Optional[str] = None, mostrar_diff: bool = True) -> str:
    ctx.cambios.add(rel)
    diff = diff_unificado(antes or "", despues, rel)
    lineas = despues.count("\n") + (0 if despues.endswith("\n") or not despues else 1)
    if antes is None:
        ctx.ui.tenue(f"      + {rel} (nuevo, {lineas} líneas)")
    elif mostrar_diff:
        ctx.ui.diff(diff, max_lineas=24)

    en_construccion = rel in ctx.parciales
    if ctx.settings.autofix and not en_construccion:
        reporte = autoarreglar(ctx.ws, rel, usar_ruff=ctx.settings.autofix_ruff)
        if reporte.cambio:
            notas = list(notas) + [f"autofix: {reporte.texto()}"]
            ctx.notas_autofix.append(f"{rel}: {reporte.texto()}")
            try:
                despues = ctx.ws.leer(rel)
            except (OSError, ValueError, ErrorRuta):
                pass
            lineas = despues.count("\n") + (0 if despues.endswith("\n") or not despues else 1)

    resultados = validar_archivo(ctx.ws, rel)
    malos = fallos(resultados)
    accion = accion or ("Creé" if antes is None else "Modifiqué")
    texto = f"{accion} {rel} ({lineas} líneas)."
    if notas:
        texto += " Notas: " + "; ".join(notas) + "."
    if antes is not None and diff and mostrar_diff:
        texto += "\nDiff aplicado:\n" + recortar(diff, 2500)
    if en_construccion:
        texto += ("\nARCHIVO EN CONSTRUCCIÓN: seguí agregando el resto con append_to_file (desde donde quedó). "
                  "Cuando esté completo, el último append valida todo.")
        if malos:
            texto += "\n(Validación parcial: " + (malos[0].stderr or malos[0].stdout).strip().splitlines()[0][:160] + ")"
        return texto
    if not resultados:
        texto += "\nValidación: no hay validador automático para este tipo de archivo."
    elif malos:
        detalle = resumen_validacion(resultados)
        texto += "\nVALIDACIÓN FALLÓ (corregilo antes de seguir):\n" + detalle
        if ctx.settings.pistas_errores:
            texto = anexar_pistas(texto, 2)
        if any("imports-locales" in r.comando or "imports-js" in r.comando for r in malos):
            ctx.tropiezo("import_inexistente")
    else:
        texto += "\nValidación: " + resumen_validacion(resultados)
    if rel.endswith(".py") and not malos:
        avisos = advertencias_python(despues)
        if es_archivo_de_test(rel):
            avisos = avisos + advertencias_tests_python(despues)
        if avisos:
            texto += "\nAdvertencias:\n" + "\n".join(f"- {a}" for a in avisos[:6])
    extra_hooks = _hook_post_escritura(ctx, rel)
    if extra_hooks:
        texto += "\n" + extra_hooks
    return texto


# ==================================================================
# LECTURA
# ==================================================================
@herramienta(
    "read_file",
    "Lee un archivo de texto. Devuelve las líneas numeradas ('  12| código'); los números NO son parte del archivo.",
    [Param("path", "ruta relativa al workspace"),
     Param("desde", "primera línea a mostrar", requerido=False),
     Param("hasta", "última línea a mostrar", requerido=False)],
    "<read_file>\n<path>src/app.py</path>\n</read_file>",
)
def read_file(ctx: Contexto, p: dict) -> str:
    rel = p["path"]
    try:
        ruta = ctx.ws.ruta(rel)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if ruta.is_dir():
        raise ErrorHerramienta(f"{rel} es una carpeta. Usá list_files.")
    if not ruta.is_file():
        raise ErrorHerramienta(f"No existe {rel}.{_sugerir_ruta(ctx, rel)}")
    if ruta.name in (".env", "id_rsa", "id_ed25519"):
        raise ErrorHerramienta("Archivo sensible: no se lee.")
    if es_binario(ruta):
        raise ErrorHerramienta(f"{rel} es binario ({ruta.stat().st_size} bytes).")
    try:
        lineas = ctx.ws.leer(rel).splitlines()
    except ValueError as e:
        raise ErrorHerramienta(str(e))
    total = len(lineas)
    if total == 0:
        return f"{ctx.ws.rel(ruta)} está vacío."
    desde = max(1, _entero(p.get("desde"), 1))
    hasta = min(total, _entero(p.get("hasta"), desde + MAX_LINEAS_LECTURA - 1))
    hasta = min(hasta, desde + MAX_LINEAS_LECTURA - 1)
    cuerpo = "\n".join(f"{i:>5}| {lineas[i - 1]}" for i in range(desde, hasta + 1))
    ctx.leidos[ctx.ws.rel(ruta)] = ctx.ws.hash(ctx.ws.rel(ruta))
    pie = ""
    if desde > 1 or hasta < total:
        pie = f"\n(mostrando líneas {desde}-{hasta} de {total}; usá desde/hasta para ver el resto)"
        if total > MAX_LINEAS_LECTURA and not p.get("desde"):
            simbolos = indice_de(ctx.ws).de_archivo(ctx.ws.rel(ruta))
            if simbolos:
                mapa = ", ".join(f"{s.nombre_completo} L{s.inicio}-{s.fin}" for s in simbolos
                                 if s.tipo in ("clase", "funcion", "metodo"))[:900]
                pie += f"\nArchivo grande: para no gastar contexto usá read_symbol. Símbolos: {mapa}"
    return f"{ctx.ws.rel(ruta)} ({total} líneas)\n{cuerpo}{pie}"


@herramienta(
    "list_files",
    "Lista archivos del workspace (ignora .git, node_modules, venv, etc.).",
    [Param("path", "carpeta relativa (por defecto la raíz)", requerido=False),
     Param("recursive", "true/false (por defecto true)", requerido=False)],
    "<list_files>\n<path>.</path>\n</list_files>",
)
def list_files(ctx: Contexto, p: dict) -> str:
    rel = p.get("path") or "."
    try:
        base = ctx.ws.ruta(rel) if rel not in (".", "") else ctx.ws.raiz
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if base.is_file():
        raise ErrorHerramienta(f"{rel} es un archivo. Usá read_file.")
    if not base.is_dir():
        raise ErrorHerramienta(f"No existe la carpeta {rel}.{_sugerir_ruta(ctx, rel)}")
    recursivo = str(p.get("recursive", "true")).strip().lower() not in ("false", "no", "0")
    if not recursivo:
        entradas = []
        for hijo in sorted(base.iterdir()):
            r = ctx.ws.rel(hijo)
            if ctx.ws.ignorado(r, hijo.is_dir()):
                continue
            entradas.append(r + ("/" if hijo.is_dir() else ""))
        return "\n".join(entradas) or "(carpeta vacía)"
    rutas = [ctx.ws.rel(x) for x in ctx.ws.iterar(rel, limite=301)]
    if not rutas:
        return "(sin archivos)"
    extra = "\n... (más de 300 archivos; filtrá con path o usá search_files)" if len(rutas) > 300 else ""
    return "\n".join(rutas[:300]) + extra


@herramienta(
    "search_files",
    "Busca una expresión regular (Python) en los archivos de texto. Devuelve archivo:línea: texto.",
    [Param("regex", "expresión a buscar, p. ej. def procesar|class Cliente"),
     Param("path", "carpeta o archivo donde buscar (opcional)", requerido=False),
     Param("file_pattern", "filtro de nombre tipo *.py (opcional)", requerido=False)],
    "<search_files>\n<regex>def guardar_</regex>\n<file_pattern>*.py</file_pattern>\n</search_files>",
)
def search_files(ctx: Contexto, p: dict) -> str:
    patron_txt = p["regex"]
    nota = ""
    try:
        patron = re.compile(patron_txt)
    except re.error:
        patron = re.compile(re.escape(patron_txt))
        nota = "(regex inválida: se buscó como texto literal)\n"
    filtro = (p.get("file_pattern") or "").strip()

    def buscar(rx: re.Pattern) -> list[str]:
        hallazgos = []
        for ruta in ctx.ws.iterar(p.get("path") or ".", limite=3000):
            if filtro and not Path(ruta.name).match(filtro):
                continue
            if not ctx.ws.es_texto(ruta) or ruta.stat().st_size > 400_000:
                continue
            try:
                texto = ruta.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n, linea in enumerate(texto.splitlines(), start=1):
                if rx.search(linea):
                    hallazgos.append(f"{ctx.ws.rel(ruta)}:{n}: {linea.strip()[:200]}")
                    if len(hallazgos) >= 80:
                        return hallazgos
        return hallazgos

    try:
        hallazgos = buscar(patron)
        if not hallazgos and not nota:
            hallazgos = buscar(re.compile(patron.pattern, re.I))
            if hallazgos:
                nota = "(sin coincidencias exactas; resultados ignorando mayúsculas)\n"
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if not hallazgos:
        return nota + "Sin coincidencias."
    extra = "\n... (hay más; afiná la búsqueda)" if len(hallazgos) >= 80 else ""
    return nota + "\n".join(hallazgos) + extra


def _outline_python(texto: str) -> list[str]:
    try:
        arbol = ast.parse(texto)
    except SyntaxError as e:
        return [f"(error de sintaxis en línea {e.lineno}: {e.msg})"]
    salida = []
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pref = "async def" if isinstance(nodo, ast.AsyncFunctionDef) else "def"
            salida.append(f"{nodo.lineno}: {pref} {nodo.name}({ast.unparse(nodo.args)})")
        elif isinstance(nodo, ast.ClassDef):
            salida.append(f"{nodo.lineno}: class {nodo.name}")
            for sub in nodo.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    salida.append(f"{sub.lineno}:     def {sub.name}({ast.unparse(sub.args)})")
        elif isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    salida.append(f"{nodo.lineno}: {t.id} = ...")
    return salida


_JS_SIMBOLOS = re.compile(
    r"^\s*(export\s+(default\s+)?)?(async\s+)?(function\*?\s+[\w$]+\s*\([^)]*\)|class\s+[\w$]+"
    r"|(const|let|var)\s+[\w$]+\s*=\s*(async\s*)?(\([^)]*\)|[\w$]+)\s*=>"
    r"|(const|let|var)\s+[\w$]+\s*=\s*(async\s+)?function)"
)


def outline(ruta: Path) -> list[str]:
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if ruta.suffix == ".py":
        return _outline_python(texto)
    if ruta.suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
        return [f"{n}: {l.strip()[:120]}" for n, l in enumerate(texto.splitlines(), 1) if _JS_SIMBOLOS.match(l)]
    return []


@herramienta(
    "code_outline",
    "Mapa rápido de un archivo o carpeta: clases, funciones y firmas con número de línea. Más barato que leer todo.",
    [Param("path", "archivo o carpeta (por defecto la raíz)", requerido=False)],
    "<code_outline>\n<path>src</path>\n</code_outline>",
)
def code_outline(ctx: Contexto, p: dict) -> str:
    rel = p.get("path") or "."
    try:
        objetivo = ctx.ws.ruta(rel) if rel not in (".", "") else ctx.ws.raiz
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if not objetivo.exists():
        raise ErrorHerramienta(f"No existe {rel}.{_sugerir_ruta(ctx, rel)}")
    rutas = [objetivo] if objetivo.is_file() else list(ctx.ws.iterar(rel, limite=600))
    partes, total = [], 0
    for ruta in rutas:
        simbolos = outline(ruta)
        if not simbolos:
            continue
        bloque = ctx.ws.rel(ruta) + "\n" + "\n".join("  " + s for s in simbolos[:40])
        if len(simbolos) > 40:
            bloque += f"\n  ... {len(simbolos) - 40} símbolos más"
        partes.append(bloque)
        total += len(bloque)
        if total > MAX_SALIDA:
            partes.append("... (salida recortada; pedí una carpeta más específica)")
            break
    return "\n".join(partes) or "No encontré símbolos (solo se analizan .py y .js/.ts)."


# ==================================================================
# ESCRITURA
# ==================================================================
@herramienta(
    "write_to_file",
    "Crea un archivo o lo reemplaza ENTERO. Para archivos existentes preferí replace_in_file. "
    "El contenido debe ser COMPLETO: prohibido '...' o 'resto igual'.",
    [Param("path", "ruta relativa"), Param("content", "contenido completo del archivo", largo=True),
     Param("partial", "true si es la PRIMERA PARTE de un archivo largo (el resto va con append_to_file)",
           requerido=False)],
    "<write_to_file>\n<path>utils/fechas.py</path>\n<content>\nfrom datetime import date\n\n\n"
    "def hoy() -> str:\n    return date.today().isoformat()\n</content>\n</write_to_file>",
    escribe=True,
)
def write_to_file(ctx: Contexto, p: dict) -> str:
    rel, contenido = p["path"], p["content"]
    try:
        ruta = ctx.ws.ruta(rel, escribir=True)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    rel = ctx.ws.rel(ruta)
    antes = None
    if ruta.is_file():
        antes = ruta.read_text(encoding="utf-8", errors="replace")
        marcador = tiene_marcadores_perezosos(contenido)
        if marcador and not tiene_marcadores_perezosos(antes):
            ctx.tropiezo("marcador_perezoso")
            raise ErrorHerramienta(
                f"El contenido tiene un marcador de código omitido ('{marcador}'). "
                "Eso borraría código real. Usá replace_in_file para cambiar solo una parte, "
                "o escribí el archivo COMPLETO."
            )
    if contenido and not contenido.endswith("\n"):
        contenido += "\n"
    if antes == contenido:
        return f"{rel} ya tenía exactamente ese contenido; no hubo cambios."

    notas = []
    if antes is not None:
        viejas, nuevas = antes.count("\n"), contenido.count("\n")
        if viejas >= 40 and nuevas < viejas * 0.4:
            notas.append(f"ATENCIÓN: el archivo pasó de {viejas} a {nuevas} líneas; verificá que no se perdió código")
    _permiso_edicion(ctx, rel, diff_unificado(antes or "", contenido, rel), antes is None)
    if str(p.get("partial", "")).strip().lower() in ("true", "si", "sí", "1", "yes"):
        ctx.parciales[rel] = contenido.count("\n")
    else:
        ctx.parciales.pop(rel, None)
    _escribir(ctx, rel, contenido)
    return _post_escritura(ctx, rel, antes, contenido, notas)


@herramienta(
    "replace_in_file",
    "Edita partes de un archivo existente con uno o más bloques SEARCH/REPLACE. "
    "SEARCH debe copiar el texto actual EXACTO (sin números de línea) y ser único; incluí 2-3 líneas de contexto. "
    "Se aplican todos los bloques o ninguno.",
    [Param("path", "ruta relativa"), Param("diff", "bloques SEARCH/REPLACE", largo=True)],
    "<replace_in_file>\n<path>app.py</path>\n<diff>\n<<<<<<< SEARCH\ndef total(items):\n    return sum(items)\n"
    "=======\ndef total(items):\n    return sum(i.precio for i in items)\n>>>>>>> REPLACE\n</diff>\n</replace_in_file>",
    escribe=True,
)
def replace_in_file(ctx: Contexto, p: dict) -> str:
    rel = p["path"]
    try:
        ruta = ctx.ws.ruta(rel, escribir=True)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    rel = ctx.ws.rel(ruta)
    existe = ruta.is_file()
    try:
        bloques = parsear_bloques(p["diff"])
    except ErrorEdicion as e:
        if existe and parece_diff_unificado(p["diff"]):
            antes = ruta.read_text(encoding="utf-8", errors="replace")
            try:
                despues, notas = aplicar_diff_unificado(antes, p["diff"])
            except ErrorEdicion as e2:
                ctx.tropiezo("search_fallido")
                raise ErrorHerramienta(str(e2))
            if despues == antes:
                return f"Sin cambios en {rel} (el diff no modificó nada)."
            _permiso_edicion(ctx, rel, diff_unificado(antes, despues, rel), False)
            _escribir(ctx, rel, despues)
            return _post_escritura(ctx, rel, antes, despues, notas + ["apliqué un diff unificado"])
        raise ErrorHerramienta(str(e))
    if not existe and not (len(bloques) == 1 and not bloques[0].buscar.strip()):
        raise ErrorHerramienta(f"No existe {rel}. Para crearlo usá write_to_file.{_sugerir_ruta(ctx, rel)}")
    antes = ruta.read_text(encoding="utf-8", errors="replace") if existe else ""
    for b in bloques:
        marcador = tiene_marcadores_perezosos(b.reemplazar)
        if marcador and marcador not in antes:
            ctx.tropiezo("marcador_perezoso")
            raise ErrorHerramienta(
                f"El REPLACE contiene '{marcador}' (código omitido). Escribí el código real completo."
            )
    try:
        despues, notas = aplicar_bloques(antes, bloques)
    except ErrorEdicion as e:
        ctx.tropiezo("search_fallido")
        raise ErrorHerramienta(str(e))
    if despues == antes:
        return f"Sin cambios en {rel} ({'; '.join(notas) or 'el contenido ya era ese'})."
    _permiso_edicion(ctx, rel, diff_unificado(antes, despues, rel), not existe)
    _escribir(ctx, rel, despues)
    return _post_escritura(ctx, rel, antes if existe else None, despues, notas)


# ==================================================================
# EJECUCIÓN Y VERIFICACIÓN
# ==================================================================
_BLOQUEADOS = [
    re.compile(p) for p in (
        r"\bsudo\b", r"(^|[;&|]\s*)su(\s|$)", r"\bmkfs", r"\bdd\s+if=", r":\(\)\s*\{",
        r"\b(shutdown|reboot|poweroff|halt)\b",
        r"\brm\s+(-\w+\s+)*(/|~|\$HOME|\*|\.)/?\*?(\s|$)",
        r"(curl|wget)\b[^|;]*\|\s*(ba|z|da)?sh\b", r">\s*/dev/(sd|block|mmc)",
        r"\bchmod\s+(-R\s+)?777\s+/", r"\bgit\s+push\b.*(--force|-f\b)",
        r"\bgit\s+(reset\s+--hard|clean\s+-\w*f)",
        r"\b(printenv|env)\s*($|[|;>])", r"\bcat\s+[^|;]*\.env\b",
    )
]

_SEGUROS = (
    "ls", "pwd", "cat ", "head ", "tail ", "wc ", "tree", "file ", "stat ", "du ",
    "grep ", "rg ", "which ", "echo ", "python -m py_compile", "python3 -m py_compile",
    "python -m pytest", "python3 -m pytest", "python -m unittest", "python3 -m unittest",
    "pytest", "node --check", "node --test", "npm test", "ruff check", "git status",
    "git diff", "git log", "git show", "pip list", "pip show", "python --version",
    "python3 --version", "node --version",
)


def comando_bloqueado(comando: str) -> Optional[str]:
    for patron in _BLOQUEADOS:
        if patron.search(comando):
            return patron.pattern
    return None


def comando_seguro(comando: str) -> bool:
    c = comando.strip()
    if any(s in c for s in (";", "&&", "||", "|", ">", "<", "`", "$(")):
        return False
    return any(c == s.strip() or c.startswith(s) for s in _SEGUROS)


PISTA_INTERACTIVO = (
    "PISTA DE REAPER: el programa es INTERACTIVO (pide datos con input()/read) y en esta prueba no recibió "
    "entrada, por eso EOFError / timeout. ESO NO ES UN BUG DEL PROGRAMA: NO lo modifiques para que deje de "
    "pedir datos ni le cambies el comportamiento. Probalo pasándole las respuestas por entrada estándar con "
    "<stdin> (una respuesta por línea), por ejemplo:\n"
    "<execute_command>\n<command>python3 calculadora.py</command>\n<stdin>2\n3\n+\nsalir\n</stdin>\n</execute_command>"
)

_RE_INTERACTIVO = re.compile(r"EOFError|EOF when reading a line|end of file|Inappropriate ioctl for device|"
                             r"read: .*: bad file descriptor|readline\(\) on closed|Tiempo agotado", re.I)


def parece_interactivo(salida: str) -> bool:
    return bool(_RE_INTERACTIVO.search(salida or ""))


def _entrada_estandar(p: dict) -> Optional[str]:
    """Texto para stdin. Acepta saltos reales o '\\n' escritos literalmente (algo que los modelos hacen)."""
    entrada = p.get("stdin")
    if entrada is None or str(entrada) == "":
        return None
    entrada = str(entrada)
    if "\n" not in entrada.strip("\n") and "\\n" in entrada:
        entrada = entrada.replace("\\n", "\n")
    return entrada.strip("\n") + "\n"


@herramienta(
    "execute_command",
    "Ejecuta un comando de shell (bash) en la raíz del workspace. Para programas interactivos (input()) pasá "
    "las respuestas en <stdin>, una por línea. Para tests preferí run_tests. Servidores se cortan por timeout.",
    [Param("command", "comando a ejecutar"),
     Param("stdin", "entrada estándar para programas interactivos (opcional, una respuesta por línea)",
           requerido=False, largo=True),
     Param("timeout", "segundos (opcional, máx 600)", requerido=False)],
    "<execute_command>\n<command>python3 main.py --ayuda</command>\n</execute_command>",
)
def execute_command(ctx: Contexto, p: dict) -> str:
    comando = p["command"].strip()
    if not comando:
        raise ErrorHerramienta("Comando vacío.")
    patron = comando_bloqueado(comando)
    if patron:
        raise ErrorHerramienta(f"Comando bloqueado por seguridad (coincide con {patron}).")
    motivo_hook = _hook_antes_de_comando(ctx, comando)
    if motivo_hook:
        raise ErrorHerramienta(f"Comando bloqueado: {motivo_hook}.")
    if ctx.settings.modo != "auto" and not comando_seguro(comando):
        if not pedir_permiso_comando(ctx, comando):
            raise ErrorHerramienta(
                "El usuario no aprobó el comando (o no hay usuario para aprobarlo). "
                "Seguí sin él o usá run_tests / validate."
            )
    timeout = min(600, _entero(p.get("timeout"), ctx.settings.exec_timeout) or ctx.settings.exec_timeout)
    entrada = _entrada_estandar(p)
    r = ejecutar(comando, cwd=ctx.ws.raiz, timeout=timeout, shell=True, entrada=entrada)
    texto = r.resumen(limite=MAX_SALIDA // 2)
    if entrada is not None:
        texto = texto.replace("\n", f"\n(stdin: {len(entrada.splitlines())} línea(s))\n", 1)
    if not r.ok and parece_interactivo(f"{r.stdout}\n{r.stderr}"):
        if entrada is None:
            texto += "\n\n" + PISTA_INTERACTIVO
        else:
            texto += ("\n\nPISTA DE REAPER: el programa pidió MÁS datos de los que pasaste en <stdin>. Agregá las "
                      "respuestas que faltan (incluida la opción para salir, si el programa tiene un menú).")
    elif not r.ok and ctx.settings.pistas_errores:
        texto = anexar_pistas(texto, 2)
    return texto


@herramienta(
    "run_tests",
    "Detecta y ejecuta la suite de tests del proyecto (pytest, unittest, npm test, node --test...).",
    [],
    "<run_tests>\n</run_tests>",
)
def run_tests(ctx: Contexto, p: dict) -> str:
    detectado = detectar_comando_tests(ctx.ws)
    if not detectado:
        return (
            "No hay tests detectados. Para Python creá tests/test_<modulo>.py con unittest "
            "(librería estándar); para JS, tests/*.test.mjs con node:test."
        )
    r = ejecutar_tests(ctx.ws, timeout=ctx.settings.tests_timeout, completo=True)
    assert r is not None
    estado = "SIN TESTS" if r.omitido else ("PASARON" if r.ok else "FALLARON")
    conteo = conteo_de_resultado(r)
    cabecera = f"Tests {estado} ({detectado[1]})" + (f": {conteo.texto()}" if conteo.reconocido else "") + "."
    if r.ok or r.omitido:
        return cabecera + "\n" + r.resumen(limite=1500)
    combinado = f"{r.stdout}\n{r.stderr}"
    detalle = fallos_relevantes(combinado, maximo=3, limite=MAX_SALIDA // 2)
    texto = f"{cabecera}\n$ {r.comando}\nexit code: {r.codigo}\n"
    if conteo.nombres_fallados:
        texto += "Fallaron: " + ", ".join(conteo.nombres_fallados[:10]) + "\n"
    texto += "DETALLE DE LOS PRIMEROS FALLOS:\n" + detalle
    if ctx.settings.pistas_errores:
        texto = anexar_pistas(texto, 2)
    return texto


@herramienta(
    "validate",
    "Corre los validadores reales (sintaxis, imports, nombres indefinidos, node --check, JSON) "
    "sobre archivos. Sin paths valida lo que cambiaste en esta tarea.",
    [Param("paths", "rutas separadas por coma (opcional)", requerido=False)],
    "<validate>\n<paths>app.py, utils.py</paths>\n</validate>",
)
def validate(ctx: Contexto, p: dict) -> str:
    texto = p.get("paths") or ""
    rels = [r.strip() for r in re.split(r"[,\n]", texto) if r.strip()] or sorted(ctx.cambios)
    if not rels:
        return "No cambiaste archivos todavía; indicá paths para validar."
    resultados = validar_archivos(ctx.ws, rels)
    if not resultados:
        return "Ninguno de esos archivos tiene validador automático (o no existen)."
    return "\n".join(r.linea() for r in resultados) + (
        "\n\nDETALLE DE FALLOS:\n" + resumen_validacion(resultados) if fallos(resultados) else ""
    )


@herramienta(
    "view_diff",
    "Muestra el diff real de los cambios hechos desde que empezó la tarea actual.",
    [],
    "<view_diff>\n</view_diff>",
)
def view_diff(ctx: Contexto, p: dict) -> str:
    cid = ctx.cid_inicio if ctx.cid_inicio is not None else ctx.ws.checkpoints.actual
    if cid is None:
        return "No hay cambios registrados."
    diff = ctx.ws.checkpoints.diff_desde(cid)
    return recortar(diff, MAX_SALIDA) if diff.strip() else "No hay cambios todavía."


# ==================================================================
# PLANIFICACIÓN, SUBAGENTES Y CIERRE (los maneja el bucle del agente)
# ==================================================================
@herramienta(
    "update_todo",
    "Mantiene tu lista de tareas. Mandá la lista COMPLETA cada vez: '[x]' hecho, '[ ]' pendiente, '[>]' en curso.",
    [Param("items", "una tarea por línea", largo=True)],
    "<update_todo>\n<items>\n[x] Leer la estructura\n[>] Agregar validación de email\n[ ] Escribir tests\n</items>\n</update_todo>",
)
def update_todo(ctx: Contexto, p: dict) -> str:
    items = []
    for linea in (p.get("items") or "").splitlines():
        linea = re.sub(r"^\s*([-*]|\d+[.)])\s*", "", linea).strip()
        if not linea:
            continue
        m = re.match(r"^\[(.)\]\s*(.+)$", linea)
        estado, texto = (m.group(1).lower(), m.group(2)) if m else (" ", linea)
        estado = {"x": "x", "✓": "x", ">": ">", "~": ">"}.get(estado, " ")
        items.append((estado, texto))
    ctx.todo[:] = items
    for estado, texto in items:
        marca = {"x": "✓", ">": "▸"}.get(estado, "○")
        ctx.ui.tenue(f"      {marca} {texto}")
    hechos = sum(1 for e, _ in items if e == "x")
    return f"Lista actualizada: {hechos}/{len(items)} hechas."


@herramienta(
    "delegate",
    "Lanza un SUBAGENTE con contexto limpio para una tarea acotada. Roles: explorador (investiga, solo lectura), "
    "implementador (escribe código), revisor (revisa, solo lectura), qa (tests), reparador (arregla fallos). "
    "Varios <delegate> de solo lectura en el MISMO mensaje corren EN PARALELO. Devuelve el informe del subagente.",
    [Param("role", "explorador | implementador | revisor | qa | reparador"),
     Param("task", "instrucciones completas y autocontenidas", largo=True),
     Param("files", "archivos relevantes separados por coma (opcional)", requerido=False)],
    "<delegate>\n<role>explorador</role>\n<task>Encontrá dónde se valida el login y qué funciones lo llaman.</task>\n</delegate>",
)
def delegate(ctx: Contexto, p: dict) -> str:  # pragma: no cover - lo intercepta el agente
    raise ErrorHerramienta("delegate solo puede usarlo un agente con permiso para delegar.")


@herramienta(
    "ask_user",
    "Hace una pregunta al usuario cuando falta información imprescindible. No la uses para pedir permiso.",
    [Param("question", "pregunta concreta")],
    "<ask_user>\n<question>¿Querés guardar los datos en JSON o en SQLite?</question>\n</ask_user>",
)
def ask_user(ctx: Contexto, p: dict) -> str:
    if not ctx.ui.interactivo:
        return "El usuario no está disponible. Elegí la opción más simple y segura, y dejala anotada en el informe."
    respuesta = ctx.ui.preguntar(f"  [{ctx.etiqueta}] {p['question']}")
    return f"Respuesta del usuario: {respuesta or '(sin respuesta)'}"


@herramienta(
    "attempt_completion",
    "Termina la tarea. Solo cuando verificaste el resultado. REAPER valida los archivos cambiados antes de aceptar.",
    [Param("result", "informe final: qué hiciste, archivos, cómo se verificó, pendientes", largo=True)],
    "<attempt_completion>\n<result>\nAgregué hoy() en utils/fechas.py y su test. run_tests: 3 tests pasaron.\n</result>\n</attempt_completion>",
)
def attempt_completion(ctx: Contexto, p: dict) -> str:  # pragma: no cover - lo intercepta el agente
    return p.get("result", "")


def resumen_params(nombre: str, params: dict) -> str:
    if nombre in ("read_symbol", "replace_symbol", "insert_after_symbol"):
        return f"{params.get('path', '')} :: {params.get('symbol', '')}".strip(" :")
    if nombre in ("append_to_file", "insert_lines", "replace_lines", "delete_file"):
        extra = ""
        if params.get("line") or params.get("desde"):
            extra = f" @{params.get('line') or params.get('desde')}"
        return params.get("path", "") + extra
    if nombre == "move_file":
        return f"{params.get('path', '')} → {params.get('new_path', '')}"
    if nombre == "find_references":
        return params.get("symbol", "")
    if nombre in ("save_note", "learn_lesson"):
        return recortar(params.get("note", "") or params.get("lesson", ""), 70)
    if nombre in ("read_file", "write_to_file", "replace_in_file", "code_outline", "list_files"):
        detalle = params.get("path", "")
        if nombre == "read_file" and (params.get("desde") or params.get("hasta")):
            detalle += f" [{params.get('desde', '')}-{params.get('hasta', '')}]"
        return detalle
    if nombre == "search_files":
        return f"/{params.get('regex', '')}/ {params.get('file_pattern', '')}"
    if nombre == "execute_command":
        return params.get("command", "") + ("  < stdin" if params.get("stdin") else "")
    if nombre == "delegate":
        return f"{params.get('role', '?')}: {params.get('task', '')[:70]}"
    if nombre == "validate":
        return params.get("paths", "(cambios)")
    return ""
