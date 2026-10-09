"""
Spec Core + Bug Classifier (v9, Fase 3): la ESPECIFICACIÓN manda sobre los tests.

Ataca los fallos de v8 (MASTER SPEC §1.5-§1.6):
  §1.6  un test exige un efecto que el usuario NUNCA pidió (crear denuncia.txt) → requisito_inventado
  §1.5  "el test falla ⇒ el código está mal": no siempre. Puede ser TEST_BUG, PATH_BUG,
        DEPENDENCY_BUG, FIXTURE_BUG, INPUT_MODEL_BUG, FLAKY_TEST o SPEC_GAP → clasificar_bug
  §..   confundir lo OBSERVADO (un <resultado> real) con lo INTERPRETADO (la conclusión del
        modelo) al diagnosticar → separar_observacion

Orden de autoridad: usuario > spec/plan > interfaz/contrato > criterios > docs > tests > suposiciones.
Un test NO es la fuente de la verdad: CODIFICA la spec, no la inventa.
"""

# Orden de autoridad (ante un conflicto, gana el de más arriba) — MASTER SPEC §1.5.
ORDEN_AUTORIDAD = (
    ("usuario", "lo que el usuario pidió explícitamente"),
    ("spec", "la especificación o el plan aprobado (<plan>, objetivo)"),
    ("contrato", "la interfaz/firmas públicas acordadas"),
    ("criterios", "los criterios de aceptación comprobables"),
    ("docs", "la documentación del proyecto (README, docstrings)"),
    ("tests", "los tests existentes"),
    ("suposiciones", "las suposiciones del modelo"),
)

# Categorías de un test en rojo (por qué falla) — MASTER SPEC §1.5.
TIPOS_BUG = ("IMPLEMENTATION_BUG", "TEST_BUG", "SPEC_GAP", "PATH_BUG", "INPUT_MODEL_BUG",
             "FIXTURE_BUG", "DEPENDENCY_BUG", "FLAKY_TEST", "DESCONOCIDO")

# Módulos de la librería estándar (si falta uno de estos NO es DEPENDENCY_BUG: es otra cosa).
_SP_STDLIB = frozenset((
    "os", "sys", "re", "io", "json", "math", "time", "random", "typing", "pathlib", "collections",
    "itertools", "functools", "datetime", "unittest", "subprocess", "shutil", "tempfile", "argparse",
    "logging", "threading", "asyncio", "socket", "sqlite3", "csv", "hashlib", "base64", "struct",
    "textwrap", "string", "copy", "enum", "dataclasses", "abc", "contextlib", "traceback", "glob",
    "inspect", "ast", "decimal", "fractions", "statistics", "unicodedata", "urllib", "http", "email",
    "html", "xml", "pickle", "gzip", "zipfile", "tarfile", "configparser", "platform", "signal",
    "queue", "heapq", "bisect", "operator", "warnings", "weakref", "types", "numbers", "array",
    "secrets", "uuid", "difflib", "pprint", "shlex", "getpass", "selectors", "concurrent",
))


def nota_autoridad() -> str:
    """Nota para el prompt: el orden de autoridad y que los tests no inventan requisitos."""
    cuerpo = " > ".join(n for n, _ in ORDEN_AUTORIDAD)
    return ("ORDEN DE AUTORIDAD (ante un conflicto, gana el de más arriba):\n  " + cuerpo + "\n"
            "Un test NO define el requisito: lo codifica. Si un test EXIGE algo que el usuario/la spec no "
            "pidieron (un archivo, una ruta, un mensaje exacto), el equivocado es el test (requisito "
            "inventado), no el código. Ante un test en rojo, primero decidí QUÉ está mal (código, test, "
            "spec, ruta, dependencia, fixture, entrada o flaky), no asumas que siempre es el código.")


# ============================================================================ requisitos inventados (§1.6)
@dataclass
class RequisitoInventado:
    test: str
    linea: int
    tipo: str            # ARCHIVO_NO_PEDIDO | RUTA_ABSOLUTA
    artefacto: str
    detalle: str


# Funciones cuyo primer argumento literal es un artefacto que el test EXIGE que exista/ya esté producido.
_SP_EXIGEN_EXISTENCIA = {
    "exists", "isfile", "isdir", "is_file", "is_dir", "lexists", "getsize",
}
# Funciones/métodos que CREAN el artefacto (si el propio test lo crea, no es un requisito al código).
_SP_CREAN = {
    "mkdir", "makedirs", "touch", "write_text", "write_bytes", "mkstemp", "mkdtemp",
    "NamedTemporaryFile", "TemporaryFile", "TemporaryDirectory", "symlink", "link",
}
_SP_MODOS_ESCRITURA = ("w", "a", "x", "+")


def _sp_norm(texto: str) -> str:
    """Normaliza para comparar (minúsculas, sin tildes si está disponible sin_tildes)."""
    try:
        base = sin_tildes(texto or "")
    except NameError:
        base = texto or ""
    return base.lower()


def _sp_literal(nodo) -> Optional[str]:
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    return None


def _sp_nombre_llamada(nodo) -> str:
    """'exists', 'write_text', 'open'... el atributo o nombre final de una llamada."""
    f = nodo.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _sp_literal_receptor(nodo_call) -> Optional[str]:
    """Literal del receptor en 'Path("x").metodo()' / 'open("x").metodo()': el string está en la llamada base."""
    f = nodo_call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Call) and f.value.args:
        return _sp_literal(f.value.args[0])
    return None


def _sp_es_ruta_de_sistema(valor: str) -> bool:
    v = valor.strip()
    if not v:
        return False
    if re.match(r"^[A-Za-z]:[\\/]", v):          # C:\... o C:/...
        return True
    if v.startswith("/") and not re.match(r"^/(tmp|var/folders|private)\b", v):
        return len(v) > 1
    if v.startswith("~"):
        return True
    return False


def requisito_inventado(fuente: str, pedido: str, criterios: str = "") -> list:
    """
    Tests que EXIGEN un artefacto (archivo/ruta) que ni el usuario ni los criterios pidieron, y que el
    propio test tampoco crea. Es el fallo §1.6: el test obliga a producir 'denuncia.txt' por su cuenta.
    Análisis estático; devuelve [] ante SyntaxError o si no hay nada que objetar.
    """
    try:
        arbol = ast.parse(fuente or "")
    except (SyntaxError, ValueError):
        return []
    blob = _sp_norm((pedido or "") + "\n" + (criterios or ""))
    def _base(lit: str) -> str:
        return os.path.basename(lit.rstrip("/\\")) or lit

    def _modo_open(nodo_call) -> str:
        modo = _sp_literal(nodo_call.args[1]) if len(nodo_call.args) >= 2 else ""
        for kw in nodo_call.keywords:
            if kw.arg == "mode":
                modo = _sp_literal(kw.value) or modo
        return modo

    # artefactos que el propio archivo de test crea: no son requisitos al código
    creados: set = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        nombre = _sp_nombre_llamada(nodo)
        if nombre in _SP_CREAN:
            for lit in list(filter(None, [_sp_literal(a) for a in nodo.args] + [_sp_literal_receptor(nodo)])):
                creados.add(_base(lit))
        elif nombre == "open":
            modo = _modo_open(nodo)
            if modo and any(m in modo for m in _SP_MODOS_ESCRITURA):
                lit = _sp_literal(nodo.args[0]) if nodo.args else _sp_literal_receptor(nodo)
                if lit:
                    creados.add(_base(lit))

    def _demandas(nodo_call) -> list:
        nombre = _sp_nombre_llamada(nodo_call)
        salida = []
        if nombre in _SP_EXIGEN_EXISTENCIA or nombre in ("read_text", "read_bytes"):
            salida += [lit for lit in [_sp_literal(a) for a in nodo_call.args] + [_sp_literal_receptor(nodo_call)]
                       if lit]
        elif nombre == "open":
            modo = _modo_open(nodo_call) or "r"
            if not any(m in modo for m in _SP_MODOS_ESCRITURA):
                lit = _sp_literal(nodo_call.args[0]) if nodo_call.args else _sp_literal_receptor(nodo_call)
                if lit:
                    salida.append(lit)
        return salida

    problemas: list = []
    for fn in ast.walk(arbol):
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("test"):
            continue
        for nodo in ast.walk(fn):
            if not isinstance(nodo, ast.Call):
                continue
            for lit in _demandas(nodo):
                base = os.path.basename(lit.rstrip("/\\")) or lit
                if _sp_es_ruta_de_sistema(lit):
                    problemas.append(RequisitoInventado(
                        fn.name, getattr(nodo, "lineno", fn.lineno), "RUTA_ABSOLUTA", lit,
                        f"el test depende de la ruta absoluta '{lit}' del sistema; usá tempfile, no una ruta fija."))
                    continue
                if base in creados:
                    continue
                if _sp_norm(base) in blob or (len(base) > 3 and _sp_norm(os.path.splitext(base)[0]) in blob):
                    continue
                problemas.append(RequisitoInventado(
                    fn.name, getattr(nodo, "lineno", fn.lineno), "ARCHIVO_NO_PEDIDO", base,
                    f"el test exige que exista '{base}', pero ni el usuario ni los criterios lo pidieron y el "
                    f"test no lo crea. Es un requisito inventado: ajustá el test a la spec, no el código a él."))
    # dedup por (test, artefacto, tipo)
    vistos, unicos = set(), []
    for p in problemas:
        clave = (p.test, p.artefacto, p.tipo)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(p)
    return unicos


def requisitos_inventados_para_prompt(fuente: str, pedido: str, criterios: str = "", maximo: int = 6) -> str:
    problemas = requisito_inventado(fuente, pedido, criterios)
    if not problemas:
        return ""
    lineas = [f"- {p.test} (línea {p.linea}) [{p.tipo}]: {p.detalle}" for p in problemas[:maximo]]
    return ("REQUISITOS INVENTADOS (un test no puede exigir lo que la spec no pide):\n" + "\n".join(lineas))


# ============================================================================ clasificador de bugs (§1.5)
@dataclass
class Clasificacion:
    tipo: str
    confianza: float
    senales: list
    recomendacion: str

    def como_linea(self) -> str:
        return f"{self.tipo} (confianza {self.confianza:.0%}): {self.recomendacion}"


_SP_RECOMENDACION = {
    "DEPENDENCY_BUG": "falta instalar una dependencia de terceros; no la reimplementes a mano: instalala o evitala.",
    "PATH_BUG": "es un problema de ruta/import del propio proyecto (módulo o archivo donde no está). "
                "No cambies la lógica: corregí la ruta, el nombre del módulo o el directorio de trabajo.",
    "IMPLEMENTATION_BUG": "el código produce un resultado o estado incorrecto. Arreglá el código (causa raíz), "
                          "no el test.",
    "TEST_BUG": "el test está mal (valor esperado equivocado, tautología o exige algo que la spec no pide). "
                "Corregí el test contra la spec; NO toques el código para contentar a un test erróneo.",
    "INPUT_MODEL_BUG": "la firma/forma de la entrada no coincide entre el test y la implementación. Alineá la "
                       "interfaz con el contrato acordado antes de tocar la lógica.",
    "FIXTURE_BUG": "falla el armado del test (fixture/setUp), no la lógica bajo prueba. Arreglá el fixture.",
    "FLAKY_TEST": "el test depende de tiempo, azar, red, puertos u orden: es inestable. Hacelo determinista "
                  "(sembrá el azar, mockeá el reloj/red, aislá el estado); no cambies la lógica a ciegas.",
    "SPEC_GAP": "la spec no dice qué se espera acá: el conflicto es de requisitos, no de código. Pedí la "
                "aclaración o decidí según el orden de autoridad, no inventes el comportamiento en el test.",
    "DESCONOCIDO": "no hay una señal clara; recogé más evidencia (el traceback completo) antes de cambiar nada.",
}

_SP_RE_FLAKY = re.compile(
    r"address already in use|connection (?:refused|reset|aborted)|timed?\s*out|\btimeout\b|resource temporarily"
    r"|broken pipe|\bflaky\b|intermittent|randomly|non-?deterministic|\bport\b.*\bin use\b", re.I)
_SP_RE_TIEMPO_AZAR = re.compile(r"\b(datetime\.now|time\.time|random\.|randint|uuid4|monotonic)\b", re.I)


def _sp_modulo_de(error: str) -> str:
    m = re.search(r"No module named ['\"]([\w\.]+)['\"]", error or "")
    return m.group(1).split(".")[0] if m else ""


def clasificar_bug(error: str, *, archivo_test: str = "", codigo_cambiado: bool = True,
                   test_cambiado: bool = False, modulos_proyecto: Iterable[str] = (),
                   requisito_inventado_detectado: bool = False, traceback_txt: str = "") -> Clasificacion:
    """
    Clasifica POR QUÉ falla un test a partir del mensaje de error + contexto. Heurístico y determinista:
    no decide el arreglo, decide dónde mirar (MASTER SPEC §1.5: el test rojo no implica código malo).
    """
    texto = (error or "") + "\n" + (traceback_txt or "")
    proyecto = {m.lower() for m in modulos_proyecto}
    senales: list = []

    def resultado(tipo, confianza, senal):
        senales.append(senal)
        return Clasificacion(tipo, confianza, senales, _SP_RECOMENDACION.get(tipo, _SP_RECOMENDACION["DESCONOCIDO"]))

    # 1) el test exige algo que la spec no pide → el test está mal (puede ser SPEC_GAP si el usuario lo quería)
    if requisito_inventado_detectado:
        return resultado("TEST_BUG", 0.8, "el test exige un artefacto que la spec no pide (requisito inventado)")

    # 2) módulo ausente: dependencia de terceros vs. ruta del propio proyecto
    modulo = _sp_modulo_de(texto)
    if modulo:
        if modulo.lower() in proyecto:
            return resultado("PATH_BUG", 0.85, f"no encuentra el módulo propio '{modulo}' (ruta/paquete mal armado)")
        if modulo.lower() in _SP_STDLIB:
            return resultado("PATH_BUG", 0.6, f"falta un módulo de la stdlib ('{modulo}'): revisá el nombre/entorno")
        return resultado("DEPENDENCY_BUG", 0.85, f"falta la dependencia de terceros '{modulo}'")

    # 3) flaky: red/puertos/tiempo/azar
    if _SP_RE_FLAKY.search(texto):
        return resultado("FLAKY_TEST", 0.8, "error típico de recurso externo/tiempo (red, puerto, timeout)")

    # 4) fixture / setUp
    if re.search(r"fixture ['\"][\w\-]+['\"] not found", texto, re.I):
        return resultado("FIXTURE_BUG", 0.85, "pytest no encuentra un fixture declarado")
    if re.search(r"\bin (?:setUp|setUpClass|setUpModule|tearDown)\b", texto):
        return resultado("FIXTURE_BUG", 0.7, "el error ocurre en el armado/desarme del test, no en la lógica")

    # 5) ruta/archivo ausente
    if re.search(r"FileNotFoundError|No such file or directory", texto, re.I):
        return resultado("PATH_BUG", 0.65, "FileNotFoundError: ruta o directorio de trabajo equivocado, o fixture")

    # 6) firma/forma de la entrada
    if re.search(r"TypeError.*(?:argument|positional|keyword)|missing \d+ required|takes \d+ .*but \d+", texto, re.I):
        return resultado("INPUT_MODEL_BUG", 0.7, "TypeError de argumentos: la firma no coincide con la llamada del test")

    # 7) símbolo inexistente (import name / attribute): implementación incompleta, salvo que el test se tocó solo
    if re.search(r"ImportError: cannot import name|AttributeError:.*has no attribute|NameError: name", texto, re.I):
        if test_cambiado and not codigo_cambiado:
            return resultado("TEST_BUG", 0.55, "el símbolo no existe y lo último que cambió fue el test (quizá un typo)")
        return resultado("IMPLEMENTATION_BUG", 0.65, "falta un símbolo que el contrato promete: implementación incompleta")

    # 8) no implementado
    if re.search(r"NotImplementedError", texto):
        return resultado("IMPLEMENTATION_BUG", 0.8, "NotImplementedError: la implementación está pendiente")

    # 9) assert: valor equivocado. Código vs test según qué se tocó último
    if re.search(r"AssertionError|assert ", texto):
        if test_cambiado and not codigo_cambiado:
            return resultado("TEST_BUG", 0.55, "falla un assert y lo último que cambió fue el test: revisá el esperado")
        return resultado("IMPLEMENTATION_BUG", 0.6, "falla un assert: el código produjo un valor distinto del esperado")

    if _SP_RE_TIEMPO_AZAR.search(texto):
        return resultado("FLAKY_TEST", 0.5, "el test usa tiempo/azar sin fijarlos: posible inestabilidad")

    return resultado("DESCONOCIDO", 0.3, "sin una señal clara en el mensaje de error")


def clasificacion_para_prompt(error: str, **kwargs) -> str:
    c = clasificar_bug(error, **kwargs)
    senales = "; ".join(c.senales[-3:])
    return (f"CLASIFICACIÓN PRELIMINAR DEL FALLO: {c.tipo} (confianza {c.confianza:.0%}).\n"
            f"  Señales: {senales}.\n  {c.recomendacion}\n"
            "  (Es una hipótesis heurística; confirmala con la evidencia antes de arreglar.)")


# ============================================================================ observación vs interpretación
_SP_RE_INTERPRETACION = re.compile(
    r"\b(creo|pienso|supongo|me parece|parece|probablemente|quiz[áa]s?|tal vez|seguramente|deduzco|"
    r"la causa (?:es|ser[íi]a|debe)|el (?:bug|problema|error) est[áa]|por lo tanto|entonces|esto (?:significa|"
    r"implica|quiere decir)|deber[íi]a(?:mos)?|habr[íi]a que|conviene|sospecho|intuyo|asumo|"
    r"i think|i believe|probably|maybe|likely|the (?:cause|bug|problem) is|therefore|this means|should be)\b",
    re.I)
_SP_RE_OBSERVACION = re.compile(
    r"(exit\s*code|exit_code|return code|\bok\b|\bfail(?:ed|ure)?\b|\berror\b|traceback|assert\w*error|"
    r"\bpass(?:ed|aron|a)?\b|\bfall[óa]\w*\b|\d+\s*/\s*\d+|\d+\s+(?:passed|failed|errors?|tests?)|"
    r"stdout|stderr|<resultado|raised|no module named|expected .*but|!=|==)", re.I)


def es_interpretacion(linea: str) -> bool:
    l = (linea or "").strip()
    if not l:
        return False
    return bool(_SP_RE_INTERPRETACION.search(l)) and not _SP_RE_OBSERVACION.search(l)


def es_observacion(linea: str) -> bool:
    l = (linea or "").strip()
    if not l:
        return False
    return bool(_SP_RE_OBSERVACION.search(l)) and not _SP_RE_INTERPRETACION.search(l)


def separar_observacion(texto: str) -> tuple:
    """Separa un diagnóstico en (observaciones, interpretaciones). Una línea que es ambas o ninguna queda fuera."""
    observaciones, interpretaciones = [], []
    for linea in (texto or "").splitlines():
        l = linea.strip(" -•\t")
        if not l:
            continue
        if es_observacion(l):
            observaciones.append(l)
        elif es_interpretacion(l):
            interpretaciones.append(l)
    return observaciones, interpretaciones


def nota_observacion() -> str:
    return ("SEPARÁ OBSERVACIÓN DE INTERPRETACIÓN: una OBSERVACIÓN es lo que viste en un <resultado> real "
            "(salida, exit code, assert). Una INTERPRETACIÓN es tu conclusión sobre la causa. Escribí primero "
            "lo observado y recién después lo interpretado, y nunca presentes una interpretación como un hecho "
            "observado.")


def nota_spec() -> str:
    """Nota combinada (autoridad + observación) para el contexto del reparador/forense."""
    return nota_autoridad() + "\n" + nota_observacion()
