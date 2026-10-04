"""
Lectura de la salida de las suites de tests: cuántos pasaron, fallaron, con
error u omitidos, y cuáles fallaron.

El torneo necesita un número ("pasa más tests") y el reparador necesita el
detalle de los primeros fallos, sin el ruido del resto de la salida.
Soporta pytest, unittest, node --test (TAP y spec), jest, vitest, mocha,
go test y cargo test. Si no reconoce nada, usa el código de salida.
"""


@dataclass
class ConteoTests:
    pasados: int = 0
    fallados: int = 0
    errores: int = 0
    omitidos: int = 0
    fuente: str = "desconocido"
    nombres_fallados: list = field(default_factory=list)
    reconocido: bool = False

    @property
    def total(self) -> int:
        return self.pasados + self.fallados + self.errores + self.omitidos

    @property
    def ok(self) -> bool:
        return self.fallados == 0 and self.errores == 0

    @property
    def ejecutados(self) -> int:
        return self.pasados + self.fallados + self.errores

    def proporcion(self) -> float:
        return self.pasados / self.ejecutados if self.ejecutados else 0.0

    def texto(self) -> str:
        if not self.reconocido:
            return "sin conteo (se usa el código de salida)"
        partes = [f"{self.pasados} pasaron"]
        if self.fallados:
            partes.append(f"{self.fallados} fallaron")
        if self.errores:
            partes.append(f"{self.errores} con error")
        if self.omitidos:
            partes.append(f"{self.omitidos} omitidos")
        return ", ".join(partes) + f" ({self.fuente})"


_RE_PYTEST_RESUMEN = re.compile(
    r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)", re.I
)
_RE_PYTEST_LINEA = re.compile(r"^=*\s*(?:\d+\s+\w+(?:,\s*)?)+.*\bin\s+[\d.]+s", re.M)
_RE_PYTEST_FALLO = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)
_RE_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in", re.M)
_RE_UNITTEST_FAILED = re.compile(r"^FAILED \(([^)]*)\)", re.M)
_RE_UNITTEST_OK = re.compile(r"^OK(?: \(([^)]*)\))?\s*$", re.M)
_RE_UNITTEST_NOMBRE = re.compile(r"^(?:FAIL|ERROR): (\S+)(?: \(([^)]+)\))?", re.M)
_RE_TAP_RESUMEN = re.compile(r"^[#ℹ]\s*(tests|pass|fail|skipped|todo|cancelled)\s+(\d+)", re.M)
_RE_TAP_NOT_OK = re.compile(r"^\s*not ok \d+ - (.+)$", re.M)
_RE_SPEC_FALLO = re.compile(r"^\s*✖\s+(.+?)(?:\s+\([\d.]+m?s\))?$", re.M)
_RE_JEST = re.compile(r"^Tests:\s+(.*?)(\d+)\s+total", re.M)
_RE_VITEST = re.compile(r"^\s*Tests\s+(.*)\((\d+)\)", re.M)
_RE_MOCHA = re.compile(r"^\s*(\d+)\s+(passing|failing|pending)", re.M)
_RE_GO_CASO = re.compile(r"^\s*--- (PASS|FAIL|SKIP): (\S+)", re.M)
# "ok  \tmodulo/pkg\t0.01s", "FAIL\tmodulo/pkg [build failed]", "?   \tmodulo/cmd\t[no test files]"
# (no confundir con TAP: "ok 1 - nombre")
_RE_GO_PAQUETE = re.compile(r"^(ok|FAIL|\?)\s+(?!\d+\b)\S+\s+(?:[\d.]+s|\(cached\)|\[[\w ]+\])", re.M)
_RE_CARGO = re.compile(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored")
_RE_CARGO_FALLO = re.compile(r"^test (\S+) \.\.\. FAILED", re.M)


def _pytest(salida: str) -> Optional[ConteoTests]:
    lineas = [l for l in salida.splitlines() if re.search(r"\b(passed|failed|errors?)\b", l)
              and re.search(r"\bin\s+[\d.]+s", l) and not l.lstrip().startswith("test result:")]  # cargo
    if not lineas:
        if "no tests ran" in salida.lower():
            return ConteoTests(fuente="pytest", reconocido=True)
        return None
    c = ConteoTests(fuente="pytest", reconocido=True)
    for cantidad, tipo in _RE_PYTEST_RESUMEN.findall(lineas[-1]):
        n = int(cantidad)
        tipo = tipo.lower()
        if tipo in ("passed", "xpassed"):
            c.pasados += n
        elif tipo == "failed":
            c.fallados += n
        elif tipo.startswith("error"):
            c.errores += n
        elif tipo in ("skipped", "xfailed", "deselected"):
            c.omitidos += n
    c.nombres_fallados = _RE_PYTEST_FALLO.findall(salida)[:50]
    return c


def _unittest(salida: str) -> Optional[ConteoTests]:
    ran = _RE_UNITTEST_RAN.findall(salida)
    if not ran:
        return None
    total = sum(int(n) for n in ran)
    c = ConteoTests(fuente="unittest", reconocido=True)
    fallos = errores = omitidos = 0
    for detalle in _RE_UNITTEST_FAILED.findall(salida) + [g for g in _RE_UNITTEST_OK.findall(salida) if g]:
        for clave, valor in re.findall(r"(\w+)=(\d+)", detalle):
            if clave == "failures":
                fallos += int(valor)
            elif clave == "errors":
                errores += int(valor)
            elif clave in ("skipped", "expected_failures"):
                omitidos += int(valor)
            elif clave == "unexpected_successes":
                fallos += int(valor)
    c.fallados, c.errores, c.omitidos = fallos, errores, omitidos
    c.pasados = max(0, total - fallos - errores - omitidos)
    nombres = []
    for metodo, clase in _RE_UNITTEST_NOMBRE.findall(salida):
        nombres.append(f"{clase}.{metodo}" if clase and metodo not in clase else (clase or metodo))
    c.nombres_fallados = nombres[:50]
    return c


def _tap(salida: str) -> Optional[ConteoTests]:
    datos = {k: int(v) for k, v in _RE_TAP_RESUMEN.findall(salida)}
    if "pass" not in datos and "fail" not in datos:
        return None
    c = ConteoTests(fuente="node --test" if ("ℹ" in salida or "duration_ms" in salida) else "TAP", reconocido=True)
    c.pasados = datos.get("pass", 0)
    c.fallados = datos.get("fail", 0) + datos.get("cancelled", 0)
    c.omitidos = datos.get("skipped", 0) + datos.get("todo", 0)
    nombres = [n.strip() for n in _RE_TAP_NOT_OK.findall(salida)]
    if not nombres:
        nombres = [n.strip() for n in _RE_SPEC_FALLO.findall(salida)]
    c.nombres_fallados = [n for n in nombres if not n.endswith(".mjs") and not n.endswith(".js")][:50] or nombres[:50]
    return c


def _jest(salida: str) -> Optional[ConteoTests]:
    m = None
    for m in _RE_JEST.finditer(salida):
        pass
    if not m:
        return None
    c = ConteoTests(fuente="jest", reconocido=True)
    for cantidad, tipo in re.findall(r"(\d+)\s+(passed|failed|skipped|todo|pending)", m.group(1)):
        n = int(cantidad)
        if tipo == "passed":
            c.pasados += n
        elif tipo == "failed":
            c.fallados += n
        else:
            c.omitidos += n
    c.nombres_fallados = re.findall(r"^\s*●\s+(.+)$", salida, re.M)[:50]
    return c


def _vitest(salida: str) -> Optional[ConteoTests]:
    m = None
    for m in _RE_VITEST.finditer(salida):
        pass
    if not m or "|" not in m.group(1) and not re.search(r"\d+\s+(passed|failed)", m.group(1)):
        return None
    c = ConteoTests(fuente="vitest", reconocido=True)
    for cantidad, tipo in re.findall(r"(\d+)\s+(passed|failed|skipped|todo)", m.group(1)):
        n = int(cantidad)
        if tipo == "passed":
            c.pasados += n
        elif tipo == "failed":
            c.fallados += n
        else:
            c.omitidos += n
    return c if c.total else None


def _mocha(salida: str) -> Optional[ConteoTests]:
    datos = {t: int(n) for n, t in _RE_MOCHA.findall(salida)}
    if "passing" not in datos and "failing" not in datos:
        return None
    return ConteoTests(datos.get("passing", 0), datos.get("failing", 0), 0, datos.get("pending", 0),
                       "mocha", re.findall(r"^\s*\d+\)\s+(.+)$", salida, re.M)[:50], True)


def _go(salida: str) -> Optional[ConteoTests]:
    casos = _RE_GO_CASO.findall(salida)
    if casos:
        c = ConteoTests(fuente="go test", reconocido=True)
        for estado, nombre in casos:
            if estado == "PASS":
                c.pasados += 1
            elif estado == "FAIL":
                c.fallados += 1
                c.nombres_fallados.append(nombre)
            else:
                c.omitidos += 1
        return c
    paquetes = _RE_GO_PAQUETE.findall(salida)
    if not paquetes:
        return None
    return ConteoTests(paquetes.count("ok"), paquetes.count("FAIL"), 0, paquetes.count("?"), "go test (paquetes)",
                       [], True)


def _cargo(salida: str) -> Optional[ConteoTests]:
    resultados = _RE_CARGO.findall(salida)
    if not resultados:
        return None
    c = ConteoTests(fuente="cargo test", reconocido=True)
    for p, f, i in resultados:
        c.pasados += int(p)
        c.fallados += int(f)
        c.omitidos += int(i)
    c.nombres_fallados = _RE_CARGO_FALLO.findall(salida)[:50]
    return c


_PARSERS = (_pytest, _unittest, _jest, _vitest, _tap, _mocha, _cargo, _go)


def contar_tests(salida: str, codigo: Optional[int] = None) -> ConteoTests:
    """Conteo de tests a partir de la salida combinada (stdout + stderr)."""
    texto = sin_ansi(salida or "")
    for parser in _PARSERS:
        try:
            conteo = parser(texto)
        except (ValueError, IndexError):
            conteo = None
        if conteo is not None:
            if codigo not in (None, 0) and conteo.ok and conteo.total and not conteo.fallados:
                # El runner dijo que todo pasó pero salió con error (p. ej. crash al final): cuenta como error.
                conteo.errores += 1
            return conteo
    if codigo is None:
        return ConteoTests()
    if codigo == 0:
        return ConteoTests(pasados=1, fuente="código de salida")
    return ConteoTests(fallados=1, fuente="código de salida")


def conteo_de_resultado(r: Optional["Resultado"]) -> ConteoTests:
    if r is None:
        return ConteoTests(fuente="sin suite")
    if r.omitido:
        return ConteoTests(fuente="sin tests", reconocido=True)
    if r.timeout:
        return ConteoTests(errores=1, fuente="timeout", reconocido=True)
    return contar_tests(f"{r.stdout}\n{r.stderr}", r.codigo)


_RE_SECCION_PYTEST = re.compile(r"^_{3,}\s+(.+?)\s+_{3,}$", re.M)
_RE_SECCION_UNITTEST = re.compile(r"^={20,}\n(?:FAIL|ERROR): .*$", re.M)


def fallos_relevantes(salida: str, maximo: int = 3, limite: int = 3500) -> str:
    """
    Extrae solo el detalle de los primeros fallos (sin la parte que pasó) para
    dárselo al reparador: menos ruido = mejor diagnóstico de un modelo chico.
    """
    texto = sin_ansi(salida or "")
    bloques: list[str] = []
    secciones = list(_RE_SECCION_PYTEST.finditer(texto))
    if secciones:
        for k, m in enumerate(secciones[:maximo]):
            fin = secciones[k + 1].start() if k + 1 < len(secciones) else texto.find("short test summary", m.end())
            if fin < 0:
                fin = len(texto)
            bloques.append(texto[m.start():fin].strip())
    else:
        secciones = list(_RE_SECCION_UNITTEST.finditer(texto))
        for k, m in enumerate(secciones[:maximo]):
            fin = secciones[k + 1].start() if k + 1 < len(secciones) else texto.find("\n----------------------------------------------------------------------\nRan", m.end())
            if fin < 0:
                fin = len(texto)
            bloques.append(texto[m.start():fin].strip())
    if not bloques:
        tap = re.split(r"^(?=not ok \d+)", texto, flags=re.M)
        bloques = [b.strip() for b in tap if b.startswith("not ok")][:maximo]
    if not bloques:
        return recortar(texto.strip(), limite)
    por_bloque = max(400, limite // len(bloques))
    return "\n\n".join(recortar(b, por_bloque) for b in bloques)
