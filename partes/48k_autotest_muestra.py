"""Autotests del análisis estático de muestras (REAPER v11, §10) — defensivo, nunca ejecuta."""

# "Muestras" sintéticas en bytes (inventadas, inofensivas): nunca se ejecutan.
_MU_PE = b"MZ" + b"\x00" * 60 + b"este binario llama a VirtualAlloc y WriteProcessMemory\nhttp://c2.lab.invalid/x\n"
_MU_ELF = b"\x7fELF" + b"\x00" * 16 + b"/bin/sh conecta a 10.0.0.5\n"
_MU_SCRIPT = b"#!/bin/sh\necho hola\n"


class TestAnalizarMuestra(BaseTest):
    def test_detecta_formato_pe(self):
        self.assertIn("PE", analizar_muestra(_MU_PE, "m.bin")["formato"])

    def test_detecta_formato_elf(self):
        self.assertIn("ELF", analizar_muestra(_MU_ELF)["formato"])

    def test_hashes_estables(self):
        a = analizar_muestra(_MU_PE)
        b = analizar_muestra(_MU_PE)
        self.assertEqual(a["sha256"], b["sha256"])
        self.assertEqual(len(a["sha256"]), 64)
        self.assertNotEqual(a["sha256"], analizar_muestra(_MU_ELF)["sha256"])

    def test_extrae_url_y_api(self):
        info = analizar_muestra(_MU_PE)
        self.assertTrue(any("c2.lab.invalid" in u for u in info["urls"]))
        self.assertIn("VirtualAlloc", info["apis_sospechosas"])
        self.assertTrue(any(h.estado == "STATIC_FINDING" for h in info["hallazgos"]))

    def test_extrae_ip(self):
        self.assertIn("10.0.0.5", analizar_muestra(_MU_ELF)["ips"])

    def test_entropia_alta_en_datos_aleatorios(self):
        import os as _os
        aleatorio = _os.urandom(4096)
        self.assertGreaterEqual(analizar_muestra(aleatorio)["entropia"], 7.0)

    def test_entropia_baja_en_texto(self):
        self.assertLess(analizar_muestra(b"aaaaaaaaaaaaaaaaaaaaaaaa")["entropia"], 2.0)

    def test_muestra_vacia_no_rompe(self):
        info = analizar_muestra(b"")
        self.assertEqual(info["tamano"], 0)
        self.assertEqual(info["formato"], "desconocido")


class TestReglaYara(BaseTest):
    def test_genera_regla(self):
        regla = generar_regla_yara("familia-demo", ["VirtualAlloc", "c2.lab.invalid"], "demo")
        self.assertIn("rule familia_demo", regla)
        self.assertIn("$s0", regla)
        self.assertIn("condition", regla)

    def test_escapa_comillas(self):
        regla = generar_regla_yara("x", ['dice "hola"'])
        self.assertNotIn('"dice "hola""', regla)       # las comillas internas quedan escapadas


class TestMuestraCLI(BaseTest):
    def test_comando_muestra(self):
        ws = self.proyecto()
        (ws.raiz / "sample.bin").write_bytes(_MU_PE)
        app = App(self.ajustes(forense=False, escalar=False), MockLLM([]), self.ui(), ws, persistir=False)
        app.comando("/muestra sample.bin")
        texto = app.ui.texto_registrado()
        self.assertIn("PE", texto)
        self.assertIn("NO fue ejecutada", texto)
