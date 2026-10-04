"""
Parsers de salida de tests para más lenguajes (se suman a los de 11_testparse):

  minitest (Ruby)   "5 runs, 9 assertions, 1 failures, 0 errors, 0 skips"
  TAP plano (Perl prove / Test::More, bats, runners propios)   "1..N" + "ok N - x" / "not ok N - x"
  prove             "Files=1, Tests=4, ...  Result: PASS|FAIL"
  PHPUnit           "OK (12 tests, 30 assertions)" / "Tests: 12, Assertions: 30, Failures: 2."
  JUnit console     "[ 10 tests successful ]" / "[ 2 tests failed ]"
  Ctest             "100% tests passed, 0 tests failed out of 7"
"""

_RE_MINITEST = re.compile(r"(\d+) (?:runs|tests), (\d+) assertions, (\d+) failures, (\d+) errors(?:, (\d+) skips)?")
_RE_MINITEST_FALLO = re.compile(r"^\s*\d+\) (?:Failure|Error):\n(\S+?)(?:\s|$)", re.M)
_RE_TAP_PLAN = re.compile(r"^\s*1\.\.(\d+)", re.M)
_RE_TAP_OK = re.compile(r"^\s*ok \d+\b", re.M)
_RE_TAP_NOK = re.compile(r"^\s*not ok \d+(?:\s*-\s*(.+))?$", re.M)
_RE_TAP_SKIP = re.compile(r"^\s*ok \d+.*#\s*(?:skip|SKIP|todo|TODO)", re.M)
_RE_PROVE = re.compile(r"Files=\d+, Tests=(\d+),.*?Result: (PASS|FAIL)", re.S)
_RE_PHPUNIT_OK = re.compile(r"^OK \((\d+) tests?, \d+ assertions?\)", re.M)
_RE_PHPUNIT_MAL = re.compile(r"^Tests: (\d+), Assertions: \d+(?:, (?:Errors: (\d+)|Failures: (\d+)|Skipped: (\d+)|"
                             r"Incomplete: \d+|Risky: \d+|Warnings: \d+|Deprecations: \d+|Notices: \d+)[,.]?)*", re.M)
_RE_JUNIT = re.compile(r"\[\s*(\d+) tests (successful|failed|skipped|aborted)\s*\]")
_RE_CTEST = re.compile(r"(\d+)% tests passed, (\d+) tests failed out of (\d+)")


def _minitest(salida: str) -> Optional[ConteoTests]:
    m = None
    for m in _RE_MINITEST.finditer(salida):
        pass
    if not m:
        return None
    corridas, _asserts, fallas, errores = (int(m.group(i)) for i in range(1, 5))
    omitidos = int(m.group(5) or 0)
    c = ConteoTests(fuente="minitest", reconocido=True)
    c.fallados, c.errores, c.omitidos = fallas, errores, omitidos
    c.pasados = max(0, corridas - fallas - errores - omitidos)
    c.nombres_fallados = _RE_MINITEST_FALLO.findall(salida)[:50]
    return c


def _tap_plano(salida: str) -> Optional[ConteoTests]:
    prove = _RE_PROVE.search(salida)
    oks = len(_RE_TAP_OK.findall(salida))
    noks = _RE_TAP_NOK.findall(salida)
    plan = _RE_TAP_PLAN.search(salida)
    if not plan and not prove and not (oks or noks):
        return None
    if not plan and not prove and not re.search(r"^#\s*(?:fail|pass|tests)\b", salida, re.M):
        return None
    c = ConteoTests(fuente="TAP", reconocido=True)
    saltados = len(_RE_TAP_SKIP.findall(salida))
    c.pasados = max(0, oks - saltados)
    c.omitidos = saltados
    c.fallados = len(noks)
    c.nombres_fallados = [n.strip() for n in noks if n][:50]
    if plan:
        faltan = int(plan.group(1)) - (oks + len(noks))
        if faltan > 0:
            c.errores += faltan        # el script murió antes de correr todos los tests del plan
    if prove and not (oks or noks):
        total = int(prove.group(1))
        if prove.group(2) == "PASS":
            c.pasados = total
        else:
            c.fallados = max(1, c.fallados)
    return c


def _phpunit(salida: str) -> Optional[ConteoTests]:
    m = _RE_PHPUNIT_OK.search(salida)
    if m:
        return ConteoTests(int(m.group(1)), 0, 0, 0, "phpunit", [], True)
    m = _RE_PHPUNIT_MAL.search(salida)
    if not m:
        return None
    linea = salida[m.start():salida.find("\n", m.start()) if "\n" in salida[m.start():] else len(salida)]
    total = int(m.group(1))
    errores = int((re.search(r"Errors: (\d+)", linea) or [0, 0])[1])
    fallas = int((re.search(r"Failures: (\d+)", linea) or [0, 0])[1])
    omitidos = int((re.search(r"Skipped: (\d+)", linea) or [0, 0])[1])
    nombres = re.findall(r"^\d+\) (\S+)$", salida, re.M)[:50]
    return ConteoTests(max(0, total - errores - fallas - omitidos), fallas, errores, omitidos, "phpunit", nombres, True)


def _junit(salida: str) -> Optional[ConteoTests]:
    datos = {tipo: int(n) for n, tipo in _RE_JUNIT.findall(salida)}
    if not datos:
        return None
    return ConteoTests(datos.get("successful", 0), datos.get("failed", 0), datos.get("aborted", 0),
                       datos.get("skipped", 0), "junit", re.findall(r"✘\s+(.+?)\s*$", salida, re.M)[:50], True)


def _ctest(salida: str) -> Optional[ConteoTests]:
    m = _RE_CTEST.search(salida)
    if not m:
        return None
    fallados, total = int(m.group(2)), int(m.group(3))
    nombres = re.findall(r"^\s*\d+ - (\S+) \(Failed\)", salida, re.M)
    return ConteoTests(total - fallados, fallados, 0, 0, "ctest", nombres[:50], True)


# El TAP con resumen "# pass/# fail" (node --test) va antes; el TAP plano al final porque es el más genérico.
_PARSERS = _PARSERS + (_minitest, _phpunit, _junit, _ctest, _tap_plano)
