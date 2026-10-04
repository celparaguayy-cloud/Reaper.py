"""Soluciones de referencia de las tareas originales de /evaluar (validan que sus tests ocultos sean correctos)."""

solucion_eval("fizzbuzz", {"fizz.py": """
    def fizzbuzz(n):
        salida = []
        for i in range(1, n + 1):
            if "7" in str(i):
                salida.append("Siete")
            elif i % 15 == 0:
                salida.append("FizzBuzz")
            elif i % 3 == 0:
                salida.append("Fizz")
            elif i % 5 == 0:
                salida.append("Buzz")
            else:
                salida.append(str(i))
        return salida
"""})

solucion_eval("palindromo", {"texto.py": """
    import unicodedata

    def _normalizar(frase):
        letras = []
        for c in frase.lower():
            if c == "ñ":
                letras.append(c)
                continue
            base = unicodedata.normalize("NFKD", c)[0]
            if base.isalnum():
                letras.append(base)
        return "".join(letras)

    def es_palindromo(frase):
        t = _normalizar(frase)
        return bool(t) and t == t[::-1]
"""})

solucion_eval("duracion", {"tiempo.py": """
    import re

    UNIDADES = {"h": 3600, "m": 60, "s": 1}

    def parsear_duracion(texto):
        t = (texto or "").lower().replace(" ", "")
        if not t or not re.fullmatch(r"(\\d+[hms])+", t):
            raise ValueError(f"duración inválida: {texto!r}")
        return sum(int(n) * UNIDADES[u] for n, u in re.findall(r"(\\d+)([hms])", t))

    def formatear_duracion(segundos):
        if segundos == 0:
            return "0s"
        h, resto = divmod(segundos, 3600)
        m, s = divmod(resto, 60)
        return "".join(f"{v}{u}" for v, u in ((h, "h"), (m, "m"), (s, "s")) if v)
"""})

solucion_eval("estadisticas", {"estadistica.py": """
    from collections import Counter

    def _validar(datos):
        if not datos:
            raise ValueError("lista vacía")

    def media(datos):
        _validar(datos)
        return sum(datos) / len(datos)

    def mediana(datos):
        _validar(datos)
        orden = sorted(datos)
        mitad = len(orden) // 2
        return orden[mitad] if len(orden) % 2 else (orden[mitad - 1] + orden[mitad]) / 2

    def modas(datos):
        _validar(datos)
        conteo = Counter(datos)
        maximo = max(conteo.values())
        return sorted(v for v, n in conteo.items() if n == maximo)
"""})

solucion_eval("pila", {"estructuras.py": """
    class Pila:
        def __init__(self, capacidad=None):
            self._datos = []
            self.capacidad = capacidad

        def apilar(self, x):
            if self.capacidad is not None and len(self._datos) >= self.capacidad:
                raise OverflowError("pila llena")
            self._datos.append(x)

        def desapilar(self):
            if not self._datos:
                raise IndexError("pila vacía")
            return self._datos.pop()

        def tope(self):
            if not self._datos:
                raise IndexError("pila vacía")
            return self._datos[-1]

        def esta_vacia(self):
            return not self._datos

        def __len__(self):
            return len(self._datos)
"""})

solucion_eval("romanos", SOLUCIONES_EVAL["romanos_canonicos"])

solucion_eval("bug-descuento", {"tienda.py": """
    def precio_final(precio_unitario, cantidad):
        if cantidad <= 0:
            raise ValueError("cantidad inválida")
        total = precio_unitario * cantidad
        if cantidad > 50:
            total = total * 0.8
        elif cantidad >= 10:
            total = total * 0.9
        return round(total, 2)
"""})

solucion_eval("agregar-funcion", {"geometria.py": """
    import math


    def _positivos(*medidas):
        if any(m < 0 for m in medidas):
            raise ValueError("las medidas no pueden ser negativas")


    def area_rectangulo(base, altura):
        _positivos(base, altura)
        return base * altura


    def area_circulo(radio):
        _positivos(radio)
        return math.pi * radio ** 2


    def perimetro_rectangulo(base, altura):
        _positivos(base, altura)
        return 2 * (base + altura)


    def hipotenusa(a, b):
        _positivos(a, b)
        return math.hypot(a, b)
"""})

solucion_eval("config-json", {"config.py": """
    import json
    from pathlib import Path

    DEFECTO = {"idioma": "es", "tema": "oscuro", "volumen": 5}

    def cargar_config(ruta):
        config = dict(DEFECTO)
        try:
            datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
            if isinstance(datos, dict):
                config.update(datos)
        except (OSError, ValueError):
            pass
        try:
            config["volumen"] = max(0, min(10, int(config["volumen"])))
        except (TypeError, ValueError):
            config["volumen"] = DEFECTO["volumen"]
        return config

    def guardar_config(ruta, config):
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
"""})

solucion_eval("ventas-csv", {"ventas.py": """
    import csv
    from collections import defaultdict

    def resumen_ventas(ruta_csv):
        por_producto = defaultdict(float)
        unidades = defaultdict(int)
        with open(ruta_csv, newline="", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                try:
                    cantidad = int(fila["cantidad"])
                    precio = float(fila["precio"])
                except (KeyError, TypeError, ValueError):
                    continue
                por_producto[fila["producto"]] += cantidad * precio
                unidades[fila["producto"]] += cantidad
        por_producto = {k: round(v, 2) for k, v in por_producto.items()}
        return {
            "total": round(sum(por_producto.values()), 2),
            "por_producto": por_producto,
            "mas_vendido": max(unidades, key=unidades.get) if unidades else None,
        }
"""})

solucion_eval("matriz", {"matriz.py": """
    def transponer(m):
        return [list(f) for f in zip(*m)]

    def rotar_derecha(m):
        return [list(f) for f in zip(*m[::-1])]

    def multiplicar(a, b):
        if not a or not b or len(a[0]) != len(b):
            raise ValueError("dimensiones incompatibles")
        return [[sum(x * y for x, y in zip(fila, col)) for col in zip(*b)] for fila in a]
"""})

solucion_eval("cuenta-bancaria", {"banco.py": """
    class Cuenta:
        def __init__(self, titular, saldo_inicial=0):
            self.titular = titular
            self._saldo = saldo_inicial
            self.historial = []

        @property
        def saldo(self):
            return self._saldo

        @staticmethod
        def _validar(monto):
            if monto <= 0:
                raise ValueError("el monto debe ser positivo")

        def depositar(self, monto):
            self._validar(monto)
            self._saldo += monto
            self.historial.append(("deposito", monto))

        def extraer(self, monto):
            self._validar(monto)
            if monto > self._saldo:
                raise ValueError("saldo insuficiente")
            self._saldo -= monto
            self.historial.append(("extraccion", monto))

        def transferir(self, destino, monto):
            self._validar(monto)
            if monto > self._saldo:
                raise ValueError("saldo insuficiente")
            self._saldo -= monto
            destino._saldo += monto
            self.historial.append(("transferencia_enviada", monto))
            destino.historial.append(("transferencia_recibida", monto))
"""})
