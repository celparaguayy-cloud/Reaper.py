"""
Torneo de implementadores: varios intentos compiten y gana el que pasa más tests reales.

Un modelo de 24B es irregular: el mismo pedido sale bien una vez y mal la
siguiente. En vez de confiar en un solo intento, REAPER lanza N
implementadores EN PARALELO, cada uno en una copia aislada del proyecto y con
temperatura distinta (0.1 / 0.4 / 0.7 por defecto). Después, en cada copia:

  1. restaura los tests de la especificación y los tests que ya existían
     (nadie gana debilitando o borrando tests)
  2. aparta los tests NUEVOS que agregó el candidato (nadie gana inflando el
     número con tests triviales) y corre la suite
  3. corre los validadores sobre los archivos que cambió

Gana el que pasa más tests; si empatan: validadores OK, menos tests fallando,
el agente terminó limpio y menos líneas cambiadas. Solo el cambio ganador se
aplica al proyecto real (con checkpoint, así /deshacer sigue funcionando).
"""


@dataclass
class Candidato:
    indice: int
    temperatura: float
    copia: Optional[Copia] = None
    resultado: Optional[ResultadoAgente] = None
    cambios: list = field(default_factory=list)
    validaciones: list = field(default_factory=list)
    tests: Optional[Resultado] = None
    conteo: ConteoTests = field(default_factory=ConteoTests)
    lineas: int = 0
    error: str = ""
    segundos: float = 0.0

    @property
    def validaciones_ok(self) -> bool:
        return not fallos(self.validaciones)

    def clave(self) -> tuple:
        """Menor es mejor (se usa con sorted)."""
        agente_ok = bool(self.resultado and self.resultado.ok)
        return (
            bool(self.error),                       # los que explotaron, al final
            -self.conteo.pasados,                   # más tests pasando
            0 if self.validaciones_ok else 1,       # validadores OK
            self.conteo.fallados + self.conteo.errores,
            0 if self.cambios else 1,               # hizo algo
            0 if agente_ok else 1,
            self.lineas,                            # menos líneas cambiadas
            self.temperatura,
        )

    def fila(self) -> list:
        estado = "error" if self.error else ("✓" if self.resultado and self.resultado.ok else "✗")
        tests = self.conteo.texto() if self.conteo.reconocido else ("sin suite" if self.tests is None else
                                                                    ("OK" if self.tests.ok else "falló"))
        return [f"#{self.indice + 1}", f"{self.temperatura:.1f}", estado, tests,
                "OK" if self.validaciones_ok else f"{len(fallos(self.validaciones))} fallos",
                str(len(self.cambios)), str(self.lineas), formatear_duracion(self.segundos)]


@dataclass
class ResultadoTorneo:
    ganador: Optional[Candidato]
    candidatos: list
    aplicados: list = field(default_factory=list)
    todos_pasan: bool = False
    modo: str = "torneo"  # torneo | simple
    notas: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ganador is not None and not self.ganador.error and self.ganador.validaciones_ok \
            and bool(self.aplicados or self.ganador.cambios)

    def informe(self) -> str:
        if not self.ganador:
            return "Ningún candidato produjo un resultado utilizable."
        g = self.ganador
        partes = [f"Ganó el candidato #{g.indice + 1} (temperatura {g.temperatura:.1f}): "
                  f"{g.conteo.texto() if g.conteo.reconocido else 'sin conteo de tests'}; "
                  f"validadores {'OK' if g.validaciones_ok else 'con fallos'}; {len(g.cambios)} archivo(s), "
                  f"{g.lineas} líneas cambiadas."]
        if g.resultado:
            partes.append("Informe del ganador:\n" + recortar(g.resultado.resumen, 2500))
        partes.extend(self.notas)
        return "\n".join(partes)


def _archivos_de_tests(ws: Workspace) -> list[str]:
    return [r for r in ws.archivos_codigo(limite=2000)
            if any(fnmatch.fnmatch(r, p) for p in PATRONES_TESTS)]


class Torneo:
    def __init__(self, llm, ws: Workspace, settings: Settings, ui: UI, *,
                 memoria: Optional[MemoriaLecciones] = None,
                 on_atascado: Optional[Callable[[str], Optional[str]]] = None):
        self.llm = llm
        self.ws = ws
        self.settings = settings
        self.ui = ui
        self.memoria = memoria
        self.on_atascado = on_atascado

    # ------------------------------------------------------------ evaluación
    def _evaluar(self, cand: Candidato, protegidos: dict[str, Optional[str]], existentes: dict[str, Optional[str]]) -> None:
        copia = cand.copia
        assert copia is not None and copia.ws is not None
        # 1) restaurar especificación y tests previos
        copia.forzar_contenidos({**existentes, **protegidos})
        cambios = copia.cambios()
        # 2) apartar tests nuevos del candidato mientras se puntúa
        nuevos_tests = {c.rel: c.despues for c in cambios
                        if c.tipo == "nuevo" and c.rel not in protegidos
                        and any(fnmatch.fnmatch(c.rel, p) for p in PATRONES_TESTS)}
        if nuevos_tests:
            copia.forzar_contenidos({rel: None for rel in nuevos_tests})
        try:
            cand.tests = ejecutar_tests(copia.ws, timeout=self.settings.tests_timeout, completo=True)
            cand.conteo = conteo_de_resultado(cand.tests)
        finally:
            if nuevos_tests:
                copia.forzar_contenidos(nuevos_tests)
        cand.cambios = [c for c in copia.cambios() if c.rel not in protegidos]
        rels = [c.rel for c in cand.cambios if c.tipo != "borrado"]
        cand.validaciones = validar_archivos(copia.ws, rels)
        cand.lineas = sum(c.lineas_cambiadas() for c in cand.cambios)

    def _correr_candidato(self, cand: Candidato, tarea: str, archivos: str, rol: str,
                          protegidos: dict[str, Optional[str]], existentes: dict[str, Optional[str]],
                          progreso: bool) -> Candidato:
        inicio = time.monotonic()
        assert cand.copia is not None and cand.copia.ws is not None
        etiqueta = f"impl{cand.indice + 1}·t{cand.temperatura:.1f}"
        agente = Agente(rol, self.llm, cand.copia.ws, self.settings, self.ui, profundidad=1,
                        etiqueta=etiqueta, mostrar_progreso=progreso, temperatura=cand.temperatura,
                        memoria=self.memoria, protegidos=set(protegidos), on_atascado=self.on_atascado)
        texto = tarea + (f"\n\nArchivos relevantes: {archivos}" if archivos else "") + SUFIJO_SUBTAREA
        try:
            cand.resultado = agente.ejecutar(texto, cid_inicio=cand.copia.ws.checkpoints.iniciar("candidato"))
        except (Cancelado, KeyboardInterrupt):
            raise
        except LLMError as e:
            cand.error = f"modelo: {e}"
        except Exception as e:  # un candidato roto no tumba el torneo
            cand.error = f"{type(e).__name__}: {e}"
        try:
            self._evaluar(cand, protegidos, existentes)
        except (OSError, ErrorSandbox) as e:
            cand.error = cand.error or f"evaluación: {e}"
        cand.segundos = time.monotonic() - inicio
        estado = "✗ error" if cand.error else f"{cand.conteo.texto() if cand.conteo.reconocido else 'listo'}"
        self.ui.agente(etiqueta, f"terminó · {estado} · {len(cand.cambios)} archivo(s)")
        return cand

    # ------------------------------------------------------------ API
    def correr(self, tarea: str, *, archivos: str = "", titulo: str = "", rol: str = "implementador",
               n: Optional[int] = None, protegidos: Optional[dict[str, Optional[str]]] = None,
               cid: Optional[int] = None) -> ResultadoTorneo:
        n = max(1, n or self.settings.candidatos)
        protegidos = dict(protegidos or {})
        # Los tests que ya existían se restauran antes de puntuar, salvo los que la tarea pide tocar.
        pedidos = {a.strip() for a in re.split(r"[,;\s]+", archivos or "") if a.strip()}
        existentes = copiar_contenidos(self.ws, [r for r in _archivos_de_tests(self.ws) if r not in pedidos])
        if n == 1:
            return self._simple(tarea, archivos, titulo, rol, protegidos, cid)

        candidatos = [Candidato(i, self.settings.temperatura_candidato(i)) for i in range(n)]
        try:
            for cand in candidatos:
                cand.copia = Copia(self.ws, f"cand{cand.indice + 1}").crear()
        except ErrorSandbox as e:
            for cand in candidatos:
                if cand.copia:
                    cand.copia.limpiar()
            self.ui.aviso(f"  Torneo desactivado: {e}")
            res = self._simple(tarea, archivos, titulo, rol, protegidos, cid)
            res.notas.append(f"Sin torneo: {e}")
            return res

        try:
            paralelo = max(1, min(self.settings.paralelo_torneo, n))
            temps = ", ".join(f"{c.temperatura:.1f}" for c in candidatos)
            self.ui.tenue(f"  ⚔ torneo: {n} implementadores en copias aisladas (temperaturas {temps}; "
                          f"{paralelo} a la vez)" + (f" · {titulo}" if titulo else ""))
            if paralelo == 1:
                for cand in candidatos:
                    self._correr_candidato(cand, tarea, archivos, rol, protegidos, existentes, True)
            else:
                with ThreadPoolExecutor(max_workers=paralelo) as ejecutor:
                    futuros = [ejecutor.submit(self._correr_candidato, cand, tarea, archivos, rol, protegidos,
                                               existentes, False) for cand in candidatos]
                    try:
                        for f in futuros:
                            f.result()
                    except (KeyboardInterrupt, Cancelado):
                        CANCELAR.set()
                        raise
            return self._decidir(candidatos, cid, protegidos)
        finally:
            for cand in candidatos:
                if cand.copia:
                    cand.copia.limpiar()

    def _decidir(self, candidatos: list[Candidato], cid: Optional[int],
                 protegidos: dict[str, Optional[str]]) -> ResultadoTorneo:
        ordenados = sorted(candidatos, key=lambda c: c.clave())
        self.ui.tabla([c.fila() for c in sorted(candidatos, key=lambda c: c.indice)],
                      ["cand", "temp", "agente", "tests", "validación", "archivos", "líneas", "tiempo"], "llllllrr")
        ganador = next((c for c in ordenados if not c.error and c.cambios), None)
        resultado = ResultadoTorneo(ganador, candidatos)
        if ganador is None:
            resultado.notas.append("Ningún candidato cambió archivos sin errores.")
            self.ui.error("Ningún candidato produjo cambios utilizables.")
            return resultado
        if cid is not None:
            self.ws.checkpoints.actual = cid
        assert ganador.copia is not None
        resultado.aplicados = ganador.copia.aplicar_a(self.ws, ganador.cambios, excluir=protegidos.keys())
        resultado.todos_pasan = ganador.conteo.ok and ganador.conteo.reconocido and ganador.conteo.pasados > 0
        indice_de(self.ws).invalidar()
        self.ui.ok(f"Ganó el candidato #{ganador.indice + 1} (t={ganador.temperatura:.1f}): "
                   f"{len(resultado.aplicados)} archivo(s) aplicados al proyecto")
        return resultado

    def _simple(self, tarea: str, archivos: str, titulo: str, rol: str,
                protegidos: dict[str, Optional[str]], cid: Optional[int]) -> ResultadoTorneo:
        """Un solo intento en el workspace real (sin copias)."""
        inicio = time.monotonic()
        res = ejecutar_subagentes(
            [(rol, tarea, archivos, titulo, {"memoria": self.memoria, "protegidos": set(protegidos),
                                             "on_atascado": self.on_atascado})],
            self.llm, self.ws, self.settings, self.ui, profundidad=1, cid_inicio=cid,
        )[0]
        cand = Candidato(0, ROLES[rol].temperatura, resultado=res, segundos=time.monotonic() - inicio)
        if protegidos:
            # Si el agente igual tocó la especificación (p. ej. con execute_command), se restaura.
            for rel, contenido in protegidos.items():
                actual = self.ws.leer(rel) if self.ws.existe(rel) else None
                if actual != contenido and contenido is not None:
                    self.ws.escribir(rel, contenido)
        cand.tests = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout, completo=True)
        cand.conteo = conteo_de_resultado(cand.tests)
        cand.validaciones = validar_archivos(self.ws, [r for r in res.cambios if (self.ws.raiz / r).is_file()])
        cand.cambios = [CambioArchivo(r, "modificado") for r in res.cambios]
        resultado = ResultadoTorneo(cand, [cand], list(res.cambios), cand.conteo.ok and cand.conteo.reconocido,
                                    modo="simple")
        return resultado
