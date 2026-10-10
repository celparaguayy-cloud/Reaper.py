"""
Registro multi-proveedor (v9, Fase 6): rutear cada modelo a SU proveedor.

Antes REAPER hablaba con un único proveedor por sesión (un endpoint, una clave). Para coordinar varios
modelos independientes (p. ej. uno fuerte en OpenRouter, uno local en Ollama, uno directo de Venice) cada
modelo tiene que saber a qué endpoint va y con qué clave. InfoModelo.proveedor declara eso; cuando está vacío
el modelo usa el proveedor activo de la sesión, así el comportamiento de un solo proveedor no cambia.

Las claves SIEMPRE salen de variables de entorno (una por proveedor), nunca del repo.
"""


@dataclass(frozen=True)
class DestinoModelo:
    modelo: str           # id real del modelo
    proveedor: str        # openrouter | venice | ollama | openai | ...
    url: str              # endpoint de chat/completions
    clave_env: str        # nombre de la variable de entorno con la clave ("" = sin clave, p. ej. Ollama)

    def necesita_clave(self) -> bool:
        return bool(self.clave_env)

    def es_local(self) -> bool:
        """
        ¿El endpoint corre en el propio dispositivo (loopback/privado)? Bajo privacidad estricta solo lo
        local sale sin autorización explícita (R-001). Se mira la IP/host real, no el nombre del proveedor.
        """
        host = (urllib.parse.urlsplit(self.url).hostname or "").strip("[]").lower()
        if host in ("localhost", "ip6-localhost") or host.endswith(".local"):
            return True
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_loopback or ip.is_private or ip.is_link_local
        except ValueError:
            return False


def destino_modelo(nombre: str, settings: "Settings") -> DestinoModelo:
    """A qué proveedor/endpoint va un modelo. Si InfoModelo no fija proveedor, usa el activo de la sesión."""
    real = resolver_modelo(nombre)
    info = info_modelo(nombre)
    prov = getattr(info, "proveedor", "") or settings.proveedor or "openrouter"
    if prov not in PROVEEDORES:
        prov = settings.proveedor if settings.proveedor in PROVEEDORES else "openrouter"
    # el proveedor activo respeta el override de api_url; los demás usan su endpoint fijo
    url = settings.url_api() if prov == settings.proveedor else PROVEEDORES[prov]["url"]
    return DestinoModelo(real, prov, url, PROVEEDORES[prov]["clave"])


def clave_de_proveedor(proveedor: str, settings: "Settings") -> Optional[str]:
    """Clave para un proveedor (de entorno). Para el proveedor activo reutiliza la lógica completa."""
    datos = PROVEEDORES.get(proveedor, PROVEEDORES["openrouter"])
    variable = datos["clave"]
    if not variable:
        return "sin-clave"
    if proveedor == settings.proveedor:
        return obtener_clave_api(settings)
    valor = os.getenv(variable)
    if valor:
        return valor.strip()
    # Archivo por proveedor (dueño inequívoco); NUNCA el `.clave` heredado para otro proveedor (sin fuga).
    return _leer_clave_archivo(BASE_DIR / f".clave_{proveedor}")


def proveedores_de(settings: "Settings") -> dict:
    """Mapa proveedor → lista de modelos (alias) que REAPER usaría en esta sesión, para /modelos y diagnóstico."""
    usados = [settings.modelo] + list(settings.modelos_rol.values()) + list(settings.fallbacks)
    salida: dict = {}
    for nombre in usados:
        if not nombre:
            continue
        d = destino_modelo(nombre, settings)
        salida.setdefault(d.proveedor, [])
        if nombre not in salida[d.proveedor]:
            salida[d.proveedor].append(nombre)
    return salida
