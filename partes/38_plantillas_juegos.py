"""Plantillas de juegos para la terminal: motor puro testeable + interfaz de texto."""

# ======================================================================
# ahorcado
# ======================================================================
registrar_plantilla(
    "ahorcado",
    "Ahorcado en la terminal: palabras por categoría, tildes equivalentes, dibujo ASCII y pistas.",
    "python",
    {
        "ahorcado/__init__.py": "",
        "ahorcado/motor.py": r'''
import random
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

PALABRAS = {
    "animales": ["murciélago", "pingüino", "jirafa", "cocodrilo", "mariposa", "tiburón", "ñandú"],
    "programación": ["variable", "función", "algoritmo", "recursión", "compilador", "terminal", "depurar"],
    "frutas": ["frutilla", "durazno", "mandarina", "ananá", "pomelo", "arándano", "sandía"],
}
DIBUJOS = [
    "\n\n\n\n\n=====", "\n |\n |\n |\n |\n=====", " +---+\n |\n |\n |\n |\n=====",
    " +---+\n |   O\n |\n |\n |\n=====", " +---+\n |   O\n |   |\n |\n |\n=====",
    " +---+\n |   O\n |  /|\n |\n |\n=====", " +---+\n |   O\n |  /|\\\n |\n |\n=====",
    " +---+\n |   O\n |  /|\\\n |  /\n |\n=====", " +---+\n |   O\n |  /|\\\n |  / \\\n |\n=====",
]


def base(letra: str) -> str:
    """Letra sin tilde (la ñ se mantiene)."""
    if letra.lower() == "ñ":
        return "ñ"
    return "".join(c for c in unicodedata.normalize("NFD", letra.lower()) if not unicodedata.combining(c))


@dataclass
class Partida:
    palabra: str
    intentos: int = 8
    usadas: set = field(default_factory=set)
    fallos: int = 0

    @classmethod
    def nueva(cls, categoria: Optional[str] = None, semilla: Optional[int] = None) -> "Partida":
        azar = random.Random(semilla)
        categoria = categoria or azar.choice(sorted(PALABRAS))
        if categoria not in PALABRAS:
            raise ValueError(f"categoría desconocida: {categoria}")
        return cls(azar.choice(PALABRAS[categoria]))

    def adivinar(self, letra: str) -> bool:
        letra = base(letra.strip())
        if len(letra) != 1 or not letra.isalpha():
            raise ValueError("escribí una sola letra")
        if letra in self.usadas:
            raise ValueError(f"ya usaste la {letra}")
        if self.terminada:
            raise ValueError("la partida terminó")
        self.usadas.add(letra)
        acierto = any(base(c) == letra for c in self.palabra)
        if not acierto:
            self.fallos += 1
        return acierto

    def oculta(self) -> str:
        return " ".join(c if base(c) in self.usadas or not c.isalpha() else "_" for c in self.palabra)

    @property
    def ganada(self) -> bool:
        return all(base(c) in self.usadas for c in self.palabra if c.isalpha())

    @property
    def perdida(self) -> bool:
        return self.fallos >= self.intentos

    @property
    def terminada(self) -> bool:
        return self.ganada or self.perdida

    def dibujo(self) -> str:
        indice = min(len(DIBUJOS) - 1, self.fallos * (len(DIBUJOS) - 1) // self.intentos)
        return DIBUJOS[indice]

    def pista(self) -> str:
        faltan = sorted({base(c) for c in self.palabra if c.isalpha() and base(c) not in self.usadas})
        return faltan[0] if faltan else ""
''',
        "ahorcado/__main__.py": r'''
from ahorcado.motor import Partida

p = Partida.nueva()
while not p.terminada:
    print(p.dibujo())
    print(f"\n{p.oculta()}   fallos: {p.fallos}/{p.intentos}   usadas: {' '.join(sorted(p.usadas))}")
    try:
        entrada = input("letra (? = pista): ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if entrada == "?":
        print(f"pista: probá con la {p.pista()}")
        continue
    try:
        print("¡bien!" if p.adivinar(entrada) else "no está")
    except ValueError as e:
        print(e)
print(p.dibujo())
print(("¡GANASTE! " if p.ganada else "Perdiste. ") + f"La palabra era: {p.palabra}")
''',
        "tests/__init__.py": "",
        "tests/test_ahorcado.py": r'''
import unittest

from ahorcado.motor import PALABRAS, Partida, base


class TestAhorcado(unittest.TestCase):
    def test_tildes_equivalentes(self):
        self.assertEqual(base("Á"), "a")
        self.assertEqual(base("ñ"), "ñ")
        p = Partida("canción")
        self.assertTrue(p.adivinar("o"))
        self.assertIn("ó", p.oculta())

    def test_ganar(self):
        p = Partida("sol")
        for letra in "sol":
            p.adivinar(letra)
        self.assertTrue(p.ganada)
        self.assertEqual(p.oculta(), "s o l")
        with self.assertRaises(ValueError):
            p.adivinar("x")

    def test_perder_y_dibujo(self):
        p = Partida("sol", intentos=3)
        for letra in "xyz":
            self.assertFalse(p.adivinar(letra))
        self.assertTrue(p.perdida)
        self.assertIn("/ \\", p.dibujo())

    def test_validaciones_y_pista(self):
        p = Partida("luna")
        with self.assertRaises(ValueError):
            p.adivinar("ab")
        p.adivinar("a")
        with self.assertRaises(ValueError):
            p.adivinar("A")
        self.assertEqual(p.pista(), "l")

    def test_nueva(self):
        p = Partida.nueva("frutas", semilla=1)
        self.assertIn(p.palabra, PALABRAS["frutas"])
        with self.assertRaises(ValueError):
            Partida.nueva("planetas")


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m ahorcado",
    etiquetas=("juego", "ahorcado", "palabras", "adivinar", "terminal"),
)

# ======================================================================
# tateti con minimax
# ======================================================================
registrar_plantilla(
    "tateti",
    "Ta-te-ti contra la computadora imbatible (minimax con poda alfa-beta) y modo dos jugadores.",
    "python",
    {
        "tateti/__init__.py": "",
        "tateti/motor.py": r'''
from functools import lru_cache
from typing import Optional

LINEAS = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


def ganador(tablero: str) -> Optional[str]:
    """'X', 'O', 'empate' o None si sigue. El tablero es un string de 9 caracteres ('.' = vacío)."""
    for a, b, c in LINEAS:
        if tablero[a] != "." and tablero[a] == tablero[b] == tablero[c]:
            return tablero[a]
    return "empate" if "." not in tablero else None


def turno(tablero: str) -> str:
    return "X" if tablero.count("X") == tablero.count("O") else "O"


def jugar(tablero: str, casilla: int) -> str:
    if not 0 <= casilla <= 8:
        raise ValueError("casilla entre 1 y 9")
    if tablero[casilla] != ".":
        raise ValueError("casilla ocupada")
    if ganador(tablero):
        raise ValueError("la partida terminó")
    return tablero[:casilla] + turno(tablero) + tablero[casilla + 1:]


@lru_cache(maxsize=None)
def _minimax(tablero: str, alfa: int, beta: int) -> int:
    resultado = ganador(tablero)
    if resultado == "X":
        return 10 - tablero.count(".") * 0 - (9 - tablero.count("."))
    if resultado == "O":
        return -10 + (9 - tablero.count("."))
    if resultado == "empate":
        return 0
    maximizar = turno(tablero) == "X"
    mejor = -100 if maximizar else 100
    for i in range(9):
        if tablero[i] != ".":
            continue
        valor = _minimax(jugar(tablero, i), alfa, beta)
        if maximizar:
            mejor = max(mejor, valor)
            alfa = max(alfa, valor)
        else:
            mejor = min(mejor, valor)
            beta = min(beta, valor)
        if beta <= alfa:
            break
    return mejor


def mejor_jugada(tablero: str) -> int:
    if ganador(tablero):
        raise ValueError("la partida terminó")
    maximizar = turno(tablero) == "X"
    opciones = []
    for i in range(9):
        if tablero[i] == ".":
            opciones.append((_minimax(jugar(tablero, i), -100, 100), i))
    opciones.sort(key=lambda t: (-t[0], t[1]) if maximizar else (t[0], t[1]))
    return opciones[0][1]


def dibujar(tablero: str) -> str:
    filas = []
    for f in range(3):
        celdas = [tablero[f * 3 + c] if tablero[f * 3 + c] != "." else str(f * 3 + c + 1) for c in range(3)]
        filas.append(" " + " │ ".join(celdas))
    return "\n───┼───┼───\n".join(filas)
''',
        "tateti/__main__.py": r'''
from tateti.motor import dibujar, ganador, jugar, mejor_jugada

tablero = "........."
contra_pc = input("¿Jugar contra la computadora? (S/n) ").strip().lower() != "n"
while not ganador(tablero):
    print("\n" + dibujar(tablero))
    if contra_pc and tablero.count(".") % 2 == 0:
        tablero = jugar(tablero, mejor_jugada(tablero))
        continue
    try:
        tablero = jugar(tablero, int(input("casilla (1-9): ")) - 1)
    except (ValueError, IndexError) as e:
        print(f"inválido: {e}")
    except (EOFError, KeyboardInterrupt):
        raise SystemExit
print("\n" + dibujar(tablero))
resultado = ganador(tablero)
print("¡Empate!" if resultado == "empate" else f"Ganó {resultado}")
''',
        "tests/__init__.py": "",
        "tests/test_tateti.py": r'''
import itertools
import unittest

from tateti.motor import dibujar, ganador, jugar, mejor_jugada, turno


class TestTateti(unittest.TestCase):
    def test_ganador(self):
        self.assertEqual(ganador("XXX......"), "X")
        self.assertEqual(ganador("O...O...O"), "O")
        self.assertEqual(ganador("XOXXOOOXX"), "empate")
        self.assertIsNone(ganador("........."))

    def test_jugar_y_errores(self):
        t = jugar(".........", 4)
        self.assertEqual((t, turno(t)), ("....X....", "O"))
        with self.assertRaises(ValueError):
            jugar(t, 4)
        with self.assertRaises(ValueError):
            jugar(t, 9)

    def test_ia_gana_o_bloquea(self):
        self.assertEqual(mejor_jugada("XX.OO...."), 2)   # X gana
        self.assertEqual(mejor_jugada("XX..O...."), 2)   # O bloquea

    def test_ia_nunca_pierde(self):
        """La IA juega de O contra todas las secuencias de un rival al azar sistemático."""
        for primera in range(9):
            tablero = jugar(".........", primera)
            for orden in itertools.islice(itertools.permutations(range(9)), 0, 2000, 37):
                t = tablero
                while not ganador(t):
                    if turno(t) == "O":
                        t = jugar(t, mejor_jugada(t))
                    else:
                        t = jugar(t, next(i for i in orden if t[i] == "."))
                self.assertNotEqual(ganador(t), "X", t)

    def test_dibujo(self):
        self.assertIn("X │ 2 │ 3", dibujar("X........"))


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m tateti",
    etiquetas=("juego", "tateti", "tres en raya", "minimax", "ia", "tablero"),
)

# ======================================================================
# buscaminas
# ======================================================================
registrar_plantilla(
    "buscaminas",
    "Buscaminas en la terminal: primer clic seguro, apertura en cascada, banderas y detección de victoria.",
    "python",
    {
        "buscaminas/__init__.py": "",
        "buscaminas/motor.py": r'''
import random
from collections import deque
from typing import Optional


class Tablero:
    def __init__(self, filas: int = 9, columnas: int = 9, minas: int = 10, semilla: Optional[int] = None):
        if minas >= filas * columnas:
            raise ValueError("demasiadas minas para el tablero")
        self.filas, self.columnas, self.cantidad_minas = filas, columnas, minas
        self.azar = random.Random(semilla)
        self.minas: set = set()
        self.abiertas: set = set()
        self.banderas: set = set()
        self.exploto = False

    def _vecinos(self, f: int, c: int):
        for df in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if (df or dc) and 0 <= f + df < self.filas and 0 <= c + dc < self.columnas:
                    yield f + df, c + dc

    def _sembrar(self, seguro: tuple) -> None:
        prohibidas = {seguro, *self._vecinos(*seguro)}
        libres = [(f, c) for f in range(self.filas) for c in range(self.columnas) if (f, c) not in prohibidas]
        if len(libres) < self.cantidad_minas:
            libres = [(f, c) for f in range(self.filas) for c in range(self.columnas) if (f, c) != seguro]
        self.minas = set(self.azar.sample(libres, self.cantidad_minas))

    def numero(self, f: int, c: int) -> int:
        return sum(1 for v in self._vecinos(f, c) if v in self.minas)

    def abrir(self, f: int, c: int) -> int:
        """Abre una casilla. Devuelve cuántas se abrieron (0 si era bandera o ya estaba abierta)."""
        if not (0 <= f < self.filas and 0 <= c < self.columnas):
            raise ValueError("casilla fuera del tablero")
        if self.terminado or (f, c) in self.banderas or (f, c) in self.abiertas:
            return 0
        if not self.minas:
            self._sembrar((f, c))
        if (f, c) in self.minas:
            self.exploto = True
            self.abiertas.add((f, c))
            return 1
        abiertas = 0
        cola = deque([(f, c)])
        while cola:
            actual = cola.popleft()
            if actual in self.abiertas or actual in self.banderas:
                continue
            self.abiertas.add(actual)
            abiertas += 1
            if self.numero(*actual) == 0:
                cola.extend(v for v in self._vecinos(*actual) if v not in self.abiertas)
        return abiertas

    def bandera(self, f: int, c: int) -> bool:
        if (f, c) in self.abiertas:
            return False
        if (f, c) in self.banderas:
            self.banderas.discard((f, c))
            return False
        self.banderas.add((f, c))
        return True

    @property
    def ganado(self) -> bool:
        return bool(self.minas) and not self.exploto and \
            len(self.abiertas) == self.filas * self.columnas - self.cantidad_minas

    @property
    def terminado(self) -> bool:
        return self.exploto or self.ganado

    def dibujar(self, revelar: bool = False) -> str:
        lineas = ["   " + " ".join(f"{c % 10}" for c in range(self.columnas))]
        for f in range(self.filas):
            celdas = []
            for c in range(self.columnas):
                if (f, c) in self.abiertas or (revelar and (f, c) in self.minas):
                    celdas.append("*" if (f, c) in self.minas else (str(self.numero(f, c)) if self.numero(f, c) else " "))
                else:
                    celdas.append("⚑" if (f, c) in self.banderas else "■")
            lineas.append(f"{f:>2} " + " ".join(celdas))
        return "\n".join(lineas)
''',
        "buscaminas/__main__.py": r'''
from buscaminas.motor import Tablero

t = Tablero()
while not t.terminado:
    print(t.dibujar())
    try:
        partes = input("fila columna (b fila columna = bandera): ").split()
        if partes and partes[0] == "b":
            t.bandera(int(partes[1]), int(partes[2]))
        else:
            t.abrir(int(partes[0]), int(partes[1]))
    except (ValueError, IndexError):
        print("formato: 3 4   o   b 3 4")
    except (EOFError, KeyboardInterrupt):
        raise SystemExit
print(t.dibujar(revelar=True))
print("¡GANASTE!" if t.ganado else "💥 Boom")
''',
        "tests/__init__.py": "",
        "tests/test_buscaminas.py": r'''
import unittest

from buscaminas.motor import Tablero


class TestBuscaminas(unittest.TestCase):
    def test_primer_clic_seguro(self):
        for semilla in range(30):
            t = Tablero(9, 9, 10, semilla)
            t.abrir(4, 4)
            self.assertFalse(t.exploto)
            self.assertEqual(len(t.minas), 10)
            self.assertNotIn((4, 4), t.minas)

    def test_cascada(self):
        t = Tablero(5, 5, 1, semilla=1)
        t.minas = {(0, 0)}
        abiertas = t.abrir(4, 4)
        self.assertEqual(abiertas, 24)
        self.assertTrue(t.ganado)

    def test_explotar(self):
        t = Tablero(3, 3, 1)
        t.minas = {(1, 1)}
        t.abrir(1, 1)
        self.assertTrue(t.exploto)
        self.assertEqual(t.abrir(0, 0), 0)
        self.assertIn("*", t.dibujar(revelar=True))

    def test_banderas_y_numeros(self):
        t = Tablero(3, 3, 2)
        t.minas = {(0, 0), (0, 2)}
        self.assertEqual(t.numero(1, 1), 2)
        self.assertTrue(t.bandera(0, 0))
        self.assertEqual(t.abrir(0, 0), 0)
        self.assertFalse(t.bandera(0, 0))
        with self.assertRaises(ValueError):
            t.abrir(5, 5)
        with self.assertRaises(ValueError):
            Tablero(2, 2, 4)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m buscaminas",
    etiquetas=("juego", "buscaminas", "minas", "tablero", "puzzle"),
)

# ======================================================================
# 2048
# ======================================================================
registrar_plantilla(
    "2048",
    "El juego 2048 en la terminal: movimientos, fusiones correctas, puntaje y detección de fin.",
    "python",
    {
        "juego2048/__init__.py": "",
        "juego2048/motor.py": r'''
import random
from typing import Optional


def deslizar_fila(fila: list) -> tuple[list, int]:
    """Desliza una fila hacia la izquierda fusionando una vez por casilla. Devuelve (fila, puntos)."""
    numeros = [n for n in fila if n]
    resultado, puntos, i = [], 0, 0
    while i < len(numeros):
        if i + 1 < len(numeros) and numeros[i] == numeros[i + 1]:
            resultado.append(numeros[i] * 2)
            puntos += numeros[i] * 2
            i += 2
        else:
            resultado.append(numeros[i])
            i += 1
    return resultado + [0] * (len(fila) - len(resultado)), puntos


class Juego:
    def __init__(self, tamano: int = 4, semilla: Optional[int] = None):
        self.tamano = tamano
        self.azar = random.Random(semilla)
        self.tablero = [[0] * tamano for _ in range(tamano)]
        self.puntaje = 0
        self.agregar_ficha()
        self.agregar_ficha()

    def agregar_ficha(self) -> bool:
        vacias = [(f, c) for f in range(self.tamano) for c in range(self.tamano) if not self.tablero[f][c]]
        if not vacias:
            return False
        f, c = self.azar.choice(vacias)
        self.tablero[f][c] = 4 if self.azar.random() < 0.1 else 2
        return True

    def _rotar(self, veces: int) -> None:
        for _ in range(veces % 4):
            self.tablero = [list(fila) for fila in zip(*self.tablero[::-1])]

    def mover(self, direccion: str) -> bool:
        """direccion: izquierda, derecha, arriba, abajo. Devuelve True si algo se movió."""
        rotaciones = {"izquierda": 0, "abajo": 1, "derecha": 2, "arriba": 3}
        if direccion not in rotaciones:
            raise ValueError("dirección inválida")
        antes = [fila[:] for fila in self.tablero]
        self._rotar(rotaciones[direccion])
        for i, fila in enumerate(self.tablero):
            self.tablero[i], puntos = deslizar_fila(fila)
            self.puntaje += puntos
        self._rotar(-rotaciones[direccion])
        movio = self.tablero != antes
        if movio:
            self.agregar_ficha()
        return movio

    def maximo(self) -> int:
        return max(max(fila) for fila in self.tablero)

    def puede_moverse(self) -> bool:
        for f in range(self.tamano):
            for c in range(self.tamano):
                valor = self.tablero[f][c]
                if not valor:
                    return True
                if c + 1 < self.tamano and self.tablero[f][c + 1] == valor:
                    return True
                if f + 1 < self.tamano and self.tablero[f + 1][c] == valor:
                    return True
        return False

    def dibujar(self) -> str:
        return "\n".join(" ".join(f"{n:>5}" if n else "    ·" for n in fila) for fila in self.tablero)
''',
        "juego2048/__main__.py": r'''
from juego2048.motor import Juego

TECLAS = {"a": "izquierda", "d": "derecha", "w": "arriba", "s": "abajo"}
j = Juego()
while j.puede_moverse():
    print(f"\n{j.dibujar()}\npuntaje: {j.puntaje}")
    try:
        tecla = input("w/a/s/d (q sale): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        break
    if tecla == "q":
        break
    if tecla in TECLAS:
        j.mover(TECLAS[tecla])
print(f"Fin. Puntaje {j.puntaje}, ficha máxima {j.maximo()}")
''',
        "tests/__init__.py": "",
        "tests/test_2048.py": r'''
import unittest

from juego2048.motor import Juego, deslizar_fila


class Test2048(unittest.TestCase):
    def test_deslizar(self):
        self.assertEqual(deslizar_fila([2, 2, 2, 2]), ([4, 4, 0, 0], 8))
        self.assertEqual(deslizar_fila([2, 0, 2, 4]), ([4, 4, 0, 0], 4))
        self.assertEqual(deslizar_fila([4, 4, 8, 0]), ([8, 8, 0, 0], 8))
        self.assertEqual(deslizar_fila([2, 4, 8, 16]), ([2, 4, 8, 16], 0))

    def test_mover_en_todas_direcciones(self):
        j = Juego(semilla=1)
        j.tablero = [[2, 0, 0, 2], [0, 0, 0, 0], [0, 0, 0, 0], [2, 0, 0, 0]]
        self.assertTrue(j.mover("izquierda"))
        self.assertEqual(j.tablero[0][0], 4)
        self.assertEqual(j.puntaje, 4)
        j.tablero = [[2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [2, 0, 0, 0]]
        j.mover("arriba")
        self.assertEqual(j.tablero[0][0], 4)
        with self.assertRaises(ValueError):
            j.mover("diagonal")

    def test_sin_movimiento_no_agrega(self):
        j = Juego(semilla=2)
        j.tablero = [[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2]]
        self.assertFalse(j.mover("izquierda"))
        self.assertFalse(j.puede_moverse())

    def test_inicio(self):
        j = Juego(semilla=3)
        self.assertEqual(sum(1 for fila in j.tablero for n in fila if n), 2)
        self.assertIn(j.maximo(), (2, 4))


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m juego2048",
    etiquetas=("juego", "2048", "puzzle", "numeros", "fichas"),
)

# ======================================================================
# conecta 4
# ======================================================================
registrar_plantilla(
    "conecta4",
    "Conecta 4 contra la computadora (minimax con heurística de ventanas y poda alfa-beta).",
    "python",
    {
        "conecta4/__init__.py": "",
        "conecta4/motor.py": r'''
import math
from typing import Optional

FILAS, COLUMNAS = 6, 7
VACIO = "."


def nuevo() -> list:
    return [[VACIO] * COLUMNAS for _ in range(FILAS)]


def columnas_validas(t: list) -> list:
    return [c for c in range(COLUMNAS) if t[0][c] == VACIO]


def soltar(t: list, columna: int, ficha: str) -> int:
    """Suelta una ficha; devuelve la fila donde cayó. Modifica t."""
    if columna not in columnas_validas(t):
        raise ValueError("columna llena o inválida")
    for fila in range(FILAS - 1, -1, -1):
        if t[fila][columna] == VACIO:
            t[fila][columna] = ficha
            return fila
    raise ValueError("columna llena")


def gano(t: list, ficha: str) -> bool:
    for f in range(FILAS):
        for c in range(COLUMNAS):
            for df, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                if all(0 <= f + i * df < FILAS and 0 <= c + i * dc < COLUMNAS and t[f + i * df][c + i * dc] == ficha
                       for i in range(4)):
                    return True
    return False


def _puntuar_ventana(ventana: list, ficha: str, rival: str) -> int:
    if ventana.count(ficha) == 4:
        return 100
    if ventana.count(ficha) == 3 and ventana.count(VACIO) == 1:
        return 5
    if ventana.count(ficha) == 2 and ventana.count(VACIO) == 2:
        return 2
    if ventana.count(rival) == 3 and ventana.count(VACIO) == 1:
        return -4
    return 0


def evaluar(t: list, ficha: str) -> int:
    rival = "O" if ficha == "X" else "X"
    puntaje = sum(3 for f in range(FILAS) if t[f][COLUMNAS // 2] == ficha)
    for f in range(FILAS):
        for c in range(COLUMNAS):
            for df, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                celdas = [(f + i * df, c + i * dc) for i in range(4)]
                if all(0 <= a < FILAS and 0 <= b < COLUMNAS for a, b in celdas):
                    puntaje += _puntuar_ventana([t[a][b] for a, b in celdas], ficha, rival)
    return puntaje


def minimax(t: list, profundidad: int, alfa: float, beta: float, maximizar: bool, ficha: str) -> tuple:
    rival = "O" if ficha == "X" else "X"
    validas = columnas_validas(t)
    if gano(t, ficha):
        return None, 10 ** 6 + profundidad
    if gano(t, rival):
        return None, -(10 ** 6) - profundidad
    if not validas or profundidad == 0:
        return None, evaluar(t, ficha)
    orden = sorted(validas, key=lambda c: abs(c - COLUMNAS // 2))
    mejor_col = orden[0]
    if maximizar:
        valor = -math.inf
        for c in orden:
            fila = soltar(t, c, ficha)
            puntaje = minimax(t, profundidad - 1, alfa, beta, False, ficha)[1]
            t[fila][c] = VACIO
            if puntaje > valor:
                valor, mejor_col = puntaje, c
            alfa = max(alfa, valor)
            if alfa >= beta:
                break
    else:
        valor = math.inf
        for c in orden:
            fila = soltar(t, c, rival)
            puntaje = minimax(t, profundidad - 1, alfa, beta, True, ficha)[1]
            t[fila][c] = VACIO
            if puntaje < valor:
                valor, mejor_col = puntaje, c
            beta = min(beta, valor)
            if alfa >= beta:
                break
    return mejor_col, valor


def jugada_ia(t: list, ficha: str = "O", profundidad: int = 4) -> int:
    return minimax(t, profundidad, -math.inf, math.inf, True, ficha)[0]


def dibujar(t: list) -> str:
    return "\n".join(" ".join(fila) for fila in t) + "\n" + " ".join(str(c + 1) for c in range(COLUMNAS))
''',
        "conecta4/__main__.py": r'''
from conecta4.motor import columnas_validas, dibujar, gano, jugada_ia, nuevo, soltar

t = nuevo()
while columnas_validas(t):
    print("\n" + dibujar(t))
    try:
        soltar(t, int(input("columna (1-7): ")) - 1, "X")
    except ValueError as e:
        print(e)
        continue
    except (EOFError, KeyboardInterrupt):
        raise SystemExit
    if gano(t, "X"):
        print(dibujar(t) + "\n¡Ganaste!")
        break
    soltar(t, jugada_ia(t), "O")
    if gano(t, "O"):
        print(dibujar(t) + "\nGanó la computadora")
        break
else:
    print("Empate")
''',
        "tests/__init__.py": "",
        "tests/test_conecta4.py": r'''
import unittest

from conecta4.motor import columnas_validas, gano, jugada_ia, nuevo, soltar


class TestConecta4(unittest.TestCase):
    def test_soltar_y_columna_llena(self):
        t = nuevo()
        self.assertEqual(soltar(t, 3, "X"), 5)
        self.assertEqual(soltar(t, 3, "O"), 4)
        for _ in range(4):
            soltar(t, 3, "X")
        self.assertNotIn(3, columnas_validas(t))
        with self.assertRaises(ValueError):
            soltar(t, 3, "O")

    def test_victorias(self):
        t = nuevo()
        for c in range(4):
            soltar(t, c, "X")
        self.assertTrue(gano(t, "X"))
        t = nuevo()
        for i in range(4):
            for _ in range(i):
                soltar(t, i, "O")
            soltar(t, i, "X")
        self.assertTrue(gano(t, "X"))  # diagonal

    def test_ia_gana_y_bloquea(self):
        t = nuevo()
        for c in range(3):
            soltar(t, c, "O")
        self.assertEqual(jugada_ia(t, "O"), 3)
        t = nuevo()
        for c in range(3):
            soltar(t, c, "X")
        self.assertEqual(jugada_ia(t, "O"), 3)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m conecta4",
    etiquetas=("juego", "conecta 4", "cuatro en linea", "ia", "minimax", "tablero"),
)

# ======================================================================
# sudoku
# ======================================================================
registrar_plantilla(
    "sudoku",
    "Sudoku: solucionador por backtracking con candidatos, generador con solución única y validación de jugadas.",
    "python",
    {
        "sudoku/__init__.py": "",
        "sudoku/motor.py": r'''
import random
from typing import Optional

Tablero = list  # 9x9 de enteros, 0 = vacío


def parsear(texto: str) -> Tablero:
    digitos = [0 if c in ".0" else int(c) for c in texto if c.isdigit() or c == "."]
    if len(digitos) != 81:
        raise ValueError("un sudoku tiene 81 casillas")
    return [digitos[i * 9:(i + 1) * 9] for i in range(9)]


def candidatos(t: Tablero, f: int, c: int) -> set:
    if t[f][c]:
        return set()
    usados = set(t[f]) | {t[i][c] for i in range(9)}
    bf, bc = 3 * (f // 3), 3 * (c // 3)
    usados |= {t[i][j] for i in range(bf, bf + 3) for j in range(bc, bc + 3)}
    return set(range(1, 10)) - usados


def valido(t: Tablero) -> bool:
    for i in range(9):
        fila = [n for n in t[i] if n]
        col = [t[j][i] for j in range(9) if t[j][i]]
        caja = [t[3 * (i // 3) + a][3 * (i % 3) + b] for a in range(3) for b in range(3)
                if t[3 * (i // 3) + a][3 * (i % 3) + b]]
        if any(len(g) != len(set(g)) for g in (fila, col, caja)):
            return False
    return True


def resolver(t: Tablero, contar_hasta: int = 1) -> tuple[Optional[Tablero], int]:
    """Devuelve (una solución, cantidad de soluciones encontradas hasta contar_hasta)."""
    if not valido(t):
        return None, 0
    tablero = [fila[:] for fila in t]
    soluciones = []

    def paso() -> bool:
        mejor, opciones = None, None
        for f in range(9):
            for c in range(9):
                if not tablero[f][c]:
                    cand = candidatos(tablero, f, c)
                    if not cand:
                        return False
                    if opciones is None or len(cand) < len(opciones):
                        mejor, opciones = (f, c), cand
        if mejor is None:
            soluciones.append([fila[:] for fila in tablero])
            return len(soluciones) >= contar_hasta
        f, c = mejor
        for n in sorted(opciones):
            tablero[f][c] = n
            if paso():
                return True
        tablero[f][c] = 0
        return False

    paso()
    return (soluciones[0] if soluciones else None), len(soluciones)


def generar(pistas: int = 30, semilla: Optional[int] = None) -> tuple[Tablero, Tablero]:
    """(sudoku con solución única, solución)."""
    azar = random.Random(semilla)
    base = [[0] * 9 for _ in range(9)]
    for caja in range(0, 9, 3):
        numeros = list(range(1, 10))
        azar.shuffle(numeros)
        for i in range(9):
            base[caja + i // 3][caja + i % 3] = numeros[i]
    solucion, _ = resolver(base)
    sudoku = [fila[:] for fila in solucion]
    casillas = [(f, c) for f in range(9) for c in range(9)]
    azar.shuffle(casillas)
    for f, c in casillas:
        if sum(1 for fila in sudoku for n in fila if n) <= pistas:
            break
        guardado, sudoku[f][c] = sudoku[f][c], 0
        if resolver(sudoku, contar_hasta=2)[1] != 1:
            sudoku[f][c] = guardado
    return sudoku, solucion


def dibujar(t: Tablero) -> str:
    lineas = []
    for f in range(9):
        if f and f % 3 == 0:
            lineas.append("------+-------+------")
        fila = ""
        for c in range(9):
            if c and c % 3 == 0:
                fila += "| "
            fila += (str(t[f][c]) if t[f][c] else ".") + " "
        lineas.append(fila.rstrip())
    return "\n".join(lineas)
''',
        "sudoku/__main__.py": r'''
from sudoku.motor import candidatos, dibujar, generar

sudoku, solucion = generar(32)
while any(0 in fila for fila in sudoku):
    print("\n" + dibujar(sudoku))
    try:
        entrada = input("fila columna número (1-9), o 'ver' para la solución: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if entrada == "ver":
        print(dibujar(solucion))
        break
    try:
        f, c, n = (int(x) - 1 if i < 2 else int(x) for i, x in enumerate(entrada.split()))
        if n not in candidatos(sudoku, f, c):
            print("ese número no va ahí")
        else:
            sudoku[f][c] = n
    except ValueError:
        print("formato: 1 3 7")
''',
        "tests/__init__.py": "",
        "tests/test_sudoku.py": r'''
import unittest

from sudoku.motor import candidatos, dibujar, generar, parsear, resolver, valido

FACIL = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"


class TestSudoku(unittest.TestCase):
    def test_parsear_y_candidatos(self):
        t = parsear(FACIL)
        self.assertEqual(t[0][:2], [5, 3])
        self.assertEqual(candidatos(t, 0, 2), {1, 2, 4})
        with self.assertRaises(ValueError):
            parsear("123")

    def test_resolver(self):
        solucion, n = resolver(parsear(FACIL))
        self.assertEqual(n, 1)
        self.assertTrue(valido(solucion))
        self.assertEqual(solucion[0], [5, 3, 4, 6, 7, 8, 9, 1, 2])

    def test_invalido(self):
        t = parsear(FACIL)
        t[0][2] = 5
        self.assertFalse(valido(t))
        self.assertEqual(resolver(t), (None, 0))

    def test_generar_unico(self):
        sudoku, solucion = generar(32, semilla=4)
        self.assertGreaterEqual(sum(1 for f in sudoku for n in f if n), 32)
        self.assertEqual(resolver(sudoku, contar_hasta=2)[1], 1)
        self.assertEqual(resolver(sudoku)[0], solucion)
        self.assertIn("|", dibujar(sudoku))


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m sudoku",
    etiquetas=("juego", "sudoku", "puzzle", "backtracking", "resolver"),
)

# ======================================================================
# blackjack
# ======================================================================
registrar_plantilla(
    "blackjack",
    "Blackjack (21) en la terminal: mazo con semilla, ases flexibles, crupier que se planta en 17 y apuestas.",
    "python",
    {
        "blackjack/__init__.py": "",
        "blackjack/motor.py": r'''
import random
from dataclasses import dataclass, field
from typing import Optional

PALOS = "♠♥♦♣"
VALORES = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def valor_mano(cartas: list) -> int:
    total = sum(10 if v in "JQK" or v == "10" else (11 if v == "A" else int(v)) for v, _ in cartas)
    ases = sum(1 for v, _ in cartas if v == "A")
    while total > 21 and ases:
        total -= 10
        ases -= 1
    return total


def es_blackjack(cartas: list) -> bool:
    return len(cartas) == 2 and valor_mano(cartas) == 21


@dataclass
class Ronda:
    apuesta: int
    semilla: Optional[int] = None
    mazo: list = field(default_factory=list)
    jugador: list = field(default_factory=list)
    crupier: list = field(default_factory=list)
    terminada: bool = False

    def __post_init__(self):
        if self.apuesta <= 0:
            raise ValueError("la apuesta debe ser positiva")
        if not self.mazo:
            self.mazo = [(v, p) for p in PALOS for v in VALORES]
            random.Random(self.semilla).shuffle(self.mazo)
        self.jugador = [self.mazo.pop(), self.mazo.pop()]
        self.crupier = [self.mazo.pop(), self.mazo.pop()]
        if es_blackjack(self.jugador):
            self.terminada = True

    def pedir(self) -> int:
        if self.terminada:
            raise ValueError("la ronda terminó")
        self.jugador.append(self.mazo.pop())
        total = valor_mano(self.jugador)
        if total >= 21:
            self.terminada = True
        return total

    def plantarse(self) -> None:
        self.terminada = True

    def juega_crupier(self) -> None:
        if valor_mano(self.jugador) > 21:
            return
        while valor_mano(self.crupier) < 17:
            self.crupier.append(self.mazo.pop())

    def resultado(self) -> tuple[str, int]:
        """(texto, ganancia neta)."""
        if not self.terminada:
            raise ValueError("la ronda sigue")
        self.juega_crupier()
        j, c = valor_mano(self.jugador), valor_mano(self.crupier)
        if j > 21:
            return "te pasaste", -self.apuesta
        if es_blackjack(self.jugador) and not es_blackjack(self.crupier):
            return "¡blackjack!", int(self.apuesta * 1.5)
        if c > 21 or j > c:
            return "ganaste", self.apuesta
        if j == c:
            return "empate", 0
        return "ganó la banca", -self.apuesta


def mostrar(cartas: list, ocultar_segunda: bool = False) -> str:
    return " ".join("🂠" if ocultar_segunda and i == 1 else f"{v}{p}" for i, (v, p) in enumerate(cartas))
''',
        "blackjack/__main__.py": r'''
from blackjack.motor import Ronda, mostrar, valor_mano

fichas = 100
while fichas > 0:
    try:
        apuesta = int(input(f"\nFichas: {fichas}. Apuesta (0 sale): ") or 0)
    except (ValueError, EOFError, KeyboardInterrupt):
        break
    if apuesta <= 0 or apuesta > fichas:
        break
    r = Ronda(apuesta)
    while not r.terminada:
        print(f"Crupier: {mostrar(r.crupier, True)}   Vos: {mostrar(r.jugador)} ({valor_mano(r.jugador)})")
        if input("¿(p)edir o (s)plantarse? ").strip().lower().startswith("p"):
            r.pedir()
        else:
            r.plantarse()
    texto, ganancia = r.resultado()
    fichas += ganancia
    print(f"Crupier: {mostrar(r.crupier)} ({valor_mano(r.crupier)})  Vos: {mostrar(r.jugador)} → {texto}")
print(f"Te vas con {fichas} fichas")
''',
        "tests/__init__.py": "",
        "tests/test_blackjack.py": r'''
import unittest

from blackjack.motor import Ronda, es_blackjack, valor_mano


def mano(*valores):
    return [(v, "♠") for v in valores]


class TestBlackjack(unittest.TestCase):
    def test_valores(self):
        self.assertEqual(valor_mano(mano("A", "K")), 21)
        self.assertEqual(valor_mano(mano("A", "A", "9")), 21)
        self.assertEqual(valor_mano(mano("K", "Q", "5")), 25)
        self.assertTrue(es_blackjack(mano("A", "J")))
        self.assertFalse(es_blackjack(mano("7", "7", "7")))

    def test_ronda_controlada(self):
        # El mazo se reparte desde el final: jugador, jugador, crupier, crupier.
        mazo = [("2", "♠"), ("K", "♣"), ("9", "♦"), ("10", "♥"), ("Q", "♠")]
        r = Ronda(10, mazo=mazo[:])
        self.assertEqual(valor_mano(r.jugador), 20)
        self.assertEqual(valor_mano(r.crupier), 19)
        r.plantarse()
        self.assertEqual(r.resultado(), ("ganaste", 10))

    def test_pasarse(self):
        mazo = [("K", "♦"), ("8", "♣"), ("9", "♦"), ("6", "♥"), ("Q", "♠")]
        r = Ronda(10, mazo=mazo[:])
        r.pedir()
        self.assertTrue(r.terminada)
        self.assertEqual(r.resultado(), ("te pasaste", -10))
        with self.assertRaises(ValueError):
            r.pedir()

    def test_crupier_se_planta_en_17(self):
        r = Ronda(10, semilla=5)
        r.plantarse()
        r.juega_crupier()
        self.assertGreaterEqual(valor_mano(r.crupier), 17)
        with self.assertRaises(ValueError):
            Ronda(0)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m blackjack",
    etiquetas=("juego", "blackjack", "cartas", "21", "casino", "naipes"),
)

# ======================================================================
# memoria
# ======================================================================
registrar_plantilla(
    "memoria",
    "Juego de memoria (pares) en la terminal: tablero configurable, intentos, mejor puntaje y emojis.",
    "python",
    {
        "memoria/__init__.py": "",
        "memoria/motor.py": r'''
import random
from typing import Optional

SIMBOLOS = list("🐉🍎🚀🎲🎧🌵🐙🍕⚽🎈🔑🌙")


class Memoria:
    def __init__(self, pares: int = 8, semilla: Optional[int] = None):
        if not 2 <= pares <= len(SIMBOLOS):
            raise ValueError(f"pares entre 2 y {len(SIMBOLOS)}")
        cartas = SIMBOLOS[:pares] * 2
        random.Random(semilla).shuffle(cartas)
        self.cartas = cartas
        self.descubiertas: set = set()
        self.intentos = 0
        self._primera: Optional[int] = None

    def elegir(self, posicion: int) -> Optional[bool]:
        """Primera carta → None. Segunda → True si es par, False si no."""
        if not 0 <= posicion < len(self.cartas):
            raise ValueError("posición inválida")
        if posicion in self.descubiertas or posicion == self._primera:
            raise ValueError("esa carta ya está visible")
        if self._primera is None:
            self._primera = posicion
            return None
        primera, self._primera = self._primera, None
        self.intentos += 1
        if self.cartas[primera] == self.cartas[posicion]:
            self.descubiertas |= {primera, posicion}
            return True
        return False

    @property
    def terminado(self) -> bool:
        return len(self.descubiertas) == len(self.cartas)

    def puntaje(self) -> int:
        pares = len(self.cartas) // 2
        return max(0, 100 - (self.intentos - pares) * 5) if self.terminado else 0

    def dibujar(self, mostrar: tuple = ()) -> str:
        celdas = [self.cartas[i] if i in self.descubiertas or i in mostrar else f"{i:>2}" for i in range(len(self.cartas))]
        return "\n".join(" ".join(celdas[i:i + 4]) for i in range(0, len(celdas), 4))
''',
        "memoria/__main__.py": r'''
import time

from memoria.motor import Memoria

m = Memoria()
while not m.terminado:
    print("\n" + m.dibujar())
    try:
        a = int(input("primera carta: "))
        m.elegir(a)
        print(m.dibujar(mostrar=(a,)))
        b = int(input("segunda carta: "))
        par = m.elegir(b)
        print(m.dibujar(mostrar=(a, b)))
        print("¡Par!" if par else "No...")
        time.sleep(1)
    except ValueError as e:
        print(e)
    except (EOFError, KeyboardInterrupt):
        raise SystemExit
print(f"¡Terminaste en {m.intentos} intentos! Puntaje: {m.puntaje()}")
''',
        "tests/__init__.py": "",
        "tests/test_memoria.py": r'''
import unittest

from memoria.motor import Memoria


class TestMemoria(unittest.TestCase):
    def test_partida_perfecta(self):
        m = Memoria(4, semilla=1)
        posiciones = {}
        for i, simbolo in enumerate(m.cartas):
            posiciones.setdefault(simbolo, []).append(i)
        for a, b in posiciones.values():
            self.assertIsNone(m.elegir(a))
            self.assertTrue(m.elegir(b))
        self.assertTrue(m.terminado)
        self.assertEqual((m.intentos, m.puntaje()), (4, 100))

    def test_fallo_y_errores(self):
        m = Memoria(2, semilla=3)
        distinta = next(i for i in range(1, 4) if m.cartas[i] != m.cartas[0])
        m.elegir(0)
        with self.assertRaises(ValueError):
            m.elegir(0)
        self.assertFalse(m.elegir(distinta))
        with self.assertRaises(ValueError):
            m.elegir(99)
        with self.assertRaises(ValueError):
            Memoria(1)
        self.assertEqual(m.puntaje(), 0)


if __name__ == "__main__":
    unittest.main()
''',
    },
    comando_tests=_PY_TESTS,
    comando_ejecutar="python3 -m memoria",
    etiquetas=("juego", "memoria", "pares", "cartas", "memotest"),
)
