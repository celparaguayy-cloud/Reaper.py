"""
/reporte: un ZIP para mandar cuando algo sale mal (o bien) y hay que mejorar REAPER, en vez de copiar la terminal a
mano desde el teléfono. Junta lo que hace falta para diagnosticar sin volver a correr nada:

- LEEME.txt: versión, Python, sistema, modelo/equipo (sin claves), estado de /grande y del /construir pendiente;
- diagnostico.txt (lo mismo que /diagnostico), informes de las builds, el estado de /grande, el diario pendiente,
  los informes forenses y la cola de los logs de hoy y ayer;
- arbol.txt (qué archivos quedaron) y, salvo `sin-codigo`, el CÓDIGO del proyecto: lo que construyó REAPER.

Todo pasa por redactar_secretos y, al final, un escaneo de patrones de claves conocidas: si quedara alguna, se borra
del ZIP. Nunca entra .env, .clave*, *.pem/*.key, id_rsa ni la carpeta de claves de REAPER.
"""

_EXCLUIR_REPORTE = re.compile(r"(^|/)(\.env[^/]*|\.clave[^/]*|[^/]*\.(?:pem|key|p12|pfx|keystore|jks)|id_(?:rsa|ed25519|"
                              r"ecdsa)[^/]*|\.netrc|\.pypirc|\.npmrc|credentials[^/]*|secrets?\.[^/]+)$", re.I)
_PATRON_CLAVE_REPORTE = re.compile(r"(sk-or-v1-[A-Za-z0-9_-]{8,}|sk-ant-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9]{20,}|"
                                   r"gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|nvapi-[A-Za-z0-9_-]{12,}|"
                                   r"github_pat_[A-Za-z0-9_]{12,}|ghp_[A-Za-z0-9]{20,})")
MAX_REPORTE_BYTES = 15 * 1024 * 1024
MAX_ARCHIVO_REPORTE = 300 * 1024


def _limpiar_texto_reporte(texto: str) -> str:
    texto = redactar_secretos(texto or "")
    return _PATRON_CLAVE_REPORTE.sub("[REDACTADO]", texto)


def _cola(ruta: Path, lineas: int = 3000) -> str:
    try:
        contenido = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(contenido[-lineas:]) + "\n"


def _resumen_estado_reporte(ws: Workspace) -> list:
    lineas = []
    try:
        grande = ConstructorGrande(None, ws, Settings(), None).leer()
    except (ValueError, OSError):
        grande = {"estado": "ilegible"}
    if grande:
        etapas = (grande.get("maestro") or {}).get("etapas", [])
        hechas = sum(1 for e in etapas if e.get("estado") in ESTADOS_OK_ETAPA)
        lineas.append(f"/grande: {grande.get('estado')} · {hechas}/{len(etapas)} etapas verificadas")
        for e in etapas:
            lineas.append(f"  - etapa {e.get('id')} · {e.get('titulo')}: {e.get('estado')} · intentos "
                          f"{e.get('intentos')} · {e.get('pedidos', '?')} pedidos")
        if grande.get("motivo"):
            lineas.append(f"  motivo de parada: {grande.get('motivo')}")
    try:
        build = RegistroBuild(ws).leer()
    except (ValueError, OSError):
        build = {"estado": "ilegible"}
    if build:
        lineas.append(f"/construir pendiente: {build.get('estado')} · {recortar(str(build.get('pedido', '')), 160)}")
        for tid, est in (build.get("estados") or {}).items():
            lineas.append(f"  - tarea {tid}: {est}")
    return lineas or ["sin /grande ni /construir pendientes"]


def armar_reporte(ws: Workspace, settings: Settings, destino: Optional[Path] = None, con_codigo: bool = True,
                  con_doctor: bool = True) -> tuple:
    """Crea el ZIP. → (ruta, lista de lo incluido)."""
    nombre = re.sub(r"[^\w.-]+", "_", ws.raiz.name)[:40] or "proyecto"
    destino = destino or Path.home()
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"reaper_reporte_{nombre}_{datetime.now():%Y%m%d_%H%M%S}.zip"
    incluidos, total = [], 0

    def agregar(z, arcname: str, texto: str) -> None:
        nonlocal total
        datos = _limpiar_texto_reporte(texto).encode("utf-8")
        if total + len(datos) > MAX_REPORTE_BYTES:
            return
        z.writestr(arcname, datos)
        total += len(datos)
        incluidos.append(arcname)

    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        leeme = [f"REAPER {__version__} · reporte {datetime.now():%Y-%m-%d %H:%M}",
                 f"Python {sys.version.split()[0]} · {platform.system()} {platform.machine()}"
                 + (" · Termux" if es_termux() else ""),
                 f"Proyecto: {_ruta_corta(ws.raiz)}",
                 f"Modelo: {settings.modelo} · proveedor: {settings.proveedor} · respaldos: {', '.join(settings.fallbacks) or '—'}",
                 f"Roles: {json.dumps(settings.modelos_rol, ensure_ascii=False)}",
                 f"torneo={settings.torneo} candidatos={settings.candidatos} tests_primero={settings.tests_primero} "
                 f"max_tareas={settings.max_tareas} max_etapas={getattr(settings, 'max_etapas', '?')} "
                 f"rpm={settings.rpm} juez={getattr(settings, 'juez', '?')}",
                 "", *_resumen_estado_reporte(ws), "",
                 "Las claves se redactan; no entran .env, .clave*, *.key/*.pem ni id_rsa."]
        agregar(z, "LEEME.txt", "\n".join(leeme) + "\n")
        try:
            agregar(z, "diagnostico.txt", diagnostico_texto(settings) if con_doctor else "(omitido)")
        except (OSError, ValueError, RuntimeError) as e:
            agregar(z, "diagnostico.txt", f"no se pudo generar: {e}")
        carpeta = ws.carpeta_reaper()
        for patron, cuantos in (("informes/*.md", 25), ("forense/*.md", 5)):
            for archivo in sorted(carpeta.glob(patron))[-cuantos:]:
                agregar(z, f"reaper/{archivo.relative_to(carpeta).as_posix()}", _cola(archivo, 4000))
        for nombre_estado in ("proyecto_grande.json", "build_pendiente.json"):
            archivo = carpeta / nombre_estado
            if archivo.is_file():
                agregar(z, f"reaper/{nombre_estado}", _cola(archivo, 20000))
        for log in sorted(LOGS_DIR.glob("*.log"))[-2:] if LOGS_DIR.is_dir() else []:
            agregar(z, f"logs/{log.name}", _cola(log, 3000))
        arbol = []
        for p in ws.iterar(limite=3000):
            rel = ws.rel(p)
            try:
                tam = p.stat().st_size
            except OSError:
                continue
            arbol.append(f"{tam:>9}  {rel}")
            if (con_codigo and not _EXCLUIR_REPORTE.search(rel) and tam <= MAX_ARCHIVO_REPORTE
                    and ws.es_texto(p) and not rel.startswith(".reaper/")):
                try:
                    agregar(z, f"proyecto/{rel}", p.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
        agregar(z, "arbol.txt", "\n".join(arbol) + "\n")
    return ruta, incluidos


def _cmd_reporte(self: "App", arg: str) -> None:
    """/reporte [sin-codigo] — ZIP para mandar y mejorar REAPER (informes, estado, logs, árbol y código; sin claves)."""
    con_codigo = "sin-codigo" not in arg.lower() and "sin codigo" not in arg.lower()
    try:
        ruta, incluidos = armar_reporte(self.ws, self.settings, con_codigo=con_codigo)
    except (OSError, zipfile.BadZipFile) as e:
        self.ui.error(f"No pude armar el reporte: {e}")
        return
    self.ui.ok(f"Reporte listo: {_ruta_corta(ruta)} ({len(incluidos)} archivos, sin claves)")
    if not con_codigo:
        self.ui.tenue("  Sin el código del proyecto (pediste sin-codigo).")
    if es_termux():
        self.ui.tenue("  Para subirlo desde el teléfono: termux-setup-storage (una vez) y "
                      f"cp {_ruta_corta(ruta)} ~/storage/downloads/")


App.cmd_reporte = _cmd_reporte
