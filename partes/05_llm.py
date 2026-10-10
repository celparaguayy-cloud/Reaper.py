"""
Cliente LLM compatible con OpenAI/OpenRouter: streaming, reintentos con
backoff, modelos de respaldo, límite de solicitudes por minuto, presupuesto
de costo, ajuste automático de max_tokens y registro de uso por modelo.
"""

try:  # httpx es opcional: sin él se usa urllib (streaming igual).
    import httpx
except ImportError:  # pragma: no cover - depende del entorno
    httpx = None


class LLMError(RuntimeError):
    def __init__(self, mensaje: str, *, probar_otro_modelo: bool = False, contexto_excedido: bool = False,
                 presupuesto: bool = False, solo_razonamiento: bool = False):
        super().__init__(mensaje)
        self.probar_otro_modelo = probar_otro_modelo
        self.contexto_excedido = contexto_excedido
        self.presupuesto = presupuesto
        # El modelo respondió, pero gastó toda la salida en razonamiento sin dar contenido (modelos "thinking").
        self.solo_razonamiento = solo_razonamiento


class _Transitorio(Exception):
    """Error que vale la pena reintentar (429, 5xx, red, respuesta vacía)."""

    def __init__(self, mensaje: str, espera: Optional[float] = None, vacia: bool = False):
        super().__init__(mensaje)
        self.espera = espera
        self.vacia = vacia          # el modelo respondió 200 pero sin contenido


@dataclass
class Respuesta:
    texto: str
    finish_reason: Optional[str] = None
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0
    duracion: float = 0.0
    primer_token: float = 0.0


@dataclass
class UsoModelo:
    llamadas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo: float = 0.0
    segundos: float = 0.0


@dataclass
class Uso:
    llamadas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo: float = 0.0
    reintentos: int = 0
    errores: int = 0
    respaldos: int = 0
    por_modelo: dict = field(default_factory=dict)
    por_rol: dict = field(default_factory=dict)

    def resumen(self) -> str:
        texto = (f"{self.llamadas} llamadas · {formatear_numero(self.tokens_entrada)} tokens entrada · "
                 f"{formatear_numero(self.tokens_salida)} salida")
        if self.costo:
            texto += f" · ${self.costo:.4f}"
        if self.reintentos:
            texto += f" · {self.reintentos} reintentos"
        return texto


MENSAJES_HTTP = {
    400: "Pedido rechazado por el proveedor (¿contexto demasiado largo?).",
    401: "Clave API inválida, revocada o ausente.",
    402: "La cuenta no tiene crédito suficiente para este modelo.",
    403: "Acceso denegado por el proveedor (moderación o permisos).",
    404: "Modelo o endpoint no disponible.",
    408: "El proveedor tardó demasiado.",
    413: "El pedido es demasiado grande.",
    429: "Límite de solicitudes alcanzado.",
}

TRANSITORIOS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}

_RE_CONTEXTO = re.compile(
    r"context(_| )length|maximum context|too many tokens|context window|prompt is too long|reduce the length",
    re.I,
)
# Modelo inexistente/retirado para esta cuenta (404): se retira de la ruta, no se reintenta (Ω §5.2).
_RE_MODELO_RETIRADO = re.compile(
    r"\b404\b|model_not_found|does not exist|no such model|modelo o endpoint no disponible|model.*not found",
    re.I,
)


def _lanzar_http(status: int, cuerpo: str, retry_after: Optional[str]) -> None:
    detalle = " ".join((cuerpo or "").split())[:400]
    motivo = MENSAJES_HTTP.get(status, "Error HTTP del proveedor.")
    if status in TRANSITORIOS:
        espera = None
        try:
            espera = float(retry_after) if retry_after else None
        except ValueError:
            espera = None
        raise _Transitorio(f"{motivo} HTTP {status}. {detalle}".strip(), espera)
    excedido = status in (400, 413) and bool(_RE_CONTEXTO.search(cuerpo or ""))
    raise LLMError(
        f"{motivo} HTTP {status}. {detalle}".strip(),
        probar_otro_modelo=status in (400, 402, 403, 404, 413, 422) and not excedido,
        contexto_excedido=excedido,
    )


def _transporte_httpx(url: str, headers: dict, payload: dict, timeout: int) -> Iterator[str]:
    try:
        with httpx.stream(
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=httpx.Timeout(timeout, connect=30),
        ) as r:
            if r.status_code >= 400:
                # En streaming hay que leer el cuerpo antes de usarlo.
                cuerpo = r.read().decode("utf-8", "replace")
                _lanzar_http(r.status_code, cuerpo, r.headers.get("retry-after"))
            for linea in r.iter_lines():
                yield linea
    except httpx.TimeoutException as e:
        raise _Transitorio(f"El modelo no respondió dentro de {timeout}s.") from e
    except httpx.RequestError as e:
        raise _Transitorio(f"Error de red hablando con el proveedor: {e}") from e


def _transporte_urllib(url: str, headers: dict, payload: dict, timeout: int) -> Iterator[str]:
    datos = json.dumps(payload).encode("utf-8")
    pedido = urllib.request.Request(url, data=datos, headers=headers, method="POST")
    try:
        respuesta = urllib.request.urlopen(pedido, timeout=timeout)
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace") if e.fp else ""
        _lanzar_http(e.code, cuerpo, e.headers.get("Retry-After") if e.headers else None)
        return
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        raise _Transitorio(f"Error de red hablando con el proveedor: {e}") from e

    with respuesta:
        try:
            for crudo in respuesta:
                yield crudo.decode("utf-8", "replace").rstrip("\r\n")
        except (socket.timeout, TimeoutError, ConnectionError) as e:
            raise _Transitorio(f"Se cortó el streaming: {e}") from e


def parsear_linea_sse(linea: str):
    """Devuelve dict del evento, la cadena 'DONE' o None si la línea no aporta nada."""
    if not linea or not linea.startswith("data:"):
        return None
    datos = linea[5:].strip()
    if datos == "[DONE]":
        return "DONE"
    try:
        obj = json.loads(datos)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


Transporte = Callable[[str, dict, dict, int], Iterator[str]]


class LimitadorTasa:
    """Ventana deslizante de 60 s: como máximo 'rpm' solicitudes por minuto (thread-safe)."""

    def __init__(self, rpm: int, reloj: Callable[[], float] = time.monotonic,
                 dormir: Callable[[float], None] = time.sleep):
        self.rpm = max(0, int(rpm))
        self._reloj = reloj
        self._dormir = dormir
        self._marcas: collections.deque = collections.deque()
        self._lock = threading.Lock()

    def espera_necesaria(self) -> float:
        """Peek SIN reservar: cuánto habría que esperar ahora mismo (0 = hay lugar)."""
        if self.rpm <= 0:
            return 0.0
        with self._lock:
            return self._espera_bloqueado(self._reloj())

    def _espera_bloqueado(self, ahora: float) -> float:
        while self._marcas and ahora - self._marcas[0] >= 60.0:
            self._marcas.popleft()
        if len(self._marcas) < self.rpm:
            return 0.0
        return max(0.0, 60.0 - (ahora - self._marcas[0]) + 0.05)

    def _reservar(self) -> float:
        """
        Atómico (R-007): si hay lugar, RESERVA el turno (append) y devuelve 0; si no, devuelve la espera sin
        reservar. Chequear-y-reservar en el MISMO lock evita que dos hilos pasen el chequeo y superen el rpm.
        """
        with self._lock:
            ahora = self._reloj()
            espera = self._espera_bloqueado(ahora)
            if espera <= 0:
                self._marcas.append(ahora)
            return espera

    def adquirir(self, cancelado: Optional[Callable[[], bool]] = None) -> float:
        """Bloquea hasta que haya lugar. Devuelve los segundos esperados."""
        if self.rpm <= 0:
            return 0.0
        esperado = 0.0
        while True:
            espera = self._reservar()
            if espera <= 0:
                return esperado
            tramo = min(espera, 1.0)
            if cancelado and cancelado():
                raise LLMError("Cancelado mientras se esperaba el límite de solicitudes.")
            self._dormir(tramo)
            esperado += tramo


class LLMClient:
    def __init__(
        self,
        api_key: str,
        settings: Settings,
        url: Optional[str] = None,
        transporte: Optional[Transporte] = None,
    ):
        self.api_key = api_key
        # El api_key del constructor pertenece al proveedor activo AL CREAR el cliente. Si después cambia el
        # proveedor (p.ej. un override del proyecto), esta clave NO se reutiliza para otro proveedor (BUG-001).
        self._proveedor_api_key = settings.proveedor
        self.settings = settings
        self.url = url or settings.url_api()
        self.uso = Uso()
        self._lock = threading.Lock()
        self._transporte = transporte or (_transporte_httpx if httpx else _transporte_urllib)
        self.dormir = time.sleep
        self.limitador = LimitadorTasa(settings.rpm_efectivo())
        self.disyuntor = DisyuntorModelos(umbral=getattr(settings, "disyuntor_umbral", 3),
                                          enfriamiento=getattr(settings, "disyuntor_enfriamiento", 45.0))
        self._claves_proveedor: dict = {}       # proveedor → clave (cache; Fase 6, ruteo multi-proveedor)
        self.on_evento: Optional[Callable[[str], None]] = None

    def _destino(self, modelo: str) -> "DestinoModelo":
        return destino_modelo(modelo, self.settings)

    def _clave_de(self, destino: "DestinoModelo") -> Optional[str]:
        """
        Clave del proveedor DESTINO. Cada endpoint recibe SOLO la clave de su propio proveedor: nunca la de
        otro, ni el api_key del constructor si pertenece a un proveedor distinto (BUG-001, fuga entre proveedores).
        """
        prov = destino.proveedor
        if prov not in self._claves_proveedor:
            if prov == self._proveedor_api_key and self.api_key:
                self._claves_proveedor[prov] = self.api_key
            else:
                self._claves_proveedor[prov] = clave_de_proveedor(prov, replace(self.settings, proveedor=prov))
        return self._claves_proveedor[prov]

    def _respaldos_equipo(self, principal: str, ya: list) -> list:
        """
        Los OTROS modelos del equipo (principal + los asignados a cada rol) como respaldo automático: si el
        modelo de un rol falla (413 demasiado grande, 429 tras reintentos, vacío, 404, caído), se prueba con otro
        en vez de abortar todo. Primero los de OTRO proveedor (un límite de cuenta no los afecta) y solo los que
        tienen credencial. Se apaga con settings.respaldo_equipo = False.
        """
        if not getattr(self.settings, "respaldo_equipo", True):
            return []
        equipo = [self.settings.modelo] + list((self.settings.modelos_rol or {}).values())
        try:
            prov_principal = self._destino(principal).proveedor
        except (ValueError, KeyError):
            prov_principal = ""
        otros, mismos = [], []
        for nombre in equipo:
            m = resolver_modelo(nombre)
            if not m or m in ya or m in otros or m in mismos:
                continue
            try:
                d = self._destino(m)
                if d.necesita_clave() and not self._clave_de(d):
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            (mismos if d.proveedor == prov_principal else otros).append(m)
        return otros + mismos

    # ------------------------------------------------------------ API
    def chat(
        self,
        mensajes: list[dict],
        *,
        modelo: Optional[str] = None,
        temperatura: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        rol: str = "",
        sin_respaldo: bool = False,
    ) -> Respuesta:
        self._verificar_presupuesto()
        principal = resolver_modelo(modelo or self.settings.modelo)
        candidatos = [principal]
        if not sin_respaldo:
            for respaldo in self.settings.fallbacks:
                respaldo = resolver_modelo(respaldo)
                if respaldo and respaldo not in candidatos:
                    candidatos.append(respaldo)
            candidatos += self._respaldos_equipo(principal, candidatos)

        # Privacidad estricta (Ω §4.3 / R-001): ÚNICO punto de egreso. Deny-by-default cuando el destino es
        # externo. Se bloquea ANTES de serializar/enviar (0 llamadas de red). chat_simple, subagentes,
        # escalada y benchmarks pasan todos por acá, así que la política no tiene rodeos.
        if getattr(self.settings, "privacidad_estricta", False):
            locales = [c for c in candidatos if self._destino(c).es_local()]
            if not locales:
                externos = sorted({self._destino(c).proveedor for c in candidatos})
                raise LLMError(
                    "Privacidad estricta ACTIVA: el destino es un proveedor externo "
                    f"({', '.join(externos) or '—'}) y no se envía contenido del proyecto afuera. "
                    "Usá un modelo local (ollama) o desactivá con /privacidad estricto off para autorizar el envío.",
                    probar_otro_modelo=False)
            candidatos = locales

        # Disyuntor (Ω §5.2): EXCLUIR los modelos abiertos/retirados; no "probar igual" contra algo caído.
        orden = self.disyuntor.elegibles(candidatos)
        if not orden:
            estados = ", ".join(f"{c}:{self.disyuntor.estado(c)}" for c in candidatos)
            raise LLMError(
                f"Todos los modelos están en enfriamiento o retirados ({estados}). Esperá unos segundos o "
                "elegí otro modelo/proveedor (/modelo <alias>, /equipo auto).", probar_otro_modelo=False)

        ultimo: Optional[LLMError] = None
        for n, candidato in enumerate(orden):
            try:
                respuesta = self._con_reintentos(
                    candidato, mensajes, temperatura, max_tokens, stop, on_progress
                )
                self.disyuntor.exito(candidato)
                if candidato != principal:
                    with self._lock:
                        self.uso.respaldos += 1
                self._registrar_rol(rol, respuesta)
                return respuesta
            except LLMError as e:
                ultimo = e
                with self._lock:
                    self.uso.errores += 1
                if not e.probar_otro_modelo:
                    raise
                if _RE_MODELO_RETIRADO.search(str(e)):      # 404 model_not_found → cuarentena de esa ruta
                    self.disyuntor.retirar(candidato)
                    if self.on_evento:
                        self.on_evento(f"{candidato} retirado (no disponible/404): no lo vuelvo a intentar hasta que responda")
                elif self.disyuntor.fallo(candidato) and self.on_evento:
                    self.on_evento(f"disyuntor ABIERTO para {candidato}: lo salteo un rato ({self.disyuntor.enfriamiento:.0f}s)")
                if self.on_evento and n + 1 < len(orden):
                    self.on_evento(f"{candidato} falló ({e}); pruebo con {orden[n + 1]}")
        assert ultimo is not None
        raise ultimo

    def chat_simple(self, prompt: str, *, sistema: str = "", modelo: Optional[str] = None,
                    temperatura: float = 0.2, max_tokens: int = 1500, rol: str = "") -> str:
        """Una pregunta y una respuesta, sin herramientas (diagnósticos, lecciones, resúmenes)."""
        mensajes = []
        if sistema:
            mensajes.append({"role": "system", "content": sistema})
        mensajes.append({"role": "user", "content": prompt})
        return self.chat(mensajes, modelo=modelo, temperatura=temperatura, max_tokens=max_tokens, rol=rol).texto

    # ------------------------------------------------------------ internos
    def _verificar_presupuesto(self) -> None:
        limite = self.settings.costo_maximo
        if limite and self.uso.costo >= limite:
            raise LLMError(
                f"Se alcanzó el presupuesto de la sesión (${self.uso.costo:.4f} de ${limite:.2f}). "
                "Subilo con /config costo_maximo <usd> o ponelo en 0.",
                presupuesto=True,
            )

    def _payload(self, modelo, mensajes, temperatura, max_tokens, stop, proveedor=None) -> dict:
        info = info_modelo(modelo)
        proveedor = proveedor or self._destino(modelo).proveedor
        presupuesto = Presupuesto(min(self.settings.contexto_tokens, info.contexto) if info.contexto else
                                  self.settings.contexto_tokens, max_tokens or self.settings.max_tokens)
        payload = {
            "model": self._destino(modelo).modelo,
            "messages": mensajes,
            "temperature": self.settings.temperatura if temperatura is None else temperatura,
            "max_tokens": presupuesto.respuesta_posible(mensajes),
            "stream": True,
        }
        if proveedor == "openrouter":
            payload["usage"] = {"include": True}
        elif proveedor == "openai":
            payload["stream_options"] = {"include_usage": True}
        if stop:
            payload["stop"] = stop[:4]
        return payload

    def _con_reintentos(self, modelo, mensajes, temperatura, max_tokens, stop, on_progress):
        payload = self._payload(modelo, mensajes, temperatura, max_tokens, stop, self._destino(modelo).proveedor)
        intentos = max(0, int(self.settings.reintentos))
        vacias = 0
        for intento in range(intentos + 1):
            try:
                cancelado = (lambda: CANCELAR.is_set()) if "CANCELAR" in globals() else None
                self.limitador.adquirir(cancelado)
                return self._una_vez(modelo, payload, on_progress)
            except _Transitorio as e:
                with self._lock:
                    self.uso.reintentos += 1
                vacias += int(getattr(e, "vacia", False))
                if vacias >= 2 and intento < intentos:
                    # Dos respuestas vacías seguidas: ese modelo no está respondiendo (típico de :free saturados);
                    # mejor pasar a otra IA del equipo que esperar ~30 s más de reintentos.
                    raise LLMError(f"{modelo}: {vacias} respuestas vacías seguidas", probar_otro_modelo=True) from e
                if intento >= intentos:
                    raise LLMError(
                        f"{e} (después de {intentos + 1} intentos)",
                        probar_otro_modelo=True,
                    ) from e
                espera = e.espera
                if espera is None:
                    espera = min(60.0, 2.0 * (2 ** intento)) + random.uniform(0, 1)
                if self.on_evento:
                    self.on_evento(f"reintento {intento + 1}/{intentos} en {espera:.0f}s: {e}")
                self.dormir(min(espera, 120.0))
        raise LLMError("No se obtuvo respuesta del modelo.")  # pragma: no cover

    def _headers(self, destino: Optional["DestinoModelo"] = None) -> dict:
        proveedor = destino.proveedor if destino is not None else self.settings.proveedor
        clave = self._clave_de(destino) if destino is not None else self.api_key
        headers = {"Content-Type": "application/json"}
        if clave and clave != "sin-clave":
            headers["Authorization"] = f"Bearer {clave}"
        if proveedor == "openrouter":
            headers["X-Title"] = "REAPER"
            headers["HTTP-Referer"] = "https://github.com/reaper-termux"
        return headers

    def _una_vez(self, modelo: str, payload: dict, on_progress) -> Respuesta:
        partes: list[str] = []
        total = 0
        razonamiento = 0          # caracteres de razonamiento (delta.reasoning) sin contenido visible
        finish = None
        inicio = time.monotonic()
        primer = 0.0
        tokens_in = tokens_out = 0

        destino = self._destino(modelo)
        if destino.necesita_clave() and not self._clave_de(destino):
            raise LLMError(
                f"falta la clave del proveedor '{destino.proveedor}' (variable {destino.clave_env}) para el modelo "
                f"{modelo}. Exportala como variable de entorno.", probar_otro_modelo=True)
        visto_done = False
        for linea in self._transporte(destino.url, self._headers(destino), payload, self.settings.timeout):
            evento = parsear_linea_sse(linea)
            if evento is None:
                continue
            if evento == "DONE":
                visto_done = True
                break

            if "error" in evento:
                err = evento["error"]
                mensaje = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                codigo = err.get("code") if isinstance(err, dict) else None
                if _RE_CONTEXTO.search(mensaje or ""):
                    raise LLMError(f"Contexto excedido: {mensaje}", contexto_excedido=True)
                if codigo is None or codigo in TRANSITORIOS:
                    raise _Transitorio(f"Error del proveedor durante el streaming: {mensaje}")
                raise LLMError(f"Error del proveedor: {mensaje}", probar_otro_modelo=True)

            uso = evento.get("usage")
            if isinstance(uso, dict):
                tokens_in = int(uso.get("prompt_tokens") or tokens_in or 0)
                tokens_out = int(uso.get("completion_tokens") or tokens_out or 0)
                self._registrar_uso(modelo, uso)

            for choice in evento.get("choices") or []:
                delta = choice.get("delta") or choice.get("message") or {}
                contenido = delta.get("content")
                pensado = delta.get("reasoning") or delta.get("reasoning_content")
                if isinstance(pensado, str):
                    razonamiento += len(pensado)
                if contenido:
                    if not primer:
                        primer = time.monotonic() - inicio
                    partes.append(contenido)
                    total += len(contenido)
                    if on_progress:
                        on_progress(total)
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]

        duracion = time.monotonic() - inicio
        with self._lock:
            self.uso.llamadas += 1
            por = self.uso.por_modelo.setdefault(modelo, UsoModelo())
            por.llamadas += 1
            por.segundos += duracion

        texto = "".join(partes)
        if texto.strip() and not visto_done and not finish:
            # El stream se cortó sin [DONE] ni finish_reason: la respuesta está TRUNCADA. Aceptarla haría que el
            # agente escriba un archivo cortado como si estuviera completo. Se reintenta / se cambia de modelo.
            raise _Transitorio("respuesta truncada: el stream terminó sin cierre ni finish_reason")
        if not texto.strip():
            if razonamiento:
                # Modelo con razonamiento que se quedó sin salida antes de responder: reintentar igual no sirve,
                # conviene pasar a otro modelo del equipo.
                raise LLMError(
                    f"{modelo} solo devolvió razonamiento ({razonamiento} caracteres) y ninguna respuesta "
                    f"(finish={finish or '?'}).", probar_otro_modelo=True, solo_razonamiento=True)
            raise _Transitorio("El modelo devolvió una respuesta vacía.", vacia=True)
        if not tokens_out:
            tokens_out = estimar_tokens(texto)
        return Respuesta(texto=texto, finish_reason=finish, modelo=modelo, tokens_entrada=tokens_in,
                         tokens_salida=tokens_out, duracion=duracion, primer_token=primer)

    def _registrar_uso(self, modelo: str, uso: dict) -> None:
        with self._lock:
            entrada = int(uso.get("prompt_tokens") or 0)
            salida = int(uso.get("completion_tokens") or 0)
            self.uso.tokens_entrada += entrada
            self.uso.tokens_salida += salida
            por = self.uso.por_modelo.setdefault(modelo, UsoModelo())
            por.tokens_entrada += entrada
            por.tokens_salida += salida
            try:
                costo = float(uso.get("cost") or 0.0)
            except (TypeError, ValueError):
                costo = 0.0
            self.uso.costo += costo
            por.costo += costo

    def _registrar_rol(self, rol: str, respuesta: Respuesta) -> None:
        if not rol:
            return
        with self._lock:
            datos = self.uso.por_rol.setdefault(rol, {"llamadas": 0, "tokens_salida": 0})
            datos["llamadas"] += 1
            datos["tokens_salida"] += respuesta.tokens_salida
