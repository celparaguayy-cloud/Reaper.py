"""Autotests del Lab Challenge Engine (REAPER v11, §8/§23): juez independiente y flag no falsificable."""


class TestMotorLab(BaseTest):
    def motor(self):
        return MotorLab(self.proyecto().raiz)

    def test_listar_escenarios(self):
        ids = {e["id"] for e in self.motor().listar()}
        self.assertIn("web-config-inseguro", ids)
        self.assertIn("web-config-parcheado", ids)
        self.assertIn("deps-desactualizadas", ids)

    def test_iniciar_materializa_fixture(self):
        m = self.motor()
        info = m.iniciar("web-config-inseguro")
        self.assertTrue((info["dir"] / "settings.py").exists())
        self.assertTrue(info["fixture_hash"])
        self.assertEqual(info["scope"].kind, "isolated_lab")

    def test_lab_positivo_pasa_y_acuna_flag(self):
        m = self.motor()
        res = m.evaluar("web-config-inseguro", resolver_con_auditor("web-config-inseguro"))
        self.assertEqual(res.result, "PASS")
        self.assertTrue(res.flag)
        self.assertTrue(verificar_flag_lab("web-config-inseguro", res.fixture_hash, res.flag))

    def test_lab_negativo_abstencion_correcta(self):
        m = self.motor()
        res = m.evaluar("web-config-parcheado", resolver_con_auditor("web-config-parcheado"))
        self.assertEqual(res.result, "PASS")          # no reportar nada grave en el fixture sano = correcto

    def test_falso_positivo_falla(self):
        m = self.motor()
        inventado = [Hallazgo("x", "Inventado grave", estado="STATIC_FINDING", severidad="alta")]
        res = m.evaluar("web-config-parcheado", inventado)
        self.assertEqual(res.result, "FAIL")
        self.assertFalse(res.flag)
        self.assertIn("falso positivo", res.reason.lower())

    def test_no_detectar_falla(self):
        m = self.motor()
        res = m.evaluar("web-config-inseguro", [])      # candidato que no encontró nada
        self.assertEqual(res.result, "FAIL")
        self.assertFalse(res.flag)

    def test_deps_positivo(self):
        m = self.motor()
        res = m.evaluar("deps-desactualizadas", resolver_con_auditor("deps-desactualizadas"))
        self.assertEqual(res.result, "PASS")

    def test_deps_invento_de_mas_falla(self):
        m = self.motor()
        hs = resolver_con_auditor("deps-desactualizadas") + [
            Hallazgo("y", "requests==2.31.0: revisar versión", estado="VERSION_MATCH_ONLY", severidad="media")]
        res = m.evaluar("deps-desactualizadas", hs)
        self.assertEqual(res.result, "FAIL")

    def test_flag_inventado_no_valida(self):
        info = self.motor().iniciar("web-config-inseguro")
        self.assertFalse(verificar_flag_lab("web-config-inseguro", info["fixture_hash"], "LAB_FLAG-FALSO"))
        self.assertFalse(verificar_flag_lab("web-config-inseguro", info["fixture_hash"], ""))

    def test_reiniciar_borra_fixture(self):
        m = self.motor()
        info = m.iniciar("web-config-inseguro")
        self.assertTrue(info["dir"].exists())
        self.assertTrue(m.reiniciar("web-config-inseguro"))
        self.assertFalse(info["dir"].exists())
        # tras el reset, iniciar de nuevo funciona (sin contaminación) y el flag es el mismo (fixture determinista)
        res2 = m.evaluar("web-config-inseguro", resolver_con_auditor("web-config-inseguro"))
        self.assertEqual(res2.result, "PASS")

    def test_escenario_desconocido(self):
        with self.assertRaises(ValueError):
            self.motor().evaluar("no-existe", [])


class TestLabCLI(BaseTest):
    def test_comando_lab_probar(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/lab probar web-config-inseguro")
        texto = app.ui.texto_registrado()
        self.assertIn("PASS", texto)
        self.assertIn("LAB_FLAG", texto)

    def test_comando_lab_escenarios(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/lab escenarios")
        self.assertIn("web-config-inseguro", app.ui.texto_registrado())
