"""
Proyectos GRANDES por etapas (/grande).

Un /construir mete todo el pedido en UN plan de hasta max_tareas tareas y un plazo de pared: alcanza para un proyecto
chico o mediano, pero uno grande (una app con backend, base de datos, frontend, autenticación, panel…) terminaba con
las tareas sobrantes amontonadas en la última o cortado por el plazo. Acá:

1. Un PLAN MAESTRO divide el pedido en etapas. Cada etapa es una porción que se puede construir y probar sola, con
   los archivos que toca, la INTERFAZ que deja para las siguientes y sus criterios.
2. Cada etapa es un /construir completo, con TODAS sus guardas (tests primero, juez, preservación de lo anterior,
   examen de realidad, arranque). Los tests de las etapas anteriores quedan protegidos: una etapa nueva no puede
   debilitarlos para pasar.
3. Si una etapa no queda verificada, NO se construye nada encima (se reintenta una vez retomando su build y, si
   sigue mal, se frena y se informa). /grande continuar retoma donde quedó, aunque se haya cortado a mitad.
4. Al final, una verificación de INTEGRACIÓN sobre todo el proyecto y el juez contra el PEDIDO ORIGINAL (no contra
   lo que escribió el modelo). Si falta algo, una build de integración acotada lo completa.

Lo que el modelo escribe en el plan maestro NUNCA autoriza nada: reescribir archivos previos o aceptar "datos de
ejemplo" se decide con el pedido del usuario (Orquestador.pedido_usuario).
"""

_RE_ETAPA = re.compile(r"<etapa\b([^>]*)>(.*?)</etapa\s*>", re.S | re.I)
_RE_ATTR_ETAPA = re.compile(r"""(\w+)\s*=\s*["']([^"']*)["']""")
# Intentos TOTALES por etapa (entre todas las invocaciones) antes de pedir intervención: no quemar tokens en bucle.
MAX_INTENTOS_ETAPA = 4
ESTADOS_OK_ETAPA = ("verificada", "validada")

MISION_MAESTRO = """Sos el ARQUITECTO DE UN PROYECTO GRANDE. No escribís código: dividís el pedido en ETAPAS que otro
equipo va a construir UNA POR VEZ, cada una con su propio plan, sus tests y su verificación.

Reglas:
- Cada etapa entrega código REAL, completo y que se puede probar SOLO (con tests automáticos), sobre lo que dejaron
  las anteriores. Nada de esqueletos, stubs, placeholders, TODO, `pass`, NotImplementedError ni "datos de ejemplo
  para completar después": lo que una etapa crea, lo termina.
- Orden por dependencias: primero la base (modelo de datos, núcleo, configuración), después lo que la usa. Preferí
  porciones verticales que funcionen de punta a punta antes que capas sueltas.
- Cada etapa entra en un plan de ~4 a 10 tareas: si es más grande, partila.
- Definí la ARQUITECTURA una sola vez (stack, carpetas, cómo se corren los tests y la app, convenciones) y que
  todas las etapas la respeten.
- La INTERFAZ de cada etapa (archivos, funciones/clases/endpoints con firmas exactas) es un contrato: las etapas
  siguientes la usan tal cual y no la rompen.
- NO agregues etapas de solo "ejecutar/verificar pruebas" ni de "documentación" suelta: REAPER verifica todo.
- Usá solo lo que el entorno tiene (Termux/Linux: Python y su librería estándar, Node si hace falta). No inventes
  servicios, claves ni datos: si algo viene de afuera, la etapa lo obtiene de verdad.

Respondé EXACTAMENTE con este formato (nada antes ni después):
<maestro>
<vision>qué es el producto terminado, en 2-4 frases</vision>
<arquitectura>
stack, estructura de carpetas, comando de tests, cómo se arranca, convenciones
</arquitectura>
<etapa id="1" titulo="nombre corto" deps="">
<objetivo>qué queda funcionando al terminar esta etapa</objetivo>
<archivos>ruta/a.py, ruta/b.py, tests/test_a.py</archivos>
<interfaz>
- ruta/a.py: def funcion(param: tipo) -> tipo — qué devuelve
</interfaz>
<criterios>
- criterio comprobable con un test (entrada → salida esperada)
</criterios>
</etapa>
<etapa id="2" titulo="..." deps="1">
...
</etapa>
</maestro>"""


@dataclass
class Etapa:
    id: str
    titulo: str
    objetivo: str
    archivos: list = field(default_factory=list)
    interfaz: str = ""
    criterios: list = field(default_factory=list)
    deps: list = field(default_factory=list)
    estado: str = "pendiente"           # pendiente | en_curso | verificada | validada | parcial | fallida | cancelada
    intentos: int = 0
    informe: str = ""                   # ruta del informe de la última build de la etapa
    motivo: str = ""                    # por qué no quedó verificada (el error REAL, recortado)
    segundos: float = 0.0
    consumo: int = 0                    # tokens (entrada + salida) de sus builds

    @property
    def ok(self) -> bool:
        return self.estado in ESTADOS_OK_ETAPA


@dataclass
class PlanMaestro:
    vision: str
    arquitectura: str
    etapas: list
    texto: str = ""

    def por_id(self, eid: str) -> Optional[Etapa]:
        return next((e for e in self.etapas if e.id == eid), None)

    def como_texto(self) -> str:
        lineas = [f"Visión: {self.vision}"]
        if self.arquitectura:
            lineas.append("Arquitectura:")
            lineas.extend(f"  {l.strip()}" for l in self.arquitectura.strip().splitlines() if l.strip())
        for e in self.etapas:
            deps = f" (después de {', '.join(e.deps)})" if e.deps else ""
            lineas.append(f"[{e.estado}] Etapa {e.id} · {e.titulo}{deps}: {recortar(e.objetivo, 300)}")
        return "\n".join(lineas)


def _tag(cuerpo: str, nombre: str) -> str:
    m = re.search(rf"<{nombre}>(.*?)</{nombre}\s*>", cuerpo or "", re.S | re.I)
    return m.group(1).strip() if m else ""


def _lista_criterios(texto: str) -> list:
    salida = []
    for linea in (texto or "").splitlines():
        linea = re.sub(r"^\s*([-*•]|\d+[.)])\s*", "", linea).strip()
        if linea:
            salida.append(linea)
    return salida


def _rutas_etapa(texto: str) -> list:
    """Rutas relativas sanas: sin absolutas, sin '..', sin basura de markdown."""
    salida = []
    for parte in re.split(r"[,;\n]+", texto or ""):
        rel = parte.strip().strip("`'\"*-• ").strip()
        if not rel or " " in rel or rel.startswith(("/", "~")) or ".." in Path(rel).parts:
            continue
        if rel not in salida:
            salida.append(rel)
    return salida


def parsear_maestro(texto: str) -> PlanMaestro:
    """Plan maestro desde la respuesta del modelo. Tolerante con el formato; no inventa etapas que no vinieron."""
    texto = texto or ""
    etapas = []
    for m in _RE_ETAPA.finditer(texto):
        attrs = {k.lower(): v for k, v in _RE_ATTR_ETAPA.findall(m.group(1))}
        cuerpo = m.group(2)
        objetivo = _tag(cuerpo, "objetivo") or re.sub(r"<[^>]+>", " ", cuerpo).strip()[:400]
        if not objetivo:
            continue
        eid = (attrs.get("id") or str(len(etapas) + 1)).strip()
        deps = [d.strip() for d in re.split(r"[,;\s]+", attrs.get("deps", "")) if d.strip()]
        etapas.append(Etapa(eid, (attrs.get("titulo") or attrs.get("title") or f"Etapa {eid}").strip()[:80],
                            objetivo, _rutas_etapa(_tag(cuerpo, "archivos")), _tag(cuerpo, "interfaz"),
                            _lista_criterios(_tag(cuerpo, "criterios"))[:10], deps))
    return PlanMaestro(_tag(texto, "vision"), _tag(texto, "arquitectura"), etapas, texto)


def problemas_maestro(maestro: PlanMaestro, max_etapas: int, pedido: str = "") -> list:
    """Determinista (0 tokens): lo que hace que un plan maestro no sirva. → razones para replanificar."""
    salida = []
    if not maestro.etapas:
        return ["no vino ninguna <etapa> con el formato pedido"]
    if len(maestro.etapas) > max_etapas:
        salida.append(f"trae {len(maestro.etapas)} etapas y el tope es {max_etapas}: agrupá etapas chicas "
                      "(cada etapa puede tener hasta ~10 tareas)")
    ids = [e.id for e in maestro.etapas]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        salida.append(f"ids de etapa repetidos: {', '.join(repetidos)}")
    for e in maestro.etapas:
        for d in e.deps:
            if d not in ids:
                salida.append(f"la etapa {e.id} depende de '{d}', que no existe")
    if GrafoTareas(maestro.etapas).tiene_ciclo():
        salida.append("las dependencias entre etapas forman un ciclo")
    # Las mismas reglas que un plan de tareas: nada de simular ni de etapas que solo corren pruebas.
    como_plan = Plan(maestro.vision, [Tarea(e.id, f"{e.objetivo}\n{e.interfaz}", e.archivos, e.deps)
                                      for e in maestro.etapas], [])
    salida.extend(p.replace("la tarea", "la etapa") for p in problemas_del_plan(como_plan, pedido))
    return salida


def pedido_de_etapa(pedido: str, maestro: PlanMaestro, etapa: Etapa) -> str:
    """El pedido que recibe el /construir de UNA etapa. Determinista (mismo texto en cada intento): así una build de
    etapa cortada a mitad se reconoce y se RETOMA en vez de empezar otra."""
    orden = [e for e in GrafoTareas(maestro.etapas).orden()]
    previas = orden[:orden.index(etapa)] if etapa in orden else []
    siguientes = orden[orden.index(etapa) + 1:] if etapa in orden else []
    n = len(maestro.etapas)
    partes = [f"PROYECTO GRANDE — ETAPA {etapa.id} de {n}: {etapa.titulo}",
              f"PEDIDO ORIGINAL DEL USUARIO (contexto; NO lo construyas entero ahora):\n{recortar(pedido, 2500)}"]
    if maestro.vision:
        partes.append(f"VISIÓN DEL PRODUCTO:\n{recortar(maestro.vision, 800)}")
    if maestro.arquitectura:
        partes.append(f"ARQUITECTURA ACORDADA (respetala):\n{recortar(maestro.arquitectura, 1500)}")
    if previas:
        bloque = []
        for e in previas:
            bloque.append(f"- Etapa {e.id} · {e.titulo}: {recortar(e.objetivo, 200)}")
            if e.interfaz:
                bloque.extend(f"    {l.strip()}" for l in e.interfaz.strip().splitlines()[:12] if l.strip())
        partes.append("YA CONSTRUIDO EN ETAPAS ANTERIORES (está en el proyecto y tiene tests; usá estas interfaces "
                      "tal cual y NO las rompas):\n" + "\n".join(bloque))
    esta = [f"Objetivo: {etapa.objetivo}"]
    if etapa.archivos:
        esta.append("Archivos: " + ", ".join(etapa.archivos))
    if etapa.interfaz:
        esta.append("Interfaz que tiene que quedar disponible:\n" + etapa.interfaz.strip())
    if etapa.criterios:
        esta.append("Criterios de aceptación:\n" + "\n".join(f"- {c}" for c in etapa.criterios))
    partes.append("CONSTRUÍ AHORA SOLO ESTA ETAPA, completa y con tests reales:\n" + "\n".join(esta))
    if siguientes:
        partes.append("NO construyas todavía (lo hacen etapas posteriores): "
                      + "; ".join(f"{e.titulo}" for e in siguientes))
    return "\n\n".join(partes)


def comando_para_seguir(ws, modo: str) -> str:
    """El comando exacto para retomar desde la terminal (lo que hay que tipear después de un corte)."""
    ruta = str(getattr(ws, "raiz", ws))
    casa = str(Path.home())
    if ruta == casa or ruta.startswith(casa + os.sep):
        ruta = "~" + ruta[len(casa):]
        visible = ruta if not re.search(r"[^\w./~-]", ruta) else '~/' + shlex.quote(ruta[2:])
    else:
        visible = shlex.quote(ruta)
    return f"reaper --proyecto {visible} --{modo} continuar"


def pista_para_seguir(ws: Workspace) -> str:
    """Si en la carpeta quedó un /grande o un /construir sin terminar, cómo seguirlo ('' si no hay nada)."""
    try:
        grande = ConstructorGrande(None, ws, Settings(), None).leer()
        if grande and grande.get("estado") != "terminado":
            return f"El proyecto grande quedó guardado. Para seguir: {comando_para_seguir(ws, 'grande')}"
        build = RegistroBuild(ws).leer()
        if build and build.get("estado") not in ESTADOS_OK_ETAPA:
            return f"La build quedó guardada. Para seguir: {comando_para_seguir(ws, 'construir')}"
    except (ValueError, OSError, KeyError, TypeError):
        return ""
    return ""


def _redactar_textos(valor):
    """Copia con redactar_secretos aplicado a cada string (las claves y los números quedan como están)."""
    if isinstance(valor, str):
        return redactar_secretos(valor)
    if isinstance(valor, dict):
        return {k: _redactar_textos(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_redactar_textos(v) for v in valor]
    return valor


class ConstructorGrande:
    """Orquesta un proyecto por etapas. `construir_build(pedido_etapa, reanudar, pedido_usuario)` corre UN
    /construir y devuelve su InformeBuild (en la App suma estadísticas y hooks; en los tests, un Orquestador)."""

    ESQUEMA = 1

    def __init__(self, llm, ws: Workspace, settings: Settings, ui: UI,
                 construir_build: Optional[Callable[..., "InformeBuild"]] = None):
        self.llm, self.ws, self.settings, self.ui = llm, ws, settings, ui
        self.ruta = ws.carpeta_reaper() / "proyecto_grande.json"
        self._construir_build = construir_build or self._build_directo

    # ------------------------------------------------------------ estado en disco
    def leer(self) -> Optional[dict]:
        if not self.ruta.is_file():
            return None
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ValueError(f"Estado de /grande ilegible ({self.ruta.name}): {e}")
        if not isinstance(datos, dict) or datos.get("esquema") != self.ESQUEMA or "maestro" not in datos:
            raise ValueError(f"Estado de /grande con formato desconocido ({self.ruta.name})")
        return datos

    def guardar(self, estado: dict, maestro: PlanMaestro) -> None:
        estado["maestro"] = asdict(maestro)
        estado["actualizado"] = datetime.now().isoformat(timespec="seconds")
        # Se redactan los TEXTOS, no el JSON serializado: redactar_secretos tomaba `"tokens": 1234` por una
        # credencial, lo cambiaba por [REDACTADO] y el estado quedaba ilegible (lo atrapó el autotest de /grande).
        escritura_atomica(self.ruta, json.dumps(_redactar_textos(estado), ensure_ascii=False, indent=2))

    def borrar(self) -> None:
        if self.ruta.is_file():
            self.ruta.unlink()

    @staticmethod
    def maestro_de(estado: dict) -> PlanMaestro:
        datos = estado["maestro"]
        campos = {f.name for f in fields(Etapa)}
        etapas = [Etapa(**{k: v for k, v in e.items() if k in campos}) for e in datos.get("etapas", [])]
        return PlanMaestro(datos.get("vision", ""), datos.get("arquitectura", ""), etapas, datos.get("texto", ""))

    # ------------------------------------------------------------ plan maestro
    def _pedir_maestro(self, pedido: str, feedback: str = "", anterior: Optional[PlanMaestro] = None) -> PlanMaestro:
        existentes = self.ws.archivos_codigo(limite=150)
        prompt = (f"PEDIDO DEL USUARIO:\n{pedido}\n\n"
                  f"ARCHIVOS QUE YA EXISTEN EN EL PROYECTO ({len(existentes)}):\n"
                  + ("\n".join(f"- {a}" for a in existentes[:150]) or "(ninguno: proyecto nuevo)")
                  + f"\n\nTope: {self.settings.max_etapas} etapas, cada una de hasta {self.settings.max_tareas} tareas.")
        if anterior is not None and feedback:
            prompt += (f"\n\nTU PLAN MAESTRO ANTERIOR:\n{anterior.como_texto()}\n\n"
                       f"CORREGÍ ESTO:\n{feedback}")
        modelo = self.settings.modelo_para("arquitecto")
        resp = self.llm.chat([{"role": "system", "content": "# TU ROL: MAESTRO\n" + MISION_MAESTRO}, {"role": "user", "content": prompt}],
                             modelo=modelo, temperatura=0.3, max_tokens=max(3000, self.settings.max_tokens // 2),
                             rol="arquitecto")
        return parsear_maestro(str(getattr(resp, "texto", "") or ""))

    def planificar(self, pedido: str, confirmar: bool) -> Optional[PlanMaestro]:
        self.ui.fase("G", "Plan maestro (proyecto grande por etapas)")
        maestro = self._pedir_maestro(pedido)
        problemas = problemas_maestro(maestro, self.settings.max_etapas, pedido)
        if problemas:
            # Juez (0 tokens): una sola replanificación con las razones; si sigue mal, no se arranca a ciegas.
            self.ui.aviso("  Juez · el plan maestro tiene problemas: lo hago rehacer una vez.")
            for p in problemas[:5]:
                self.ui.tenue(f"    • {p}")
            maestro = self._pedir_maestro(pedido, "\n".join(f"- {p}" for p in problemas), maestro)
            problemas = problemas_maestro(maestro, self.settings.max_etapas, pedido)
            if problemas:
                self.ui.error("El plan maestro sigue sin servir: " + "; ".join(problemas[:4]))
                if any("tope es" in p for p in problemas):
                    self.ui.tenue(f"  Si de verdad necesita más etapas: /config max_etapas "
                                  f"{min(30, len(maestro.etapas))}")
                return None
        maestro.etapas = GrafoTareas(maestro.etapas).orden()
        for _ in range(3):
            self._mostrar_maestro(maestro)
            if not confirmar:
                return maestro
            if self.ui.confirmar("¿Aprobás el plan maestro y arrancamos por la etapa 1?", defecto=True):
                return maestro
            feedback = self.ui.preguntar("¿Qué cambiarías del plan maestro? (Enter vacío = cancelar)")
            if not feedback:
                return None
            nuevo = self._pedir_maestro(pedido, feedback, maestro)
            if problemas_maestro(nuevo, self.settings.max_etapas, pedido):
                self.ui.aviso("  El plan corregido no cumple las reglas; te muestro el anterior.")
            else:
                maestro = nuevo
                maestro.etapas = GrafoTareas(maestro.etapas).orden()
        return None

    def _mostrar_maestro(self, maestro: PlanMaestro) -> None:
        self.ui.linea("")
        if maestro.vision:
            self.ui.info("  " + recortar(maestro.vision, 400))
        if maestro.arquitectura:
            for l in maestro.arquitectura.strip().splitlines()[:10]:
                self.ui.tenue("    " + recortar(l.strip(), 140))
        for e in maestro.etapas:
            marca = "✓" if e.ok else ("✗" if e.estado in ("parcial", "fallida") else "○")
            deps = f"  (tras {', '.join(e.deps)})" if e.deps else ""
            self.ui.linea(f"  {marca} Etapa {e.id} · {e.titulo}{deps}")
            self.ui.tenue(f"      {recortar(e.objetivo, 160)}")
            if e.archivos:
                self.ui.tenue("      archivos: " + recortar(", ".join(e.archivos), 150))

    # ------------------------------------------------------------ ejecución
    def iniciar(self, pedido: str, confirmar: bool = True) -> bool:
        try:
            previo = self.leer()
        except ValueError as e:
            self.ui.error(str(e))
            return False
        if previo and previo.get("estado") != "terminado":
            if " ".join(str(previo.get("pedido", "")).split()) == " ".join(pedido.split()):
                # Repetir el MISMO comando después de un corte (Termux cerrado, teléfono bloqueado, límite del
                # modelo) es la forma natural de "seguir": antes daba error y había que saber /grande continuar.
                self.ui.info("Este mismo proyecto grande había quedado a medias: lo retomo donde quedó.")
                return self.continuar()
            self.ui.error("Ya hay OTRO proyecto grande sin terminar en esta carpeta. Seguilo con "
                          f"`{comando_para_seguir(self.ws, 'grande')}`, miralo con /grande estado o descartalo con "
                          "/grande descartar (no borra archivos). Para uno nuevo usá otra carpeta (--proyecto).")
            return False
        try:
            pendiente = RegistroBuild(self.ws).leer()
        except ValueError as e:
            self.ui.error(str(e))
            return False
        if pendiente and pendiente.get("estado") not in ESTADOS_OK_ETAPA:
            self.ui.error("Hay un /construir sin terminar en esta carpeta: terminalo (/construir continuar) o "
                          "descartalo (/construir descartar) antes de empezar un proyecto grande.")
            return False
        try:
            maestro = self.planificar(pedido, confirmar)
        except LLMError as e:
            self.ui.error(f"El arquitecto no respondió el plan maestro: {recortar(str(e), 200)}")
            return False
        if maestro is None:
            self.ui.tenue("Proyecto grande cancelado; no se tocó ningún archivo.")
            return False
        estado = {"esquema": self.ESQUEMA, "pedido": pedido, "estado": "en_curso",
                  "creado": datetime.now().isoformat(timespec="seconds"),
                  # Todo lo que se escriba desde acá queda en checkpoints >= cid_inicio: así la integración final
                  # revisa el proyecto ENTERO (validación, examen de realidad, diff para el juez).
                  "cid_inicio": self.ws.checkpoints.iniciar(f"proyecto grande: {pedido[:80]}"),
                  "integracion": {}}
        self.guardar(estado, maestro)
        return self._ejecutar(estado, maestro)

    def continuar(self) -> bool:
        try:
            estado = self.leer()
        except ValueError as e:
            self.ui.error(str(e))
            return False
        if not estado:
            self.ui.aviso("No hay ningún proyecto grande en esta carpeta. Empezá uno con /grande <pedido>.")
            return False
        if estado.get("estado") == "terminado":
            self.ui.ok("El proyecto grande ya está terminado y verificado.")
            return True
        maestro = self.maestro_de(estado)
        self.ui.info("Retomo el proyecto grande: " + recortar(redactar_secretos(estado["pedido"]), 140))
        return self._ejecutar(estado, maestro)

    def _ejecutar(self, estado: dict, maestro: PlanMaestro) -> bool:
        inicio = time.monotonic()
        grafo = GrafoTareas(maestro.etapas)
        for n, etapa in enumerate(grafo.orden(), start=1):
            if etapa.ok:
                continue
            rotas = [d for d in grafo.dependencias(etapa.id) if not maestro.por_id(d).ok]
            if rotas:
                # Mismo principio que BUG-012 entre tareas: nunca construir sobre una base que no está verificada.
                return self._detener(estado, maestro, f"la etapa {etapa.id} depende de {', '.join(rotas)}, que no "
                                                      "quedó verificada")
            if etapa.intentos >= MAX_INTENTOS_ETAPA:
                return self._detener(estado, maestro, f"la etapa {etapa.id} ya se intentó {etapa.intentos} veces sin "
                                                      "quedar verificada: revisá su informe y partila o corregila a mano")
            self.ui.linea("")
            self.ui.titulo(f"Etapa {etapa.id} ({n}/{len(maestro.etapas)}) · {etapa.titulo}")
            for intento in range(2):                     # el intento original + UNA reanudación de su misma build
                try:
                    informe = self._correr_etapa(estado, maestro, etapa)
                except LLMError as e:
                    etapa.estado, etapa.motivo = "pendiente", recortar(str(e), 400)
                    return self._detener(estado, maestro, f"el modelo no responde ({recortar(str(e), 160)})")
                if etapa.ok or informe.estado == "cancelada" or intento == 1:
                    break
                if etapa.intentos >= MAX_INTENTOS_ETAPA:
                    break
                self.ui.aviso(f"  La etapa {etapa.id} quedó {etapa.estado.upper()}: la retomo una vez (sin replanificar) "
                              "para que el reparador termine lo que falta.")
            if not etapa.ok:
                return self._detener(estado, maestro, f"la etapa {etapa.id} quedó {etapa.estado.upper()}"
                                     + (f": {_primera_linea_util(etapa.motivo)}" if etapa.motivo else ""))
        ok = self._integrar(estado, maestro)
        self._cierre(estado, maestro, time.monotonic() - inicio)
        return ok

    def _correr_etapa(self, estado: dict, maestro: PlanMaestro, etapa: Etapa) -> "InformeBuild":
        pedido_etapa = pedido_de_etapa(estado["pedido"], maestro, etapa)
        try:
            pendiente = RegistroBuild(self.ws).leer()
        except ValueError as e:
            raise LLMError(f"diario de build ilegible: {e}", probar_otro_modelo=False)
        reanudar = bool(pendiente and pendiente.get("estado") not in ESTADOS_OK_ETAPA)
        if reanudar and pendiente.get("pedido") != pedido_etapa:
            etapa.estado, etapa.motivo = "pendiente", "hay otro /construir sin terminar en la carpeta"
            self.guardar(estado, maestro)
            self.ui.error("Hay un /construir sin terminar que no es de esta etapa: terminalo o descartalo "
                          "(/construir estado) y después /grande continuar.")
            return InformeBuild("cancelada")
        etapa.estado = "en_curso"
        etapa.intentos += 1
        self.guardar(estado, maestro)
        if reanudar:
            self.ui.tenue("  Hay una build de esta etapa a medio terminar: la retomo sin replanificar.")
        informe = self._construir_build(pedido_etapa, reanudar, estado["pedido"])
        etapa.estado = informe.estado if informe.estado != "cancelada" else "pendiente"
        etapa.segundos += float(getattr(informe, "segundos", 0.0) or 0.0)
        etapa.consumo += int(getattr(informe, "tokens_build", 0) or 0)
        etapa.informe = str(informe.ruta_informe or "")
        etapa.motivo = "" if etapa.ok else recortar(
            informe.diagnostico or "; ".join(f"{t}: {m}" for t, m in informe.motivos_fallo.items())
            or "; ".join(informe.notas[-3:]), 1500)
        self.guardar(estado, maestro)
        return informe

    def _build_directo(self, pedido_etapa: str, reanudar: bool, pedido_usuario: str) -> "InformeBuild":
        orq = Orquestador(self.llm, self.ws, self.settings, self.ui)
        orq.pedido_usuario = pedido_usuario
        return orq.construir("" if reanudar else pedido_etapa, confirmar=False, reanudar=reanudar)

    def _detener(self, estado: dict, maestro: PlanMaestro, motivo: str) -> bool:
        estado["estado"] = "detenido"
        estado["motivo"] = motivo
        self.guardar(estado, maestro)
        hechas = sum(1 for e in maestro.etapas if e.ok)
        self.ui.linea("")
        self.ui.caja([f"Etapas verificadas: {hechas}/{len(maestro.etapas)}",
                      f"Me detengo: {recortar(motivo, 300)}",
                      "No construyo encima de algo que no está verificado.",
                      "Revisá el informe de la etapa y seguí con: /grande continuar"],
                     titulo="Proyecto grande · DETENIDO", color=Tema.aviso)
        # Fuera de la caja: adentro se recorta al ancho de la terminal y el comando no se podía copiar entero.
        self.ui.info(f"  Desde la terminal: {comando_para_seguir(self.ws, 'grande')}")
        return False

    # ------------------------------------------------------------ integración
    def _integrar(self, estado: dict, maestro: PlanMaestro) -> bool:
        """Todas las etapas verdes ≠ el pedido cumplido. Verificación real del proyecto ENTERO + juez contra el PEDIDO
        ORIGINAL. Si falta algo: UNA build de integración con lo que falta y se vuelve a juzgar."""
        self.ui.linea("")
        self.ui.fase("G", "Integración final (todo el proyecto contra tu pedido original)")
        pedido = estado["pedido"]
        resultado = self._verificar_integracion(estado, maestro)
        if not resultado["ok"] and not estado["integracion"].get("reparada"):
            faltas = resultado["faltantes"] or [_primera_linea_util(resultado["diagnostico"])]
            self.ui.aviso("  Falta para cumplir el pedido completo: " + "; ".join(recortar(f, 80) for f in faltas[:4]))
            estado["integracion"]["reparada"] = True
            self.guardar(estado, maestro)
            pedido_integracion = (
                "PROYECTO GRANDE — INTEGRACIÓN FINAL. Todas las etapas están construidas y verificadas; NO rehagas "
                "nada que funcione. Completá SOLO esto para que el proyecto cumpla el pedido original:\n"
                + "\n".join(f"- {f}" for f in faltas[:8])
                + (f"\n\nDiagnóstico real:\n{recortar(resultado['diagnostico'], 2500)}" if resultado["diagnostico"] else "")
                + f"\n\nPEDIDO ORIGINAL DEL USUARIO:\n{recortar(pedido, 2500)}")
            try:
                informe = self._construir_build(pedido_integracion, False, pedido)
            except LLMError as e:
                informe = InformeBuild("fallida", diagnostico=str(e))
            if informe.estado == "cancelada":
                self.ui.aviso("  La build de integración no arrancó (otro /construir pendiente o plan inválido).")
            resultado = self._verificar_integracion(estado, maestro)
        estado["integracion"].update({k: resultado[k] for k in ("ok", "estado", "faltantes", "juicio")})
        estado["estado"] = "terminado" if resultado["ok"] else "integracion_pendiente"
        if not resultado["ok"]:
            estado["motivo"] = "la integración final no quedó verificada: " + (
                "; ".join(resultado["faltantes"][:3]) or _primera_linea_util(resultado["diagnostico"]))
        self.guardar(estado, maestro)
        return resultado["ok"]

    def _verificar_integracion(self, estado: dict, maestro: PlanMaestro) -> dict:
        orq = Orquestador(self.llm, self.ws, self.settings, self.ui)
        orq.pedido_usuario = estado["pedido"]
        try:
            orq._huella_aceptacion = huella_aceptacion(self.ws)
        except (ValueError, OSError):
            orq._huella_aceptacion = None
        cid = int(estado.get("cid_inicio") or 1)
        verif = orq.verificar(cid)
        orq._mostrar_verificacion(verif)
        plan = Plan(maestro.vision or recortar(estado["pedido"], 200),
                    [Tarea(e.id, f"{e.titulo}: {e.objetivo}", e.archivos, e.deps) for e in maestro.etapas],
                    [c for e in maestro.etapas for c in e.criterios][:20],
                    interfaz="\n".join(e.interfaz for e in maestro.etapas if e.interfaz))
        informe = InformeBuild("fallida", plan=plan, cid=cid)
        informe.estado = estado_final_build(verif, informe)
        informe.criterios_entrega = orq._contrato_de_entrega(estado["pedido"])
        orq._juicio_de_entrega(estado["pedido"], plan, verif, informe)
        juicio = informe.juicio
        faltantes = list(juicio.faltantes) if juicio is not None and juicio.valido and not juicio.cumple else []
        return {"ok": informe.ok, "estado": informe.estado, "faltantes": faltantes,
                "diagnostico": verif.diagnostico if not verif.ok else "",
                "juicio": juicio.texto() if juicio is not None else "sin veredicto del juez"}

    # ------------------------------------------------------------ salida
    def _cierre(self, estado: dict, maestro: PlanMaestro, segundos: float) -> None:
        integ = estado.get("integracion", {})
        ok = estado.get("estado") == "terminado"
        lineas = [f"{'✓' if e.ok else '✗'} Etapa {e.id} · {recortar(e.titulo, 40)}: {e.estado}"
                  f" · {formatear_duracion(e.segundos)}" for e in maestro.etapas]
        lineas.append(f"Integración final: {integ.get('estado', '?')} · {recortar(str(integ.get('juicio', '')), 90)}")
        if not ok:
            lineas.append("Pendiente: " + recortar(str(estado.get("motivo", "")), 200))
            lineas.append("Seguí con: /grande continuar (el comando completo va debajo)")
        lineas.append(f"Tiempo de esta corrida: {formatear_duracion(segundos)}")
        self.ui.linea("")
        self.ui.caja(lineas, titulo="Proyecto grande · " + ("✓ TERMINADO Y VERIFICADO" if ok else "INCOMPLETO"),
                     color=Tema.ok if ok else Tema.aviso)
        if not ok:
            self.ui.info(f"  Desde la terminal: {comando_para_seguir(self.ws, 'grande')}")
        ruta = self._guardar_informe(estado, maestro)
        if ruta:
            self.ui.tenue(f"  Informe: {ruta}")

    def _guardar_informe(self, estado: dict, maestro: PlanMaestro) -> Optional[Path]:
        lineas = [f"# Proyecto grande REAPER — {estado.get('estado', '?')}", "",
                  f"Fecha: {datetime.now():%Y-%m-%d %H:%M}", "", "## Pedido", redactar_secretos(estado["pedido"]), "",
                  "## Plan maestro", "```", maestro.como_texto(), "```", "", "## Etapas"]
        for e in maestro.etapas:
            lineas.append(f"- Etapa {e.id} · {e.titulo}: **{e.estado}** · intentos {e.intentos} · "
                          f"{formatear_duracion(e.segundos)} · ~{e.consumo} tokens"
                          + (f" · informe: {e.informe}" if e.informe else ""))
            if e.motivo and not e.ok:
                lineas.append(f"  - motivo: {recortar(e.motivo, 400)}")
        integ = estado.get("integracion", {})
        lineas += ["", "## Integración final", f"- estado: {integ.get('estado', 'no corrió')}",
                   f"- juez: {integ.get('juicio', '—')}"]
        lineas += [f"- falta: {f}" for f in integ.get("faltantes", [])]
        try:
            carpeta = self.ws.carpeta_reaper() / "informes"
            ruta = carpeta / f"proyecto_grande_{datetime.now():%Y%m%d_%H%M%S}.md"
            escritura_atomica(ruta, "\n".join(lineas) + "\n")
            return ruta
        except OSError:
            return None

    def mostrar_estado(self) -> None:
        try:
            estado = self.leer()
        except ValueError as e:
            self.ui.error(str(e))
            return
        if not estado:
            self.ui.tenue("No hay ningún proyecto grande en esta carpeta. Empezá uno con /grande <pedido>.")
            return
        maestro = self.maestro_de(estado)
        hechas = sum(1 for e in maestro.etapas if e.ok)
        self.ui.info(f"Proyecto grande ({estado.get('estado')}): {hechas}/{len(maestro.etapas)} etapas verificadas")
        self.ui.tenue("  " + recortar(redactar_secretos(estado["pedido"]), 200))
        self._mostrar_maestro(maestro)
        if estado.get("motivo"):
            self.ui.aviso("  Último motivo de parada: " + recortar(str(estado["motivo"]), 300))


def _cmd_grande(self: "App", arg: str) -> None:
    """/grande <pedido> | estado | continuar | descartar — proyecto grande construido por etapas verificadas."""
    modo = arg.strip().lower()
    grande = ConstructorGrande(self.llm, self.ws, self.settings, self.ui, construir_build=self._build_de_etapa)
    if modo == "estado":
        grande.mostrar_estado()
        return
    if modo == "descartar":
        if self.ui.confirmar("¿Descartar el ESTADO del proyecto grande? Los archivos del proyecto no se borran."):
            grande.borrar()
            self.ui.ok("Estado del proyecto grande descartado; los archivos siguen intactos.")
        return
    if modo == "continuar":
        grande.continuar()
        return
    if not arg.strip():
        self.ui.tenue("Uso: /grande <pedido> | estado | continuar | descartar   "
                      f"(hasta {self.settings.max_etapas} etapas; cada una es un /construir verificado)")
        return
    grande.iniciar(arg.strip(), confirmar=self.ui.interactivo and self.settings.modo != "auto")


def _build_de_etapa(self: "App", pedido_etapa: str, reanudar: bool, pedido_usuario: str) -> "InformeBuild":
    """Un /construir de etapa con la misma contabilidad que /construir (historial, estadísticas, hooks)."""
    return self._construir_informe(pedido_etapa, confirmar=False, reanudar=reanudar, pedido_usuario=pedido_usuario)


App.cmd_grande = _cmd_grande
App._build_de_etapa = _build_de_etapa
