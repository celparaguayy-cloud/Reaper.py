"""
Herramientas nuevas de v7, pensadas para que un modelo de 24B no se rompa
con archivos grandes:

  read_symbol / replace_symbol / insert_after_symbol   trabajar por función o clase
  append_to_file                                       escribir archivos largos por partes
  insert_lines / replace_lines                         ediciones por número de línea (verificadas)
  find_references                                      dónde se usa un nombre
  delete_file / move_file / revert_file                manejo de archivos con checkpoint
  save_note / learn_lesson                             memoria persistente
  project_map                                          archivos relevantes para un tema
  run_python                                           probar un fragmento de Python
"""

ALIAS_HERRAMIENTAS.update({
    "read_function": "read_symbol", "show_symbol": "read_symbol", "get_symbol": "read_symbol",
    "leer_simbolo": "read_symbol", "leer_funcion": "read_symbol", "view_symbol": "read_symbol",
    "replace_function": "replace_symbol", "edit_symbol": "replace_symbol", "reemplazar_simbolo": "replace_symbol",
    "reemplazar_funcion": "replace_symbol", "rewrite_function": "replace_symbol",
    "add_after": "insert_after_symbol", "insert_function": "insert_after_symbol", "add_method": "insert_after_symbol",
    "append_file": "append_to_file", "append_content": "append_to_file", "agregar_al_final": "append_to_file",
    "continue_file": "append_to_file", "continuar_archivo": "append_to_file",
    "insert_code": "insert_lines", "insertar_lineas": "insert_lines", "insert_at_line": "insert_lines",
    "edit_lines": "replace_lines", "reemplazar_lineas": "replace_lines",
    "references": "find_references", "find_usages": "find_references", "usages": "find_references",
    "buscar_referencias": "find_references",
    "remove_file": "delete_file", "rm": "delete_file", "borrar_archivo": "delete_file",
    "rename_file": "move_file", "mv": "move_file", "mover_archivo": "move_file",
    "restore_file": "revert_file", "restaurar_archivo": "revert_file",
    "remember": "save_note", "note": "save_note", "guardar_nota": "save_note",
    "lesson": "learn_lesson", "aprender": "learn_lesson",
    "relevant_files": "project_map", "mapa": "project_map",
    "python": "run_python", "exec_python": "run_python", "ejecutar_python": "run_python",
})

ALIAS_PARAMS.update({
    "symbol": ("name", "nombre", "simbolo", "símbolo", "function", "funcion", "función", "class", "clase",
               "method", "metodo", "método", "symbol_name"),
    "line": ("linea", "línea", "after_line", "despues_de", "line_number", "after"),
    "new_path": ("to", "destino", "dest", "nuevo_path", "nueva_ruta", "destination"),
    "note": ("nota",),
    "lesson": ("leccion", "lección"),
    "scope": ("ambito", "ámbito", "alcance"),
    "last": ("final", "ultimo", "último", "done", "is_last"),
    "topic": ("tema", "pedido", "consulta", "about"),
})

ESCRITURA_V7 = ("replace_symbol", "insert_after_symbol", "append_to_file", "insert_lines", "replace_lines")
LECTURA_V7 = ("read_symbol", "find_references", "project_map")


def _ruta_existente(ctx: Contexto, rel: str, escribir: bool = False) -> tuple[Path, str]:
    try:
        ruta = ctx.ws.ruta(rel, escribir=escribir)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if ruta.is_dir():
        raise ErrorHerramienta(f"{rel} es una carpeta.")
    if not ruta.is_file():
        raise ErrorHerramienta(f"No existe {rel}.{_sugerir_ruta(ctx, rel)}")
    return ruta, ctx.ws.rel(ruta)


def _verificar_lectura_vigente(ctx: Contexto, rel: str) -> None:
    """Para ediciones por número de línea: el archivo no puede haber cambiado desde la última lectura."""
    leido = ctx.leidos.get(rel)
    if leido is None:
        raise ErrorHerramienta(
            f"Para editar {rel} por número de línea primero leelo con read_file (los números tienen que ser los actuales)."
        )
    if leido != ctx.ws.hash(rel):
        raise ErrorHerramienta(
            f"{rel} cambió desde tu última lectura y los números de línea ya no son válidos. Releelo con read_file."
        )


def _chequear_perezoso(ctx: Contexto, texto: str, antes: str = "") -> None:
    marcador = tiene_marcadores_perezosos(texto)
    if marcador and marcador not in antes:
        ctx.tropiezo("marcador_perezoso")
        raise ErrorHerramienta(f"El contenido tiene '{marcador}' (código omitido). Escribí el código real completo.")


def _simbolo_unico(ctx: Contexto, rel: Optional[str], nombre: str) -> Simbolo:
    indice = indice_de(ctx.ws)
    encontrados, sugerencias = indice.buscar(nombre, rel)
    if not encontrados:
        donde = f" en {rel}" if rel else " en el proyecto"
        extra = f" ¿Quisiste decir: {', '.join(sugerencias)}?" if sugerencias else ""
        if rel and not indice.de_archivo(rel):
            extra += f" (No detecté símbolos en {rel}: usá read_file.)"
        raise ErrorHerramienta(f"No encontré el símbolo '{nombre}'{donde}.{extra}")
    if len(encontrados) > 1:
        lista = "\n".join("  " + s.describir() for s in encontrados[:12])
        raise ErrorHerramienta(
            f"'{nombre}' es ambiguo ({len(encontrados)} coincidencias). Usá 'Clase.metodo' y/o indicá path:\n{lista}"
        )
    return encontrados[0]


# ==================================================================
# LECTURA POR SÍMBOLO
# ==================================================================
@herramienta(
    "read_symbol",
    "Lee SOLO una función, clase o método por nombre (con números de línea). Mucho más barato que read_file en "
    "archivos grandes. Formato del nombre: 'funcion', 'Clase' o 'Clase.metodo'. path es opcional.",
    [Param("symbol", "nombre: funcion | Clase | Clase.metodo"),
     Param("path", "archivo donde buscar (opcional: si falta busca en todo el proyecto)", requerido=False)],
    "<read_symbol>\n<path>app/carrito.py</path>\n<symbol>Carrito.total</symbol>\n</read_symbol>",
)
def read_symbol(ctx: Contexto, p: dict) -> str:
    rel = (p.get("path") or "").strip() or None
    if rel:
        _ruta, rel = _ruta_existente(ctx, rel)
    indice = indice_de(ctx.ws)
    encontrados, sugerencias = indice.buscar(p["symbol"], rel)
    if not encontrados:
        extra = f" ¿Quisiste decir: {', '.join(sugerencias)}?" if sugerencias else ""
        raise ErrorHerramienta(f"No encontré '{p['symbol']}'{' en ' + rel if rel else ''}.{extra}")
    partes = []
    for s in encontrados[:3]:
        try:
            texto = ctx.ws.leer(s.archivo)
        except (OSError, ValueError, ErrorRuta) as e:
            raise ErrorHerramienta(str(e))
        cuerpo = texto_de_simbolo(texto, s)
        if s.lineas > 300:
            lineas = cuerpo.splitlines()
            cuerpo = "\n".join(lineas[:300]) + (
                f"\n(símbolo de {s.lineas} líneas: mostrando las primeras 300; usá read_file con desde/hasta "
                "o pedí sus métodos uno por uno)")
        partes.append(f"{s.describir()}\n{cuerpo}")
        ctx.leidos[s.archivo] = ctx.ws.hash(s.archivo)
    if len(encontrados) > 3:
        partes.append("Otras coincidencias:\n" + "\n".join("  " + s.describir() for s in encontrados[3:12]))
    return "\n\n".join(partes)


@herramienta(
    "find_references",
    "Busca dónde se usa un nombre (función, clase, variable) en todo el proyecto, sin contar su definición.",
    [Param("symbol", "nombre a buscar")],
    "<find_references>\n<symbol>calcular_total</symbol>\n</find_references>",
)
def find_references(ctx: Contexto, p: dict) -> str:
    nombre = p["symbol"].strip()
    indice = indice_de(ctx.ws)
    definiciones, _ = indice.buscar(nombre)
    usos = indice.referencias(nombre)
    partes = []
    if definiciones:
        partes.append("Definido en:\n" + "\n".join("  " + s.describir() for s in definiciones[:8]))
    partes.append((f"Usos ({len(usos)}{'+' if len(usos) >= 60 else ''}):\n" + "\n".join("  " + u for u in usos))
                  if usos else "Sin usos fuera de su definición.")
    return "\n".join(partes)


@herramienta(
    "project_map",
    "Archivos y funciones del proyecto más relacionados con un tema (ranking por nombres, símbolos e imports).",
    [Param("topic", "de qué se trata lo que buscás (palabras clave)")],
    "<project_map>\n<topic>login de usuarios y contraseñas</topic>\n</project_map>",
)
def project_map(ctx: Contexto, p: dict) -> str:
    texto = mapa_relevante(ctx.ws, p["topic"], maximo=max(4, ctx.settings.max_relevantes))
    return texto or "No encontré archivos relacionados (¿proyecto vacío o palabras muy genéricas?). Probá con search_files."


# ==================================================================
# ESCRITURA POR SÍMBOLO
# ==================================================================
@herramienta(
    "replace_symbol",
    "Reemplaza una función, método o clase ENTERA por nombre. Escribí la definición completa nueva (con su "
    "línea def/function/class); REAPER la reindenta al nivel correcto. Más robusto que SEARCH/REPLACE.",
    [Param("path", "archivo"), Param("symbol", "funcion | Clase | Clase.metodo"),
     Param("content", "definición completa nueva", largo=True)],
    "<replace_symbol>\n<path>app/carrito.py</path>\n<symbol>Carrito.total</symbol>\n<content>\n"
    "def total(self):\n    return sum(i.precio * i.cantidad for i in self.items)\n</content>\n</replace_symbol>",
    escribe=True,
)
def replace_symbol(ctx: Contexto, p: dict) -> str:
    ruta, rel = _ruta_existente(ctx, p["path"], escribir=True)
    nuevo = p["content"]
    if not nuevo.strip():
        raise ErrorHerramienta("content vacío: para borrar una función usá replace_in_file.")
    antes = ruta.read_text(encoding="utf-8", errors="replace")
    _chequear_perezoso(ctx, nuevo, antes)
    simbolo = _simbolo_unico(ctx, rel, p["symbol"])
    if simbolo.nombre not in nuevo.split("\n", 3)[0] + "\n".join(nuevo.split("\n")[:4]):
        raise ErrorHerramienta(
            f"El content no empieza con la definición de '{simbolo.nombre}'. Escribí la definición completa "
            f"(p. ej. 'def {simbolo.nombre}(...)'). Para agregar algo nuevo usá insert_after_symbol."
        )
    despues = reemplazar_simbolo(antes, simbolo, nuevo)
    if despues == antes:
        return f"Sin cambios: {simbolo.nombre_completo} ya tenía exactamente ese contenido."
    if rel.endswith(".py"):
        try:
            compile(despues, rel, "exec", dont_inherit=True)
        except SyntaxError as e:
            raise ErrorHerramienta(
                f"El reemplazo deja {rel} con error de sintaxis: {e.msg} (línea {e.lineno}). No se aplicó. "
                "Revisá la indentación y que la definición esté completa."
            )
    _permiso_edicion(ctx, rel, diff_unificado(antes, despues, rel), False)
    _escribir(ctx, rel, despues)
    return _post_escritura(ctx, rel, antes, despues, [f"reemplacé {simbolo.nombre_completo} "
                                                      f"(líneas {simbolo.inicio}-{simbolo.fin})"])


@herramienta(
    "insert_after_symbol",
    "Inserta código nuevo (una función, método o clase) justo DESPUÉS de un símbolo existente. Si el símbolo es "
    "una clase, el código se agrega al FINAL de la clase como método.",
    [Param("path", "archivo"), Param("symbol", "símbolo de referencia (funcion | Clase | Clase.metodo)"),
     Param("content", "código nuevo completo", largo=True)],
    "<insert_after_symbol>\n<path>app/carrito.py</path>\n<symbol>Carrito</symbol>\n<content>\n"
    "def vaciar(self):\n    self.items.clear()\n</content>\n</insert_after_symbol>",
    escribe=True,
)
def insert_after_symbol(ctx: Contexto, p: dict) -> str:
    ruta, rel = _ruta_existente(ctx, p["path"], escribir=True)
    nuevo = p["content"]
    antes = ruta.read_text(encoding="utf-8", errors="replace")
    _chequear_perezoso(ctx, nuevo, antes)
    simbolo = _simbolo_unico(ctx, rel, p["symbol"])
    if simbolo.tipo == "clase":
        miembros = [s for s in indice_de(ctx.ws).de_archivo(rel)
                    if s.padre == simbolo.nombre_completo and s.inicio > simbolo.inicio and s.fin <= simbolo.fin]
        if miembros:
            ultimo = max(miembros, key=lambda s: s.fin)
            despues = insertar_tras_simbolo(antes, ultimo, nuevo, separacion=1)
        else:
            lineas = antes.splitlines()
            cuerpo = [l for l in lineas[simbolo.inicio: simbolo.fin] if l.strip()]
            indent_miembro = (cuerpo[0][: len(cuerpo[0]) - len(cuerpo[0].lstrip())] if cuerpo
                              else simbolo.indent + "    ")
            falso = Simbolo("_", "metodo", rel, simbolo.inicio, simbolo.fin if rel.endswith(".py") else simbolo.fin - 1,
                            "", simbolo.nombre, indent_miembro)
            despues = insertar_tras_simbolo(antes, falso, nuevo, separacion=1)
    else:
        despues = insertar_tras_simbolo(antes, simbolo, nuevo)
    if rel.endswith(".py"):
        try:
            compile(despues, rel, "exec", dont_inherit=True)
        except SyntaxError as e:
            raise ErrorHerramienta(f"La inserción deja {rel} con error de sintaxis: {e.msg} (línea {e.lineno}). "
                                   "No se aplicó.")
    _permiso_edicion(ctx, rel, diff_unificado(antes, despues, rel), False)
    _escribir(ctx, rel, despues)
    return _post_escritura(ctx, rel, antes, despues, [f"inserté código después de {simbolo.nombre_completo}"])


# ==================================================================
# ARCHIVOS LARGOS Y EDICIÓN POR LÍNEAS
# ==================================================================
@herramienta(
    "append_to_file",
    "Agrega contenido al FINAL de un archivo. Es la forma de escribir archivos largos por partes: primero "
    "write_to_file (con partial=true) y después varios append_to_file de ~150 líneas. Si repetís las últimas "
    "líneas, REAPER las detecta y no las duplica. En la última parte poné last=true.",
    [Param("path", "archivo"), Param("content", "contenido a agregar", largo=True),
     Param("last", "true si es la última parte del archivo", requerido=False)],
    "<append_to_file>\n<path>juego.py</path>\n<content>\n\ndef main():\n    Juego().correr()\n\n\n"
    "if __name__ == \"__main__\":\n    main()\n</content>\n<last>true</last>\n</append_to_file>",
    escribe=True,
)
def append_to_file(ctx: Contexto, p: dict) -> str:
    try:
        ruta = ctx.ws.ruta(p["path"], escribir=True)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    rel = ctx.ws.rel(ruta)
    nuevo = p["content"]
    if not nuevo.strip():
        raise ErrorHerramienta("content vacío.")
    antes = ruta.read_text(encoding="utf-8", errors="replace") if ruta.is_file() else ""
    _chequear_perezoso(ctx, nuevo, antes)
    despues, repetidas = unir_continuacion(antes, nuevo)
    if despues == antes:
        return f"Sin cambios en {rel}: ese contenido ya estaba al final del archivo."
    ultima = str(p.get("last", "")).strip().lower() in ("true", "si", "sí", "1", "yes")
    if ultima:
        ctx.parciales.pop(rel, None)
    elif rel in ctx.parciales:
        ctx.parciales[rel] = despues.count("\n")
    notas = [f"agregué {nuevo.count(chr(10)) + 1 - repetidas} líneas al final"]
    if repetidas:
        notas.append(f"omití {repetidas} líneas repetidas del final anterior")
    _permiso_edicion(ctx, rel, diff_unificado(antes, despues, rel), not ruta.is_file())
    _escribir(ctx, rel, despues)
    texto = _post_escritura(ctx, rel, antes if antes else None, despues, notas, accion="Extendí",
                            mostrar_diff=False)
    if rel in ctx.parciales:
        ultimas = "\n".join(f"{n:>5}| {l}" for n, l in
                            enumerate(despues.splitlines()[-6:], start=max(1, despues.count("\n") - 5)))
        texto += f"\nÚltimas líneas actuales (seguí desde acá):\n{ultimas}"
    return texto


@herramienta(
    "insert_lines",
    "Inserta líneas nuevas DESPUÉS de la línea N (0 = al principio). Requiere haber leído el archivo actual con "
    "read_file (los números deben ser los vigentes).",
    [Param("path", "archivo"), Param("line", "insertar después de esta línea (0 = inicio)"),
     Param("content", "líneas a insertar", largo=True)],
    "<insert_lines>\n<path>config.py</path>\n<line>3</line>\n<content>\nDEBUG = False\n</content>\n</insert_lines>",
    escribe=True,
)
def insert_lines(ctx: Contexto, p: dict) -> str:
    ruta, rel = _ruta_existente(ctx, p["path"], escribir=True)
    _verificar_lectura_vigente(ctx, rel)
    linea = _entero(p.get("line"), None)
    if linea is None:
        raise ErrorHerramienta("line debe ser un número (0 = al principio del archivo).")
    antes = ruta.read_text(encoding="utf-8", errors="replace")
    _chequear_perezoso(ctx, p["content"], antes)
    try:
        despues = insertar_despues(antes, linea, p["content"])
    except ErrorEdicion as e:
        raise ErrorHerramienta(str(e))
    _permiso_edicion(ctx, rel, diff_unificado(antes, despues, rel), False)
    _escribir(ctx, rel, despues)
    ctx.leidos[rel] = ctx.ws.hash(rel)
    return _post_escritura(ctx, rel, antes, despues, [f"inserté después de la línea {linea}"])


@herramienta(
    "replace_lines",
    "Reemplaza el rango de líneas desde..hasta (inclusive) por contenido nuevo. Requiere haber leído el archivo "
    "actual con read_file. Útil cuando SEARCH/REPLACE no coincide.",
    [Param("path", "archivo"), Param("desde", "primera línea a reemplazar"), Param("hasta", "última línea a reemplazar"),
     Param("content", "contenido nuevo para ese rango", largo=True)],
    "<replace_lines>\n<path>app.py</path>\n<desde>10</desde>\n<hasta>12</hasta>\n<content>\n"
    "    total = calcular(items)\n    return total\n</content>\n</replace_lines>",
    escribe=True,
)
def replace_lines(ctx: Contexto, p: dict) -> str:
    ruta, rel = _ruta_existente(ctx, p["path"], escribir=True)
    _verificar_lectura_vigente(ctx, rel)
    desde, hasta = _entero(p.get("desde"), None), _entero(p.get("hasta"), None)
    if desde is None or hasta is None:
        raise ErrorHerramienta("desde y hasta deben ser números de línea.")
    antes = ruta.read_text(encoding="utf-8", errors="replace")
    _chequear_perezoso(ctx, p["content"], antes)
    if hasta - desde > 200:
        raise ErrorHerramienta("Rango demasiado grande (más de 200 líneas): usá write_to_file o replace_symbol.")
    try:
        despues = reemplazar_lineas(antes, desde, hasta, p["content"])
    except ErrorEdicion as e:
        raise ErrorHerramienta(str(e))
    if despues == antes:
        return f"Sin cambios en {rel}."
    _permiso_edicion(ctx, rel, diff_unificado(antes, despues, rel), False)
    _escribir(ctx, rel, despues)
    ctx.leidos[rel] = ctx.ws.hash(rel)
    return _post_escritura(ctx, rel, antes, despues, [f"reemplacé las líneas {desde}-{hasta}"])


# ==================================================================
# MANEJO DE ARCHIVOS
# ==================================================================
@herramienta(
    "delete_file",
    "Borra un archivo del proyecto (queda guardado en el checkpoint: se recupera con /deshacer).",
    [Param("path", "archivo a borrar")],
    "<delete_file>\n<path>viejo/no_se_usa.py</path>\n</delete_file>",
    escribe=True,
)
def delete_file(ctx: Contexto, p: dict) -> str:
    ruta, rel = _ruta_existente(ctx, p["path"], escribir=True)
    if rel in ctx.protegidos:
        raise ErrorHerramienta(f"{rel} es parte de la especificación y no se puede borrar.")
    if ctx.settings.modo == "confirmar":
        ctx.ui.aviso(f"  {ctx.etiqueta} quiere BORRAR {rel}")
        if not ctx.ui.confirmar("  ¿Borrar?"):
            raise ErrorHerramienta("El usuario no aprobó borrar el archivo.")
    try:
        ctx.ws.borrar(rel)
    except (ErrorRuta, OSError) as e:
        raise ErrorHerramienta(f"No pude borrar {rel}: {e}")
    ctx.cambios.add(rel)
    indice_de(ctx.ws).invalidar(rel)
    referencias = indice_de(ctx.ws).referencias(Path(rel).stem, limite=8)
    texto = f"Borré {rel} (recuperable con /deshacer)."
    if referencias:
        texto += "\nOjo, el nombre todavía aparece en:\n" + "\n".join("  " + r for r in referencias)
    return texto


@herramienta(
    "move_file",
    "Mueve o renombra un archivo (con checkpoint). No actualiza imports: revisalos con find_references.",
    [Param("path", "archivo actual"), Param("new_path", "ruta nueva")],
    "<move_file>\n<path>utils.py</path>\n<new_path>app/utils.py</new_path>\n</move_file>",
    escribe=True,
)
def move_file(ctx: Contexto, p: dict) -> str:
    _ruta, rel = _ruta_existente(ctx, p["path"], escribir=True)
    destino = (p.get("new_path") or "").strip()
    if not destino:
        raise ErrorHerramienta("Falta new_path.")
    if rel in ctx.protegidos:
        raise ErrorHerramienta(f"{rel} es parte de la especificación y no se puede mover.")
    try:
        nueva = ctx.ws.mover(rel, destino)
    except (ErrorRuta, OSError) as e:
        raise ErrorHerramienta(f"No pude mover {rel}: {e}")
    nuevo_rel = ctx.ws.rel(nueva)
    ctx.cambios.update({rel, nuevo_rel})
    indice_de(ctx.ws).invalidar()
    referencias = indice_de(ctx.ws).referencias(Path(rel).stem, limite=10)
    texto = f"Moví {rel} → {nuevo_rel}."
    if referencias:
        texto += "\nActualizá estas referencias al nombre viejo:\n" + "\n".join("  " + r for r in referencias)
    return texto


@herramienta(
    "revert_file",
    "Devuelve un archivo al estado que tenía al empezar esta tarea (si lo rompiste y querés volver a empezar).",
    [Param("path", "archivo")],
    "<revert_file>\n<path>app.py</path>\n</revert_file>",
    escribe=True,
)
def revert_file(ctx: Contexto, p: dict) -> str:
    try:
        ruta = ctx.ws.ruta(p["path"], escribir=True)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    rel = ctx.ws.rel(ruta)
    cid = ctx.cid_inicio if ctx.cid_inicio is not None else ctx.ws.checkpoints.actual
    if cid is None:
        raise ErrorHerramienta("No hay checkpoint de esta tarea para restaurar.")
    tipo, _copia = ctx.ws.checkpoints._origen(rel, cid)
    if tipo == "sin_cambios":
        return f"{rel} no cambió en esta tarea: no hay nada que revertir."
    original = ctx.ws.checkpoints.original(rel, cid)
    if original is None:
        if ruta.is_file():
            ctx.ws.borrar(rel)
        ctx.cambios.discard(rel)
        ctx.parciales.pop(rel, None)
        return f"{rel} no existía al empezar la tarea: lo borré."
    actual = ruta.read_text(encoding="utf-8", errors="replace") if ruta.is_file() else ""
    if actual == original:
        return f"{rel} ya está como al empezar la tarea."
    _escribir(ctx, rel, original)
    ctx.parciales.pop(rel, None)
    return f"Restauré {rel} al estado del inicio de la tarea ({original.count(chr(10))} líneas). Releelo antes de editarlo."


# ==================================================================
# MEMORIA
# ==================================================================
@herramienta(
    "save_note",
    "Guarda una nota corta y duradera sobre el proyecto en .reaper/notas.md (la ven los próximos agentes). "
    "Ej.: decisiones de diseño, comandos útiles, dónde está cada cosa.",
    [Param("note", "nota de una o dos líneas")],
    "<save_note>\n<note>Los precios se guardan en centavos (int) en data/productos.json</note>\n</save_note>",
)
def save_note(ctx: Contexto, p: dict) -> str:
    nota = " ".join((p.get("note") or "").split())
    if len(nota) < 8:
        raise ErrorHerramienta("La nota es demasiado corta.")
    ruta = ctx.ws.carpeta_reaper() / "notas.md"
    try:
        previo = ruta.read_text(encoding="utf-8") if ruta.is_file() else "# Notas de los agentes de REAPER\n\n"
        if nota in previo:
            return "Esa nota ya estaba guardada."
        escritura_atomica(ruta, previo.rstrip("\n") + f"\n- {nota}  <!-- {datetime.now():%Y-%m-%d} -->\n")
    except OSError as e:
        raise ErrorHerramienta(f"No pude guardar la nota: {e}")
    return "Nota guardada en .reaper/notas.md."


@herramienta(
    "learn_lesson",
    "Registra una lección aprendida de un error real (una línea concreta). scope: proyecto (hecho de este "
    "proyecto) o general (error típico tuyo que vale para cualquier proyecto).",
    [Param("lesson", "lección de una línea, con nombres concretos"),
     Param("scope", "proyecto | general", requerido=False)],
    "<learn_lesson>\n<lesson>Los tests de este proyecto se corren con python3 -m unittest discover -s tests</lesson>\n"
    "<scope>proyecto</scope>\n</learn_lesson>",
)
def learn_lesson(ctx: Contexto, p: dict) -> str:
    if ctx.memoria is None or not ctx.settings.lecciones:
        return "Las lecciones están desactivadas en esta sesión."
    leccion = p.get("lesson") or ""
    general = (p.get("scope") or "").strip().lower().startswith("gen")
    hechos = ctx.memoria.registrar([] if general else [leccion], [leccion] if general else [])
    if not hechos:
        return "No guardé la lección: tiene que ser concreta (archivos, comandos o funciones reales), no un consejo genérico."
    return "Lección registrada: " + hechos[0]


# ==================================================================
# PYTHON RÁPIDO
# ==================================================================
@herramienta(
    "run_python",
    "Ejecuta un fragmento corto de Python en la raíz del proyecto (para probar una función o inspeccionar datos). "
    "Usa print() para ver resultados. Si el código usa input(), pasá las respuestas en <stdin>. Timeout 60 s.",
    [Param("content", "código Python", largo=True),
     Param("stdin", "entrada estándar para input() (opcional, una respuesta por línea)", requerido=False, largo=True)],
    "<run_python>\n<content>\nfrom app.carrito import Carrito\nc = Carrito()\nprint(c.total())\n</content>\n</run_python>",
)
def run_python(ctx: Contexto, p: dict) -> str:
    codigo = p.get("content") or ""
    if not codigo.strip():
        raise ErrorHerramienta("Falta el código.")
    entrada = _entrada_estandar(p)
    if re.search(r"\binput\s*\(", codigo) and entrada is None:
        raise ErrorHerramienta(
            "El fragmento usa input() y no pasaste entrada. Pasá las respuestas en <stdin> (una por línea) o los "
            "valores directamente en el código. No cambies el programa para quitarle el input()."
        )
    for patron in _BLOQUEADOS:
        if patron.search(codigo):
            raise ErrorHerramienta(f"El código contiene algo bloqueado por seguridad ({patron.pattern}).")
    if re.search(r"\b(shutil\.rmtree|os\.remove|os\.unlink|os\.rmdir|subprocess|os\.system)\b", codigo) \
            and ctx.settings.modo != "auto":
        ctx.ui.aviso(f"  {ctx.etiqueta} quiere ejecutar Python que borra archivos o lanza procesos:")
        ctx.ui.codigo(recortar(codigo, 1200), "python")
        if not ctx.ui.confirmar("  ¿Ejecutar?"):
            raise ErrorHerramienta("El usuario no aprobó ejecutar ese código.")
    if entrada is None:
        # Por stdin ("python -"): así el directorio del proyecto queda en sys.path y los imports locales andan.
        r = ejecutar([sys.executable, "-"], cwd=ctx.ws.raiz, timeout=60, entrada=codigo)
    else:
        # Con entrada para input(): el código va por -c (sys.path[0] sigue siendo el proyecto) y stdin queda libre.
        r = ejecutar([sys.executable, "-c", codigo], cwd=ctx.ws.raiz, timeout=60, entrada=entrada)
    r.comando = "run_python"
    texto = r.resumen(limite=MAX_SALIDA // 2).replace('File "<stdin>"', 'File "<fragmento>"').replace(
        'File "<string>"', 'File "<fragmento>"')
    if not r.ok and parece_interactivo(f"{r.stdout}\n{r.stderr}"):
        texto += "\n\n" + PISTA_INTERACTIVO
    elif not r.ok and ctx.settings.pistas_errores:
        texto = anexar_pistas(texto, 2)
    return texto


# ==================================================================
# inspect_tests — REAPER analiza sus propios tests (Fase 1 / v9)
# ==================================================================
def _archivos_de_test(ctx: Contexto, limite: int = 400) -> list[str]:
    salida = []
    for ruta in ctx.ws.iterar(limite=limite * 3):
        rel = ctx.ws.rel(ruta)
        if rel.endswith(".py") and es_archivo_de_test(rel):
            salida.append(rel)
    return salida[:limite]


@herramienta(
    "inspect_tests",
    "Analiza los tests (estático) buscando lo que los vuelve engañosos: tautologías (assertTrue(True)), "
    "mocks que reemplazan el sistema bajo prueba, valor esperado fabricado por el propio mock, tests sin "
    "assert y clasificación unit/integration mal etiquetada. Sin path, inspecciona todos los tests del proyecto. "
    "Con mutacion=true y un archivo de código en 'target', mide discriminación mutando el código y re-ejecutando.",
    [Param("path", "archivo de tests a analizar (opcional; por defecto todos)", requerido=False),
     Param("mutacion", "true para medir discriminación por mutación (ejecuta los tests)", requerido=False),
     Param("target", "archivo de código a mutar (con mutacion=true)", requerido=False)],
    "<inspect_tests>\n<path>tests/test_app.py</path>\n</inspect_tests>",
)
def inspect_tests(ctx: Contexto, p: dict) -> str:
    objetivo = (p.get("path") or "").strip()
    if objetivo:
        archivos = [ctx.ws.rel(ctx.ws.ruta(objetivo))]
    else:
        archivos = _archivos_de_test(ctx)
    if not archivos:
        return ("No encontré archivos de tests Python para analizar. (El análisis estático es para Python; "
                "para JS/Go usá run_tests.)")
    bloques, total_problemas, discriminaciones = [], 0, []
    for rel in archivos:
        try:
            fuente = ctx.ws.leer(rel)
        except (OSError, ValueError, ErrorRuta):
            continue
        res = analizar_tests_python(fuente)
        discriminaciones.append(res.discriminacion)
        if res.problemas:
            total_problemas += len(res.problemas)
            problemas = sorted(res.problemas, key=lambda x: {"alta": 0, "media": 1}.get(x.severidad, 2))
            detalle = "\n".join(f"  [{x.severidad}] {x.tipo} · {x.test} (L{x.linea}): {x.detalle}"
                                for x in problemas[:10])
            niveles = ", ".join(sorted({t.nivel_real for t in res.tests}))
            bloques.append(f"### {rel}  (discriminación {res.discriminacion}; niveles: {niveles or '—'})\n{detalle}")
        else:
            bloques.append(f"### {rel}  ✓ sin problemas detectados (discriminación {res.discriminacion})")

    cabecera = (f"INSPECCIÓN DE TESTS: {len(archivos)} archivo(s), {total_problemas} problema(s). "
                f"Discriminación media: {round(sum(discriminaciones) / len(discriminaciones), 2) if discriminaciones else 1.0}.\n"
                "(Un test que no discrimina NO demuestra que el código sea correcto, aunque esté verde.)\n")
    texto = cabecera + "\n".join(bloques)

    if ctx.pedido:
        inventados = []
        for rel in archivos:
            try:
                fuente = ctx.ws.leer(rel)
            except (OSError, ValueError, ErrorRuta):
                continue
            for req in requisito_inventado(fuente, ctx.pedido):
                inventados.append(f"  {rel}: {req.test} (L{req.linea}) [{req.tipo}]: {req.detalle}")
        if inventados:
            texto += ("\n\nREQUISITOS INVENTADOS (el test exige algo que el pedido no pide; ajustá el TEST a la "
                      "spec, no el código al test):\n" + "\n".join(inventados[:8]))

    if str(p.get("mutacion", "")).strip().lower() in ("true", "1", "sí", "si"):
        target = (p.get("target") or "").strip()
        if not target:
            texto += "\n\n(mutacion=true necesita 'target': el archivo de código a mutar.)"
        else:
            try:
                rel_target = ctx.ws.rel(ctx.ws.ruta(target))
            except (ErrorRuta, ValueError):
                return texto + f"\n\nNo existe el target {target}."
            def correr() -> bool:
                r = ejecutar_tests(ctx.ws, timeout=ctx.settings.tests_timeout, completo=True)
                return bool(r and r.ok)
            res_mut = probar_discriminacion(ctx.ws, rel_target, correr)
            if res_mut.error:
                texto += f"\n\nMUTACIÓN ({rel_target}): {res_mut.error}"
            else:
                texto += (f"\n\nMUTACIÓN ({rel_target}): {res_mut.detectadas}/{res_mut.total} mutaciones detectadas "
                          f"(puntaje {res_mut.puntaje}).")
                if res_mut.sobrevivientes:
                    texto += "\nMutaciones NO detectadas (los tests pasan igual → faltan casos):\n" + "\n".join(
                        f"  - {s}" for s in res_mut.sobrevivientes[:8])
    return texto
