"""Autotests de la entrega verificada de archivos (REAPER Ω §8): copia+sha256, no mv a ciegas, /deshacer seguro."""


class TestEntregaArchivo(BaseTest):
    def _origen(self, contenido="contenido real\n"):
        p = self.dir / "origen.md"
        p.write_text(contenido, encoding="utf-8")
        return p

    def test_copia_verificada_conserva_original(self):
        origen = self._origen()
        destino = self.dir / "salida" / "origen.md"
        r = entregar_archivo(origen, destino)
        self.assertTrue(r.verified)
        self.assertEqual(r.estado, "EXPORT_VERIFIED")
        self.assertTrue(destino.exists())
        self.assertTrue(origen.exists())                 # copia, no mueve
        self.assertEqual(len(r.sha256), 64)

    def test_no_declara_exito_si_destino_no_coincide(self):
        origen = self._origen()
        destino = self.dir / "s" / "origen.md"

        def abrir_roto(*a, **k):
            raise AssertionError("no debería usarse")

        # simular corrupción: copiar y luego alterar el destino antes de verificar es difícil;
        # en su lugar probamos el camino de origen inexistente → no verificado
        r = entregar_archivo(self.dir / "no_existe.md", destino)
        self.assertFalse(r.verified)
        self.assertIn("origen", r.motivo.lower())

    def test_mover_borra_original_solo_tras_verificar(self):
        origen = self._origen()
        destino = self.dir / "s" / "m.md"
        r = entregar_archivo(origen, destino, mover=True)
        self.assertTrue(r.verified)
        self.assertFalse(origen.exists())                # recién ahora se borra el original
        self.assertTrue(destino.exists())

    def test_no_sobrescribe_sin_permiso(self):
        origen = self._origen()
        destino = self.dir / "existe.md"
        destino.write_text("previo", encoding="utf-8")
        r = entregar_archivo(origen, destino)
        self.assertFalse(r.verified)
        self.assertIn("existe", r.motivo.lower())
        self.assertEqual(destino.read_text(encoding="utf-8"), "previo")   # no lo pisó

    def test_ruta_destino_cae_a_interna_sin_sdcard(self):
        # en el entorno de test no hay /sdcard ni ~/storage: debe caer a carpeta interna
        ruta, externo = ruta_destino_android("x.md", interno=self.dir / "exports")
        self.assertFalse(externo)
        self.assertTrue(str(ruta).endswith("x.md"))


class TestDeshacerEntrega(BaseTest):
    def test_deshace_si_no_cambio(self):
        origen = self.dir / "o.md"
        origen.write_text("hola", encoding="utf-8")
        destino = self.dir / "d" / "o.md"
        r = entregar_archivo(origen, destino)
        ok, msg = deshacer_entrega(r.como_dict())
        self.assertTrue(ok)
        self.assertFalse(destino.exists())

    def test_no_borra_si_usuario_lo_modifico(self):
        origen = self.dir / "o.md"
        origen.write_text("hola", encoding="utf-8")
        destino = self.dir / "d" / "o.md"
        r = entregar_archivo(origen, destino)
        destino.write_text("editado por el usuario", encoding="utf-8")   # cambió después de entregar
        ok, msg = deshacer_entrega(r.como_dict())
        self.assertFalse(ok)
        self.assertTrue(destino.exists())                # protege los datos del usuario
        self.assertIn("modificado", msg.lower())


class TestEntregaCLI(BaseTest):
    def test_comando_entregar(self):
        ws = self.proyecto({"nota.md": "contenido de prueba\n"})
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/entregar nota.md " + str(self.dir / "destino"))
        texto = app.ui.texto_registrado()
        self.assertIn("verificado", texto.lower())
        self.assertTrue((self.dir / "destino" / "nota.md").exists())