"""
Copias aisladas del proyecto (sandbox) para que varios implementadores
trabajen en paralelo sin pisarse.

Cada candidato del torneo recibe una carpeta temporal con una copia del
proyecto. Las carpetas pesadas de dependencias (node_modules, .venv...) no se
copian: se enlazan con symlinks, así los tests corren igual sin gastar disco.
Al terminar, solo los archivos que cambió el candidato ganador se aplican al
workspace real (pasando por los checkpoints, así /deshacer sigue funcionando).

Funciona sin git: compara huellas SHA-1 de los archivos antes y después.
"""

DIRS_ENLAZAR = {"node_modules", ".venv", "venv", "env", "vendor", ".bundle", "Pods"}
# .reaper sí se copia (config local con el comando de tests), salvo sus subcarpetas pesadas.
DIRS_NO_COPIAR = (IGNORAR_DIRS - DIRS_ENLAZAR - {".reaper"}) | {".git"}
SUBDIRS_REAPER_NO_COPIAR = {"sandboxes", "informes", "planes", "logs", "cache"}
MAX_BYTES_ARCHIVO_COPIA = 20_000_000
MAX_BYTES_PROYECTO_COPIA = 400_000_000


class ErrorSandbox(RuntimeError):
    pass


def _carpeta_temporal_base() -> Optional[Path]:
    """En Termux $TMPDIR apunta a almacenamiento interno (soporta symlinks)."""
    for candidato in (os.getenv("REAPER_TMP"), os.getenv("TMPDIR")):
        if candidato and Path(candidato).is_dir() and os.access(candidato, os.W_OK):
            return Path(candidato)
    try:
        destino = BASE_DIR / "tmp"
        destino.mkdir(parents=True, exist_ok=True)
        return destino
    except OSError:
        return None


def tamano_proyecto(raiz: Path, limite: int = MAX_BYTES_PROYECTO_COPIA) -> int:
    """Bytes que ocuparía la copia (corta en cuanto supera 'limite')."""
    total = 0
    for actual, dirs, archivos in os.walk(raiz):
        rel = Path(actual).relative_to(raiz)
        dirs[:] = [d for d in dirs if d not in DIRS_NO_COPIAR and d not in DIRS_ENLAZAR
                   and not (rel.parts[:1] == (".reaper",) and d in SUBDIRS_REAPER_NO_COPIAR)]
        for nombre in archivos:
            try:
                tam = (Path(actual) / nombre).stat().st_size
            except OSError:
                continue
            if tam <= MAX_BYTES_ARCHIVO_COPIA:
                total += tam
            if total > limite:
                return total
    return total


@dataclass
class CambioArchivo:
    rel: str
    tipo: str  # nuevo | modificado | borrado
    antes: Optional[str] = None
    despues: Optional[str] = None

    def lineas_cambiadas(self) -> int:
        antes = (self.antes or "").splitlines()
        despues = (self.despues or "").splitlines()
        cambios = 0
        for op, i1, i2, j1, j2 in SequenceMatcher(None, antes, despues, autojunk=False).get_opcodes():
            if op != "equal":
                cambios += max(i2 - i1, j2 - j1)
        return cambios


class Copia:
    """Una copia aislada del workspace. Usar como context manager para limpiarla siempre."""

    def __init__(self, origen: Workspace, etiqueta: str = "copia", base: Optional[Path] = None):
        self.origen = origen
        self.etiqueta = re.sub(r"[^\w.-]+", "_", etiqueta)[:40] or "copia"
        self.base = base or _carpeta_temporal_base()
        self.carpeta: Optional[Path] = None
        self.raiz: Optional[Path] = None
        self.ws: Optional[Workspace] = None
        self.huella_inicial: dict[str, str] = {}
        self.enlaces: list[str] = []

    # ------------------------------------------------------------ ciclo de vida
    def __enter__(self) -> "Copia":
        self.crear()
        return self

    def __exit__(self, *exc) -> None:
        self.limpiar()

    def crear(self) -> "Copia":
        tam = tamano_proyecto(self.origen.raiz)
        if tam > MAX_BYTES_PROYECTO_COPIA:
            raise ErrorSandbox(
                f"El proyecto ocupa más de {MAX_BYTES_PROYECTO_COPIA // 1_000_000} MB sin dependencias; "
                "no se crean copias aisladas (el torneo queda desactivado para este proyecto)."
            )
        try:
            self.carpeta = Path(tempfile.mkdtemp(prefix=f"reaper_{self.etiqueta}_",
                                                 dir=str(self.base) if self.base else None))
        except OSError as e:
            raise ErrorSandbox(f"No pude crear la carpeta temporal: {e}") from e
        self.raiz = self.carpeta / self.origen.raiz.name
        try:
            self._copiar(self.origen.raiz, self.raiz)
        except OSError as e:
            self.limpiar()
            raise ErrorSandbox(f"No pude copiar el proyecto: {e}") from e
        self.ws = Workspace(self.raiz, checkpoints_dir=self.carpeta / "_checkpoints")
        self.huella_inicial = self.huella()
        return self

    def limpiar(self) -> None:
        if self.carpeta and self.carpeta.exists():
            # Primero los symlinks, para que rmtree nunca siga un enlace hacia el proyecto real.
            for rel in self.enlaces:
                enlace = (self.raiz or self.carpeta) / rel
                try:
                    if enlace.is_symlink():
                        enlace.unlink()
                except OSError:
                    pass
            shutil.rmtree(self.carpeta, ignore_errors=True)
        self.carpeta = None

    # ------------------------------------------------------------ copia
    def _copiar(self, origen: Path, destino: Path) -> None:
        destino.mkdir(parents=True, exist_ok=True)
        for actual, dirs, archivos in os.walk(origen):
            actual_p = Path(actual)
            rel = actual_p.relative_to(origen)
            destino_dir = destino / rel
            destino_dir.mkdir(parents=True, exist_ok=True)
            conservar = []
            for d in sorted(dirs):
                if d in DIRS_ENLAZAR:
                    enlace = destino_dir / d
                    try:
                        os.symlink(actual_p / d, enlace, target_is_directory=True)
                        self.enlaces.append((rel / d).as_posix())
                    except OSError:
                        pass  # sin symlinks (algunos almacenamientos): los tests que dependan de esto fallarán igual en todos
                    continue
                if d in DIRS_NO_COPIAR:
                    continue
                if rel.parts[:1] == (".reaper",) or (rel == Path(".") and d == ".reaper"):
                    if d in SUBDIRS_REAPER_NO_COPIAR:
                        continue
                if (actual_p / d).is_symlink():
                    continue
                conservar.append(d)
            dirs[:] = conservar
            for nombre in archivos:
                fuente = actual_p / nombre
                try:
                    if fuente.is_symlink() or fuente.stat().st_size > MAX_BYTES_ARCHIVO_COPIA:
                        continue
                    shutil.copy2(fuente, destino_dir / nombre)
                except OSError:
                    continue

    # ------------------------------------------------------------ comparación
    def _archivos(self, ws: Workspace) -> list[Path]:
        return [p for p in ws.iterar(limite=50_000) if not p.is_symlink()]

    def huella(self) -> dict[str, str]:
        assert self.ws is not None
        salida = {}
        for ruta in self._archivos(self.ws):
            try:
                salida[self.ws.rel(ruta)] = hashlib.sha1(ruta.read_bytes()).hexdigest()
            except OSError:
                continue
        return salida

    def cambios(self) -> list[CambioArchivo]:
        """Archivos que el candidato creó, modificó o borró respecto del inicio de la copia."""
        assert self.ws is not None and self.raiz is not None
        actual = self.huella()
        salida = []
        for rel in sorted(set(actual) | set(self.huella_inicial)):
            antes_h, despues_h = self.huella_inicial.get(rel), actual.get(rel)
            if antes_h == despues_h:
                continue
            ruta_copia = self.raiz / rel
            ruta_origen = self.origen.raiz / rel
            if despues_h and es_binario(ruta_copia):
                continue  # los agentes solo trabajan con texto; un binario nuevo suele ser basura de un test
            antes = ruta_origen.read_text(encoding="utf-8", errors="replace") if antes_h and ruta_origen.is_file() else None
            despues = ruta_copia.read_text(encoding="utf-8", errors="replace") if despues_h else None
            tipo = "nuevo" if antes_h is None else ("borrado" if despues_h is None else "modificado")
            salida.append(CambioArchivo(rel, tipo, antes, despues))
        return salida

    def diff(self, cambios: Optional[list[CambioArchivo]] = None) -> str:
        partes = []
        for c in cambios if cambios is not None else self.cambios():
            partes.append(diff_unificado(c.antes or "", c.despues or "", c.rel))
        return "\n".join(p for p in partes if p)

    def forzar_contenidos(self, contenidos: dict[str, Optional[str]]) -> list[str]:
        """
        Pisa archivos de la copia con contenidos fijos (p. ej. los tests de la
        especificación, para que un candidato no gane debilitándolos).
        None = el archivo no debe existir.
        """
        assert self.raiz is not None
        tocados = []
        for rel, contenido in contenidos.items():
            ruta = self.raiz / rel
            try:
                if contenido is None:
                    if ruta.is_file():
                        ruta.unlink()
                        tocados.append(rel)
                    continue
                if not ruta.is_file() or ruta.read_text(encoding="utf-8", errors="replace") != contenido:
                    escritura_atomica(ruta, contenido)
                    tocados.append(rel)
            except OSError:
                continue
        return tocados

    def aplicar_a(self, destino: Workspace, cambios: Optional[list[CambioArchivo]] = None,
                  excluir: Iterable[str] = ()) -> list[str]:
        """Aplica los cambios de la copia al workspace real, registrando checkpoints."""
        excluidos = set(excluir)
        aplicados = []
        self.conflictos: list[str] = []
        for c in cambios if cambios is not None else self.cambios():
            if c.rel in excluidos:
                continue
            try:
                if c.tipo == "borrado":
                    if destino.existe(c.rel):
                        destino.borrar(c.rel)
                        aplicados.append(c.rel)
                elif c.despues is not None:
                    if c.tipo == "nuevo" and destino.existe(c.rel):
                        # El candidato lo cree NUEVO, pero en el proyecto real YA existe: quedó fuera de la copia
                        # (archivo grande/binario) o se creó en paralelo. Pisarlo destruiría datos que el candidato
                        # nunca vio. No se aplica (data loss, p.ej. un .csv de 21 MB reemplazado por 13 bytes).
                        self.conflictos.append(c.rel)
                        continue
                    destino.escribir(c.rel, c.despues)
                    aplicados.append(c.rel)
            except (ErrorRuta, OSError):
                continue
        return aplicados


def copiar_contenidos(ws: Workspace, rels: Iterable[str]) -> dict[str, Optional[str]]:
    """Foto de los contenidos actuales de unos archivos (None si no existen)."""
    salida: dict[str, Optional[str]] = {}
    for rel in rels:
        try:
            ruta = ws.ruta(rel)
        except ErrorRuta:
            continue
        salida[ws.rel(ruta)] = ruta.read_text(encoding="utf-8", errors="replace") if ruta.is_file() else None
    return salida


def limpiar_sandboxes_viejos(horas: float = 12.0) -> int:
    """Borra copias temporales huérfanas (por ejemplo, de una sesión interrumpida)."""
    base = _carpeta_temporal_base()
    if not base or not base.is_dir():
        return 0
    limite = time.time() - horas * 3600
    borrados = 0
    for carpeta in base.glob("reaper_*"):
        try:
            if carpeta.is_dir() and carpeta.stat().st_mtime < limite:
                for enlace in carpeta.rglob("*"):
                    if enlace.is_symlink():
                        try:
                            enlace.unlink()
                        except OSError:
                            pass
                shutil.rmtree(carpeta, ignore_errors=True)
                borrados += 1
        except OSError:
            continue
    return borrados
