"""Autotests del TaskGraph (Fase 8 / v9): orden topológico por dependencias y olas en paralelo."""


def _t(id, archivos=None, deps=None):
    return Tarea(id, f"tarea {id}", archivos or [], deps or [])


class TestGrafoTareas(BaseTest):
    def test_sin_deps_respeta_orden_del_plan(self):
        g = GrafoTareas([_t("1"), _t("2"), _t("3")])
        self.assertEqual([t.id for t in g.orden()], ["1", "2", "3"])
        self.assertFalse(g.tiene_ciclo())

    def test_orden_topologico(self):
        # 3 depende de 1 y 2; aunque esté primero en el plan, va después
        g = GrafoTareas([_t("3", deps=["1", "2"]), _t("1"), _t("2")])
        orden = [t.id for t in g.orden()]
        self.assertLess(orden.index("1"), orden.index("3"))
        self.assertLess(orden.index("2"), orden.index("3"))

    def test_cadena(self):
        g = GrafoTareas([_t("a"), _t("b", deps=["a"]), _t("c", deps=["b"])])
        self.assertEqual([t.id for t in g.orden()], ["a", "b", "c"])

    def test_ciclo_cae_al_orden_del_plan(self):
        g = GrafoTareas([_t("1", deps=["2"]), _t("2", deps=["1"])])
        self.assertTrue(g.tiene_ciclo())
        self.assertEqual(len(g.orden()), 2)             # no pierde tareas
        self.assertTrue(any("ciclo" in p for p in g.problemas))

    def test_dep_inexistente_se_ignora(self):
        g = GrafoTareas([_t("1", deps=["99"]), _t("2")])
        self.assertEqual([t.id for t in g.orden()], ["1", "2"])
        self.assertTrue(any("no existe" in p for p in g.problemas))

    def test_olas_paralelas_por_archivos_disjuntos(self):
        # 1 y 2 no dependen entre sí y tocan archivos distintos → misma ola
        g = GrafoTareas([_t("1", archivos=["a.py"]), _t("2", archivos=["b.py"]), _t("3", archivos=["a.py"], deps=["1"])])
        olas = g.olas()
        self.assertIn({"1", "2"}, [set(t.id for t in o) for o in olas])

    def test_olas_separa_archivos_compartidos(self):
        g = GrafoTareas([_t("1", archivos=["x.py"]), _t("2", archivos=["x.py"])])
        olas = [set(t.id for t in o) for o in g.olas()]
        self.assertEqual(olas, [{"1"}, {"2"}])          # comparten x.py → olas separadas

    def test_tarea_sin_archivos_corre_sola(self):
        g = GrafoTareas([_t("1"), _t("2", archivos=["b.py"])])
        olas = [set(t.id for t in o) for o in g.olas()]
        self.assertEqual(olas[0], {"1"})                # footprint desconocido → sola

    def test_olas_cubren_todas_las_tareas(self):
        g = GrafoTareas([_t("1", archivos=["a.py"]), _t("2", archivos=["b.py"], deps=["1"]),
                         _t("3", archivos=["c.py"])])
        ids = {t.id for o in g.olas() for t in o}
        self.assertEqual(ids, {"1", "2", "3"})


class TestPlanConDeps(BaseTest):
    def test_parsear_plan_lee_deps(self):
        texto = ('<plan><objetivo>x</objetivo>'
                 '<tarea id="1" archivos="a.py">hacer a</tarea>'
                 '<tarea id="2" archivos="b.py" deps="1">hacer b</tarea></plan>')
        plan = parsear_plan(texto, "pedido")
        self.assertEqual(plan.tareas[1].deps, ["1"])
        self.assertEqual([t.id for t in GrafoTareas(plan.tareas).orden()], ["1", "2"])
