"""
Escalada a un modelo más fuerte cuando Venice se traba.

El modelo de respaldo de v6 solo se usaba si la API fallaba. En v7, si la
misma tarea falla la verificación real `umbral_escalada` veces (2 por
defecto), ese paso —y solo ese— se le consulta a un modelo más fuerte
(deepseek, qwen-coder...). El modelo fuerte NO edita: lee el error real y el
código y escribe un diagnóstico preciso con el arreglo exacto. Después Venice
(el reparador) lo aplica. Así se paga el modelo caro solo en los pocos casos
difíciles y Venice sigue haciendo todo lo demás.
"""


@dataclass
class Consulta:
    momento: str
    modelo: str
    tarea: str
    diagnostico: str
    ok: bool
    segundos: float


class Escalador:
    def __init__(self, llm, settings: Settings, ui: UI):
        self.llm = llm
        self.settings = settings
        self.ui = ui
        self.historial: list[Consulta] = []
        self._lock = threading.Lock()

    @property
    def modelo(self) -> str:
        return resolver_modelo(self.settings.modelo_fuerte)

    def disponible(self) -> bool:
        if not self.settings.escalar or not self.settings.modelo_fuerte.strip():
            return False
        return self.modelo != resolver_modelo(self.settings.modelo)

    def diagnosticar(self, ws: Workspace, tarea: str, error: str, archivos: Iterable[str] = (),
                     intentos: str = "") -> Optional[str]:
        """Lanza un consultor (solo lectura) con el modelo fuerte. Devuelve su diagnóstico o None."""
        if not self.disponible():
            return None
        archivos = [a for a in archivos if a]
        texto = (
            f"TAREA QUE EL OTRO MODELO NO LOGRA RESOLVER:\n{recortar(tarea, 3500)}\n\n"
            f"ERROR REAL (validadores/tests):\n{recortar(error, 5000)}\n\n"
        )
        if archivos:
            texto += f"Archivos involucrados: {', '.join(archivos[:12])}\n\n"
        if intentos:
            texto += f"LO QUE YA SE INTENTÓ (sin éxito):\n{recortar(intentos, 2500)}\n\n"
        texto += ("Leé el código necesario y escribí el diagnóstico con el arreglo exacto "
                  "(DIAGNÓSTICO / ARREGLO / VERIFICACIÓN).")
        self.ui.linea(f"{Tema.acento}⇪ escalada:{C.RESET} {Tema.tenue}consulto a {self.modelo} "
                      f"(la verificación falló {self.settings.umbral_escalada} veces){C.RESET}")
        inicio = time.monotonic()
        agente = Agente("consultor", self.llm, ws, self.settings, self.ui, profundidad=2,
                        etiqueta="consultor", modelo=self.modelo, temperatura=0.1, mostrar_progreso=True)
        try:
            res = agente.ejecutar(texto + SUFIJO_SUBTAREA)
        except LLMError as e:
            self.ui.aviso(f"  El modelo fuerte no respondió ({e}); sigo sin escalar.")
            self._registrar(tarea, f"error: {e}", False, time.monotonic() - inicio)
            return None
        diagnostico = (res.resumen or "").strip()
        if len(diagnostico) < 40 and res.contexto:
            diagnostico = (res.contexto + "\n" + diagnostico).strip()
        ok = len(diagnostico) >= 40
        self._registrar(tarea, diagnostico, ok, time.monotonic() - inicio)
        if ok:
            self.ui.ok(f"diagnóstico del experto recibido ({len(diagnostico)} caracteres)")
            primera = next((l for l in diagnostico.splitlines() if l.strip()), "")
            self.ui.tenue("  " + recortar(primera, 200))
            return diagnostico
        self.ui.aviso("  El modelo fuerte no produjo un diagnóstico útil.")
        return None

    def _registrar(self, tarea: str, diagnostico: str, ok: bool, segundos: float) -> None:
        with self._lock:
            self.historial.append(Consulta(datetime.now().strftime("%H:%M:%S"), self.modelo,
                                           _titulo(tarea), diagnostico, ok, segundos))

    def gancho(self, ws: Workspace, tarea: str) -> Optional[Callable[[str], Optional[str]]]:
        """Función para Agente.on_atascado: se llama cuando el agente repite el mismo error."""
        if not self.disponible():
            return None

        def consultar(error: str) -> Optional[str]:
            return self.diagnosticar(ws, tarea, error)

        return consultar

    def resumen(self) -> str:
        if not self.historial:
            return "Sin escaladas en esta sesión."
        lineas = [f"{len(self.historial)} consulta(s) al modelo fuerte:"]
        for c in self.historial[-10:]:
            marca = "✓" if c.ok else "✗"
            lineas.append(f"  {marca} {c.momento} {c.modelo} · {c.tarea} ({formatear_duracion(c.segundos)})")
        return "\n".join(lineas)


def tarea_con_diagnostico(tarea: str, diagnostico: str) -> str:
    return (f"{tarea}\n\nDIAGNÓSTICO DE UN EXPERTO (un modelo más fuerte analizó el error real; seguilo al pie "
            f"de la letra y verificá con validate/run_tests):\n{recortar(diagnostico, 6000)}")
