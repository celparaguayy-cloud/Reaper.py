"""Rutas, modelos, perfiles y configuración persistente de REAPER."""

BASE_DIR = Path(os.getenv("REAPER_HOME") or (Path.home() / "reaper")).expanduser()
PROJECTS_DIR = BASE_DIR / "proyectos"
CHECKPOINTS_DIR = BASE_DIR / "checkpoints"
SESIONES_DIR = BASE_DIR / "sesiones"
LOGS_DIR = BASE_DIR / "logs"
CACHE_DIR = BASE_DIR / "cache"
PLANTILLAS_USUARIO_DIR = BASE_DIR / "plantillas"
CONFIG_FILE = BASE_DIR / "config.json"
ESTADO_FILE = BASE_DIR / "estado.json"
LECCIONES_GLOBALES = BASE_DIR / "lecciones.md"
HISTORIAL_FILE = BASE_DIR / "historial_repl.txt"
COMANDOS_USUARIO_DIR = BASE_DIR / "comandos"
HERRAMIENTAS_USUARIO_DIR = BASE_DIR / "herramientas"
ESTADISTICAS_FILE = BASE_DIR / "estadisticas.json"

API_URL = os.getenv("REAPER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

PROVEEDORES = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "clave": "OPENROUTER_API_KEY",
        "nota": "por defecto; un solo key para cientos de modelos",
    },
    "venice": {
        "url": "https://api.venice.ai/api/v1/chat/completions",
        "clave": "VENICE_API_KEY",
        "nota": "API directa de Venice (modelos con ids propios de Venice)",
    },
    "ollama": {
        "url": "http://127.0.0.1:11434/v1/chat/completions",
        "clave": "",
        "nota": "modelos locales con Ollama (sin clave)",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "clave": "OPENAI_API_KEY",
        "nota": "cualquier API compatible con OpenAI (cambiá api_url)",
    },
}


@dataclass(frozen=True)
class InfoModelo:
    id: str
    contexto: int = 32768
    nivel: str = "base"  # base | fuerte
    nota: str = ""


INFO_MODELOS = {
    "venice": InfoModelo("cognitivecomputations/dolphin-mistral-24b-venice-edition", 32768, "base",
                         "Venice 24B: el caballo de batalla de REAPER"),
    "venice-free": InfoModelo("cognitivecomputations/dolphin-mistral-24b-venice-edition:free", 32768, "base",
                              "gratis, con límite de solicitudes"),
    "hermes": InfoModelo("nousresearch/hermes-3-llama-3.1-70b", 131072, "base", "70B, buen seguidor de formato"),
    "qwen": InfoModelo("qwen/qwen-2.5-coder-32b-instruct", 32768, "fuerte", "programación, 32B"),
    "qwen72": InfoModelo("qwen/qwen-2.5-72b-instruct", 32768, "fuerte", "general, 72B"),
    "qwen3-coder": InfoModelo("qwen/qwen3-coder", 262144, "fuerte", "programación agéntica, contexto enorme"),
    "deepseek": InfoModelo("deepseek/deepseek-chat", 65536, "fuerte", "muy bueno diagnosticando, barato"),
    "deepseek-r1": InfoModelo("deepseek/deepseek-r1", 65536, "fuerte", "razonamiento largo (lento)"),
    "devstral": InfoModelo("mistralai/devstral-small", 131072, "base", "24B entrenado para agentes de código"),
    "llama70": InfoModelo("meta-llama/llama-3.3-70b-instruct", 131072, "base", "70B general"),
}

MODELOS = {alias: info.id for alias, info in INFO_MODELOS.items()}

MODOS = ("confirmar", "auto-edicion", "auto")


def resolver_modelo(nombre: str) -> str:
    nombre = (nombre or "").strip()
    return MODELOS.get(nombre.lower(), nombre)


def info_modelo(nombre: str) -> InfoModelo:
    real = resolver_modelo(nombre)
    for info in INFO_MODELOS.values():
        if info.id == real:
            return info
    return InfoModelo(real, 32768, "base", "")


def es_modelo_gratis(nombre: str) -> bool:
    return resolver_modelo(nombre).endswith(":free")


@dataclass
class Settings:
    # Modelo principal y overrides por rol, p. ej. {"revisor": "qwen"}.
    modelo: str = MODELOS["venice"]
    modelos_rol: dict = field(default_factory=dict)
    # Modelos de respaldo si el principal falla (404, 402, caídas persistentes).
    fallbacks: list = field(default_factory=list)
    proveedor: str = "openrouter"
    api_url: str = ""

    temperatura: float = 0.2
    max_tokens: int = 6000
    # Venice 24B tiene 32k de contexto: REAPER compacta antes de llegar al límite.
    contexto_tokens: int = 32768
    timeout: int = 180
    reintentos: int = 4
    # Solicitudes por minuto (0 = sin límite; con modelos :free se usa 16 si queda en 0).
    rpm: int = 0

    # confirmar: pregunta antes de editar y de correr comandos.
    # auto-edicion: edita solo (con checkpoint para /deshacer), pregunta comandos.
    # auto: todo automático salvo comandos bloqueados.
    modo: str = "auto-edicion"

    max_pasos: int = 40
    max_pasos_sub: int = 25
    max_profundidad: int = 1
    max_llamadas_turno: int = 4
    max_reparaciones: int = 3
    max_revisiones: int = 2
    max_tareas: int = 8
    paralelo: int = 2
    qa: bool = True

    # --- v7: tests primero + torneo de implementadores ---------------
    tests_primero: bool = True
    torneo: bool = True
    candidatos: int = 3
    temperaturas: list = field(default_factory=lambda: [0.1, 0.4, 0.7])
    # Con modelos :free conviene 2 por el límite de solicitudes.
    paralelo_torneo: int = 2

    # --- v7: escalada a un modelo más fuerte --------------------------
    escalar: bool = True
    # v8: revertir solo las ediciones que dejan los tests peor que el mejor estado visto
    guardia_regresion: bool = True
    # v8: modo forense (aislar tests, estado compartido, bisección, hipótesis con experimentos)
    forense: bool = True
    umbral_forense: int = 3
    modelo_fuerte: str = "deepseek"
    umbral_escalada: int = 2

    # --- v7: lecciones entre sesiones ---------------------------------
    lecciones: bool = True
    max_lecciones_prompt: int = 8

    # --- v7: archivos largos sin romperse -----------------------------
    continuar_cortes: bool = True
    max_continuaciones: int = 8
    lineas_por_bloque: int = 160
    escritor_largo: bool = True

    # --- v7: calidad automática ---------------------------------------
    autofix: bool = True
    autofix_ruff: bool = True
    mapa_relevantes: bool = True
    max_relevantes: int = 8
    pistas_errores: bool = True
    git_snapshots: bool = True
    rama_git: str = "reaper/builds"

    # --- v7: extensiones ------------------------------------------------
    web: bool = True                 # herramienta fetch_url (leer documentación)
    dominios_web: list = field(default_factory=list)  # vacío = cualquiera (con confirmación fuera de modo auto)
    plugins: bool = True             # herramientas propias en ~/reaper/herramientas/*.py
    hooks: bool = True               # comandos antes/después de herramientas (.reaper/config.json → "hooks")
    idioma_prompts: str = "es"       # "en": instrucciones en inglés (respuestas en español)

    # --- v7: interfaz ---------------------------------------------------
    tema: str = "dragon"
    animacion: bool = True
    detalle: int = 1
    log: bool = True
    costo_maximo: float = 0.0

    exec_timeout: int = 90
    tests_timeout: int = 300

    def modelo_para(self, rol: str) -> str:
        return resolver_modelo(self.modelos_rol.get(rol) or self.modelo)

    def url_api(self) -> str:
        if self.api_url.strip():
            return self.api_url.strip()
        if os.getenv("REAPER_API_URL"):
            return os.environ["REAPER_API_URL"]
        return PROVEEDORES.get(self.proveedor, PROVEEDORES["openrouter"])["url"]

    def variable_clave(self) -> str:
        return PROVEEDORES.get(self.proveedor, PROVEEDORES["openrouter"])["clave"]

    def rpm_efectivo(self) -> int:
        if self.rpm > 0:
            return self.rpm
        modelos = [self.modelo] + list(self.modelos_rol.values())
        return 16 if any(es_modelo_gratis(m) for m in modelos) else 0

    def temperatura_candidato(self, indice: int) -> float:
        lista = [t for t in self.temperaturas if isinstance(t, (int, float))] or [0.1, 0.4, 0.7]
        if indice < len(lista):
            return float(lista[indice])
        return round(min(1.0, lista[-1] + 0.15 * (indice - len(lista) + 1)), 2)

    def validar(self) -> "Settings":
        """Lleva cada valor a un rango sano (un config.json editado a mano no debe romper nada)."""
        def acotar(nombre: str, minimo, maximo) -> None:
            valor = getattr(self, nombre)
            setattr(self, nombre, max(minimo, min(maximo, valor)))

        acotar("temperatura", 0.0, 2.0)
        acotar("max_tokens", 256, 64000)
        acotar("contexto_tokens", 4096, 2_000_000)
        acotar("timeout", 10, 1800)
        acotar("reintentos", 0, 10)
        acotar("rpm", 0, 600)
        acotar("max_pasos", 3, 400)
        acotar("max_pasos_sub", 3, 200)
        acotar("max_profundidad", 0, 3)
        acotar("max_llamadas_turno", 1, 10)
        acotar("max_reparaciones", 0, 10)
        acotar("max_revisiones", 0, 5)
        acotar("max_tareas", 1, 30)
        acotar("paralelo", 1, 8)
        acotar("candidatos", 1, 6)
        acotar("paralelo_torneo", 1, 6)
        acotar("umbral_escalada", 1, 10)
        acotar("max_lecciones_prompt", 0, 40)
        acotar("max_continuaciones", 0, 40)
        acotar("lineas_por_bloque", 40, 600)
        acotar("max_relevantes", 0, 30)
        acotar("detalle", 0, 2)
        acotar("costo_maximo", 0.0, 10_000.0)
        acotar("exec_timeout", 5, 3600)
        acotar("tests_timeout", 10, 7200)
        if self.modo not in MODOS:
            self.modo = "auto-edicion"
        if self.proveedor not in PROVEEDORES:
            self.proveedor = "openrouter"
        if self.tema not in TEMAS:
            self.tema = "dragon"
        if self.idioma_prompts not in ("es", "en"):
            self.idioma_prompts = "es"
        self.dominios_web = [str(d).strip().lower() for d in self.dominios_web if str(d).strip()]
        self.temperaturas = [max(0.0, min(2.0, float(t))) for t in self.temperaturas
                             if isinstance(t, (int, float)) and not isinstance(t, bool)] or [0.1, 0.4, 0.7]
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def desde_dict(cls, data: dict) -> "Settings":
        base = cls()
        tipos = {f.name: type(getattr(base, f.name)) for f in fields(cls)}
        valores = {}
        for clave, valor in (data or {}).items():
            tipo = tipos.get(clave)
            if tipo is None:
                continue
            if tipo is float and isinstance(valor, int) and not isinstance(valor, bool):
                valor = float(valor)
            if isinstance(valor, tipo) and not (tipo is int and isinstance(valor, bool)):
                valores[clave] = valor
        return cls(**valores).validar()


PERFILES = {
    "gratis": {
        "descripcion": "modelos :free, 2 candidatos, sin escalada paga, límite de 16 solicitudes/min",
        "valores": {"modelo": MODELOS["venice-free"], "paralelo": 1, "paralelo_torneo": 1,
                    "candidatos": 2, "rpm": 16, "escalar": False},
    },
    "rapido": {
        "descripcion": "sin torneo ni tests previos: un intento por tarea (barato y veloz)",
        "valores": {"torneo": False, "tests_primero": False, "max_revisiones": 1, "candidatos": 1},
    },
    "equilibrado": {
        "descripcion": "tests primero + torneo de 2, escalada a deepseek (recomendado)",
        "valores": {"torneo": True, "tests_primero": True, "candidatos": 2, "paralelo_torneo": 2,
                    "escalar": True, "max_revisiones": 1},
    },
    "maximo": {
        "descripcion": "torneo de 3 en paralelo, revisor, escalada y reparaciones extra",
        "valores": {"torneo": True, "tests_primero": True, "candidatos": 3, "paralelo_torneo": 3,
                    "escalar": True, "max_revisiones": 2, "max_reparaciones": 4},
    },
}


def aplicar_perfil(settings: Settings, nombre: str) -> list[str]:
    perfil = PERFILES.get((nombre or "").strip().lower())
    if not perfil:
        raise KeyError(nombre)
    cambios = []
    for clave, valor in perfil["valores"].items():
        if getattr(settings, clave) != valor:
            setattr(settings, clave, copy.deepcopy(valor))
            cambios.append(f"{clave}={valor}")
    settings.validar()
    return cambios


def asegurar_dirs() -> None:
    for carpeta in (BASE_DIR, PROJECTS_DIR, CHECKPOINTS_DIR, SESIONES_DIR, LOGS_DIR, CACHE_DIR):
        carpeta.mkdir(parents=True, exist_ok=True)


def cargar_settings(ruta: Optional[Path] = None) -> Settings:
    ruta = ruta or CONFIG_FILE
    settings = Settings()
    if ruta.exists():
        try:
            settings = Settings.desde_dict(json.loads(ruta.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            settings = Settings()

    if os.getenv("MODEL_NAME"):
        settings.modelo = resolver_modelo(os.environ["MODEL_NAME"])
    if os.getenv("REAPER_MODO") in MODOS:
        settings.modo = os.environ["REAPER_MODO"]
    if os.getenv("REAPER_PROVEEDOR") in PROVEEDORES:
        settings.proveedor = os.environ["REAPER_PROVEEDOR"]
    if settings.modo not in MODOS:
        settings.modo = "auto-edicion"
    return settings.validar()


def guardar_settings(settings: Settings, ruta: Optional[Path] = None) -> None:
    ruta = ruta or CONFIG_FILE
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ruta)


def settings_con_local(settings: Settings, local: dict) -> Settings:
    """Copia de settings con los overrides de .reaper/config.json del proyecto (claves 'settings')."""
    overrides = local.get("settings") if isinstance(local, dict) else None
    if not isinstance(overrides, dict) or not overrides:
        return settings
    combinado = settings.to_dict()
    combinado.update(overrides)
    return Settings.desde_dict(combinado)


def cargar_estado() -> dict:
    try:
        data = json.loads(ESTADO_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_estado(**valores) -> None:
    data = cargar_estado()
    data.update({k: v for k, v in valores.items()})
    try:
        ESTADO_FILE.parent.mkdir(parents=True, exist_ok=True)
        ESTADO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def obtener_clave_api(settings: Settings) -> Optional[str]:
    """Clave del proveedor activo. Ollama no necesita clave."""
    variable = settings.variable_clave()
    if not variable:
        return "sin-clave"
    valor = os.getenv(variable) or (os.getenv("OPENROUTER_API_KEY") if settings.proveedor == "openrouter" else None)
    if valor:
        return valor.strip()
    archivo = BASE_DIR / ".clave"
    try:
        texto = archivo.read_text(encoding="utf-8").strip()
        return texto or None
    except OSError:
        return None
