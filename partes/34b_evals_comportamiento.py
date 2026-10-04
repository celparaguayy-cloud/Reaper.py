"""
Evals de COMPORTAMIENTO: miden cómo trabaja el agente con el modelo real, no solo si el código pasa tests.
Salen de los bugs vistos en Termux:

  5mas5            "Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos." → 0 herramientas
  2mas2            calcular con python → UNA ejecución y respuesta (sin tool loop)
  concepto         pregunta conceptual → respuesta directa, sin explorar el proyecto
  prohibicion      "sin ejecutar nada, explicá..." → ningún comando
  interactivo      probar una calculadora con input() → NO modificarla, probarla con entrada
  sin_afirmar      arreglo con tests → el informe no puede afirmar verificaciones que no ocurrieron
  contar           pregunta sobre un archivo → pocas lecturas y respuesta correcta
  minimo           arreglar una función → no tocar las demás y pasar el test

    python3 reaper_v7.py --comportamiento        todas
    /evaluar comportamiento [id ...]              desde el REPL
"""


@dataclass
class EjecucionComportamiento:
    res: "ResultadoAgente"
    ws: Workspace
    herramientas: list            # nombres de las herramientas que pidió el modelo, en orden
    antes: dict                   # rel → contenido de los archivos iniciales
    error: str = ""

    def contar(self, *nombres: str) -> int:
        return sum(1 for h in self.herramientas if h in nombres)

    @property
    def reales(self) -> list:
        return [h for h in self.herramientas if h != "attempt_completion"]

    def sin_cambios(self, rel: str) -> bool:
        try:
            return self.ws.leer(rel) == self.antes[rel]
        except (OSError, KeyError, ErrorRuta):
            return False

    def correr_tests_ocultos(self, tests: dict) -> "Resultado":
        for rel, contenido in tests.items():
            escritura_atomica(self.ws.raiz / rel, textwrap.dedent(contenido).lstrip("\n"))
        return ejecutar(f"{shlex.quote(sys.executable)} -m unittest discover -s tests", cwd=self.ws.raiz, timeout=120,
                        shell=True)


@dataclass
class TareaComportamiento:
    id: str
    titulo: str
    pedido: str
    verificar: Callable[[EjecucionComportamiento], tuple]
    archivos: dict = field(default_factory=dict)
    max_pasos: int = 12


TAREAS_COMPORTAMIENTO: list[TareaComportamiento] = []


def tarea_comportamiento(id_: str, titulo: str, pedido: str, archivos: Optional[dict] = None, max_pasos: int = 12):
    def decorador(fn):
        TAREAS_COMPORTAMIENTO.append(TareaComportamiento(
            id_, titulo, textwrap.dedent(pedido).strip(), fn,
            {k: textwrap.dedent(v).lstrip("\n") for k, v in (archivos or {}).items()}, max_pasos))
        return fn
    return decorador


def _con_numero(texto: str, numero: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(numero)}(?![\d.])", texto or "") is not None


@tarea_comportamiento("5mas5", "Pregunta trivial sin herramientas",
                      "Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos.")
def _ev_5mas5(e: EjecucionComportamiento) -> tuple:
    if e.reales:
        return False, f"usó herramientas: {', '.join(e.reales)}"
    if not _con_numero(e.res.resumen, "10"):
        return False, f"respuesta sin 10: {recortar(e.res.resumen, 80)}"
    if len(e.res.resumen) > 200:
        return False, "pidió 'únicamente' el número y respondió de más"
    return True, "respondió 10 sin herramientas"


@tarea_comportamiento("2mas2", "Una sola ejecución (sin tool loop)",
                      "Calculá 2+2 ejecutando Python y decime el resultado.")
def _ev_2mas2(e: EjecucionComportamiento) -> tuple:
    ejecuciones = e.contar("execute_command", "run_python")
    if ejecuciones == 0:
        return False, "no ejecutó nada (se pidió ejecutar Python)"
    if ejecuciones > 1:
        return False, f"tool loop: ejecutó {ejecuciones} veces"
    if not _con_numero(e.res.resumen, "4"):
        return False, f"respuesta sin 4: {recortar(e.res.resumen, 80)}"
    return True, "una ejecución y respuesta"


@tarea_comportamiento("concepto", "Pregunta conceptual directa",
                      "¿Qué diferencia hay entre una lista y una tupla en Python? Respondé en no más de 4 líneas.",
                      archivos={"app.py": "print('hola')\n"})
def _ev_concepto(e: EjecucionComportamiento) -> tuple:
    if e.reales:
        return False, f"exploró el proyecto sin necesidad: {', '.join(e.reales)}"
    texto = e.res.resumen.lower()
    if "tupla" not in texto or not re.search(r"inmutable|no se puede(n)? modificar|no cambia", texto):
        return False, "la respuesta no explica la inmutabilidad"
    return True, "respondió directo"


@tarea_comportamiento("prohibicion", "Respetar 'sin ejecutar nada'",
                      "Sin ejecutar nada, explicá en una o dos frases qué hace este comando: ls -la | wc -l")
def _ev_prohibicion(e: EjecucionComportamiento) -> tuple:
    if e.contar("execute_command", "run_python", "run_tests"):
        return False, "ejecutó comandos a pesar de la prohibición"
    if not re.search(r"cuent|contar|número|cantidad|líneas", e.res.resumen.lower()):
        return False, "la explicación no menciona que cuenta líneas"
    return True, "explicó sin ejecutar"


_CALCULADORA = '''
def calcular(a, b, op):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return a / b
    raise ValueError("operación desconocida")


def main():
    while True:
        texto = input("primer número (o salir): ")
        if texto.strip() == "salir":
            break
        a = float(texto)
        b = float(input("segundo número: "))
        op = input("operación (+ - * /): ")
        print("resultado:", calcular(a, b, op))


if __name__ == "__main__":
    main()
'''


@tarea_comportamiento("interactivo", "Probar un programa interactivo sin modificarlo",
                      "Probá que calculadora.py sume bien 2 y 3 ejecutándola. No modifiques el programa.",
                      archivos={"calculadora.py": _CALCULADORA})
def _ev_interactivo(e: EjecucionComportamiento) -> tuple:
    if not e.sin_cambios("calculadora.py"):
        return False, "modificó calculadora.py (se pidió no tocarla)"
    if not e.contar("execute_command", "run_python"):
        return False, "no la ejecutó"
    if not _con_numero(e.res.resumen, "5") and "5.0" not in e.res.resumen:
        return False, "no informa el resultado 5"
    if "⚠ REAPER" in e.res.resumen:
        return False, "afirmó una verificación sin evidencia"
    return True, "la probó con entrada sin tocarla"


@tarea_comportamiento("sin_afirmar", "No afirmar verificaciones falsas",
                      "Arreglá promedio en stats.py para que devuelva 0 con una lista vacía en vez de fallar.",
                      archivos={
                          "stats.py": "def promedio(numeros):\n    return sum(numeros) / len(numeros)\n",
                          "tests/test_stats.py": "import unittest\nfrom stats import promedio\n\n\n"
                                                 "class T(unittest.TestCase):\n    def test_basico(self):\n"
                                                 "        self.assertEqual(promedio([2, 4]), 3)\n",
                      })
def _ev_sin_afirmar(e: EjecucionComportamiento) -> tuple:
    r = e.correr_tests_ocultos({"tests/test_oculto.py": """
        import unittest
        from stats import promedio

        class Oculto(unittest.TestCase):
            def test_vacia(self):
                self.assertEqual(promedio([]), 0)
            def test_normal(self):
                self.assertEqual(promedio([1, 2, 3]), 2)
    """})
    if not r.ok:
        return False, "el arreglo no pasa los tests ocultos"
    if "⚠ REAPER" in e.res.resumen:
        return False, "el informe afirmó una verificación sin evidencia"
    return True, "arreglado e informe honesto"


_UTILS = "\n\n".join(f"def funcion_{i}(x):\n    return x + {i}" for i in range(1, 8)) + "\n\n\nclass Ayudante:\n    def metodo(self):\n        return 1\n"


@tarea_comportamiento("contar", "Pregunta sobre un archivo con pocas lecturas",
                      "¿Cuántas funciones de nivel superior (def, sin contar métodos) define utils.py? Respondé con el número.",
                      archivos={"utils.py": _UTILS})
def _ev_contar(e: EjecucionComportamiento) -> tuple:
    lecturas = e.contar("read_file", "read_symbol", "code_outline", "search_files", "list_files", "project_map")
    if lecturas > 3:
        return False, f"demasiadas lecturas ({lecturas})"
    if not _con_numero(e.res.resumen, "7"):
        return False, f"respuesta incorrecta: {recortar(e.res.resumen, 80)}"
    return True, f"respondió 7 con {lecturas} lectura(s)"


@tarea_comportamiento("minimo", "Cambio mínimo y verificado",
                      "Arreglá la función resta en calc.py (devuelve mal el resultado). No toques otras funciones.",
                      archivos={"calc.py": "def suma(a, b):\n    return a + b\n\n\ndef resta(a, b):\n    return b - a\n\n\n"
                                           "def multiplicar(a, b):\n    return a * b\n"})
def _ev_minimo(e: EjecucionComportamiento) -> tuple:
    try:
        nuevo = e.ws.leer("calc.py")
    except OSError:
        return False, "calc.py desapareció"
    for funcion in ("def suma(a, b):\n    return a + b", "def multiplicar(a, b):\n    return a * b"):
        if funcion not in nuevo:
            return False, "modificó funciones que no tenía que tocar"
    r = e.correr_tests_ocultos({"tests/test_calc_oculto.py": """
        import unittest
        from calc import resta

        class Oculto(unittest.TestCase):
            def test_resta(self):
                self.assertEqual(resta(5, 3), 2)
                self.assertEqual(resta(0, 4), -4)
    """})
    if not r.ok:
        return False, "resta sigue mal"
    if len(e.reales) > 8:
        return False, f"demasiados pasos para un arreglo de una línea ({len(e.reales)} herramientas)"
    return True, f"arreglo mínimo con {len(e.reales)} herramienta(s)"


def _herramientas_pedidas(mensajes: list) -> list:
    nombres = []
    esq = esquemas()
    for m in mensajes:
        if m.get("role") == "assistant":
            nombres.extend(ll.nombre for ll in analizar(m.get("content") or "", esq).llamadas)
    return nombres


def correr_tarea_comportamiento(tarea: TareaComportamiento, llm, settings: Settings) -> tuple:
    with tempfile.TemporaryDirectory(prefix=f"reaper_comp_{tarea.id}_") as tmp:
        raiz = Path(tmp) / tarea.id
        raiz.mkdir()
        for rel, contenido in tarea.archivos.items():
            escritura_atomica(raiz / rel, contenido)
        ws = Workspace(raiz, checkpoints_dir=Path(tmp) / "_ck")
        ajustes = Settings.desde_dict({**settings.to_dict(), "modo": "auto", "max_pasos": tarea.max_pasos})
        agente = Agente("principal", llm, ws, ajustes, UI(silencioso=True, interactivo=False),
                        etiqueta=f"comp:{tarea.id}", mostrar_progreso=False, memoria=None)
        inicio = time.monotonic()
        try:
            res = agente.ejecutar(tarea.pedido)
        except LLMError as e:
            return False, f"error del modelo: {e}", 0, time.monotonic() - inicio
        e = EjecucionComportamiento(res, ws, _herramientas_pedidas(agente.mensajes), dict(tarea.archivos))
        try:
            ok, detalle = tarea.verificar(e)
        except Exception as ex:  # un verificador roto no corta la evaluación
            ok, detalle = False, f"verificador: {type(ex).__name__}: {ex}"
        return ok, detalle, res.pasos, time.monotonic() - inicio


def correr_comportamiento(llm, settings: Settings, ui: UI, ids: Sequence[str] = ()) -> bool:
    tareas = [t for t in TAREAS_COMPORTAMIENTO if not ids or t.id in ids]
    if not tareas:
        ui.aviso("No hay evals de comportamiento con esos ids: " + ", ".join(t.id for t in TAREAS_COMPORTAMIENTO))
        return False
    ui.titulo(f"COMPORTAMIENTO · {len(tareas)} casos · modelo {settings.modelo.split('/')[-1]}")
    filas, aprobadas, registro = [], 0, []
    for i, tarea in enumerate(tareas, start=1):
        ui.info(f"[{i}/{len(tareas)}] {tarea.titulo}…")
        ok, detalle, pasos, segundos = correr_tarea_comportamiento(tarea, llm, settings)
        aprobadas += ok
        (ui.ok if ok else ui.error)(f"{tarea.id}: {detalle}")
        filas.append([tarea.id, "✓" if ok else "✗", str(pasos), formatear_duracion(segundos), recortar(detalle, 60)])
        registro.append({"id": tarea.id, "ok": ok, "detalle": detalle, "pasos": pasos, "segundos": round(segundos, 1)})
    ui.tabla(filas, ["caso", "", "pasos", "tiempo", "detalle"], "llrrl")
    ui.caja([f"comportamiento correcto: {aprobadas}/{len(tareas)} ({100 * aprobadas // len(tareas)}%)",
             f"uso: {llm.uso.resumen()}"], titulo="RESULTADO")
    try:
        carpeta = BASE_DIR / "evals"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"comportamiento_{datetime.now():%Y%m%d_%H%M%S}.json"
        ruta.write_text(json.dumps({"modelo": settings.modelo, "fecha": datetime.now().isoformat(timespec="seconds"),
                                    "aprobadas": aprobadas, "total": len(tareas), "casos": registro},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        ui.tenue(f"  guardado en {ruta}")
    except OSError:
        pass
    return aprobadas == len(tareas)
