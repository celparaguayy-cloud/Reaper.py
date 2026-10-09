"""Autotests de los auditores offline y del importador nmap (REAPER v11, §7/§21 iteración A)."""

# Fixtures sintéticos (datos inventados). Positivo = inseguro; negativo = corregido.
_AUD_VULN = (
    "DEBUG = True\n"
    "ALLOWED_HOSTS = ['*']\n"
    "SESSION_COOKIE_SECURE = False\n"
    "API_KEY = 'sk-abcdef123456'\n"
    "import requests\n"
    "requests.get(url, verify=False)\n"
)
_AUD_OK = (
    "import os\n"
    "DEBUG = False\n"
    "ALLOWED_HOSTS = ['example.com']\n"
    "SESSION_COOKIE_SECURE = True\n"
    "API_KEY = os.environ['API_KEY']\n"
    "import requests\n"
    "requests.get(url, verify=True)\n"
)
_AUD_NMAP = (
    '<?xml version="1.0"?>\n<nmaprun>\n'
    '  <host>\n    <address addr="127.0.0.1" addrtype="ipv4"/>\n    <ports>\n'
    '      <port protocol="tcp" portid="443"><state state="open"/><service name="https"/></port>\n'
    '      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>\n'
    '    </ports>\n  </host>\n</nmaprun>\n'
)


class TestAuditorConfig(BaseTest):
    def test_detecta_config_insegura(self):
        hs = auditar_config(_AUD_VULN, "settings.py")
        self.assertTrue(hs)
        self.assertTrue(any(h.severidad == "alta" for h in hs))
        self.assertTrue(all(h.estado == "STATIC_FINDING" for h in hs))

    def test_fixture_corregido_no_da_falsos_positivos(self):
        # discriminación tipo laboratorio: el fixture parcheado NO debe disparar hallazgos
        self.assertEqual(auditar_config(_AUD_OK, "settings.py"), [])

    def test_hallazgos_no_son_confirmados(self):
        # un hallazgo estático jamás es "confirmado en laboratorio"
        self.assertFalse(any(h.confirmado() for h in auditar_config(_AUD_VULN)))


class TestAnalizarDependencias(BaseTest):
    def test_version_vieja_marca_version_match_only(self):
        hs = analizar_dependencias("pyyaml==5.1\nflask==0.10\n")
        self.assertTrue(hs)
        self.assertTrue(all(h.estado == "VERSION_MATCH_ONLY" for h in hs))
        self.assertFalse(any(h.confirmado() for h in hs))

    def test_version_nueva_no_marca(self):
        self.assertEqual(analizar_dependencias("pyyaml==6.0.1\n"), [])

    def test_paquete_desconocido_no_marca(self):
        self.assertEqual(analizar_dependencias("paquete-inventado==1.0\n"), [])


class TestImportarNmap(BaseTest):
    def test_parsea_inventario(self):
        inv = importar_nmap_xml(_AUD_NMAP)
        self.assertEqual(len(inv["hosts"]), 1)
        host = inv["hosts"][0]
        self.assertEqual(host["host"], "127.0.0.1")
        self.assertEqual(len(host["puertos"]), 2)
        self.assertEqual(host["puertos"][0]["puerto"], 80)       # ordenado
        self.assertEqual(host["puertos"][0]["servicio"], "http")

    def test_determinista(self):
        self.assertEqual(importar_nmap_xml(_AUD_NMAP), importar_nmap_xml(_AUD_NMAP))

    def test_xml_corrupto_rechazado(self):
        with self.assertRaises(ValueError):
            importar_nmap_xml("<nmaprun><host>")        # sin cerrar

    def test_xml_no_nmap_rechazado(self):
        with self.assertRaises(ValueError):
            importar_nmap_xml("<algo><x/></algo>")


class TestAuditorCLI(BaseTest):
    def test_comando_auditar(self):
        ws = self.proyecto({"settings.py": _AUD_VULN})
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/auditar settings.py")
        texto = app.ui.texto_registrado()
        self.assertIn("hallazgo", texto.lower())
