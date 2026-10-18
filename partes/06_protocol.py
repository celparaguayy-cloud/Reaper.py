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
# <parameter name="path">…</parameter> (estilo Cline) y <parameter=path>…</parameter> (Llama/Nemotron/Qwen-coder).
_RE_PARAMETER = re.compile(
    r"<\s*parameter\s*(?:\s+name\s*)?=\s*[\"']?([A-Za-z_][\w-]*)[\"']?\s*>(.*?)"
    r"(?:<\s*/\s*parameter\s*>|(?=<\s*parameter\b)|(?=<\s*/\s*(?:function|invoke|tool)\s*>)|\Z)",
    re.S | re.I,
)
_RE_HAY_PARAMETER = re.compile(r"<\s*parameter\s*(?:\s+name\s*)?=", re.I)
_RE_FIN_PARAMETER = re.compile(r"<\s*/\s*parameter\s*>\Z", re.I)


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

    # Estilo <parameter name="path">valor</parameter> o <parameter=path>valor</parameter>.
    if _RE_HAY_PARAMETER.search(cuerpo):
        largos = {n for n, l in definicion if l}
        for m in _RE_PARAMETER.finditer(cuerpo):
            nombre = _canonico_param(m.group(1))
            valor = m.group(2)
            params[nombre] = limpiar_largo(valor) if nombre in largos else sin_comillas(valor)
            if nombre in largos and m.end() == len(cuerpo) and not _RE_FIN_PARAMETER.search(m.group(0)):
                completa = False                            # el archivo se cortó adentro de <parameter=content>
                if abiertos is not None:
                    abiertos.add(nombre)
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


# Envoltorios de "tool calling" nativo que los modelos emiten cuando ignoran el formato XML de REAPER:
# <tool_call>{json}</tool_call> (Qwen/Hermes/Nemotron), <tool_use>…</tool_use>, <function_call>…</function_call>.
_RE_ENVOLTORIO_JSON = re.compile(
    r"<\s*(tool_call|tool_use|function_call|tool_calls)\s*>(.*?)(?:<\s*/\s*\1\s*>|(?=<\s*\1\s*>)|\Z)", re.S | re.I)
_RE_TOOL_CALLS_MISTRAL = re.compile(r"\[TOOL_CALLS\]\s*", re.I)
_RE_FENCE_JSON = re.compile(r"```(?:json|JSON)?[ \t]*\r?\n([\[{].*?[\]}])\s*\r?\n?```", re.S)


def _json_suelto(texto: str):
    """json.loads tolerante: strict=False acepta saltos de línea CRUDOS dentro de los strings (los modelos escriben
    así el código del archivo dentro de "content")."""
    try:
        return json.loads(texto, strict=False)
    except (json.JSONDecodeError, ValueError):
        return None


def _json_desde(texto: str, inicio: int):
    """El primer valor JSON que empieza en `inicio` (aunque después siga texto): (valor, fin) o (None, inicio)."""
    try:
        return json.JSONDecoder(strict=False).raw_decode(texto, inicio)
    except (json.JSONDecodeError, ValueError):
        return None, inicio


def _aplanar_json(valor) -> list[dict]:
    if isinstance(valor, dict):
        return [valor]
    if isinstance(valor, list):
        return [v for v in valor if isinstance(v, dict)]
    return []


def _objetos_json(texto: str) -> list[dict]:
    """Objetos JSON que pueden ser llamadas: dentro de envoltorios nativos, después de [TOOL_CALLS] (Mistral), en
    bloques ```json (objeto o lista) o el texto entero."""
    objetos: list = []
    for m in _RE_ENVOLTORIO_JSON.finditer(texto):
        interior = m.group(2).strip()
        if interior[:1] in ("[", "{"):
            valor = _json_suelto(interior)
            if valor is None:
                valor, _fin = _json_desde(interior, 0)
            objetos.extend(_aplanar_json(valor))
    for m in _RE_TOOL_CALLS_MISTRAL.finditer(texto):
        valor, _fin = _json_desde(texto, m.end())
        objetos.extend(_aplanar_json(valor))
    for interior in _RE_FENCE_JSON.findall(texto):
        objetos.extend(_aplanar_json(_json_suelto(interior)))
    limpio = texto.strip()
    if not objetos and ((limpio.startswith("{") and limpio.endswith("}"))
                        or (limpio.startswith("[") and limpio.endswith("]"))):
        objetos.extend(_aplanar_json(_json_suelto(limpio)))
    return objetos


_CLAVES_NOMBRE_JSON = ("tool", "name", "herramienta", "tool_name", "function_name")
_CLAVES_ARGS_JSON = ("args", "arguments", "parameters", "params", "input", "tool_input", "argumentos")


def _nombre_y_args_json(obj: dict) -> tuple:
    """(nombre, args) de una llamada JSON en los dialectos comunes (REAPER, Hermes, Mistral, OpenAI), o (None, None)."""
    fn = obj.get("function")
    if isinstance(fn, dict):                                # OpenAI: {"type": "function", "function": {...}}
        obj = fn
    nombre = next((obj[k] for k in _CLAVES_NOMBRE_JSON if isinstance(obj.get(k), str)), None)
    if nombre is None and isinstance(fn, str):
        nombre = fn
    if nombre is None:
        return None, None
    for clave in _CLAVES_ARGS_JSON:
        if clave in obj:                                   # "arguments": {} es válido (antes se perdía por falsy)
            return nombre, obj[clave]
    excluir = set(_CLAVES_NOMBRE_JSON) | {"type", "function", "id", "index"}
    return nombre, {k: v for k, v in obj.items() if k not in excluir}


def _params_json(args) -> dict:
    if isinstance(args, str):
        args = _json_suelto(args)
        if args is None:
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
_RE_FIN_FUNCION_LLAMA = re.compile(r"<\s*/\s*function\s*>\Z", re.I)
# "clave": "texto… — el último string puede no cerrar (respuesta cortada por longitud).
_RE_TEXTO_JSON_CORTADO = re.compile(r'"([A-Za-z_][\w-]*)"\s*:\s*"((?:[^"\\]|\\.)*)("?)', re.S)
_RE_INICIO_JSON_NATIVO = re.compile(r"<\s*(?:tool_call|tool_use|function_call)\s*>\s*(\{.*)\Z|\[TOOL_CALLS\]\s*\[?\s*(\{.*)\Z",
                                    re.S | re.I)


def _texto_json_parcial(crudo: str) -> str:
    for recorte in range(0, 6):                             # un \u00e cortado a la mitad no se puede decodificar
        try:
            return json.loads('"' + crudo[:len(crudo) - recorte] + '"', strict=False)
        except ValueError:
            continue
    return crudo


def _json_cortado(texto: str) -> tuple[Optional[str], dict, set]:
    """Una llamada JSON que se cortó por longitud ({"name": "write_to_file", "arguments": {"path": "a.py",
    "content": "import os\\n…): (nombre, campos de texto, claves que quedaron abiertas). Sin esto, el JSON inválido
    se perdía entero y el agente recibía "sin herramientas" en vez de poder continuar el archivo."""
    campos: dict = {}
    abiertos: set = set()
    for m in _RE_TEXTO_JSON_CORTADO.finditer(texto):
        clave = m.group(1)
        campos[clave] = _texto_json_parcial(m.group(2))
        if not m.group(3):
            abiertos.add(clave)
    nombre = next((campos.pop(k) for k in _CLAVES_NOMBRE_JSON if k in campos), None)
    campos.pop("type", None)
    return nombre, {_canonico_param(k): v for k, v in campos.items()}, {_canonico_param(k) for k in abiertos}


def _llamada_json_cortada(nombre: Optional[str], params: dict, abiertos: set, crudo: str,
                          esquemas: Esquemas, nombres: dict) -> Optional[Llamada]:
    if not nombre:
        return None
    real = nombres.get(nombre.lower(), ALIAS_HERRAMIENTAS.get(nombre.lower(), nombre.lower()))
    if real not in esquemas:
        return None
    largos = {p for p, largo in esquemas[real] if largo}
    params = {k: v for k, v in params.items() if k not in abiertos or k in largos}   # una ruta cortada no sirve
    # Sin strings abiertos el JSON es inválido por otra cosa (coma de más, cierre faltante): los valores están enteros.
    return Llamada(real, params, not abiertos, crudo, frozenset(abiertos & largos))


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
            # Sin </function> al final la respuesta pudo cortarse adentro del archivo: se marca incompleta para que
            # el agente guarde lo parcial y pida seguir, en vez de escribir medio archivo como si estuviera entero.
            cerrada = bool(_RE_FIN_FUNCION_LLAMA.search(m.group(0)))
            abiertos_llama: set = set()
            if cuerpo.startswith("{"):
                params, completa = _params_json(cuerpo), True
                if _json_suelto(cuerpo) is None and not cerrada:
                    cortada = _llamada_json_cortada(real, *_json_cortado(cuerpo)[1:], m.group(0), esquemas, nombres)
                    if cortada is not None:
                        llamadas.append(cortada)
                        continue
            else:
                params, completa = _extraer_params(cuerpo, esquemas.get(real, []), abiertos_llama)
            llamadas.append(Llamada(real, params, completa or cerrada, m.group(0), frozenset(abiertos_llama)))
        if llamadas:
            fuera = [_RE_FUNCION_LLAMA.sub("", limpio)]

    if not llamadas:
        # "Tool calling" nativo cuando el modelo ignora el XML: <tool_call>{json}</tool_call> (Qwen/Hermes/Nemotron),
        # [TOOL_CALLS][...] (Mistral), {"type": "function", "function": {...}} (OpenAI), ```json [...]```.
        for obj in _objetos_json(limpio):
            nombre, args = _nombre_y_args_json(obj)
            if not isinstance(nombre, str):
                continue
            if not isinstance(args, (dict, str)):
                args = {}
            real = nombres.get(nombre.lower(), ALIAS_HERRAMIENTAS.get(nombre.lower(), nombre.lower()))
            if real not in esquemas and not isinstance(obj.get("function"), dict) \
                    and not any(clave in obj for clave in _CLAVES_ARGS_JSON):
                continue                                    # {"name": "Juan", "edad": 3} son DATOS, no una llamada
            llamadas.append(Llamada(real, _params_json(args), True, json.dumps(obj, ensure_ascii=False)))
        if llamadas:
            # Lo que el modelo escribió ALREDEDOR de las llamadas sigue siendo texto visible.
            visible = _RE_FENCE_JSON.sub("", _RE_ENVOLTORIO_JSON.sub("", limpio))
            corte = _RE_TOOL_CALLS_MISTRAL.search(visible)
            visible = visible[:corte.start()] if corte else visible
            fuera = [] if visible.strip()[:1] in ("[", "{") else [visible]

    if not llamadas:
        # <tool_call>{"name": "write_to_file", "arguments": {..., "content": "… y la respuesta se cortó por longitud.
        inicio = _RE_INICIO_JSON_NATIVO.search(limpio)
        crudo = (inicio.group(1) or inicio.group(2)) if inicio else ""
        if crudo and _json_desde(crudo, 0)[0] is None:
            cortada = _llamada_json_cortada(*_json_cortado(crudo), crudo, esquemas, nombres)
            if cortada is not None:
                llamadas.append(cortada)
                fuera = [limpio[:inicio.start()]]

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
