"""
Pipeline /construir v7: tests primero + torneo + escalada + lecciones.

    PEDIDO
      ↓
    Exploradores (en paralelo, solo lectura) → informe del código real
      ↓
    Arquitecto → plan con INTERFAZ (firmas exactas), tareas y criterios
      ↓
    confirmación del usuario (puede pedir cambios al plan)
      ↓
    Especificador (QA ANTES de implementar) → tests que todavía fallan:
      la especificación ejecutable. Quedan protegidos durante la build.
      ↓
    por cada tarea:
      ⚔ TORNEO: N implementadores en copias aisladas (temperaturas distintas)
         → se corren los tests en cada copia → gana el que pasa más tests
         → solo el cambio ganador se aplica al proyecto real
      → verificación de la tarea (validadores + que no se rompa nada que andaba)
      → si falla: reparador con el error real; si vuelve a fallar → ⇪ ESCALADA:
        un modelo más fuerte diagnostica y el reparador aplica
      → revisor (opcional) sobre el diff real
      ↓
    verificación final: validadores + suite completa
      ↓ ¿falló?
    Reparador (diagnóstico real) → re-verificar (con escalada si se repite)
      ↓
    Lecciones: cada reparación que funcionó deja una lección de una línea
      ↓
    BUILD VERIFICADA → snapshot en la rama git reaper/builds
"""

_RE_TAREA = re.compile(r"<\s*(tarea|task)\b([^>]*)>(.*?)<\s*/\s*\1\s*>", re.S | re.I)
_RE_ATTR = re.compile(r"(\w+)\s*=\s*[\"']([^\"']*)[\"']")
_RE_OBJETIVO = re.compile(r"<\s*objetivo\s*>(.*?)<\s*/\s*objetivo\s*>", re.S | re.I)
_RE_CRITERIOS = re.compile(r"<\s*criterios\s*>(.*?)<\s*/\s*criterios\s*>", re.S | re.I)
_RE_INTERFAZ = re.compile(r"<\s*interfaz\s*>(.*?)<\s*/\s*interfaz\s*>", re.S | re.I)
_RE_VEREDICTO = re.compile(r"VEREDICTO\s*:?\s*\**\s*(APROBADO|CAMBIOS|RECHAZADO)", re.I)

EXTENSIONES_TESTEABLES = (".py", ".js", ".mjs", ".cjs", ".ts")


@dataclass
class Tarea:
    id: str
    descripcion: str
    archivos: list = field(default_factory=list)


@dataclass
class Plan:
    objetivo: str
    tareas: list
    criterios: list
    texto: str = ""
    interfaz: str = ""

    def como_texto(self, actual: Optional[int] = None, hechas: int = 0) -> str:
        lineas = [f"Objetivo: {self.objetivo}"]
        if self.interfaz:
            lineas.append("Interfaz:")
            lineas.extend(f"  {l.strip()}" for l in self.interfaz.strip().splitlines() if l.strip())
        for i, t in enumerate(self.tareas):
            marca = "✓" if i < hechas else ("▸" if i == actual else " ")
            archivos = f" [{', '.join(t.archivos)}]" if t.archivos else ""
            lineas.append(f"[{marca}] {t.id}. {recortar(t.descripcion, 400)}{archivos}")
        if self.criterios:
            lineas.append("Criterios de aceptación:")
            lineas.extend(f"- {c}" for c in self.criterios)
        return "\n".join(lineas)

    def archivos(self) -> list[str]:
        vistos: dict[str, None] = {}
        for t in self.tareas:
            for a in t.archivos:
                vistos.setdefault(a, None)
        for m in re.finditer(r"([\w./-]+\.(?:py|js|mjs|cjs|ts|tsx|html|css|sh|go|rs))", self.interfaz):
            vistos.setdefault(m.group(1), None)
        return list(vistos)


def parsear_plan(texto: str, pedido: str, max_tareas: int = 8) -> Plan:
    texto = texto or ""
    m = _RE_OBJETIVO.search(texto)
    objetivo = m.group(1).strip() if m else recortar(pedido.strip().splitlines()[0] if pedido.strip() else "", 200)

    tareas: list[Tarea] = []
    for m in _RE_TAREA.finditer(texto):
        attrs = {k.lower(): v for k, v in _RE_ATTR.findall(m.group(2))}
        lista = attrs.get("archivos") or attrs.get("files") or ""
        archivos = [a.strip() for a in re.split(r"[,;\s]+", lista) if a.strip()]
        descripcion = m.group(3).strip()
        if descripcion:
            tareas.append(Tarea(attrs.get("id") or str(len(tareas) + 1), descripcion, archivos))

    if not tareas:
        sin_criterios = _RE_INTERFAZ.sub("", _RE_CRITERIOS.sub("", texto))
        for linea in sin_criterios.splitlines():
            m = re.match(r"^\s*(?:tarea\s*)?(\d+)[.):-]\s+(.{8,})$", linea, re.I)
            if m:
                tareas.append(Tarea(m.group(1), m.group(2).strip(), []))
    if not tareas:
        tareas = [Tarea("1", pedido.strip(), [])]

    if len(tareas) > max_tareas:
        sobrantes = tareas[max_tareas - 1:]
        tareas = tareas[: max_tareas - 1] + [Tarea(
            sobrantes[0].id,
            "\n".join(f"- {t.descripcion}" for t in sobrantes),
            sorted({a for t in sobrantes for a in t.archivos}),
        )]

    criterios = []
    m = _RE_CRITERIOS.search(texto)
    if m:
        for linea in m.group(1).splitlines():
            linea = re.sub(r"^\s*([-*•]|\d+[.)])\s*", "", linea).strip()
            if linea:
                criterios.append(linea)
    m = _RE_INTERFAZ.search(texto)
    interfaz = m.group(1).strip() if m else ""
    return Plan(objetivo, tareas, criterios, texto, interfaz)


def veredicto(informe: str) -> tuple[bool, bool]:
    """(aprobado, claro). Si el revisor no respeta el formato se aprueba para no entrar en bucles."""
    m = _RE_VEREDICTO.search(informe or "")
    if not m:
        return True, False
    return m.group(1).upper() == "APROBADO", True


@dataclass
class Verificacion:
    ok: bool
    validaciones: list
    tests: Optional[Resultado]
    diagnostico: str
    archivos: list
    conteo: ConteoTests = field(default_factory=ConteoTests)


@dataclass
class InformeBuild:
    estado: str
    plan: Optional[Plan] = None
    archivos: list = field(default_factory=list)
    tests: Optional[Resultado] = None
    diagnostico: str = ""
    cid: Optional[int] = None
    ruta_informe: Optional[Path] = None
    notas: list = field(default_factory=list)
    lecciones: list = field(default_factory=list)
    escaladas: int = 0
    torneos: list = field(default_factory=list)
    commit: Optional[str] = None
    spec_tests: list = field(default_factory=list)
    segundos: float = 0.0

    @property
    def ok(self) -> bool:
        return self.estado in ("verificada", "validada")


def _diffstat(diff: str) -> str:
    stats: dict[str, list[int]] = {}
    actual = None
    for linea in diff.splitlines():
        if linea.startswith("+++ b/"):
            actual = linea[6:]
            stats.setdefault(actual, [0, 0])
        elif actual and linea.startswith("+") and not linea.startswith("+++"):
            stats[actual][0] += 1
        elif actual and linea.startswith("-") and not linea.startswith("---"):
            stats[actual][1] += 1
    return "\n".join(f"  {a}  +{m} -{n}" for a, (m, n) in stats.items())


def _es_test(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, p) for p in PATRONES_TESTS)


def _es_de_especificacion(nombre_test: str, protegidos: dict) -> bool:
    """¿El test que falla pertenece a un archivo de la especificación? (pytest usa ruta::test, unittest modulo.Clase.test)"""
    for rel in protegidos:
        ruta = Path(rel)
        modulo = ".".join(ruta.with_suffix("").parts)
        if rel in nombre_test or nombre_test.startswith(modulo + ".") or f".{ruta.stem}." in f".{nombre_test}." \
                or nombre_test.startswith(ruta.stem + "."):
            return True
    return False


class Orquestador:
    def __init__(self, llm, ws: Workspace, settings: Settings, ui: UI):
        self.llm = llm
        self.ws = ws
        self.settings = settings
        self.ui = ui
        self.memoria = MemoriaLecciones(ws) if settings.lecciones else None
        self.escalador = Escalador(llm, settings, ui)
        self._protegidos: dict[str, Optional[str]] = {}

    def _sub(self, rol: str, tarea: str, cid: Optional[int], archivos: str = "", titulo: str = "",
             **opciones) -> ResultadoAgente:
        opciones.setdefault("memoria", self.memoria)
        return ejecutar_subagentes(
            [(rol, tarea, archivos, titulo, opciones)], self.llm, self.ws, self.settings, self.ui,
            profundidad=1, cid_inicio=cid,
        )[0]

    # ------------------------------------------------------------ fases
    def explorar(self, pedido: str) -> str:
        archivos = self.ws.archivos_codigo(limite=500)
        if not archivos:
            return "El workspace está vacío: hay que crear todo desde cero."
        mapa = mapa_relevante(self.ws, pedido, self.settings.max_relevantes) if self.settings.mapa_relevantes else ""
        if len(archivos) <= 6:
            # Proyecto chico: un mapa directo sale gratis y no gasta llamadas al modelo.
            partes = ["Proyecto chico; mapa completo:"]
            for rel in archivos:
                simbolos = outline(self.ws.raiz / rel)
                partes.append(rel + ("\n" + "\n".join("  " + s for s in simbolos[:30]) if simbolos else ""))
            return "\n".join(partes)

        specs = [(
            "explorador",
            f"PEDIDO DEL USUARIO:\n{pedido}\n\nInvestigá qué partes del código tocan este pedido: archivos, "
            "funciones y clases involucradas, cómo se conectan y qué convenciones hay que respetar.",
            "",
            "código relacionado con el pedido",
            {"memoria": self.memoria},
        )]
        if len(archivos) > 15 and self.settings.paralelo > 1:
            specs.append((
                "explorador",
                f"PEDIDO DEL USUARIO:\n{pedido}\n\nNO analices la lógica del pedido. Investigá cómo se ejecuta y "
                "cómo se prueba este proyecto: puntos de entrada, dependencias, tests existentes y su comando, "
                "estructura de carpetas y configuración.",
                "",
                "cómo se ejecuta y se prueba el proyecto",
                {"memoria": self.memoria},
            ))
        resultados = ejecutar_subagentes(specs, self.llm, self.ws, self.settings, self.ui, profundidad=1)
        informe = "\n\n".join(
            f"### Informe explorador {i}\n{r.resumen}" for i, r in enumerate(resultados, start=1)
        )
        return (mapa + "\n\n" + informe) if mapa else informe

    def planificar(self, pedido: str, exploracion: str, feedback: str = "", anterior: Optional[Plan] = None) -> Plan:
        detectado = detectar_comando_tests(self.ws)
        tarea = (
            f"PEDIDO DEL USUARIO:\n{pedido}\n\n"
            f"INFORME DE EXPLORACIÓN (código real):\n{recortar(exploracion, 7000)}\n\n"
            f"Comando de tests detectado: {detectado[0] if detectado else 'ninguno (habrá que crear tests)'}\n"
            f"Armá el plan con un máximo de {self.settings.max_tareas} tareas."
        )
        if self.settings.tests_primero:
            tarea += ("\nLos tests se escriben ANTES de implementar a partir de tu <interfaz> y tus <criterios>: "
                      "que sean precisos (rutas, nombres, firmas, valores esperados).")
        if anterior and feedback:
            tarea += (
                f"\n\nPLAN ANTERIOR:\n{anterior.como_texto()}\n\n"
                f"EL USUARIO PIDIÓ ESTOS CAMBIOS AL PLAN:\n{feedback}"
            )
        res = self._sub("arquitecto", tarea, None, titulo="diseña el plan de tareas")
        texto = res.resumen
        if not _RE_TAREA.search(texto) and _RE_TAREA.search(res.contexto):
            texto = res.contexto + "\n" + texto
        plan = parsear_plan(texto, pedido, self.settings.max_tareas)
        if not res.ok:
            self.ui.aviso("El arquitecto no terminó limpio; uso lo que produjo.")
        return plan

    def especificar(self, pedido: str, plan: Plan, cid: int) -> dict[str, Optional[str]]:
        """Tests primero: el especificador escribe la especificación ejecutable. Devuelve {rel: contenido}."""
        detectado = detectar_comando_tests(self.ws)
        criterios = "\n".join(f"- {c}" for c in plan.criterios) or "- (derivalos del pedido y la interfaz)"
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"PLAN:\n{plan.como_texto()}\n\n"
            f"INTERFAZ QUE TUS TESTS DEBEN USAR:\n{plan.interfaz or '(no hay interfaz explícita: usá las firmas de las tareas)'}\n\n"
            f"CRITERIOS DE ACEPTACIÓN:\n{criterios}\n\n"
            f"Comando de tests detectado: {detectado[0] if detectado else 'ninguno todavía (creá la carpeta tests/)'}\n\n"
            "Escribí los tests de aceptación AHORA, antes de que exista la implementación. Tienen que fallar por "
            "falta de implementación (ImportError/AttributeError/assert) y pasar cuando el plan esté hecho."
        )
        res = self._sub("especificador", texto, cid, titulo="escribe los tests ANTES de implementar")
        tests = [r for r in res.cambios if _es_test(r) and (self.ws.raiz / r).is_file()]
        if not tests:
            self.ui.aviso("  El especificador no dejó archivos de test: sigo sin especificación ejecutable.")
            return {}
        validacion = validar_archivos(self.ws, tests)
        rotos = [r for r in fallos(validacion) if r.comando.startswith(("py_compile", "node --check"))]
        if rotos:
            self.ui.aviso("  Los tests de la especificación tienen errores de sintaxis: le pido al especificador que los arregle.")
            self._sub("especificador", "Los tests que escribiste no compilan:\n" + resumen_validacion(validacion, 2500)
                      + "\nCorregí SOLO los errores de sintaxis de los tests.", cid, titulo="corrige los tests")
            if fallos([r for r in validar_archivos(self.ws, tests) if r.comando.startswith(("py_compile", "node --check"))]):
                self.ui.aviso("  Siguen sin compilar: descarto la especificación para no bloquear la build.")
                return {}
        r = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        conteo = conteo_de_resultado(r)
        if r is not None and conteo.reconocido:
            if conteo.ok and conteo.pasados:
                self.ui.aviso(f"  Ojo: la especificación ya pasa entera ({conteo.texto()}); quizá la función ya existía.")
            else:
                self.ui.ok(f"especificación lista: {len(tests)} archivo(s) de test, {conteo.texto()} (esperado: fallan)")
        else:
            self.ui.ok(f"especificación lista: {len(tests)} archivo(s) de test")
        return copiar_contenidos(self.ws, tests)

    def _texto_tarea(self, pedido: str, plan: Plan, indice: int, exploracion: str,
                     protegidos: dict[str, Optional[str]], correcciones: str = "") -> str:
        tarea = plan.tareas[indice]
        texto = (
            f"PEDIDO ORIGINAL DEL USUARIO:\n{pedido}\n\n"
            f"PLAN GENERAL:\n{plan.como_texto(actual=indice, hechas=indice)}\n\n"
            f"TU TAREA AHORA (#{tarea.id}):\n{tarea.descripcion}\n\n"
            f"CONTEXTO DE EXPLORACIÓN:\n{recortar(exploracion, 3500)}\n\n"
            "Implementá SOLO esta tarea (las demás las hacen otros). Leé antes de editar."
        )
        if protegidos:
            texto += ("\n\nTESTS DE ESPECIFICACIÓN (escritos antes de implementar; NO los modifiques, hacé que pasen "
                      "los que corresponden a tu tarea): " + ", ".join(protegidos))
        if correcciones:
            texto += (
                "\n\nUN REVISOR YA REVISÓ TU TRABAJO EN ESTA TAREA Y PIDIÓ CAMBIOS. Aplicalos (si alguno es "
                f"incorrecto, explicá por qué en el informe):\n{recortar(correcciones, 4000)}"
            )
        return texto

    def implementar(self, pedido: str, plan: Plan, indice: int, exploracion: str,
                    cid: int, correcciones: str = "", protegidos: Optional[dict] = None) -> ResultadoTorneo:
        protegidos = protegidos or {}
        tarea = plan.tareas[indice]
        texto = self._texto_tarea(pedido, plan, indice, exploracion, protegidos, correcciones)
        titulo = f"tarea {tarea.id}: {recortar(tarea.descripcion.splitlines()[0], 90)}"
        if correcciones:
            titulo = f"corrige tarea {tarea.id} según el revisor"
        usar_torneo = self.settings.torneo and self.settings.candidatos > 1 and not correcciones
        torneo = Torneo(self.llm, self.ws, self.settings, self.ui, memoria=self.memoria,
                        on_atascado=self.escalador.gancho(self.ws, texto))
        return torneo.correr(texto, archivos=", ".join(tarea.archivos), titulo=titulo,
                             n=self.settings.candidatos if usar_torneo else 1, protegidos=protegidos, cid=cid)

    def revisar(self, pedido: str, tarea: Tarea, diff: str, cid: int) -> tuple[bool, str]:
        rels = self.ws.checkpoints.archivos_desde(cid)
        validacion = resumen_validacion(validar_archivos(self.ws, rels), limite=1500)
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"TAREA REVISADA (#{tarea.id}):\n{tarea.descripcion}\n\n"
            f"DIFF REAL DE LOS CAMBIOS:\n```diff\n{recortar(diff, 12000)}\n```\n\n"
            f"Validación automática de los archivos cambiados: {validacion}\n\n"
            "Leé los archivos completos si necesitás contexto. Empezá tu informe con la línea VEREDICTO."
        )
        res = self._sub("revisor", texto, cid, titulo=f"revisa el diff de la tarea {tarea.id}")
        aprobado, claro = veredicto(res.resumen)
        if not claro:
            self.ui.tenue("  (el revisor no usó el formato VEREDICTO: se toma como aprobado)")
        return aprobado, res.resumen

    def qa(self, pedido: str, plan: Plan, archivos: list, cid: int) -> ResultadoAgente:
        detectado = detectar_comando_tests(self.ws)
        criterios = "\n".join(f"- {c}" for c in plan.criterios) or "- (derivalos del pedido)"
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"CRITERIOS DE ACEPTACIÓN:\n{criterios}\n\n"
            f"ARCHIVOS CAMBIADOS EN ESTA BUILD: {', '.join(archivos)}\n"
            f"Comando de tests detectado: {detectado[0] if detectado else 'ninguno todavía'}\n\n"
            "Escribí (o completá) tests automáticos que verifiquen los criterios y corrélos con run_tests. "
            "Reportá el resultado REAL."
        )
        return self._sub("qa", texto, cid, titulo="escribe y corre tests de aceptación")

    def verificar(self, cid: int) -> Verificacion:
        archivos = [r for r in self.ws.checkpoints.archivos_desde(cid) if (self.ws.raiz / r).is_file()]
        validaciones = validar_archivos(self.ws, archivos)
        tests = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        conteo = conteo_de_resultado(tests)
        malos = fallos(validaciones)
        tests_ok = tests is None or tests.ok
        partes = [r.resumen(2500) for r in malos]
        if tests is not None and not tests.ok:
            partes.append("TESTS: " + conteo.texto() + "\n" + fallos_relevantes(f"{tests.stdout}\n{tests.stderr}",
                                                                                maximo=3, limite=5000))
        diagnostico = "\n\n".join(partes)
        if diagnostico and self.settings.pistas_errores:
            diagnostico = anexar_pistas(diagnostico, 3)
        return Verificacion(not malos and tests_ok, validaciones, tests, diagnostico, archivos, conteo)

    def reparar(self, pedido: str, verif: Verificacion, cid: int, base_fallaba: bool,
                diagnostico_experto: str = "", contexto: str = "") -> ResultadoAgente:
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"Hay fallos REALES. Diagnóstico de validadores/tests:\n{verif.diagnostico}\n\n"
            f"Archivos cambiados en esta build: {', '.join(verif.archivos)}\n"
        )
        if contexto:
            texto += f"\n{contexto}\n"
        if base_fallaba:
            texto += "Ojo: la suite de tests ya fallaba ANTES de esta build; priorizá los fallos causados por los cambios.\n"
        texto += "Encontrá la causa raíz y corregila. No debilites ni borres tests."
        if diagnostico_experto:
            texto = tarea_con_diagnostico(texto, diagnostico_experto)
        protegidos = set(self._protegidos)
        return self._sub("reparador", texto, cid, titulo="arregla los fallos reales" + (" (con diagnóstico experto)"
                                                                                    if diagnostico_experto else ""),
                         protegidos=protegidos)

    # ------------------------------------------------------------ lecciones
    def _aprender(self, diagnostico: str, cid: int, informe_reparador: str, build: InformeBuild) -> None:
        if not self.memoria or not self.settings.lecciones:
            return
        diff = self.ws.checkpoints.diff_desde(cid)
        if not diff.strip():
            return
        proyecto, general = extraer_lecciones(self.llm, self.settings.modelo_para("reparador"), diagnostico, diff,
                                              informe_reparador, self.ws)
        hechos = self.memoria.registrar(proyecto, general)
        for h in hechos:
            self.ui.linea(f"  {Tema.acento}📚 lección{C.RESET} {Tema.tenue}{h}{C.RESET}")
        build.lecciones.extend(hechos)

    def _reparar_con_escalada(self, pedido: str, verif: Verificacion, grupo: int, base_fallaba: bool,
                              informe: InformeBuild, etiqueta: str, max_intentos: int,
                              verificador: Callable[[], Verificacion], contexto: str = "") -> Verificacion:
        """Bucle de reparación: reparador → re-verificar; al repetirse el fallo, escala al modelo fuerte."""
        diagnosticos_vistos: list[str] = []
        fallos_seguidos = 0
        intento = 0
        intentos_txt: list[str] = []
        while not verif.ok and intento < max_intentos:
            firma = _firma_error(verif.diagnostico)
            if diagnosticos_vistos.count(firma) >= 3:
                informe.notas.append(f"{etiqueta}: la reparación no logró avances (mismo diagnóstico repetido).")
                break
            diagnosticos_vistos.append(firma)
            intento += 1
            experto = ""
            if fallos_seguidos >= self.settings.umbral_escalada and self.escalador.disponible():
                experto = self.escalador.diagnosticar(self.ws, pedido, verif.diagnostico, verif.archivos,
                                                      "\n---\n".join(intentos_txt[-2:])) or ""
                if experto:
                    informe.escaladas += 1
                    fallos_seguidos = 0
            self.ui.titulo(f"REPARACIÓN {etiqueta} {intento}/{max_intentos}" + (" · con experto" if experto else ""))
            rcid = self.ws.checkpoints.iniciar(f"reparación {etiqueta} {intento}", grupo=grupo)
            antes = verif
            res = self.reparar(pedido, verif, rcid, base_fallaba, experto, contexto)
            intentos_txt.append(recortar(res.resumen, 1200))
            verif = verificador()
            self._mostrar_verificacion(verif)
            if verif.ok:
                self._aprender(antes.diagnostico, rcid, res.resumen, informe)
            else:
                fallos_seguidos += 1
        return verif

    # ------------------------------------------------------------ flujos
    def _mostrar_plan(self, plan: Plan) -> None:
        self.ui.titulo("PLAN")
        self.ui.linea(plan.como_texto())

    def obtener_plan(self, pedido: str, confirmar: bool) -> tuple[Optional[Plan], str]:
        self.ui.fase(1, "Exploración")
        exploracion = self.explorar(pedido)
        self.ui.fase(2, "Arquitectura")
        plan = self.planificar(pedido, exploracion)
        for _ in range(3):
            self._mostrar_plan(plan)
            if not confirmar or self.ui.confirmar("¿Aprobás el plan y arrancamos?", defecto=True):
                return plan, exploracion
            feedback = self.ui.preguntar("¿Qué cambiarías del plan? (Enter vacío = cancelar)")
            if not feedback:
                return None, exploracion
            plan = self.planificar(pedido, exploracion, feedback, plan)
        return None, exploracion

    def solo_plan(self, pedido: str) -> Optional[Path]:
        plan, exploracion = self.obtener_plan(pedido, confirmar=False)
        if plan is None:
            return None
        carpeta = self.ws.raiz / ".reaper" / "planes"
        ruta = carpeta / f"plan_{datetime.now():%Y%m%d_%H%M%S}.md"
        escritura_atomica(ruta, (
            f"# Plan REAPER\n\n## Pedido\n{pedido}\n\n## Plan\n```\n{plan.como_texto()}\n```\n\n"
            f"## Exploración\n{exploracion}\n\n## Respuesta del arquitecto\n{plan.texto}\n"
        ))
        return ruta

    def _verificar_tarea(self, tcid: int, antes: ConteoTests, nombres_antes: set) -> Verificacion:
        """
        Una tarea intermedia no necesita que pasen TODOS los tests (los de tareas
        siguientes todavía fallan): alcanza con validadores OK y que no se rompa
        nada que antes pasaba.
        """
        archivos = [r for r in self.ws.checkpoints.archivos_desde(tcid) if (self.ws.raiz / r).is_file()]
        validaciones = validar_archivos(self.ws, archivos)
        tests = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        conteo = conteo_de_resultado(tests)
        problemas = [r.resumen(2500) for r in fallos(validaciones)]
        if tests is not None and not tests.ok and conteo.reconocido:
            # Los tests de la especificación de tareas siguientes fallan a propósito: no son regresión.
            nuevos_fallos = [n for n in conteo.nombres_fallados
                             if n not in nombres_antes and not _es_de_especificacion(n, self._protegidos)]
            retroceso = conteo.pasados < antes.pasados
            mas_errores = conteo.errores > antes.errores
            if retroceso or mas_errores or nuevos_fallos:
                detalle = f"antes {antes.texto()}, ahora {conteo.texto()}"
                if nuevos_fallos:
                    detalle += "; fallan tests que antes no fallaban: " + ", ".join(nuevos_fallos[:8])
                problemas.append(
                    f"REGRESIÓN DE TESTS: {detalle}.\n"
                    + fallos_relevantes(f"{tests.stdout}\n{tests.stderr}", maximo=3, limite=4000)
                )
        elif tests is not None and not tests.ok and not conteo.reconocido and antes.ok:
            problemas.append("TESTS: la suite pasaba antes de la tarea y ahora falla.\n" + tests.resumen(4000))
        diagnostico = "\n\n".join(problemas)
        if diagnostico and self.settings.pistas_errores:
            diagnostico = anexar_pistas(diagnostico, 2)
        return Verificacion(not problemas, validaciones, tests, diagnostico, archivos, conteo)

    def construir(self, pedido: str, confirmar: bool = True) -> InformeBuild:
        inicio = time.monotonic()
        self._protegidos: dict[str, Optional[str]] = {}
        base = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        base_fallaba = base is not None and not base.ok
        if base_fallaba:
            self.ui.aviso("Atención: la suite de tests YA falla antes de empezar; se tendrá en cuenta.")

        plan, exploracion = self.obtener_plan(pedido, confirmar)
        if plan is None:
            self.ui.tenue("Construcción cancelada; no se tocó ningún archivo.")
            return InformeBuild("cancelada")

        grupo = self.ws.checkpoints.iniciar(f"construir: {pedido[:80]}")
        informe = InformeBuild("fallida", plan=plan, cid=grupo)

        testeable = any(a.endswith(EXTENSIONES_TESTEABLES) for a in plan.archivos()) or any(
            a.endswith(EXTENSIONES_TESTEABLES) for a in self.ws.archivos_codigo(limite=200)) or not self.ws.archivos_codigo(limite=5)
        numero_fase = 3
        if self.settings.tests_primero and testeable:
            self.ui.fase(numero_fase, "Tests primero (especificación ejecutable)")
            numero_fase += 1
            self._protegidos = self.especificar(pedido, plan, grupo)
            informe.spec_tests = list(self._protegidos)

        self.ui.fase(numero_fase, "Implementación" + (" · torneo" if self.settings.torneo and self.settings.candidatos > 1 else ""))
        numero_fase += 1
        for i, tarea in enumerate(plan.tareas):
            self.ui.info(f"\n▸ Tarea {i + 1}/{len(plan.tareas)}: {recortar(tarea.descripcion.splitlines()[0], 120)}")
            antes_tests = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
            conteo_antes = conteo_de_resultado(antes_tests)
            nombres_antes = set(conteo_antes.nombres_fallados)
            tcid = self.ws.checkpoints.iniciar(f"tarea {tarea.id}", grupo=grupo)
            resultado = self.implementar(pedido, plan, i, exploracion, tcid, protegidos=self._protegidos)
            informe.torneos.append((tarea.id, resultado.modo, resultado.ganador.indice if resultado.ganador else None))
            if not resultado.ok:
                informe.notas.append(f"Tarea {tarea.id}: la implementación no terminó limpia.")

            verif_tarea = self._verificar_tarea(tcid, conteo_antes, nombres_antes)
            if not verif_tarea.ok:
                self.ui.aviso(f"  La tarea {tarea.id} no pasó su verificación: la reparo con el error real.")
                verif_tarea = self._reparar_con_escalada(
                    pedido, verif_tarea, grupo, base_fallaba, informe, f"tarea {tarea.id}",
                    max(1, self.settings.umbral_escalada + 1),
                    lambda: self._verificar_tarea(tcid, conteo_antes, nombres_antes),
                    contexto=f"TAREA EN CURSO (#{tarea.id}): {tarea.descripcion}",
                )
                if not verif_tarea.ok:
                    informe.notas.append(f"Tarea {tarea.id}: quedó con fallos de verificación.")

            for ronda in range(self.settings.max_revisiones):
                diff = self.ws.checkpoints.diff_desde(tcid)
                if not diff.strip():
                    informe.notas.append(f"Tarea {tarea.id}: sin cambios en archivos.")
                    break
                aprobado, revision = self.revisar(pedido, tarea, diff, tcid)
                if aprobado:
                    self.ui.ok(f"Revisor aprobó la tarea {tarea.id}")
                    break
                self.ui.aviso(f"  Revisor pidió cambios en la tarea {tarea.id} (ronda {ronda + 1})")
                if ronda + 1 >= self.settings.max_revisiones:
                    informe.notas.append(f"Tarea {tarea.id}: quedaron observaciones del revisor sin resolver.")
                    break
                self.implementar(pedido, plan, i, exploracion, tcid, correcciones=revision,
                                 protegidos=self._protegidos)

        archivos = [r for r in self.ws.checkpoints.archivos_desde(grupo) if (self.ws.raiz / r).is_file()]
        hay_tests_build = any(_es_test(a) for a in archivos)
        if self.settings.qa and testeable and not (self._protegidos or hay_tests_build):
            self.ui.fase(numero_fase, "QA (tests reales)")
            numero_fase += 1
            qcid = self.ws.checkpoints.iniciar("qa", grupo=grupo)
            self.qa(pedido, plan, archivos, qcid)

        self.ui.fase(numero_fase, "Verificación real")
        verif = self.verificar(grupo)
        self._mostrar_verificacion(verif)
        verif = self._reparar_con_escalada(pedido, verif, grupo, base_fallaba, informe, "final",
                                           self.settings.max_reparaciones, lambda: self.verificar(grupo))

        informe.archivos = verif.archivos
        informe.tests = verif.tests
        informe.diagnostico = verif.diagnostico
        if verif.ok:
            informe.estado = "verificada" if verif.tests is not None and not verif.tests.omitido else "validada"
            if self.settings.git_snapshots and es_repo_git(self.ws):
                try:
                    informe.commit = snapshot_build(self.ws, self.settings.rama_git,
                                                    f"REAPER build verificada: {pedido[:72]}\n\n{plan.objetivo}")
                except RuntimeError as e:
                    informe.notas.append(f"No pude guardar la build en git: {e}")
        informe.segundos = time.monotonic() - inicio
        informe.ruta_informe = self._guardar_informe(pedido, informe)
        self._mostrar_cierre(informe)
        return informe

    # ------------------------------------------------------------ salida
    def _mostrar_verificacion(self, verif: Verificacion) -> None:
        for r in verif.validaciones:
            if not r.ok:
                self.ui.error(r.linea()[2:])
        malos = len(fallos(verif.validaciones))
        self.ui.linea(f"  validadores: {len(verif.validaciones) - malos}/{len(verif.validaciones)} OK")
        if verif.tests is None:
            self.ui.aviso("  tests: no hay suite detectada")
        elif verif.tests.omitido:
            self.ui.aviso("  tests: la suite no encontró tests")
        elif verif.tests.ok:
            self.ui.ok(f"tests: pasaron ({verif.conteo.texto() if verif.conteo.reconocido else verif.tests.comando})")
        else:
            self.ui.error(f"tests: fallaron ({verif.conteo.texto() if verif.conteo.reconocido else verif.tests.comando})")
            self.ui.tenue(recortar(fallos_relevantes(verif.tests.stdout + "\n" + verif.tests.stderr, 2, 1500), 1500))

    def _guardar_informe(self, pedido: str, informe: InformeBuild) -> Optional[Path]:
        try:
            diff = self.ws.checkpoints.diff_desde(informe.cid) if informe.cid else ""
            tests = informe.tests.resumen(4000) if informe.tests else "sin suite de tests"
            contenido = (
                f"# Build REAPER — {informe.estado.upper()}\n\n"
                f"Fecha: {datetime.now():%Y-%m-%d %H:%M} · duración: {formatear_duracion(informe.segundos)}\n\n"
                f"## Pedido\n{pedido}\n\n"
                f"## Plan\n```\n{informe.plan.como_texto() if informe.plan else '-'}\n```\n\n"
                f"## Archivos\n```\n{_diffstat(diff) or '-'}\n```\n\n"
                f"## Tests\n```\n{tests}\n```\n\n"
                + (f"## Especificación (tests escritos antes de implementar)\n" + "\n".join(f"- {t}" for t in informe.spec_tests) + "\n\n"
                   if informe.spec_tests else "")
                + (f"## Escaladas al modelo fuerte\n{informe.escaladas}\n\n" if informe.escaladas else "")
                + ("## Lecciones aprendidas\n" + "\n".join(f"- {l}" for l in informe.lecciones) + "\n\n" if informe.lecciones else "")
                + (f"## Commit\n`{informe.commit}` en la rama {self.settings.rama_git}\n\n" if informe.commit else "")
                + (f"## Diagnóstico pendiente\n```\n{informe.diagnostico}\n```\n\n" if informe.diagnostico else "")
                + ("## Notas\n" + "\n".join(f"- {n}" for n in informe.notas) + "\n" if informe.notas else "")
            )
            ruta = self.ws.raiz / ".reaper" / "informes" / f"build_{datetime.now():%Y%m%d_%H%M%S}.md"
            escritura_atomica(ruta, contenido)
            return ruta
        except OSError as e:
            self.ui.aviso(f"No pude guardar el informe: {e}")
            return None

    def _mostrar_cierre(self, informe: InformeBuild) -> None:
        if informe.estado == "verificada":
            self.ui.titulo("✓ BUILD VERIFICADA (validadores + tests reales)")
        elif informe.estado == "validada":
            self.ui.titulo("✓ BUILD VALIDADA (validadores OK, sin tests que correr)")
        else:
            self.ui.titulo("✗ BUILD FALLIDA")
        diff = self.ws.checkpoints.diff_desde(informe.cid) if informe.cid else ""
        if diff:
            self.ui.linea(_diffstat(diff))
        datos = [f"duración {formatear_duracion(informe.segundos)}"]
        if informe.spec_tests:
            datos.append(f"{len(informe.spec_tests)} archivo(s) de tests previos")
        torneos = sum(1 for _, modo, _g in informe.torneos if modo == "torneo")
        if torneos:
            datos.append(f"{torneos} torneo(s)")
        if informe.escaladas:
            datos.append(f"{informe.escaladas} escalada(s)")
        if informe.lecciones:
            datos.append(f"{len(informe.lecciones)} lección(es)")
        self.ui.tenue("  " + " · ".join(datos))
        if informe.commit:
            self.ui.ok(f"guardada en git: {informe.commit[:10]} (rama {self.settings.rama_git})")
        for nota in informe.notas:
            self.ui.aviso(f"  • {nota}")
        if informe.ruta_informe:
            self.ui.tenue(f"  informe: {informe.ruta_informe}")
        self.ui.tenue("  /diff para ver los cambios · /deshacer revierte TODA la build\n")

    def revisar_proyecto(self, foco: str = "") -> str:
        archivos = [a for a in self.ws.archivos_codigo(limite=400)
                    if a.endswith((".py", ".js", ".mjs", ".ts", ".sh", ".html", ".css"))]
        if not archivos:
            return "No hay archivos de código para revisar."
        grupos = max(1, min(self.settings.paralelo, (len(archivos) + 11) // 12))
        lotes = [archivos[i::grupos] for i in range(grupos)]
        specs = []
        for lote in lotes:
            specs.append((
                "revisor",
                "Revisión general del proyecto (no hay diff). Revisá estos archivos buscando bugs reales, "
                "errores de manejo de excepciones, problemas de compatibilidad con Termux y riesgos de seguridad. "
                + (f"Foco pedido por el usuario: {foco}. " if foco else "")
                + "Empezá con VEREDICTO (APROBADO si no hay problemas graves) y después: hallazgos confirmados "
                "(archivo:línea), riesgos probables marcados como inferidos y qué arreglar primero.\n\n"
                f"Archivos asignados: {', '.join(lote)}",
                "",
                f"revisa {len(lote)} archivos",
            ))
        resultados = ejecutar_subagentes(specs, self.llm, self.ws, self.settings, self.ui, profundidad=1)
        return "\n\n".join(f"### Revisor {i}\n{r.resumen}" for i, r in enumerate(resultados, start=1))
