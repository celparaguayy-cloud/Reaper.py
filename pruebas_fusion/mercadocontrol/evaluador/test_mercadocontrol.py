"""
Evaluador INDEPENDIENTE de MercadoControl (fusión REAPER 8.10, Claude Code).

Se coloca FUERA del proyecto que REAPER edita y no lo genera ni lo modifica REAPER. Levanta el servidor real del
proyecto con subprocess, usa HTTP real (urllib) y una base SQLite temporal y fresca por corrida.

CONTRATO SUPUESTO (documentado; los criterios originales del 1/10 histórico NO estaban disponibles):
  - app.py en la raíz del proyecto; puerto en la variable PORT; ruta de la base en MERCADO_DB.
  - GET /            → HTML que enlaza style.css y script.js
  - GET /style.css   → text/css no vacío;  GET /script.js → JavaScript no vacío
  - API JSON en /api/productos: GET lista (array), POST crea (201, devuelve id), GET/PUT/DELETE /api/productos/<id>
  - validaciones → 400 con JSON {"error": ...};  rutas desconocidas → 404
Si el proyecto real usa otro contrato, ajustá SOLO este archivo (nunca el proyecto para que pase).
"""
import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

PROYECTO = os.environ.get("REAPER_PROYECTO") or os.getcwd()


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Servidor:
    def __init__(self, db):
        self.db = db
        self.puerto = _puerto_libre()
        self.proceso = None

    def iniciar(self):
        env = dict(os.environ, PORT=str(self.puerto), MERCADO_DB=self.db, PYTHONUNBUFFERED="1")
        self.log = tempfile.TemporaryFile()
        self.proceso = subprocess.Popen([sys.executable, "app.py"], cwd=PROYECTO, env=env,
                                        stdout=self.log, stderr=subprocess.STDOUT)
        limite = time.monotonic() + 15
        while time.monotonic() < limite:
            if self.proceso.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", self.puerto), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.2)
        salida = self.salida()
        self.detener()
        raise AssertionError(f"El servidor no arrancó en 15 s (exit {self.proceso.returncode}):\n{salida[-1500:]}")

    def salida(self):
        try:
            self.log.seek(0)
            return self.log.read().decode("utf-8", "replace")
        except (OSError, AttributeError, ValueError):
            return ""

    def detener(self):
        if self.proceso and self.proceso.poll() is None:
            self.proceso.terminate()
            try:
                self.proceso.wait(5)
            except subprocess.TimeoutExpired:
                self.proceso.kill()
                self.proceso.wait()


class BaseMercado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mercado_eval_")
        cls.srv = Servidor(os.path.join(cls.tmp, "mercado.db"))
        cls.srv.iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.srv.detener()

    def pedir(self, metodo, ruta, cuerpo=None, crudo=None):
        datos = crudo if crudo is not None else (json.dumps(cuerpo).encode() if cuerpo is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.puerto}{ruta}", data=datos, method=metodo,
                                     headers={"Content-Type": "application/json"} if datos is not None else {})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", ""), e.read()

    def json_de(self, cuerpo):
        try:
            return json.loads(cuerpo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.fail(f"La respuesta no es JSON válido: {cuerpo[:200]!r}")

    def crear(self, nombre="Arroz", precio=12.5, stock=3):
        status, _t, cuerpo = self.pedir("POST", "/api/productos", {"nombre": nombre, "precio": precio, "stock": stock})
        self.assertEqual(status, 201, cuerpo[:300])
        dato = self.json_de(cuerpo)
        self.assertIn("id", dato)
        return dato


class TestFrontend(BaseMercado):
    def test_01_raiz_entrega_html(self):
        status, tipo, cuerpo = self.pedir("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", tipo)
        self.assertIn(b"<html", cuerpo.lower())

    def test_02_css_con_mime_y_contenido(self):
        status, tipo, cuerpo = self.pedir("GET", "/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", tipo)
        self.assertTrue(cuerpo.strip())
        self.assertNotIn(b"<html", cuerpo.lower())                # no es la página disfrazada de CSS

    def test_03_js_con_mime_y_contenido(self):
        status, tipo, cuerpo = self.pedir("GET", "/script.js")
        self.assertEqual(status, 200)
        self.assertTrue("javascript" in tipo or "ecmascript" in tipo, tipo)
        self.assertTrue(cuerpo.strip())
        self.assertNotIn(b"<html", cuerpo.lower())

    def test_04_raiz_sobrevive_a_assets_y_enlaza_recursos_cargables(self):
        for ruta in ("/style.css", "/script.js", "/no-existe.css"):
            self.pedir("GET", ruta)
        status, tipo, cuerpo = self.pedir("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", tipo)
        html = cuerpo.decode("utf-8", "replace")
        self.assertIn("style.css", html)
        self.assertIn("script.js", html)


class TestApi(BaseMercado):
    def test_05_crear_y_listar_devuelve_un_array(self):
        creado = self.crear("Leche", 9.9, 5)
        status, tipo, cuerpo = self.pedir("GET", "/api/productos")
        self.assertEqual(status, 200)
        self.assertIn("application/json", tipo)
        lista = self.json_de(cuerpo)
        self.assertIsInstance(lista, list, "el contrato es una LISTA, no un objeto envoltorio")
        self.assertIn(creado["id"], [p.get("id") for p in lista])

    def test_06_obtener_por_id_y_404(self):
        creado = self.crear("Pan", 3, 10)
        status, _t, cuerpo = self.pedir("GET", f"/api/productos/{creado['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(self.json_de(cuerpo)["nombre"], "Pan")
        self.assertEqual(self.pedir("GET", "/api/productos/999999")[0], 404)

    def test_07_editar(self):
        creado = self.crear("Yerba", 20, 1)
        status, _t, cuerpo = self.pedir("PUT", f"/api/productos/{creado['id']}", {"nombre": "Yerba", "precio": 25, "stock": 4})
        self.assertEqual(status, 200, cuerpo[:300])
        dato = self.json_de(self.pedir("GET", f"/api/productos/{creado['id']}")[2])
        self.assertEqual((dato["precio"], dato["stock"]), (25, 4))

    def test_08_eliminar(self):
        creado = self.crear("Azúcar", 7, 2)
        self.assertIn(self.pedir("DELETE", f"/api/productos/{creado['id']}")[0], (200, 204))
        self.assertEqual(self.pedir("GET", f"/api/productos/{creado['id']}")[0], 404)

    def test_09_validaciones_devuelven_400_con_error(self):
        for cuerpo in ({"precio": 3, "stock": 1}, {"nombre": "", "precio": 3, "stock": 1},
                       {"nombre": "X", "precio": -1, "stock": 1}, {"nombre": "X", "precio": 1, "stock": -5}):
            status, _t, resp = self.pedir("POST", "/api/productos", cuerpo)
            self.assertEqual(status, 400, f"{cuerpo} → {status}")
            self.assertIn("error", self.json_de(resp))
        status, _t, _r = self.pedir("POST", "/api/productos", crudo=b"{no es json")
        self.assertEqual(status, 400)

    def test_10_rutas_desconocidas_y_traversal(self):
        self.assertEqual(self.pedir("GET", "/api/nada")[0], 404)
        status, _t, cuerpo = self.pedir("GET", "/../app.py")
        self.assertNotIn(b"import", cuerpo)                        # nunca sirve el código del servidor
        status, _t, cuerpo = self.pedir("GET", "/%2e%2e/app.py")
        self.assertNotIn(b"import", cuerpo)

    def test_11_altas_concurrentes_sin_perder_datos(self):
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            ids = list(ex.map(lambda i: self.crear(f"Item{i}", i + 1, i)["id"], range(12)))
        self.assertEqual(len(set(ids)), 12)
        lista = self.json_de(self.pedir("GET", "/api/productos")[2])
        self.assertTrue(set(ids) <= {p["id"] for p in lista})


class TestPersistencia(unittest.TestCase):
    def test_12_los_datos_sobreviven_al_reinicio(self):
        tmp = tempfile.mkdtemp(prefix="mercado_eval_")
        db = os.path.join(tmp, "mercado.db")
        srv = Servidor(db)
        srv.iniciar()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{srv.puerto}/api/productos", method="POST",
                                         data=json.dumps({"nombre": "Fideos", "precio": 4, "stock": 9}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                self.assertEqual(r.status, 201)
        finally:
            srv.detener()
        srv2 = Servidor(db)
        srv2.iniciar()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{srv2.puerto}/api/productos", timeout=8) as r:
                nombres = [p["nombre"] for p in json.loads(r.read())]
            self.assertIn("Fideos", nombres)
            with urllib.request.urlopen(f"http://127.0.0.1:{srv2.puerto}/", timeout=8) as r:
                self.assertIn("text/html", r.headers.get("Content-Type", ""))
        finally:
            srv2.detener()


if __name__ == "__main__":
    unittest.main()
