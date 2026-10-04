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


def _renombrar_python(texto: str, viejo: str, nuevo: str) -> tuple[str, int]:
    lineas = texto.splitlines(keepends=True)
    try:
        tokens = list(_tokenize.generate_tokens(io.StringIO(texto).readline))
    except (_tokenize.TokenError, IndentationError, SyntaxError):
        return texto, -1
    cambios = [(t.start, t.end) for t in tokens if t.type == _tokenize.NAME and t.string == viejo]
    if not cambios:
        return texto, 0
    # Se aplica de atrás hacia adelante para no correr las posiciones.
    for (fila, col), (_fila_fin, col_fin) in reversed(cambios):
        linea = lineas[fila - 1]
        lineas[fila - 1] = linea[:col] + nuevo + linea[col_fin:]
    return "".join(lineas), len(cambios)


def _renombrar_generico(texto: str, viejo: str, nuevo: str, comentario: str = "//") -> tuple[str, int]:
    salida = []
    i, n, cambios = 0, len(texto), 0
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
                salida.append(nuevo)
                i += largo
                cambios += 1
                continue
        salida.append(ch)
        i += 1
    return "".join(salida), cambios


def renombrar_en_texto(rel: str, texto: str, viejo: str, nuevo: str) -> tuple[str, int]:
    sufijo = Path(rel).suffix.lower()
    if sufijo == ".py":
        nuevo_texto, cambios = _renombrar_python(texto, viejo, nuevo)
        if cambios >= 0:
            return nuevo_texto, cambios
        return _renombrar_generico(texto, viejo, nuevo, "#")
    if sufijo in (".sh", ".bash", ".rb"):
        return _renombrar_generico(texto, viejo, nuevo, "#")
    if sufijo in LENGUAJES_LLAVES or sufijo in (".html", ".htm", ".vue", ".svelte"):
        return _renombrar_generico(texto, viejo, nuevo, "//")
    return texto, 0


@dataclass
class PlanRenombrado:
    viejo: str
    nuevo: str
    cambios: dict = field(default_factory=dict)  # rel → (antes, despues, cantidad)
    conflictos: list = field(default_factory=list)

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
    for rel in candidatos:
        try:
            texto = ws.leer(rel)
        except (OSError, ValueError, ErrorRuta):
            continue
        if viejo not in texto:
            continue
        nuevo_texto, cantidad = renombrar_en_texto(rel, texto, viejo, nuevo)
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
    return texto + "\nValidación: " + resumen_validacion(resultados)


ALIAS_HERRAMIENTAS.update({"rename": "rename_symbol", "renombrar": "rename_symbol", "refactor_rename": "rename_symbol"})
ALIAS_PARAMS.update({"old": ("viejo", "old_name", "from_name", "actual"), "new": ("nuevo", "new_name", "to_name")})
