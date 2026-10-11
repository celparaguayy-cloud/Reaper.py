"""
MercadoControl — IMPLEMENTACIÓN DE REFERENCIA escrita por Claude Code para validar el evaluador independiente.
NO la generó REAPER y no prueba que REAPER construya MercadoControl: sirve para demostrar que el evaluador
puede aprobar una app correcta (y que, por lo tanto, sus rechazos a otras apps son fallos reales de esas apps).
Solo stdlib: http.server + sqlite3 (apto para Termux sin root).
"""
import json
import os
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

RAIZ_WEB = (Path(__file__).resolve().parent / "web").resolve()
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml"}
RE_ID = re.compile(r"^/api/productos/(\d+)$")


def conectar(db_path):
    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def preparar_base(db_path):
    with conectar(db_path) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS productos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "nombre TEXT NOT NULL, precio REAL NOT NULL, stock INTEGER NOT NULL)")


def validar(datos):
    if not isinstance(datos, dict):
        return "el cuerpo debe ser un objeto JSON"
    nombre = datos.get("nombre")
    if not isinstance(nombre, str) or not nombre.strip():
        return "nombre es obligatorio"
    precio, stock = datos.get("precio"), datos.get("stock", 0)
    if isinstance(precio, bool) or not isinstance(precio, (int, float)) or precio < 0:
        return "precio debe ser un número >= 0"
    if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
        return "stock debe ser un entero >= 0"
    return None


class Manejador(BaseHTTPRequestHandler):
    server_version = "MercadoControl/1.0"

    def log_message(self, formato, *args):
        pass

    # ---------------------------------------------------------------- utilidades
    def _enviar(self, status, cuerpo=b"", tipo="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _json(self, status, dato):
        self._enviar(status, json.dumps(dato, ensure_ascii=False).encode("utf-8"))

    def _leer_json(self):
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > 100_000:
            raise ValueError("cuerpo demasiado grande")
        return json.loads(self.rfile.read(largo).decode("utf-8") or "null")

    def _db(self):
        return conectar(self.server.db_path)

    # ---------------------------------------------------------------- estáticos
    def _estatico(self, ruta):
        relativa = "index.html" if ruta in ("", "/") else unquote(ruta).lstrip("/")
        destino = (RAIZ_WEB / relativa).resolve()
        if RAIZ_WEB not in destino.parents or not destino.is_file():     # fuera de web/ o inexistente
            return self._json(404, {"error": "no encontrado"})
        self._enviar(200, destino.read_bytes(), MIME.get(destino.suffix, "application/octet-stream"))

    # ---------------------------------------------------------------- verbos
    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta == "/api/productos":
            with self._db() as con:
                filas = [dict(f) for f in con.execute("SELECT * FROM productos ORDER BY id")]
            return self._json(200, filas)
        m = RE_ID.match(ruta)
        if m:
            with self._db() as con:
                fila = con.execute("SELECT * FROM productos WHERE id = ?", (int(m.group(1)),)).fetchone()
            return self._json(200, dict(fila)) if fila else self._json(404, {"error": "producto inexistente"})
        if ruta.startswith("/api/"):
            return self._json(404, {"error": "ruta inexistente"})
        return self._estatico(ruta)

    def do_POST(self):
        if urlparse(self.path).path != "/api/productos":
            return self._json(404, {"error": "ruta inexistente"})
        try:
            datos = self._leer_json()
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "JSON inválido"})
        error = validar(datos)
        if error:
            return self._json(400, {"error": error})
        with self._db() as con:
            cur = con.execute("INSERT INTO productos (nombre, precio, stock) VALUES (?, ?, ?)",
                              (datos["nombre"].strip(), datos["precio"], datos.get("stock", 0)))
            nuevo = dict(con.execute("SELECT * FROM productos WHERE id = ?", (cur.lastrowid,)).fetchone())
        self._json(201, nuevo)

    def do_PUT(self):
        m = RE_ID.match(urlparse(self.path).path)
        if not m:
            return self._json(404, {"error": "ruta inexistente"})
        try:
            datos = self._leer_json()
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "JSON inválido"})
        error = validar(datos)
        if error:
            return self._json(400, {"error": error})
        with self._db() as con:
            cur = con.execute("UPDATE productos SET nombre = ?, precio = ?, stock = ? WHERE id = ?",
                              (datos["nombre"].strip(), datos["precio"], datos.get("stock", 0), int(m.group(1))))
            if cur.rowcount == 0:
                return self._json(404, {"error": "producto inexistente"})
            fila = dict(con.execute("SELECT * FROM productos WHERE id = ?", (int(m.group(1)),)).fetchone())
        self._json(200, fila)

    def do_DELETE(self):
        m = RE_ID.match(urlparse(self.path).path)
        if not m:
            return self._json(404, {"error": "ruta inexistente"})
        with self._db() as con:
            cur = con.execute("DELETE FROM productos WHERE id = ?", (int(m.group(1)),))
        if cur.rowcount == 0:
            return self._json(404, {"error": "producto inexistente"})
        self._enviar(204)


class Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, direccion, db_path):
        self.db_path = db_path                 # se fija ANTES de aceptar conexiones (antes: AttributeError)
        preparar_base(db_path)
        super().__init__(direccion, Manejador)


def main():
    puerto = int(os.environ.get("PORT", "8765"))
    db_path = os.environ.get("MERCADO_DB", str(Path(__file__).resolve().parent / "mercado.db"))
    servidor = Servidor(("127.0.0.1", puerto), db_path)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
