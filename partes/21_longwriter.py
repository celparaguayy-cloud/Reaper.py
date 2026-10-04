"""
Escritor de archivos largos: esqueleto + relleno por función.

Un modelo de 24B con 32k de contexto y ~6k tokens de salida no puede escribir
un archivo de 1500 líneas de una vez: se corta, se olvida de lo que escribió
arriba o pone "...". REAPER lo divide así:

  1. ESQUELETO: el modelo escribe el plano completo del archivo (imports,
     constantes, clases, firmas y docstrings) con un marcador en cada cuerpo:
         raise NotImplementedError("REAPER")      (Python)
         throw new Error("REAPER");               (JS/TS)
     El esqueleto es corto, compila, y fija la arquitectura.
  2. RELLENO: por cada función marcada, una llamada chica con solo lo que hace
     falta (el contorno del archivo, la firma, el docstring y la especificación)
     devuelve la función completa. REAPER la aplica con replace_symbol, valida
     que compile y, si falla, reintenta con el error real.
  3. VERIFICACIÓN: no puede quedar ningún marcador; validadores + tests.

Las funciones se generan en paralelo (son independientes dado el esqueleto)
y se aplican en secuencia.
"""

MARCADOR_PY = 'raise NotImplementedError("REAPER")'
MARCADOR_JS = 'throw new Error("REAPER");'
_RE_MARCADOR = re.compile(r"""NotImplementedError\(\s*["']REAPER["']\s*\)|new Error\(\s*["']REAPER["']\s*\)""")
_RE_BLOQUE = re.compile(r"```[ \t]*([\w+#.-]*)[ \t]*\r?\n(.*?)\r?\n?```", re.S)

LENGUAJES_ESCRITOR = {".py": "python", ".js": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
                      ".jsx": "js"}

PROMPT_ESQUELETO = """Vas a diseñar el ESQUELETO del archivo `{rel}` ({lenguaje}). Es el plano completo del archivo final:
TODOS los imports, constantes, clases, y las firmas de TODAS las funciones y métodos que el archivo va a
necesitar, cada una con un docstring/comentario que diga qué recibe, qué devuelve y los casos borde.
NO implementes los cuerpos: cada función o método tiene SOLO su docstring y esta línea:
    {marcador}
Excepciones: constantes, dataclasses/estructuras de datos simples y el bloque `if __name__ == "__main__":`
(o el arranque del programa) se escriben completos.
El esqueleto TIENE que ser código válido que compile.

ESPECIFICACIÓN DEL ARCHIVO:
{especificacion}
{contexto}
Respondé SOLO con un bloque de código ```{bloque}``` con el esqueleto completo."""

PROMPT_RELLENO = """Estás implementando el archivo `{rel}` función por función. Este es su contorno actual (las
funciones con {marcador_corto} todavía no están implementadas; otras ya pueden estarlo):
```
{contorno}
```
{vecinos}
ESPECIFICACIÓN GENERAL DEL ARCHIVO:
{especificacion}

IMPLEMENTÁ AHORA {cuales}:
{actuales}

Reglas: misma firma y mismo nombre; cuerpo REAL y completo (nada de '...', TODO ni {marcador_corto});
usá solo nombres que existan en el archivo o en la librería estándar (o en los imports del esqueleto);
manejá los casos borde del docstring.
Respondé SOLO con {formato}."""


class ErrorEscritor(RuntimeError):
    pass


@dataclass
class InformeEscritor:
    ok: bool
    rel: str
    lineas: int = 0
    funciones: int = 0
    rellenadas: int = 0
    fallidas: list = field(default_factory=list)
    notas: list = field(default_factory=list)

    def texto(self) -> str:
        estado = "COMPLETO" if self.ok else "INCOMPLETO"
        partes = [f"Archivo largo {self.rel}: {estado} ({self.lineas} líneas, {self.rellenadas}/{self.funciones} "
                  "funciones implementadas)."]
        if self.fallidas:
            partes.append("Sin implementar (seguí con replace_symbol): " + ", ".join(self.fallidas[:20]))
        partes.extend(self.notas)
        return "\n".join(partes)


def extraer_bloques_codigo(texto: str) -> list[tuple[str, str]]:
    bloques = [(m.group(1).lower(), m.group(2)) for m in _RE_BLOQUE.finditer(texto or "")]
    if bloques:
        return bloques
    limpio = (texto or "").strip()
    if re.match(r"^(@|def |async def |class |function |export |const |let |var |import |from )", limpio):
        return [("", limpio)]
    abierto = re.search(r"```[ \t]*[\w+#.-]*[ \t]*\r?\n(.*)$", texto or "", re.S)
    if abierto:  # bloque sin cerrar (respuesta cortada): se usa igual y la validación decide
        return [("", abierto.group(1))]
    return []


def simbolos_pendientes(texto: str, rel: str) -> list[Simbolo]:
    """Funciones/métodos cuyo cuerpo todavía tiene el marcador del esqueleto (los más internos)."""
    simbolos = extraer_simbolos(Path(rel), texto, rel)
    lineas = texto.splitlines()
    pendientes = []
    for s in simbolos:
        if s.tipo not in ("funcion", "metodo"):
            continue
        cuerpo = "\n".join(lineas[s.inicio - 1: s.fin])
        if not _RE_MARCADOR.search(cuerpo):
            continue
        # Si una función interna tiene el marcador, la externa no se rellena como un todo.
        internas = [o for o in simbolos if o is not s and o.inicio > s.inicio and o.fin <= s.fin
                    and o.tipo in ("funcion", "metodo")
                    and _RE_MARCADOR.search("\n".join(lineas[o.inicio - 1: o.fin]))]
        if internas:
            continue
        pendientes.append(s)
    return pendientes


def contorno_archivo(texto: str, rel: str, maximo: int = 9000) -> str:
    """Contorno legible: imports, constantes y firmas con docstring corto (sin cuerpos)."""
    simbolos = extraer_simbolos(Path(rel), texto, rel)
    lineas = texto.splitlines()
    if len(texto) <= maximo // 2:
        return texto
    incluidas: set[int] = set()
    for i, l in enumerate(lineas, start=1):
        if i <= 40 and (l.startswith(("import ", "from ", "const ", "let ", "export ", "#!")) or l.isupper()):
            incluidas.add(i)
        if re.match(r"^[A-Z_][A-Z0-9_]*\s*[:=]", l):
            incluidas.add(i)
    for s in simbolos:
        incluidas.add(s.inicio)
        # Firma de varias líneas + primera línea del docstring.
        for k in range(s.inicio, min(s.fin, s.inicio + 4) + 1):
            linea = lineas[k - 1] if k - 1 < len(lineas) else ""
            incluidas.add(k)
            if linea.rstrip().endswith((":", "{")):
                if k < len(lineas) and re.match(r'^\s*("""|\'\'\'|/\*\*|//)', lineas[k]):
                    incluidas.add(k + 1)
                break
    salida, previo = [], 0
    for i in sorted(incluidas):
        if i - previo > 1:
            salida.append("    ...")
        salida.append(lineas[i - 1])
        previo = i
    return recortar("\n".join(salida), maximo)


def _vecinos_llamados(texto: str, rel: str, simbolo: Simbolo, limite: int = 2500) -> str:
    """Código de funciones ya implementadas que el docstring del símbolo menciona (para coherencia)."""
    lineas = texto.splitlines()
    cuerpo = "\n".join(lineas[simbolo.inicio - 1: simbolo.fin])
    salida, usado = [], 0
    for otro in extraer_simbolos(Path(rel), texto, rel):
        if otro.nombre == simbolo.nombre or otro.tipo not in ("funcion", "metodo"):
            continue
        if not re.search(r"\b" + re.escape(otro.nombre) + r"\b", cuerpo):
            continue
        codigo = "\n".join(lineas[otro.inicio - 1: otro.fin])
        if _RE_MARCADOR.search(codigo) or usado + len(codigo) > limite:
            continue
        salida.append(codigo)
        usado += len(codigo)
    if not salida:
        return ""
    return "Funciones ya implementadas que usa:\n```\n" + "\n\n".join(salida) + "\n```\n"


def _definicion_de(bloque: str, nombre: str, lenguaje: str) -> Optional[str]:
    """Del bloque devuelto por el modelo, la definición completa de 'nombre' (o el bloque entero)."""
    if lenguaje == "python":
        try:
            arbol = ast.parse(textwrap.dedent(bloque))
        except SyntaxError:
            return bloque if re.search(r"\bdef\s+" + re.escape(nombre) + r"\b", bloque) else None
        lineas = textwrap.dedent(bloque).splitlines()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
                inicio = min([d.lineno for d in nodo.decorator_list] + [nodo.lineno])
                return "\n".join(lineas[inicio - 1: nodo.end_lineno])
        return None
    simbolos = simbolos_llaves(bloque, "bloque.js", "js")
    for s in simbolos:
        if s.nombre == nombre:
            return "\n".join(bloque.splitlines()[s.inicio - 1: s.fin])
    if re.search(r"\b" + re.escape(nombre) + r"\s*\(", bloque):
        return bloque
    return None


class EscritorLargo:
    def __init__(self, llm, ws: Workspace, settings: Settings, ui: UI, *, modelo: Optional[str] = None,
                 etiqueta: str = "escritor"):
        self.llm = llm
        self.ws = ws
        self.settings = settings
        self.ui = ui
        self.modelo = modelo or settings.modelo_para("implementador")
        self.etiqueta = etiqueta
        self._lock = threading.Lock()

    # ------------------------------------------------------------ fases
    def escribir(self, rel: str, especificacion: str, contexto: str = "",
                 escribir_archivo: Optional[Callable[[str, str], None]] = None) -> InformeEscritor:
        sufijo = Path(rel).suffix.lower()
        lenguaje = LENGUAJES_ESCRITOR.get(sufijo)
        if not lenguaje:
            raise ErrorEscritor(f"El escritor largo soporta Python y JS/TS; para {sufijo or 'este archivo'} "
                                "escribí por partes con write_to_file + append_to_file.")
        escribir_archivo = escribir_archivo or self.ws.escribir
        informe = InformeEscritor(False, rel)
        existente = self.ws.leer(rel) if self.ws.existe(rel) else ""
        if existente and simbolos_pendientes(existente, rel):
            self.ui.tenue(f"  [{self.etiqueta}] {rel} ya tiene un esqueleto con funciones pendientes: sigo desde ahí")
            texto = existente
        else:
            texto = self._esqueleto(rel, lenguaje, especificacion, contexto)
            escribir_archivo(rel, texto)
            self.ui.ok(f"[{self.etiqueta}] esqueleto de {rel}: {texto.count(chr(10)) + 1} líneas")
        pendientes = simbolos_pendientes(texto, rel)
        informe.funciones = len(pendientes)
        self.ui.tenue(f"  [{self.etiqueta}] {len(pendientes)} funciones por implementar")
        texto = self._rellenar(rel, lenguaje, especificacion, texto, informe, escribir_archivo)
        restantes = simbolos_pendientes(texto, rel)
        informe.fallidas = [s.nombre_completo for s in restantes]
        informe.lineas = texto.count("\n") + 1
        informe.rellenadas = informe.funciones - len(restantes)
        validacion = validar_archivo(self.ws, rel)
        malos = fallos(validacion)
        if malos:
            informe.notas.append("Validación final con errores:\n" + resumen_validacion(validacion, 1500))
        informe.ok = not restantes and not malos
        return informe

    def _esqueleto(self, rel: str, lenguaje: str, especificacion: str, contexto: str) -> str:
        marcador = MARCADOR_PY if lenguaje == "python" else MARCADOR_JS
        prompt = PROMPT_ESQUELETO.format(
            rel=rel, lenguaje="Python" if lenguaje == "python" else "JavaScript/TypeScript",
            marcador=marcador, especificacion=recortar(especificacion, 6000),
            contexto=("\nCONTEXTO DEL PROYECTO:\n" + recortar(contexto, 4000) + "\n") if contexto else "",
            bloque="python" if lenguaje == "python" else "javascript",
        )
        mensajes = [{"role": "system", "content": "Sos un arquitecto de software. Escribís código válido y completo."},
                    {"role": "user", "content": prompt}]
        ultimo_error = ""
        for intento in range(3):
            self.ui.esperando(self.etiqueta, "diseñando el esqueleto")
            try:
                respuesta = self.llm.chat(mensajes, modelo=self.modelo, temperatura=0.2,
                                          max_tokens=self.settings.max_tokens, rol="escritor")
            finally:
                self.ui.fin_progreso()
            bloques = extraer_bloques_codigo(respuesta.texto)
            if not bloques:
                ultimo_error = "No devolviste un bloque de código."
            else:
                codigo = max(bloques, key=lambda b: len(b[1]))[1].rstrip() + "\n"
                problema = self._problema_sintaxis(codigo, lenguaje, rel)
                if not problema and not _RE_MARCADOR.search(codigo):
                    problema = f"El esqueleto no tiene ningún marcador {marcador}: ¿implementaste todo? Dejá los cuerpos con el marcador."
                    if codigo.count("\n") < 120:
                        return codigo  # archivo chico: si ya vino completo, sirve
                if not problema:
                    return codigo
                ultimo_error = problema
                if respuesta.finish_reason == "length":
                    ultimo_error += " (Tu respuesta se cortó: hacé el esqueleto más compacto, docstrings de una línea.)"
            mensajes.append({"role": "assistant", "content": respuesta.texto})
            mensajes.append({"role": "user", "content": f"El esqueleto tiene un problema:\n{ultimo_error}\n"
                                                         "Devolvé el esqueleto COMPLETO corregido en un solo bloque."})
        raise ErrorEscritor(f"No logré un esqueleto válido para {rel}: {ultimo_error}")

    def _problema_sintaxis(self, codigo: str, lenguaje: str, rel: str) -> str:
        if lenguaje == "python":
            try:
                compile(codigo, rel, "exec", dont_inherit=True)
                return ""
            except SyntaxError as e:
                return f"SyntaxError: {e.msg} (línea {e.lineno})"
        problema = balance_llaves(codigo, "js")
        if problema:
            return problema
        if shutil.which("node") and Path(rel).suffix in (".js", ".mjs", ".cjs"):
            r = _node_check_texto(self.ws, codigo, ".mjs" if re.search(r"^\s*(import|export)\b", codigo, re.M) else ".js")
            if not r.ok:
                return (r.stderr or r.stdout).strip()[-600:]
        return ""

    def _pedir_relleno(self, rel: str, lenguaje: str, especificacion: str, texto: str,
                       grupo: list[Simbolo], error: str = "") -> dict[str, str]:
        lineas = texto.splitlines()
        actuales = "\n\n".join("```\n" + "\n".join(lineas[s.inicio - 1: s.fin]) + "\n```" for s in grupo)
        nombres = [s.nombre for s in grupo]
        cuales = (f"la función `{nombres[0]}`" if len(grupo) == 1
                  else "estas funciones: " + ", ".join(f"`{n}`" for n in nombres))
        formato = ("un bloque de código con la definición COMPLETA de la función" if len(grupo) == 1 else
                   "un bloque de código por función, cada uno con la definición COMPLETA, en el mismo orden")
        if grupo[0].padre and lenguaje == "python":
            formato += f" (es un método de {grupo[0].padre}: incluí self y escribila sin indentar)"
        prompt = PROMPT_RELLENO.format(
            rel=rel, marcador_corto="REAPER", contorno=contorno_archivo(texto, rel),
            vecinos=_vecinos_llamados(texto, rel, grupo[0]), especificacion=recortar(especificacion, 3000),
            cuales=cuales, actuales=actuales, formato=formato,
        )
        if error:
            prompt += f"\n\nTU INTENTO ANTERIOR FALLÓ:\n{recortar(error, 1500)}\nCorregilo."
        mensajes = [{"role": "system", "content": "Sos un programador senior. Devolvés código real, completo y correcto."},
                    {"role": "user", "content": prompt}]
        respuesta = self.llm.chat(mensajes, modelo=self.modelo, temperatura=0.15,
                                  max_tokens=self.settings.max_tokens, rol="escritor")
        bloques = extraer_bloques_codigo(respuesta.texto)
        salida: dict[str, str] = {}
        for s in grupo:
            for _lang, bloque in bloques:
                definicion = _definicion_de(bloque, s.nombre, lenguaje)
                if definicion:
                    salida[s.nombre_completo] = definicion
                    break
        return salida

    def _aplicar(self, rel: str, lenguaje: str, texto: str, simbolo_nombre: str, definicion: str) -> tuple[str, str]:
        """Aplica una definición sobre el texto actual. Devuelve (texto_nuevo, error)."""
        encontrados, _ = elegir_simbolo(extraer_simbolos(Path(rel), texto, rel), simbolo_nombre)
        if len(encontrados) != 1:
            return texto, f"no ubiqué '{simbolo_nombre}' en el archivo actual"
        if _RE_MARCADOR.search(definicion) or tiene_marcadores_perezosos(definicion):
            return texto, "la implementación todavía tiene el marcador REAPER o '...'"
        nuevo = reemplazar_simbolo(texto, encontrados[0], definicion)
        problema = self._problema_sintaxis(nuevo, lenguaje, rel)
        if problema:
            return texto, problema
        if lenguaje == "python":
            indefinidos = [n for n, _ in nombres_indefinidos_python(nuevo)
                           if n not in {x for x, _ in nombres_indefinidos_python(texto)}]
            if indefinidos:
                return texto, "usa nombres que no existen: " + ", ".join(sorted(set(indefinidos))[:6])
        return nuevo, ""

    def _rellenar(self, rel: str, lenguaje: str, especificacion: str, texto: str, informe: InformeEscritor,
                  escribir_archivo: Callable[[str, str], None]) -> str:
        pendientes = simbolos_pendientes(texto, rel)
        if not pendientes:
            return texto
        # Grupos chicos: hasta 3 funciones cortas seguidas del mismo padre por llamada.
        grupos: list[list[Simbolo]] = []
        for s in pendientes:
            if grupos and len(grupos[-1]) < 3 and grupos[-1][-1].padre == s.padre and s.lineas <= 12 \
                    and grupos[-1][-1].lineas <= 12:
                grupos[-1].append(s)
            else:
                grupos.append([s])
        total = len(pendientes)
        hechos = 0
        paralelo = max(1, min(self.settings.paralelo, 4))
        errores: dict[str, str] = {}

        def generar(grupo: list[Simbolo], texto_base: str) -> tuple[list[Simbolo], dict[str, str]]:
            if CANCELAR.is_set():
                raise Cancelado()
            try:
                return grupo, self._pedir_relleno(rel, lenguaje, especificacion, texto_base, grupo,
                                                  "\n".join(errores.get(s.nombre_completo, "") for s in grupo).strip())
            except LLMError as e:
                if e.presupuesto:
                    raise
                return grupo, {}

        for ronda in range(3):
            if not grupos:
                break
            fallidos: list[Simbolo] = []
            base = texto
            with ThreadPoolExecutor(max_workers=paralelo) as ejecutor:
                futuros = [ejecutor.submit(generar, g, base) for g in grupos]
                for futuro in as_completed(futuros):
                    grupo, definiciones = futuro.result()
                    with self._lock:
                        for s in grupo:
                            definicion = definiciones.get(s.nombre_completo)
                            if not definicion:
                                errores[s.nombre_completo] = "No devolviste la definición completa de esta función."
                                fallidos.append(s)
                                continue
                            nuevo, error = self._aplicar(rel, lenguaje, texto, s.nombre_completo, definicion)
                            if error:
                                errores[s.nombre_completo] = error
                                fallidos.append(s)
                                continue
                            texto = nuevo
                            hechos += 1
                            escribir_archivo(rel, texto)
                            self.ui.linea(f"      {Tema.ok}✓{C.RESET} {Tema.tenue}{s.nombre_completo} "
                                          f"({hechos}/{total}){C.RESET}")
            if not fallidos:
                break
            self.ui.tenue(f"  [{self.etiqueta}] ronda {ronda + 2}: reintento {len(fallidos)} función(es) con el error real")
            grupos = [[s] for s in fallidos]
        return texto


@herramienta(
    "write_large_file",
    "Escribe un archivo LARGO (Python o JS/TS, cientos o miles de líneas) sin cortarse: REAPER genera primero "
    "un esqueleto con todas las firmas y después implementa cada función por separado, validando cada una. "
    "Usalo para archivos nuevos de más de ~250 líneas. Describí en spec TODO lo que el archivo debe hacer.",
    [Param("path", "archivo a crear"), Param("spec", "especificación completa: responsabilidades, clases, "
                                                     "funciones, datos, casos borde", largo=True)],
    "<write_large_file>\n<path>juego/motor.py</path>\n<spec>\nMotor de un juego de serpiente en terminal: clase "
    "Tablero (ancho, alto, celdas), clase Serpiente (mover, crecer, choca), clase Juego (tick, puntaje, "
    "guardar_record en records.json)...\n</spec>\n</write_large_file>",
    escribe=True,
)
def write_large_file(ctx: Contexto, p: dict) -> str:
    if ctx.llm is None:
        raise ErrorHerramienta("El escritor largo no está disponible en este contexto.")
    try:
        ruta = ctx.ws.ruta(p["path"], escribir=True)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    rel = ctx.ws.rel(ruta)
    if rel in ctx.protegidos:
        raise ErrorHerramienta(f"{rel} es parte de la especificación y no se puede modificar.")
    if ctx.permitidos and not any(fnmatch.fnmatch(rel, patron) for patron in ctx.permitidos):
        raise ErrorHerramienta(f"En este rol no podés escribir {rel}.")
    especificacion = p.get("spec") or ""
    if len(especificacion.strip()) < 30:
        raise ErrorHerramienta("La spec es demasiado corta: describí clases, funciones y comportamiento esperado.")
    antes = ruta.read_text(encoding="utf-8", errors="replace") if ruta.is_file() else None
    if antes and not simbolos_pendientes(antes, rel) and antes.count("\n") > 30:
        raise ErrorHerramienta(f"{rel} ya existe con contenido: para cambiarlo usá replace_symbol / replace_in_file.")
    if ctx.settings.modo == "confirmar" and not ctx.ui.confirmar(f"  ¿{ctx.etiqueta} puede generar {rel} (archivo largo)?"):
        raise ErrorHerramienta("El usuario no aprobó generar el archivo.")
    escritor = EscritorLargo(ctx.llm, ctx.ws, ctx.settings, ctx.ui, etiqueta=f"{ctx.etiqueta}/escritor")

    def escribir(rel_: str, contenido: str) -> None:
        ctx.ws.escribir(rel_, contenido)
        indice_de(ctx.ws).invalidar(rel_)

    try:
        informe = escritor.escribir(rel, especificacion, contexto=ctx.ws.memoria(1500), escribir_archivo=escribir)
    except ErrorEscritor as e:
        raise ErrorHerramienta(str(e))
    ctx.cambios.add(rel)
    texto = informe.texto()
    resultados = validar_archivo(ctx.ws, rel)
    if fallos(resultados):
        texto += "\nVALIDACIÓN FALLÓ (corregilo antes de seguir):\n" + resumen_validacion(resultados)
    else:
        texto += "\nValidación: " + resumen_validacion(resultados)
    return texto
