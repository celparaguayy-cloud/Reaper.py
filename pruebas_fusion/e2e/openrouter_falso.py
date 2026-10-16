"""OpenRouter FALSO para correr la CLI real de REAPER de punta a punta (HTTP + SSE de verdad).

Cerebro: el guion del almacén (5 etapas) del autotest, extendido a TODO el pipeline real (especificador con tests
primero, torneo, revisor, qa, juez). Fallas configurables por variables de entorno:
  MOCK_CUPO=N            → tras N pedidos de chat, 429 de cupo DIARIO (free-models-per-day) hasta MOCK_CUPO_RESET
  MOCK_429_CADA=K        → cada K pedidos, un 429 por minuto con Retry-After: 1
  MOCK_RAZONA=modelo     → ese modelo responde SOLO razonamiento (finish=length) a pedidos cortos (max_tokens<=2048)
  MOCK_ESTADO=archivo    → contador persistente de pedidos (para simular el día siguiente: se borra)
  MOCK_FLOJO=1           → el implementador escribe una venta que NO controla el stock; el reparador la arregla
Log de cada pedido (modelo, rol, status) en MOCK_LOG.
"""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.environ.get("REAPER_REPO") or os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
import reaper_v8 as R  # noqa: E402

G = R._GuionAlmacen
MODELOS = ["cohere/north-mini-code:free", "nvidia/nemotron-3.5-lightning:free", "nvidia/nemotron-3.5-super-vl:free"]
LOCK = threading.Lock()
ESTADO = os.environ.get("MOCK_ESTADO", "")
LOG = os.environ.get("MOCK_LOG", "")


def _leer_estado():
    try:
        with open(ESTADO) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"pedidos": 0}


def _guardar_estado(e):
    if ESTADO:
        with open(ESTADO, "w") as f:
            json.dump(e, f)


def _turno(mensajes):
    return sum(1 for m in mensajes if m["role"] == "assistant")


def _etapa(texto):
    m = re.search(r"ETAPA (\d+) de (\d+)", texto)
    return m.group(1) if m else "1"


def cerebro(mensajes):
    rol = R.MockLLM.rol_de(mensajes)
    primero = next((m["content"] for m in mensajes if m["role"] == "user"), "")
    sistema = mensajes[0]["content"] if mensajes and mensajes[0]["role"] == "system" else ""
    if "REAPER_OK" in primero:                     # el sondeo de modelos gratis de --perfil gratis
        return "probe", "REAPER_OK"
    etapa = _etapa(primero + sistema)
    turno = _turno(mensajes)
    if rol == "maestro":
        return rol, G.MAESTRO
    if rol == "arquitecto":
        return rol, R.terminar_xml(G.PLANES.get(etapa, G.PLANES["1"]))
    if rol == "especificador":
        tests = [a for t in _tareas_de(etapa) for a in G.TAREAS[t] if a.startswith("tests/")]
        if turno < len(tests):
            return rol, R.herramienta_xml("write_to_file", path=tests[turno], content=G.ARCHIVOS[tests[turno]])
        return rol, R.terminar_xml("tests escritos: fallan por ImportError hasta que exista el código (esperado)")
    if rol == "implementador":
        tarea = re.search(r"TU TAREA AHORA \(#[^)]*\):\n(.*?)\n\n", primero, re.S)
        marca = re.search(r"\((T\d+[ab]?)\)", tarea.group(1) if tarea else "")
        archivos = G.TAREAS[marca.group(1)] if marca else []
        if marca is None:
            # Sin la marca no sé qué tarea es: escribo todo lo que falte de la etapa (como un modelo "proactivo").
            archivos = [a for t in _tareas_de(etapa) for a in G.TAREAS[t]]
        codigo = [a for a in archivos if not a.startswith("tests/")]
        if turno < len(codigo):
            contenido = G.ARCHIVOS[codigo[turno]]
            if os.environ.get("MOCK_FLOJO") and codigo[turno] == "almacen/ventas.py":
                contenido = _VENTAS_FLOJA                 # vende aunque no haya stock
            return rol, R.herramienta_xml("write_to_file", path=codigo[turno], content=contenido)
        return rol, R.terminar_xml("listo: implementado y con los tests en verde")
    if rol == "juez":
        texto = R.MockLLM.ultimo_usuario(mensajes)
        if "TAREA: CONTRATO" in texto:
            return rol, '{"criterios": ["lo pedido funciona y tiene tests"]}'
        return rol, '{"cumple": true, "confianza": "high", "evidence_ids": ["EV-TESTS"]}'
    if rol in ("reparador", "integrador") and "ventas" in primero and turno == 0 and os.environ.get("MOCK_FLOJO"):
        # El reparador ve el test que falla (SinStock no se lanzó) y escribe la versión correcta.
        return rol, R.herramienta_xml("write_to_file", path="almacen/ventas.py", content=G.ARCHIVOS["almacen/ventas.py"])
    if rol in ("revisor", "qa", "reparador", "integrador", "explorador"):
        return rol, R.terminar_xml("revisado: sin cambios necesarios")
    return rol or "?", R.terminar_xml("sin cambios")


_VENTAS_FLOJA = G.ARCHIVOS["almacen/ventas.py"].replace(
    '            if fila["stock"] < cantidad:\n', '            if False:\n')
assert _VENTAS_FLOJA != G.ARCHIVOS["almacen/ventas.py"]


def _tareas_de(etapa):
    plan = G.PLANES.get(etapa, "")
    return re.findall(r"\((T\d+[ab]?)\)", plan)


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, codigo, datos, cabeceras=None):
        cuerpo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        for k, v in (cabeceras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path.endswith("/models"):
            datos = [{"id": m, "pricing": {"prompt": "0", "completion": "0"}, "context_length": 131072,
                      "supported_parameters": ["tools", "reasoning"], "architecture": {"output_modalities": ["text"]}}
                     for m in MODELOS]
            datos.append({"id": "openai/gpt-pago", "pricing": {"prompt": "0.001", "completion": "0.002"}})
            return self._json(200, {"data": datos})
        if self.path.endswith("/key"):
            if not self.headers.get("Authorization", "").startswith("Bearer "):
                return self._json(401, {"error": {"message": "No auth"}})
            e = _leer_estado()
            cupo = int(os.environ.get("MOCK_CUPO_DIA", "1000"))
            return self._json(200, {"data": {"is_free_tier": False, "free_model_daily_requests":
                                              {"limit": cupo, "used": e["pedidos"],
                                               "remaining": max(0, cupo - e["pedidos"])}}})
        self._json(404, {"error": {"message": "no existe"}})

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", "0"))
        pedido = json.loads(self.rfile.read(largo) or b"{}")
        mensajes = pedido.get("messages", [])
        modelo = pedido.get("model", "")
        with LOCK:
            e = _leer_estado()
            e["pedidos"] += 1
            n = e["pedidos"]
            _guardar_estado(e)
        rol, texto = cerebro(mensajes)
        registro = {"n": n, "modelo": modelo, "rol": rol, "max_tokens": pedido.get("max_tokens"),
                    "reasoning": pedido.get("reasoning"), "status": 200}
        cupo = int(os.environ.get("MOCK_CUPO", "0") or 0)
        cada = int(os.environ.get("MOCK_429_CADA", "0") or 0)
        try:
            if cupo and n > cupo:
                registro["status"] = 429
                reset_ms = int((time.time() + float(os.environ.get("MOCK_CUPO_RESET", "36000"))) * 1000)
                return self._json(429, {"error": {"message": "Rate limit exceeded: free-models-per-day. Add 10 credits "
                                                  "to unlock 1000 free model requests per day", "code": 429,
                                                  "metadata": {"headers": {"X-RateLimit-Limit": str(cupo),
                                                                           "X-RateLimit-Remaining": "0",
                                                                           "X-RateLimit-Reset": str(reset_ms)}}}},
                                  {"X-RateLimit-Limit": str(cupo), "X-RateLimit-Remaining": "0",
                                   "X-RateLimit-Reset": str(reset_ms)})
            if cada and n % cada == 0:
                registro["status"] = 429
                return self._json(429, {"error": {"message": "Rate limit exceeded: limit_rpm/20", "code": 429}},
                                  {"Retry-After": "1"})
            razona = os.environ.get("MOCK_RAZONA", "")
            solo_razona = (razona and modelo == razona and (pedido.get("max_tokens") or 99999) <= 2048
                           and (pedido.get("reasoning") or {}).get("effort") not in ("none", "minimal"))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if solo_razona:
                registro["solo_razona"] = True
                trozos = [{"choices": [{"delta": {"reasoning": "pensando " * 40}}]},
                          {"choices": [{"delta": {}, "finish_reason": "length"}],
                           "usage": {"prompt_tokens": 500, "completion_tokens": pedido.get("max_tokens") or 0}}]
            else:
                trozos = [{"choices": [{"delta": {"content": texto[i:i + 400]}}]} for i in range(0, len(texto), 400)]
                trozos.append({"choices": [{"delta": {}, "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 1000, "completion_tokens": len(texto) // 4, "cost": 0}})
            self.wfile.write(b": OPENROUTER PROCESSING\n\n")
            for t in trozos:
                self.wfile.write(b"data: " + json.dumps(t).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        finally:
            if LOG:
                with LOCK, open(LOG, "a") as f:
                    f.write(json.dumps(registro) + "\n")


if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    print(srv.server_port, flush=True)
    srv.serve_forever()
