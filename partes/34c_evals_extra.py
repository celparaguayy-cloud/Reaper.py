"""
Más tareas para /evaluar (Python, JavaScript y Go). Cada una trae su SOLUCIÓN DE REFERENCIA en
SOLUCIONES_EVAL: el autotest corre los tests ocultos contra esa solución, así un test mal escrito se
detecta antes de usarlo para juzgar a un modelo (ya pasó una vez con FizzBuzz).
"""

SOLUCIONES_EVAL: dict[str, dict] = {}


def solucion_eval(id_: str, archivos: dict) -> None:
    SOLUCIONES_EVAL[id_] = {k: textwrap.dedent(v).lstrip("\n") for k, v in archivos.items()}


# ======================================================================== PYTHON
tarea_eval("cuit", "Validar CUIT argentino", """
    Creá cuit.py con:
    - validar_cuit(texto: str) -> bool: acepta "20-12345678-6", "20123456786" o con espacios; verifica que tenga
      11 dígitos, un prefijo válido (20, 23, 24, 27, 30, 33, 34) y el dígito verificador (módulo 11 con los
      pesos 5,4,3,2,7,6,5,4,3,2; si el resultado es 11 el dígito es 0 y si es 10 el CUIT es inválido).
    - formatear_cuit(texto: str) -> str: devuelve "XX-XXXXXXXX-X" o lanza ValueError si no es válido.
""", {"tests/test_cuit.py": """
    import unittest
    from cuit import formatear_cuit, validar_cuit

    class T(unittest.TestCase):
        def test_validos(self):
            for c in ("20-12345678-6", "20123456786", " 20 12345678 6 ", "30-71234567-1"):
                self.assertTrue(validar_cuit(c), c)
        def test_invalidos(self):
            for c in ("20-12345678-5", "99-12345678-6", "2012345678", "abc", "", "20-12345678-60"):
                self.assertFalse(validar_cuit(c), c)
        def test_formatear(self):
            self.assertEqual(formatear_cuit("20123456786"), "20-12345678-6")
            with self.assertRaises(ValueError):
                formatear_cuit("20123456785")
"""}, dificultad=2)
solucion_eval("cuit", {"cuit.py": """
    import re
    PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    PREFIJOS = {"20", "23", "24", "27", "30", "33", "34"}

    def _digitos(texto):
        return re.sub(r"[\\s-]", "", texto or "")

    def validar_cuit(texto):
        d = _digitos(texto)
        if not re.fullmatch(r"\\d{11}", d) or d[:2] not in PREFIJOS:
            return False
        resto = 11 - sum(int(x) * p for x, p in zip(d[:10], PESOS)) % 11
        if resto == 10:
            return False
        return (0 if resto == 11 else resto) == int(d[10])

    def formatear_cuit(texto):
        if not validar_cuit(texto):
            raise ValueError("CUIT inválido")
        d = _digitos(texto)
        return f"{d[:2]}-{d[2:10]}-{d[10]}"
"""})

tarea_eval("romanos_canonicos", "Números romanos ida y vuelta", """
    Creá romanos.py con a_romano(n: int) -> str (1 a 3999, si no ValueError) y desde_romano(texto: str) -> int que
    acepta mayúsculas o minúsculas y lanza ValueError si el número romano no es canónico (ej. "IIII", "VX", "IC").
""", {"tests/test_romanos.py": """
    import unittest
    from romanos import a_romano, desde_romano

    class T(unittest.TestCase):
        def test_a_romano(self):
            self.assertEqual(a_romano(1994), "MCMXCIV")
            self.assertEqual(a_romano(3999), "MMMCMXCIX")
            self.assertEqual(a_romano(4), "IV")
        def test_desde_romano(self):
            self.assertEqual(desde_romano("mcmxciv"), 1994)
            self.assertEqual(desde_romano("XL"), 40)
        def test_ida_y_vuelta(self):
            for n in range(1, 4000, 37):
                self.assertEqual(desde_romano(a_romano(n)), n)
        def test_invalidos(self):
            for malo in (0, 4000, -1):
                with self.assertRaises(ValueError):
                    a_romano(malo)
            for malo in ("IIII", "VX", "IC", "", "ABC"):
                with self.assertRaises(ValueError):
                    desde_romano(malo)
"""}, dificultad=2)
solucion_eval("romanos_canonicos", {"romanos.py": """
    VALORES = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
               (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]

    def a_romano(n):
        if not isinstance(n, int) or not 1 <= n <= 3999:
            raise ValueError("fuera de rango")
        salida = ""
        for valor, letras in VALORES:
            while n >= valor:
                salida += letras
                n -= valor
        return salida

    def desde_romano(texto):
        t = (texto or "").upper()
        mapa = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        if not t or any(c not in mapa for c in t):
            raise ValueError("número romano inválido")
        total = 0
        for i, c in enumerate(t):
            v = mapa[c]
            total += -v if i + 1 < len(t) and mapa[t[i + 1]] > v else v
        if not 1 <= total <= 3999 or a_romano(total) != t:
            raise ValueError("número romano no canónico")
        return total
"""})

tarea_eval("lru", "Caché LRU", """
    Creá cache.py con la clase CacheLRU(capacidad: int) (capacidad < 1 → ValueError) con:
    obtener(clave, defecto=None), guardar(clave, valor), __len__, __contains__ y la propiedad estadisticas que
    devuelve {"aciertos": int, "fallos": int}. Al superar la capacidad se descarta el usado hace más tiempo
    (leer o guardar cuenta como uso).
""", {"tests/test_cache.py": """
    import unittest
    from cache import CacheLRU

    class T(unittest.TestCase):
        def test_descarta_el_menos_usado(self):
            c = CacheLRU(2)
            c.guardar("a", 1); c.guardar("b", 2)
            c.obtener("a")
            c.guardar("c", 3)
            self.assertIn("a", c)
            self.assertNotIn("b", c)
            self.assertEqual(len(c), 2)
        def test_actualizar_cuenta_como_uso(self):
            c = CacheLRU(2)
            c.guardar("a", 1); c.guardar("b", 2); c.guardar("a", 10); c.guardar("c", 3)
            self.assertEqual(c.obtener("a"), 10)
            self.assertIsNone(c.obtener("b"))
        def test_estadisticas_y_defecto(self):
            c = CacheLRU(1)
            c.guardar("x", 1)
            c.obtener("x"); c.obtener("y"); self.assertEqual(c.obtener("z", 0), 0)
            self.assertEqual(c.estadisticas, {"aciertos": 1, "fallos": 2})
        def test_capacidad_invalida(self):
            with self.assertRaises(ValueError):
                CacheLRU(0)
"""})
solucion_eval("lru", {"cache.py": """
    from collections import OrderedDict

    class CacheLRU:
        def __init__(self, capacidad):
            if capacidad < 1:
                raise ValueError("capacidad inválida")
            self.capacidad = capacidad
            self._datos = OrderedDict()
            self._aciertos = 0
            self._fallos = 0

        def obtener(self, clave, defecto=None):
            if clave in self._datos:
                self._datos.move_to_end(clave)
                self._aciertos += 1
                return self._datos[clave]
            self._fallos += 1
            return defecto

        def guardar(self, clave, valor):
            self._datos[clave] = valor
            self._datos.move_to_end(clave)
            while len(self._datos) > self.capacidad:
                self._datos.popitem(last=False)

        def __len__(self):
            return len(self._datos)

        def __contains__(self, clave):
            return clave in self._datos

        @property
        def estadisticas(self):
            return {"aciertos": self._aciertos, "fallos": self._fallos}
"""})

tarea_eval("merge", "Fusionar configuraciones anidadas", """
    Creá config.py con fusionar(base: dict, extra: dict) -> dict que devuelve un dict NUEVO (sin modificar los
    originales): los dicts anidados se fusionan recursivamente, las listas y demás valores de extra reemplazan
    a los de base, y una clave con valor None en extra BORRA esa clave del resultado.
""", {"tests/test_config.py": """
    import copy
    import unittest
    from config import fusionar

    class T(unittest.TestCase):
        def test_anidado(self):
            base = {"db": {"host": "x", "puerto": 1}, "debug": False, "tags": [1]}
            extra = {"db": {"puerto": 2}, "tags": [2, 3]}
            self.assertEqual(fusionar(base, extra), {"db": {"host": "x", "puerto": 2}, "debug": False, "tags": [2, 3]})
        def test_none_borra(self):
            self.assertEqual(fusionar({"a": 1, "b": {"c": 1, "d": 2}}, {"a": None, "b": {"d": None}}), {"b": {"c": 1}})
        def test_no_modifica_originales(self):
            base = {"a": {"b": [1]}}
            extra = {"a": {"c": 2}}
            copia_base, copia_extra = copy.deepcopy(base), copy.deepcopy(extra)
            r = fusionar(base, extra)
            r["a"]["b"].append(9)
            self.assertEqual((base, extra), (copia_base, copia_extra))
        def test_dict_reemplaza_valor_simple(self):
            self.assertEqual(fusionar({"a": 1}, {"a": {"x": 1}}), {"a": {"x": 1}})
"""}, dificultad=2)
solucion_eval("merge", {"config.py": """
    import copy

    def fusionar(base, extra):
        resultado = copy.deepcopy(base)
        for clave, valor in extra.items():
            if valor is None:
                resultado.pop(clave, None)
            elif isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
                resultado[clave] = fusionar(resultado[clave], valor)
            else:
                resultado[clave] = copy.deepcopy(valor)
        return resultado
"""})

tarea_eval("matriz_ops", "Operaciones con matrices", """
    Creá matriz.py (sin numpy) con: transponer(m), multiplicar(a, b) (ValueError si las dimensiones no son
    compatibles) y determinante(m) (ValueError si no es cuadrada; usar expansión por cofactores o eliminación).
    Las matrices son listas de listas de números.
""", {"tests/test_matriz.py": """
    import unittest
    from matriz import determinante, multiplicar, transponer

    class T(unittest.TestCase):
        def test_transponer(self):
            self.assertEqual(transponer([[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]])
        def test_multiplicar(self):
            self.assertEqual(multiplicar([[1, 2], [3, 4]], [[5, 6], [7, 8]]), [[19, 22], [43, 50]])
            with self.assertRaises(ValueError):
                multiplicar([[1, 2]], [[1, 2]])
        def test_determinante(self):
            self.assertEqual(determinante([[4]]), 4)
            self.assertEqual(determinante([[1, 2], [3, 4]]), -2)
            self.assertEqual(determinante([[6, 1, 1], [4, -2, 5], [2, 8, 7]]), -306)
            with self.assertRaises(ValueError):
                determinante([[1, 2, 3], [4, 5, 6]])
"""})
solucion_eval("matriz_ops", {"matriz.py": """
    def transponer(m):
        return [list(f) for f in zip(*m)]

    def multiplicar(a, b):
        if not a or not b or len(a[0]) != len(b):
            raise ValueError("dimensiones incompatibles")
        return [[sum(x * y for x, y in zip(fila, col)) for col in zip(*b)] for fila in a]

    def determinante(m):
        n = len(m)
        if any(len(f) != n for f in m):
            raise ValueError("la matriz no es cuadrada")
        if n == 1:
            return m[0][0]
        if n == 2:
            return m[0][0] * m[1][1] - m[0][1] * m[1][0]
        return sum((-1) ** j * m[0][j] * determinante([f[:j] + f[j + 1:] for f in m[1:]]) for j in range(n))
"""})

tarea_eval("urls", "Parsear y armar query strings", """
    Creá urls.py con:
    - parsear_query(url: str) -> dict[str, list[str]]: los parámetros de la URL (decodificados, se repiten si
      aparecen varias veces; "?a" sin valor da {"a": [""]}).
    - agregar_parametros(url: str, **params) -> str: agrega o reemplaza parámetros y conserva el resto de la
      URL (esquema, host, ruta y #fragmento). Un valor None quita el parámetro.
""", {"tests/test_urls.py": """
    import unittest
    from urls import agregar_parametros, parsear_query

    class T(unittest.TestCase):
        def test_parsear(self):
            self.assertEqual(parsear_query("https://x.com/b?q=mate+cocido&t=1&t=2&v"),
                             {"q": ["mate cocido"], "t": ["1", "2"], "v": [""]})
            self.assertEqual(parsear_query("https://x.com"), {})
        def test_agregar(self):
            self.assertEqual(agregar_parametros("https://x.com/b?a=1#arriba", b="2 3"), "https://x.com/b?a=1&b=2+3#arriba")
            self.assertEqual(agregar_parametros("https://x.com/?a=1&b=2", a="9"), "https://x.com/?a=9&b=2")
            self.assertEqual(agregar_parametros("https://x.com/?a=1&b=2", a=None), "https://x.com/?b=2")
"""}, dificultad=2)
solucion_eval("urls", {"urls.py": """
    from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

    def parsear_query(url):
        return parse_qs(urlsplit(url).query, keep_blank_values=True)

    def agregar_parametros(url, **params):
        partes = urlsplit(url)
        actuales = parse_qs(partes.query, keep_blank_values=True)
        pares = {k: v[-1] for k, v in actuales.items()}
        for clave, valor in params.items():
            if valor is None:
                pares.pop(clave, None)
            else:
                pares[clave] = str(valor)
        return urlunsplit((partes.scheme, partes.netloc, partes.path, urlencode(pares), partes.fragment))
"""})

tarea_eval("agenda_choques", "Detectar choques en una agenda", """
    Creá agenda.py con choques(eventos: list[tuple[str, str, str]]) -> list[tuple[str, str]] donde cada evento
    es (nombre, inicio, fin) con horas "HH:MM". Devuelve los pares de nombres que se superponen (tocarse en el
    borde NO es choque), cada par ordenado alfabéticamente y la lista ordenada. Si un evento tiene fin <= inicio
    lanza ValueError.
""", {"tests/test_agenda.py": """
    import unittest
    from agenda import choques

    class T(unittest.TestCase):
        def test_choques(self):
            eventos = [("yoga", "09:00", "10:00"), ("café", "09:30", "09:45"), ("reunión", "10:00", "11:00"),
                       ("almuerzo", "10:30", "12:00")]
            self.assertEqual(choques(eventos), [("almuerzo", "reunión"), ("café", "yoga")])
        def test_sin_choques(self):
            self.assertEqual(choques([("a", "08:00", "09:00"), ("b", "09:00", "10:00")]), [])
        def test_invalido(self):
            with self.assertRaises(ValueError):
                choques([("a", "10:00", "09:00")])
"""})
solucion_eval("agenda_choques", {"agenda.py": """
    def _min(h):
        horas, minutos = h.split(":")
        return int(horas) * 60 + int(minutos)

    def choques(eventos):
        convertidos = []
        for nombre, inicio, fin in eventos:
            a, b = _min(inicio), _min(fin)
            if b <= a:
                raise ValueError(f"{nombre}: el fin tiene que ser posterior al inicio")
            convertidos.append((nombre, a, b))
        pares = []
        for i, (n1, a1, b1) in enumerate(convertidos):
            for n2, a2, b2 in convertidos[i + 1:]:
                if a1 < b2 and a2 < b1:
                    pares.append(tuple(sorted((n1, n2))))
        return sorted(pares)
"""})

tarea_eval("frecuencias", "Palabras más frecuentes", """
    Creá palabras.py con mas_frecuentes(texto: str, n: int = 3, ignorar: set[str] | None = None) -> list[tuple[str, int]]:
    cuenta palabras sin distinguir mayúsculas ni tildes (á = a, pero ñ es distinta de n), ignora signos de
    puntuación y números, y las palabras en `ignorar` (comparadas también sin tildes). Ordena por frecuencia
    descendente y, a igual frecuencia, alfabéticamente.
""", {"tests/test_palabras.py": """
    import unittest
    from palabras import mas_frecuentes

    class T(unittest.TestCase):
        def test_basico(self):
            texto = "El mate, el MATE y él. ¡Mate! Año 2024: año nuevo"
            self.assertEqual(mas_frecuentes(texto, 2), [("el", 3), ("mate", 3)])
        def test_ignorar_y_enie(self):
            texto = "año ano año el el"
            self.assertEqual(mas_frecuentes(texto, 3, ignorar={"Él"}), [("año", 2), ("ano", 1)])
        def test_vacio(self):
            self.assertEqual(mas_frecuentes("123 !!!"), [])
"""}, dificultad=2)
solucion_eval("frecuencias", {"palabras.py": """
    import re
    import unicodedata
    from collections import Counter

    def _norm(p):
        p = p.lower().replace("ñ", "\\x00")
        p = unicodedata.normalize("NFKD", p).encode("ascii", "ignore").decode()
        return p.replace("\\x00", "ñ")

    def mas_frecuentes(texto, n=3, ignorar=None):
        ignorar = {_norm(x) for x in (ignorar or set())}
        palabras = [_norm(p) for p in re.findall(r"[^\\W\\d_]+", texto)]
        conteo = Counter(p for p in palabras if p and p not in ignorar)
        return sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
"""})

# ======================================================================== JAVASCRIPT
tarea_eval("js_slug", "Slugs para URLs (JavaScript)", """
    Creá src/slug.mjs que exporte slugify(texto) → string: minúsculas, sin tildes (ñ → n), cualquier cosa que
    no sea letra o número se convierte en un guion, sin guiones repetidos ni al principio o al final.
    También exportá slugUnico(texto, existentes: Set) que agrega -2, -3... si el slug ya existe.
""", {"tests/slug.test.mjs": """
    import { test } from 'node:test';
    import assert from 'node:assert/strict';
    import { slugify, slugUnico } from '../src/slug.mjs';

    test('slugify', () => {
      assert.equal(slugify('¡Hola, Mundo!'), 'hola-mundo');
      assert.equal(slugify('  Año   Nuevo -- 2024 '), 'ano-nuevo-2024');
      assert.equal(slugify('Ñandú & Cía.'), 'nandu-cia');
      assert.equal(slugify('***'), '');
    });

    test('slugUnico', () => {
      const existentes = new Set(['hola', 'hola-2']);
      assert.equal(slugUnico('Hola', existentes), 'hola-3');
      assert.equal(slugUnico('Chau', existentes), 'chau');
    });
"""}, comando_tests="node --test tests/*.test.mjs", requiere=("node",), lenguaje="javascript")
solucion_eval("js_slug", {"src/slug.mjs": """
    export function slugify(texto) {
      return texto
        .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    }

    export function slugUnico(texto, existentes) {
      const base = slugify(texto);
      if (!existentes.has(base)) return base;
      let n = 2;
      while (existentes.has(`${base}-${n}`)) n++;
      return `${base}-${n}`;
    }
"""})

tarea_eval("js_carrito", "Carrito con descuentos (JavaScript)", """
    Creá src/carrito.mjs que exporte totalCarrito(items, cupon = null) donde items es un array de
    {precio, cantidad} (precios en centavos, enteros). Reglas: subtotal = suma de precio*cantidad; cupón
    "DESC10" descuenta 10% (redondeando hacia abajo al centavo), "ENVIO" no descuenta pero hace gratis el
    envío; el envío cuesta 50000 centavos si el subtotal (antes del descuento) es menor a 3000000, si no es
    gratis. Devuelve {subtotal, descuento, envio, total}. Cantidades o precios negativos → Error; cupón
    desconocido → Error.
""", {"tests/carrito.test.mjs": """
    import { test } from 'node:test';
    import assert from 'node:assert/strict';
    import { totalCarrito } from '../src/carrito.mjs';

    test('sin cupón con envío', () => {
      assert.deepEqual(totalCarrito([{ precio: 100000, cantidad: 3 }]),
        { subtotal: 300000, descuento: 0, envio: 50000, total: 350000 });
    });

    test('envío gratis por monto y DESC10', () => {
      assert.deepEqual(totalCarrito([{ precio: 1000005, cantidad: 3 }], 'DESC10'),
        { subtotal: 3000015, descuento: 300001, envio: 0, total: 2700014 });
    });

    test('cupón ENVIO', () => {
      assert.equal(totalCarrito([{ precio: 1000, cantidad: 1 }], 'ENVIO').envio, 0);
    });

    test('errores', () => {
      assert.throws(() => totalCarrito([{ precio: -1, cantidad: 1 }]));
      assert.throws(() => totalCarrito([{ precio: 1, cantidad: 1 }], 'TRUCHO'));
    });
"""}, comando_tests="node --test tests/*.test.mjs", requiere=("node",), lenguaje="javascript", dificultad=2)
solucion_eval("js_carrito", {"src/carrito.mjs": """
    export function totalCarrito(items, cupon = null) {
      let subtotal = 0;
      for (const { precio, cantidad } of items) {
        if (precio < 0 || cantidad < 0) throw new Error('precio o cantidad negativos');
        subtotal += precio * cantidad;
      }
      if (cupon !== null && !['DESC10', 'ENVIO'].includes(cupon)) throw new Error(`cupón desconocido: ${cupon}`);
      const descuento = cupon === 'DESC10' ? Math.floor(subtotal / 10) : 0;
      const envio = cupon === 'ENVIO' || subtotal >= 3000000 ? 0 : 50000;
      return { subtotal, descuento, envio, total: subtotal - descuento + envio };
    }
"""})

# ======================================================================== GO
tarea_eval("go_pila", "Pila genérica con errores (Go)", """
    En un módulo Go llamado "pila" (creá go.mod con `module pila` y `go 1.18`), creá pila.go en el paquete pila
    con el tipo Pila[T any] y los métodos Apilar(v T), Desapilar() (T, error), Ver() (T, error), Largo() int y
    Vacia() bool. Desapilar y Ver sobre una pila vacía devuelven el error ErrVacia (variable exportada).
""", {"pila_oculto_test.go": """
    package pila

    import (
        "errors"
        "testing"
    )

    func TestPila(t *testing.T) {
        var p Pila[string]
        if !p.Vacia() {
            t.Fatal("nueva pila debería estar vacía")
        }
        p.Apilar("a")
        p.Apilar("b")
        if v, err := p.Ver(); err != nil || v != "b" {
            t.Fatalf("Ver = %v, %v", v, err)
        }
        if v, _ := p.Desapilar(); v != "b" || p.Largo() != 1 {
            t.Fatalf("Desapilar = %v, largo %d", v, p.Largo())
        }
        p.Desapilar()
        if _, err := p.Desapilar(); !errors.Is(err, ErrVacia) {
            t.Fatalf("err = %v", err)
        }
    }
"""}, comando_tests="go test ./...", requiere=("go",), lenguaje="go", dificultad=2)
solucion_eval("go_pila", {"go.mod": "module pila\n\ngo 1.18\n", "pila.go": """
    package pila

    import "errors"

    var ErrVacia = errors.New("pila vacía")

    type Pila[T any] struct{ datos []T }

    func (p *Pila[T]) Apilar(v T) { p.datos = append(p.datos, v) }

    func (p *Pila[T]) Ver() (T, error) {
        var cero T
        if len(p.datos) == 0 {
            return cero, ErrVacia
        }
        return p.datos[len(p.datos)-1], nil
    }

    func (p *Pila[T]) Desapilar() (T, error) {
        v, err := p.Ver()
        if err == nil {
            p.datos = p.datos[:len(p.datos)-1]
        }
        return v, err
    }

    func (p *Pila[T]) Largo() int  { return len(p.datos) }
    func (p *Pila[T]) Vacia() bool { return len(p.datos) == 0 }
"""})
