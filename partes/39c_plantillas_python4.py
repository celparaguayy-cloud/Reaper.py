"""
Plantillas de Python (cuarta tanda):

  api-usuarios   API REST con registro, login (PBKDF2), tokens con vencimiento y SQLite (http.server)
  presupuesto    finanzas personales: movimientos, presupuesto por categoría, alertas y CSV (Decimal)
  monitor        monitor del sistema leyendo /proc (CPU, memoria, uptime, batería en Termux) con fixtures
  chatbot        chatbot de reglas con intenciones (regex), contexto y respuestas reproducibles
  descargas      gestor de descargas con cola, reintentos con espera creciente y progreso (red inyectable)
  horario        planificador de horarios: asigna actividades a franjas sin choques (backtracking)
"""

# ======================================================================
# api-usuarios
# ======================================================================
registrar_plantilla(
    "api-usuarios",
    "API REST de usuarios: registro, login con PBKDF2, tokens con vencimiento, perfil protegido y SQLite. Solo stdlib.",
    "python",
    {
        "app/__init__.py": "",
        "app/seguridad.py": '''
            """Contraseñas (PBKDF2 con sal) y tokens de sesión con vencimiento."""
            from __future__ import annotations

            import base64
            import hashlib
            import hmac
            import secrets
            import time

            ITERACIONES = 120_000


            def hashear(password: str, iteraciones: int = ITERACIONES) -> str:
                sal = secrets.token_bytes(16)
                clave = hashlib.pbkdf2_hmac("sha256", password.encode(), sal, iteraciones)
                return f"{iteraciones}${base64.b64encode(sal).decode()}${base64.b64encode(clave).decode()}"


            def verificar(password: str, guardado: str) -> bool:
                try:
                    iteraciones, sal, clave = guardado.split("$")
                    calculada = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(sal), int(iteraciones))
                except (ValueError, TypeError):
                    return False
                return hmac.compare_digest(calculada, base64.b64decode(clave))


            def nuevo_token() -> str:
                return secrets.token_urlsafe(32)


            def vence_en(segundos: int, ahora: float | None = None) -> float:
                return (time.time() if ahora is None else ahora) + segundos


            def validar_password(password: str) -> str | None:
                """Devuelve el problema (o None si está bien)."""
                if len(password) < 8:
                    return "la contraseña necesita al menos 8 caracteres"
                if password.isdigit() or password.isalpha():
                    return "la contraseña tiene que mezclar letras y números"
                return None
        ''',
        "app/datos.py": '''
            """Usuarios y sesiones en SQLite."""
            from __future__ import annotations

            import re
            import sqlite3
            import threading
            import time

            from .seguridad import hashear, nuevo_token, validar_password, vence_en, verificar

            DURACION_SESION = 3600
            _EMAIL = re.compile(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")


            class ErrorDatos(Exception):
                def __init__(self, mensaje: str, estado: int = 400):
                    super().__init__(mensaje)
                    self.estado = estado


            class Repositorio:
                def __init__(self, ruta: str = ":memory:", reloj=time.time):
                    self.con = sqlite3.connect(ruta, check_same_thread=False)
                    self.con.row_factory = sqlite3.Row
                    self.lock = threading.Lock()
                    self.reloj = reloj
                    with self.con:
                        self.con.executescript("""
                            CREATE TABLE IF NOT EXISTS usuarios (
                                id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                                nombre TEXT NOT NULL, hash TEXT NOT NULL, creado REAL NOT NULL);
                            CREATE TABLE IF NOT EXISTS sesiones (
                                token TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                                vence REAL NOT NULL);
                        """)

                def registrar(self, email: str, nombre: str, password: str) -> dict:
                    email, nombre = (email or "").strip().lower(), (nombre or "").strip()
                    if not _EMAIL.match(email):
                        raise ErrorDatos("email inválido")
                    if not nombre:
                        raise ErrorDatos("el nombre es obligatorio")
                    problema = validar_password(password or "")
                    if problema:
                        raise ErrorDatos(problema)
                    with self.lock:
                        try:
                            with self.con:
                                cur = self.con.execute(
                                    "INSERT INTO usuarios (email, nombre, hash, creado) VALUES (?, ?, ?, ?)",
                                    (email, nombre, hashear(password), self.reloj()))
                        except sqlite3.IntegrityError:
                            raise ErrorDatos("ya existe una cuenta con ese email", 409) from None
                    return {"id": cur.lastrowid, "email": email, "nombre": nombre}

                def login(self, email: str, password: str) -> dict:
                    with self.lock:
                        fila = self.con.execute("SELECT * FROM usuarios WHERE email = ?", ((email or "").strip(),)).fetchone()
                    if fila is None or not verificar(password or "", fila["hash"]):
                        raise ErrorDatos("email o contraseña incorrectos", 401)   # mismo mensaje: no revela cuál falló
                    token = nuevo_token()
                    with self.lock, self.con:
                        self.con.execute("INSERT INTO sesiones VALUES (?, ?, ?)",
                                         (token, fila["id"], vence_en(DURACION_SESION, self.reloj())))
                    return {"token": token, "vence_en": DURACION_SESION}

                def usuario_de(self, token: str) -> dict:
                    with self.lock:
                        fila = self.con.execute(
                            "SELECT u.id, u.email, u.nombre, s.vence FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id "
                            "WHERE s.token = ?", (token or "",)).fetchone()
                    if fila is None:
                        raise ErrorDatos("token inválido", 401)
                    if fila["vence"] < self.reloj():
                        self.logout(token)
                        raise ErrorDatos("la sesión venció: volvé a iniciar sesión", 401)
                    return {"id": fila["id"], "email": fila["email"], "nombre": fila["nombre"]}

                def logout(self, token: str) -> None:
                    with self.lock, self.con:
                        self.con.execute("DELETE FROM sesiones WHERE token = ?", (token,))

                def cambiar_nombre(self, usuario_id: int, nombre: str) -> None:
                    nombre = (nombre or "").strip()
                    if not nombre:
                        raise ErrorDatos("el nombre es obligatorio")
                    with self.lock, self.con:
                        self.con.execute("UPDATE usuarios SET nombre = ? WHERE id = ?", (nombre, usuario_id))
        ''',
        "app/servidor.py": '''
            """
            API JSON:
              POST /registro   {"email", "nombre", "password"}         → 201
              POST /login      {"email", "password"}                   → {"token", "vence_en"}
              GET  /yo         Authorization: Bearer <token>           → perfil
              PATCH /yo        {"nombre"}  (con token)                 → perfil
              POST /logout     (con token)                             → 204
            """
            from __future__ import annotations

            import json
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

            from .datos import ErrorDatos, Repositorio

            MAX_CUERPO = 64 * 1024


            def crear_servidor(repo: Repositorio, host: str = "127.0.0.1", puerto: int = 8000) -> ThreadingHTTPServer:
                class Manejador(BaseHTTPRequestHandler):
                    def log_message(self, *args):  # silencioso (los tests no se llenan de logs)
                        pass

                    def _responder(self, estado: int, cuerpo: dict | None = None) -> None:
                        datos = b"" if cuerpo is None else json.dumps(cuerpo, ensure_ascii=False).encode()
                        self.send_response(estado)
                        if cuerpo is not None:
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Content-Length", str(len(datos)))
                        self.end_headers()
                        self.wfile.write(datos)

                    def _json(self) -> dict:
                        largo = int(self.headers.get("Content-Length") or 0)
                        if largo > MAX_CUERPO:
                            raise ErrorDatos("cuerpo demasiado grande", 413)
                        try:
                            datos = json.loads(self.rfile.read(largo) or b"{}")
                        except ValueError:
                            raise ErrorDatos("JSON inválido") from None
                        if not isinstance(datos, dict):
                            raise ErrorDatos("se esperaba un objeto JSON")
                        return datos

                    def _token(self) -> str:
                        cabecera = self.headers.get("Authorization", "")
                        if not cabecera.startswith("Bearer "):
                            raise ErrorDatos("falta el token (Authorization: Bearer ...)", 401)
                        return cabecera[7:].strip()

                    def _manejar(self, metodo: str) -> None:
                        try:
                            ruta = self.path.split("?")[0].rstrip("/") or "/"
                            if metodo == "POST" and ruta == "/registro":
                                d = self._json()
                                self._responder(201, repo.registrar(d.get("email"), d.get("nombre"), d.get("password")))
                            elif metodo == "POST" and ruta == "/login":
                                d = self._json()
                                self._responder(200, repo.login(d.get("email"), d.get("password")))
                            elif ruta == "/yo" and metodo == "GET":
                                self._responder(200, repo.usuario_de(self._token()))
                            elif ruta == "/yo" and metodo == "PATCH":
                                usuario = repo.usuario_de(self._token())
                                repo.cambiar_nombre(usuario["id"], self._json().get("nombre"))
                                self._responder(200, repo.usuario_de(self._token()))
                            elif metodo == "POST" and ruta == "/logout":
                                repo.logout(self._token())
                                self._responder(204)
                            elif ruta == "/salud":
                                self._responder(200, {"estado": "ok"})
                            else:
                                self._responder(404, {"error": "ruta inexistente"})
                        except ErrorDatos as e:
                            self._responder(e.estado, {"error": str(e)})

                    def do_GET(self):
                        self._manejar("GET")

                    def do_POST(self):
                        self._manejar("POST")

                    def do_PATCH(self):
                        self._manejar("PATCH")

                return ThreadingHTTPServer((host, puerto), Manejador)


            def main() -> None:
                import os
                repo = Repositorio(os.environ.get("USUARIOS_DB", "usuarios.db"))
                servidor = crear_servidor(repo, puerto=int(os.environ.get("PORT", "8000")))
                print(f"API en http://127.0.0.1:{servidor.server_address[1]} (Ctrl+C para salir)", flush=True)
                try:
                    servidor.serve_forever()
                except KeyboardInterrupt:
                    pass


            if __name__ == "__main__":
                main()
        ''',
        "tests/test_api.py": '''
            import json
            import threading
            import unittest
            import urllib.error
            import urllib.request

            from app.datos import ErrorDatos, Repositorio
            from app.seguridad import hashear, validar_password, verificar
            from app.servidor import crear_servidor


            class TestSeguridad(unittest.TestCase):
                def test_hash(self):
                    h = hashear("clave123", iteraciones=1000)
                    self.assertTrue(verificar("clave123", h))
                    self.assertFalse(verificar("clave124", h))
                    self.assertFalse(verificar("x", "roto"))

                def test_politica(self):
                    self.assertIsNotNone(validar_password("corta1"))
                    self.assertIsNotNone(validar_password("solamenteletras"))
                    self.assertIsNone(validar_password("mate2024"))


            class TestRepositorio(unittest.TestCase):
                def setUp(self):
                    self.t = [1000.0]
                    self.repo = Repositorio(reloj=lambda: self.t[0])
                    self.repo.registrar("Ana@Mail.com", "Ana", "mate2024")

                def test_login_y_token(self):
                    token = self.repo.login("ana@mail.com", "mate2024")["token"]
                    self.assertEqual(self.repo.usuario_de(token)["nombre"], "Ana")

                def test_errores(self):
                    with self.assertRaises(ErrorDatos) as cm:
                        self.repo.registrar("ana@mail.com", "Otra", "mate2024")
                    self.assertEqual(cm.exception.estado, 409)
                    with self.assertRaises(ErrorDatos) as cm:
                        self.repo.login("ana@mail.com", "mal")
                    self.assertEqual(cm.exception.estado, 401)
                    with self.assertRaises(ErrorDatos):
                        self.repo.registrar("no-es-email", "X", "mate2024")

                def test_sesion_vence(self):
                    token = self.repo.login("ana@mail.com", "mate2024")["token"]
                    self.t[0] += 3601
                    with self.assertRaises(ErrorDatos) as cm:
                        self.repo.usuario_de(token)
                    self.assertIn("venció", str(cm.exception))


            class TestServidor(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    cls.servidor = crear_servidor(Repositorio(), puerto=0)
                    threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()
                    cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"

                @classmethod
                def tearDownClass(cls):
                    cls.servidor.shutdown()
                    cls.servidor.server_close()

                def pedir(self, metodo, ruta, cuerpo=None, token=None):
                    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
                    req = urllib.request.Request(self.base + ruta, data=datos, method=metodo)
                    req.add_header("Content-Type", "application/json")
                    if token:
                        req.add_header("Authorization", f"Bearer {token}")
                    try:
                        with urllib.request.urlopen(req, timeout=5) as r:
                            texto = r.read()
                            return r.status, json.loads(texto) if texto else None
                    except urllib.error.HTTPError as e:
                        return e.code, json.loads(e.read() or b"null")

                def test_flujo_completo(self):
                    estado, u = self.pedir("POST", "/registro", {"email": "luis@x.com", "nombre": "Luis", "password": "clave2024"})
                    self.assertEqual((estado, u["nombre"]), (201, "Luis"))
                    estado, sesion = self.pedir("POST", "/login", {"email": "luis@x.com", "password": "clave2024"})
                    self.assertEqual(estado, 200)
                    token = sesion["token"]
                    self.assertEqual(self.pedir("GET", "/yo", token=token)[1]["email"], "luis@x.com")
                    self.assertEqual(self.pedir("PATCH", "/yo", {"nombre": "Luis M."}, token)[1]["nombre"], "Luis M.")
                    self.assertEqual(self.pedir("POST", "/logout", token=token)[0], 204)
                    self.assertEqual(self.pedir("GET", "/yo", token=token)[0], 401)

                def test_sin_token_y_rutas(self):
                    self.assertEqual(self.pedir("GET", "/yo")[0], 401)
                    self.assertEqual(self.pedir("GET", "/nada")[0], 404)
                    self.assertEqual(self.pedir("GET", "/salud")[1], {"estado": "ok"})
                    estado, error = self.pedir("POST", "/registro", {"email": "a@b.co", "nombre": "A", "password": "123"})
                    self.assertEqual(estado, 400)
                    self.assertIn("8 caracteres", error["error"])


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 -m app.servidor",
    etiquetas=("api", "usuarios", "login", "auth", "tokens", "sqlite", "rest"),
)

# ======================================================================
# presupuesto
# ======================================================================
registrar_plantilla(
    "presupuesto",
    "Finanzas personales: ingresos y gastos con Decimal, presupuesto mensual por categoría, alertas y exportación CSV.",
    "python",
    {
        "finanzas.py": '''
            """__TITULO__: presupuesto mensual con alertas (dinero siempre en Decimal)."""
            from __future__ import annotations

            import csv
            import io
            import json
            from dataclasses import dataclass
            from datetime import date
            from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
            from pathlib import Path

            CENTAVO = Decimal("0.01")


            def dinero(valor) -> Decimal:
                texto = str(valor).strip().replace("$", "").replace(" ", "")
                if "," in texto:
                    texto = texto.replace(".", "").replace(",", ".")
                try:
                    d = Decimal(texto)
                except InvalidOperation:
                    raise ValueError(f"monto inválido: {valor!r}") from None
                if not d.is_finite():
                    raise ValueError(f"monto inválido: {valor!r}")
                return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


            def formato(d: Decimal) -> str:
                signo = "-" if d < 0 else ""
                entero, _, decimales = f"{abs(d):.2f}".partition(".")
                miles = f"{int(entero):,}".replace(",", ".")
                return f"{signo}${miles},{decimales}"


            @dataclass
            class Movimiento:
                fecha: date
                monto: Decimal          # positivo = ingreso, negativo = gasto
                categoria: str
                detalle: str = ""

                @property
                def mes(self) -> str:
                    return self.fecha.strftime("%Y-%m")


            class Finanzas:
                def __init__(self):
                    self.movimientos: list[Movimiento] = []
                    self.presupuesto: dict[str, Decimal] = {}

                def ingreso(self, monto, categoria: str = "sueldo", fecha: date | None = None, detalle: str = "") -> Movimiento:
                    m = Movimiento(fecha or date.today(), abs(dinero(monto)), categoria.strip().lower(), detalle)
                    self.movimientos.append(m)
                    return m

                def gasto(self, monto, categoria: str, fecha: date | None = None, detalle: str = "") -> Movimiento:
                    if not categoria.strip():
                        raise ValueError("el gasto necesita una categoría")
                    m = Movimiento(fecha or date.today(), -abs(dinero(monto)), categoria.strip().lower(), detalle)
                    self.movimientos.append(m)
                    return m

                def fijar_presupuesto(self, categoria: str, monto) -> None:
                    valor = dinero(monto)
                    if valor <= 0:
                        raise ValueError("el presupuesto tiene que ser positivo")
                    self.presupuesto[categoria.strip().lower()] = valor

                def del_mes(self, mes: str) -> list[Movimiento]:
                    return [m for m in self.movimientos if m.mes == mes]

                def balance(self, mes: str | None = None) -> Decimal:
                    movs = self.del_mes(mes) if mes else self.movimientos
                    return sum((m.monto for m in movs), Decimal("0.00"))

                def gastos_por_categoria(self, mes: str) -> dict[str, Decimal]:
                    totales: dict[str, Decimal] = {}
                    for m in self.del_mes(mes):
                        if m.monto < 0:
                            totales[m.categoria] = totales.get(m.categoria, Decimal("0.00")) - m.monto
                    return dict(sorted(totales.items(), key=lambda kv: -kv[1]))

                def alertas(self, mes: str, umbral: Decimal = Decimal("0.8")) -> list[str]:
                    avisos = []
                    gastado = self.gastos_por_categoria(mes)
                    for categoria, limite in sorted(self.presupuesto.items()):
                        usado = gastado.get(categoria, Decimal("0.00"))
                        if usado > limite:
                            avisos.append(f"{categoria}: te pasaste por {formato(usado - limite)} (límite {formato(limite)})")
                        elif usado >= limite * umbral:
                            porcentaje = (usado / limite * 100).quantize(Decimal("1"))
                            avisos.append(f"{categoria}: usaste el {porcentaje}% ({formato(usado)} de {formato(limite)})")
                    return avisos

                def a_csv(self) -> str:
                    salida = io.StringIO()
                    w = csv.writer(salida)
                    w.writerow(["fecha", "monto", "categoria", "detalle"])
                    for m in sorted(self.movimientos, key=lambda m: m.fecha):
                        w.writerow([m.fecha.isoformat(), f"{m.monto:.2f}", m.categoria, m.detalle])
                    return salida.getvalue()

                def importar_csv(self, texto: str) -> int:
                    n = 0
                    for fila in csv.DictReader(io.StringIO(texto)):
                        monto = dinero(fila["monto"])
                        mov = Movimiento(date.fromisoformat(fila["fecha"]), monto, fila["categoria"].strip().lower(),
                                         fila.get("detalle", ""))
                        self.movimientos.append(mov)
                        n += 1
                    return n

                def guardar(self, ruta: Path) -> None:
                    datos = {"presupuesto": {k: str(v) for k, v in self.presupuesto.items()}, "movimientos": self.a_csv()}
                    tmp = Path(ruta).with_suffix(".tmp")
                    tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(ruta)

                @classmethod
                def cargar(cls, ruta: Path) -> "Finanzas":
                    f = cls()
                    if Path(ruta).exists():
                        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
                        f.presupuesto = {k: Decimal(v) for k, v in datos.get("presupuesto", {}).items()}
                        f.importar_csv(datos.get("movimientos", ""))
                    return f


            def main(argv: list[str] | None = None) -> int:
                import os
                import sys
                args = sys.argv[1:] if argv is None else argv
                ruta = Path(os.environ.get("FINANZAS_ARCHIVO", Path.home() / ".__PROYECTO__.json"))
                f = Finanzas.cargar(ruta)
                mes = date.today().strftime("%Y-%m")
                try:
                    if len(args) >= 3 and args[0] == "gasto":
                        f.gasto(args[1], args[2], detalle=" ".join(args[3:]))
                    elif len(args) >= 2 and args[0] == "ingreso":
                        f.ingreso(args[1], args[2] if len(args) > 2 else "sueldo")
                    elif len(args) == 3 and args[0] == "presupuesto":
                        f.fijar_presupuesto(args[1], args[2])
                    elif args and args[0] == "exportar":
                        sys.stdout.write(f.a_csv())
                        return 0
                    elif not args or args[0] == "resumen":
                        print(f"Balance de {mes}: {formato(f.balance(mes))}")
                        for cat, total in f.gastos_por_categoria(mes).items():
                            print(f"  {cat:<15} {formato(total):>14}")
                        for aviso in f.alertas(mes):
                            print("⚠", aviso)
                        return 0
                    else:
                        print("uso: finanzas.py [gasto MONTO CATEGORIA [detalle] | ingreso MONTO [categoria] | "
                              "presupuesto CATEGORIA MONTO | resumen | exportar]")
                        return 2
                except ValueError as e:
                    print(f"error: {e}")
                    return 1
                f.guardar(ruta)
                print("listo")
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "tests/test_finanzas.py": '''
            import tempfile
            import unittest
            from datetime import date
            from decimal import Decimal
            from pathlib import Path

            from finanzas import Finanzas, dinero, formato

            MARZO = date(2024, 3, 5)


            class TestDinero(unittest.TestCase):
                def test_parseo(self):
                    self.assertEqual(dinero("1.234,56"), Decimal("1234.56"))
                    self.assertEqual(dinero("$ 10.005"), Decimal("10.01"))   # redondeo comercial
                    self.assertEqual(dinero(3), Decimal("3.00"))
                    with self.assertRaises(ValueError):
                        dinero("diez")

                def test_formato(self):
                    self.assertEqual(formato(Decimal("1234567.5")), "$1.234.567,50")
                    self.assertEqual(formato(Decimal("-20")), "-$20,00")


            class TestFinanzas(unittest.TestCase):
                def setUp(self):
                    self.f = Finanzas()
                    self.f.ingreso("500000", fecha=MARZO)
                    self.f.gasto("120000,50", "Comida", MARZO)
                    self.f.gasto("30000", "transporte", MARZO)
                    self.f.gasto("99999", "comida", date(2024, 2, 1))

                def test_balance_por_mes(self):
                    self.assertEqual(self.f.balance("2024-03"), Decimal("349999.50"))
                    self.assertEqual(self.f.balance(), Decimal("250000.50"))

                def test_gastos_por_categoria(self):
                    self.assertEqual(self.f.gastos_por_categoria("2024-03"),
                                     {"comida": Decimal("120000.50"), "transporte": Decimal("30000.00")})

                def test_alertas(self):
                    self.f.fijar_presupuesto("comida", "100000")
                    self.f.fijar_presupuesto("transporte", "35000")
                    self.f.fijar_presupuesto("ocio", "1000")
                    alertas = self.f.alertas("2024-03")
                    self.assertEqual(len(alertas), 2)
                    self.assertIn("comida: te pasaste por $20.000,50", alertas[0])
                    self.assertIn("transporte: usaste el 86%", alertas[1])
                    with self.assertRaises(ValueError):
                        self.f.fijar_presupuesto("x", "0")

                def test_guardar_y_cargar(self):
                    self.f.fijar_presupuesto("comida", "100000")
                    with tempfile.TemporaryDirectory() as d:
                        ruta = Path(d) / "f.json"
                        self.f.guardar(ruta)
                        otra = Finanzas.cargar(ruta)
                    self.assertEqual(otra.balance(), self.f.balance())
                    self.assertEqual(otra.presupuesto, {"comida": Decimal("100000.00")})

                def test_gasto_sin_categoria(self):
                    with self.assertRaises(ValueError):
                        self.f.gasto("10", "  ")


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 finanzas.py resumen",
    etiquetas=("finanzas", "presupuesto", "gastos", "dinero", "decimal"),
)

# ======================================================================
# monitor
# ======================================================================
registrar_plantilla(
    "monitor",
    "Monitor del sistema para Termux/Linux: CPU, memoria, uptime, disco y batería leyendo /proc y termux-api (con fixtures en tests).",
    "python",
    {
        "monitor.py": '''
            """__TITULO__: estado del sistema sin dependencias (lee /proc; batería con termux-api si está)."""
            from __future__ import annotations

            import json
            import shutil
            import subprocess
            import time
            from pathlib import Path

            PROC = Path("/proc")


            def leer(ruta: Path) -> str:
                try:
                    return ruta.read_text(encoding="utf-8")
                except OSError:
                    return ""


            def memoria(proc: Path = PROC) -> dict | None:
                datos = {}
                for linea in leer(proc / "meminfo").splitlines():
                    clave, _, valor = linea.partition(":")
                    partes = valor.split()
                    if partes and partes[0].isdigit():
                        datos[clave.strip()] = int(partes[0]) * 1024
                if "MemTotal" not in datos:
                    return None
                disponible = datos.get("MemAvailable", datos.get("MemFree", 0))
                usada = datos["MemTotal"] - disponible
                return {"total": datos["MemTotal"], "usada": usada, "disponible": disponible,
                        "porcentaje": round(usada * 100 / datos["MemTotal"], 1)}


            def uptime(proc: Path = PROC) -> float | None:
                texto = leer(proc / "uptime").split()
                try:
                    return float(texto[0])
                except (IndexError, ValueError):
                    return None


            def carga(proc: Path = PROC) -> tuple[float, float, float] | None:
                partes = leer(proc / "loadavg").split()
                try:
                    return float(partes[0]), float(partes[1]), float(partes[2])
                except (IndexError, ValueError):
                    return None


            def tiempos_cpu(proc: Path = PROC) -> tuple[int, int] | None:
                for linea in leer(proc / "stat").splitlines():
                    if linea.startswith("cpu "):
                        valores = [int(x) for x in linea.split()[1:]]
                        inactivo = valores[3] + (valores[4] if len(valores) > 4 else 0)
                        return sum(valores), inactivo
                return None


            def uso_cpu(antes: tuple[int, int] | None, despues: tuple[int, int] | None) -> float | None:
                if not antes or not despues:
                    return None
                total = despues[0] - antes[0]
                if total <= 0:
                    return 0.0
                return round((1 - (despues[1] - antes[1]) / total) * 100, 1)


            def disco(ruta: str = str(Path.home())) -> dict:
                total, usado, libre = shutil.disk_usage(ruta)
                return {"total": total, "usado": usado, "libre": libre, "porcentaje": round(usado * 100 / total, 1)}


            def bateria(ejecutar=subprocess.run) -> dict | None:
                if not shutil.which("termux-battery-status") and ejecutar is subprocess.run:
                    return None
                try:
                    r = ejecutar(["termux-battery-status"], capture_output=True, text=True, timeout=8)
                    datos = json.loads(r.stdout)
                except (OSError, ValueError, subprocess.SubprocessError):
                    return None
                return {"porcentaje": datos.get("percentage"), "estado": datos.get("status"),
                        "temperatura": datos.get("temperature")}


            def legible(n: float) -> str:
                for unidad in ("B", "KB", "MB", "GB", "TB"):
                    if n < 1024 or unidad == "TB":
                        return f"{n:.0f} {unidad}" if unidad == "B" else f"{n:.1f} {unidad}"
                    n /= 1024
                return f"{n:.1f} TB"


            def duracion(segundos: float) -> str:
                s = int(segundos)
                dias, s = divmod(s, 86400)
                horas, s = divmod(s, 3600)
                minutos = s // 60
                return (f"{dias}d " if dias else "") + f"{horas}h {minutos}m"


            def barra(porcentaje: float, ancho: int = 20) -> str:
                llenos = round(max(0.0, min(100.0, porcentaje)) / 100 * ancho)
                return "█" * llenos + "░" * (ancho - llenos)


            def informe(proc: Path = PROC, intervalo: float = 0.3, ruta_disco: str = str(Path.home())) -> str:
                lineas = []
                antes = tiempos_cpu(proc)
                if antes and intervalo:
                    time.sleep(intervalo)
                cpu = uso_cpu(antes, tiempos_cpu(proc))
                if cpu is not None:
                    lineas.append(f"CPU      {barra(cpu)} {cpu:5.1f}%")
                mem = memoria(proc)
                if mem:
                    lineas.append(f"Memoria  {barra(mem['porcentaje'])} {mem['porcentaje']:5.1f}%  "
                                  f"({legible(mem['usada'])} de {legible(mem['total'])})")
                d = disco(ruta_disco)
                lineas.append(f"Disco    {barra(d['porcentaje'])} {d['porcentaje']:5.1f}%  (libre {legible(d['libre'])})")
                c = carga(proc)
                if c:
                    lineas.append(f"Carga    {c[0]:.2f} {c[1]:.2f} {c[2]:.2f}")
                u = uptime(proc)
                if u is not None:
                    lineas.append(f"Encendido hace {duracion(u)}")
                b = bateria()
                if b and b["porcentaje"] is not None:
                    lineas.append(f"Batería  {barra(b['porcentaje'])} {b['porcentaje']:5}%  {b['estado']}")
                if not lineas:
                    return "No pude leer información del sistema."
                return "\\n".join(lineas)


            if __name__ == "__main__":
                import sys
                if "--vigilar" in sys.argv:
                    try:
                        while True:
                            print("\\033[2J\\033[H" + informe())
                            time.sleep(2)
                    except KeyboardInterrupt:
                        pass
                else:
                    print(informe())
        ''',
        "tests/test_monitor.py": '''
            import json
            import tempfile
            import unittest
            from pathlib import Path
            from types import SimpleNamespace

            import monitor

            MEMINFO = "MemTotal:        4000000 kB\\nMemFree:          500000 kB\\nMemAvailable:    1000000 kB\\n"
            STAT_1 = "cpu  100 0 100 800 0 0 0 0 0 0\\ncpu0 1 2 3 4\\n"
            STAT_2 = "cpu  150 0 150 900 0 0 0 0 0 0\\n"


            class TestMonitor(unittest.TestCase):
                def setUp(self):
                    self.tmp = tempfile.TemporaryDirectory()
                    self.proc = Path(self.tmp.name)
                    (self.proc / "meminfo").write_text(MEMINFO)
                    (self.proc / "uptime").write_text("93784.12 1000.0\\n")
                    (self.proc / "loadavg").write_text("0.50 0.75 1.00 1/200 3000\\n")
                    (self.proc / "stat").write_text(STAT_1)

                def tearDown(self):
                    self.tmp.cleanup()

                def test_memoria(self):
                    m = monitor.memoria(self.proc)
                    self.assertEqual(m["porcentaje"], 75.0)
                    self.assertEqual(m["total"], 4000000 * 1024)

                def test_cpu(self):
                    antes = monitor.tiempos_cpu(self.proc)
                    (self.proc / "stat").write_text(STAT_2)
                    self.assertEqual(monitor.uso_cpu(antes, monitor.tiempos_cpu(self.proc)), 50.0)
                    self.assertIsNone(monitor.uso_cpu(None, antes))

                def test_uptime_carga_y_formatos(self):
                    self.assertEqual(monitor.duracion(monitor.uptime(self.proc)), "1d 2h 3m")
                    self.assertEqual(monitor.carga(self.proc), (0.5, 0.75, 1.0))
                    self.assertEqual(monitor.legible(1536), "1.5 KB")
                    self.assertEqual(monitor.barra(50, 10), "█████░░░░░")

                def test_sin_proc(self):
                    vacio = self.proc / "no_existe"
                    self.assertIsNone(monitor.memoria(vacio))
                    self.assertIsNone(monitor.uptime(vacio))
                    self.assertIn("Disco", monitor.informe(vacio, intervalo=0, ruta_disco=self.tmp.name))

                def test_bateria_con_termux_simulado(self):
                    falso = lambda *a, **k: SimpleNamespace(stdout=json.dumps({"percentage": 80, "status": "CHARGING", "temperature": 30.1}))
                    self.assertEqual(monitor.bateria(falso)["estado"], "CHARGING")
                    roto = lambda *a, **k: SimpleNamespace(stdout="no json")
                    self.assertIsNone(monitor.bateria(roto))

                def test_informe_completo(self):
                    texto = monitor.informe(self.proc, intervalo=0, ruta_disco=self.tmp.name)
                    self.assertIn("Memoria", texto)
                    self.assertIn("Encendido hace 1d 2h 3m", texto)


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 monitor.py",
    etiquetas=("monitor", "sistema", "cpu", "memoria", "bateria", "termux"),
)

# ======================================================================
# chatbot
# ======================================================================
registrar_plantilla(
    "chatbot",
    "Chatbot de reglas: intenciones con regex, contexto de conversación (nombre, último tema) y respuestas reproducibles.",
    "python",
    {
        "bot.py": '''
            """__TITULO__: chatbot de reglas sin IA (útil como base o para atención simple)."""
            from __future__ import annotations

            import random
            import re
            import unicodedata
            from dataclasses import dataclass, field
            from datetime import datetime
            from typing import Callable


            def normalizar(texto: str) -> str:
                sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
                return re.sub(r"\\s+", " ", sin_tildes.lower()).strip()


            @dataclass
            class Contexto:
                nombre: str | None = None
                ultimo_tema: str | None = None
                turnos: int = 0
                datos: dict = field(default_factory=dict)


            @dataclass
            class Intencion:
                nombre: str
                patrones: list
                respuestas: list
                accion: Callable | None = None   # accion(match, contexto) -> str | None
                con_tildes: bool = False         # buscar en el texto original (conserva tildes, p. ej. nombres)

                def coincide(self, texto: str, original: str = ""):
                    objetivo = original if self.con_tildes else texto
                    for p in self.patrones:
                        m = re.search(p, objetivo)
                        if m:
                            return m
                    return None


            class Bot:
                def __init__(self, semilla: int | None = None, reloj=datetime.now):
                    self.azar = random.Random(semilla)
                    self.reloj = reloj
                    self.contexto = Contexto()
                    self.intenciones: list[Intencion] = []
                    self._registrar_basicas()

                def intencion(self, nombre: str, patrones: list, respuestas: list, accion: Callable | None = None,
                              con_tildes: bool = False) -> None:
                    self.intenciones.append(Intencion(nombre, [re.compile(p) for p in patrones], respuestas, accion, con_tildes))

                def _registrar_basicas(self) -> None:
                    def guardar_nombre(m, ctx):
                        ctx.nombre = m.group("nombre").strip().title()
                        return f"¡Mucho gusto, {ctx.nombre}!"

                    def decir_hora(_m, _ctx):
                        return f"Son las {self.reloj():%H:%M}."

                    def calcular(m, _ctx):
                        a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
                        if op == "/" and b == 0:
                            return "No se puede dividir por cero."
                        r = {"+": a + b, "-": a - b, "*": a * b, "x": a * b, "/": a / b if b else 0}[op]
                        return f"Da {r:g}."

                    self.intencion("saludo", [r"^(hola|buenas|buen dia|buenas tardes|buenas noches|hey)\\b"],
                                   ["¡Hola{nombre}! ¿En qué te ayudo?", "¡Buenas{nombre}! Contame."])
                    self.intencion("nombre", [r"(?:me llamo|mi nombre es|soy) (?P<nombre>[^\\W\\d_]{2,20}(?: [^\\W\\d_]{2,20}){0,3})$"],
                                   [], guardar_nombre, con_tildes=True)
                    self.intencion("quien_soy", [r"como me llamo|sabes mi nombre|quien soy"], [],
                                   lambda _m, ctx: f"Te llamás {ctx.nombre}." if ctx.nombre else "Todavía no me dijiste tu nombre.")
                    self.intencion("hora", [r"\\bque hora\\b|\\bla hora\\b"], [], decir_hora)
                    self.intencion("cuenta", [r"(-?\\d+(?:\\.\\d+)?)\\s*([-+*/x])\\s*(-?\\d+(?:\\.\\d+)?)"], [], calcular)
                    self.intencion("gracias", [r"\\bgracias\\b|\\bgenial\\b|\\bbarbaro\\b"],
                                   ["¡De nada{nombre}!", "¡Para eso estoy!"])
                    self.intencion("despedida", [r"^(chau|adios|hasta luego|nos vemos)\\b"],
                                   ["¡Chau{nombre}! 👋", "¡Hasta luego{nombre}!"])
                    self.intencion("ayuda", [r"\\bayuda\\b|que podes hacer|que sabes hacer"],
                                   ["Puedo saludar, recordar tu nombre, decirte la hora y hacer cuentas (ej: 12 * 3)."])

                def responder(self, mensaje: str) -> str:
                    texto = normalizar(mensaje)
                    original = " ".join(re.sub(r"[¿?¡!.,;]", " ", mensaje.lower()).split())
                    self.contexto.turnos += 1
                    if not texto:
                        return "¿Me escribiste algo?"
                    for intencion in self.intenciones:
                        m = intencion.coincide(texto, original)
                        if not m:
                            continue
                        self.contexto.ultimo_tema = intencion.nombre
                        if intencion.accion:
                            respuesta = intencion.accion(m, self.contexto)
                            if respuesta:
                                return respuesta
                        if intencion.respuestas:
                            nombre = f", {self.contexto.nombre}" if self.contexto.nombre else ""
                            return self.azar.choice(intencion.respuestas).format(nombre=nombre)
                    self.contexto.ultimo_tema = None
                    return "No entendí. Escribí 'ayuda' para ver qué sé hacer."


            def main() -> int:
                bot = Bot()
                print("Bot: ¡Hola! Escribí 'chau' para salir.")
                while True:
                    try:
                        mensaje = input("Vos: ")
                    except EOFError:
                        print()
                        break
                    respuesta = bot.responder(mensaje)
                    print("Bot:", respuesta)
                    if bot.contexto.ultimo_tema == "despedida":
                        break
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "tests/test_bot.py": '''
            import subprocess
            import sys
            import unittest
            from datetime import datetime
            from pathlib import Path

            from bot import Bot, normalizar


            class TestBot(unittest.TestCase):
                def setUp(self):
                    self.bot = Bot(semilla=1, reloj=lambda: datetime(2024, 3, 1, 14, 5))

                def test_normalizar(self):
                    self.assertEqual(normalizar("  ¿Qué  HORA es?  "), "que hora es?")

                def test_recuerda_el_nombre(self):
                    self.assertEqual(self.bot.responder("¿Cómo me llamo?"), "Todavía no me dijiste tu nombre.")
                    self.assertEqual(self.bot.responder("Me llamo ana maría"), "¡Mucho gusto, Ana María!")
                    self.assertEqual(self.bot.responder("cómo me llamo"), "Te llamás Ana María.")
                    self.assertIn("Ana María", self.bot.responder("hola"))

                def test_hora_y_cuentas(self):
                    self.assertEqual(self.bot.responder("¿Qué hora es?"), "Son las 14:05.")
                    self.assertEqual(self.bot.responder("cuánto es 12 * 3"), "Da 36.")
                    self.assertEqual(self.bot.responder("7 / 0"), "No se puede dividir por cero.")
                    self.assertEqual(self.bot.responder("2.5 + 1"), "Da 3.5.")

                def test_desconocido_y_vacio(self):
                    self.assertIn("No entendí", self.bot.responder("asdf qwer"))
                    self.assertIsNone(self.bot.contexto.ultimo_tema)
                    self.assertEqual(self.bot.responder("   "), "¿Me escribiste algo?")

                def test_respuestas_reproducibles(self):
                    otro = Bot(semilla=1)
                    self.assertEqual(Bot(semilla=1).responder("gracias"), otro.responder("gracias"))

                def test_conversacion_por_stdin(self):
                    raiz = Path(__file__).resolve().parent.parent
                    r = subprocess.run([sys.executable, str(raiz / "bot.py")], input="hola\\nme llamo luis\\nchau\\nesto no llega\\n",
                                       capture_output=True, text=True, timeout=20)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("Mucho gusto, Luis", r.stdout)
                    self.assertNotIn("esto no llega", r.stdout)


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 bot.py",
    etiquetas=("chatbot", "bot", "conversacion", "reglas", "interactivo"),
)

# ======================================================================
# descargas
# ======================================================================
registrar_plantilla(
    "descargas",
    "Gestor de descargas: cola con prioridad, reintentos con espera creciente, progreso y reanudación. La red es inyectable (tests sin internet).",
    "python",
    {
        "gestor.py": '''
            """__TITULO__: cola de descargas robusta (urllib) con reintentos y progreso."""
            from __future__ import annotations

            import hashlib
            import time
            import urllib.error
            import urllib.request
            from dataclasses import dataclass, field
            from pathlib import Path
            from typing import Callable, Iterable


            class ErrorTransitorio(Exception):
                """Falla que vale la pena reintentar (red caída, timeout, 5xx)."""


            @dataclass(order=True)
            class Descarga:
                prioridad: int
                url: str = field(compare=False)
                destino: Path = field(compare=False)
                sha256: str | None = field(default=None, compare=False)
                estado: str = field(default="pendiente", compare=False)   # pendiente | ok | error
                intentos: int = field(default=0, compare=False)
                error: str = field(default="", compare=False)
                bytes: int = field(default=0, compare=False)


            def fuente_urllib(url: str, desde: int = 0, timeout: float = 30) -> Iterable[bytes]:
                pedido = urllib.request.Request(url, headers={"User-Agent": "__PROYECTO__/1.0"})
                if desde:
                    pedido.add_header("Range", f"bytes={desde}-")
                try:
                    respuesta = urllib.request.urlopen(pedido, timeout=timeout)
                except urllib.error.HTTPError as e:
                    if e.code >= 500 or e.code == 429:
                        raise ErrorTransitorio(f"HTTP {e.code}") from None
                    raise
                except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                    raise ErrorTransitorio(str(e)) from None
                with respuesta:
                    while True:
                        try:
                            bloque = respuesta.read(64 * 1024)
                        except (TimeoutError, ConnectionError) as e:
                            raise ErrorTransitorio(str(e)) from None
                        if not bloque:
                            return
                        yield bloque


            class Gestor:
                def __init__(self, fuente: Callable = fuente_urllib, reintentos: int = 3, espera: float = 1.0,
                             dormir: Callable[[float], None] = time.sleep,
                             progreso: Callable[[Descarga], None] | None = None):
                    self.fuente = fuente
                    self.reintentos = reintentos
                    self.espera = espera
                    self.dormir = dormir
                    self.progreso = progreso
                    self.cola: list[Descarga] = []

                def agregar(self, url: str, destino: str | Path, prioridad: int = 0, sha256: str | None = None) -> Descarga:
                    if not url.startswith(("http://", "https://")):
                        raise ValueError(f"URL inválida: {url}")
                    d = Descarga(-prioridad, url, Path(destino), sha256)
                    self.cola.append(d)
                    self.cola.sort()
                    return d

                def _bajar(self, d: Descarga) -> None:
                    parcial = d.destino.with_suffix(d.destino.suffix + ".parcial")
                    parcial.parent.mkdir(parents=True, exist_ok=True)
                    desde = parcial.stat().st_size if parcial.exists() else 0
                    d.bytes = desde
                    with open(parcial, "ab") as archivo:
                        for bloque in self.fuente(d.url, desde):
                            archivo.write(bloque)
                            d.bytes += len(bloque)
                            if self.progreso:
                                self.progreso(d)
                    if d.sha256:
                        h = hashlib.sha256(parcial.read_bytes()).hexdigest()
                        if h != d.sha256:
                            parcial.unlink()
                            raise ValueError(f"el hash no coincide (esperado {d.sha256[:12]}…, llegó {h[:12]}…)")
                    parcial.replace(d.destino)

                def procesar(self) -> list[Descarga]:
                    for d in self.cola:
                        if d.estado == "ok":
                            continue
                        espera = self.espera
                        while True:
                            d.intentos += 1
                            try:
                                self._bajar(d)
                                d.estado, d.error = "ok", ""
                                break
                            except ErrorTransitorio as e:
                                d.error = str(e)
                                if d.intentos > self.reintentos:
                                    d.estado = "error"
                                    break
                                self.dormir(espera)
                                espera *= 2
                            except (OSError, ValueError, urllib.error.HTTPError) as e:
                                d.estado, d.error = "error", str(e)
                                break
                    return self.cola

                def resumen(self) -> str:
                    ok = sum(1 for d in self.cola if d.estado == "ok")
                    errores = [f"  ✗ {d.url}: {d.error}" for d in self.cola if d.estado == "error"]
                    return "\\n".join([f"{ok}/{len(self.cola)} descargas completas"] + errores)


            def main(argv: list[str] | None = None) -> int:
                import sys
                args = sys.argv[1:] if argv is None else argv
                if not args:
                    print("uso: gestor.py URL [URL ...]   (se guardan en ./descargas/)")
                    return 2

                def mostrar(d: Descarga) -> None:
                    print(f"\\r{d.destino.name}: {d.bytes / 1024:.0f} KB", end="", flush=True)

                g = Gestor(progreso=mostrar)
                for url in args:
                    nombre = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or "descarga"
                    g.agregar(url, Path("descargas") / nombre)
                g.procesar()
                print()
                print(g.resumen())
                return 0 if all(d.estado == "ok" for d in g.cola) else 1


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "tests/test_gestor.py": '''
            import hashlib
            import tempfile
            import unittest
            from pathlib import Path

            from gestor import ErrorTransitorio, Gestor

            CONTENIDO = b"0123456789" * 1000


            class FuenteFalsa:
                """Simula la red: falla N veces y después entrega el contenido (soporta reanudar con 'desde')."""
                def __init__(self, fallas=0, cortar_en=None):
                    self.fallas = fallas
                    self.cortar_en = cortar_en
                    self.llamadas = []

                def __call__(self, url, desde=0, timeout=30):
                    self.llamadas.append((url, desde))
                    if "404" in url:
                        raise OSError("HTTP 404")
                    if self.fallas:
                        self.fallas -= 1
                        raise ErrorTransitorio("sin conexión")
                    datos = CONTENIDO[desde:]
                    for i in range(0, len(datos), 3000):
                        if self.cortar_en is not None and desde + i >= self.cortar_en:
                            self.cortar_en = None
                            raise ErrorTransitorio("se cortó")
                        yield datos[i:i + 3000]


            class TestGestor(unittest.TestCase):
                def setUp(self):
                    self.tmp = tempfile.TemporaryDirectory()
                    self.dir = Path(self.tmp.name)
                    self.esperas = []

                def tearDown(self):
                    self.tmp.cleanup()

                def gestor(self, fuente, **kw):
                    return Gestor(fuente=fuente, dormir=self.esperas.append, espera=1, **kw)

                def test_descarga_simple(self):
                    g = self.gestor(FuenteFalsa())
                    d = g.agregar("https://x.com/a.bin", self.dir / "a.bin")
                    g.procesar()
                    self.assertEqual((d.estado, (self.dir / "a.bin").read_bytes()), ("ok", CONTENIDO))
                    self.assertFalse((self.dir / "a.bin.parcial").exists())

                def test_reintentos_con_espera_creciente(self):
                    g = self.gestor(FuenteFalsa(fallas=2))
                    d = g.agregar("https://x.com/a.bin", self.dir / "a.bin")
                    g.procesar()
                    self.assertEqual((d.estado, d.intentos), ("ok", 3))
                    self.assertEqual(self.esperas, [1, 2])

                def test_agota_reintentos(self):
                    g = self.gestor(FuenteFalsa(fallas=10), reintentos=2)
                    d = g.agregar("https://x.com/a.bin", self.dir / "a.bin")
                    g.procesar()
                    self.assertEqual((d.estado, d.intentos), ("error", 3))
                    self.assertIn("0/1 descargas completas", g.resumen())

                def test_reanuda_donde_se_corto(self):
                    fuente = FuenteFalsa(cortar_en=6000)
                    g = self.gestor(fuente)
                    g.agregar("https://x.com/a.bin", self.dir / "a.bin")
                    g.procesar()
                    self.assertEqual((self.dir / "a.bin").read_bytes(), CONTENIDO)
                    self.assertEqual(fuente.llamadas[1][1], 6000)   # el segundo intento pidió desde el byte 6000

                def test_hash_y_errores_definitivos(self):
                    g = self.gestor(FuenteFalsa())
                    bueno = g.agregar("https://x.com/a", self.dir / "a", sha256=hashlib.sha256(CONTENIDO).hexdigest())
                    malo = g.agregar("https://x.com/b", self.dir / "b", sha256="0" * 64)
                    no_existe = g.agregar("https://x.com/404", self.dir / "c")
                    g.procesar()
                    self.assertEqual([bueno.estado, malo.estado, no_existe.estado], ["ok", "error", "error"])
                    self.assertIn("hash no coincide", malo.error)
                    self.assertEqual(no_existe.intentos, 1)   # un 404 no se reintenta

                def test_prioridad_y_validacion(self):
                    g = self.gestor(FuenteFalsa())
                    g.agregar("https://x.com/baja", self.dir / "1")
                    g.agregar("https://x.com/alta", self.dir / "2", prioridad=5)
                    self.assertEqual(g.cola[0].url, "https://x.com/alta")
                    with self.assertRaises(ValueError):
                        g.agregar("ftp://x", self.dir / "3")


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 gestor.py https://example.com/",
    etiquetas=("descargas", "red", "reintentos", "cola", "urllib", "progreso"),
)

# ======================================================================
# horario
# ======================================================================
registrar_plantilla(
    "horario",
    "Planificador de horarios: reparte actividades en franjas de la semana sin choques, respetando disponibilidad (backtracking).",
    "python",
    {
        "horario.py": '''
            """__TITULO__: arma un horario semanal sin superposiciones (búsqueda con vuelta atrás)."""
            from __future__ import annotations

            import json
            from dataclasses import dataclass, field

            DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


            def a_minutos(hora: str) -> int:
                h, _, m = hora.partition(":")
                if not h.isdigit() or (m and not m.isdigit()):
                    raise ValueError(f"hora inválida: {hora}")
                total = int(h) * 60 + int(m or 0)
                if not 0 <= total <= 24 * 60:
                    raise ValueError(f"hora fuera de rango: {hora}")
                return total


            def a_hora(minutos: int) -> str:
                return f"{minutos // 60:02d}:{minutos % 60:02d}"


            @dataclass(frozen=True)
            class Franja:
                dia: str
                inicio: int
                fin: int

                def se_superpone(self, otra: "Franja") -> bool:
                    return self.dia == otra.dia and self.inicio < otra.fin and otra.inicio < self.fin

                def __str__(self) -> str:
                    return f"{self.dia} {a_hora(self.inicio)}-{a_hora(self.fin)}"


            @dataclass
            class Actividad:
                nombre: str
                duracion: int                  # minutos
                veces: int = 1                 # sesiones por semana (en días distintos)
                dias: list = field(default_factory=lambda: list(DIAS))
                desde: int = 8 * 60
                hasta: int = 22 * 60


            def candidatas(a: Actividad, paso: int = 30) -> list[Franja]:
                salida = []
                for dia in a.dias:
                    inicio = a.desde
                    while inicio + a.duracion <= a.hasta:
                        salida.append(Franja(dia, inicio, inicio + a.duracion))
                        inicio += paso
                return salida


            def planificar(actividades: list[Actividad], ocupado: list[Franja] | None = None, paso: int = 30):
                """Devuelve {actividad: [franjas]} o None si no hay forma de acomodar todo."""
                ocupado = list(ocupado or [])
                sesiones = sorted(((a, i) for a in actividades for i in range(a.veces)),
                                  key=lambda s: (len(candidatas(s[0], paso)), -s[0].duracion))
                asignado: dict[str, list[Franja]] = {a.nombre: [] for a in actividades}
                usadas: list[Franja] = []

                def libre(f: Franja, actividad: Actividad) -> bool:
                    if any(f.se_superpone(o) for o in ocupado + usadas):
                        return False
                    return all(x.dia != f.dia for x in asignado[actividad.nombre])   # una sesión por día

                def buscar(k: int) -> bool:
                    if k == len(sesiones):
                        return True
                    actividad, _ = sesiones[k]
                    for f in candidatas(actividad, paso):
                        if libre(f, actividad):
                            asignado[actividad.nombre].append(f)
                            usadas.append(f)
                            if buscar(k + 1):
                                return True
                            usadas.pop()
                            asignado[actividad.nombre].pop()
                    return False

                return asignado if buscar(0) else None


            def tabla(plan: dict[str, list[Franja]]) -> str:
                por_dia: dict[str, list[tuple[int, str]]] = {d: [] for d in DIAS}
                for nombre, franjas in plan.items():
                    for f in franjas:
                        por_dia[f.dia].append((f.inicio, f"{a_hora(f.inicio)}-{a_hora(f.fin)} {nombre}"))
                lineas = []
                for dia in DIAS:
                    if por_dia[dia]:
                        lineas.append(dia.capitalize())
                        lineas.extend(f"  {texto}" for _, texto in sorted(por_dia[dia]))
                return "\\n".join(lineas) or "(vacío)"


            def desde_json(texto: str) -> tuple[list[Actividad], list[Franja]]:
                datos = json.loads(texto)
                actividades = [Actividad(a["nombre"], int(a["duracion"]), int(a.get("veces", 1)),
                                         a.get("dias", list(DIAS)), a_minutos(a.get("desde", "08:00")),
                                         a_minutos(a.get("hasta", "22:00"))) for a in datos.get("actividades", [])]
                ocupado = [Franja(o["dia"], a_minutos(o["inicio"]), a_minutos(o["fin"])) for o in datos.get("ocupado", [])]
                return actividades, ocupado


            def main(argv: list[str] | None = None) -> int:
                import sys
                from pathlib import Path
                args = sys.argv[1:] if argv is None else argv
                if not args:
                    print("uso: horario.py plan.json   (ver ejemplo.json)")
                    return 2
                actividades, ocupado = desde_json(Path(args[0]).read_text(encoding="utf-8"))
                plan = planificar(actividades, ocupado)
                if plan is None:
                    print("No entra todo: probá con menos sesiones, más días o franjas horarias más amplias.")
                    return 1
                print(tabla(plan))
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
        ''',
        "ejemplo.json": '''
            {
              "actividades": [
                {"nombre": "gimnasio", "duracion": 60, "veces": 3, "desde": "18:00", "hasta": "21:00"},
                {"nombre": "inglés", "duracion": 90, "veces": 2, "dias": ["martes", "jueves"], "desde": "19:00"},
                {"nombre": "lectura", "duracion": 30, "veces": 5}
              ],
              "ocupado": [{"dia": "lunes", "inicio": "18:00", "fin": "20:00"}]
            }
        ''',
        "tests/test_horario.py": '''
            import unittest
            from pathlib import Path

            from horario import Actividad, Franja, a_hora, a_minutos, desde_json, planificar, tabla


            class TestHorario(unittest.TestCase):
                def test_horas(self):
                    self.assertEqual(a_minutos("09:30"), 570)
                    self.assertEqual(a_hora(570), "09:30")
                    for malo in ("25:00", "x", "10:aa"):
                        with self.assertRaises(ValueError):
                            a_minutos(malo)

                def test_superposicion(self):
                    a = Franja("lunes", 600, 660)
                    self.assertTrue(a.se_superpone(Franja("lunes", 630, 700)))
                    self.assertFalse(a.se_superpone(Franja("lunes", 660, 700)))    # se tocan pero no se pisan
                    self.assertFalse(a.se_superpone(Franja("martes", 600, 660)))

                def test_sin_choques_y_en_dias_distintos(self):
                    acts = [Actividad("gym", 60, 3, desde=18 * 60, hasta=20 * 60),
                            Actividad("curso", 120, 2, dias=["martes", "jueves"], desde=18 * 60, hasta=21 * 60)]
                    plan = planificar(acts)
                    todas = [f for fs in plan.values() for f in fs]
                    self.assertEqual(len(todas), 5)
                    for i, x in enumerate(todas):
                        for y in todas[i + 1:]:
                            self.assertFalse(x.se_superpone(y), f"{x} choca con {y}")
                    self.assertEqual(len({f.dia for f in plan["gym"]}), 3)

                def test_respeta_lo_ocupado(self):
                    plan = planificar([Actividad("x", 60, 1, dias=["lunes"], desde=600, hasta=720)],
                                      ocupado=[Franja("lunes", 600, 660)])
                    self.assertEqual(plan["x"], [Franja("lunes", 660, 720)])

                def test_imposible(self):
                    self.assertIsNone(planificar([Actividad("x", 60, 2, dias=["lunes"])]))   # 2 veces el mismo día

                def test_ejemplo_completo(self):
                    actividades, ocupado = desde_json((Path(__file__).resolve().parent.parent / "ejemplo.json").read_text(encoding="utf-8"))
                    plan = planificar(actividades, ocupado)
                    self.assertIsNotNone(plan)
                    texto = tabla(plan)
                    self.assertIn("inglés", texto)
                    self.assertNotIn("Lunes\\n  18:00-19:00 gimnasio", texto)


            if __name__ == "__main__":
                unittest.main()
        ''',
    },
    comando_tests="python3 -m unittest discover -s tests",
    comando_ejecutar="python3 horario.py ejemplo.json",
    etiquetas=("horario", "agenda", "planificar", "semana", "algoritmo"),
)
