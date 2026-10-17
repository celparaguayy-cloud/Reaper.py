"""
Protocolo de herramientas en texto, estilo XML.

Por qué texto y no "function calling" nativo: Venice 24B (y muchos modelos
de OpenRouter) no soportan tools nativas de forma confiable. Las etiquetas
XML no necesitan escapar comillas ni saltos de línea, así que el modelo puede
escribir código crudo dentro de <content> sin romper nada.

El parser es tolerante con todo lo que un modelo chico suele mezclar:
  - alias de herramientas y de parámetros (cat → read_file, file → path)
  - <tool name="x">, <invoke name="x"> con <parameter name="p">valor</parameter>
  - atributos: <read_file path="a.py"/> o <write_to_file path="a.py">...
  - <function=read_file>{"path": "a.py"}</function> (estilo Llama)
  - un único parámetro sin etiqueta: <read_file>a.py</read_file>
  - bloques ``` o CDATA alrededor del código
  - como último recurso, un objeto JSON {"tool": ..., "args": {...}}
"""

# Nunca usar como alias nombres que coincidan con parámetros (task, path, diff...).
ALIAS_HERRAMIENTAS = {
    "read": "read_file",
    "cat": "read_file",
    "open_file": "read_file",
    "view_file": "read_file",
    "leer_archivo": "read_file",
    "ls": "list_files",
    "list_dir": "list_files",
    "list_directory": "list_files",
    "listar_archivos": "list_files",
    "grep": "search_files",
    "search": "search_files",
    "buscar": "search_files",
    "outline": "code_outline",
    "repo_map": "code_outline",
    "write_file": "write_to_file",
    "create_file": "write_to_file",
    "escribir_archivo": "write_to_file",
    "edit_file": "replace_in_file",
    "apply_diff": "replace_in_file",
    "editar_archivo": "replace_in_file",
    "run_command": "execute_command",
    "bash": "execute_command",
    "shell": "execute_command",
    "ejecutar_comando": "execute_command",
    "run_test": "run_tests",
    "todo_write": "update_todo",
    "spawn_agent": "delegate",
    "subagent": "delegate",
    "delegar": "delegate",
    "finish": "attempt_completion",
    "final_answer": "attempt_completion",
    "complete": "attempt_completion",
    "terminar": "attempt_completion",
    "ask_followup_question": "ask_user",
    "preguntar": "ask_user",
}

ALIAS_PARAMS = {
    "path": ("file", "filepath", "file_path", "filename", "ruta", "archivo"),
    "command": ("cmd", "comando"),
    "content": ("contenido", "code", "codigo", "código", "text"),
    "regex": ("pattern", "query", "patron"),
    "desde": ("start_line", "start", "linea_inicio"),
    "hasta": ("end_line", "end", "linea_fin"),
    "result": ("answer", "summary", "respuesta", "informe"),
    "role": ("rol", "agent", "agente"),
    "task": ("tarea", "prompt", "instrucciones"),
    "files": ("archivos",),
    "question": ("pregunta",),
    "diff": ("diffs", "changes", "cambios", "edits"),
    "items": ("todos", "lista"),
    "paths": ("rutas",),
    "stdin": ("input", "entrada", "user_input", "inputs", "entrada_estandar"),
}

_CORTE_RESULTADO = re.compile(
    r"<\s*(resultado|tool_result|observation|function_results?)\b", re.I
)
_FENCE = re.compile(r"\A\s*```[\w+#.-]*[ \t]*\r?\n(.*?)\r?\n?```\s*\Z", re.S)
_CDATA = re.compile(r"\A\s*<!\[CDATA\[(.*)\]\]>\s*\Z", re.S)
_RE_ATRIBUTO = re.compile(r"""([A-Za-z_][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>/]+))""")
_RE_PARAMETER = re.compile(
    r"<\s*parameter\s+name\s*=\s*[\"']?([A-Za-z_][\w-]*)[\"']?\s*>(.*?)(?:<\s*/\s*parameter\s*>|(?=<\s*parameter\b)|\Z)",
    re.S | re.I,
)


@dataclass
class Llamada:
    nombre: str
    params: dict = field(default_factory=dict)
    completa: bool = True
    crudo: str = ""
    sin_cierre: frozenset = frozenset()   # parámetros largos cuya etiqueta de cierre propia NO apareció


@dataclass
class Analisis:
    llamadas: list
    texto: str
    respuesta_limpia: str


# esquemas: {"write_to_file": [("path", False), ("content", True)], ...}
Esquemas = dict


def limpiar_largo(valor: str) -> str:
    v = valor
    if v.startswith("\r\n"):
        v = v[2:]
    elif v.startswith("\n"):
        v = v[1:]
    v = v.rstrip(" \t")
    if v.endswith("\r\n"):
        v = v[:-2]
    elif v.endswith("\n"):
        v = v[:-1]
    for patron in (_CDATA, _FENCE):
        m = patron.match(v)
        if m:
            v = m.group(1)
    return v


def sin_comillas(valor: str) -> str:
    """
    Quita comillas o backticks que ENVUELVEN el valor entero ("app.py", `ls -la`), nunca las de adentro:
    antes se usaba strip('"') y `python3 -c "print(2+2)"` perdía la comilla final (el comando fallaba).
    """
    v = (valor or "").strip()
    m = re.fullmatch(r"(`+)(.*?)\1", v, re.S)
    if m and "`" not in m.group(2):
        return m.group(2).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"" and v[0] not in v[1:-1]:
        return v[1:-1].strip()
    return v


def _apertura(tag: str) -> re.Pattern:
    return re.compile(r"<\s*" + re.escape(tag) + r"\s*>", re.I)


def _cierre(tag: str) -> re.Pattern:
    return re.compile(r"<\s*/\s*" + re.escape(tag) + r"\s*>", re.I)


def _canonico_param(nombre: str) -> str:
    nombre = nombre.lower()
    for real, alias in ALIAS_PARAMS.items():
        if nombre == real or nombre in alias:
            return real
    return nombre


def _atributos(texto: str) -> dict:
    salida = {}
    for m in _RE_ATRIBUTO.finditer(texto or ""):
        valor = next((g for g in m.groups()[1:] if g is not None), "")
        salida[m.group(1)] = valor
    return salida


def _extraer_params(cuerpo: str, definicion: list, abiertos: Optional[set] = None) -> tuple[dict, bool]:
    params: dict = {}
    completa = True
    enmascarado = cuerpo

    # Estilo <parameter name="path">valor</parameter>.
    if re.search(r"<\s*parameter\s+name\s*=", cuerpo, re.I):
        largos = {n for n, l in definicion if l}
        for m in _RE_PARAMETER.finditer(cuerpo):
            nombre = _canonico_param(m.group(1))
            valor = m.group(2)
            params[nombre] = limpiar_largo(valor) if nombre in largos else sin_comillas(valor)
        if params:
            return params, completa

    # Primero los parámetros largos (código), y se enmascaran para que un
    # "<path>" dentro del código no se confunda con el parámetro path.
    ordenados = sorted(definicion, key=lambda d: not d[1])
    for nombre, largo in ordenados:
        for tag in (nombre, *ALIAS_PARAMS.get(nombre, ())):
            ap = _apertura(tag).search(enmascarado)
            if not ap:
                continue
            if largo:
                cierres = list(_cierre(tag).finditer(enmascarado, ap.end()))
                if cierres:
                    fin_valor, fin_total = cierres[-1].start(), cierres[-1].end()
                else:
                    fin_valor = fin_total = len(enmascarado)
                    completa = False
                    if abiertos is not None:
                        abiertos.add(nombre)
                params[nombre] = limpiar_largo(cuerpo[ap.end():fin_valor])
                enmascarado = (
                    enmascarado[:ap.start()]
                    + " " * (fin_total - ap.start())
                    + enmascarado[fin_total:]
                )
            else:
                c = _cierre(tag).search(enmascarado, ap.end())
                if c:
                    valor = cuerpo[ap.end():c.start()]
                else:
                    valor = cuerpo[ap.end():].split("\n", 1)[0]
                params[nombre] = sin_comillas(valor)
            break

    if not params and definicion and cuerpo.strip():
        # Atajo: <read_file>app.py</read_file> o <attempt_completion>texto</attempt_completion>
        nombre, largo = definicion[0]
        if largo or not re.search(r"<\s*\w+\s*>", cuerpo):
            params[nombre] = limpiar_largo(cuerpo) if largo else cuerpo.strip()
        elif len([d for d in definicion if d[1]]) == 1 and len(definicion) >= 1:
            # Un único parámetro largo y el resto vino como atributos.
            largo_nombre = next(n for n, l in definicion if l)
            params[largo_nombre] = limpiar_largo(cuerpo)

    return params, completa


def _objetos_json(texto: str) -> list[dict]:
    candidatos = re.findall(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", texto, re.S)
    limpio = texto.strip()
    if limpio.startswith("{") and limpio.endswith("}"):
        candidatos.append(limpio)
    objetos = []
    for c in candidatos:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objetos.append(obj)
    return objetos


def _params_json(args) -> dict:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {}
    if not isinstance(args, dict):
        return {}
    salida = {}
    for k, v in args.items():
        if isinstance(v, str):
            salida[_canonico_param(k)] = v
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            salida[_canonico_param(k)] = "\n".join(v)       # {"items": ["[x] a", "[ ] b"]} → una por línea
        else:
            salida[_canonico_param(k)] = json.dumps(v, ensure_ascii=False)
    return salida


_RE_FUNCION_LLAMA = re.compile(r"<\s*function\s*=\s*([A-Za-z_][\w-]*)\s*>(.*?)(?:<\s*/\s*function\s*>|\Z)", re.S | re.I)


_TAGS_BUSCAR = ("search", "buscar", "find", "old", "old_str", "old_string", "original", "antes")
_TAGS_REEMPLAZO = ("replace", "reemplazar", "new", "new_str", "new_string", "replacement", "nuevo", "despues")
_RE_CODIGO_EN_HERRAMIENTA = re.compile(r"```[\w+#.-]*[ \t]*\r?\n(.*?)\r?\n?```", re.S)


def _bloques_de_tag(cuerpo: str, tags: tuple) -> list:
    alternativa = "|".join(re.escape(t) for t in tags)
    return [m.group(2) for m in re.finditer(rf"<\s*({alternativa})\s*>(.*?)<\s*/\s*\1\s*>", cuerpo, re.S | re.I)]


def _diff_alternativo(cuerpo: str) -> str:
    """replace_in_file escrito de otra forma por modelos reales: pares <search>/<replace> (u <old>/<new>…), o los
    bloques SEARCH/REPLACE sin la etiqueta <diff>. → diff en el formato de REAPER ('' si no hay nada usable)."""
    if "<<<<<<<" in cuerpo and ">>>>>>>" in cuerpo:
        inicio, fin = cuerpo.index("<<<<<<<"), cuerpo.rindex(">>>>>>>")
        fin = cuerpo.find("\n", fin)
        return cuerpo[inicio:fin if fin >= 0 else len(cuerpo)].strip("\n")
    buscados, reemplazos = _bloques_de_tag(cuerpo, _TAGS_BUSCAR), _bloques_de_tag(cuerpo, _TAGS_REEMPLAZO)
    if not buscados or len(buscados) != len(reemplazos):
        return ""
    return "\n".join(f"<<<<<<< SEARCH\n{limpiar_largo(b)}\n=======\n{limpiar_largo(r)}\n>>>>>>> REPLACE"
                     for b, r in zip(buscados, reemplazos))


def _contenido_en_bloque(cuerpo: str) -> Optional[str]:
    """write_to_file con el código en un bloque ``` y sin <content> (prueba real: 4 veces "faltan content")."""
    bloques = _RE_CODIGO_EN_HERRAMIENTA.findall(cuerpo)
    return max(bloques, key=len) if bloques else None


def analizar(texto: str, esquemas: Esquemas) -> Analisis:
    limpio = texto or ""
    corte = _CORTE_RESULTADO.search(limpio)
    if corte:
        # El modelo empezó a inventar el resultado de la herramienta: se descarta.
        limpio = limpio[:corte.start()].rstrip()

    nombres = {n.lower(): n for n in esquemas}
    for alias, real in ALIAS_HERRAMIENTAS.items():
        if real in esquemas:
            nombres.setdefault(alias, real)

    alternativas = "|".join(re.escape(n) for n in sorted(nombres, key=len, reverse=True))
    apertura = re.compile(
        r"<\s*(?:(?:tool|invoke)\s+name\s*=\s*[\"']?([A-Za-z_][\w-]*)[\"']?|(" + alternativas + r"))"
        r"(?=[\s/>])([^<>]*?)(/?)\s*>",
        re.I,
    )

    llamadas: list[Llamada] = []
    fuera: list[str] = []
    pos = 0
    while True:
        m = apertura.search(limpio, pos)
        if not m:
            fuera.append(limpio[pos:])
            break
        fuera.append(limpio[pos:m.start()])

        generico = m.group(1) is not None
        tag = m.group(1) or m.group(2)
        real = nombres.get(tag.lower(), ALIAS_HERRAMIENTAS.get(tag.lower(), tag.lower()))
        atributos = {} if generico else _atributos(m.group(3) or "")
        autocerrada = bool(m.group(4))
        etiqueta_cierre = ("invoke" if "invoke" in m.group(0).lower()[:10] else "tool") if generico else tag
        cierre = _cierre(etiqueta_cierre)

        c_encontrado = False
        if autocerrada:
            cuerpo = ""
            pos = m.end()
        else:
            c = cierre.search(limpio, m.end())
            c_encontrado = c is not None
            if c:
                cuerpo = limpio[m.end():c.start()]
                pos = c.end()
            else:
                siguiente = apertura.search(limpio, m.end())
                # Un <search> dentro de un replace_in_file sin cerrar es SU bloque a buscar, no la herramienta
                # search_files (prueba real: salía un search_files fantasma con ">>>>>> REPLACE </diff>" de regex).
                while real == "replace_in_file" and siguiente is not None and \
                        (siguiente.group(2) or "").lower() in _TAGS_BUSCAR:
                    siguiente = apertura.search(limpio, siguiente.end())
                fin = siguiente.start() if siguiente else len(limpio)
                cuerpo = limpio[m.end():fin]
                pos = fin

        definicion = esquemas.get(real, [])
        abiertos: set = set()
        params, completa = _extraer_params(cuerpo, definicion, abiertos) if cuerpo.strip() else ({}, True)
        if not completa and not autocerrada and c_encontrado:
            # Falta el cierre del parámetro (</content>) pero el de la herramienta está: el valor queda
            # delimitado por </herramienta>, así que la llamada se entiende entera.
            completa = True
        for clave, valor in atributos.items():
            canon = _canonico_param(clave)
            params.setdefault(canon, valor)
        if real == "replace_in_file" and not params.get("diff"):
            diff = _diff_alternativo(cuerpo)
            if diff:
                params["diff"] = diff
        if real == "write_to_file" and "content" not in params:
            suelto = _contenido_en_bloque(cuerpo)
            if suelto is not None:
                params["content"] = suelto
        if not params and cuerpo.strip() and definicion:
            completa = completa and True
        llamadas.append(Llamada(real, params, completa, limpio[m.start():pos], frozenset(abiertos)))

    if not llamadas:
        for m in _RE_FUNCION_LLAMA.finditer(limpio):
            nombre = m.group(1).lower()
            real = nombres.get(nombre, ALIAS_HERRAMIENTAS.get(nombre, nombre))
            cuerpo = m.group(2).strip()
            params = _params_json(cuerpo) if cuerpo.startswith("{") else _extraer_params(cuerpo, esquemas.get(real, []))[0]
            llamadas.append(Llamada(real, params, True, m.group(0)))
        if llamadas:
            fuera = [_RE_FUNCION_LLAMA.sub("", limpio)]

    if not llamadas:
        for obj in _objetos_json(limpio):
            nombre = obj.get("tool") or obj.get("name") or obj.get("herramienta")
            if not isinstance(nombre, str):
                continue
            args = obj.get("args") or obj.get("arguments") or obj.get("parameters") or obj.get("params")
            if args is None or (not isinstance(args, (dict, str))):
                args = {k: v for k, v in obj.items() if k not in ("tool", "name", "herramienta")}
            real = ALIAS_HERRAMIENTAS.get(nombre.lower(), nombre.lower())
            llamadas.append(Llamada(real, _params_json(args), True, json.dumps(obj, ensure_ascii=False)))
        if llamadas:
            fuera = []

    if not llamadas:
        # Modelos entrenados con "tool calling" nativo a veces mandan SOLO los argumentos en JSON, sin el nombre
        # (prueba real: nemotron mandó {"items": [...]} tres veces y REAPER lo trató como "sin herramientas").
        # Se infiere la herramienta solo si UNA ÚNICA tiene todas esas claves; ambiguos ({"path": ...}) no se
        # adivinan, y attempt_completion nunca se infiere (un "ya terminé" anticipado no cierra nada).
        for obj in _objetos_json(limpio):
            if obj.keys() & {"tool", "name", "herramienta"}:
                continue
            # Valores planos (texto, número, lista de textos). Con objetos anidados es casi siempre un RESULTADO
            # inventado (logs reales: {"items": [{"type": "file", "path": ...}]} = un listado alucinado), no un pedido.
            planos = all(isinstance(v, (str, int, float, bool)) or
                         (isinstance(v, list) and all(isinstance(x, str) for x in v)) for v in obj.values())
            claves = {_canonico_param(k) for k in obj}
            candidatas = [n for n, ps in esquemas.items() if planos and claves and claves <= {p for p, _ in ps}]
            if len(candidatas) == 1 and candidatas[0] != "attempt_completion":
                llamadas.append(Llamada(candidatas[0], _params_json(obj), True,
                                        json.dumps(obj, ensure_ascii=False)))
        if llamadas:
            fuera = []

    return Analisis(llamadas=llamadas, texto="".join(fuera).strip(), respuesta_limpia=limpio)


_RE_CIERRE_FINAL = re.compile(r"<\s*/\s*([A-Za-z_][\w-]*)\s*>?\s*\Z")


def cierre_espurio(valor: str, cercanos: Iterable[str], exactos: Iterable[str] = ()) -> Optional[str]:
    """
    Si un parámetro largo TERMINA en una etiqueta de cierre que se parece al nombre de la herramienta o de un
    parámetro (p. ej. `</replace_line>` en vez de `</replace_lines>`, `</contnet>`), esa etiqueta es un error
    de formato del modelo, no contenido: se devuelve para rechazar la llamada SIN escribir nada. Antes se
    escribía tal cual dentro del archivo (assets .css/.js rotos, sin validador que lo notara).
    Solo se aplica a parámetros cuya etiqueta de cierre propia NO apareció (Llamada.sin_cierre): un archivo
    bien delimitado que termina en </Context> o </path> no se toca.
    """
    m = _RE_CIERRE_FINAL.search(valor or "")
    if not m:
        return None
    etiqueta = m.group(1).lower()
    if etiqueta in {(n or "").lower() for n in exactos}:
        return m.group(0).strip()
    for nombre in cercanos:
        nombre = (nombre or "").lower()
        if nombre and (etiqueta == nombre or difflib.SequenceMatcher(None, etiqueta, nombre).ratio() >= 0.8):
            return m.group(0).strip()
    return None


def contenido_parcial(llamada: Llamada, esquemas: Esquemas) -> Optional[tuple[str, str]]:
    """
    Si la llamada quedó cortada dentro de un parámetro largo (típico cuando el
    modelo llega al límite de tokens escribiendo un archivo), devuelve
    (nombre_parametro, texto_parcial) para poder continuar desde ahí.
    """
    if llamada.completa:
        return None
    for nombre, largo in esquemas.get(llamada.nombre, []):
        if largo and nombre in llamada.params:
            return nombre, llamada.params[nombre]
    return None
