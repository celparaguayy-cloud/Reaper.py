"""Autotests del display de seis agentes + independencia (REAPER AUTO-6-IA §6/§9)."""


class TestEstadoEquipo(BaseTest):
    def test_seis_roles(self):
        estado = estado_equipo(self.ajustes())
        self.assertEqual(len(estado), 6)
        self.assertEqual([e["rol"] for e in estado],
                         ["coordinador", "arquitecto", "implementador", "revisor", "qa", "reparador"])

    def test_un_solo_proveedor_es_independencia_reducida(self):
        # por defecto todos los roles resuelven al mismo proveedor
        ind = independencia_equipo(estado_equipo(self.ajustes()))
        self.assertEqual(ind["proveedores_distintos"], 1)
        self.assertTrue(ind["reducida"])

    def test_rol_en_otro_proveedor_sube_independencia(self):
        s = self.ajustes(modelos_rol={"revisor": "ollama-qwen"})
        estado = estado_equipo(s)
        rev = next(e for e in estado if e["rol"] == "revisor")
        self.assertEqual(rev["proveedor"], "ollama")
        ind = independencia_equipo(estado)
        self.assertEqual(ind["proveedores_distintos"], 2)
        self.assertFalse(ind["reducida"])


class TestEquipoCLI(BaseTest):
    def test_comando_equipo(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/equipo")
        texto = app.ui.texto_registrado()
        self.assertIn("coordinador", texto)
        self.assertIn("NO VERIFICADA", texto)

    def test_comando_equipo_independencia(self):
        ws = self.proyecto()
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/equipo independencia")
        self.assertIn("Proveedores distintos", app.ui.texto_registrado())

    def test_plan_sigue_funcionando(self):
        # repurposar /equipo no rompe el planificador: /plan sigue siendo cmd_plan
        self.assertTrue(hasattr(App, "cmd_plan"))
