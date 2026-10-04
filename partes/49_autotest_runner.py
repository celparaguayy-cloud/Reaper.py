"""Ejecutor del autotest interno."""


def clases_de_test() -> list:
    return sorted(
        (obj for nombre, obj in globals().items()
         if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and nombre.startswith("Test")),
        key=lambda c: c.__name__,
    )


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
    print(f"{Tema.titulo}{C.BOLD}🐉 REAPER v{__version__} · autotest{C.RESET} {Tema.tenue}"
          f"({total} tests, sin API){C.RESET}")
    inicio = time.monotonic()
    resultado = unittest.TextTestRunner(verbosity=verbosidad, stream=sys.stdout).run(suite)
    duracion = formatear_duracion(time.monotonic() - inicio)
    if resultado.wasSuccessful():
        print(f"{Tema.ok}✓ {resultado.testsRun} tests OK en {duracion}"
              f"{f' ({len(resultado.skipped)} salteados)' if resultado.skipped else ''}{C.RESET}")
        return 0
    print(f"{Tema.error}✗ {len(resultado.failures)} fallos y {len(resultado.errors)} errores de "
          f"{resultado.testsRun} tests ({duracion}){C.RESET}")
    return 1
