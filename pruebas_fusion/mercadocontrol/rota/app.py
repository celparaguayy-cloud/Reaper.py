"""
MercadoControl ROTO a propósito (Claude Code) — reproduce los defectos reportados en la especificación de la
fusión para comprobar que el evaluador y el gate de REAPER los RECHAZAN (sin falsos verdes):
  - la "reparación" de /style.css y /script.js rompió la raíz: "/" busca un archivo y devuelve 404
  - CSS servido como text/plain y JS como text/html (MIME incorrecto)
  - GET /api/productos devuelve {"productos": [...]} en vez de la lista del contrato
  - ThreadedHTTPServer.db_path no existe (se fija con otro nombre) → 500 en la API
"""
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"


class ThreadedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _enviar(self, status, cuerpo, tipo):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path.startswith("/api/productos"):
            con = sqlite3.connect(self.server.db_path)          # AttributeError: el servidor guardó "db"
            filas = con.execute("SELECT id, nombre, precio, stock FROM productos").fetchall()
            return self._enviar(200, json.dumps({"productos": filas}).encode(), "application/json")
        archivo = WEB / self.path.lstrip("/")                  # "/" → carpeta web/ → no es archivo
        if not archivo.is_file():
            return self._enviar(404, b"no encontrado", "text/plain")
        tipo = "text/plain" if archivo.suffix == ".css" else "text/html"
        self._enviar(200, archivo.read_bytes(), tipo)

    def do_POST(self):
        con = sqlite3.connect(self.server.db_path)
        datos = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        con.execute("INSERT INTO productos (nombre, precio, stock) VALUES (?, ?, ?)",
                    (datos["nombre"], datos["precio"], datos["stock"]))
        con.commit()
        self._enviar(200, b"{}", "application/json")


def main():
    servidor = ThreadedHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8765"))), Manejador)
    servidor.db = os.environ.get("MERCADO_DB", "mercado.db")
    con = sqlite3.connect(servidor.db)
    con.execute("CREATE TABLE IF NOT EXISTS productos (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, stock INTEGER)")
    con.commit()
    servidor.serve_forever()


if __name__ == "__main__":
    main()
