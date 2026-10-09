"""
Evidence Core (v9, Fase 2): separar CLAIM (lo que un agente afirma) de EVIDENCE (lo que una herramienta
observó), y un EvidenceGate que decide el NIVEL de verificación en vez de aceptar "funciona" a secas.

Ataca los fallos de v8:
  §1.4 "todos los tests pasan, por lo tanto no hay errores"  → CLAIM_SCOPE_EXCEEDS_EVIDENCE
  §1.1/1.2 tests verdes pero tautológicos o que mockean el sistema → TEST_SUITE_GREEN ≠ BEHAVIOR_VERIFIED
  §31 evidencia de una revisión vieja → STALE_EVIDENCE

La filosofía: los modelos proponen, las herramientas observan, la evidencia decide.
"""

# Niveles de verificación, de menor a mayor fuerza (MASTER SPEC §1.4).
NIVELES_VERIFICACION = ("UNVERIFIED", "TEST_SUITE_GREEN", "PARTIALLY_VERIFIED", "BEHAVIOR_VERIFIED",
                        "INTEGRATION_VERIFIED", "SPEC_VERIFIED")
# Estados de un claim.
ESTADOS_CLAIM = ("UNVERIFIED", "SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "REJECTED", "STALE")


@dataclass
class ToolReceipt:
    """Observación cruda de una herramienta (lo único en lo que el gate confía)."""
    source: str                       # run_tests | validate | execute_command | run_python | inspect_tests
    exit_code: Optional[int] = None
    ok: bool = False
    resumen: str = ""
    revision: str = ""                # huella del workspace cuando se observó
    discriminacion: float = 1.0       # si aplica (tests): 1.0 = discriminan; <1 = débiles
    timestamp: float = field(default_factory=time.time)

    def como_dict(self) -> dict:
        return {"source": self.source, "exit_code": self.exit_code, "ok": self.ok,
                "resumen": recortar(self.resumen, 400), "revision": self.revision,
                "discriminacion": self.discriminacion}


@dataclass
class Claim:
    statement: str
    agent: str = ""
    tipo: str = "resultado"           # resultado | tests | comportamiento | spec
    confidence: float = 0.5
    evidence: list = field(default_factory=list)   # ToolReceipt
    status: str = "UNVERIFIED"
    nivel: str = "UNVERIFIED"
    motivo: str = ""

    def como_dict(self) -> dict:
        return {"statement": recortar(self.statement, 300), "agent": self.agent, "tipo": self.tipo,
                "status": self.status, "nivel": self.nivel, "motivo": self.motivo,
                "evidence": [e.como_dict() for e in self.evidence]}


# Afirmaciones que EXCEDEN lo que un test verde puede demostrar (§1.4).
_RE_EXCEDE = re.compile(
    r"\b(no\s+(?:hay|tiene|existen?|quedan)\s+(?:errores|bugs?|fallos?|problemas?)"
    r"|sin\s+(?:errores|bugs?|fallos?)\b"
    r"|(?:100|cien)\s*%?\s*(?:correcto|funcional|cubierto)"
    r"|funciona\s+(?:perfectamente|a\s+la\s+perfecci[óo]n)"
    r"|listo\s+para\s+producci[óo]n|production[- ]ready"
    r"|totalmente\s+(?:correcto|verificad|probad)|completamente\s+(?:correcto|verificad|probad)"
    r"|garantiz\w+\s+que|imposible\s+que\s+falle|no\s+puede\s+fallar"
    r"|bug[- ]free|no\s+bugs?\b)",
    re.I,
)
# Afirmaciones de que los tests pasan.
_RE_TESTS_PASAN = re.compile(
    r"\b(?:todos\s+los\s+)?tests?\s+(?:pasan|pasaron|est[áa]n\s+en\s+verde|ok)\b"
    r"|\b(?:all\s+)?tests?\s+pass(?:ed)?\b|\b\d+\s*/\s*\d+\b|pytest\b.*\bok\b|unittest.*\bok\b",
    re.I,
)
# Afirmaciones de comportamiento ("funciona", "anda", "corre bien").
_RE_COMPORTAMIENTO = re.compile(
    r"\b(funciona|anda|corre|ejecuta)\b(?!\s+(?:de|como))|se\s+comporta|produce\s+(?:el|la)\s+(?:resultado|salida)"
    r"\s+(?:correct|esperad)|verifiqu[ée]\s+el\s+comportamiento",
    re.I,
)


def _revision(ws) -> str:
    try:
        return ws.huella()
    except (OSError, AttributeError):
        return ""


def receipt_de_evidencia(tipo: str, estado: str, ws=None, resumen: str = "",
                         discriminacion: float = 1.0) -> ToolReceipt:
    """Construye un ToolReceipt a partir de la evidencia que el agente ya registra (tipo, estado)."""
    ok = estado == "ok"
    return ToolReceipt(source=tipo, ok=ok, exit_code=0 if ok else 1, resumen=resumen,
                       revision=_revision(ws) if ws is not None else "", discriminacion=discriminacion)


def discriminacion_de_tests(ws, limite: int = 60) -> tuple[float, list[str]]:
    """
    Discriminación media de los tests Python del proyecto y los problemas ALTA (tautología, mock del sujeto).
    1.0 y [] si no hay tests Python o están sanos.
    """
    try:
        archivos = [ws.rel(p) for p in ws.iterar(limite=limite * 3)
                    if ws.rel(p).endswith(".py") and es_archivo_de_test(ws.rel(p))][:limite]
    except OSError:
        return 1.0, []
    if not archivos:
        return 1.0, []
    valores, problemas = [], []
    for rel in archivos:
        try:
            res = analizar_tests_python(ws.leer(rel))
        except (OSError, ValueError, ErrorRuta):
            continue
        valores.append(res.discriminacion)
        for p in res.problemas:
            if p.severidad == "alta" and p.tipo in ("TAUTOLOGIA", "MOCK_SISTEMA_BAJO_PRUEBA", "VALOR_DESDE_MOCK",
                                                    "INTEGRACION_MOCKEADA"):
                problemas.append(f"{rel}: {p.test} [{p.tipo}]")
    if not valores:
        return 1.0, []
    return round(sum(valores) / len(valores), 2), problemas[:12]


class EvidenceGate:
    """
    Evalúa un claim contra evidencia real + inteligencia de tests. No decide 'verdadero/falso':
    asigna un NIVEL de verificación y explica qué falta para subir.
    """

    def __init__(self, ws=None):
        self.ws = ws

    def evaluar(self, claim: Claim) -> Claim:
        texto = claim.statement or ""
        afirma_tests = bool(_RE_TESTS_PASAN.search(texto))
        afirma_comportamiento = bool(_RE_COMPORTAMIENTO.search(texto))
        afirma_exceso = bool(_RE_EXCEDE.search(texto))

        receipts = claim.evidence
        tests_ok = [r for r in receipts if r.source == "run_tests" and r.ok]
        tests_fallan = [r for r in receipts if r.source == "run_tests" and not r.ok]
        corridas = [r for r in receipts if r.source in ("execute_command", "run_python") and r.ok]
        bloqueadas = [r for r in receipts if r.source in ("run_tests", "validate", "execute_command", "run_python")
                      and r.exit_code in (None,) and not r.ok]

        # revisión obsoleta: la última evidencia es de otra revisión que la actual
        revision_actual = _revision(self.ws) if self.ws is not None else ""
        if revision_actual and receipts:
            frescas = [r for r in receipts if not r.revision or r.revision == revision_actual]
            if not frescas and tests_ok:
                claim.status, claim.nivel = "STALE", "UNVERIFIED"
                claim.motivo = ("STALE_EVIDENCE: la evidencia es de una revisión anterior; el código cambió después. "
                                "Volvé a correr los tests sobre el estado actual.")
                return claim

        # discriminación de los tests (Fase 1)
        discriminacion = 1.0
        problemas_tests: list[str] = []
        if self.ws is not None and (afirma_tests or afirma_comportamiento):
            discriminacion, problemas_tests = discriminacion_de_tests(self.ws)
            for r in tests_ok:
                r.discriminacion = discriminacion

        # 0) dijo que los tests pasan pero el último run_tests falló (un run fallido ES evidencia de ejecución)
        if afirma_tests and tests_fallan and not tests_ok:
            claim.status, claim.nivel = "CONTRADICTED", "UNVERIFIED"
            claim.motivo = "decís que los tests pasan pero el último run_tests FALLÓ. Contradice la evidencia."
            return claim

        # 1) nada ejecutado pero afirma éxito
        if (afirma_tests or afirma_comportamiento or afirma_exceso) and not (tests_ok or corridas):
            claim.status, claim.nivel = "UNVERIFIED", "UNVERIFIED"
            if bloqueadas:
                claim.motivo = ("las ejecuciones fueron BLOQUEADAS/rechazadas: no hay evidencia real. "
                                "Corré run_tests o execute_command de verdad.")
            else:
                claim.motivo = "no hay evidencia de ejecución (run_tests / execute_command). Ejecutá antes de afirmar."
            return claim

        # nivel base por lo observado
        nivel = "UNVERIFIED"
        if tests_ok:
            nivel = "TEST_SUITE_GREEN"
        if tests_ok and corridas:
            nivel = "BEHAVIOR_VERIFIED"
        elif corridas and not (afirma_tests or tests_ok):
            nivel = "BEHAVIOR_VERIFIED"

        # 3) tests verdes pero no discriminan → no sube a BEHAVIOR_VERIFIED
        if tests_ok and discriminacion < 0.7 and problemas_tests:
            claim.status, claim.nivel = "PARTIALLY_SUPPORTED", "TEST_SUITE_GREEN"
            claim.motivo = ("TEST_SUITE_GREEN pero NO BEHAVIOR_VERIFIED: los tests pasan pero no discriminan "
                            f"(discriminación {discriminacion}). Problemas: " + "; ".join(problemas_tests[:4])
                            + ". Verde no equivale a correcto; corregí los tests o agregá casos que fallen si el "
                            "código se rompe.")
            return claim

        # 4) el alcance del claim excede la evidencia (§1.4)
        if afirma_exceso:
            claim.status, claim.nivel = "PARTIALLY_SUPPORTED", nivel
            cuanto = (f"{len(tests_ok)} corrida(s) de tests" if tests_ok else "la evidencia disponible")
            claim.motivo = ("CLAIM_SCOPE_EXCEEDS_EVIDENCE: afirmás ausencia total de errores / correctitud "
                            f"absoluta, pero {cuanto} solo demuestra que esos casos pasan. Acotá la afirmación a "
                            "lo que la evidencia respalda (p. ej. 'los N tests pasan sobre esta revisión').")
            return claim

        claim.status = "SUPPORTED" if nivel != "UNVERIFIED" else "UNVERIFIED"
        claim.nivel = nivel
        claim.confidence = {"BEHAVIOR_VERIFIED": 0.85, "TEST_SUITE_GREEN": 0.65, "UNVERIFIED": 0.3}.get(nivel, 0.5)
        return claim


class LibroEvidencia:
    """Registro de claims de una tarea (para el informe final y /claims). Opcional en disco."""

    def __init__(self, ws=None):
        self.ws = ws
        self.claims: list[Claim] = []

    def registrar(self, claim: Claim) -> Claim:
        self.claims.append(claim)
        return claim

    def resumen(self) -> str:
        if not self.claims:
            return "Sin claims registrados."
        lineas = []
        for c in self.claims[-12:]:
            lineas.append(f"[{c.status}/{c.nivel}] {recortar(c.statement, 90)}"
                          + (f"  → {recortar(c.motivo, 120)}" if c.motivo else ""))
        return "\n".join(lineas)

    def guardar(self) -> Optional[Path]:
        if self.ws is None or not self.claims:
            return None
        try:
            carpeta = self.ws.raiz / ".reaper" / "evidencia"
            carpeta.mkdir(parents=True, exist_ok=True)
            ruta = carpeta / f"claims_{datetime.now():%Y%m%d_%H%M%S}.json"
            escritura_atomica(ruta, json.dumps([c.como_dict() for c in self.claims], ensure_ascii=False, indent=2))
            return ruta
        except OSError:
            return None


def evaluar_cierre(ws, informe: str, evidencias: list, agente: str = "") -> Claim:
    """
    Construye un Claim desde el informe final + la evidencia que el agente registró (lista de tuplas
    (tipo, estado, version)) y lo pasa por el EvidenceGate. Devuelve el Claim evaluado.
    """
    receipts = []
    for ev in evidencias[-12:]:
        tipo, estado = ev[0], ev[1]
        receipts.append(receipt_de_evidencia(tipo, estado, ws))
    claim = Claim(statement=informe, agent=agente, evidence=receipts)
    return EvidenceGate(ws).evaluar(claim)
