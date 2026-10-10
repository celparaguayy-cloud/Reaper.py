"""Workspace seguro: rutas confinadas, escritura atómica, listado y checkpoints con deshacer."""



IGNORAR_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "env", "node_modules", "dist", "build",
    ".next", ".cache", "coverage", ".idea", ".vscode", ".reaper", ".tox",
    ".gradle", "target",
}

ARCHIVOS_SENSIBLES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "credentials.json", "secrets.json", "secret.json",
    ".netrc", ".pgpass", ".htpasswd", ".npmrc", ".pypirc", ".git-credentials",
}
# Plantillas/ejemplos SIN secretos reales: se permiten (no rechazar algo inocuo por coincidencia parcial).
_SUFIJOS_ENV_EJEMPLO = (".example", ".sample", ".template", ".dist", ".ejemplo", ".defaults")
# Extensiones de material criptográfico privado (una clave pública .pub NO es secreto).
_EXT_SENSIBLES = {".pem", ".key", ".p12", ".pfx", ".pkcs12", ".keystore", ".jks"}


def es_archivo_sensible(nombre: str) -> bool:
    """
    ¿El CONTENIDO de este archivo es secreto y no debe leerse ni mandarse a un modelo? (R-002).
    Deny-by-default ACOTADO: bloquea credenciales, claves privadas y variantes `.env.*` reales, pero NO
    rechaza archivos inocuos por coincidencia parcial (p.ej. `environment.py`, `.env.example`, `key.pub`).
    """
    base = (nombre or "").strip().lower()
    if not base:
        return False
    if base in ARCHIVOS_SENSIBLES:
        return True
    if base.endswith(".pub"):                      # clave pública: no es secreto
        return False
    if base == ".env" or base.startswith(".env."):
        return not any(base.endswith(suf) for suf in _SUFIJOS_ENV_EJEMPLO)
    if Path(base).suffix in _EXT_SENSIBLES:
        return True
    if re.fullmatch(r"id_(rsa|dsa|ecdsa|ed25519)(_sk)?", base):  # claves SSH privadas (no `id_generator`)
        return True
    return False

EXTENSIONES_TEXTO = {
    ".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".html", ".htm",
    ".css", ".scss", ".sql", ".go", ".rs", ".java", ".kt", ".php", ".rb",
    ".c", ".h", ".cpp", ".hpp", ".lua", ".ini", ".cfg", ".xml", ".svg",
    ".webmanifest", ".csv", ".env.example", ".gitignore",
}

NOMBRES_TEXTO = {
    "Makefile", "Dockerfile", "requirements.txt", "package.json",
    "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", "README",
    "LICENSE", ".gitignore", "REAPER.md",
}

PATRONES_SECRETOS = [
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\b(\s*[:=]\s*)[\"']?([^\s\"']{6,})"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]

MAX_BYTES_LECTURA = 1_000_000


class ErrorRuta(ValueError):
    pass


def redactar_secretos(texto: str) -> str:
    limpio = PATRONES_SECRETOS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTADO]", texto)
    for patron in PATRONES_SECRETOS[1:]:
        limpio = patron.sub("[REDACTADO]", limpio)
    return limpio


def escritura_atomica(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, temporal = tempfile.mkstemp(prefix=f".{ruta.name}.", suffix=".tmp", dir=str(ruta.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        if ruta.exists():
            try:
                shutil.copymode(ruta, temporal)
            except OSError:
                pass
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def es_binario(ruta: Path) -> bool:
    try:
        with open(ruta, "rb") as f:
            return b"\0" in f.read(2048)
    except OSError:
        return True


def diff_unificado(antes: str, despues: str, rel: str) -> str:
    return "".join(
        difflib.unified_diff(
            antes.splitlines(keepends=True),
            despues.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            n=2,
        )
    )


class Workspace:
    def __init__(self, raiz: Path, checkpoints_dir: Optional[Path] = None):
        self.raiz = Path(raiz).expanduser().resolve()
        if not self.raiz.is_dir():
            raise ErrorRuta(f"No es una carpeta: {self.raiz}")
        if checkpoints_dir is None:
            checkpoints_dir = CHECKPOINTS_DIR
        clave = hashlib.sha1(str(self.raiz).encode()).hexdigest()[:10]
        self.checkpoints = Checkpoints(self, Path(checkpoints_dir) / f"{self.raiz.name}_{clave}")
        self._ignorar: list[str] = []
        self._gitignore_mtime: Optional[float] = None

    # ------------------------------------------------------------ rutas
    def ruta(self, rel: str, *, escribir: bool = False) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise ErrorRuta("Ruta vacía.")
        texto = rel.strip().strip("`'\"").strip()
        if "<" in texto:
            # Basura de un modelo torpe: "src/db.py</script>" o "app.py</path>". Ninguna ruta real lleva etiquetas.
            texto = re.sub(r"\s*</?[A-Za-z_][\w:-]*\s*/?>.*$", "", texto).strip()
        if texto.startswith("./"):
            texto = texto[2:]
        candidato = Path(os.path.expandvars(texto)).expanduser()
        if not candidato.is_absolute():
            candidato = self.raiz / candidato
        destino = candidato.resolve()
        try:
            relativa = destino.relative_to(self.raiz)
        except ValueError:
            raise ErrorRuta(f"Ruta fuera del workspace: {rel}") from None
        if escribir:
            if es_archivo_sensible(destino.name):
                raise ErrorRuta(f"Archivo sensible protegido: {rel}")
            if relativa.parts and relativa.parts[0] == ".git":
                raise ErrorRuta("No se escribe dentro de .git")
            if destino == self.raiz:
                raise ErrorRuta("La ruta apunta a la raíz del workspace, no a un archivo.")
        return destino

    def rel(self, ruta: Path) -> str:
        try:
            return Path(ruta).resolve().relative_to(self.raiz).as_posix()
        except ValueError:
            return str(ruta)

    # ------------------------------------------------------------ lectura/escritura
    def leer(self, rel: str, *, permitir_sensible: bool = False) -> str:
        ruta = self.ruta(rel)
        if es_archivo_sensible(ruta.name) and not permitir_sensible:
            # R-002: bloquear la LECTURA de secretos, no solo la escritura. La excepción pide autorización
            # explícita (permitir_sensible=True) y, aun así, se devuelve con los secretos redactados.
            raise ErrorRuta(f"Archivo sensible protegido (no se lee su contenido): {rel}")
        if not ruta.is_file():
            raise FileNotFoundError(rel)
        if ruta.stat().st_size > MAX_BYTES_LECTURA:
            raise ValueError(f"Archivo demasiado grande para leer entero ({ruta.stat().st_size} bytes).")
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        return redactar_secretos(texto) if (permitir_sensible and es_archivo_sensible(ruta.name)) else texto

    def escribir(self, rel: str, contenido: str) -> Path:
        ruta = self.ruta(rel, escribir=True)
        if ruta.is_dir():
            raise ErrorRuta(f"{rel} es una carpeta.")
        self.checkpoints.registrar(self.rel(ruta))
        escritura_atomica(ruta, contenido)
        return ruta

    def borrar(self, rel: str) -> Path:
        """Borra un archivo guardando el original en el checkpoint (se recupera con /deshacer)."""
        ruta = self.ruta(rel, escribir=True)
        if ruta.is_dir():
            raise ErrorRuta(f"{rel} es una carpeta: solo se borran archivos.")
        if not ruta.is_file():
            raise FileNotFoundError(rel)
        self.checkpoints.registrar(self.rel(ruta))
        ruta.unlink()
        return ruta

    def mover(self, origen: str, destino: str) -> Path:
        desde = self.ruta(origen, escribir=True)
        hacia = self.ruta(destino, escribir=True)
        if not desde.is_file():
            raise FileNotFoundError(origen)
        if hacia.exists():
            raise ErrorRuta(f"Ya existe {destino}.")
        contenido = desde.read_text(encoding="utf-8", errors="replace")
        self.escribir(self.rel(hacia), contenido)
        self.borrar(self.rel(desde))
        return hacia

    def existe(self, rel: str) -> bool:
        try:
            return self.ruta(rel).is_file()
        except ErrorRuta:
            return False

    def hash(self, rel: str) -> Optional[str]:
        try:
            return hashlib.sha1(self.ruta(rel).read_bytes()).hexdigest()
        except (OSError, ErrorRuta):
            return None

    def carpeta_reaper(self) -> Path:
        return self.raiz / ".reaper"

    def notas(self, limite: int = 2500) -> str:
        """Notas persistentes que dejaron los agentes (save_note) en .reaper/notas.md."""
        ruta = self.carpeta_reaper() / "notas.md"
        try:
            return ruta.read_text(encoding="utf-8", errors="replace")[-limite:]
        except OSError:
            return ""

    # ------------------------------------------------------------ listado
    def _patrones_gitignore(self) -> list[str]:
        """Se recarga si .gitignore cambia (el agente o el usuario pueden editarlo en la sesión)."""
        archivo = self.raiz / ".gitignore"
        try:
            mtime = archivo.stat().st_mtime
        except OSError:
            self._ignorar, self._gitignore_mtime = [], None
            return self._ignorar
        if mtime != self._gitignore_mtime:
            patrones = []
            try:
                for linea in archivo.read_text(encoding="utf-8").splitlines():
                    linea = linea.strip()
                    if linea and not linea.startswith(("#", "!")):
                        patrones.append(linea)
            except OSError:
                pass
            self._ignorar, self._gitignore_mtime = patrones, mtime
        return self._ignorar

    def ignorado(self, rel: str, es_dir: bool) -> bool:
        nombre = rel.rsplit("/", 1)[-1]
        if es_dir and nombre in IGNORAR_DIRS:
            return True
        for patron in self._patrones_gitignore():
            solo_dir = patron.endswith("/")
            p = patron.strip("/")
            if solo_dir and not es_dir:
                continue
            if "/" in p:
                if fnmatch.fnmatch(rel, p):
                    return True
            elif fnmatch.fnmatch(nombre, p):
                return True
        return False

    def iterar(self, sub: str = ".", limite: int = 2000) -> Iterator[Path]:
        base = self.ruta(sub) if sub not in ("", ".") else self.raiz
        if base.is_file():
            yield base
            return
        contador = 0
        for actual, dirs, archivos in os.walk(base):
            rel_actual = self.rel(Path(actual))
            rel_actual = "" if rel_actual == "." else rel_actual
            dirs[:] = sorted(
                d for d in dirs
                if not self.ignorado(f"{rel_actual}/{d}".lstrip("/"), True)
            )
            for nombre in sorted(archivos):
                rel = f"{rel_actual}/{nombre}".lstrip("/")
                if self.ignorado(rel, False):
                    continue
                yield Path(actual) / nombre
                contador += 1
                if contador >= limite:
                    return

    def huella(self, limite: int = 3000) -> str:
        """Huella barata del estado del workspace (rutas, tamaños y fechas): cambia si algún archivo cambió."""
        h = hashlib.sha1()
        for ruta in self.iterar(limite=limite):
            try:
                st = ruta.stat()
            except OSError:
                continue
            h.update(f"{ruta}\0{st.st_size}\0{st.st_mtime_ns}\n".encode("utf-8", "replace"))
        return h.hexdigest()[:16]

    def es_texto(self, ruta: Path) -> bool:
        if es_archivo_sensible(ruta.name):     # búsquedas/símbolos/mapa/contexto NUNCA escanean secretos (R-002)
            return False
        return ruta.suffix.lower() in EXTENSIONES_TEXTO or ruta.name in NOMBRES_TEXTO

    def archivos_codigo(self, limite: int = 400) -> list[str]:
        return [self.rel(p) for p in self.iterar(limite=limite * 3) if self.es_texto(p)][:limite]

    def arbol(self, limite: int = 120) -> str:
        lineas = []
        total = 0
        for ruta in self.iterar(limite=5000):
            total += 1
            if len(lineas) < limite:
                lineas.append(self.rel(ruta))
        if not lineas:
            return "(workspace vacío)"
        if total > limite:
            lineas.append(f"... y {total - limite} archivos más (usá list_files o search_files)")
        return "\n".join(lineas)

    def es_git(self) -> bool:
        return (self.raiz / ".git").exists()

    def memoria(self, limite: int = 4000) -> str:
        for nombre in ("REAPER.md", "CLAUDE.md", "AGENTS.md"):
            ruta = self.raiz / nombre
            if ruta.is_file():
                try:
                    texto = ruta.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                return f"({nombre})\n" + texto[:limite]
        return ""

    def config_local(self) -> dict:
        ruta = self.raiz / ".reaper" / "config.json"
        try:
            data = json.loads(ruta.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}


class Checkpoints:
    """
    Antes de cada escritura se guarda el original del archivo dentro del
    checkpoint activo. Un checkpoint por pedido (o por tarea en /construir);
    los checkpoints de una misma build comparten 'grupo' para deshacerla entera.
    """

    def __init__(self, ws: Workspace, carpeta: Path):
        self.ws = ws
        self.carpeta = carpeta
        self.actual: Optional[int] = None
        self._lock = threading.RLock()

    def _dir(self, cid: int) -> Path:
        return self.carpeta / f"{cid:05d}"

    def _manifiesto(self, cid: int) -> dict:
        try:
            return json.loads((self._dir(cid) / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"id": cid, "etiqueta": "?", "grupo": cid, "fecha": "", "archivos": {}}

    def _guardar(self, cid: int, manifiesto: dict) -> None:
        destino = self._dir(cid) / "manifest.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        escritura_atomica(destino, json.dumps(manifiesto, ensure_ascii=False, indent=1))

    def ids(self) -> list[int]:
        if not self.carpeta.is_dir():
            return []
        return sorted(int(p.name) for p in self.carpeta.iterdir() if p.is_dir() and p.name.isdigit())

    def iniciar(self, etiqueta: str, grupo: Optional[int] = None) -> int:
        with self._lock:
            existentes = self.ids()
            cid = (existentes[-1] + 1) if existentes else 1
            self._guardar(cid, {
                "id": cid,
                "etiqueta": etiqueta[:120],
                "grupo": grupo if grupo is not None else cid,
                "fecha": datetime.now().isoformat(timespec="seconds"),
                "archivos": {},
            })
            self.actual = cid
            return cid

    def registrar(self, rel: str) -> None:
        with self._lock:
            if self.actual is None:
                self.iniciar("cambios sueltos")
            cid = self.actual
            man = self._manifiesto(cid)
            if rel in man["archivos"]:
                return
            origen = self.ws.raiz / rel
            if origen.is_file():
                copia = f"files/{len(man['archivos']):04d}"
                destino = self._dir(cid) / copia
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origen, destino)
                man["archivos"][rel] = {"nuevo": False, "copia": copia}
            else:
                man["archivos"][rel] = {"nuevo": True}
            self._guardar(cid, man)

    def descartar_si_vacio(self, cid: int) -> None:
        with self._lock:
            if cid in self.ids() and not self._manifiesto(cid)["archivos"]:
                shutil.rmtree(self._dir(cid), ignore_errors=True)
                if self.actual == cid:
                    self.actual = None

    def listar(self) -> list[dict]:
        return [self._manifiesto(c) for c in self.ids()]

    def archivos_desde(self, cid: int) -> list[str]:
        vistos: dict[str, None] = {}
        for c in self.ids():
            if c >= cid:
                for rel in self._manifiesto(c)["archivos"]:
                    vistos.setdefault(rel, None)
        return list(vistos)

    def _origen(self, rel: str, desde: int) -> tuple[str, Optional[Path]]:
        """('nuevo', None) si no existía, ('copia', ruta_backup) o ('sin_cambios', None)."""
        for c in self.ids():
            if c < desde:
                continue
            info = self._manifiesto(c)["archivos"].get(rel)
            if info is None:
                continue
            if info.get("nuevo"):
                return "nuevo", None
            return "copia", self._dir(c) / info["copia"]
        return "sin_cambios", None

    def original(self, rel: str, desde: int) -> Optional[str]:
        """Contenido de rel al inicio del checkpoint 'desde' (None si no existía)."""
        tipo, copia = self._origen(rel, desde)
        if tipo == "nuevo":
            return None
        ruta = copia if tipo == "copia" else self.ws.raiz / rel
        try:
            return ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def diff_desde(self, cid: int, rels: Optional[list[str]] = None) -> str:
        partes = []
        for rel in rels or self.archivos_desde(cid):
            antes = self.original(rel, cid) or ""
            ruta = self.ws.raiz / rel
            despues = ruta.read_text(encoding="utf-8", errors="replace") if ruta.is_file() else ""
            if antes != despues:
                partes.append(diff_unificado(antes, despues, rel))
        return "\n".join(partes)

    def inicio_grupo(self, cid: Optional[int] = None) -> Optional[int]:
        ids = self.ids()
        if not ids:
            return None
        objetivo = cid if cid is not None else ids[-1]
        grupo = self._manifiesto(objetivo).get("grupo", objetivo)
        return min(c for c in ids if self._manifiesto(c).get("grupo", c) == grupo or c == objetivo)

    def deshacer(self, cid: Optional[int] = None) -> list[str]:
        """Restaura el estado previo a 'cid' (por defecto, el último grupo). Devuelve archivos tocados."""
        with self._lock:
            desde = cid if cid is not None else self.inicio_grupo()
            if desde is None:
                return []
            tocados = []
            for rel in self.archivos_desde(desde):
                tipo, copia = self._origen(rel, desde)
                ruta = self.ws.raiz / rel
                if tipo == "nuevo":
                    if ruta.is_file():
                        ruta.unlink()
                        tocados.append(rel)
                elif tipo == "copia" and copia is not None and copia.is_file():
                    if not ruta.is_file() or ruta.read_bytes() != copia.read_bytes():
                        ruta.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(copia, ruta)
                        tocados.append(rel)
            for c in self.ids():
                if c >= desde:
                    shutil.rmtree(self._dir(c), ignore_errors=True)
            self.actual = None
            return tocados
