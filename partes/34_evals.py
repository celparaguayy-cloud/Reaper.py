"""
Benchmark /evaluar: tareas reales con tests ocultos para medir al modelo.

Cada tarea arranca en una carpeta temporal con algunos archivos, REAPER
recibe el pedido (que nombra los módulos y funciones esperados) y trabaja
solo. Al terminar se agregan los tests OCULTOS y se corren. Así se compara
Venice contra otros modelos, o el agente simple contra el torneo, con datos.

    python3 reaper_v8.py --evaluar        todas las tareas
    python3 reaper_v8.py --evaluar 5      las primeras 5
    /evaluar 3                            desde el REPL
"""


@dataclass
class TareaEval:
    id: str
    titulo: str
    pedido: str
    tests: dict
    archivos: dict = field(default_factory=dict)
    dificultad: int = 1
    comando_tests: str = ""          # vacío = unittest de Python
    requiere: tuple = ()             # ejecutables necesarios (node, go...)
    lenguaje: str = "python"

    def disponible(self) -> bool:
        return all(shutil.which(r) for r in self.requiere)


TAREAS_EVAL: list[TareaEval] = []


def tarea_eval(id_: str, titulo: str, pedido: str, tests: dict, archivos: Optional[dict] = None,
               dificultad: int = 1, comando_tests: str = "", requiere: Sequence[str] = (),
               lenguaje: str = "python") -> None:
    TAREAS_EVAL.append(TareaEval(id_, titulo, textwrap.dedent(pedido).strip(),
                                 {k: textwrap.dedent(v).lstrip("\n") for k, v in tests.items()},
                                 {k: textwrap.dedent(v).lstrip("\n") for k, v in (archivos or {}).items()},
                                 dificultad, comando_tests, tuple(requiere), lenguaje))


tarea_eval("fizzbuzz", "FizzBuzz con reglas", """
    Creá fizz.py con la función fizzbuzz(n: int) -> list[str] que devuelve los textos del 1 al n:
    múltiplos de 3 → "Fizz", de 5 → "Buzz", de ambos → "FizzBuzz", y si el número contiene el dígito 7 → "Siete"
    (esta regla tiene prioridad). Si n < 1 devuelve lista vacía.
""", {"tests/test_fizz.py": """
    import unittest
    from fizz import fizzbuzz

    class T(unittest.TestCase):
        def test_basico(self):
            self.assertEqual(fizzbuzz(5), ["1", "2", "Fizz", "4", "Buzz"])
        def test_quince(self):
            self.assertEqual(fizzbuzz(15)[-1], "FizzBuzz")
        def test_siete(self):
            r = fizzbuzz(27)
            self.assertEqual(r[6], "Siete")
            self.assertEqual(r[26], "Siete")
            self.assertEqual(r[16], "Siete")
            self.assertEqual(r[20], "Fizz")
        def test_vacio(self):
            self.assertEqual(fizzbuzz(0), [])
"""})

tarea_eval("palindromo", "Palíndromos con tildes", """
    Creá texto.py con es_palindromo(frase: str) -> bool que ignore mayúsculas, espacios, signos de puntuación
    y tildes (á→a, ñ se mantiene como ñ). Una cadena vacía o sin letras devuelve False.
""", {"tests/test_texto.py": """
    import unittest
    from texto import es_palindromo

    class T(unittest.TestCase):
        def test_si(self):
            self.assertTrue(es_palindromo("Anita lava la tina"))
            self.assertTrue(es_palindromo("¿Acaso hubo búhos acá?"))
        def test_no(self):
            self.assertFalse(es_palindromo("Hola mundo"))
        def test_vacio(self):
            self.assertFalse(es_palindromo(""))
            self.assertFalse(es_palindromo("¡!"))
"""})

tarea_eval("duracion", "Parsear duraciones", """
    Creá tiempo.py con parsear_duracion(texto: str) -> int que convierte textos como "1h30m", "45s", "2h",
    "1h 5m 10s" o "90m" a segundos. Acepta mayúsculas y espacios. Si el formato es inválido (vacío, unidades
    desconocidas, números negativos) lanza ValueError. También formatear_duracion(segundos: int) -> str que
    devuelve el formato más corto sin ceros: 5400 → "1h30m", 45 → "45s", 0 → "0s".
""", {"tests/test_tiempo.py": """
    import unittest
    from tiempo import formatear_duracion, parsear_duracion

    class T(unittest.TestCase):
        def test_parsear(self):
            self.assertEqual(parsear_duracion("1h30m"), 5400)
            self.assertEqual(parsear_duracion("1H 5m 10S"), 3910)
            self.assertEqual(parsear_duracion("90m"), 5400)
        def test_invalido(self):
            for malo in ("", "abc", "10x", "-5m"):
                with self.assertRaises(ValueError):
                    parsear_duracion(malo)
        def test_formatear(self):
            self.assertEqual(formatear_duracion(5400), "1h30m")
            self.assertEqual(formatear_duracion(3661), "1h1m1s")
            self.assertEqual(formatear_duracion(0), "0s")
"""}, dificultad=2)

tarea_eval("estadisticas", "Estadísticas sin statistics", """
    Creá estadistica.py SIN importar el módulo statistics, con: media(datos), mediana(datos) y modas(datos)
    (lista ordenada de los valores más frecuentes). Todas lanzan ValueError si la lista está vacía.
""", {"tests/test_estadistica.py": """
    import unittest
    import estadistica as e

    class T(unittest.TestCase):
        def test_media(self):
            self.assertAlmostEqual(e.media([1, 2, 3, 4]), 2.5)
        def test_mediana(self):
            self.assertEqual(e.mediana([3, 1, 2]), 2)
            self.assertEqual(e.mediana([4, 1, 3, 2]), 2.5)
        def test_modas(self):
            self.assertEqual(e.modas([1, 2, 2, 3, 3]), [2, 3])
        def test_vacio(self):
            for f in (e.media, e.mediana, e.modas):
                with self.assertRaises(ValueError):
                    f([])
        def test_sin_statistics(self):
            import inspect
            self.assertNotIn("import statistics", inspect.getsource(e))
"""})

tarea_eval("pila", "Clase Pila", """
    Creá estructuras.py con la clase Pila: apilar(x), desapilar() (lanza IndexError "pila vacía" si está vacía),
    tope() (igual que desapilar pero sin sacar), esta_vacia() y len(pila) con __len__. Opcional capacidad máxima
    en el constructor: Pila(capacidad=3) lanza OverflowError al superar la capacidad.
""", {"tests/test_pila.py": """
    import unittest
    from estructuras import Pila

    class T(unittest.TestCase):
        def test_lifo(self):
            p = Pila()
            p.apilar(1); p.apilar(2)
            self.assertEqual(p.tope(), 2)
            self.assertEqual(p.desapilar(), 2)
            self.assertEqual(len(p), 1)
        def test_vacia(self):
            p = Pila()
            self.assertTrue(p.esta_vacia())
            with self.assertRaises(IndexError):
                p.desapilar()
            with self.assertRaises(IndexError):
                p.tope()
        def test_capacidad(self):
            p = Pila(capacidad=1)
            p.apilar("a")
            with self.assertRaises(OverflowError):
                p.apilar("b")
"""})

tarea_eval("romanos", "Números romanos", """
    Creá romanos.py con a_romano(n: int) -> str (1 a 3999) y desde_romano(texto: str) -> int.
    Fuera de rango o romano inválido (como "IIII", "VX" o letras desconocidas) → ValueError.
""", {"tests/test_romanos.py": """
    import unittest
    from romanos import a_romano, desde_romano

    class T(unittest.TestCase):
        def test_ida(self):
            self.assertEqual(a_romano(1994), "MCMXCIV")
            self.assertEqual(a_romano(3999), "MMMCMXCIX")
        def test_vuelta(self):
            self.assertEqual(desde_romano("MCMXCIV"), 1994)
            self.assertEqual(desde_romano("xlii"), 42)
        def test_todos(self):
            for n in range(1, 400):
                self.assertEqual(desde_romano(a_romano(n)), n)
        def test_errores(self):
            for malo in (0, 4000):
                with self.assertRaises(ValueError):
                    a_romano(malo)
            for malo in ("IIII", "VX", "ABC", ""):
                with self.assertRaises(ValueError):
                    desde_romano(malo)
"""}, dificultad=2)

tarea_eval("bug-descuento", "Arreglar un bug existente", """
    Los clientes se quejan de que el descuento por cantidad de tienda.py no se aplica bien: comprando
    exactamente 10 unidades no se aplica el 10% y con más de 50 debería ser 20%. Encontrá y arreglá el bug
    sin cambiar la firma de precio_final(precio_unitario, cantidad).
""", {"tests/test_tienda.py": """
    import unittest
    from tienda import precio_final

    class T(unittest.TestCase):
        def test_sin_descuento(self):
            self.assertEqual(precio_final(10, 9), 90)
        def test_diez(self):
            self.assertEqual(precio_final(10, 10), 90)
        def test_cincuenta_y_uno(self):
            self.assertEqual(precio_final(10, 51), 408)
        def test_invalido(self):
            with self.assertRaises(ValueError):
                precio_final(10, 0)
"""}, archivos={"tienda.py": """
    def precio_final(precio_unitario, cantidad):
        if cantidad <= 0:
            raise ValueError("cantidad inválida")
        total = precio_unitario * cantidad
        if cantidad > 10:
            total = total * 0.9
        elif cantidad > 50:
            total = total * 0.8
        return round(total, 2)
"""})

tarea_eval("agregar-funcion", "Extender un módulo sin romperlo", """
    En geometria.py ya existen area_rectangulo y area_circulo. Agregá perimetro_rectangulo(base, altura) y
    hipotenusa(a, b). Todas deben lanzar ValueError con medidas negativas (las existentes todavía no lo hacen:
    agregalo también). No cambies los nombres existentes.
""", {"tests/test_geometria.py": """
    import math
    import unittest
    from geometria import area_circulo, area_rectangulo, hipotenusa, perimetro_rectangulo

    class T(unittest.TestCase):
        def test_existentes(self):
            self.assertEqual(area_rectangulo(2, 3), 6)
            self.assertAlmostEqual(area_circulo(1), math.pi)
        def test_nuevas(self):
            self.assertEqual(perimetro_rectangulo(2, 3), 10)
            self.assertEqual(hipotenusa(3, 4), 5)
        def test_negativos(self):
            for f, args in ((area_rectangulo, (-1, 2)), (area_circulo, (-1,)), (perimetro_rectangulo, (1, -2)),
                            (hipotenusa, (-3, 4))):
                with self.assertRaises(ValueError):
                    f(*args)
"""}, archivos={"geometria.py": """
    import math


    def area_rectangulo(base, altura):
        return base * altura


    def area_circulo(radio):
        return math.pi * radio ** 2
"""})

tarea_eval("config-json", "Config con valores por defecto", """
    Creá config.py con cargar_config(ruta) -> dict: lee un JSON y lo combina con los valores por defecto
    {"idioma": "es", "tema": "oscuro", "volumen": 5}. Si el archivo no existe o tiene JSON inválido devuelve los
    valores por defecto (sin lanzar excepción). "volumen" fuera de 0..10 se corrige al límite más cercano.
    Y guardar_config(ruta, config) que escribe el JSON con indentación (creando la carpeta si falta).
""", {"tests/test_config.py": """
    import json
    import tempfile
    import unittest
    from pathlib import Path
    from config import cargar_config, guardar_config

    class T(unittest.TestCase):
        def test_defecto(self):
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(cargar_config(Path(tmp) / "no.json")["tema"], "oscuro")
        def test_mezcla_y_limite(self):
            with tempfile.TemporaryDirectory() as tmp:
                ruta = Path(tmp) / "c.json"
                ruta.write_text(json.dumps({"tema": "claro", "volumen": 50}))
                c = cargar_config(ruta)
                self.assertEqual((c["tema"], c["volumen"], c["idioma"]), ("claro", 10, "es"))
        def test_invalido(self):
            with tempfile.TemporaryDirectory() as tmp:
                ruta = Path(tmp) / "c.json"
                ruta.write_text("{malo")
                self.assertEqual(cargar_config(ruta)["volumen"], 5)
        def test_guardar(self):
            with tempfile.TemporaryDirectory() as tmp:
                ruta = Path(tmp) / "sub" / "c.json"
                guardar_config(ruta, {"idioma": "en"})
                self.assertEqual(cargar_config(ruta)["idioma"], "en")
"""})

tarea_eval("ventas-csv", "Resumen de ventas desde CSV", """
    Creá ventas.py con resumen_ventas(ruta_csv) -> dict que lee un CSV con columnas producto,cantidad,precio
    y devuelve {"total": total_facturado, "por_producto": {producto: total}, "mas_vendido": producto con más
    unidades}. Las filas con cantidad o precio inválidos se ignoran. Redondeá los montos a 2 decimales.
""", {"tests/test_ventas.py": """
    import tempfile
    import unittest
    from pathlib import Path
    from ventas import resumen_ventas

    class T(unittest.TestCase):
        def test_resumen(self):
            with tempfile.TemporaryDirectory() as tmp:
                ruta = Path(tmp) / "v.csv"
                ruta.write_text("producto,cantidad,precio\\npan,2,1.5\\nleche,1,2.25\\npan,3,1.5\\nmalo,x,1\\n")
                r = resumen_ventas(ruta)
                self.assertEqual(r["total"], 9.75)
                self.assertEqual(r["por_producto"], {"pan": 7.5, "leche": 2.25})
                self.assertEqual(r["mas_vendido"], "pan")
"""}, dificultad=2)

tarea_eval("matriz", "Operaciones con matrices", """
    Creá matriz.py (sin numpy) con transponer(m), rotar_derecha(m) (90° horario), y multiplicar(a, b) que lanza
    ValueError si las dimensiones no son compatibles. Las matrices son listas de listas; no modifiques la entrada.
""", {"tests/test_matriz.py": """
    import unittest
    from matriz import multiplicar, rotar_derecha, transponer

    class T(unittest.TestCase):
        def test_transponer(self):
            self.assertEqual(transponer([[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]])
        def test_rotar(self):
            m = [[1, 2], [3, 4]]
            self.assertEqual(rotar_derecha(m), [[3, 1], [4, 2]])
            self.assertEqual(m, [[1, 2], [3, 4]])
        def test_multiplicar(self):
            self.assertEqual(multiplicar([[1, 2], [3, 4]], [[5], [6]]), [[17], [39]])
            with self.assertRaises(ValueError):
                multiplicar([[1, 2]], [[1, 2]])
"""})

tarea_eval("cuenta-bancaria", "Cuenta bancaria con historial", """
    Creá banco.py con la clase Cuenta(titular, saldo_inicial=0): depositar(monto), extraer(monto) (no puede
    quedar saldo negativo: lanza ValueError "saldo insuficiente"), transferir(destino, monto), saldo (propiedad
    de solo lectura) e historial (lista de tuplas (tipo, monto) con tipos "deposito", "extraccion",
    "transferencia_enviada", "transferencia_recibida"). Montos <= 0 → ValueError.
""", {"tests/test_banco.py": """
    import unittest
    from banco import Cuenta

    class T(unittest.TestCase):
        def test_operaciones(self):
            a, b = Cuenta("Ana", 100), Cuenta("Beto")
            a.depositar(50)
            a.extraer(30)
            a.transferir(b, 20)
            self.assertEqual((a.saldo, b.saldo), (100, 20))
            self.assertEqual(a.historial[-1], ("transferencia_enviada", 20))
            self.assertEqual(b.historial, [("transferencia_recibida", 20)])
        def test_errores(self):
            c = Cuenta("Ana", 10)
            with self.assertRaises(ValueError):
                c.extraer(11)
            with self.assertRaises(ValueError):
                c.depositar(0)
            with self.assertRaises(AttributeError):
                c.saldo = 999
            self.assertEqual(c.saldo, 10)
"""}, dificultad=2)


@dataclass
class ResultadoEval:
    tarea: TareaEval
    ok: bool
    conteo: ConteoTests
    pasos: int
    segundos: float
    error: str = ""


def correr_tarea_eval(tarea: TareaEval, llm, settings: Settings, ui: UI, modo: str = "agente") -> ResultadoEval:
    inicio = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"reaper_eval_{tarea.id}_") as tmp:
        raiz = Path(tmp) / tarea.id
        raiz.mkdir()
        for rel, contenido in tarea.archivos.items():
            escritura_atomica(raiz / rel, contenido)
        ws = Workspace(raiz, checkpoints_dir=Path(tmp) / "_ck")
        pasos, error = 0, ""
        silenciosa = UI(silencioso=True, interactivo=False)
        try:
            if modo == "torneo":
                resultado = Torneo(llm, ws, settings, silenciosa).correr(tarea.pedido, n=max(2, settings.candidatos))
                pasos = sum(c.resultado.pasos for c in resultado.candidatos if c.resultado)
            else:
                res = Agente("principal", llm, ws, settings, silenciosa, etiqueta=f"eval:{tarea.id}",
                             mostrar_progreso=False, memoria=None).ejecutar(tarea.pedido)
                pasos = res.pasos
        except LLMError as e:
            error = str(e)
        except Exception as e:  # una tarea rota no corta el benchmark
            error = f"{type(e).__name__}: {e}"
        for rel, contenido in tarea.tests.items():
            escritura_atomica(raiz / rel, contenido)
        comando = comando_portable(tarea.comando_tests) if tarea.comando_tests else \
            f"{shlex.quote(sys.executable)} -m unittest discover -s tests"
        r = ejecutar(comando, cwd=raiz, timeout=settings.tests_timeout, shell=True)
        conteo = contar_tests(r.stdout + r.stderr, r.codigo)
        return ResultadoEval(tarea, r.ok and not error, conteo, pasos, time.monotonic() - inicio, error)


def correr_evaluacion(llm, settings: Settings, ui: UI, cantidad: Optional[int] = None, modo: str = "agente",
                      ids: Sequence[str] = ()) -> bool:
    tareas = [t for t in TAREAS_EVAL if (not ids or t.id in ids or t.lenguaje in ids) and t.disponible()]
    if cantidad:
        tareas = tareas[:cantidad]
    if not tareas:
        ui.aviso("No hay tareas de evaluación que coincidan.")
        return False
    ajustes = Settings.desde_dict({**settings.to_dict(), "modo": "auto", "max_pasos": min(settings.max_pasos, 25)})
    ui.titulo(f"EVALUACIÓN · {len(tareas)} tareas · modelo {ajustes.modelo.split('/')[-1]} · modo {modo}")
    resultados = []
    for i, tarea in enumerate(tareas, start=1):
        ui.info(f"[{i}/{len(tareas)}] {tarea.titulo}…")
        res = correr_tarea_eval(tarea, llm, ajustes, ui, modo)
        resultados.append(res)
        (ui.ok if res.ok else ui.error)(f"{tarea.titulo}: {res.conteo.texto()} · {res.pasos} pasos · "
                                        f"{formatear_duracion(res.segundos)}" + (f" · {res.error}" if res.error else ""))
    aprobadas = sum(1 for r in resultados if r.ok)
    puntos = sum(r.conteo.pasados for r in resultados)
    totales = sum(r.conteo.ejecutados for r in resultados) or 1
    ui.tabla([[r.tarea.id, "✓" if r.ok else "✗", r.conteo.texto(), str(r.pasos), formatear_duracion(r.segundos)]
              for r in resultados], ["tarea", "", "tests", "pasos", "tiempo"], "lllrr")
    ui.caja([f"tareas resueltas: {aprobadas}/{len(resultados)} ({100 * aprobadas // len(resultados)}%)",
             f"tests pasados: {puntos}/{totales} ({100 * puntos // totales}%)",
             f"uso: {llm.uso.resumen()}"], titulo="RESULTADO")
    try:
        carpeta = BASE_DIR / "evals"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"eval_{datetime.now():%Y%m%d_%H%M%S}.json"
        ruta.write_text(json.dumps({
            "modelo": ajustes.modelo, "modo": modo, "fecha": datetime.now().isoformat(timespec="seconds"),
            "resueltas": aprobadas, "total": len(resultados),
            "tareas": [{"id": r.tarea.id, "ok": r.ok, "pasados": r.conteo.pasados, "ejecutados": r.conteo.ejecutados,
                        "pasos": r.pasos, "segundos": round(r.segundos, 1), "error": r.error} for r in resultados],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        ui.tenue(f"  guardado en {ruta}")
    except OSError:
        pass
    return aprobadas == len(resultados)
