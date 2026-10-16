"""
Simulación de un proyecto GRANDE y realista con /grande: un almacén de barrio en 5 etapas (datos SQLite → ventas con
control de stock → reportes y CSV → API HTTP real → web con módulos JS y tests de node). El modelo es simulado pero
el código es real y los tests del proyecto corren de verdad (unittest + node --test, servidor HTTP incluido).
Variante "modelo flojo": en la web escribe <script src="app.js"> SIN type="module" (la página no anda en el
navegador aunque node --test pase); REAPER tiene que detectarlo y hacerlo reparar.
"""


class _GuionAlmacen:
    ARCHIVOS = {
        'almacen/__init__.py': '',
        'almacen/db.py': 'import sqlite3\n\nESQUEMA = """\nCREATE TABLE IF NOT EXISTS productos (codigo TEXT PRIMARY KEY, nombre TEXT NOT NULL,\n    precio REAL NOT NULL CHECK (precio >= 0), stock INTEGER NOT NULL CHECK (stock >= 0));\nCREATE TABLE IF NOT EXISTS clientes (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL);\nCREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY, cliente_id INTEGER REFERENCES clientes(id),\n    fecha TEXT NOT NULL, total REAL NOT NULL);\nCREATE TABLE IF NOT EXISTS items (venta_id INTEGER REFERENCES ventas(id), codigo TEXT REFERENCES productos(codigo),\n    cantidad INTEGER NOT NULL, precio REAL NOT NULL);\n"""\n\n\ndef conectar(ruta=":memory:"):\n    con = sqlite3.connect(ruta, check_same_thread=False)\n    con.row_factory = sqlite3.Row\n    con.executescript(ESQUEMA)\n    return con\n\n\ndef agregar_producto(con, codigo, nombre, precio, stock):\n    if not codigo.strip() or not nombre.strip():\n        raise ValueError("código y nombre son obligatorios")\n    if precio < 0 or stock < 0:\n        raise ValueError("precio y stock no pueden ser negativos")\n    con.execute("INSERT INTO productos VALUES (?, ?, ?, ?)", (codigo.strip(), nombre.strip(), float(precio), int(stock)))\n    con.commit()\n\n\ndef productos(con, buscar=""):\n    filas = con.execute("SELECT * FROM productos WHERE nombre LIKE ? ORDER BY nombre", (f"%{buscar}%",))\n    return [dict(f) for f in filas]\n\n\ndef agregar_cliente(con, nombre):\n    if not nombre.strip():\n        raise ValueError("el nombre es obligatorio")\n    cur = con.execute("INSERT INTO clientes (nombre) VALUES (?)", (nombre.strip(),))\n    con.commit()\n    return cur.lastrowid\n',
        'tests/test_db.py': 'import unittest\n\nfrom almacen import db\n\n\nclass TestDb(unittest.TestCase):\n    def setUp(self):\n        self.con = db.conectar()\n\n    def test_agregar_y_buscar_producto(self):\n        db.agregar_producto(self.con, "A1", "Yerba", 3500, 10)\n        db.agregar_producto(self.con, "B2", "Azúcar", 1200, 5)\n        self.assertEqual([p["codigo"] for p in db.productos(self.con, "Yer")], ["A1"])\n\n    def test_no_acepta_negativos(self):\n        with self.assertRaises(ValueError):\n            db.agregar_producto(self.con, "A1", "Yerba", -1, 10)\n\n    def test_cliente(self):\n        self.assertEqual(db.agregar_cliente(self.con, "Ana"), 1)\n',
        'almacen/ventas.py': 'from datetime import date\n\n\nclass SinStock(ValueError):\n    pass\n\n\ndef registrar_venta(con, cliente_id, items, fecha=None):\n    """items: [(codigo, cantidad)]. Todo o nada: si falta stock de uno, no se vende ninguno."""\n    if not items:\n        raise ValueError("la venta no tiene productos")\n    fecha = fecha or date.today().isoformat()\n    with con:\n        total = 0.0\n        detalle = []\n        for codigo, cantidad in items:\n            if cantidad <= 0:\n                raise ValueError(f"cantidad inválida para {codigo}")\n            fila = con.execute("SELECT precio, stock FROM productos WHERE codigo = ?", (codigo,)).fetchone()\n            if fila is None:\n                raise KeyError(codigo)\n            if fila["stock"] < cantidad:\n                raise SinStock(f"sin stock de {codigo}: hay {fila[\'stock\']}, pidieron {cantidad}")\n            detalle.append((codigo, cantidad, fila["precio"]))\n            total += cantidad * fila["precio"]\n        cur = con.execute("INSERT INTO ventas (cliente_id, fecha, total) VALUES (?, ?, ?)", (cliente_id, fecha, total))\n        for codigo, cantidad, precio in detalle:\n            con.execute("UPDATE productos SET stock = stock - ? WHERE codigo = ?", (cantidad, codigo))\n            con.execute("INSERT INTO items VALUES (?, ?, ?, ?)", (cur.lastrowid, codigo, cantidad, precio))\n    return cur.lastrowid, round(total, 2)\n',
        'tests/test_ventas.py': 'import unittest\n\nfrom almacen import db\nfrom almacen.ventas import SinStock, registrar_venta\n\n\nclass TestVentas(unittest.TestCase):\n    def setUp(self):\n        self.con = db.conectar()\n        db.agregar_producto(self.con, "A1", "Yerba", 3500, 3)\n        db.agregar_producto(self.con, "B2", "Azúcar", 1200, 1)\n        self.cliente = db.agregar_cliente(self.con, "Ana")\n\n    def test_descuenta_stock_y_calcula_total(self):\n        _id, total = registrar_venta(self.con, self.cliente, [("A1", 2), ("B2", 1)])\n        self.assertEqual(total, 8200)\n        stock = {p["codigo"]: p["stock"] for p in db.productos(self.con)}\n        self.assertEqual(stock, {"A1": 1, "B2": 0})\n\n    def test_sin_stock_no_vende_nada(self):\n        with self.assertRaises(SinStock):\n            registrar_venta(self.con, self.cliente, [("A1", 1), ("B2", 5)])\n        stock = {p["codigo"]: p["stock"] for p in db.productos(self.con)}\n        self.assertEqual(stock, {"A1": 3, "B2": 1})\n',
        'almacen/reportes.py': 'import csv\nimport io\n\n\ndef ventas_por_dia(con):\n    filas = con.execute("SELECT fecha, COUNT(*) AS ventas, SUM(total) AS total FROM ventas GROUP BY fecha ORDER BY fecha")\n    return [dict(f) for f in filas]\n\n\ndef mas_vendidos(con, limite=5):\n    filas = con.execute("SELECT i.codigo, p.nombre, SUM(i.cantidad) AS unidades FROM items i "\n                        "JOIN productos p ON p.codigo = i.codigo GROUP BY i.codigo ORDER BY unidades DESC, i.codigo "\n                        "LIMIT ?", (limite,))\n    return [dict(f) for f in filas]\n\n\ndef exportar_csv(filas):\n    if not filas:\n        return ""\n    salida = io.StringIO()\n    escritor = csv.DictWriter(salida, fieldnames=list(filas[0]))\n    escritor.writeheader()\n    escritor.writerows(filas)\n    return salida.getvalue()\n',
        'tests/test_reportes.py': 'import unittest\n\nfrom almacen import db, reportes\nfrom almacen.ventas import registrar_venta\n\n\nclass TestReportes(unittest.TestCase):\n    def setUp(self):\n        self.con = db.conectar()\n        db.agregar_producto(self.con, "A1", "Yerba", 100, 50)\n        db.agregar_producto(self.con, "B2", "Azúcar", 10, 50)\n        registrar_venta(self.con, None, [("A1", 1), ("B2", 5)], fecha="2026-10-01")\n        registrar_venta(self.con, None, [("B2", 2)], fecha="2026-10-02")\n\n    def test_por_dia(self):\n        self.assertEqual(reportes.ventas_por_dia(self.con),\n                         [{"fecha": "2026-10-01", "ventas": 1, "total": 150.0},\n                          {"fecha": "2026-10-02", "ventas": 1, "total": 20.0}])\n\n    def test_mas_vendidos_y_csv(self):\n        top = reportes.mas_vendidos(self.con)\n        self.assertEqual(top[0]["codigo"], "B2")\n        texto = reportes.exportar_csv(top)\n        self.assertTrue(texto.startswith("codigo,nombre,unidades"))\n        self.assertIn("B2,Azúcar,7", texto)\n',
        'almacen/api.py': 'import json\nfrom http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer\nfrom pathlib import Path\n\nfrom almacen import db, reportes\nfrom almacen.ventas import SinStock, registrar_venta\n\nWEB = Path(__file__).resolve().parent.parent / "web"\n\n\ndef crear_servidor(con, puerto=0):\n    class Manejador(SimpleHTTPRequestHandler):\n        def __init__(self, *args, **kwargs):\n            super().__init__(*args, directory=str(WEB), **kwargs)\n\n        def log_message(self, formato, *args):\n            pass\n\n        def _json(self, codigo, datos):\n            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")\n            self.send_response(codigo)\n            self.send_header("Content-Type", "application/json; charset=utf-8")\n            self.send_header("Content-Length", str(len(cuerpo)))\n            self.end_headers()\n            self.wfile.write(cuerpo)\n\n        def do_GET(self):\n            if self.path.startswith("/api/productos"):\n                return self._json(200, db.productos(con))\n            if self.path == "/api/reportes/mas-vendidos":\n                return self._json(200, reportes.mas_vendidos(con))\n            return super().do_GET()\n\n        def do_POST(self):\n            if self.path != "/api/ventas":\n                return self._json(404, {"error": "ruta inexistente"})\n            try:\n                largo = int(self.headers.get("Content-Length", "0"))\n                datos = json.loads(self.rfile.read(largo) or b"{}")\n                items = [(i["codigo"], int(i["cantidad"])) for i in datos.get("items", [])]\n                venta, total = registrar_venta(con, datos.get("cliente_id"), items)\n            except SinStock as e:\n                return self._json(409, {"error": str(e)})\n            except (ValueError, KeyError, TypeError) as e:\n                return self._json(400, {"error": f"datos inválidos: {e}"})\n            return self._json(201, {"venta": venta, "total": total})\n\n    return ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)\n',
        'almacen/__main__.py': 'import argparse\n\nfrom almacen import db\nfrom almacen.api import crear_servidor\n\n\ndef main(argv=None):\n    parser = argparse.ArgumentParser(prog="almacen", description="Almacén de barrio: API y web")\n    parser.add_argument("--puerto", type=int, default=8000)\n    parser.add_argument("--db", default="almacen.db")\n    args = parser.parse_args(argv)\n    servidor = crear_servidor(db.conectar(args.db), args.puerto)\n    print(f"Almacén en http://127.0.0.1:{servidor.server_port}")\n    try:\n        servidor.serve_forever()\n    except KeyboardInterrupt:\n        pass\n    finally:\n        servidor.server_close()\n\n\nif __name__ == "__main__":\n    main()\n',
        'tests/test_api.py': 'import json\nimport threading\nimport unittest\nimport urllib.error\nimport urllib.request\n\nfrom almacen import db\nfrom almacen.api import crear_servidor\n\n\nclass TestApi(unittest.TestCase):\n    def setUp(self):\n        self.con = db.conectar()\n        db.agregar_producto(self.con, "A1", "Yerba", 100, 2)\n        self.servidor = crear_servidor(self.con)\n        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)\n        self.hilo.start()\n        self.base = f"http://127.0.0.1:{self.servidor.server_port}"\n\n    def tearDown(self):\n        self.servidor.shutdown()\n        self.servidor.server_close()\n\n    def _post(self, ruta, datos):\n        pedido = urllib.request.Request(self.base + ruta, data=json.dumps(datos).encode(), method="POST",\n                                        headers={"Content-Type": "application/json"})\n        try:\n            with urllib.request.urlopen(pedido, timeout=5) as r:\n                return r.status, json.loads(r.read())\n        except urllib.error.HTTPError as e:\n            return e.code, json.loads(e.read())\n\n    def test_productos(self):\n        with urllib.request.urlopen(self.base + "/api/productos", timeout=5) as r:\n            self.assertEqual(json.loads(r.read())[0]["codigo"], "A1")\n\n    def test_venta_y_sin_stock(self):\n        self.assertEqual(self._post("/api/ventas", {"items": [{"codigo": "A1", "cantidad": 2}]}),\n                         (201, {"venta": 1, "total": 200.0}))\n        codigo, datos = self._post("/api/ventas", {"items": [{"codigo": "A1", "cantidad": 1}]})\n        self.assertEqual(codigo, 409)\n        self.assertIn("sin stock", datos["error"])\n',
        'web/logica.js': 'export function totalCarrito(items) {\n  return items.reduce((suma, item) => suma + item.precio * item.cantidad, 0);\n}\n\nexport function validarItem(item, stock) {\n  if (!Number.isInteger(item.cantidad) || item.cantidad <= 0) return "la cantidad tiene que ser un entero positivo";\n  if (item.cantidad > stock) return `sin stock: hay ${stock}`;\n  return "";\n}\n\nexport function formatearPrecio(valor) {\n  return "$ " + valor.toFixed(2);\n}\n',
        'tests/logica.test.mjs': 'import { test } from "node:test";\nimport assert from "node:assert/strict";\nimport { totalCarrito, validarItem, formatearPrecio } from "../web/logica.js";\n\ntest("total del carrito", () => {\n  assert.equal(totalCarrito([{ precio: 100, cantidad: 2 }, { precio: 10, cantidad: 1 }]), 210);\n});\n\ntest("valida cantidad y stock", () => {\n  assert.equal(validarItem({ cantidad: 0 }, 5), "la cantidad tiene que ser un entero positivo");\n  assert.equal(validarItem({ cantidad: 6 }, 5), "sin stock: hay 5");\n  assert.equal(validarItem({ cantidad: 2 }, 5), "");\n});\n\ntest("formatea precio", () => {\n  assert.equal(formatearPrecio(3.5), "$ 3.50");\n});\n',
        'web/app.js': 'import { totalCarrito, validarItem, formatearPrecio } from "./logica.js";\n\nconst carrito = [];\n\nasync function cargarProductos() {\n  const respuesta = await fetch("/api/productos");\n  const productos = await respuesta.json();\n  const lista = document.getElementById("productos");\n  lista.innerHTML = "";\n  for (const p of productos) {\n    const fila = document.createElement("li");\n    fila.textContent = `${p.nombre} · ${formatearPrecio(p.precio)} · stock ${p.stock}`;\n    const boton = document.createElement("button");\n    boton.textContent = "Agregar";\n    boton.addEventListener("click", () => agregar(p));\n    fila.append(boton);\n    lista.append(fila);\n  }\n}\n\nfunction agregar(producto) {\n  const item = { codigo: producto.codigo, precio: producto.precio, cantidad: 1 };\n  const error = validarItem(item, producto.stock);\n  document.getElementById("mensaje").textContent = error;\n  if (error) return;\n  carrito.push(item);\n  document.getElementById("total").textContent = formatearPrecio(totalCarrito(carrito));\n}\n\ndocument.getElementById("vender").addEventListener("click", async () => {\n  const respuesta = await fetch("/api/ventas", {\n    method: "POST",\n    headers: { "Content-Type": "application/json" },\n    body: JSON.stringify({ items: carrito.map(({ codigo, cantidad }) => ({ codigo, cantidad })) }),\n  });\n  const datos = await respuesta.json();\n  document.getElementById("mensaje").textContent = respuesta.ok ? `Venta ${datos.venta} registrada` : datos.error;\n  carrito.length = 0;\n  cargarProductos();\n});\n\ncargarProductos();\n',
        'web/index.html': '<!doctype html>\n<html lang="es">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <title>Almacén</title>\n  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n  <h1>Almacén</h1>\n  <ul id="productos"></ul>\n  <p>Total: <strong id="total">$ 0.00</strong></p>\n  <button id="vender">Vender</button>\n  <p id="mensaje" role="status"></p>\n  <script type="module" src="app.js"></script>\n</body>\n</html>\n',
        'web/style.css': 'body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 0 auto; padding: 1rem; }\nli { display: flex; justify-content: space-between; gap: 0.5rem; padding: 0.4rem 0; }\nbutton { padding: 0.5rem 1rem; }\n@media (max-width: 30rem) { li { flex-direction: column; } }\n',
    }
    TAREAS = {  # marca de la tarea → archivos que escribe el implementador, en orden
        "T1": ["almacen/__init__.py", "almacen/db.py", "tests/test_db.py"],
        "T2": ["almacen/ventas.py", "tests/test_ventas.py"],
        "T3": ["almacen/reportes.py", "tests/test_reportes.py"],
        "T4a": ["almacen/api.py", "tests/test_api.py"],
        "T4b": ["almacen/__main__.py"],
        "T5a": ["web/logica.js", "tests/logica.test.mjs"],
        "T5b": ["web/index.html", "web/app.js", "web/style.css"],
    }
    MAESTRO = """<maestro>
<vision>Sistema de gestión de un almacén de barrio: productos con stock, ventas, reportes, API JSON y una web.</vision>
<arquitectura>
Python 3 solo librería estándar (sqlite3, http.server). Paquete almacen/. Web estática en web/ con módulos ES.
Tests: unittest en tests/ y node:test para la lógica JS. Arranca con python -m almacen --puerto 8000.
</arquitectura>
<etapa id="1" titulo="Datos" deps="">
<objetivo>Base sqlite con productos, clientes, ventas e items.</objetivo>
<archivos>almacen/__init__.py, almacen/db.py, tests/test_db.py</archivos>
<interfaz>
- almacen/db.py: conectar(ruta) -> Connection; agregar_producto(con, codigo, nombre, precio, stock); productos(con, buscar="") -> list[dict]; agregar_cliente(con, nombre) -> int
</interfaz>
<criterios>
- no acepta precio ni stock negativos
</criterios>
</etapa>
<etapa id="2" titulo="Ventas" deps="1">
<objetivo>Ventas que descuentan stock y no permiten vender sin stock (todo o nada).</objetivo>
<archivos>almacen/ventas.py, tests/test_ventas.py</archivos>
<interfaz>
- almacen/ventas.py: registrar_venta(con, cliente_id, items) -> (id, total); class SinStock(ValueError)
</interfaz>
</etapa>
<etapa id="3" titulo="Reportes" deps="2">
<objetivo>Ventas por día, más vendidos y exportar a CSV.</objetivo>
<archivos>almacen/reportes.py, tests/test_reportes.py</archivos>
</etapa>
<etapa id="4" titulo="API" deps="2, 3">
<objetivo>API JSON con http.server y arranque python -m almacen.</objetivo>
<archivos>almacen/api.py, almacen/__main__.py, tests/test_api.py</archivos>
<interfaz>
- almacen/api.py: crear_servidor(con, puerto=0) -> ThreadingHTTPServer
</interfaz>
</etapa>
<etapa id="5" titulo="Web" deps="4">
<objetivo>Página para cargar ventas y ver el stock, adaptable al celular.</objetivo>
<archivos>web/index.html, web/app.js, web/logica.js, web/style.css, tests/logica.test.mjs</archivos>
<interfaz>
- web/logica.js: export function totalCarrito(items); export function validarItem(item, stock); export function formatearPrecio(valor)
</interfaz>
</etapa>
</maestro>"""
    PLANES = {
        "1": '<plan><objetivo>Datos</objetivo><tarea id="1" archivos="almacen/__init__.py, almacen/db.py, tests/test_db.py">Base sqlite y sus tests (T1).</tarea></plan>',
        "2": '<plan><objetivo>Ventas</objetivo><tarea id="1" archivos="almacen/ventas.py, tests/test_ventas.py">Ventas con control de stock y sus tests (T2).</tarea></plan>',
        "3": '<plan><objetivo>Reportes</objetivo><tarea id="1" archivos="almacen/reportes.py, tests/test_reportes.py">Reportes y CSV con tests (T3).</tarea></plan>',
        "4": ('<plan><objetivo>API</objetivo><tarea id="1" archivos="almacen/api.py, tests/test_api.py">API http.server y '
              'sus tests (T4a).</tarea><tarea id="2" archivos="almacen/__main__.py" deps="1">Arranque con argparse '
              '(T4b).</tarea></plan>'),
        "5": ('<plan><objetivo>Web</objetivo><tarea id="1" archivos="web/logica.js, tests/logica.test.mjs">Lógica pura '
              'y tests node (T5a).</tarea><tarea id="2" archivos="web/index.html, web/app.js, web/style.css" deps="1">'
              'Página y estilos (T5b).</tarea></plan>'),
    }

    def __init__(self, ws, html_roto=False, romper_db=False):
        self.ws = ws
        self.html_roto = html_roto
        self.romper_db = romper_db              # en la etapa 3 "de paso" borra agregar_cliente de db.py (etapa 1)
        self.llamadas = collections.Counter()
        self.reparo_html = False

    def _contenido(self, rel):
        texto = self.ARCHIVOS[rel]
        if rel == "web/index.html" and self.html_roto:
            return texto.replace('<script type="module" src="app.js">', '<script src="app.js">')
        return texto

    def __call__(self, mensajes, kw):
        rol = MockLLM.rol_de(mensajes)
        self.llamadas[rol] += 1
        primero = next((m["content"] for m in mensajes if m["role"] == "user"), "")
        if rol == "maestro":
            return self.MAESTRO
        if rol == "arquitecto":
            etapa = re.search(r"ETAPA (\d+) de 5", primero)
            return terminar_xml(self.PLANES[etapa.group(1) if etapa else "1"])
        if rol == "implementador":
            tarea = re.search(r"TU TAREA AHORA \(#[^)]*\):\n(.*?)\n\n", primero, re.S)
            marca = re.search(r"\((T\d+[ab]?)\)", tarea.group(1) if tarea else "")
            archivos = self.TAREAS[marca.group(1)] if marca else []
            turno = _turno(mensajes)
            if self.romper_db and marca and marca.group(1) == "T3" and turno == len(archivos):
                roto = self.ARCHIVOS["almacen/db.py"].split("def agregar_cliente")[0]
                return herramienta_xml("write_to_file", path="almacen/db.py", content=roto)
            if self.romper_db and marca and marca.group(1) == "T3" and turno > len(archivos):
                return terminar_xml("listo")
            if turno < len(archivos):
                return herramienta_xml("write_to_file", path=archivos[turno], content=self._contenido(archivos[turno]))
            return terminar_xml("listo")
        if rol in ("reparador", "integrador"):
            # El reparador ve el error REAL del validador y corrige el HTML (una sola escritura).
            if 'type=\"module\"' in primero or 'type="module"' in primero:
                if _turno(mensajes) == 0:
                    self.reparo_html = True
                    return herramienta_xml("write_to_file", path="web/index.html",
                                           content=self.ARCHIVOS["web/index.html"])
            return terminar_xml("revisado")
        if rol == "juez":
            texto = MockLLM.ultimo_usuario(mensajes)
            if "TAREA: CONTRATO" in texto:
                return '{"criterios": ["lo pedido funciona y tiene tests"]}'
            return '{"cumple": true, "confianza": "high", "evidence_ids": ["EV-TESTS"]}'
        return terminar_xml("sin cambios")


class TestGrandeAlmacen(BaseTest):
    PEDIDO = ("Un sistema para un almacén de barrio: productos con stock, ventas que no permiten vender sin stock, "
              "reportes por día y más vendidos con CSV, una API JSON con http.server y una web para el celular")

    def _correr(self, **guion_kw):
        if not shutil.which("node"):
            self.skipTest("node no está instalado")
        ws = self.proyecto({})
        guion = _GuionAlmacen(ws, **guion_kw)
        ui = self.ui()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=2, juez=True, git_snapshots=False)
        grande = ConstructorGrande(MockLLM(guion), ws, ajustes, ui)
        grande.consultar_cuenta = lambda: None
        grande.dormir = lambda s: self.fail(f"no debía esperar {s}s")
        ok = grande.iniciar(self.PEDIDO, confirmar=False)
        return ws, guion, ui, grande, ok

    def test_cinco_etapas_con_api_y_web_y_un_modelo_flojo(self):
        # Una sola corrida (≈30 s): recorre las 5 etapas y, en la web, el HTML roto del "modelo flojo".
        ws, guion, ui, grande, ok = self._correr(html_roto=True)
        texto = ui.texto_registrado()
        self.assertTrue(ok, texto[-4000:])
        estado = grande.leer()
        self.assertEqual([e["estado"] for e in estado["maestro"]["etapas"]], ["verificada"] * 5)
        self.assertTrue(guion.reparo_html, "el reparador nunca vio el error del HTML")
        self.assertIn("SyntaxError: Unexpected token 'export'", texto)          # el error que vio el reparador
        self.assertEqual(scripts_html_incoherentes(ws, ws.raiz / "web/index.html", ws.leer("web/index.html")), [])
        r = ejecutar_tests(ws, timeout=180)
        self.assertTrue(r.ok, r.stdout[-2000:] + r.stderr[-2000:])
        conteo = conteo_de_resultado(r)
        self.assertEqual((conteo.pasados, conteo.fallados), (12, 0))           # 9 de Python + 3 de node
        self.assertIn("TERMINADO Y VERIFICADO", texto)
        self.assertIn("✓ Juez de entrega: CUMPLE", texto)                       # a favor no sale como ⚠
        self.assertNotIn("⚠ • Juez de entrega: CUMPLE", texto)

    def test_etapa_que_rompe_lo_verificado_se_frena_se_deshace_y_se_rehace(self):
        if not shutil.which("node"):
            self.skipTest("node no está instalado")
        ws = self.proyecto({})
        guion = _GuionAlmacen(ws, romper_db=True)
        ui = self.ui()
        ajustes = self.ajustes(tests_primero=False, torneo=False, escalar=False, max_revisiones=0, qa=False,
                               max_reparaciones=1, juez=False, git_snapshots=False)
        grande = ConstructorGrande(MockLLM(guion), ws, ajustes, ui)
        grande.consultar_cuenta = lambda: None
        self.assertFalse(grande.iniciar(self.PEDIDO, confirmar=False))
        estado = grande.leer()
        self.assertEqual([e["estado"] for e in estado["maestro"]["etapas"]][:3], ["verificada", "verificada", "fallida"])
        self.assertIn("1", estado["rotas_previas"])                                 # avisa qué verificado rompió
        self.assertIn("ROMPIERON lo que ya estaba verificado", ui.texto_registrado())
        self.assertNotIn("def agregar_cliente", ws.leer("almacen/db.py"))
        self.assertTrue(grande.deshacer_etapa())                                    # vuelve al último verificado
        self.assertIn("def agregar_cliente", ws.leer("almacen/db.py"))
        self.assertFalse(ws.existe("almacen/reportes.py"))                          # lo de la etapa 3, afuera
        self.assertIsNone(RegistroBuild(ws).leer())
        self.assertTrue(ejecutar_tests(ws, timeout=120).ok)                         # etapas 1 y 2 en verde de nuevo
        guion.romper_db = False                                                     # "el modelo lo hace bien"
        self.assertTrue(grande.continuar(), ui.texto_registrado()[-3000:])
        self.assertEqual(grande.leer()["estado"], "terminado")

