"""
MODO FORENSE (v8): cuando la reparación no encuentra la causa raíz, en vez de seguir probando cambios al azar
(lo que con un modelo de 24B suele EMPEORAR las cosas: 2 fallos → 13), REAPER investiga con método:

  1. AISLAR     corre cada test que falla SOLO y la suite en orden INVERSO:
                  - falla solo            → bug en el código o en ese test
                  - pasa solo y falla en la suite, o cambia con el orden → ESTADO COMPARTIDO entre tests
                    (archivo/DB en ruta fija, variable global, caché, fixture sin limpiar)
  2. EVIDENCIA  ejecuta el test con un arnés que captura el traceback con las VARIABLES LOCALES de cada
                frame del proyecto y los archivos que el test crea o modifica dentro del proyecto
  3. BISECCIÓN  si hay un "mejor estado" anterior, revierte archivo por archivo y bloque por bloque para
                encontrar QUÉ CAMBIO introdujo la regresión (siempre deja el proyecto como estaba)
  4. HIPÓTESIS  pide al modelo 2-3 hipótesis, cada una con un EXPERIMENTO (código que imprime algo que la
                confirma o la descarta), REAPER corre los experimentos y le devuelve los resultados reales
  5. CONCLUSIÓN causa raíz respaldada por evidencia + arreglo propuesto

El informe entra al contexto del agente y queda en .reaper/forense/.
"""

_MARCA_FORENSE = "@@REAPER_FORENSE@@"

ARNES_UNITTEST = r'''
import contextlib, io, json, os, reprlib, sys, traceback, unittest
raiz = os.getcwd()
for d in (raiz, os.path.join(raiz, "tests"), os.path.join(raiz, "test")):
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)
repr_corto = reprlib.Repr()
repr_corto.maxstring, repr_corto.maxother, repr_corto.maxlist, repr_corto.maxdict = 160, 160, 8, 8
IGNORAR = {"__builtins__", "__class__"}

def atributos(v):
    return {a: b for a, b in vars(v).items() if not a.startswith("_")}

traza = []
profundidad = [0]

def rastreador(frame, evento, arg):
    archivo = frame.f_code.co_filename
    if not archivo.startswith(raiz) or "/unittest/" in archivo or len(traza) >= 80:
        return None
    if frame.f_code.co_name.startswith("<"):   # <listcomp>, <genexpr>, <lambda>...: ruido
        return None
    if evento == "call":
        codigo = frame.f_code
        argumentos = {}
        cantidad = codigo.co_argcount + codigo.co_kwonlyargcount
        cantidad += bool(codigo.co_flags & 0x04) + bool(codigo.co_flags & 0x08)   # *args y **kwargs
        for nombre in codigo.co_varnames[:cantidad]:
            if nombre != "self" and nombre in frame.f_locals:
                try:
                    argumentos[nombre] = repr_corto.repr(frame.f_locals[nombre])
                except Exception:
                    argumentos[nombre] = "?"
        traza.append({"e": "call", "f": codigo.co_name, "a": os.path.relpath(archivo, raiz), "l": frame.f_lineno,
                      "args": argumentos, "p": profundidad[0]})
        profundidad[0] += 1
        return rastreador
    if evento == "return":
        profundidad[0] = max(0, profundidad[0] - 1)
        try:
            valor = repr_corto.repr(arg)
        except Exception:
            valor = "?"
        traza.append({"e": "ret", "f": frame.f_code.co_name, "v": valor, "p": profundidad[0]})
    return rastreador

def foto():
    estado = {}
    for base, dirs, archivos in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in (".git", ".reaper", "__pycache__", "node_modules", ".pytest_cache")]
        for a in archivos:
            ruta = os.path.join(base, a)
            try:
                st = os.stat(ruta)
            except OSError:
                continue
            estado[os.path.relpath(ruta, raiz)] = (st.st_size, st.st_mtime_ns)
    return estado

class Resultado(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.detalles = []
    def _guardar(self, test, err, tipo):
        frames = []
        for frame, linea in traceback.walk_tb(err[2]):
            archivo = frame.f_code.co_filename
            if not archivo.startswith(raiz) or "/unittest/" in archivo:
                continue
            locales = {}
            for k, v in list(frame.f_locals.items())[:25]:
                if k in IGNORAR or k.startswith("__"):
                    continue
                try:
                    if k == "self" and hasattr(v, "__dict__"):
                        # el estado del objeto (en un TestCase: los fixtures armados en setUp)
                        locales["self"] = type(v).__name__ + repr_corto.repr(atributos(v))
                        continue
                    texto = repr_corto.repr(v)
                    if " object at 0x" in texto and hasattr(v, "__dict__"):
                        # repr genérico: se muestran los atributos, que es lo que sirve para diagnosticar
                        texto = type(v).__name__ + repr_corto.repr(atributos(v))
                    locales[k] = texto
                except Exception as e:
                    locales[k] = f"<repr falló: {type(e).__name__}>"
            frames.append({"archivo": os.path.relpath(archivo, raiz), "linea": linea, "funcion": frame.f_code.co_name,
                           "locales": locales})
        self.detalles.append({"test": test.id(), "tipo": tipo, "error": "".join(traceback.format_exception_only(err[0], err[1])).strip(),
                              "frames": frames[-4:]})
    def addFailure(self, test, err):
        super().addFailure(test, err); self._guardar(test, err, "fallo")
    def addError(self, test, err):
        super().addError(test, err); self._guardar(test, err, "error")

def aplanar(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from aplanar(t)
        else:
            yield t

def correr(tests, rastrear=False):
    r = Resultado()
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
        for t in tests:
            if rastrear:
                sys.settrace(rastreador)
            try:
                t.run(r)
            finally:
                sys.settrace(None)
    return r, salida.getvalue()

modo, argumento = sys.argv[1], json.loads(sys.argv[2])
cargador = unittest.TestLoader()
informe = {}
if modo == "aislar":
    informe["tests"] = []
    for nombre in argumento:
        try:
            tests = list(aplanar(cargador.loadTestsFromName(nombre)))
        except Exception as e:
            informe["tests"].append({"nombre": nombre, "estado": "no_cargo", "detalle": repr(e)[:300]})
            continue
        antes = foto()
        del traza[:]
        r, texto = correr(tests, rastrear=True)
        despues = foto()
        cambiados = sorted(k for k in set(antes) | set(despues) if antes.get(k) != despues.get(k))
        estado = "pasa" if r.wasSuccessful() else ("error" if r.errors else "falla")
        informe["tests"].append({"nombre": nombre, "estado": estado, "detalles": r.detalles,
                                 "archivos_tocados": cambiados[:20], "salida": texto[-800:], "traza": list(traza)})
elif modo == "orden":
    base = argumento.get("base") or ("tests" if os.path.isdir("tests") else ".")
    tests = list(aplanar(cargador.discover(base, top_level_dir=None)))
    if argumento.get("inverso"):
        tests.reverse()
    resultado, _ = correr(tests)
    informe = {"total": len(tests), "fallan": sorted({d["test"] for d in resultado.detalles})}
print("@@REAPER_FORENSE@@" + json.dumps(informe, ensure_ascii=False))
'''


@dataclass
class Hipotesis:
    texto: str
    experimento: str
    esperado: str
    resultado: str = ""
    estado: str = "sin probar"     # confirmada | descartada | no concluyente | no ejecutada


@dataclass
class InformeForense:
    fallidos: list = field(default_factory=list)
    aislados: list = field(default_factory=list)           # dicts del arnés
    dependientes_de_orden: list = field(default_factory=list)
    archivos_tocados_por_tests: list = field(default_factory=list)
    inestables: list = field(default_factory=list)          # el mismo test da otro error al repetirlo
    culpables: list = field(default_factory=list)          # textos con el cambio que introdujo la regresión
    hipotesis: list = field(default_factory=list)
    conclusion: str = ""
    notas: list = field(default_factory=list)
    ruta: Optional[Path] = None

    def texto(self, limite: int = 7000) -> str:
        partes = ["INFORME FORENSE DE REAPER (evidencia real, no suposiciones)"]
        if self.fallidos:
            partes.append("Tests que fallan: " + ", ".join(self.fallidos[:10]))
        if self.dependientes_de_orden:
            partes.append("⚠ DEPENDENCIA DE ORDEN / ESTADO COMPARTIDO: " + ", ".join(self.dependientes_de_orden[:8]) +
                          "\n  Pasan solos (o cambian según el orden) pero fallan en la suite: un test deja estado que "
                          "afecta a otro (archivo o base de datos en una ruta fija, variable global, caché, datos de "
                          "clase mutables, un fixture que no se limpia). Buscá ESO, no cambies la lógica a ciegas.")
        if self.inestables:
            partes.append("⚠ RESULTADO DISTINTO ENTRE CORRIDAS IDÉNTICAS (sin cambiar código):\n  " +
                          "\n  ".join(self.inestables[:3]) +
                          "\n  Hay estado que PERSISTE entre corridas (casi siempre un archivo o base de datos que los "
                          "tests escriben en una ruta fija y nunca limpian): por eso los números crecen corrida a corrida. "
                          "La corrección suele ser que cada test use su propia carpeta temporal (tempfile) y la borre.")
        if self.archivos_tocados_por_tests:
            datos = [r for r in self.archivos_tocados_por_tests
                     if r.endswith((".db", ".sqlite", ".sqlite3", ".json", ".csv", ".txt", ".log", ".dat", ".bin", ".pkl"))]
            partes.append("Archivos del PROYECTO que los tests crean o modifican al correr: " +
                          ", ".join(self.archivos_tocados_por_tests[:10]) +
                          "\n  (un test que escribe en el proyecto en vez de en una carpeta temporal contamina a los demás"
                          + (f"; {', '.join(datos[:4])} parecen datos que se ACUMULAN entre corridas" if datos else "") + ")")
        for a in self.aislados[:4]:
            linea = f"- {a.get('nombre')}: SOLO → {a.get('estado')}"
            for d in (a.get("detalles") or [])[:1]:
                linea += f"\n  {d.get('error', '')[:400]}"
                for fr in d.get("frames", [])[-3:]:
                    locales = ", ".join(f"{k}={v}" for k, v in list(fr.get("locales", {}).items())[:8])
                    linea += f"\n    en {fr['archivo']}:{fr['linea']} ({fr['funcion']}): {locales}"
            partes.append(linea)
        for a in self.aislados[:2]:
            arbol = arbol_de_llamadas(a.get("traza") or [])
            if arbol:
                partes.append(f"LLAMADAS durante {a.get('nombre')} (argumentos → valor devuelto):\n{arbol}")
        if self.culpables:
            partes.append("CAMBIO QUE INTRODUJO LA REGRESIÓN (encontrado por bisección):\n" + "\n".join(self.culpables[:3]))
        for i, h in enumerate(self.hipotesis, 1):
            partes.append(f"H{i} [{h.estado.upper()}]: {h.texto}\n  experimento → {recortar(h.resultado or '(no se ejecutó)', 500)}")
        if self.conclusion:
            partes.append("CONCLUSIÓN:\n" + self.conclusion)
        if self.notas:
            partes.append("Notas: " + "; ".join(self.notas))
        partes.append("Siguiente paso: arreglá la causa que muestra la evidencia con el cambio MÍNIMO y corré run_tests. "
                      "Si un cambio empeora los tests, REAPER lo revierte solo.")
        return recortar("\n\n".join(partes), limite)


def arbol_de_llamadas(traza: list, maximo: int = 30) -> str:
    """Traza del arnés → árbol legible: '→ f(a=1)' al entrar y '← f = 3' al salir, indentado por profundidad."""
    lineas = []
    for ev in traza:
        sangria = "  " * min(int(ev.get("p", 0)), 8)
        if ev.get("e") == "call":
            if ev.get("f", "").startswith("test"):
                continue
            argumentos = ", ".join(f"{k}={v}" for k, v in (ev.get("args") or {}).items())
            lineas.append(f"  {sangria}→ {ev['f']}({argumentos})  [{ev.get('a')}:{ev.get('l')}]")
        elif ev.get("e") == "ret" and not ev.get("f", "").startswith("test"):
            lineas.append(f"  {sangria}← {ev['f']} = {ev.get('v')}")
        if len(lineas) >= maximo:
            lineas.append("  ...")
            break
    return "\n".join(lineas)


def _correr_arnes(ws: Workspace, modo: str, argumento, timeout: int = 120) -> Optional[dict]:
    with tempfile.NamedTemporaryFile("w", suffix="_arnes.py", delete=False, encoding="utf-8") as f:
        f.write(ARNES_UNITTEST)
        ruta = f.name
    try:
        r = ejecutar([sys.executable, ruta, modo, json.dumps(argumento)], cwd=ws.raiz, timeout=timeout)
    finally:
        try:
            os.unlink(ruta)
        except OSError:
            pass
    salida = r.stdout or ""
    if _MARCA_FORENSE not in salida:
        return None
    try:
        return json.loads(salida.split(_MARCA_FORENSE, 1)[1].strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def es_proyecto_unittest(ws: Workspace) -> bool:
    detectado = detectar_comando_tests(ws, completo=True)
    return bool(detectado) and detectado[1] in ("unittest", "pytest")


def nombres_para_unittest(nombres: Iterable[str]) -> list[str]:
    """'test_calc.T.test_suma' tal cual; 'tests/test_calc.py::T::test_suma' (pytest) → 'test_calc.T.test_suma'."""
    salida = []
    for n in nombres:
        n = n.strip()
        if "::" in n:
            archivo, _, resto = n.partition("::")
            modulo = Path(archivo).with_suffix("").name
            n = ".".join([modulo] + [p for p in resto.split("::") if p and "[" not in p])
        if re.fullmatch(r"[\w.]+", n) and n not in salida:
            salida.append(n)
    return salida


def conteo_actual(ws: Workspace, timeout: int = 300) -> ConteoTests:
    return conteo_de_resultado(ejecutar_tests(ws, timeout=timeout, completo=True))


def _malos(c: ConteoTests) -> int:
    return c.fallados + c.errores


def es_peor(despues: ConteoTests, antes: ConteoTests) -> bool:
    """¿El resultado de tests empeoró? (más fallos/errores o menos tests que pasan)."""
    if not (despues.reconocido and antes.reconocido):
        return False
    return _malos(despues) > _malos(antes) or despues.pasados < antes.pasados


def es_mejor(despues: ConteoTests, antes: ConteoTests) -> bool:
    if not (despues.reconocido and antes.reconocido):
        return False
    return (_malos(despues) < _malos(antes) and despues.pasados >= antes.pasados) or \
        (_malos(despues) == _malos(antes) and despues.pasados > antes.pasados)


def biseccion(ws: Workspace, estado_bueno: dict, timeout: int = 300, max_archivos: int = 6,
              max_bloques: int = 10) -> list[str]:
    """
    estado_bueno: {rel: contenido o None} de un momento con MENOS fallos. Revierte archivo por archivo y,
    en el culpable, bloque por bloque, para encontrar el cambio que introdujo la regresión.
    El proyecto SIEMPRE queda como estaba al empezar.
    """
    actuales: dict[str, Optional[str]] = {}
    for rel in estado_bueno:
        ruta = ws.raiz / rel
        actuales[rel] = ruta.read_text(encoding="utf-8", errors="replace") if ruta.is_file() else None
    cambiados = [rel for rel in estado_bueno if estado_bueno[rel] != actuales[rel]][:max_archivos]
    if not cambiados:
        return []
    base = conteo_actual(ws, timeout)
    culpables = []

    def poner(rel: str, contenido: Optional[str]) -> None:
        ruta = ws.raiz / rel
        if contenido is None:
            if ruta.exists():
                ruta.unlink()
        else:
            escritura_atomica(ruta, contenido)

    try:
        for rel in cambiados:
            poner(rel, estado_bueno[rel])
            probado = conteo_actual(ws, timeout)
            poner(rel, actuales[rel])
            if not es_mejor(probado, base):
                continue
            antes, despues = (estado_bueno[rel] or ""), (actuales[rel] or "")
            a_lineas, d_lineas = antes.splitlines(keepends=True), despues.splitlines(keepends=True)
            grupos = [op for op in difflib.SequenceMatcher(None, a_lineas, d_lineas).get_opcodes() if op[0] != "equal"]
            encontrado = False
            for tag, i1, i2, j1, j2 in grupos[:max_bloques]:
                version = "".join(d_lineas[:j1] + a_lineas[i1:i2] + d_lineas[j2:])
                poner(rel, version)
                probado_bloque = conteo_actual(ws, timeout)
                poner(rel, actuales[rel])
                if es_mejor(probado_bloque, base):
                    quitado = "".join("- " + l for l in a_lineas[i1:i2])
                    agregado = "".join("+ " + l for l in d_lineas[j1:j2])
                    culpables.append(f"{rel} (líneas {j1 + 1}-{max(j1 + 1, j2)} actuales): revertir este bloque mejora "
                                     f"de {base.texto()} a {probado_bloque.texto()}\n{quitado}{agregado}".rstrip())
                    encontrado = True
            if not encontrado:
                culpables.append(f"{rel}: revertir el archivo entero mejora de {base.texto()} a {probado.texto()} "
                                 "(el problema está en la combinación de varios bloques)")
    finally:
        for rel, contenido in actuales.items():
            poner(rel, contenido)
    return culpables


_RE_INICIO_HIPOTESIS = re.compile(r"^\s*(?:\*\*)?(?:H\s*\d+|hip[óo]tesis\s*\d*|\d+[.)])\s*(?:\*\*)?\s*[:.)-]?\s*(?:\*\*)?\s*",
                                  re.I | re.M)
_RE_CODIGO = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
_RE_ESPERADO = re.compile(r"(?:SI ES VERDAD|SI ES CIERTA|SI ES CIERTO|ESPERADO|RESULTADO ESPERADO)\s*:?\s*\**\s*([^\n]*)", re.I)


def parsear_hipotesis(texto: str, maximo: int = 3) -> list:
    """Tolerante con el formato de un modelo chico: 'H1:', 'Hipótesis 1:', '1.', negritas, etc."""
    inicios = [m for m in _RE_INICIO_HIPOTESIS.finditer(texto or "")]
    salida = []
    for i, m in enumerate(inicios):
        bloque = texto[m.end(): inicios[i + 1].start() if i + 1 < len(inicios) else len(texto)]
        primera = bloque.strip().splitlines()[0] if bloque.strip() else ""
        enunciado = re.sub(r"\*\*|\bEXPERIMENTO\s*:.*$", "", primera, flags=re.I).strip(" :-")
        codigo = _RE_CODIGO.search(bloque)
        esperado = _RE_ESPERADO.search(bloque[codigo.end():] if codigo else bloque)
        if not enunciado:
            continue
        salida.append(Hipotesis(enunciado, codigo.group(1).strip() if codigo else "",
                                esperado.group(1).strip() if esperado else ""))
        if len(salida) >= maximo:
            break
    return salida
_INSEGURO = re.compile(r"\b(shutil\.rmtree|os\.remove|os\.unlink|os\.rmdir|os\.system|subprocess|socket|urllib|requests|"
                       r"http\.client|ftplib|smtplib|__import__\(['\"]os['\"]\)\.system|\.unlink\(|rmtree)\b")

PROMPT_HIPOTESIS = """Sos un depurador experto. Un modelo más chico no encuentra la causa de este fallo.
No propongas un arreglo todavía: proponé de 2 a 3 HIPÓTESIS distintas sobre la causa raíz, cada una con un
EXPERIMENTO corto en Python (se ejecuta en la raíz del proyecto; puede importar los módulos del proyecto)
que IMPRIMA algo que la confirme o la descarte. Nada de borrar archivos ni usar la red.

Formato EXACTO para cada una:
H1: <hipótesis concreta>
EXPERIMENTO:
```python
<código>
```
SI ES VERDAD: <qué imprimiría>

EVIDENCIA RECOGIDA POR REAPER:
{evidencia}

CÓDIGO RELEVANTE:
{codigo}
"""

PROMPT_CONCLUSION = """Estos son los resultados REALES de los experimentos:
{resultados}

{spec}

Con esa evidencia escribí (distinguí lo OBSERVADO de lo INTERPRETADO; no presentes una suposición como hecho):
CLASIFICACIÓN: <IMPLEMENTATION_BUG | TEST_BUG | SPEC_GAP | PATH_BUG | INPUT_MODEL_BUG | FIXTURE_BUG | DEPENDENCY_BUG | FLAKY_TEST>
CAUSA RAÍZ: <una o dos frases, solo lo que la evidencia respalda>
ARREGLO: <cambio mínimo y exacto: archivo, función y qué cambiar. Si el test exige algo que la spec no pide, el arreglo es corregir el TEST, no el código>
"""


def _codigo_relevante(ws: Workspace, informe: InformeForense, limite: int = 6000) -> str:
    archivos: list[str] = []
    for a in informe.aislados:
        for d in a.get("detalles") or []:
            for fr in d.get("frames", []):
                if fr["archivo"] not in archivos:
                    archivos.append(fr["archivo"])
    partes, usado = [], 0
    for rel in archivos[:4]:
        try:
            texto = ws.leer(rel)
        except (OSError, ErrorRuta, ValueError):
            continue
        bloque = f"### {rel}\n" + recortar(texto, 2500)
        if usado + len(bloque) > limite:
            break
        partes.append(bloque)
        usado += len(bloque)
    return "\n\n".join(partes) or "(no se pudo ubicar código del proyecto en el traceback)"


def correr_experimento(ws: Workspace, codigo: str, timeout: int = 30) -> tuple[bool, str]:
    if _INSEGURO.search(codigo) or comando_bloqueado(codigo):
        return False, "no ejecutado: el experimento hace algo inseguro (borrar, procesos o red)"
    r = ejecutar([sys.executable, "-"], cwd=ws.raiz, timeout=timeout, entrada=codigo)
    texto = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()
    return True, recortar(texto or f"(sin salida, exit {r.codigo})", 1500)


class FotoProyecto:
    """Guarda los archivos chicos del proyecto y al salir deshace lo que hayan cambiado las corridas de tests."""

    def __init__(self, ws: Workspace, max_bytes: int = 2_000_000, limite: int = 3000):
        self.ws = ws
        self.max_bytes = max_bytes
        self.limite = limite
        self.contenidos: dict[str, bytes] = {}
        self.restaurados: list[str] = []

    def __enter__(self) -> "FotoProyecto":
        for ruta in self.ws.iterar(limite=self.limite):
            try:
                if ruta.stat().st_size <= self.max_bytes:
                    self.contenidos[self.ws.rel(ruta)] = ruta.read_bytes()
            except OSError:
                continue
        return self

    def __exit__(self, *exc) -> None:
        actuales = {self.ws.rel(r) for r in self.ws.iterar(limite=self.limite)}
        for rel in sorted(actuales - set(self.contenidos)):
            if rel.startswith(".reaper/"):
                continue
            try:
                (self.ws.raiz / rel).unlink()
                self.restaurados.append(f"{rel} (creado por los tests, borrado)")
            except OSError:
                pass
        for rel, contenido in self.contenidos.items():
            ruta = self.ws.raiz / rel
            try:
                if not ruta.is_file() or ruta.read_bytes() != contenido:
                    ruta.parent.mkdir(parents=True, exist_ok=True)
                    ruta.write_bytes(contenido)
                    self.restaurados.append(rel)
            except OSError:
                pass


def investigar(ws: Workspace, settings: Settings, ui: UI, llm=None, *, fallidos: Iterable[str] = (),
               estado_bueno: Optional[dict] = None, contexto: str = "", con_hipotesis: bool = True,
               modelo: Optional[str] = None) -> InformeForense:
    """Ejecuta el modo forense completo y devuelve el informe (también lo guarda en .reaper/forense/)."""
    informe = InformeForense()
    ui.linea(f"{Tema.acento}🔎 modo forense:{C.RESET} {Tema.tenue}investigo el fallo con experimentos en vez de "
             f"seguir probando cambios{C.RESET}")
    with FotoProyecto(ws) as foto:   # ni las corridas ni los experimentos pueden dejar cambios en el proyecto
        _investigar_con_corridas(ws, settings, informe, fallidos, estado_bueno)
        _hipotesis_y_conclusion(ws, informe, llm, contexto, con_hipotesis, modelo)
    if foto.restaurados:
        informe.notas.append("la investigación dejó el proyecto como estaba (restauré: "
                             + ", ".join(foto.restaurados[:6]) + ")")
    try:
        carpeta = ws.raiz / ".reaper" / "forense"
        carpeta.mkdir(parents=True, exist_ok=True)
        informe.ruta = carpeta / f"forense_{datetime.now():%Y%m%d_%H%M%S}.md"
        escritura_atomica(informe.ruta, informe.texto(20000) + "\n")
    except OSError:
        informe.ruta = None
    for hallazgo in hallazgos_principales(informe):
        ui.linea(f"    {Tema.aviso}•{C.RESET} {hallazgo}")
    ui.tenue(f"  🔎 informe forense listo ({len(informe.hipotesis)} hipótesis, "
             f"{len(informe.dependientes_de_orden)} dependencias de orden, {len(informe.inestables)} inestables, "
             f"{len(informe.culpables)} culpables)" + (f" · {ws.rel(informe.ruta)}" if informe.ruta else ""))
    return informe


def hallazgos_principales(informe: InformeForense) -> list[str]:
    """Lo más importante del informe en pocas líneas, para mostrarle al usuario."""
    salida = []
    if informe.inestables:
        salida.append("el resultado cambia entre corridas idénticas: hay estado que persiste")
    if informe.dependientes_de_orden:
        salida.append("depende del orden o de estado compartido: " + ", ".join(informe.dependientes_de_orden[:3]))
    if informe.archivos_tocados_por_tests:
        salida.append("los tests escriben en el proyecto: " + ", ".join(informe.archivos_tocados_por_tests[:3]))
    if informe.culpables:
        salida.append("cambio culpable: " + informe.culpables[0].splitlines()[0][:120])
    confirmadas = [h for h in informe.hipotesis if h.estado == "confirmada"]
    if confirmadas:
        salida.append("hipótesis confirmada: " + confirmadas[0].texto[:120])
    return salida


def _investigar_con_corridas(ws: Workspace, settings: Settings, informe: InformeForense, fallidos, estado_bueno) -> None:
    if not fallidos:
        conteo = conteo_actual(ws, settings.tests_timeout)
        fallidos = conteo.nombres_fallados
    informe.fallidos = list(fallidos)[:20]

    if es_proyecto_unittest(ws):
        nombres = nombres_para_unittest(informe.fallidos)[:6]
        for nombre in nombres:
            # cada test en SU proceso: el estado en memoria de uno no contamina al otro
            aislado = _correr_arnes(ws, "aislar", [nombre], timeout=settings.tests_timeout)
            if not aislado or not aislado.get("tests"):
                informe.notas.append(f"no pude aislar {nombre}")
                continue
            t = aislado["tests"][0]
            informe.aislados.append(t)
            if t.get("estado") == "pasa":
                informe.dependientes_de_orden.append(t["nombre"])
            for rel in t.get("archivos_tocados", []):
                if rel not in informe.archivos_tocados_por_tests and not rel.endswith(".pyc"):
                    informe.archivos_tocados_por_tests.append(rel)
        if informe.aislados:
            # la misma prueba otra vez, sin tocar el código: si el resultado cambia, hay estado que persiste
            primero = informe.aislados[0]
            otra = _correr_arnes(ws, "aislar", [primero["nombre"]], timeout=settings.tests_timeout)
            segundo = ((otra or {}).get("tests") or [{}])[0]

            def resumen(t: dict) -> str:
                error = ((t.get("detalles") or [{}])[0]).get("error", "")
                return f"{t.get('estado', '?')}" + (f" ({error[:150]})" if error else "")

            if otra and resumen(primero) != resumen(segundo):
                informe.inestables.append(f"{primero['nombre']}: 1ª corrida → {resumen(primero)} | "
                                          f"2ª corrida → {resumen(segundo)}")
        directo = _correr_arnes(ws, "orden", {"inverso": False}, timeout=settings.tests_timeout)
        inverso = _correr_arnes(ws, "orden", {"inverso": True}, timeout=settings.tests_timeout)
        if directo and inverso and set(directo["fallan"]) != set(inverso["fallan"]):
            for n in sorted(set(directo["fallan"]) ^ set(inverso["fallan"])):
                if n not in informe.dependientes_de_orden:
                    informe.dependientes_de_orden.append(n)
            informe.notas.append(f"en orden directo fallan {len(directo['fallan'])} y en orden inverso "
                                 f"{len(inverso['fallan'])}: el resultado depende del orden")
    elif _aislar_generico(ws, settings, informe):
        pass
    else:
        informe.notas.append("no pude aislar tests individuales en este lenguaje; comparo la suite completa entre corridas")
        primera = conteo_actual(ws, settings.tests_timeout)
        segunda = conteo_actual(ws, settings.tests_timeout)
        if (primera.reconocido and segunda.reconocido and
                (primera.texto() != segunda.texto() or set(primera.nombres_fallados) != set(segunda.nombres_fallados))):
            informe.inestables.append(f"suite completa: 1ª corrida → {primera.texto()} | 2ª corrida → {segunda.texto()}")

    if estado_bueno:
        try:
            informe.culpables = biseccion(ws, estado_bueno, timeout=settings.tests_timeout)
        except (OSError, ValueError) as e:
            informe.notas.append(f"la bisección falló: {e}")


def _foto_archivos(ws: Workspace, limite: int = 3000) -> dict:
    foto = {}
    for ruta in ws.iterar(limite=limite):
        try:
            st = ruta.stat()
        except OSError:
            continue
        foto[ws.rel(ruta)] = (st.st_size, st.st_mtime_ns)
    return foto


def _comando_test_individual(ws: Workspace, nombre: str) -> Optional[tuple[str, str]]:
    """
    (comando, lenguaje) para correr UN test aislado en JS (node:test) o Go. None si no se puede.
    En JS filtra por nombre de test; en Go por -run con el nombre de la función.
    """
    detectado = detectar_comando_tests(ws, completo=True)
    if not detectado:
        return None
    comando, tipo = detectado
    if tipo == "node --test" and shutil.which("node"):
        # se reusa el comando detectado (trae la lista de archivos) y se le inyecta el filtro por nombre,
        # porque `node --test <dir>` trata el directorio como script y falla
        patron = shlex.quote(nombre.strip())
        if "--test" in comando:
            filtrado = comando.replace("--test", f"--test --test-name-pattern={patron}", 1)
        else:
            filtrado = f"{comando} --test-name-pattern={patron}"
        return (filtrado, "javascript")
    if tipo in ("go test", "go test (paquetes)") and shutil.which("go"):
        funcion = nombre.split("/")[0].strip()        # TestX/sub → TestX
        if not re.fullmatch(r"[A-Za-z_]\w*", funcion):
            return None
        return (f"go test -run {shlex.quote('^' + funcion + '$')} ./...", "go")
    return None


def _aislar_generico(ws: Workspace, settings: Settings, informe: InformeForense) -> bool:
    """Aísla cada test que falla en JS/Go: lo corre solo, lo repite y mira qué archivos toca. True si pudo."""
    pudo = False
    for nombre in informe.fallidos[:5]:
        armado = _comando_test_individual(ws, nombre)
        if armado is None:
            continue
        pudo = True
        comando, lenguaje = armado

        def una_corrida() -> tuple:
            antes = _foto_archivos(ws)
            r = ejecutar(comando_portable(comando), cwd=ws.raiz, timeout=settings.tests_timeout, shell=True)
            conteo = contar_tests(r.stdout + r.stderr, r.codigo)
            despues = _foto_archivos(ws)
            tocados = sorted(k for k in set(antes) | set(despues) if antes.get(k) != despues.get(k))
            if conteo.reconocido and conteo.total == conteo.omitidos:
                estado = "no_corrio"      # el filtro no seleccionó ningún test (todos omitidos o ninguno)
            elif r.codigo == 0 and not (conteo.fallados or conteo.errores):
                estado = "pasa"
            else:
                estado = "falla"
            return estado, tocados, (r.stdout + r.stderr)

        estado1, tocados, salida = una_corrida()
        if estado1 == "no_corrio":
            continue
        informe.aislados.append({"nombre": nombre, "estado": estado1, "detalles": [], "archivos_tocados": tocados,
                                 "salida": salida[-800:]})
        if estado1 == "pasa":
            informe.dependientes_de_orden.append(nombre)
        for rel in tocados:
            if rel not in informe.archivos_tocados_por_tests and not rel.endswith(".pyc"):
                informe.archivos_tocados_por_tests.append(rel)
        estado2, _t2, _s2 = una_corrida()      # repetir: si cambia sin tocar el código, hay estado que persiste
        if estado2 != estado1:
            informe.inestables.append(f"{nombre}: 1ª corrida → {estado1} | 2ª corrida → {estado2}")
    return pudo


def _hipotesis_y_conclusion(ws: Workspace, informe: InformeForense, llm, contexto: str, con_hipotesis: bool,
                            modelo: Optional[str]) -> None:
    if con_hipotesis and llm is not None:
        evidencia = informe.texto(4000)
        if contexto:
            evidencia = recortar(contexto, 1500) + "\n\n" + evidencia
        try:
            respuesta = llm.chat_simple(PROMPT_HIPOTESIS.format(evidencia=evidencia, codigo=_codigo_relevante(ws, informe)),
                                        modelo=modelo, temperatura=0.2, max_tokens=1800, rol="consultor")
        except LLMError as e:
            respuesta = ""
            informe.notas.append(f"no pude pedir hipótesis: {e}")
        for h in parsear_hipotesis(respuesta or ""):
            if not h.experimento:
                h.estado = "sin experimento"
                informe.hipotesis.append(h)
                continue
            ejecutado, salida = correr_experimento(ws, h.experimento)
            h.resultado = salida
            if not ejecutado:
                h.estado = "no ejecutada"
            elif h.esperado and h.esperado.strip("`'\" ").lower() in salida.lower():
                h.estado = "confirmada"
            elif "Traceback" in salida:
                h.estado = "no concluyente"
            else:
                h.estado = "descartada?"
            informe.hipotesis.append(h)
        if informe.hipotesis:
            resultados = "\n\n".join(f"H{i}: {h.texto}\nEXPERIMENTO:\n{h.experimento}\nSALIDA REAL:\n{h.resultado}"
                                     for i, h in enumerate(informe.hipotesis, 1))
            try:
                informe.conclusion = (llm.chat_simple(
                    PROMPT_CONCLUSION.format(resultados=resultados, spec=_bloque_spec(ws, informe)), modelo=modelo,
                    temperatura=0.1, max_tokens=900, rol="consultor") or "").strip()
            except LLMError as e:
                informe.notas.append(f"no pude pedir la conclusión: {e}")


def _errores_forenses(informe: InformeForense, limite: int = 1200) -> str:
    """Junta los mensajes de error REALES del informe para clasificar el fallo."""
    trozos: list = []
    for a in informe.aislados[:4]:
        for d in (a.get("detalles") or [])[:1]:
            err = (d.get("error") or "").strip()
            if err:
                trozos.append(err)
    return recortar("\n".join(trozos), limite)


def _modulos_del_proyecto(ws: Workspace, limite: int = 200) -> set:
    """Nombres de módulos/paquetes top-level del proyecto (para distinguir PATH_BUG de DEPENDENCY_BUG)."""
    nombres: set = set()
    try:
        for ruta in ws.iterar(limite=limite):
            rel = ws.rel(ruta)
            if "/" in rel:
                nombres.add(rel.split("/", 1)[0])
            if rel.endswith(".py"):
                nombres.add(os.path.splitext(os.path.basename(rel))[0])
    except OSError:
        pass
    nombres.discard("__init__")
    return nombres


def _bloque_spec(ws: Workspace, informe: InformeForense) -> str:
    """Nota de autoridad + observación + clasificación heurística del fallo, para el prompt de conclusión."""
    partes = [nota_spec()]
    error = _errores_forenses(informe)
    if error:
        partes.append(clasificacion_para_prompt(error, modulos_proyecto=_modulos_del_proyecto(ws)))
    return "\n\n".join(partes)
