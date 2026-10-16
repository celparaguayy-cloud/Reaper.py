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
    ayuda: str = ""          # explicación completa (la tabla recorta "cómo arreglarlo"); se imprime debajo si falla


def es_termux() -> bool:
    return "com.termux" in os.getenv("PREFIX", "") or bool(os.getenv("TERMUX_VERSION")) \
        or os.path.isdir("/data/data/com.termux")


_RE_SIN_VERSION = re.compile(r"unrecognized option|invalid option|illegal option|unknown option|^usage:",
                             re.IGNORECASE | re.MULTILINE)


def _ruta_corta(ruta: Path) -> str:
    """~/reaper en vez de /data/data/com.termux/files/home/reaper: más fácil de copiar en el teléfono."""
    try:
        return "~/" + ruta.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(ruta)


def _chequeo_clave(settings: Settings) -> Chequeo:
    """Clave del proveedor activo. Dice A QUÉ SERVIDOR va (un api_url propio, p. ej. nano-gpt.com, usa la variable
    del proveedor 'openai' y eso confunde) y cómo dejarla guardada sin que se pierda al cerrar Termux.
    Nunca muestra la clave."""
    variable = settings.variable_clave()
    if not variable:
        return Chequeo("clave API", True, "no hace falta")
    try:
        host = urllib.parse.urlparse(settings.url_api()).hostname or ""
    except ValueError:
        host = ""
    propio = PROVEEDORES.get(settings.proveedor, {}).get("url", "")
    destino = f" ({host})" if host and host not in propio else ""
    if obtener_clave_api(settings):
        return Chequeo("clave API", True, f"{variable} configurada{destino}")
    archivo = _ruta_corta(BASE_DIR / f".clave_{settings.proveedor}")
    arreglo = f"printf %s 'TU_KEY' > {archivo}"
    para = f"la clave de {host}" if host else f"la clave de {settings.proveedor}"
    ayuda = [f"Guardá {para} (queda guardada aunque cierres Termux):",
             f"  printf %s 'TU_KEY' > {archivo} && chmod 600 {archivo}",
             f"o solo para esta sesión:  export {variable}='TU_KEY'"]
    if (BASE_DIR / ".clave").is_file() and not _duenio_clave_legacy():
        # Una clave vieja en ~/reaper/.clave sin dueño declarado no se usa (aislamiento por proveedor).
        ayuda.append(f"Si tu clave ya está en {_ruta_corta(BASE_DIR / '.clave')} y es {para}: "
                     f"echo {settings.proveedor} > {_ruta_corta(BASE_DIR / '.clave_proveedor')}")
    return Chequeo("clave API", False, f"falta {variable}{destino}", arreglo, True, "\n".join(ayuda))


def _chequeo_comando(nombre: str, paquete: str, para: str, critico: bool = False) -> Chequeo:
    ruta = shutil.which(nombre)
    if ruta:
        version = ""
        try:
            salida = subprocess.run([nombre, "--version"], capture_output=True, text=True, timeout=8)
            texto = (salida.stdout or salida.stderr or "").strip()
            # Herramientas sin --version (termux-notification) contestan con un error de getopt: eso no es la
            # versión. Solo se muestra lo que salió con exit 0 y no parece un mensaje de uso; si no, la ruta.
            if salida.returncode == 0 and texto and not _RE_SIN_VERSION.search(texto):
                version = texto.splitlines()[0][:60]
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


def _chequeo_cuenta_openrouter(settings: Settings) -> Optional[Chequeo]:
    """Cupo de pedidos gratis de TU cuenta (50/día sin crédito, 1000 con ≥10 de crédito). Un proyecto grande necesita
    cientos de pedidos: mejor saberlo antes que a mitad de camino. Solo con OpenRouter y con clave."""
    if not usa_free_openrouter(settings):
        return None
    cuenta = cuenta_openrouter(clave_de_proveedor("openrouter", settings))
    if cuenta is None or cuenta.cupo_dia is None:
        return None
    poco = cuenta.quedan_hoy is not None and cuenta.quedan_hoy < 40
    return Chequeo("cupo gratis", not poco, cuenta.resumen_corto(),
                   "esperá a mañana o cargá crédito" if poco else
                   ("sin crédito: 50/día" if cuenta.sin_credito else ""),
                   ayuda=("Con 50 pedidos por día un /grande no termina en un día: REAPER se detiene limpio cuando "
                          "se agota y sigue con --grande continuar. Con al menos 10 de crédito comprado el cupo de "
                          "modelos :free sube a 1000 por día." if cuenta.sin_credito else ""))


def chequeos_sistema(settings: Settings) -> list[Chequeo]:
    chequeos = []
    version = sys.version_info
    chequeos.append(Chequeo("python", version >= (3, 9), f"{sys.version.split()[0]} ({sys.executable})",
                            "pkg upgrade python", version < (3, 9)))
    chequeos.append(Chequeo("sistema", True, "Termux en Android" if es_termux() else f"{platform.system()} {platform.machine()}"))
    chequeos.append(_chequeo_clave(settings))
    chequeos.append(_chequeo_red(settings.url_api()))
    cuenta = _chequeo_cuenta_openrouter(settings)
    if cuenta is not None:
        chequeos.append(cuenta)
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
        for c in criticos:
            # La tabla recorta la columna del arreglo: acá va entero, listo para copiar.
            ui.info(f"  {c.nombre}:")
            for linea in (c.ayuda or c.arreglo).splitlines():
                ui.info(f"    {linea}")
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
    destino = carpeta_app / "reaper.py"
    import py_compile
    temporal = None
    try:
        if origen.resolve() != destino.resolve():
            # Validar primero y reemplazar después: una actualización defectuosa
            # nunca debe sobreescribir la instalación que ya funciona.
            fd, nombre = tempfile.mkstemp(prefix=".reaper-8_10-", suffix=".py", dir=carpeta_app)
            os.close(fd)
            temporal = Path(nombre)
            shutil.copy2(origen, temporal)
            py_compile.compile(str(temporal), doraise=True)
            os.replace(temporal, destino)
            temporal = None
        else:
            py_compile.compile(str(destino), doraise=True)
    except (OSError, py_compile.PyCompileError) as e:
        ui.error(f"No pude copiar/compilar REAPER: {e}")
        return None
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
    prefijo = os.getenv("PREFIX")
    bin_dir = Path(prefijo) / "bin" if prefijo and es_termux() else Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    lanzador = bin_dir / "reaper"
    contenido = (
        "#!/usr/bin/env python3\n"
        "# Lanzador de REAPER (generado por --instalar). Importa el módulo para usar el bytecode cacheado.\n"
        "import sys\n"
        f"sys.path.insert(0, {str(carpeta_app)!r})\n"
        "import reaper\n"
        "sys.exit(reaper.main())\n"
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
