"""
Lecciones que se acumulan entre sesiones.

Dos archivos Markdown editables a mano:
  - <proyecto>/.reaper/lecciones.md   hechos del proyecto ("acá los tests se corren con X",
                                       "content.js expone un objeto global, no un módulo")
  - ~/reaper/lecciones.md             errores típicos del modelo ("en archivos largos se olvida
                                       de cerrar </content>")

Cómo se llenan:
  1. Cada vez que el reparador arregla un fallo REAL (la verificación pasa de
     fallar a pasar), REAPER le pide al modelo una lección de una línea sobre
     la causa y la guarda (deduplicada: si ya existe una parecida, suma +1).
  2. REAPER cuenta los tropiezos del modelo (llamadas cortadas, SEARCH que no
     coincide, '...' perezosos). Cuando un tropiezo se repite, se convierte
     solo en una lección general, sin gastar llamadas.

Cómo se usan: las lecciones más relevantes para la tarea (por palabras en
común y por cuántas veces se confirmaron) entran en el system prompt.
"""

_RE_LECCION = re.compile(r"^\s*[-*]\s*(?:\[(\d+)\]\s*)?(.+?)\s*(?:<!--\s*(\S+)\s*-->)?\s*$")
MAX_LECCIONES_PROYECTO = 60
MAX_LECCIONES_GLOBALES = 40


@dataclass
class Leccion:
    texto: str
    veces: int = 1
    fecha: str = ""

    def linea(self) -> str:
        fecha = f"  <!-- {self.fecha} -->" if self.fecha else ""
        return f"- [{self.veces}] {self.texto}{fecha}"


def normalizar_leccion(texto: str) -> str:
    texto = " ".join((texto or "").replace("\n", " ").split())
    texto = texto.strip(" -*•\"'")
    texto = re.sub(r"^(lecci[oó]n|proyecto|general)\s*:\s*", "", texto, flags=re.I)
    if len(texto) > 220:
        texto = texto[:217].rstrip() + "..."
    return texto


def _tokens_leccion(texto: str) -> set[str]:
    return {_raiz(t) for t in re.findall(r"[a-z0-9_./-]{3,}", sin_tildes(texto.lower())) if t not in PALABRAS_VACIAS}


def similitud_lecciones(a: str, b: str) -> float:
    ta, tb = _tokens_leccion(a), _tokens_leccion(b)
    if not ta or not tb:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()
    jaccard = len(ta & tb) / len(ta | tb)
    return max(jaccard, SequenceMatcher(None, a.lower(), b.lower()).ratio() * 0.9)


_RE_GENERICA = re.compile(
    r"^(siempre|nunca|es importante|hay que|recordar|asegurarse|asegurate)\b.{0,40}"
    r"(verific|revis|test|prob|cuidado|atenci|bien|correct)", re.I)


def es_leccion_util(texto: str) -> bool:
    """Descarta lecciones vacías de contenido ("siempre verificar el código")."""
    texto = normalizar_leccion(texto)
    if len(texto) < 15 or texto.upper() in ("NINGUNA", "NINGUNO", "N/A", "NADA"):
        return False
    if "```" in texto:
        return False
    especifico = bool(re.search(r"[`/_.()<>=]|--|\b[A-Z][a-z]+[A-Z]\w*|\b\w+\.\w{1,4}\b|\d", texto))
    if _RE_GENERICA.search(texto) and not especifico:
        return False
    return len(_tokens_leccion(texto)) >= 3


class ArchivoLecciones:
    def __init__(self, ruta: Path, titulo: str, maximo: int):
        self.ruta = ruta
        self.titulo = titulo
        self.maximo = maximo
        self._lock = threading.Lock()

    def cargar(self) -> list[Leccion]:
        try:
            texto = self.ruta.read_text(encoding="utf-8")
        except OSError:
            return []
        lecciones = []
        for linea in texto.splitlines():
            if not linea.strip().startswith(("-", "*")):
                continue
            m = _RE_LECCION.match(linea)
            if not m:
                continue
            contenido = normalizar_leccion(m.group(2))
            if contenido:
                lecciones.append(Leccion(contenido, int(m.group(1) or 1), m.group(3) or ""))
        return lecciones

    def guardar(self, lecciones: list[Leccion]) -> None:
        cabecera = (f"# {self.titulo}\n\n"
                    "<!-- Una lección por línea. REAPER las agrega y ordena solo; podés editarlas o borrarlas.\n"
                    "     El número entre corchetes es cuántas veces se confirmó. -->\n\n")
        cuerpo = "\n".join(l.linea() for l in lecciones)
        try:
            escritura_atomica(self.ruta, cabecera + cuerpo + "\n")
        except OSError:
            pass

    def agregar(self, texto: str) -> Optional[str]:
        """Agrega o refuerza una lección. Devuelve 'nueva', 'reforzada' o None si se descartó."""
        texto = normalizar_leccion(texto)
        if not es_leccion_util(texto):
            return None
        with self._lock:
            lecciones = self.cargar()
            for l in lecciones:
                if similitud_lecciones(l.texto, texto) >= 0.72:
                    l.veces += 1
                    l.fecha = datetime.now().strftime("%Y-%m-%d")
                    if len(texto) > len(l.texto) and l.veces <= 2:
                        l.texto = texto  # la versión más específica gana mientras la lección es joven
                    self.guardar(self._ordenar(lecciones))
                    return "reforzada"
            lecciones.append(Leccion(texto, 1, datetime.now().strftime("%Y-%m-%d")))
            self.guardar(self._ordenar(lecciones))
            return "nueva"

    def borrar(self, indice: int) -> Optional[Leccion]:
        with self._lock:
            lecciones = self.cargar()
            if 0 <= indice < len(lecciones):
                quitada = lecciones.pop(indice)
                self.guardar(lecciones)
                return quitada
        return None

    def _ordenar(self, lecciones: list[Leccion]) -> list[Leccion]:
        orden = sorted(lecciones, key=lambda l: (-l.veces, l.fecha or ""), reverse=False)
        if len(orden) > self.maximo:
            # Se descartan las menos confirmadas y más viejas.
            conservar = sorted(orden, key=lambda l: (l.veces, l.fecha or ""), reverse=True)[: self.maximo]
            orden = [l for l in orden if l in conservar]
        return orden


def ranking_lecciones(lecciones: Sequence[Leccion], consulta: str, k: int) -> list[Leccion]:
    if k <= 0 or not lecciones:
        return []
    tokens = _tokens_leccion(consulta or "")
    puntuadas = []
    for orden, l in enumerate(lecciones):
        comunes = len(tokens & _tokens_leccion(l.texto)) if tokens else 0
        puntaje = comunes * 2.0 + math.log(1 + l.veces) - orden * 0.01
        puntuadas.append((puntaje, orden, l))
    puntuadas.sort(key=lambda t: (-t[0], t[1]))
    return [l for _, _, l in puntuadas[:k]]


TROPIEZOS = {
    "llamada_incompleta": (3, "En archivos largos escribí por partes (write_to_file con ~150 líneas y después "
                              "append_to_file) y cerrá siempre </content> y la etiqueta de la herramienta."),
    "search_fallido": (3, "Antes de replace_in_file releé el tramo exacto con read_file; para cambiar una función "
                          "entera usá replace_symbol en vez de SEARCH/REPLACE."),
    "marcador_perezoso": (2, "Nunca escribas '...', '# resto igual' ni código omitido: el contenido va completo o se "
                             "edita solo el tramo con replace_in_file."),
    "sin_herramienta": (3, "Cada respuesta lleva una herramienta en XML (o attempt_completion); no pegues código "
                           "suelto en el chat porque no se guarda en ningún archivo."),
    "import_inexistente": (2, "Antes de importar algo de un módulo del proyecto verificá que exista con read_symbol o "
                              "search_files (el validador 'imports-locales' lo rechaza)."),
    "funcion_vacia": (2, "No dejes funciones con pass/... al terminar: implementá el cuerpo real con replace_symbol."),
    "cierre_rechazado": (3, "Antes de attempt_completion corré validate y run_tests y corregí lo que fallen."),
}


class MemoriaLecciones:
    """Las dos fuentes de lecciones (proyecto + general) más el contador de tropiezos."""

    def __init__(self, ws: Workspace, ruta_global: Optional[Path] = None):
        self.ws = ws
        self.proyecto = ArchivoLecciones(ws.raiz / ".reaper" / "lecciones.md",
                                         f"Lecciones de REAPER · {ws.raiz.name}", MAX_LECCIONES_PROYECTO)
        self.general = ArchivoLecciones(ruta_global or LECCIONES_GLOBALES,
                                        "Lecciones generales de REAPER (errores típicos del modelo)",
                                        MAX_LECCIONES_GLOBALES)
        self._ruta_tropiezos = (ruta_global or LECCIONES_GLOBALES).with_name("tropiezos.json")
        self._lock = threading.Lock()

    def para_prompt(self, consulta: str, k: int = 8) -> str:
        if k <= 0:
            return ""
        proyecto = ranking_lecciones(self.proyecto.cargar(), consulta, max(1, k * 5 // 8))
        general = ranking_lecciones(self.general.cargar(), consulta, max(1, k - len(proyecto)))
        partes = []
        if proyecto:
            partes.append("De este proyecto:\n" + "\n".join(f"- {l.texto}" for l in proyecto))
        if general:
            partes.append("Errores que ya cometiste antes (no los repitas):\n" + "\n".join(f"- {l.texto}" for l in general))
        return "\n".join(partes)

    def registrar(self, proyecto: Iterable[str] = (), general: Iterable[str] = ()) -> list[str]:
        hechos = []
        for texto in proyecto:
            estado = self.proyecto.agregar(texto)
            if estado:
                hechos.append(f"proyecto ({estado}): {normalizar_leccion(texto)}")
        for texto in general:
            estado = self.general.agregar(texto)
            if estado:
                hechos.append(f"general ({estado}): {normalizar_leccion(texto)}")
        return hechos

    def tropiezo(self, tipo: str) -> Optional[str]:
        """Cuenta un tropiezo del modelo; al llegar al umbral se convierte en lección general."""
        if tipo not in TROPIEZOS:
            return None
        umbral, leccion = TROPIEZOS[tipo]
        with self._lock:
            try:
                datos = json.loads(self._ruta_tropiezos.read_text(encoding="utf-8"))
                if not isinstance(datos, dict):
                    datos = {}
            except (OSError, ValueError):
                datos = {}
            datos[tipo] = int(datos.get(tipo, 0)) + 1
            try:
                self._ruta_tropiezos.parent.mkdir(parents=True, exist_ok=True)
                self._ruta_tropiezos.write_text(json.dumps(datos, indent=1), encoding="utf-8")
            except OSError:
                pass
            alcanzado = datos[tipo] % umbral == 0
        if alcanzado:
            return self.general.agregar(leccion)
        return None


PROMPT_LECCION = """Un agente de programación tuvo un fallo REAL y otro agente lo reparó. Escribí la lección que
evitaría repetirlo, en UNA línea concreta (máximo 25 palabras), con nombres reales de archivos, comandos o
funciones. Separá:
- PROYECTO: un hecho de ESTE proyecto (cómo se testea, una convención, cómo está armado un archivo).
- GENERAL: un error típico del modelo que vale para cualquier proyecto.
Si no hay nada específico que aprender en alguna de las dos, escribí NINGUNA. Nada de consejos genéricos como
"verificar bien el código".

FALLO ORIGINAL:
{diagnostico}

CAMBIO QUE LO ARREGLÓ:
{diff}

INFORME DEL REPARADOR:
{informe}

Respondé EXACTAMENTE con este formato:
PROYECTO: ...
GENERAL: ..."""


def parsear_lecciones(texto: str) -> tuple[list[str], list[str]]:
    proyecto, general = [], []
    for linea in (texto or "").splitlines():
        m = re.match(r"^\s*[-*]?\s*\**\s*(PROYECTO|GENERAL)\s*\**\s*:\s*(.+)$", linea.strip(), re.I)
        if not m:
            continue
        contenido = normalizar_leccion(m.group(2))
        if not es_leccion_util(contenido):
            continue
        (proyecto if m.group(1).upper() == "PROYECTO" else general).append(contenido)
    return proyecto[:1], general[:1]


def lecciones_heuristicas(diagnostico: str, ws: Optional[Workspace] = None) -> tuple[list[str], list[str]]:
    """Lecciones que se pueden deducir sin modelo a partir del error real."""
    proyecto, general = [], []
    texto = diagnostico or ""
    m = re.search(r"ModuleNotFoundError: No module named '([\w.]+)'", texto)
    if m:
        modulo = m.group(1).split(".")[0]
        if ws and ((ws.raiz / f"{modulo}.py").exists() or (ws.raiz / modulo).is_dir()):
            proyecto.append(f"El módulo local `{modulo}` se importa desde la raíz: los comandos se corren desde la raíz del proyecto.")
        else:
            proyecto.append(f"`{modulo}` no está instalado en este entorno: usar la librería estándar o instalarlo con pip.")
    if re.search(r"Cannot use import statement outside a module", texto):
        proyecto.append("Los .js de este proyecto se ejecutan como CommonJS: usar .mjs o \"type\": \"module\" para import/export.")
    if re.search(r"(document|window|localStorage) is not defined", texto):
        general.append("La lógica de los .js del navegador va en un módulo sin DOM para poder testearla con node:test.")
    m = re.search(r"imports-locales .*?: .*? no define '(\w+)'", texto, re.S)
    if m:
        general.append(f"Verificar con read_symbol que una función existe antes de importarla (pasó con `{m.group(1)}`).")
    return proyecto, general


def extraer_lecciones(llm, modelo: str, diagnostico: str, diff: str, informe: str,
                      ws: Optional[Workspace] = None) -> tuple[list[str], list[str]]:
    """Pide al modelo una lección (barato: una llamada corta) y completa con heurísticas."""
    proyecto_h, general_h = lecciones_heuristicas(diagnostico, ws)
    try:
        respuesta = llm.chat_simple(
            PROMPT_LECCION.format(diagnostico=recortar(diagnostico, 2500), diff=recortar(diff, 2500),
                                  informe=recortar(informe, 1200)),
            modelo=modelo, temperatura=0.1, max_tokens=220, rol="lecciones",
        )
        proyecto, general = parsear_lecciones(respuesta)
    except (LLMError, AttributeError):
        proyecto, general = [], []
    return (proyecto or proyecto_h)[:1], (general or general_h)[:1]
