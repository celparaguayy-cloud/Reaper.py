"""
Índice de símbolos: funciones, clases y métodos con su rango exacto de líneas.

Para un modelo de 24B, leer un archivo entero de 1500 líneas para cambiar una
función es la forma más rápida de llenar el contexto y equivocarse. Con este
índice REAPER puede:
  - read_symbol: leer solo `Cliente.guardar` (con números de línea)
  - replace_symbol: reemplazar una función entera por nombre (más robusto que SEARCH/REPLACE)
  - find_references: encontrar dónde se usa un nombre
  - armar el mapa de archivos relevantes para un pedido

Python usa el AST real. JS/TS/Go/Rust/Java/C/C++/C#/PHP/Kotlin/Swift/Dart
usan detección de cabeceras + un tokenizador que salta strings, comentarios,
template literals y regex para encontrar la llave de cierre correcta.
Shell, Ruby y Lua tienen detectores propios.
"""


@dataclass
class Simbolo:
    nombre: str
    tipo: str  # funcion | clase | metodo | variable | tipo | interfaz | modulo
    archivo: str
    inicio: int
    fin: int
    firma: str = ""
    padre: str = ""
    indent: str = ""

    @property
    def nombre_completo(self) -> str:
        return f"{self.padre}.{self.nombre}" if self.padre else self.nombre

    @property
    def lineas(self) -> int:
        return self.fin - self.inicio + 1

    def describir(self) -> str:
        return f"{self.archivo}:{self.inicio}-{self.fin} {self.tipo} {self.nombre_completo}{self.firma}"


LENGUAJES_LLAVES = {
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".cs": "java", ".scala": "java",
    ".go": "go", ".rs": "rust", ".c": "c", ".h": "c", ".cpp": "c", ".hpp": "c", ".cc": "c",
    ".cxx": "c", ".swift": "swift", ".php": "php", ".dart": "java",
}


# ======================================================================
# PYTHON
# ======================================================================
def _firma_python(nodo: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:
    try:
        args = ast.unparse(nodo.args)
    except (AttributeError, ValueError):
        args = "..."
    retorno = ""
    if nodo.returns is not None:
        try:
            retorno = " -> " + ast.unparse(nodo.returns)
        except (AttributeError, ValueError):
            retorno = ""
    return f"({args}){retorno}"


def simbolos_python(texto: str, archivo: str = "") -> list[Simbolo]:
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return simbolos_python_regex(texto, archivo)
    lineas = texto.splitlines()
    salida: list[Simbolo] = []

    def indent_de(linea: int) -> str:
        if 0 < linea <= len(lineas):
            l = lineas[linea - 1]
            return l[: len(l) - len(l.lstrip())]
        return ""

    def visitar(cuerpo, padre: str, en_clase: bool) -> None:
        for nodo in cuerpo:
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inicio = min([d.lineno for d in nodo.decorator_list] + [nodo.lineno])
                tipo = "metodo" if en_clase else "funcion"
                pref = "async " if isinstance(nodo, ast.AsyncFunctionDef) else ""
                salida.append(Simbolo(nodo.name, tipo, archivo, inicio, nodo.end_lineno or nodo.lineno,
                                      (pref and " async") + _firma_python(nodo), padre, indent_de(inicio)))
                # Funciones anidadas: se indexan con el padre para poder leerlas también.
                visitar(nodo.body, f"{padre}.{nodo.name}" if padre else nodo.name, False)
            elif isinstance(nodo, ast.ClassDef):
                inicio = min([d.lineno for d in nodo.decorator_list] + [nodo.lineno])
                bases = ", ".join(ast.unparse(b) for b in nodo.bases) if nodo.bases else ""
                salida.append(Simbolo(nodo.name, "clase", archivo, inicio, nodo.end_lineno or nodo.lineno,
                                      f"({bases})" if bases else "", padre, indent_de(inicio)))
                visitar(nodo.body, f"{padre}.{nodo.name}" if padre else nodo.name, True)
            elif isinstance(nodo, (ast.Assign, ast.AnnAssign)) and not padre:
                objetivos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
                for t in objetivos:
                    if isinstance(t, ast.Name) and (t.id.isupper() or t.id[:1].isupper()):
                        salida.append(Simbolo(t.id, "variable", archivo, nodo.lineno, nodo.end_lineno or nodo.lineno,
                                              "", "", indent_de(nodo.lineno)))
            elif isinstance(nodo, (ast.If, ast.Try)) and not padre:
                # Definiciones condicionales de primer nivel (try: import ... / if TYPE_CHECKING:)
                internos = list(nodo.body) + list(getattr(nodo, "orelse", []))
                for h in getattr(nodo, "handlers", []):
                    internos.extend(h.body)
                visitar([n for n in internos if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))],
                        padre, en_clase)

    visitar(arbol.body, "", False)
    return salida


_RE_PY_DEF = re.compile(r"^(\s*)(async\s+def|def|class)\s+([A-Za-z_]\w*)\s*(\([^)]*\)?)?")


def simbolos_python_regex(texto: str, archivo: str = "") -> list[Simbolo]:
    """Respaldo para archivos Python con errores de sintaxis: rangos por indentación."""
    lineas = texto.splitlines()
    salida: list[Simbolo] = []
    pila: list[tuple[int, str]] = []
    for i, linea in enumerate(lineas, start=1):
        m = _RE_PY_DEF.match(linea)
        if not m:
            continue
        indent = len(m.group(1).expandtabs(4))
        while pila and pila[-1][0] >= indent:
            pila.pop()
        padre = ".".join(n for _, n in pila)
        fin = i
        for j in range(i, len(lineas)):
            sig = lineas[j]
            if sig.strip() and len(sig) - len(sig.lstrip()) <= indent and not sig.lstrip().startswith(("#", ")", "]")):
                break
            fin = j + 1
        tipo = "clase" if m.group(2) == "class" else ("metodo" if pila and any(True for _ in pila) else "funcion")
        salida.append(Simbolo(m.group(3), tipo, archivo, i, max(i, fin), m.group(4) or "", padre, m.group(1)))
        pila.append((indent, m.group(3)))
    return salida


# ======================================================================
# LENGUAJES CON LLAVES
# ======================================================================
def _saltar_hasta_llave_cierre(texto: str, inicio: int, lenguaje: str) -> Optional[int]:
    """
    Desde la posición de una '{' devuelve la posición de su '}' de cierre,
    saltando strings, comentarios, template literals y regex (aprox.).
    """
    nivel = 0
    i, n = inicio, len(texto)
    previo_significativo = ""
    while i < n:
        ch = texto[i]
        sig = texto[i + 1] if i + 1 < n else ""
        if ch == "/" and sig == "/":
            fin = texto.find("\n", i)
            i = n if fin < 0 else fin
            continue
        if ch == "/" and sig == "*":
            fin = texto.find("*/", i + 2)
            i = n if fin < 0 else fin + 2
            continue
        if ch == "#" and lenguaje == "php":
            fin = texto.find("\n", i)
            i = n if fin < 0 else fin
            continue
        if ch in "\"`" or (ch == "'" and lenguaje != "rust"):
            j = i + 1
            while j < n and texto[j] != ch:
                if texto[j] == "\\":
                    j += 1
                elif texto[j] == "\n" and ch != "`" and lenguaje not in ("go",):
                    break
                j += 1
            i = j + 1
            previo_significativo = ch
            continue
        if ch == "'" and lenguaje == "rust":
            m = re.match(r"'(?:\\.|[^\\'])'", texto[i:i + 6])
            if m:
                i += len(m.group(0))
                continue
        if ch == "/" and lenguaje == "js" and previo_significativo in ("", "(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";"):
            j = i + 1
            en_clase = False
            while j < n and texto[j] != "\n":
                c = texto[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    en_clase = True
                elif c == "]":
                    en_clase = False
                elif c == "/" and not en_clase:
                    break
                j += 1
            if j < n and texto[j] == "/":
                i = j + 1
                previo_significativo = "/"
                continue
        if ch == "{":
            nivel += 1
        elif ch == "}":
            nivel -= 1
            if nivel == 0:
                return i
        if not ch.isspace():
            previo_significativo = ch
        i += 1
    return None


_CABECERAS = {
    "js": [
        (re.compile(r"^(\s*)(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*([\w$]+)\s*(\([^)]*\))?"), "funcion"),
        (re.compile(r"^(\s*)(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([\w$]+)"), "clase"),
        (re.compile(r"^(\s*)(?:export\s+)?interface\s+([\w$]+)"), "interfaz"),
        (re.compile(r"^(\s*)(?:export\s+)?(?:const\s+)?enum\s+([\w$]+)"), "tipo"),
        (re.compile(r"^(\s*)(?:export\s+)?type\s+([\w$]+)\s*(?:<[^=]*>)?\s*="), "tipo"),
        (re.compile(r"^(\s*)(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|[\w$]+\s*=>)"), "funcion"),
        (re.compile(r"^(\s*)(?:(?:public|private|protected|static|readonly|override|async|get|set)\s+)*(#?[\w$]+)\s*(\([^)]*\))\s*(?::\s*[^{]+)?\{\s*$"), "metodo"),
    ],
    "java": [
        (re.compile(r"^(\s*)(?:(?:public|private|protected|static|final|abstract|sealed|partial|internal|open|data)\s+)*(?:class|interface|enum|record|struct|object)\s+([\w$]+)"), "clase"),
        (re.compile(r"^(\s*)(?:(?:public|private|protected|static|final|abstract|synchronized|override|async|virtual|internal|suspend|open)\s+)*(?:fun\s+)?(?:<[^>]+>\s+)?(?:[\w<>\[\],.?]+\s+)?([\w$]+)\s*(\([^)]*\))\s*(?::\s*[\w<>?,. ]+)?\s*(?:throws\s+[\w., ]+)?\s*\{?\s*$"), "metodo"),
    ],
    "kotlin": [
        (re.compile(r"^(\s*)(?:(?:public|private|protected|internal|open|abstract|sealed|data|enum|inner)\s+)*(?:class|interface|object)\s+([\w$]+)"), "clase"),
        (re.compile(r"^(\s*)(?:(?:public|private|protected|internal|open|override|suspend|inline)\s+)*fun\s+(?:<[^>]+>\s+)?(?:[\w.]+\.)?([\w$]+)\s*(\([^)]*\))"), "funcion"),
    ],
    "go": [
        (re.compile(r"^()func\s+\(\s*\w+\s+\*?([\w]+)\s*\)\s+([\w]+)\s*(\([^)]*\))"), "metodo_go"),
        (re.compile(r"^()func\s+([\w]+)\s*(\([^)]*\))"), "funcion"),
        (re.compile(r"^()type\s+([\w]+)\s+(?:struct|interface)"), "tipo"),
    ],
    "rust": [
        (re.compile(r"^(\s*)(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:const\s+)?fn\s+([\w]+)\s*(?:<[^>]*>)?\s*(\([^)]*\))?"), "funcion"),
        (re.compile(r"^(\s*)(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+([\w]+)"), "tipo"),
        (re.compile(r"^(\s*)impl(?:<[^>]*>)?\s+(?:[\w:<>, ]+\s+for\s+)?([\w]+)"), "clase"),
        (re.compile(r"^(\s*)(?:pub\s+)?mod\s+([\w]+)\s*\{"), "modulo"),
    ],
    "c": [
        (re.compile(r"^()(?:struct|class|union|enum)\s+([\w]+)\s*(?::[^{]*)?\{?\s*$"), "clase"),
        (re.compile(r"^(\s*)(?:(?:static|inline|extern|virtual|const|unsigned|signed|long|short|struct)\s+)*[\w:<>*&]+[\s*&]+(?:[\w]+::)?([\w~]+)\s*(\([^;]*\))\s*(?:const)?\s*(?:override)?\s*\{?\s*$"), "funcion"),
    ],
    "swift": [
        (re.compile(r"^(\s*)(?:(?:public|private|fileprivate|internal|open|final)\s+)*(?:class|struct|enum|protocol|extension|actor)\s+([\w]+)"), "clase"),
        (re.compile(r"^(\s*)(?:(?:public|private|fileprivate|internal|open|static|override|mutating|final)\s+)*func\s+([\w]+)\s*(\([^)]*\))?"), "funcion"),
    ],
    "php": [
        (re.compile(r"^(\s*)(?:(?:abstract|final)\s+)?(?:class|interface|trait|enum)\s+([\w]+)"), "clase"),
        (re.compile(r"^(\s*)(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+&?([\w]+)\s*(\([^)]*\))?"), "funcion"),
    ],
}

_NO_SON_METODOS = {"if", "for", "while", "switch", "catch", "function", "return", "else", "do", "try",
                   "with", "new", "typeof", "await", "yield", "constructor_", "super", "this", "elif", "sizeof"}


def _offsets_lineas(texto: str) -> list[int]:
    offsets = [0]
    for m in re.finditer("\n", texto):
        offsets.append(m.end())
    return offsets


def _linea_de_offset(offsets: list[int], pos: int) -> int:
    lo, hi = 0, len(offsets) - 1
    while lo < hi:
        medio = (lo + hi + 1) // 2
        if offsets[medio] <= pos:
            lo = medio
        else:
            hi = medio - 1
    return lo + 1


def simbolos_llaves(texto: str, archivo: str, lenguaje: str) -> list[Simbolo]:
    patrones = _CABECERAS.get(lenguaje, [])
    lineas = texto.splitlines()
    offsets = _offsets_lineas(texto)
    salida: list[Simbolo] = []
    contenedores: list[Simbolo] = []
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        despojada = linea.strip()
        if not despojada or despojada.startswith(("//", "/*", "*", "#", "import ", "package ", "using ")):
            i += 1
            continue
        for patron, tipo in patrones:
            m = patron.match(linea)
            if not m:
                continue
            if tipo == "metodo_go":
                indent, receptor, nombre = m.group(1), m.group(2), m.group(3)
                firma = m.group(4) or ""
                padre_forzado = receptor
                tipo_real = "metodo"
            else:
                indent, nombre = m.group(1), m.group(2)
                firma = m.group(3) if m.lastindex and m.lastindex >= 3 and m.group(3) else ""
                padre_forzado = None
                tipo_real = tipo
            if tipo == "metodo" and (nombre in _NO_SON_METODOS or keyword.iskeyword(nombre)):
                break
            if tipo == "metodo" and lenguaje == "js" and not contenedores:
                break  # un "metodo" suelto fuera de clase suele ser una llamada o un if
            if tipo == "metodo" and lenguaje in ("java",) and re.match(r"^\s*(return|new|else|throw)\b", linea):
                break
            # Buscar la llave de apertura en esta línea o las 3 siguientes (firmas partidas).
            pos_linea = offsets[i]
            limite = offsets[min(len(offsets) - 1, i + 4)] if i + 4 < len(offsets) else len(texto)
            abre = -1
            for k in range(pos_linea + len(indent), limite):
                c = texto[k]
                if c == "{":
                    abre = k
                    break
                if c == ";" and tipo_real not in ("tipo",):
                    break
                if c == "=" and lenguaje == "js" and tipo_real == "funcion" and "=>" not in texto[k:k + 2] \
                        and texto[k:k + 2] != "==" and "function" not in linea and "=>" not in linea:
                    break
            if abre < 0:
                # Función flecha de una sola expresión o declaración sin cuerpo.
                fin_linea = i + 1
                if lenguaje == "js" and "=>" in linea and not linea.rstrip().endswith((";", ")")):
                    j = i + 1
                    while j < len(lineas) and lineas[j].strip() and not lineas[j].rstrip().endswith(";"):
                        j += 1
                    fin_linea = min(len(lineas), j + 1)
                salida.append(Simbolo(nombre, tipo_real, archivo, i + 1, fin_linea, firma,
                                      padre_forzado or (contenedores[-1].nombre if contenedores else ""), indent))
                break
            cierre = _saltar_hasta_llave_cierre(texto, abre, lenguaje)
            fin = _linea_de_offset(offsets, cierre) if cierre is not None else len(lineas)
            while contenedores and contenedores[-1].fin < i + 1:
                contenedores.pop()
            padre = padre_forzado or (contenedores[-1].nombre if contenedores else "")
            if tipo_real == "metodo" and not padre and lenguaje in ("java", "c"):
                tipo_real = "funcion"
            simbolo = Simbolo(nombre, tipo_real, archivo, i + 1, fin, firma, padre, indent)
            salida.append(simbolo)
            if tipo_real in ("clase", "interfaz", "modulo") or (tipo_real == "tipo" and lenguaje in ("rust", "go")):
                contenedores.append(simbolo)
            break
        i += 1
    return salida


# ======================================================================
# SHELL, RUBY, LUA
# ======================================================================
_RE_SH_FUNC = re.compile(r"^(\s*)(?:function\s+([\w:-]+)\s*(?:\(\s*\))?|([\w:-]+)\s*\(\s*\))\s*\{?")


def simbolos_shell(texto: str, archivo: str) -> list[Simbolo]:
    salida = []
    lineas = texto.splitlines()
    offsets = _offsets_lineas(texto)
    for i, linea in enumerate(lineas):
        m = _RE_SH_FUNC.match(linea)
        if not m or linea.strip().startswith("#"):
            continue
        nombre = m.group(2) or m.group(3)
        abre = texto.find("{", offsets[i], offsets[min(len(offsets) - 1, i + 2)] if i + 2 < len(offsets) else len(texto))
        if abre < 0:
            continue
        # En bash la llave de cierre solo cuenta en posición de comando: una línea que empieza con '}'
        # con la misma indentación (o menos) que la función. 'echo }' no cierra nada.
        indent = len(m.group(1).expandtabs(4))
        fin = None
        if linea.rstrip().endswith("}") and linea.count("{") == linea.count("}"):
            fin = i + 1  # función de una sola línea: f() { echo hola; }
        else:
            for j in range(i + 1, len(lineas)):
                sig = lineas[j]
                if re.match(r"^\s*\}(\s|;|>|$|\|)", sig) and len(sig) - len(sig.lstrip()) <= indent:
                    fin = j + 1
                    break
        if fin is None:
            cierre = _saltar_hasta_llave_cierre(texto, abre, "sh")
            fin = _linea_de_offset(offsets, cierre) if cierre is not None else len(lineas)
        salida.append(Simbolo(nombre, "funcion", archivo, i + 1, fin, "()", "", m.group(1)))
    return salida


_RE_RB = re.compile(r"^(\s*)(def|class|module)\s+([\w.:?!=]+)")
_RE_RB_ABRE = re.compile(r"^\s*(def|class|module|if|unless|while|until|case|begin|for)\b|\bdo(\s*\|[^|]*\|)?\s*$")
_RE_LUA = re.compile(r"^(\s*)(?:local\s+)?function\s+([\w.:]+)\s*(\([^)]*\))")
_RE_LUA_ABRE = re.compile(r"\b(function|do|then|repeat)\b")


def simbolos_end(texto: str, archivo: str, lenguaje: str) -> list[Simbolo]:
    """Ruby y Lua: bloques que terminan con 'end' (conteo de aperturas/cierres por línea)."""
    lineas = texto.splitlines()
    salida = []
    patron = _RE_RB if lenguaje == "ruby" else _RE_LUA
    for i, linea in enumerate(lineas):
        m = patron.match(linea)
        if not m:
            continue
        nivel = 0
        fin = len(lineas)
        for j in range(i, len(lineas)):
            l = re.sub(r"#.*$" if lenguaje == "ruby" else r"--.*$", "", lineas[j])
            l = re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", "", l)
            if lenguaje == "ruby":
                if _RE_RB_ABRE.search(l) and not re.search(r"\bend\s*$", l.strip()) or (j == i):
                    nivel += 1
            else:
                nivel += len(_RE_LUA_ABRE.findall(l))
            nivel -= len(re.findall(r"\bend\b", l))
            if lenguaje == "lua":
                nivel -= len(re.findall(r"\buntil\b", l))
            if nivel <= 0 and j >= i:
                fin = j + 1
                break
        if lenguaje == "ruby":
            tipo = "funcion" if m.group(2) == "def" else "clase"
            nombre = m.group(3)
            firma = ""
        else:
            tipo, nombre, firma = "funcion", m.group(2), m.group(3)
        padre = ""
        if "." in nombre or ":" in nombre:
            padre, nombre = re.split(r"[.:]", nombre, maxsplit=1)[0], re.split(r"[.:]", nombre)[-1]
        salida.append(Simbolo(nombre, tipo, archivo, i + 1, fin, firma, padre, m.group(1)))
    return salida


# ======================================================================
# API
# ======================================================================
def extraer_simbolos(ruta: Path, texto: Optional[str] = None, archivo: str = "") -> list[Simbolo]:
    if texto is None:
        try:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    archivo = archivo or ruta.name
    sufijo = ruta.suffix.lower()
    try:
        if sufijo == ".py":
            return simbolos_python(texto, archivo)
        if sufijo in LENGUAJES_LLAVES:
            return simbolos_llaves(texto, archivo, LENGUAJES_LLAVES[sufijo])
        if sufijo in (".sh", ".bash", ".zsh"):
            return simbolos_shell(texto, archivo)
        if sufijo == ".rb":
            return simbolos_end(texto, archivo, "ruby")
        if sufijo == ".lua":
            return simbolos_end(texto, archivo, "lua")
    except RecursionError:
        return []
    return []


def elegir_simbolo(simbolos: Sequence[Simbolo], nombre: str) -> tuple[list[Simbolo], list[str]]:
    """
    Encuentra el símbolo pedido: 'Clase.metodo', 'metodo' o 'clase'. Devuelve
    (coincidencias, sugerencias si no hay ninguna).
    """
    nombre = (nombre or "").strip().strip("`'\"").strip()
    nombre = re.sub(r"\(.*\)$", "", nombre).strip()
    nombre = nombre.replace("::", ".").replace("#", ".")
    for prefijo in ("def ", "class ", "function ", "func ", "fn "):
        if nombre.startswith(prefijo):
            nombre = nombre[len(prefijo):]
    if not nombre:
        return [], []
    exactos = [s for s in simbolos if s.nombre_completo == nombre]
    if not exactos:
        exactos = [s for s in simbolos if s.nombre_completo.endswith("." + nombre) or s.nombre == nombre]
    if not exactos:
        bajo = nombre.lower()
        exactos = [s for s in simbolos if s.nombre_completo.lower() == bajo or s.nombre.lower() == bajo]
    if exactos:
        return exactos, []
    nombres = sorted({s.nombre_completo for s in simbolos} | {s.nombre for s in simbolos})
    return [], difflib.get_close_matches(nombre, nombres, n=4, cutoff=0.55)


def texto_de_simbolo(texto: str, simbolo: Simbolo, numerar: bool = True) -> str:
    lineas = texto.splitlines()
    tramo = lineas[simbolo.inicio - 1: simbolo.fin]
    if not numerar:
        return "\n".join(tramo)
    return "\n".join(f"{simbolo.inicio + k:>5}| {l}" for k, l in enumerate(tramo))


def _indent_minimo(lineas: Sequence[str]) -> str:
    indents = [l[: len(l) - len(l.lstrip())] for l in lineas if l.strip()]
    if not indents:
        return ""
    return min(indents, key=len)


def reemplazar_simbolo(texto: str, simbolo: Simbolo, nuevo: str) -> str:
    """
    Reemplaza el rango del símbolo por 'nuevo', reindentándolo para que quede
    al nivel del símbolo original (el modelo suele escribir métodos sin indentar).
    """
    lineas = texto.splitlines(keepends=True)
    nuevas = nuevo.rstrip("\n").split("\n")
    actual = _indent_minimo(nuevas)
    objetivo = simbolo.indent
    if actual != objetivo:
        ajustadas = []
        for l in nuevas:
            if not l.strip():
                ajustadas.append("")
            elif l.startswith(actual):
                ajustadas.append(objetivo + l[len(actual):])
            else:
                ajustadas.append(objetivo + l.lstrip())
        nuevas = ajustadas
    bloque = "\n".join(nuevas) + "\n"
    termina_sin_salto = simbolo.fin >= len(lineas) and lineas and not lineas[-1].endswith("\n")
    if termina_sin_salto:
        bloque = bloque[:-1]
    return "".join(lineas[: simbolo.inicio - 1]) + bloque + "".join(lineas[simbolo.fin:])


def insertar_tras_simbolo(texto: str, simbolo: Simbolo, nuevo: str, separacion: int = 2) -> str:
    """Inserta 'nuevo' después del símbolo (con líneas en blanco de separación y su indentación)."""
    lineas = texto.splitlines(keepends=True)
    nuevas = nuevo.rstrip("\n").split("\n")
    actual = _indent_minimo(nuevas)
    if actual != simbolo.indent:
        nuevas = [(simbolo.indent + l[len(actual):]) if l.strip() and l.startswith(actual) else
                  (simbolo.indent + l.lstrip() if l.strip() else "") for l in nuevas]
    separador = "\n" * (separacion if not simbolo.indent else 1)
    previo = "".join(lineas[: simbolo.fin])
    if previo and not previo.endswith("\n"):
        previo += "\n"
    return previo + separador + "\n".join(nuevas) + "\n" + "".join(lineas[simbolo.fin:])


class IndiceSimbolos:
    """Índice perezoso de símbolos del workspace con caché por (mtime, tamaño)."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self._cache: dict[str, tuple[float, int, list[Simbolo]]] = {}
        self._lock = threading.Lock()

    def de_archivo(self, rel: str) -> list[Simbolo]:
        try:
            ruta = self.ws.ruta(rel)
            if es_archivo_sensible(ruta.name):     # read_symbol tampoco expone estructura de secretos (R-002)
                return []
            st = ruta.stat()
        except (ErrorRuta, OSError):
            return []
        rel = self.ws.rel(ruta)
        with self._lock:
            cache = self._cache.get(rel)
            if cache and cache[0] == st.st_mtime and cache[1] == st.st_size:
                return cache[2]
        if st.st_size > 2_000_000:
            return []
        simbolos = extraer_simbolos(ruta, archivo=rel)
        with self._lock:
            self._cache[rel] = (st.st_mtime, st.st_size, simbolos)
        return simbolos

    def archivos(self, limite: int = 1500) -> list[str]:
        return [r for r in self.ws.archivos_codigo(limite=limite)
                if Path(r).suffix.lower() in (".py", ".sh", ".bash", ".rb", ".lua", *LENGUAJES_LLAVES)]

    def todos(self, limite: int = 1500) -> list[Simbolo]:
        salida = []
        for rel in self.archivos(limite):
            salida.extend(self.de_archivo(rel))
        return salida

    def buscar(self, nombre: str, archivo: Optional[str] = None) -> tuple[list[Simbolo], list[str]]:
        simbolos = self.de_archivo(archivo) if archivo else self.todos()
        return elegir_simbolo(simbolos, nombre)

    def referencias(self, nombre: str, limite: int = 60) -> list[str]:
        """Líneas donde aparece el nombre como palabra completa (excluye su propia definición)."""
        corto = nombre.split(".")[-1]
        if not corto:
            return []
        patron = re.compile(r"(?<![\w$])" + re.escape(corto) + r"(?![\w$])")
        definiciones = {(s.archivo, s.inicio) for s in self.todos() if s.nombre == corto}
        hallazgos = []
        for rel in self.ws.archivos_codigo(limite=2000):
            ruta = self.ws.raiz / rel
            try:
                if ruta.stat().st_size > 600_000:
                    continue
                texto = ruta.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if corto not in texto:
                continue
            for n, linea in enumerate(texto.splitlines(), start=1):
                if (rel, n) in definiciones:
                    continue
                if patron.search(linea):
                    hallazgos.append(f"{rel}:{n}: {linea.strip()[:160]}")
                    if len(hallazgos) >= limite:
                        return hallazgos
        return hallazgos

    def invalidar(self, rel: Optional[str] = None) -> None:
        with self._lock:
            if rel is None:
                self._cache.clear()
            else:
                self._cache.pop(rel, None)


_INDICES: dict[str, IndiceSimbolos] = {}
_LOCK_INDICES = threading.Lock()


def indice_de(ws: Workspace) -> IndiceSimbolos:
    clave = str(ws.raiz)
    with _LOCK_INDICES:
        if clave not in _INDICES or _INDICES[clave].ws is not ws:
            _INDICES[clave] = IndiceSimbolos(ws)
        return _INDICES[clave]
