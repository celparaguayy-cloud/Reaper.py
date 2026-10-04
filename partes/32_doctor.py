"""
/doctor e instalador.

/doctor revisa todo lo que REAPER necesita en Termux y dice exactamente qué
comando corre para arreglar cada cosa. /instalar crea el comando `reaper`:
copia este archivo a ~/reaper/app/ y genera un lanzador que lo IMPORTA, así
Python guarda el bytecode compilado y el arranque es rápido aunque el archivo
tenga decenas de miles de líneas.
"""


@dataclass
class Chequeo:
    nombre: str
    ok: bool
    detalle: str
    arreglo: str = ""
    critico: bool = False


def es_termux() -> bool:
    return "com.termux" in os.getenv("PREFIX", "") or bool(os.getenv("TERMUX_VERSION")) \
        or os.path.isdir("/data/data/com.termux")


def _chequeo_comando(nombre: str, paquete: str, para: str, critico: bool = False) -> Chequeo:
    ruta = shutil.which(nombre)
    if ruta:
        version = ""
        try:
            salida = subprocess.run([nombre, "--version"], capture_output=True, text=True, timeout=8)
            version = (salida.stdout or salida.stderr).strip().splitlines()[0][:60] if (salida.stdout or salida.stderr) else ""
        except (OSError, subprocess.TimeoutExpired, IndexError):
            version = ""
        return Chequeo(nombre, True, version or ruta)
    instalar = f"pkg install {paquete}" if es_termux() else f"instalá {paquete}"
    return Chequeo(nombre, False, f"no está ({para})", instalar, critico)


def _chequeo_modulo(modulo: str, para: str, pip: str = "") -> Chequeo:
    disponible = importlib.util.find_spec(modulo) is not None
    return Chequeo(modulo, disponible, "instalado" if disponible else f"no está ({para})",
                   "" if disponible else f"pip install {pip or modulo}")


def _chequeo_red(url: str) -> Chequeo:
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        puerto = urllib.parse.urlparse(url).port or (443 if url.startswith("https") else 80)
    except ValueError:
        return Chequeo("red", False, f"URL inválida: {url}", "revisá api_url en /config", True)
    if host in ("127.0.0.1", "localhost"):
        try:
            with socket.create_connection((host, puerto), timeout=3):
                return Chequeo("servidor local", True, f"{host}:{puerto} responde")
        except OSError:
            return Chequeo("servidor local", False, f"nada escuchando en {host}:{puerto}", "iniciá Ollama (ollama serve)", True)
    try:
        inicio = time.monotonic()
        with socket.create_connection((host, puerto), timeout=6):
            ms = (time.monotonic() - inicio) * 1000
        return Chequeo("red", True, f"{host} alcanzable ({ms:.0f} ms)")
    except socket.gaierror:
        return Chequeo("red", False, f"no resuelve {host} (DNS)", "revisá la conexión a internet", True)
    except OSError as e:
        return Chequeo("red", False, f"no conecta con {host}: {e}", "revisá la conexión o un proxy", True)


def _chequeo_symlinks() -> Chequeo:
    base = _carpeta_temporal_base()
    if not base:
        return Chequeo("carpeta temporal", False, "no hay carpeta temporal escribible", "export TMPDIR=$HOME/tmp", True)
    try:
        with tempfile.TemporaryDirectory(dir=str(base)) as tmp:
            destino = Path(tmp) / "x"
            destino.mkdir()
            os.symlink(destino, Path(tmp) / "enlace", target_is_directory=True)
        return Chequeo("copias aisladas", True, f"{base} (soporta symlinks)")
    except OSError as e:
        return Chequeo("copias aisladas", False, f"{base}: sin symlinks ({e})",
                       "export REAPER_TMP=$HOME/.cache/reaper (almacenamiento interno)")


def chequeos_sistema(settings: Settings) -> list[Chequeo]:
    chequeos = []
    version = sys.version_info
    chequeos.append(Chequeo("python", version >= (3, 9), f"{sys.version.split()[0]} ({sys.executable})",
                            "pkg upgrade python", version < (3, 9)))
    chequeos.append(Chequeo("sistema", True, "Termux en Android" if es_termux() else f"{platform.system()} {platform.machine()}"))
    variable = settings.variable_clave()
    clave = obtener_clave_api(settings)
    chequeos.append(Chequeo("clave API", bool(clave), (f"{variable} configurada" if clave and variable else
                                                        ("no hace falta" if not variable else f"falta {variable}")),
                            f'export {variable}="tu_key"  (agregalo a ~/.bashrc)' if not clave else "", not clave))
    chequeos.append(_chequeo_red(settings.url_api()))
    chequeos.append(_chequeo_modulo("httpx", "streaming más robusto; sin él se usa urllib"))
    chequeos.append(_chequeo_modulo("pyflakes", "nombres indefinidos más precisos (REAPER tiene un detector propio)"))
    chequeos.append(_chequeo_modulo("readline", "historial y autocompletado en el REPL", "gnureadline"))
    chequeos.append(_chequeo_modulo("pytest", "suite de tests (unittest funciona igual)"))
    chequeos.append(_chequeo_comando("node", "nodejs", "validar y testear JavaScript"))
    chequeos.append(_chequeo_comando("git", "git", "snapshots de builds verificadas"))
    chequeos.append(_chequeo_comando("ruff", "ruff", "lint y arreglos automáticos de Python"))
    chequeos.append(_chequeo_symlinks())
    try:
        uso = shutil.disk_usage(str(BASE_DIR if BASE_DIR.exists() else Path.home()))
        libre_gb = uso.free / 1e9
        chequeos.append(Chequeo("disco", libre_gb > 0.5, f"{libre_gb:.1f} GB libres",
                                "liberá espacio (las copias del torneo necesitan disco)" if libre_gb <= 0.5 else ""))
    except OSError:
        pass
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        prueba = BASE_DIR / ".prueba_escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
        chequeos.append(Chequeo("carpeta REAPER", True, str(BASE_DIR)))
    except OSError as e:
        chequeos.append(Chequeo("carpeta REAPER", False, f"{BASE_DIR}: {e}", "export REAPER_HOME=$HOME/reaper", True))
    if es_termux():
        compartido = Path.home() / "storage" / "shared"
        chequeos.append(Chequeo("almacenamiento", compartido.exists(),
                                "~/storage/shared disponible" if compartido.exists() else "sin acceso a /sdcard (opcional)",
                                "" if compartido.exists() else "termux-setup-storage"))
        chequeos.append(_chequeo_comando("termux-notification", "termux-api", "notificaciones al terminar builds largas"))
    return chequeos


def diagnostico_sistema(ui: UI, settings: Settings, llm=None, probar_modelo: bool = False) -> bool:
    chequeos = chequeos_sistema(settings)
    filas = []
    for c in chequeos:
        marca = f"{Tema.ok}✓{C.RESET}" if c.ok else (f"{Tema.error}✗{C.RESET}" if c.critico else f"{Tema.aviso}○{C.RESET}")
        filas.append([marca, c.nombre, recortar(c.detalle, 60).replace("\n", " "), c.arreglo])
    ui.titulo("DOCTOR REAPER")
    ui.tabla(filas, ["", "chequeo", "estado", "cómo arreglarlo"])
    if probar_modelo and llm is not None:
        try:
            inicio = time.monotonic()
            texto = llm.chat_simple("Respondé solo: OK", max_tokens=5, rol="doctor")
            ui.ok(f"el modelo responde ({formatear_duracion(time.monotonic() - inicio)}): {texto.strip()[:20]}")
        except LLMError as e:
            ui.error(f"el modelo no responde: {e}")
            return False
    criticos = [c for c in chequeos if c.critico and not c.ok]
    if criticos:
        ui.error(f"{len(criticos)} problema(s) crítico(s): REAPER no va a poder trabajar hasta arreglarlos.")
        return False
    opcionales = [c for c in chequeos if not c.ok]
    if opcionales:
        ui.aviso(f"Todo lo esencial está bien; {len(opcionales)} mejora(s) opcional(es) arriba.")
    else:
        ui.ok("Todo en orden. 🐉")
    return True


def archivo_actual() -> Optional[Path]:
    candidato = globals().get("__file__") or (sys.argv[0] if sys.argv else "")
    try:
        ruta = Path(candidato).resolve()
    except (OSError, RuntimeError):
        return None
    return ruta if ruta.is_file() and ruta.suffix == ".py" else None


def instalar_lanzador(ui: UI) -> Optional[Path]:
    origen = archivo_actual()
    if origen is None:
        ui.error("No encuentro el archivo de REAPER para instalarlo.")
        return None
    carpeta_app = BASE_DIR / "app"
    carpeta_app.mkdir(parents=True, exist_ok=True)
    destino = carpeta_app / "reaper_v7.py"
    import py_compile
    try:
        if origen.resolve() != destino.resolve():
            shutil.copy2(origen, destino)
        py_compile.compile(str(destino), doraise=True)
    except (OSError, py_compile.PyCompileError) as e:
        ui.error(f"No pude copiar/compilar REAPER: {e}")
        return None
    prefijo = os.getenv("PREFIX")
    bin_dir = Path(prefijo) / "bin" if prefijo and es_termux() else Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    lanzador = bin_dir / "reaper"
    contenido = (
        "#!/usr/bin/env python3\n"
        "# Lanzador de REAPER (generado por --instalar). Importa el módulo para usar el bytecode cacheado.\n"
        "import sys\n"
        f"sys.path.insert(0, {str(carpeta_app)!r})\n"
        "import reaper_v7\n"
        "sys.exit(reaper_v7.main())\n"
    )
    try:
        lanzador.write_text(contenido, encoding="utf-8")
        os.chmod(lanzador, 0o755)
    except OSError as e:
        ui.error(f"No pude crear {lanzador}: {e}")
        return None
    ui.ok(f"Instalado: {lanzador}")
    if str(bin_dir) not in os.getenv("PATH", "").split(os.pathsep):
        ui.aviso(f'  Agregá {bin_dir} al PATH: echo \'export PATH="{bin_dir}:$PATH"\' >> ~/.bashrc')
    ui.tenue("  Ahora podés escribir simplemente: reaper  (o reaper --proyecto ~/mi_app)")
    return lanzador


def notificar(titulo: str, texto: str) -> bool:
    """Notificación de Android al terminar algo largo (si termux-api está instalado)."""
    if not shutil.which("termux-notification"):
        return False
    try:
        subprocess.run(["termux-notification", "--title", titulo[:80], "--content", texto[:300],
                        "--id", "reaper"], timeout=10, capture_output=True)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
