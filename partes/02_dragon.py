"""
El dragón de REAPER: pixel art vectorial que se rasteriza al ancho de la terminal.

En vez de guardar una imagen fija, el dragón está definido con formas
(polígonos para las alas, cabeza y cola; trazos gruesos para cuerpo y patas;
un cono para el fuego). Se rasteriza a la resolución exacta de la terminal y
se dibuja con medios bloques '▀' (2 píxeles por celda) en truecolor, así se ve
nítido tanto en un celular angosto como en una pantalla ancha.

También sirve para animar: las alas aletean moviendo sus vértices y el fuego
crece/titila cambiando el largo del cono y la semilla de las chispas.
"""

# Espacio de diseño: x 0..104, y 0..76 (proporción del dibujo original ~1.37:1).
_DW, _DH = 104.0, 76.0

_COLOR_CONTORNO = (22, 22, 64)
_COLOR_HUESO = (88, 26, 104)

# Ala izquierda (detrás de la cabeza), en orden horario. La raíz está en el hombro.
_ALA_IZQ = [
    (8.0, 1.0), (24.0, 6.5), (42.0, 14.0), (44.5, 22.0), (44.5, 37.5), (39.0, 36.5), (35.0, 35.0),
    (32.0, 30.5), (27.5, 31.5), (25.0, 26.5), (20.5, 26.0), (18.0, 21.5), (13.0, 20.0),
    (11.0, 12.0),
]
_ALA_IZQ_RAIZ = (41.0, 24.0)
_ALA_IZQ_MUNECA = (41.5, 14.5)
_ALA_IZQ_DEDOS = [(35.0, 35.0), (27.5, 31.5), (20.5, 26.0), (13.0, 20.0), (8.0, 1.0)]

# Ala derecha (la más grande, arriba a la derecha).
_ALA_DER = [
    (58.0, 15.0), (80.0, 6.0), (101.0, 1.0), (99.5, 8.0), (100.5, 20.0), (94.0, 21.5),
    (91.0, 24.5), (85.5, 24.5), (81.0, 29.5), (76.5, 29.5), (72.0, 35.5), (68.0, 34.0),
    (64.0, 38.5), (61.0, 41.5), (55.5, 40.5), (56.5, 28.0),
]
_ALA_DER_RAIZ = (59.0, 27.0)
_ALA_DER_MUNECA = (59.5, 15.5)
_ALA_DER_DEDOS = [(64.0, 38.5), (72.0, 35.5), (81.0, 29.5), (91.0, 24.5), (100.5, 20.0), (101.0, 1.0)]

# Cabeza mirando a la izquierda, con la boca abierta.
_CABEZA = [
    (25.5, 41.5), (29.5, 38.0), (33.5, 35.5), (37.5, 35.0), (40.5, 37.0), (40.0, 41.0),
    (36.0, 43.5), (32.0, 44.0), (29.0, 43.6), (31.5, 45.0), (30.5, 47.0), (27.5, 46.5),
    (26.0, 44.0),
]
_CUERNOS = [((35.5, 36.5), (41.0, 26.5), 1.1), ((38.0, 36.5), (44.5, 30.0), 1.0)]
# Púas del lomo: (x, y) de la base de cada una.
_PUAS = [(41.0, 36.4), (46.0, 36.0), (51.0, 36.6), (56.0, 38.6), (61.0, 42.4)]
_COLOR_PUA = (40, 52, 115)
_OJO = (32.6, 38.9)
_DIENTES = [(27.4, 43.2), (28.6, 43.6), (28.0, 45.3)]

# Cuello y cuerpo como trazo grueso: (x, y, grosor).
_CUERPO = [(36.0, 40.5, 3.4), (42.0, 40.0, 4.2), (49.0, 40.8, 4.8), (55.0, 43.0, 5.0), (61.0, 46.5, 4.6),
           (65.5, 49.0, 3.8)]
_PECHO = (44.0, 43.0, 3.2)
_PATAS = [
    [(43.0, 43.5, 1.6), (41.5, 48.0, 1.4), (39.5, 51.0, 1.1)],
    [(47.5, 44.0, 1.6), (47.0, 49.0, 1.4), (45.5, 52.0, 1.1)],
    [(58.0, 47.0, 2.0), (57.0, 52.0, 1.7), (54.5, 55.5, 1.2)],
    [(63.0, 49.5, 1.9), (63.5, 54.5, 1.6), (61.5, 57.5, 1.1)],
]
_GARRAS = [(39.0, 51.8), (45.0, 52.8), (54.0, 56.2), (61.0, 58.2)]

# Cola: curva que baja, se arrastra a la derecha y sube en rulo.
_COLA_CONTROL = [(65.0, 49.0), (71.0, 58.0), (75.0, 67.0), (84.0, 69.5), (91.5, 68.5), (94.5, 62.0), (93.0, 54.0)]
_COLA_PUNTA = [(92.5, 43.5), (96.0, 48.5), (95.5, 53.0), (92.5, 54.5), (90.0, 50.5)]

# Fuego: de la boca hacia abajo a la izquierda.
_FUEGO_ORIGEN = (27.0, 46.0)
_FUEGO_FIN = (2.5, 70.0)


def _dentro_poligono(x: float, y: float, poligono: Sequence[tuple]) -> bool:
    dentro = False
    n = len(poligono)
    j = n - 1
    for i in range(n):
        xi, yi = poligono[i]
        xj, yj = poligono[j]
        if (yi > y) != (yj > y):
            cruce = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            if x < cruce:
                dentro = not dentro
        j = i
    return dentro


def _distancia_segmento(px: float, py: float, a: tuple, b: tuple) -> tuple[float, float]:
    """(distancia, t) del punto al segmento ab, con t en [0, 1]."""
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    dx, dy = bx - ax, by - ay
    largo2 = dx * dx + dy * dy
    if largo2 == 0:
        return math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / largo2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), t


def _dentro_trazo(x: float, y: float, trazo: Sequence[tuple], grosor_min: float = 0.0) -> Optional[float]:
    """Si el punto cae en el trazo grueso devuelve la posición vertical relativa (-1 arriba, 1 abajo)."""
    mejor = None
    for a, b in zip(trazo, trazo[1:]):
        d, t = _distancia_segmento(x, y, a, b)
        grosor = max(grosor_min, a[2] + (b[2] - a[2]) * t)
        if d <= grosor:
            cy = a[1] + (b[1] - a[1]) * t
            rel = (y - cy) / grosor
            if mejor is None or abs(rel) < abs(mejor):
                mejor = rel
    return mejor


def _bezier(puntos: Sequence[tuple], pasos: int = 40) -> list[tuple]:
    """Curva Catmull-Rom que pasa por los puntos de control."""
    if len(puntos) < 2:
        return list(puntos)
    pts = [puntos[0]] + list(puntos) + [puntos[-1]]
    salida = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for k in range(pasos):
            t = k / pasos
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            salida.append((x, y))
    salida.append(puntos[-1])
    return salida


def _mezclar(c1: tuple, c2: tuple, t: float) -> tuple:
    t = max(0.0, min(1.0, t))
    return (int(c1[0] + (c2[0] - c1[0]) * t), int(c1[1] + (c2[1] - c1[1]) * t), int(c1[2] + (c2[2] - c1[2]) * t))


def _degradado_ala(t: float) -> tuple:
    """t=0 borde superior (magenta) → t=1 borde inferior (naranja claro)."""
    paradas = [(0.0, (150, 40, 150)), (0.25, (205, 50, 130)), (0.55, (250, 105, 55)),
               (0.8, (255, 145, 45)), (1.0, (255, 175, 85))]
    for (t1, c1), (t2, c2) in zip(paradas, paradas[1:]):
        if t <= t2:
            return _mezclar(c1, c2, (t - t1) / ((t2 - t1) or 1))
    return paradas[-1][1]


def _aletear(poligono: Sequence[tuple], raiz: tuple, fase: float, amplitud: float) -> list[tuple]:
    """Desplaza verticalmente los vértices según su distancia a la raíz (más lejos = más movimiento)."""
    if not fase:
        return list(poligono)
    maximo = max(math.hypot(x - raiz[0], y - raiz[1]) for x, y in poligono) or 1.0
    salida = []
    for x, y in poligono:
        peso = (math.hypot(x - raiz[0], y - raiz[1]) / maximo) ** 1.3
        salida.append((x, y + fase * amplitud * peso))
    return salida


def _ruido(i: int, j: int, semilla: int) -> float:
    h = (i * 374761393 + j * 668265263 + semilla * 2147483647) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def pintar_dragon(ancho: int, alto: Optional[int] = None, alas: float = 0.0, fuego: float = 1.0,
                  semilla: int = 7, contorno: bool = True) -> list[list[Optional[tuple]]]:
    """
    Devuelve una matriz alto×ancho de colores RGB (o None si es transparente).
    alas: -1..1 (posición del aleteo). fuego: 0..1 (largo de la llamarada).
    """
    ancho = max(16, int(ancho))
    if alto is None:
        alto = max(8, int(round(ancho * _DH / _DW)))
    sx, sy = _DW / ancho, _DH / alto

    ala_izq = _aletear(_ALA_IZQ, _ALA_IZQ_RAIZ, alas, 7.0)
    ala_der = _aletear(_ALA_DER, _ALA_DER_RAIZ, alas, 9.0)
    dedos_izq = _aletear(_ALA_IZQ_DEDOS, _ALA_IZQ_RAIZ, alas, 7.0)
    dedos_der = _aletear(_ALA_DER_DEDOS, _ALA_DER_RAIZ, alas, 9.0)
    muneca_izq = _aletear([_ALA_IZQ_MUNECA], _ALA_IZQ_RAIZ, alas, 7.0)[0]
    muneca_der = _aletear([_ALA_DER_MUNECA], _ALA_DER_RAIZ, alas, 9.0)[0]
    ys_izq = [p[1] for p in ala_izq]
    ys_der = [p[1] for p in ala_der]

    cola_eje = _bezier(_COLA_CONTROL, 18)
    n_cola = len(cola_eje)
    cola = [(x, y, 3.6 - 2.2 * (k / max(1, n_cola - 1))) for k, (x, y) in enumerate(cola_eje)]

    fx0, fy0 = _FUEGO_ORIGEN
    fx1, fy1 = _FUEGO_FIN
    largo_fuego = math.hypot(fx1 - fx0, fy1 - fy0)
    ux, uy = (fx1 - fx0) / largo_fuego, (fy1 - fy0) / largo_fuego

    pixeles: list[list[Optional[tuple]]] = [[None] * ancho for _ in range(alto)]
    capas: list[list[int]] = [[0] * ancho for _ in range(alto)]
    # capas: 0 vacío, 1 ala der, 2 ala izq, 3 cola, 4 cuerpo/patas, 5 cabeza, 6 fuego

    tolerancia_hueso = max(0.35, 0.5 * sx)
    con_huesos = ancho >= 36
    grosor_min = 0.8 * sx  # a baja resolución los trazos finos no deben desaparecer
    for j in range(alto):
        y = (j + 0.5) * sy
        for i in range(ancho):
            x = (i + 0.5) * sx
            color = None
            capa = 0

            if _dentro_poligono(x, y, ala_der):
                t = (y - min(ys_der)) / ((max(ys_der) - min(ys_der)) or 1)
                color, capa = _degradado_ala(t), 1
                if con_huesos and any(_distancia_segmento(x, y, muneca_der, d)[0] < tolerancia_hueso
                                      for d in dedos_der):
                    color = _COLOR_HUESO
            if _dentro_poligono(x, y, ala_izq):
                t = (y - min(ys_izq)) / ((max(ys_izq) - min(ys_izq)) or 1)
                color, capa = _degradado_ala(t), 2
                if con_huesos and any(_distancia_segmento(x, y, muneca_izq, d)[0] < tolerancia_hueso
                                      for d in dedos_izq):
                    color = _COLOR_HUESO

            rel = _dentro_trazo(x, y, cola, grosor_min)
            if rel is not None or _dentro_poligono(x, y, _COLA_PUNTA):
                if rel is None:
                    color = (120, 165, 235) if x < 93.5 else (80, 115, 200)
                else:
                    color = (150, 190, 245) if rel < -0.35 else ((60, 90, 170) if rel > 0.45 else (90, 125, 205))
                capa = 3

            for pata in _PATAS:
                rel_p = _dentro_trazo(x, y, pata, grosor_min)
                if rel_p is not None:
                    color = (70, 100, 180) if rel_p > 0 else (100, 140, 215)
                    capa = 4
            if any(math.hypot(x - gx, y - gy) < max(0.9, 0.8 * sx) for gx, gy in _GARRAS):
                color, capa = (35, 35, 80), 4

            for px_, py_ in _PUAS:
                if _dentro_poligono(x, y, [(px_ - 1.4, py_ + 1.2), (px_ + 1.0, py_ - 2.2), (px_ + 1.6, py_ + 1.2)]):
                    color, capa = _COLOR_PUA, 4
            rel = _dentro_trazo(x, y, _CUERPO, grosor_min)
            if rel is not None:
                if rel < -0.45:
                    color = (165, 200, 250)
                elif rel < 0.1:
                    color = (100, 138, 215)
                else:
                    color = (66, 96, 175)
                d_pecho = math.hypot(x - _PECHO[0], y - _PECHO[1])
                if d_pecho < _PECHO[2]:
                    color = _mezclar((255, 235, 190), (255, 140, 60), d_pecho / _PECHO[2])
                capa = 4

            if _dentro_poligono(x, y, _CABEZA):
                arriba = y < 39.5
                color = (150, 190, 245) if arriba else (95, 130, 210)
                capa = 5
            for base, punta, grosor in _CUERNOS:
                d, t = _distancia_segmento(x, y, base, punta)
                if d < grosor * (1.0 - 0.6 * t) + 0.25 * sx:
                    color, capa = (55, 70, 140), 5
            if math.hypot(x - _OJO[0], y - _OJO[1]) < max(0.85, 0.7 * sx):
                color, capa = (255, 245, 170), 5
            if any(math.hypot(x - dx, y - dy) < max(0.6, 0.55 * sx) for dx, dy in _DIENTES):
                color, capa = (250, 250, 255), 5

            if fuego > 0:
                vx, vy = x - fx0, y - fy0
                u = (vx * ux + vy * uy) / largo_fuego
                v = abs(-vx * uy + vy * ux)
                if 0 <= u <= fuego:
                    media = 1.0 + 9.5 * (u ** 0.8)
                    ruido = _ruido(i, j, semilla)
                    borde = media * (0.85 + 0.3 * ruido)
                    if v <= borde:
                        r = v / borde
                        if r < 0.22 and u < fuego * 0.9:
                            color = (255, 248, 215)
                        elif r < 0.45:
                            color = (255, 214, 80)
                        elif r < 0.72:
                            color = (255, 150, 40)
                        else:
                            color = (245, 70, 95) if ruido > 0.5 else (255, 95, 60)
                        if u > fuego * 0.82 and ruido > 0.82:
                            color = None if capa == 0 else color
                        if color is not None:
                            capa = 6
                elif fuego <= u <= fuego + 0.22:
                    media = 1.0 + 9.5 * (fuego ** 0.8)
                    if v <= media * 1.5 and _ruido(i, j, semilla + 11) > 0.86:
                        color = [(255, 90, 130), (255, 150, 40), (250, 60, 60)][int(_ruido(j, i, semilla) * 3) % 3]
                        capa = 6

            pixeles[j][i] = color
            capas[j][i] = capa

    if contorno:
        salida = [fila[:] for fila in pixeles]
        for j in range(alto):
            for i in range(ancho):
                capa = capas[j][i]
                vecinas = []
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = i + di, j + dj
                    vecinas.append(capas[nj][ni] if 0 <= ni < ancho and 0 <= nj < alto else 0)
                if capa == 0:
                    # Contorno por fuera: el píxel vacío pegado a una forma (salvo el fuego) se oscurece.
                    if any(v not in (0, 6) for v in vecinas):
                        salida[j][i] = _COLOR_CONTORNO
                elif capa in (1, 2) and ancho >= 40:
                    # Borde entre ala y cuerpo/cabeza para separar las formas.
                    if any(v in (3, 4, 5) for v in vecinas):
                        salida[j][i] = _COLOR_CONTORNO
        pixeles = salida
    return pixeles


def renderizar_pixeles(pixeles: list[list[Optional[tuple]]], margen: int = 0) -> list[str]:
    """Convierte la matriz en líneas de terminal usando medios bloques (2 filas por línea)."""
    lineas = []
    alto = len(pixeles)
    ancho = len(pixeles[0]) if pixeles else 0
    reset = C.RESET
    for j in range(0, alto, 2):
        partes = [" " * margen]
        arriba = pixeles[j]
        abajo = pixeles[j + 1] if j + 1 < alto else [None] * ancho
        for i in range(ancho):
            a, b = arriba[i], abajo[i]
            if a is None and b is None:
                partes.append(" ")
            elif a is not None and b is None:
                partes.append(rgb(*a) + "▀" + reset)
            elif a is None and b is not None:
                partes.append(rgb(*b) + "▄" + reset)
            elif a == b:
                partes.append(rgb(*a) + "█" + reset)
            else:
                partes.append(rgb(*a) + rgb(*b, fondo=True) + "▀" + reset)
        lineas.append("".join(partes).rstrip() if not _USAR_COLOR else "".join(partes))
    return lineas


_RAMPA_ASCII = " .:-=+*#%@"


def renderizar_ascii(pixeles: list[list[Optional[tuple]]], margen: int = 0) -> list[str]:
    """Versión sin color: un carácter por celda según el brillo promedio de dos píxeles."""
    lineas = []
    alto = len(pixeles)
    for j in range(0, alto, 2):
        fila = []
        for i in range(len(pixeles[j])):
            muestras = [p for p in (pixeles[j][i], pixeles[j + 1][i] if j + 1 < alto else None) if p]
            if not muestras:
                fila.append(" ")
                continue
            brillo = sum(0.3 * r + 0.59 * g + 0.11 * b for r, g, b in muestras) / len(muestras) / 255
            fila.append(_RAMPA_ASCII[1 + min(len(_RAMPA_ASCII) - 2, int(brillo * (len(_RAMPA_ASCII) - 1)))])
        lineas.append(" " * margen + "".join(fila).rstrip())
    return lineas


# Letras de bloque compactas (3 filas) para el logo.
_LETRAS = {
    "R": ["█▀▀▄", "█▄▄▀", "█  █"],
    "E": ["█▀▀▀", "█▄▄ ", "█▄▄▄"],
    "A": ["▄▀▀▄", "█▄▄█", "█  █"],
    "P": ["█▀▀▄", "█▄▄▀", "█   "],
    "V": ["█  █", "█  █", " ▀▀ "],
    "7": ["▀▀▀█", "  █ ", " █  "],
    " ": ["  ", "  ", "  "],
}


def logo_texto(texto: str = "REAPER") -> list[str]:
    filas = ["", "", ""]
    for letra in texto.upper():
        dibujo = _LETRAS.get(letra, _LETRAS[" "])
        for k in range(3):
            filas[k] += dibujo[k] + " "
    return [f.rstrip() for f in filas]


def logo_reaper(margen: int = 0) -> list[str]:
    filas = logo_texto("REAPER V7")
    if not _USAR_COLOR:
        return [" " * margen + f for f in filas]
    return [" " * margen + degradado(f, (255, 150, 40), (200, 60, 220)) for f in filas]


def ancho_dragon(columnas: Optional[int] = None) -> int:
    columnas = columnas or ancho_terminal()
    return max(28, min(72, columnas - 2))


def banner_dragon(columnas: Optional[int] = None, subtitulo: str = "") -> str:
    """Dragón + logo + subtítulo, listo para imprimir."""
    columnas = columnas or ancho_terminal()
    ancho = ancho_dragon(columnas)
    margen = max(0, (columnas - ancho) // 2)
    pixeles = pintar_dragon(ancho)
    lineas = renderizar_pixeles(pixeles, margen) if _USAR_COLOR else renderizar_ascii(pixeles, margen)
    logo = logo_reaper()
    ancho_logo = max(ancho_visible(l) for l in logo)
    margen_logo = max(0, (columnas - ancho_logo) // 2)
    lineas.append("")
    lineas.extend(" " * margen_logo + l for l in logo)
    texto = subtitulo or f"agente autónomo de programación · v{__version__} «{__codename__}»"
    margen_sub = max(0, (columnas - ancho_visible(texto)) // 2)
    lineas.append(" " * margen_sub + f"{C.ESCAMA}{texto}{C.RESET}")
    return "\n".join(lineas)


def animar_intro(columnas: Optional[int] = None, salida=None, cuadros: int = 7, pausa: float = 0.07) -> bool:
    """
    Pequeña animación de arranque: el dragón aletea mientras la llamarada crece.
    Devuelve False si no se pudo animar (sin TTY o sin color) para que se use el banner fijo.
    """
    salida = salida or sys.stdout
    try:
        es_tty = salida.isatty()
    except (AttributeError, ValueError):
        es_tty = False
    if not (_USAR_COLOR and es_tty) or os.getenv("REAPER_SIN_ANIMACION"):
        return False
    columnas = columnas or ancho_terminal()
    ancho = ancho_dragon(columnas)
    margen = max(0, (columnas - ancho) // 2)
    alto_lineas = None
    try:
        salida.write("\033[?25l")
        for k in range(cuadros):
            t = (k + 1) / cuadros
            alas = math.sin(t * math.pi * 2.0) * 0.8
            pixeles = pintar_dragon(ancho, alas=alas, fuego=min(1.0, 0.15 + t), semilla=7 + k)
            lineas = renderizar_pixeles(pixeles, margen)
            if alto_lineas is not None:
                salida.write(f"\033[{alto_lineas}A")
            salida.write("\n".join(l + "\033[K" for l in lineas) + "\n")
            salida.flush()
            alto_lineas = len(lineas)
            time.sleep(pausa)
        pixeles = pintar_dragon(ancho, alas=0.0, fuego=1.0, semilla=7)
        salida.write(f"\033[{alto_lineas}A")
        salida.write("\n".join(l + "\033[K" for l in renderizar_pixeles(pixeles, margen)) + "\n")
        logo = logo_reaper()
        ancho_logo = max(ancho_visible(l) for l in logo)
        margen_logo = max(0, (columnas - ancho_logo) // 2)
        salida.write("\n")
        for l in logo:
            salida.write(" " * margen_logo + l + "\n")
            salida.flush()
            time.sleep(pausa / 2)
        texto = f"agente autónomo de programación · v{__version__} «{__codename__}»"
        salida.write(" " * max(0, (columnas - ancho_visible(texto)) // 2) + f"{C.ESCAMA}{texto}{C.RESET}\n")
    except (OSError, ValueError):
        return False
    finally:
        try:
            salida.write("\033[?25h")
            salida.flush()
        except (OSError, ValueError):
            pass
    return True


def dragon_png(ruta: Path, ancho: int = 104, escala: int = 6, fondo: tuple = (255, 255, 255)) -> Path:
    """Exporta el dragón como PNG (sin dependencias) para compartirlo o usarlo de ícono."""
    import struct
    import zlib

    pixeles = pintar_dragon(ancho)
    alto = len(pixeles)
    filas = []
    for fila in pixeles:
        linea = bytearray([0])
        for px in fila:
            linea.extend(bytes(px or fondo) * escala)
        filas.append(bytes(linea) * escala)
    crudo = b"".join(filas)

    def bloque(tipo: bytes, datos: bytes) -> bytes:
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)

    cabecera = struct.pack(">IIBBBBB", ancho * escala, alto * escala, 8, 2, 0, 0, 0)
    datos = b"\x89PNG\r\n\x1a\n" + bloque(b"IHDR", cabecera) + bloque(b"IDAT", zlib.compress(crudo, 9)) + bloque(b"IEND", b"")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    return ruta
