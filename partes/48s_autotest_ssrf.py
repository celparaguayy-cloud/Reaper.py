"""Autotests del gate de egreso / SSRF (REAPER Ω §4.3): deniega ANTES de conectar, valida cada salto."""


def _resolver_fijo(ip):
    return lambda host: [ip]


class TestValidarDestino(BaseTest):
    def test_https_publica_permitida(self):
        d = validar_destino("https://docs.python.org/3/", resolver=_resolver_fijo("151.101.0.223"))
        self.assertTrue(d.permitido)
        self.assertTrue(d.confiable)

    def test_http_denegado_por_defecto(self):
        d = validar_destino("http://ejemplo.com/", resolver=_resolver_fijo("93.184.216.34"))
        self.assertFalse(d.permitido)
        self.assertEqual(d.estado, "ESQUEMA")

    def test_credenciales_en_url(self):
        d = validar_destino("https://user:pass@ejemplo.com/", resolver=_resolver_fijo("93.184.216.34"))
        self.assertEqual(d.estado, "CREDENCIALES")

    def test_esquema_no_http(self):
        self.assertFalse(validar_destino("ftp://x/").permitido)
        self.assertFalse(validar_destino("file:///etc/passwd").permitido)

    def test_puerto_no_permitido(self):
        d = validar_destino("https://ejemplo.com:22/", resolver=_resolver_fijo("93.184.216.34"))
        self.assertEqual(d.estado, "PUERTO")

    def test_loopback_por_dns_bloqueado(self):
        # host público que RESUELVE a loopback: el filtro textual no lo vería; el gate sí
        d = validar_destino("https://malicioso.example/", resolver=_resolver_fijo("127.0.0.1"))
        self.assertFalse(d.permitido)
        self.assertEqual(d.estado, "IP_PRIVADA")

    def test_ip_privada_bloqueada(self):
        self.assertFalse(validar_destino("https://x.example/", resolver=_resolver_fijo("192.168.1.10")).permitido)
        self.assertFalse(validar_destino("https://x.example/", resolver=_resolver_fijo("10.0.0.5")).permitido)

    def test_metadata_cloud_bloqueada(self):
        d = validar_destino("https://x.example/", resolver=_resolver_fijo("169.254.169.254"))
        self.assertFalse(d.permitido)

    def test_ip_literal_privada(self):
        self.assertFalse(validar_destino("https://127.0.0.1/").permitido)
        self.assertFalse(validar_destino("https://[::1]/").permitido)

    def test_permitir_local_abre_loopback(self):
        d = validar_destino("http://127.0.0.1:8123/x", permitir_local=True)
        self.assertTrue(d.permitido)

    def test_query_sospechosa(self):
        d = validar_destino("https://x.example/?k=sk-abcdefghijklmnopqrst", resolver=_resolver_fijo("1.2.3.4"))
        self.assertEqual(d.estado, "SOSPECHOSA")

    def test_hereda_auth_solo_mismo_host(self):
        self.assertTrue(puede_heredar_auth("api.groq.com", "api.groq.com"))
        self.assertFalse(puede_heredar_auth("api.groq.com", "evil.example"))


class TestDescargarSSRF(BaseTest):
    def test_destino_prohibido_cero_conexiones(self):
        llamadas = []

        def abrir_espia(d, url, timeout, maximo):
            llamadas.append(url)
            return {"status": 200, "location": None, "ctype": "text/plain", "body": b"x"}

        # host que resuelve a IP privada: debe denegarse ANTES de llamar a 'abrir'
        with self.assertRaises(ValueError):
            descargar_texto("https://interno.example/secreto", usar_cache=False,
                            resolver=_resolver_fijo("10.0.0.9"), abrir=abrir_espia)
        self.assertEqual(llamadas, [])          # 0 conexiones al destino prohibido

    def test_redireccion_a_privada_se_bloquea(self):
        estados = {"n": 0}

        def abrir(d, url, timeout, maximo):
            estados["n"] += 1
            if estados["n"] == 1:
                return {"status": 302, "location": "https://interno.example/x", "ctype": "", "body": b""}
            return {"status": 200, "location": None, "ctype": "text/plain", "body": b"secreto"}

        def resolver(host):
            return ["1.2.3.4"] if host == "publica.example" else ["127.0.0.1"]

        with self.assertRaises(ValueError):
            descargar_texto("https://publica.example/", usar_cache=False, resolver=resolver, abrir=abrir)
        self.assertEqual(estados["n"], 1)       # el 2º salto (privado) se bloquea antes de conectar

    def test_descarga_ok_con_abrir_inyectado(self):
        def abrir(d, url, timeout, maximo):
            return {"status": 200, "location": None, "ctype": "text/plain", "body": b"hola mundo"}
        datos = descargar_texto("https://docs.python.org/x", usar_cache=False,
                                resolver=_resolver_fijo("151.101.0.223"), abrir=abrir)
        self.assertEqual(datos["texto"], "hola mundo")

    def test_demasiadas_redirecciones(self):
        def abrir(d, url, timeout, maximo):
            return {"status": 302, "location": "https://docs.python.org/otra", "ctype": "", "body": b""}
        with self.assertRaises(ValueError):
            descargar_texto("https://docs.python.org/a", usar_cache=False,
                            resolver=_resolver_fijo("151.101.0.223"), abrir=abrir)