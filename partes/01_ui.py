"""
Salida de consola: colores (truecolor / 256 / básico), temas, diffs, spinner,
cajas, tablas, resaltado de código, markdown y confirmaciones. Thread-safe.

Todo lo que se imprime pasa por la clase UI. En tests se usa
UI(silencioso=True, respuestas=[...]) para no imprimir y contestar preguntas.
"""

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _hay_color() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR") or os.getenv("REAPER_COLOR"):
        return True
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _profundidad_color() -> int:
    """24 = truecolor, 8 = 256 colores, 4 = 16 colores, 0 = sin color."""
    if not _hay_color():
        return 0
    forzado = os.getenv("REAPER_COLOR", "").strip().lower()
    if forzado in ("24", "truecolor", "24bit"):
        return 24
    if forzado in ("8", "256"):
        return 8
    if forzado in ("4", "16", "basico", "básico"):
        return 4
    colorterm = os.getenv("COLORTERM", "").lower()
    if "truecolor" in colorterm or "24bit" in colorterm:
        return 24
    # Termux soporta truecolor aunque no siempre exporte COLORTERM.
    if "com.termux" in os.getenv("PREFIX", "") or os.getenv("TERMUX_VERSION"):
        return 24
    term = os.getenv("TERM", "")
    if "256" in term or term.startswith(("xterm", "screen", "tmux", "rxvt")):
        return 8
    return 4


_USAR_COLOR = _hay_color()
PROFUNDIDAD_COLOR = _profundidad_color()


def _c(codigo: str) -> str:
    return codigo if _USAR_COLOR else ""


def _rgb_a_256(r: int, g: int, b: int) -> int:
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round(((r - 8) / 247) * 24) + 232
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def _rgb_a_16(r: int, g: int, b: int) -> int:
    brillo = max(r, g, b)
    if brillo < 50:
        return 30
    base = 30 + ((1 if r > 127 else 0) | (2 if g > 127 else 0) | (4 if b > 127 else 0))
    return base + 60 if brillo > 190 else base


def rgb(r: int, g: int, b: int, fondo: bool = False) -> str:
    """Código ANSI para un color RGB, degradado según lo que soporte la terminal."""
    if not _USAR_COLOR:
        return ""
    if PROFUNDIDAD_COLOR >= 24:
        return f"\033[{48 if fondo else 38};2;{r};{g};{b}m"
    if PROFUNDIDAD_COLOR >= 8:
        return f"\033[{48 if fondo else 38};5;{_rgb_a_256(r, g, b)}m"
    codigo = _rgb_a_16(r, g, b)
    return f"\033[{codigo + 10 if fondo else codigo}m"


def hex_a_rgb(valor: str) -> tuple[int, int, int]:
    valor = valor.strip().lstrip("#")
    if len(valor) == 3:
        valor = "".join(ch * 2 for ch in valor)
    if len(valor) != 6 or any(ch not in string.hexdigits for ch in valor):
        raise ValueError(f"color hex inválido: {valor!r}")
    return int(valor[0:2], 16), int(valor[2:4], 16), int(valor[4:6], 16)


def color_hex(valor: str, fondo: bool = False) -> str:
    return rgb(*hex_a_rgb(valor), fondo=fondo)


def sin_ansi(texto: str) -> str:
    return _ANSI.sub("", texto or "")


def ancho_visible(texto: str) -> int:
    """Columnas que ocupa el texto en la terminal (sin ANSI, con anchos de Unicode)."""
    total = 0
    for ch in sin_ansi(texto):
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def ancho_terminal(defecto: int = 80) -> int:
    try:
        columnas = shutil.get_terminal_size((defecto, 24)).columns
    except (OSError, ValueError):
        columnas = defecto
    return max(30, min(columnas, 200))


def ajustar(texto: str, ancho: int) -> str:
    """Recorta o rellena con espacios hasta 'ancho' columnas visibles (respeta ANSI)."""
    actual = ancho_visible(texto)
    if actual <= ancho:
        return texto + " " * (ancho - actual)
    salida, usado = [], 0
    pos = 0
    while pos < len(texto) and usado < ancho - 1:
        m = _ANSI.match(texto, pos)
        if m:
            salida.append(m.group(0))
            pos = m.end()
            continue
        ch = texto[pos]
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if usado + w > ancho - 1:
            break
        salida.append(ch)
        usado += w
        pos += 1
    return "".join(salida) + "…" + (C.RESET if _USAR_COLOR else "") + " " * max(0, ancho - usado - 1)


class C:
    """Paleta activa. Los nombres básicos son los mismos de v6 para no romper nada."""

    RESET = _c("\033[0m")
    BOLD = _c("\033[1m")
    DIM = _c("\033[2m")
    ITALICA = _c("\033[3m")
    SUBRAYADO = _c("\033[4m")
    INVERSO = _c("\033[7m")
    CYAN = _c("\033[96m")
    VERDE = _c("\033[92m")
    AMARILLO = _c("\033[93m")
    ROJO = _c("\033[91m")
    MAGENTA = _c("\033[95m")
    AZUL = _c("\033[94m")
    GRIS = _c("\033[90m")
    BLANCO = _c("\033[97m")
    # Colores del dragón (se recalculan con aplicar_tema).
    NARANJA = rgb(255, 140, 40)
    FUEGO = rgb(255, 90, 30)
    ORO = rgb(255, 200, 60)
    VIOLETA = rgb(170, 90, 230)
    ROSA = rgb(255, 80, 140)
    ESCAMA = rgb(110, 150, 230)
    HIELO = rgb(170, 210, 255)


TEMAS = {
    "dragon": {
        "titulo": (255, 140, 40), "info": (120, 200, 255), "ok": (90, 220, 120),
        "aviso": (255, 200, 60), "error": (255, 85, 85), "tenue": (130, 130, 150),
        "agente": (190, 110, 255), "herramienta": (110, 150, 230), "texto": (235, 235, 240),
        "prompt": (255, 140, 40), "acento": (255, 80, 140),
    },
    "oceano": {
        "titulo": (80, 200, 255), "info": (120, 220, 255), "ok": (80, 230, 170),
        "aviso": (255, 220, 120), "error": (255, 110, 110), "tenue": (120, 140, 160),
        "agente": (120, 160, 255), "herramienta": (90, 200, 220), "texto": (230, 240, 245),
        "prompt": (80, 200, 255), "acento": (140, 120, 255),
    },
    "matrix": {
        "titulo": (60, 255, 120), "info": (120, 255, 160), "ok": (60, 255, 120),
        "aviso": (200, 255, 100), "error": (255, 90, 90), "tenue": (60, 140, 80),
        "agente": (150, 255, 150), "herramienta": (90, 200, 120), "texto": (200, 255, 210),
        "prompt": (60, 255, 120), "acento": (180, 255, 60),
    },
    "clasico": None,  # los 16 colores de v6
    "mono": "mono",
}


class Tema:
    """Colores semánticos usados por UI. Se pueden cambiar en caliente (/tema)."""

    nombre = "dragon"
    titulo = C.CYAN
    info = C.CYAN
    ok = C.VERDE
    aviso = C.AMARILLO
    error = C.ROJO
    tenue = C.GRIS
    agente = C.MAGENTA
    herramienta = C.AZUL
    texto = C.BLANCO
    prompt = C.VERDE
    acento = C.MAGENTA


def aplicar_tema(nombre: str) -> str:
    nombre = (nombre or "dragon").strip().lower()
    if nombre not in TEMAS:
        nombre = "dragon"
    definicion = TEMAS[nombre]
    Tema.nombre = nombre
    if definicion == "mono" or not _USAR_COLOR:
        for clave in ("titulo", "info", "ok", "aviso", "error", "tenue", "agente",
                      "herramienta", "texto", "prompt", "acento"):
            setattr(Tema, clave, "")
        if definicion == "mono" and _USAR_COLOR:
            Tema.titulo = C.BOLD
            Tema.error = C.BOLD
            Tema.tenue = C.DIM
        return nombre
    if definicion is None:
        Tema.titulo, Tema.info, Tema.ok = C.CYAN, C.CYAN, C.VERDE
        Tema.aviso, Tema.error, Tema.tenue = C.AMARILLO, C.ROJO, C.GRIS
        Tema.agente, Tema.herramienta, Tema.texto = C.MAGENTA, C.AZUL, C.BLANCO
        Tema.prompt, Tema.acento = C.VERDE, C.MAGENTA
        return nombre
    for clave, (r, g, b) in definicion.items():
        setattr(Tema, clave, rgb(r, g, b))
    return nombre


aplicar_tema(os.getenv("REAPER_TEMA", "dragon"))

SI = {"s", "si", "sí", "y", "yes", "dale", "ok", "1"}


def recortar(texto: str, limite: int) -> str:
    texto = texto or ""
    if len(texto) <= limite:
        return texto
    mitad = max(1, limite // 2)
    return texto[:mitad].rstrip() + "\n...[recortado]...\n" + texto[-mitad:].lstrip()


def degradado(texto: str, desde: tuple, hasta: tuple) -> str:
    """Pinta 'texto' con un degradado horizontal (si hay color)."""
    if not _USAR_COLOR or not texto:
        return texto
    visibles = [ch for ch in texto]
    n = max(1, len(visibles) - 1)
    partes = []
    for i, ch in enumerate(visibles):
        t = i / n
        r = int(desde[0] + (hasta[0] - desde[0]) * t)
        g = int(desde[1] + (hasta[1] - desde[1]) * t)
        b = int(desde[2] + (hasta[2] - desde[2]) * t)
        partes.append(rgb(r, g, b) + ch)
    return "".join(partes) + C.RESET


def formatear_duracion(segundos: float) -> str:
    segundos = max(0.0, float(segundos))
    if segundos < 1:
        return f"{int(segundos * 1000)}ms"
    if segundos < 60:
        return f"{segundos:.1f}s"
    minutos, seg = divmod(int(segundos), 60)
    if minutos < 60:
        return f"{minutos}m{seg:02d}s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas}h{minutos:02d}m"


def formatear_numero(n: Union[int, float]) -> str:
    n = float(n)
    for umbral, sufijo in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= umbral:
            return f"{n / umbral:.1f}{sufijo}"
    return str(int(n)) if n == int(n) else f"{n:.2f}"


# ======================================================================
# RESALTADO DE CÓDIGO (sin dependencias)
# ======================================================================
_PALABRAS = {
    "python": set(keyword.kwlist) | {"self", "cls", "print", "len", "range", "True", "False", "None"},
    "js": {
        "await", "async", "break", "case", "catch", "class", "const", "continue", "default",
        "delete", "do", "else", "export", "extends", "finally", "for", "from", "function", "if",
        "import", "in", "instanceof", "let", "new", "null", "of", "return", "static", "super",
        "switch", "this", "throw", "true", "false", "try", "typeof", "undefined", "var", "void",
        "while", "yield", "interface", "type", "enum", "implements", "readonly", "public", "private",
    },
    "sh": {
        "if", "then", "else", "elif", "fi", "for", "while", "do", "done", "case", "esac", "function",
        "in", "return", "local", "export", "echo", "cd", "exit", "set", "source", "read",
    },
    "go": {
        "break", "case", "chan", "const", "continue", "default", "defer", "else", "fallthrough",
        "for", "func", "go", "goto", "if", "import", "interface", "map", "package", "range",
        "return", "select", "struct", "switch", "type", "var", "nil", "true", "false",
    },
    "rust": {
        "as", "break", "const", "continue", "crate", "else", "enum", "extern", "false", "fn", "for",
        "if", "impl", "in", "let", "loop", "match", "mod", "move", "mut", "pub", "ref", "return",
        "self", "Self", "static", "struct", "super", "trait", "true", "type", "unsafe", "use",
        "where", "while", "async", "await", "dyn",
    },
}

_ALIAS_LENGUAJE = {
    "py": "python", "python3": "python", "javascript": "js", "mjs": "js", "cjs": "js",
    "ts": "js", "typescript": "js", "tsx": "js", "jsx": "js", "bash": "sh", "shell": "sh",
    "zsh": "sh", "golang": "go", "rs": "rust", "json": "json", "html": "html", "css": "css",
}

_COMENTARIO_LINEA = {"python": "#", "sh": "#", "js": "//", "go": "//", "rust": "//", "css": None}


def lenguaje_de(nombre_o_ext: str) -> str:
    valor = (nombre_o_ext or "").strip().lower().lstrip(".")
    if "/" in valor or "." in valor:
        valor = valor.rsplit(".", 1)[-1]
    return _ALIAS_LENGUAJE.get(valor, valor)


def resaltar_codigo(codigo: str, lenguaje: str = "") -> str:
    """Resaltado simple por tokens: palabras clave, strings, comentarios y números."""
    if not _USAR_COLOR or not codigo:
        return codigo
    lang = lenguaje_de(lenguaje)
    c_kw, c_str, c_com, c_num, c_fn = (
        rgb(200, 120, 255), rgb(150, 220, 120), rgb(120, 120, 140), rgb(255, 170, 80), rgb(110, 180, 255)
    )
    if lang == "json":
        patron = re.compile(r'("(?:\\.|[^"\\])*")(\s*:)?|(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|\b(true|false|null)\b')

        def json_tok(m: re.Match) -> str:
            if m.group(1):
                color = c_fn if m.group(2) else c_str
                return color + m.group(1) + C.RESET + (m.group(2) or "")
            if m.group(3):
                return c_num + m.group(3) + C.RESET
            return c_kw + m.group(4) + C.RESET
        return patron.sub(json_tok, codigo)
    if lang in ("html", "xml"):
        codigo = re.sub(r"(<!--.*?-->)", lambda m: c_com + m.group(1) + C.RESET, codigo, flags=re.S)
        codigo = re.sub(r"(</?)([\w-]+)", lambda m: m.group(1) + c_kw + m.group(2) + C.RESET, codigo)
        return re.sub(r'(\s[\w-]+)(=)("[^"]*"|\'[^\']*\')',
                      lambda m: c_fn + m.group(1) + C.RESET + m.group(2) + c_str + m.group(3) + C.RESET, codigo)
    if lang == "css":
        codigo = re.sub(r"(/\*.*?\*/)", lambda m: c_com + m.group(1) + C.RESET, codigo, flags=re.S)
        return re.sub(r"([\w-]+)(\s*:)(?!:)", lambda m: c_fn + m.group(1) + C.RESET + m.group(2), codigo)

    palabras = _PALABRAS.get(lang, _PALABRAS["python"] if not lang else set())
    comentario = _COMENTARIO_LINEA.get(lang, "#")
    partes = [r'(?P<str>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`)']
    if comentario:
        partes.append(r"(?P<com>" + re.escape(comentario) + r"[^\n]*)")
    if lang in ("js", "go", "rust", "css"):
        partes.append(r"(?P<bloque>/\*[\s\S]*?\*/)")
    partes.append(r"(?P<num>\b\d+(?:\.\d+)?\b)")
    partes.append(r"(?P<pal>\b[A-Za-z_][\w]*\b)(?P<par>\s*\()?")
    patron = re.compile("|".join(partes))

    def tok(m: re.Match) -> str:
        tipo = m.lastgroup
        if m.group("str") is not None:
            return c_str + m.group("str") + C.RESET
        if comentario and m.groupdict().get("com") is not None:
            return c_com + m.group("com") + C.RESET
        if m.groupdict().get("bloque") is not None:
            return c_com + m.group("bloque") + C.RESET
        if m.group("num") is not None:
            return c_num + m.group("num") + C.RESET
        palabra = m.group("pal")
        if palabra is not None:
            sufijo = m.group("par") or ""
            if palabra in palabras:
                return c_kw + palabra + C.RESET + sufijo
            if sufijo:
                return c_fn + palabra + C.RESET + sufijo
            return palabra
        return m.group(0) if tipo else m.group(0)

    return patron.sub(tok, codigo)


# ======================================================================
# CAJAS Y TABLAS
# ======================================================================
_BORDES = {
    "redondo": ("╭", "╮", "╰", "╯", "─", "│"),
    "doble": ("╔", "╗", "╚", "╝", "═", "║"),
    "simple": ("┌", "┐", "└", "┘", "─", "│"),
    "grueso": ("┏", "┓", "┗", "┛", "━", "┃"),
    "ascii": ("+", "+", "+", "+", "-", "|"),
}


def caja(lineas: Sequence[str], titulo: str = "", color: str = "", estilo: str = "redondo",
         ancho: Optional[int] = None, relleno: int = 1) -> str:
    """Devuelve una caja dibujada con bordes alrededor de las líneas."""
    tl, tr, bl, br, h, v = _BORDES.get(estilo, _BORDES["redondo"])
    lineas = [l for bloque in lineas for l in str(bloque).split("\n")]
    interior = max([ancho_visible(l) for l in lineas] + [ancho_visible(titulo) + 2, 10])
    maximo = ancho_terminal() - 2 - 2 * relleno
    if ancho:
        interior = max(10, min(ancho - 2 - 2 * relleno, maximo))
    else:
        interior = min(interior, maximo)
    reset = C.RESET if color else ""
    pad = " " * relleno
    if titulo:
        t = f" {titulo} "
        resto = interior + 2 * relleno - ancho_visible(t) - 1
        arriba = f"{color}{tl}{h}{reset}{C.BOLD}{t}{C.RESET}{color}{h * max(0, resto)}{tr}{reset}"
    else:
        arriba = f"{color}{tl}{h * (interior + 2 * relleno)}{tr}{reset}"
    cuerpo = [f"{color}{v}{reset}{pad}{ajustar(l, interior)}{pad}{color}{v}{reset}" for l in lineas]
    abajo = f"{color}{bl}{h * (interior + 2 * relleno)}{br}{reset}"
    return "\n".join([arriba] + cuerpo + [abajo])


def tabla(filas: Sequence[Sequence[Any]], encabezados: Optional[Sequence[str]] = None,
          alinear: str = "", color_encabezado: str = "") -> str:
    """Tabla de texto simple. alinear: cadena con 'l'/'r'/'c' por columna."""
    datos = [[str(c) for c in fila] for fila in filas]
    if encabezados:
        datos = [[str(e) for e in encabezados]] + datos
    if not datos:
        return ""
    columnas = max(len(f) for f in datos)
    for fila in datos:
        fila.extend([""] * (columnas - len(fila)))
    anchos = [max(ancho_visible(f[i]) for f in datos) for i in range(columnas)]
    disponible = ancho_terminal() - 3 * (columnas - 1) - 2
    while sum(anchos) > disponible and max(anchos) > 8:
        mayor = anchos.index(max(anchos))
        anchos[mayor] -= 1

    def celda(texto: str, i: int) -> str:
        modo = alinear[i] if i < len(alinear) else "l"
        if ancho_visible(texto) > anchos[i]:
            return ajustar(texto, anchos[i])
        falta = anchos[i] - ancho_visible(texto)
        if modo == "r":
            return " " * falta + texto
        if modo == "c":
            return " " * (falta // 2) + texto + " " * (falta - falta // 2)
        return texto + " " * falta

    salida = []
    for n, fila in enumerate(datos):
        linea = " │ ".join(celda(c, i) for i, c in enumerate(fila))
        if n == 0 and encabezados:
            salida.append(f"{color_encabezado}{C.BOLD}{linea}{C.RESET}")
            salida.append("─┼─".join("─" * a for a in anchos))
        else:
            salida.append(linea)
    return "\n".join(salida)


def barra(actual: float, total: float, ancho: int = 24, color: str = "") -> str:
    total = total or 1
    fraccion = max(0.0, min(1.0, actual / total))
    llenos = fraccion * ancho
    enteros = int(llenos)
    parciales = " ▏▎▍▌▋▊▉"
    resto = parciales[int((llenos - enteros) * 8)] if enteros < ancho else ""
    cuerpo = "█" * enteros + resto
    cuerpo += " " * (ancho - ancho_visible(cuerpo))
    reset = C.RESET if color else ""
    return f"{color}{cuerpo}{reset} {int(fraccion * 100):>3}%"


# ======================================================================
# MARKDOWN
# ======================================================================
def _markdown_en_linea(texto: str) -> str:
    if not _USAR_COLOR:
        return texto
    texto = re.sub(r"`([^`\n]+)`", lambda m: rgb(255, 170, 80) + m.group(1) + C.RESET + Tema.texto, texto)
    texto = re.sub(r"\*\*([^*\n]+)\*\*", lambda m: C.BOLD + m.group(1) + C.RESET + Tema.texto, texto)
    texto = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", lambda m: C.ITALICA + m.group(1) + C.RESET + Tema.texto, texto)
    return texto


def renderizar_markdown(texto: str) -> list[str]:
    """Convierte markdown simple en líneas con color para la terminal."""
    lineas: list[str] = []
    en_codigo = False
    lenguaje = ""
    buffer: list[str] = []
    ancho = min(ancho_terminal(), 100)
    for linea in (texto or "").splitlines():
        cerca = re.match(r"^\s*```\s*([\w+#.-]*)\s*$", linea)
        if cerca:
            if not en_codigo:
                en_codigo, lenguaje, buffer = True, cerca.group(1), []
            else:
                etiqueta = f" {lenguaje or 'código'} "
                lineas.append(f"{Tema.tenue}┌{etiqueta}{'─' * max(0, min(50, ancho - 4) - len(etiqueta))}{C.RESET}")
                for l in resaltar_codigo("\n".join(buffer), lenguaje).split("\n"):
                    lineas.append(f"{Tema.tenue}│{C.RESET} {l}")
                lineas.append(f"{Tema.tenue}└{'─' * min(50, ancho - 4)}{C.RESET}")
                en_codigo = False
            continue
        if en_codigo:
            buffer.append(linea)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", linea)
        if m:
            nivel = len(m.group(1))
            color = Tema.titulo if nivel <= 2 else Tema.info
            prefijo = "▌ " if nivel == 1 else ("▸ " if nivel == 2 else "· ")
            lineas.append(f"{color}{C.BOLD}{prefijo}{m.group(2)}{C.RESET}")
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", linea)
        if m:
            marca = "•" if m.group(2) in "-*+" else m.group(2)
            casilla = re.match(r"^\[( |x|X)\]\s+(.*)$", m.group(3))
            if casilla:
                marca = f"{Tema.ok}✔{C.RESET}" if casilla.group(1).lower() == "x" else f"{Tema.tenue}☐{C.RESET}"
                contenido = casilla.group(2)
            else:
                contenido = m.group(3)
            lineas.append(f"{m.group(1)}{Tema.acento}{marca}{C.RESET} {Tema.texto}{_markdown_en_linea(contenido)}{C.RESET}")
            continue
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", linea):
            lineas.append(f"{Tema.tenue}{'─' * min(60, ancho - 2)}{C.RESET}")
            continue
        if linea.startswith(">"):
            lineas.append(f"{Tema.tenue}┃{C.RESET} {C.ITALICA}{linea[1:].strip()}{C.RESET}")
            continue
        lineas.append(f"{Tema.texto}{_markdown_en_linea(linea)}{C.RESET}" if linea.strip() else "")
    if en_codigo and buffer:
        for l in resaltar_codigo("\n".join(buffer), lenguaje).split("\n"):
            lineas.append(f"{Tema.tenue}│{C.RESET} {l}")
    return lineas


# ======================================================================
# SPINNER
# ======================================================================
_SPINNERS = {
    "puntos": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏",
    "llama": "🔥🔥🔥🔥",
    "barra": "▁▂▃▄▅▆▇█▇▆▅▄▃▂",
    "ascii": "|/-\\",
}


class UI:
    """
    Toda la salida pasa por acá. En tests se usa UI(silencioso=True,
    respuestas=[...]) para no imprimir y contestar confirmaciones.
    """

    def __init__(
        self,
        *,
        silencioso: bool = False,
        interactivo: bool = True,
        respuestas: Optional[list] = None,
        entrada: Optional[Callable[[str], str]] = None,
        log: Optional[Path] = None,
        detalle: int = 1,
    ):
        self.silencioso = silencioso
        self.interactivo = interactivo
        self._respuestas = list(respuestas or [])
        self._entrada = entrada or input
        self._lock = threading.RLock()
        self._progreso_visible = False
        self._ultimo_progreso = 0.0
        self._inicio_progreso: Optional[float] = None
        self._frame = 0
        self.registro: list[str] = []
        self.log = log
        # 0 = mínimo (solo resultados), 1 = normal, 2 = detallado (razonamientos completos)
        self.detalle = detalle
        self.spinner = _SPINNERS["puntos"] if _USAR_COLOR else _SPINNERS["ascii"]

    # ------------------------------------------------------------ básico
    def _borrar_progreso(self) -> None:
        if self._progreso_visible:
            sys.stdout.write("\r\033[K" if _USAR_COLOR else "\r" + " " * 70 + "\r")
            sys.stdout.flush()
            self._progreso_visible = False

    def _a_log(self, texto: str) -> None:
        if not self.log:
            return
        try:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%H:%M:%S}] {sin_ansi(texto)}\n")
        except OSError:
            self.log = None

    def linea(self, texto: str = "") -> None:
        with self._lock:
            self._a_log(texto)
            if self.silencioso:
                self.registro.append(texto)
                return
            self._borrar_progreso()
            try:
                print(texto, flush=True)
            except UnicodeEncodeError:
                print(texto.encode("ascii", "replace").decode("ascii"), flush=True)

    def texto_registrado(self) -> str:
        """Todo lo impreso en modo silencioso, sin códigos de color (útil en tests)."""
        return sin_ansi("\n".join(self.registro))

    def info(self, texto: str) -> None:
        self.linea(f"{Tema.info}{texto}{C.RESET}")

    def ok(self, texto: str) -> None:
        self.linea(f"{Tema.ok}✓ {texto}{C.RESET}")

    def aviso(self, texto: str) -> None:
        self.linea(f"{Tema.aviso}{texto}{C.RESET}")

    def error(self, texto: str) -> None:
        self.linea(f"{Tema.error}✗ {texto}{C.RESET}")

    def tenue(self, texto: str) -> None:
        self.linea(f"{Tema.tenue}{texto}{C.RESET}")

    def titulo(self, texto: str) -> None:
        self.linea(f"\n{Tema.titulo}{C.BOLD}══ {texto} ══{C.RESET}")

    def fase(self, numero: Union[int, str], texto: str) -> None:
        ancho = min(ancho_terminal(), 72)
        etiqueta = f" FASE {numero} · {texto} "
        relleno = max(2, ancho - ancho_visible(etiqueta) - 4)
        self.linea("")
        self.linea(f"{Tema.titulo}{C.BOLD}━━{etiqueta}{'━' * relleno}{C.RESET}")

    def separador(self, caracter: str = "─") -> None:
        self.linea(f"{Tema.tenue}{caracter * min(ancho_terminal(), 72)}{C.RESET}")

    def caja(self, lineas: Sequence[str], titulo: str = "", color: str = "", estilo: str = "redondo") -> None:
        self.linea(caja(lineas, titulo, color or Tema.titulo, estilo))

    def tabla(self, filas: Sequence[Sequence[Any]], encabezados: Optional[Sequence[str]] = None,
              alinear: str = "") -> None:
        self.linea(tabla(filas, encabezados, alinear, Tema.titulo))

    def barra(self, etiqueta: str, actual: float, total: float) -> None:
        self.linea(f"  {etiqueta} {barra(actual, total, color=Tema.acento)}")

    def codigo(self, texto: str, lenguaje: str = "", numeros: bool = False, desde: int = 1) -> None:
        resaltado = resaltar_codigo(texto, lenguaje).split("\n")
        for i, l in enumerate(resaltado):
            if numeros:
                self.linea(f"{Tema.tenue}{desde + i:>5}│{C.RESET} {l}")
            else:
                self.linea(f"  {l}")

    def markdown(self, texto: str) -> None:
        for l in renderizar_markdown(texto):
            self.linea(l)

    # ------------------------------------------------------------ agentes
    def agente(self, etiqueta: str, texto: str) -> None:
        self.linea(f"{Tema.agente}{C.BOLD}[{etiqueta}]{C.RESET} {texto}")

    def pensamiento(self, etiqueta: str, texto: str, limite: int = 700) -> None:
        texto = (texto or "").strip()
        if not texto or self.detalle <= 0:
            return
        if self.detalle >= 2:
            limite = max(limite, 4000)
        self.linea(f"{Tema.agente}[{etiqueta}]{C.RESET} {Tema.texto}{recortar(texto, limite)}{C.RESET}")

    def herramienta(self, etiqueta: str, nombre: str, detalle: str = "") -> None:
        detalle = detalle.replace("\n", " ")
        maximo = max(30, ancho_terminal() - len(etiqueta) - len(nombre) - 12)
        if len(detalle) > maximo:
            detalle = detalle[:maximo - 3] + "..."
        self.linea(f"{Tema.tenue}  [{etiqueta}]{C.RESET} {Tema.herramienta}⚙ {nombre}{C.RESET} {Tema.tenue}{detalle}{C.RESET}")

    def resultado_herramienta(self, ok: bool, texto: str) -> None:
        primera = (texto or "").strip().splitlines()[0] if (texto or "").strip() else ""
        maximo = max(40, ancho_terminal() - 10)
        if len(primera) > maximo:
            primera = primera[:maximo - 3] + "..."
        color = Tema.ok if ok else Tema.error
        marca = "✓" if ok else "✗"
        self.linea(f"      {color}{marca}{C.RESET} {Tema.tenue}{primera}{C.RESET}")

    def diff(self, texto: str, max_lineas: int = 60) -> None:
        lineas = (texto or "").splitlines()
        for linea in lineas[:max_lineas]:
            if linea.startswith("+") and not linea.startswith("+++"):
                self.linea(f"      {Tema.ok}{linea}{C.RESET}")
            elif linea.startswith("-") and not linea.startswith("---"):
                self.linea(f"      {Tema.error}{linea}{C.RESET}")
            elif linea.startswith("@@"):
                self.linea(f"      {Tema.info}{linea}{C.RESET}")
            else:
                self.linea(f"      {Tema.tenue}{linea}{C.RESET}")
        if len(lineas) > max_lineas:
            self.tenue(f"      ... {len(lineas) - max_lineas} líneas más (/diff para ver todo)")

    def progreso(self, etiqueta: str, caracteres: int) -> None:
        if self.silencioso or not sys.stdout.isatty():
            return
        ahora = time.monotonic()
        if self._inicio_progreso is None:
            self._inicio_progreso = ahora
        if ahora - self._ultimo_progreso < 0.12:
            return
        self._ultimo_progreso = ahora
        self._frame = (self._frame + 1) % len(self.spinner)
        transcurrido = ahora - self._inicio_progreso
        velocidad = caracteres / transcurrido / CARACTERES_POR_TOKEN_UI if transcurrido > 0.5 else 0
        extra = f" · {velocidad:.0f} tok/s" if velocidad else ""
        with self._lock:
            sys.stdout.write(
                f"\r{Tema.acento}{self.spinner[self._frame]}{C.RESET} {Tema.tenue}[{etiqueta}] generando… "
                f"{caracteres} car · {formatear_duracion(transcurrido)}{extra}{C.RESET}\033[K"
            )
            sys.stdout.flush()
            self._progreso_visible = True

    def esperando(self, etiqueta: str, texto: str = "pensando") -> None:
        """Línea de estado antes de que llegue el primer token."""
        if self.silencioso or not sys.stdout.isatty():
            return
        with self._lock:
            sys.stdout.write(f"\r{Tema.acento}{self.spinner[0]}{C.RESET} {Tema.tenue}[{etiqueta}] {texto}…{C.RESET}\033[K")
            sys.stdout.flush()
            self._progreso_visible = True

    def fin_progreso(self) -> None:
        with self._lock:
            self._borrar_progreso()
            self._inicio_progreso = None

    # ------------------------------------------------------------ entrada
    def confirmar(self, pregunta: str, defecto: bool = False) -> bool:
        if self._respuestas:
            respuesta = self._respuestas.pop(0)
            return bool(respuesta) if not isinstance(respuesta, str) else respuesta.strip().lower() in SI
        if not self.interactivo:
            return defecto
        with self._lock:
            self._borrar_progreso()
            try:
                opciones = "S/n" if defecto else "s/N"
                texto = self._entrada(f"{Tema.aviso}{pregunta} ({opciones}) {C.RESET}")
            except EOFError:
                return defecto
        texto = texto.strip().lower()
        if not texto:
            return defecto
        return texto in SI

    def preguntar(self, pregunta: str) -> str:
        if self._respuestas:
            return str(self._respuestas.pop(0))
        if not self.interactivo:
            return ""
        with self._lock:
            self._borrar_progreso()
            try:
                return self._entrada(f"{Tema.aviso}{pregunta}{C.RESET}\n{Tema.prompt}› {C.RESET}").strip()
            except EOFError:
                return ""

    def elegir(self, pregunta: str, opciones: Sequence[str], defecto: int = 0) -> int:
        """Menú numerado. Devuelve el índice elegido (o el defecto)."""
        if self._respuestas:
            valor = self._respuestas.pop(0)
            try:
                return max(0, min(len(opciones) - 1, int(valor)))
            except (TypeError, ValueError):
                return defecto
        if not self.interactivo:
            return defecto
        self.linea(f"{Tema.aviso}{pregunta}{C.RESET}")
        for i, op in enumerate(opciones, start=1):
            marca = f"{Tema.acento}›{C.RESET}" if i - 1 == defecto else " "
            self.linea(f"  {marca} {Tema.titulo}{i}{C.RESET}. {op}")
        respuesta = self.preguntar(f"Número (Enter = {defecto + 1})")
        if respuesta.isdigit() and 1 <= int(respuesta) <= len(opciones):
            return int(respuesta) - 1
        return defecto


CARACTERES_POR_TOKEN_UI = 3.0


def mostrar_markdown(ui: UI, texto: str) -> None:
    ui.markdown(texto)
