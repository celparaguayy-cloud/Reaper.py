"""
fetch_url: leer documentación o una página web desde el agente.

Un modelo de 24B no sabe todas las APIs. Con fetch_url puede leer la
documentación oficial, un README o la respuesta a un error, convertida a
texto limpio (sin HTML, scripts ni menús) y recortada a lo relevante.

Seguridad:
  - solo GET, máximo 2 MB, timeout 20 s, sin cookies
  - fuera del modo auto pide confirmación (salvo dominios permitidos)
  - rechaza URLs con datos sospechosos (claves, query strings enormes): un
    texto malicioso no puede usar fetch_url para sacar información del proyecto
  - caché de 1 hora para no repetir descargas
"""

_RE_URL_SOSPECHOSA = re.compile(r"(sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{12,}|[A-Za-z0-9+/=]{120,})")
DOMINIOS_SEGUROS = ("docs.python.org", "developer.mozilla.org", "nodejs.org", "wiki.termux.com", "github.com",
                    "raw.githubusercontent.com", "pypi.org", "stackoverflow.com", "go.dev", "doc.rust-lang.org",
                    "en.wikipedia.org", "es.wikipedia.org", "readthedocs.io", "npmjs.com")


from html.parser import HTMLParser as _HTMLParserBase


class HTMLaTexto(_HTMLParserBase):
    """Convierte HTML en texto tipo Markdown: títulos, listas, código y links."""

    IGNORAR = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "button", "iframe", "template"}
    BLOQUES = {"p", "div", "section", "article", "main", "br", "tr", "table", "blockquote", "dd", "dt"}

    def __init__(self, base: str = ""):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.partes: list[str] = []
        self._ignorar = 0
        self._pre = 0
        self._link: Optional[str] = None
        self._texto_link: list[str] = []
        self.titulo = ""
        self._en_titulo = False

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._ignorar += 1
            return
        if self._ignorar:
            return
        atributos = dict(attrs)
        if tag == "title":
            self._en_titulo = True
        elif tag in ("h1", "h2", "h3", "h4"):
            self.partes.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.partes.append("\n- ")
        elif tag == "pre":
            self._pre += 1
            self.partes.append("\n```\n")
        elif tag == "code" and not self._pre:
            self.partes.append("`")
        elif tag == "a" and atributos.get("href"):
            self._link = urllib.parse.urljoin(self.base, atributos["href"])
            self._texto_link = []
        elif tag in self.BLOQUES:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR:
            self._ignorar = max(0, self._ignorar - 1)
            return
        if self._ignorar:
            return
        if tag == "title":
            self._en_titulo = False
        elif tag == "pre":
            self._pre = max(0, self._pre - 1)
            self.partes.append("\n```\n")
        elif tag == "code" and not self._pre:
            self.partes.append("`")
        elif tag == "a" and self._link is not None:
            texto = "".join(self._texto_link).strip()
            if texto and not self._link.startswith("javascript:") and len(texto) < 80:
                self.partes.append(f" ({self._link})" if texto != self._link else "")
            self._link = None
        elif tag in ("h1", "h2", "h3", "h4") or tag in self.BLOQUES:
            self.partes.append("\n")

    def handle_data(self, data):
        if self._ignorar:
            return
        if self._en_titulo:
            self.titulo += data
            return
        if self._link is not None:
            self._texto_link.append(data)
        self.partes.append(data if self._pre else re.sub(r"\s+", " ", data))

    def texto(self) -> str:
        crudo = "".join(self.partes)
        crudo = re.sub(r"[ \t]+\n", "\n", crudo)
        crudo = re.sub(r"\n{3,}", "\n\n", crudo)
        return crudo.strip()


def html_a_texto(html: str, base: str = "") -> tuple[str, str]:
    conversor = HTMLaTexto(base)
    try:
        conversor.feed(html)
        conversor.close()
    except (ValueError, AssertionError):
        pass
    return " ".join(conversor.titulo.split()), conversor.texto()


def filtrar_relevante(texto: str, buscar: str, contexto: int = 1, maximo: int = 8000) -> str:
    """Párrafos que contienen alguna palabra buscada (con sus vecinos)."""
    palabras = [p for p in re.findall(r"[\w.-]{3,}", sin_tildes(buscar.lower()))]
    if not palabras:
        return recortar(texto, maximo)
    parrafos = [p for p in re.split(r"\n\s*\n", texto) if p.strip()]
    marcados = set()
    for i, p in enumerate(parrafos):
        bajo = sin_tildes(p.lower())
        if any(palabra in bajo for palabra in palabras):
            for j in range(max(0, i - contexto), min(len(parrafos), i + contexto + 1)):
                marcados.add(j)
    if not marcados:
        return "(no encontré esas palabras; primeras partes de la página)\n" + recortar(texto, maximo)
    seleccion, previo = [], -2
    for i in sorted(marcados):
        if i != previo + 1:
            seleccion.append("[...]")
        seleccion.append(parrafos[i])
        previo = i
    return recortar("\n\n".join(seleccion), maximo)


import ipaddress as _web_ipaddr
import http.client as _web_httpc
import ssl as _web_ssl

PUERTOS_WEB = (80, 443, 8080, 8443)
_WEB_MAX_REDIRECTS = 5


@dataclass
class DecisionEgress:
    permitido: bool
    razon: str = ""
    estado: str = ""          # ALLOW | ESQUEMA | CREDENCIALES | PUERTO | DNS | IP_PRIVADA | SOSPECHOSA
    host: str = ""
    puerto: int = 0
    ips: tuple = ()
    confiable: bool = False


def _web_es_ip_literal(host: str):
    try:
        return _web_ipaddr.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _web_motivo_ip(ip_str: str) -> str:
    try:
        ip = _web_ipaddr.ip_address(ip_str)
    except ValueError:
        return "ip inválida"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:         # incluye 169.254.0.0/16 (metadata cloud) y fe80::/10
        return "link-local/metadata"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "no especificada"
    if ip.is_reserved:
        return "reservada"
    if ip.is_private:
        return "privada"
    if not ip.is_global:
        return "no global"
    return ""


def _web_resolver(host: str) -> list:
    """Resuelve A y AAAA. Lanza OSError si no resuelve."""
    infos = socket.getaddrinfo(host, None)
    return sorted({i[4][0] for i in infos})


def validar_destino(url: str, *, permitir_http: bool = False, permitir_local: bool = False,
                    permitidos: Sequence[str] = (), resolver=None) -> DecisionEgress:
    """
    Gate de egreso REAL (Ω §4.3): resuelve el host y clasifica TODAS sus IPs; deniega loopback, privadas,
    link-local/metadata, multicast, reservadas y no-globales. No es un filtro de texto. Deniega ANTES de
    conectar, así un destino prohibido tiene 0 conexiones. `resolver` se inyecta en tests.
    `permitir_local=True` es el canal explícito para servicios locales autorizados (p. ej. Ollama en
    localhost) y para los tests; relaja IP privada/loopback y el puerto, nunca por defecto.
    """
    resolver = resolver or _web_resolver
    url = (url or "").strip().strip("<>\"'")
    partes = urllib.parse.urlparse(url)
    scheme = (partes.scheme or "").lower()
    if scheme not in ("http", "https"):
        return DecisionEgress(False, "solo http(s)", "ESQUEMA")
    if scheme == "http" and not (permitir_http or permitir_local):
        return DecisionEgress(False, "http sin cifrar no permitido por defecto (usá https)", "ESQUEMA")
    if partes.username or partes.password:
        return DecisionEgress(False, "la URL lleva credenciales (user:pass@): rechazada", "CREDENCIALES")
    host = (partes.hostname or "").lower()
    if not host:
        return DecisionEgress(False, "falta el host", "ESQUEMA")
    puerto = partes.port or (443 if scheme == "https" else 80)
    if not permitir_local and puerto not in PUERTOS_WEB:
        return DecisionEgress(False, f"puerto {puerto} no permitido", "PUERTO")
    if len(partes.query) > 300 or _RE_URL_SOSPECHOSA.search(url):
        return DecisionEgress(False, "la URL lleva datos sospechosos (claves o query enorme)", "SOSPECHOSA")
    literal = _web_es_ip_literal(host)
    try:
        ips = [host.strip("[]")] if literal is not None else list(resolver(host))
    except OSError as e:
        return DecisionEgress(False, f"no se pudo resolver {host}: {e}", "DNS")
    if not ips:
        return DecisionEgress(False, f"{host} no resolvió a ninguna IP", "DNS")
    if not permitir_local:
        for ip in ips:
            motivo = _web_motivo_ip(ip)
            if motivo:
                return DecisionEgress(False, f"{host} resuelve a {ip} ({motivo}): bloqueado", "IP_PRIVADA",
                                      host, puerto, tuple(ips))
    confiable = any(host == d or host.endswith("." + d) for d in (*DOMINIOS_SEGUROS, *permitidos))
    return DecisionEgress(True, "ok", "ALLOW", host, puerto, tuple(ips), confiable)


def puede_heredar_auth(origen_host: str, destino_host: str) -> bool:
    """Una redirección solo conserva Authorization si va al MISMO host exacto (Ω §4.3.7)."""
    return bool(origen_host) and origen_host.lower() == (destino_host or "").lower()


def _ruta_cache(url: str) -> Path:
    return CACHE_DIR / "web" / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ".json")


def _web_charset(ctype: str) -> str:
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    return (m.group(1) if m else "utf-8")


def _web_abrir(decision: DecisionEgress, url: str, timeout: int, maximo: int) -> dict:
    """Conecta PINNEADO a la IP ya validada (anti-rebinding), SNI/Host = host. GET, sin credenciales."""
    partes = urllib.parse.urlparse(url)
    scheme = (partes.scheme or "https").lower()
    ip = decision.ips[0]
    ruta = partes.path or "/"
    if partes.query:
        ruta += "?" + partes.query
    raw = socket.create_connection((ip, decision.puerto), timeout=timeout)
    sock = raw
    conn = None
    try:
        if scheme == "https":
            sock = _web_ssl.create_default_context().wrap_socket(raw, server_hostname=decision.host)
            conn = _web_httpc.HTTPSConnection(decision.host, decision.puerto, timeout=timeout)
        else:
            conn = _web_httpc.HTTPConnection(decision.host, decision.puerto, timeout=timeout)
        conn.sock = sock
        conn.request("GET", ruta, headers={
            "Host": decision.host,
            "User-Agent": "Mozilla/5.0 (Linux; Android) REAPER/" + __version__,
            "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.5",
            "Accept-Encoding": "identity",     # sin compresión: evita bombas de descompresión (Ω §4.3.5)
            "Connection": "close",
        })
        r = conn.getresponse()
        body = r.read(maximo + 1)
        return {"status": r.status, "location": r.getheader("Location"),
                "ctype": (r.getheader("Content-Type") or "").lower(), "body": body}
    finally:
        # Si TLS falla antes de crear conn, el socket original también debe cerrarse.
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        try:
            sock.close()
        except OSError:
            pass
        if sock is not raw:
            try:
                raw.close()
            except OSError:
                pass


def descargar_texto(url: str, timeout: int = 20, maximo: int = 2_000_000, usar_cache: bool = True, *,
                    permitir_http: bool = False, permitir_local: bool = False, permitidos: Sequence[str] = (),
                    resolver=None, abrir=None) -> dict:
    """Descarga y convierte. Valida el destino (SSRF) en CADA salto y conecta pinneado. Lanza ValueError/OSError."""
    actual = (url or "").strip().strip("<>\"'")
    cache = _ruta_cache(actual)
    if usar_cache and cache.is_file():
        # Una respuesta cacheada no debe omitir el gate de egreso. El destino
        # original Y el final deben seguir siendo admisibles, sin hacer GET.
        destino = validar_destino(actual, permitir_http=permitir_http, permitir_local=permitir_local,
                                  permitidos=permitidos, resolver=resolver)
        if not destino.permitido:
            raise ValueError(destino.razon)
        try:
            datos = json.loads(cache.read_text(encoding="utf-8"))
            if not isinstance(datos, dict) or not isinstance(datos.get("texto"), str):
                raise ValueError("entrada de caché web inválida")
            final_cache = datos.get("url") or actual
            final_decision = validar_destino(final_cache, permitir_http=permitir_http,
                                             permitir_local=permitir_local, permitidos=permitidos,
                                             resolver=resolver)
            if not final_decision.permitido:
                raise ValueError(final_decision.razon)
            if time.time() - float(datos.get("guardado", 0)) < 3600:
                return datos
        except (OSError, ValueError, TypeError):
            pass
    abrir = abrir or _web_abrir
    saltos = 0
    while True:
        d = validar_destino(actual, permitir_http=permitir_http, permitir_local=permitir_local,
                            permitidos=permitidos, resolver=resolver)
        if not d.permitido:
            raise ValueError(d.razon)       # se deniega ANTES de conectar → 0 conexiones al destino prohibido
        resp = abrir(d, actual, timeout, maximo)
        status = resp["status"]
        if status in (301, 302, 303, 307, 308) and resp.get("location"):
            saltos += 1
            if saltos > _WEB_MAX_REDIRECTS:
                raise ValueError("demasiadas redirecciones")
            actual = urllib.parse.urljoin(actual, resp["location"])     # cada salto se revalida en el loop
            continue
        if status >= 400:
            raise urllib.error.HTTPError(actual, status, f"HTTP {status}", None, None)
        break
    crudo = resp["body"]
    if len(crudo) > maximo:
        raise ValueError(f"la página supera {maximo // 1_000_000} MB")
    tipo = resp["ctype"]
    codificacion = _web_charset(tipo)
    final = actual
    try:
        texto = crudo.decode(codificacion, errors="replace")
    except LookupError:  # Algunos servidores declaran charsets inválidos.
        texto = crudo.decode("utf-8", errors="replace")
    titulo = ""
    if "json" in tipo or texto.lstrip()[:1] in "[{" and "html" not in tipo:
        try:
            texto = json.dumps(json.loads(texto), ensure_ascii=False, indent=2)
            tipo = "json"
        except ValueError:
            pass
    elif "html" in tipo or "<html" in texto[:2000].lower():
        titulo, texto = html_a_texto(texto, final)
        tipo = "html"
    else:
        tipo = "texto"
    datos = {"url": final, "titulo": titulo, "tipo": tipo, "texto": texto, "guardado": time.time()}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return datos


def validar_url(url: str, permitidos: Sequence[str] = ()) -> tuple[str, bool]:
    """(url normalizada, es_de_confianza). Lanza ValueError si la URL no se debe pedir."""
    url = (url or "").strip().strip("<>\"'")
    partes = urllib.parse.urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.netloc:
        raise ValueError("solo URLs http(s) completas, p. ej. https://docs.python.org/3/library/json.html")
    host = (partes.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.endswith(".local") or re.match(r"^(10|192\.168|172\.(1[6-9]|2\d|3[01]))\.", host):
        raise ValueError("no se piden direcciones locales o de la red interna con fetch_url (usá execute_command)")
    if len(partes.query) > 300 or _RE_URL_SOSPECHOSA.search(url):
        raise ValueError("la URL lleva datos sospechosos (claves o parámetros enormes): no la pido")
    confiable = any(host == d or host.endswith("." + d) for d in (*DOMINIOS_SEGUROS, *permitidos))
    return url, confiable


@herramienta(
    "fetch_url",
    "Lee una página web (documentación oficial, README, una respuesta a un error) y devuelve su texto limpio. "
    "Con 'buscar' devuelve solo los párrafos que contienen esas palabras. Solo GET; no envía datos del proyecto.",
    [Param("url", "URL completa http(s)"),
     Param("buscar", "palabras clave para quedarse con lo relevante (opcional)", requerido=False)],
    "<fetch_url>\n<url>https://docs.python.org/3/library/sqlite3.html</url>\n<buscar>row_factory</buscar>\n</fetch_url>",
)
def fetch_url(ctx: Contexto, p: dict) -> str:
    if not ctx.settings.web:
        raise ErrorHerramienta("La lectura web está desactivada (/config web true).")
    try:
        url, confiable = validar_url(p["url"], ctx.settings.dominios_web)
    except ValueError as e:
        raise ErrorHerramienta(str(e))
    if ctx.settings.modo != "auto" and not confiable:
        ctx.ui.aviso(f"  {ctx.etiqueta} quiere leer: {url}")
        if not ctx.ui.confirmar("  ¿Permitir?"):
            raise ErrorHerramienta("El usuario no permitió leer esa URL. Seguí con lo que sabés.")
    try:
        datos = descargar_texto(url)
    except urllib.error.HTTPError as e:
        raise ErrorHerramienta(f"HTTP {e.code} al leer {url}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ErrorHerramienta(f"No pude leer {url}: {e}")
    texto = datos["texto"]
    if p.get("buscar"):
        texto = filtrar_relevante(texto, p["buscar"])
    else:
        texto = recortar(texto, 8000)
    cabecera = f"{datos['url']}" + (f" — {datos['titulo']}" if datos.get("titulo") else "") + f" ({datos['tipo']})"
    return redactar_secretos(f"{cabecera}\n\n{texto}")


from html.parser import HTMLParser as _ReaperHTMLParser
from html import unescape as _reaper_html_unescape


class _ExtractorResultadosBusqueda(_ReaperHTMLParser):
    """Parser pequeño de enlaces HTML públicos; no ejecuta JavaScript ni enlaces."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.resultados = []
        self._href = ""
        self._partes = []
        self._capturando = False

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        atributos = dict(attrs)
        clases = atributos.get("class", "").lower()
        if "result__a" in clases or "result-link" in clases:
            self._href = atributos.get("href", "")
            self._partes = []
            self._capturando = True

    def handle_data(self, data):
        if self._capturando:
            self._partes.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._capturando:
            nombre = " ".join(" ".join(self._partes).split())
            if nombre and self._href:
                self.resultados.append((nombre, self._href))
            self._capturando = False


def extraer_resultados_busqueda(html: str, limite: int = 5) -> list[tuple[str, str]]:
    extractor = _ExtractorResultadosBusqueda()
    extractor.feed(html)
    vistos, salida = set(), []
    for titulo, href in extractor.resultados:
        enlace = urllib.parse.urljoin("https://html.duckduckgo.com/", _reaper_html_unescape(href))
        destino = urllib.parse.urlparse(enlace)
        if destino.hostname and (destino.hostname == "duckduckgo.com" or
                                 destino.hostname.endswith(".duckduckgo.com")):
            redirigido = urllib.parse.parse_qs(destino.query).get("uddg", [])
            if redirigido:
                enlace = redirigido[0]
        try:
            url, _ = validar_url(enlace)
        except ValueError:
            continue
        if url not in vistos:
            vistos.add(url)
            salida.append((titulo[:180], url))
        if len(salida) >= limite:
            break
    return salida


def _consulta_web_tiene_secretos(consulta: str) -> bool:
    """Evita filtrar credenciales o fragmentos de datos personales al buscador."""
    return bool(
        _RE_URL_SOSPECHOSA.search(consulta)
        or re.search(r"(?i)\b(?:api[_ -]?key|secret|token|password|contrase(?:n|ñ)a|bearer)\s*[:=]\s*\S+", consulta)
        or re.search(r"(?i)\b(?:gh[pousr]_[a-z0-9]{12,}|sk-[a-z0-9_-]{12,}|AIza[a-z0-9_-]{20,})\b", consulta)
        or re.search(r"(?i)(?:/data/data/|/sdcard/|~?/storage/|~?/\.ssh/|-----BEGIN .*PRIVATE KEY)", consulta)
    )


@herramienta(
    "web_search",
    "Busca documentación pública, errores de programación o datos recientes y devuelve títulos con URL. "
    "Después abrí las fuentes con fetch_url. No ejecuta scripts ni instala paquetes.",
    [Param("query", "consulta de búsqueda, sin claves ni datos privados"),
     Param("max_results", "máximo de resultados, 1 a 8", requerido=False)],
    "<web_search>\n<query>Python sqlite3 documentación transacciones</query>\n</web_search>",
)
def web_search(ctx: Contexto, p: dict) -> str:
    if not ctx.settings.web or ctx.settings.privacidad_estricta:
        raise ErrorHerramienta("Búsqueda web desactivada (web=false o privacidad_estricta=true).")
    consulta = str(p.get("query") or "").strip()
    if not consulta or len(consulta) > 250:
        raise ErrorHerramienta("La consulta debe tener entre 1 y 250 caracteres.")
    if _consulta_web_tiene_secretos(consulta):
        raise ErrorHerramienta("La consulta parece contener credenciales o rutas privadas; eliminá esos datos.")
    limite = max(1, min(8, _entero(p.get("max_results"), 5)))
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": consulta})
    error_primario = ""
    try:
        datos = descargar_texto(url, usar_cache=True, maximo=850_000, timeout=15,
                                permitidos=("duckduckgo.com",))
        texto = str(datos.get("texto") or "")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
        texto = ""
        error_primario = f"{type(e).__name__}: {e}"
    # descargar_texto transforma HTML en texto. HTMLaTexto conserva URLs en paréntesis.
    resultados = extraer_resultados_busqueda(texto, limite)
    if not resultados:
        # descargar_texto convierte HTML en texto: HTMLaTexto conserva el enlace como
        # 'Título (URL)' y no como Markdown. El motor puede responder con enlaces
        # de redirección de DuckDuckGo; se extrae uddg cuando está presente.
        enlaces = re.findall(r"([^\n()]{5,180}?)\s*\((https?://[^)\s]+)\)", texto)
        vistos = set()
        for titulo, enlace in enlaces:
            titulo = titulo.strip().split("  ")[-1][-180:].strip()
            p_url = urllib.parse.urlparse(enlace)
            if p_url.hostname and (p_url.hostname == "duckduckgo.com" or
                                   p_url.hostname.endswith(".duckduckgo.com")):
                destino = urllib.parse.parse_qs(p_url.query).get("uddg", [])
                if destino:
                    enlace = destino[0]
            try:
                validar_url(enlace)
            except ValueError:
                continue
            if not titulo or enlace in vistos:
                continue
            vistos.add(enlace)
            resultados.append((titulo, enlace))
            if len(resultados) >= limite:
                break
    if not resultados:
        # Respaldo independiente: XML RSS público de Bing, sin claves API.
        try:
            import xml.etree.ElementTree as _web_et
            rss_url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": consulta, "format": "rss"})
            rss = descargar_texto(rss_url, usar_cache=True, maximo=500_000, timeout=15,
                                  permitidos=("bing.com",))
            raiz_xml = _web_et.fromstring(str(rss.get("texto") or ""))
            for item in raiz_xml.findall(".//channel/item"):
                titulo = (item.findtext("title") or "").strip()
                enlace = (item.findtext("link") or "").strip()
                try:
                    validar_url(enlace)
                except ValueError:
                    continue
                if titulo and enlace and (titulo, enlace) not in resultados:
                    resultados.append((titulo[:180], enlace))
                if len(resultados) >= limite:
                    break
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError, _web_et.ParseError):
            pass
    if not resultados:
        raise ErrorHerramienta("No se pudo recuperar ningún resultado fiable de los motores web. "
                               + (error_primario[:160] + ". " if error_primario else "")
                               + "No inventes enlaces ni afirmes búsqueda exitosa.")
    return "Resultados web (no verificados; abrí los enlaces con fetch_url):\n" + "\n".join(
        f"{i}. {titulo} — {enlace}" for i, (titulo, enlace) in enumerate(resultados, 1))


ALIAS_HERRAMIENTAS.update({"web": "fetch_url", "leer_web": "fetch_url", "browse": "fetch_url",
                           "open_url": "fetch_url", "web_fetch": "fetch_url", "curl": "fetch_url",
                           "buscar_web": "web_search", "search_web": "web_search"})
