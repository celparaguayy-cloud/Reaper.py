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
    """Extrae un objeto JSON sin confundir llaves dentro de cadenas o JSON anidado.

    Acepta un objeto directo o incluido en un bloque Markdown; no usa eval,
    ignora ejemplos inválidos previos y limita la cantidad de intentos para
    que la salida de un modelo no provoque un análisis cuadrático ilimitado.
    """
    if not isinstance(texto, str) or not texto.strip():
        return None
    # Los dictámenes operativos no necesitan megabytes de texto del modelo.
    texto = texto[:262144]
    decoder = json.JSONDecoder()
    intentos = 0
    for indice, caracter in enumerate(texto):
        if caracter != "{":
            continue
        intentos += 1
        if intentos > 64:
            break
        try:
            datos, _fin = decoder.raw_decode(texto, indice)
        except (ValueError, RecursionError):
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
    if decision == "APPROVE" and evidencia is None:
        base.problema = "APPROVE sin inventario de evidencia verificable"
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


def _evidencia_positiva_entrega(identificador: str, contenido: Any) -> bool:
    """Una evidencia presente no equivale automáticamente a una prueba favorable.

    Los planes, la ausencia de cambios y los resultados de tests fallidos no
    demuestran la entrega. Este filtro es conservador; verificar el significado
    específico de cada criterio sigue siendo responsabilidad del auditor.
    """
    id_norm = str(identificador).upper()
    valor = str(contenido or "").strip().lower()
    if not valor:
        return False
    if id_norm in ("EV-PLAN", "EV-PEDIDO"):
        return False
    if id_norm == "EV-DIFF":
        return valor not in ("(sin cambios)", "sin cambios", "-", "no changes")
    if id_norm == "EV-ESTADO":
        return ("estado por verificación real: verificada" in valor or
                "estado por verificación real: validada" in valor)
    if id_norm == "EV-TESTS":
        if ("sin suite" in valor or "sin tests" in valor or
                re.search(r"\bexit\s+[1-9]\d*\b", valor) or
                re.search(r"\b(?:fallaron|failed|error|errores)\b", valor)):
            return False
        return True
    if id_norm == "EV-VALID":
        return not ("fallaron" in valor or "failed" in valor or "error" in valor)
    return valor not in ("ninguna", "desconocido", "sin evidencia")


def parsear_auditoria(texto: str, evidencia: dict) -> Optional[list]:
    """[{criterion, status, evidence_ids}]; MET requiere evidencia existente y positiva."""
    datos = extraer_json_x(texto)
    if datos is None or not isinstance(datos.get("criteria"), list):
        return None
    if not isinstance(evidencia, dict):
        return None
    # Un resultado fallido global contradice una declaración de entrega completa,
    # incluso si el auditor cita solo el diff y omite deliberadamente EV-TESTS.
    estado_global = str(evidencia.get("EV-ESTADO", "")).lower()
    tests_globales = str(evidencia.get("EV-TESTS", "")).lower()
    validacion_global = str(evidencia.get("EV-VALID", "")).lower()
    entrega_roja = bool(
        re.search(r"estado por verificación real: (?:fallida|parcial|cancelada)", estado_global)
        or ("EV-TESTS" in evidencia and not _evidencia_positiva_entrega("EV-TESTS", tests_globales))
        or ("EV-VALID" in evidencia and not _evidencia_positiva_entrega("EV-VALID", validacion_global))
    )
    salida = []
    for c in datos["criteria"]:
        if not isinstance(c, dict) or not str(c.get("criterion", "")).strip():
            continue
        status = str(c.get("status", "UNKNOWN")).strip().upper()
        ids = [e for e in _lista_str(c.get("evidence_ids")) if e in evidencia]
        if status not in ("MET", "NOT_MET", "UNKNOWN"):
            status = "UNKNOWN"
        if status == "MET" and (entrega_roja or not any(_evidencia_positiva_entrega(e, evidencia[e]) for e in ids)):
            status = "UNKNOWN"
        salida.append({"criterion": str(c["criterion"]).strip()[:200], "status": status, "evidence_ids": ids})
    return salida


@dataclass
class Juicio:
    """Veredicto del 8.º agente (JUEZ DE ENTREGA): ¿lo entregado cumple el pedido? Solo endurece, nunca mejora."""
    cumple: bool
    faltantes: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)
    confianza: str = "low"
    valido: bool = True
    problema: str = ""

    def texto(self) -> str:
        if not self.valido:
            return f"Juez de entrega: veredicto fuera de contrato ({self.problema})"
        if self.cumple:
            return f"Juez de entrega: CUMPLE el pedido (confianza {self.confianza})"
        falta = "; ".join(self.faltantes[:4]) if self.faltantes else "sin detalle"
        return f"Juez de entrega: NO CUMPLE (confianza {self.confianza}) · falta: {falta}"


def parsear_juicio(texto: str, evidencia: Optional[dict] = None) -> Juicio:
    """Veredicto del juez desde su JSON. Si la evidencia muestra la build roja/parcial, nunca se acepta 'cumple'."""
    datos = extraer_json_x(texto)
    if not isinstance(datos, dict) or not isinstance(datos.get("cumple"), bool):
        return Juicio(False, valido=False, problema='sin JSON {"cumple": true|false}')
    cumple = bool(datos["cumple"])
    faltantes = _lista_str(datos.get("faltantes"))[:12]
    conf = str(datos.get("confianza", "low")).strip().lower()
    if conf not in _CONFIANZAS_X:
        conf = "low"
    ids = _lista_str(datos.get("evidence_ids"))
    if isinstance(evidencia, dict):
        ids = [e for e in ids if e in evidencia]
        estado_global = str(evidencia.get("EV-ESTADO", "")).lower()
        if cumple and re.search(r"estado por verificación real: (?:fallida|parcial|cancelada)", estado_global):
            # Defensa en profundidad: el juez no puede convertir una build roja/parcial en 'cumple'.
            cumple = False
            if not faltantes:
                faltantes = ["la verificación real no quedó en verde"]
    return Juicio(cumple, faltantes, ids, conf, valido=True)


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
