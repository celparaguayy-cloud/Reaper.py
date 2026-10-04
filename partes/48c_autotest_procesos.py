"""Autotests de procesos en segundo plano (start_process / process_output / stop_process)."""

_SERVIDOR_TEST = '''
import http.server, sys

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"pong")
        print("pedido", self.path, flush=True)
    def log_message(self, *a):
        pass

servidor = http.server.HTTPServer(("127.0.0.1", 0), H)
print("escuchando en", servidor.server_address[1], flush=True)
servidor.serve_forever()
'''


class TestProcesosFondo(BaseTest):
    def tearDown(self) -> None:
        detener_todos_los_procesos()
        super().tearDown()

    def test_servidor_completo(self):
        ws = self.proyecto({"srv.py": _SERVIDOR_TEST})
        ctx = self.contexto(ws)
        salida = self.herramienta(ctx, "start_process", command="python3 -u srv.py", wait_for=r"escuchando en \d+")
        self.assertIn("Listo", salida)
        puerto = re.search(r"escuchando en (\d+)", salida).group(1)
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/hola", timeout=5) as r:
            self.assertEqual(r.read(), b"pong")
        nuevas = self.herramienta(ctx, "process_output", id="p" + salida.split()[1][1:], wait_for="pedido /hola")
        self.assertIn("pedido /hola", nuevas)
        self.assertIn("(sin salida nueva", self.herramienta(ctx, "process_output"))
        final = self.herramienta(ctx, "stop_process")
        self.assertIn("detenido", final)
        self.assertEqual(procesos_activos(), [])

    def test_proceso_que_termina_enseguida(self):
        ctx = self.contexto(self.proyecto({"x.py": "print('chau')\nraise SystemExit(3)\n"}))
        salida = self.herramienta(ctx, "start_process", command="python3 x.py", wait_for="nunca", timeout="2")
        self.assertIn("YA TERMINÓ", salida)
        self.assertIn("chau", salida)
        self.assertIn("código 3", self.herramienta(ctx, "stop_process"))

    def test_limites_y_seguridad(self):
        ctx = self.contexto(self.proyecto())
        with self.assertRaises(ErrorHerramienta):
            self.herramienta(ctx, "start_process", command="sudo python3 -m http.server")
        for _ in range(MAX_PROCESOS):
            self.herramienta(ctx, "start_process", command="sleep 30")
        with self.assertRaises(ErrorHerramienta) as cm:
            self.herramienta(ctx, "start_process", command="sleep 30")
        self.assertIn("detené alguno", str(cm.exception))
        self.assertIn("Procesos:", self.herramienta(ctx, "process_output"))
        self.assertEqual(detener_todos_los_procesos(), MAX_PROCESOS)
        with self.assertRaises(ErrorHerramienta):
            self.herramienta(ctx, "stop_process", id="p999")

    def test_agente_levanta_prueba_y_detiene(self):
        ws = self.proyecto({"srv.py": _SERVIDOR_TEST})
        llm = MockLLM([
            herramienta_xml("start_process", command="python3 -u srv.py", wait_for="escuchando"),
            herramienta_xml("process_output"),
            herramienta_xml("process_output"),
            herramienta_xml("process_output"),
            herramienta_xml("stop_process"),
            terminar_xml("El servidor arranca y escucha; lo detuve."),
        ])
        res = Agente("principal", llm, ws, self.ajustes(), self.ui(), memoria=None,
                     mostrar_progreso=False).ejecutar("verificá que srv.py arranca")
        self.assertTrue(res.ok, res.resumen)
        observaciones = [MockLLM.ultimo_usuario(c["mensajes"]) for c in llm.llamadas]
        self.assertIn("Listo", observaciones[1])
        self.assertFalse(any("llamada repetida" in o for o in observaciones), "consultar la salida no es un bucle")
        self.assertEqual(procesos_activos(), [])

    def test_roles_con_procesos(self):
        for rol in ("principal", "implementador", "reparador", "qa"):
            self.assertIn("start_process", ROLES[rol].herramientas)
        self.assertNotIn("start_process", ROLES["revisor"].herramientas)
        self.assertNotIn("start_process", ROLES["planificador"].herramientas)
