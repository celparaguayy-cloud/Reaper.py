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
IGNORAR = {"self", "__builtins__", "__class__"}

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
                    texto = repr_corto.repr(v)
                    if " object at 0x" in texto and hasattr(v, "__dict__"):
                        # repr genérico: se muestran los atributos, que es lo que sirve para diagnosticar
                        atributos = {a: b for a, b in vars(v).items() if not a.startswith("__")}
                        texto = type(v).__name__ + repr_corto.repr(atributos)
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

def correr(tests):
    r = Resultado()
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
        for t in tests:
            t.run(r)
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
        r, texto = correr(tests)
        despues = foto()
        cambiados = sorted(k for k in set(antes) | set(despues) if antes.get(k) != despues.get(k))
        estado = "pasa" if r.wasSuccessful() else ("error" if r.errors else "falla")
        informe["tests"].append({"nombre": nombre, "estado": estado, "detalles": r.detalles,
                                 "archivos_tocados": cambiados[:20], "salida": texto[-800:]})
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


_RE_HIPOTESIS = re.compile(
    r"H\d+\s*[:.)-]\s*(?P<texto>.+?)\n\s*EXPERIMENTO\s*:?\s*\n?```(?:python)?\s*\n(?P<codigo>.*?)```\s*"
    r"(?:SI ES VERDAD|SI ES CIERTA|ESPERADO)\s*:?\s*(?P<esperado>[^\n]*)",
    re.S | re.I,
)
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

Con esa evidencia escribí:
CAUSA RAÍZ: <una o dos frases, solo lo que la evidencia respalda>
ARREGLO: <cambio mínimo y exacto: archivo, función y qué cambiar>
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
    ui.tenue(f"  🔎 informe forense listo ({len(informe.hipotesis)} hipótesis, "
             f"{len(informe.dependientes_de_orden)} dependencias de orden, {len(informe.inestables)} inestables, "
             f"{len(informe.culpables)} culpables)")
    return informe


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
    else:
        informe.notas.append("aislamiento detallado solo para Python (unittest/pytest); se usa el conteo general")

    if estado_bueno:
        try:
            informe.culpables = biseccion(ws, estado_bueno, timeout=settings.tests_timeout)
        except (OSError, ValueError) as e:
            informe.notas.append(f"la bisección falló: {e}")


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
        for m in list(_RE_HIPOTESIS.finditer(respuesta or ""))[:3]:
            h = Hipotesis(m.group("texto").strip(), m.group("codigo").strip(), m.group("esperado").strip())
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
                informe.conclusion = (llm.chat_simple(PROMPT_CONCLUSION.format(resultados=resultados), modelo=modelo,
                                                      temperatura=0.1, max_tokens=900, rol="consultor") or "").strip()
            except LLMError as e:
                informe.notas.append(f"no pude pedir la conclusión: {e}")
