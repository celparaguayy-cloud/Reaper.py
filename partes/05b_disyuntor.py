"""
Disyuntor de modelos (v9, Fase 5): un circuit breaker por modelo.

Si un modelo (o su proveedor) falla varias veces seguidas, abrir el disyuntor lo saca de la rotación por un
rato en vez de seguir gastando reintentos y latencia en algo caído. Se recupera solo: pasado el enfriamiento
entra en modo "medio" (se permite UN intento); si ese intento anda, el disyuntor se cierra; si falla, se
vuelve a abrir. Nunca deja al cliente sin candidatos: un modelo abierto se usa igual como último recurso.
"""


class DisyuntorModelos:
    def __init__(self, umbral: int = 3, enfriamiento: float = 45.0,
                 reloj: Callable[[], float] = time.monotonic):
        self.umbral = max(1, int(umbral))
        self.enfriamiento = float(enfriamiento)
        self.reloj = reloj
        self._fallos: collections.Counter = collections.Counter()   # modelo → fallos consecutivos
        self._abierto_hasta: dict = {}                              # modelo → instante de reapertura
        self._lock = threading.Lock()

    def disponible(self, modelo: str) -> bool:
        """¿Se puede intentar este modelo ahora? (cerrado o medio = sí; abierto en enfriamiento = no)."""
        with self._lock:
            hasta = self._abierto_hasta.get(modelo)
            return hasta is None or self.reloj() >= hasta

    def estado(self, modelo: str) -> str:
        with self._lock:
            hasta = self._abierto_hasta.get(modelo)
            if hasta is None:
                return "cerrado"
            return "medio" if self.reloj() >= hasta else "abierto"

    def exito(self, modelo: str) -> None:
        with self._lock:
            self._fallos.pop(modelo, None)
            self._abierto_hasta.pop(modelo, None)

    def fallo(self, modelo: str) -> bool:
        """Registra un fallo del modelo; devuelve True si con esto quedó ABIERTO."""
        with self._lock:
            self._fallos[modelo] += 1
            if self._fallos[modelo] >= self.umbral:
                self._abierto_hasta[modelo] = self.reloj() + self.enfriamiento
                return True
            return False

    def ordenar(self, candidatos: Sequence[str]) -> list:
        """Mismos candidatos, pero los disponibles primero y los abiertos al final (nunca se descartan)."""
        disponibles = [c for c in candidatos if self.disponible(c)]
        abiertos = [c for c in candidatos if c not in disponibles]
        return disponibles + abiertos

    def resumen(self) -> str:
        with self._lock:
            if not self._abierto_hasta:
                return "todos los modelos operativos"
            ahora = self.reloj()
            partes = []
            for modelo, hasta in self._abierto_hasta.items():
                restante = max(0, hasta - ahora)
                partes.append(f"{modelo}: {'medio' if restante <= 0 else f'abierto {restante:.0f}s'}")
            return "; ".join(partes)
