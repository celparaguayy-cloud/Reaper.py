"""
Entrega verificada de archivos a Android (REAPER Ω §8).

El bug real: REAPER hizo `mv` a /sdcard/ y anunció éxito sin comprobar que el archivo llegó. Acá la entrega
es: COPIAR (no mover por defecto), calcular sha256 en ORIGEN y DESTINO, confirmar tamaño+hash+legibilidad, y
solo entonces reportar éxito con la RUTA EFECTIVA. Nunca "éxito" porque el comando devolvió 0. Un journal
permite /deshacer la exportación externa sin pisar cambios que el usuario hizo en el destino.
"""

import shutil as _ent_shutil

# Estados del ciclo de entrega (§8.1).
ESTADOS_ENTREGA = ("ARTIFACT_CREATED", "EXPORT_AUTHORIZED", "EXPORT_COMPLETED", "EXPORT_VERIFIED", "EXPORT_REPORTED")


@dataclass
class ReciboArtefacto:
    source: str
    destination: str
    size_bytes: int = 0
    sha256: str = ""
    copied_at: str = ""
    verified: bool = False
    external_destination: bool = False
    operation_id: str = ""
    estado: str = "ARTIFACT_CREATED"
    motivo: str = ""

    def como_dict(self) -> dict:
        return dict(self.__dict__)

    def texto(self) -> str:
        marca = "✓" if self.verified else "✗"
        base = (f"{marca} entrega {self.estado}\n  origen:  {self.source}\n  destino: {self.destination}\n"
                f"  bytes: {self.size_bytes} · sha256: {self.sha256[:16]}…")
        if not self.verified:
            base += f"\n  NO VERIFICADO: {self.motivo}"
        return base


def _ent_sha256(ruta: Path) -> tuple:
    h = hashlib.sha256()
    tam = 0
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
            tam += len(bloque)
    return h.hexdigest(), tam


def ruta_destino_android(nombre: str, preferida: Optional[str] = None, interno: Optional[Path] = None):
    """
    Elige una ruta de salida REAL y legible. Prefiere la autorizada; si no hay acceso a almacenamiento
    compartido, cae a una carpeta interna de REAPER (sin fingir que llegó a /sdcard). Devuelve (ruta, externo).
    """
    candidatas = []
    if preferida:
        candidatas.append(Path(preferida).expanduser())
    candidatas += [Path("~/storage/downloads").expanduser(), Path("/sdcard/Download"), Path("/sdcard")]
    for base in candidatas:
        try:
            if base.is_dir() and os.access(base, os.W_OK):
                return base / nombre, True
        except OSError:
            continue
    interno = Path(interno) if interno else (BASE_DIR / "exports")
    interno.mkdir(parents=True, exist_ok=True)
    return interno / nombre, False


class JournalEntregas:
    """Registro de exportaciones externas para poder deshacerlas con seguridad."""

    def __init__(self, base=None):
        self.archivo = (Path(base) if base else BASE_DIR) / "entregas.json"

    def _cargar(self) -> list:
        try:
            d = json.loads(self.archivo.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def registrar(self, recibo: ReciboArtefacto) -> None:
        datos = self._cargar()
        datos.append(recibo.como_dict())
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        escritura_atomica(self.archivo, json.dumps(datos[-200:], ensure_ascii=False, indent=1))

    def ultimo(self) -> Optional[dict]:
        datos = self._cargar()
        return datos[-1] if datos else None


def entregar_archivo(origen, destino, *, mover: bool = False, sobrescribir: bool = False,
                     externo: bool = False, journal: Optional[JournalEntregas] = None) -> ReciboArtefacto:
    """
    Copia (o mueve, solo si se pide Y verifica) un archivo y COMPRUEBA la llegada por sha256. Devuelve un
    ReciboArtefacto; verified=True solo si destino existe con el mismo tamaño y hash y es legible.
    """
    origen, destino = Path(origen), Path(destino)
    op = f"ent-{uuid.uuid4().hex[:12]}"
    r = ReciboArtefacto(source=str(origen), destination=str(destino), operation_id=op,
                        external_destination=externo)
    if not origen.is_file():
        r.motivo = "el origen no existe o no es un archivo"
        return r
    sha_o, tam_o = _ent_sha256(origen)
    r.sha256, r.size_bytes, r.estado = sha_o, tam_o, "ARTIFACT_CREATED"
    if destino.exists() and not sobrescribir:
        r.motivo = f"el destino ya existe (no sobrescribo sin permiso): {destino}"
        return r
    r.estado = "EXPORT_AUTHORIZED"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        _ent_shutil.copy2(origen, destino)      # COPIA, no mueve: el original se conserva
        r.estado = "EXPORT_COMPLETED"
    except OSError as e:
        r.motivo = f"falló la copia: {e}"
        return r
    try:
        sha_d, tam_d = _ent_sha256(destino)
    except OSError as e:
        r.motivo = f"no pude leer el destino para verificar: {e}"
        return r
    if sha_d == sha_o and tam_d == tam_o:
        r.verified, r.estado = True, "EXPORT_VERIFIED"
        if mover:
            try:
                origen.unlink()                 # borrar el original SOLO tras verificar
            except OSError:
                pass
        if journal is not None:
            journal.registrar(r)
    else:
        r.motivo = f"el destino no coincide (sha/ tamaño): origen {sha_o[:12]}/{tam_o} vs destino {sha_d[:12]}/{tam_d}"
    return r


def deshacer_entrega(recibo: dict) -> tuple:
    """
    Deshace una exportación: borra la copia en el destino SOLO si sigue igual que cuando se entregó (mismo
    sha). Si el usuario la modificó, NO la toca y avisa. Devuelve (ok, mensaje).
    """
    destino = Path(recibo.get("destination", ""))
    if not destino.exists():
        return True, "la copia ya no está en el destino; nada que deshacer"
    try:
        sha_actual, _ = _ent_sha256(destino)
    except OSError as e:
        return False, f"no pude leer el destino: {e}"
    if sha_actual != recibo.get("sha256"):
        return False, f"el archivo en {destino} fue modificado después de entregarlo: no lo borro (protejo tus datos)"
    try:
        destino.unlink()
        return True, f"borré la copia entregada en {destino}"
    except OSError as e:
        return False, f"no pude borrar {destino}: {e}"
