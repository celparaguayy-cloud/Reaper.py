"""Autotests de la memoria de desempeño + router aprendido (Fase 7 / v9)."""


class TestMemoriaDesempeno(BaseTest):
    def memoria(self):
        return MemoriaDesempeno(ruta=self.dir / "desempeno.json")

    def test_prior_sin_datos(self):
        m = self.memoria()
        self.assertEqual(m.puntaje("implementador", "qwen"), m.prior)

    def test_puntaje_sube_con_exitos(self):
        m = self.memoria()
        for _ in range(5):
            m.registrar("implementador", "qwen", True, verificado=True)
        m.registrar("implementador", "venice", False)
        self.assertGreater(m.puntaje("implementador", "qwen"), m.puntaje("implementador", "venice"))

    def test_elegir_mejor_modelo(self):
        m = self.memoria()
        for _ in range(4):
            m.registrar("reparador", "deepseek", True, verificado=True)
        for _ in range(4):
            m.registrar("reparador", "venice", False)
        self.assertEqual(m.elegir("reparador", ["venice", "deepseek"]), "deepseek")

    def test_empate_gana_el_primero(self):
        m = self.memoria()       # sin datos: todos en prior → estable, gana el default (primero)
        self.assertEqual(m.elegir("implementador", ["venice", "qwen", "deepseek"]), "venice")

    def test_excluir_para_revisor(self):
        m = self.memoria()
        for _ in range(4):
            m.registrar("revisor", "qwen", True, verificado=True)
        # aunque qwen sea el mejor, si lo excluimos (lo usó el implementador) elige otro
        self.assertNotEqual(m.elegir("revisor", ["qwen", "deepseek"], excluir=["qwen"]), "qwen")

    def test_excluir_todos_no_deja_sin_opcion(self):
        m = self.memoria()
        self.assertIn(m.elegir("revisor", ["qwen"], excluir=["qwen"]), ["qwen", resolver_modelo("qwen")])

    def test_persiste_entre_instancias(self):
        ruta = self.dir / "desempeno.json"
        MemoriaDesempeno(ruta=ruta).registrar("qa", "qwen", True, verificado=True)
        self.assertGreater(MemoriaDesempeno(ruta=ruta).puntaje("qa", "qwen"), 0.5)

    def test_resumen(self):
        m = self.memoria()
        m.registrar("implementador", "qwen", True, verificado=True)
        self.assertIn("implementador", m.resumen())
        self.assertIn("qwen", m.resumen())


class TestRouterEnAgente(BaseTest):
    def test_agente_registra_desempeno(self):
        ws = self.proyecto()
        m = MemoriaDesempeno(ruta=self.dir / "d.json")
        llm = MockLLM(lambda *_: terminar_xml("Es 4."))
        Agente("principal", llm, ws, self.ajustes(forense=False, escalar=False), self.ui(),
               memoria=None, mostrar_progreso=False, desempeno=m).ejecutar("cuánto es 2+2")
        self.assertIn("principal", m.resumen())

    def test_router_elige_modelo_aprendido(self):
        ws = self.proyecto()
        m = MemoriaDesempeno(ruta=self.dir / "d.json")
        for _ in range(5):
            m.registrar("principal", resolver_modelo("qwen"), True, verificado=True)
        for _ in range(5):
            m.registrar("principal", resolver_modelo(self.ajustes().modelo), False)
        llm = MockLLM(lambda *_: terminar_xml("Es 4."))
        ag = Agente("principal", llm, ws, self.ajustes(forense=False, escalar=False, fallbacks=["qwen"]),
                    self.ui(), memoria=None, mostrar_progreso=False, desempeno=m)
        ag.ejecutar("cuánto es 2+2")
        self.assertEqual(ag._modelo_elegido, resolver_modelo("qwen"))

    def test_sin_desempeno_no_cambia_modelo(self):
        ws = self.proyecto()
        llm = MockLLM(lambda *_: terminar_xml("Es 4."))
        ag = Agente("principal", llm, ws, self.ajustes(forense=False, escalar=False, fallbacks=["qwen"]),
                    self.ui(), memoria=None, mostrar_progreso=False)
        ag.ejecutar("cuánto es 2+2")
        self.assertIsNone(ag._modelo_elegido)
