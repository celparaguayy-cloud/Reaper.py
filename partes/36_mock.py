"""
Modelo simulado para probar REAPER sin gastar API (autotest, evals en seco, demos).

MockLLM implementa la misma interfaz que LLMClient (chat, chat_simple, uso)
y responde con un guion:
  - una lista de respuestas (se consumen en orden), o
  - una función(mensajes, kwargs) -> str que decide según el contexto
    (rol del system prompt, temperatura, último resultado...).

También hay un transporte falso de SSE para probar el cliente HTTP real
(reintentos, respaldos, errores del proveedor) sin red.
"""


class GuionAgotado(LLMError):
    pass


class MockLLM:
    def __init__(self, guion: Union[Sequence[str], Callable[[list, dict], str], None] = None, *,
                 finish_reason: Optional[str] = None, latencia: float = 0.0):
        self._lista = list(guion) if isinstance(guion, (list, tuple)) else None
        self._funcion = guion if callable(guion) else None
        self.finish_reason = finish_reason
        self.latencia = latencia
        self.uso = Uso()
        self.llamadas: list[dict] = []
        self._lock = threading.Lock()
        self.on_evento = None
        self.settings = None

    def chat(self, mensajes: list[dict], **kwargs) -> Respuesta:
        if self.latencia:
            time.sleep(self.latencia)
        with self._lock:
            self.llamadas.append({"mensajes": copy.deepcopy(mensajes), **{k: v for k, v in kwargs.items()
                                                                          if k != "on_progress"}})
            if self._funcion is not None:
                texto = self._funcion(mensajes, kwargs)
            elif self._lista:
                texto = self._lista.pop(0)
            else:
                raise GuionAgotado("El guion del MockLLM se agotó.")
            self.uso.llamadas += 1
            self.uso.tokens_entrada += tokens_mensajes(mensajes)
            self.uso.tokens_salida += estimar_tokens(texto if isinstance(texto, str) else str(texto))
        finish = self.finish_reason
        if isinstance(texto, tuple):
            texto, finish = texto
        stop = kwargs.get("stop") or []
        for marca in stop:
            corte = texto.find(marca)
            if corte >= 0:
                texto = texto[:corte]
        if kwargs.get("on_progress"):
            kwargs["on_progress"](len(texto))
        return Respuesta(texto=texto, finish_reason=finish, modelo=str(kwargs.get("modelo") or "mock"),
                         tokens_salida=estimar_tokens(texto))

    def chat_simple(self, prompt: str, *, sistema: str = "", modelo: Optional[str] = None,
                    temperatura: float = 0.2, max_tokens: int = 1500, rol: str = "") -> str:
        mensajes = ([{"role": "system", "content": sistema}] if sistema else []) + [{"role": "user", "content": prompt}]
        return self.chat(mensajes, modelo=modelo, temperatura=temperatura, max_tokens=max_tokens, rol=rol).texto

    # ------------------------------------------------------------ ayudas para guiones
    @staticmethod
    def rol_de(mensajes: list) -> str:
        sistema = mensajes[0]["content"] if mensajes and mensajes[0]["role"] == "system" else ""
        m = re.search(r"# TU ROL: (\w+)", sistema)
        return m.group(1).lower() if m else ""

    @staticmethod
    def ultimo_usuario(mensajes: list) -> str:
        for m in reversed(mensajes):
            if m["role"] == "user":
                return m["content"]
        return ""

    @staticmethod
    def turnos_asistente(mensajes: list) -> int:
        return sum(1 for m in mensajes if m["role"] == "assistant")


def herramienta_xml(nombre: str, **params: str) -> str:
    """Arma una llamada de herramienta en el formato XML del protocolo (para guiones)."""
    cuerpo = "".join(f"<{k}>\n{v}\n</{k}>\n" if "\n" in str(v) or k in ("content", "diff", "result", "task", "items", "spec")
                     else f"<{k}>{v}</{k}>\n" for k, v in params.items())
    return f"<{nombre}>\n{cuerpo}</{nombre}>"


def terminar_xml(informe: str = "Listo.") -> str:
    return herramienta_xml("attempt_completion", result=informe)


def transporte_falso(eventos: Sequence[Union[str, dict, Exception]]) -> Callable:
    """
    Transporte SSE de prueba para LLMClient. Cada elemento es:
      - str: texto de una respuesta completa (se parte en chunks)
      - dict: evento crudo (se serializa como 'data: {...}')
      - Exception: se lanza al iniciar esa llamada (p. ej. _Transitorio o LLMError)
    Cada llamada al transporte consume UN elemento.
    """
    pendientes = list(eventos)

    def transporte(url: str, headers: dict, payload: dict, timeout: int) -> Iterator[str]:
        if not pendientes:
            raise _Transitorio("sin más respuestas falsas")
        actual = pendientes.pop(0)
        if isinstance(actual, Exception):
            raise actual
        if isinstance(actual, dict):
            yield "data: " + json.dumps(actual)
            yield "data: [DONE]"
            return
        for i in range(0, len(actual), 7):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": actual[i:i + 7]}}]})
        yield "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001}})
        yield "data: [DONE]"

    transporte.pendientes = pendientes  # type: ignore[attr-defined]
    return transporte
