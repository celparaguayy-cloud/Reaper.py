"""
Mapa de archivos relevantes para un pedido.

Un modelo de 24B explora mal: abre archivos al azar y se queda sin contexto.
REAPER le da resuelto, ANTES de empezar, qué archivos y funciones tocan el
pedido. Cruza las palabras del pedido (normalizadas, sin tildes, con
traducción español→inglés de conceptos de programación frecuentes) con:
  - la ruta del archivo (peso alto)
  - los nombres de funciones/clases (peso medio)
  - los identificadores del contenido (peso bajo, con IDF)
y después propaga relevancia por el grafo de imports (si a.py importa b.py
y a.py es muy relevante, b.py también sube un poco).
"""

PALABRAS_VACIAS = {
    # español
    "que", "con", "para", "por", "los", "las", "una", "uno", "unos", "unas", "del", "al", "el", "la", "de",
    "en", "y", "o", "a", "se", "su", "sus", "lo", "le", "les", "mas", "más", "como", "cuando", "donde",
    "este", "esta", "esto", "estos", "estas", "ese", "esa", "eso", "hay", "tiene", "tener", "hacer", "haga",
    "hace", "quiero", "necesito", "podes", "puedes", "favor", "agrega", "agregá", "agregar", "agregue",
    "crea", "creá", "crear", "cree", "modifica", "modificá", "modificar", "cambia", "cambiá", "cambiar",
    "arregla", "arreglá", "arreglar", "implementa", "implementá", "implementar", "nuevo", "nueva",
    "nuevos", "nuevas", "todo", "toda", "todos", "todas", "sea", "sean", "ser", "esta", "están", "estan",
    "algo", "cada", "entre", "sobre", "sin", "pero", "tambien", "también", "muy", "ya", "solo", "sólo",
    "archivo", "archivos", "codigo", "código", "funcion", "función", "funciones", "programa", "proyecto",
    "mi", "mis", "tu", "tus", "me", "te", "nos", "hola", "gracias", "bien", "mal", "usar", "usando",
    # inglés
    "the", "and", "for", "with", "that", "this", "from", "into", "add", "create", "make", "fix", "update",
    "change", "implement", "new", "file", "files", "code", "function", "please", "should", "would", "use",
    "using", "all", "some", "any", "can", "will", "not", "are", "was", "has", "have",
}

TRADUCCIONES = {
    "usuario": ["user"], "usuarios": ["user", "users"], "contrasena": ["password", "pass"],
    "clave": ["password", "key"], "carrito": ["cart"], "producto": ["product", "item"],
    "productos": ["product", "products", "item"], "pedido": ["order", "request"], "pedidos": ["order", "orders"],
    "factura": ["invoice", "bill"], "fecha": ["date", "time"], "fechas": ["date", "dates"],
    "buscar": ["search", "find", "query"], "busqueda": ["search", "query"], "guardar": ["save", "store", "write"],
    "borrar": ["delete", "remove"], "eliminar": ["delete", "remove"], "sesion": ["session", "login"],
    "ingreso": ["login", "signin"], "correo": ["email", "mail"], "precio": ["price", "cost"],
    "cliente": ["client", "customer"], "clientes": ["client", "customer"], "nota": ["note"], "notas": ["note", "notes"],
    "tarea": ["task", "todo"], "tareas": ["task", "tasks", "todo"], "lista": ["list"], "listar": ["list"],
    "base": ["db", "database"], "datos": ["data", "db"], "prueba": ["test"], "pruebas": ["test", "tests"],
    "configuracion": ["config", "settings"], "ajustes": ["settings", "config"], "juego": ["game"],
    "puntaje": ["score"], "puntos": ["score", "points"], "jugador": ["player"], "mensaje": ["message", "msg"],
    "mensajes": ["message", "messages"], "pagina": ["page"], "boton": ["button", "btn"], "imagen": ["image", "img"],
    "tabla": ["table"], "reporte": ["report"], "informe": ["report"], "inventario": ["inventory", "stock"],
    "venta": ["sale", "sales"], "ventas": ["sale", "sales"], "compra": ["purchase", "buy"], "pago": ["payment", "pay"],
    "pagos": ["payment", "payments"], "cuenta": ["account"], "registro": ["register", "signup", "log"],
    "autenticacion": ["auth", "authentication"], "permiso": ["permission", "role"], "rol": ["role"],
    "archivo": ["file"], "carpeta": ["folder", "dir"], "ruta": ["path", "route"], "rutas": ["route", "routes", "path"],
    "servidor": ["server"], "peticion": ["request"], "respuesta": ["response"], "error": ["error", "exception"],
    "errores": ["error", "errors"], "validar": ["validate", "validation"], "validacion": ["validation", "validate"],
    "formulario": ["form"], "menu": ["menu"], "ventana": ["window"], "pantalla": ["screen"], "vista": ["view"],
    "modelo": ["model"], "plantilla": ["template"], "estilo": ["style", "css"], "estilos": ["style", "styles", "css"],
    "calculadora": ["calculator", "calc"], "calcular": ["calculate", "compute"], "suma": ["sum", "add"],
    "resta": ["subtract", "sub"], "total": ["total", "sum"], "promedio": ["average", "mean", "avg"],
    "ordenar": ["sort"], "filtrar": ["filter"], "exportar": ["export"], "importar": ["import"], "leer": ["read", "load"],
    "escribir": ["write"], "cargar": ["load"], "enviar": ["send"], "recibir": ["receive"], "descargar": ["download"],
    "subir": ["upload"], "imprimir": ["print"], "mostrar": ["show", "display", "render"], "dibujar": ["draw", "render"],
    "cache": ["cache"], "registrar": ["log", "register"], "bitacora": ["log"], "historial": ["history"],
    "comando": ["command", "cmd"], "comandos": ["command", "commands", "cli"], "consola": ["console", "cli", "terminal"],
    "red": ["network", "net"], "conexion": ["connection", "connect"], "hilo": ["thread"], "cola": ["queue"],
    "evento": ["event"], "eventos": ["event", "events"], "temporizador": ["timer"], "reloj": ["clock", "timer"],
    "alarma": ["alarm"], "clima": ["weather"], "moneda": ["currency", "coin"], "dinero": ["money"], "banco": ["bank"],
    "libro": ["book"], "libros": ["book", "books"], "biblioteca": ["library"], "autor": ["author"], "contacto": ["contact"],
    "contactos": ["contact", "contacts"], "agenda": ["agenda", "contacts", "calendar"], "calendario": ["calendar"],
    "chat": ["chat"], "bot": ["bot"], "api": ["api"], "token": ["token", "auth"], "cifrar": ["encrypt"],
    "descifrar": ["decrypt"], "hash": ["hash"], "migracion": ["migration"], "esquema": ["schema"],
}

_RE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_RE_CAMEL = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def sin_tildes(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in normal if not unicodedata.combining(ch))


def partir_identificador(nombre: str) -> list[str]:
    """'guardarUsuario_v2' → ['guardar', 'usuario', 'v2']"""
    partes = []
    for trozo in re.split(r"[_\W]+", nombre):
        if not trozo:
            continue
        partes.extend(p.lower() for p in _RE_CAMEL.findall(trozo) or [trozo])
    return [p for p in partes if p]


def _raiz(palabra: str) -> str:
    """Stemming mínimo (plurales y algunas terminaciones) para que 'usuarios' encuentre 'usuario'."""
    p = palabra
    for sufijo in ("ciones", "cion", "mente", "es", "s"):
        if len(p) > len(sufijo) + 3 and p.endswith(sufijo):
            p = p[: -len(sufijo)]
            break
    return p


def tokens_pedido(pedido: str) -> dict[str, float]:
    """Tokens del pedido con peso (las traducciones pesan un poco menos que la palabra original)."""
    texto = sin_tildes(pedido or "").lower()
    pesos: dict[str, float] = {}
    crudos = re.findall(r"[a-z_][a-z0-9_.]{1,}", texto)
    for crudo in crudos:
        # nombres de archivo mencionados explícitamente valen mucho
        if "." in crudo and re.search(r"\.(py|js|ts|mjs|html|css|json|sh|go|rs|java|md)$", crudo):
            pesos[crudo] = pesos.get(crudo, 0) + 6.0
        for parte in partir_identificador(crudo):
            if len(parte) < 3 or parte in PALABRAS_VACIAS:
                continue
            raiz = _raiz(parte)
            pesos[raiz] = pesos.get(raiz, 0) + 1.0
            for traduccion in TRADUCCIONES.get(parte, []) + TRADUCCIONES.get(raiz, []):
                pesos[_raiz(traduccion)] = max(pesos.get(_raiz(traduccion), 0), 0.8)
    return pesos


@dataclass
class DocumentoArchivo:
    rel: str
    ruta_tokens: set
    simbolos: list
    simbolo_tokens: dict  # token → [nombres de símbolos]
    contenido: collections.Counter
    imports: set
    lineas: int


def _imports_archivo(ws: Workspace, rel: str, texto: str) -> set[str]:
    destino: set[str] = set()
    ruta = ws.raiz / rel
    if rel.endswith(".py"):
        for m in re.finditer(r"^\s*(?:from\s+(\.*)([\w.]*)\s+import\s+([\w, ]+)|import\s+([\w.]+))", texto, re.M):
            puntos, modulo, nombres, simple = m.group(1) or "", m.group(2) or "", m.group(3) or "", m.group(4)
            candidatos = []
            if simple:
                candidatos.append((0, simple))
            else:
                candidatos.append((len(puntos), modulo))
                for n in nombres.split(","):
                    n = n.strip()
                    if n:
                        candidatos.append((len(puntos), f"{modulo}.{n}" if modulo else n))
            for nivel, mod in candidatos:
                base = ruta.parent if nivel else ws.raiz
                for _ in range(max(0, nivel - 1)):
                    base = base.parent
                partes = [p for p in mod.split(".") if p]
                if not partes:
                    continue
                for raiz in ([base] if nivel else [ws.raiz, ws.raiz / "src", ruta.parent]):
                    archivo = raiz.joinpath(*partes)
                    for c in (archivo.with_suffix(".py"), archivo / "__init__.py"):
                        if c.is_file():
                            destino.add(ws.rel(c))
                            break
    elif Path(rel).suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html"):
        for m in re.finditer(r"""(?:from\s+|require\(\s*|import\s*\(\s*|src=)["'](\.{1,2}/[^"']+|[\w./-]+\.(?:js|mjs|css))["']""", texto):
            resuelto = _resolver_js(ruta.parent, m.group(1)) if m.group(1).startswith(".") else (ruta.parent / m.group(1))
            if resuelto and Path(resuelto).is_file():
                destino.add(ws.rel(Path(resuelto)))
    return destino


class MapaRepositorio:
    """Índice ligero para rankear archivos según un pedido."""

    def __init__(self, ws: Workspace, max_archivos: int = 1200):
        self.ws = ws
        self.max_archivos = max_archivos
        self.documentos: dict[str, DocumentoArchivo] = {}
        self._firma: Optional[tuple] = None

    def _firma_actual(self) -> tuple:
        firma = []
        for rel in self.ws.archivos_codigo(limite=self.max_archivos):
            try:
                st = (self.ws.raiz / rel).stat()
                firma.append((rel, st.st_mtime, st.st_size))
            except OSError:
                continue
        return tuple(firma)

    def construir(self) -> "MapaRepositorio":
        firma = self._firma_actual()
        if firma == self._firma:
            return self
        indice = indice_de(self.ws)
        documentos = {}
        for rel, _mtime, tam in firma:
            if tam > 400_000:
                continue
            try:
                texto = (self.ws.raiz / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            ruta_tokens = set()
            for parte in Path(rel).with_suffix("").parts:
                ruta_tokens.update(_raiz(sin_tildes(p)) for p in partir_identificador(parte))
            ruta_tokens.add(Path(rel).name.lower())
            simbolos = indice.de_archivo(rel)
            simbolo_tokens: dict[str, list] = {}
            for s in simbolos:
                for p in partir_identificador(s.nombre):
                    simbolo_tokens.setdefault(_raiz(sin_tildes(p)), []).append(s)
            contenido = collections.Counter()
            for ident in _RE_IDENT.findall(texto[:200_000]):
                for p in partir_identificador(ident):
                    if len(p) >= 3:
                        contenido[_raiz(sin_tildes(p))] += 1
            for palabra in re.findall(r"[a-záéíóúñ]{4,}", sin_tildes(texto[:100_000]).lower()):
                contenido[_raiz(palabra)] += 1
            documentos[rel] = DocumentoArchivo(rel, ruta_tokens, simbolos, simbolo_tokens, contenido,
                                               _imports_archivo(self.ws, rel, texto), texto.count("\n") + 1)
        self.documentos = documentos
        self._firma = firma
        return self

    def rankear(self, pedido: str, maximo: int = 8) -> list[tuple[str, float, list]]:
        self.construir()
        tokens = tokens_pedido(pedido)
        if not tokens or not self.documentos:
            return []
        n = len(self.documentos)
        df = collections.Counter()
        for doc in self.documentos.values():
            presentes = set(doc.contenido) | doc.ruta_tokens | set(doc.simbolo_tokens)
            for t in tokens:
                if t in presentes:
                    df[t] += 1
        puntajes: dict[str, float] = {}
        coincidencias: dict[str, list] = {}
        menciona_tests = any(t.startswith("test") or t.startswith("prueb") for t in tokens)
        for rel, doc in self.documentos.items():
            puntaje = 0.0
            simbolos_hit: list = []
            for token, peso in tokens.items():
                idf = math.log(1 + n / (1 + df.get(token, 0)))
                if token == Path(rel).name.lower() or (("." in token) and rel.endswith(token)):
                    puntaje += 12 * peso
                    continue
                if token in doc.ruta_tokens or any(t.startswith(token) and len(token) >= 4 for t in doc.ruta_tokens):
                    puntaje += 4.0 * peso * idf
                if token in doc.simbolo_tokens:
                    puntaje += 2.5 * peso * idf
                    simbolos_hit.extend(doc.simbolo_tokens[token][:4])
                frecuencia = doc.contenido.get(token, 0)
                if frecuencia:
                    puntaje += min(3.0, 1 + math.log(frecuencia)) * 0.6 * peso * idf
            es_test = "test" in rel.lower()
            if es_test and not menciona_tests:
                puntaje *= 0.6
            if puntaje > 0:
                puntajes[rel] = puntaje
                coincidencias[rel] = simbolos_hit
        # Propagación por imports (un salto, en ambos sentidos).
        propagado = dict(puntajes)
        for rel, puntaje in puntajes.items():
            for vecino in self.documentos[rel].imports:
                if vecino in self.documentos:
                    propagado[vecino] = propagado.get(vecino, 0) + puntaje * 0.25
        for rel, doc in self.documentos.items():
            for importado in doc.imports:
                if importado in puntajes:
                    propagado[rel] = propagado.get(rel, 0) + puntajes[importado] * 0.15
        orden = sorted(propagado.items(), key=lambda kv: (-kv[1], kv[0]))[:maximo]
        if not orden:
            return []
        maximo_puntaje = orden[0][1] or 1
        return [(rel, round(p / maximo_puntaje, 3), coincidencias.get(rel, [])) for rel, p in orden
                if p / maximo_puntaje >= 0.08]

    def texto(self, pedido: str, maximo: int = 8) -> str:
        ranking = self.rankear(pedido, maximo)
        if not ranking:
            return ""
        lineas = ["ARCHIVOS PROBABLEMENTE RELEVANTES PARA EL PEDIDO (calculado por REAPER, verificalo leyendo):"]
        for k, (rel, puntaje, simbolos) in enumerate(ranking, start=1):
            doc = self.documentos.get(rel)
            vistos, detalle = set(), []
            for s in simbolos:
                if s.nombre_completo in vistos:
                    continue
                vistos.add(s.nombre_completo)
                detalle.append(f"{s.nombre_completo} L{s.inicio}-{s.fin}")
                if len(detalle) >= 5:
                    break
            if not detalle and doc:
                detalle = [f"{s.nombre_completo} L{s.inicio}" for s in doc.simbolos if s.tipo in ("clase", "funcion")][:4]
            lineas_txt = f" ({doc.lineas} líneas)" if doc else ""
            lineas.append(f"{k}. {rel}{lineas_txt}" + (f" — {', '.join(detalle)}" if detalle else ""))
        lineas.append("Tip: usá read_symbol para leer solo la función que necesitás.")
        return "\n".join(lineas)


_MAPAS: dict[str, MapaRepositorio] = {}
_LOCK_MAPAS = threading.Lock()


def mapa_de(ws: Workspace) -> MapaRepositorio:
    clave = str(ws.raiz)
    with _LOCK_MAPAS:
        if clave not in _MAPAS or _MAPAS[clave].ws is not ws:
            _MAPAS[clave] = MapaRepositorio(ws)
        return _MAPAS[clave]


def mapa_relevante(ws: Workspace, pedido: str, maximo: int = 8) -> str:
    try:
        return mapa_de(ws).texto(pedido, maximo)
    except (OSError, RecursionError, ValueError):
        return ""
