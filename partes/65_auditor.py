"""
Auditores OFFLINE y adaptadores de importación (REAPER v11, §7 Research + §21 adaptadores, iteración A).

Todo acá es ESTÁTICO y sin red: analiza archivos que ya están en el workspace o importa resultados de
escaneos guardados por el operador. No ejecuta herramientas de red ni toca objetivos. Produce `Hallazgo`
con etiquetas honestas (STATIC_FINDING / VERSION_MATCH_ONLY): señala algo a revisar, no afirma compromiso.

  - auditar_config(texto): detecta configuraciones inseguras típicas (SAST-lite defensivo).
  - analizar_dependencias(texto): marca dependencias con versión potencialmente afectada como
    VERSION_MATCH_ONLY (nunca "confirmado"; no inventa CVE ni consulta la red).
  - importar_nmap_xml(texto): parsea un XML de nmap YA guardado y devuelve un inventario estructurado
    (sin ejecutar nmap ni resolver nada por red); rechaza XML corrupto.
"""

import xml.etree.ElementTree as _au_ET

# Reglas de configuración insegura: (regex, severidad, título, detalle/mitigación).
REGLAS_CONFIG = [
    (re.compile(r"\bDEBUG\s*=\s*True\b"), "alta", "DEBUG activado",
     "DEBUG=True expone trazas y datos internos; desactivalo en entornos no locales."),
    (re.compile(r"ALLOWED_HOSTS\s*=\s*\[\s*['\"]\*['\"]\s*\]"), "alta", "ALLOWED_HOSTS comodín",
     "ALLOWED_HOSTS=['*'] acepta cualquier Host header; restringí a dominios conocidos."),
    (re.compile(r"\b(?:verify|ssl_verify|verify_ssl|check_hostname)\s*=\s*False\b"), "alta",
     "Verificación TLS desactivada", "Desactivar la verificación de certificados permite MITM; dejala en True."),
    (re.compile(r"PermitRootLogin\s+yes", re.I), "alta", "Login root por SSH habilitado",
     "PermitRootLogin yes amplía la superficie de ataque; usá un usuario sin privilegios + sudo controlado."),
    (re.compile(r"\b(?:secure|httponly|http_only)\s*=\s*False\b", re.I), "media", "Cookie insegura",
     "Cookies sin Secure/HttpOnly quedan expuestas; activá ambos flags."),
    (re.compile(r"\b(?:password|passwd|secret|api_key|apikey|token)\s*=\s*['\"][^'\"]{6,}['\"]", re.I), "alta",
     "Secreto embebido", "Credencial en texto en el código/config; movela a variables de entorno o un gestor."),
    (re.compile(r"\bhashlib\.(?:md5|sha1)\b"), "media", "Hash débil",
     "MD5/SHA1 no sirven para contraseñas/integridad sensible; usá SHA-256+ o un KDF (bcrypt/scrypt/argon2)."),
    (re.compile(r"\byaml\.load\s*\((?![^)]*Loader)"), "alta", "yaml.load inseguro",
     "yaml.load sin Loader seguro permite ejecución; usá yaml.safe_load."),
    (re.compile(r"\bpickle\.loads?\s*\("), "media", "Deserialización con pickle",
     "pickle sobre datos no confiables ejecuta código; usá json o valida el origen."),
    (re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"), "media", "shell=True en subprocess",
     "shell=True con entrada variable habilita inyección de comandos; pasá argv como lista con shell=False."),
]

# Dependencias cuyo nombre sugiere revisar versión (ejemplo acotado; NO es una base CVE ni afirma vulnerabilidad).
# Formato: paquete -> (version_maxima_afectada, nota). Marca VERSION_MATCH_ONLY, nunca confirmado.
_AU_DEPS_REVISAR = {
    "pyyaml": ("5.3.1", "versiones viejas de PyYAML tuvieron problemas con load(); verificá la versión real"),
    "requests": ("2.19.1", "versiones muy viejas de requests arrastran dependencias con avisos; verificá"),
    "flask": ("0.12.2", "Flask muy antiguo; revisá avisos de seguridad de tu versión exacta"),
    "django": ("2.2.0", "Django por debajo de una LTS parcheada; confirmá la versión exacta y sus parches"),
    "jinja2": ("2.10.0", "Jinja2 antiguo tuvo avisos de sandbox; verificá la versión"),
}


def _au_lineno(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


def auditar_config(texto: str, nombre: str = "") -> list:
    """Hallazgos estáticos de configuración insegura. Cada uno es STATIC_FINDING (a revisar, no confirmado)."""
    hallazgos = []
    for i, (patron, severidad, titulo, detalle) in enumerate(REGLAS_CONFIG):
        for m in patron.finditer(texto or ""):
            linea = _au_lineno(texto, m.start())
            hallazgos.append(Hallazgo(
                id=f"cfg-{i}-{linea}", titulo=titulo, estado="STATIC_FINDING", severidad=severidad,
                detalle=(f"{nombre}:{linea}: " if nombre else f"línea {linea}: ") + detalle,
                limitaciones=["hallazgo estático; requiere comprobación contextual (no es un compromiso confirmado)"],
            ))
    return hallazgos


def _au_version_menor_o_igual(a: str, b: str) -> bool:
    def partes(v):
        return [int(x) for x in re.findall(r"\d+", v)] or [0]
    pa, pb = partes(a), partes(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa <= pb


def analizar_dependencias(texto: str, nombre: str = "requirements") -> list:
    """
    Lee un requirements.txt (paquete==version) y marca como VERSION_MATCH_ONLY lo que convenga revisar.
    NO consulta la red ni inventa CVE: solo señala 'esta versión podría estar afectada, verificá'.
    """
    hallazgos = []
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*==\s*([0-9][0-9A-Za-z.\-]*)", linea)
        if not m:
            continue
        paquete, version = m.group(1).lower(), m.group(2)
        regla = _AU_DEPS_REVISAR.get(paquete)
        if regla and _au_version_menor_o_igual(version, regla[0]):
            hallazgos.append(Hallazgo(
                id=f"dep-{paquete}", titulo=f"{paquete} {version}: revisar versión", estado="VERSION_MATCH_ONLY",
                severidad="media", detalle=f"{nombre}: {paquete}=={version}. {regla[1]}.",
                limitaciones=["coincidencia por versión; NO probado. No equivale a vulnerabilidad confirmada."],
            ))
    return hallazgos


def importar_nmap_xml(texto: str) -> dict:
    """
    Parsea un XML de nmap YA guardado (sin ejecutar nada ni tocar la red) a un inventario estructurado:
      {"hosts": [{"host": ip, "puertos": [{"puerto", "protocolo", "estado", "servicio"}]}]}
    Lanza ValueError si el XML es inválido. Determinista: el mismo XML da el mismo resultado.
    """
    try:
        raiz = _au_ET.fromstring(texto or "")
    except _au_ET.ParseError as e:
        raise ValueError(f"XML de nmap inválido: {e}") from e
    if raiz.tag != "nmaprun":
        raise ValueError("no parece un XML de nmap (falta <nmaprun>)")
    hosts = []
    for host in raiz.findall("host"):
        dir_el = host.find("address")
        ip = dir_el.get("addr") if dir_el is not None else ""
        puertos = []
        for p in host.findall("./ports/port"):
            estado_el = p.find("state")
            serv_el = p.find("service")
            puertos.append({
                "puerto": int(p.get("portid", "0") or 0),
                "protocolo": p.get("protocol", ""),
                "estado": estado_el.get("state", "") if estado_el is not None else "",
                "servicio": serv_el.get("name", "") if serv_el is not None else "",
            })
        puertos.sort(key=lambda x: (x["protocolo"], x["puerto"]))
        hosts.append({"host": ip, "puertos": puertos})
    hosts.sort(key=lambda h: h["host"])
    return {"hosts": hosts}


def resumen_hallazgos(hallazgos: list) -> str:
    if not hallazgos:
        return "Sin hallazgos."
    orden = {"critica": 0, "alta": 1, "media": 2, "baja": 3, "info": 4}
    hs = sorted(hallazgos, key=lambda h: orden.get(h.severidad, 5))
    lineas = [f"- [{h.severidad}/{h.estado}] {h.titulo} — {recortar(h.detalle, 160)}" for h in hs[:20]]
    confirmados = sum(1 for h in hallazgos if h.confirmado())
    return (f"{len(hallazgos)} hallazgo(s), {confirmados} confirmado(s) en laboratorio.\n" + "\n".join(lineas)
            + "\n(STATIC_FINDING/VERSION_MATCH_ONLY = a revisar; no es compromiso confirmado.)")
