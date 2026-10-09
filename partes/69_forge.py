"""
Tool Forge (REAPER v11, §6 / §22): REAPER crea sus PROPIAS herramientas, con manifiesto y gate de calidad.

Pipeline: intención → especificación → código → tests → (gate real) → registro → disponible/reutilizable.
Principio clave del spec: "un script no entra al catálogo hasta pasar el gate de calidad". Acá el gate es la
EJECUCIÓN REAL de sus tests por el ExecutionBroker (part 67): una herramienta queda AVAILABLE solo si sus
tests pasaron de verdad (exit 0 observado), nunca por que un modelo diga que funciona. El manifiesto liga la
herramienta a un hash del código (no fabricable).

Esto cubre la creación de herramientas propias (offline, código generado por REAPER). El descubrimiento e
instalación de herramientas de terceros desde GitHub (§22.4+, con SupplyChainGate) queda PLANNED: requiere
red y evaluación de procedencia que no se habilitan de forma autónoma.
"""

import hashlib as _fg_hashlib

ESTADOS_HERRAMIENTA = ("SPECIFIED", "GENERATED", "TESTED", "VERIFIED", "AVAILABLE",
                       "FAILED", "QUARANTINED", "DISABLED")


@dataclass
class ManifiestoHerramienta:
    id: str
    version: str = "1"
    capabilities: tuple = ()
    resumen: str = ""
    lenguaje: str = "python"
    entrypoint: str = "tool.py"
    code_hash: str = ""
    dependencias: tuple = ()
    permisos: tuple = ("local_no_network",)
    modos: tuple = ("local",)
    autoria: str = "reaper-forge"
    estado: str = "SPECIFIED"
    verificacion: str = "unverified"        # unverified | tested | verified
    tests_resultado: str = ""
    limitaciones: tuple = ()
    creado: str = ""

    def disponible(self) -> bool:
        return self.estado == "AVAILABLE" and self.verificacion == "verified"

    def como_dict(self) -> dict:
        d = dict(self.__dict__)
        for k, v in d.items():
            if isinstance(v, tuple):
                d[k] = list(v)
        return d

    @staticmethod
    def desde_dict(d: dict) -> "ManifiestoHerramienta":
        campos = {f.name for f in fields(ManifiestoHerramienta)}
        datos = {k: v for k, v in d.items() if k in campos}
        for k in ("capabilities", "dependencias", "permisos", "modos", "limitaciones"):
            if k in datos and isinstance(datos[k], list):
                datos[k] = tuple(datos[k])
        return ManifiestoHerramienta(**datos)


class CatalogoHerramientas:
    """Índice persistente de herramientas forjadas (JSON bajo .reaper/forge/catalog.json)."""

    def __init__(self, raiz):
        self.dir = Path(raiz) / ".reaper" / "forge"
        self.archivo = self.dir / "catalog.json"

    def _cargar(self) -> dict:
        try:
            datos = json.loads(self.archivo.read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def guardar(self, manifiesto: ManifiestoHerramienta) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        datos = self._cargar()
        datos[manifiesto.id] = manifiesto.como_dict()
        escritura_atomica(self.archivo, json.dumps(datos, ensure_ascii=False, indent=1))

    def obtener(self, tool_id: str) -> Optional[ManifiestoHerramienta]:
        d = self._cargar().get(tool_id)
        return ManifiestoHerramienta.desde_dict(d) if d else None

    def listar(self) -> list:
        return [ManifiestoHerramienta.desde_dict(d) for d in self._cargar().values()]

    def por_capacidad(self, capacidad: str) -> list:
        return [m for m in self.listar() if capacidad in m.capabilities and m.disponible()]


def _fg_hash(codigo: str) -> str:
    return _fg_hashlib.sha256((codigo or "").encode("utf-8", "replace")).hexdigest()


class ForjaHerramientas:
    def __init__(self, raiz, broker=None):
        self.raiz = Path(raiz)
        self.catalogo = CatalogoHerramientas(raiz)
        self.broker = broker or BrokerEjecucion(raiz=raiz)

    def _dir_tool(self, tool_id: str) -> Path:
        return self.catalogo.dir / "tools" / re.sub(r"[^\w.\-]", "_", tool_id)

    def crear(self, manifiesto: ManifiestoHerramienta, codigo: str, test_codigo: str):
        """
        Materializa la herramienta + su test, corre el test por el broker (gate real) y registra el manifiesto.
        AVAILABLE solo si el test pasó (exit 0). Devuelve (manifiesto, recibo).
        """
        destino = self._dir_tool(manifiesto.id)
        destino.mkdir(parents=True, exist_ok=True)
        (destino / manifiesto.entrypoint).write_text(codigo, encoding="utf-8")
        (destino / "test.py").write_text(test_codigo, encoding="utf-8")
        manifiesto.code_hash = _fg_hash(codigo)
        manifiesto.creado = datetime.now().isoformat(timespec="seconds")
        manifiesto.estado = "GENERATED"

        recibo = self.broker.ejecutar(SolicitudEjecucion(
            argv=["python3", "test.py"], cwd=str(destino), timeout_s=60, task_id=f"forge:{manifiesto.id}"))

        if recibo.exit_code == 0:
            manifiesto.estado, manifiesto.verificacion = "AVAILABLE", "verified"
            manifiesto.tests_resultado = "PASS"
        else:
            manifiesto.estado = "FAILED" if recibo.veredicto_alcance.startswith("LOCAL") else "QUARANTINED"
            manifiesto.verificacion = "unverified"
            manifiesto.tests_resultado = f"FAIL (exit {recibo.exit_code}): " + recortar(recibo.stderr_preview, 300)
        self.catalogo.guardar(manifiesto)
        return manifiesto, recibo

    def ejecutar(self, tool_id: str, args=()):
        """Corre una herramienta AVAILABLE por el broker (local, sin red). Rechaza las no verificadas."""
        m = self.catalogo.obtener(tool_id)
        if m is None:
            raise ValueError(f"herramienta desconocida: {tool_id}")
        if not m.disponible():
            raise ValueError(f"herramienta {tool_id} no está AVAILABLE (estado {m.estado}); no se ejecuta")
        destino = self._dir_tool(tool_id)
        argv = ["python3", m.entrypoint] + [str(a) for a in args]
        return self.broker.ejecutar(SolicitudEjecucion(argv=argv, cwd=str(destino), timeout_s=60,
                                                       task_id=f"forge-run:{tool_id}"))


# Herramienta de demostración: un mini-detector de 'DEBUG = True' con su test (todo real, offline).
_FORGE_DEMO_CODIGO = (
    "import sys, re\n"
    "def detecta_debug(texto):\n"
    "    return bool(re.search(r'\\bDEBUG\\s*=\\s*True\\b', texto))\n"
    "if __name__ == '__main__':\n"
    "    data = open(sys.argv[1], encoding='utf-8').read() if len(sys.argv) > 1 else ''\n"
    "    print('VULN' if detecta_debug(data) else 'OK')\n"
)
_FORGE_DEMO_TEST = (
    "from tool import detecta_debug\n"
    "assert detecta_debug('DEBUG = True') is True\n"
    "assert detecta_debug('DEBUG = False') is False\n"
    "print('tests ok')\n"
)
# Variante con test que FALLA, para demostrar que el gate rechaza (no entra como AVAILABLE).
_FORGE_DEMO_TEST_MALO = (
    "from tool import detecta_debug\n"
    "assert detecta_debug('DEBUG = False') is True   # aserción incorrecta a propósito\n"
)


def manifiesto_demo(tool_id: str = "detector-debug") -> ManifiestoHerramienta:
    return ManifiestoHerramienta(
        id=tool_id, version="1", capabilities=("inspect_source_code",),
        resumen="Detecta 'DEBUG = True' en un archivo (herramienta de demostración forjada por REAPER).",
        entrypoint="tool.py", permisos=("local_no_network",),
        limitaciones=("heurística simple; un hallazgo requiere revisión contextual",))
