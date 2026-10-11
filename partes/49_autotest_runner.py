"""Ejecutor del autotest interno."""


def clases_de_test() -> list:
    return sorted(
        (obj for nombre, obj in globals().items()
         if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and nombre.startswith("Test")),
        key=lambda c: c.__name__,
    )


class _ResultadoCronometrado(unittest.TextTestResult):
    """Mide cada test y deja ver cuál está corriendo (para el vigía de tests colgados)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tiempos: list = []
        self.actual: Optional[str] = None
        self.inicio_actual = 0.0

    def startTest(self, test):
        self.actual, self.inicio_actual = test.id(), time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        self.tiempos.append((time.monotonic() - self.inicio_actual, test.id()))
        self.actual = None
        super().stopTest(test)


def _vigia_tests(resultado: "_ResultadoCronometrado", alerta: float, fin: threading.Event) -> None:
    """
    Si un test pasa de `alerta` segundos, dice CUÁL es y vuelca la pila de todos los hilos (dónde está trabado:
    socket, subprocess, join...). Solo diagnostica: no mata el test ni cambia timeouts (batería atascada en Termux).
    """
    import faulthandler
    avisado = None
    while not fin.wait(1.0):
        actual = resultado.actual
        if actual and actual != avisado and time.monotonic() - resultado.inicio_actual > alerta:
            avisado = actual
            print(f"\n⏱ VIGÍA (no es un error; el test SIGUE corriendo): {actual} lleva más de {alerta:.0f}s. "
                  "Si nunca termina, esta pila muestra dónde está trabado:", file=sys.stderr, flush=True)
            try:
                faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            except (OSError, ValueError, RuntimeError):
                pass


def correr_autotest(filtro: Optional[str] = None, verbosidad: Optional[int] = None) -> int:
    filtro = (filtro if filtro is not None else os.getenv("REAPER_AUTOTEST", "")).lower()
    verbosidad = verbosidad if verbosidad is not None else (2 if os.getenv("REAPER_AUTOTEST_V") else 1)
    cargador = unittest.TestLoader()
    suite = unittest.TestSuite()
    for clase in clases_de_test():
        if filtro and filtro not in clase.__name__.lower():
            continue
        suite.addTests(cargador.loadTestsFromTestCase(clase))
    total = suite.countTestCases()
    if total == 0:
        # Un filtro que no coincide con nada NO es "todo verde": sería un falso éxito (A20).
        disponibles = ", ".join(c.__name__ for c in clases_de_test()[:12])
        print(f"No hay tests que coincidan con el filtro {filtro!r}. Clases: {disponibles}…", file=sys.stderr)
        return 2
    print(f"{Tema.titulo}{C.BOLD}🐉 REAPER {__version__} · autotest{C.RESET} {Tema.tenue}"
          f"({total} tests, sin API){C.RESET}")
    inicio = time.monotonic()
    runner = unittest.TextTestRunner(verbosity=verbosidad, stream=sys.stdout, resultclass=_ResultadoCronometrado)
    fin_vigia = threading.Event()
    try:
        # En el teléfono todo es ~15x más lento (la suite tardó 22 min en Termux): umbral más alto allí.
        alerta = float(os.getenv("REAPER_AUTOTEST_ALERTA", "180" if es_termux() else "60"))
    except ValueError:
        alerta = 60.0
    original_crear = runner._makeResult

    def _crear():
        r = original_crear()
        if alerta > 0:
            threading.Thread(target=_vigia_tests, args=(r, alerta, fin_vigia), name="vigia-autotest",
                             daemon=True).start()
        return r

    runner._makeResult = _crear
    try:
        resultado = runner.run(suite)
    finally:
        fin_vigia.set()
    duracion = formatear_duracion(time.monotonic() - inicio)
    lentos = sorted(getattr(resultado, "tiempos", []), reverse=True)[:8]
    if lentos and lentos[0][0] >= 2.0:
        print(f"{Tema.tenue}Tests más lentos: " + "; ".join(f"{n.split('.', 1)[-1]} {s:.1f}s" for s, n in lentos
                                                            if s >= 1.0) + C.RESET)
    if resultado.wasSuccessful():
        print(f"{Tema.ok}✓ {resultado.testsRun} tests OK en {duracion}"
              f"{f' ({len(resultado.skipped)} salteados)' if resultado.skipped else ''}{C.RESET}")
        return 0
    print(f"{Tema.error}✗ {len(resultado.failures)} fallos y {len(resultado.errors)} errores de "
          f"{resultado.testsRun} tests ({duracion}){C.RESET}")
    return 1
