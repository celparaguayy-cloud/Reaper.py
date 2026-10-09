"""
Catálogo vivo de modelos — OFFLINE (REAPER AUTO-6-IA §4).

REAPER no debe depender de IDs de modelo hardcodeados. Este módulo normaliza candidatos descubiertos (p. ej.
de un directorio comunitario en Markdown) a fichas honestas y los guarda en una caché con TTL y estados de
verificación. Todo acá es OFFLINE y determinista: el parser trabaja sobre texto que ya se tiene; la descarga
real (con ETag/If-Modified-Since, allowlist de hosts, etc.) se inyecta como fetcher y queda PLANNED.

Reglas honestas del spec:
  - `null` NUNCA se interpreta como `true` ni como `0`.
  - Que un directorio diga "free" NO es prueba de coste cero: `free_tier_verified` solo lo pone una
    verificación real, nunca el parser.
  - El estado arranca en "unverified"; solo una petición real autorizada marca "verified".
  - Si la caché venció y no se puede refrescar, se sigue con lo último y se avisa "datos desactualizados".
"""

CONFIANZA_FUENTE = {"community_markdown": "baja", "provider_api": "media", "verified": "alta"}

# Encabezados de tabla → clave canónica (tolerante a sinónimos español/inglés).
_CAT_CANON = {
    "provider": "provider", "proveedor": "provider", "api": "provider",
    "model": "model_id", "modelo": "model_id", "model id": "model_id", "model_id": "model_id", "id": "model_id",
    "name": "display_name", "nombre": "display_name", "display name": "display_name",
    "url": "url", "endpoint": "url", "base url": "url", "base_url": "url",
    "free": "free", "gratis": "free", "free tier": "free", "free_tier": "free",
    "context": "context", "contexto": "context", "context length": "context", "context_tokens": "context",
    "tools": "tools", "tool calls": "tools", "herramientas": "tools",
}


@dataclass
class FichaModelo:
    provider: str
    model_id: str
    display_name: str = ""
    context_tokens: Optional[int] = None
    supports_tools: Optional[bool] = None
    supports_json: Optional[bool] = None
    supports_stream: Optional[bool] = None
    cost_usd_per_m_input: Optional[float] = None
    cost_usd_per_m_output: Optional[float] = None
    free_tier_verified: bool = False
    status: str = "unverified"              # unverified | verified | retired | quarantined
    last_checked_at: Optional[str] = None
    source: str = ""

    def gratis_verificado(self) -> bool:
        return self.free_tier_verified is True and self.status == "verified"

    def como_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def desde_dict(d: dict) -> "FichaModelo":
        campos = {f.name for f in fields(FichaModelo)}
        return FichaModelo(**{k: v for k, v in d.items() if k in campos})


def _cat_celdas(linea: str) -> list:
    linea = linea.strip()
    if linea.startswith("|"):
        linea = linea[1:]
    if linea.endswith("|"):
        linea = linea[:-1]
    return [c.strip() for c in linea.split("|")]


def _cat_es_separador(linea: str) -> bool:
    cuerpo = linea.strip().strip("|")
    return bool(cuerpo) and set(cuerpo.replace("|", "").strip()) <= set("-: ")


def parsear_tablas_markdown(texto: str) -> list:
    """
    Parser TOLERANTE de tablas Markdown. Devuelve filas como dicts {clave_canónica/encabezado: valor}.
    No revienta ante tablas rotas, filas incompletas, Unicode, duplicados, URLs raras ni columnas desconocidas.
    """
    filas = []
    lineas = (texto or "").splitlines()
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if "|" in linea and i + 1 < len(lineas) and _cat_es_separador(lineas[i + 1]):
            encabezados = [_CAT_CANON.get(c.lower(), c.lower()) for c in _cat_celdas(linea)]
            i += 2
            while i < len(lineas) and "|" in lineas[i] and not _cat_es_separador(lineas[i]):
                celdas = _cat_celdas(lineas[i])
                fila = {}
                for j, clave in enumerate(encabezados):
                    if not clave:
                        continue
                    fila[clave] = celdas[j].strip() if j < len(celdas) else ""   # filas incompletas → ""
                if fila:
                    filas.append(fila)
                i += 1
        else:
            i += 1
    return filas


def _cat_int(valor) -> Optional[int]:
    m = re.search(r"\d[\d,._]*", str(valor or ""))
    if not m:
        return None
    try:
        return int(re.sub(r"[,_.]", "", m.group(0)))
    except ValueError:
        return None


def _cat_url_valida(valor: str) -> str:
    valor = (valor or "").strip().strip("<>")
    return valor if re.match(r"^https?://[^\s]+$", valor) else ""


def normalizar_fichas(filas: list, source: str = "community_markdown") -> list:
    """Convierte filas crudas a FichaModelo con nulls honestos y dedup por (provider, model_id)."""
    vistos, salida = set(), []
    for fila in filas or []:
        model_id = (fila.get("model_id") or "").strip()
        if not model_id or model_id in ("-", "n/a", "na", "tbd"):
            continue                                   # sin id no es un modelo usable
        provider = (fila.get("provider") or "").strip().lower()
        clave = (provider, model_id)
        if clave in vistos:
            continue                                   # duplicado
        vistos.add(clave)
        ficha = FichaModelo(
            provider=provider, model_id=model_id,
            display_name=(fila.get("display_name") or model_id).strip(),
            context_tokens=_cat_int(fila.get("context")),     # null si no se pudo leer; NUNCA 0 por defecto
            source=_cat_url_valida(fila.get("url", "")) or source,
            # free_tier_verified SIEMPRE False desde el parser: un directorio no verifica coste cero.
        )
        salida.append(ficha)
    return salida


class CatalogoModelos:
    """Caché del catálogo con TTL, metadatos de procedencia y estados. Offline por defecto."""

    def __init__(self, base=None, ttl_horas: int = 24):
        self.archivo = Path(base) if base else (BASE_DIR / "catalog_modelos.json")
        if self.archivo.is_dir():
            self.archivo = self.archivo / "catalog_modelos.json"
        self.ttl_horas = ttl_horas

    def _cargar(self) -> dict:
        try:
            datos = json.loads(self.archivo.read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def guardar(self, fichas: list, source_url: str = "", source_version: str = "",
                discovery: str = "community_markdown") -> None:
        meta = {"source_url": source_url, "source_version": source_version,
                "discovery": discovery, "confidence": CONFIANZA_FUENTE.get(discovery, "baja"),
                "retrieved_at": datetime.now().isoformat(timespec="seconds")}
        datos = {"meta": meta, "fichas": [f.como_dict() for f in fichas]}
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        escritura_atomica(self.archivo, json.dumps(datos, ensure_ascii=False, indent=1))

    def fichas(self) -> list:
        return [FichaModelo.desde_dict(d) for d in self._cargar().get("fichas", [])]

    def meta(self) -> dict:
        return self._cargar().get("meta", {})

    def vigente(self, ahora: Optional[datetime] = None) -> bool:
        ra = self.meta().get("retrieved_at")
        if not ra:
            return False
        try:
            t = datetime.fromisoformat(ra)
        except ValueError:
            return False
        ahora = ahora or datetime.now()
        return (ahora - t) <= timedelta(hours=self.ttl_horas)

    def estado(self) -> str:
        if not self._cargar().get("fichas"):
            return "vacío (sin catálogo; sincronizá para poblarlo)"
        return "actualizado" if self.vigente() else "datos desactualizados (caché vencida; sin red se usa igual)"

    def sincronizar_desde_markdown(self, texto: str, source_url: str = "", source_version: str = "") -> int:
        """Parsea un Markdown (ya obtenido) y actualiza la caché. Devuelve cuántas fichas quedaron."""
        fichas = normalizar_fichas(parsear_tablas_markdown(texto), "community_markdown")
        self.guardar(fichas, source_url=source_url, source_version=source_version, discovery="community_markdown")
        return len(fichas)

    def marcar_verificado(self, provider: str, model_id: str, **caps) -> bool:
        """Marca una ficha como 'verified' tras una comprobación REAL (no desde el directorio)."""
        datos = self._cargar()
        cambiado = False
        for d in datos.get("fichas", []):
            if d.get("provider") == provider and d.get("model_id") == model_id:
                d["status"] = "verified"
                d["last_checked_at"] = datetime.now().isoformat(timespec="seconds")
                for k, v in caps.items():
                    if k in d:
                        d[k] = v
                cambiado = True
        if cambiado:
            self.archivo.parent.mkdir(parents=True, exist_ok=True)
            escritura_atomica(self.archivo, json.dumps(datos, ensure_ascii=False, indent=1))
        return cambiado

    def gratis_verificados(self) -> list:
        return [f for f in self.fichas() if f.gratis_verificado()]
