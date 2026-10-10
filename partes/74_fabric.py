"""
Provider Fabric (REAPER V9 §3): manifiestos de proveedor validados, dedup honesto y contadores separados.

Un directorio con 500 modelos de 30 plataformas NO son 500 proveedores. Un gateway (OpenRouter) es 1
proveedor de API, no cientos. Este módulo:
  - define un ManifiestoProveedor declarativo (sin código ejecutable);
  - valida estructura y rechaza contenido ejecutable (JS/Python/shell) como definición;
  - deduplica por IDENTIDAD CANÓNICA (operador + estilo de API + dominio oficial), no por alias/modelo;
  - calcula contadores HONESTOS y separados (§0.1): descubiertos, con manifiesto válido, soportados,
    con credencial presente. Autenticado / chat operativo / free confirmado requieren peticiones reales
    (quedan en 0 / NO VERIFICADO hasta probarlos con tu clave).
"""

API_STYLES_SOPORTADOS = ("openai_chat_compatible", "openai_compat", "gemini", "anthropic_compat",
                         "cohere", "ollama", "openai")
TIPOS_PROVEEDOR = ("direct", "gateway", "proxy", "local")
_RE_EJECUTABLE = re.compile(r"(?:\bimport\b|\beval\(|\bexec\(|os\.system|subprocess|<script|\$\(|\blambda\b|;\s*rm\s)", re.I)


@dataclass
class ManifiestoProveedor:
    provider_id: str
    display_name: str = ""
    operator_id: str = ""
    provider_type: str = "direct"        # direct | gateway | proxy | local
    api_style: str = "openai_chat_compatible"
    official_domains: tuple = ()
    base_url: str = ""
    auth_env_var: str = ""
    free_policy: str = "unknown"         # unknown | free_claimed | free_confirmed | paid | trial
    source_url: str = ""
    status: str = "unverified"

    def es_gateway(self) -> bool:
        return self.provider_type in ("gateway", "proxy")

    def como_dict(self) -> dict:
        d = dict(self.__dict__)
        d["official_domains"] = list(self.official_domains)
        return d


def validar_manifiesto(datos: dict) -> tuple:
    """(ok, problemas). Rechaza faltantes, tipos inválidos y CONTENIDO EJECUTABLE como definición.

    Los proveedores locales (ollama) quedan exentos del requisito https y del formato de dominio público:
    corren en loopback, no son endpoints externos que haya que endurecer.
    """
    problemas = []
    if not isinstance(datos, dict):
        return False, ["el manifiesto no es un objeto"]
    if not datos.get("provider_id"):
        problemas.append("falta provider_id")
    if datos.get("provider_type") and datos["provider_type"] not in TIPOS_PROVEEDOR:
        problemas.append(f"provider_type inválido: {datos['provider_type']}")
    if datos.get("api_style") and datos["api_style"] not in API_STYLES_SOPORTADOS:
        problemas.append(f"api_style no soportado: {datos['api_style']}")
    es_local = datos.get("provider_type") == "local"
    dominios = datos.get("official_domains") or []
    if not dominios:
        problemas.append("faltan official_domains")
    if not es_local:
        for d in dominios:
            if not re.match(r"^[a-z0-9.\-]+\.[a-z]{2,}$", str(d).strip().lower()):
                problemas.append(f"dominio inválido: {d}")
        base = str(datos.get("base_url", ""))
        if base and not base.startswith("https://"):
            problemas.append("base_url debe ser https")
    # ningún valor del manifiesto puede traer código ejecutable
    for clave, valor in datos.items():
        if isinstance(valor, str) and _RE_EJECUTABLE.search(valor):
            problemas.append(f"contenido ejecutable en '{clave}': rechazado")
    return (not problemas, problemas)


def cargar_manifiesto(datos: dict) -> Optional[ManifiestoProveedor]:
    ok, _ = validar_manifiesto(datos)
    if not ok:
        return None
    campos = {f.name for f in fields(ManifiestoProveedor)}
    limpio = {k: v for k, v in datos.items() if k in campos}
    if isinstance(limpio.get("official_domains"), list):
        limpio["official_domains"] = tuple(str(d).strip().lower() for d in limpio["official_domains"])
    return ManifiestoProveedor(**limpio)


def identidad_canonica(m: ManifiestoProveedor) -> tuple:
    """Identidad para deduplicar: operador + estilo de API + dominio oficial principal (no alias ni modelo)."""
    operador = (m.operator_id or m.provider_id).strip().lower()
    dominio = (m.official_domains[0] if m.official_domains else "").lower()
    return (operador, m.api_style, dominio)


def manifiesto_desde_proveedor(prov_id: str) -> Optional[ManifiestoProveedor]:
    """Construye un manifiesto desde una entrada de PROVEEDORES (los built-in de REAPER)."""
    datos = PROVEEDORES.get(prov_id)
    if not datos:
        return None
    url = datos.get("url", "")
    dominio = re.sub(r"^https?://", "", url).split("/")[0].lower()
    tipo = "gateway" if prov_id == "openrouter" else ("local" if prov_id == "ollama" else "direct")
    estilo = "gemini" if prov_id == "gemini" else "openai_chat_compatible"
    return ManifiestoProveedor(
        provider_id=prov_id, display_name=prov_id, operator_id=prov_id, provider_type=tipo,
        api_style=estilo, official_domains=(dominio,) if dominio else (), base_url=url,
        auth_env_var=datos.get("clave", ""), source_url=url, status="unverified")


class RegistroProveedores:
    """Índice de manifiestos deduplicado por identidad canónica."""

    def __init__(self):
        self._por_identidad: dict = {}

    def agregar(self, m: ManifiestoProveedor) -> bool:
        ident = identidad_canonica(m)
        if ident in self._por_identidad:
            return False          # duplicado (mismo operador/estilo/dominio): no cuenta dos veces
        self._por_identidad[ident] = m
        return True

    def manifiestos(self) -> list:
        return list(self._por_identidad.values())

    def gateways(self) -> list:
        return [m for m in self._por_identidad.values() if m.es_gateway()]


def _hay_credencial(m: ManifiestoProveedor, settings) -> bool:
    if m.provider_type == "local":
        return True                           # ollama local: no necesita clave
    if not m.auth_env_var:
        return False
    if m.provider_id in PROVEEDORES:          # built-in: reutiliza la lógica de aislamiento de claves
        try:
            clave = clave_de_proveedor(m.provider_id, replace(settings, proveedor=m.provider_id))
            return bool(clave) and clave != "sin-clave"
        except (TypeError, ValueError, KeyError):
            pass
    return bool(os.getenv(m.auth_env_var))    # manifiesto externo: su propia variable, nunca la de otro


def contadores_proveedores(settings, manifiestos_extra: Sequence[ManifiestoProveedor] = ()) -> dict:
    """
    Contadores HONESTOS y separados (§0.1). Lo que no se puede verificar sin red queda en 0 / NO VERIFICADO.
    """
    reg = RegistroProveedores()
    for pid in PROVEEDORES:
        m = manifiesto_desde_proveedor(pid)
        if m:
            reg.agregar(m)
    for m in manifiestos_extra:
        reg.agregar(m)
    manifiestos = reg.manifiestos()
    validos = [m for m in manifiestos if validar_manifiesto(m.como_dict())[0]]
    soportados = [m for m in validos if m.api_style in API_STYLES_SOPORTADOS]
    con_credencial = [m for m in soportados if _hay_credencial(m, settings)]
    return {
        "providers_discovered": len(manifiestos),
        "providers_with_valid_manifest": len(validos),
        "providers_supported": len(soportados),
        "providers_credentials_present": len(con_credencial),
        "gateways": len(reg.gateways()),
        # Requieren peticiones reales con tus claves: no se inventan.
        "providers_authenticated": "NO VERIFICADO",
        "providers_chat_operational": "NO VERIFICADO",
        "providers_free_confirmed": "NO VERIFICADO",
        "meta_objetivo": 100,
    }
