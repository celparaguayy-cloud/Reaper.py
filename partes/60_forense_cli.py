"""/forense [tests...]: corre el modo forense a mano sobre los tests que fallan (o los indicados)."""


def _cmd_forense(self: "App", arg: str) -> None:
    detectado = detectar_comando_tests(self.ws, completo=True)
    if not detectado:
        self.ui.aviso("No detecté tests en el proyecto: el modo forense necesita una suite que falle.")
        return
    fallidos = arg.split()
    if not fallidos:
        conteo = conteo_actual(self.ws, self.settings.tests_timeout)
        if not (conteo.fallados or conteo.errores):
            self.ui.ok(f"Los tests pasan ({conteo.texto()}): no hay nada que investigar.")
            return
        fallidos = conteo.nombres_fallados
    modelo = self.escalador.modelo if self.escalador.disponible() else None
    try:
        informe = investigar(self.ws, self.settings, self.ui, self.llm, fallidos=fallidos, modelo=modelo)
    except LLMError as e:
        self.ui.error(f"Modelo: {e}")
        return
    mostrar_markdown(self.ui, informe.texto(20000))
    if informe.ruta:
        self.ui.tenue(f"  guardado en {self.ws.rel(informe.ruta)} · pedile al agente: \"arreglá según @{self.ws.rel(informe.ruta)}\"")


setattr(App, "cmd_forense", _cmd_forense)
COMANDOS_AYUDA[0][1].append(("/forense [tests]", "investiga un fallo con método: aislar, estado compartido, bisección, hipótesis"))


def _cmd_claims(self: "App", arg: str) -> None:
    claim = getattr(self.principal, "_ultimo_claim", None)
    if claim is None:
        self.ui.tenue("Todavía no hay claims evaluados (el Evidence Gate corre al cerrar un pedido).")
        return
    self.ui.info(f"Última afirmación evaluada · estado {claim.status} · nivel {claim.nivel}")
    mostrar_markdown(self.ui, recortar(claim.statement, 600))
    if claim.motivo:
        self.ui.aviso("  " + claim.motivo)
    if claim.evidence:
        self.ui.tenue("  evidencia:")
        for e in claim.evidence[-8:]:
            marca = "✓" if e.ok else "✗"
            extra = f" discr={e.discriminacion}" if e.source == "run_tests" and e.discriminacion < 1.0 else ""
            self.ui.tenue(f"    {marca} {e.source}{extra}")


setattr(App, "cmd_claims", _cmd_claims)
setattr(App, "cmd_evidence", _cmd_claims)
COMANDOS_AYUDA[0][1].append(("/claims", "muestra la última afirmación y su nivel de evidencia (TEST_SUITE_GREEN, BEHAVIOR_VERIFIED...)"))
