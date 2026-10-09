"""
Security Scope Gate + modelo de evidencia y hallazgos (REAPER v11, Fase 1).

Columna vertebral de seguridad del spec v11 (§5, §7, §12, §23):
  - PoliticaAlcance: QUÉ está autorizado (hosts, puertos, operaciones, vigencia, límites). La carga el
    OPERADOR desde un archivo; el agente/LLM NO tiene ninguna herramienta para crearla ni ampliarla.
  - PuertaAlcance (ScopeGate): decide ALLOW/DENY por (host, puerto, operación) de forma independiente del
    modelo. Sin política válida, toda operación ACTIVA de red se deniega (SCOPE_REQUIRED). No confía en el
    texto del LLM. No ejecuta red: solo decide; el enforcement real vive en el ExecutionBroker (PLANNED).
  - EstadoHallazgo / Hallazgo: etiquetas HONESTAS. Una coincidencia de versión (VERSION_MATCH_ONLY) o un
    hallazgo estático (STATIC_FINDING) NO es lo mismo que algo reproducido en laboratorio (CONFIRMED_LAB).
  - ReciboEjecucion: evidencia ligada a la revisión de git y a hashes; ningún modelo puede fabricarla.

Principio: una IP/URL/afirmación de un modelo NO es autorización. Autorización = PoliticaAlcance verificable.
"""

# Etiquetas de estado de un hallazgo (§7, §23.2): de menor a mayor fuerza; separan posibilidad de confirmación.
ESTADOS_HALLAZGO = (
    "UNVERIFIED",           # sin respaldo
    "VERSION_MATCH_ONLY",   # la versión podría estar afectada; NO se probó el fallo
    "STATIC_FINDING",       # hallazgo de código/config; requiere comprobación contextual
    "HYPOTHESIS",           # hipótesis a validar
    "CANDIDATE",            # candidato con señal, sin confirmación reproducible
    "ACTIVE_CHECK_PASSED",  # observación real compatible con el fallo, dentro del alcance
    "VERIFIED_IN_LAB",      # reproducido en laboratorio aislado
    "CONFIRMED_LAB",        # evidencia reproducible y verificada de forma independiente
    "REFUTED",              # se intentó y NO se reprodujo
    "FALSE_POSITIVE",
    "INCONCLUSIVE",
    "OUT_OF_SCOPE",
    "BLOCKED_BY_SCOPE",     # la operación cayó fuera del alcance autorizado
)
# Solo estos cuentan como "confirmado": nunca por relato del modelo ni por versión coincidente.
_CONFIRMADOS = ("VERIFIED_IN_LAB", "CONFIRMED_LAB")

TIPOS_ALCANCE = ("isolated_lab", "owned_dev", "explicitly_authorized")

# IPs/hosts que nunca se asumen en alcance aunque el texto los nombre (metadata cloud, link-local).
_SC_PELIGROSOS = ("169.254.169.254", "metadata.google.internal", "169.254.")


def es_hallazgo_confirmado(estado: str) -> bool:
    return estado in _CONFIRMADOS


def _sc_sha256(texto) -> str:
    if texto is None:
        return ""
    if isinstance(texto, str):
        texto = texto.encode("utf-8", "replace")
    return hashlib.sha256(texto).hexdigest()


def _sc_host(host: str) -> str:
    h = (host or "").strip().lower()
    h = re.sub(r"^\w+://", "", h)        # saca esquema si vino una URL
    h = h.split("/")[0].split("@")[-1]   # saca ruta y user@
    if h.startswith("[") and "]" in h:   # IPv6 entre corchetes
        return h[1:h.index("]")]
    return h.split(":")[0]               # saca puerto de host:puerto


@dataclass
class Hallazgo:
    id: str
    titulo: str
    estado: str = "UNVERIFIED"
    severidad: str = "info"              # info | baja | media | alta | critica
    fixture_id: str = ""
    revision: str = ""
    evidencia: list = field(default_factory=list)    # ids de recibos / hashes
    limitaciones: list = field(default_factory=list)
    detalle: str = ""

    def __post_init__(self):
        if self.estado not in ESTADOS_HALLAZGO:
            self.estado = "UNVERIFIED"

    def confirmado(self) -> bool:
        return es_hallazgo_confirmado(self.estado)

    def como_dict(self) -> dict:
        return {"id": self.id, "titulo": self.titulo, "estado": self.estado, "severidad": self.severidad,
                "fixture_id": self.fixture_id, "revision": self.revision,
                "evidencia": list(self.evidencia), "limitaciones": list(self.limitaciones),
                "detalle": recortar(self.detalle, 500)}


@dataclass
class PoliticaAlcance:
    scope_id: str
    kind: str = "isolated_lab"
    allowed_hosts: tuple = ()
    allowed_ports: tuple = ()
    allowed_operations: tuple = ()
    expires_at: str = ""                 # ISO 8601 (vacío = sin fecha → se considera NO vigente para red activa)
    max_requests_per_minute: int = 0
    max_execution_seconds: int = 0
    origen: str = ""                     # ruta del archivo del operador (trazabilidad)

    def valida(self) -> tuple:
        problemas = []
        if not self.scope_id:
            problemas.append("falta scope_id")
        if self.kind not in TIPOS_ALCANCE:
            problemas.append(f"kind inválido: {self.kind} (usá {', '.join(TIPOS_ALCANCE)})")
        if not self.allowed_hosts:
            problemas.append("allowed_hosts vacío: ningún host autorizado")
        for h in self.allowed_hosts:
            if any(p in str(h) for p in _SC_PELIGROSOS):
                problemas.append(f"host peligroso no permitido: {h}")
        if not self.expires_at:
            problemas.append("falta expires_at (una política sin vencimiento no habilita red activa)")
        return (not problemas, problemas)

    def vigente(self, ahora: Optional[datetime] = None) -> bool:
        if not self.expires_at:
            return False
        try:
            limite = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        ahora = ahora or datetime.now(limite.tzinfo) if limite.tzinfo else (ahora or datetime.now())
        try:
            return ahora <= limite
        except TypeError:          # comparación naive/aware
            return datetime.now() <= limite.replace(tzinfo=None)

    def como_dict(self) -> dict:
        return {"scope_id": self.scope_id, "kind": self.kind, "allowed_hosts": list(self.allowed_hosts),
                "allowed_ports": list(self.allowed_ports), "allowed_operations": list(self.allowed_operations),
                "expires_at": self.expires_at, "max_requests_per_minute": self.max_requests_per_minute,
                "max_execution_seconds": self.max_execution_seconds, "origen": self.origen}


def cargar_politica_alcance(origen) -> PoliticaAlcance:
    """Carga una PoliticaAlcance desde un dict ya parseado o un archivo .json/.yaml del OPERADOR."""
    if isinstance(origen, dict):
        datos, ruta = origen, ""
    else:
        ruta = str(origen)
        texto = Path(origen).read_text(encoding="utf-8")
        if ruta.endswith((".yaml", ".yml")):
            try:
                import yaml  # opcional; en Termux puede no estar
                datos = yaml.safe_load(texto)
            except ImportError as e:
                raise ValueError("YAML no disponible en este entorno; exportá la política como JSON") from e
        else:
            datos = json.loads(texto)
    if not isinstance(datos, dict):
        raise ValueError("la política de alcance debe ser un objeto (clave/valor)")
    return PoliticaAlcance(
        scope_id=str(datos.get("scope_id", "")),
        kind=str(datos.get("kind", "isolated_lab")),
        allowed_hosts=tuple(_sc_host(h) for h in datos.get("allowed_hosts", []) or []),
        allowed_ports=tuple(int(p) for p in datos.get("allowed_ports", []) or []),
        allowed_operations=tuple(str(o) for o in datos.get("allowed_operations", []) or []),
        expires_at=str(datos.get("expires_at", "")),
        max_requests_per_minute=int(datos.get("max_requests_per_minute", 0) or 0),
        max_execution_seconds=int(datos.get("max_execution_seconds", 0) or 0),
        origen=ruta,
    )


@dataclass
class DecisionAlcance:
    permitido: bool
    estado: str          # ALLOW | SCOPE_REQUIRED | EXPIRED | BLOCKED_BY_SCOPE | DENIED | INVALID
    razon: str = ""

    def como_dict(self) -> dict:
        return {"permitido": self.permitido, "estado": self.estado, "razon": self.razon}


class PuertaAlcance:
    """
    ScopeGate. Decide si una operación ACTIVA (de red) está dentro del alcance autorizado. Es independiente
    del LLM: la política se pasa desde fuera (archivo del operador) y esta clase NO expone ningún método para
    agregar hosts, puertos u operaciones. Sin política válida y vigente, deniega todo lo activo.
    """

    def __init__(self, politica: Optional[PoliticaAlcance] = None):
        self._politica = politica

    @property
    def scope_id(self) -> str:
        return self._politica.scope_id if self._politica else ""

    def decidir(self, host: str, puerto: Optional[int] = None, operacion: str = "") -> DecisionAlcance:
        pol = self._politica
        if pol is None:
            return DecisionAlcance(False, "SCOPE_REQUIRED",
                                   "no hay PoliticaAlcance: ninguna operación activa de red está autorizada. "
                                   "Importá una política del operador (/alcance importar) o quedate en análisis offline.")
        ok, problemas = pol.valida()
        if not ok:
            return DecisionAlcance(False, "INVALID", "la política de alcance es inválida: " + "; ".join(problemas))
        if not pol.vigente():
            return DecisionAlcance(False, "EXPIRED", f"la política {pol.scope_id} está vencida o sin vencimiento válido.")
        h = _sc_host(host)
        if not h:
            return DecisionAlcance(False, "DENIED", "host vacío.")
        if any(p in h for p in _SC_PELIGROSOS):
            return DecisionAlcance(False, "BLOCKED_BY_SCOPE", f"{h} es un host sensible (metadata/link-local): bloqueado.")
        if h not in pol.allowed_hosts:
            return DecisionAlcance(False, "BLOCKED_BY_SCOPE",
                                   f"{h} no está en allowed_hosts del alcance {pol.scope_id}. Fuera de alcance.")
        if puerto is not None and pol.allowed_ports and int(puerto) not in pol.allowed_ports:
            return DecisionAlcance(False, "DENIED", f"puerto {puerto} fuera de allowed_ports {list(pol.allowed_ports)}.")
        if operacion and pol.allowed_operations and operacion not in pol.allowed_operations:
            return DecisionAlcance(False, "DENIED",
                                   f"operación '{operacion}' no está en allowed_operations {list(pol.allowed_operations)}.")
        return DecisionAlcance(True, "ALLOW", f"dentro del alcance {pol.scope_id} ({pol.kind}).")

    def resumen(self) -> str:
        pol = self._politica
        if pol is None:
            return "Sin PoliticaAlcance: toda operación activa de red está DENEGADA (solo análisis offline)."
        ok, problemas = pol.valida()
        estado = "vigente" if (ok and pol.vigente()) else ("vencida" if ok else "inválida")
        return (f"Alcance {pol.scope_id} [{pol.kind}] — {estado}. Hosts: {', '.join(pol.allowed_hosts) or '—'}. "
                f"Puertos: {', '.join(map(str, pol.allowed_ports)) or 'todos'}. "
                f"Operaciones: {', '.join(pol.allowed_operations) or 'todas'}. Vence: {pol.expires_at or '—'}."
                + ("" if ok else "  PROBLEMAS: " + "; ".join(problemas)))


@dataclass
class ReciboEjecucion:
    """ExecutionReceipt (§9, §12, §24.4): evidencia de una ejecución real, ligada a git y hashes."""
    run_id: str
    task_id: str = ""
    argv: list = field(default_factory=list)
    cwd: str = ""
    exit_code: Optional[int] = None
    stdout_hash: str = ""
    stderr_hash: str = ""
    artifact_hashes: list = field(default_factory=list)
    git_revision: str = ""
    scope_id: str = ""
    veredicto_alcance: str = ""
    started_at: str = ""
    finished_at: str = ""

    def como_dict(self) -> dict:
        return {"run_id": self.run_id, "task_id": self.task_id, "argv": list(self.argv), "cwd": self.cwd,
                "exit_code": self.exit_code, "stdout_hash": self.stdout_hash, "stderr_hash": self.stderr_hash,
                "artifact_hashes": list(self.artifact_hashes), "git_revision": self.git_revision,
                "scope_id": self.scope_id, "veredicto_alcance": self.veredicto_alcance,
                "started_at": self.started_at, "finished_at": self.finished_at}


def _sc_revision_git(raiz) -> str:
    try:
        r = subprocess.run(["git", "-C", str(raiz), "rev-parse", "HEAD"], capture_output=True, text=True,
                           timeout=10, check=False)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def recibo_de_ejecucion(run_id: str, argv, *, cwd="", exit_code=None, stdout="", stderr="",
                        artefactos=None, raiz=None, scope_id="", veredicto="", task_id="") -> ReciboEjecucion:
    """Construye un ReciboEjecucion con hashes reales de la salida (no fabricables por un modelo)."""
    artefactos = artefactos or []
    return ReciboEjecucion(
        run_id=run_id, task_id=task_id, argv=list(argv), cwd=str(cwd),
        exit_code=exit_code, stdout_hash=_sc_sha256(stdout), stderr_hash=_sc_sha256(stderr),
        artifact_hashes=[_sc_sha256(a) for a in artefactos],
        git_revision=_sc_revision_git(raiz) if raiz is not None else "",
        scope_id=scope_id, veredicto_alcance=veredicto,
        started_at="", finished_at=datetime.now().isoformat(timespec="seconds"),
    )
