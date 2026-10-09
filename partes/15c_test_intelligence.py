"""
Test Intelligence (v9, Fase 1): REAPER mira los tests con lupa antes de creerse un "17/17 verde".

Ataca los fallos reales de v8 (MASTER SPEC §1):
  - tests tautológicos (assertTrue(True), assertEqual(1, 1), x == x): no discriminan nada;
  - mocks que reemplazan EL sistema bajo prueba (patch de la función que el test dice probar);
  - "integración" que en realidad mockea subprocess/socket/open: no es integración real;
  - valor esperado FABRICADO por el propio mock (return_value="X" ... assertEqual(r, "X"));
  - clasificación UNIT / INTEGRATION / E2E / ... y si el test está MAL ETIQUETADO.

Todo es análisis estático con AST (no ejecuta nada). La MutationProbe (ejecuta) está en otra función.
Es la base del Evidence Gate: una afirmación "los tests pasan" vale menos si los tests no discriminan.
"""

NIVELES_TEST = ("unit", "integration", "e2e", "smoke", "regression", "property", "security", "performance")

# Operaciones de E/S reales: mockearlas convierte una "integración" en unit.
_IO_REAL = (
    "subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_output", "subprocess.check_call",
    "os.system", "os.popen", "os.exec", "pty.spawn",
    "socket.socket", "socket.create_connection",
    "urllib.request.urlopen", "requests.get", "requests.post", "requests.request", "requests.put",
    "http.client.HTTPConnection", "httpx.get", "httpx.post", "httpx.Client",
    "sqlite3.connect", "psycopg2.connect", "pymysql.connect",
    "builtins.open", "open", "pathlib.Path.open", "io.open",
    "smtplib.SMTP", "ftplib.FTP",
)
_OPS_ARCHIVO = ("open", "subprocess.run", "subprocess.Popen", "os.system", "Path.open", "Path.write_text",
                "Path.read_text")


@dataclass
class ProblemaTest:
    tipo: str                 # TAUTOLOGIA | MOCK_SISTEMA_BAJO_PRUEBA | INTEGRACION_MOCKEADA | VALOR_DESDE_MOCK | SIN_ASSERT | MAL_ETIQUETADO
    test: str
    linea: int
    severidad: str            # alta | media | baja
    detalle: str


@dataclass
class InfoTest:
    nombre: str
    linea: int
    nivel_declarado: str = ""     # por nombre/docstring/marcador
    nivel_real: str = "unit"      # lo que de verdad hace
    mocks: list = field(default_factory=list)
    asserts: int = 0
    tautologias: int = 0


@dataclass
class ResultadoInteligencia:
    tests: list = field(default_factory=list)       # InfoTest
    problemas: list = field(default_factory=list)   # ProblemaTest

    @property
    def ok(self) -> bool:
        return not any(p.severidad == "alta" for p in self.problemas)

    @property
    def discriminacion(self) -> float:
        """Fracción de tests sin tautologías y con al menos un assert real (1.0 = todos discriminan)."""
        if not self.tests:
            return 1.0
        buenos = sum(1 for t in self.tests if t.asserts > t.tautologias and t.asserts > 0)
        return round(buenos / len(self.tests), 2)


def _ti_walk(nodo, tipo):
    return [n for n in ast.walk(nodo) if isinstance(n, tipo)]


def _ti_src(nodo) -> str:
    try:
        return ast.unparse(nodo)
    except Exception:
        return ""


def _es_tautologia(nodo) -> Optional[str]:
    """Si el assert/compare no puede distinguir nada, devuelve el motivo."""
    # assert <constante>  → assert True / assert 1 / assert "x"
    if isinstance(nodo, ast.Constant):
        return f"constante {nodo.value!r}: siempre es {'verdadera' if nodo.value else 'falsa'}"
    if isinstance(nodo, ast.Compare) and len(nodo.ops) == 1:
        izq, der = _ti_src(nodo.left), _ti_src(nodo.comparators[0])
        op = nodo.ops[0]
        if izq == der and isinstance(op, (ast.Eq, ast.Is, ast.LtE, ast.GtE)):
            return f"{izq} comparado consigo mismo"
        if izq == der and isinstance(op, (ast.NotEq, ast.IsNot, ast.Lt, ast.Gt)):
            return f"{izq} != {der}: siempre falso"
        if isinstance(nodo.left, ast.Constant) and isinstance(nodo.comparators[0], ast.Constant):
            return f"dos constantes ({izq} {_ti_sym(op)} {der}): no depende del código"
    return None


def _ti_sym(op) -> str:
    return {ast.Eq: "==", ast.NotEq: "!=", ast.Is: "is", ast.IsNot: "is not",
            ast.Lt: "<", ast.Gt: ">", ast.LtE: "<=", ast.GtE: ">="}.get(type(op), "?")


_ASSERT_UNO = {"assertTrue", "assertFalse", "assertIsNone", "assertIsNotNone", "assertIsInstance"}
_ASSERT_DOS = {"assertEqual", "assertNotEqual", "assertIs", "assertIsNot", "assertGreater", "assertLess",
               "assertGreaterEqual", "assertLessEqual", "assertAlmostEqual"}
_CONST_TRIVIAL = {"assertTrue": True, "assertFalse": False, "assertIsNone": None}


def _tautologia_en_assert_metodo(call: ast.Call) -> Optional[str]:
    metodo = call.func.attr if isinstance(call.func, ast.Attribute) else ""
    args = call.args
    if metodo in _ASSERT_UNO and args:
        a = args[0]
        if isinstance(a, ast.Constant):
            if metodo in _CONST_TRIVIAL and a.value == _CONST_TRIVIAL[metodo]:
                return f"{metodo}({a.value!r}): no prueba nada"
            if metodo == "assertTrue" and a.value:
                return f"{metodo}({a.value!r}): siempre verdadero"
            if metodo == "assertFalse" and not a.value:
                return f"{metodo}({a.value!r}): siempre verdadero"
    if metodo in _ASSERT_DOS and len(args) >= 2:
        a, b = _ti_src(args[0]), _ti_src(args[1])
        if a == b and metodo in ("assertEqual", "assertIs", "assertAlmostEqual", "assertGreaterEqual",
                                  "assertLessEqual"):
            return f"{metodo}({a}, {b}): compara algo consigo mismo"
        if isinstance(args[0], ast.Constant) and isinstance(args[1], ast.Constant) and metodo == "assertEqual":
            if args[0].value == args[1].value:
                return f"{metodo}({a}, {b}): dos constantes iguales"
    return None


def _patches_de(nodo) -> list[tuple[str, int, Optional[ast.Call]]]:
    """Objetivos mockeados en un test: (target, línea, call). Cubre @patch, with patch(), patch.object()."""
    salida = []
    decoradores = getattr(nodo, "decorator_list", [])
    for call in _ti_walk(nodo, ast.Call) + [d for d in decoradores if isinstance(d, ast.Call)]:
        f = _ti_src(call.func)
        if not (f.endswith("patch") or f.endswith("patch.object") or f == "mock.patch" or f.endswith(".patch")):
            continue
        if f.endswith("object") and len(call.args) >= 2:
            base = _ti_src(call.args[0])
            attr = call.args[1].value if isinstance(call.args[1], ast.Constant) else _ti_src(call.args[1])
            objetivo = f"{base}.{attr}"
        elif call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            objetivo = call.args[0].value
        else:
            continue
        salida.append((objetivo, getattr(call, "lineno", nodo.lineno), call))
    return salida


def _valores_de_mock(call: ast.Call) -> list:
    """Literales que un patch inyecta como resultado: return_value=, side_effect=, Mock(stdout=...), etc."""
    valores = []
    for kw in call.keywords:
        if kw.arg in ("return_value", "side_effect") and isinstance(kw.value, ast.Constant):
            valores.append(kw.value.value)
        # patch(..., return_value=Mock(stdout="X", returncode=0))
        if kw.arg == "return_value" and isinstance(kw.value, ast.Call):
            for kw2 in kw.value.keywords:
                if isinstance(kw2.value, ast.Constant):
                    valores.append(kw2.value.value)
    return valores


def _importa_sujetos(arbol: ast.Module) -> dict[str, str]:
    """Nombres importados con su módulo origen: {'procesar': 'app.core', 'run': 'subprocess'}."""
    sujetos = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module:
            for alias in nodo.names:
                sujetos[alias.asname or alias.name] = nodo.module
        elif isinstance(nodo, ast.Import):
            for alias in nodo.names:
                sujetos[alias.asname or alias.name.split(".")[0]] = alias.name
    return sujetos


def _nivel_declarado(nombre: str, docstring: str, decoradores: list) -> str:
    texto = (nombre + " " + (docstring or "") + " " + " ".join(_ti_src(d) for d in decoradores)).lower()
    for nivel in ("e2e", "end_to_end", "end-to-end"):
        if nivel in texto:
            return "e2e"
    for clave, nivel in (("integration", "integration"), ("integrac", "integration"), ("security", "security"),
                         ("perf", "performance"), ("smoke", "smoke"), ("property", "property"), ("regress", "regression")):
        if clave in texto:
            return nivel
    return ""


def analizar_tests_python(fuente: str) -> ResultadoInteligencia:
    """Análisis estático de un archivo de tests Python. No ejecuta nada."""
    res = ResultadoInteligencia()
    try:
        arbol = ast.parse(fuente)
    except SyntaxError:
        return res
    sujetos = _importa_sujetos(arbol)
    nombres_importados = set(sujetos)

    for fn in ast.walk(arbol):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not fn.name.startswith("test"):
            continue
        doc = ast.get_docstring(fn) or ""
        info = InfoTest(fn.name, fn.lineno, nivel_declarado=_nivel_declarado(fn.name, doc, fn.decorator_list))

        # ---- asserts y tautologías
        asserts = 0
        for a in _ti_walk(fn, ast.Assert):
            asserts += 1
            motivo = _es_tautologia(a.test)
            if motivo:
                info.tautologias += 1
                res.problemas.append(ProblemaTest("TAUTOLOGIA", fn.name, a.lineno, "alta",
                                                   f"assert {_ti_src(a.test)}: {motivo}"))
        for call in _ti_walk(fn, ast.Call):
            metodo = call.func.attr if isinstance(call.func, ast.Attribute) else ""
            if metodo in _ASSERT_UNO | _ASSERT_DOS or metodo == "assertRaises":
                asserts += 1
                motivo = _tautologia_en_assert_metodo(call)
                if motivo:
                    info.tautologias += 1
                    res.problemas.append(ProblemaTest("TAUTOLOGIA", fn.name, call.lineno, "alta", motivo))
        info.asserts = asserts
        if asserts == 0 and not any(_ti_src(c.func).endswith("raises") for c in _ti_walk(fn, ast.Call)):
            res.problemas.append(ProblemaTest("SIN_ASSERT", fn.name, fn.lineno, "alta",
                                              "el test no tiene ningún assert: no verifica nada"))

        # ---- mocks
        patches = _patches_de(fn)
        info.mocks = [t for t, _l, _c in patches]
        mockea_io = False
        valores_mock = []
        for objetivo, linea, call in patches:
            base = objetivo.split(".")[-1]
            raiz = objetivo.split(".")[0]
            valores_mock.extend(_valores_de_mock(call) if call else [])
            # ¿mockea una operación de E/S real?
            if any(objetivo == io or objetivo.endswith("." + io.split(".")[-1]) for io in _IO_REAL) or raiz in (
                    "subprocess", "socket", "requests", "httpx", "urllib"):
                mockea_io = True
            # ¿mockea EL sujeto que el test dice probar? (importado del módulo bajo prueba)
            if base in nombres_importados and sujetos.get(base) and not sujetos[base].startswith(
                    ("unittest", "mock", "pytest")):
                res.problemas.append(ProblemaTest(
                    "MOCK_SISTEMA_BAJO_PRUEBA", fn.name, linea, "alta",
                    f"mockea '{objetivo}', que es justo lo que el test debería ejercitar ('{base}' viene de "
                    f"'{sujetos[base]}'). El test pasa aunque el código real esté roto."))

        # ---- valor esperado fabricado por el mock
        if valores_mock:
            constantes_mock = {v for v in valores_mock if isinstance(v, (str, int, float, bool))}
            for call in _ti_walk(fn, ast.Call):
                metodo = call.func.attr if isinstance(call.func, ast.Attribute) else ""
                if metodo in ("assertEqual", "assertIn") and len(call.args) >= 2:
                    for arg in call.args[:2]:
                        if isinstance(arg, ast.Constant) and arg.value in constantes_mock:
                            res.problemas.append(ProblemaTest(
                                "VALOR_DESDE_MOCK", fn.name, call.lineno, "alta",
                                f"el valor esperado {arg.value!r} lo inyectó el propio mock: el test comprueba "
                                "lo que el mock inventó, no lo que hace el código."))
                            break

        # ---- clasificación real vs declarada
        corre_io_real = any(_ti_src(c.func).split(".")[-1] in ("run", "Popen", "urlopen", "connect", "socket")
                            or _ti_src(c.func) in ("open",) for c in _ti_walk(fn, ast.Call)) and not mockea_io
        if info.nivel_declarado in ("integration", "e2e"):
            info.nivel_real = info.nivel_declarado
            if mockea_io:
                res.problemas.append(ProblemaTest(
                    "INTEGRACION_MOCKEADA", fn.name, fn.lineno, "alta",
                    f"se declara '{info.nivel_declarado}' pero mockea la operación real ({', '.join(info.mocks)}): "
                    "no es integración de verdad. Clasificar como UNIT o no mockear la operación bajo prueba."))
                info.nivel_real = "unit"
        else:
            info.nivel_real = "integration" if corre_io_real else "unit"
        res.tests.append(info)
    return res


def inteligencia_para_prompt(fuente: str, maximo: int = 8) -> str:
    """Resumen para avisarle al agente/al Evidence Gate (vacío si los tests están bien)."""
    res = analizar_tests_python(fuente)
    if not res.problemas:
        return ""
    orden = {"alta": 0, "media": 1, "baja": 2}
    problemas = sorted(res.problemas, key=lambda p: orden.get(p.severidad, 3))[:maximo]
    lineas = [f"- {p.test} (línea {p.linea}) [{p.tipo}]: {p.detalle}" for p in problemas]
    return ("INTELIGENCIA DE TESTS (REAPER los analizó; un test que no discrimina NO demuestra nada):\n"
            + "\n".join(lineas))


# ============================================================================ MutationProbe (ejecuta)
_MUTACIONES = [
    (ast.Eq, ast.NotEq), (ast.NotEq, ast.Eq), (ast.Lt, ast.GtE), (ast.Gt, ast.LtE),
    (ast.LtE, ast.Gt), (ast.GtE, ast.Lt), (ast.Is, ast.IsNot),
    (ast.Add, ast.Sub), (ast.Sub, ast.Add), (ast.Mult, ast.Add), (ast.And, ast.Or), (ast.Or, ast.And),
]
_MAP_MUT = {a: b for a, b in _MUTACIONES}


class _Mutador(ast.NodeTransformer):
    """Aplica UNA mutación (la número objetivo) y recuerda qué cambió."""
    def __init__(self, objetivo: int):
        self.objetivo = objetivo
        self.contador = 0
        self.aplicada = ""

    def _quizas(self, nodo, descripcion, reemplazo):
        if self.contador == self.objetivo:
            self.aplicada = f"línea {getattr(nodo, 'lineno', '?')}: {descripcion}"
            self.contador += 1
            return reemplazo
        self.contador += 1
        return nodo

    def visit_Compare(self, nodo):
        self.generic_visit(nodo)
        if len(nodo.ops) == 1 and type(nodo.ops[0]) in _MAP_MUT:
            nuevo = _MAP_MUT[type(nodo.ops[0])]()
            r = self._quizas(nodo, f"{_ti_sym(nodo.ops[0])} → {_ti_sym(nuevo)}",
                             ast.Compare(left=nodo.left, ops=[nuevo], comparators=nodo.comparators))
            return ast.copy_location(r, nodo) if r is not nodo else nodo
        return nodo

    def visit_BinOp(self, nodo):
        self.generic_visit(nodo)
        if type(nodo.op) in _MAP_MUT:
            nuevo = _MAP_MUT[type(nodo.op)]()
            r = self._quizas(nodo, f"operador binario mutado", ast.BinOp(left=nodo.left, op=nuevo, right=nodo.right))
            return ast.copy_location(r, nodo) if r is not nodo else nodo
        return nodo

    def visit_Constant(self, nodo):
        if isinstance(nodo.value, bool):
            r = self._quizas(nodo, f"{nodo.value} → {not nodo.value}", ast.Constant(value=not nodo.value))
            return ast.copy_location(r, nodo) if r is not nodo else nodo
        if isinstance(nodo.value, int) and not isinstance(nodo.value, bool):
            r = self._quizas(nodo, f"{nodo.value} → {nodo.value + 1}", ast.Constant(value=nodo.value + 1))
            return ast.copy_location(r, nodo) if r is not nodo else nodo
        return nodo


def _contar_mutaciones(fuente: str) -> int:
    try:
        arbol = ast.parse(fuente)
    except SyntaxError:
        return 0
    m = _Mutador(-1)
    m.visit(arbol)
    return m.contador


def generar_mutante(fuente: str, indice: int) -> Optional[tuple[str, str]]:
    """Devuelve (código mutado, descripción) para la mutación número `indice`, o None."""
    try:
        arbol = ast.parse(fuente)
    except SyntaxError:
        return None
    mut = _Mutador(indice)
    nuevo = mut.visit(arbol)
    if not mut.aplicada:
        return None
    ast.fix_missing_locations(nuevo)
    try:
        return ast.unparse(nuevo), mut.aplicada
    except Exception:
        return None


@dataclass
class ResultadoMutacion:
    total: int = 0
    detectadas: int = 0
    sobrevivientes: list = field(default_factory=list)   # (descripción,)
    error: str = ""

    @property
    def puntaje(self) -> float:
        return round(self.detectadas / self.total, 2) if self.total else 1.0


def probar_discriminacion(ws, archivo: str, correr_tests: Callable[[], bool], maximo: int = 12,
                          leer: Optional[Callable[[str], str]] = None,
                          escribir: Optional[Callable[[str, str], None]] = None) -> ResultadoMutacion:
    """
    Mutation testing: muta `archivo` (código de producción) una vez por vez y corre los tests.
    correr_tests() → True si la suite pasa. Si pasa CON la mutación, esa mutación SOBREVIVIÓ:
    los tests no discriminan ese comportamiento. SIEMPRE restaura el archivo original.
    """
    leer = leer or (lambda rel: (ws.raiz / rel).read_text(encoding="utf-8", errors="replace"))
    escribir = escribir or (lambda rel, c: ws.escribir(rel, c))
    try:
        original = leer(archivo)
    except (OSError, ValueError):
        return ResultadoMutacion(error=f"no pude leer {archivo}")
    total_mut = _contar_mutaciones(original)
    if total_mut == 0:
        return ResultadoMutacion(error="no hay mutaciones aplicables (nada que mutar)")
    if not correr_tests():
        return ResultadoMutacion(error="los tests no pasan en el estado base: no se puede medir discriminación")
    resultado = ResultadoMutacion(total=0)
    indices = list(range(total_mut))
    if len(indices) > maximo:
        indices = indices[:: max(1, len(indices) // maximo)][:maximo]
    try:
        for i in indices:
            mutante = generar_mutante(original, i)
            if not mutante:
                continue
            codigo, descripcion = mutante
            if codigo == original:
                continue
            resultado.total += 1
            try:
                escribir(archivo, codigo)
            except (OSError, ValueError):
                continue
            paso = False
            try:
                paso = correr_tests()
            except Exception:
                paso = False
            finally:
                escribir(archivo, original)
            if paso:
                resultado.sobrevivientes.append(descripcion)   # mutación no detectada
            else:
                resultado.detectadas += 1
    finally:
        escribir(archivo, original)
    return resultado
