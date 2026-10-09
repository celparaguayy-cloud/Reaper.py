"""Autotest del desempate por discriminación en el torneo (Fase 9 / v9): la evidencia real decide el ganador."""


class TestTorneoDiscriminacion(BaseTest):
    def _cand(self, idx, discriminacion, pasados=3):
        c = Candidato(idx, 0.2)
        c.conteo = ConteoTests(pasados=pasados, reconocido=True)
        c.cambios = ["archivo.py"]          # hizo algo (clave usa bool(cambios))
        c.discriminacion = discriminacion
        return c

    def test_gana_el_de_tests_que_discriminan(self):
        debil = self._cand(0, 0.3)          # mismos tests pasando, pero NO discriminan
        fuerte = self._cand(1, 1.0)         # tests que sí discriminan
        ganador = sorted([debil, fuerte], key=lambda c: c.clave())[0]
        self.assertEqual(ganador.indice, 1)

    def test_discriminacion_no_pisa_mas_tests_pasando(self):
        # un candidato con más tests pasando gana aunque discrimine un poco menos
        muchos = self._cand(0, 0.8, pasados=5)
        pocos = self._cand(1, 1.0, pasados=2)
        ganador = sorted([muchos, pocos], key=lambda c: c.clave())[0]
        self.assertEqual(ganador.indice, 0)

    def test_discriminacion_en_la_fila(self):
        fila = self._cand(0, 0.42).fila()
        self.assertIn("0.42", fila)
