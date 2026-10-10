"""
Disyuntor de modelos (v9, Fase 5): un circuit breaker por modelo.

Si un modelo (o su proveedor) falla varias veces seguidas, abrir el disyuntor lo saca de la rotación por un
rato en vez de seguir gastando reintentos y latencia en algo caído. Se recupera solo: pasado el enfriamiento
entra en modo "medio" (se permite UN intento); si ese intento anda, el disyuntor se cierra; si falla, se
vuelve a abrir.

REAPER Ω §5.2: un modelo ABIERTO se EXCLUYE de la selección durante el enfriamiento (no se "prueba igual
como último recurso": eso era lo que mandaba un saludo a un Groq 404 ya marcado caído). Si TODOS están en
enfriamiento, el cliente devuelve un diagnóstico claro en vez de insistir. Un 404 model_not_found se RETIRA
(cuarentena por ruta/cuenta) hasta que el catálogo/acceso cambie o el modelo responda de nuevo.
"""


class DisyuntorModelos:
    def __init__(self, umbral: int = 3, enfriamiento: float = 45.0,
                 reloj: Callable[[], float] = time.monotonic):
        self.umbral = max(1, int(umbral))
        self.enfriamiento = float(enfriamiento)
        self.reloj = reloj
        self._fallos: collections.Counter = collections.Counter()   # modelo → fallos consecutivos
        self._abierto_hasta: dict = {}                              # modelo → instante de reapertura
        self._retirados: set = set()                               # modelo → retirado (404) hasta que responda
        self._lock = threading.Lock()

    def disponible(self, modelo: str) -> bool:
        """¿Se puede intentar este modelo ahora? (cerrado o medio = sí; abierto/retirado = no)."""
        with self._lock:
            if modelo in self._retirados:
                return False
            hasta = self._abierto_hasta.get(modelo)
            return hasta is None or self.reloj() >= hasta

    def estado(self, modelo: str) -> str:
        with self._lock:
            if modelo in self._retirados:
                return "retirado"
            hasta = self._abierto_hasta.get(modelo)
            if hasta is None:
                return "cerrado"
            return "medio" if self.reloj() >= hasta else "abierto"

    def retirar(self, modelo: str) -> None:
        """Marca un modelo como retirado (p. ej. 404 model_not_found): excluido hasta que vuelva a responder."""
        with self._lock:
            self._retirados.add(modelo)

    def exito(self, modelo: str) -> None:
        with self._lock:
            self._fallos.pop(modelo, None)
            self._abierto_hasta.pop(modelo, None)
            self._retirados.discard(modelo)

    def fallo(self, modelo: str) -> bool:
        """Registra un fallo del modelo; devuelve True si con esto quedó ABIERTO."""
        with self._lock:
            self._fallos[modelo] += 1
            if self._fallos[modelo] >= self.umbral:
                self._abierto_hasta[modelo] = self.reloj() + self.enfriamiento
                return True
            return False

    def ordenar(self, candidatos: Sequence[str]) -> list:
        """Mismos candidatos, pero los disponibles primero y los no-disponibles al final (compatibilidad)."""
        disponibles = [c for c in candidatos if self.disponible(c)]
        resto = [c for c in candidatos if c not in disponibles]
        return disponibles + resto

    def elegibles(self, candidatos: Sequence[str]) -> list:
        """
        Candidatos que se pueden probar AHORA (excluye abiertos en enfriamiento y retirados). Puede quedar
        vacío a propósito: el cliente debe dar un diagnóstico, no insistir contra un modelo caído (Ω §5.2).
        """
        return [c for c in candidatos if self.disponible(c)]

    def resumen(self) -> str:
        with self._lock:
            ahora = self.reloj()
            partes = [f"{m}: retirado" for m in self._retirados]
            for modelo, hasta in self._abierto_hasta.items():
                if modelo in self._retirados:
                    continue
                restante = max(0, hasta - ahora)
                partes.append(f"{modelo}: {'medio' if restante <= 0 else f'abierto {restante:.0f}s'}")
            return "; ".join(partes) or "todos los modelos operativos"
