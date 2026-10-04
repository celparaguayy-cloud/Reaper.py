"""Punto de entrada."""


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reaper",
        description=f"REAPER v{__version__} «{__codename__}» · agente de programación autónomo para Termux",
    )
    parser.add_argument("-p", "--pedido", help="ejecuta un pedido con el agente principal y sale")
    parser.add_argument("--construir", help="corre el pipeline completo (tests primero + torneo) y sale")
    parser.add_argument("--plan", help="solo exploración + plan y sale")
    parser.add_argument("--torneo", help="corre un torneo de implementadores para una tarea y sale")
    parser.add_argument("--escribir", nargs=2, metavar=("RUTA", "DESCRIPCION"), help="genera un archivo largo y sale")
    parser.add_argument("--proyecto", help="carpeta del workspace")
    parser.add_argument("--nuevo", nargs=2, metavar=("PLANTILLA", "CARPETA"), help="crea un proyecto desde una plantilla")
    parser.add_argument("--modelo", help="alias o id de OpenRouter (solo esta ejecución)")
    parser.add_argument("--modelo-fuerte", help="modelo para la escalada (solo esta ejecución)")
    parser.add_argument("--perfil", choices=list(PERFILES), help="preset de configuración (solo esta ejecución)")
    parser.add_argument("--modo", choices=MODOS, help="permisos (solo esta ejecución)")
    parser.add_argument("--auto", action="store_true", help="equivale a --modo auto y sin confirmar el plan")
    parser.add_argument("--sin-torneo", action="store_true", help="un solo implementador por tarea")
    parser.add_argument("--sin-animacion", action="store_true", help="banner fijo, sin animar el dragón")
    parser.add_argument("--silencioso", action="store_true", help="muestra menos detalle de los agentes")
    parser.add_argument("--doctor", action="store_true", help="diagnóstico del entorno y sale")
    parser.add_argument("--instalar", action="store_true", help="crea el comando `reaper` y sale")
    parser.add_argument("--autotest", action="store_true", help="corre los tests internos de REAPER (sin API) y sale")
    parser.add_argument("--evaluar", nargs="?", const=0, type=int, metavar="N",
                        help="benchmark con tareas reales (usa la API) y sale")
    parser.add_argument("--comportamiento", nargs="*", metavar="ID",
                        help="evals de comportamiento con el modelo real (5+5, tool loop, interactivos...) y sale")
    parser.add_argument("--dragon", action="store_true", help="muestra el dragón y sale")
    parser.add_argument("--version", action="version", version=f"REAPER {__version__} «{__codename__}»")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = construir_parser().parse_args(argv)

    if args.autotest:
        return correr_autotest()
    if args.dragon:
        if not animar_intro():
            print(banner_dragon())
        return 0

    asegurar_dirs()
    settings = cargar_settings()
    aplicar_tema(settings.tema)
    if args.perfil:
        aplicar_perfil(settings, args.perfil)
    if args.modelo:
        settings.modelo = resolver_modelo(args.modelo)
    if args.modelo_fuerte:
        settings.modelo_fuerte = args.modelo_fuerte
        settings.escalar = True
    if args.modo:
        settings.modo = args.modo
    if args.auto:
        settings.modo = "auto"
    if args.sin_torneo:
        settings.torneo = False
    if args.sin_animacion:
        settings.animacion = False

    no_interactivo = bool(args.pedido or args.construir or args.plan or args.torneo or args.escribir
                          or args.evaluar is not None or args.comportamiento is not None)
    log = LOGS_DIR / f"{datetime.now():%Y%m%d}.log" if settings.log else None
    ui = UI(interactivo=not no_interactivo or sys.stdin.isatty(), log=log,
            detalle=0 if args.silencioso else settings.detalle)

    if args.instalar:
        return 0 if instalar_lanzador(ui) else 1

    api_key = obtener_clave_api(settings)
    if args.doctor:
        llm = LLMClient(api_key, settings) if api_key else None
        return 0 if diagnostico_sistema(ui, settings, llm, probar_modelo=bool(api_key)) else 1
    if not api_key:
        if not animar_intro():
            print(banner_dragon())
        variable = settings.variable_clave() or "OPENROUTER_API_KEY"
        ui.error(f"Falta {variable}.")
        ui.tenue(f'  export {variable}="tu_key"      (agregalo a ~/.bashrc para no repetirlo)')
        ui.tenue("  python3 reaper_v7.py --doctor    revisa todo el entorno")
        return 1

    limpiar_sandboxes_viejos()
    if settings.plugins:
        cargar_plugins(ui=ui)
    try:
        if args.nuevo:
            plantilla, carpeta = args.nuevo
            destino = Path(carpeta).expanduser().resolve()
            creados = crear_desde_plantilla(plantilla, destino)
            ui.ok(f"Proyecto creado en {destino} ({len(creados)} archivos)")
            args.proyecto = str(destino)
        if args.proyecto:
            raiz = resolver_workspace(args.proyecto)
        else:
            guardado = cargar_estado().get("proyecto")
            raiz = Path(guardado) if guardado and Path(guardado).is_dir() else PROJECTS_DIR
        ws = Workspace(raiz)
    except (ErrorRuta, KeyError, FileExistsError, OSError) as e:
        ui.error(str(e) if not isinstance(e, KeyError) else f"No existe la plantilla {e}")
        return 1

    llm = LLMClient(api_key, settings)
    llm.on_evento = lambda texto: ui.tenue(f"  ↻ {texto}")
    app = App(settings, llm, ui, ws)
    if args.proyecto:
        guardar_estado(proyecto=str(ws.raiz))

    inicio = time.monotonic()
    try:
        if args.evaluar is not None:
            return 0 if correr_evaluacion(llm, settings, ui, cantidad=args.evaluar or None) else 2
        if args.comportamiento is not None:
            return 0 if correr_comportamiento(llm, settings, ui, ids=args.comportamiento) else 2
        if args.construir:
            ok = app.construir(args.construir, confirmar=not args.auto)
            if time.monotonic() - inicio > 120:
                notificar("REAPER", f"Build {'verificada ✓' if ok else 'fallida ✗'}: {args.construir[:80]}")
            return 0 if ok else 2
        if args.torneo:
            app.cmd_torneo(args.torneo)
            return 0
        if args.escribir:
            app.cmd_escribir(" ".join(args.escribir))
            return 0
        if args.plan:
            app.cmd_plan(args.plan)
            return 0
        if args.pedido:
            return 0 if app.turno(args.pedido) else 2
        return app.repl(animar=settings.animacion)
    except (KeyboardInterrupt, Cancelado):
        CANCELAR.set()
        ui.aviso("\n⏹ Interrumpido.")
        return 130
    except LLMError as e:
        ui.error(f"Modelo: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
