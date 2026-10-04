"""
Motor de ediciones SEARCH/REPLACE tolerante.

Para un modelo de 24B, reescribir archivos completos es la principal fuente
de destrozos (se cortan, ponen "...resto igual", pierden funciones). Los
bloques SEARCH/REPLACE solo tocan lo necesario y, si el texto no coincide,
REAPER devuelve las líneas más parecidas para que el modelo corrija.

Estrategia de coincidencia (en orden):
1. texto exacto (debe ser único)
2. línea por línea ignorando espacios al final
3. línea por línea ignorando la indentación (y reindenta el reemplazo)
4. si el REPLACE ya está en el archivo, se considera ya aplicado
"""



_INICIO = re.compile(r"^\s*<{5,}\s*(SEARCH|BUSCAR|ORIGINAL)\s*$", re.I)
_SEPARADOR = re.compile(r"^\s*={5,}\s*$")
_FIN = re.compile(r"^\s*>{5,}\s*(REPLACE|REEMPLAZAR|UPDATED)?\s*$", re.I)
_NUMERO_LINEA = re.compile(r"^\s*\d+\s?[|│]\s?")

_MARCADORES_PEREZOSOS = re.compile(
    r"^\s*(#|//|/\*|<!--|--|;)?\s*(\.\.\.|…)\s*"
    r"(resto|el resto|existing|rest of|previous|unchanged|same|sin cambios|"
    r"c[oó]digo (anterior|existente|original)|igual|as before|remaining)"
    r"|^\s*(#|//|/\*|<!--)\s*(\.\.\.\s*)?(el )?(resto del (c[oó]digo|archivo)|rest of (the )?(code|file))",
    re.I | re.M,
)


class ErrorEdicion(ValueError):
    pass


@dataclass
class Bloque:
    buscar: str
    reemplazar: str


def tiene_marcadores_perezosos(texto: str) -> Optional[str]:
    m = _MARCADORES_PEREZOSOS.search(texto or "")
    return m.group(0).strip() if m else None


def parsear_bloques(diff: str) -> list[Bloque]:
    bloques: list[Bloque] = []
    estado = None
    buscar: list[str] = []
    reemplazar: list[str] = []

    for linea in (diff or "").splitlines(keepends=True):
        sin_fin = linea.rstrip("\r\n")
        if estado is None:
            if _INICIO.match(sin_fin):
                estado, buscar, reemplazar = "buscar", [], []
            continue
        if estado == "buscar":
            if _SEPARADOR.match(sin_fin):
                estado = "reemplazar"
            elif _INICIO.match(sin_fin):
                raise ErrorEdicion("Bloque mal formado: '<<<<<<< SEARCH' dos veces sin '======='.")
            else:
                buscar.append(linea)
            continue
        if estado == "reemplazar":
            if _FIN.match(sin_fin):
                bloques.append(Bloque("".join(buscar), "".join(reemplazar)))
                estado = None
            elif _INICIO.match(sin_fin):
                # Faltó el cierre ">>>>>>> REPLACE": se acepta y empieza otro bloque.
                bloques.append(Bloque("".join(buscar), "".join(reemplazar)))
                estado, buscar, reemplazar = "buscar", [], []
            else:
                reemplazar.append(linea)

    if estado == "reemplazar":
        bloques.append(Bloque("".join(buscar), "".join(reemplazar)))
    elif estado == "buscar":
        raise ErrorEdicion("Bloque incompleto: falta '=======' y la parte REPLACE.")

    if not bloques:
        raise ErrorEdicion(
            "No encontré bloques SEARCH/REPLACE. Formato obligatorio:\n"
            "<<<<<<< SEARCH\n(texto exacto actual)\n=======\n(texto nuevo)\n>>>>>>> REPLACE"
        )
    return [_quitar_numeros_de_linea(b) for b in bloques]


def _quitar_numeros_de_linea(bloque: Bloque) -> Bloque:
    """Si el modelo copió las líneas con el prefijo '  12| ' de read_file, se quita."""

    def limpiar(texto: str) -> str:
        lineas = texto.splitlines(keepends=True)
        no_vacias = [l for l in lineas if l.strip()]
        if no_vacias and all(_NUMERO_LINEA.match(l) for l in no_vacias):
            return "".join(_NUMERO_LINEA.sub("", l, count=1) if l.strip() else l for l in lineas)
        return texto

    return Bloque(limpiar(bloque.buscar), limpiar(bloque.reemplazar))


def _sin_lineas_vacias_extremas(lineas: list[str]) -> list[str]:
    inicio, fin = 0, len(lineas)
    while inicio < fin and not lineas[inicio].strip():
        inicio += 1
    while fin > inicio and not lineas[fin - 1].strip():
        fin -= 1
    return lineas[inicio:fin]


def _indent(linea: str) -> str:
    return linea[: len(linea) - len(linea.lstrip())]


def _reindentar(reemplazo: list[str], indent_buscar: str, indent_archivo: str) -> list[str]:
    if indent_buscar == indent_archivo:
        return reemplazo
    if indent_archivo.startswith(indent_buscar):
        extra = indent_archivo[len(indent_buscar):]
        return [extra + l if l.strip() else l for l in reemplazo]
    if indent_buscar.startswith(indent_archivo):
        sobra = len(indent_buscar) - len(indent_archivo)
        salida = []
        for l in reemplazo:
            quitar = min(sobra, len(_indent(l)))
            salida.append(l[quitar:] if l.strip() else l)
        return salida
    return reemplazo


def _buscar_ventanas(archivo: list[str], buscar: list[str], norm) -> list[int]:
    n = len(buscar)
    objetivo = [norm(l) for l in buscar]
    normalizado = [norm(l) for l in archivo]
    return [
        i for i in range(0, len(archivo) - n + 1)
        if normalizado[i:i + n] == objetivo
    ]


def lineas_parecidas(contenido: str, buscar: str, max_lineas: int = 18) -> str:
    archivo = contenido.splitlines()
    patron = _sin_lineas_vacias_extremas(buscar.splitlines())
    if not archivo or not patron or len(archivo) > 8000:
        return ""
    n = len(patron)
    objetivo = "\n".join(l.strip() for l in patron)
    candidatos = []
    for i in range(0, max(1, len(archivo) - n + 1)):
        ventana = "\n".join(l.strip() for l in archivo[i:i + n])
        sm = SequenceMatcher(None, objetivo, ventana, autojunk=False)
        candidatos.append((sm.quick_ratio(), i, ventana))
    candidatos.sort(reverse=True)
    mejor_ratio, mejor_i = 0.0, 0
    for _, i, ventana in candidatos[:25]:
        r = SequenceMatcher(None, objetivo, ventana, autojunk=False).ratio()
        if r > mejor_ratio:
            mejor_ratio, mejor_i = r, i
    if mejor_ratio < 0.35:
        return ""
    fin = min(len(archivo), mejor_i + max(n, 1))
    fin = min(fin, mejor_i + max_lineas)
    return "\n".join(f"{k + 1:>5}| {archivo[k]}" for k in range(mejor_i, fin))


def _aplicar_uno(contenido: str, bloque: Bloque) -> tuple[str, Optional[str]]:
    buscar, reemplazar = bloque.buscar, bloque.reemplazar

    if not buscar.strip():
        if not contenido.strip():
            return reemplazar, None
        raise ErrorEdicion(
            "SEARCH vacío solo sirve para archivos nuevos o vacíos. "
            "Para agregar texto, poné en SEARCH unas líneas existentes y repetilas en REPLACE junto con lo nuevo."
        )

    veces = contenido.count(buscar)
    if veces == 1:
        return contenido.replace(buscar, reemplazar, 1), None
    if veces > 1:
        raise ErrorEdicion(
            f"El texto de SEARCH aparece {veces} veces. Agregá líneas de contexto vecinas para que sea único."
        )

    archivo = contenido.splitlines(keepends=True)
    patron = _sin_lineas_vacias_extremas(buscar.splitlines())
    reemplazo = reemplazar.splitlines()
    if patron:
        for norm, reindentar in ((str.rstrip, False), (str.strip, True)):
            coincidencias = _buscar_ventanas(
                [l.rstrip("\r\n") for l in archivo], patron, norm
            )
            if len(coincidencias) > 1:
                raise ErrorEdicion(
                    f"El texto de SEARCH coincide en {len(coincidencias)} lugares. "
                    "Agregá contexto para hacerlo único."
                )
            if len(coincidencias) == 1:
                i = coincidencias[0]
                nuevas = reemplazo
                if reindentar:
                    j = next((k for k, l in enumerate(patron) if l.strip()), 0)
                    nuevas = _reindentar(
                        reemplazo, _indent(patron[j]), _indent(archivo[i + j].rstrip("\r\n"))
                    )
                fin = i + len(patron)
                ultima_sin_salto = fin == len(archivo) and not archivo[-1].endswith("\n")
                texto_nuevo = "".join(l + "\n" for l in nuevas)
                if ultima_sin_salto and texto_nuevo.endswith("\n"):
                    texto_nuevo = texto_nuevo[:-1]
                nota = None if not reindentar else "coincidencia ignorando indentación"
                return "".join(archivo[:i]) + texto_nuevo + "".join(archivo[fin:]), nota

    # Reintento de una edición que ya se aplicó: el REPLACE ya está en el archivo.
    # Solo con reemplazos suficientemente específicos para no dar falsos positivos.
    especifico = len([l for l in reemplazo if l.strip()]) >= 2 or len(reemplazar.strip()) >= 40
    if especifico and reemplazar.strip() in contenido:
        return contenido, "ya estaba aplicado"

    parecido = lineas_parecidas(contenido, buscar)
    mensaje = "No encontré el texto de SEARCH en el archivo. Copiá el texto EXACTO actual (sin números de línea)."
    if parecido:
        mensaje += "\nLas líneas más parecidas del archivo son:\n" + parecido
    else:
        mensaje += " Volvé a leer el archivo con read_file."
    raise ErrorEdicion(mensaje)


def aplicar_bloques(contenido: str, bloques: list[Bloque]) -> tuple[str, list[str]]:
    """Aplica todos los bloques o ninguno. Devuelve (nuevo_contenido, notas)."""
    notas: list[str] = []
    actual = contenido
    for numero, bloque in enumerate(bloques, start=1):
        try:
            actual, nota = _aplicar_uno(actual, bloque)
        except ErrorEdicion as e:
            prefijo = f"Bloque {numero} de {len(bloques)}: " if len(bloques) > 1 else ""
            raise ErrorEdicion(
                f"{prefijo}{e}\n(No se aplicó ningún cambio de esta edición.)"
            ) from None
        if nota:
            notas.append(f"bloque {numero}: {nota}")
    return actual, notas


# ======================================================================
# v7: DIFF UNIFICADO, RANGOS DE LÍNEAS E INSERCIONES
# ======================================================================
_RE_HUNK = re.compile(r"^@@\s*-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s*@@")


def parece_diff_unificado(texto: str) -> bool:
    lineas = (texto or "").splitlines()
    return any(_RE_HUNK.match(l) for l in lineas) or (
        any(l.startswith("--- ") for l in lineas) and any(l.startswith("+++ ") for l in lineas)
    )


@dataclass
class Hunk:
    viejo_inicio: int
    contexto: list  # (tipo, texto) con tipo en " ", "-", "+"


def parsear_diff_unificado(diff: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    actual: Optional[Hunk] = None
    for linea in (diff or "").splitlines():
        if linea.startswith(("--- ", "+++ ", "diff ", "index ")):
            continue
        m = _RE_HUNK.match(linea)
        if m:
            actual = Hunk(int(m.group(1)), [])
            hunks.append(actual)
            continue
        if linea.startswith("@@"):
            # Hunk sin números ("@@ ... @@"): se ubica por contexto.
            actual = Hunk(0, [])
            hunks.append(actual)
            continue
        if actual is None:
            continue
        if linea.startswith("\\"):
            continue  # "\ No newline at end of file"
        tipo = linea[:1] if linea[:1] in (" ", "-", "+") else " "
        texto = linea[1:] if linea[:1] in (" ", "-", "+") else linea
        actual.contexto.append((tipo, texto))
    if not hunks:
        raise ErrorEdicion("No encontré hunks '@@ -a,b +c,d @@' en el diff.")
    return hunks


def aplicar_diff_unificado(contenido: str, diff: str) -> tuple[str, list[str]]:
    """
    Aplica un diff unificado tolerando números de línea incorrectos: cada hunk
    se ubica buscando sus líneas de contexto+borrado (exacto, luego ignorando
    espacios). Todo o nada.
    """
    hunks = parsear_diff_unificado(diff)
    lineas = contenido.splitlines()
    termina_con_salto = contenido.endswith("\n") or not contenido
    notas: list[str] = []
    desplazamiento = 0
    for numero, hunk in enumerate(hunks, start=1):
        viejas = [t for tipo, t in hunk.contexto if tipo in (" ", "-")]
        nuevas = [t for tipo, t in hunk.contexto if tipo in (" ", "+")]
        if not viejas:
            # Solo agrega líneas: se insertan en la posición indicada (o al final).
            pos = min(len(lineas), max(0, hunk.viejo_inicio - 1 + desplazamiento)) if hunk.viejo_inicio else len(lineas)
            lineas[pos:pos] = nuevas
            desplazamiento += len(nuevas)
            continue
        posicion = None
        for norm in (lambda s: s, str.rstrip, str.strip):
            objetivo = [norm(l) for l in viejas]
            candidatos = [
                i for i in range(0, len(lineas) - len(viejas) + 1)
                if [norm(l) for l in lineas[i:i + len(viejas)]] == objetivo
            ]
            if len(candidatos) == 1:
                posicion = candidatos[0]
                break
            if len(candidatos) > 1:
                esperado = hunk.viejo_inicio - 1 + desplazamiento
                posicion = min(candidatos, key=lambda i: abs(i - esperado))
                notas.append(f"hunk {numero}: varias coincidencias, usé la más cercana a la línea {hunk.viejo_inicio}")
                break
        if posicion is None:
            parecido = lineas_parecidas("\n".join(lineas), "\n".join(viejas))
            mensaje = f"Hunk {numero}: no encontré sus líneas de contexto en el archivo."
            if parecido:
                mensaje += "\nLo más parecido:\n" + parecido
            raise ErrorEdicion(mensaje + "\n(No se aplicó ningún cambio de esta edición.)")
        lineas[posicion:posicion + len(viejas)] = nuevas
        desplazamiento += len(nuevas) - len(viejas)
    resultado = "\n".join(lineas)
    if termina_con_salto and resultado:
        resultado += "\n"
    return resultado, notas


def reemplazar_lineas(contenido: str, desde: int, hasta: int, nuevo: str) -> str:
    """Reemplaza las líneas desde..hasta (1-indexadas, inclusive) por 'nuevo'."""
    lineas = contenido.splitlines(keepends=True)
    total = len(lineas)
    if desde < 1 or hasta < desde - 1 or desde > total + 1:
        raise ErrorEdicion(f"Rango inválido {desde}-{hasta} (el archivo tiene {total} líneas).")
    hasta = min(hasta, total)
    texto = nuevo
    if texto and not texto.endswith("\n") and (hasta < total or contenido.endswith("\n")):
        texto += "\n"
    return "".join(lineas[:desde - 1]) + texto + "".join(lineas[hasta:])


def insertar_despues(contenido: str, linea: int, texto: str) -> str:
    """Inserta 'texto' después de la línea indicada (0 = al principio)."""
    lineas = contenido.splitlines(keepends=True)
    if linea < 0 or linea > len(lineas):
        raise ErrorEdicion(f"Línea {linea} fuera de rango (el archivo tiene {len(lineas)} líneas).")
    if lineas and linea == len(lineas) and not lineas[-1].endswith("\n"):
        lineas[-1] += "\n"
    if texto and not texto.endswith("\n"):
        texto += "\n"
    return "".join(lineas[:linea]) + texto + "".join(lineas[linea:])


def agregar_al_final(contenido: str, texto: str) -> str:
    if not contenido:
        return texto if texto.endswith("\n") or not texto else texto + "\n"
    base = contenido if contenido.endswith("\n") else contenido + "\n"
    if texto and not texto.endswith("\n"):
        texto += "\n"
    return base + texto


def solapamiento_final(existente: str, nuevo: str, minimo: int = 2) -> int:
    """
    Cuántas líneas del principio de 'nuevo' repiten el final de 'existente'.
    Sirve para continuar un archivo cortado sin duplicar las últimas líneas
    (los modelos suelen repetir 1-5 líneas al retomar).
    """
    viejas = existente.rstrip("\n").splitlines()
    nuevas = nuevo.splitlines()
    mejor = 0
    for k in range(1, min(len(viejas), len(nuevas), 40) + 1):
        if [l.rstrip() for l in viejas[-k:]] == [l.rstrip() for l in nuevas[:k]]:
            mejor = k
    if mejor < minimo and mejor:
        # Una sola línea repetida solo cuenta si es no trivial.
        if not viejas[-1].strip() or len(viejas[-1].strip()) < 12:
            return 0
    return mejor


def unir_continuacion(existente: str, nuevo: str) -> tuple[str, int]:
    """Pega 'nuevo' al final de 'existente' quitando la parte repetida. Devuelve (texto, repetidas)."""
    repetidas = solapamiento_final(existente, nuevo)
    nuevas = nuevo.splitlines(keepends=True)[repetidas:]
    return agregar_al_final(existente, "".join(nuevas)) if nuevas else existente, repetidas


def cortar_en_linea_completa(texto: str) -> str:
    """Descarta la última línea si quedó a medias (respuesta cortada por longitud)."""
    if not texto or texto.endswith("\n"):
        return texto
    corte = texto.rfind("\n")
    return texto[:corte + 1] if corte >= 0 else ""
