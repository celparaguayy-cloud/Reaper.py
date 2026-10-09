"""
LoopBreaker (v9, Fase 4): corta bucles IMPRODUCTIVOS que el detector de llamadas idénticas NO ve.

El detector de part 20 bloquea repetir una llamada idéntica mientras el estado no cambia. Pero un modelo
chico cae en bucles más sutiles que SÍ cambian el estado cada vuelta:
  - OSCILACIÓN: edita A, lo revierte, lo vuelve a editar igual → el workspace vuelve a un estado ya visto.
  - MACHAQUE: retoca el MISMO archivo/símbolo una y otra vez sin que la verificación mejore.
  - ERROR_ESTANCADO: la misma firma de error reaparece pese a los cambios (lo que prueba no ataca la causa).

El RompedorDeBucles no bloquea por su cuenta: devuelve un VEREDICTO que el agente le muestra al modelo (y
cuenta como tropiezo) para que cambie de enfoque o active el modo forense. Cada veredicto se avisa UNA sola
vez por objetivo, para no convertirse él mismo en ruido repetido.
"""


@dataclass
class VeredictoBucle:
    tipo: str            # OSCILACION | MACHAQUE | ERROR_ESTANCADO
    objetivo: str
    veces: int
    detalle: str

    def nota(self) -> str:
        return f"⚠ REAPER detectó un BUCLE ({self.tipo}): {self.detalle}"


class RompedorDeBucles:
    def __init__(self, umbral_machaque: int = 4, umbral_error: int = 3, ventana: int = 16):
        self.umbral_machaque = umbral_machaque
        self.umbral_error = umbral_error
        self.ventana = ventana
        self.estados: list = []                       # huellas de estado tras escrituras (oscilación)
        self.ediciones: collections.Counter = collections.Counter()   # objetivo → veces editado
        self.errores: collections.Counter = collections.Counter()      # (objetivo, firma) → veces
        self._ultimo_estado: Optional[str] = None
        self._avisados: set = set()                   # (tipo, clave) ya avisados: no repetir el mismo aviso

    def _primera_vez(self, tipo: str, clave: str) -> bool:
        if (tipo, clave) in self._avisados:
            return False
        self._avisados.add((tipo, clave))
        return True

    def registrar_estado(self, huella: str) -> Optional[VeredictoBucle]:
        """Tras una escritura: si este estado ya se vio antes (y no es el inmediato anterior) → oscilación."""
        if not huella or huella == self._ultimo_estado:
            self._ultimo_estado = huella or self._ultimo_estado
            return None
        repetido = huella in self.estados
        self.estados.append(huella)
        if len(self.estados) > self.ventana:
            self.estados = self.estados[-self.ventana:]
        self._ultimo_estado = huella
        if repetido and self._primera_vez("OSCILACION", huella):
            return VeredictoBucle(
                "OSCILACION", "", 2,
                "el workspace volvió a un estado por el que ya habías pasado: estás deshaciendo y rehaciendo lo "
                "mismo. Pará ese ida y vuelta: el arreglo no está donde venís tocando. Entendé la causa raíz "
                "(leé el error real, mirá otro archivo) o activá el modo forense antes de seguir editando.")
        return None

    def registrar_edicion(self, objetivo: str) -> Optional[VeredictoBucle]:
        """Cuenta una edición exitosa sobre un objetivo (ruta o símbolo)."""
        if not objetivo:
            return None
        self.ediciones[objetivo] += 1
        veces = self.ediciones[objetivo]
        if veces >= self.umbral_machaque and self._primera_vez("MACHAQUE", objetivo):
            return VeredictoBucle(
                "MACHAQUE", objetivo, veces,
                f"editaste '{objetivo}' {veces} veces y el problema sigue. Dejá de retocar el mismo lugar a ciegas: "
                "leé el error COMPLETO, formulá una hipótesis concreta de la causa y hacé UN cambio pensado; si no "
                "sale, pedí un diagnóstico (consultor) o activá el modo forense en vez de seguir probando.")
        return None

    def registrar_error(self, objetivo: str, firma: str) -> Optional[VeredictoBucle]:
        """Cuenta una firma de error sobre un objetivo; si se repite, el enfoque no ataca la causa."""
        if not firma:
            return None
        clave = (objetivo or "?", firma)
        self.errores[clave] += 1
        veces = self.errores[clave]
        if veces >= self.umbral_error and self._primera_vez("ERROR_ESTANCADO", f"{objetivo}:{firma}"):
            return VeredictoBucle(
                "ERROR_ESTANCADO", objetivo or "?", veces,
                f"el mismo error reaparece {veces} veces sobre '{objetivo or 'el proyecto'}' pese a tus cambios. "
                "Lo que estás probando no toca la causa real: cambiá de hipótesis, mirá el problema desde otro "
                "ángulo o activá el modo forense; no repitas la misma clase de arreglo.")
        return None
