"""
Estimación de tokens y presupuesto de contexto.

Venice 24B tiene 32k tokens de contexto. Sin tokenizer real, REAPER estima
con una heurística calibrada para código y español (≈3 caracteres por token
en código, ≈3.6 en prosa). Es conservadora a propósito: es preferible
compactar un poco antes que recibir un 400 por contexto excedido.
"""

CARACTERES_POR_TOKEN = 3.0
_RE_PALABRA = re.compile(r"\w+|[^\w\s]", re.U)


def estimar_tokens(texto: str) -> int:
    """Estimación rápida: mezcla longitud en caracteres y cantidad de piezas léxicas."""
    if not texto:
        return 0
    caracteres = len(texto)
    if caracteres > 200_000:
        return int(caracteres / CARACTERES_POR_TOKEN)
    piezas = len(_RE_PALABRA.findall(texto))
    # Las piezas cortas (símbolos de código) suelen ser 1 token; las palabras largas, 2 o más.
    por_caracteres = caracteres / CARACTERES_POR_TOKEN
    por_piezas = piezas * 1.15
    return int(max(por_caracteres, por_piezas) * 0.92 + 4)


def tokens_mensajes(mensajes: Sequence[dict]) -> int:
    return sum(estimar_tokens(m.get("content", "")) + 4 for m in mensajes) + 2


@dataclass
class Presupuesto:
    """Reparto del contexto entre system prompt, historial y respuesta."""

    contexto: int
    respuesta: int
    margen: float = 0.12

    @property
    def entrada_maxima(self) -> int:
        return max(1024, int((self.contexto - self.respuesta) * (1 - self.margen)))

    def caracteres_maximos(self) -> int:
        return int(self.entrada_maxima * CARACTERES_POR_TOKEN)

    def cabe(self, mensajes: Sequence[dict]) -> bool:
        return tokens_mensajes(mensajes) <= self.entrada_maxima

    def respuesta_posible(self, mensajes: Sequence[dict]) -> int:
        """Cuántos tokens de respuesta quedan disponibles para estos mensajes."""
        libre = int(self.contexto * (1 - self.margen / 2)) - tokens_mensajes(mensajes)
        return max(256, min(self.respuesta, libre))


def recortar_a_tokens(texto: str, tokens: int, marca: str = "\n...[recortado]...\n") -> str:
    if estimar_tokens(texto) <= tokens:
        return texto
    limite = int(tokens * CARACTERES_POR_TOKEN)
    return recortar(texto, max(200, limite - len(marca)))
