"""
Bucle de agente con herramientas (estilo Claude Code / Codex) y subagentes.

Cada agente:
  1. recibe una tarea y un system prompt con su rol, sus herramientas y las
     lecciones relevantes
  2. el modelo responde con razonamiento corto + llamadas a herramientas
  3. REAPER ejecuta las herramientas de verdad y devuelve <resultado>
  4. repite hasta attempt_completion, que solo se acepta si la validación
     real de los archivos cambiados pasa

Trucos para que un modelo de 24B rinda (v6 + v7):
  - contexto chico por subagente (cada uno arranca limpio)
  - mapa de archivos relevantes calculado ANTES de empezar
  - stop en "<resultado" para que no invente resultados
  - lecturas viejas se reemplazan cuando el archivo cambia (evita SEARCH obsoletos)
  - compactación automática antes de llenar los 32k de contexto
  - CONTINUACIÓN AUTOMÁTICA: si la respuesta se corta escribiendo un archivo,
    se guarda lo escrito y el modelo sigue desde la última línea
  - detección de atascos: si la misma verificación falla una y otra vez,
    se consulta a un modelo más fuerte (escalada) y su diagnóstico entra al contexto
  - detección de bucles, recordatorios de formato y pistas por tipo de error
"""

STOP = ["<resultado", "<tool_result"]
MAX_OBSERVACION = 9000

CANCELAR = threading.Event()

ALIAS_ROLES = {
    "explorer": "explorador", "explore": "explorador", "investigador": "explorador",
    "implementer": "implementador", "coder": "implementador", "programador": "implementador",
    "developer": "implementador", "reviewer": "revisor", "review": "revisor",
    "tester": "qa", "test": "qa", "fixer": "reparador", "debugger": "reparador",
    "architect": "arquitecto", "planner": "arquitecto", "planificador": "arquitecto",
    "spec": "especificador", "tdd": "especificador", "tests_primero": "especificador",
}

RECORDATORIO = """No usaste ninguna herramienta (o el formato no se entendió). Escribí la herramienta con etiquetas XML, por ejemplo:
<read_file>
<path>archivo.py</path>
</read_file>
Para crear o cambiar archivos usá write_to_file, replace_in_file o replace_symbol (no pegues código suelto en el chat).
Si ya terminaste:
<attempt_completion>
<result>tu informe</result>
</attempt_completion>"""

SUFIJO_SUBTAREA = (
    "\n\nSos un subagente con contexto limpio: trabajá solo en esta tarea y terminá con "
    "attempt_completion y un informe autocontenido (quien lo lea no vio tu trabajo)."
)

_RE_RESULTADO = re.compile(r'(<resultado herramienta="[^"]*"[^>]*>\n)(.*?)(\n</resultado>)', re.S)
_RE_LARGO = re.compile(r"(<(content|diff)>)(.*?)(</\2>)", re.S)

HERRAMIENTAS_CONTINUABLES = ("write_to_file", "append_to_file")


class Cancelado(Exception):
    pass


@dataclass
class ResultadoAgente:
    ok: bool
    resumen: str
    cambios: list = field(default_factory=list)
    pasos: int = 0
    motivo: str = "completado"
    rol: str = ""
    contexto: str = ""  # último razonamiento suelto del modelo (por si dejó info fuera del informe)
    errores: list = field(default_factory=list)  # últimos errores reales vistos (para escalar)
    escalado: bool = False


_contadores: dict = {}
_lock_contadores = threading.Lock()


def _etiqueta(rol: str) -> str:
    with _lock_contadores:
        contador = _contadores.setdefault(rol, itertools.count(1))
        return f"{rol}#{next(contador)}"


def _stub_resultado(m: re.Match) -> str:
    cuerpo = m.group(2)
    if len(cuerpo) <= 600:
        return m.group(0)
    cabeza = "\n".join(cuerpo.splitlines()[:6])[:400]
    return (m.group(1) + cabeza
            + "\n[... resultado recortado para ahorrar contexto; repetí la herramienta si lo necesitás]"
            + m.group(3))


def _stub_largo(m: re.Match) -> str:
    if len(m.group(3)) <= 800:
        return m.group(0)
    return m.group(1) + "\n[... contenido omitido: ya fue procesado ...]\n" + m.group(4)


def _firma_error(texto: str) -> str:
    """Huella de un error para detectar que se repite (sin números de línea ni rutas temporales)."""
    texto = re.sub(r"\d+", "N", texto or "")
    texto = re.sub(r"/tmp/\S+|reaper_\w+", "TMP", texto)
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    clave = " | ".join(l for l in lineas if re.search(r"Error|FAIL|falló|fallaron|✗|no define|not defined", l))[:600]
    return hashlib.sha1((clave or texto[:400]).encode("utf-8", "replace")).hexdigest()[:12]


# ------------------------------------------------------------------ intención del pedido y del modelo
# Estas heurísticas deciden cuándo el agente principal puede terminar con una respuesta en texto
# (como Claude Code: si ya sabe la respuesta, contesta y listo) y cuándo un informe afirma una
# verificación que nunca ocurrió.

_PREGUNTA_INICIO = re.compile(
    r"^\s*[¿¡(\"']*\s*(?:qu[ée]|cu[áa]l(?:es)?|cu[áa]nto[s]?|cu[áa]nta[s]?|c[óo]mo|por\s*qu[ée]|porqu[ée]|qui[ée]n(?:es)?|"
    r"d[óo]nde|cu[áa]ndo|para\s+qu[ée]|explic[aá](?:me)?|expl[ií]came|defin[ií]|define|describ[ií]|"
    r"resum[ií]|responde|respond[eé]|dec[ií]me|dime|calcul[aá]|es\s+|son\s+|existe|hay\s+|"
    r"what|how|why|which|who|whom|when|where|is|are|does|do|did|can|could|explain|tell\s+me|compute)\b",
    re.I,
)
_PIDE_ACCION = re.compile(
    r"\b(?:cre[aáeé]|crear|crea|hac[eé]|haz|hacer|hace|escrib[ií]|escribe|escribir|gener[aáe]|generar|implement\w*|"
    r"agreg\w*|añad\w*|a[ñn]ade|modific\w*|cambi[aáe]|cambiar|arregl\w*|corrig\w*|correg\w*|refactor\w*|borr[aáe]|"
    r"borrar|elimin\w*|renombr\w*|actualiz\w*|instal\w*|constru\w*|program[aáe]|programar|desarroll\w*|"
    r"migr[aáe]|mov[eé]|mueve|ejecut[aáe]|ejecutar|corr[eé]|correr|test[eé]a|prob[aá]|probar|compil\w*|"
    r"edit[aáe]|editar|reescrib\w*|optimiz\w*|depur\w*|debugue\w*|"
    r"create|make|write|build|implement|add|fix|change|update|refactor|delete|remove|rename|install|"
    r"generate|run|execute|test|compile|edit|rewrite|optimi[sz]e|debug)\b",
    re.I,
)
_PIDE_FAVOR = re.compile(r"\b(?:pod[eé]s|puedes|podr[ií]as|quer[eé]s|quieres|can\s+you|could\s+you|would\s+you|please)\b", re.I)
_PROHIBE_COMANDOS = re.compile(
    r"\b(?:no|sin|nunca)\s+(?:ejecutes|ejecutar|corras|correr|uses|usar|lances|lanzar|llames|llamar)\s+"
    r"(?:ning[úu]n\w*\s+|nada\s+|otr[oa]s?\s+)?(?:comandos?|herramientas?|c[óo]digo|programas?|python|nada|tools?)\b"
    r"|\b(?:do\s+not|don'?t|never|without)\s+(?:run(?:ning)?|execut\w*|us(?:e|ing))\s+(?:any\s+)?(?:commands?|tools?|code)\b"
    r"|\bno\s+tools\b",
    re.I,
)
_PROHIBE_HERRAMIENTAS = re.compile(
    r"\b(?:no|sin)\s+(?:uses|usar)\s+(?:ning[úu]na\s+)?herramientas?\b|\b(?:don'?t|do\s+not|without)\s+(?:use|using)\s+(?:any\s+)?tools?\b"
    r"|\bresponde\w*\s+(?:[úu]nicamente|solamente|solo|s[óo]lo)\b|\b(?:answer|reply)\s+only\b",
    re.I,
)
_PROHIBE_ARCHIVOS = re.compile(
    r"\b(?:no|sin|nunca)\s+(?:crees|crear|escribas|escribir|modifiques|modificar|toques|tocar|edites|editar|"
    r"cambies|cambiar|borres|borrar)\s+(?:ning[úu]n\w*\s+|los\s+|el\s+|otros?\s+)?(?:archivos?|ficheros?|nada|c[óo]digo)\b"
    r"|\b(?:do\s+not|don'?t|never|without)\s+(?:creat\w*|writ\w*|modify\w*|touch\w*|edit\w*|chang\w*)\s+(?:any\s+)?(?:files?|anything|code)\b",
    re.I,
)
_RE_RUTA_ARCHIVO = re.compile(r"[\w./-]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|html|css|json|md|sh|go|rs|c|h|cpp|java|php|rb|toml|ya?ml|txt|sql)\b")
_RE_ARITMETICA = re.compile(r"\d+(?:[.,]\d+)?\s*(?:[-+*/x×÷^%]|\*\*|mas|más|menos|por|entre|dividido|plus|minus|times)\s*\d")

_RE_ANUNCIA = re.compile(
    r"(?:\b(?:voy\s+a|vamos\s+a|ahora\s+(?:voy|vamos|creo|escribo|ejecuto|corro|leo|reviso|edito|agrego|implemento|pruebo)|"
    r"a\s+continuaci[óo]n|procedo\s+a|proceder[ée]|empiezo\s+(?:por|a)|primero\s+(?:voy|leo|reviso|creo)|"
    r"luego\s+(?:voy|ejecuto|creo)|let\s+me|i'?ll|i\s+will|i\s+am\s+going\s+to|next,?\s+i|now\s+i'?ll|let'?s)\b"
    r"(?:(?!\.\s)[^\n]){0,160}$)"
    r"|:\s*$",
    re.I,
)

_RE_AFIRMA = re.compile(
    r"\b(?:valid[ée]|verifiqu[ée]|comprob[ée]|prob[ée]|teste[ée]|ejecut[ée]|corr[ií])\b"
    r"|\b(?:he|hemos|fue|fueron|est[áa]n?|qued[óo]|quedaron|ya\s+est[áa])\s+(?:validad|probad|verificad|testead|comprobad|ejecutad)[oa]s?\b"
    r"|\b(?:los\s+|todos\s+los\s+)?(?:tests?|pruebas?)\s+(?:pasan|pasaron|est[áa]n\s+en\s+verde|dan\s+ok|salen\s+bien)\b"
    r"|\b(?:pasan|pasaron)\s+(?:todos\s+)?(?:los\s+|las\s+)?(?:tests|pruebas)\b"
    r"|\b(?:funciona|anda)\s+(?:todo\s+)?(?:correctamente|bien|perfecto|perfectamente|sin\s+errores)\b"
    r"|\btodo\s+(?:funciona|anda)\b"
    r"|\b(?:verified|validated|tested|confirmed\s+(?:it|that)\s+works|all\s+tests\s+pass(?:ed)?|tests\s+pass(?:ed)?|works\s+correctly)\b",
    re.I,
)
_RE_AFIRMA_TESTS = re.compile(
    r"\b(?:tests?|pruebas?)\s+(?:pasan|pasaron|est[áa]n\s+en\s+verde|dan\s+ok)\b|\b(?:pasan|pasaron)\s+(?:todos\s+)?(?:los\s+|las\s+)?(?:tests|pruebas)\b"
    r"|\b(?:all\s+)?tests\s+pass(?:ed)?\b",
    re.I,
)
_RE_AFIRMA_EJECUCION = re.compile(r"\b(?:ejecut[ée]|corr[ií]|lanc[ée]|al\s+ejecutar(?:lo)?|ran\s+it|i\s+ran|executed)\b", re.I)
_RE_NEGACION = re.compile(r"\b(?:no|sin|nunca|ni|todav[ií]a\s+no|a[úu]n\s+no|not|never|without|couldn'?t|didn'?t|haven'?t|no\s+pude)\s*\w*\s*\w*\s*$", re.I)
_RE_FENCE_VACIO = re.compile(r"```[\w+-]*[ \t]*\n?\s*```")
_RE_BLOQUE_CODIGO = re.compile(r"```[\w+-]*\n(.*?)```", re.S)

HERRAMIENTAS_COMANDO = ("execute_command", "run_python", "run_tests")
HERRAMIENTAS_REUTILIZABLES = ("execute_command", "run_python", "run_tests", "validate", "fetch_url", "view_diff",
                              "project_map", "list_files", "search_files", "code_outline", "find_references")
HERRAMIENTAS_LECTURA_BARATA = ("read_file", "read_symbol")
_RE_COMANDO_VOLATIL = re.compile(r"\b(?:sleep|date|time|curl|wget|ping|ps|top|uptime|watch|free|df|tail\s+-f|"
                                 r"git\s+(?:fetch|pull)|pip\s+(?:install|download)|npm\s+(?:install|i)|random)\b")


def salida_fallida(nombre: str, salida: str) -> bool:
    """¿El resultado (sin excepción) igual muestra un fallo? (exit code != 0, tests que fallan, validación rota)."""
    if nombre in ("execute_command", "run_python"):
        m = re.search(r"^exit code: (-?\d+)", salida or "", re.M)
        return bool(m and m.group(1) != "0") or "estado: TIMEOUT" in (salida or "")
    if nombre == "run_tests":
        return (salida or "").startswith("Tests FALLARON")
    if nombre == "validate":
        return "DETALLE DE FALLOS" in (salida or "") or "VALIDACIÓN FALLÓ" in (salida or "")
    return False


_RE_COMANDO_TESTS = re.compile(r"\b(?:pytest|unittest|npm\s+(?:run\s+)?test|node\s+--test|go\s+test|cargo\s+test|"
                               r"jest|vitest|mocha|phpunit|rspec|bats|ctest|make\s+test)\b")


def limpiar_texto_visible(texto: str) -> str:
    """Quita los ```xml``` vacíos que quedan cuando el modelo envuelve herramientas en bloques de código."""
    texto = _RE_FENCE_VACIO.sub("", texto or "")
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def pide_cambios(tarea: str) -> bool:
    """¿El pedido requiere crear/modificar/ejecutar algo? (si no, es una pregunta para responder en texto)."""
    t = (tarea or "").strip()[:800]
    if not t:
        return False
    if _PROHIBE_ARCHIVOS.search(t) and _PROHIBE_COMANDOS.search(t):
        return False
    if _PREGUNTA_INICIO.search(t) and not _PIDE_FAVOR.search(t[:60]):
        return False
    return bool(_PIDE_ACCION.search(t))


def prohibiciones(tarea: str) -> set:
    """Lo que el usuario prohibió explícitamente en el pedido: 'comandos', 'archivos' y/o 'herramientas'."""
    t = (tarea or "")[:1500]
    salida = set()
    if _PROHIBE_HERRAMIENTAS.search(t):
        salida.add("herramientas")
    if _PROHIBE_COMANDOS.search(t):
        salida.add("comandos")
    if _PROHIBE_ARCHIVOS.search(t):
        salida.add("archivos")
    return salida


def es_pregunta_simple(tarea: str) -> bool:
    """Pregunta corta que el modelo puede contestar sin explorar el proyecto (ej. 'cuánto es 5+5')."""
    t = (tarea or "").strip()
    if not t or len(t) > 320 or _RE_RUTA_ARCHIVO.search(t):
        return False
    if prohibiciones(t) & {"herramientas", "comandos"}:
        return True
    if pide_cambios(t):
        return False
    return bool(_PREGUNTA_INICIO.search(t) or t.rstrip().endswith("?") or _RE_ARITMETICA.search(t))


def anuncia_accion(texto: str) -> bool:
    """El modelo dice que VA a hacer algo ('voy a crear el archivo:') pero no llamó ninguna herramienta."""
    cola = (texto or "").strip()[-240:]
    return bool(cola) and bool(_RE_ANUNCIA.search(cola))


def afirma_verificacion(texto: str) -> bool:
    """¿El texto afirma que algo se probó/validó/funciona? (ignora frases negadas: 'no pude probar')."""
    for m in _RE_AFIRMA.finditer(texto or ""):
        previo = texto[max(0, m.start() - 28):m.start()]
        if _RE_NEGACION.search(previo):
            continue
        return True
    return False


def afirma_ejecucion(texto: str) -> bool:
    """¿El texto dice que ejecutó algo ('lo ejecuté', 'corrí el programa')? (ignora frases negadas)."""
    for m in _RE_AFIRMA_EJECUCION.finditer(texto or ""):
        if not _RE_NEGACION.search(texto[max(0, m.start() - 28):m.start()]):
            return True
    return False


def codigo_pegado(texto: str) -> bool:
    """Bloque de código de varias líneas pegado en el chat (en vez de escrito con una herramienta)."""
    for m in _RE_BLOQUE_CODIGO.finditer(texto or ""):
        if len([l for l in m.group(1).splitlines() if l.strip()]) >= 3:
            return True
    return False


class Agente:
    def __init__(
        self,
        rol: str,
        llm,
        ws: Workspace,
        settings: Settings,
        ui: UI,
        *,
        profundidad: int = 0,
        etiqueta: Optional[str] = None,
        mostrar_progreso: bool = True,
        cid_inicio: Optional[int] = None,
        temperatura: Optional[float] = None,
        modelo: Optional[str] = None,
        memoria: Optional[MemoriaLecciones] = None,
        protegidos: Iterable[str] = (),
        extra_prompt: str = "",
        max_pasos: Optional[int] = None,
        on_atascado: Optional[Callable[[str], Optional[str]]] = None,
    ):
        self.rol = ROLES[rol]
        self.llm = llm
        self.ws = ws
        self.settings = settings
        self.ui = ui
        self.profundidad = profundidad
        self.etiqueta = etiqueta or _etiqueta(rol)
        self.mostrar_progreso = mostrar_progreso
        if memoria is None and settings.lecciones:
            try:
                memoria = MemoriaLecciones(ws)
            except OSError:
                memoria = None
        self.memoria = memoria
        self.ctx = Contexto(ws, settings, ui, self.etiqueta, set(), [], cid_inicio, memoria=memoria,
                            protegidos=set(protegidos), permitidos=tuple(self.rol.rutas_permitidas), llm=llm)
        base = settings.max_pasos if rol == "principal" else settings.max_pasos_sub
        self.max_pasos = max_pasos or self.rol.max_pasos or base
        self.temperatura = self.rol.temperatura if temperatura is None else temperatura
        self.modelo = modelo
        self.extra_prompt = extra_prompt
        self.on_atascado = on_atascado
        self.mensajes: list[dict] = []
        # Se parsean TODAS las herramientas para poder decirle al modelo cuáles no tiene permitidas.
        self._esquemas = esquemas()
        self._lecturas: list[tuple[int, str]] = []
        self._indice_tarea = 0
        self._rechazos = 0
        self._ultimo_texto = ""
        self._continuaciones: dict[str, int] = {}
        self._errores: collections.Counter = collections.Counter()
        self._errores_texto: list[str] = []
        self._escalado = False
        self._fallos_por_herramienta: collections.Counter = collections.Counter()
        self._factor_contexto = 1.0
        # v7.1: anti-bucles por estado del workspace y control de afirmaciones
        self._historial: dict[str, dict] = {}   # clave de llamada → {version, salida, error, veces}
        self._escrituras = 0                     # se incrementa con cada escritura exitosa
        self._evidencias: list[tuple[str, str, int]] = []  # (herramienta, ok|fallo|bloqueado|sin_tests, escrituras)
        self._reusos_seguidos = 0
        self._ultima_salida_ok = ""
        self._prohibido: set = set()
        self._pide_cambios = True
        self._pregunta_simple = False
        self._aviso_pendiente = ""
        self._finish_actual: Optional[str] = None
        self._ultima_llamada: Optional[Llamada] = None

    # ------------------------------------------------------------ API
    def ejecutar(self, tarea: str, cid_inicio: Optional[int] = None) -> ResultadoAgente:
        if cid_inicio is not None:
            self.ctx.cid_inicio = cid_inicio
        principal = self.rol.nombre == "principal"
        self._prohibido = prohibiciones(tarea) if principal else set()
        self._pide_cambios = pide_cambios(tarea) if principal else True
        self._pregunta_simple = principal and es_pregunta_simple(tarea)
        lecciones = ""
        if self.memoria is not None and self.settings.lecciones:
            try:
                lecciones = self.memoria.para_prompt(tarea, self.settings.max_lecciones_prompt)
            except OSError:
                lecciones = ""
        prompt = system_prompt(self.rol, self.ws, self.settings.max_llamadas_turno,
                               lecciones=lecciones, extra=self.extra_prompt, idioma=self.settings.idioma_prompts)
        if self.mensajes:
            self.mensajes[0] = {"role": "system", "content": prompt}
        else:
            self.mensajes = [{"role": "system", "content": prompt}]
        self._agregar_usuario(self._preparar_tarea(tarea))
        self._indice_tarea = len(self.mensajes) - 1
        self.ctx.cambios = set()
        self.ctx.parciales = {}
        self._rechazos = 0
        self._continuaciones = {}
        self._errores = collections.Counter()
        self._errores_texto = []
        self._escalado = False
        self._historial = {}
        self._escrituras = 0
        self._evidencias = []
        self._reusos_seguidos = 0
        self._ultima_salida_ok = ""

        sin_herramienta = 0
        anuncios = 0
        repeticiones: dict = {}
        self._ultimo_texto = ""

        for paso in range(1, self.max_pasos + 1):
            if CANCELAR.is_set():
                raise Cancelado()
            self._compactar()
            respuesta = self._llamar_con_recuperacion()
            analisis = analizar(respuesta.texto, self._esquemas)
            self.mensajes.append({
                "role": "assistant",
                "content": analisis.respuesta_limpia.strip() or "(respuesta vacía)",
            })
            texto_visible = limpiar_texto_visible(analisis.texto)
            if texto_visible:
                self._ultimo_texto = texto_visible
                self.ui.pensamiento(self.etiqueta, texto_visible)

            if not analisis.llamadas:
                texto = texto_visible
                if texto and respuesta.finish_reason != "length":
                    cierre = self._cierre_en_texto(texto, paso, sin_herramienta, anuncios)
                    if cierre is not None:
                        return cierre
                if texto and anuncia_accion(texto):
                    anuncios += 1
                sin_herramienta += 1
                self.ctx.tropiezo("sin_herramienta")
                if sin_herramienta > 2:
                    return self._cerrar(texto or "El agente no produjo un resultado.", paso, "sin_herramientas")
                aviso = self._aviso_sin_herramienta(texto)
                if respuesta.finish_reason == "length":
                    aviso = ("Tu respuesta se cortó por longitud. Escribí menos por mensaje: "
                             "archivos largos en partes (write_to_file con partial=true + append_to_file).\n\n") + aviso
                self._agregar_usuario(aviso)
                continue

            sin_herramienta = 0
            limite = max(1, self.settings.max_llamadas_turno)
            llamadas, excedentes = analisis.llamadas[:limite], analisis.llamadas[limite:]
            self._finish_actual = respuesta.finish_reason
            self._ultima_llamada = analisis.llamadas[-1]
            observaciones: list[str] = []
            hubo_error = False
            final: Optional[tuple[str, bool]] = None

            i = 0
            while i < len(llamadas):
                llamada = llamadas[i]
                if llamada.nombre == "delegate":
                    grupo = [llamada]
                    while i + len(grupo) < len(llamadas) and llamadas[i + len(grupo)].nombre == "delegate":
                        grupo.append(llamadas[i + len(grupo)])
                    obs, error = self._delegar(grupo)
                    observaciones.extend(obs)
                    hubo_error |= error
                    i += len(grupo)
                    continue
                if llamada.nombre == "attempt_completion" and "attempt_completion" in self.rol.herramientas:
                    informe = (llamada.params.get("result") or "").strip() or texto_visible
                    aceptado, obs, ok_final = self._intentar_terminar(hubo_error, informe)
                    if aceptado:
                        nota = self._nota_afirmacion(informe)
                        final = (informe + nota, ok_final and not nota)
                        break
                    observaciones.append(obs)
                    i += 1
                    continue
                if not llamada.completa and respuesta.finish_reason == "length" \
                        and llamada.nombre in HERRAMIENTAS_CONTINUABLES and self.settings.continuar_cortes:
                    obs, error = self._continuar_corte(llamada)
                    observaciones.append(obs)
                    hubo_error |= error
                    i += 1
                    continue
                obs, error = self._ejecutar_herramienta(llamada, repeticiones)
                observaciones.append(obs)
                hubo_error |= error
                i += 1

            if final is not None:
                return self._cerrar(final[0], paso, "completado", ok=final[1])

            if self._reusos_seguidos >= 2 and (self.rol.nombre == "principal" or self._reusos_seguidos >= 4):
                # El modelo pide una y otra vez lo mismo que ya tiene: se corta el bucle. Si había obtenido
                # un resultado (ej. 2+2 → 4) se responde con eso; Claude Code tampoco ejecuta tres veces "2+2".
                self.ui.aviso(f"  [{self.etiqueta}] bucle de herramientas: corto y respondo con lo que ya tengo")
                if self._ultima_salida_ok and self.rol.nombre == "principal" and not self.ctx.cambios:
                    return self._cerrar(self._respuesta_por_bucle(), paso, "respuesta")
                return self._cerrar(
                    "El modelo repetía las mismas herramientas sin avanzar (nada cambió entre llamadas). "
                    + self._respuesta_por_bucle(), paso, "bucle", ok=False)

            if excedentes:
                observaciones.append(
                    f"(Ignoré {len(excedentes)} herramienta(s) extra: máximo {limite} por mensaje. "
                    "Repetilas si siguen haciendo falta.)"
                )
            if respuesta.finish_reason == "length" and not any("SEGUÍ DESDE" in o for o in observaciones):
                observaciones.append("(Tu mensaje se cortó por longitud: escribí menos por mensaje.)")
            diagnostico = self._quizas_escalar(observaciones)
            if diagnostico:
                observaciones.append(diagnostico)
            restantes = self.max_pasos - paso
            if 0 < restantes <= 3:
                observaciones.append(f"(Te quedan {restantes} pasos: cerrá pronto con attempt_completion.)")
            self._agregar_usuario("\n\n".join(observaciones))

        return self._cerrar(
            "Se alcanzó el límite de pasos sin terminar. Último razonamiento: " + recortar(self._ultimo_texto, 800),
            self.max_pasos,
            "max_pasos",
            ok=False,
        )

    # ------------------------------------------------------------ preparación
    def _preparar_tarea(self, tarea: str) -> str:
        if self.rol.nombre == "principal" and (self._pregunta_simple or self._prohibido):
            notas = []
            if "herramientas" in self._prohibido:
                notas.append("el usuario pidió que respondas SIN usar herramientas")
            elif "comandos" in self._prohibido:
                notas.append("el usuario pidió que NO ejecutes comandos")
            if "archivos" in self._prohibido:
                notas.append("el usuario pidió que NO crees ni modifiques archivos")
            if self._pregunta_simple:
                notas.append("es una pregunta directa: si podés responderla con lo que sabés, respondé YA en "
                             "texto, en tu primer mensaje y sin herramientas")
            return tarea + "\n\n(REAPER: " + "; ".join(notas) + ".)"
        extras = []
        if self.settings.mapa_relevantes and self.rol.nombre in ("principal", "implementador", "reparador",
                                                                 "explorador", "especificador"):
            mapa = mapa_relevante(self.ws, tarea, self.settings.max_relevantes)
            if mapa:
                extras.append(mapa)
        if self.rol.nombre in ("implementador", "especificador", "qa", "principal", "escritor"):
            archivos = re.findall(r"[\w./-]+\.(?:py|js|mjs|cjs|ts|html|css|sh|go|rs|c|h|java|php|rb|pl|pm)\b", tarea)
            guia = guias_para(archivos or self.ws.archivos_codigo(limite=60), tarea)
            if guia:
                extras.append("GUÍA RÁPIDA DEL LENGUAJE:\n" + guia)
            recetas = recetas_para_prompt(tarea)
            if recetas:
                extras.append(recetas)
        if not extras:
            return tarea
        return tarea + "\n\n" + "\n\n".join(extras)

    # ------------------------------------------------------------ internos
    def _cerrar(self, resumen: str, pasos: int, motivo: str, ok: Optional[bool] = None) -> ResultadoAgente:
        if ok is None:
            ok = motivo in ("completado", "respuesta")
            if self.ctx.cambios:
                ok = ok and not fallos(validar_archivos(self.ws, sorted(self.ctx.cambios)))
        return ResultadoAgente(ok, resumen, sorted(self.ctx.cambios), pasos, motivo, self.rol.nombre,
                               self._ultimo_texto, self._errores_texto[-3:], self._escalado)

    def _llamar_modelo(self) -> Respuesta:
        progreso = (lambda n: self.ui.progreso(self.etiqueta, n)) if self.mostrar_progreso else None
        if self.mostrar_progreso:
            self.ui.esperando(self.etiqueta)
        try:
            return self.llm.chat(
                self.mensajes,
                modelo=self.modelo or self.settings.modelo_para(self.rol.nombre),
                temperatura=self.temperatura,
                stop=STOP,
                on_progress=progreso,
                rol=self.rol.nombre,
            )
        finally:
            if self.mostrar_progreso:
                self.ui.fin_progreso()

    def _llamar_con_recuperacion(self) -> Respuesta:
        """Si el proveedor dice que el contexto se excedió, compacta fuerte y reintenta una vez."""
        try:
            return self._llamar_modelo()
        except LLMError as e:
            if not getattr(e, "contexto_excedido", False):
                raise
            self.ui.aviso(f"  [{self.etiqueta}] contexto excedido: compacto la conversación y reintento")
            self._factor_contexto = max(0.4, self._factor_contexto * 0.65)
            self._compactar(forzar=True)
            return self._llamar_modelo()

    def _agregar_usuario(self, texto: str) -> None:
        if self.mensajes and self.mensajes[-1]["role"] == "user":
            self.mensajes[-1]["content"] += "\n\n" + texto
        else:
            self.mensajes.append({"role": "user", "content": texto})

    def _ejecutar_herramienta(self, llamada: Llamada, repeticiones: dict) -> tuple[str, bool]:
        nombre = llamada.nombre
        h = REGISTRO.get(nombre)

        def obs(texto: str, attrs: str = "") -> str:
            return f'<resultado herramienta="{nombre}"{attrs}>\n{texto}\n</resultado>'

        if h is None or nombre not in self.rol.herramientas:
            disponibles = ", ".join(self.rol.herramientas)
            self.ui.resultado_herramienta(False, f"herramienta no disponible: {nombre}")
            return obs(f"ERROR: '{nombre}' no existe o no está disponible para tu rol. Disponibles: {disponibles}"), True
        if not llamada.completa and self._finish_actual != "length" and llamada is self._ultima_llamada \
                and all(llamada.params.get(p.nombre) not in (None, "") for p in h.params if p.requerido):
            # El mensaje terminó normal y la llamada es la última: el modelo solo olvidó cerrar las etiquetas.
            # Se acepta (si el contenido quedó truncado, la validación real del archivo lo va a mostrar).
            llamada = Llamada(llamada.nombre, llamada.params, True, llamada.crudo)
        if not llamada.completa:
            self.ui.resultado_herramienta(False, f"{nombre}: llamada incompleta")
            self.ctx.tropiezo("llamada_incompleta")
            return obs(
                f"ERROR: la llamada a {nombre} quedó incompleta (falta la etiqueta de cierre o se cortó tu "
                "respuesta). Si el archivo es largo, escribilo por partes: write_to_file con partial=true y "
                "después append_to_file."
            ), True

        faltan = []
        for p in h.params:
            if not p.requerido:
                continue
            valor = llamada.params.get(p.nombre)
            if valor is None or (not p.largo and not str(valor).strip()):
                faltan.append(p.nombre)
        if faltan:
            self.ui.resultado_herramienta(False, f"{nombre}: faltan {', '.join(faltan)}")
            return obs(f"ERROR: faltan parámetros: {', '.join(faltan)}. Uso correcto:\n{h.ejemplo}"), True

        prohibicion = self._prohibicion_para(nombre, h)
        if prohibicion:
            self.ui.resultado_herramienta(False, f"{nombre}: el usuario lo prohibió")
            self._registrar_evidencia(nombre, "bloqueado")
            return obs(
                f"ERROR: {prohibicion} No uses herramientas para esto: respondé directamente en texto con lo que sabés."
            ), True

        # Detector de repeticiones según el ESTADO del workspace: después de una escritura, releer o
        # volver a correr los tests es legítimo; repetir lo mismo sin que nada cambie, no.
        clave = nombre + json.dumps(llamada.params, sort_keys=True, ensure_ascii=False)
        previo = self._historial.get(clave) if not h.escribe else None
        aviso_relectura = ""
        misma_version = previo is not None and previo["version"] == self._version()
        seguir_contando = misma_version
        if misma_version and previo.get("muta") and previo["veces"] < 5:
            previo["veces"] += 1
        elif misma_version:
            previo["veces"] += 1
            veces = previo["veces"]
            volatil = nombre == "execute_command" and bool(_RE_COMANDO_VOLATIL.search(llamada.params.get("command", "")))
            fallido = previo["error"] or salida_fallida(nombre, previo["salida"])
            if nombre in HERRAMIENTAS_REUTILIZABLES and not fallido and not volatil:
                self._reusos_seguidos += 1
                self.ui.resultado_herramienta(True, f"{nombre}: llamada idéntica y nada cambió → reutilizo el resultado anterior")
                return obs(self._texto_reuso(nombre, previo["salida"], veces), previo["attrs"]), False
            if nombre in HERRAMIENTAS_LECTURA_BARATA and not previo["error"] and veces < 4:
                if veces >= 3:
                    aviso_relectura = (f"(Ya leíste esto {veces} veces y no cambió: no lo vuelvas a pedir; "
                                       "usá lo que ya sabés y avanzá con el próximo paso.)\n")
            elif veces >= 3:
                self.ui.resultado_herramienta(False, f"{nombre}: llamada repetida")
                self._registrar_evidencia(nombre, "bloqueado")
                return obs(
                    f"ERROR: ya hiciste exactamente esta llamada {veces} veces sin cambiar nada en el proyecto y el "
                    "resultado no cambia (esta vez NO se ejecutó, así que no hay resultado nuevo: no afirmes que lo "
                    "verificaste). Cambiá algo antes de repetirla, probá otro enfoque o terminá explicando qué falta."
                ), True

        self.ui.herramienta(self.etiqueta, nombre, resumen_params(nombre, llamada.params))
        version_antes = self._version() if nombre in ("execute_command", "run_python") else ""
        error = False
        try:
            salida = h.fn(self.ctx, llamada.params)
        except ErrorHerramienta as e:
            salida, error = f"ERROR: {e}", True
        except (Cancelado, KeyboardInterrupt):
            raise
        except Exception as e:  # una herramienta rota no debe tumbar al agente
            salida, error = f"ERROR inesperado en {nombre}: {type(e).__name__}: {e}", True
        if not error and "VALIDACIÓN FALLÓ" in salida:
            error = True
        if nombre == "run_tests" and salida.startswith("Tests FALLARON"):
            error = True
        self.ui.resultado_herramienta(not error, salida)
        if error:
            self._registrar_error(nombre, llamada.params.get("path", ""), salida)
            if self.settings.pistas_errores and "PISTAS DE REAPER" not in salida:
                salida = anexar_pistas(salida, 2)
            salida += self._sugerencia_por_repeticion(nombre, llamada.params.get("path", ""))
        salida = redactar_secretos(recortar(salida, MAX_OBSERVACION))

        attrs = ""
        ruta = None
        if "path" in llamada.params:
            try:
                ruta = self.ws.rel(self.ws.ruta(llamada.params["path"]))
            except (ErrorRuta, ValueError):
                ruta = None
        if nombre in ("read_file", "read_symbol") and ruta and not error:
            attrs = f' ruta="{ruta}"'
            self._lecturas.append((len(self.mensajes), ruta))
        if h.escribe and ruta and not salida.startswith("ERROR"):
            self._marcar_lecturas_viejas(ruta)
        if h.escribe and not error:
            self._escrituras += 1
        self._reusos_seguidos = 0
        if nombre in ("run_tests", "validate", "execute_command", "run_python"):
            self._registrar_evidencia(nombre, self._estado_evidencia(nombre, llamada.params, salida, error),
                                      llamada.params.get("command", ""))
        if not error and nombre in ("execute_command", "run_python", "fetch_url"):
            self._ultima_salida_ok = salida
        if not h.escribe:
            version_despues = self._version()
            self._historial[clave] = {"version": version_despues, "salida": salida, "error": error,
                                      "veces": previo["veces"] if seguir_contando else 1, "attrs": attrs,
                                      # un comando que cambió archivos al correr (append, mkdir...) es una
                                      # acción, no una consulta: repetirlo no es un bucle de lectura
                                      "muta": bool(version_antes) and version_antes != version_despues}
        if (not error and self.rol.nombre == "principal" and nombre in ("execute_command", "run_python")
                and not self.ctx.cambios and not self._pide_cambios and not salida_fallida(nombre, salida)):
            salida += ("\n\n(Si este resultado ya responde lo que te preguntaron, respondé AHORA en texto, sin más "
                       "herramientas. No repitas el comando.)")
        return obs(aviso_relectura + salida, attrs), error

    # ------------------------------------------------------------ anti-bucles y evidencias (v7.1)
    def _version(self) -> str:
        """Estado del workspace: cambia con cada escritura de una herramienta o si un comando tocó archivos."""
        try:
            huella = self.ws.huella()
        except OSError:
            huella = "?"
        return f"{self._escrituras}:{huella}"

    def _prohibicion_para(self, nombre: str, h) -> str:
        if not self._prohibido or nombre == "attempt_completion":
            return ""
        if "herramientas" in self._prohibido:
            return "el usuario pidió explícitamente que respondas SIN usar herramientas."
        if "comandos" in self._prohibido and nombre in HERRAMIENTAS_COMANDO:
            return "el usuario pidió explícitamente que NO ejecutes comandos ni código."
        if "archivos" in self._prohibido and h.escribe:
            return "el usuario pidió explícitamente que NO crees ni modifiques archivos."
        return ""

    def _texto_reuso(self, nombre: str, salida: str, veces: int) -> str:
        cabecera = (f"YA HICISTE EXACTAMENTE ESTA LLAMADA ({veces} veces) y nada cambió en el proyecto desde "
                    "entonces, así que no la repito. Resultado de la vez anterior:\n")
        if salida_fallida(nombre, salida):
            consejo = ("Ese resultado es un FALLO y repetir lo mismo da el mismo fallo. Cambiá el código o el "
                       "comando antes de volver a probar, o explicá qué falta.")
        elif self.rol.nombre == "principal":
            consejo = ("YA TENÉS LO QUE NECESITABAS. Si esto responde el pedido, RESPONDÉ AHORA al usuario en texto "
                       "(sin herramientas). Si falta algo, hacé OTRA cosa distinta.")
        else:
            consejo = ("Ya tenés este resultado: usalo y seguí con el próximo paso, o terminá con attempt_completion.")
        return cabecera + recortar(salida, 4000) + "\n\n" + consejo

    def _estado_evidencia(self, nombre: str, params: dict, salida: str, error: bool) -> str:
        if error and re.search(r"bloquead|no aprob|prohibi|no se ejecut", salida, re.I):
            return "bloqueado"
        if nombre == "run_tests" and (salida.startswith("No hay tests") or salida.startswith("Tests SIN TESTS")):
            return "sin_tests"
        if error or salida_fallida(nombre, salida):
            return "fallo"
        return "ok"

    def _registrar_evidencia(self, nombre: str, estado: str, comando: str = "") -> None:
        if nombre not in ("run_tests", "validate", "execute_command", "run_python"):
            return
        tipo = "run_tests" if nombre == "execute_command" and _RE_COMANDO_TESTS.search(comando or "") else nombre
        self._evidencias.append((tipo, estado, self._escrituras))
        self._evidencias = self._evidencias[-30:]

    def _falta_evidencia(self, texto: str) -> str:
        """Si el texto afirma una verificación que no ocurrió (o que falló / fue bloqueada), devuelve el motivo."""
        if self.rol.nombre not in ("principal", "implementador", "reparador", "escritor"):
            return ""
        texto = texto or ""
        exito = afirma_verificacion(texto)
        ejecucion = afirma_ejecucion(texto)
        if not exito and not ejecucion:
            return ""
        reales = [e for e in self._evidencias if e[1] != "bloqueado"]
        if not self._evidencias or (ejecucion and not exito and not reales):
            if not self._evidencias:
                return ("no corriste ninguna verificación en esta tarea (run_tests, validate, execute_command o "
                        "run_python): ninguna ejecución tuya produjo un resultado real")
            return "las ejecuciones que intentaste fueron BLOQUEADAS o rechazadas: no produjeron ningún resultado"
        if not exito:
            return ""
        tipo, estado, version = self._evidencias[-1]
        honesto = bool(re.search(r"\b(?:falla|fallan|fall[óo]|fallaron|error|errores|no\s+pasa|fail\w*)\b", texto, re.I))
        if estado == "bloqueado":
            return f"la última verificación ({tipo}) fue BLOQUEADA o rechazada como repetida: no se ejecutó"
        if estado == "fallo" and not honesto:
            return f"la última verificación ({tipo}) FALLÓ"
        if _RE_AFIRMA_TESTS.search(texto):
            tests = [e for e in self._evidencias if e[0] == "run_tests"]
            if not tests:
                return "decís que los tests pasan, pero no corriste los tests (run_tests)"
            if tests[-1][1] == "sin_tests":
                return "decís que los tests pasan, pero run_tests no encontró ningún test"
            if tests[-1][1] != "ok" and not honesto:
                return "decís que los tests pasan, pero el último run_tests " + (
                    "FALLÓ" if tests[-1][1] == "fallo" else "fue bloqueado")
        if version < self._escrituras and self.ctx.cambios:
            return "cambiaste archivos DESPUÉS de la última verificación, así que ese resultado ya no vale"
        return ""

    def _rechazo_afirmacion(self, motivo: str) -> str:
        return ("No acepto ese cierre: tu texto afirma que algo se verificó/probó/funciona, pero " + motivo + ". "
                "Nunca afirmes una verificación que no viste en un <resultado> real. Corré la verificación ahora "
                "(run_tests, validate o execute_command) o reescribí la respuesta diciendo con honestidad qué se "
                "verificó y qué NO.")

    def _nota_afirmacion(self, texto: str) -> str:
        motivo = self._falta_evidencia(texto)
        if not motivo:
            return ""
        self.ui.aviso(f"  [{self.etiqueta}] el informe afirma una verificación sin evidencia: {motivo}")
        return f"\n\n⚠ REAPER: este informe afirma una verificación, pero {motivo}. Tomalo como NO verificado."

    def _cierre_en_texto(self, texto: str, paso: int, sin_herramienta: int, anuncios: int) -> Optional[ResultadoAgente]:
        """
        ¿Una respuesta SIN herramientas es la respuesta final? Para el principal casi siempre sí: si ya tiene
        el resultado (o la pregunta no necesitaba herramientas) contesta y termina, como Claude Code.
        Antes, REAPER le contestaba "no usaste ninguna herramienta" y el modelo repetía el comando: ese era el
        origen del bucle 2+2 → 4 → execute_command otra vez.
        """
        self._aviso_pendiente = ""
        if self.rol.nombre != "principal":
            if not self.rol.solo_lectura or "attempt_completion" not in self.rol.herramientas or anuncia_accion(texto):
                return None
            if (self.rol.nombre == "arquitecto" and "<plan" in texto and "</plan>" in texto) \
                    or (self.rol.nombre == "revisor" and re.search(r"VEREDICTO\s*:", texto)) \
                    or (sin_herramienta >= 1 and len(texto) >= 200):
                return self._cerrar(texto, paso, "completado")
            return None
        sin_tools = bool(self._prohibido & {"herramientas", "comandos"})
        if self.ctx.parciales:
            pendientes = ", ".join(f"{r} ({n} líneas)" for r, n in self.ctx.parciales.items())
            self._aviso_pendiente = (f"Hay archivos EN CONSTRUCCIÓN sin terminar: {pendientes}. Completalos con "
                                     "append_to_file (la última parte con last=true) antes de responder.")
            return None
        if anuncia_accion(texto) and anuncios < 2 and not sin_tools:
            return None
        if codigo_pegado(texto) and self._pide_cambios and not self.ctx.cambios and sin_herramienta < 1 \
                and "archivos" not in self._prohibido:
            return None
        if self.ctx.cambios:
            resultados = validar_archivos(self.ws, sorted(self.ctx.cambios))
            if fallos(resultados) and self._rechazos < 2:
                self._rechazos += 1
                self.ctx.tropiezo("cierre_rechazado")
                self._aviso_pendiente = ("Antes de responder: la validación REAL de los archivos que cambiaste falla:\n"
                                         + anexar_pistas(resumen_validacion(resultados), 2))
                return None
        motivo = self._falta_evidencia(texto)
        if motivo and self._rechazos < 2 and not sin_tools:
            self._rechazos += 1
            self.ctx.tropiezo("cumplimiento_falso")
            self.ui.aviso(f"  [{self.etiqueta}] respuesta rechazada: afirma una verificación sin evidencia")
            self._aviso_pendiente = self._rechazo_afirmacion(motivo)
            return None
        return self._cerrar(texto + self._nota_afirmacion(texto), paso, "respuesta")

    def _aviso_sin_herramienta(self, texto: str) -> str:
        pendiente = self._aviso_pendiente
        self._aviso_pendiente = ""
        if pendiente:
            return pendiente
        base = RECORDATORIO_EN if self.settings.idioma_prompts == "en" else RECORDATORIO
        if self.rol.nombre != "principal":
            return base
        if texto and anuncia_accion(texto):
            return ("Dijiste lo que ibas a hacer, pero no llamaste ninguna herramienta. Si vas a actuar, escribí la "
                    "herramienta en XML AHORA (no la anuncies). Si ya terminaste, escribí directamente la respuesta "
                    "final para el usuario.\n\n" + base)
        if texto and codigo_pegado(texto) and self._pide_cambios:
            return ("Pegaste código en el chat, pero el pedido es crear/cambiar archivos: para que exista de verdad "
                    "escribilo con write_to_file (archivo nuevo) o replace_symbol/replace_in_file (archivo existente)."
                    "\n\n" + base)
        return base + "\nSi el pedido era solo una pregunta, respondé directamente en texto (sin herramientas)."

    def _respuesta_por_bucle(self) -> str:
        partes = []
        texto = (self._ultimo_texto or "").strip()
        if texto and not anuncia_accion(texto):
            partes.append(texto)
        salida = (self._ultima_salida_ok or "").strip()
        if salida:
            partes.append("Resultado obtenido:\n" + recortar(salida, 1500))
        return "\n\n".join(partes) or "Ya tenía el resultado, pero el modelo repetía la misma herramienta."

    def _registrar_error(self, herramienta: str, ruta: str, salida: str) -> None:
        firma = _firma_error(salida)
        self._errores[firma] += 1
        self._errores_texto.append(recortar(salida, 3000))
        self._errores_texto = self._errores_texto[-6:]
        self._fallos_por_herramienta[(herramienta, ruta)] += 1

    def _sugerencia_por_repeticion(self, herramienta: str, ruta: str) -> str:
        veces = self._fallos_por_herramienta[(herramienta, ruta)]
        if veces < 2:
            return ""
        if herramienta == "replace_in_file":
            return ("\n\n(Ya falló {} veces en {}. Cambiá de estrategia: read_symbol + replace_symbol para "
                    "reemplazar la función entera, o read_file + replace_lines con los números actuales.)").format(veces, ruta)
        if herramienta in ("write_to_file", "append_to_file") and veces >= 2:
            return ("\n\n(Ya falló {} veces. Si el archivo es largo, escribilo en partes más chicas "
                    "(~100 líneas) y validá cada parte.)").format(veces)
        if herramienta == "run_tests" and veces >= 3:
            return ("\n\n(Los tests fallan una y otra vez. Leé con atención el PRIMER fallo, buscá la línea exacta "
                    "del código que lo causa con read_symbol y arreglá solo eso.)")
        return ""

    def _quizas_escalar(self, observaciones: list[str]) -> str:
        """Si el mismo error real se repite, pide un diagnóstico a un modelo más fuerte (una vez por tarea)."""
        if self._escalado or self.on_atascado is None or not self.settings.escalar:
            return ""
        if not self._errores:
            return ""
        firma, veces = self._errores.most_common(1)[0]
        if veces < self.settings.umbral_escalada:
            return ""
        self._escalado = True
        contexto = "\n\n".join(self._errores_texto[-2:])
        try:
            diagnostico = self.on_atascado(contexto)
        except (LLMError, OSError) as e:
            self.ui.aviso(f"  [{self.etiqueta}] la escalada falló: {e}")
            return ""
        if not diagnostico:
            return ""
        return ("DIAGNÓSTICO DE UN EXPERTO (un modelo más fuerte analizó el error que se repite). Aplicalo:\n"
                + recortar(diagnostico, 5000))

    def _continuar_corte(self, llamada: Llamada) -> tuple[str, bool]:
        """
        La respuesta se cortó por longitud en medio de write_to_file/append_to_file:
        se guarda lo escrito hasta la última línea completa y se pide continuar.
        """
        nombre = llamada.nombre

        def obs(texto: str) -> str:
            return f'<resultado herramienta="{nombre}">\n{texto}\n</resultado>'

        parcial = contenido_parcial(llamada, self._esquemas)
        ruta_txt = (llamada.params.get("path") or "").strip()
        if not parcial or not ruta_txt:
            self.ctx.tropiezo("llamada_incompleta")
            return obs("ERROR: tu respuesta se cortó antes de que se entendiera la herramienta. Escribí partes más "
                       "chicas (máximo ~150 líneas por mensaje)."), True
        _param, texto = parcial
        texto = cortar_en_linea_completa(texto)
        contador = self._continuaciones.get(ruta_txt, 0) + 1
        self._continuaciones[ruta_txt] = contador
        if contador > self.settings.max_continuaciones:
            return obs(f"ERROR: {ruta_txt} ya se cortó {contador - 1} veces. Dividí el archivo en módulos más "
                       "chicos o escribí partes de ~80 líneas."), True
        if len(texto.strip().splitlines()) < 3:
            self.ctx.tropiezo("llamada_incompleta")
            return obs("ERROR: tu respuesta se cortó casi al principio del contenido. Escribí partes más chicas."), True
        params = dict(llamada.params)
        params["content"] = texto
        if nombre == "write_to_file":
            params["partial"] = "true"
        else:
            params.pop("last", None)
            try:
                # Un append cortado deja el archivo incompleto: se valida recién al final.
                self.ctx.parciales.setdefault(self.ws.rel(self.ws.ruta(ruta_txt)), 0)
            except ErrorRuta:
                pass
        sintetica = Llamada(nombre, params, True, llamada.crudo)
        salida, error = self._ejecutar_herramienta(sintetica, {})
        if error:
            return salida, True
        try:
            rel = self.ws.rel(self.ws.ruta(ruta_txt))
            actual = self.ws.leer(rel)
        except (ErrorRuta, OSError, ValueError):
            return salida, False
        self.ctx.parciales[rel] = actual.count("\n")
        total = actual.count("\n")
        ultimas = "\n".join(f"{n:>5}| {l}" for n, l in
                            enumerate(actual.splitlines()[-8:], start=max(1, total - 7)))
        self.ui.tenue(f"      ↻ respuesta cortada: guardé {rel} hasta la línea {total}; el modelo sigue desde ahí")
        return salida + (
            f"\n\nTU RESPUESTA SE CORTÓ POR LONGITUD. Guardé {rel} hasta la línea {total} (solo líneas completas). "
            f"SEGUÍ DESDE la línea {total + 1} con append_to_file (sin repetir lo ya escrito; si es la última "
            f"parte poné last=true). Últimas líneas guardadas:\n{ultimas}"
        ), False

    def _marcar_lecturas_viejas(self, ruta: str) -> None:
        patron = re.compile(
            r'<resultado herramienta="(?:read_file|read_symbol)" ruta="' + re.escape(ruta) + r'">\n.*?\n</resultado>',
            re.S,
        )
        reemplazo = (
            f'<resultado herramienta="read_file" ruta="{ruta}">\n'
            f"[contenido viejo de {ruta} omitido: el archivo cambió después. Releelo si necesitás editarlo otra vez.]\n"
            "</resultado>"
        )
        quedan = []
        for indice, r in self._lecturas:
            if r == ruta and indice < len(self.mensajes):
                mensaje = self.mensajes[indice]
                mensaje["content"] = patron.sub(lambda _m: reemplazo, mensaje["content"])
            else:
                quedan.append((indice, r))
        self._lecturas = quedan

    def _intentar_terminar(self, hubo_error: bool, informe: str = "") -> tuple[bool, str, bool]:
        def obs(texto: str) -> str:
            return f'<resultado herramienta="attempt_completion">\n{texto}\n</resultado>'

        if hubo_error and self._rechazos < 2:
            self._rechazos += 1
            self.ctx.tropiezo("cierre_rechazado")
            return False, obs(
                "No acepto el cierre todavía: hubo errores en herramientas de este mismo mensaje. "
                "Revisá esos resultados y corregí antes de terminar."
            ), False

        if self.ctx.parciales and self._rechazos < 3:
            self._rechazos += 1
            pendientes = ", ".join(f"{r} ({n} líneas)" for r, n in self.ctx.parciales.items())
            return False, obs(
                f"Hay archivos EN CONSTRUCCIÓN sin terminar: {pendientes}. Completalos con append_to_file "
                "(la última parte con last=true) antes de terminar."
            ), False
        if self.ctx.parciales:
            self.ctx.parciales.clear()

        ok = True
        if self.ctx.cambios:
            resultados = validar_archivos(self.ws, sorted(self.ctx.cambios))
            if fallos(resultados):
                if self._rechazos < 2:
                    self._rechazos += 1
                    self.ctx.tropiezo("cierre_rechazado")
                    self.ui.aviso(f"  [{self.etiqueta}] cierre rechazado: la validación real falla")
                    return False, obs(
                        "No podés terminar todavía: la validación REAL de los archivos que cambiaste falla:\n"
                        + anexar_pistas(resumen_validacion(resultados), 2)
                    ), False
                ok = False
            elif self.rol.nombre in ("implementador", "escritor", "reparador") and self._rechazos < 2:
                vacias = []
                for rel in sorted(self.ctx.cambios):
                    if rel.endswith(".py") and (self.ws.raiz / rel).is_file() and rel not in self.ctx.protegidos:
                        try:
                            for nombre, linea in funciones_vacias_python(self.ws.leer(rel)):
                                vacias.append(f"{rel}:{linea} {nombre}")
                        except (OSError, ValueError, ErrorRuta):
                            continue
                if vacias:
                    self._rechazos += 1
                    self.ctx.tropiezo("funcion_vacia")
                    return False, obs(
                        "Quedaron funciones sin implementar (cuerpo pass/.../NotImplementedError): "
                        + ", ".join(vacias[:8]) + ". Implementalas con replace_symbol antes de terminar "
                        "(si alguna es intencional, explicá por qué en el informe y volvé a cerrar)."
                    ), False
        motivo = self._falta_evidencia(informe)
        if motivo and self._rechazos < 3:
            self._rechazos += 1
            self.ctx.tropiezo("cumplimiento_falso")
            self.ui.aviso(f"  [{self.etiqueta}] cierre rechazado: afirma una verificación sin evidencia")
            return False, obs(self._rechazo_afirmacion(motivo)), False
        return True, "", ok

    def _delegar(self, grupo: list) -> tuple[list[str], bool]:
        def obs(texto: str, rol: str = "?") -> str:
            return f'<resultado herramienta="delegate" rol="{rol}">\n{texto}\n</resultado>'

        if not self.rol.puede_delegar or self.profundidad >= self.settings.max_profundidad:
            return [obs("ERROR: no podés lanzar subagentes desde acá; hacé la tarea vos.")] * len(grupo), True

        salida: list[Optional[str]] = [None] * len(grupo)
        specs = []
        error = False
        for k, llamada in enumerate(grupo):
            rol = (llamada.params.get("role") or "").strip().lower()
            rol = ALIAS_ROLES.get(rol, rol)
            tarea = (llamada.params.get("task") or "").strip()
            if rol not in ROLES_DELEGABLES or not tarea:
                salida[k] = obs(
                    f"ERROR: rol inválido o tarea vacía. Roles válidos: {', '.join(ROLES_DELEGABLES)}", rol or "?"
                )
                error = True
                continue
            specs.append((k, rol, tarea, llamada.params.get("files") or ""))

        resultados = ejecutar_subagentes(
            [(rol, tarea, archivos, "", {"memoria": self.memoria, "on_atascado": self.on_atascado})
             for _, rol, tarea, archivos in specs],
            self.llm, self.ws, self.settings, self.ui,
            profundidad=self.profundidad + 1,
            cid_inicio=self.ctx.cid_inicio,
        )
        for (k, rol, _tarea, _archivos), res in zip(specs, resultados):
            self.ctx.cambios.update(res.cambios)
            estado = "COMPLETADO" if res.ok else f"NO COMPLETADO ({res.motivo})"
            salida[k] = obs(
                f"Subagente {rol}: {estado} en {res.pasos} pasos.\n"
                f"Archivos cambiados: {', '.join(res.cambios) or 'ninguno'}\n"
                f"Informe:\n{recortar(redactar_secretos(res.resumen), 6000)}",
                rol,
            )
            error |= not res.ok
        return [s or obs("ERROR interno") for s in salida], error

    # ------------------------------------------------------------ contexto
    def _tamano(self) -> int:
        return sum(len(m["content"]) for m in self.mensajes)

    def _limite_contexto(self) -> int:
        contexto = min(self.settings.contexto_tokens,
                       info_modelo(self.modelo or self.settings.modelo_para(self.rol.nombre)).contexto)
        return int((contexto - self.settings.max_tokens) * 0.85 * CARACTERES_POR_TOKEN * self._factor_contexto)

    def _compactar(self, forzar: bool = False) -> None:
        limite = self._limite_contexto()
        if self._tamano() <= limite and not forzar:
            return
        proteger = max(self._indice_tarea + 1, len(self.mensajes) - 6)

        # Fase 1: resultados viejos largos → resumen corto.
        for i in range(1, proteger):
            m = self.mensajes[i]
            if m["role"] == "user" and "<resultado" in m["content"]:
                m["content"] = _RE_RESULTADO.sub(_stub_resultado, m["content"])
                if self._tamano() <= limite and not forzar:
                    return
        # Fase 2: código ya aplicado en mensajes viejos del modelo.
        for i in range(1, proteger):
            m = self.mensajes[i]
            if m["role"] == "assistant":
                m["content"] = _RE_LARGO.sub(_stub_largo, m["content"])
                if self._tamano() <= limite and not forzar:
                    return
        if self._tamano() <= limite:
            return
        # Fase 3: descartar el medio de la conversación (se conserva la tarea y la cola).
        if self._indice_tarea >= proteger:
            cola = self.mensajes[self._indice_tarea:]
            descartados = self._indice_tarea - 1
            nuevos = [self.mensajes[0]] + cola
            indice = 1
        else:
            inicio = proteger
            while inicio < len(self.mensajes) and self.mensajes[inicio]["role"] != "assistant":
                inicio += 1
            descartados = inicio - self._indice_tarea - 1
            nuevos = [self.mensajes[0], dict(self.mensajes[self._indice_tarea])] + self.mensajes[inicio:]
            indice = 1
        if descartados > 0:
            todo = "\n".join(f"[{e}] {t}" for e, t in self.ctx.todo)
            nota = f"\n\n[REAPER: se omitieron {descartados} mensajes anteriores para ahorrar contexto."
            if todo:
                nota += f" Tu lista de tareas actual:\n{todo}"
            if self.ctx.cambios:
                nota += f"\nArchivos que ya cambiaste: {', '.join(sorted(self.ctx.cambios))}"
            if self.ctx.parciales:
                nota += "\nArchivos EN CONSTRUCCIÓN (seguí con append_to_file): " + ", ".join(
                    f"{r} ({n} líneas)" for r, n in self.ctx.parciales.items())
            if self._errores_texto:
                nota += "\nÚltimo error real visto:\n" + recortar(self._errores_texto[-1], 1200)
            nuevos[indice] = {"role": "user", "content": nuevos[indice]["content"] + nota + "]"}
        self.mensajes = nuevos
        self._indice_tarea = indice
        self._lecturas = []
        # Último recurso: recortar todo resultado salvo el del último mensaje.
        if self._tamano() > limite:
            for m in self.mensajes[1:-1]:
                if m["role"] == "user":
                    m["content"] = _RE_RESULTADO.sub(_stub_resultado, m["content"])
                else:
                    m["content"] = _RE_LARGO.sub(_stub_largo, m["content"])
        if self._tamano() > limite and len(self.mensajes) > 2:
            ultimo = self.mensajes[-1]
            ultimo["content"] = recortar(ultimo["content"], max(2000, limite // 3))


def _titulo(tarea: str) -> str:
    """Primera línea útil de la tarea (saltea encabezados tipo 'PEDIDO DEL USUARIO:')."""
    for linea in tarea.splitlines():
        linea = linea.strip()
        if linea and not (linea.endswith(":") and linea.upper() == linea):
            return linea[:100] + ("…" if len(linea) > 100 else "")
    return "(sin descripción)"


def ejecutar_subagentes(
    specs: list,
    llm,
    ws: Workspace,
    settings: Settings,
    ui: UI,
    *,
    profundidad: int = 1,
    cid_inicio: Optional[int] = None,
    max_paralelo: Optional[int] = None,
) -> list[ResultadoAgente]:
    """
    Corre subagentes. specs: (rol, tarea, archivos[, título[, opciones]]).
    opciones es un dict con kwargs para Agente (temperatura, modelo, memoria,
    protegidos, extra_prompt, max_pasos, on_atascado) y opcionalmente 'ws'
    (otro workspace, p. ej. una copia aislada) y 'cid' (checkpoint inicial).

    Corren en paralelo si todos son de solo lectura o si cada uno trabaja en
    su propio workspace (copias aisladas); si no, van en secuencia para no
    pisarse archivos.
    """
    def opciones_de(spec) -> dict:
        return dict(spec[4]) if len(spec) > 4 and isinstance(spec[4], dict) else {}

    espacios = [opciones_de(s).get("ws") for s in specs]
    aislados = all(e is not None for e in espacios) and len({id(e) for e in espacios}) == len(espacios)
    limite = max_paralelo or settings.paralelo
    paralelo = (
        len(specs) > 1
        and limite > 1
        and (all(ROLES[spec[0]].solo_lectura for spec in specs) or aislados)
    )

    def correr(spec, progreso: bool) -> ResultadoAgente:
        rol, tarea, archivos = spec[0], spec[1], spec[2]
        titulo = spec[3] if len(spec) > 3 and spec[3] else _titulo(tarea)
        opciones = opciones_de(spec)
        ws_agente = opciones.pop("ws", None) or ws
        cid = opciones.pop("cid", cid_inicio)
        etiqueta_extra = opciones.pop("etiqueta", None)
        agente = Agente(rol, llm, ws_agente, settings, ui, profundidad=profundidad,
                        mostrar_progreso=progreso, cid_inicio=cid, etiqueta=etiqueta_extra, **opciones)
        ui.agente(agente.etiqueta, f"↳ {titulo}")
        texto = tarea + (f"\n\nArchivos relevantes: {archivos}" if archivos else "") + SUFIJO_SUBTAREA
        try:
            res = agente.ejecutar(texto)
        except (Cancelado, KeyboardInterrupt, LLMError):
            # Si el modelo no responde (después de reintentos y respaldos) no tiene sentido seguir.
            raise
        except Exception as e:
            res = ResultadoAgente(False, f"{type(e).__name__}: {e}", sorted(agente.ctx.cambios), 0, "error", rol)
        ui.agente(agente.etiqueta, ("✓ terminó" if res.ok else f"✗ no completó ({res.motivo})") + f" · {res.pasos} pasos")
        return res

    if not paralelo:
        return [correr(s, True) for s in specs]

    ui.tenue(f"  ⇉ {len(specs)} subagentes en paralelo (máx {limite} a la vez)")
    ejecutor = ThreadPoolExecutor(max_workers=min(limite, len(specs)))
    try:
        futuros = [ejecutor.submit(correr, s, False) for s in specs]
        return [f.result() for f in futuros]
    except (KeyboardInterrupt, Cancelado):
        CANCELAR.set()
        raise
    finally:
        ejecutor.shutdown(wait=not CANCELAR.is_set(), cancel_futures=True)
