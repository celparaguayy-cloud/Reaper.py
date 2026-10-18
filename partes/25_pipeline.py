"""
Pipeline /construir v7: tests primero + torneo + escalada + lecciones.

    PEDIDO
      ↓
    Exploradores (en paralelo, solo lectura) → informe del código real
      ↓
    Arquitecto → plan con INTERFAZ (firmas exactas), tareas y criterios
      ↓
    confirmación del usuario (puede pedir cambios al plan)
      ↓
    Especificador (QA ANTES de implementar) → tests que todavía fallan:
      la especificación ejecutable. Quedan protegidos durante la build.
      ↓
    por cada tarea:
      ⚔ TORNEO: N implementadores en copias aisladas (temperaturas distintas)
         → se corren los tests en cada copia → gana el que pasa más tests
         → solo el cambio ganador se aplica al proyecto real
      → verificación de la tarea (validadores + que no se rompa nada que andaba)
      → si falla: reparador con el error real; si vuelve a fallar → ⇪ ESCALADA:
        un modelo más fuerte diagnostica y el reparador aplica
      → revisor (opcional) sobre el diff real
      ↓
    verificación final: validadores + suite completa
      ↓ ¿falló?
    Reparador (diagnóstico real) → re-verificar (con escalada si se repite)
      ↓
    Lecciones: cada reparación que funcionó deja una lección de una línea
      ↓
    BUILD VERIFICADA → snapshot en la rama git reaper/builds
"""

_RE_TAREA = re.compile(r"<\s*(tarea|task)\b([^>]*)>(.*?)<\s*/\s*\1\s*>", re.S | re.I)
_RE_ATTR = re.compile(r"(\w+)\s*=\s*[\"']([^\"']*)[\"']")
_RE_OBJETIVO = re.compile(r"<\s*objetivo\s*>(.*?)<\s*/\s*objetivo\s*>", re.S | re.I)
_RE_CRITERIOS = re.compile(r"<\s*criterios\s*>(.*?)<\s*/\s*criterios\s*>", re.S | re.I)
_RE_INTERFAZ = re.compile(r"<\s*interfaz\s*>(.*?)<\s*/\s*interfaz\s*>", re.S | re.I)
_RE_VEREDICTO = re.compile(r"VEREDICTO\s*:?\s*\**\s*(APROBADO|CAMBIOS|RECHAZADO)", re.I)

EXTENSIONES_TESTEABLES = (".py", ".js", ".mjs", ".cjs", ".ts")


def _es_testeable(archivos_plan: list, archivos_ws: list) -> bool:
    """¿Tiene sentido 'tests primero'? Sí si hay lógica (.py/.js/.ts) en el plan o en el proyecto, o si el proyecto
    está vacío y el plan TODAVÍA no nombra archivos (no sabemos qué construirá, así que no bajamos la guardia).
    NO para un plan que solo produce assets estáticos (.html/.css): escribir 'tests ejecutables' para una página
    estática no aporta y traba trabajos chicos ('construí una web') en modelos flojos. La validación igual corre."""
    if any(a.endswith(EXTENSIONES_TESTEABLES) for a in archivos_plan):
        return True
    if any(a.endswith(EXTENSIONES_TESTEABLES) for a in archivos_ws):
        return True
    return not archivos_plan and not archivos_ws


def _lineas_borradas(antes: str, ahora: str) -> tuple:
    """(borradas, total_previas) sobre líneas no vacías: cuántas líneas del contenido previo YA NO están.
    Agregar no cuenta; cambiar una línea cuenta como una borrada (la versión vieja desapareció)."""
    previas = [l for l in (antes or "").splitlines() if l.strip()]
    quedan = collections.Counter(l for l in (ahora or "").splitlines() if l.strip())
    borradas = 0
    for linea in previas:
        if quedan[linea] > 0:
            quedan[linea] -= 1
        else:
            borradas += 1
    return borradas, len(previas)


def resumen_preservacion(ws, cid_build: Optional[int]) -> str:
    """Determinista: qué pasó con el trabajo que YA EXISTÍA antes de esta actualización (evidencia para el juez)."""
    if cid_build is None:
        return "sin datos"
    modificados, borrados, reescritos = [], [], []
    for rel in ws.checkpoints.archivos_desde(cid_build):
        antes = ws.checkpoints.original(rel, cid_build)
        if antes is None:
            continue                                   # nació en esta actualización: no es trabajo previo
        ruta = ws.raiz / rel
        if not ruta.is_file():
            borrados.append(rel)
            continue
        ahora = ruta.read_text(encoding="utf-8", errors="replace")
        if ahora == antes:
            continue
        modificados.append(rel)
        borradas, total = _lineas_borradas(antes, ahora)
        if total and borradas >= 8 and borradas / total >= 0.6:
            reescritos.append(f"{rel} ({borradas}/{total} líneas previas borradas)")
    if not (modificados or borrados):
        return "no se tocó ningún archivo previo: solo se agregó trabajo nuevo"
    partes = [f"archivos previos modificados: {', '.join(modificados[:8]) or 'ninguno'}"]
    if borrados:
        partes.append(f"BORRADOS: {', '.join(borrados[:8])}")
    if reescritos:
        partes.append(f"REESCRITOS casi por completo: {'; '.join(reescritos[:5])}")
    return "; ".join(partes)


# Intención EXPLÍCITA de reemplazar un archivo (en el pedido o en la tarea). Solo palabras fuertes: "eliminar
# espacios" o "borrar duplicados" describen lógica, no reescribir el archivo.
_RE_REEMPLAZO = re.compile(r"\b(?:reemplaz\w*|reescrib\w*|rehac\w*|sustitu\w*|desde\s+cero|"
                           r"replac\w*|rewrit\w*|from\s+scratch)\b", re.IGNORECASE)
# Para que el PEDIDO autorice por sí solo una reescritura hace falta intención de archivo ENTERO: "reemplazá
# print por logging" es una edición chica y no habilita a borrar el 60 % de app.py.
_RE_REESCRITURA_PEDIDA = re.compile(r"\b(?:reescrib\w*|rehac\w*|desde\s+cero|de\s+cero|rewrit\w*|"
                                    r"from\s+scratch)\b", re.IGNORECASE)


def _primera_linea_util(diagnostico: str, limite: int = 200) -> str:
    """El motivo de un fallo en una línea, para pantalla y notas. Saltea el eco del comando ("$ ...", "exit code")
    para mostrar el error en sí. Antes la nota decía solo "quedó con fallos de verificación" y el motivo real
    (p. ej. REESCRITURA DESTRUCTIVA) no llegaba ni al usuario ni al informe."""
    for linea in (diagnostico or "").splitlines():
        texto = linea.strip()
        if not texto or texto.startswith(("$ ", "exit code", "STDOUT:", "STDERR:", "Hay fallos REALES")):
            continue
        return recortar(texto, limite)
    return "sin detalle"


# Tareas que PLANEAN simular (prueba real con OpenRouter: la tarea 1 decía "crear core.py con esqueletos que
# lanzan NotImplementedError y un __main__ que imprima TODO"). De ahí salían las entregas de mentira.
_RE_TAREA_SIMULADA = re.compile(
    r"esqueleto|skeleton|\bstubs?\b|placeholder|marcador(?:es)?\s+de\s+posici|NotImplementedError|"
    r"implement\w*\s+(?:m[aá]s\s+)?(?:tarde|despu[eé]s|later)|datos?\s+de\s+ejemplo|datos?\s+fictici",
    re.IGNORECASE)
# El marcador de programador va en MAYÚSCULAS y aparte: con IGNORECASE marcaba la palabra "todo" ("verificar que
# todo funciona"), un falso positivo que en la prueba real hizo replanificar sin motivo.
_RE_TODO = re.compile(r"\b(?:TODO|FIXME)\b")
# Viñetas o numeración al principio ("- ejecutar las pruebas", "2) Correr los tests"): el modelo real las usa.
_RE_VINETA = re.compile(r"^\s*(?:[-*•·]+|\d+[.)])\s*")
# Tareas que solo "corren las pruebas": no entregan archivos y REAPER ya verifica después de cada tarea.
_RE_META_TAREA = re.compile(
    r"^\s*(?:ejecut|corr[eé]|run\b|verific|valid|comprob|lanz)\w*\s+(?:que\s+)?"
    r"(?:(?:todas?|todos|el|la|los|las|the|all)\s+)*"
    r"(?:(?:conjunto|suite|bater[ií]a|set|juego)\s+(?:de\s+|of\s+)?)?"     # "Ejecutar el conjunto de pruebas"
    r"(?:(?:las?|los|the)\s+)?(?:pruebas|tests?|suite|unit\s*tests?)\b", re.IGNORECASE)


_RE_CONTEXTO_TEST = re.compile(r"\btests?\b|\btestead|prueba|unittest|pytest|fixture|node:test", re.I)


def problemas_del_plan(plan, pedido: str = "") -> list:
    """Determinista (0 tokens): tareas que planean simular o que no entregan nada. → mensajes para replanificar.
    "Datos de ejemplo" no cuenta si el PEDIDO los pide ("la base arranca con 3 recetas de ejemplo")."""
    salida = []
    pide_ejemplos = "ejemplo" in familias_pedidas(pedido)
    for tarea in getattr(plan, "tareas", []) or []:
        texto = tarea.descripcion or ""
        m = _RE_TAREA_SIMULADA.search(texto) or _RE_TODO.search(texto)
        if m and re.search(r"ejemplo|fictici", m.group(0), re.I) and (
                pide_ejemplos or _RE_CONTEXTO_TEST.search(texto[max(0, m.start() - 80):m.end() + 80])):
            # "testeadas con datos de ejemplo" es lo normal en un test (prueba real: hizo replanificar sin motivo).
            m = _RE_TODO.search(texto)
        if m:
            salida.append(f"la tarea {tarea.id} planea una simulación («{m.group(0)}»): tiene que implementar "
                          "el código real y completo, sin esqueletos ni placeholders")
        if _es_meta_tarea(texto):
            salida.append(f"la tarea {tarea.id} solo corre/verifica pruebas: REAPER ya lo hace después de cada "
                          "tarea; quitala o fusionala con una tarea que cree archivos")
    return salida


def _es_meta_tarea(descripcion: str) -> bool:
    primera = (descripcion or "").strip().splitlines()[0] if (descripcion or "").strip() else ""
    return bool(_RE_META_TAREA.search(_RE_VINETA.sub("", primera, count=1)))


def quitar_meta_tareas(plan) -> list:
    """Saca del plan las tareas que solo corren pruebas (y sus ids de las deps de las demás). → ids quitados."""
    quitadas = [t.id for t in plan.tareas if _es_meta_tarea(t.descripcion)]
    if quitadas and len(quitadas) < len(plan.tareas):
        plan.tareas = [t for t in plan.tareas if t.id not in quitadas]
        for t in plan.tareas:
            t.deps = [d for d in (t.deps or []) if d not in quitadas]
        return quitadas
    return []


def reemplazos_del_plan(ws, plan) -> dict:
    """Archivos que YA EXISTEN y que una tarea del plan dice que va a reemplazar → líneas que tienen hoy.

    Determinista, 0 tokens. Sirve para avisar ANTES de aprobar el plan (caso real: el plan decía "Reemplazar la
    funcionalidad actual" y se llevó puesto un app.py de 204 líneas que el pedido no mencionaba)."""
    salida: dict = {}
    for tarea in getattr(plan, "tareas", []) or []:
        if not _RE_REEMPLAZO.search(tarea.descripcion or ""):
            continue
        for rel in tarea.archivos:
            if not isinstance(rel, str) or rel in salida:
                continue
            try:
                if ws.existe(rel) and (ws.raiz / rel).is_file():
                    salida[rel] = sum(1 for l in ws.leer(rel).splitlines() if l.strip())
            except (OSError, ValueError, ErrorRuta):
                continue
    return salida


_RE_MAIN_SCRIPT = re.compile(r"""__name__\s*==\s*['"]__main__['"]""")
_RE_CLI_SCRIPT = re.compile(r"\b(argparse|ArgumentParser|click|typer|sys\.argv|fire\.Fire)\b")
# Solo cuentan fallas de CARGA: el código ni siquiera se pudo importar. Un ValueError por recibir '--help'
# como dato, un EOFError de un programa interactivo o un "opción no reconocida" NO son "proyecto roto".
_FIRMAS_NO_ARRANCA = ("ModuleNotFoundError", "ImportError", "No module named", "SyntaxError",
                      "IndentationError", "TabError")


def puntos_de_entrada(ws, limite: int = 3) -> list:
    """Cómo se arranca el proyecto: paquetes con __main__.py (python -m paquete, también en src/) y scripts de la
    raíz que son una CLI (if __name__ == '__main__' + argparse/click/sys.argv). [(etiqueta, cmd, cwd, env)]."""
    raiz = ws.raiz
    candidatos = []
    for base, env in ((raiz, None), (raiz / "src", {"PYTHONPATH": str(raiz / "src")})):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if (d.is_dir() and not d.name.startswith((".", "_")) and (d / "__init__.py").is_file()
                    and (d / "__main__.py").is_file()):
                candidatos.append((f"python -m {d.name}", [sys.executable, "-m", d.name, "--help"], raiz, env))
    for archivo in sorted(raiz.glob("*.py")):
        nombre = archivo.name
        if nombre.startswith("test_") or nombre.endswith("_test.py") or nombre in ("setup.py", "conftest.py"):
            continue
        try:
            texto = archivo.read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            continue
        if _RE_MAIN_SCRIPT.search(texto) and _RE_CLI_SCRIPT.search(texto):
            candidatos.append((f"python {nombre}", [sys.executable, nombre, "--help"], raiz, None))
    return candidatos[:limite]


def verificar_arranque(ws, timeout: int = 12) -> list:
    """¿El proyecto ARRANCA de verdad? Corre cada punto de entrada con --help (stdin vacío, plazo corto) y marca
    como roto solo una falla de CARGA (ModuleNotFoundError, SyntaxError, ...). Un timeout (servidor o programa
    interactivo) no cuenta. Caso real: los tests pasaban y `python -m paquete` ni siquiera importaba."""
    problemas = []
    for etiqueta, cmd, cwd, env in puntos_de_entrada(ws):
        r = ejecutar(cmd, cwd=cwd, timeout=timeout, entrada="", env_extra=env)
        if r.ok or r.timeout:
            continue
        salida = f"{r.stdout}\n{r.stderr}"
        if any(firma in salida for firma in _FIRMAS_NO_ARRANCA):
            problemas.append(f"ARRANQUE: `{etiqueta}` no arranca: falla al cargar el código (exit {r.codigo}). "
                             f"Los tests pueden pasar y la app igual estar rota.\n"
                             + fallos_relevantes(salida, maximo=2, limite=2500))
    return problemas


def _cuerpo_vacio(fn) -> Optional[str]:
    """'vacia' si el cuerpo es solo pass / ... (sin contar el docstring), 'no_implementada' si solo lanza
    NotImplementedError; None si hace algo de verdad."""
    cuerpo = list(fn.body)
    if (cuerpo and isinstance(cuerpo[0], ast.Expr) and isinstance(cuerpo[0].value, ast.Constant)
            and isinstance(cuerpo[0].value.value, str)):
        cuerpo = cuerpo[1:]
    if not cuerpo:
        return "vacia"
    if len(cuerpo) != 1:
        return None
    sentencia = cuerpo[0]
    if isinstance(sentencia, ast.Pass):
        return "vacia"
    if isinstance(sentencia, ast.Expr) and isinstance(sentencia.value, ast.Constant) \
            and sentencia.value.value is Ellipsis:
        return "vacia"
    if isinstance(sentencia, ast.Raise) and sentencia.exc is not None:
        objetivo = sentencia.exc.func if isinstance(sentencia.exc, ast.Call) else sentencia.exc
        if isinstance(objetivo, ast.Name) and objetivo.id == "NotImplementedError":
            return "no_implementada"
    return None


def stubs_en_codigo(fuente: str) -> list:
    """[(funcion, linea, 'vacia'|'no_implementada')]. No cuenta métodos abstractos, sobrecargas, Protocols ni
    métodos especiales (__init__, __exit__...), donde un cuerpo vacío suele ser lo correcto."""
    try:
        arbol = ast.parse(fuente)
    except SyntaxError:
        return []
    salida = []

    def nombre_de(nodo) -> str:
        return nodo.attr if isinstance(nodo, ast.Attribute) else getattr(nodo, "id", "")

    def clase_abstracta(clase) -> bool:
        return (any(nombre_de(b) in ("Protocol", "ABC") for b in clase.bases)
                or any(k.arg == "metaclass" for k in clase.keywords))

    def visitar(nodo, abstracta: bool = False) -> None:
        for hijo in ast.iter_child_nodes(nodo):
            if isinstance(hijo, ast.ClassDef):
                visitar(hijo, clase_abstracta(hijo))
            elif isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decoradores = {nombre_de(d.func if isinstance(d, ast.Call) else d) for d in hijo.decorator_list}
                especial = hijo.name.startswith("__") and hijo.name.endswith("__")
                if not (abstracta or especial or decoradores & {"abstractmethod", "overload", "abstractproperty"}):
                    tipo = _cuerpo_vacio(hijo)
                    if tipo:
                        salida.append((hijo.name, hijo.lineno, tipo))
                visitar(hijo, abstracta)
    visitar(arbol)
    return salida


# El modelo ADMITE que lo que escribió es provisional/ficticio. Frases muy específicas (no palabras sueltas) para
# no marcar código legítimo: un comentario que dice "en una implementación real llamaríamos a la API" o un string
# "número de ejemplo" es una simulación confesada. Caso real: get_free_number devolvía "+1555" + dígitos al azar.
# Lo que NO es confesión (falsos positivos reales, ver PRUEBAS §18.d): "No hardcodear la ruta", "Evitamos valores
# hardcodeados", "Simulación de la gravedad en cada frame", "In production you should set DEBUG to False", "En
# producción debería usarse HTTPS", "Por ahora usamos SQLite", "En producción habría que poner un proxy".
_COND_ES = (r"(?:ir|usar|conectar|llamar|consultar|traer|enviar|descargar|leer|recibir|pedir|integrar|"
            r"reemplazar|scrapear)[ií]a(?:mos|n)?|obtendr[ií]a(?:mos|n)?|har[ií]a(?:mos|n)?")
_RE_ADMITE_SIMULACION = re.compile(
    r"en\s+(?:una\s+|la\s+)?(?:implementaci[oó]n|versi[oó]n|app|aplicaci[oó]n)\s+real"
    r"|in\s+a\s+real\s+(?:implementation|app|application|world\s+app)"
    r"|in\s+production,?\s+(?:you|we|this|it|one)\s+would"
    r"|en\s+producci[oó]n,?\s+(?:se\s+|esto\s+se\s+)?(?:" + _COND_ES + r")"
    r"|por\s+ahora\s+(?:se\s+)?(?:devolv|retorn|simul|invent|fing)"
    r"|de\s+momento\s+(?:se\s+)?(?:devolv|retorn|simul|invent|fing)"
    r"|datos?\s+(?:de\s+ejemplo|simulad|fictici|inventad|dummy|falsos|de\s+prueba\s+fals)"
    r"|(?:respuesta|n[uú]mero|mensaje|c[oó]digo|resultado)s?\s+(?:simulad|fictici|inventad|falsos?\b|de\s+ejemplo"
    r"|hardcode|harcode)"
    r"|valor(?:es)?\s+(?:simulad|fictici|inventad)"
    r"|(?:fake|mock(?:ed)?|simulated)\s+(?:data|response|number|result|value)s?|dummy\s+(?:data|response)s?"
    r"|esto\s+es\s+(?:una\s+)?(?:simulaci[oó]n|un\s+mock|un\s+placeholder|provisional)"
    r"|simula(?:mos)?\s+(?:la\s+|el\s+|una\s+|un\s+)?(?:llamada|respuesta|api|petici[oó]n|request|env[ií]o|consulta"
    r"|descarga|conexi[oó]n|servidor|backend|base\s+de\s+datos|pago|sms|scrap)"
    r"|har[dt]?cod\w*\s+(?:por\s+ahora|temporalmente|de\s+momento|for\s+now|temporarily)"
    r"|placeholder\s+(?:value|data|response|implementation)|(?:mock|stub)\s+for\s+now"
    r"|reemplaz\w*\s+(?:esto\s+(?:por|con)|con\s+la\s+real|por\s+la\s+real|en\s+producci)"
    r"|pendiente\s+de\s+implementar|falta\s+implementar|sin\s+implementar\s+(?:a[uú]n|todav)"
    r"|not\s+implemented\s+yet|implement\s+(?:this|me)\s+later",
    re.IGNORECASE)
# Negación justo antes de la frase ("Evitamos valores hardcodeados", "sin datos simulados"): no es confesión.
_RE_NEGACION_CONFESION = re.compile(r"^(?:no|sin|nunca|ni|evit\w*|avoid\w*|never|not|without|don'?t|nada)$", re.IGNORECASE)
# Familias que el PEDIDO puede pedir a propósito: "3 recetas de ejemplo", "--simular (no mueve, solo muestra)".
_FAMILIAS_PERMITIBLES = {
    "ejemplo": (re.compile(r"ejemplo|example|sample|semilla|seed|demo", re.IGNORECASE),
                re.compile(r"ejemplo|example|sample", re.IGNORECASE)),
    "simulacion": (re.compile(r"simul|dry.?run|mock|fake|fictici|dummy", re.IGNORECASE),
                   re.compile(r"simul|mock|fake|fictici|dummy", re.IGNORECASE)),
}


def familias_pedidas(pedido: str) -> set:
    """Familias de 'confesión' que el PEDIDO del usuario pide a propósito (y sin negar: "no quiero datos simulados"
    NO habilita nada). Solo se mira el pedido, nunca el plan: el plan lo escribe el modelo."""
    salida = set()
    for familia, (en_pedido, _en_frase) in _FAMILIAS_PERMITIBLES.items():
        for m in en_pedido.finditer(pedido or ""):
            previas = re.findall(r"[\w']+", pedido[max(0, m.start() - 40):m.start()])[-4:]   # "sin datos de ejemplo"
            if not any(_RE_NEGACION_CONFESION.match(p) for p in previas):
                salida.add(familia)
                break
    return salida


def _confesiones_en_texto(texto: str, permitidas: set = frozenset()) -> list:
    """Frases de confesión en un comentario o string, descartando las negadas y las de familias permitidas."""
    salida = []
    for m in _RE_ADMITE_SIMULACION.finditer(texto):
        previas = re.findall(r"[\w']+", texto[max(0, m.start() - 30):m.start()])[-2:]
        if any(_RE_NEGACION_CONFESION.match(p) for p in previas):
            continue
        frase = m.group(0).strip()
        if any(_FAMILIAS_PERMITIBLES[f][1].search(frase) for f in permitidas if f in _FAMILIAS_PERMITIBLES):
            continue
        salida.append(frase)
    return salida


def admisiones_de_simulacion(fuente: str, permitidas: set = frozenset()) -> list:
    """[(linea, frase)] de comentarios o textos que CONFIESAN que el código es provisional/ficticio. Usa tokenize
    para ver comentarios y strings reales (0 tokens de modelo). Precisión alta: solo frases inequívocas.
    `permitidas`: familias que el pedido pidió a propósito (ver familias_pedidas)."""
    salida = []
    tipos = {tokenize.COMMENT, tokenize.STRING}
    if hasattr(tokenize, "FSTRING_MIDDLE"):                            # Python 3.12+: el texto de un f-string
        tipos.add(tokenize.FSTRING_MIDDLE)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(fuente).readline):
            if tok.type in tipos:
                for frase in _confesiones_en_texto(tok.string, permitidas)[:1]:
                    salida.append((tok.start[0], frase))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        pass
    return salida


# JS/TS/HTML: no hay tokenize, pero los comentarios se reconocen bien con regex (// y /* */ y <!-- -->). Un
# `//` dentro de un string (una URL) puede colarse como "comentario"; no importa: una URL no confiesa nada.
EXTENSIONES_WEB = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".html", ".htm", ".vue", ".svelte")
_RE_COMENTARIO_WEB = re.compile(r"/\*[\s\S]*?\*/|<!--[\s\S]*?-->|(?<![:\\])//[^\n]*")
_RE_JS_NO_IMPLEMENTADO = re.compile(
    r"throw\s+new\s+Error\(\s*['\"`]\s*(?:not\s+implemented|no\s+implementad|sin\s+implementar|todo\b)",
    re.IGNORECASE)


def admisiones_web(fuente: str, permitidas: set = frozenset()) -> list:
    """[(linea, frase)] de confesiones en comentarios de JS/TS/HTML y de `throw new Error("not implemented")`."""
    salida = []
    for m in _RE_COMENTARIO_WEB.finditer(fuente):
        for frase in _confesiones_en_texto(m.group(0), permitidas)[:1]:
            salida.append((fuente.count("\n", 0, m.start()) + 1, frase))
    for m in _RE_JS_NO_IMPLEMENTADO.finditer(fuente):
        salida.append((fuente.count("\n", 0, m.start()) + 1, m.group(0).strip()))
    return sorted(salida)


_RE_FUNCION_JS_VACIA = re.compile(
    r"function\s*\*?\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{\s*\}"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\s*)?\([^)]*\)\s*(?:=>\s*)?\{\s*\}"
    r"|^[ \t]*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{\s*\}", re.M)
_NO_SON_METODOS_JS = {"if", "for", "while", "switch", "catch", "function", "with", "return", "constructor"}


def stubs_js(fuente: str) -> list:
    """[(nombre, linea)] de funciones JS/TS con cuerpo vacío (o solo comentarios). Los comentarios se borran
    conservando los saltos de línea para que el número de línea siga siendo el real."""
    sin_comentarios = _RE_COMENTARIO_WEB.sub(lambda m: "\n" * m.group(0).count("\n"), fuente)
    salida = []
    for m in _RE_FUNCION_JS_VACIA.finditer(sin_comentarios):
        nombre = m.group(1) or m.group(2) or m.group(3)
        if nombre and nombre not in _NO_SON_METODOS_JS:
            salida.append((nombre, sin_comentarios.count("\n", 0, m.start()) + 1))
    return salida


_RE_TEST_JS_INICIO = re.compile(r"\b(?:test|it)\s*\(\s*(['\"`])(.+?)\1\s*,", re.S)
_RE_ALGUNA_VERIFICACION_JS = re.compile(r"assert|expect|should|verific|comprob|check|throws|rejects|fail\(", re.I)
_RE_ASSERT_JS = re.compile(r"\b(?:assert(?:\.\w+)?|expect)\s*\(")
_RE_ASSERT_TAUTOLOGICO = re.compile(
    r"^(?:assert(?:\.ok)?\(\s*(?:true|1|!0|!!1)\s*[,)]"
    r"|expect\(\s*(true|1|null|undefined|(['\"])\w*\2|\d+)\s*\)\.(?:toBe|toEqual|toStrictEqual)\(\s*\1\s*\)"
    r"|expect\(\s*true\s*\)\.toBeTruthy\(\s*\))")
_RE_ASSERT_IGUALES = re.compile(r"^assert\.(?:equal|strictEqual|deepEqual|deepStrictEqual)\(\s*([^,()]+?)\s*,\s*([^,()]+?)\s*[,)]")


def _cuerpo_js(texto: str, desde: int) -> str:
    """Texto del bloque { ... } que empieza en la primera llave desde `desde` (llaves balanceadas; los strings
    simples se saltean). '' si no cierra."""
    inicio = texto.find("{", desde)
    if inicio < 0:
        return ""
    nivel, i, comilla = 0, inicio, ""
    while i < len(texto):
        c = texto[i]
        if comilla:
            if c == "\\":
                i += 2
                continue
            if c == comilla:
                comilla = ""
        elif c in "'\"`":
            comilla = c
        elif c == "{":
            nivel += 1
        elif c == "}":
            nivel -= 1
            if nivel == 0:
                return texto[inicio + 1:i]
        i += 1
    return ""


def tests_js_sin_valor(fuente: str) -> list:
    """[(nombre, linea, detalle)] de tests de JS (node:test, jest, vitest, mocha) que no prueban nada: sin ninguna
    verificación, o con verificaciones que siempre pasan (assert.ok(true), assert.equal(1, 1),
    expect(true).toBe(true)). Conservador: si llama a algo que parezca verificar, no lo marca."""
    texto = _RE_COMENTARIO_WEB.sub(lambda m: "\n" * m.group(0).count("\n"), fuente)
    salida = []
    for m in _RE_TEST_JS_INICIO.finditer(texto):
        cuerpo = _cuerpo_js(texto, m.end())
        linea = texto.count("\n", 0, m.start()) + 1
        nombre = m.group(2).strip()[:60]
        if not cuerpo.strip() or not _RE_ALGUNA_VERIFICACION_JS.search(cuerpo):
            salida.append((nombre, linea, "el test no verifica nada (ni assert ni expect)"))
            continue
        asserts = [cuerpo[a.start():] for a in _RE_ASSERT_JS.finditer(cuerpo)]
        if asserts and all(_RE_ASSERT_TAUTOLOGICO.match(a) or ((g := _RE_ASSERT_IGUALES.match(a)) is not None
                                                                and g.group(1) == g.group(2)) for a in asserts):
            salida.append((nombre, linea, "todas sus verificaciones pasan siempre (comparan algo consigo mismo)"))
    return salida


_LLAMADAS_IO_REAL = ("httpx", "requests", "urllib", "urlopen", "socket", "aiohttp", "http", "subprocess", "popen",
            "run", "open", "connect", "fetch", "get", "post", "session", "curl", "sqlite3", "psycopg", "execute")
_RE_PIDE_DATOS_REALES = re.compile(
    r"scrap|descarg|download|\bfetch|consult|obten|recib|\bapi\b|\bhttp|web\b|solicit|"
    r"n[uú]mero|number|sms|mensaje|verificaci|\bsaldo\b|precio|cotiza",
    re.IGNORECASE)


def _usa_io_real(fn) -> bool:
    for nodo in ast.walk(fn):
        if isinstance(nodo, ast.Call):
            objetivo = nodo.func
            nombre = (objetivo.attr if isinstance(objetivo, ast.Attribute)
                      else getattr(objetivo, "id", "")).lower()
            if nombre in _LLAMADAS_IO_REAL:
                return True
    return False


def _fabrica_datos(fn) -> bool:
    """La función inventa su valor con random/uuid (no lo trae de ningún lado): señal de dato fabricado."""
    for nodo in ast.walk(fn):
        if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name) \
                and nodo.value.id in ("random", "uuid", "secrets", "faker"):
            return True
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) \
                and nodo.func.id in ("randint", "randrange", "choice", "uuid4", "getrandbits"):
            return True
    return False


def fabricaciones_en_codigo(fuente: str, deben_traer_datos: set) -> list:
    """[(funcion, linea)] de funciones que el plan pidió para TRAER datos reales (de la web, SMS, una API…) pero que
    los INVENTAN con random/uuid y no hacen ninguna llamada de IO. Es el patrón `+1555` + dígitos al azar."""
    try:
        arbol = ast.parse(fuente)
    except SyntaxError:
        return []
    salida = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name in deben_traer_datos:
            if _fabrica_datos(nodo) and not _usa_io_real(nodo):
                salida.append((nodo.name, nodo.lineno))
    return salida


def examen_de_realidad(ws, cid_build: Optional[int], plan=None, pedido: str = "") -> list:
    """
    Determinista (0 tokens): ¿lo entregado es REAL o una simulación? Revisa lo que cambió en esta build:
    - funciones que el plan pidió (def nombre en la interfaz o las tareas) y quedaron vacías (pass / ...), y
      cualquier `raise NotImplementedError` fuera de métodos abstractos: el código existe pero no hace nada;
    - tests creados o tocados en esta build que no prueban nada (tautologías, sin assert, mockean justo lo que
      deberían probar, esperan el valor que inyectó el propio mock): un verde que no demuestra nada;
    - comentarios/strings que CONFIESAN ser provisionales (también en JS/TS/HTML), salvo lo que el PEDIDO pidió a
      propósito ("3 recetas de ejemplo", "--simular").
    Devuelve hallazgos legibles; [] si lo revisado es real.
    """
    if cid_build is None:
        return []
    declaradas = set()
    deben_traer_datos = set()
    if plan is not None:
        texto = (getattr(plan, "interfaz", "") or "") + "\n" + "\n".join(t.descripcion for t in plan.tareas)
        declaradas = set(re.findall(r"\bdef\s+([A-Za-z_]\w*)", texto))
        declaradas |= set(re.findall(r"\bfunction\*?\s+([A-Za-z_$][\w$]*)", texto))   # interfaz de JS
        # Funciones cuyo CONTEXTO en el plan pide datos reales (traer de la web, SMS, una API, un número…):
        # si las fabrican con random en vez de traerlas, es simulación. Se mira la línea de cada `def` declarado.
        for linea in texto.splitlines():
            if _RE_PIDE_DATOS_REALES.search(linea):
                deben_traer_datos.update(re.findall(r"\bdef\s+([A-Za-z_]\w*)", linea))
        # Si el pedido entero habla de traer datos reales, cualquier función declarada cuenta (plan corto sin detalle).
        if _RE_PIDE_DATOS_REALES.search(texto) and not deben_traer_datos:
            deben_traer_datos = set(declaradas)
    permitidas = familias_pedidas(pedido)
    hallazgos = []
    for rel in ws.checkpoints.archivos_desde(cid_build):
        ruta = ws.raiz / rel
        es_web = rel.lower().endswith(EXTENSIONES_WEB)
        if not (rel.endswith(".py") or es_web) or not ruta.is_file():
            continue
        try:
            fuente = ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if es_web:
            if _es_test(rel):
                for nombre, linea, detalle in tests_js_sin_valor(fuente)[:3]:
                    hallazgos.append(f"TEST SIN VALOR en {rel}::{nombre} (línea {linea}): {detalle}")
            else:
                for nombre, linea in stubs_js(fuente):
                    if nombre in declaradas:
                        hallazgos.append(f"SIMULACIÓN en {rel}:{linea}: `{nombre}` quedó vacía ({{ }}): existe pero "
                                         "no hace nada.")
                for linea, frase in admisiones_web(fuente, permitidas):
                    hallazgos.append(f"SIMULACIÓN CONFESADA en {rel}:{linea}: «{recortar(frase, 80)}»: el código "
                                     "admite ser provisional/ficticio, no lo real que se pidió.")
            continue
        if _es_test(rel):
            graves = [p for p in analizar_tests_python(fuente).problemas if p.severidad == "alta"]
            for p in graves[:3]:
                hallazgos.append(f"TEST SIN VALOR en {rel}::{p.test} (línea {p.linea}): {p.detalle}")
            continue
        for nombre, linea, tipo in stubs_en_codigo(fuente):
            if tipo == "no_implementada" or nombre in declaradas:
                motivo = "lanza NotImplementedError" if tipo == "no_implementada" else "quedó vacía (pass/...)"
                hallazgos.append(f"SIMULACIÓN en {rel}:{linea}: `{nombre}` {motivo}: existe pero no hace nada.")
        for nombre, linea in fabricaciones_en_codigo(fuente, deben_traer_datos):
            hallazgos.append(f"DATOS FABRICADOS en {rel}:{linea}: `{nombre}` los INVENTA (random/uuid) en vez de "
                             "traerlos de verdad; el pedido pide datos reales, no generados.")
        for linea, frase in admisiones_de_simulacion(fuente, permitidas):
            hallazgos.append(f"SIMULACIÓN CONFESADA en {rel}:{linea}: «{frase}»: el código admite ser "
                             "provisional/ficticio, no lo real que se pidió.")
    return hallazgos[:12]


def _tokens_usados(llm) -> int:
    """Tokens (entrada + salida) que lleva gastados el cliente de modelos; 0 si no lleva la cuenta."""
    uso = getattr(llm, "uso", None)
    return int(getattr(uso, "tokens_entrada", 0) or 0) + int(getattr(uso, "tokens_salida", 0) or 0)


def _palabras_clave(texto: str) -> set:
    return {p for p in re.findall(r"[a-záéíóúñ0-9/._-]{4,}", (texto or "").lower())}


_RE_RESTRICCION = re.compile(r"únicamente|unicamente|solo (?:la )?(?:biblioteca|librer)|sin dependencias|"
                             r"no se (?:incluy|requier|us)|todavía no|no (?:usar|incluir|agregar)|standard library|"
                             r"no external|without (?:external|dependencies)", re.I)


def cobertura_criterios(criterios: list, plan) -> list:
    """Determinista (0 llamadas al modelo): criterios del contrato que NINGUNA tarea del plan parece cubrir, por
    solape de palabras/archivos. Es una señal temprana de desvío para el juez, NO un veredicto: lo real lo decide
    el juez al final con la evidencia. Conservadora: solo marca un criterio si no comparte ni una palabra con el plan."""
    if not criterios:
        return []
    texto = " ".join(f"{t.descripcion} {' '.join(t.archivos)}" for t in plan.tareas)
    texto += " " + (plan.objetivo or "") + " " + (plan.interfaz or "")
    palabras = _palabras_clave(texto)
    sin_cubrir = []
    for c in criterios:
        if _RE_RESTRICCION.search(c):
            continue                    # "solo la biblioteca estándar", "todavía no": restricción, no una tarea
        pc = _palabras_clave(c)
        if pc and not (pc & palabras):
            sin_cubrir.append(c)
    return sin_cubrir


@dataclass
class Tarea:
    id: str
    descripcion: str
    archivos: list = field(default_factory=list)
    deps: list = field(default_factory=list)   # ids de tareas que deben completarse antes (TaskGraph, Fase 8)


@dataclass
class Plan:
    objetivo: str
    tareas: list
    criterios: list
    texto: str = ""
    interfaz: str = ""

    def como_texto(self, actual: Optional[int] = None, hechas: int = 0) -> str:
        lineas = [f"Objetivo: {self.objetivo}"]
        if self.interfaz:
            lineas.append("Interfaz:")
            lineas.extend(f"  {l.strip()}" for l in self.interfaz.strip().splitlines() if l.strip())
        for i, t in enumerate(self.tareas):
            marca = "✓" if i < hechas else ("▸" if i == actual else " ")
            archivos = f" [{', '.join(t.archivos)}]" if t.archivos else ""
            lineas.append(f"[{marca}] {t.id}. {recortar(t.descripcion, 400)}{archivos}")
        if self.criterios:
            lineas.append("Criterios de aceptación:")
            lineas.extend(f"- {c}" for c in self.criterios)
        return "\n".join(lineas)

    def archivos(self) -> list[str]:
        vistos: dict[str, None] = {}
        for t in self.tareas:
            for a in t.archivos:
                vistos.setdefault(a, None)
        for m in re.finditer(r"([\w./-]+\.(?:py|js|mjs|cjs|ts|tsx|html|css|sh|go|rs))", self.interfaz):
            vistos.setdefault(m.group(1), None)
        return list(vistos)


def parsear_plan(texto: str, pedido: str, max_tareas: int = 8) -> Plan:
    texto = texto or ""
    m = _RE_OBJETIVO.search(texto)
    objetivo = m.group(1).strip() if m else recortar(pedido.strip().splitlines()[0] if pedido.strip() else "", 200)

    tareas: list[Tarea] = []
    for m in _RE_TAREA.finditer(texto):
        attrs = {k.lower(): v for k, v in _RE_ATTR.findall(m.group(2))}
        lista = attrs.get("archivos") or attrs.get("files") or ""
        archivos = [a.strip() for a in re.split(r"[,;\s]+", lista) if a.strip()]
        dep_txt = (attrs.get("deps") or attrs.get("depende") or attrs.get("dependencias")
                   or attrs.get("after") or attrs.get("tras") or "")
        deps = [d.strip() for d in re.split(r"[,;\s]+", dep_txt) if d.strip()]
        descripcion = m.group(3).strip()
        if descripcion:
            tareas.append(Tarea(attrs.get("id") or str(len(tareas) + 1), descripcion, archivos, deps))

    if not tareas:
        sin_criterios = _RE_INTERFAZ.sub("", _RE_CRITERIOS.sub("", texto))
        for linea in sin_criterios.splitlines():
            m = re.match(r"^\s*(?:tarea\s*)?(\d+)[.):-]\s+(.{8,})$", linea, re.I)
            if m:
                tareas.append(Tarea(m.group(1), m.group(2).strip(), []))
    if not tareas:
        tareas = [Tarea("1", pedido.strip(), [])]

    if len(tareas) > max_tareas:
        sobrantes = tareas[max_tareas - 1:]
        ids_sobrantes = {t.id for t in sobrantes}
        tareas = tareas[: max_tareas - 1] + [Tarea(
            sobrantes[0].id,
            "\n".join(f"- {t.descripcion}" for t in sobrantes),
            sorted({a for t in sobrantes for a in t.archivos}),
            # Antes se perdían: la tarea agrupada podía correr aunque una de la que dependía hubiera fallado.
            sorted({d for t in sobrantes for d in t.deps if d not in ids_sobrantes}),
        )]

    criterios = []
    m = _RE_CRITERIOS.search(texto)
    if m:
        for linea in m.group(1).splitlines():
            linea = re.sub(r"^\s*([-*•]|\d+[.)])\s*", "", linea).strip()
            if linea:
                criterios.append(linea)
    m = _RE_INTERFAZ.search(texto)
    interfaz = m.group(1).strip() if m else ""
    return Plan(objetivo, tareas, criterios, texto, interfaz)


def _archivos_interfaz(interfaz: str) -> list[str]:
    vistos: dict[str, None] = {}
    for m in re.finditer(r"([\w./-]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|html|css|sh|go|rs|java|php|rb|c|h|cpp))\b", interfaz or ""):
        vistos.setdefault(m.group(1), None)
    return list(vistos)


def plan_degenerado(plan: Plan, pedido: str, texto: str = "") -> str:
    """
    Motivo si el plan no sirve para trabajar por partes: una sola tarea gigante que repite el pedido
    (lo que se vio con NebulaDB). Vacío si el plan está bien. Un pedido chico SÍ puede tener una tarea.
    """
    if len(plan.tareas) != 1:
        return ""
    unica = plan.tareas[0]
    archivos = set(unica.archivos) | set(_archivos_interfaz(plan.interfaz))
    grande = len(pedido or "") >= 160 or len(archivos) >= 3
    if not grande:
        return ""
    if not _RE_TAREA.search(texto or plan.texto or ""):
        return "no usaste etiquetas <tarea>: el plan no se pudo leer"
    parecido = difflib.SequenceMatcher(None, unica.descripcion.lower()[:1500], (pedido or "").lower()[:1500]).ratio()
    if parecido >= 0.6:
        return "tu única tarea repite el pedido completo"
    if len(unica.archivos) >= 4 or len(archivos) >= 4:
        return f"tu única tarea toca {len(archivos)} archivos"
    return ""


def dividir_por_interfaz(plan: Plan) -> Plan:
    """Último recurso: una tarea por archivo de la interfaz (en el orden en que aparecen)."""
    archivos = _archivos_interfaz(plan.interfaz) or (plan.tareas[0].archivos if plan.tareas else [])
    if len(archivos) < 2:
        return plan
    lineas = [l.strip() for l in (plan.interfaz or "").splitlines() if l.strip()]
    tareas = []
    for n, rel in enumerate(archivos, 1):
        propias = [l for l in lineas if rel in l]
        detalle = "\n".join(propias) or "(ver la interfaz del plan)"
        tareas.append(Tarea(str(n), f"Implementá {rel} según la INTERFAZ del plan:\n{detalle}\n"
                                    f"Contexto general: {recortar(plan.objetivo, 300)}", [rel]))
    return Plan(plan.objetivo, tareas, plan.criterios, plan.texto, plan.interfaz)


def verificacion_peor(despues: "Verificacion", antes: "Verificacion") -> bool:
    """¿La verificación empeoró? Más validaciones rotas, o tests peores (más fallos o menos que pasan)."""
    if len(fallos(despues.validaciones)) > len(fallos(antes.validaciones)):
        return True
    return es_peor(despues.conteo, antes.conteo)


REVISION_SIN_DICTAMEN = "VEREDICTO: CAMBIOS\nLa revisión no entregó un dictamen verificable (APROBADO o CAMBIOS)."
_RE_ITEM_REVISION = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S")
_RE_PROBLEMA_REVISION = re.compile(r"\b(?:falta|faltan|error|errores|bug|falla|fallan|corregi|correg|deber[íi]a|"
                                   r"no (?:valida|maneja|cubre|funciona|controla|verifica)|problema|incorrect|"
                                   r"missing|should|fix|wrong|broken)", re.I)


def observaciones_concretas(informe: str) -> bool:
    """Una revisión sin la línea VEREDICTO puede igual traer puntos accionables (lista + un problema nombrado)."""
    texto = informe or ""
    return bool(_RE_ITEM_REVISION.search(texto) and _RE_PROBLEMA_REVISION.search(texto))


def veredicto(informe: str) -> tuple[bool, bool]:
    """(aprobado, claro). Un dictamen malformado NO equivale a una aprobación."""
    m = _RE_VEREDICTO.search(informe or "")
    if not m:
        return False, False
    return m.group(1).upper() == "APROBADO", True


# ======================================================================
# REAPER 8.10 — RONDA 12: PRUEBAS DE ACEPTACIÓN INDEPENDIENTES
# ======================================================================
# Contrato administrado por el propietario, separado del workspace.
# No usa shell, no descarga código ni aprueba si se recogieron 0 tests.
# El manifiesto .reaper/acceptance.json es opcional para proyectos antiguos.

def _aceptacion_error(mensaje: str) -> Resultado:
    return Resultado(False, 'aceptacion_independiente', 1, stderr=str(mensaje))


def _manifiesto_aceptacion(ws: Workspace) -> Optional[tuple]:
    """(bytes_crudos, spec, carpeta_suite) del manifiesto validado; None si no hay evaluador configurado."""
    cfg = ws.raiz / '.reaper' / 'acceptance.json'
    if not cfg.exists() and not cfg.is_symlink():
        return None
    if cfg.is_symlink() or not cfg.is_file():
        raise ValueError('El manifiesto de aceptación no puede ser un enlace simbólico.')
    if cfg.stat().st_size > 16_384:
        raise ValueError('El manifiesto de aceptación supera 16 KiB.')
    raw = cfg.read_bytes()
    try:
        spec = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f'Manifiesto de aceptación inválido: {exc}') from exc
    if not isinstance(spec, dict) or set(spec) - {'suite_dir', 'min_tests', 'timeout'}:
        raise ValueError('El manifiesto acepta solo suite_dir, min_tests y timeout.')
    suite_str = spec.get('suite_dir')
    if not isinstance(suite_str, str) or not os.path.isabs(os.path.expanduser(suite_str)):
        raise ValueError('suite_dir debe ser una carpeta ABSOLUTA fuera del proyecto.')
    suite = Path(os.path.expanduser(suite_str)).resolve(strict=False)
    raiz = ws.raiz.resolve()
    if os.path.commonpath((str(suite), str(raiz))) == str(raiz):
        raise ValueError('La suite independiente debe estar FUERA del proyecto editado por REAPER.')
    if not suite.is_dir():
        raise ValueError(f'No existe la suite independiente: {suite}')
    minimo = spec.get('min_tests', 1)
    tiempo = spec.get('timeout', 60)
    if isinstance(minimo, bool) or not isinstance(minimo, int) or not 1 <= minimo <= 10000:
        raise ValueError('min_tests debe ser un entero entre 1 y 10000.')
    if isinstance(tiempo, bool) or not isinstance(tiempo, int) or not 1 <= tiempo <= 180:
        raise ValueError('timeout debe ser un entero entre 1 y 180.')
    return raw, spec, suite


def _archivos_suite(suite: Path) -> list:
    """Todos los archivos de la suite externa (tests Y auxiliares), sin cachés de bytecode. Acotado."""
    archivos = []
    for p in sorted(suite.rglob('*')):
        rel = p.relative_to(suite)
        if '__pycache__' in rel.parts or p.suffix == '.pyc':
            continue
        if p.is_symlink():
            raise ValueError(f'La suite independiente no admite enlaces simbólicos: {rel}')
        if p.is_file():
            archivos.append(p)
            if len(archivos) > 2000:
                raise ValueError('La suite externa tiene demasiados archivos (> 2000).')
    return archivos


def huella_aceptacion(ws: Workspace) -> str:
    """
    Fija el manifiesto y TODA la suite externa (tests y auxiliares: un helpers.py editado también cuenta);
    cambios durante la build => fallo cerrado.
    """
    datos = _manifiesto_aceptacion(ws)
    if datos is None:
        return 'sin-evaluador'
    raw, _spec, suite = datos
    archivos = _archivos_suite(suite)
    tests = [p for p in archivos if p.name.startswith('test_') and p.suffix == '.py']
    if not tests or len(tests) > 500:
        raise ValueError('La suite externa debe incluir 1 a 500 archivos test_*.py.')
    h = hashlib.sha256(b'REAPER-810-ACCEPTANCE-V2\0' + raw)
    total = 0
    for p in archivos:
        tam = p.stat().st_size
        if tam > 1_000_000:
            raise ValueError(f'Archivo de la suite externa demasiado grande: {p.name}')
        total += tam
        if total > 20_000_000:
            raise ValueError('La suite externa supera 20 MB.')
        h.update(str(p.relative_to(suite)).encode('utf-8') + b'\0')
        h.update(p.read_bytes())
        h.update(b'\0')
    return h.hexdigest()


def huella_aceptacion_v1(ws: Workspace) -> str:
    """Huella de la ronda 12 (solo test_*.py). Solo para reanudar diarios creados con esa versión."""
    datos = _manifiesto_aceptacion(ws)
    if datos is None:
        return 'sin-evaluador'
    raw, _spec, suite = datos
    h = hashlib.sha256(b'REAPER-810-ACCEPTANCE-V1\0' + raw)
    for p in sorted(suite.rglob('test_*.py')):
        h.update(str(p.relative_to(suite)).encode('utf-8') + b'\0')
        h.update(p.read_bytes())
        h.update(b'\0')
    return h.hexdigest()


# Runner de confianza del evaluador externo. Corre con `python -I -B`: el proyecto (editable por el agente)
# NUNCA entra en sys.path, así un `unittest.py`/`json.py` del proyecto no puede suplantar la librería
# estándar e imprimir un "OK" falso (antes pasaba: el gate aprobaba una suite que fallaba). El conteo sale de
# los objetos de unittest, no de leer texto, en una línea con una marca aleatoria que llega por stdin.
_RUNNER_ACEPTACION = r"""
import os, sys
sys.path[:] = [p for p in sys.path if p not in ('', '.') and os.path.abspath(p) != os.getcwd()]
import json, unittest
marca = sys.stdin.readline().strip()
suite = sys.argv[1]
r = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(
    unittest.TestLoader().discover(suite, pattern='test_*.py', top_level_dir=suite))
datos = {'ran': r.testsRun, 'failures': len(r.failures), 'errors': len(r.errors), 'skipped': len(r.skipped),
         'expected_failures': len(r.expectedFailures), 'unexpected_successes': len(r.unexpectedSuccesses)}
sys.stdout.write('\n' + marca + json.dumps(datos) + '\n')
sys.stdout.flush()
sys.exit(0 if r.wasSuccessful() else 1)
"""


def ejecutar_aceptacion_independiente(ws: Workspace, *,
                                        huella_fijada: Optional[str] = None) -> Optional[Resultado]:
    """Devuelve None solo si NO se configuró un evaluador al inicio de la build.

    Ejecuta la suite con el runner de confianza (argv real, sin shell, aislado del proyecto). No acepta
    cambiar/quitar los tests, resultados vacíos, sin conteo verificable o con todo omitido.
    """
    try:
        huella_actual = huella_aceptacion(ws)
        if huella_fijada is not None and huella_fijada != huella_actual:
            return _aceptacion_error('Evaluador independiente cambiado o eliminado durante la build.')
        if huella_actual == 'sin-evaluador':
            return None
        _raw, spec, suite = _manifiesto_aceptacion(ws)
        marca = 'REAPER-ACEPTACION-' + secrets.token_hex(16)
        resultado = ejecutar([sys.executable, '-I', '-B', '-c', _RUNNER_ACEPTACION, str(suite)],
                             cwd=ws.raiz, timeout=int(spec.get('timeout', 60)), shell=False,
                             entrada=marca + '\n', env_extra={'REAPER_PROYECTO': str(ws.raiz)})
        resultado.comando = f"aceptación independiente: unittest {suite}"
        datos = None
        for linea in reversed(resultado.stdout.splitlines()):
            if linea.startswith(marca):
                try:
                    datos = json.loads(linea[len(marca):].strip())
                except ValueError:
                    datos = None
                break
        resultado.stdout = '\n'.join(l for l in resultado.stdout.splitlines() if not l.startswith(marca))
        minimo = spec.get('min_tests', 1)
        if not isinstance(datos, dict):
            resultado.ok = False
            resultado.stderr += '\nACEPTACIÓN: falta conteo verificable del runner (¿se interrumpió o se cortó?).'
        else:
            efectivos = max(0, int(datos.get('ran', 0)) - int(datos.get('skipped', 0))
                            - int(datos.get('expected_failures', 0)))
            malos = int(datos.get('failures', 0)) + int(datos.get('errors', 0)) + int(datos.get('unexpected_successes', 0))
            resultado.stderr += (f"\nACEPTACIÓN: {datos.get('ran', 0)} corridos, {efectivos} efectivos, "
                                 f"{datos.get('failures', 0)} fallos, {datos.get('errors', 0)} errores, "
                                 f"{datos.get('skipped', 0)} omitidos (mínimo {minimo}).")
            if malos or resultado.codigo != 0:
                resultado.ok = False
            if efectivos < minimo:
                resultado.ok = False
                resultado.stderr += (f'\nACEPTACIÓN: solo {efectivos}/{minimo} pruebas ejecutadas '
                                     'sin omisiones o fallos esperados.')
        if huella_aceptacion(ws) != huella_actual:
            resultado.ok = False
            resultado.stderr += '\nACEPTACIÓN: los tests/manifiesto se modificaron al ejecutarse.'
        return resultado
    except (ValueError, OSError, UnicodeError) as exc:
        return _aceptacion_error(f'ACEPTACIÓN inválida: {exc}')


_RE_REF_FALTANTE = re.compile(r"referencia a '([^']+)' que no existe")


def _sin_recursos_planeados(ws: Workspace, resultado: Resultado, planeados: Sequence[str]) -> Optional[Resultado]:
    """
    En una tarea INTERMEDIA, un HTML que enlaza un CSS/JS que crea una tarea POSTERIOR del plan no es un fallo
    todavía (antes: la tarea del HTML fallaba, las de los assets quedaban bloqueadas y la build nunca los creaba).
    Devuelve None si todas las referencias faltantes están planeadas, o el resultado con solo las no planeadas.
    La verificación FINAL sigue exigiéndolas todas.
    """
    if not planeados or not resultado.comando.startswith("recursos-html"):
        return resultado
    base_html = Path(resultado.archivo or "").parent
    planeados_norm = {Path(p).as_posix().lstrip("./") for p in planeados}
    pendientes = []
    for linea in resultado.stderr.splitlines():
        m = _RE_REF_FALTANTE.search(linea)
        if not m:
            pendientes.append(linea)
            continue
        ref = m.group(1).lstrip("/")
        candidatos = {ref, (base_html / ref).as_posix()} | {f"{d}/{ref}" for d in _RAICES_WEB}
        if not ({Path(c).as_posix().lstrip("./") for c in candidatos} & planeados_norm):
            pendientes.append(linea)
    if not [l for l in pendientes if l.strip()]:
        return None
    return replace(resultado, stderr="\n".join(pendientes))


@dataclass
class Verificacion:
    ok: bool
    validaciones: list
    tests: Optional[Resultado]
    diagnostico: str
    archivos: list
    conteo: ConteoTests = field(default_factory=ConteoTests)
    aceptacion: Optional[Resultado] = None


@dataclass
class InformeBuild:
    estado: str
    plan: Optional[Plan] = None
    archivos: list = field(default_factory=list)
    tests: Optional[Resultado] = None
    aceptacion: Optional[Resultado] = None
    diagnostico: str = ""
    cid: Optional[int] = None
    ruta_informe: Optional[Path] = None
    notas: list = field(default_factory=list)
    lecciones: list = field(default_factory=list)
    escaladas: int = 0
    torneos: list = field(default_factory=list)
    commit: Optional[str] = None
    spec_tests: list = field(default_factory=list)
    segundos: float = 0.0
    tareas_fallidas: list = field(default_factory=list)    # quedaron con fallos tras reparar
    tareas_bloqueadas: list = field(default_factory=list)  # no se ejecutaron: dependen de una fallida
    juicio: Optional["Juicio"] = None                      # veredicto del 8.º agente (juez de entrega)
    criterios_entrega: list = field(default_factory=list)  # contrato: criterios que el juez derivó del pedido
    intervenciones_juez: int = 0                           # cuántas veces el juez tuvo que intervenir para cerrar
    tokens_juez: int = 0                                   # lo que gastó el juez en ESTA build (estimado)
    tokens_build: int = 0                                  # lo que gastó la build entera (para comparar)
    motivos_fallo: dict = field(default_factory=dict)      # tarea → por qué quedó fallida (el error REAL, no "falló")
    restaurados: list = field(default_factory=list)        # archivos previos que PRESERVAR devolvió a su estado
    reemplazos_autorizados: list = field(default_factory=list)  # archivos previos que el usuario autorizó reescribir

    @property
    def ok(self) -> bool:
        return self.estado in ("verificada", "validada")


def estado_final_build(verif: Verificacion, informe: InformeBuild) -> str:
    """Nunca declarar terminada una build con tareas omitidas, aunque la suite actual esté verde."""
    if not verif.ok:
        return "fallida"
    if informe.tareas_bloqueadas or informe.tareas_fallidas:
        return "parcial"
    hay_tests = verif.tests is not None and not verif.tests.omitido
    return "verificada" if hay_tests or (verif.aceptacion is not None and verif.aceptacion.ok) else "validada"


def _diffstat(diff: str) -> str:
    stats: dict[str, list[int]] = {}
    actual = None
    for linea in diff.splitlines():
        if linea.startswith("+++ b/"):
            actual = linea[6:]
            stats.setdefault(actual, [0, 0])
        elif actual and linea.startswith("+") and not linea.startswith("+++"):
            stats[actual][0] += 1
        elif actual and linea.startswith("-") and not linea.startswith("---"):
            stats[actual][1] += 1
    return "\n".join(f"  {a}  +{m} -{n}" for a, (m, n) in stats.items())


def _resumen_diff(diff: str) -> str:
    """Total compacto del diff para el cierre: 'N archivo(s) · +X −Y'. Vacío si no hubo cambios."""
    archivos = mas = menos = 0
    actual = None
    for linea in (diff or "").splitlines():
        if linea.startswith("+++ b/"):
            actual = True
            archivos += 1
        elif actual and linea.startswith("+") and not linea.startswith("+++"):
            mas += 1
        elif actual and linea.startswith("-") and not linea.startswith("---"):
            menos += 1
    if not archivos:
        return ""
    return f"{archivos} archivo(s) · +{mas} −{menos}"


_RE_DIAGNOSTICO_OBVIO = re.compile(
    r"NameError|ImportError|ModuleNotFoundError|No module named|SyntaxError|IndentationError|F821|Undefined name|"
    r"is not defined|no define '|has no attribute|missing \d+ required positional|takes \d+ positional|"
    r"ENTREGA INCOMPLETA|DESVÍO|TRAMPA PARA LOS TESTS|TEST DEBILITADO")


def diagnostico_obvio(diagnostico: str) -> bool:
    """Errores que se arreglan leyendo el mensaje (un import, un nombre, la sintaxis, un archivo que falta): el modo
    forense (varias llamadas de experimentos) no aporta y solo gasta pedidos y tiempo."""
    return bool(_RE_DIAGNOSTICO_OBVIO.search(diagnostico or ""))


def verificacion_mejor(despues: "Verificacion", antes: "Verificacion") -> bool:
    """¿Hubo avance medible (más tests pasando o menos fallos)?"""
    d, a = despues.conteo, antes.conteo
    if not (d.reconocido and a.reconocido):
        return False
    return d.pasados > a.pasados or (d.fallados + d.errores) < (a.fallados + a.errores)


def fusionar_tareas_de_solo_tests(plan: "Plan", ya_escritos: Optional[set] = None) -> list:
    """Una tarea que SOLO escribe tests y va ANTES del código que prueba nunca puede quedar verde (sus tests fallan
    hasta que otra tarea escriba el código): se reparaba en vano y bloqueaba a las que dependían de ella (prueba real:
    "2. Escribir prueba unitaria…" antes de "3. Implementar main"). Se fusiona con la tarea de código que la usa; los
    tests que van DESPUÉS del código (o que dependen de él) se dejan, igual que los que ya escribió la especificación
    (`ya_escritos`: esa tarea se da por cubierta). Modifica el plan y devuelve los avisos; si la fusión dejara el grafo
    inválido, no toca nada."""
    ya_escritos = set(ya_escritos or ())
    tareas = [replace(t, archivos=list(t.archivos), deps=list(t.deps)) for t in plan.tareas]
    avisos = []
    i = 0
    while i < len(tareas):
        tarea = tareas[i]
        if not tarea.archivos or not all(_es_test(a) for a in tarea.archivos) \
                or all(a in ya_escritos for a in tarea.archivos):
            i += 1
            continue
        con_codigo = [t for t in tareas[i + 1:] if any(not _es_test(a) for a in t.archivos)]
        destino = next((t for t in con_codigo if tarea.id in t.deps), None)
        if destino is None and not tarea.deps and con_codigo:
            destino = con_codigo[0]
        if destino is None:
            i += 1
            continue
        destino.archivos = list(dict.fromkeys(list(destino.archivos) + list(tarea.archivos)))
        destino.descripcion = destino.descripcion.rstrip() + "\nIncluye también sus tests: " + tarea.descripcion.strip()
        destino.deps = [d for d in dict.fromkeys(list(destino.deps) + list(tarea.deps)) if d not in (tarea.id, destino.id)]
        for otra in tareas:
            if otra is not tarea and tarea.id in otra.deps:
                otra.deps = [d for d in dict.fromkeys(destino.id if d == tarea.id else d for d in otra.deps)
                             if d != otra.id]
        tareas.pop(i)
        avisos.append(f"Tarea {tarea.id} (solo tests, antes de su código) unida a la tarea {destino.id}: "
                      f"{', '.join(tarea.archivos)}")
    if avisos and not errores_grafo_build(replace(plan, tareas=tareas)):
        plan.tareas = tareas
        return avisos
    return []


def tests_de_especificacion_rotos(validaciones: list) -> list:
    """Fallos que son errores DEL TEST (sintaxis o nombres que el test nunca importó ni definió), no el rojo
    esperado de tests primero (importar un módulo que todavía no existe)."""
    return [r for r in fallos(validaciones)
            if r.comando.startswith(("py_compile", "node --check")) or "(nombres indefinidos)" in r.comando]


def _es_test(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, p) for p in PATRONES_TESTS)


FASE_BUILD = "fase:"


def _marcar_fase(registro_build: "RegistroBuild", previo: dict, nombre: str, cid: int) -> None:
    """Una FASE que escribe archivos (tests primero, verificación final y reparación) queda anotada en el diario como
    la tarea activa: si se corta ahí (cupo diario, Ctrl+C, Termux cerrado), sus cambios tienen dueño y la build se
    puede retomar. Antes solo las tareas lo tenían: la corrida E2E de /grande cortada por el cupo mientras el
    especificador escribía tests/test_api.py quedaba en "Cambios externos…" y la etapa no se podía seguir nunca."""
    previo["tarea_activa"] = FASE_BUILD + nombre
    previo["tcid"] = cid
    previo["huellas_inicio"] = registro_build.huellas()
    registro_build.guardar(previo)


def _cerrar_fase(previo: dict) -> None:
    for clave in ("tarea_activa", "tcid", "huellas_inicio"):
        previo.pop(clave, None)


def mismo_pedido(guardado, actual: str) -> bool:
    """¿El pedido guardado en un diario/estado es este? Los diarios se escriben REDACTADOS (un pedido con
    "password: admin123" queda "password: [REDACTADO]"), así que se compara también contra la forma redactada:
    si no, la build a medio hacer de ese pedido no se reconocía nunca más y /grande quedaba trabado."""
    def norma(texto) -> str:
        return " ".join(str(texto or "").split())
    return norma(guardado) in (norma(actual), norma(redactar_secretos(actual or "")))


def fallos_tolerables_al_reintentar(fallan_ahora: set, fallaban_al_inicio: Sequence[str], tarea, tareas) -> set:
    """Al RE-EJECUTAR una tarea que falló o se cortó, ¿qué tests en rojo no son culpa suya? Los que ya fallaban al
    empezar la build y los de archivos de test que declaran OTRAS tareas (en una corrida normal también se
    toleran). Los suyos —o los que rompió y no declaraba— no: si no, su propio test en rojo pasaba por "previo"."""
    ajenos = {rel: None for t in tareas if t.id != tarea.id for rel in t.archivos if _es_test(rel)}
    previos = set(fallaban_al_inicio)
    return {n for n in fallan_ahora if n in previos or (ajenos and _es_de_especificacion(n, ajenos))}


def _es_de_especificacion(nombre_test: str, protegidos: dict) -> bool:
    """¿El test que falla pertenece a un archivo de la especificación? (pytest usa ruta::test, unittest modulo.Clase.test)"""
    for rel in protegidos:
        ruta = Path(rel)
        modulo = ".".join(ruta.with_suffix("").parts)
        if rel in nombre_test or nombre_test.startswith(modulo + ".") or f".{ruta.stem}." in f".{nombre_test}." \
                or nombre_test.startswith(ruta.stem + "."):
            return True
    return False


# Registro persistente y prudente de /construir. No es una fuente de verdad
# sobre los tests: conserva solo estados observados y permite un resume explícito.
class RegistroBuild:
    ESQUEMA = 1

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.ruta = ws.carpeta_reaper() / "build_pendiente.json"

    def huellas(self) -> dict[str, str]:
        """Inventario para reanudar: incluye binarios, permisos y symlinks sin leer secretos.

        El inventario anterior solo incluía archivos de texto conocidos, y
        permitía pasar por alto cambios externos en datos SQLite, imágenes o
        enlaces simbólicos. Para archivos grandes se usa metadata y no contenido.
        """
        salidas: dict[str, str] = {}
        maximo = 2000
        for actual, carpetas, archivos in os.walk(self.ws.raiz, followlinks=False):
            base = Path(actual)
            rel_base = base.relative_to(self.ws.raiz).as_posix()
            rel_base = "" if rel_base == "." else rel_base
            permitidas = []
            for nombre in sorted(carpetas):
                rel = f"{rel_base}/{nombre}".lstrip("/")
                if self.ws.ignorado(rel, True):
                    continue
                ruta = base / nombre
                if ruta.is_symlink():
                    # Registrar su existencia y destino, sin seguirlo ni abrirlo.
                    salidas[rel + "/"] = "link:" + hashlib.sha256(os.fsencode(os.readlink(ruta))).hexdigest()
                else:
                    permitidas.append(nombre)
                if len(salidas) > maximo:
                    raise ValueError("Más de 2000 archivos/enlaces: no puedo verificar la reanudación")
            carpetas[:] = permitidas
            for nombre in sorted(archivos):
                rel = f"{rel_base}/{nombre}".lstrip("/")
                if self.ws.ignorado(rel, False):
                    continue
                ruta = base / nombre
                try:
                    st = ruta.lstat()
                    if ruta.is_symlink():
                        digest = "link:" + hashlib.sha256(os.fsencode(os.readlink(ruta))).hexdigest()
                    elif not ruta.is_file():
                        continue
                    elif es_archivo_sensible(nombre) or st.st_size > 16_000_000:
                        # No abrir claves privadas; sin cargar archivos enormes en RAM.
                        detalle = f"meta:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}:{st.st_mode}"
                        digest = hashlib.sha256(detalle.encode()).hexdigest()
                    else:
                        h = hashlib.sha256()
                        with ruta.open("rb") as f:
                            for bloque in iter(lambda: f.read(65536), b""):
                                h.update(bloque)
                        digest = h.hexdigest()
                    salidas[rel] = digest
                except OSError as e:
                    raise ValueError(f"No pude verificar {rel}: {e}") from e
                if len(salidas) > maximo:
                    raise ValueError("Más de 2000 archivos/enlaces: no puedo verificar la reanudación")
        return salidas

    def huella(self) -> str:
        h = hashlib.sha256()
        for rel, digest in sorted(self.huellas().items()):
            h.update(f"{rel}\0{digest}\n".encode("utf-8"))
        return h.hexdigest()

    def huella_legada(self) -> str:
        """Solo para validar la huella de diarios anteriores a la ronda 6.

        El inventario antiguo omitía binarios y enlaces. Por ese motivo,
        incluso si coincide, NO conserva tareas verificadas: vuelve a probarlas.
        """
        salidas = {}
        archivos = list(self.ws.iterar(limite=2001))
        if len(archivos) > 2000:
            raise ValueError("Más de 2000 archivos en el diario antiguo")
        for ruta in archivos:
            if not self.ws.es_texto(ruta) or not ruta.is_file() or ruta.is_symlink():
                continue
            try:
                if ruta.stat().st_size > 2_000_000:
                    raise ValueError("El archivo grande requiere iniciar una construcción nueva")
                h = hashlib.sha256()
                with ruta.open("rb") as f:
                    for bloque in iter(lambda: f.read(65536), b""):
                        h.update(bloque)
                salidas[self.ws.rel(ruta)] = h.hexdigest()
            except OSError as e:
                raise ValueError(f"Inventario legado ilegible: {e}") from e
        h = hashlib.sha256()
        for rel, digest in sorted(salidas.items()):
            h.update(f"{rel}\0{digest}\n".encode("utf-8"))
        return h.hexdigest()

    def recuperable(self, previo: dict) -> bool:
        """Acepta modificaciones de la tarea interrumpida SOLO si están en su checkpoint.

        Si cambió un archivo fuera de ese checkpoint, puede tratarse de una
        edición externa: no saltamos tareas con evidencia antigua.
        """
        if previo["huella"] == self.huella():
            return True
        activo = previo.get("tarea_activa")
        tcid = previo.get("tcid")
        inicio = previo.get("huellas_inicio")
        if not isinstance(activo, str) or not isinstance(tcid, int) or not isinstance(inicio, dict):
            return False
        if tcid not in self.ws.checkpoints.ids():
            return False
        antes = inicio
        ahora = self.huellas()
        cambiados = {p for p in set(antes) | set(ahora) if antes.get(p) != ahora.get(p)}
        registrados = set(self.ws.checkpoints.archivos_desde(tcid))
        if not cambiados or not cambiados.issubset(registrados):
            return False
        if activo == FASE_BUILD + "cierre":
            # Cortada en la verificación final o la reparación: el reparador SÍ toca archivos de tareas verificadas,
            # y al retomar la verificación final se repite entera (no se omite nada con evidencia vieja).
            return True
        # Una tarea a medio hacer no debe invalidar en silencio otra ya validada.
        verificados = previo.get("archivos_verificados", {})
        if any(antes.get(p) != ahora.get(p) for p in verificados):
            return False
        return True

    def leer(self) -> Optional[dict]:
        if not self.ruta.is_file():
            return None
        try:
            if self.ruta.stat().st_size > 250_000:
                raise ValueError("registro demasiado grande")
            registro = json.loads(self.ruta.read_text(encoding="utf-8"))
            if not isinstance(registro, dict) or registro.get("esquema") != self.ESQUEMA:
                raise ValueError("versión de registro incompatible")
            if registro.get("proyecto") != str(self.ws.raiz):
                raise ValueError("el registro es de otro proyecto")
            if not isinstance(registro.get("pedido"), str) or not isinstance(registro.get("plan"), dict):
                raise ValueError("pedido/plan no válidos")
            tareas = registro["plan"].get("tareas")
            if not isinstance(tareas, list) or not tareas or len(tareas) > 60:
                raise ValueError("grafo de tareas inválido")
            ids = [t.get("id") for t in tareas if isinstance(t, dict)]
            if len(ids) != len(tareas) or len(set(ids)) != len(ids) or any(not isinstance(i, str) for i in ids):
                raise ValueError("ids de tareas inválidos")
            if not isinstance(registro.get("estados"), dict) or not isinstance(registro.get("huella"), str):
                raise ValueError("estados o huella inválidos")
            if not isinstance(registro.get("grupo"), int) or registro["grupo"] < 1:
                raise ValueError("checkpoint inválido")
            if not isinstance(registro.get("archivos_verificados", {}), dict) or not isinstance(registro.get("tests_protegidos", {}), dict):
                raise ValueError("huellas de verificación inválidas")
            try:
                plan = _plan_de_registro(registro["plan"])
                if errores_grafo_build(plan):
                    raise ValueError("plan guardado con dependencias inválidas")
            except (KeyError, TypeError, AttributeError, ValueError) as e:
                raise ValueError(f"plan guardado no válido: {e}") from e
            return registro
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"Registro de build dañado: {e}") from e

    def guardar(self, registro: dict) -> None:
        registro["huella"] = self.huella()
        registro["huellas_version"] = 2
        registro["actualizado"] = datetime.now().isoformat(timespec="seconds")
        # Nunca guardar prompts de conversación con claves sin redactar.
        contenido = redactar_secretos(json.dumps(registro, ensure_ascii=False, indent=2))
        if len(contenido) > 250_000:
            raise ValueError("Registro de build demasiado grande")
        escritura_atomica(self.ruta, contenido)

    def borrar(self) -> None:
        if self.ruta.is_file():
            self.ruta.unlink()


def _plan_de_registro(datos: dict) -> Plan:
    for item in datos["tareas"]:
        if not isinstance(item, dict) or not isinstance(item.get("descripcion"), str) \
                or not isinstance(item.get("archivos", []), list) or not isinstance(item.get("deps", []), list):
            raise ValueError("Plan inválido")
        if any(not isinstance(x, str) for x in item.get("archivos", []) + item.get("deps", [])):
            raise ValueError("Plan inválido: nombres de archivos o dependencias")
    tareas = [Tarea(t["id"], t["descripcion"], t.get("archivos", []), t.get("deps", []))
              for t in datos["tareas"]]
    return Plan(str(datos.get("objetivo", "")), tareas, list(datos.get("criterios", [])),
                str(datos.get("texto", "")), str(datos.get("interfaz", "")))


def errores_grafo_build(plan: Plan) -> list[str]:
    """No ejecutar un plan con dependencias ambiguas o tareas duplicadas."""
    if not plan.tareas:
        return ["el plan no contiene tareas"]
    ids = [t.id for t in plan.tareas]
    errores = []
    if any(not isinstance(i, str) or not i.strip() for i in ids):
        errores.append("hay identificadores de tarea vacíos o inválidos")
    elif len(ids) != len(set(ids)):
        errores.append("hay identificadores de tarea duplicados")
    if errores:
        return errores
    grafo = GrafoTareas(plan.tareas)
    grafo.orden()  # registra ciclos y dependencias inexistentes
    errores.extend(grafo.problemas)
    if any(t.id in (t.deps or []) for t in plan.tareas):
        errores.append("hay tareas que dependen de sí mismas")
    return errores


class Orquestador:
    def __init__(self, llm, ws: Workspace, settings: Settings, ui: UI):
        self.llm = llm
        self.ws = ws
        self.settings = settings
        self.ui = ui
        self.memoria = MemoriaLecciones(ws) if settings.lecciones else None
        self.escalador = Escalador(llm, settings, ui)
        self._protegidos: dict[str, Optional[str]] = {}
        self._huella_aceptacion: Optional[str] = None
        # Pedido ORIGINAL del usuario cuando el pedido de la build lo arma REAPER (etapas de /grande): lo que
        # autoriza reescribir archivos previos o pedir "datos de ejemplo" sale de acá, nunca del plan del modelo.
        self.pedido_usuario: Optional[str] = None

    def _sub(self, rol: str, tarea: str, cid: Optional[int], archivos: str = "", titulo: str = "",
             **opciones) -> ResultadoAgente:
        opciones.setdefault("memoria", self.memoria)
        return ejecutar_subagentes(
            [(rol, tarea, archivos, titulo, opciones)], self.llm, self.ws, self.settings, self.ui,
            profundidad=1, cid_inicio=cid,
        )[0]

    def _sub_opcional(self, rol: str, tarea: str, cid: Optional[int], **kw) -> Optional[ResultadoAgente]:
        """
        Roles de APOYO (revisor, QA, explorador): si su modelo falla incluso después del respaldo entre las IAs
        del equipo, se avisa y la build SIGUE (antes un 413 del revisor abortaba todo /construir). Solo el
        presupuesto agotado corta, porque seguir gastaría más.
        """
        try:
            return self._sub(rol, tarea, cid, **kw)
        except LLMError as e:
            if e.detiene_todo:
                raise
            self.ui.aviso(f"  {rol}: el modelo no respondió ({recortar(str(e), 180)}). Sigo sin esa fase.")
            return None

    # ------------------------------------------------------------ fases
    def explorar(self, pedido: str) -> str:
        archivos = self.ws.archivos_codigo(limite=500)
        if not archivos:
            return "El workspace está vacío: hay que crear todo desde cero."
        mapa = mapa_relevante(self.ws, pedido, self.settings.max_relevantes) if self.settings.mapa_relevantes else ""
        if len(archivos) <= 6:
            # Proyecto chico: un mapa directo sale gratis y no gasta llamadas al modelo.
            partes = ["Proyecto chico; mapa completo:"]
            for rel in archivos:
                simbolos = outline(self.ws.raiz / rel)
                partes.append(rel + ("\n" + "\n".join("  " + s for s in simbolos[:30]) if simbolos else ""))
            return "\n".join(partes)

        specs = [(
            "explorador",
            f"PEDIDO DEL USUARIO:\n{pedido}\n\nInvestigá qué partes del código tocan este pedido: archivos, "
            "funciones y clases involucradas, cómo se conectan y qué convenciones hay que respetar.",
            "",
            "código relacionado con el pedido",
            {"memoria": self.memoria},
        )]
        if len(archivos) > 15 and self.settings.paralelo > 1:
            specs.append((
                "explorador",
                f"PEDIDO DEL USUARIO:\n{pedido}\n\nNO analices la lógica del pedido. Investigá cómo se ejecuta y "
                "cómo se prueba este proyecto: puntos de entrada, dependencias, tests existentes y su comando, "
                "estructura de carpetas y configuración.",
                "",
                "cómo se ejecuta y se prueba el proyecto",
                {"memoria": self.memoria},
            ))
        try:
            resultados = ejecutar_subagentes(specs, self.llm, self.ws, self.settings, self.ui, profundidad=1)
        except LLMError as e:
            if e.detiene_todo:
                raise
            self.ui.aviso(f"  explorador: el modelo no respondió ({recortar(str(e), 180)}). Sigo con el mapa local.")
            return mapa or "(exploración no disponible: el modelo no respondió)"
        informe = "\n\n".join(
            f"### Informe explorador {i}\n{r.resumen}" for i, r in enumerate(resultados, start=1)
        )
        return (mapa + "\n\n" + informe) if mapa else informe

    def planificar(self, pedido: str, exploracion: str, feedback: str = "", anterior: Optional[Plan] = None) -> Plan:
        detectado = detectar_comando_tests(self.ws)
        tarea = (
            f"PEDIDO DEL USUARIO:\n{pedido}\n\n"
            f"INFORME DE EXPLORACIÓN (código real):\n{recortar(exploracion, 7000)}\n\n"
            f"Comando de tests detectado: {detectado[0] if detectado else 'ninguno (habrá que crear tests)'}\n"
            f"Usá TANTAS tareas como el proyecto realmente necesite, hasta un máximo de {self.settings.max_tareas}. "
            f"Un proyecto chico lleva pocas; uno grande se descompone por módulo/capa: UNA tarea por pieza coherente "
            f"(un módulo, una pantalla, un endpoint, su test), con sus dependencias en deps= para que se ordenen bien. "
            f"No metas medio proyecto en una sola tarea gigante ni inventes tareas de relleno."
        )
        if self.settings.tests_primero:
            tarea += ("\nLos tests se escriben ANTES de implementar a partir de tu <interfaz> y tus <criterios>: "
                      "que sean precisos (rutas, nombres, firmas, valores esperados).")
        if anterior and feedback:
            tarea += (
                f"\n\nPLAN ANTERIOR:\n{anterior.como_texto()}\n\n"
                f"EL USUARIO PIDIÓ ESTOS CAMBIOS AL PLAN:\n{feedback}"
            )
        res = self._sub("arquitecto", tarea, None, titulo="diseña el plan de tareas")
        texto = res.resumen
        if not _RE_TAREA.search(texto) and _RE_TAREA.search(res.contexto):
            texto = res.contexto + "\n" + texto
        plan = parsear_plan(texto, pedido, self.settings.max_tareas)
        crudas = len(_RE_TAREA.findall(texto))
        if crudas > self.settings.max_tareas:
            self.ui.aviso(f"  El plan traía {crudas} tareas y el tope es {self.settings.max_tareas}: agrupé el resto "
                          f"en la última. Para un proyecto grande usá /grande (por etapas verificadas) o subí el tope: "
                          f"/config max_tareas {min(60, crudas)}")
        if not res.ok:
            self.ui.aviso("El arquitecto no terminó limpio; uso lo que produjo.")
        motivo = plan_degenerado(plan, pedido, texto)
        if motivo:
            # Un plan de UNA tarea gigante hace que un modelo de 24B se pierda (y que el revisor apruebe
            # cualquier cosa): se pide de nuevo, y si sigue igual se divide por archivo de la interfaz.
            self.ui.aviso(f"  Plan inútil ({motivo}): se lo pido de nuevo dividido en tareas chicas.")
            tarea2 = (tarea + f"\n\nTU PLAN ANTERIOR NO SIRVE: {motivo}. Rehacelo con entre 3 y "
                      f"{self.settings.max_tareas} tareas chicas, ordenadas por dependencia, cada una con "
                      "<tarea id=\"N\" archivos=\"...\"> y como mucho 1-2 archivos. Usá EXACTAMENTE el formato <plan>.")
            res2 = self._sub("arquitecto", tarea2, None, titulo="rehace el plan en tareas chicas")
            texto2 = res2.resumen
            if not _RE_TAREA.search(texto2) and _RE_TAREA.search(res2.contexto):
                texto2 = res2.contexto + "\n" + texto2
            plan2 = parsear_plan(texto2, pedido, self.settings.max_tareas)
            if not plan_degenerado(plan2, pedido, texto2):
                return plan2
            if not plan2.interfaz and plan.interfaz:
                plan2.interfaz = plan.interfaz
            dividido = dividir_por_interfaz(plan2)
            if len(dividido.tareas) > 1:
                self.ui.aviso(f"  El arquitecto insistió con una sola tarea: la divido por archivo ({len(dividido.tareas)} tareas).")
                return dividido
            return plan2
        return plan

    def especificar(self, pedido: str, plan: Plan, cid: int) -> dict[str, Optional[str]]:
        """Tests primero: el especificador escribe la especificación ejecutable. Devuelve {rel: contenido}."""
        detectado = detectar_comando_tests(self.ws)
        criterios = "\n".join(f"- {c}" for c in plan.criterios) or "- (derivalos del pedido y la interfaz)"
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"PLAN:\n{plan.como_texto()}\n\n"
            f"INTERFAZ QUE TUS TESTS DEBEN USAR:\n{plan.interfaz or '(no hay interfaz explícita: usá las firmas de las tareas)'}\n\n"
            f"CRITERIOS DE ACEPTACIÓN:\n{criterios}\n\n"
            f"Comando de tests detectado: {detectado[0] if detectado else 'ninguno todavía (creá la carpeta tests/)'}\n\n"
            "Escribí los tests de aceptación AHORA, antes de que exista la implementación. Tienen que fallar por "
            "falta de implementación (ImportError/AttributeError/assert) y pasar cuando el plan esté hecho."
        )
        res = self._sub("especificador", texto, cid, titulo="escribe los tests ANTES de implementar")
        # También cuentan los tests que esta MISMA build ya había escrito antes de un corte (cupo diario, Ctrl+C): al
        # retomar, el especificador los encuentra hechos y no los reescribe; sin esto se descartaba la especificación.
        escritos = sorted(set(res.cambios) | set(self.ws.checkpoints.archivos_desde(cid)))
        tests = [r for r in escritos if _es_test(r) and (self.ws.raiz / r).is_file()]
        if not tests:
            self.ui.aviso("  El especificador no dejó archivos de test: sigo sin especificación ejecutable.")
            return {}
        validacion = validar_archivos(self.ws, tests)
        rotos = tests_de_especificacion_rotos(validacion)
        if rotos:
            # Prueba real en el teléfono: el test hacía `from almacen import __main__` y llamaba `main(...)` sin
            # importarlo (NameError). Solo se rechazaba la sintaxis: el test roto quedó PROTEGIDO, nadie pudo
            # corregirlo y el reparador pasó horas inyectando `main` en el módulo del test con sys._getframe.
            self.ui.aviso("  Los tests de la especificación están rotos (sintaxis o nombres sin importar): le pido al "
                          "especificador que los arregle.")
            self._sub("especificador",
                      "Tus tests tienen errores PROPIOS (no son el rojo esperado):\n" + resumen_validacion(rotos, 2500)
                      + "\n\nUn nombre indefinido (p. ej. llamar `main(...)` sin `from paquete.modulo import main`) es "
                      "un error del test. Que falle porque el MÓDULO todavía no existe está bien; usar un nombre que "
                      "nunca importaste, no. Corregí SOLO eso en los tests (agregá los imports que faltan).",
                      cid, titulo="corrige los tests")
            siguen = {r.archivo for r in tests_de_especificacion_rotos(validar_archivos(self.ws, tests))}
            if siguen:
                # No se protegen: así el implementador o el reparador pueden corregirlos (protegidos, no podía nadie).
                self.ui.aviso("  Siguen rotos " + ", ".join(sorted(siguen)) + ": no los protejo (los puede corregir "
                              "el implementador).")
                tests = [t for t in tests if t not in siguen]
                self._marcar_spec_rotos(siguen)              # sin proteger, pero la tarea igual los tiene que pasar
                if not tests:
                    return {}
        acoplados = {}
        for rel in tests:
            if rel.endswith(".py"):
                try:
                    hallazgos = acoples_a_la_implementacion(self.ws.leer(rel))
                except (OSError, ValueError, ErrorRuta):
                    hallazgos = []
                if hallazgos:
                    acoplados[rel] = hallazgos
        if acoplados:
            # Una sola vez (sin quemar pedidos): si el modelo insiste, siguen en disco pero SIN proteger (abajo).
            self.ui.aviso("  Tests de la especificación acoplados a la implementación (mockean la base o exigen el SQL "
                          "exacto): le pido al especificador que los reescriba con una base real.")
            detalle = "\n".join(f"{rel}:\n" + "\n".join(f"  - {h}" for h in hs) for rel, hs in acoplados.items())
            self._sub("especificador",
                      "Estos tests prueban CÓMO está hecho el código, no QUÉ hace: cualquier implementación correcta "
                      "pero distinta los rompe.\n" + detalle + "\n\nReescribilos con una base sqlite REAL temporal "
                      "(sqlite3 ':memory:' o un archivo en tempfile) cargada con datos de prueba, llamando a las "
                      "funciones públicas de la INTERFAZ y verificando el RESULTADO. Sin mocks de la conexión y sin "
                      "afirmar SQL.", cid, titulo="reescribe los tests acoplados")
            tests = sorted(set(tests) | {x for x in self.ws.checkpoints.archivos_desde(cid)
                                         if _es_test(x) and (self.ws.raiz / x).is_file()})
            rotos_ahora = {r.archivo for r in tests_de_especificacion_rotos(validar_archivos(self.ws, tests))}
            if rotos_ahora:
                # La reescritura no puede dejar protegido un test roto.
                self.ui.aviso("  La reescritura dejó tests rotos (" + ", ".join(sorted(rotos_ahora)) + "): no los protejo.")
                self._marcar_spec_rotos(rotos_ahora)
                tests = [t for t in tests if t not in rotos_ahora]
                if not tests:
                    return {}
            siguen_acoplados = set()
            for rel in tests:
                try:
                    if rel.endswith(".py") and acoples_a_la_implementacion(self.ws.leer(rel)):
                        siguen_acoplados.add(rel)
                except (OSError, ValueError, ErrorRuta):
                    continue
            if siguen_acoplados:
                # La especificación nunca bloquea: si después del pedido siguen acoplados, NO se protegen (el
                # implementador puede reescribirlos), pero la tarea igual tiene que dejarlos en verde.
                self.ui.aviso("  Siguen acoplados a la implementación (" + ", ".join(sorted(siguen_acoplados))
                              + "): no los protejo (el implementador los puede corregir).")
                self._marcar_spec_rotos(siguen_acoplados)
                tests = [t for t in tests if t not in siguen_acoplados]
                if not tests:
                    return {}
        r = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        conteo = conteo_de_resultado(r)
        codigo_plan = [a for a in plan.archivos() if not _es_test(a)]
        proyecto_nuevo = bool(codigo_plan) and not any(self.ws.existe(a) for a in codigo_plan)
        # Los tests que YA pasaban antes de la build (etapas anteriores de /grande, el proyecto existente) no son de
        # esta especificación: la corrida E2E de /grande acusaba al especificador en cada etapa desde la 2 ("3 tests
        # YA pasan sin el código" = los de la etapa 1) y le hacía reescribir tests buenos.
        base = getattr(self, "_base_tests", None)
        conteo_base = conteo_de_resultado(base) if base is not None else None
        ya_pasaban = conteo_base.pasados if conteo_base is not None and conteo_base.reconocido else 0
        pasan_sin_codigo = max(0, conteo.pasados - ya_pasaban)
        if r is not None and conteo.reconocido and pasan_sin_codigo and not conteo.ok and proyecto_nuevo:
            # Prueba real con OpenRouter: 3 tests "de error" pasaban SIN que existiera el código (solo miraban
            # returncode != 0 y stderr no vacío; "No module named conversor" también cumple). Después darían verde
            # aunque el CLI se rompiera por cualquier otra cosa. En un proyecto nuevo, un test que ya pasa no prueba nada.
            self.ui.aviso(f"  {pasan_sin_codigo} test(s) de la especificación YA pasan sin que exista el código: no "
                          "prueban la función. Le pido al especificador que los ajuste.")
            self._sub("especificador",
                      f"{pasan_sin_codigo} de tus tests YA PASAN y la implementación todavía no existe "
                      f"({conteo.texto()}): esos tests no prueban nada. Un test de aceptación tiene que FALLAR ahora. "
                      "Típico: un test de error que solo mira returncode != 0 o stderr no vacío también pasa si el "
                      "módulo ni existe. Comprobá el error CONCRETO (el tipo, p. ej. 'ValueError' en stderr, o el "
                      "mensaje pedido). Corregí SOLO esos tests y corré run_tests.", cid,
                      titulo="ajusta los tests que pasan sin implementación")
            r = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
            conteo = conteo_de_resultado(r)
            tests = sorted(set(tests) | {x for x in self.ws.checkpoints.archivos_desde(cid)
                                          if _es_test(x) and (self.ws.raiz / x).is_file()})
        if r is not None and conteo.reconocido:
            if conteo.ok and conteo.pasados:
                self.ui.aviso(f"  Ojo: la especificación ya pasa entera ({conteo.texto()}); quizá la función ya existía.")
            else:
                previos = f"; {ya_pasaban} ya pasaban de antes" if ya_pasaban else ""
                self.ui.ok(f"especificación lista: {len(tests)} archivo(s) de test, {conteo.texto()}{previos} "
                           "(esperado: fallan los nuevos)")
        else:
            self.ui.ok(f"especificación lista: {len(tests)} archivo(s) de test")
        return copiar_contenidos(self.ws, tests)

    def _texto_tarea(self, pedido: str, plan: Plan, indice: int, exploracion: str,
                     protegidos: dict[str, Optional[str]], correcciones: str = "") -> str:
        tarea = plan.tareas[indice]
        texto = (
            f"PEDIDO ORIGINAL DEL USUARIO:\n{pedido}\n\n"
            f"PLAN GENERAL:\n{plan.como_texto(actual=indice, hechas=indice)}\n\n"
            f"TU TAREA AHORA (#{tarea.id}):\n{tarea.descripcion}\n\n"
            f"CONTEXTO DE EXPLORACIÓN:\n{recortar(exploracion, 3500)}\n\n"
            "Implementá SOLO esta tarea (las demás las hacen otros). Leé antes de editar."
        )
        if protegidos:
            texto += ("\n\nTESTS DE ESPECIFICACIÓN (escritos antes de implementar; NO los modifiques, hacé que pasen "
                      "los que corresponden a tu tarea): " + ", ".join(protegidos))
        if correcciones:
            texto += (
                "\n\nUN REVISOR YA REVISÓ TU TRABAJO EN ESTA TAREA Y PIDIÓ CAMBIOS. Aplicalos (si alguno es "
                f"incorrecto, explicá por qué en el informe):\n{recortar(correcciones, 4000)}"
            )
        return texto

    def implementar(self, pedido: str, plan: Plan, indice: int, exploracion: str,
                    cid: int, correcciones: str = "", protegidos: Optional[dict] = None) -> ResultadoTorneo:
        protegidos = protegidos or {}
        tarea = plan.tareas[indice]
        texto = self._texto_tarea(pedido, plan, indice, exploracion, protegidos, correcciones)
        titulo = f"tarea {tarea.id}: {recortar(tarea.descripcion.splitlines()[0], 90)}"
        if correcciones:
            titulo = f"corrige tarea {tarea.id} según el revisor"
        usar_torneo = self.settings.torneo and self.settings.candidatos > 1 and not correcciones
        torneo = Torneo(self.llm, self.ws, self.settings, self.ui, memoria=self.memoria,
                        on_atascado=self.escalador.gancho(self.ws, texto))
        return torneo.correr(texto, archivos=", ".join(tarea.archivos), titulo=titulo,
                             n=self.settings.candidatos if usar_torneo else 1, protegidos=protegidos, cid=cid)

    def revisar(self, pedido: str, tarea: Tarea, diff: str, cid: int, tests_reales: str = "") -> tuple[bool, str]:
        rels = self.ws.checkpoints.archivos_desde(cid)
        validacion = resumen_validacion(validar_archivos(self.ws, rels), limite=1500)
        # El revisor es de solo lectura: sin el resultado real de los tests intentaba correrlos él mismo
        # (logs reales: 15 pedidos de execute_command rechazados = turnos de modelo perdidos).
        evidencia = (f"Tests reales (ya los corrió REAPER, no hace falta ejecutarlos): {tests_reales}\n\n"
                     if tests_reales else "")
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"TAREA REVISADA (#{tarea.id}):\n{tarea.descripcion}\n\n"
            f"DIFF REAL DE LOS CAMBIOS:\n```diff\n{recortar(diff, 12000)}\n```\n\n"
            f"Validación automática de los archivos cambiados: {validacion}\n\n"
            f"{evidencia}"
            "Leé los archivos completos si necesitás contexto. Empezá tu informe con la línea VEREDICTO."
        )
        res = self._sub_opcional("revisor", texto, cid, titulo=f"revisa el diff de la tarea {tarea.id}")
        if res is None:                      # revisor caído: decide la validación real, no un modelo ausente
            if validacion and not validacion.startswith(("OK", "sin validadores")):
                return False, ("VEREDICTO: CAMBIOS\n1. La validación automática falla (corregilo antes que nada):\n"
                               + validacion)
            return True, "(revisión omitida: el revisor no respondió; la validación real pasa)"
        aprobado, claro = veredicto(res.resumen)
        if not claro:
            if observaciones_concretas(res.resumen):
                # Sin la línea VEREDICTO pero con puntos concretos ("1. falta validar…"): se pasan tal cual.
                self.ui.aviso("  Revisión sin la línea VEREDICTO, pero con observaciones concretas: las paso como CAMBIOS.")
                return False, "VEREDICTO: CAMBIOS\n" + res.resumen
            self.ui.aviso("  Revisión SIN VEREDICTO: no se considera aprobada; la verificación real decidirá el resultado.")
            return False, REVISION_SIN_DICTAMEN
        if aprobado and validacion and not validacion.startswith(("OK", "sin validadores")):
            self.ui.aviso("  El revisor aprobó, pero la validación real falla: lo tomo como CAMBIOS.")
            return False, ("VEREDICTO: CAMBIOS\n1. La validación automática falla (corregilo antes que nada):\n"
                           + validacion + "\n\n" + res.resumen)
        return aprobado, res.resumen

    def qa(self, pedido: str, plan: Plan, archivos: list, cid: int) -> Optional[ResultadoAgente]:
        detectado = detectar_comando_tests(self.ws)
        criterios = "\n".join(f"- {c}" for c in plan.criterios) or "- (derivalos del pedido)"
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"CRITERIOS DE ACEPTACIÓN:\n{criterios}\n\n"
            f"ARCHIVOS CAMBIADOS EN ESTA BUILD: {', '.join(archivos)}\n"
            f"Comando de tests detectado: {detectado[0] if detectado else 'ninguno todavía'}\n\n"
            "Escribí (o completá) tests automáticos que verifiquen los criterios y corrélos con run_tests. "
            "Reportá el resultado REAL."
        )
        return self._sub_opcional("qa", texto, cid, titulo="escribe y corre tests de aceptación")

    def _custodiar_protegidos(self) -> None:
        """Los tests protegidos se custodian EN DISCO, no solo en las herramientas de escritura: el reparador de la
        prueba real los pisaba con `cp tests/test_cli.py.backup tests/test_cli.py` (execute_command). Si solo se les
        agregaron imports (lo único permitido), se acepta y se actualiza el diario; cualquier otro cambio se revierte."""
        for rel, original in list(getattr(self, "_protegidos", {}).items()):
            if original is None:
                continue
            try:
                actual = self.ws.leer(rel)
            except (OSError, ValueError, ErrorRuta):
                actual = None
            if actual == original:
                continue
            if solo_agrega_imports(original, actual):
                self._protegidos[rel] = actual
                diario = getattr(self, "_diario_build", None)
                if diario is not None:
                    registro, previo = diario
                    previo.setdefault("tests_protegidos", {})[rel] = self.ws.hash(rel)
                    registro.guardar(previo)
                self.ui.tenue(f"  {rel}: se le agregaron imports al test protegido (permitido: no cambia lo que prueba).")
                continue
            try:
                self.ws.escribir(rel, original)
            except (OSError, ErrorRuta) as e:
                self.ui.error(f"  {rel} es un test protegido, cambió y no lo pude restaurar: {e}")
                continue
            self.ui.aviso(f"  {rel} es un test protegido y se cambió por fuera de lo permitido: lo restauré.")

    def verificar(self, cid: int) -> Verificacion:
        self._custodiar_protegidos()
        archivos = [r for r in self.ws.checkpoints.archivos_desde(cid) if (self.ws.raiz / r).is_file()]
        validaciones = validar_archivos(self.ws, archivos)
        tests = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        conteo = conteo_de_resultado(tests)
        malos = fallos(validaciones)
        tests_ok = tests is None or tests.ok
        partes = [r.resumen(2500) for r in malos]
        if tests is not None and tests.omitido:
            # Hay archivos de test (si no, no habría comando) pero la suite no recolectó NINGUNO: 0 tests no es éxito.
            tests_ok = False
            partes.append("TESTS: hay archivos de test pero la suite no recolectó ningún test "
                          "(funciones sin prefijo test_, clases que no heredan de TestCase o archivos vacíos).")
        elif tests is not None and not tests.ok:
            partes.append("TESTS: " + conteo.texto() + "\n" + fallos_relevantes(f"{tests.stdout}\n{tests.stderr}",
                                                                                maximo=3, limite=5000))
        elif tests is not None and conteo.reconocido and conteo.ejecutados == 0 and conteo.omitidos > 0:
            # Exit 0 con TODO salteado (skip/xfail): 0 tests ejecutados no verifican nada (antes daba "verificada").
            tests_ok = False
            partes.append(f"TESTS: todos los tests fueron OMITIDOS ({conteo.texto()}): 0 ejecutados no prueban "
                          "nada. Quitá los @skip / xfail o implementá lo que falta para que corran de verdad.")
        # Evaluador externo, colocado FUERA del directorio editable del proyecto.
        # Si falla, no se puede declarar la build verificada aunque el LLM diga que terminó.
        aceptacion = ejecutar_aceptacion_independiente(
            self.ws, huella_fijada=self._huella_aceptacion)
        aceptacion_ok = aceptacion is None or aceptacion.ok
        if not aceptacion_ok:
            partes.append('PRUEBAS DE ACEPTACIÓN INDEPENDIENTES:\n'
                          + aceptacion.resumen(4500))
        # ¿Arranca? Que los tests pasen no prueba que `python -m paquete` cargue: si se cae al importar, está roto.
        arranque = verificar_arranque(self.ws) if getattr(self.settings, "verificar_arranque", True) else []
        partes.extend(arranque)
        debilitados = self._tests_debilitados()
        partes.extend(debilitados)
        diagnostico = "\n\n".join(partes)
        if diagnostico and self.settings.pistas_errores:
            diagnostico = anexar_pistas(diagnostico, 3)
        return Verificacion(not malos and tests_ok and aceptacion_ok and not arranque and not debilitados, validaciones,
                            tests, diagnostico, archivos, conteo, aceptacion)

    def reparar(self, pedido: str, verif: Verificacion, cid: int, base_fallaba: bool,
                diagnostico_experto: str = "", contexto: str = "") -> ResultadoAgente:
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"Hay fallos REALES. Diagnóstico de validadores/tests:\n{verif.diagnostico}\n\n"
            f"Archivos cambiados en esta build: {', '.join(verif.archivos)}\n"
        )
        if contexto:
            texto += f"\n{contexto}\n"
        if base_fallaba:
            texto += "Ojo: la suite de tests ya fallaba ANTES de esta build; priorizá los fallos causados por los cambios.\n"
        texto += "Encontrá la causa raíz y corregila. No debilites ni borres tests."
        en_protegidos = sorted(rel for rel in self._protegidos if rel in (verif.diagnostico or ""))
        if en_protegidos:
            # Sin esto, el reparador de la prueba real "arreglaba" un test protegido que llamaba main() sin importarlo
            # inyectando main en el módulo del test con sys._getframe (una trampa) durante horas.
            texto += ("\n\nEl fallo está en un test PROTEGIDO de la especificación (" + ", ".join(en_protegidos) + "). "
                      "No podés cambiar lo que prueba, pero SÍ podés AGREGARLE las líneas import/from que le falten "
                      "(p. ej. `from paquete.modulo import main`): es lo único permitido en ese archivo. Nunca hagas "
                      "trampas en el código (inyectar nombres en el módulo del test, sys._getframe, builtins).")
        if diagnostico_experto:
            texto = tarea_con_diagnostico(texto, diagnostico_experto)
        protegidos = set(self._protegidos)
        return self._sub(getattr(self, "_rol_reparacion", "reparador"), texto, cid,
                         titulo="arregla los fallos reales" + (" (con diagnóstico experto)"
                                                                                    if diagnostico_experto else ""),
                         protegidos=protegidos)

    # ------------------------------------------------------------ lecciones
    def _aprender(self, diagnostico: str, cid: int, informe_reparador: str, build: InformeBuild) -> None:
        if not self.memoria or not self.settings.lecciones:
            return
        diff = self.ws.checkpoints.diff_desde(cid)
        if not diff.strip():
            return
        proyecto, general = extraer_lecciones(self.llm, self.settings.modelo_para("reparador"), diagnostico, diff,
                                              informe_reparador, self.ws)
        hechos = self.memoria.registrar(proyecto, general)
        for h in hechos:
            self.ui.linea(f"  {Tema.acento}📚 lección{C.RESET} {Tema.tenue}{h}{C.RESET}")
        build.lecciones.extend(hechos)

    def _reparar_con_escalada(self, pedido: str, verif: Verificacion, grupo: int, base_fallaba: bool,
                              informe: InformeBuild, etiqueta: str, max_intentos: int,
                              verificador: Callable[[], Verificacion], contexto: str = "") -> Verificacion:
        """Bucle de reparación: reparador → re-verificar; al repetirse el fallo, escala al modelo fuerte."""
        diagnosticos_vistos: list[str] = []
        fallos_seguidos = 0
        intento = 0
        intentos_txt: list[str] = []
        forense_hecho = False
        informe_forense = ""
        sin_cambios = 0
        # Intentos que no sirvieron (no cambiaron nada, la guardia los revirtió o dejaron el MISMO error). En el
        # teléfono un reparador giraba en vacío horas: 2 seguidos cortan, con el motivo a la vista.
        inutiles: list[str] = []
        liberacion_hecha = False
        experto_usado = False
        while not verif.ok:
            sin_avance = len(inutiles) >= 2 or sin_cambios >= 2
            if intento >= max_intentos and (liberacion_hecha or not sin_avance):
                break                       # sin intentos: solo hay UNO más si abajo se libera la especificación
            vencido = PLAZO.vencido()
            if vencido:
                informe.notas.append(f"{etiqueta}: se agotó el tiempo de {vencido}; quedan fallos sin reparar.")
                self.ui.aviso(f"  ⏱ {etiqueta}: se agotó el tiempo de {vencido}; no sigo reparando.")
                break
            liberados = []
            if sin_avance and not liberacion_hecha:
                # Antes de rendirse: ¿lo que bloquea es un test de la especificación que está roto o acoplado a la
                # implementación? Protegido, nadie lo podía corregir (prueba real). Se libera UNA vez; con 2 intentos
                # por tarea (umbral_escalada=1) la liberación caía justo después del último y no servía de nada.
                liberacion_hecha = True
                liberados = self._liberar_especificacion_mala(verif, informe)
                if liberados:
                    inutiles.clear()
                    sin_cambios = 0
                    diagnosticos_vistos.clear()
                    contexto = (contexto + "\n\nLIBERADOS: " + ", ".join(liberados) + " tenían problemas propios (rotos "
                                "o acoplados a la implementación). Ahora podés corregirlos para que prueben el "
                                "COMPORTAMIENTO pedido, sin debilitarlos.").strip()
            if intento >= max_intentos and not liberados:
                break
            if len(inutiles) >= 2 or sin_cambios >= 2:
                if not experto_usado and self.escalador.disponible():
                    # Última carta antes de cortar: UN intento con el diagnóstico del modelo fuerte.
                    fallos_seguidos = max(fallos_seguidos, self.settings.umbral_escalada)
                else:
                    motivo = "; ".join(inutiles[-2:]) or "sin cambios reales"
                    informe.notas.append(f"{etiqueta}: la reparación no avanzó en 2 intentos seguidos ({motivo}).")
                    self.ui.aviso(f"  {etiqueta}: 2 intentos sin avance ({motivo}); corto la reparación.")
                    break
            firma = _firma_error(verif.diagnostico)
            if diagnosticos_vistos.count(firma) >= 3:
                informe.notas.append(f"{etiqueta}: la reparación no logró avances (mismo diagnóstico repetido).")
                break
            diagnosticos_vistos.append(firma)
            intento += 1
            experto = ""
            if fallos_seguidos >= self.settings.umbral_escalada and self.escalador.disponible():
                experto_usado = True
                experto = self.escalador.diagnosticar(self.ws, pedido, verif.diagnostico, verif.archivos,
                                                      "\n---\n".join(intentos_txt[-2:])) or ""
                if experto:
                    informe.escaladas += 1
                    fallos_seguidos = 0
            if (fallos_seguidos >= 1 and not forense_hecho and self.settings.forense
                    and verif.tests is not None and not verif.tests.ok
                    and not diagnostico_obvio(verif.diagnostico)):
                # el primer intento no alcanzó: antes de seguir probando, investigar con método
                forense_hecho = True
                try:
                    informe_forense = investigar(
                        self.ws, self.settings, self.ui, self.llm, fallidos=verif.conteo.nombres_fallados,
                        contexto=verif.diagnostico,
                        modelo=self.escalador.modelo if self.escalador.disponible() else None).texto()
                    informe.notas.append(f"{etiqueta}: se usó el modo forense")
                except (OSError, ValueError, LLMError) as e:
                    self.ui.aviso(f"  el modo forense falló: {e}")
            self.ui.titulo(f"REPARACIÓN {etiqueta} {intento}/{max_intentos}" + (" · con experto" if experto else "")
                           + (" · con informe forense" if informe_forense else ""))
            rcid = self.ws.checkpoints.iniciar(f"reparación {etiqueta} {intento}", grupo=grupo)
            antes = verif
            contexto_intento = contexto + (f"\n\n{informe_forense}" if informe_forense else "")
            if intentos_txt:
                contexto_intento += ("\n\nINTENTOS ANTERIORES QUE NO FUNCIONARON (no los repitas; entendé por qué fallaron):\n"
                                     + "\n---\n".join(intentos_txt[-2:]))
            try:
                res = self.reparar(pedido, verif, rcid, base_fallaba, experto, contexto_intento.strip())
            except LLMError as e:
                if e.detiene_todo:
                    raise
                # Prueba real (teléfono): se agotó el tiempo de la tarea 2 en medio de un reintento (Nvidia 500) y el
                # error subió como "el modelo no responde": /grande se DETENÍA entero. Es el fin de ESTA reparación:
                # la tarea queda con sus fallos, la build sigue y /grande la retoma con tiempo nuevo.
                motivo = _primera_linea_util(str(e))
                informe.notas.append(f"{etiqueta}: el reparador no pudo terminar ({recortar(motivo, 200)}).")
                self.ui.aviso(f"  {etiqueta}: el reparador no pudo terminar ({recortar(motivo, 160)}); dejo la "
                              "reparación acá.")
                break
            diff_intento = self.ws.checkpoints.diff_desde(rcid)
            sin_cambios = 0 if diff_intento.strip() else sin_cambios + 1
            verif = verificador()
            self._mostrar_verificacion(verif)
            # Lo que el próximo intento tiene que saber: QUÉ cambió este (el diff, no solo su relato) y en qué terminó.
            resultado_txt = (verif.conteo.texto() if verif.conteo.reconocido
                             else _primera_linea_util(verif.diagnostico) or "sin cambios en la verificación")
            intentos_txt.append(recortar(res.resumen, 600)
                                + (f"\nLo que cambió:\n```diff\n{recortar(diff_intento, 1500)}\n```" if diff_intento.strip()
                                   else "\n(No cambió ningún archivo.)")
                                + f"\nResultado: {resultado_txt}")
            if verif.ok:
                self._aprender(antes.diagnostico, rcid, res.resumen, informe)
                continue
            fallos_seguidos += 1
            if not diff_intento.strip():
                inutiles.append(f"intento {intento}: no cambió ningún archivo")
            elif _firma_error(verif.diagnostico) == firma and not verificacion_mejor(verif, antes):
                inutiles.append(f"intento {intento}: el mismo error sigue igual")
            elif not (self.settings.guardia_regresion and verificacion_peor(verif, antes)):
                inutiles.clear()
            if self.settings.guardia_regresion and verificacion_peor(verif, antes):
                # el intento EMPEORÓ las cosas (2 fallos → 13): se revierte entero y se sigue desde lo que había
                revertidos = self.ws.checkpoints.deshacer(rcid)
                self.ui.aviso(f"  ⟲ el intento {intento} empeoró la verificación ({antes.conteo.texto()} → "
                              f"{verif.conteo.texto()}): lo revierto ({', '.join(revertidos[:5]) or 'sin archivos'})")
                informe.notas.append(f"{etiqueta}: se revirtió el intento {intento} porque empeoró los tests")
                intentos_txt[-1] += (f"\n(ESTE INTENTO EMPEORÓ LOS TESTS de {antes.conteo.texto()} a "
                                     f"{verif.conteo.texto()} y se revirtió: no lo repitas)")
                if not inutiles or not inutiles[-1].startswith(f"intento {intento}:"):
                    inutiles.append(f"intento {intento}: empeoró los tests y se revirtió")
                verif = antes
        return verif

    def _marcar_spec_rotos(self, rels) -> None:
        """Tests de la especificación SIN proteger (rotos o acoplados): la tarea igual los tiene que dejar en verde, y
        se anota cuántos tests tenían para que nadie los "arregle" vaciándolos (ver _tests_debilitados)."""
        self._spec_rotos = sorted(set(getattr(self, "_spec_rotos", [])) | set(rels))
        minimos = self.__dict__.setdefault("_minimo_tests", {})
        for rel in rels:
            if not rel.endswith(".py") or rel in minimos:
                continue
            try:
                minimos[rel] = len(analizar_tests_python(self.ws.leer(rel)).tests)
            except (OSError, ValueError, ErrorRuta):
                continue

    def _tests_debilitados(self) -> list[str]:
        """Un test liberado se corrige para que pruebe el COMPORTAMIENTO; vaciarlo (borrar tests, dejarlos sin assert)
        no cuenta como arreglo, aunque la suite quede en verde."""
        problemas = []
        for rel, minimo in sorted(getattr(self, "_minimo_tests", {}).items()):
            if not (self.ws.raiz / rel).is_file():
                problemas.append(f"TEST DEBILITADO ({rel}): se borró un test de la especificación.")
                continue
            try:
                hallazgos = debilitamiento_de_test(self.ws.leer(rel), minimo)
            except (OSError, ValueError, ErrorRuta):
                continue
            if hallazgos:
                problemas.append(f"TEST DEBILITADO ({rel}): " + "; ".join(hallazgos) + ". Es un test de la "
                                 "especificación que se liberó para CORREGIRLO (que pruebe el comportamiento pedido con "
                                 "datos reales), no para vaciarlo: mantené todos sus casos con asserts que verifiquen "
                                 "resultados.")
        return problemas

    def _liberar_especificacion_mala(self, verif: Verificacion, informe: InformeBuild) -> list:
        """Tests de la especificación de ESTA build que están protegidos, participan del fallo y tienen problemas
        propios (rotos o acoplados a la implementación): se desprotegen para que se puedan corregir. La tarea igual
        los tiene que dejar en verde (pasan a _spec_rotos). Los tests que ya existían antes de la build no se tocan."""
        spec = set(informe.spec_tests or [])
        if not spec:
            return []
        fallados = list(verif.conteo.nombres_fallados) if verif.conteo.reconocido else []
        liberados = []
        for rel in sorted(spec & set(getattr(self, "_protegidos", {}))):
            participa = rel in (verif.diagnostico or "") or any(_es_de_especificacion(n, {rel: None}) for n in fallados)
            if not participa or not (self.ws.raiz / rel).is_file():
                continue
            try:
                texto = self.ws.leer(rel)
            except (OSError, ValueError, ErrorRuta):
                continue
            malo = (rel.endswith(".py") and acoples_a_la_implementacion(texto)) or \
                tests_de_especificacion_rotos(validar_archivos(self.ws, [rel]))
            if not malo:
                continue
            self._protegidos.pop(rel, None)
            liberados.append(rel)
        if liberados:
            self._marcar_spec_rotos(liberados)
            diario = getattr(self, "_diario_build", None)
            if diario is not None:
                registro, previo = diario
                for rel in liberados:
                    previo.setdefault("tests_protegidos", {}).pop(rel, None)
                previo["spec_rotos"] = list(self._spec_rotos)
                previo["minimo_tests"] = dict(self._minimo_tests)
                registro.guardar(previo)
            self.ui.aviso("  La reparación no avanza y el bloqueo es la especificación (" + ", ".join(liberados)
                          + ": rota o acoplada a la implementación). La libero para que se pueda corregir.")
            informe.notas.append("Se liberaron tests de la especificación con problemas propios: "
                                 + ", ".join(liberados))
        return liberados

    # ------------------------------------------------------------ REAPER X (10 roles)
    def _consultar_rol_x(self, rol: str, prompt: str, max_tokens: int = 1500) -> tuple:
        """
        Rol de dirección/auditoría por TEXTO (sin herramientas): devuelve (texto|None, modelo_pedido, modelo_servido).
        Si respondió otro modelo (respaldo del equipo), se declara: nada de degradación silenciosa.
        """
        pedido_modelo = self.settings.modelo_para(rol)
        mensajes = [{"role": "system", "content": f"# TU ROL: {rol.upper()}\n{ROLES[rol].mision}"},
                    {"role": "user", "content": prompt}]
        try:
            resp = self.llm.chat(mensajes, modelo=pedido_modelo, temperatura=ROLES[rol].temperatura,
                                 max_tokens=max_tokens, rol=rol)
        except LLMError as e:
            if e.detiene_todo:
                raise
            self.ui.aviso(f"  {rol}: el modelo no respondió ({recortar(str(e), 160)}); sigo sin su dictamen.")
            return None, pedido_modelo, "unknown"
        if rol == "juez":
            # Contabilidad del juez: así se puede mostrar que es el que menos gasta.
            self._tokens_juez = getattr(self, "_tokens_juez", 0) + tokens_mensajes(mensajes) + int(
                getattr(resp, "tokens_salida", 0) or estimar_tokens(str(getattr(resp, "texto", "") or "")))
        servido = str(getattr(resp, "modelo", "") or "unknown")
        if servido not in ("unknown", "mock", pedido_modelo) and resolver_modelo(servido) != resolver_modelo(pedido_modelo):
            self.ui.tenue(f"  {rol}: pedido {pedido_modelo} → respondió {servido} (respaldo del equipo)")
        return resp.texto, pedido_modelo, servido

    def _directiva_director(self, pedido: str) -> str:
        texto, _p, _s = self._consultar_rol_x("director", f"PEDIDO DEL USUARIO:\n{pedido}")
        datos = extraer_json_x(texto or "")
        if not datos or not str(datos.get("mission", "")).strip():
            if texto is not None:
                self.ui.aviso("  director: respuesta fuera de contrato (no es el JSON pedido); sigo sin directiva.")
            return ""
        criterios = _lista_str(datos.get("acceptance_criteria"))
        prioridades = _lista_str(datos.get("priorities"))
        self.ui.info(f"  director: {recortar(str(datos['mission']), 160)}")
        partes = [f"DIRECTIVA DEL DIRECTOR: {str(datos['mission']).strip()}"]
        if prioridades:
            partes.append("Prioridades: " + "; ".join(prioridades[:8]))
        if criterios:
            partes.append("Criterios de aceptación pedidos:\n" + "\n".join(f"- {c}" for c in criterios[:12]))
        return "\n".join(partes)

    def _revision_supervisor_plan(self, pedido: str, plan: Plan) -> Optional[Dictamen]:
        evidencia = {"EV-PLAN": plan.como_texto()}
        texto, pedido_m, servido = self._consultar_rol_x(
            "supervisor", f"PEDIDO:\n{pedido}\n\nEVIDENCIA EV-PLAN (plan propuesto):\n{evidencia['EV-PLAN']}\n\n"
                          "¿El plan cubre el pedido con dependencias correctas y criterios verificables?")
        if texto is None:
            return None
        dictamen = parsear_dictamen(texto, "supervisor", evidencia, model_requested=pedido_m, model_served=servido)
        (self.ui.info if dictamen.valido else self.ui.aviso)("  " + dictamen.texto())
        return dictamen

    def _auditoria_x(self, pedido: str, plan: Plan, verif: Verificacion, informe: InformeBuild) -> None:
        """Seguridad defensiva, auditor de entrega y supervisor sobre EVIDENCIA real. Solo informan: no deciden."""
        diff = self.ws.checkpoints.diff_desde(informe.cid) if informe.cid else ""
        evidencia = {
            "EV-ESTADO": f"estado por verificación real: {informe.estado}; tareas fallidas: "
                         f"{', '.join(informe.tareas_fallidas) or 'ninguna'}; bloqueadas: "
                         f"{', '.join(informe.tareas_bloqueadas) or 'ninguna'}",
            "EV-TESTS": (verif.conteo.texto() if verif.conteo.reconocido else
                         ("sin suite de tests" if verif.tests is None else f"exit {verif.tests.codigo}")),
            "EV-VALID": resumen_validacion(verif.validaciones, limite=1500),
            "EV-ACEPTACION": (verif.aceptacion.resumen(1600) if verif.aceptacion is not None
                               else 'no configurada'),
            "EV-DIFF": _diffstat(diff) or "(sin cambios)",
        }
        bloque = "\n".join(f"{k}: {v}" for k, v in evidencia.items())
        texto, _p, _s = self._consultar_rol_x("seguridad", f"DIFF DE LA BUILD:\n```diff\n{recortar(diff, 9000)}\n```")
        hallazgos = parsear_hallazgos_seguridad(texto or "") if texto is not None else None
        if texto is not None and hallazgos is None:
            self.ui.aviso("  seguridad: respuesta fuera de contrato; hallazgos descartados.")
        for h in (hallazgos or [])[:8]:
            linea = f"Seguridad [{h['severity']}] {h['file'] or '?'}: {h['issue']}" + (f" → {h['fix']}" if h["fix"] else "")
            (self.ui.aviso if h["severity"] == "high" else self.ui.tenue)("  " + linea)
            informe.notas.append(linea)
        criterios = "\n".join(f"- {c}" for c in plan.criterios) or "- (derivalos del pedido)"
        texto, _p, _s = self._consultar_rol_x(
            "auditor_entrega", f"CRITERIOS:\n{criterios}\n\nEVIDENCIA:\n{bloque}")
        auditoria = parsear_auditoria(texto or "", evidencia) if texto is not None else None
        if auditoria is not None:
            met = sum(1 for c in auditoria if c["status"] == "MET")
            informe.notas.append(f"Auditor de entrega: {met}/{len(auditoria)} criterios con evidencia (MET).")
            self.ui.tenue(f"  auditor de entrega: {met}/{len(auditoria)} criterios demostrados con evidencia")
        elif texto is not None:
            self.ui.aviso("  auditor de entrega: respuesta fuera de contrato; auditoría descartada.")
        texto, pedido_m, servido = self._consultar_rol_x(
            "supervisor", f"PEDIDO:\n{pedido}\n\nEVIDENCIA:\n{bloque}\n\n¿Se puede entregar?")
        if texto is not None:
            dictamen = parsear_dictamen(texto, "supervisor", evidencia, model_requested=pedido_m, model_served=servido)
            self.ui.tenue("  " + dictamen.texto())
            informe.estado, notas = estado_controlado(informe.estado, dictamen)
            informe.notas.extend(notas)

    def _contrato_de_entrega(self, pedido: str) -> list:
        """Motor central, paso 1: el juez convierte el PEDIDO en criterios de aceptación ANTES de construir.
        Una sola llamada chica (max_tokens 350). Si el juez está apagado o no responde en contrato, devuelve [] y
        el build sigue con los criterios del plan: nunca bloquea por esto."""
        if not getattr(self.settings, "juez", True):
            return []
        prompt = (f"TAREA: CONTRATO. Convertí este PEDIDO en criterios de aceptación concretos y verificables, "
                  f"sin inventar extras.\n\nPEDIDO:\n{recortar(pedido, 1500)}")
        texto, _p, _s = self._consultar_rol_x("juez", prompt, max_tokens=350)
        return parsear_criterios_entrega(texto or "")

    def _mostrar_contrato(self, criterios: list, plan: Plan) -> None:
        """Muestra el contrato del juez y la vigía DETERMINISTA de cobertura (criterios que el plan no parece cubrir)."""
        if not criterios:
            return
        self.ui.tenue("  Juez · contrato de entrega (lo que hay que cumplir):")
        for c in criterios:
            self.ui.tenue(f"    • {recortar(c, 90)}")
        sin_cubrir = cobertura_criterios(criterios, plan)
        if sin_cubrir:
            self.ui.aviso("  Juez · el plan todavía no parece cubrir: "
                          + "; ".join(recortar(c, 60) for c in sin_cubrir))

    def _juicio_de_entrega(self, pedido: str, plan: Plan, verif: Verificacion, informe: InformeBuild) -> None:
        """8.º agente (JUEZ DE ENTREGA): compara lo entregado contra el PEDIDO y solo puede ENDURECER el estado.

        Nunca convierte una build roja en verde. Entrada compacta (diffstat, no el diff entero) y un veredicto JSON
        chico: consume MUCHOS menos tokens que los roles que escriben o razonan. Si el modelo no responde o contesta
        fuera de contrato, NO cambia el estado (no inventamos ni un éxito ni un fracaso).
        """
        if not getattr(self.settings, "juez", True):
            return
        if informe.estado not in ("verificada", "validada"):
            return  # la build ya está en rojo/parcial: el juez solo endurece, no hay verde que revisar
        # 1) EXAMEN DE REALIDAD, gratis: si algo es una simulación (funciones pedidas vacías, NotImplementedError,
        #    tests que no prueban nada), el juez decide SIN llamar al modelo. Gasta 0 tokens y hace más que nadie.
        realidad = examen_de_realidad(self.ws, informe.cid, plan, self.pedido_usuario or pedido)
        if realidad:
            self._aplicar_juicio(Juicio(False, realidad, [], "high", determinista=True), informe)
            return
        diff = self.ws.checkpoints.diff_desde(informe.cid) if informe.cid else ""
        criterios = "\n".join(f"- {c}" for c in (informe.criterios_entrega or plan.criterios)) or "- (derivalos del pedido)"
        evidencia = {
            "EV-ESTADO": f"estado por verificación real: {informe.estado}; tareas fallidas: "
                         f"{', '.join(informe.tareas_fallidas) or 'ninguna'}; bloqueadas: "
                         f"{', '.join(informe.tareas_bloqueadas) or 'ninguna'}",
            "EV-TESTS": (verif.conteo.texto() if verif.conteo.reconocido else
                         ("sin suite de tests" if verif.tests is None else f"exit {verif.tests.codigo}")),
            "EV-VALID": resumen_validacion(verif.validaciones, limite=600),
            "EV-ACEPTACION": (verif.aceptacion.resumen(600) if verif.aceptacion is not None else "no configurada"),
            "EV-DIFF": _diffstat(diff) or "(sin cambios)",
            # Qué pasó con lo que ya existía antes de esta actualización (determinista, 0 tokens extra de cálculo).
            "EV-PRESERVA": resumen_preservacion(self.ws, informe.cid),
            "EV-REAL": "examen de realidad OK: las funciones pedidas tienen cuerpo y los tests de la build "
                       "tienen asserts reales (sin tautologías ni mocks del código bajo prueba)",
        }
        bloque = "\n".join(f"{k}: {v}" for k, v in evidencia.items())
        prompt = (f"PEDIDO DEL USUARIO:\n{recortar(pedido, 1200)}\n\nOBJETIVO DEL PLAN: {recortar(plan.objetivo, 300)}\n\n"
                  f"CRITERIOS DE ACEPTACIÓN:\n{criterios}\n\nEVIDENCIA:\n{bloque}\n\n"
                  f"¿La entrega cumple el pedido tal como se pidió?")
        texto, _pedido_m, _servido = self._consultar_rol_x("juez", prompt, max_tokens=400)
        if texto is None:
            informe.notas.append("Juez de entrega: el modelo no respondió; sin veredicto (no se cambió el estado).")
            return
        self._aplicar_juicio(parsear_juicio(texto, evidencia), informe)

    def _aplicar_juicio(self, juicio: "Juicio", informe: InformeBuild) -> None:
        """Registra el veredicto (venga del examen determinista o del modelo) y endurece el estado si corresponde."""
        informe.juicio = juicio
        self.ui.tenue("  " + juicio.texto())
        if not juicio.valido:
            informe.notas.append("Juez de entrega: respuesta fuera de contrato; veredicto descartado.")
            return
        informe.notas.append(juicio.texto())
        for f in juicio.faltantes[:6]:
            informe.notas.append(f"Falta según el juez: {f}")
        # Gate en dirección segura: solo baja de verde a parcial. Pide confianza media/alta para no castigar
        # por el ruido de un modelo débil; un 'no cumple' dudoso queda como nota, no como veredicto.
        if (not juicio.cumple and juicio.confianza in ("medium", "high")
                and informe.estado in ("verificada", "validada")):
            informe.estado = "parcial"
            self.ui.aviso("  El juez de entrega observa que el pedido NO quedó cumplido: marco la build como parcial.")
        elif not juicio.cumple:
            informe.notas.append("Juez de entrega: duda de que se cumpla el pedido (confianza baja); lo dejo como aviso.")

    def _debe_intervenir_juez(self, informe: InformeBuild, maximo: int) -> bool:
        """¿El juez debe intervenir para cerrar? Solo si dio un veredicto VÁLIDO de NO cumple con confianza
        media/alta, hay faltantes concretos, quedan intervenciones y la build no está en rojo."""
        j = informe.juicio
        return bool(j is not None and j.valido and not j.cumple and j.confianza in ("medium", "high")
                    and j.faltantes and informe.intervenciones_juez < maximo
                    and informe.estado in ("verificada", "validada", "parcial"))

    def _cerrar_con_juez(self, pedido: str, plan: Plan, verif: Verificacion, informe: InformeBuild,
                         grupo: int, base_fallaba: bool) -> Verificacion:
        """Motor central, paso final: si el juez dice que falta algo, INTERVIENE — el reparador implementa los
        faltantes, se re-verifica DE VERDAD y el juez vuelve a juzgar. Acotado por juez_max_intervenciones; solo
        gasta tokens cuando realmente faltaba algo. Nunca declara verde sin que la verificación real lo confirme."""
        maximo = max(0, int(getattr(self.settings, "juez_max_intervenciones", 1)))
        while self._debe_intervenir_juez(informe, maximo):
            if PLAZO.vencido():
                informe.notas.append("Juez: no intervengo más; se agotó el tiempo.")
                break
            faltantes = list(informe.juicio.faltantes)
            informe.intervenciones_juez += 1
            self.ui.info(f"  Juez · intervención {informe.intervenciones_juez}: completar lo que falta "
                         f"({'; '.join(recortar(f, 50) for f in faltantes[:3])})")
            diag = ("El JUEZ DE ENTREGA detecta que el pedido NO quedó cumplido. Implementá EXACTAMENTE lo que "
                    "falta, sin romper lo que ya anda:\n" + "\n".join(f"- {f}" for f in faltantes))
            verif_sint = replace(verif, ok=False, diagnostico=diag)
            verif = self._reparar_con_escalada(pedido, verif_sint, grupo, base_fallaba, informe,
                                               f"cierre-juez {informe.intervenciones_juez}", 2,
                                               lambda: self.verificar(grupo), contexto=diag)
            informe.estado = estado_final_build(verif, informe)
            informe.juicio = None
            self._juicio_de_entrega(pedido, plan, verif, informe)
        if informe.intervenciones_juez and informe.juicio is not None and informe.juicio.cumple:
            informe.notas.append(f"Juez: el pedido quedó cumplido tras {informe.intervenciones_juez} intervención(es).")
        return verif

    # ------------------------------------------------------------ flujos
    def _mostrar_plan(self, plan: Plan) -> None:
        self.ui.titulo("PLAN")
        self.ui.linea(plan.como_texto())

    def obtener_plan(self, pedido: str, confirmar: bool) -> tuple[Optional[Plan], str]:
        self.ui.fase(1, "Exploración")
        exploracion = self.explorar(pedido)
        self.ui.fase(2, "Arquitectura")
        pedido_plan = pedido
        if self.settings.roles_x:
            directiva = self._directiva_director(pedido)
            if directiva:
                pedido_plan = f"{pedido}\n\n{directiva}"
        plan = self.planificar(pedido_plan, exploracion)
        if self.settings.roles_x:
            dictamen = self._revision_supervisor_plan(pedido, plan)
            if dictamen is not None and dictamen.decision in ("REWORK", "REJECT"):
                self.ui.aviso("  El supervisor pidió rehacer el plan: lo replanifico una vez con sus razones.")
                plan = self.planificar(pedido_plan, exploracion,
                                       "Observaciones del supervisor:\n" + "\n".join(f"- {r}" for r in dictamen.reasons),
                                       plan)
        # Juez (0 tokens): un plan que ORDENA simular (esqueletos, NotImplementedError, TODO) o que trae tareas de
        # "solo correr las pruebas" se rehace una vez con las razones. Lo que quede de meta-tareas se quita solo.
        problemas = problemas_del_plan(plan, self.pedido_usuario or pedido)
        if problemas:
            self.ui.aviso("  Juez · el plan pide simulaciones o tareas sin entrega: lo hago replanificar.")
            for problema in problemas[:4]:
                self.ui.tenue(f"    • {problema}")
            plan = self.planificar(pedido_plan, exploracion,
                                   "Corregí estos problemas del plan:\n" + "\n".join(f"- {p}" for p in problemas),
                                   plan)
        quitadas = quitar_meta_tareas(plan)
        if quitadas:
            self.ui.tenue(f"  Juez · quité la(s) tarea(s) {', '.join(quitadas)}: solo corrían pruebas "
                          "(REAPER verifica después de cada tarea).")
        self._plan_confirmado = False
        for _ in range(3):
            self._mostrar_plan(plan)
            reemplazos = reemplazos_del_plan(self.ws, plan)
            if reemplazos:
                # Que se vea ANTES de aprobar: el plan va a reemplazar código que ya existe.
                self.ui.aviso("  ⚠ Este plan dice que REEMPLAZA código que ya existe: "
                              + ", ".join(f"{rel} ({n} líneas)" for rel, n in list(reemplazos.items())[:6]))
                self.ui.tenue("    Si no querés perderlo, respondé que no y pedí hacerlo en archivos nuevos "
                              "(o en otra carpeta: reaper --proyecto ~/otra_carpeta).")
            if not confirmar:
                return plan, exploracion
            if self.ui.confirmar("¿Aprobás el plan y arrancamos?", defecto=True):
                self._plan_confirmado = True
                return plan, exploracion
            feedback = self.ui.preguntar("¿Qué cambiarías del plan? (Enter vacío = cancelar)")
            if not feedback:
                return None, exploracion
            plan = self.planificar(pedido, exploracion, feedback, plan)
        return None, exploracion

    def solo_plan(self, pedido: str) -> Optional[Path]:
        plan, exploracion = self.obtener_plan(pedido, confirmar=False)
        if plan is None:
            return None
        carpeta = self.ws.raiz / ".reaper" / "planes"
        ruta = carpeta / f"plan_{datetime.now():%Y%m%d_%H%M%S}.md"
        escritura_atomica(ruta, (
            f"# Plan REAPER\n\n## Pedido\n{pedido}\n\n## Plan\n```\n{plan.como_texto()}\n```\n\n"
            f"## Exploración\n{exploracion}\n\n## Respuesta del arquitecto\n{plan.texto}\n"
        ))
        return ruta

    def _violaciones_preservar(self, tcid: int, cid_build: Optional[int], declarados: list) -> list:
        """PRESERVAR TRABAJO PREVIO: en una actualización, lo que ya existía ANTES de esta build no se borra ni se
        reescribe por accidente. Agregar está bien; borrar un archivo previo que la tarea no declaró, o perder buena
        parte de su contenido, no. Los archivos creados en esta misma build no cuentan (se construyen unos sobre
        otros) y las ediciones chicas (un import, una línea) pasan. Un archivo declarado cuyo reemplazo se AUTORIZÓ
        (lo pidió el usuario o aprobó un plan que lo anunciaba) se puede reescribir. → [(rel, mensaje)]."""
        if cid_build is None:
            return []
        autorizados = getattr(self, "_reemplazos_autorizados", set())
        salida = []
        for rel in self.ws.checkpoints.archivos_desde(tcid):
            if self.ws.checkpoints.original(rel, cid_build) is None:
                continue                               # nació en esta actualización
            antes_tarea = self.ws.checkpoints.original(rel, tcid)
            if antes_tarea is None:
                continue
            declarado = rel in declarados
            if declarado and rel in autorizados:
                continue
            ruta = self.ws.raiz / rel
            if not ruta.is_file():
                if not declarado:
                    salida.append((rel, f"BORRÓ TRABAJO PREVIO: eliminó {rel}, que ya existía antes de esta "
                                        f"actualización y la tarea no lo pedía. Restauralo."))
                continue
            borradas, total = _lineas_borradas(antes_tarea, ruta.read_text(encoding="utf-8", errors="replace"))
            if not total:
                continue
            fraccion = borradas / total
            if (not declarado and borradas >= 3 and fraccion >= 0.2) or \
                    (declarado and borradas >= 8 and fraccion >= 0.6):
                tipo = "REESCRITURA DESTRUCTIVA" if declarado else "MODIFICÓ TRABAJO PREVIO"
                salida.append((rel, f"{tipo}: borró {borradas} de {total} líneas ({fraccion:.0%}) que ya había en "
                                    f"{rel} antes de esta actualización. Extendé el archivo sin perder lo que ya "
                                    f"hacía."))
        return salida

    def _restaurar_trabajo_previo(self, tcid: int, cid_build: Optional[int], declarados: list) -> list:
        """Si una tarea TERMINA rechazada por PRESERVAR, el daño no se queda en disco: cada archivo previo que
        borró o vació vuelve a como estaba antes de la tarea. Antes el rechazo frenaba la tarea pero el app.py
        reescrito quedaba igual (el trabajo previo solo se recuperaba con /deshacer). → archivos restaurados."""
        restaurados = []
        for rel, _mensaje in self._violaciones_preservar(tcid, cid_build, declarados):
            contenido = self.ws.checkpoints.original(rel, tcid)
            if contenido is None or rel in restaurados:
                continue
            try:
                self.ws.escribir(rel, contenido)
                restaurados.append(rel)
            except (OSError, ValueError, ErrorRuta) as e:
                self.ui.aviso(f"  No pude restaurar {rel}: {e}. Recuperalo con /deshacer.")
        return restaurados

    def _verificar_tarea(self, tcid: int, antes: ConteoTests, nombres_antes: set,
                         exigir_progreso: bool = False, verificar_entrega: bool = False,
                         archivos_esperados: Sequence[str] = (),
                         archivos_planeados: Sequence[str] = (),
                         cid_build: Optional[int] = None,
                         spec_ajena: Optional[Iterable[str]] = None,
                         spec_propia: Iterable[str] = ()) -> Verificacion:
        """
        Una tarea intermedia no necesita que pasen TODOS los tests (los de tareas
        siguientes todavía fallan): alcanza con validadores OK y que no se rompa
        nada que antes pasaba. `spec_ajena`: los archivos de la especificación que son de OTRAS tareas (los únicos
        cuyo rojo se tolera); None = toda la especificación (comportamiento anterior).
        """
        self._custodiar_protegidos()
        archivos = [r for r in self.ws.checkpoints.archivos_desde(tcid) if (self.ws.raiz / r).is_file()]
        # Sus tests de la especificación también se validan: el diagnóstico dice "nombres indefinidos en
        # tests/test_db.py" en vez de solo un NameError en la salida de los tests.
        validaciones = validar_archivos(self.ws, archivos + sorted(
            r for r in spec_propia if r not in archivos and (self.ws.raiz / r).is_file()))
        tests = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        conteo = conteo_de_resultado(tests)
        problemas = []
        creados_en_build = False
        for r in fallos(validaciones):
            r = _sin_recursos_planeados(self.ws, r, archivos_planeados)
            if r is not None:
                problemas.append(r.resumen(2500))
        if verificar_entrega:
            # La palabra "listo" del modelo NO es evidencia. Cada tarea debe
            # materializar sus objetivos declarados y producir cambios reales.
            # No se exige que toda la suite esté verde antes de tareas futuras.
            faltantes = [rel for rel in archivos_esperados
                         if not isinstance(rel, str) or not rel.strip()
                         or not self.ws.existe(rel)]
            if faltantes:
                problemas.append("ENTREGA INCOMPLETA: faltan archivos declarados por la tarea: "
                                 + ", ".join(map(str, faltantes[:10])))
            declarados = [rel for rel in archivos_esperados if isinstance(rel, str) and rel.strip()]
            # Un modelo suele crear de más: si TODOS los archivos de esta tarea ya los creó una tarea anterior de
            # ESTA build (no existían al empezar), la entrega está en disco y no es "sin cambios" (antes fallaba,
            # bloqueaba las dependientes y gastaba reparaciones). Un archivo previo que había que MODIFICAR sigue
            # exigiendo cambios reales.
            creados_en_build = bool(declarados) and not faltantes and cid_build is not None and all(
                self.ws.checkpoints._origen(rel, cid_build)[0] == "nuevo" for rel in declarados)
            # Una tarea que NO declara archivos ("- ejecutar las pruebas…") no tiene entrega verificable: si terminó
            # limpia y la suite pasa, exigirle cambios solo quemaba reparaciones (prueba real: 3 reparaciones inútiles
            # y build PARCIAL con todo funcionando; en otra corrida el reparador creó un archivo para "cumplir").
            # El resultado lo juzgan la verificación final y el juez.
            sin_entrega_declarada = (not declarados and not exigir_progreso
                                     and tests is not None and tests.ok)
            if not archivos and not creados_en_build and not sin_entrega_declarada:
                problemas.append("SIN CAMBIOS: la tarea no modificó archivos del proyecto. "
                                 "No se puede verificar una implementación solo por el texto del modelo.")
            # DESVÍO: cambió archivos pero NINGUNO de los que la tarea declaró (p. ej. bumpeó la versión en vez de
            # implementar el módulo pedido). Que existan los declarados y que los tests pasen no alcanza: el trabajo
            # tiene que estar en SUS archivos, no en otra cosa. No aplica si los declarados ya se crearon en la build.
            tocados_declarados = [rel for rel in declarados if rel in archivos]
            if declarados and archivos and not tocados_declarados and not creados_en_build:
                problemas.append(
                    "DESVÍO: la tarea declaró trabajar en " + ", ".join(declarados[:6])
                    + " pero no tocó ninguno de esos archivos; cambió " + ", ".join(archivos[:6])
                    + ". Implementá EXACTAMENTE lo pedido en sus archivos, no otra cosa.")
            # PRESERVAR TRABAJO PREVIO: en una actualización, lo que ya existía ANTES de esta build no se borra ni se
            # reescribe por accidente. Agregar está bien; borrar un archivo previo que la tarea no declaró, o perder
            # buena parte de su contenido, no. Los archivos creados en esta misma build no cuentan (se construyen
            # unos sobre otros). Ediciones chicas (un import, una línea) pasan.
            problemas.extend(mensaje for _rel, mensaje in self._violaciones_preservar(tcid, cid_build, declarados))
        if tests is not None and not tests.ok and conteo.reconocido:
            # Los tests de la especificación de tareas siguientes fallan a propósito: no son regresión.
            tolerables = self._protegidos if spec_ajena is None else {rel: None for rel in spec_ajena}
            nuevos_fallos = [n for n in conteo.nombres_fallados
                             if n not in nombres_antes and not _es_de_especificacion(n, tolerables)]
            retroceso = conteo.pasados < antes.pasados
            mas_errores = conteo.errores > antes.errores
            if retroceso or mas_errores or nuevos_fallos:
                detalle = f"antes {antes.texto()}, ahora {conteo.texto()}"
                if nuevos_fallos:
                    detalle += "; fallan tests que antes no fallaban: " + ", ".join(nuevos_fallos[:8])
                problemas.append(
                    f"REGRESIÓN DE TESTS: {detalle}.\n"
                    + fallos_relevantes(f"{tests.stdout}\n{tests.stderr}", maximo=3, limite=4000)
                )
        elif tests is not None and not tests.ok and not conteo.reconocido and antes.ok:
            problemas.append("TESTS: la suite pasaba antes de la tarea y ahora falla.\n" + tests.resumen(4000))
        propios = {rel: None for rel in spec_propia}
        rojos_propios = [n for n in (conteo.nombres_fallados if tests is not None and conteo.reconocido else [])
                         if propios and _es_de_especificacion(n, propios)]
        if rojos_propios and not any(p.startswith("REGRESIÓN DE TESTS") for p in problemas):
            # Sus tests de la especificación fallaban ANTES (es tests primero) y por eso no contaban como regresión: la
            # tarea quedaba "verificada" con su propia especificación en rojo (con pytest los nombres no cambian; E2E
            # con un test de la especificación roto).
            problemas.append("LA ESPECIFICACIÓN DE ESTA TAREA SIGUE EN ROJO (" + ", ".join(sorted(propios)) + "): "
                             + ", ".join(rojos_propios[:8]) + "\n"
                             + fallos_relevantes(f"{tests.stdout}\n{tests.stderr}", maximo=3, limite=4000))
        problemas.extend(self._tests_debilitados())
        if exigir_progreso and not problemas:
            # El implementador NO terminó (límite de pasos, error...). "No romper nada" no alcanza:
            # tiene que haber cambios reales y, si hay tests fallando, alguno más tiene que pasar.
            # Si una tarea anterior de ESTA build ya entregó sus archivos y la suite pasa, no hay nada que reparar:
            # exigir "progreso" ahí dejaba al reparador en un bucle sin salida (prueba real con OpenRouter).
            if not archivos and not (creados_en_build and tests is not None and tests.ok):
                problemas.append("SIN PROGRESO: el implementador no terminó y no cambió ningún archivo.")
            elif tests is not None and not tests.ok and conteo.reconocido and conteo.pasados <= antes.pasados:
                problemas.append(
                    f"SIN PROGRESO: el implementador no terminó y los tests siguen igual (antes {antes.texto()}, "
                    f"ahora {conteo.texto()}).\n"
                    + fallos_relevantes(f"{tests.stdout}\n{tests.stderr}", maximo=3, limite=4000)
                )
        diagnostico = "\n\n".join(problemas)
        if diagnostico and self.settings.pistas_errores:
            diagnostico = anexar_pistas(diagnostico, 2)
        return Verificacion(not problemas, validaciones, tests, diagnostico, archivos, conteo)

    def construir(self, pedido: str, confirmar: bool = True, reanudar: bool = False) -> InformeBuild:
        if not reanudar and pedido.strip():
            # Repetir el MISMO /construir después de un corte (Termux cerrado, plazo, límite del modelo) lo RETOMA:
            # antes respondía "ya hay una build incompleta" y había que saber /construir continuar.
            try:
                previo = RegistroBuild(self.ws).leer()
            except ValueError:
                previo = None                          # _construir informa el diario dañado con su mensaje
            if (previo and previo.get("estado") not in ("verificada", "validada")
                    and mismo_pedido(previo.get("pedido"), pedido)):
                self.ui.info("Esta misma build había quedado a medias: la retomo donde quedó (no empiezo de cero).")
                reanudar = True
        restaurar_equipo = self._equipo_del_juez()
        try:
            with PLAZO.limitar(self.settings.tiempo_max_build, "la build"):
                pila = list(PLAZO._pila)
                try:
                    return self._construir(pedido, confirmar, reanudar)
                finally:
                    # Si una excepción cortó una tarea, su plazo no debe sobrevivir a la build.
                    with PLAZO._lock:
                        PLAZO._pila = [e for e in PLAZO._pila if e in pila]
        finally:
            restaurar_equipo()            # la asignación del juez vale para ESTA build; tu config queda intacta

    def _equipo_del_juez(self) -> Callable[[], None]:
        """Motor central: antes de construir, el juez arma el equipo según la necesidad (salud de cada modelo,
        historial por rol y peso del rol). Sin tokens. Devuelve cómo volver a la configuración del usuario."""
        if not getattr(self.settings, "juez", True):
            return lambda: None
        try:
            desempeno = MemoriaDesempeno() if getattr(self.settings, "router_aprendido", True) else None
            cambios, motivos = asignar_equipo_juez(self.settings, desempeno, getattr(self.llm, "disyuntor", None))
        except (OSError, ValueError, TypeError, AttributeError):
            return lambda: None
        if not cambios:
            return lambda: None
        original = dict(self.settings.modelos_rol)
        self.settings.modelos_rol.update(cambios)
        self.ui.tenue("  Juez · arma el equipo según la necesidad:")
        for motivo in motivos:
            self.ui.tenue(f"    • {motivo}")

        def restaurar() -> None:
            self.settings.modelos_rol.clear()
            self.settings.modelos_rol.update(original)
        return restaurar

    def _construir(self, pedido: str, confirmar: bool = True, reanudar: bool = False) -> InformeBuild:
        inicio = time.monotonic()
        self._protegidos: dict[str, Optional[str]] = {}
        self._spec_rotos: list = []
        self._minimo_tests: dict[str, int] = {}
        self._tokens_juez = 0
        self._tokens_inicio = _tokens_usados(self.llm)
        registro_build = RegistroBuild(self.ws)
        try:
            previo = registro_build.leer()
        except ValueError as e:
            self.ui.error(str(e) + ". Usá /construir estado y revisá el registro antes de descartarlo.")
            return InformeBuild("cancelada")
        self._diario_build = None                     # (registro, previo) para que el custodio actualice los hashes
        base = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        self._base_tests = base
        base_fallaba = base is not None and not base.ok
        if base_fallaba and not reanudar:
            self.ui.aviso("Atención: la suite de tests YA falla antes de empezar; se tendrá en cuenta.")
        # La huella original es ajena al LLM: si sus tests cambian durante la
        # construcción, el verificador fallará sin conceder un falso verde.
        try:
            huella_actual = huella_aceptacion(self.ws)
        except (ValueError, OSError) as exc:
            self.ui.error(f'No puedo iniciar: evaluador independiente inválido: {exc}')
            return InformeBuild('cancelada')
        if reanudar:
            if not previo:
                self.ui.aviso("No hay /construir pendiente en este proyecto.")
                return InformeBuild("cancelada")
            if previo.get("huellas_version", 1) != 2:
                # La huella anterior ignoraba binarios y enlaces simbólicos.
                # No podemos heredar sus resultados "verificados" como evidencia.
                try:
                    igual_legado = previo["huella"] == registro_build.huella_legada()
                except (OSError, ValueError) as e:
                    self.ui.error(f"Inventario antiguo no verificable: {e}")
                    return InformeBuild("cancelada")
                if not igual_legado:
                    self.ui.error("El proyecto cambió desde el diario antiguo. No reanudo ni "
                                  "sobrescribo archivos; revisá el proyecto manualmente.")
                    return InformeBuild("cancelada")
                previo["estados"] = {tid: "pendiente" for tid in previo["estados"]}
                previo["archivos_verificados"] = {}
                previo.pop("tarea_activa", None)
                previo.pop("tcid", None)
                previo.pop("huellas_inicio", None)
                registro_build.guardar(previo)
                self.ui.aviso("Diario antiguo migrado: ninguna tarea se omite; "
                              "se repiten las verificaciones reales.")
            if not registro_build.recuperable(previo):
                self.ui.error("Cambios externos o tareas ya verificadas alteradas; "
                              "no puedo omitir trabajo con evidencia antigua. Revisá /diff.")
                return InformeBuild("cancelada")
            # Actualizar la huella después de una tarea que quedó a mitad.
            # Sus cambios siguen pendientes de verificación, no se marcan como OK.
            if previo["huella"] != registro_build.huella():
                previo["huella"] = registro_build.huella()
                registro_build.guardar(previo)
            if previo["grupo"] not in self.ws.checkpoints.ids():
                self.ui.error("El checkpoint original ya no existe; no puedo reanudar con evidencia.")
                return InformeBuild("cancelada")
            huella_guardada = previo.get('huella_aceptacion')
            if huella_guardada is not None and huella_guardada != huella_actual:
                try:
                    if huella_guardada == huella_aceptacion_v1(self.ws):
                        huella_guardada = None          # diario de la ronda 12: la misma suite, se migra a V2
                except (ValueError, OSError):
                    pass
            if huella_guardada is not None and huella_actual != huella_guardada:
                self.ui.error('Cambió el evaluador independiente desde el checkpoint; no reanudo.')
                return InformeBuild('cancelada')
            self._huella_aceptacion = huella_guardada if huella_guardada is not None else huella_actual
            if huella_guardada is None:
                previo['huella_aceptacion'] = huella_actual
                registro_build.guardar(previo)
            pedido = previo["pedido"]
            # Migración tolerante de registros antiguos: el campo se introdujo
            # después de la primera versión del diario de construcciones.
            # Los campos ausentes NO significan que una tarea esté verificada.
            previo.setdefault("archivos_verificados", {})
            previo.setdefault("tests_protegidos", {})
            plan = _plan_de_registro(previo["plan"])
            problemas_grafo = errores_grafo_build(plan)
            if problemas_grafo:
                self.ui.error("Plan guardado inválido; no retomo la construcción: " + "; ".join(problemas_grafo))
                return InformeBuild("cancelada")
            exploracion = str(previo.get("exploracion", ""))
            grupo = previo["grupo"]
            # Restaurar tests protegidos. No desprotegerlos silenciosamente si desaparecieron.
            for rel, digest in previo.get("tests_protegidos", {}).items():
                if not self.ws.existe(rel) or self.ws.hash(rel) != digest:
                    self.ui.error("Los tests de especificación cambiaron: " + rel)
                    return InformeBuild("cancelada")
                self._protegidos[rel] = self.ws.leer(rel)
            # Lo que fallaba ANTES de la build sale del diario, no de medir ahora: al retomar, la suite puede estar
            # roja por esta MISMA build (una tarea que falló). Medirlo de nuevo lo convertía en "ya fallaba antes" y
            # la tarea re-ejecutada quedaba VERIFICADA con su propio test en rojo (y nunca más se reintentaba).
            if "base_fallaba" in previo:
                if base_fallaba and not previo["base_fallaba"]:
                    self.ui.tenue("  La suite falla al retomar por cambios de esta misma build (antes de empezar "
                                  "pasaba): se repara, no se toma como fallo previo.")
                base_fallaba = bool(previo["base_fallaba"])
            elif base_fallaba:
                self.ui.aviso("Atención: la suite de tests falla al retomar (diario sin el estado inicial).")
            self.ui.info("Retomo la build desde el checkpoint guardado, sin replanificar.")
        else:
            if previo and previo.get("estado") not in ("verificada", "validada"):
                self.ui.error("Ya hay OTRA build incompleta en esta carpeta. Seguila con /construir continuar "
                              f"(o `{comando_para_seguir(self.ws, 'construir', self.settings)}`) o descartala con "
                              "/construir descartar para comenzar otra (sin borrar archivos).")
                return InformeBuild("cancelada")
            plan, exploracion = self.obtener_plan(pedido, confirmar)
            if plan is None:
                self.ui.tenue("Construcción cancelada; no se tocó ningún archivo.")
                return InformeBuild("cancelada")
            if not self.settings.tests_primero:
                for aviso in fusionar_tareas_de_solo_tests(plan):
                    self.ui.tenue("  " + aviso)
            problemas_grafo = errores_grafo_build(plan)
            if problemas_grafo:
                self.ui.error("El plan no es ejecutable: " + "; ".join(problemas_grafo)
                              + ". Corregí sus dependencias antes de empezar.")
                return InformeBuild("cancelada")
            grupo = self.ws.checkpoints.iniciar(f"construir: {pedido[:80]}")
            previo = {"esquema": RegistroBuild.ESQUEMA, "proyecto": str(self.ws.raiz),
                      "pedido": pedido, "plan": asdict(plan), "grupo": grupo,
                      "exploracion": recortar(exploracion, 3000), "estados": {},
                      "tests_protegidos": {}, "archivos_verificados": {}, "estado": "en_curso",
                      "especificacion_completa": False,
                      "tests_primero": bool(self.settings.tests_primero),
                      "huella_aceptacion": huella_actual,
                      # Estado de la suite AL EMPEZAR: al retomar, es la única base honesta para decidir qué
                      # fallo es "previo" y cuál lo causó esta build.
                      "base_fallaba": bool(base_fallaba),
                      "fallaban_al_inicio": sorted(conteo_de_resultado(base).nombres_fallados) if base else []}
            self._huella_aceptacion = huella_actual
            # ¿Quién autoriza reescribir un archivo que ya existía? Vos: pidiéndolo, o aprobando un plan que lo
            # anunciaba (el aviso sale antes de aprobar). Sin eso, PRESERVAR lo protege. Antes no había forma: hasta
            # un "reescribí app.py desde cero" terminaba en REESCRITURA DESTRUCTIVA y tarea fallida.
            reemplazos = reemplazos_del_plan(self.ws, plan)
            if reemplazos and (getattr(self, "_plan_confirmado", False)
                               or _RE_REESCRITURA_PEDIDA.search(self.pedido_usuario or pedido)):
                previo["reemplazos_autorizados"] = sorted(reemplazos)
            elif reemplazos:
                self.ui.aviso("  El plan quiere reemplazar " + ", ".join(sorted(reemplazos)[:6]) + " pero no lo "
                              "pediste ni aprobaste el plan: se protegen (no se pierde lo que ya tenías).")
            registro_build.guardar(previo)
        self._reemplazos_autorizados = set(previo.get("reemplazos_autorizados", []))
        self._diario_build = (registro_build, previo)

        informe = InformeBuild("fallida", plan=plan, cid=grupo,
                               reemplazos_autorizados=sorted(self._reemplazos_autorizados))

        # Motor central: el juez fija el CONTRATO (criterios del pedido) antes de construir. En reanudación se
        # reutiliza el que ya quedó en el diario: no se gasta otra llamada.
        if not reanudar:
            informe.criterios_entrega = self._contrato_de_entrega(pedido)
            if informe.criterios_entrega:
                previo["criterios_entrega"] = informe.criterios_entrega
                # El juez MANDA: su contrato pasa a ser el criterio de aceptación de TODO el build (lo usan los
                # tests primero, el checklist y la verificación), no solo el gate final. Así el equipo construye
                # hacia lo que se pidió, no hacia lo que un rol interpretó.
                fusion = list(informe.criterios_entrega) + [c for c in plan.criterios
                                                            if c not in informe.criterios_entrega]
                plan.criterios = fusion[:10]
                informe.plan = plan
                previo["plan"] = asdict(plan)
                registro_build.guardar(previo)
                self._mostrar_contrato(informe.criterios_entrega, plan)
        else:
            informe.criterios_entrega = list(previo.get("criterios_entrega", []))

        testeable = _es_testeable(plan.archivos(), self.ws.archivos_codigo(limite=200))
        numero_fase = 3
        if not reanudar:
            # Proteger los tests que YA existían en el proyecto: ni el implementador ni un candidato del torneo
            # pueden editarlos para que un bug "pase" (test gaming). Se fijan a su contenido actual y sus hashes
            # quedan en el diario, así una reanudación los vuelve a exigir intactos en vez de congelar lo que haya.
            for rel in self.ws.archivos_codigo(limite=800):
                if _es_test(rel):
                    try:
                        self._protegidos[rel] = self.ws.leer(rel)
                    except (OSError, ValueError, ErrorRuta):
                        pass
            if self._protegidos:
                previo["tests_protegidos"] = {p: self.ws.hash(p) for p in self._protegidos}
                registro_build.guardar(previo)
        # Si se interrumpió la etapa de especificación, reanudarla (no
        # saltarla silenciosamente). Para registros antiguos, los hashes de
        # los tests permiten reconocer la etapa como completada.
        tests_primero_build = bool(previo.get("tests_primero", self.settings.tests_primero))
        spec_completa = bool(previo.get("especificacion_completa",
                                         bool(previo.get("tests_protegidos"))))
        if tests_primero_build and testeable and not spec_completa:
            self.ui.fase(numero_fase, "Tests primero (especificación ejecutable)")
            numero_fase += 1
            _marcar_fase(registro_build, previo, "especificacion", grupo)
            espec = self.especificar(pedido, plan, grupo)
            self._protegidos.update(espec)
            informe.spec_tests = list(espec)
            previo["spec_tests"] = list(espec)
            previo["tests_protegidos"] = {p: self.ws.hash(p) for p in self._protegidos}
            previo["spec_rotos"] = list(self._spec_rotos)
            previo["minimo_tests"] = dict(self._minimo_tests)
            previo["especificacion_completa"] = True
            _cerrar_fase(previo)
            avisos_fusion = fusionar_tareas_de_solo_tests(
                plan, {a for a in espec if self.ws.existe(a)})
            for aviso in avisos_fusion:
                self.ui.tenue("  " + aviso)
            if avisos_fusion:
                informe.plan = plan
                previo["plan"] = asdict(plan)
            registro_build.guardar(previo)
        elif reanudar:
            informe.spec_tests = list(previo.get("spec_tests", self._protegidos))
            self._spec_rotos = [r for r in previo.get("spec_rotos", []) if isinstance(r, str)]
            minimos = previo.get("minimo_tests", {})
            self._minimo_tests = {r: n for r, n in (minimos.items() if isinstance(minimos, dict) else ())
                                  if isinstance(r, str) and isinstance(n, int)}

        self.ui.fase(numero_fase, "Implementación" + (" · torneo" if self.settings.torneo and self.settings.candidatos > 1 else ""))
        numero_fase += 1
        grafo = GrafoTareas(plan.tareas)
        orden = grafo.orden()
        for aviso in grafo.problemas:
            self.ui.aviso("  TaskGraph: " + aviso)
        if [t.id for t in orden] != [t.id for t in plan.tareas]:
            self.ui.tenue("  Orden por dependencias: " + " → ".join(t.id for t in orden))
            plan.tareas = orden
        self._checklist_plan(plan, grafo)
        # Si hay tareas verificadas, la huella del proyecto se confirmó ANTES de
        # retomarlas. No se repiten implementaciones exitosas ni sus solicitudes a IA.
        token_tarea = None
        for i, tarea in enumerate(plan.tareas):
            PLAZO.cerrar(token_tarea)
            token_tarea = None
            self.ui.info(f"\n▸ Tarea {i + 1}/{len(plan.tareas)}: {recortar(tarea.descripcion.splitlines()[0], 120)}")
            if reanudar and previo["estados"].get(tarea.id) == "verificada":
                self.ui.ok(f"Tarea {tarea.id}: conservada (verificada antes de la interrupción)")
                continue
            rotas = [d for d in grafo.dependencias(tarea.id)
                     if d in informe.tareas_fallidas or d in informe.tareas_bloqueadas]
            if rotas:
                # BUG-012: no construir sobre una base que no pasó su verificación; la build termina PARCIAL.
                self.ui.aviso(f"  Tarea {tarea.id} BLOQUEADA: depende de {', '.join(rotas)}, que no pasó su verificación.")
                informe.tareas_bloqueadas.append(tarea.id)
                informe.notas.append(f"Tarea {tarea.id}: bloqueada (depende de {', '.join(rotas)}).")
                previo["estados"][tarea.id] = "bloqueada"
                registro_build.guardar(previo)
                continue
            vencido = PLAZO.vencido()
            if vencido:
                self.ui.aviso(f"  Tarea {tarea.id} NO iniciada: se agotó el tiempo de {vencido}.")
                informe.tareas_fallidas.append(tarea.id)
                informe.notas.append(f"Tarea {tarea.id}: sin iniciar (se agotó el tiempo de {vencido}); "
                                     "retomala con /construir continuar.")
                previo["estados"][tarea.id] = "pendiente"
                registro_build.guardar(previo)
                continue
            ya_escritos = [a for a in tarea.archivos if _es_test(a) and a in (informe.spec_tests or [])
                           and self.ws.existe(a)]
            if tarea.archivos and len(ya_escritos) == len(tarea.archivos):
                # Prueba real: el arquitecto planeó "Escribir la prueba unitaria" como tarea y la especificación ya la
                # había escrito (y protegido). Los implementadores no podían tocarla → SIN PROGRESO → 2 reparaciones y
                # modo forense sin nada que hacer. No hay nada que implementar: lo verifican las tareas que siguen.
                self.ui.ok(f"Tarea {tarea.id}: {', '.join(ya_escritos)} ya lo escribió la especificación (tests "
                           "primero): no hay nada que implementar.")
                informe.notas.append(f"Tarea {tarea.id}: cubierta por la especificación ({', '.join(ya_escritos)}).")
                previo["estados"][tarea.id] = "verificada"
                registro_build.guardar(previo)
                continue
            token_tarea = PLAZO.abrir(self.settings.tiempo_max_tarea, f"la tarea {tarea.id}")
            previo["estados"][tarea.id] = "en_curso"
            previo["tarea_activa"] = tarea.id
            previo["huellas_inicio"] = registro_build.huellas()
            registro_build.guardar(previo)
            planeados_despues = [a for t_sig in plan.tareas[i + 1:] for a in t_sig.archivos]
            estado_previo_tarea = previo["estados"].get(tarea.id) if reanudar else None
            antes_tests = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
            conteo_antes = conteo_de_resultado(antes_tests)
            nombres_antes = set(conteo_antes.nombres_fallados)
            if estado_previo_tarea in ("fallida", "en_curso") and "fallaban_al_inicio" in previo:
                nombres_antes = fallos_tolerables_al_reintentar(
                    nombres_antes, previo["fallaban_al_inicio"], tarea, plan.tareas)
            tcid = self.ws.checkpoints.iniciar(f"tarea {tarea.id}", grupo=grupo)
            previo["tcid"] = tcid
            registro_build.guardar(previo)
            resultado = self.implementar(pedido, plan, i, exploracion, tcid, protegidos=self._protegidos)
            informe.torneos.append((tarea.id, resultado.modo, resultado.ganador.indice if resultado.ganador else None))
            # "Terminó sin cambiar nada" (el trabajo ya estaba hecho) NO es "no terminó": exigir progreso ahí era un
            # callejón sin salida (nada que reparar). Los archivos previos siguen protegidos por SIN CAMBIOS.
            termino_sin_cambios = getattr(resultado, "termino_sin_cambios", False)
            if not resultado.ok and not termino_sin_cambios:
                informe.notas.append(f"Tarea {tarea.id}: la implementación no terminó limpia.")
            elif termino_sin_cambios:
                self.ui.tenue(f"  Tarea {tarea.id}: el implementador terminó sin cambios (ya estaba hecho); "
                              "lo confirma la verificación real.")

            exigir = not resultado.ok and not termino_sin_cambios
            # Solo se tolera el rojo de la especificación de las tareas SIGUIENTES. Antes se toleraba toda: con una
            # venta que no controlaba el stock, el test de la propia tarea fallaba y la tarea quedaba "verificada"
            # (pasaba al revisor y lo atajaba recién la verificación final; corrida E2E de /grande, modelo flojo).
            # Los tests que existían antes de la build (etapas anteriores) tampoco: romperlos es regresión.
            spec_build = set(informe.spec_tests or []) | set(getattr(self, "_spec_rotos", ()))
            ultima = i == len(plan.tareas) - 1
            spec_ajena = set() if ultima else (spec_build - {a for a in tarea.archivos if _es_test(a)})
            # Los de la especificación que declara ESTA tarea (y ninguna posterior) tienen que quedar en verde con
            # ella; en la última tarea, todos.
            de_despues = {a for t_sig in plan.tareas[i + 1:] for a in t_sig.archivos}
            spec_propia = spec_build if ultima else {a for a in tarea.archivos
                                                     if a in spec_build and a not in de_despues}
            verif_tarea = self._verificar_tarea(tcid, conteo_antes, nombres_antes,
                                                 exigir_progreso=exigir, verificar_entrega=True,
                                                 archivos_esperados=tarea.archivos,
                                                 archivos_planeados=planeados_despues, cid_build=grupo,
                                                 spec_ajena=spec_ajena, spec_propia=spec_propia)
            if not verif_tarea.ok:
                self.ui.aviso(f"  La tarea {tarea.id} no pasó su verificación: la reparo con el error real.")
                self.ui.tenue(f"    motivo: {_primera_linea_util(verif_tarea.diagnostico)}")
                verif_tarea = self._reparar_con_escalada(
                    pedido, verif_tarea, grupo, base_fallaba, informe, f"tarea {tarea.id}",
                    max(1, self.settings.umbral_escalada + 1),
                    lambda: self._verificar_tarea(tcid, conteo_antes, nombres_antes,
                                                 exigir_progreso=exigir, verificar_entrega=True,
                                                 archivos_esperados=tarea.archivos,
                                                 archivos_planeados=planeados_despues, cid_build=grupo,
                                                 spec_ajena=spec_ajena, spec_propia=spec_propia),
                    contexto=f"TAREA EN CURSO (#{tarea.id}): {tarea.descripcion}",
                )
                if not verif_tarea.ok:
                    motivo = _primera_linea_util(verif_tarea.diagnostico)
                    informe.notas.append(f"Tarea {tarea.id}: quedó con fallos de verificación → {motivo}")
                    informe.motivos_fallo[tarea.id] = recortar(verif_tarea.diagnostico, 1500)
                    informe.tareas_fallidas.append(tarea.id)
                    restaurados = self._restaurar_trabajo_previo(tcid, grupo, tarea.archivos)
                    if restaurados:
                        informe.restaurados.extend(r for r in restaurados if r not in informe.restaurados)
                        self.ui.aviso(f"  PRESERVAR: devolví a como estaban {', '.join(restaurados)} "
                                      "(la tarea fallida los había borrado o reescrito).")
                        informe.notas.append(f"Tarea {tarea.id}: se restauró el trabajo previo en "
                                             f"{', '.join(restaurados)}.")

            if not verif_tarea.ok and self.settings.max_revisiones:
                # Revisar código que no pasa su verificación no tiene sentido (y un revisor de 24B
                # terminaba "aprobando" igual): el problema ya está diagnosticado por los tests.
                self.ui.aviso(f"  No paso la tarea {tarea.id} al revisor: su verificación real falla.")
                informe.notas.append(f"Tarea {tarea.id}: sin revisión porque la verificación real falla.")
                previo["estados"][tarea.id] = "fallida"
                previo.pop("tarea_activa", None)
                previo.pop("tcid", None)
                previo.pop("huellas_inicio", None)
                registro_build.guardar(previo)
                continue

            for ronda in range(self.settings.max_revisiones):
                diff = self.ws.checkpoints.diff_desde(tcid)
                if not diff.strip():
                    informe.notas.append(f"Tarea {tarea.id}: sin cambios en archivos.")
                    break
                conteo_tarea = getattr(verif_tarea, "conteo", None)
                aprobado, revision = self.revisar(
                    pedido, tarea, diff, tcid,
                    tests_reales=conteo_tarea.texto() if conteo_tarea is not None and conteo_tarea.reconocido else "")
                if aprobado:
                    self.ui.ok(f"Revisor aprobó la tarea {tarea.id}")
                    break
                if revision == REVISION_SIN_DICTAMEN:
                    # Nada que aplicar: una ronda de "corrección" sin observaciones gastaba 1 implementador + 1
                    # revisor por tarea (corrida E2E de /grande: 28 pedidos de 112 en revisiones vacías).
                    informe.notas.append(f"Tarea {tarea.id}: el revisor no dio un dictamen; decide la verificación real.")
                    break
                self.ui.aviso(f"  Revisor pidió cambios en la tarea {tarea.id} (ronda {ronda + 1})")
                if ronda + 1 >= self.settings.max_revisiones:
                    informe.notas.append(f"Tarea {tarea.id}: quedaron observaciones del revisor sin resolver.")
                    break
                self.implementar(pedido, plan, i, exploracion, tcid, correcciones=revision,
                                 protegidos=self._protegidos)
            # La revisión puede editar código. Verificar de nuevo antes de
            # registrar la tarea como hecha: tests verdes previos no bastan.
            verif_post = self._verificar_tarea(tcid, conteo_antes, nombres_antes,
                                              exigir_progreso=exigir, verificar_entrega=True,
                                              archivos_esperados=tarea.archivos,
                                              archivos_planeados=planeados_despues, cid_build=grupo,
                                              spec_ajena=spec_ajena, spec_propia=spec_propia)
            if verif_post.ok:
                previo["estados"][tarea.id] = "verificada"
                # Archivo verificado por primera vez: no permitir que una tarea
                # interrumpida lo altere y sea saltado al reanudar.
                for rel in self.ws.checkpoints.archivos_desde(tcid):
                    previo["archivos_verificados"][rel] = self.ws.hash(rel)
                for rel in list(previo["archivos_verificados"]):
                    previo["archivos_verificados"][rel] = self.ws.hash(rel)
            else:
                previo["estados"][tarea.id] = "fallida"
                if tarea.id not in informe.tareas_fallidas:
                    informe.tareas_fallidas.append(tarea.id)
                informe.motivos_fallo.setdefault(tarea.id, recortar(verif_post.diagnostico, 1500))
                informe.notas.append(f"Tarea {tarea.id}: falla tras revisión; verificación final pendiente.")
            previo.pop("tarea_activa", None)
            previo.pop("tcid", None)
            previo.pop("huellas_inicio", None)
            registro_build.guardar(previo)
        PLAZO.cerrar(token_tarea)
        _marcar_fase(registro_build, previo, "cierre", grupo)

        archivos = [r for r in self.ws.checkpoints.archivos_desde(grupo) if (self.ws.raiz / r).is_file()]
        hay_tests_build = any(_es_test(a) for a in archivos)
        if self.settings.qa and testeable and not (self._protegidos or hay_tests_build):
            self.ui.fase(numero_fase, "QA (tests reales)")
            numero_fase += 1
            qcid = self.ws.checkpoints.iniciar("qa", grupo=grupo)
            self.qa(pedido, plan, archivos, qcid)

        self.ui.fase(numero_fase, "Verificación real")
        verif = self.verificar(grupo)
        self._mostrar_verificacion(verif)
        self._rol_reparacion = "integrador" if self.settings.roles_x else "reparador"
        try:
            verif = self._reparar_con_escalada(pedido, verif, grupo, base_fallaba, informe, "final",
                                               self.settings.max_reparaciones, lambda: self.verificar(grupo))
        finally:
            self._rol_reparacion = "reparador"

        informe.archivos = verif.archivos
        informe.tests = verif.tests
        informe.aceptacion = verif.aceptacion
        informe.diagnostico = verif.diagnostico
        informe.estado = estado_final_build(verif, informe)
        # 8.º agente: el juez de entrega puede bajar de verde a parcial si el pedido no quedó cumplido (nunca sube).
        self._juicio_de_entrega(pedido, plan, verif, informe)
        # Motor central: si falta algo del pedido, el juez interviene para cerrarlo (acotado) y vuelve a juzgar.
        verif = self._cerrar_con_juez(pedido, plan, verif, informe, grupo, base_fallaba)
        if informe.estado == "parcial":
            if informe.tareas_bloqueadas or informe.tareas_fallidas:
                informe.notas.append("Verificación final verde, pero hay tareas fallidas/bloqueadas sin completar.")
        elif informe.ok:
            if self.settings.git_snapshots and es_repo_git(self.ws):
                try:
                    informe.commit = snapshot_build(self.ws, self.settings.rama_git,
                                                    f"REAPER build verificada: {pedido[:72]}\n\n{plan.objetivo}")
                except RuntimeError as e:
                    informe.notas.append(f"No pude guardar la build en git: {e}")
        if self.settings.roles_x:
            self.ui.fase(numero_fase + 1, "Auditoría REAPER X (seguridad defensiva · entrega · supervisor)")
            self._auditoria_x(pedido, plan, verif, informe)
        informe.segundos = time.monotonic() - inicio
        informe.tokens_juez = getattr(self, "_tokens_juez", 0)
        informe.tokens_build = max(0, _tokens_usados(self.llm) - getattr(self, "_tokens_inicio", 0))
        previo["estado"] = informe.estado
        _cerrar_fase(previo)
        registro_build.guardar(previo)
        if informe.ok:
            registro_build.borrar()
        informe.ruta_informe = self._guardar_informe(pedido, informe)
        self._mostrar_cierre(informe)
        return informe

    # ------------------------------------------------------------ salida
    def _mostrar_verificacion(self, verif: Verificacion) -> None:
        for r in verif.validaciones:
            if not r.ok:
                self.ui.error(r.linea()[2:])
        malos = len(fallos(verif.validaciones))
        self.ui.linea(f"  validadores: {len(verif.validaciones) - malos}/{len(verif.validaciones)} OK")
        if verif.tests is None:
            self.ui.aviso("  tests: no hay suite detectada")
        elif verif.tests.omitido:
            self.ui.aviso("  tests: la suite no encontró tests")
        elif verif.tests.ok:
            self.ui.ok(f"tests: pasaron ({verif.conteo.texto() if verif.conteo.reconocido else verif.tests.comando})")
        else:
            self.ui.error(f"tests: fallaron ({verif.conteo.texto() if verif.conteo.reconocido else verif.tests.comando})")
            self.ui.tenue(recortar(fallos_relevantes(verif.tests.stdout + "\n" + verif.tests.stderr, 2, 1500), 1500))
        if verif.aceptacion is not None:
            if verif.aceptacion.ok:
                self.ui.ok('aceptación independiente: pruebas externas superadas')
            else:
                self.ui.error('aceptación independiente: FALLIDA')
                self.ui.tenue(recortar(verif.aceptacion.resumen(1500), 1500))

    def _guardar_informe(self, pedido: str, informe: InformeBuild) -> Optional[Path]:
        try:
            diff = self.ws.checkpoints.diff_desde(informe.cid) if informe.cid else ""
            tests = informe.tests.resumen(4000) if informe.tests else "sin suite de tests"
            # Sin versión ni motivos, un informe no deja reconstruir qué pasó (caso script_whatsapp: no se podía
            # saber qué REAPER corrió ni por qué falló la tarea 1). Ahora quedan escritos.
            entorno = "Termux/Android" if es_termux() else platform.system()
            juez = ""
            if getattr(self.settings, "juez", True):
                juez = "## Juez de entrega\n"
                if informe.criterios_entrega:
                    juez += "Contrato:\n" + "\n".join(f"- {c}" for c in informe.criterios_entrega) + "\n"
                juez += f"Veredicto: {informe.juicio.texto() if informe.juicio is not None else 'sin veredicto'}\n"
                juez += (f"Intervenciones: {informe.intervenciones_juez} · tokens del juez: "
                         f"~{informe.tokens_juez} de ~{informe.tokens_build}\n\n")
            motivos = "".join(f"### Tarea {tid}\n```\n{texto}\n```\n" for tid, texto in informe.motivos_fallo.items())
            contenido = (
                f"# Build REAPER — {informe.estado.upper()}\n\n"
                f"Fecha: {datetime.now():%Y-%m-%d %H:%M} · duración: {formatear_duracion(informe.segundos)}\n"
                f"Versión: REAPER {__version__} · Python {sys.version.split()[0]} · {entorno}\n\n"
                f"## Pedido\n{pedido}\n\n"
                f"## Plan\n```\n{informe.plan.como_texto() if informe.plan else '-'}\n```\n\n"
                f"## Archivos\n```\n{_diffstat(diff) or '-'}\n```\n\n"
                f"## Tests\n```\n{tests}\n```\n\n"
                + (f"## Aceptación independiente\n```\n{informe.aceptacion.resumen(4500)}\n```\n\n"
                   if informe.aceptacion is not None else '')
                + ("## Tareas pendientes de la build\n"
                   + "\n".join(f"- Fallida: {t}" for t in informe.tareas_fallidas)
                   + ("\n" if informe.tareas_fallidas and informe.tareas_bloqueadas else "")
                   + "\n".join(f"- Bloqueada: {t}" for t in informe.tareas_bloqueadas)
                   + "\n\n" if (informe.tareas_fallidas or informe.tareas_bloqueadas) else "")
                + (f"## Por qué fallaron las tareas\n{motivos}\n" if motivos else "")
                + ("## Trabajo previo restaurado (PRESERVAR)\n" + "\n".join(f"- {r}" for r in informe.restaurados)
                   + "\n\n" if informe.restaurados else "")
                + ("## Reemplazos autorizados\n" + "\n".join(f"- {r}" for r in informe.reemplazos_autorizados)
                   + "\n\n" if informe.reemplazos_autorizados else "")
                + juez
                + ("## Especificación (tests escritos antes de implementar)\n" + "\n".join(f"- {t}" for t in informe.spec_tests) + "\n\n"
                   if informe.spec_tests else "")
                + (f"## Escaladas al modelo fuerte\n{informe.escaladas}\n\n" if informe.escaladas else "")
                + ("## Lecciones aprendidas\n" + "\n".join(f"- {l}" for l in informe.lecciones) + "\n\n" if informe.lecciones else "")
                + (f"## Commit\n`{informe.commit}` en la rama {self.settings.rama_git}\n\n" if informe.commit else "")
                + (f"## Diagnóstico pendiente\n```\n{informe.diagnostico}\n```\n\n" if informe.diagnostico else "")
                + ("## Notas\n" + "\n".join(f"- {n}" for n in informe.notas) + "\n" if informe.notas else "")
            )
            ruta = self.ws.raiz / ".reaper" / "informes" / f"build_{datetime.now():%Y%m%d_%H%M%S}.md"
            # Los informes persisten fuera de la conversación y no deben
            # filtrar tokens mencionados en el pedido ni en los diagnósticos.
            escritura_atomica(ruta, redactar_secretos(contenido))
            return ruta
        except OSError as e:
            self.ui.aviso(f"No pude guardar el informe: {e}")
            return None

    def _checklist_plan(self, plan: Plan, grafo: "GrafoTareas") -> None:
        """Checklist del plan antes de implementar: se ve de un vistazo qué se va a hacer y en qué orden."""
        if len(plan.tareas) <= 1:
            return
        ancho = max(24, min(ancho_terminal(), 100) - 26)
        lineas = []
        for t in plan.tareas:
            desc = recortar(t.descripcion.splitlines()[0], ancho)
            deps = grafo.dependencias(t.id)
            cola = f"  {Tema.tenue}← {', '.join(deps)}{C.RESET}" if deps else ""
            lineas.append(f"{Tema.tenue}○{C.RESET} {C.BOLD}{t.id}{C.RESET} {desc}{cola}")
        self.ui.caja(lineas, titulo=f"Plan · {len(plan.tareas)} tareas", color=C.ESCAMA)

    def _mostrar_cierre(self, informe: InformeBuild) -> None:
        insignias = {
            "verificada": ("✓", "BUILD VERIFICADA", "validadores + tests reales", Tema.ok),
            "validada": ("✓", "BUILD VALIDADA", "validadores OK, sin tests que correr", Tema.ok),
            "parcial": ("◐", "BUILD PARCIAL", "lo hecho pasa; faltan tareas del plan", Tema.aviso),
            "cancelada": ("•", "BUILD CANCELADA", "no se tocó ningún archivo", Tema.tenue),
            "fallida": ("✗", "BUILD FALLIDA", "quedaron fallos sin resolver", Tema.error),
        }
        glifo, titulo, subt, color = insignias.get(informe.estado, insignias["fallida"])
        diff = self.ws.checkpoints.diff_desde(informe.cid) if informe.cid else ""
        datos = [formatear_duracion(informe.segundos)]
        resumen = _resumen_diff(diff)
        if resumen:
            datos.append(resumen)
        torneos = sum(1 for _, modo, _g in informe.torneos if modo == "torneo")
        if torneos:
            datos.append(f"{torneos} torneo(s)")
        if informe.escaladas:
            datos.append(f"{informe.escaladas} escalada(s)")
        if informe.spec_tests:
            datos.append(f"{len(informe.spec_tests)} tests previos")
        if informe.lecciones:
            datos.append(f"{len(informe.lecciones)} lección(es)")
        lineas = [f"{color}{subt}{C.RESET}", f"{Tema.tenue}{' · '.join(datos)}{C.RESET}"]
        if informe.estado == "parcial" and (informe.tareas_fallidas or informe.tareas_bloqueadas):
            lineas.append(f"{Tema.aviso}fallidas: {', '.join(informe.tareas_fallidas) or '—'} · "
                          f"bloqueadas: {', '.join(informe.tareas_bloqueadas) or '—'}{C.RESET}")
        if informe.juicio is not None and informe.juicio.valido and not informe.juicio.cumple:
            faltan = "; ".join(informe.juicio.faltantes[:3]) or "sin detalle"
            lineas.append(f"{Tema.aviso}juez: no cumple el pedido → {recortar(faltan, 90)}{C.RESET}")
        if getattr(self.settings, "juez", True) and informe.tokens_build:
            # El juez es el que más controla y el que menos gasta: que se vea con números.
            if informe.tokens_juez:
                pct = 100 * informe.tokens_juez / informe.tokens_build
                lineas.append(f"{Tema.tenue}⚖ juez: ~{formatear_numero(informe.tokens_juez)} tokens "
                              f"({pct:.1f}% de la build){C.RESET}")
            else:
                lineas.append(f"{Tema.tenue}⚖ juez: 0 tokens · decidió con evidencia local{C.RESET}")
        if informe.commit:
            lineas.append(f"{Tema.ok}git {informe.commit[:10]} · rama {self.settings.rama_git}{C.RESET}")
        self.ui.linea("")
        self.ui.caja(lineas, titulo=f"{glifo} {titulo}", color=color)
        detalle = _diffstat(diff)
        if detalle:
            self.ui.tenue(detalle)
        for nota in informe.notas:
            if nota.startswith("Juez de entrega: CUMPLE"):
                self.ui.ok(f"  ✓ {nota}")                  # un veredicto a favor no es una advertencia
            else:
                self.ui.aviso(f"  • {nota}")
        if informe.ruta_informe:
            self.ui.tenue(f"  informe: {informe.ruta_informe}")
        self.ui.tenue("  /diff ver cambios · /deshacer revierte toda la build\n")

    def revisar_proyecto(self, foco: str = "") -> str:
        archivos = [a for a in self.ws.archivos_codigo(limite=400)
                    if a.endswith((".py", ".js", ".mjs", ".ts", ".sh", ".html", ".css"))]
        if not archivos:
            return "No hay archivos de código para revisar."
        grupos = max(1, min(self.settings.paralelo, (len(archivos) + 11) // 12))
        lotes = [archivos[i::grupos] for i in range(grupos)]
        specs = []
        for lote in lotes:
            specs.append((
                "revisor",
                "Revisión general del proyecto (no hay diff). Revisá estos archivos buscando bugs reales, "
                "errores de manejo de excepciones, problemas de compatibilidad con Termux y riesgos de seguridad. "
                + (f"Foco pedido por el usuario: {foco}. " if foco else "")
                + "Empezá con VEREDICTO (APROBADO si no hay problemas graves) y después: hallazgos confirmados "
                "(archivo:línea), riesgos probables marcados como inferidos y qué arreglar primero.\n\n"
                f"Archivos asignados: {', '.join(lote)}",
                "",
                f"revisa {len(lote)} archivos",
            ))
        resultados = ejecutar_subagentes(specs, self.llm, self.ws, self.settings, self.ui, profundidad=1)
        return "\n\n".join(f"### Revisor {i}\n{r.resumen}" for i, r in enumerate(resultados, start=1))
