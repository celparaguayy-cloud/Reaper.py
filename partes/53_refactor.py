"""
Refactor sin modelo: renombrar un símbolo en todo el proyecto.

Renombrar una función usada en 12 archivos es justo el tipo de cambio en el
que un modelo de 24B se olvida de alguno. REAPER lo hace de forma
determinista:
  - Python: con el tokenizador real (tokenize), solo cambia tokens NAME, nunca
    texto dentro de strings ni comentarios.
  - JS/TS y otros lenguajes con llaves: escáner que salta strings, template
    literals y comentarios, y cambia identificadores completos.
Después valida todos los archivos tocados; si alguno queda roto, no se aplica nada.
"""

import tokenize as _tokenize

_RE_IDENT_VALIDO = re.compile(r"^[A-Za-z_$][\w$]*$")
_IGNORAR_TOKEN = frozenset({
    _tokenize.NL, _tokenize.NEWLINE, _tokenize.COMMENT, _tokenize.INDENT, _tokenize.DEDENT, _tokenize.ENCODING,
})


def _modulos_importados(texto: str) -> set:
    """Nombres ligados por `import X` / `import X as Y` / `import a.b` (se liga `a`): un `a.viejo` es la función,
    no un atributo ajeno, así que sí hay que renombrarlo."""
    nombres: set = set()
    try:
        arbol = ast.parse(texto)
    except (SyntaxError, ValueError):
        return nombres
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                nombres.add((alias.asname or alias.name).split(".")[0])
    return nombres


def _es_metodo_de_clase(texto: str, viejo: str) -> bool:
    """¿`viejo` está definido como método (def directo en el cuerpo de una clase)? Entonces los accesos por
    atributo (`obj.viejo`) son sus llamadas y SÍ deben renombrarse; si no, son miembros ajenos del mismo nombre."""
    try:
        arbol = ast.parse(texto)
    except (SyntaxError, ValueError):
        return False
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef):
            for hijo in ast.iter_child_nodes(nodo):
                if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)) and hijo.name == viejo:
                    return True
    return False


def _renombrar_python(texto: str, viejo: str, nuevo: str, incluir_atributos: bool = True) -> tuple[str, int, int]:
    """
    Renombra tokens NAME == viejo (nunca strings ni comentarios). Cuando incluir_atributos es False, NO toca los
    accesos por atributo de instancia (`obj.viejo`, `self.viejo`) —que suelen ser miembros ajenos del mismo
    nombre— salvo que estén calificados por un módulo importado (`a.viejo`, que sí es la función). Devuelve
    (texto_nuevo, cambios, atributos_de_instancia_omitidos).
    """
    lineas = texto.splitlines(keepends=True)
    try:
        tokens = list(_tokenize.generate_tokens(io.StringIO(texto).readline))
    except (_tokenize.TokenError, IndentationError, SyntaxError):
        return texto, -1, 0
    modulos = set() if incluir_atributos else _modulos_importados(texto)
    cambios: list = []
    omitidos = 0
    prev1 = prev2 = None               # tokens significativos previos (prev1 = inmediatamente anterior)
    for t in tokens:
        if t.type in _IGNORAR_TOKEN:
            continue
        if t.type == _tokenize.NAME and t.string == viejo:
            es_atributo = prev1 is not None and prev1.type == _tokenize.OP and prev1.string == "."
            if es_atributo and not incluir_atributos:
                calificado_por_modulo = (prev2 is not None and prev2.type == _tokenize.NAME
                                         and prev2.string in modulos)
                if not calificado_por_modulo:
                    omitidos += 1
                    prev2, prev1 = prev1, t
                    continue
            cambios.append((t.start, t.end))
        prev2, prev1 = prev1, t
    if not cambios:
        return texto, 0, omitidos
    # Se aplica de atrás hacia adelante para no correr las posiciones.
    for (fila, col), (_fila_fin, col_fin) in reversed(cambios):
        linea = lineas[fila - 1]
        lineas[fila - 1] = linea[:col] + nuevo + linea[col_fin:]
    return "".join(lineas), len(cambios), omitidos


def _renombrar_generico(texto: str, viejo: str, nuevo: str, comentario: str = "//",
                        incluir_atributos: bool = True) -> tuple[str, int, int]:
    salida = []
    i, n, cambios, omitidos = 0, len(texto), 0, 0
    largo = len(viejo)
    while i < n:
        ch = texto[i]
        if texto.startswith(comentario, i):
            fin = texto.find("\n", i)
            fin = n if fin < 0 else fin
            salida.append(texto[i:fin])
            i = fin
            continue
        if comentario == "//" and texto.startswith("/*", i):
            fin = texto.find("*/", i + 2)
            fin = n if fin < 0 else fin + 2
            salida.append(texto[i:fin])
            i = fin
            continue
        if ch in "\"'`":
            j = i + 1
            while j < n and texto[j] != ch:
                if texto[j] == "\\":
                    j += 1
                elif texto[j] == "\n" and ch != "`":
                    break
                j += 1
            salida.append(texto[i:j + 1])
            i = j + 1
            continue
        if texto.startswith(viejo, i):
            antes = texto[i - 1] if i > 0 else ""
            despues = texto[i + largo] if i + largo < n else ""
            if not (antes.isalnum() or antes in "_$") and not (despues.isalnum() or despues in "_$"):
                if antes == "." and not incluir_atributos:
                    omitidos += 1
                    salida.append(viejo)
                    i += largo
                    continue
                salida.append(nuevo)
                i += largo
                cambios += 1
                continue
        salida.append(ch)
        i += 1
    return "".join(salida), cambios, omitidos


def renombrar_en_texto(rel: str, texto: str, viejo: str, nuevo: str,
                       incluir_atributos: bool = True) -> tuple[str, int, int]:
    sufijo = Path(rel).suffix.lower()
    if sufijo == ".py":
        nuevo_texto, cambios, omitidos = _renombrar_python(texto, viejo, nuevo, incluir_atributos)
        if cambios >= 0:
            return nuevo_texto, cambios, omitidos
        return _renombrar_generico(texto, viejo, nuevo, "#", incluir_atributos)
    if sufijo in (".sh", ".bash", ".rb"):
        return _renombrar_generico(texto, viejo, nuevo, "#", incluir_atributos)
    if sufijo in LENGUAJES_LLAVES or sufijo in (".html", ".htm", ".vue", ".svelte"):
        return _renombrar_generico(texto, viejo, nuevo, "//", incluir_atributos)
    return texto, 0, 0


@dataclass
class PlanRenombrado:
    viejo: str
    nuevo: str
    cambios: dict = field(default_factory=dict)  # rel → (antes, despues, cantidad)
    conflictos: list = field(default_factory=list)
    atributos_omitidos: int = 0                  # accesos `.viejo` de instancia que se dejaron sin tocar

    @property
    def total(self) -> int:
        return sum(c for _, _, c in self.cambios.values())

    def diff(self) -> str:
        return "\n".join(diff_unificado(a, d, rel) for rel, (a, d, _c) in self.cambios.items())

    def resumen(self) -> str:
        filas = [f"  {rel}: {c} cambio(s)" for rel, (_a, _d, c) in sorted(self.cambios.items())]
        return f"{self.viejo} → {self.nuevo}: {self.total} cambio(s) en {len(self.cambios)} archivo(s)\n" + "\n".join(filas)


def planificar_renombrado(ws: Workspace, viejo: str, nuevo: str, archivos: Optional[Iterable[str]] = None) -> PlanRenombrado:
    viejo, nuevo = viejo.strip(), nuevo.strip()
    if not _RE_IDENT_VALIDO.match(viejo) or not _RE_IDENT_VALIDO.match(nuevo):
        raise ValueError("los nombres deben ser identificadores válidos (letras, números y _)")
    if viejo == nuevo:
        raise ValueError("el nombre nuevo es igual al viejo")
    if keyword.iskeyword(nuevo):
        raise ValueError(f"'{nuevo}' es una palabra reservada de Python")
    plan = PlanRenombrado(viejo, nuevo)
    candidatos = list(archivos) if archivos else ws.archivos_codigo(limite=3000)
    # Primero leemos todo y decidimos si `viejo` es un MÉTODO en algún lado del proyecto: si lo es, los accesos
    # por atributo son sus llamadas y hay que renombrarlos; si no (función/clase/variable libre), un `obj.viejo`
    # es casi seguro un miembro ajeno del mismo nombre y NO debe tocarse (evita corromper código silenciosamente).
    textos: dict = {}
    for rel in candidatos:
        try:
            texto = ws.leer(rel)
        except (OSError, ValueError, ErrorRuta):
            continue
        if viejo not in texto:
            continue
        textos[rel] = texto
    incluir_atributos = any(
        rel.lower().endswith(".py") and _es_metodo_de_clase(texto, viejo) for rel, texto in textos.items()
    ) or not any(rel.lower().endswith(".py") for rel in textos)   # proyecto sin .py: no sé clasificar, comportamiento previo
    for rel, texto in textos.items():
        nuevo_texto, cantidad, omitidos = renombrar_en_texto(rel, texto, viejo, nuevo, incluir_atributos)
        plan.atributos_omitidos += omitidos
        if cantidad > 0:
            if re.search(r"(?<![\w$])" + re.escape(nuevo) + r"(?![\w$])", texto):
                plan.conflictos.append(f"{rel}: ya existe el nombre '{nuevo}'")
            plan.cambios[rel] = (texto, nuevo_texto, cantidad)
    return plan


def aplicar_renombrado(ws: Workspace, plan: PlanRenombrado) -> list[Resultado]:
    """Escribe todos los cambios; si la validación empeora, revierte todo y lanza ValueError."""
    previos = {rel: fallos(validar_archivo(ws, rel)) for rel in plan.cambios}
    for rel, (_antes, despues, _c) in plan.cambios.items():
        ws.escribir(rel, despues)
    resultados = validar_archivos(ws, list(plan.cambios))
    nuevos_fallos = [r for r in fallos(resultados) if not any(p.comando == r.comando for p in previos.get(r.archivo, []))]
    if nuevos_fallos:
        for rel, (antes, _d, _c) in plan.cambios.items():
            ws.escribir(rel, antes)
        raise ValueError("el renombrado rompía la validación; no apliqué nada:\n" + resumen_validacion(nuevos_fallos, 1500))
    indice_de(ws).invalidar()
    return resultados


@herramienta(
    "rename_symbol",
    "Renombra una función, clase, variable o método en TODO el proyecto (o en los archivos indicados) de forma "
    "segura: no toca strings ni comentarios y valida todo al final. Mucho más confiable que editar archivo por archivo.",
    [Param("old", "nombre actual"), Param("new", "nombre nuevo"),
     Param("paths", "archivos separados por coma (opcional: por defecto todo el proyecto)", requerido=False)],
    "<rename_symbol>\n<old>calcular_total</old>\n<new>total_con_iva</new>\n</rename_symbol>",
    escribe=True,
)
def rename_symbol(ctx: Contexto, p: dict) -> str:
    archivos = [a.strip() for a in re.split(r"[,\n]", p.get("paths") or "") if a.strip()] or None
    try:
        plan = planificar_renombrado(ctx.ws, p["old"], p["new"], archivos)
    except ValueError as e:
        raise ErrorHerramienta(str(e))
    if not plan.cambios:
        return f"No encontré usos de '{p['old']}' como identificador."
    protegidos = [rel for rel in plan.cambios if rel in ctx.protegidos]
    if protegidos:
        raise ErrorHerramienta(f"El renombrado tocaría tests de la especificación ({', '.join(protegidos)}): no permitido.")
    if ctx.settings.modo == "confirmar":
        ctx.ui.aviso(f"  {ctx.etiqueta} quiere renombrar {plan.resumen()}")
        ctx.ui.diff(plan.diff(), max_lineas=40)
        if not ctx.ui.confirmar("  ¿Aplicar?"):
            raise ErrorHerramienta("El usuario rechazó el renombrado.")
    try:
        resultados = aplicar_renombrado(ctx.ws, plan)
    except ValueError as e:
        raise ErrorHerramienta(str(e))
    ctx.cambios.update(plan.cambios)
    texto = plan.resumen()
    if plan.conflictos:
        texto += "\nOjo, el nombre nuevo ya existía en: " + "; ".join(plan.conflictos)
    if plan.atributos_omitidos:
        texto += (f"\nDejé sin tocar {plan.atributos_omitidos} acceso(s) por atributo `.{p['old']}` "
                  f"(parecen miembros ajenos del mismo nombre, no esta función/clase/variable). "
                  f"Si eran un método o atributo que también querías renombrar, revisalos a mano.")
    return texto + "\nValidación: " + resumen_validacion(resultados)


ALIAS_HERRAMIENTAS.update({"rename": "rename_symbol", "renombrar": "rename_symbol", "refactor_rename": "rename_symbol"})
ALIAS_PARAMS.update({"old": ("viejo", "old_name", "from_name", "actual"), "new": ("nuevo", "new_name", "to_name")})
