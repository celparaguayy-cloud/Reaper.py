"""
REAPER X: equipo de 10 roles con dictámenes estructurados y un controlador determinista.

Distinción que no se rompe: ROL (responsabilidad) ≠ MODELO (id servido por una API) ≠ PROVEEDOR (dominio de
autenticación). Diez roles pueden compartir modelos; solo se cuentan modelos "verificados" después de una
prueba real (/equipo probar). Los roles de dirección y auditoría (director, supervisor, seguridad defensiva,
auditor de entrega) responden JSON por texto, sin herramientas: el controlador valida ese JSON y nunca ejecuta
nada de lo que dice. El estado final de una build lo decide la verificación real (tests + validadores), no un
dictamen: un APPROVE sin evidencia es inválido y ningún dictamen puede convertir una build roja en verde.
"""

ROLES_EQUIPO_DIEZ = (
    ("director", "director"),
    ("supervisor", "supervisor"),
    ("arquitecto", "arquitecto"),
    ("implementador", "implementador"),
    ("revisor", "revisor"),
    ("qa", "qa"),
    ("reparador", "reparador"),
    ("integrador", "integrador"),
    ("seguridad", "seguridad"),
    ("auditor_entrega", "auditor_entrega"),
)

DECISIONES_X = ("APPROVE", "REJECT", "REWORK", "ESCALATE", "ABSTAIN")
_CONFIANZAS_X = ("low", "medium", "high")


def roles_equipo(settings) -> tuple:
    """Los roles del equipo según la configuración: 10 con REAPER X activado, los 6 clásicos si no."""
    return ROLES_EQUIPO_DIEZ if getattr(settings, "roles_x", False) else ROLES_EQUIPO_SEIS


def extraer_json_x(texto: str) -> Optional[dict]:
    """Primer objeto JSON del texto (acepta ```json ...```). None si no hay un objeto válido. Nunca evalúa código."""
    if not texto:
        return None
    candidatos = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.S)
    inicio = texto.find("{")
    if inicio >= 0:
        profundidad = 0
        for i in range(inicio, len(texto)):
            if texto[i] == "{":
                profundidad += 1
            elif texto[i] == "}":
                profundidad -= 1
                if profundidad == 0:
                    candidatos.append(texto[inicio:i + 1])
                    break
    for c in candidatos:
        try:
            datos = json.loads(c)
        except ValueError:
            continue
        if isinstance(datos, dict):
            return datos
    return None


def _lista_str(valor) -> list:
    if isinstance(valor, str):
        return [valor] if valor.strip() else []
    if isinstance(valor, (list, tuple)):
        return [str(x).strip() for x in valor if str(x).strip()]
    return []


@dataclass
class Dictamen:
    rol: str
    decision: str                      # una de DECISIONES_X, o "INVALID"
    reasons: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)
    next_actions: list = field(default_factory=list)
    confidence: str = "low"
    model_requested: str = ""
    model_served: str = "unknown"
    problema: str = ""                 # por qué es INVALID

    @property
    def valido(self) -> bool:
        return self.decision in DECISIONES_X

    def texto(self) -> str:
        if not self.valido:
            return f"{self.rol}: dictamen INVÁLIDO ({self.problema})"
        razones = "; ".join(self.reasons[:4]) or "sin razones"
        return f"{self.rol}: {self.decision} [{self.confidence}] — {razones}"


def parsear_dictamen(texto: str, rol: str, evidencia: Optional[dict] = None, *, model_requested: str = "",
                     model_served: str = "unknown") -> Dictamen:
    """
    Valida la respuesta de un rol de dirección contra el contrato. Reglas: JSON obligatorio; decisión del
    enum; APPROVE exige evidence_ids que EXISTAN en la evidencia dada; REJECT/REWORK exigen razones.
    confidence=high no cambia nada: solo la evidencia cuenta.
    """
    base = Dictamen(rol, "INVALID", model_requested=model_requested, model_served=model_served or "unknown")
    datos = extraer_json_x(texto)
    if datos is None:
        base.problema = "la respuesta no es un objeto JSON"
        return base
    decision = str(datos.get("decision", "")).strip().upper()
    if decision not in DECISIONES_X:
        base.problema = f"decisión fuera del contrato: {decision or '(vacía)'}"
        return base
    base.reasons = _lista_str(datos.get("reasons"))
    base.evidence_ids = _lista_str(datos.get("evidence_ids"))
    base.next_actions = _lista_str(datos.get("next_actions"))
    confianza = str(datos.get("confidence", "low")).strip().lower()
    base.confidence = confianza if confianza in _CONFIANZAS_X else "low"
    if evidencia is not None:
        inexistentes = [e for e in base.evidence_ids if e not in evidencia]
        if inexistentes:
            base.problema = "cita evidencia inexistente: " + ", ".join(inexistentes[:4])
            return base
    if decision == "APPROVE" and not base.evidence_ids:
        base.problema = "APPROVE sin evidence_ids"
        return base
    if decision in ("REJECT", "REWORK") and not base.reasons:
        base.problema = f"{decision} sin razones verificables"
        return base
    base.decision = decision
    return base


def estado_controlado(estado_determinista: str, dictamen: Optional[Dictamen]) -> tuple:
    """
    El controlador: el estado final es el de la verificación real. Un dictamen del supervisor solo agrega
    observaciones (nunca convierte una build roja/parcial en verificada). Devuelve (estado, notas).
    """
    notas = []
    if dictamen is None:
        return estado_determinista, notas
    if not dictamen.valido:
        notas.append(f"Dictamen del supervisor descartado: {dictamen.problema}.")
    elif dictamen.decision == "APPROVE" and estado_determinista not in ("verificada", "validada"):
        notas.append("El supervisor aprobó, pero la verificación real no pasa: manda la verificación.")
    elif dictamen.decision in ("REJECT", "REWORK"):
        notas.append("Objeción del supervisor: " + "; ".join(dictamen.reasons[:4]))
    return estado_determinista, notas


def parsear_hallazgos_seguridad(texto: str) -> Optional[list]:
    """[{severity, file, issue, fix}] validados; None si la respuesta no cumple el contrato."""
    datos = extraer_json_x(texto)
    if datos is None or not isinstance(datos.get("findings"), list):
        return None
    salida = []
    for h in datos["findings"]:
        if not isinstance(h, dict) or not str(h.get("issue", "")).strip():
            continue
        sev = str(h.get("severity", "low")).strip().lower()
        salida.append({"severity": sev if sev in ("high", "medium", "low") else "low",
                       "file": str(h.get("file", "")).strip(), "issue": str(h["issue"]).strip()[:300],
                       "fix": str(h.get("fix", "")).strip()[:300]})
    return salida


def parsear_auditoria(texto: str, evidencia: dict) -> Optional[list]:
    """[{criterion, status, evidence_ids}]; un MET sin evidencia existente baja a UNKNOWN. None si es inválido."""
    datos = extraer_json_x(texto)
    if datos is None or not isinstance(datos.get("criteria"), list):
        return None
    salida = []
    for c in datos["criteria"]:
        if not isinstance(c, dict) or not str(c.get("criterion", "")).strip():
            continue
        status = str(c.get("status", "UNKNOWN")).strip().upper()
        ids = [e for e in _lista_str(c.get("evidence_ids")) if e in evidencia]
        if status not in ("MET", "NOT_MET", "UNKNOWN"):
            status = "UNKNOWN"
        if status == "MET" and not ids:
            status = "UNKNOWN"
        salida.append({"criterion": str(c["criterion"]).strip()[:200], "status": status, "evidence_ids": ids})
    return salida


def conteo_equipo_x(settings, probados: Optional[dict] = None) -> dict:
    """
    Conteos honestos y separados: roles, modelos distintos configurados, modelos distintos VERIFICADOS (solo los
    que respondieron una prueba real) y proveedores. Un gateway (OpenRouter) cuenta como UN proveedor.
    """
    probados = probados or {}
    roles = roles_equipo(settings)
    modelos, proveedores = set(), set()
    for _etiqueta, rol in roles:
        m = settings.modelo_para(rol)
        modelos.add(m)
        proveedores.add(destino_modelo(m, settings).proveedor)
    verificados = {m for m in modelos if probados.get(m) == "RESPONDE"}
    return {"roles": len(roles), "modelos_configurados": len(modelos), "modelos_verificados": len(verificados),
            "proveedores": len(proveedores), "independencia_reducida": len(proveedores) <= 1}
