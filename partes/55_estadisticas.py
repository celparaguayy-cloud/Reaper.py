"""
Estadísticas persistentes de uso: pedidos, builds, torneos, escaladas, tokens y costo por día.

Sirven para ver con datos si un perfil o un modelo rinde mejor (tasa de builds
verificadas, pasos promedio, costo por build) y cuánto se gasta.
"""

CAMPOS_DIA = ("pedidos", "pedidos_ok", "builds", "builds_ok", "torneos", "escaladas", "lecciones",
              "tokens_entrada", "tokens_salida", "llamadas", "segundos")


class Estadisticas:
    def __init__(self, ruta: Optional[Path] = None):
        self.ruta = ruta or ESTADISTICAS_FILE
        self._lock = threading.Lock()
        self._ultimo_uso = (0, 0, 0, 0.0)

    def _cargar(self) -> dict:
        try:
            datos = json.loads(Path(self.ruta).read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def _guardar(self, datos: dict) -> None:
        try:
            escritura_atomica(Path(self.ruta), json.dumps(datos, ensure_ascii=False, indent=1))
        except OSError:
            pass

    def _dia(self, datos: dict, fecha: Optional[str] = None) -> dict:
        dias = datos.setdefault("dias", {})
        clave = fecha or datetime.now().strftime("%Y-%m-%d")
        dia = dias.setdefault(clave, {})
        for campo in CAMPOS_DIA:
            dia.setdefault(campo, 0)
        dia.setdefault("costo", 0.0)
        dia.setdefault("modelos", {})
        return dia

    def registrar(self, **incrementos) -> None:
        with self._lock:
            datos = self._cargar()
            dia = self._dia(datos, incrementos.pop("fecha", None))
            modelo = incrementos.pop("modelo", None)
            for clave, valor in incrementos.items():
                if clave in dia and isinstance(valor, (int, float)):
                    dia[clave] = round(dia[clave] + valor, 6) if isinstance(dia[clave], float) else dia[clave] + valor
            if modelo:
                dia["modelos"][modelo] = dia["modelos"].get(modelo, 0) + 1
            datos["actualizado"] = datetime.now().isoformat(timespec="seconds")
            self._guardar(datos)

    def registrar_uso(self, uso: Uso, modelo: str = "") -> None:
        """Suma lo que el cliente LLM gastó desde la última vez."""
        actual = (uso.llamadas, uso.tokens_entrada, uso.tokens_salida, uso.costo)
        previo = self._ultimo_uso
        delta = [a - b for a, b in zip(actual, previo)]
        self._ultimo_uso = actual
        if not any(delta):
            return
        with self._lock:
            datos = self._cargar()
            dia = self._dia(datos)
            dia["llamadas"] += int(delta[0])
            dia["tokens_entrada"] += int(delta[1])
            dia["tokens_salida"] += int(delta[2])
            dia["costo"] = round(dia["costo"] + float(delta[3]), 6)
            if modelo:
                dia["modelos"][modelo] = dia["modelos"].get(modelo, 0) + int(delta[0])
            self._guardar(datos)

    def dias(self, cantidad: int = 14) -> list[tuple[str, dict]]:
        datos = self._cargar().get("dias", {})
        return sorted(datos.items())[-cantidad:]

    def totales(self) -> dict:
        total = {campo: 0 for campo in CAMPOS_DIA}
        total["costo"] = 0.0
        for _fecha, dia in self._cargar().get("dias", {}).items():
            for campo in total:
                total[campo] += dia.get(campo, 0)
        return total


def tasa(ok: int, total: int) -> str:
    return f"{100 * ok // total}%" if total else "-"


def mostrar_estadisticas(ui: UI, est: Estadisticas, cantidad: int = 14) -> None:
    dias = est.dias(cantidad)
    if not dias:
        ui.tenue("Todavía no hay estadísticas (se juntan solas mientras usás REAPER).")
        return
    filas = []
    for fecha, d in dias:
        filas.append([fecha, f"{d.get('pedidos_ok', 0)}/{d.get('pedidos', 0)}", f"{d.get('builds_ok', 0)}/{d.get('builds', 0)}",
                      str(d.get("torneos", 0)), str(d.get("escaladas", 0)), formatear_numero(d.get("tokens_entrada", 0)),
                      formatear_numero(d.get("tokens_salida", 0)), f"${d.get('costo', 0):.3f}" if d.get("costo") else "-"])
    ui.tabla(filas, ["día", "pedidos", "builds", "torneos", "escal.", "entrada", "salida", "costo"], "lrrrrrrr")
    t = est.totales()
    ui.caja([f"pedidos resueltos: {t['pedidos_ok']}/{t['pedidos']} ({tasa(t['pedidos_ok'], t['pedidos'])})",
             f"builds verificadas: {t['builds_ok']}/{t['builds']} ({tasa(t['builds_ok'], t['builds'])})",
             f"torneos: {t['torneos']} · escaladas: {t['escaladas']} · lecciones: {t['lecciones']}",
             f"tokens: {formatear_numero(t['tokens_entrada'])} entrada / {formatear_numero(t['tokens_salida'])} salida"
             + (f" · costo total ${t['costo']:.3f}" if t["costo"] else "")], titulo="TOTALES")
