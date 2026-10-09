"""Autotests del Security Scope Gate + modelo de hallazgos/evidencia (REAPER v11, Fase 1)."""


def _pol_valida(**kw):
    base = dict(scope_id="lab-001", kind="isolated_lab",
                allowed_hosts=("127.0.0.1", "lab.internal"), allowed_ports=(80, 443, 8080),
                allowed_operations=("read_only_http_checks", "lab_specific_validation"),
                expires_at="2099-12-31T23:59:59")
    base.update(kw)
    return PoliticaAlcance(**base)


class TestPuertaAlcance(BaseTest):
    def test_sin_politica_deniega_red_activa(self):
        d = PuertaAlcance().decidir("127.0.0.1", 80)
        self.assertFalse(d.permitido)
        self.assertEqual(d.estado, "SCOPE_REQUIRED")

    def test_dentro_de_alcance_permite(self):
        d = PuertaAlcance(_pol_valida()).decidir("127.0.0.1", 80, "read_only_http_checks")
        self.assertTrue(d.permitido)
        self.assertEqual(d.estado, "ALLOW")

    def test_host_fuera_de_alcance(self):
        d = PuertaAlcance(_pol_valida()).decidir("8.8.8.8", 80)
        self.assertFalse(d.permitido)
        self.assertEqual(d.estado, "BLOCKED_BY_SCOPE")

    def test_puerto_no_permitido(self):
        d = PuertaAlcance(_pol_valida()).decidir("127.0.0.1", 22)
        self.assertEqual(d.estado, "DENIED")

    def test_operacion_no_permitida(self):
        d = PuertaAlcance(_pol_valida()).decidir("127.0.0.1", 80, "exploit")
        self.assertEqual(d.estado, "DENIED")

    def test_politica_vencida(self):
        d = PuertaAlcance(_pol_valida(expires_at="2000-01-01T00:00:00")).decidir("127.0.0.1", 80)
        self.assertEqual(d.estado, "EXPIRED")

    def test_host_metadata_siempre_bloqueado(self):
        # aunque el usuario pase una política, el host de metadata/link-local nunca entra en alcance
        d = PuertaAlcance(_pol_valida()).decidir("169.254.169.254")
        self.assertEqual(d.estado, "BLOCKED_BY_SCOPE")

    def test_politica_invalida_sin_expires(self):
        d = PuertaAlcance(_pol_valida(expires_at="")).decidir("127.0.0.1", 80)
        self.assertEqual(d.estado, "INVALID")

    def test_normaliza_host_desde_url(self):
        d = PuertaAlcance(_pol_valida()).decidir("http://LAB.INTERNAL:8080/panel", 8080, "lab_specific_validation")
        self.assertTrue(d.permitido)

    def test_el_gate_no_puede_ampliarse(self):
        # el LLM no puede ensanchar el alcance: la clase no expone ningún método para agregar hosts/operaciones
        gate = PuertaAlcance(_pol_valida())
        for metodo in ("add_host", "permitir", "ampliar", "importar", "set_politica", "allow", "agregar_host"):
            self.assertFalse(hasattr(gate, metodo), f"PuertaAlcance no debería tener {metodo}")


class TestPoliticaAlcance(BaseTest):
    def test_valida_detecta_faltantes(self):
        ok, problemas = PoliticaAlcance(scope_id="", kind="raro", allowed_hosts=()).valida()
        self.assertFalse(ok)
        self.assertTrue(any("scope_id" in p for p in problemas))
        self.assertTrue(any("kind" in p for p in problemas))

    def test_cargar_desde_dict(self):
        pol = cargar_politica_alcance({"scope_id": "d1", "kind": "owned_dev",
                                       "allowed_hosts": ["127.0.0.1"], "expires_at": "2099-01-01T00:00:00"})
        self.assertEqual(pol.scope_id, "d1")
        self.assertIn("127.0.0.1", pol.allowed_hosts)
        self.assertTrue(pol.valida()[0])

    def test_cargar_desde_json(self):
        ruta = self.dir / "scope.json"
        ruta.write_text(json.dumps({"scope_id": "j1", "kind": "isolated_lab",
                                    "allowed_hosts": ["lab.internal"], "allowed_ports": [80],
                                    "expires_at": "2099-01-01T00:00:00"}), encoding="utf-8")
        pol = cargar_politica_alcance(ruta)
        self.assertEqual((pol.scope_id, pol.allowed_ports), ("j1", (80,)))


class TestHallazgoYRecibo(BaseTest):
    def test_estado_invalido_cae_a_unverified(self):
        self.assertEqual(Hallazgo("h", "x", estado="inventado").estado, "UNVERIFIED")

    def test_version_match_no_es_confirmado(self):
        self.assertFalse(Hallazgo("h", "x", estado="VERSION_MATCH_ONLY").confirmado())
        self.assertFalse(es_hallazgo_confirmado("STATIC_FINDING"))

    def test_solo_lab_es_confirmado(self):
        self.assertTrue(Hallazgo("h", "x", estado="CONFIRMED_LAB").confirmado())
        self.assertTrue(es_hallazgo_confirmado("VERIFIED_IN_LAB"))

    def test_recibo_hashea_salida_real(self):
        r1 = recibo_de_ejecucion("r1", ["python3", "x.py"], stdout="hola", exit_code=0)
        r2 = recibo_de_ejecucion("r2", ["python3", "x.py"], stdout="chau", exit_code=0)
        self.assertNotEqual(r1.stdout_hash, r2.stdout_hash)
        self.assertEqual(r1.stdout_hash, recibo_de_ejecucion("r3", [], stdout="hola").stdout_hash)
        self.assertEqual(len(r1.stdout_hash), 64)        # sha256 hex
