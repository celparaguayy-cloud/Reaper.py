"""Punto de entrada."""


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reaper",
        description=f"REAPER {__version__} · agente de programación autónomo para Termux",
    )
    parser.add_argument("-p", "--pedido", help="ejecuta un pedido con el agente principal y sale")
    parser.add_argument("--construir", help="corre el pipeline completo (tests primero + torneo) y sale. "
                                            "'continuar' / 'estado' retoman o muestran la build que quedó a medias")
    parser.add_argument("--grande", help="proyecto grande por etapas verificadas (plan maestro + un /construir por "
                                         "etapa + integración final) y sale. 'continuar' / 'estado' retoman o "
                                         "muestran el que quedó a medias")
    parser.add_argument("--reporte", action="store_true",
                        help="arma un ZIP para mandar (informes, estado, logs, árbol y código; sin claves) y sale")
    parser.add_argument("--plan", help="solo exploración + plan y sale")
    parser.add_argument("--torneo", help="corre un torneo de implementadores para una tarea y sale")
    parser.add_argument("--escribir", nargs=2, metavar=("RUTA", "DESCRIPCION"), help="genera un archivo largo y sale")
    parser.add_argument("--proyecto", help="carpeta del workspace")
    parser.add_argument("--nuevo", nargs=2, metavar=("PLANTILLA", "CARPETA"), help="crea un proyecto desde una plantilla")
    parser.add_argument("--plantillas", action="store_true", help="lista plantillas sin clave de IA")
    parser.add_argument("--auditar-web", nargs="?", const="", metavar="CARPETA",
                        help="auditoría estructural web offline (no ejecuta código del proyecto)")
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
    parser.add_argument("--aceptacion", action="store_true",
                        help="ejecuta solo el evaluador independiente sin gastar API")
    parser.add_argument("--autotest-filtro", metavar="NOMBRE",
                        help="ejecuta solo clases internas de test que incluyan ese nombre")
    parser.add_argument("--evaluar", nargs="?", const=0, type=int, metavar="N",
                        help="benchmark con tareas reales (usa la API) y sale")
    parser.add_argument("--comportamiento", nargs="*", metavar="ID",
                        help="evals de comportamiento con el modelo real (5+5, tool loop, interactivos...) y sale")
    parser.add_argument("--dragon", action="store_true", help="muestra el dragón y sale")
    parser.add_argument("--version", action="version", version=f"REAPER {__version__}")
    return parser


def aplicar_flags_cli(settings: Settings, args) -> Settings:
    """Flags de línea de comandos ("solo esta ejecución"): tienen la máxima precedencia."""
    if args.perfil:
        catalogo = (catalogo_free_openrouter() if args.perfil.strip().lower() == "gratis"
                    and settings.proveedor == "openrouter" else None)
        aplicar_perfil(settings, args.perfil, catalogo)
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
    return settings


def preparar_settings_proyecto(settings: Settings, ws: Workspace, args) -> Settings:
    """
    Precedencia (R-011): defaults < config global < .reaper/config.json del proyecto < entorno < flags CLI.
    Si el proyecto no trae sección "settings", devuelve los settings sin tocar.
    """
    local = ws.config_local()
    if not local.get("settings"):
        return settings
    combinado = settings_con_local(settings, local)
    aplicar_overrides_entorno(combinado)
    return aplicar_flags_cli(combinado, args)


def main(argv: Optional[list] = None) -> int:
    args = construir_parser().parse_args(argv)

    if args.autotest or args.autotest_filtro is not None:
        return correr_autotest(filtro=args.autotest_filtro)
    if args.dragon:
        if not animar_intro():
            print(banner_dragon())
        return 0

    asegurar_dirs()
    settings = cargar_settings()
    aplicar_tema(settings.tema)
    aplicar_flags_cli(settings, args)

    no_interactivo = bool(args.pedido or args.construir or args.grande or args.reporte or args.plan or args.torneo or args.escribir
                          or args.evaluar is not None or args.comportamiento is not None or args.aceptacion)
    log = LOGS_DIR / f"{datetime.now():%Y%m%d}.log" if settings.log else None
    ui = UI(interactivo=not no_interactivo or sys.stdin.isatty(), log=log,
            detalle=0 if args.silencioso else settings.detalle)

    if args.instalar:
        return 0 if instalar_lanzador(ui) else 1

    # Crear / inspeccionar proyectos locales nunca debe exigir una API externa.
    if args.plantillas:
        for nombre, plantilla in sorted(todas_las_plantillas().items()):
            print(f"{nombre:24} {plantilla.lenguaje:12} {plantilla.descripcion}")
        return 0
    if args.nuevo:
        nombre, carpeta = args.nuevo
        try:
            destino = Path(carpeta).expanduser().resolve()
            creados = crear_desde_plantilla(nombre, destino)
        except (OSError, KeyError, ValueError) as e:
            ui.error(str(e))
            return 1
        ui.ok(f"Proyecto creado: {destino} ({len(creados)} archivos).")
        ui.tenue(f"  Ejecutalo o probalo desde esa carpeta. Para abrirlo en REAPER: reaper --proyecto {shlex.quote(str(destino))}")
        return 0
    if args.auditar_web is not None:
        carpeta = Path(args.auditar_web or args.proyecto or os.getcwd()).expanduser()
        if not carpeta.is_dir():
            ui.error(f"No existe la carpeta: {carpeta}")
            return 1
        reporte = auditar_web_proyecto(carpeta)
        ui.info(f"Auditoría web estática: {carpeta} · {reporte['paginas']} entrada(s) HTML")
        for hallazgo in reporte['hallazgos']:
            (ui.error if hallazgo.startswith(('ERROR:', 'RIESGO:')) else ui.aviso)(hallazgo)
        (ui.ok if reporte['ok'] else ui.error)(reporte['estado'])
        return 0 if reporte['ok'] else 2

    if args.aceptacion:
        carpeta = Path(args.proyecto or os.getcwd()).expanduser().resolve()
        if not carpeta.is_dir():
            ui.error(f'No existe el proyecto: {carpeta}')
            return 2
        verif_externa = ejecutar_aceptacion_independiente(Workspace(carpeta))
        if verif_externa is None:
            ui.error('No hay .reaper/acceptance.json; no hay pruebas independientes configuradas.')
            return 2
        print(verif_externa.resumen(4000))
        return 0 if verif_externa.ok else 2

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
        ui.tenue("  python3 reaper_8.10.py --doctor    revisa todo el entorno")
        return 1

    limpiar_sandboxes_viejos()
    if settings.plugins:
        cargar_plugins(ui=ui)
    try:
        if args.proyecto:
            # Un /construir o /grande NUEVO crea su carpeta (lo normal es que todavía no exista); retomar, ver el
            # estado o deshacer necesitan una carpeta que ya exista.
            nuevo = bool((args.construir and args.construir.strip().lower() not in ("continuar", "estado"))
                         or (args.grande and args.grande.strip().lower() not in ("continuar", "estado", "deshacer")))
            existia = Path(os.path.expandvars(args.proyecto.strip())).expanduser().exists()
            raiz = resolver_workspace(args.proyecto, crear=nuevo)
            if nuevo and not existia:
                ui.ok(f"Creé la carpeta del proyecto: {_ruta_corta(raiz)}")
        else:
            guardado = cargar_estado().get("proyecto")
            raiz = Path(guardado) if guardado and Path(guardado).is_dir() else PROJECTS_DIR
        ws = Workspace(raiz)
    except (ErrorRuta, KeyError, FileExistsError, OSError) as e:
        ui.error(str(e) if not isinstance(e, KeyError) else f"No existe la plantilla {e}")
        return 1

    # R-011: aplicar los overrides de .reaper/config.json del proyecto ANTES de construir el cliente, para que
    # candidatos/torneo/rpm/modelo/temperatura del proyecto manden de verdad (antes se definían y se ignoraban).
    if ws.config_local().get("settings"):
        ignorados = overrides_proyecto_ignorados(ws.config_local(), settings)
        settings = preparar_settings_proyecto(settings, ws, args)
        api_key = obtener_clave_api(settings) or api_key        # el proyecto pudo cambiar el modelo/proveedor
        ui.tenue("  Apliqué overrides de .reaper/config.json (settings del proyecto).")
        if ignorados:
            ui.aviso("  Ignoré claves inseguras del .reaper/config.json del proyecto (no cambian a dónde van "
                     "tus credenciales, la red ni aflojan tus permisos): " + ", ".join(sorted(ignorados)) + ".")

    llm = LLMClient(api_key, settings)
    llm.on_evento = lambda texto: ui.tenue(f"  ↻ {texto}")
    if (args.perfil or "").strip().lower() == "gratis" and settings.proveedor == "openrouter" and api_key \
            and (args.construir or args.grande):
        # Igual que /perfil gratis: solo los :free que RESPONDEN hoy (el catálogo no dice cuáles dan 403 o están
        # caídos). Con memoria de 6 h: cada sondeo es un pedido del cupo diario.
        catalogo = catalogo_free_openrouter()
        if catalogo:
            vivos = free_vivos(llm, catalogo, on_probar=lambda m: ui.tenue(f"  probando {m}"))
            if vivos:
                aplicar_perfil(settings, "gratis", vivos)
                ui.tenue(f"  Modelos gratis que responden: {', '.join(vivos)}")
    app = App(settings, llm, ui, ws)
    if args.proyecto:
        guardar_estado(proyecto=str(ws.raiz))

    inicio = time.monotonic()
    try:
        if args.evaluar is not None:
            return 0 if correr_evaluacion(llm, settings, ui, cantidad=args.evaluar or None) else 2
        if args.comportamiento is not None:
            return 0 if correr_comportamiento(llm, settings, ui, ids=args.comportamiento) else 2
        if args.reporte:
            app.cmd_reporte("")
            return 0
        if args.construir and args.construir.strip().lower() in ("continuar", "estado"):
            # Después de un corte: `reaper --proyecto X --construir continuar` (sin entrar al modo interactivo).
            if args.construir.strip().lower() == "estado":
                app.cmd_construir("estado")
                return 0
            return 0 if app.construir("", confirmar=False, reanudar=True) else 2
        if args.grande and args.grande.strip().lower() in ("continuar", "estado", "deshacer"):
            grande = ConstructorGrande(llm, app.ws, settings, ui, construir_build=app._build_de_etapa)
            if args.grande.strip().lower() == "estado":
                grande.mostrar_estado()
                return 0
            if args.grande.strip().lower() == "deshacer":          # lo tipeó a propósito: no se vuelve a preguntar
                return 0 if grande.deshacer_etapa() else 2
            return 0 if grande.continuar() else 2
        if args.construir:
            ok = app.construir(args.construir, confirmar=not args.auto)
            if time.monotonic() - inicio > 120:
                notificar("REAPER", f"Build {'verificada ✓' if ok else 'fallida ✗'}: {args.construir[:80]}")
            return 0 if ok else 2
        if args.grande:
            grande = ConstructorGrande(llm, app.ws, settings, ui, construir_build=app._build_de_etapa)
            ok = grande.iniciar(args.grande, confirmar=not args.auto)
            if time.monotonic() - inicio > 120:
                notificar("REAPER", f"Proyecto grande {'terminado ✓' if ok else 'incompleto ✗'}: {args.grande[:80]}")
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
        pista = pista_para_seguir(ws)
        if pista:
            ui.info(pista)
        return 130
    except LLMError as e:
        ui.error(f"Modelo: {e}")
        pista = pista_para_seguir(ws)
        if pista:
            ui.info(pista)
        return 1


class TestReaper810BuildResume(BaseTest):
    """Regresiones del diario por tarea; no consumen APIs."""

    def test_registro_persiste_sin_guardar_secretos(self):
        ws = self.proyecto({"main.py": "x = 1\n"})
        r = RegistroBuild(ws)
        cid = ws.checkpoints.iniciar("build")
        plan = Plan("crear", [Tarea("1", "archivo", ["main.py"])], [])
        datos = {"esquema": 1, "proyecto": str(ws.raiz), "pedido": "crear", "plan": asdict(plan),
                 "grupo": cid, "estados": {"1": "en_curso"}, "estado": "en_curso"}
        r.guardar(datos)
        self.assertEqual(RegistroBuild(ws).leer()["estados"]["1"], "en_curso")
        self.assertTrue(r.recuperable(r.leer()))

    def test_no_permite_modificaciones_externas(self):
        ws = self.proyecto({"main.py": "x = 1\n"})
        r = RegistroBuild(ws)
        cid = ws.checkpoints.iniciar("build")
        datos = {"esquema": 1, "proyecto": str(ws.raiz), "pedido": "crear", "plan":
                 asdict(Plan("crear", [Tarea("1", "código")], [])), "grupo": cid,
                 "estados": {}, "estado": "en_curso"}
        r.guardar(datos)
        (ws.raiz / "main.py").write_text("x = 999\n")
        self.assertFalse(r.recuperable(r.leer()))

    def test_recupera_tarea_interrumpida_de_checkpoint(self):
        ws = self.proyecto({"uno.py": "x = 1\n"})
        r = RegistroBuild(ws)
        cid = ws.checkpoints.iniciar("build")
        datos = {"esquema": 1, "proyecto": str(ws.raiz), "pedido": "crear", "plan":
                 asdict(Plan("crear", [Tarea("1", "primero"), Tarea("2", "segundo")], [])),
                 "grupo": cid, "estados": {"1": "verificada", "2": "en_curso"},
                 "archivos_verificados": {"uno.py": ws.hash("uno.py")},
                 "estado": "en_curso", "tarea_activa": "2", "huellas_inicio": r.huellas()}
        tcid = ws.checkpoints.iniciar("tarea 2", grupo=cid)
        datos["tcid"] = tcid
        r.guardar(datos)
        ws.escribir("dos.py", "x = 2\n")
        self.assertTrue(r.recuperable(r.leer()))
        ws.escribir("uno.py", "x = 99\n")
        self.assertFalse(r.recuperable(r.leer()))

    def test_registro_corrupto_no_se_considera_valido(self):
        ws = self.proyecto()
        r = RegistroBuild(ws)
        r.ruta.parent.mkdir(exist_ok=True, parents=True)
        r.ruta.write_text("{mal json")
        with self.assertRaises(ValueError):
            r.leer()

    def test_resume_salta_tarea_verificada_sin_replanificar(self):
        ws = self.proyecto({"uno.py": "x = 1\n"})
        cid = ws.checkpoints.iniciar("build")
        r = RegistroBuild(ws)
        plan = Plan("dos archivos", [Tarea("1", "uno", ["uno.py"]),
                                     Tarea("2", "dos", ["dos.py"])], [])
        datos = {"esquema": 1, "proyecto": str(ws.raiz), "pedido": "dos archivos",
                 "plan": asdict(plan), "grupo": cid, "estados": {"1": "verificada"},
                 "archivos_verificados": {"uno.py": ws.hash("uno.py")},
                 "estado": "en_curso", "tests_protegidos": {}}
        r.guardar(datos)
        orq = Orquestador(MockLLM([]), ws, self.ajustes(tests_primero=False, qa=False,
                                                     max_revisiones=0, max_reparaciones=0), self.ui())
        def implementar(pedido, plan, indice, exploracion, checkpoint, **kw):
            self.assertEqual(indice, 1, "No debe reimplementar la tarea verificada")
            ws.escribir("dos.py", "x = 2\n")
            return type("Resultado", (), {"ok": True, "modo": "simple", "ganador": None})()
        orq.implementar = implementar
        orq.obtener_plan = lambda *args: self.fail("No debe consultar al arquitecto para reanudar")
        reporte = orq.construir("", confirmar=False, reanudar=True)
        self.assertTrue(reporte.ok, reporte.diagnostico)
        self.assertTrue(ws.existe("uno.py"))
        self.assertTrue(ws.existe("dos.py"))
        self.assertFalse(r.ruta.exists(), "La build completa limpia su registro de espera")

    def test_nueva_build_no_pisa_registro_inconcluso(self):
        ws = self.proyecto({"main.py": "x = 1\n"})
        r = RegistroBuild(ws)
        cid = ws.checkpoints.iniciar("build")
        datos = {"esquema": 1, "proyecto": str(ws.raiz), "pedido": "anterior",
                 "plan": asdict(Plan("anterior", [Tarea("1", "primero")], [])),
                 "grupo": cid, "estados": {}, "estado": "en_curso"}
        r.guardar(datos)
        orq = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        informe = orq.construir("nuevo", confirmar=False)
        self.assertEqual(informe.estado, "cancelada")
        self.assertEqual(r.leer()["pedido"], "anterior")

class TestReaper810Round5(BaseTest):
    """Planes inválidos, recuperación de especificación y aislamiento de archivos."""

    def test_grafo_inexistente_no_se_ejecuta(self):
        ws = self.proyecto()
        o = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        o.obtener_plan = lambda *args: (Plan("x", [Tarea("1", "x", deps=["no-existe"])], []), "")
        o.implementar = lambda *args, **kw: self.fail("no ejecutar implementación")
        self.assertEqual(o.construir("crear", confirmar=False).estado, "cancelada")
        self.assertFalse(RegistroBuild(ws).ruta.exists())

    def test_grafo_ciclico_no_se_ejecuta(self):
        ws = self.proyecto()
        o = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        o.obtener_plan = lambda *args: (Plan("x", [Tarea("1", "primera", deps=["2"]),
                                              Tarea("2", "segunda", deps=["1"])], []), "")
        o.implementar = lambda *args, **kw: self.fail("no ejecutar implementación")
        self.assertEqual(o.construir("crear", confirmar=False).estado, "cancelada")

    def test_grafo_duplicado_y_autodependencia_rechazados(self):
        self.assertTrue(errores_grafo_build(Plan("x", [Tarea("1", "uno"), Tarea("1", "dos")], [])))
        self.assertTrue(errores_grafo_build(Plan("x", [Tarea("1", "uno", deps=["1"])], [])))

    def test_iterador_no_expone_symlinks_externos(self):
        ws = self.proyecto({"seguro.py": "print(1)\n"})
        fuera = self.dir / "privado.py"
        fuera.write_text("token=secreto_superprivado_123\n")
        (ws.raiz / "alias.py").symlink_to(fuera)
        nombres = [ws.rel(r) for r in ws.iterar()]
        self.assertIn("seguro.py", nombres)
        self.assertNotIn("alias.py", nombres)
        self.assertNotIn(fuera.as_posix(), nombres)

    def _registro_para_especificacion(self, ws, completada):
        checkpoint = ws.checkpoints.iniciar("build")
        plan = Plan("prueba", [Tarea("1", "app", ["app.py"])], [])
        RegistroBuild(ws).guardar({"esquema": 1, "proyecto": str(ws.raiz), "pedido": "prueba",
            "plan": asdict(plan), "grupo": checkpoint, "estados": {}, "estado": "en_curso",
            "tests_primero": True, "especificacion_completa": completada})

    def _orq_mock_app(self, ws):
        orq = Orquestador(MockLLM([]), ws, self.ajustes(tests_primero=True,
                          max_revisiones=0, max_reparaciones=0), self.ui())
        def implementar(pedido, plan, indice, exploracion, checkpoint, **kw):
            ws.escribir("app.py", "x = 1\n")
            return type("Resultado", (), {"ok": True, "modo": "simple", "ganador": None})()
        orq.implementar = implementar
        return orq

    def test_reanuda_especificacion_incompleta(self):
        ws = self.proyecto()
        self._registro_para_especificacion(ws, False)
        orq = self._orq_mock_app(ws)
        llamadas = []
        orq.especificar = lambda *args: (llamadas.append("spec") or {})
        self.assertTrue(orq.construir("", confirmar=False, reanudar=True).ok)
        self.assertEqual(llamadas, ["spec"])

    def test_no_repite_especificacion_completa(self):
        ws = self.proyecto()
        self._registro_para_especificacion(ws, True)
        orq = self._orq_mock_app(ws)
        orq.especificar = lambda *args: self.fail("No debe repetir una etapa completada")
        self.assertTrue(orq.construir("", confirmar=False, reanudar=True).ok)

    def test_redactor_json_con_claves_entrecomilladas(self):
        ejemplo = '{"OPENROUTER_API_KEY": "clave_de_prueba_123456", "WHATSAPP_ACCESS_TOKEN": "token_ficticio_abcdef"}'
        salida = redactar_secretos(ejemplo)
        self.assertNotIn("clave_de_prueba_123456", salida)
        self.assertNotIn("token_ficticio_abcdef", salida)
        self.assertIn('"OPENROUTER_API_KEY": "[REDACTADO]"', salida)

    def test_informe_redacta_credenciales(self):
        ws = self.proyecto()
        orq = Orquestador(MockLLM([]), ws, self.ajustes(), self.ui())
        ruta = orq._guardar_informe("token=secreto123456789", InformeBuild("fallida",
                      diagnostico="api_key=abcdef123456789"))
        contenido = ruta.read_text()
        self.assertIn("[REDACTADO]", contenido)
        self.assertNotIn("secreto123456789", contenido)
        self.assertNotIn("abcdef123456789", contenido)



class TestReaper810Round6(BaseTest):
    """Regresiones: archivos de contexto, diario y reanudación contra cambios externos."""

    def test_memoria_no_sigue_enlace_a_archivo_externo(self):
        ws = self.proyecto({"AGENTS.md": "Instrucciones ordinarias"})
        secreto = self.dir / "privado.txt"
        secreto.write_text("contenido_confidencial_fuera_del_proyecto", encoding="utf-8")
        (ws.raiz / "REAPER.md").symlink_to(secreto)
        self.assertNotIn("contenido_confidencial", ws.memoria())
        self.assertIn("Instrucciones ordinarias", ws.memoria())

    def test_notas_no_sigue_enlace_externo(self):
        ws = self.proyecto()
        externo = self.dir / "notas_privadas.txt"
        externo.write_text("informacion_privada_fuera_del_proyecto", encoding="utf-8")
        ws.carpeta_reaper().mkdir(parents=True)
        (ws.carpeta_reaper() / "notas.md").symlink_to(externo)
        self.assertEqual(ws.notas(), "")

    def test_config_local_no_sigue_enlaces(self):
        ws = self.proyecto()
        externo = self.dir / "config_ajena.json"
        externo.write_text('{"settings": {"modo": "auto"}}', encoding="utf-8")
        ws.carpeta_reaper().mkdir(parents=True)
        (ws.carpeta_reaper() / "config.json").symlink_to(externo)
        self.assertEqual(ws.config_local(), {})

    def test_memoria_redacta_tokens(self):
        ws = self.proyecto({"REAPER.md": "OPENROUTER_API_KEY=secreto_de_prueba_12345"})
        self.assertNotIn("secreto_de_prueba_12345", ws.memoria())
        self.assertIn("[REDACTADO]", ws.memoria())

    def test_huellas_detectan_cambio_binario(self):
        ws = self.proyecto({"app.py": "pass\n"})
        binario = ws.raiz / "datos.sqlite3"
        binario.write_bytes(b"uno\x00dos")
        r = RegistroBuild(ws)
        cid = ws.checkpoints.iniciar("build")
        r.guardar({"esquema": 1, "proyecto": str(ws.raiz), "pedido": "crear",
                   "plan": asdict(Plan("prueba", [Tarea("1", "app")], [])),
                   "grupo": cid, "estados": {}, "estado": "en_curso"})
        previo = r.leer()
        binario.write_bytes(b"CAMBIADO\x00")
        self.assertFalse(r.recuperable(previo))

    def test_huellas_detectan_symlink_añadido(self):
        ws = self.proyecto({"app.py": "pass\n"})
        r = RegistroBuild(ws)
        primero = r.huellas()
        externo = self.dir / "exterior.txt"
        externo.write_text("privado")
        (ws.raiz / "alias.txt").symlink_to(externo)
        segundo = r.huellas()
        self.assertNotEqual(primero, segundo)
        self.assertIn("alias.txt", segundo)

    def test_registro_invalido_no_se_reanuda(self):
        ws = self.proyecto()
        r = RegistroBuild(ws)
        cid = ws.checkpoints.iniciar("build")
        r.guardar({"esquema": 1, "proyecto": str(ws.raiz), "pedido": "crear",
                   "plan": {"tareas": [{"id": "1"}]},
                   "grupo": cid, "estados": {}, "estado": "en_curso"})
        with self.assertRaisesRegex(ValueError, "plan"):
            r.leer()

    def test_memoria_ordinaria_se_conserva(self):
        ws = self.proyecto({"REAPER.md": "Regla: documentar el código"})
        self.assertIn("Regla: documentar el código", ws.memoria())

    def test_gitignore_externo_no_oculta_codigo(self):
        ws = self.proyecto({"main.py": "print(1)\n"})
        externo = self.dir / "reglas_ajenas.txt"
        externo.write_text("*.py\n", encoding="utf-8")
        (ws.raiz / ".gitignore").symlink_to(externo)
        archivos = [ws.rel(r) for r in ws.iterar()]
        self.assertIn("main.py", archivos)


    def test_diario_legado_no_omite_tareas_sin_evidencia(self):
        ws = self.proyecto({"app.py": "x = 0\n"})
        r = RegistroBuild(ws)
        cid = ws.checkpoints.iniciar("build")
        r.guardar({"esquema": 1, "proyecto": str(ws.raiz), "pedido": "app",
                   "plan": asdict(Plan("app", [Tarea("1", "hacer app", ["app.py"])], [])),
                   "grupo": cid, "estados": {"1": "verificada"}, "estado": "en_curso",
                   "archivos_verificados": {"app.py": ws.hash("app.py")}})
        viejo = r.leer()
        viejo.pop("huellas_version", None)
        viejo["huella"] = r.huella_legada()
        escritura_atomica(r.ruta, json.dumps(viejo))
        orq = Orquestador(MockLLM([]), ws, self.ajustes(tests_primero=False, qa=False,
                                  max_revisiones=0, max_reparaciones=0), self.ui())
        llamadas = []
        def implementar(*args, **kwargs):
            llamadas.append(1)
            ws.escribir("app.py", "x = 1\n")
            return type("Resultado", (), {"ok": True, "modo": "simple", "ganador": None})()
        orq.implementar = implementar
        orq.obtener_plan = lambda *args: self.fail("No debe replanificar")
        informe = orq.construir("", confirmar=False, reanudar=True)
        self.assertTrue(informe.ok, informe.diagnostico)
        self.assertEqual(llamadas, [1])

    def test_diario_legado_con_cambios_no_se_migra(self):
        ws = self.proyecto({"app.py": "x = 0\n"})
        r = RegistroBuild(ws)
        cid = ws.checkpoints.iniciar("build")
        r.guardar({"esquema": 1, "proyecto": str(ws.raiz), "pedido": "app",
                   "plan": asdict(Plan("app", [Tarea("1", "hacer app")], [])),
                   "grupo": cid, "estados": {}, "estado": "en_curso"})
        viejo = r.leer()
        viejo.pop("huellas_version", None)
        viejo["huella"] = r.huella_legada()
        escritura_atomica(r.ruta, json.dumps(viejo))
        (ws.raiz / "app.py").write_text("x = 999\n")
        orq = Orquestador(MockLLM([]), ws, self.ajustes(tests_primero=False), self.ui())
        self.assertEqual(orq.construir("", confirmar=False, reanudar=True).estado, "cancelada")
        self.assertNotIn("huellas_version", json.loads(r.ruta.read_text()))





# ======================================================================
# REAPER 8.10 — AUDITOR WEB ESTÁTICO LOCAL (NO ejecuta el proyecto)
# ======================================================================
def auditar_web_proyecto(carpeta: Path) -> dict:
    """Comprobación *estática*, offline y no ejecutable de estructura y recursos web."""
    carpeta = Path(carpeta).resolve()
    hallazgos = []
    paginas = []
    for candidato in ("index.html", "web/index.html", "public/index.html", "dist/index.html"):
        ruta = carpeta / candidato
        if ruta.is_symlink() or carpeta not in ruta.resolve().parents:
            hallazgos.append(f"RIESGO: {candidato} sale del proyecto mediante enlace simbólico; no se abre")
            continue
        if ruta.is_file():
            paginas.append(ruta)
    if not paginas:
        hallazgos.append("ERROR: No se encontró index.html en raíz, web/, public/ o dist/")
    revisados = 0
    for pagina in paginas:
        if pagina.stat().st_size > 2_000_000:
            hallazgos.append(f"ERROR: {pagina.relative_to(carpeta)} excede 2 MB; no se analiza")
            continue
        html = pagina.read_text(encoding="utf-8", errors="replace")
        nombre = pagina.relative_to(carpeta).as_posix()
        revisados += 1
        if not re.search(r"<title\b[^>]*>.+?</title>", html, re.I | re.S):
            hallazgos.append(f"AVISO: {nombre} no tiene <title> con texto")
        if not re.search(r'<meta\s+name=[\"\']viewport[\"\']', html, re.I):
            hallazgos.append(f"AVISO: {nombre} no declara viewport responsive")
        if not re.search(r"<html\b[^>]*lang=", html, re.I):
            hallazgos.append(f"AVISO: {nombre} no declara atributo lang")
        # Solo rutas estáticas explícitas, sin cargar HTTP ni seguir symlinks.
        for attr in re.finditer(r'(?:src|href)\s*=\s*[\"\']([^\"\']+)[\"\']', html, re.I):
            valor = attr.group(1).strip().split('?', 1)[0].split('#', 1)[0]
            if not valor or valor.startswith(('#', 'http:', 'https:', '//', 'data:', 'mailto:', 'tel:', 'javascript:')):
                continue
            if not re.search(r'\.(css|js|jsx|ts|tsx|json|webmanifest|png|jpg|jpeg|svg|webp|ico|woff2?|mjs)$', valor, re.I):
                continue
            # En app.py /style.css se sirve desde web/, no necesariamente la raíz.
            base = pagina.parent
            relativo = (carpeta / valor.lstrip('/')) if valor.startswith('/') else (base / valor)
            alternativas = [relativo]
            if valor.startswith('/') and pagina.parent != carpeta:
                alternativas.append(base / valor.lstrip('/'))
            validos = []
            for p in alternativas:
                if p.is_symlink():
                    continue
                candidato = p.resolve()
                if (candidato == carpeta or carpeta in candidato.parents) and candidato.is_file():
                    validos.append(candidato)
            if not validos:
                hallazgos.append(f"ERROR: {nombre} referencia recurso local ausente/no permitido: {valor[:140]}")
    errores = sum(x.startswith(('ERROR:', 'RIESGO:')) for x in hallazgos)
    return {"ok": errores == 0 and revisados > 0, "paginas": revisados, "hallazgos": hallazgos,
            "estado": "SIN ERRORES ESTRUCTURALES (no equivale a tests E2E)" if not errores else "REVISAR"}

# ======================================================================
# REAPER 8.10 — PLANTILLA FULL-STACK SIN DEPENDENCIAS
# ======================================================================
registrar_plantilla(
    "web-fullstack",
    "Web full-stack responsive: frontend HTML/CSS/JS + API REST Python + SQLite; tests HTTP reales, sin pip ni npm.",
    "python",
    {'app.py': '"""REAPER 8.10: web full-stack lista para desarrollo local.\n\nPython 3.9+ sin dependencias. Por defecto solo escucha en 127.0.0.1.\n"""\nimport argparse\nimport json\nimport os\nimport re\nimport sqlite3\nfrom contextlib import closing\nfrom http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\nfrom pathlib import Path\nfrom urllib.parse import parse_qs, urlsplit\n\nROOT = Path(__file__).resolve().parent\nSTATIC = ROOT / \'web\'\nDB_DEFAULT = ROOT / \'instance\' / \'tareas.sqlite3\'\nMAX_BYTES = 64 * 1024\nESTADOS = {\'pendiente\', \'progreso\', \'hecha\'}\n\n\nclass Repository:\n    def __init__(self, database):\n        self.database = Path(database)\n        self.database.parent.mkdir(parents=True, exist_ok=True)\n        with closing(self._connect()) as db:\n            db.execute(\'\'\'CREATE TABLE IF NOT EXISTS tareas (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                titulo TEXT NOT NULL,\n                descripcion TEXT NOT NULL DEFAULT \'\',\n                estado TEXT NOT NULL DEFAULT \'pendiente\',\n                creada TEXT NOT NULL DEFAULT (datetime(\'now\'))\n            )\'\'\')\n            db.commit()\n\n    def _connect(self):\n        db = sqlite3.connect(str(self.database), timeout=10)\n        db.row_factory = sqlite3.Row\n        db.execute(\'PRAGMA busy_timeout=10000\')\n        return db\n\n    def list(self, estado=\'\', buscar=\'\', limit=50, offset=0):\n        args = []\n        cond = []\n        if estado:\n            cond.append(\'estado = ?\')\n            args.append(estado)\n        if buscar:\n            cond.append(\'(titulo LIKE ? OR descripcion LIKE ?)\')\n            term = \'%\' + buscar.replace(\'%\', \'\\\\%\').replace(\'_\', \'\\\\_\') + \'%\'\n            cond[-1] = cond[-1].replace(\'LIKE ?\', "LIKE ? ESCAPE \'\\\\\'")\n            args += [term, term]\n        where = \' WHERE \' + \' AND \'.join(cond) if cond else \'\'\n        with closing(self._connect()) as db:\n            total = db.execute(\'SELECT count(*) FROM tareas\' + where, args).fetchone()[0]\n            rows = db.execute(\'SELECT * FROM tareas\' + where + \' ORDER BY id DESC LIMIT ? OFFSET ?\',\n                              args + [limit, offset]).fetchall()\n        return {\'items\': [dict(r) for r in rows], \'total\': total, \'limit\': limit, \'offset\': offset}\n\n    def get(self, task_id):\n        with closing(self._connect()) as db:\n            item = db.execute(\'SELECT * FROM tareas WHERE id = ?\', (task_id,)).fetchone()\n        return dict(item) if item else None\n\n    def create(self, data):\n        clean = validate(data, creating=True)\n        with closing(self._connect()) as db:\n            with db:\n                cur = db.execute(\'INSERT INTO tareas (titulo, descripcion, estado) VALUES (?, ?, ?)\',\n                                 (clean[\'titulo\'], clean[\'descripcion\'], clean[\'estado\']))\n                pk = cur.lastrowid\n        return self.get(pk)\n\n    def update(self, task_id, data):\n        clean = validate(data, creating=False)\n        with closing(self._connect()) as db:\n            with db:\n                actual = db.execute(\'SELECT id FROM tareas WHERE id=?\', (task_id,)).fetchone()\n                if actual is None:\n                    return None\n                if clean:\n                    cols = \', \'.join(k + \'=?\' for k in clean)\n                    db.execute(\'UPDATE tareas SET \' + cols + \' WHERE id=?\', (*clean.values(), task_id))\n        return self.get(task_id)\n\n    def delete(self, task_id):\n        with closing(self._connect()) as db:\n            with db:\n                return db.execute(\'DELETE FROM tareas WHERE id=?\', (task_id,)).rowcount > 0\n\n\ndef validate(data, creating):\n    if not isinstance(data, dict):\n        raise ValueError(\'Se espera un objeto JSON\')\n    permitidos = {\'titulo\', \'descripcion\', \'estado\'}\n    if set(data) - permitidos:\n        raise ValueError(\'Campos desconocidos: \' + \', \'.join(sorted(set(data) - permitidos)))\n    if creating and \'titulo\' not in data:\n        raise ValueError(\'El título es obligatorio\')\n    if not creating and not data:\n        raise ValueError(\'No hay campos para actualizar\')\n    cleaned = {}\n    for key, value in data.items():\n        if not isinstance(value, str):\n            raise ValueError(key + \' debe ser texto\')\n        cleaned[key] = value.strip()\n        if key == \'titulo\' and not 1 <= len(cleaned[key]) <= 160:\n            raise ValueError(\'El título debe tener entre 1 y 160 caracteres\')\n        if key == \'descripcion\' and len(cleaned[key]) > 2000:\n            raise ValueError(\'La descripción es demasiado larga\')\n        if key == \'estado\' and cleaned[key] not in ESTADOS:\n            raise ValueError(\'Estado no válido\')\n    if creating:\n        cleaned.setdefault(\'estado\', \'pendiente\')\n        cleaned.setdefault(\'descripcion\', \'\')\n    return cleaned\n\n\ndef make_handler(repo):\n    class Handler(BaseHTTPRequestHandler):\n        server_version = \'REAPER-Web/8.10\'\n        def log_message(self, format, *args):\n            return  # evita registrar contenidos sensibles en consultas\n\n        def headers_common(self):\n            self.send_header(\'X-Content-Type-Options\', \'nosniff\')\n            self.send_header(\'X-Frame-Options\', \'DENY\')\n            self.send_header(\'Referrer-Policy\', \'no-referrer\')\n            self.send_header(\'Cache-Control\', \'no-store\')\n            self.send_header(\'Content-Security-Policy\', "default-src \'self\'; script-src \'self\'; style-src \'self\'; object-src \'none\'; base-uri \'none\'; frame-ancestors \'none\'")\n\n        def response(self, status, value):\n            payload = json.dumps(value, ensure_ascii=False).encode(\'utf-8\')\n            self.send_response(status)\n            self.send_header(\'Content-Type\', \'application/json; charset=utf-8\')\n            self.send_header(\'Content-Length\', str(len(payload)))\n            self.headers_common()\n            self.end_headers()\n            self.wfile.write(payload)\n\n        def error_json(self, status, msg):\n            self.response(status, {\'error\': msg})\n\n        def _route(self):\n            parsed = urlsplit(self.path)\n            return parsed.path, parse_qs(parsed.query)\n\n        def _task_id(self, path):\n            m = re.fullmatch(r\'/api/tareas/([1-9][0-9]*)\', path)\n            return int(m.group(1)) if m and len(m.group(1)) <= 18 else None\n\n        def _body(self):\n            if self.headers.get(\'Content-Type\', \'\').split(\';\')[0].strip().lower() != \'application/json\':\n                raise ValueError(\'Content-Type debe ser application/json\')\n            length = self.headers.get(\'Content-Length\', \'\')\n            if not length.isdigit() or int(length) > MAX_BYTES:\n                raise ValueError(\'Content-Length inválido o demasiado grande\')\n            try:\n                return json.loads(self.rfile.read(int(length)).decode(\'utf-8\'))\n            except (UnicodeDecodeError, json.JSONDecodeError) as exc:\n                raise ValueError(\'JSON inválido\') from exc\n\n        def do_GET(self):\n            path, params = self._route()\n            if path == \'/api/health\':\n                return self.response(200, {\'ok\': True, \'app\': \'__TITULO__\'})\n            if path == \'/api/tareas\':\n                try:\n                    estado = params.get(\'estado\', [\'\'])[0]\n                    buscar = params.get(\'buscar\', [\'\'])[0]\n                    limit = int(params.get(\'limit\', [\'50\'])[0])\n                    offset = int(params.get(\'offset\', [\'0\'])[0])\n                    if estado and estado not in ESTADOS:\n                        raise ValueError(\'Filtro estado inválido\')\n                    if not (1 <= limit <= 100 and 0 <= offset <= 1000000 and len(buscar) <= 160):\n                        raise ValueError(\'Parámetros de paginación o búsqueda inválidos\')\n                    return self.response(200, repo.list(estado, buscar, limit, offset))\n                except ValueError as exc:\n                    return self.error_json(400, str(exc))\n            pk = self._task_id(path)\n            if pk is not None:\n                item = repo.get(pk)\n                return self.response(200, item) if item else self.error_json(404, \'No existe\')\n            if path in (\'/\', \'/index.html\'):\n                file_path, mime = STATIC / \'index.html\', \'text/html; charset=utf-8\'\n            elif path == \'/style.css\':\n                file_path, mime = STATIC / \'style.css\', \'text/css; charset=utf-8\'\n            elif path == \'/app.js\':\n                file_path, mime = STATIC / \'app.js\', \'text/javascript; charset=utf-8\'\n            else:\n                return self.error_json(404, \'Ruta no encontrada\')\n            try:\n                data = file_path.read_bytes()\n            except OSError:\n                return self.error_json(500, \'Recurso no disponible\')\n            self.send_response(200)\n            self.send_header(\'Content-Type\', mime)\n            self.send_header(\'Content-Length\', str(len(data)))\n            self.headers_common()\n            self.end_headers()\n            self.wfile.write(data)\n\n        def do_POST(self):\n            path, _ = self._route()\n            if path != \'/api/tareas\':\n                return self.error_json(404, \'Ruta no encontrada\')\n            try:\n                obj = repo.create(self._body())\n                return self.response(201, obj)\n            except ValueError as exc:\n                return self.error_json(400, str(exc))\n\n        def do_PATCH(self):\n            path, _ = self._route()\n            pk = self._task_id(path)\n            if pk is None:\n                return self.error_json(404, \'Ruta no encontrada\')\n            try:\n                obj = repo.update(pk, self._body())\n                return self.response(200, obj) if obj else self.error_json(404, \'No existe\')\n            except ValueError as exc:\n                return self.error_json(400, str(exc))\n\n        def do_PUT(self):\n            return self.do_PATCH()\n\n        def do_DELETE(self):\n            path, _ = self._route()\n            pk = self._task_id(path)\n            if pk is None:\n                return self.error_json(404, \'Ruta no encontrada\')\n            return self.response(200, {\'deleted\': True}) if repo.delete(pk) else self.error_json(404, \'No existe\')\n\n    return Handler\n\n\ndef run(host=\'127.0.0.1\', port=8080, database=DB_DEFAULT):\n    with ThreadingHTTPServer((host, port), make_handler(Repository(database))) as server:\n        print(\'REAPER Web: http://%s:%d\' % (host, server.server_address[1]), flush=True)\n        server.serve_forever()\n\n\nif __name__ == \'__main__\':\n    parser = argparse.ArgumentParser(description=\'Servidor web local: __TITULO__\')\n    parser.add_argument(\'--host\', default=\'127.0.0.1\')\n    parser.add_argument(\'--port\', type=int, default=8080)\n    parser.add_argument(\'--db\', default=str(DB_DEFAULT))\n    flags = parser.parse_args()\n    run(flags.host, flags.port, flags.db)\n', 'README.md': '# __TITULO__ · Aplicación web full-stack\n\nProyecto funcional creado con REAPER 8.10. Incluye interfaz web adaptable, API REST y SQLite.\n\n## Ejecutar (Termux o computadora)\n\n```bash\npython3 app.py\n```\n\nAbrí **http://127.0.0.1:8080** en Chrome. Sin Internet y sin instalar librerías extras.\n\n## Pruebas de extremo a extremo\n\n```bash\npython3 -m unittest discover -s tests -v\n```\n\nVerifica servidor HTTP real, CRUD, errores y persistencia entre conexiones.\n\n## Endpoints\n\n- `GET /api/health`\n- `GET /api/tareas?estado=&buscar=&limit=20&offset=0`\n- `POST /api/tareas` cuerpo JSON con `titulo`, `descripcion`, `estado`\n- `GET /api/tareas/<id>`\n- `PATCH /api/tareas/<id>`\n- `PUT /api/tareas/<id>`\n- `DELETE /api/tareas/<id>`\n\nSQLite se guarda en `instance/tareas.sqlite3`. El servidor se limita por defecto a `127.0.0.1`. No hay usuarios, autenticación ni cifrado TLS: **NO abrir a Internet sin implementar autenticación, CSRF y despliegue seguro**. Los tests están hechos para ejecución local.\n\n## Personalización\n\n- `web/index.html`: estructura, título y contenido\n- `web/style.css`: colores, responsive y apariencia\n- `web/app.js`: eventos, filtros, fetch y UI\n- `app.py`: rutas, modelo de datos y validaciones\n\nEl proyecto es un punto de partida real, no una promesa de compatibilidad con todos los frameworks.\n', '.gitignore': '__pycache__/\n*.pyc\ninstance/\n.env\n.pytest_cache/\n', 'tests/test_app.py': '"""Pruebas HTTP reales y persistencia: python3 -m unittest discover -s tests -v"""\nimport http.client\nimport json\nimport tempfile\nimport threading\nimport unittest\nfrom pathlib import Path\nfrom http.server import ThreadingHTTPServer\nfrom app import Repository, make_handler\n\n\nclass WebIntegrationTest(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n        cls.temp = tempfile.TemporaryDirectory()\n        cls.db = Path(cls.temp.name) / \'tareas.sqlite3\'\n        cls.repo = Repository(cls.db)\n        cls.server = ThreadingHTTPServer((\'127.0.0.1\', 0), make_handler(cls.repo))\n        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)\n        cls.thread.start()\n\n    @classmethod\n    def tearDownClass(cls):\n        cls.server.shutdown()\n        cls.server.server_close()\n        cls.thread.join(timeout=3)\n        cls.temp.cleanup()\n\n    def request(self, method, path, data=None, headers=None):\n        conn = http.client.HTTPConnection(\'127.0.0.1\', self.server.server_address[1], timeout=5)\n        payload = json.dumps(data).encode(\'utf-8\') if data is not None else None\n        heads = {\'Content-Type\':\'application/json\'} if payload is not None else {}\n        heads.update(headers or {})\n        conn.request(method, path, body=payload, headers=heads)\n        res = conn.getresponse()\n        raw = res.read()\n        status, content_type = res.status, res.getheader(\'Content-Type\', \'\')\n        conn.close()\n        body = json.loads(raw.decode(\'utf-8\')) if \'application/json\' in content_type else raw\n        return status, body, content_type\n\n    def test_01_health_and_html(self):\n        s, body, _ = self.request(\'GET\',\'/api/health\')\n        self.assertEqual((s,body[\'ok\']), (200,True))\n        s, body, kind = self.request(\'GET\',\'/\')\n        self.assertEqual(s,200)\n        self.assertIn(b\'<html\',body)\n        self.assertIn(\'text/html\',kind)\n        for asset in (\'/style.css\',\'/app.js\'):\n            self.assertEqual(self.request(\'GET\',asset)[0],200)\n\n    def test_02_crud_real(self):\n        s, body, _=self.request(\'POST\',\'/api/tareas\',{\'titulo\':\'Aprender Termux\',\'descripcion\':\'Desde Android\'})\n        self.assertEqual(s,201)\n        task_id=body[\'id\']\n        self.assertEqual(self.request(\'GET\',\'/api/tareas/\'+str(task_id))[1][\'titulo\'],\'Aprender Termux\')\n        s, body, _=self.request(\'PATCH\',\'/api/tareas/\'+str(task_id),{\'estado\':\'hecha\'})\n        self.assertEqual((s,body[\'estado\']), (200,\'hecha\'))\n        self.assertGreaterEqual(self.request(\'GET\',\'/api/tareas?estado=hecha\')[1][\'total\'],1)\n        self.assertTrue(self.request(\'DELETE\',\'/api/tareas/\'+str(task_id))[1][\'deleted\'])\n        self.assertEqual(self.request(\'GET\',\'/api/tareas/\'+str(task_id))[0],404)\n\n    def test_03_validation_errors(self):\n        for data in ({\'titulo\':\'\'},{\'titulo\':2},{\'titulo\':\'x\',\'estado\':\'bad\'},{\'titulo\':\'x\',\'secret\':\'a\'}):\n            self.assertEqual(self.request(\'POST\',\'/api/tareas\',data)[0],400)\n        self.assertEqual(self.request(\'GET\',\'/api/tareas?limit=100000\')[0],400)\n        self.assertEqual(self.request(\'GET\',\'/api/tareas?offset=-1\')[0],400)\n        self.assertEqual(self.request(\'GET\',\'/api/tareas/99999999\')[0],404)\n        self.assertEqual(self.request(\'GET\',\'/../../.env\')[0],404)\n        self.assertEqual(self.request(\'POST\',\'/api/tareas\',b\'bad\' if False else {\'titulo\':\'ok\'},headers={\'Content-Type\':\'text/plain\'})[0],400)\n\n    def test_04_persistence_real(self):\n        task=self.repo.create({\'titulo\':\'Persistente\'})\n        reopened=Repository(self.db)\n        self.assertEqual(reopened.get(task[\'id\'])[\'titulo\'],\'Persistente\')\n        self.repo.delete(task[\'id\'])\n\n    def test_05_search_pagination(self):\n        ids=[self.repo.create({\'titulo\':\'Prueba \'+str(i)})[\'id\'] for i in range(4)]\n        try:\n            result=self.repo.list(buscar=\'Prueba \', limit=2,offset=1)\n            self.assertGreaterEqual(result[\'total\'],4)\n            self.assertEqual(len(result[\'items\']),2)\n        finally:\n            for i in ids:self.repo.delete(i)\n\n    def test_06_static_and_bad_methods(self):\n        self.assertEqual(self.request(\'GET\',\'/api/noexiste\')[0],404)\n        self.assertEqual(self.request(\'PATCH\',\'/api/tareas/1\',{\'nada\':\'x\'})[0],400)\n        self.assertIn(\'text/css\',self.request(\'GET\',\'/style.css\')[2])\n\n\nif __name__==\'__main__\': unittest.main()\n', 'web/style.css': ":root{color-scheme:dark;--bg:#0c0f1b;--surface:#151a29;--surface2:#1a2031;--border:#293146;--text:#f0f2fb;--muted:#9ba4bc;--accent:#a99bff;--blue:#73a7ff;--green:#56dbc0;--amber:#fac27b}*{box-sizing:border-box}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--text)}button,input,textarea,select{font:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:3px}a{color:inherit;text-decoration:none}.layout{display:grid;grid-template-columns:245px minmax(0,1fr);min-height:100vh}.sidebar{padding:30px 20px;position:sticky;top:0;height:100vh;background:#111625;border-right:1px solid var(--border);display:flex;flex-direction:column;gap:55px}.brand{display:flex;gap:12px;align-items:center;font-size:17px;line-height:1.1;font-weight:800;letter-spacing:-.4px}.brand small{display:block;font-size:9px;color:var(--muted);letter-spacing:2px;margin-top:6px}.brand-icon{display:grid;place-items:center;width:43px;height:43px;background:linear-gradient(140deg,#9e8aff,#5973d0);border-radius:14px;color:#fff;font-size:23px;box-shadow:0 6px 28px #6759df45}.nav-label,.eyebrow{font-size:10px;letter-spacing:2px;font-weight:800;color:var(--muted)}.nav-link{display:flex;gap:12px;align-items:center;border:1px solid #40405f;background:#25233d;border-radius:12px;padding:14px;font-size:13px;color:#ddd7ff}.nav-link span{font-size:21px}.sidebar-bottom{margin-top:auto;color:#c0c7d8;font-size:12px}.sidebar-bottom small{display:block;margin:10px 0 0 16px;color:#818ba6;font-size:11px}.online{display:inline-block;background:#4fe0a4;border-radius:50%;width:8px;height:8px;margin-right:6px}.main{padding:50px clamp(24px,5vw,76px);max-width:1600px;width:100%;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:40px}h1{font-size:clamp(29px,3.3vw,43px);letter-spacing:-1.3px;margin:10px 0 8px}h2{letter-spacing:-.45px}.subtitle{font-size:14px;color:var(--muted);margin:0}.primary{border:0;border-radius:11px;background:#a99bff;color:#151125;padding:13px 18px;font-size:13px;font-weight:750;box-shadow:0 3px 16px #8e7bea26;min-height:44px}.primary:hover{background:#c1b7ff}.secondary{border:1px solid var(--border);border-radius:9px;color:#c6cee2;background:#252b3d;padding:9px 13px;min-height:40px}.secondary:disabled{opacity:.45;cursor:not-allowed}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:30px}.stat{border:1px solid var(--border);border-radius:16px;background:linear-gradient(140deg,#1b2032,#171b29);padding:22px;min-width:0}.stat-top{color:#c1c9de;font-size:12px;display:flex;align-items:center;justify-content:space-between;gap:8px}.stat-icon{display:grid;place-items:center;width:36px;height:36px;border-radius:11px;font-size:20px}.purple{color:#c5b7ff;background:#392c62}.amber{color:#ffc985;background:#47351f}.blue{color:#9cc1ff;background:#273d65}.green{color:#77e2c9;background:#20453e}.stat strong{display:block;font-size:35px;letter-spacing:-1px;margin:13px 0 5px}.stat small{font-size:11px;color:var(--muted)}.panel{border:1px solid var(--border);border-radius:18px;background:var(--surface);overflow:hidden}.panel-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:27px 28px 23px}.panel h2{font-size:20px;margin:0 0 7px}.search-label input{background:#202637;border:1px solid #31384c;border-radius:9px;color:var(--text);font-size:13px;padding:13px 15px;width:min(270px,100%)}.filters{display:flex;gap:8px;flex-wrap:wrap;padding:0 28px 20px;border-bottom:1px solid var(--border)}.filter{border:1px solid transparent;background:transparent;color:var(--muted);font-weight:600;font-size:12px;padding:10px 14px;border-radius:8px}.filter.active{background:#33304f;border-color:#51477b;color:#d9d1ff}.tasks{margin:0;list-style:none;padding:4px 28px}.task{display:flex;align-items:flex-start;gap:15px;padding:19px 0;border-bottom:1px solid #2a3042}.task:last-child{border:0}.task-info{flex:1;min-width:0}.task-info strong{display:block;font-size:14px;overflow-wrap:anywhere}.task-info p{margin:7px 0;color:var(--muted);font-size:12px;overflow-wrap:anywhere}.task-info small{color:#77839c;font-size:11px}.pill{border-radius:50px;padding:7px 10px;font-size:10px;font-weight:750;white-space:nowrap}.pill.pendiente{background:#47351f;color:#ffd198}.pill.progreso{background:#26395c;color:#acc9ff}.pill.hecha{background:#1e443d;color:#7fe6cd}.task-actions{display:flex;gap:6px}.iconbtn{border:1px solid var(--border);border-radius:8px;background:#202638;color:#bfc8de;width:32px;height:32px}.iconbtn:hover{border-color:var(--accent)}.message{font-size:12px;color:var(--amber);padding:0 28px}.message:empty{display:none}.pagination{padding:19px 28px;display:flex;justify-content:space-between;gap:10px;align-items:center;color:var(--muted);font-size:12px}.pagination>div{display:flex;gap:10px}.empty{color:var(--muted);text-align:center;padding:55px 20px!important;font-size:14px}.footer{color:#6d7790;font-size:11px;margin-top:28px;display:flex;gap:10px;align-items:center}.footer span{color:var(--accent)}dialog{border:1px solid var(--border);border-radius:18px;background:#1b2131;color:var(--text);width:min(460px,calc(100% - 28px));padding:0;box-shadow:0 30px 100px #0009}dialog::backdrop{background:#050713c9}.modal{padding:27px;display:grid;gap:20px}.modal-header{display:flex;justify-content:space-between;align-items:center}.modal h2{margin:0}.close{border:0;background:none;color:var(--muted);font-size:25px}.modal label{display:grid;gap:9px;font-size:12px;font-weight:650}.modal input,.modal textarea,.modal select{width:100%;background:#101626;border:1px solid #364056;border-radius:9px;color:var(--text);padding:12px;resize:vertical}.modal-actions{display:flex;justify-content:flex-end;gap:10px}.visually-hidden{position:absolute;width:1px;height:1px;clip:rect(0,0,0,0);white-space:nowrap;overflow:hidden}@media(max-width:1000px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.sidebar{width:210px}.layout{grid-template-columns:210px 1fr}.main{padding:36px 24px}}@media(max-width:680px){.layout{display:block}.sidebar{position:static;width:auto;height:auto;flex-direction:row;align-items:center;padding:16px 20px;gap:15px}.sidebar .nav-label,.sidebar nav,.sidebar-bottom{display:none}.main{padding:24px 15px}.top{align-items:flex-start;flex-direction:column;margin-bottom:24px}.top .primary{width:100%}.stats{gap:9px}.stat{padding:15px}.stat strong{font-size:29px}.stat-icon{width:27px;height:27px}.stat-top{font-size:10px}.panel-heading{flex-direction:column;align-items:stretch;padding:20px}.search-label input{width:100%}.filters{padding:0 16px 16px;gap:3px}.filter{padding:9px 8px}.tasks{padding:0 15px}.task{gap:9px;flex-wrap:wrap}.task-actions{margin-left:auto}.pagination{padding:16px;flex-wrap:wrap}}\n", 'web/index.html': '<!doctype html>\n<html lang="es">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width,initial-scale=1">\n  <meta name="theme-color" content="#101321">\n  <meta name="description" content="Gestión de tareas moderna, rápida y accesible">\n  <title>__TITULO__ · Panel de trabajo</title>\n  <link rel="stylesheet" href="/style.css">\n</head>\n<body>\n  <div class="layout">\n    <aside class="sidebar" aria-label="Navegación">\n      <a class="brand" href="/" aria-label="Inicio __TITULO__"><span class="brand-icon">◆</span><span>__TITULO__<small>WORKSPACE</small></span></a>\n      <p class="nav-label">ESPACIO DE TRABAJO</p>\n      <nav><a class="nav-link active" href="/" aria-current="page"><span>▦</span> Vista general</a></nav>\n      <div class="sidebar-bottom"><span class="online"></span> Sistema local y privado <small>REAPER 8.10 · Python + SQLite</small></div>\n    </aside>\n    <main class="main" id="main">\n      <header class="top"><div><p class="eyebrow">TU ESPACIO, TUS PROYECTOS</p><h1>Tablero de trabajo</h1><p class="subtitle">Todo lo que importa, en un solo lugar.</p></div><button id="newTask" class="primary">＋ Nueva tarea</button></header>\n      <section class="stats" aria-label="Resumen">\n        <article class="stat"><div class="stat-top">Tareas totales <span class="stat-icon purple">▣</span></div><strong id="statTotal">—</strong><small>Registradas</small></article>\n        <article class="stat"><div class="stat-top">Pendientes <span class="stat-icon amber">◷</span></div><strong id="statPending">—</strong><small>Para comenzar</small></article>\n        <article class="stat"><div class="stat-top">En progreso <span class="stat-icon blue">↗</span></div><strong id="statProgress">—</strong><small>En movimiento</small></article>\n        <article class="stat"><div class="stat-top">Completadas <span class="stat-icon green">✓</span></div><strong id="statDone">—</strong><small>Objetivos logrados</small></article>\n      </section>\n      <section class="panel" aria-labelledby="taskHeading">\n        <div class="panel-heading"><div><h2 id="taskHeading">Mis tareas</h2><p class="subtitle">Organizá lo próximo con claridad.</p></div><label class="search-label"><span class="visually-hidden">Buscar tareas</span><input id="search" placeholder="⌕  Buscar tareas..." maxlength="160" autocomplete="off"></label></div>\n        <div class="filters" role="group" aria-label="Filtrar tareas"><button class="filter active" data-state="" aria-pressed="true">Todas</button><button class="filter" data-state="pendiente" aria-pressed="false">Pendientes</button><button class="filter" data-state="progreso" aria-pressed="false">En progreso</button><button class="filter" data-state="hecha" aria-pressed="false">Completadas</button></div>\n        <div id="message" class="message" role="status" aria-live="polite"></div>\n        <ul id="tasks" class="tasks" aria-label="Lista de tareas"></ul>\n        <div class="pagination"><span id="paginationLabel"></span><div><button id="prev" class="secondary">← Anterior</button><button id="next" class="secondary">Siguiente →</button></div></div>\n      </section>\n      <footer class="footer">Creado con REAPER 8.10 <span>●</span> Funciona sin servicios externos</footer>\n    </main>\n  </div>\n  <dialog id="taskDialog" aria-labelledby="dialogTitle"><form id="taskForm" class="modal"><div class="modal-header"><h2 id="dialogTitle">Nueva tarea</h2><button type="button" class="close" id="closeDialog" aria-label="Cerrar">×</button></div><input type="hidden" id="taskId"><label>Título <input id="titleInput" required minlength="1" maxlength="160" placeholder="¿Qué querés hacer?"></label><label>Descripción <textarea id="descriptionInput" maxlength="2000" rows="4" placeholder="Notas opcionales"></textarea></label><label>Estado <select id="statusInput"><option value="pendiente">Pendiente</option><option value="progreso">En progreso</option><option value="hecha">Completada</option></select></label><div class="modal-actions"><button type="button" class="secondary" id="cancelDialog">Cancelar</button><button type="submit" class="primary">Guardar tarea</button></div></form></dialog>\n  <script src="/app.js" defer></script>\n</body>\n</html>\n', 'web/app.js': "'use strict';\nconst $ = (id) => document.getElementById(id);\nconst state = {filter:'', query:'', limit:20, offset:0, items:[]};\nconst statuses = {pendiente:'Pendiente', progreso:'En progreso', hecha:'Completada'};\nasync function api(path, options={}) {\n  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json', ...(options.headers||{})}});\n  let data;\n  try { data = await response.json(); } catch { throw new Error('Respuesta inválida del servidor'); }\n  if (!response.ok) throw new Error(data.error || `Error HTTP ${response.status}`);\n  return data;\n}\nfunction message(text='') { $('message').textContent=text; }\nfunction button(label,title,action){const b=document.createElement('button');b.className='iconbtn';b.type='button';b.textContent=label;b.title=title;b.setAttribute('aria-label',title);b.addEventListener('click',action);return b;}\nfunction display(tasks) {\n  const list=$('tasks');list.replaceChildren();\n  if (!tasks.length){const li=document.createElement('li');li.className='empty';li.textContent='Todavía no hay tareas en esta vista. ¡Creá la primera!';list.append(li);return;}\n  for(const task of tasks){\n    const li=document.createElement('li');li.className='task';\n    const info=document.createElement('div');info.className='task-info';\n    const title=document.createElement('strong');title.textContent=task.titulo;\n    const desc=document.createElement('p');desc.textContent=task.descripcion || 'Sin descripción';\n    const date=document.createElement('small');date.textContent='Creada: '+task.creada;\n    info.append(title,desc,date);\n    const pill=document.createElement('span');pill.className='pill '+task.estado;pill.textContent=statuses[task.estado]||task.estado;\n    const actions=document.createElement('div');actions.className='task-actions';\n    actions.append(button('✎','Editar tarea '+task.titulo,()=>openEditor(task)),button('×','Eliminar tarea '+task.titulo,()=>removeTask(task)));\n    li.append(info,pill,actions);list.append(li);\n  }\n}\nasync function refresh(){\n  try{\n    const qs=new URLSearchParams({estado:state.filter,buscar:state.query,limit:String(state.limit),offset:String(state.offset)});\n    const result=await api('/api/tareas?'+qs);\n    state.items=result.items;display(result.items);\n    $('paginationLabel').textContent=result.total?`${result.offset+1}–${Math.min(result.total,result.offset+result.limit)} de ${result.total}`:'0 tareas';\n    $('prev').disabled=state.offset===0;$('next').disabled=state.offset+state.limit>=result.total;\n    const all=await api('/api/tareas?limit=100&offset=0');\n    // Para no contar solo la página visible, el total general se obtiene del endpoint sin filtros.\n    $('statTotal').textContent=all.total;\n    const counts=await Promise.all(['pendiente','progreso','hecha'].map(s=>api('/api/tareas?estado='+s+'&limit=1')));\n    $('statPending').textContent=counts[0].total;$('statProgress').textContent=counts[1].total;$('statDone').textContent=counts[2].total;\n    message();\n  }catch(err){message('No se pudo consultar el servidor: '+err.message);}\n}\nfunction openEditor(task=null){$('taskId').value=task?task.id:'';$('dialogTitle').textContent=task?'Editar tarea':'Nueva tarea';$('titleInput').value=task?task.titulo:'';$('descriptionInput').value=task?task.descripcion:'';$('statusInput').value=task?task.estado:'pendiente';$('taskDialog').showModal();$('titleInput').focus();}\nasync function removeTask(task){if(!confirm('¿Eliminar «'+task.titulo+'»?'))return;try{await api('/api/tareas/'+task.id,{method:'DELETE'});await refresh();}catch(err){message(err.message);}}\n$('taskForm').addEventListener('submit',async(e)=>{e.preventDefault();const id=$('taskId').value;const data={titulo:$('titleInput').value,descripcion:$('descriptionInput').value,estado:$('statusInput').value};try{await api(id?'/api/tareas/'+id:'/api/tareas',{method:id?'PATCH':'POST',body:JSON.stringify(data)});$('taskDialog').close();state.offset=0;await refresh();}catch(err){message(err.message);}});\n$('newTask').addEventListener('click',()=>openEditor());\nfor(const id of ['closeDialog','cancelDialog']){$(id).addEventListener('click',()=>$('taskDialog').close());}\nfor(const b of document.querySelectorAll('.filter'))b.addEventListener('click',()=>{document.querySelectorAll('.filter').forEach(x=>{x.classList.remove('active');x.setAttribute('aria-pressed','false');});b.classList.add('active');b.setAttribute('aria-pressed','true');state.filter=b.dataset.state;state.offset=0;refresh();});\nlet typing; $('search').addEventListener('input',(e)=>{clearTimeout(typing);typing=setTimeout(()=>{state.query=e.target.value.trim();state.offset=0;refresh();},250);});\n$('prev').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-state.limit);refresh();});\n$('next').addEventListener('click',()=>{state.offset+=state.limit;refresh();});\nrefresh();\n"},
    comando_tests="python3 -m unittest discover -s tests -v",
    comando_ejecutar="python3 app.py",
    etiquetas=("web", "pagina", "página", "sitio", "frontend", "backend", "fullstack", "sqlite", "crud", "api", "termux"),
)

# ======================================================================
# REAPER 8.10 — VALIDACIÓN DE ENTREGA / REGRESIONES DE PRODUCTO
# ======================================================================
class TestReaper810Producto(BaseTest):
    """Fallos reales: comandos personalizados, artefactos ausentes y builds falsas."""

    def test_comando_personalizado_exit_5_es_fallo(self):
        ws = self.proyecto()
        ws.carpeta_reaper().mkdir(exist_ok=True)
        comando = shlex.quote(sys.executable) + ' -c "import sys; print(\'test_runner_failed\'); sys.exit(5)"'
        (ws.carpeta_reaper() / "config.json").write_text(
            json.dumps({"comando_tests": comando}), encoding="utf-8")
        r = ejecutar_tests(ws, timeout=15)
        self.assertIsNotNone(r)
        self.assertFalse(r.ok)
        self.assertFalse(r.omitido)
        self.assertEqual(r.codigo, 5)

    def test_salida_5_personalizada_con_mensaje_sin_tests_sigue_fallando(self):
        ws = self.proyecto()
        ws.carpeta_reaper().mkdir(exist_ok=True)
        comando = shlex.quote(sys.executable) + ' -c "import sys; print(\'no tests ran\'); sys.exit(5)"'
        (ws.carpeta_reaper() / "config.json").write_text(
            json.dumps({"comando_tests": comando}), encoding="utf-8")
        r = ejecutar_tests(ws, timeout=15)
        self.assertFalse(r.ok)
        self.assertFalse(r.omitido)

    def test_build_sin_archivo_ni_cambios_no_puede_ser_verificada(self):
        ws = self.proyecto()
        o = Orquestador(MockLLM([]), ws, self.ajustes(max_reparaciones=0), self.ui())
        o._reparar_con_escalada = lambda pedido, verif, *args, **kw: verif
        o.obtener_plan = lambda *args: (Plan("crear", [Tarea("1", "Escribir app.py", ["app.py"])], []), "")
        o.implementar = lambda *args, **kw: type("Resultado", (), {"ok": True, "modo": "simple", "ganador": None})()
        informe = o.construir("Crear app.py", confirmar=False)
        self.assertFalse(informe.ok, "Falso positivo: el agente dice 'listo' pero no creó app.py")
        self.assertIn("1", informe.tareas_fallidas)
        self.assertFalse(ws.existe("app.py"))

    def test_build_con_archivo_real_puede_validarse_sin_suite(self):
        ws = self.proyecto()
        o = Orquestador(MockLLM([]), ws, self.ajustes(max_reparaciones=0), self.ui())
        o._reparar_con_escalada = lambda pedido, verif, *args, **kw: verif
        o.obtener_plan = lambda *args: (Plan("crear", [Tarea("1", "Escribir app.py", ["app.py"])], []), "")
        def implementar(*args, **kw):
            ws.escribir("app.py", "def sumar(a, b):\n    return a + b\n")
            return type("Resultado", (), {"ok": True, "modo": "simple", "ganador": None})()
        o.implementar = implementar
        informe = o.construir("Crear app.py", confirmar=False)
        self.assertEqual(informe.estado, "validada", informe.diagnostico)
        self.assertEqual(ws.leer("app.py").splitlines()[0], "def sumar(a, b):")

    def test_multiples_archivos_declarados_faltantes_bloquean(self):
        ws = self.proyecto()
        o = Orquestador(MockLLM([]), ws, self.ajustes(max_reparaciones=0), self.ui())
        o._reparar_con_escalada = lambda pedido, verif, *args, **kw: verif
        o.obtener_plan = lambda *args: (Plan("crear", [Tarea("1", "Crear app.py y README.md", ["app.py", "README.md"])], []), "")
        def implementar(*args, **kw):
            ws.escribir("app.py", "x = 1\n")
            return type("Resultado", (), {"ok": True, "modo": "simple", "ganador": None})()
        o.implementar = implementar
        informe = o.construir("Crear proyecto completo", confirmar=False)
        self.assertFalse(informe.ok)
        self.assertIn("1", informe.tareas_fallidas)

    def test_reanudacion_no_considera_una_tarea_incompleta_verificada(self):
        ws = self.proyecto()
        o = Orquestador(MockLLM([]), ws, self.ajustes(max_reparaciones=0), self.ui())
        o._reparar_con_escalada = lambda pedido, verif, *args, **kw: verif
        o.obtener_plan = lambda *args: (Plan("crear", [Tarea("1", "Crear app.py", ["app.py"])], []), "")
        o.implementar = lambda *args, **kw: type("Resultado", (), {"ok": True, "modo": "simple", "ganador": None})()
        informe = o.construir("Crear app.py", confirmar=False)
        diario = RegistroBuild(ws).leer()
        self.assertNotEqual(diario["estados"].get("1"), "verificada")
        self.assertFalse(informe.ok)


class TestReaper810Fullstack(BaseTest):
    """Pruebas de la construcción web y de los comandos offline de REAPER."""

    def test_plantilla_registrada_y_renderizada(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "mipagina"
            creados = crear_desde_plantilla("web-fullstack", ruta)
            self.assertIn("web/index.html", creados)
            self.assertIn("app.py", creados)
            self.assertIn("tests/test_app.py", creados)
            self.assertIn("Mipagina", (ruta / "web/index.html").read_text())
            self.assertNotIn("__TITULO__", (ruta / "app.py").read_text())

    def test_plantilla_fullstack_http_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "aplicacion"
            crear_desde_plantilla("web-fullstack", ruta)
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                               cwd=ruta, capture_output=True, text=True, timeout=35)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Ran 6 tests", r.stderr)

    def test_auditoria_web_plantilla(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "webreal"
            crear_desde_plantilla("web-fullstack", ruta)
            r = auditar_web_proyecto(ruta)
            self.assertTrue(r['ok'], r['hallazgos'])
            (ruta / "web/app.js").unlink()
            self.assertFalse(auditar_web_proyecto(ruta)['ok'])

    def test_auditoria_detecta_link_simbolico_fuera(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "proyecto"
            ruta.mkdir()
            externo = Path(tmp) / "externo.html"
            externo.write_text("<title>Externos</title>")
            try:
                (ruta / "index.html").symlink_to(externo)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks no disponibles")
            r = auditar_web_proyecto(ruta)
            self.assertFalse(r['ok'])
            self.assertTrue(any('enlace simbólico' in x for x in r['hallazgos']))

    def test_cli_nuevo_sin_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "sitio"
            prev = os.environ.get("OPENROUTER_API_KEY")
            os.environ.pop("OPENROUTER_API_KEY", None)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    status = main(["--nuevo", "web-fullstack", str(ruta)])
            finally:
                if prev is not None: os.environ["OPENROUTER_API_KEY"] = prev
            self.assertEqual(status, 0)
            self.assertTrue((ruta / "web/index.html").is_file())

    def test_cli_auditoria_sin_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "webreal"
            crear_desde_plantilla("web-fullstack", ruta)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--auditar-web", str(ruta)]), 0)
            self.assertFalse((ruta / ".reaper" / "config.json").is_symlink())



    def test_plantilla_externa_path_traversal_es_rechazada_sin_efectos(self):
        with tempfile.TemporaryDirectory() as tmp:
            nombre = "test_reaper810_malicious_template"
            PLANTILLAS[nombre] = Plantilla(nombre, "x", "python", {"../fuera.txt":"MAL", "ok.py":"print(1)"})
            try:
                with self.assertRaises(ValueError):
                    crear_desde_plantilla(nombre, Path(tmp)/"proyecto")
                self.assertFalse((Path(tmp)/"fuera.txt").exists())
                self.assertFalse((Path(tmp)/"proyecto"/"ok.py").exists())
            finally:
                del PLANTILLAS[nombre]

    def test_plantilla_no_escribe_mediante_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            proyecto = Path(tmp)/"proyecto"
            proyecto.mkdir()
            externo = Path(tmp)/"externo"
            externo.mkdir()
            try:
                (proyecto/"data").symlink_to(externo, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks no soportados")
            nombre = "test_reaper810_malicious_symlink"
            PLANTILLAS[nombre] = Plantilla(nombre,"x","python",{"data/secret.txt":"NO","ok.py":"PASS"})
            try:
                with self.assertRaises((FileExistsError,ValueError)):
                    crear_desde_plantilla(nombre,proyecto,sobrescribir=True)
                self.assertFalse((externo/"secret.txt").exists())
                self.assertFalse((proyecto/"ok.py").exists())
            finally:
                del PLANTILLAS[nombre]

    def test_auditoria_rechaza_carpeta_web_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            proyecto=Path(tmp)/"proyecto"
            proyecto.mkdir()
            externo=Path(tmp)/"fuera"
            externo.mkdir()
            (externo/"index.html").write_text('<html lang="es"><title>Externo</title></html>')
            try:
                (proyecto/"web").symlink_to(externo,target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks no soportados")
            r=auditar_web_proyecto(proyecto)
            self.assertFalse(r['ok'])
            self.assertEqual(r['paginas'],0)





# ======================================================================
# REAPER 8.10 — PLANTILLAS MULTIPLATAFORMA / RONDA 9
# ======================================================================
registrar_plantilla('react-vite', 'React 19 + Vite 8: tablero responsive, pruebas JavaScript y guía de despliegue estático.', 'javascript', {'.gitignore': 'node_modules/\ndist/\n.env\n.env.*\n!.env.example\n.DS_Store\n', 'DEPLOY.md': '# Despliegue de React / Vite\n\n1. `npm install` y `npm test`\n2. `npm run build` y verificar la carpeta `dist/`\n3. Subir `dist/` al hosting estático de tu elección. El comando de build es `npm run build`.\n4. Configurar HTTPS, política de dominio y rutas SPA si se agregan páginas en el router.\n5. No incluir claves privadas en el frontend ni en `VITE_*`.\n6. Confirmar funcionamiento desde el navegador y celular antes de anunciar que está en producción.\n', 'README.md': '# __TITULO__ — React / Vite\n\nUna aplicación React funcional, responsive y con persistencia local.\n\n## Android Termux / PC\n\n- Node.js 20.19+ o 22.12+ requerido para Vite 8 (ver documentación oficial).\n- `npm install` para descargar dependencias (requiere Internet; no se ejecuta al generar la plantilla).\n- `npm test` ejecuta 5 pruebas de lógica **sin instalar dependencias** (Node 20+).\n- `npm run dev` inicia la web en http://127.0.0.1:5173\n- `npm run build` produce `dist/` para hosting estático.\n\nLos datos se guardan en `localStorage` del navegador; no hay backend ni usuarios en esta plantilla.\nPara producción: revisar dependencias, configurar dominio/HTTPS y desplegar `dist/` en hosting estático.\nNo subir `.env` ni credenciales al repositorio; las variables `VITE_*` son públicas en el frontend.\n', 'index.html': '<!doctype html>\n<html lang="es"><head>\n<meta charset="UTF-8"/>\n<meta name="viewport" content="width=device-width,initial-scale=1"/>\n<meta name="description" content="Gestor de tareas hecho con REAPER 8.10"/>\n<title>__TITULO__</title>\n</head><body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body></html>\n', 'package.json': '{\n  "name": "__PROYECTO__",\n  "private": true,\n  "version": "0.1.0",\n  "type": "module",\n  "scripts": {\n    "dev": "vite --host 127.0.0.1",\n    "build": "vite build",\n    "preview": "vite preview --host 127.0.0.1",\n    "test": "node --test tests/*.test.mjs"\n  },\n  "dependencies": {"react": "^19.2.0", "react-dom": "^19.2.0"},\n  "devDependencies": {"vite": "^8.0.0"}\n}\n', 'src/App.jsx': 'import React, {useEffect, useMemo, useState} from \'react\';\nimport {filterTasks, loadTasks, makeTask, updateTask} from \'./tasks.mjs\';\nconst names={all:\'Todas\',todo:\'Pendientes\',doing:\'En progreso\',done:\'Completadas\'};\nexport default function App(){\n  const [tasks,setTasks]=useState(()=>loadTasks(localStorage));\n  const [title,setTitle]=useState(\'\'); const [query,setQuery]=useState(\'\'); const [status,setStatus]=useState(\'all\');\n  const [error,setError]=useState(\'\');\n  useEffect(()=>{try{localStorage.setItem(\'reaper.tasks.v1\',JSON.stringify(tasks))}catch{setError(\'No se pudo guardar en el dispositivo.\')}},[tasks]);\n  const visible=useMemo(()=>filterTasks(tasks,query,status),[tasks,query,status]);\n  function create(e){e.preventDefault(); try{setTasks(t=>[makeTask(title,crypto.randomUUID()),...t]);setTitle(\'\');setError(\'\')}catch(err){setError(err.message)}}\n  function move(id,status){setTasks(t=>updateTask(t,id,{status}))}\n  return <main className="shell"><header><div><p className="eyebrow">REAPER 8.10 · React</p><h1>__TITULO__</h1><p className="muted">Organizá tus proyectos desde el celular.</p></div><span className="chip">{tasks.length} tareas</span></header>\n    <section className="hero"><div><h2>Tu tablero de trabajo</h2><p>Simple, rápido y guardado en este dispositivo.</p></div><div className="counts"><span>{tasks.filter(t=>t.status===\'todo\').length}<small>Pendientes</small></span><span>{tasks.filter(t=>t.status===\'doing\').length}<small>En curso</small></span><span>{tasks.filter(t=>t.status===\'done\').length}<small>Hechas</small></span></div></section>\n    <section className="panel"><h2>Nueva tarea</h2><form onSubmit={create} className="form"><label htmlFor="taskTitle">Nombre de la tarea</label><div className="inputrow"><input id="taskTitle" value={title} onChange={e=>setTitle(e.target.value)} maxLength={120} placeholder="¿Qué querés hacer?"/><button type="submit">Agregar</button></div></form>{error&&<p role="alert" className="error">{error}</p>}</section>\n    <section className="panel"><div className="tools"><h2>Mis tareas</h2><label className="sr" htmlFor="searchTasks">Buscar</label><input id="searchTasks" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Buscar tareas"/></div><div className="filters">{Object.entries(names).map(([key,label])=><button type="button" key={key} aria-pressed={status===key} className={status===key?\'active\':\'\'} onClick={()=>setStatus(key)}>{label}</button>)}</div>\n      <ul className="tasks">{visible.map(t=><li key={t.id}><div><strong>{t.title}</strong><small>{names[t.status]}</small></div><div className="actions"><select aria-label={\'Estado de \'+t.title} value={t.status} onChange={e=>move(t.id,e.target.value)}>{Object.keys(names).filter(x=>x!==\'all\').map(s=><option key={s} value={s}>{names[s]}</option>)}</select><button type="button" className="danger" aria-label={\'Eliminar \'+t.title} onClick={()=>setTasks(old=>old.filter(x=>x.id!==t.id))}>Eliminar</button></div></li>)}{!visible.length&&<li className="empty">No hay tareas para mostrar.</li>}</ul>\n    </section><footer>Plantilla React · REAPER 8.10</footer></main>\n}\n', 'src/main.jsx': "import React from 'react';\nimport {createRoot} from 'react-dom/client';\nimport App from './App.jsx';\nimport './styles.css';\ncreateRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>);\n", 'src/styles.css': ':root{font:16px system-ui,-apple-system,Segoe UI,sans-serif;color:#e8edf9;background:#0b1120}*{box-sizing:border-box}body{margin:0}.shell{max-width:1050px;margin:0 auto;padding:28px 18px 80px}header{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:26px}h1{font-size:clamp(1.9rem,4vw,3rem);margin:5px 0}h2{margin:0 0 15px;font-size:1.3rem}.muted,footer{color:#91a0be}.eyebrow{color:#9c8dff;text-transform:uppercase;letter-spacing:.15em;font-size:.72rem;font-weight:750}.chip{border:1px solid #485576;border-radius:99px;padding:9px 15px;white-space:nowrap}.hero{display:flex;justify-content:space-between;gap:20px;background:linear-gradient(115deg,#333181,#23335c);border:1px solid #6564bd;border-radius:21px;padding:26px;margin-bottom:19px}.hero p{color:#d7dcfb}.counts{display:flex;gap:18px;align-items:center}.counts span{font-size:2rem;font-weight:750;text-align:center}.counts small{display:block;font-size:.75rem;font-weight:500}.panel{background:#131d31;border:1px solid #2e3d59;padding:22px;border-radius:18px;margin-bottom:18px}button,input,select{font:inherit;border-radius:10px;padding:11px 13px}input,select{background:#0b1427;border:1px solid #445370;color:inherit}button{background:#786df5;border:1px solid #8c84ff;color:white;cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #b0aaff;outline-offset:2px}button:hover{filter:brightness(1.1)}label{display:block;margin-bottom:8px}.inputrow{display:flex;gap:10px}.inputrow input{flex:1;min-width:0}.tools{display:flex;align-items:center;justify-content:space-between;gap:12px}.tools input{max-width:260px;width:100%}.filters{display:flex;flex-wrap:wrap;gap:9px;margin:8px 0 20px}.filters button{background:#202d47;border-color:#40506d}.filters .active{background:#675edb}.tasks{padding:0;margin:0;list-style:none;display:grid;gap:10px}.tasks li{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:17px;border:1px solid #31415d;border-radius:12px}.tasks strong,.tasks small{display:block}.tasks small{margin-top:6px;color:#93a4c7}.actions{display:flex;gap:8px;align-items:center}.danger{background:transparent;border-color:#8f4b6a;color:#ffa7c0}.empty{color:#aab6d0}footer{text-align:center;padding-top:30px}.error{color:#ffadbe}.sr{position:absolute;width:1px;height:1px;clip:rect(0,0,0,0);overflow:hidden}@media(max-width:670px){.hero{display:block}.counts{justify-content:space-around;margin-top:22px}.tools,.tasks li{flex-wrap:wrap}.tools input{max-width:none}.actions{width:100%;justify-content:space-between}}\n', 'src/tasks.mjs': "export const STATES = Object.freeze(['todo', 'doing', 'done']);\nexport function normalizeTitle(value) {\n  const title = String(value ?? '').trim().replace(/\\s+/g, ' ');\n  if (!title || title.length > 120) throw new Error('Título obligatorio (máximo 120 caracteres)');\n  return title;\n}\nexport function makeTask(title, id) {\n  return { id: String(id), title: normalizeTitle(title), status: 'todo', createdAt: new Date().toISOString() };\n}\nexport function updateTask(tasks, id, changes) {\n  if (changes.status !== undefined && !STATES.includes(changes.status)) throw new Error('Estado inválido');\n  return tasks.map(t => t.id === id ? {...t, ...changes, id:t.id} : t);\n}\nexport function filterTasks(tasks, query='', state='all') {\n  const q = String(query).trim().toLowerCase();\n  return tasks.filter(t => (state === 'all' || t.status === state) && t.title.toLowerCase().includes(q));\n}\nexport function loadTasks(storage) {\n  try { const value = JSON.parse(storage.getItem('reaper.tasks.v1') || '[]');\n    return Array.isArray(value) ? value.filter(t=> t && typeof t.title==='string' && STATES.includes(t.status) && typeof t.id==='string') : [];\n  } catch { return []; }\n}\n", 'tests/tasks.test.mjs': 'import test from \'node:test\';\nimport assert from \'node:assert/strict\';\nimport {normalizeTitle,makeTask,updateTask,filterTasks,loadTasks} from \'../src/tasks.mjs\';\ntest(\'valida el título\',()=>{assert.equal(normalizeTitle(\'  hacer   pruebas \'),\'hacer pruebas\');assert.throws(()=>normalizeTitle(\'   \'));assert.throws(()=>normalizeTitle(\'x\'.repeat(121)));});\ntest(\'crea una tarea real\',()=>{const task=makeTask(\'Nueva\',\'abc\');assert.equal(task.status,\'todo\');assert.equal(task.id,\'abc\');});\ntest(\'actualiza sin mutar la lista anterior\',()=>{const a=[makeTask(\'A\',\'1\')];const b=updateTask(a,\'1\',{status:\'done\'});assert.equal(a[0].status,\'todo\');assert.equal(b[0].status,\'done\');assert.throws(()=>updateTask(a,\'1\',{status:\'unsafe\'}));});\ntest(\'filtra por nombre y estado\',()=>{const a=[makeTask(\'Aprender React\',\'1\'),{...makeTask(\'Aprender Python\',\'2\'),status:\'done\'}];assert.equal(filterTasks(a,\'APRENDER\',\'done\').length,1);});\ntest(\'recupera almacenamiento corrupto\',()=>{assert.deepEqual(loadTasks({getItem:()=>\'{nojson\'}),[]);assert.deepEqual(loadTasks({getItem:()=>\'{"x":1}\'}),[]);});\n'},
    comando_tests='node --test tests/*.test.mjs', comando_ejecutar='npm run dev', etiquetas=('react', 'vite', 'typescript', 'pagina', 'frontend', 'dashboard', 'node'), requiere=('node',))
registrar_plantilla('pwa-offline', 'PWA para Android instalable desde Chrome, notas offline y service worker, sin npm.', 'javascript', {'README.md': '# __TITULO__ — PWA offline para Android\n\nAplicación web instalable (PWA), no un APK ni una app nativa Kotlin.\n\n## Uso\n\n1. `python3 -m http.server 8080 --bind 127.0.0.1`\n2. En el celular abrir http://127.0.0.1:8080 (desde el mismo Termux).\n3. En Chrome: menú → Agregar a pantalla principal / Instalar aplicación, si el navegador lo permite.\n4. Abrir primero online/local para instalar el service worker. Probar después en modo avión.\n5. `node --test tests/*.test.mjs` para tests de lógica (requiere Node.js).\n\nLos datos son locales en `localStorage`. Borrar los datos del navegador borrará las notas.\n\n## Despliegue\n\nHospedar los archivos en la raíz de un dominio con **HTTPS**. Service worker y manifest necesitan rutas coherentes, iconos adecuados y pruebas reales de instalación.\nNo funciona desde `file://`; para usarla desde otro dispositivo hay que desplegarla en HTTPS. Evitá usar servidores públicos sin revisar su configuración.\n', 'app.js': "import {add,remove,load,save} from './storage.mjs';\nconst el=id=>document.getElementById(id);\nlet notes=load(localStorage);\nfunction render(){el('count').textContent=notes.length;el('notes').replaceChildren();if(!notes.length){const li=document.createElement('li');li.textContent='Todavía no hay notas.';el('notes').append(li)}\nfor(const note of notes){const li=document.createElement('li');const text=document.createElement('span');text.textContent=note.text;const del=document.createElement('button');del.type='button';del.textContent='Eliminar';del.setAttribute('aria-label','Eliminar nota '+note.text.slice(0,30));del.addEventListener('click',()=>{notes=remove(notes,note.id);persist();render()});li.append(text,del);el('notes').append(li)}}\nfunction persist(){try{save(localStorage,notes);el('alert').textContent='Guardado en este navegador.'}catch{el('alert').textContent='No se pudo guardar; revisá el almacenamiento disponible.'}}\nel('form').addEventListener('submit',e=>{e.preventDefault();try{notes=add(notes,el('note').value,crypto.randomUUID());persist();el('form').reset();render()}catch(err){el('alert').textContent=err.message}});\nrender();\nif('serviceWorker' in navigator && (location.protocol==='https:'||location.hostname==='localhost'||location.hostname==='127.0.0.1'))navigator.serviceWorker.register('/sw.js').catch(()=>{el('alert').textContent='Sin servicio offline: recargá en HTTPS o localhost.'});\n", 'assets/icon.svg': '<svg xmlns="http://www.w3.org/2000/svg" width="192" height="192" viewBox="0 0 192 192"><rect width="192" height="192" rx="38" fill="#17213b"/><rect x="38" y="30" width="116" height="132" rx="16" fill="#8176ef"/><path d="M60 75h74M60 98h74M60 121h50" stroke="white" stroke-width="10" stroke-linecap="round"/></svg>\n', 'index.html': '<!doctype html>\n<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<meta name="theme-color" content="#17213b"><meta name="description" content="Notas offline y privadas">\n<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" type="image/svg+xml" href="/assets/icon.svg"><link rel="stylesheet" href="/style.css">\n<title>__TITULO__</title></head><body><main class="shell"><header><p class="tag">REAPER 8.10 · PWA</p><h1>__TITULO__</h1><p>Notas rápidas en el celular, disponibles sin conexión después de la primera visita.</p></header>\n<section class="panel"><h2>Agregar una nota</h2><form id="form"><label for="note">Contenido</label><textarea id="note" required maxlength="2000" rows="3" placeholder="Escribí una nota…"></textarea><button>Guardar nota</button></form><p id="alert" role="status"></p></section>\n<section class="panel"><h2>Mis notas <span id="count"></span></h2><ul id="notes"></ul></section><footer>Los datos se guardan únicamente en este navegador.</footer></main><script type="module" src="/app.js"></script></body></html>\n', 'manifest.webmanifest': '{"name":"__TITULO__","short_name":"Notas","description":"Notas locales sin conexión","start_url":"/","scope":"/","display":"standalone","theme_color":"#17213b","background_color":"#0b1325","icons":[{"src":"/assets/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]}\n', 'storage.mjs': "const KEY='reaper.pwa.notes.v1';\nexport function validate(text){const value=String(text??'').trim();if(!value||value.length>2000)throw new Error('La nota debe tener entre 1 y 2000 caracteres');return value;}\nexport function load(storage){try{const data=JSON.parse(storage.getItem(KEY)||'[]');return Array.isArray(data)?data.filter(x=>x&&typeof x.id==='string'&&typeof x.text==='string'):[];}catch{return [];}}\nexport function save(storage,items){storage.setItem(KEY,JSON.stringify(items));}\nexport function add(items,text,id){return [{id:String(id),text:validate(text),createdAt:new Date().toISOString()},...items]}\nexport function remove(items,id){return items.filter(x=>x.id!==id)}\n", 'style.css': ':root{font-family:system-ui,-apple-system,sans-serif;background:#0b1325;color:#e9eeff}*{box-sizing:border-box}body{margin:0}.shell{max-width:790px;padding:32px 18px;margin:auto}h1{font-size:clamp(2rem,7vw,3.2rem)}.tag{color:#aca2ff;text-transform:uppercase;letter-spacing:.15em;font-weight:bold;font-size:.76rem}header{margin-bottom:26px}header>p:last-child,footer{color:#a3b1cc}.panel{background:#16223b;border:1px solid #334363;padding:24px;margin:18px 0;border-radius:18px}h2{margin:0 0 20px}label{display:block;margin-bottom:8px}textarea{width:100%;background:#0a1428;border:1px solid #50668c;border-radius:10px;padding:12px;color:inherit;font:inherit;resize:vertical}button{background:#796cf6;color:white;border:1px solid #9b93ff;border-radius:10px;padding:12px 15px;margin-top:12px;font:inherit;cursor:pointer}button:focus-visible,textarea:focus-visible{outline:3px solid white}#notes{list-style:none;margin:0;padding:0;display:grid;gap:10px}#notes li{background:#0b162a;border:1px solid #34435e;padding:14px;border-radius:12px;display:flex;justify-content:space-between;gap:10px;align-items:center;overflow-wrap:anywhere}#notes button{background:transparent;color:#ffa6bc;border-color:#8f4967;margin:0}footer{text-align:center;padding-top:24px}\n', 'sw.js': "const CACHE='__PROYECTO__-pwa-v1';\nconst ASSETS=['/','/index.html','/style.css','/app.js','/storage.mjs','/manifest.webmanifest','/assets/icon.svg'];\nself.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));\nself.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));\nself.addEventListener('fetch',event=>{const req=event.request;if(req.method!=='GET'||new URL(req.url).origin!==self.location.origin)return;\n  event.respondWith(caches.match(req).then(hit=>hit||fetch(req).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(c=>c.put(req,copy));}return response;}).catch(()=>req.mode==='navigate'?caches.match('/index.html'):Response.error())));\n});\n", 'tests/storage.test.mjs': "import test from 'node:test'; import assert from 'node:assert/strict';import{validate,add,remove,load,save}from '../storage.mjs';\ntest('validación real',()=>{assert.equal(validate(' hola '),'hola');assert.throws(()=>validate(''));assert.throws(()=>validate('x'.repeat(2001)))});\ntest('agregar y eliminar',()=>{const n=add([],'nota','id1');assert.equal(n.length,1);assert.deepEqual(remove(n,'id1'),[])});\ntest('persistencia',()=>{const state=new Map();const storage={getItem:k=>state.get(k),setItem:(k,v)=>state.set(k,v)};save(storage,add([],'hola','id1'));assert.equal(load(storage)[0].text,'hola')});\ntest('datos corruptos',()=>{assert.deepEqual(load({getItem:()=>'{garbage'}),[])});\n"},
    comando_tests='node --test tests/*.test.mjs', comando_ejecutar='python3 -m http.server 8080 --bind 127.0.0.1', etiquetas=('mobile', 'android', 'pwa', 'web', 'offline', 'celular', 'instalable'), requiere=('node',))
registrar_plantilla('web-auth', 'API de autenticación LOCAL con SQLite, PBKDF2, sesiones, CSRF y pruebas HTTP. No apta para producción pública.', 'python', {'.env.example': '# Solo ejemplos, NO son secretos ni deben copiarse a producción sin revisión\nPORT=8080\nREAPER_AUTH_DB=instance/auth.sqlite3\n# REAPER_AUTH_HTTPS=1 se configura SOLO cuando realmente hay TLS extremo a extremo/proxy seguro\n', '.gitignore': 'instance/\n__pycache__/\n.pytest_cache/\n.env\n.env.*\n!.env.example\n', 'DEPLOY_CHECKLIST.md': '# Verificación obligatoria antes de despliegue\n\n- [ ] Elegir framework y proveedor de identidad mantenidos; revisar riesgos de esta plantilla demostrativa.\n- [ ] HTTPS real y cookie `Secure` correctamente configurada detrás de proxy de confianza.\n- [ ] Protección de inicio de sesión contra fuerza bruta y límite de solicitudes por IP/cuenta.\n- [ ] CSRF y validación de cabecera Origin/Referer en endpoints mutadores.\n- [ ] Migraciones y backups de SQLite, o DB gestionada para escalado.\n- [ ] Monitorización, recuperación de contraseñas, confirmación de correo y registros seguros.\n- [ ] Escaneo de dependencias, pruebas E2E, seguridad y carga antes de conectar dominios públicos.\n\nEsta plantilla no proporciona un despliegue de un clic y REAPER no debe declarar que está lista para producción.\n', 'README.md': '# __TITULO__ — API con autenticación y SQLite\n\n**Demo de desarrollo LOCAL, no producción**. Implementada en Python stdlib y SQLite sin pip/npm.\n\n## Ejecutar y probar\n\n```bash\npython3 -m unittest discover -s tests -v\npython3 app.py\n```\n\nAPI en `http://127.0.0.1:8080`:\n- `GET /api/health` (sin autenticación)\n- `POST /api/register` con JSON `{ "email": "demo@example.com", "password": "una-contraseña-larga" }`\n- `POST /api/login` con el mismo JSON\n- `GET /api/me` con cookie de sesión\n- `POST /api/logout` con cookie y cabecera `X-CSRF-Token` recibida en login\n\nCookies HttpOnly SameSite=Strict, contraseña almacenada como hash PBKDF2 con sal y sesiones aleatorias almacenadas como hash.\n\n## Antes de cualquier despliegue público\n\n**No publicar este servidor**. Faltan: proxy HTTPS seguro, cookie Secure validada, control de intentos/rate limit persistente, logs y observabilidad, recuperación de cuenta, confirmación de correo, backups cifrados, política de usuarios, revisión de privacidad, control de CSRF por origen y pruebas de seguridad externas. La aplicación deliberadamente escucha solo en 127.0.0.1.\n\nPara trabajo real usar un framework mantenido y soluciones especializadas de identidad; esta plantilla es para aprender y extender dentro de un laboratorio propio.\n', 'app.py': '"""REAPER 8.10: demo HTTP local de autenticación con SQLite (no lista para Internet público)."""\nfrom __future__ import annotations\nimport hashlib\nimport hmac\nimport json\nimport os\nimport re\nimport secrets\nimport sqlite3\nimport time\nfrom http import HTTPStatus\nfrom http.cookies import SimpleCookie\nfrom http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\nfrom pathlib import Path\nfrom urllib.parse import urlsplit\n\nROOT = Path(__file__).resolve().parent\nDB = Path(os.environ.get(\'REAPER_AUTH_DB\', str(ROOT / \'instance\' / \'auth.sqlite3\')))\nITERATIONS = 310000\nTTL_SECONDS = 12 * 60 * 60\nMAX_BODY = 8192\n# Todos los endpoints son locales. Usar HTTPS+protección de proxy y gestión de secretos antes de exponerlo.\n\n\ndef connect():\n    DB.parent.mkdir(parents=True, exist_ok=True)\n    con = sqlite3.connect(str(DB), timeout=10)\n    con.row_factory = sqlite3.Row\n    con.execute(\'PRAGMA foreign_keys=ON\')\n    con.execute(\'CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, digest TEXT NOT NULL)\')\n    con.execute(\'CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, csrf_hash TEXT NOT NULL, expires INTEGER NOT NULL)\')\n    con.commit()\n    return con\n\n\ndef hash_password(password, salt):\n    return hashlib.pbkdf2_hmac(\'sha256\', password.encode(\'utf-8\'), bytes.fromhex(salt), ITERATIONS).hex()\n\n\ndef validate(email, password):\n    if not isinstance(email, str) or not isinstance(password, str):\n        raise ValueError(\'Correo o contraseña inválidos\')\n    email = email.strip().lower()\n    if len(email) > 254 or not re.fullmatch(r\'[^\\s@]{1,64}@[^\\s@]+\\.[^\\s@]+\', email):\n        raise ValueError(\'Formato de correo inválido\')\n    if not (12 <= len(password) <= 256):\n        raise ValueError(\'La contraseña debe tener entre 12 y 256 caracteres\')\n    return email\n\n\ndef create_session(con, user_id):\n    token = secrets.token_urlsafe(32)\n    csrf = secrets.token_urlsafe(32)\n    con.execute(\'INSERT INTO sessions (token_hash,user_id,csrf_hash,expires) VALUES (?,?,?,?)\',\n                (hashlib.sha256(token.encode()).hexdigest(), user_id, hashlib.sha256(csrf.encode()).hexdigest(), int(time.time())+TTL_SECONDS))\n    con.commit()\n    return token, csrf\n\n\nclass Handler(BaseHTTPRequestHandler):\n    server_version = \'REAPER-Demo/1.0\'\n    sys_version = \'\'\n\n    def log_message(self, fmt, *args):\n        # No registrar cookies ni cuerpos de peticiones.\n        pass\n\n    def respond(self, code, data, cookie=None):\n        blob = json.dumps(data, ensure_ascii=False).encode(\'utf-8\')\n        self.send_response(code)\n        self.send_header(\'Content-Type\',\'application/json; charset=utf-8\')\n        self.send_header(\'Cache-Control\',\'no-store\')\n        self.send_header(\'X-Content-Type-Options\',\'nosniff\')\n        self.send_header(\'Referrer-Policy\',\'no-referrer\')\n        self.send_header(\'X-Frame-Options\',\'DENY\')\n        if cookie is not None:\n            # Solo marcar Secure cuando hay TLS delante de esta aplicación.\n            secure = \'; Secure\' if os.environ.get(\'REAPER_AUTH_HTTPS\') == \'1\' else \'\'\n            self.send_header(\'Set-Cookie\',f\'session={cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age={TTL_SECONDS if cookie else 0}{secure}\')\n        self.send_header(\'Content-Length\',str(len(blob)))\n        self.end_headers()\n        self.wfile.write(blob)\n\n    def read_data(self):\n        if self.headers.get(\'Content-Type\',\'\').split(\';\')[0].lower()!=\'application/json\':\n            raise ValueError(\'Content-Type application/json requerido\')\n        try:\n            length = int(self.headers.get(\'Content-Length\',\'0\'))\n        except ValueError as exc:\n            raise ValueError(\'Content-Length inválido\') from exc\n        if length <= 0 or length > MAX_BODY:\n            raise ValueError(\'El JSON debe tener entre 1 y 8192 bytes\')\n        try:\n            obj = json.loads(self.rfile.read(length))\n        except (ValueError, UnicodeDecodeError) as exc:\n            raise ValueError(\'JSON malformado\') from exc\n        if not isinstance(obj, dict):\n            raise ValueError(\'Se esperaba un objeto JSON\')\n        return obj\n\n    def cookie_token(self):\n        jar = SimpleCookie()\n        try:jar.load(self.headers.get(\'Cookie\',\'\'))\n        except Exception:return \'\'\n        return jar[\'session\'].value if \'session\' in jar else \'\'\n\n    def auth_session(self, con):\n        token = self.cookie_token()\n        if not token:\n            return None\n        row = con.execute(\'SELECT sessions.token_hash, sessions.csrf_hash, users.id, users.email FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?\',\n                          (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()\n        return row\n\n    def do_GET(self):\n        path = urlsplit(self.path).path\n        if path==\'/api/health\':\n            return self.respond(200,{\'ok\':True})\n        if path==\'/api/me\':\n            with connect() as con:\n                row=self.auth_session(con)\n            return self.respond(200,{\'authenticated\':bool(row),\'email\':row[\'email\'] if row else None})\n        return self.respond(404,{\'error\':\'Ruta inexistente\'})\n\n    def do_POST(self):\n        path=urlsplit(self.path).path\n        if path not in (\'/api/register\',\'/api/login\',\'/api/logout\'):\n            return self.respond(404,{\'error\':\'Ruta inexistente\'})\n        try:\n            body=self.read_data()\n        except ValueError as exc:\n            return self.respond(400,{\'error\':str(exc)})\n        if path==\'/api/logout\':\n            with connect() as con:\n                row=self.auth_session(con)\n                if row is None:return self.respond(401,{\'error\':\'No autenticado\'})\n                csrf=self.headers.get(\'X-CSRF-Token\',\'\')\n                if not hmac.compare_digest(hashlib.sha256(csrf.encode()).hexdigest(),row[\'csrf_hash\']):\n                    return self.respond(403,{\'error\':\'Token CSRF inválido\'})\n                con.execute(\'DELETE FROM sessions WHERE token_hash=?\',(row[\'token_hash\'],))\n                con.commit()\n            return self.respond(200,{\'ok\':True},cookie=\'\')\n        try:\n            email=validate(body.get(\'email\'),body.get(\'password\'))\n        except ValueError as exc:\n            return self.respond(400,{\'error\':str(exc)})\n        with connect() as con:\n            if path==\'/api/register\':\n                salt=secrets.token_hex(16)\n                digest=hash_password(body[\'password\'],salt)\n                try:\n                    cur=con.execute(\'INSERT INTO users(email,salt,digest) VALUES (?,?,?)\',(email,salt,digest))\n                    con.commit()\n                except sqlite3.IntegrityError:\n                    return self.respond(409,{\'error\':\'No se pudo registrar ese correo\'})\n                user_id=cur.lastrowid\n                status=201\n            else:\n                row=con.execute(\'SELECT id,salt,digest FROM users WHERE email=?\',(email,)).fetchone()\n                # Coste comparable si no existe; la cuota/IP debe gestionarla un proxy en producción.\n                guess=hash_password(body[\'password\'],row[\'salt\'] if row else \'00\'*16)\n                if not row or not hmac.compare_digest(guess,row[\'digest\']):\n                    return self.respond(401,{\'error\':\'Credenciales inválidas\'})\n                user_id=row[\'id\'];status=200\n            token,csrf=create_session(con,user_id)\n        return self.respond(status,{\'ok\':True,\'email\':email,\'csrf\':csrf},cookie=token)\n\n\ndef main():\n    with connect():pass\n    server=ThreadingHTTPServer((\'127.0.0.1\',int(os.environ.get(\'PORT\',\'8080\'))),Handler)\n    print(f\'REAPER demo auth local: http://127.0.0.1:{server.server_port}\',flush=True)\n    try:server.serve_forever()\n    except KeyboardInterrupt:pass\n    finally:server.server_close()\n\n\nif __name__==\'__main__\':main()\n', 'tests/test_auth.py': "import contextlib\nimport importlib.util\nimport json\nimport tempfile\nimport threading\nimport unittest\nfrom http.server import ThreadingHTTPServer\nfrom http.client import HTTPConnection\nfrom pathlib import Path\n\nspec = importlib.util.spec_from_file_location('demo_auth', str(Path(__file__).resolve().parents[1] / 'app.py'))\napp = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(app)\n\n\nclass AuthHTTPTests(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n        cls.temp=tempfile.TemporaryDirectory()\n        app.DB=Path(cls.temp.name)/'auth.db'\n        cls.server=ThreadingHTTPServer(('127.0.0.1',0), app.Handler)\n        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)\n        cls.thread.start()\n    @classmethod\n    def tearDownClass(cls):\n        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=3);cls.temp.cleanup()\n\n    def request(self,method,path,data=None,cookie='',csrf=''):\n        con=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)\n        body=json.dumps(data or {}).encode() if method=='POST' else None\n        headers={'Content-Type':'application/json'}\n        if cookie:headers['Cookie']=cookie\n        if csrf:headers['X-CSRF-Token']=csrf\n        try:\n            con.request(method,path,body=body,headers=headers)\n            res=con.getresponse();out=(res.status, dict(res.getheaders()), json.loads(res.read()))\n        finally:con.close()\n        return out\n\n    def test_01_health_and_unauthenticated(self):\n        self.assertEqual(self.request('GET','/api/health')[0],200)\n        self.assertFalse(self.request('GET','/api/me')[2]['authenticated'])\n\n    def test_02_register_login_logout_and_csrf(self):\n        email='person-test@example.org';pw='long-secure-password-123'\n        code,head,data=self.request('POST','/api/register',{'email':email,'password':pw})\n        self.assertEqual(code,201)\n        cookie=head['Set-Cookie'].split(';')[0]\n        self.assertIn('HttpOnly',head['Set-Cookie']);self.assertIn('SameSite=Strict',head['Set-Cookie'])\n        self.assertTrue(self.request('GET','/api/me',cookie=cookie)[2]['authenticated'])\n        self.assertEqual(self.request('POST','/api/logout',{},cookie=cookie)[0],403)\n        self.assertEqual(self.request('POST','/api/logout',{},cookie=cookie,csrf=data['csrf'])[0],200)\n        self.assertFalse(self.request('GET','/api/me',cookie=cookie)[2]['authenticated'])\n        self.assertEqual(self.request('POST','/api/login',{'email':email,'password':'wrong-password123'})[0],401)\n        self.assertEqual(self.request('POST','/api/login',{'email':email,'password':pw})[0],200)\n\n    def test_03_duplicate_registration(self):\n        email='duplicate-test@example.org';body={'email':email,'password':'a-long-password123'}\n        self.assertEqual(self.request('POST','/api/register',body)[0],201)\n        self.assertEqual(self.request('POST','/api/register',body)[0],409)\n\n    def test_04_bad_input(self):\n        self.assertEqual(self.request('POST','/api/register',{'email':'invalid','password':'short'})[0],400)\n        self.assertEqual(self.request('POST','/api/register',{'email':'x@y.com','password':'tiny'})[0],400)\n        self.assertEqual(self.request('GET','/invalid')[0],404)\n\n    def test_05_password_not_stored_in_clear(self):\n        with app.connect() as con: rows=con.execute('SELECT salt,digest FROM users').fetchall()\n        self.assertTrue(rows)\n        for row in rows:\n            self.assertEqual(len(row['salt']),32)\n            self.assertEqual(len(row['digest']),64)\n            self.assertNotIn('password',row['digest'])\n\nif __name__=='__main__':unittest.main()\n"},
    comando_tests='python3 -m unittest discover -s tests -v', comando_ejecutar='python3 app.py', etiquetas=('api', 'backend', 'autenticacion', 'login', 'registro', 'sqlite', 'sesiones'), requiere=())
registrar_plantilla('android-java', 'Proyecto Android nativo Java con Gradle/GitHub Actions para compilar APK debug y tests de lógica.', 'java', {'.github/workflows/android.yml': 'name: Android Debug APK\non:\n  workflow_dispatch:\n  push:\n    paths:\n      - "app/**"\n      - "build.gradle"\n      - "settings.gradle"\n      - "gradle.properties"\n      - ".github/workflows/android.yml"\npermissions:\n  contents: read\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-java@v4\n        with:\n          distribution: temurin\n          java-version: \'17\'\n      - uses: android-actions/setup-android@v3\n      - uses: gradle/actions/setup-gradle@v4\n        with:\n          gradle-version: \'8.11.1\'\n      - name: Install Android SDK platform\n        run: sdkmanager --install \'platforms;android-35\' \'build-tools;35.0.0\'\n      - name: Build debug APK\n        run: gradle --no-daemon assembleDebug\n      - uses: actions/upload-artifact@v4\n        with:\n          name: reaper-android-debug-apk\n          path: app/build/outputs/apk/debug/*.apk\n', '.gitignore': '.gradle/\n**/build/\nlocal.properties\n*.keystore\n*.jks\n*.apk\n.idea/\n', 'README.md': '# __TITULO__ — Android nativo (Java)\n\nProyecto Android nativo real de ejemplo con Activity y botón que conserva un contador en SharedPreferences.\n\n## Verificación sin Android SDK (Termux con JDK)\n\n`bash tests/test_counter.sh` compila y ejecuta la lógica de Java (4 aserciones). Esto **NO construye el APK**.\n\n## Construir el APK usando GitHub Actions\n\n1. Crear un repositorio propio y subir todos los archivos, conservando `.github/workflows/android.yml`.\n2. Ir a Actions → Android Debug APK → Run workflow.\n3. Si termina correctamente, el APK **debug** aparecerá como artefacto del workflow. No es un paquete de producción ni está firmado para tiendas.\n4. Antes de distribuir, cambiar `applicationId`, nombre, permisos, iconos, revisar dependencias y configurar firma de release.\n\nEl workflow descarga Android SDK y Gradle en el runner. Sin conexión ni GitHub Actions, se requiere Android SDK y Gradle locales.\n**No se ha compilado un APK en esta entrega**: este entorno no tiene Android SDK.\n\nBuild toolchain: AGP 8.9.2, Gradle 8.11.1, Java 17, compileSdk 35.\n', 'app/build.gradle': "plugins { id 'com.android.application' }\n\nandroid {\n    namespace 'com.reaper.demo'\n    compileSdk 35\n    defaultConfig {\n        applicationId 'com.reaper.__PROYECTO__'\n        minSdk 24\n        targetSdk 35\n        versionCode 1\n        versionName '0.1.0'\n    }\n}\n", 'app/src/main/AndroidManifest.xml': '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n    <application android:allowBackup="false" android:label="__TITULO__" android:theme="@android:style/Theme.Material.Light.NoActionBar" android:usesCleartextTraffic="false">\n        <activity android:name="com.reaper.demo.MainActivity" android:exported="true">\n            <intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>\n        </activity>\n    </application>\n</manifest>\n', 'app/src/main/java/com/reaper/demo/CounterLogic.java': 'package com.reaper.demo;\n\npublic final class CounterLogic {\n    private CounterLogic() { }\n    public static int increment(int previous) {\n        if (previous < 0) throw new IllegalArgumentException("Contador negativo");\n        return previous == Integer.MAX_VALUE ? 0 : previous + 1;\n    }\n}\n', 'app/src/main/java/com/reaper/demo/MainActivity.java': 'package com.reaper.demo;\n\nimport android.app.Activity;\nimport android.os.Bundle;\nimport android.view.Gravity;\nimport android.widget.Button;\nimport android.widget.LinearLayout;\nimport android.widget.TextView;\n\npublic class MainActivity extends Activity {\n    private int count;\n    private TextView label;\n    @Override public void onCreate(Bundle state) {\n        super.onCreate(state);\n        count = getPreferences(MODE_PRIVATE).getInt("count", 0);\n        LinearLayout layout = new LinearLayout(this);\n        layout.setPadding(40, 80, 40, 40);\n        layout.setOrientation(LinearLayout.VERTICAL);\n        layout.setGravity(Gravity.CENTER);\n        layout.setBackgroundColor(0xff13213a);\n        TextView title = new TextView(this);\n        title.setText("__TITULO__");\n        title.setTextSize(26);\n        title.setTextColor(0xffffffff);\n        label = new TextView(this);\n        label.setTextSize(24);\n        label.setTextColor(0xffd8ddff);\n        label.setPadding(0, 40, 0, 28);\n        Button button = new Button(this);\n        button.setText("Sumar uno");\n        button.setOnClickListener(view -> {\n            count = CounterLogic.increment(count);\n            getPreferences(MODE_PRIVATE).edit().putInt("count", count).apply();\n            updateLabel();\n        });\n        layout.addView(title);\n        layout.addView(label);\n        layout.addView(button);\n        setContentView(layout);\n        updateLabel();\n    }\n    private void updateLabel() { label.setText("Contador: " + count); }\n}\n', 'build.gradle': "plugins {\n    id 'com.android.application' version '8.9.2' apply false\n}\n", 'gradle.properties': 'org.gradle.jvmargs=-Xmx1536m -Dfile.encoding=UTF-8\nandroid.useAndroidX=true\n', 'settings.gradle': "pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\ndependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\nrootProject.name = '__Proyecto__'\ninclude ':app'\n", 'tests/CounterLogicTest.java': 'import com.reaper.demo.CounterLogic;\npublic class CounterLogicTest {\n    public static void main(String[] args) {\n        if (CounterLogic.increment(0) != 1) throw new AssertionError("0+1 debe ser 1");\n        if (CounterLogic.increment(41) != 42) throw new AssertionError("41+1 debe ser 42");\n        if (CounterLogic.increment(Integer.MAX_VALUE) != 0) throw new AssertionError("overflow controlado");\n        try { CounterLogic.increment(-1); throw new AssertionError("No rechazó negativo"); }\n        catch (IllegalArgumentException expected) { }\n        System.out.println("4 comprobaciones Java aprobadas");\n    }\n}\n', 'tests/test_counter.sh': '#!/usr/bin/env bash\nset -euo pipefail\nROOT="$(cd "$(dirname "$0")/.." && pwd)"\nTMP="$(mktemp -d)"\ntrap \'rm -rf "$TMP"\' EXIT\njavac -d "$TMP" "$ROOT/app/src/main/java/com/reaper/demo/CounterLogic.java" "$ROOT/tests/CounterLogicTest.java"\njava -cp "$TMP" CounterLogicTest\n'},
    comando_tests='bash tests/test_counter.sh', comando_ejecutar='gradle assembleDebug', etiquetas=('android', 'apk', 'movil', 'mobile', 'gradle', 'java', 'nativo'), requiere=('java', 'javac', 'bash'))

class TestReaper810Round9(BaseTest):
    """Pruebas de nuevas plantillas multiplataforma, sin proveedores IA ni red externa."""

    def test_catalogo_completo(self):
        for nombre in ('react-vite','pwa-offline','web-auth','android-java'):
            p=obtener_plantilla(nombre)
            self.assertIsNotNone(p)
            self.assertTrue(len(p.archivos)>=5)
            self.assertTrue(p.comando_tests)

    def test_crea_plantillas_sin_api(self):
        for nombre in ('react-vite','pwa-offline','web-auth','android-java'):
            with self.subTest(nombre=nombre), tempfile.TemporaryDirectory() as tmp:
                destino=Path(tmp)/'reaperdemo'
                archivos=crear_desde_plantilla(nombre,destino)
                self.assertGreaterEqual(len(archivos),6)
                self.assertTrue((destino/'REAPER.md').is_file())
                self.assertTrue((destino/'.reaper'/'config.json').is_file())

    def test_react_estructura_auditable(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino=Path(tmp)/'react'
            crear_desde_plantilla('react-vite',destino)
            self.assertTrue(auditar_web_proyecto(destino)['ok'])
            self.assertEqual(json.loads((destino/'package.json').read_text())['name'],'react')

    def test_pwa_manifest_recursos_validos(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino=Path(tmp)/'notas'
            crear_desde_plantilla('pwa-offline',destino)
            manifest=json.loads((destino/'manifest.webmanifest').read_text())
            self.assertEqual(manifest['display'],'standalone')
            self.assertTrue((destino/'sw.js').is_file())
            self.assertTrue(auditar_web_proyecto(destino)['ok'])

    def test_node_logica_react_y_pwa(self):
        if not shutil.which('node'):
            self.skipTest('Node.js no instalado')
        for nombre in ('react-vite','pwa-offline'):
            with self.subTest(nombre=nombre), tempfile.TemporaryDirectory() as tmp:
                destino=Path(tmp)/nombre
                crear_desde_plantilla(nombre,destino)
                archivos=sorted((destino/'tests').glob('*.test.mjs'))
                p=subprocess.run(['node','--test',*[str(f) for f in archivos]],cwd=destino,
                    text=True,capture_output=True,timeout=25)
                self.assertEqual(p.returncode,0,p.stdout[-1500:]+p.stderr[-1500:])

    def test_python_auth_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino=Path(tmp)/'auth'
            crear_desde_plantilla('web-auth',destino)
            p=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=destino,
                text=True,capture_output=True,timeout=35)
            self.assertEqual(p.returncode,0,p.stdout[-1500:]+p.stderr[-1500:])

    def test_android_java_offline(self):
        if not all(shutil.which(x) for x in ('java','javac','bash')):
            self.skipTest('Java/JDK o bash no instalado')
        with tempfile.TemporaryDirectory() as tmp:
            destino=Path(tmp)/'apk'
            crear_desde_plantilla('android-java',destino)
            p=subprocess.run(['bash','tests/test_counter.sh'],cwd=destino,
                text=True,capture_output=True,timeout=25)
            self.assertEqual(p.returncode,0,p.stdout[-1500:]+p.stderr[-1500:])

    def test_cli_nuevo_no_requiere_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino=Path(tmp)/'nueva'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--nuevo','pwa-offline',str(destino)]),0)
            self.assertTrue((destino/'index.html').exists())

    def test_archivos_privados_no_incluidos_en_plantillas(self):
        for nombre in ('react-vite','pwa-offline','web-auth','android-java'):
            p=obtener_plantilla(nombre)
            self.assertTrue(all('__pycache__' not in r and 'node_modules' not in r for r in p.archivos))
            self.assertFalse(any(r in ('.env','instance/auth.sqlite3') for r in p.archivos))



class TestReaper810Round10(BaseTest):
    """Auditoría de dictámenes de revisores: no aprobar respuestas inconclusas."""

    def test_veredicto_no_formato_no_aprueba(self):
        self.assertEqual(veredicto("todo perfecto"), (False, False))
        self.assertEqual(veredicto("VEREDICTO: APROBADO\nSin incidencias"), (True, True))
        self.assertEqual(veredicto("VEREDICTO: CAMBIOS\nFalta un test"), (False, True))

    def test_revisor_inconcluso_registra_aviso(self):
        ws = self.proyecto({"app.py": "x = 1\n"})
        llm = MockLLM(lambda m, k: terminar_xml("todo perfecto"))
        ui = self.ui()
        orq = Orquestador(llm, ws,
                          self.ajustes(tests_primero=False, torneo=False,
                                       max_revisiones=1, lecciones=False, forense=False), ui)
        cid = ws.checkpoints.iniciar("revisión")
        aprobado, motivo = orq.revisar("revisar app", Tarea("1", "revisar código", ["app.py"]),
                                       "diff válido", cid)
        self.assertFalse(aprobado)
        self.assertIn("un dictamen verificable", motivo)
        self.assertIn("SIN VEREDICTO", ui.texto_registrado())


class TestReaper810Round11(BaseTest):
    """Contratos de salida: JSON anidado y evidencias realmente positivas."""

    def test_json_anidado_y_llaves_dentro_de_strings(self):
        texto = ('```json\n' + json.dumps({
            "decision": "APPROVE", "reasons": ["Se comprobó {x} y } dentro de texto"],
            "details": {"nested": {"ok": True}}, "evidence_ids": ["EV-TESTS"]
        }, ensure_ascii=False) + '\n```')
        recibido = extraer_json_x(texto)
        self.assertEqual(recibido["details"]["nested"], {"ok": True})
        self.assertEqual(recibido["reasons"], ["Se comprobó {x} y } dentro de texto"])

    def test_json_valido_despues_de_ejemplo_invalido(self):
        dato = extraer_json_x('Ejemplo: {no-json}; real: {"decision":"ABSTAIN","reasons":["ok"]}')
        self.assertEqual(dato["decision"], "ABSTAIN")

    def test_json_sin_objeto_o_puro_texto(self):
        self.assertIsNone(extraer_json_x('[1, 2, 3]'))
        self.assertIsNone(extraer_json_x('No puedo aprobar.'))

    def test_approve_sin_inventario_no_es_verificado(self):
        d = parsear_dictamen('{"decision":"APPROVE","evidence_ids":["EV-1"]}', 'supervisor')
        self.assertFalse(d.valido)
        self.assertIn("inventario", d.problema)

    def test_auditoria_no_aprueba_pruebas_rojas(self):
        texto = '{"criteria":[{"criterion":"CRUD","status":"MET","evidence_ids":["EV-TESTS"]}]}'
        self.assertEqual(parsear_auditoria(texto, {"EV-TESTS": "exit 1"})[0]["status"], "UNKNOWN")
        self.assertEqual(parsear_auditoria(texto, {"EV-TESTS": "22 pasaron; 34 failed"})[0]["status"], "UNKNOWN")

    def test_auditoria_no_aprueba_plan_sin_ejecutar(self):
        t = '{"criteria":[{"criterion":"UI","status":"MET","evidence_ids":["EV-PLAN"]}]}'
        self.assertEqual(parsear_auditoria(t, {"EV-PLAN": "interfaz + db"})[0]["status"], "UNKNOWN")

    def test_auditoria_no_aprueba_sin_cambios(self):
        t = '{"criteria":[{"criterion":"API","status":"MET","evidence_ids":["EV-DIFF"]}]}'
        self.assertEqual(parsear_auditoria(t, {"EV-DIFF": "(sin cambios)"})[0]["status"], "UNKNOWN")

    def test_auditoria_acepta_evidencia_positiva(self):
        t = '{"criteria":[{"criterion":"tests","status":"MET","evidence_ids":["EV-TESTS"]}]}'
        self.assertEqual(parsear_auditoria(t, {"EV-TESTS": "17 pasaron"})[0]["status"], "MET")

    def test_auditoria_no_oculta_tests_fallidos_citando_diff(self):
        t = '{"criteria":[{"criterion":"API","status":"MET","evidence_ids":["EV-DIFF"]}]}'
        evidencia = {"EV-DIFF": "src/api.py +120", "EV-TESTS": "exit 1",
                     "EV-ESTADO": "estado por verificación real: fallida; tareas fallidas: 2"}
        self.assertEqual(parsear_auditoria(t, evidencia)[0]["status"], "UNKNOWN")

    def test_auditoria_sin_contradicciones_si_mantiene_met(self):
        t = '{"criteria":[{"criterion":"API","status":"MET","evidence_ids":["EV-DIFF", "EV-TESTS"]}]}'
        evidencia = {"EV-DIFF": "src/api.py +120", "EV-TESTS": "12 pasaron",
                     "EV-ESTADO": "estado por verificación real: verificada; tareas fallidas: ninguna"}
        self.assertEqual(parsear_auditoria(t, evidencia)[0]["status"], "MET")

    def test_compatibilidad_dictamen_antiguo_valido(self):
        d = parsear_dictamen('{"decision":"APPROVE","evidence_ids":["EV-TESTS"]}',
                             'supervisor', {"EV-TESTS": "5 pasaron"})
        self.assertTrue(d.valido)



class TestReaper810Round12(BaseTest):
    """Aceptación independiente: pruebas reales, protección anti-falsos verdes."""

    def _externo(self, codigo: str, minimo: int = 1, timeout: int = 15):
        suite = self.dir / 'evaluador_independiente'
        suite.mkdir(parents=True, exist_ok=True)
        (suite / 'test_calidad.py').write_text(codigo, encoding='utf-8')
        ws = self.proyecto({'.reaper/acceptance.json': json.dumps({
            'suite_dir': str(suite), 'min_tests': minimo, 'timeout': timeout
        })})
        return ws, suite

    def test_config_ausente_compatibilidad(self):
        ws = self.proyecto({'app.py': 'x=1\n'})
        self.assertEqual(huella_aceptacion(ws), 'sin-evaluador')
        self.assertIsNone(ejecutar_aceptacion_independiente(ws))

    def test_prueba_externa_real_verde(self):
        ws, suite = self._externo('import unittest\nclass TestX(unittest.TestCase):\n'
                                  ' def test_ok(self): self.assertEqual(2+2,4)\n')
        huella = huella_aceptacion(ws)
        r = ejecutar_aceptacion_independiente(ws, huella_fijada=huella)
        self.assertTrue(r.ok, r.resumen())
        self.assertIn('Ran 1 test', r.stderr)

    def test_prueba_externa_fallida_no_aprueba(self):
        ws, suite = self._externo('import unittest\nclass TestX(unittest.TestCase):\n'
                                  ' def test_falla(self): self.assertEqual(1,2)\n')
        r = ejecutar_aceptacion_independiente(ws)
        self.assertFalse(r.ok)
        self.assertIn('FAIL', r.stderr)

    def test_minimo_no_se_cumple(self):
        ws, _ = self._externo('import unittest\nclass TestX(unittest.TestCase):\n'
                              ' def test_ok(self): self.assertTrue(True)\n', minimo=10)
        r = ejecutar_aceptacion_independiente(ws)
        self.assertFalse(r.ok)
        self.assertIn('1/10', r.stderr)

    def test_zero_tests_ni_omitir(self):
        ws, suite = self._externo('import unittest\nclass TestX(unittest.TestCase):\n pass\n')
        self.assertFalse(ejecutar_aceptacion_independiente(ws).ok)
        (suite / 'test_calidad.py').write_text('import unittest\nclass TestX(unittest.TestCase):\n'
                                                ' @unittest.skip("no")\n def test_ok(self): pass\n')
        self.assertFalse(ejecutar_aceptacion_independiente(ws).ok)

    def test_suite_editada_no_acepta(self):
        ws, suite = self._externo('import unittest\nclass TestX(unittest.TestCase):\n'
                                  ' def test_ok(self): self.assertTrue(True)\n')
        huella = huella_aceptacion(ws)
        (suite / 'test_calidad.py').write_text('import unittest\nclass TestX(unittest.TestCase):\n'
                                                ' def test_ok(self): self.assertFalse(False)\n')
        r = ejecutar_aceptacion_independiente(ws, huella_fijada=huella)
        self.assertFalse(r.ok)
        self.assertIn('cambiado', r.stderr)

    def test_eliminacion_manifiesto_no_acepta(self):
        ws, _ = self._externo('import unittest\nclass TestX(unittest.TestCase):\n'
                              ' def test_ok(self): pass\n')
        huella = huella_aceptacion(ws)
        (ws.raiz / '.reaper' / 'acceptance.json').unlink()
        self.assertFalse(ejecutar_aceptacion_independiente(ws, huella_fijada=huella).ok)

    def test_cli_aceptacion_sin_api(self):
        ws, _ = self._externo('import unittest\nclass TestX(unittest.TestCase):\n'
                              ' def test_ok(self): self.assertTrue(True)\n')
        self.assertEqual(main(['--aceptacion', '--proyecto', str(ws.raiz)]), 0)

    def test_no_evaluador_dentro_proyecto(self):
        ws = self.proyecto({'.reaper/acceptance.json': json.dumps({
            'suite_dir': str(self.dir / 'proy' / 'tests'), 'min_tests': 1
        }), 'tests/test_calidad.py': 'import unittest\n'})
        with self.assertRaisesRegex(ValueError, 'FUERA'):
            huella_aceptacion(ws)

    def test_orquestador_verificar_es_bloqueante(self):
        ws, _ = self._externo('import unittest\nclass TestX(unittest.TestCase):\n'
                              ' def test_falla(self): self.assertEqual(7,8)\n')
        ws.checkpoints.iniciar('base')
        orq = Orquestador(MockLLM([]), ws, self.ajustes(tests_primero=False,
                           lecciones=False, forense=False), self.ui())
        verif = orq.verificar(1)
        self.assertFalse(verif.ok)
        self.assertIsNotNone(verif.aceptacion)
        self.assertIn('ACEPTACIÓN INDEPENDIENTES', verif.diagnostico)
        self.assertEqual(estado_final_build(verif, InformeBuild('fallida')), 'fallida')

if __name__ == "__main__":
    sys.exit(main())
