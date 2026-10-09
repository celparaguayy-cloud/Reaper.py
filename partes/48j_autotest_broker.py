"""Autotests del ExecutionBroker (REAPER v11, §9): ejecución estructurada, recibos y revalidación de alcance."""


class TestBrokerEjecucion(BaseTest):
    def test_argv_string_rechazado(self):
        r = BrokerEjecucion().ejecutar(SolicitudEjecucion(argv="echo hola"))  # string, no lista
        self.assertEqual(r.veredicto_alcance, "INVALID_ARGV")
        self.assertIsNone(r.exit_code)

    def test_comando_de_dispositivo_bloqueado(self):
        r = BrokerEjecucion().ejecutar(SolicitudEjecucion(argv=["sudo", "ls"]))
        self.assertEqual(r.veredicto_alcance, "BLOCKED_DEVICE")
        self.assertIsNone(r.exit_code)

    def test_ejecucion_local_real_con_recibo(self):
        r = BrokerEjecucion(raiz=self.dir).ejecutar(
            SolicitudEjecucion(argv=["python3", "-c", "print('hola')"], cwd=str(self.dir)))
        self.assertEqual(r.exit_code, 0)
        self.assertEqual(r.veredicto_alcance, "LOCAL_NO_NETWORK")
        self.assertIn("hola", r.stdout_preview)
        self.assertEqual(len(r.stdout_hash), 64)

    def test_red_sin_alcance_no_ejecuta(self):
        # requires_network sin PuertaAlcance: se deniega y NO corre (el archivo no se crea)
        objetivo = self.dir / "no_deberia_existir.txt"
        sol = SolicitudEjecucion(
            argv=["python3", "-c", f"open({str(objetivo)!r}, 'w').write('x')"],
            cwd=str(self.dir), requires_network=True, host="8.8.8.8", puerto=443)
        r = BrokerEjecucion().ejecutar(sol)
        self.assertEqual(r.veredicto_alcance, "SCOPE_REQUIRED")
        self.assertIsNone(r.exit_code)
        self.assertFalse(objetivo.exists())

    def test_red_fuera_de_alcance_bloqueada(self):
        pol = PoliticaAlcance(scope_id="lab", kind="isolated_lab", allowed_hosts=("127.0.0.1",),
                              expires_at="2099-12-31T23:59:59")
        r = BrokerEjecucion(PuertaAlcance(pol)).ejecutar(
            SolicitudEjecucion(argv=["python3", "-c", "print(1)"], requires_network=True, host="8.8.8.8"))
        self.assertEqual(r.veredicto_alcance, "BLOCKED_BY_SCOPE")
        self.assertIsNone(r.exit_code)

    def test_red_dentro_de_alcance_ejecuta(self):
        pol = PoliticaAlcance(scope_id="lab", kind="isolated_lab", allowed_hosts=("127.0.0.1",),
                              expires_at="2099-12-31T23:59:59")
        r = BrokerEjecucion(PuertaAlcance(pol), raiz=self.dir).ejecutar(
            SolicitudEjecucion(argv=["python3", "-c", "print('ok')"], cwd=str(self.dir),
                               requires_network=True, host="127.0.0.1"))
        self.assertEqual(r.veredicto_alcance, "ALLOW")
        self.assertEqual(r.exit_code, 0)

    def test_timeout(self):
        r = BrokerEjecucion().ejecutar(
            SolicitudEjecucion(argv=["python3", "-c", "import time; time.sleep(5)"], timeout_s=1))
        self.assertIn("TIMEOUT", r.veredicto_alcance)
        self.assertEqual(r.exit_code, -1)

    def test_exit_inesperado_se_marca(self):
        r = BrokerEjecucion(raiz=self.dir).ejecutar(
            SolicitudEjecucion(argv=["python3", "-c", "import sys; sys.exit(3)"], cwd=str(self.dir)))
        self.assertEqual(r.exit_code, 3)
        self.assertIn("UNEXPECTED_EXIT", r.veredicto_alcance)

    def test_cancelado(self):
        CANCELAR.set()
        try:
            r = BrokerEjecucion().ejecutar(SolicitudEjecucion(argv=["python3", "-c", "print(1)"]))
            self.assertEqual(r.veredicto_alcance, "CANCELLED")
            self.assertIsNone(r.exit_code)
        finally:
            CANCELAR.clear()


class TestBrokerCLI(BaseTest):
    def test_comando_ejecutar(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/ejecutar python3 -c \"print('receipt-demo')\"")
        self.assertIn("receipt-demo", app.ui.texto_registrado())
