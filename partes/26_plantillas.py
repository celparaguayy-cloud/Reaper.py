"""
Plantillas de proyectos: arrancar desde una base que ya funciona y ya tiene tests.

Un modelo de 24B construye mucho mejor sobre un proyecto ordenado (lógica
separada de la interfaz, tests que pasan, comando de tests claro) que desde
una carpeta vacía. Cada plantilla de REAPER:
  - usa solo la librería estándar (anda en Termux sin pip) o node/go/rust/cc
  - trae tests que PASAN (REAPER lo verifica en --autotest)
  - trae un REAPER.md con cómo ejecutar y testear

Placeholders que se reemplazan al crear: __PROYECTO__ (nombre en snake_case),
__Proyecto__ (CamelCase), __TITULO__ (texto), __FECHA__, __ANIO__.

También se pueden agregar plantillas propias: ~/reaper/plantillas/<nombre>/
con los archivos tal cual (y opcionalmente plantilla.json con descripcion,
lenguaje, comando_tests y comando_ejecutar).
"""


@dataclass
class Plantilla:
    nombre: str
    descripcion: str
    lenguaje: str
    archivos: dict
    comando_tests: str = ""
    comando_ejecutar: str = ""
    etiquetas: tuple = ()
    requiere: tuple = ()

    def disponible(self) -> bool:
        return all(shutil.which(r) for r in self.requiere)


PLANTILLAS: dict[str, Plantilla] = {}


def registrar_plantilla(nombre: str, descripcion: str, lenguaje: str, archivos: dict, *,
                        comando_tests: str = "", comando_ejecutar: str = "", etiquetas: Sequence[str] = (),
                        requiere: Sequence[str] = ()) -> Plantilla:
    p = Plantilla(nombre, descripcion.strip(), lenguaje, {k: textwrap.dedent(v).lstrip("\n") if v.startswith("\n") else v
                                                         for k, v in archivos.items()},
                  comando_tests, comando_ejecutar, tuple(etiquetas), tuple(requiere))
    PLANTILLAS[nombre] = p
    return p


def nombre_proyecto(destino: Path) -> str:
    base = sin_tildes(destino.name).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "proyecto"
    if base[0].isdigit():
        base = "p_" + base
    if keyword.iskeyword(base):
        base += "_app"
    return base


def variables_para(destino: Path) -> dict[str, str]:
    slug = nombre_proyecto(destino)
    return {
        "__PROYECTO__": slug,
        "__Proyecto__": "".join(p.capitalize() for p in slug.split("_")),
        "__TITULO__": slug.replace("_", " ").title(),
        "__FECHA__": datetime.now().strftime("%Y-%m-%d"),
        "__ANIO__": datetime.now().strftime("%Y"),
    }


def renderizar_plantilla(texto: str, variables: dict[str, str]) -> str:
    for clave, valor in variables.items():
        texto = texto.replace(clave, valor)
    return texto


def _plantilla_usuario(nombre: str) -> Optional[Plantilla]:
    carpeta = PLANTILLAS_USUARIO_DIR / nombre
    if not carpeta.is_dir():
        return None
    meta: dict = {}
    if (carpeta / "plantilla.json").is_file():
        try:
            meta = json.loads((carpeta / "plantilla.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    archivos = {}
    for ruta in carpeta.rglob("*"):
        if ruta.is_file() and ruta.name != "plantilla.json" and "__pycache__" not in ruta.parts:
            try:
                archivos[ruta.relative_to(carpeta).as_posix()] = ruta.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    return Plantilla(nombre, meta.get("descripcion", "plantilla propia"), meta.get("lenguaje", "?"), archivos,
                     meta.get("comando_tests", ""), meta.get("comando_ejecutar", ""), ("propia",))


def obtener_plantilla(nombre: str) -> Optional[Plantilla]:
    return _plantilla_usuario(nombre) or PLANTILLAS.get(nombre)


def todas_las_plantillas() -> dict[str, Plantilla]:
    salida = dict(PLANTILLAS)
    if PLANTILLAS_USUARIO_DIR.is_dir():
        for carpeta in PLANTILLAS_USUARIO_DIR.iterdir():
            propia = _plantilla_usuario(carpeta.name) if carpeta.is_dir() else None
            if propia:
                salida[carpeta.name] = propia
    return salida


def _reaper_md(p: Plantilla, variables: dict[str, str]) -> str:
    return (
        f"# {variables['__TITULO__']}\n\n"
        f"## Descripción\n{p.descripcion}\n\n(Creado con la plantilla `{p.nombre}` de REAPER el {variables['__FECHA__']}.)\n\n"
        f"## Cómo ejecutar\n`{p.comando_ejecutar or '(ver archivos)'}`\n\n"
        f"## Cómo testear\n`{p.comando_tests or '(sin tests)'}`\n\n"
        "## Estructura\n" + "\n".join(f"- {rel}" for rel in sorted(p.archivos)) + "\n\n"
        "## Convenciones\n- Lógica pura separada de la entrada/salida para poder testearla.\n"
        "- Solo librería estándar salvo que se indique otra cosa.\n- Interfaz en español.\n"
    )


def crear_desde_plantilla(nombre: str, destino: Path, variables: Optional[dict] = None,
                          sobrescribir: bool = False) -> list[str]:
    p = obtener_plantilla(nombre)
    if p is None:
        raise KeyError(nombre)
    destino = Path(destino).expanduser()
    if destino.exists() and any(destino.iterdir()) and not sobrescribir:
        raise FileExistsError(f"{destino} ya existe y no está vacía.")
    variables = {**variables_para(destino), **(variables or {})}
    creados = []
    for rel, contenido in sorted(p.archivos.items()):
        rel_final = renderizar_plantilla(rel, variables)
        ruta = destino / rel_final
        texto = renderizar_plantilla(contenido, variables)
        escritura_atomica(ruta, texto)
        if rel_final.endswith(".sh") or texto.startswith("#!"):
            try:
                os.chmod(ruta, 0o755)
            except OSError:
                pass
        creados.append(rel_final)
    if "REAPER.md" not in creados:
        escritura_atomica(destino / "REAPER.md", _reaper_md(p, variables))
        creados.append("REAPER.md")
    if p.comando_tests and "comando_tests" not in p.archivos.get(".reaper/config.json", ""):
        config = destino / ".reaper" / "config.json"
        if not config.exists():
            escritura_atomica(config, json.dumps({"comando_tests": p.comando_tests}, indent=2) + "\n")
    return creados


def plantillas_sugeridas(pedido: str, k: int = 3) -> list[Plantilla]:
    tokens = set(tokens_pedido(pedido))
    puntuadas = []
    for p in PLANTILLAS.values():
        texto = f"{p.nombre} {p.descripcion} {' '.join(p.etiquetas)} {p.lenguaje}"
        propios = {_raiz(sin_tildes(t)) for t in re.findall(r"[a-záéíóúñ0-9]{3,}", texto.lower())}
        comunes = tokens & propios
        if comunes:
            puntuadas.append((len(comunes), p.nombre, p))
    puntuadas.sort(key=lambda t: (-t[0], t[1]))
    return [p for _, _, p in puntuadas[:k]]


def comando_portable(comando: str) -> str:
    """En autotest/CI se usa el Python actual en vez de 'python3' a secas."""
    return re.sub(r"(^|&&\s*|;\s*)python3?(?=\s)", lambda m: m.group(1) + shlex.quote(sys.executable), comando)
