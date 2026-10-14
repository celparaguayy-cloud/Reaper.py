"""
Autotests de errores que SOLO aparecen en el navegador (node --test pasa igual), típicos de los modelos gratis al
construir un juego o una web: el build salía VERIFICADO y la página no hacía nada.

- <script src="juego.js"> sin type="module" con juego.js lleno de `export` → SyntaxError en el navegador.
- onclick="reiniciar()" con reiniciar definida dentro de un módulo → ReferenceError (lo de un módulo no es global).
"""


class TestNavegadorScripts(BaseTest):
    def _errores(self, archivos):
        ws = self.proyecto(archivos)
        return [r for r in validar_archivo(ws, "index.html") if not r.ok]

    def test_script_clasico_que_es_modulo_es_error(self):
        errores = self._errores({"index.html": '<body>\n<script src="juego.js"></script>\n</body>\n',
                                 "juego.js": "export function mover(s) { return s; }\n"})
        self.assertEqual(len(errores), 1)
        self.assertIn('type="module"', errores[0].stderr)
        self.assertIn("línea 2", errores[0].stderr)

    def test_onclick_a_funcion_de_modulo_es_error(self):
        errores = self._errores({"index.html": '<button onclick="reiniciar()">Otra</button>\n'
                                               '<script type="module" src="main.js"></script>\n',
                                 "main.js": 'import { mover } from "./juego.js";\nfunction reiniciar() { mover(1); }\n',
                                 "juego.js": "export function mover(s) { return s; }\n"})
        self.assertEqual(len(errores), 1)
        self.assertIn("ReferenceError: reiniciar is not defined", errores[0].stderr)

    def test_lo_correcto_no_se_marca(self):
        casos = [
            # módulo bien cargado y handler con addEventListener
            {"index.html": '<button id="b">Otra</button>\n<script type="module" src="main.js"></script>\n',
             "main.js": 'import { mover } from "./juego.js";\ndocument.getElementById("b").addEventListener("click", '
                        '() => mover(1));\n', "juego.js": "export function mover(s) { return s; }\n"},
            # handler inline con la función expuesta en window
            {"index.html": '<button onclick="reiniciar()">Otra</button>\n<script type="module" src="m.js"></script>\n',
             "m.js": "function reiniciar() {}\nwindow.reiniciar = reiniciar;\n"},
            # script clásico con onclick a una función global, import() dinámico y un comentario con "export"
            {"index.html": '<button onclick="reiniciar()">Otra</button>\n<script src="app.js"></script>\n',
             "app.js": "// export no es un problema en un comentario\nfunction reiniciar() { import('./x.js'); }\n"},
            # CDN externo: no se revisa
            {"index.html": '<script src="https://cdn.example.com/lib.js"></script>\n'},
        ]
        for archivos in casos:
            with self.subTest(html=archivos["index.html"][:40]):
                self.assertEqual([r.stderr for r in self._errores(archivos)], [])

    def test_plantillas_web_de_reaper_no_se_marcan(self):
        # Las plantillas propias son la referencia: si la regla las marcara, sería la regla la que está mal.
        for nombre, plantilla in PLANTILLAS.items():
            archivos = {rel: contenido for rel, contenido in plantilla.archivos.items() if isinstance(contenido, str)}
            htmls = [rel for rel in archivos if rel.endswith((".html", ".htm"))]
            if not htmls:
                continue
            ws = self.proyecto(archivos, nombre=f"p_{nombre}")
            for rel in htmls:
                with self.subTest(plantilla=nombre, html=rel):
                    self.assertEqual(scripts_html_incoherentes(ws, ws.raiz / rel, ws.leer(rel)), [])


class TestBundleSinNombresPisados(BaseTest):
    # Todas las partes se empaquetan en UN archivo: dos `_X = ...` globales con el mismo nombre en partes distintas
    # no dan error, la segunda pisa a la primera y la parte de arriba usa en silencio datos ajenos. Pasó con
    # _RE_NEGACION (afirma_verificacion dejó de ver "no verifiqué"), _IO_REAL (Test Intelligence usaba la lista
    # del examen de realidad) y _LOCK_PROCESOS (dos locks distintos eran el mismo).
    EXTENSIONES_A_PROPOSITO = {"_PARSERS"}                                 # _PARSERS = _PARSERS + (...): se extiende

    def test_ningun_global_definido_dos_veces(self):
        fuente = Path(__file__).read_text(encoding="utf-8")
        contador = collections.Counter()
        for nodo in ast.parse(fuente).body:
            if isinstance(nodo, (ast.Assign, ast.AnnAssign)):
                objetivos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
                for t in objetivos:
                    contador.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))   # también `_A, _B = …`
            elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                contador[nodo.name] += 1
        repetidos = sorted(n for n, k in contador.items() if k > 1 and n not in self.EXTENSIONES_A_PROPOSITO)
        self.assertEqual(repetidos, [])
