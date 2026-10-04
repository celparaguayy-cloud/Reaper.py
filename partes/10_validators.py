"""
Validadores reales y ejecución de comandos/tests.

Nada de "el modelo dice que anda": cada archivo que se escribe pasa por
validadores concretos y el resultado real vuelve al agente.

v7 agrega validaciones que atrapan los errores típicos de un modelo de 24B:
  - nombres indefinidos en Python aunque no haya ruff ni pyflakes (análisis AST propio)
  - `from modulo import X` donde el módulo del proyecto no define X
  - imports locales de JS que apuntan a archivos o exports inexistentes
  - HTML que referencia .js/.css que no existen
  - funciones vacías (pass / ... / NotImplementedError) que quedaron sin implementar
  - C/C++/Go/PHP/Ruby/Lua con su compilador si está instalado, y balance de llaves si no
"""

try:
    from pyflakes import api as _pyflakes_api
    from pyflakes import reporter as _pyflakes_reporter
except ImportError:  # pragma: no cover - opcional
    _pyflakes_api = None

_ENV_SECRETO = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)
_CACHE_MODULOS: dict[str, bool] = {}
_LOCK_IMPORTS = threading.Lock()
MAX_SALIDA_PROCESO = 400_000


@dataclass
class Resultado:
    ok: bool
    comando: str
    codigo: int = 0
    stdout: str = ""
    stderr: str = ""
    timeout: bool = False
    omitido: bool = False
    archivo: str = ""
    duracion: float = 0.0

    def resumen(self, limite: int = 4000) -> str:
        partes = [f"$ {self.comando}", f"exit code: {self.codigo}"]
        if self.timeout:
            partes.append("estado: TIMEOUT")
        if self.stdout.strip():
            partes.append("STDOUT:\n" + recortar(self.stdout.strip(), limite))
        if self.stderr.strip():
            partes.append("STDERR:\n" + recortar(self.stderr.strip(), limite))
        return "\n".join(partes)

    def linea(self) -> str:
        if self.omitido:
            return f"↷ {self.comando}: {(self.stdout or self.stderr).strip()[:120]}"
        if self.ok:
            return f"✓ {self.comando}"
        detalle = (self.stderr or self.stdout).strip().splitlines()
        return f"✗ {self.comando}: {detalle[-1][:160] if detalle else 'exit ' + str(self.codigo)}"


def entorno_seguro() -> dict:
    """Entorno para subprocesos sin claves API (el modelo nunca debe verlas)."""
    env = {k: v for k, v in os.environ.items() if not _ENV_SECRETO.search(k)}
    if any(k.startswith("GIT_CONFIG_") and k not in env for k in os.environ):
        # GIT_CONFIG_COUNT/KEY_n/VALUE_n van juntas: si se quitó una, se quitan todas (si no, git no arranca).
        env = {k: v for k, v in env.items() if not (k.startswith("GIT_CONFIG_") or k == "GIT_CONFIG_PARAMETERS")}
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")  # muchos runners de tests evitan modos interactivos con CI=1
    return env


def ejecutar(
    cmd: Union[str, list],
    *,
    cwd: Path,
    timeout: int = 60,
    shell: bool = False,
    entrada: Optional[str] = None,
) -> Resultado:
    etiqueta = cmd if isinstance(cmd, str) else " ".join(shlex.quote(str(c)) for c in cmd)
    inicio = time.monotonic()
    try:
        proceso = subprocess.Popen(
            cmd,
            shell=shell,
            executable=(shutil.which("bash") if shell else None),
            cwd=str(cwd),
            stdin=subprocess.PIPE if entrada is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=entorno_seguro(),
            start_new_session=True,
        )
    except FileNotFoundError:
        nombre = cmd.split()[0] if isinstance(cmd, str) else cmd[0]
        return Resultado(False, etiqueta, 127, stderr=f"No existe el ejecutable: {nombre}")
    except OSError as e:
        return Resultado(False, etiqueta, 1, stderr=f"{type(e).__name__}: {e}")

    try:
        out, err = proceso.communicate(input=entrada, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proceso.pid, signal.SIGKILL)
        except OSError:
            proceso.kill()
        out, err = proceso.communicate()
        return Resultado(
            False, etiqueta, 124, (out or "")[-MAX_SALIDA_PROCESO:],
            (err or "")[-MAX_SALIDA_PROCESO:] + f"\nTiempo agotado después de {timeout}s (¿programa interactivo o servidor?).",
            timeout=True, duracion=time.monotonic() - inicio,
        )
    return Resultado(proceso.returncode == 0, etiqueta, proceso.returncode,
                     (out or "")[-MAX_SALIDA_PROCESO:], (err or "")[-MAX_SALIDA_PROCESO:],
                     duracion=time.monotonic() - inicio)


# ==================================================================
# PYTHON: imports
# ==================================================================
def _nodos_protegidos(arbol: ast.AST) -> set[int]:
    """Imports dentro de try/except ImportError o if TYPE_CHECKING no se exigen."""
    protegidos: set[int] = set()
    for nodo in ast.walk(arbol):
        bloques = []
        if isinstance(nodo, ast.Try):
            for handler in nodo.handlers:
                tipo = ast.unparse(handler.type) if handler.type is not None else ""
                if not tipo or any(n in tipo for n in ("ImportError", "ModuleNotFoundError", "Exception")):
                    bloques.append(nodo.body)
                    break
        elif isinstance(nodo, ast.If) and "TYPE_CHECKING" in ast.unparse(nodo.test):
            bloques.append(nodo.body)
        for bloque in bloques:
            for sentencia in bloque:
                for sub in ast.walk(sentencia):
                    protegidos.add(id(sub))
    return protegidos


def _carpetas_import(ws: Workspace, ruta: Path) -> list[Path]:
    carpetas = [ws.raiz, ws.raiz / "src"]
    actual = ruta.parent
    while True:
        carpetas.append(actual)
        if actual == ws.raiz or ws.raiz not in actual.parents:
            break
        actual = actual.parent
    return carpetas


def imports_faltantes(ws: Workspace, ruta: Path, arbol: ast.AST) -> list[str]:
    protegidos = _nodos_protegidos(arbol)
    modulos: set[str] = set()
    for nodo in ast.walk(arbol):
        if id(nodo) in protegidos:
            continue
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                modulos.add(alias.name.split(".")[0])
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            modulos.add(nodo.module.split(".")[0])

    carpetas = _carpetas_import(ws, ruta)
    estandar = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
    faltan = []
    for modulo in sorted(modulos):
        if modulo in estandar or modulo == "__future__":
            continue
        if any((d / f"{modulo}.py").is_file() or (d / modulo).is_dir() for d in carpetas):
            continue
        with _LOCK_IMPORTS:
            if modulo not in _CACHE_MODULOS:
                try:
                    _CACHE_MODULOS[modulo] = importlib.util.find_spec(modulo) is not None
                except (ImportError, ValueError):
                    _CACHE_MODULOS[modulo] = False
            if not _CACHE_MODULOS[modulo]:
                faltan.append(modulo)
    return faltan


def _resolver_modulo_local(ws: Workspace, ruta: Path, modulo: str, nivel: int) -> Optional[Path]:
    """Archivo .py del proyecto que corresponde a 'modulo' (o None si no es local)."""
    partes = modulo.split(".") if modulo else []
    if nivel:
        base = ruta.parent
        for _ in range(nivel - 1):
            base = base.parent
        bases = [base]
    else:
        bases = _carpetas_import(ws, ruta)
    for base in bases:
        destino = base.joinpath(*partes) if partes else base
        if destino.with_suffix(".py").is_file() and partes:
            return destino.with_suffix(".py")
        if (destino / "__init__.py").is_file():
            return destino / "__init__.py"
    return None


def nombres_exportados_python(texto: str) -> Optional[set[str]]:
    """Nombres de primer nivel de un módulo. None si no se puede saber (import *, __getattr__...)."""
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return None
    nombres: set[str] = set()
    for nodo in arbol.body:
        nombres |= _nombres_definidos_en(nodo)
        if isinstance(nodo, ast.ImportFrom) and any(a.name == "*" for a in nodo.names):
            return None
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == "__getattr__":
            return None
    return nombres


def _nombres_definidos_en(nodo: ast.AST) -> set[str]:
    """Nombres que una sentencia de primer nivel define (sin entrar en funciones/clases)."""
    nombres: set[str] = set()
    if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        nombres.add(nodo.name)
    elif isinstance(nodo, ast.Import):
        for a in nodo.names:
            nombres.add((a.asname or a.name).split(".")[0])
    elif isinstance(nodo, ast.ImportFrom):
        for a in nodo.names:
            if a.name != "*":
                nombres.add(a.asname or a.name)
    elif isinstance(nodo, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        objetivos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
        for objetivo in objetivos:
            for sub in ast.walk(objetivo):
                if isinstance(sub, ast.Name):
                    nombres.add(sub.id)
    elif isinstance(nodo, (ast.For, ast.AsyncFor, ast.While, ast.If, ast.With, ast.AsyncWith, ast.Try)):
        for sub in ast.walk(nodo):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                nombres.add(sub.id)
            elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nombres.add(sub.name)
            elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                nombres |= _nombres_definidos_en(sub)
    elif isinstance(nodo, ast.Expr) and isinstance(nodo.value, ast.NamedExpr):
        nombres.add(nodo.value.target.id)
    return nombres


def imports_locales_rotos(ws: Workspace, ruta: Path, arbol: ast.AST) -> list[str]:
    """`from modulo_del_proyecto import nombre` donde el módulo no define 'nombre'."""
    protegidos = _nodos_protegidos(arbol)
    problemas = []
    cache: dict[Path, Optional[set[str]]] = {}
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.ImportFrom) or id(nodo) in protegidos:
            continue
        modulo = nodo.module or ""
        destino = _resolver_modulo_local(ws, ruta, modulo, nodo.level)
        if destino is None or destino.resolve() == ruta.resolve():
            continue
        if destino not in cache:
            try:
                cache[destino] = nombres_exportados_python(destino.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                cache[destino] = None
        exportados = cache[destino]
        if exportados is None:
            continue
        carpeta_paquete = destino.parent if destino.name == "__init__.py" else None
        for alias in nodo.names:
            if alias.name == "*" or alias.name in exportados:
                continue
            if carpeta_paquete and ((carpeta_paquete / f"{alias.name}.py").is_file()
                                    or (carpeta_paquete / alias.name / "__init__.py").is_file()):
                continue  # from paquete import submodulo
            rel = ws.rel(destino)
            sugerencia = difflib.get_close_matches(alias.name, sorted(exportados), n=1)
            extra = f" (¿quisiste decir '{sugerencia[0]}'?)" if sugerencia else ""
            problemas.append(f"línea {nodo.lineno}: {rel} no define '{alias.name}'{extra}")
    return problemas


# ==================================================================
# PYTHON: nombres indefinidos sin dependencias
# ==================================================================
_BUILTINS = set(dir(importlib.import_module("builtins")))
_BUILTINS |= {"_", "__file__", "__name__", "__doc__", "__spec__", "__loader__", "__package__",
              "__builtins__", "__path__", "__annotations__", "__dict__", "__module__", "__qualname__",
              "__class__", "__debug__", "WindowsError", "reveal_type", "__version__"}


class _Ambito:
    def __init__(self, tipo: str, padre: Optional["_Ambito"] = None):
        self.tipo = tipo  # modulo | funcion | clase | comprension
        self.padre = padre
        self.nombres: set[str] = set()
        self.globales: set[str] = set()


class _DetectorIndefinidos(ast.NodeVisitor):
    """
    Detector conservador: solo informa un nombre si no está definido en ningún
    ámbito alcanzable ni en builtins. Si el módulo usa 'import *', exec,
    globals() o locals(), no informa nada (no se puede saber).
    """

    def __init__(self, futuro_anotaciones: bool):
        self.futuro = futuro_anotaciones
        self.modulo = _Ambito("modulo")
        self.actual = self.modulo
        self.usos: list[tuple[str, int, _Ambito]] = []
        self.dinamico = False

    # ------------------------------------------------------------ definiciones previas
    def _recolectar(self, cuerpo: Sequence[ast.AST], ambito: _Ambito) -> None:
        for sentencia in cuerpo:
            for sub in self._recorrer_sin_ambitos(sentencia):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                    ambito.nombres.add(sub.id)
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    ambito.nombres.add(sub.name)
                elif isinstance(sub, ast.Import):
                    for a in sub.names:
                        ambito.nombres.add((a.asname or a.name).split(".")[0])
                elif isinstance(sub, ast.ImportFrom):
                    for a in sub.names:
                        if a.name == "*":
                            self.dinamico = True
                        else:
                            ambito.nombres.add(a.asname or a.name)
                elif isinstance(sub, ast.ExceptHandler) and sub.name:
                    ambito.nombres.add(sub.name)
                elif isinstance(sub, ast.Global):
                    ambito.globales.update(sub.names)
                    self.modulo.nombres.update(sub.names)
                elif isinstance(sub, ast.Nonlocal):
                    ambito.nombres.update(sub.names)
                elif isinstance(sub, ast.arg):
                    ambito.nombres.add(sub.arg)
                elif sub.__class__.__name__ in ("MatchAs", "MatchStar") and getattr(sub, "name", None):
                    ambito.nombres.add(sub.name)
                elif sub.__class__.__name__ == "MatchMapping" and getattr(sub, "rest", None):
                    ambito.nombres.add(sub.rest)

    def _recorrer_sin_ambitos(self, nodo: ast.AST) -> Iterator[ast.AST]:
        """Como ast.walk pero sin entrar al cuerpo de funciones, clases, lambdas ni comprensiones."""
        pila = [nodo]
        while pila:
            actual = pila.pop()
            yield actual
            if isinstance(actual, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pila.extend(actual.decorator_list)
                pila.extend(d for d in actual.args.defaults if d is not None)
                pila.extend(d for d in actual.args.kw_defaults if d is not None)
                continue
            if isinstance(actual, ast.ClassDef):
                pila.extend(actual.decorator_list)
                pila.extend(actual.bases)
                pila.extend(k.value for k in actual.keywords)
                continue
            if isinstance(actual, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                if isinstance(actual, ast.Lambda):
                    pila.extend(d for d in actual.args.defaults if d is not None)
                else:
                    pila.append(actual.generators[0].iter)
                continue
            # La variable de la walrus dentro de comprensiones se asigna al ámbito que la contiene.
            pila.extend(ast.iter_child_nodes(actual))

    # ------------------------------------------------------------ visitas
    def analizar(self, arbol: ast.Module) -> list[tuple[str, int]]:
        self._recolectar(arbol.body, self.modulo)
        for sentencia in arbol.body:
            self.visit(sentencia)
        if self.dinamico:
            return []
        indefinidos = []
        vistos = set()
        for nombre, linea, ambito in self.usos:
            if self._definido(nombre, ambito):
                continue
            if (nombre, linea) in vistos:
                continue
            vistos.add((nombre, linea))
            indefinidos.append((nombre, linea))
        return indefinidos

    def _definido(self, nombre: str, ambito: _Ambito) -> bool:
        if nombre in _BUILTINS:
            return True
        actual: Optional[_Ambito] = ambito
        primero = True
        while actual is not None:
            # Los nombres de una clase solo se ven desde el cuerpo de la propia clase.
            if actual.tipo != "clase" or primero:
                if nombre in actual.nombres:
                    return True
            primero = False
            actual = actual.padre
        return False

    def visit_Name(self, nodo: ast.Name) -> None:
        if isinstance(nodo.ctx, ast.Load):
            if nodo.id in ("globals", "locals", "vars", "exec", "eval", "__import__"):
                self.dinamico = self.dinamico or nodo.id in ("exec", "globals", "locals")
            self.usos.append((nodo.id, nodo.lineno, self.actual))

    def _visitar_funcion(self, nodo: Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda]) -> None:
        if not isinstance(nodo, ast.Lambda):
            for d in nodo.decorator_list:
                self.visit(d)
        argumentos = nodo.args
        for d in list(argumentos.defaults) + [d for d in argumentos.kw_defaults if d is not None]:
            self.visit(d)
        con_tipos = bool(getattr(nodo, "type_params", None))
        if not isinstance(nodo, ast.Lambda) and not self.futuro and not con_tipos:
            for a in argumentos.args + argumentos.posonlyargs + argumentos.kwonlyargs:
                if a.annotation is not None:
                    self.visit(a.annotation)
            if nodo.returns is not None:
                self.visit(nodo.returns)
        ambito = _Ambito("funcion", self.actual)
        todos = argumentos.args + argumentos.posonlyargs + argumentos.kwonlyargs
        for a in todos:
            ambito.nombres.add(a.arg)
        if argumentos.vararg:
            ambito.nombres.add(argumentos.vararg.arg)
        if argumentos.kwarg:
            ambito.nombres.add(argumentos.kwarg.arg)
        cuerpo = [nodo.body] if isinstance(nodo, ast.Lambda) else nodo.body
        if isinstance(nodo, ast.Lambda):
            cuerpo = [ast.Expr(nodo.body)]
        self._recolectar(cuerpo, ambito)
        anterior, self.actual = self.actual, ambito
        for sentencia in cuerpo:
            self.visit(sentencia)
        self.actual = anterior

    visit_FunctionDef = _visitar_funcion
    visit_AsyncFunctionDef = _visitar_funcion
    visit_Lambda = _visitar_funcion

    def visit_ClassDef(self, nodo: ast.ClassDef) -> None:
        for d in nodo.decorator_list:
            self.visit(d)
        if not getattr(nodo, "type_params", None):
            for b in nodo.bases:
                self.visit(b)
            for k in nodo.keywords:
                self.visit(k.value)
        ambito = _Ambito("clase", self.actual)
        self._recolectar(nodo.body, ambito)
        anterior, self.actual = self.actual, ambito
        for sentencia in nodo.body:
            self.visit(sentencia)
        self.actual = anterior

    def _visitar_comprension(self, nodo) -> None:
        ambito = _Ambito("comprension", self.actual)
        for gen in nodo.generators:
            for sub in ast.walk(gen.target):
                if isinstance(sub, ast.Name):
                    ambito.nombres.add(sub.id)
        # El primer iterable se evalúa en el ámbito de afuera.
        self.visit(nodo.generators[0].iter)
        anterior, self.actual = self.actual, ambito
        for k, gen in enumerate(nodo.generators):
            if k:
                self.visit(gen.iter)
            for condicion in gen.ifs:
                self.visit(condicion)
        for sub in ast.walk(nodo):
            if isinstance(sub, ast.NamedExpr):
                anterior.nombres.add(sub.target.id)
        if isinstance(nodo, ast.DictComp):
            self.visit(nodo.key)
            self.visit(nodo.value)
        else:
            self.visit(nodo.elt)
        self.actual = anterior

    visit_ListComp = _visitar_comprension
    visit_SetComp = _visitar_comprension
    visit_GeneratorExp = _visitar_comprension
    visit_DictComp = _visitar_comprension

    def visit_AnnAssign(self, nodo: ast.AnnAssign) -> None:
        if not self.futuro and self.actual.tipo != "funcion":
            self.visit(nodo.annotation)
        if nodo.value is not None:
            self.visit(nodo.value)
        self.visit(nodo.target)

    def visit_arg(self, nodo: ast.arg) -> None:
        return

    def visit_Constant(self, nodo: ast.Constant) -> None:
        return


def nombres_indefinidos_python(texto: str) -> list[tuple[str, int]]:
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return []
    futuro = any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names)
        for n in arbol.body
    )
    detector = _DetectorIndefinidos(futuro)
    try:
        return detector.analizar(arbol)
    except RecursionError:
        return []


def _nombres_indefinidos(ws: Workspace, rel: str, texto: str) -> Optional[Resultado]:
    ruff = shutil.which("ruff")
    if ruff:
        r = ejecutar(
            [ruff, "check", "--isolated", "--no-cache", "--select", "E9,F63,F7,F82",
             "--output-format", "concise", rel],
            cwd=ws.raiz,
            timeout=30,
        )
        if r.codigo in (0, 1):
            r.comando = f"ruff (nombres indefinidos) {rel}"
            r.archivo = rel
            if r.ok:
                r.stdout = ""
            return r
    if _pyflakes_api is not None:
        salida, errores = io.StringIO(), io.StringIO()
        _pyflakes_api.check(texto, rel, _pyflakes_reporter.Reporter(salida, errores))
        graves = [
            l for l in salida.getvalue().splitlines()
            if "undefined name" in l or "undefined local" in l
        ]
        return Resultado(not graves, f"pyflakes (nombres indefinidos) {rel}",
                         0 if not graves else 1, stderr="\n".join(graves), archivo=rel)
    indefinidos = nombres_indefinidos_python(texto)
    lineas = [f"{rel}:{linea}: nombre indefinido '{nombre}'" for nombre, linea in indefinidos[:30]]
    return Resultado(not lineas, f"ast (nombres indefinidos) {rel}", 0 if not lineas else 1,
                     stderr="\n".join(lineas), archivo=rel)


def funciones_vacias_python(texto: str) -> list[tuple[str, int]]:
    """Funciones cuyo cuerpo es solo pass / ... / raise NotImplementedError (sin ser abstractas)."""
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return []
    vacias = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decoradores = " ".join(ast.unparse(d) for d in nodo.decorator_list)
        if "abstract" in decoradores or "overload" in decoradores:
            continue
        cuerpo = list(nodo.body)
        if cuerpo and isinstance(cuerpo[0], ast.Expr) and isinstance(getattr(cuerpo[0], "value", None), ast.Constant) \
                and isinstance(cuerpo[0].value.value, str):
            cuerpo = cuerpo[1:]
        if not cuerpo:
            vacias.append((nodo.name, nodo.lineno))
            continue
        if len(cuerpo) != 1:
            continue
        s = cuerpo[0]
        if isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is Ellipsis):
            vacias.append((nodo.name, nodo.lineno))
        elif isinstance(s, ast.Raise) and s.exc is not None and "NotImplementedError" in ast.unparse(s.exc):
            vacias.append((nodo.name, nodo.lineno))
    return vacias


def advertencias_python(texto: str) -> list[str]:
    """Problemas que no rompen la compilación pero casi siempre son bugs de un modelo chico."""
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return []
    avisos = []
    vistos: dict[str, int] = {}
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if nodo.name in vistos:
                avisos.append(f"'{nodo.name}' se define dos veces (líneas {vistos[nodo.name]} y {nodo.lineno}): "
                              "la segunda pisa a la primera")
            vistos[nodo.name] = nodo.lineno
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef):
            metodos: dict[str, int] = {}
            for sub in nodo.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decoradores = " ".join(ast.unparse(d) for d in sub.decorator_list)
                    if sub.name in metodos and "setter" not in decoradores and "overload" not in decoradores:
                        avisos.append(f"el método {nodo.name}.{sub.name} se define dos veces (líneas "
                                      f"{metodos[sub.name]} y {sub.lineno})")
                    metodos[sub.name] = sub.lineno
        if isinstance(nodo, ast.ExceptHandler) and nodo.type is None:
            if len(nodo.body) == 1 and isinstance(nodo.body[0], ast.Pass):
                avisos.append(f"línea {nodo.lineno}: 'except: pass' oculta todos los errores")
    for nombre, linea in funciones_vacias_python(texto)[:8]:
        avisos.append(f"línea {linea}: la función '{nombre}' está vacía (pass/.../NotImplementedError)")
    return avisos


def _validar_python(ws: Workspace, ruta: Path, rel: str) -> list[Resultado]:
    texto = ruta.read_text(encoding="utf-8", errors="replace")
    try:
        arbol = ast.parse(texto, filename=rel)
        compile(arbol, rel, "exec", dont_inherit=True)
    except SyntaxError as e:
        detalle = f"{type(e).__name__}: {e.msg} (línea {e.lineno}, columna {e.offset})"
        if e.text:
            detalle += f"\n    {e.text.rstrip()}\n    {' ' * max(0, (e.offset or 1) - 1)}^"
        pista = pista_sintaxis_python(texto, e)
        if pista:
            detalle += f"\nPista: {pista}"
        return [Resultado(False, f"py_compile {rel}", 1, stderr=detalle, archivo=rel)]
    except ValueError as e:
        return [Resultado(False, f"py_compile {rel}", 1, stderr=str(e), archivo=rel)]

    resultados = [Resultado(True, f"py_compile {rel}", 0, archivo=rel)]
    indefinidos = _nombres_indefinidos(ws, rel, texto)
    if indefinidos is not None:
        resultados.append(indefinidos)
    faltan = imports_faltantes(ws, ruta, arbol)
    resultados.append(Resultado(
        not faltan,
        f"imports {rel}",
        0 if not faltan else 1,
        stderr=("Módulos no instalados ni presentes en el proyecto: " + ", ".join(faltan)
                + "\n(Instalalos con pip o usá la librería estándar.)") if faltan else "",
        archivo=rel,
    ))
    rotos = imports_locales_rotos(ws, ruta, arbol)
    if rotos:
        resultados.append(Resultado(False, f"imports-locales {rel}", 1, stderr="\n".join(rotos), archivo=rel))
    return resultados


def pista_sintaxis_python(texto: str, error: SyntaxError) -> str:
    """Pistas concretas para los errores de sintaxis más comunes de un modelo chico."""
    msg = (error.msg or "").lower()
    lineas = texto.splitlines()
    linea = lineas[error.lineno - 1] if error.lineno and 0 < error.lineno <= len(lineas) else ""
    if "unterminated triple-quoted" in msg or "eof while scanning triple" in msg:
        return "hay un docstring o string triple sin cerrar; buscá un \"\"\" o ''' sin pareja."
    if "unexpected eof" in msg or "was never closed" in msg:
        return "falta cerrar un paréntesis/corchete/llave abierto antes de esa línea, o el archivo quedó cortado."
    if "unindent does not match" in msg or "unexpected indent" in msg:
        return "mezcla de indentaciones: usá 4 espacios en todo el archivo (sin tabs)."
    if "expected an indented block" in msg:
        return "después de una línea que termina en ':' tiene que venir un bloque indentado (al menos 'pass')."
    if "invalid character" in msg and any(ord(ch) > 127 for ch in linea):
        return "hay un carácter Unicode raro (comillas tipográficas “ ” o un guion largo); reemplazalo por ASCII."
    if "f-string" in msg:
        return "revisá las llaves y comillas dentro del f-string (no reutilices el mismo tipo de comilla adentro)."
    if "invalid syntax" in msg and linea.strip().startswith(("<<<<<<<", "=======", ">>>>>>>")):
        return "quedaron marcadores SEARCH/REPLACE dentro del archivo; borralos."
    if "invalid syntax" in msg and re.search(r"^\s*(\.\.\.|…)\s*$", linea):
        return "hay un '...' suelto: el código quedó incompleto."
    return ""


# ==================================================================
# JS / HTML / OTROS
# ==================================================================
_ERRORES_ESM = ("Cannot use import statement outside a module", "Unexpected token 'export'",
                "await is only valid", "Cannot use 'import.meta' outside a module")


def _node_check_texto(ws: Workspace, codigo: str, sufijo: str) -> Resultado:
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / f"check{sufijo}"
        destino.write_text(codigo, encoding="utf-8")
        return ejecutar(["node", "--check", str(destino)], cwd=ws.raiz, timeout=30)


_RE_IMPORT_JS = re.compile(
    r"""(?:^|[;\n])\s*import\s+(?:(?P<que>[\w$*{}\s,]+?)\s+from\s+)?["'](?P<ruta>\.{1,2}/[^"']+)["']"""
    r"""|require\(\s*["'](?P<req>\.{1,2}/[^"']+)["']\s*\)""",
    re.M,
)
_EXTENSIONES_JS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json")


def _resolver_js(base: Path, ruta: str) -> Optional[Path]:
    destino = (base / ruta)
    candidatos = [destino] + [destino.with_name(destino.name + ext) for ext in _EXTENSIONES_JS]
    candidatos += [destino / f"index{ext}" for ext in _EXTENSIONES_JS]
    for c in candidatos:
        if c.is_file():
            return c
    return None


def exports_js(texto: str) -> Optional[set[str]]:
    if re.search(r"export\s*\*\s*from", texto) or "module.exports" in texto or "exports." in texto:
        return None
    nombres = set(re.findall(r"export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|class|const|let|var)\s+([\w$]+)", texto))
    for grupo in re.findall(r"export\s*\{([^}]*)\}", texto):
        for parte in grupo.split(","):
            parte = parte.strip()
            if not parte:
                continue
            nombres.add(re.split(r"\s+as\s+", parte)[-1].strip())
    if re.search(r"export\s+default\b", texto):
        nombres.add("default")
    return nombres


def imports_js_rotos(ws: Workspace, ruta: Path, texto: str) -> list[str]:
    problemas = []
    sin_comentarios = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    sin_comentarios = re.sub(r"(^|[^:\"'])//[^\n]*", r"\1", sin_comentarios)
    for m in _RE_IMPORT_JS.finditer(sin_comentarios):
        destino_txt = m.group("ruta") or m.group("req")
        linea = sin_comentarios.count("\n", 0, m.start()) + 1
        destino = _resolver_js(ruta.parent, destino_txt)
        if destino is None:
            problemas.append(f"línea ~{linea}: no existe el archivo importado '{destino_txt}'")
            continue
        que = (m.group("que") or "").strip()
        llaves = re.search(r"\{([^}]*)\}", que)
        if not llaves or destino.suffix == ".json":
            continue
        try:
            exportados = exports_js(destino.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if exportados is None:
            continue
        for parte in llaves.group(1).split(","):
            nombre = re.split(r"\s+as\s+", parte.strip())[0].strip()
            if nombre and nombre not in exportados:
                problemas.append(f"línea ~{linea}: {ws.rel(destino)} no exporta '{nombre}'")
    return problemas


def _validar_js(ws: Workspace, ruta: Path, rel: str) -> list[Resultado]:
    resultados = []
    if not shutil.which("node"):
        resultados.append(Resultado(True, f"node --check {rel}", 0, omitido=True,
                                    stdout="node no está instalado (pkg install nodejs)", archivo=rel))
        balance = balance_llaves(ruta.read_text(encoding="utf-8", errors="replace"), "js")
        if balance:
            resultados.append(Resultado(False, f"llaves {rel}", 1, stderr=balance, archivo=rel))
    else:
        r = ejecutar(["node", "--check", rel], cwd=ws.raiz, timeout=30)
        if not r.ok and any(m in r.stderr for m in _ERRORES_ESM) and ruta.suffix == ".js":
            # JS de navegador con import/export: se revalida como módulo ES.
            r2 = _node_check_texto(ws, ruta.read_text(encoding="utf-8", errors="replace"), ".mjs")
            r2.stderr = r2.stderr.replace(r2.comando.split()[-1], rel)
            r = r2
        r.comando = f"node --check {rel}"
        r.archivo = rel
        resultados.append(r)
    rotos = imports_js_rotos(ws, ruta, ruta.read_text(encoding="utf-8", errors="replace"))
    if rotos:
        resultados.append(Resultado(False, f"imports-js {rel}", 1, stderr="\n".join(rotos), archivo=rel))
    return resultados


_SCRIPT_HTML = re.compile(r"<script(?![^>]*\bsrc\s*=)([^>]*)>(.*?)</script\s*>", re.S | re.I)
_RECURSOS_HTML = re.compile(r"""<(?:script|link|img|source)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"'#?]+)""", re.I)


def recursos_html_faltantes(ws: Workspace, ruta: Path, texto: str) -> list[str]:
    faltan = []
    for m in _RECURSOS_HTML.finditer(texto):
        destino = m.group(1).strip()
        if not destino or re.match(r"^(https?:|//|data:|mailto:|tel:|javascript:|\{\{|\$\{)", destino):
            continue
        if destino.startswith("/"):
            candidato = ws.raiz / destino.lstrip("/")
        else:
            candidato = ruta.parent / destino
        if not candidato.exists():
            linea = texto.count("\n", 0, m.start()) + 1
            faltan.append(f"línea {linea}: referencia a '{destino}' que no existe")
    return faltan


def _validar_html(ws: Workspace, ruta: Path, rel: str) -> list[Resultado]:
    texto = ruta.read_text(encoding="utf-8", errors="replace")
    resultados = []
    faltan = recursos_html_faltantes(ws, ruta, texto)
    if faltan:
        resultados.append(Resultado(False, f"recursos-html {rel}", 1, stderr="\n".join(faltan), archivo=rel))
    if not shutil.which("node"):
        return resultados
    for numero, m in enumerate(_SCRIPT_HTML.finditer(texto), start=1):
        atributos, codigo = m.group(1).lower(), m.group(2)
        tipo = re.search(r"type\s*=\s*[\"']?([\w/+-]+)", atributos)
        tipo = tipo.group(1) if tipo else ""
        if tipo and tipo not in ("module", "text/javascript", "application/javascript"):
            continue
        if not codigo.strip():
            continue
        linea_inicio = texto.count("\n", 0, m.start(2))
        # Se rellena con saltos de línea para que los números de línea coincidan con el HTML.
        r = _node_check_texto(ws, "\n" * linea_inicio + codigo, ".mjs" if tipo == "module" else ".js")
        if not r.ok and any(e in r.stderr for e in _ERRORES_ESM):
            r = _node_check_texto(ws, "\n" * linea_inicio + codigo, ".mjs")
        r.comando = f"node --check <script #{numero}> {rel}"
        r.archivo = rel
        resultados.append(r)
    return resultados


def _validar_css(ruta: Path, rel: str) -> list[Resultado]:
    texto = re.sub(r"/\*.*?\*/", "", ruta.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    texto = re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", "", texto)
    nivel = 0
    for numero, linea in enumerate(texto.splitlines(), start=1):
        for ch in linea:
            if ch == "{":
                nivel += 1
            elif ch == "}":
                nivel -= 1
                if nivel < 0:
                    return [Resultado(False, f"css-llaves {rel}", 1,
                                      stderr=f"'}}' sin abrir en la línea {numero}", archivo=rel)]
    if nivel:
        return [Resultado(False, f"css-llaves {rel}", 1,
                          stderr=f"Faltan {nivel} '}}' de cierre", archivo=rel)]
    return [Resultado(True, f"css-llaves {rel}", 0, archivo=rel)]


_PARES = {")": "(", "]": "[", "}": "{"}


def balance_llaves(texto: str, lenguaje: str = "c") -> str:
    """
    Verifica que (), [] y {} estén balanceados ignorando strings y comentarios.
    Devuelve "" si está bien o una descripción del primer problema.
    """
    pila: list[tuple[str, int]] = []
    i, n, linea = 0, len(texto), 1
    comentario_linea = "#" if lenguaje in ("py", "sh", "rb") else "//"
    while i < n:
        ch = texto[i]
        if ch == "\n":
            linea += 1
            i += 1
            continue
        if texto.startswith(comentario_linea, i):
            fin = texto.find("\n", i)
            i = n if fin < 0 else fin
            continue
        if lenguaje not in ("py", "sh", "rb") and texto.startswith("/*", i):
            fin = texto.find("*/", i + 2)
            if fin < 0:
                return f"comentario /* sin cerrar desde la línea {linea}"
            linea += texto.count("\n", i, fin)
            i = fin + 2
            continue
        if ch in "\"'`":
            j = i + 1
            while j < n and texto[j] != ch:
                if texto[j] == "\\":
                    j += 1
                elif texto[j] == "\n" and ch != "`":
                    break
                j += 1
            linea += texto.count("\n", i, j)
            i = j + 1
            continue
        if ch in "([{":
            pila.append((ch, linea))
        elif ch in ")]}":
            if not pila:
                return f"'{ch}' sin abrir en la línea {linea}"
            abierto, linea_abierto = pila.pop()
            if abierto != _PARES[ch]:
                return f"'{ch}' en la línea {linea} cierra '{abierto}' abierto en la línea {linea_abierto}"
        i += 1
    if pila:
        abierto, linea_abierto = pila[-1]
        return f"'{abierto}' abierto en la línea {linea_abierto} nunca se cierra ({len(pila)} sin cerrar en total)"
    return ""


_COMPILADORES = {
    ".c": [("clang", ["-fsyntax-only"]), ("gcc", ["-fsyntax-only"])],
    ".h": [("clang", ["-fsyntax-only"]), ("gcc", ["-fsyntax-only"])],
    ".cpp": [("clang++", ["-fsyntax-only", "-std=c++17"]), ("g++", ["-fsyntax-only", "-std=c++17"])],
    ".hpp": [("clang++", ["-fsyntax-only", "-std=c++17"]), ("g++", ["-fsyntax-only", "-std=c++17"])],
    ".cc": [("clang++", ["-fsyntax-only", "-std=c++17"]), ("g++", ["-fsyntax-only", "-std=c++17"])],
    ".go": [("gofmt", ["-e", "-l"])],
    ".php": [("php", ["-l"])],
    ".rb": [("ruby", ["-c"])],
    ".lua": [("luac", ["-p"]), ("luac5.4", ["-p"])],
}


def _validar_compilado(ws: Workspace, ruta: Path, rel: str) -> list[Resultado]:
    sufijo = ruta.suffix.lower()
    for ejecutable, args in _COMPILADORES.get(sufijo, []):
        if shutil.which(ejecutable):
            r = ejecutar([ejecutable, *args, rel], cwd=ws.raiz, timeout=60)
            if ejecutable == "gofmt":
                r.ok = r.codigo == 0 and "expected" not in r.stderr
                r.stdout = ""
            r.comando = f"{ejecutable} {rel}"
            r.archivo = rel
            return [r]
    lenguaje = {".rb": "rb", ".lua": "lua"}.get(sufijo, "c")
    if lenguaje == "lua":
        return []
    problema = balance_llaves(ruta.read_text(encoding="utf-8", errors="replace"), lenguaje)
    return [Resultado(not problema, f"llaves {rel}", 0 if not problema else 1, stderr=problema, archivo=rel)]


def _validar_yaml(ruta: Path, rel: str) -> list[Resultado]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return []
    try:
        list(yaml.safe_load_all(ruta.read_text(encoding="utf-8")))
        return [Resultado(True, f"yaml {rel}", 0, archivo=rel)]
    except Exception as e:  # yaml.YAMLError y errores de decodificación
        return [Resultado(False, f"yaml {rel}", 1, stderr=f"YAML inválido: {e}", archivo=rel)]


def validar_archivo(ws: Workspace, rel: str) -> list[Resultado]:
    try:
        ruta = ws.ruta(rel)
    except ValueError as e:
        return [Resultado(False, f"validar {rel}", 2, stderr=str(e), archivo=rel)]
    rel = ws.rel(ruta)
    if not ruta.is_file():
        return [Resultado(False, f"validar {rel}", 2, stderr="El archivo no existe.", archivo=rel)]

    sufijo = ruta.suffix.lower()
    try:
        if sufijo == ".py":
            return _validar_python(ws, ruta, rel)
        if sufijo in (".sh", ".bash"):
            r = ejecutar(["bash", "-n", rel], cwd=ws.raiz, timeout=20)
            r.archivo = rel
            return [r]
        if sufijo in (".js", ".mjs", ".cjs", ".jsx"):
            return _validar_js(ws, ruta, rel)
        if sufijo in (".ts", ".tsx"):
            problema = balance_llaves(ruta.read_text(encoding="utf-8", errors="replace"), "js")
            resultados = [Resultado(not problema, f"llaves {rel}", 0 if not problema else 1, stderr=problema, archivo=rel)]
            rotos = imports_js_rotos(ws, ruta, ruta.read_text(encoding="utf-8", errors="replace"))
            if rotos:
                resultados.append(Resultado(False, f"imports-ts {rel}", 1, stderr="\n".join(rotos), archivo=rel))
            return resultados
        if sufijo in (".html", ".htm"):
            return _validar_html(ws, ruta, rel)
        if sufijo == ".css":
            return _validar_css(ruta, rel)
        if sufijo in (".json", ".webmanifest"):
            try:
                json.loads(ruta.read_text(encoding="utf-8"))
                return [Resultado(True, f"json {rel}", 0, archivo=rel)]
            except json.JSONDecodeError as e:
                return [Resultado(False, f"json {rel}", 1,
                                  stderr=f"JSON inválido: {e.msg} (línea {e.lineno}, columna {e.colno})", archivo=rel)]
            except (ValueError, UnicodeDecodeError) as e:
                return [Resultado(False, f"json {rel}", 1, stderr=f"JSON inválido: {e}", archivo=rel)]
        if sufijo == ".toml":
            try:
                import tomllib
            except ImportError:
                return []
            try:
                tomllib.loads(ruta.read_text(encoding="utf-8"))
                return [Resultado(True, f"toml {rel}", 0, archivo=rel)]
            except (ValueError, UnicodeDecodeError) as e:
                return [Resultado(False, f"toml {rel}", 1, stderr=f"TOML inválido: {e}", archivo=rel)]
        if sufijo in (".yaml", ".yml"):
            return _validar_yaml(ruta, rel)
        if sufijo in _COMPILADORES or sufijo in (".java", ".kt", ".rs", ".swift", ".dart", ".cs"):
            return _validar_compilado(ws, ruta, rel)
    except OSError as e:
        return [Resultado(False, f"validar {rel}", 1, stderr=f"{type(e).__name__}: {e}", archivo=rel)]
    return []


def validar_archivos(ws: Workspace, rels: list[str]) -> list[Resultado]:
    resultados = []
    for rel in rels:
        if (ws.raiz / rel).is_file():
            resultados.extend(validar_archivo(ws, rel))
    return resultados


def fallos(resultados: list[Resultado]) -> list[Resultado]:
    return [r for r in resultados if not r.ok]


def resumen_validacion(resultados: list[Resultado], limite: int = 3000) -> str:
    if not resultados:
        return "sin validadores aplicables"
    malos = fallos(resultados)
    if not malos:
        return "OK (" + ", ".join(r.comando.split(" ")[0] for r in resultados if not r.omitido) + ")"
    return "\n\n".join(r.resumen(limite) for r in malos)


# ==================================================================
# TESTS
# ==================================================================
def detectar_comando_tests(ws: Workspace, completo: bool = False) -> Optional[tuple[str, str]]:
    """
    Comando de la suite de tests. completo=True no corta en el primer fallo
    (sirve para contar cuántos tests pasan, p. ej. en el torneo).
    """
    raiz = ws.raiz
    local = ws.config_local().get("comando_tests")
    if isinstance(local, str) and local.strip():
        return local.strip(), "config .reaper"

    py = shlex.quote(sys.executable)
    hay_tests_py = (
        (raiz / "tests").is_dir() and any((raiz / "tests").rglob("*.py"))
        or (raiz / "test").is_dir() and any((raiz / "test").rglob("*.py"))
        or any(raiz.glob("test_*.py"))
        or any(raiz.glob("*_test.py"))
    )
    if hay_tests_py:
        if importlib.util.find_spec("pytest") is not None:
            corte = "" if completo else " -x"
            return f"{py} -m pytest -q{corte} --tb=short -p no:cacheprovider", "pytest"
        for carpeta in ("tests", "test"):
            if (raiz / carpeta).is_dir():
                if (raiz / carpeta / "__init__.py").is_file():
                    return f"{py} -m unittest discover -s {carpeta} -t .", "unittest"
                return f"{py} -m unittest discover -s {carpeta}", "unittest"
        return f"{py} -m unittest discover", "unittest"

    paquete = raiz / "package.json"
    if paquete.is_file():
        try:
            datos = json.loads(paquete.read_text(encoding="utf-8"))
            script = (datos.get("scripts") or {}).get("test")
            if script and "no test specified" not in script and shutil.which("npm"):
                return "npm test --silent", "npm test"
        except (OSError, ValueError):
            pass
    if shutil.which("node") and any((raiz / d).is_dir() for d in ("tests", "test")):
        js = [p for d in ("tests", "test") for p in (raiz / d).glob("*.test.*js")]
        if js:
            return "node --test " + " ".join(shlex.quote(ws.rel(p)) for p in sorted(js)), "node --test"
    if (raiz / "go.mod").is_file() and shutil.which("go"):
        return "go test ./...", "go test"
    if (raiz / "Cargo.toml").is_file() and shutil.which("cargo"):
        return "cargo test", "cargo test"
    makefile = raiz / "Makefile"
    if makefile.is_file() and shutil.which("make"):
        try:
            if re.search(r"^test\s*:", makefile.read_text(encoding="utf-8"), re.M):
                return "make test", "make test"
        except OSError:
            pass
    return None


def ejecutar_tests(ws: Workspace, timeout: int = 300, completo: bool = False) -> Optional[Resultado]:
    detectado = detectar_comando_tests(ws, completo=completo)
    if not detectado:
        return None
    comando, _nombre = detectado
    r = ejecutar(comando, cwd=ws.raiz, timeout=timeout, shell=True)
    combinado = r.stdout + r.stderr
    if r.codigo == 5 or "NO TESTS RAN" in combinado or re.search(r"\bRan 0 tests?\b", combinado):
        r.ok, r.omitido = True, True
        r.stdout = "No se encontraron tests para ejecutar. " + r.stdout
    return r


def es_crash_real(r: Resultado) -> bool:
    """Un exit != 0 controlado (uso incorrecto, validación) no es un bug a reparar."""
    if r.timeout or r.codigo in (126, 127) or r.codigo < 0:
        return True
    combinado = f"{r.stdout}\n{r.stderr}"
    patrones = (
        "Traceback (most recent call last)", "SyntaxError", "IndentationError",
        "ModuleNotFoundError", "ImportError", "NameError", "UnboundLocalError",
        "AttributeError", "TypeError:", "RecursionError", "ReferenceError",
        "Segmentation fault",
    )
    return any(p in combinado for p in patrones)
