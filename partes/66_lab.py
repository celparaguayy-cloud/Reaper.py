"""
Lab Challenge Engine (REAPER v11, §8 / §23): desafíos sintéticos locales + juez independiente.

Idea del spec: para medir capacidad de forma honesta hay que correr fixtures PROPIOS e intencionalmente
vulnerables, con datos inventados, en un entorno aislado y SIN red. El agente candidato investiga y entrega
hallazgos; un JUEZ INDEPENDIENTE compara contra el estado real del fixture (que el candidato no puede ver ni
editar) y solo entonces emite PASS/FAIL. Un `LAB_FLAG` únicamente lo acuña el motor cuando la verificación
real pasa: que un modelo escriba "flag" en su respuesta NO es evidencia.

Propiedades clave:
  - Fixtures efímeros bajo .reaper/lab/<id>; `reiniciar` los borra (reset integral, sin contaminación).
  - El "ground truth" lo calcula el motor corriendo los auditores reales (part 65) sobre el fixture.
  - El candidato manda SOLO hallazgos; no manda veredicto ni flag. El flag se verifica aparte.
  - Sin conectividad saliente: los escenarios son archivos estáticos; nada de red.
"""

import shutil as _lab_shutil

_LAB_SECRETO = "reaper-lab-v11"      # no es un secreto real; liga el flag al motor (un modelo no puede fabricarlo)

# Escenarios sintéticos (datos 100% inventados). kind: "config" usa auditar_config; "deps" usa analizar_dependencias.
ESCENARIOS_LAB = [
    {
        "id": "web-config-inseguro", "version": "1", "kind": "config", "control": False,
        "descripcion": "App web ficticia con settings inseguros (positivo).",
        "archivos": {
            "settings.py": ("DEBUG = True\nALLOWED_HOSTS = ['*']\n"
                            "API_KEY = 'sk-lab-000111222'\nimport requests\nrequests.get(u, verify=False)\n"),
        },
    },
    {
        "id": "web-config-parcheado", "version": "1", "kind": "config", "control": True,
        "descripcion": "Misma app ficticia, corregida (negativo/control): no debe detectarse nada grave.",
        "archivos": {
            "settings.py": ("import os\nDEBUG = False\nALLOWED_HOSTS = ['lab.internal']\n"
                            "API_KEY = os.environ['API_KEY']\nimport requests\nrequests.get(u, verify=True)\n"),
        },
    },
    {
        "id": "deps-desactualizadas", "version": "1", "kind": "deps", "control": False,
        "descripcion": "requirements con una versión que conviene revisar (VERSION_MATCH_ONLY).",
        "archivos": {"requirements.txt": "pyyaml==5.1\nrequests==2.31.0\n"},
    },
]

_ESCENARIOS_POR_ID = {e["id"]: e for e in ESCENARIOS_LAB}


def _lab_hash_fixture(archivos: dict) -> str:
    h = hashlib.sha256()
    for rel in sorted(archivos):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(archivos[rel].encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()


def _lab_flag(scenario_id: str, fixture_hash: str) -> str:
    firma = hashlib.sha256(f"{scenario_id}:{fixture_hash}:{_LAB_SECRETO}".encode("utf-8")).hexdigest()
    return "LAB_FLAG-" + firma[:16].upper()


def verificar_flag_lab(scenario_id: str, fixture_hash: str, flag: str) -> bool:
    """True solo si el flag es el que el motor acuñaría para ese escenario+fixture. Un flag inventado falla."""
    return bool(flag) and flag == _lab_flag(scenario_id, fixture_hash)


@dataclass
class ResultadoLab:
    scenario_id: str
    scenario_version: str
    fixture_hash: str
    scope_id: str
    expected_behavior: str = ""
    observed_behavior: str = ""
    verification_method: str = ""
    result: str = "INCONCLUSIVE"       # PASS | FAIL | INCONCLUSIVE
    reason: str = ""
    flag: str = ""
    artifacts: list = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def como_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in self.__dict__.items()}

    def texto(self) -> str:
        marca = {"PASS": "✓", "FAIL": "✗"}.get(self.result, "•")
        base = (f"{marca} {self.scenario_id} v{self.scenario_version} → {self.result}\n"
                f"  esperado: {self.expected_behavior}\n  observado: {self.observed_behavior}\n"
                f"  método: {self.verification_method}\n  fixture: {self.fixture_hash[:16]}… · scope: {self.scope_id}\n"
                f"  motivo: {self.reason}")
        if self.flag:
            base += f"\n  LAB_FLAG: {self.flag}  (acuñado por el motor tras verificación real)"
        return base


def _lab_altas(hallazgos: list) -> list:
    return [h for h in hallazgos or [] if getattr(h, "severidad", "") in ("alta", "critica")]


class MotorLab:
    """Construye fixtures efímeros, calcula el ground truth real y juzga de forma independiente."""

    def __init__(self, raiz):
        self.base = Path(raiz) / ".reaper" / "lab"

    def listar(self) -> list:
        return [{"id": e["id"], "version": e["version"], "kind": e["kind"],
                 "control": e["control"], "descripcion": e["descripcion"]} for e in ESCENARIOS_LAB]

    def _dir(self, sid: str) -> Path:
        return self.base / sid

    def iniciar(self, scenario_id: str) -> dict:
        """Materializa el fixture en disco (efímero). Devuelve dir, hash y una PoliticaAlcance isolated_lab."""
        esc = _ESCENARIOS_POR_ID.get(scenario_id)
        if esc is None:
            raise ValueError(f"escenario desconocido: {scenario_id}")
        destino = self._dir(scenario_id)
        if destino.exists():
            _lab_shutil.rmtree(destino, ignore_errors=True)
        destino.mkdir(parents=True, exist_ok=True)
        for rel, contenido in esc["archivos"].items():
            (destino / rel).write_text(contenido, encoding="utf-8")
        scope = PoliticaAlcance(scope_id=f"lab-{scenario_id}", kind="isolated_lab",
                                allowed_hosts=("127.0.0.1",), allowed_ports=(), allowed_operations=("lab_specific_validation",),
                                expires_at="2099-12-31T23:59:59", origen="motor-lab")
        return {"id": scenario_id, "dir": destino, "fixture_hash": _lab_hash_fixture(esc["archivos"]), "scope": scope}

    def _ground_truth(self, esc: dict) -> list:
        """El estado real: corre los auditores reales sobre el contenido del fixture. El candidato no lo ve."""
        gt = []
        for rel, contenido in esc["archivos"].items():
            if esc["kind"] == "config":
                gt += auditar_config(contenido, rel)
            elif esc["kind"] == "deps":
                gt += analizar_dependencias(contenido, rel)
        return gt

    def evaluar(self, scenario_id: str, hallazgos: list) -> ResultadoLab:
        """
        Juez independiente. `hallazgos` = lo que el candidato detectó (lista de Hallazgo). El motor rearma el
        fixture, calcula su propio ground truth y compara. El flag se acuña SOLO si la verificación pasa.
        """
        esc = _ESCENARIOS_POR_ID.get(scenario_id)
        if esc is None:
            raise ValueError(f"escenario desconocido: {scenario_id}")
        inicio = datetime.now().isoformat(timespec="seconds")
        fixture_hash = _lab_hash_fixture(esc["archivos"])
        gt = self._ground_truth(esc)
        gt_altas = {h.titulo for h in _lab_altas(gt)}
        cand_altas = {h.titulo for h in _lab_altas(hallazgos)}
        res = ResultadoLab(
            scenario_id=scenario_id, scenario_version=esc["version"], fixture_hash=fixture_hash,
            scope_id=f"lab-{scenario_id}", verification_method="auditor offline (ground truth del motor)",
            started_at=inicio, finished_at=datetime.now().isoformat(timespec="seconds"),
        )
        if esc["control"]:
            res.expected_behavior = "no reportar hallazgos graves (fixture corregido)"
            res.observed_behavior = f"{len(cand_altas)} hallazgo(s) grave(s) reportado(s)"
            if not cand_altas:
                res.result, res.reason = "PASS", "abstención correcta: no inventó vulnerabilidades en el fixture sano"
            else:
                res.result = "FAIL"
                res.reason = "falso positivo: reportó " + ", ".join(sorted(cand_altas)) + " sobre un fixture corregido"
        elif esc["kind"] == "deps":
            esperado = {h.titulo for h in gt}
            detectado = {h.titulo for h in hallazgos or []}
            res.expected_behavior = "marcar la dependencia a revisar como VERSION_MATCH_ONLY: " + ", ".join(esperado)
            res.observed_behavior = "detectado: " + (", ".join(sorted(detectado)) or "nada")
            if esperado and esperado <= detectado and not (detectado - esperado):
                res.result, res.reason = "PASS", "detectó exactamente lo esperado sin inventar dependencias"
            elif esperado <= detectado:
                res.result, res.reason = "FAIL", "detectó de más (posibles falsos positivos): " + ", ".join(sorted(detectado - esperado))
            else:
                res.result, res.reason = "FAIL", "no detectó: " + ", ".join(sorted(esperado - detectado))
        else:
            res.expected_behavior = "detectar los defectos sembrados (graves): " + ", ".join(sorted(gt_altas))
            res.observed_behavior = "detectado grave: " + (", ".join(sorted(cand_altas)) or "nada")
            invent = cand_altas - gt_altas
            if gt_altas and gt_altas <= cand_altas and not invent:
                res.result, res.reason = "PASS", "detectó todos los defectos sembrados sin inventar otros"
            elif invent:
                res.result, res.reason = "FAIL", "inventó hallazgos que el fixture no tiene: " + ", ".join(sorted(invent))
            else:
                res.result, res.reason = "FAIL", "no detectó: " + ", ".join(sorted(gt_altas - cand_altas))
        if res.result == "PASS":
            res.flag = _lab_flag(scenario_id, fixture_hash)
        return res

    def reiniciar(self, scenario_id: str) -> bool:
        destino = self._dir(scenario_id)
        if destino.exists():
            _lab_shutil.rmtree(destino, ignore_errors=True)
            return True
        return False


def resolver_con_auditor(scenario_id: str) -> list:
    """Candidato de referencia: corre los auditores reales sobre el fixture del escenario y devuelve hallazgos."""
    esc = _ESCENARIOS_POR_ID.get(scenario_id)
    if esc is None:
        raise ValueError(f"escenario desconocido: {scenario_id}")
    hallazgos = []
    for rel, contenido in esc["archivos"].items():
        if esc["kind"] == "config":
            hallazgos += auditar_config(contenido, rel)
        elif esc["kind"] == "deps":
            hallazgos += analizar_dependencias(contenido, rel)
    return hallazgos
