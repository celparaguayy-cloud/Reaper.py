"""
Memoria de desempeño + router aprendido (v9, Fase 7): el RoleAllocator del MASTER SPEC.

"Las IAs proponen, la evidencia decide": en vez de clavar un modelo por rol a mano, REAPER recuerda cómo le
fue a cada modelo en cada rol (éxitos/fracasos verificados por herramientas) y, la próxima vez, elige para
ese rol el modelo con mejor historial. A un modelo sin datos se le da una prior optimista para que se lo
pruebe (exploración); así el default configurado se sigue usando hasta que haya evidencia de que otro rinde
más. Persiste en un JSON global (desempeno.json); las claves son ids de modelo ya resueltos.
"""


class MemoriaDesempeno:
    def __init__(self, ruta: Optional[Path] = None, prior: float = 0.6):
        self.ruta = Path(ruta) if ruta else DESEMPENO_FILE
        self.prior = prior                 # puntaje de un modelo sin datos (optimista: fomenta explorar)
        self._lock = threading.Lock()

    def _cargar(self) -> dict:
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def _guardar(self, datos: dict) -> None:
        try:
            escritura_atomica(self.ruta, json.dumps(datos, ensure_ascii=False, indent=1))
        except OSError:
            pass

    def registrar(self, rol: str, modelo: str, exito: bool, *, verificado: bool = False, pasos: int = 0) -> None:
        if not rol or not modelo:
            return
        modelo = resolver_modelo(modelo)
        with self._lock:
            datos = self._cargar()
            roles = datos.setdefault("roles", {})
            porrol = roles.setdefault(rol, {})
            fila = porrol.setdefault(modelo, {"exitos": 0, "fallos": 0, "verificados": 0, "pasos": 0, "usos": 0})
            fila["usos"] += 1
            fila["pasos"] += int(pasos)
            if exito:
                fila["exitos"] += 1
                if verificado:
                    fila["verificados"] += 1
            else:
                fila["fallos"] += 1
            datos["actualizado"] = datetime.now().isoformat(timespec="seconds")
            self._guardar(datos)

    def _fila(self, datos: dict, rol: str, modelo: str) -> Optional[dict]:
        return datos.get("roles", {}).get(rol, {}).get(resolver_modelo(modelo))

    def puntaje(self, rol: str, modelo: str, datos: Optional[dict] = None) -> float:
        """Tasa de éxito suavizada (Laplace) con un pequeño bono por resultados verificados. Sin datos → prior."""
        fila = self._fila(datos if datos is not None else self._cargar(), rol, modelo)
        if not fila:
            return self.prior
        exitos, fallos = fila["exitos"], fila["fallos"]
        total = exitos + fallos
        if total == 0:
            return self.prior
        base = (exitos + 1) / (total + 2)                          # Laplace
        bono = 0.1 * (fila.get("verificados", 0) / total)          # premia la verificación real
        return round(min(1.0, base + bono), 4)

    def elegir(self, rol: str, candidatos: Sequence[str], excluir: Iterable[str] = ()) -> Optional[str]:
        """Mejor candidato para el rol según el historial. Empata a favor del primero (el default configurado)."""
        lista = [c for c in candidatos if c]
        if not lista:
            return None
        fuera = {resolver_modelo(e) for e in excluir}
        permitidos = [c for c in lista if resolver_modelo(c) not in fuera] or lista
        datos = self._cargar()
        mejor, mejor_p = permitidos[0], self.puntaje(rol, permitidos[0], datos)
        for c in permitidos[1:]:
            p = self.puntaje(rol, c, datos)
            if p > mejor_p + 1e-9:          # estrictamente mejor: ante empate gana el primero (estable)
                mejor, mejor_p = c, p
        return mejor

    def resumen(self, rol: Optional[str] = None) -> str:
        datos = self._cargar().get("roles", {})
        if not datos:
            return "Sin datos de desempeño todavía."
        lineas = []
        for r in sorted(datos):
            if rol and r != rol:
                continue
            filas = datos[r]
            orden = sorted(filas, key=lambda m: self.puntaje(r, m), reverse=True)
            partes = [f"{m} {self.puntaje(r, m):.0%} ({filas[m]['exitos']}/{filas[m]['exitos'] + filas[m]['fallos']})"
                      for m in orden[:5]]
            lineas.append(f"{r}: " + ", ".join(partes))
        return "\n".join(lineas) or "Sin datos de desempeño todavía."
