"""
/vigilar: corre los tests (o un comando) cada vez que cambia un archivo del proyecto.

Sin dependencias (no hay inotify en la librería estándar): compara mtimes
cada segundo, espera un instante para agrupar guardados seguidos y muestra
una línea de resultado con el conteo de tests. Ctrl+C para salir.
"""


def foto_mtimes(ws: Workspace, limite: int = 3000) -> dict[str, float]:
    foto = {}
    for ruta in ws.iterar(limite=limite):
        try:
            foto[ws.rel(ruta)] = ruta.stat().st_mtime
        except OSError:
            continue
    return foto


def diferencias_mtimes(antes: dict[str, float], despues: dict[str, float]) -> list[str]:
    cambiados = [r for r, t in despues.items() if antes.get(r) != t]
    borrados = [r for r in antes if r not in despues]
    return sorted(cambiados + borrados)


def vigilar(ws: Workspace, ui: UI, comando: Optional[str] = None, timeout: int = 300,
            intervalo: float = 1.0, max_ciclos: Optional[int] = None, dormir: Callable[[float], None] = time.sleep) -> int:
    """Devuelve la cantidad de corridas hechas (útil en tests con max_ciclos)."""
    detectado = None if comando else detectar_comando_tests(ws, completo=True)
    if not comando and not detectado:
        ui.aviso("No hay suite de tests detectada; indicá un comando: /vigilar python3 main.py")
        return 0
    etiqueta = comando or detectado[0]
    ui.info(f"Vigilando {ws.raiz} · al cambiar un archivo corro: {etiqueta}")
    ui.tenue("  Ctrl+C para salir")
    foto = foto_mtimes(ws)
    corridas = 0
    ciclos = 0

    def correr(cambiados: list[str]) -> None:
        nonlocal corridas
        corridas += 1
        hora = datetime.now().strftime("%H:%M:%S")
        if cambiados:
            ui.tenue(f"  {hora} cambió: {', '.join(cambiados[:5])}{' ...' if len(cambiados) > 5 else ''}")
        if comando:
            r = ejecutar(comando, cwd=ws.raiz, timeout=timeout, shell=True)
        else:
            r = ejecutar_tests(ws, timeout=timeout, completo=True)
        if r is None:
            ui.aviso("  la suite desapareció")
            return
        conteo = conteo_de_resultado(r)
        resumen = conteo.texto() if conteo.reconocido else f"exit {r.codigo}"
        if r.ok:
            ui.ok(f"{hora} {resumen} · {formatear_duracion(r.duracion)}")
        else:
            ui.error(f"{hora} {resumen} · {formatear_duracion(r.duracion)}")
            detalle = fallos_relevantes(f"{r.stdout}\n{r.stderr}", maximo=1, limite=1200)
            ui.tenue(recortar(detalle, 1200))
            for pista in pistas_para(r.stdout + r.stderr, 1):
                ui.tenue(f"  💡 {pista}")

    try:
        correr([])
        while max_ciclos is None or ciclos < max_ciclos:
            ciclos += 1
            dormir(intervalo)
            actual = foto_mtimes(ws)
            cambiados = diferencias_mtimes(foto, actual)
            if not cambiados:
                continue
            dormir(0.3)
            foto = foto_mtimes(ws)
            correr(cambiados)
    except KeyboardInterrupt:
        ui.linea("")
        ui.tenue("Fin de la vigilancia.")
    return corridas
