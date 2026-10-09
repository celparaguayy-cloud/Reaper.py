"""
Análisis estático de muestras (REAPER v11, §10) — DEFENSIVO. Nunca ejecuta la muestra.

Capacidad blue-team: clasificar un artefacto por hashes (identidad/IOC), formato (magic bytes), entropía
(indicio de empaque/cifrado), strings imprimibles e indicadores estáticos (URLs, IPs, claves de registro,
APIs sospechosas), y GENERAR una regla YARA de DETECCIÓN. Todo sobre bytes, en memoria, sin ejecutar nada,
sin red. No fabrica malware ni payloads: solo describe y ayuda a detectar. Para análisis DINÁMICO haría falta
una VM realmente aislada (PLANNED); acá siempre es estático.
"""

import hashlib as _mu_hashlib

# Firmas de formato por magic bytes (prefijo -> nombre).
FORMATOS_MAGIC = [
    (b"MZ", "PE/DOS (ejecutable Windows)"),
    (b"\x7fELF", "ELF (ejecutable Linux)"),
    (b"\xca\xfe\xba\xbe", "Mach-O universal / class Java"),
    (b"\xcf\xfa\xed\xfe", "Mach-O (macOS)"),
    (b"%PDF", "PDF"),
    (b"PK\x03\x04", "ZIP/JAR/APK/OOXML"),
    (b"\x1f\x8b", "GZIP"),
    (b"Rar!", "RAR"),
    (b"\xd0\xcf\x11\xe0", "OLE2 (doc/xls antiguos)"),
    (b"\x89PNG", "PNG"),
    (b"dex\n", "DEX (Android)"),
    (b"#!", "script con shebang"),
]

# Nombres de API/indicadores que suelen aparecer en binarios ofensivos (SOLO para marcar, no para usar).
_MU_APIS_SOSPECHOSAS = (
    "VirtualAlloc", "WriteProcessMemory", "CreateRemoteThread", "LoadLibrary", "GetProcAddress",
    "WinExec", "ShellExecute", "URLDownloadToFile", "RegSetValue", "CreateService", "CryptEncrypt",
    "socket", "connect", "/bin/sh", "cmd.exe", "powershell", "base64",
)
_MU_RE_URL = re.compile(rb"https?://[\w\.\-/:%?=&#~+]{4,}")
_MU_RE_IP = re.compile(rb"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MU_RE_STRING = re.compile(rb"[\x20-\x7e]{5,}")


def _mu_entropia(datos: bytes) -> float:
    if not datos:
        return 0.0
    frec = collections.Counter(datos)
    total = len(datos)
    return round(-sum((c / total) * math.log2(c / total) for c in frec.values()), 3)


def _mu_formato(datos: bytes) -> str:
    for firma, nombre in FORMATOS_MAGIC:
        if datos.startswith(firma):
            return nombre
    return "desconocido"


def _mu_strings(datos: bytes, limite: int = 300) -> list:
    vistos = []
    for m in _MU_RE_STRING.finditer(datos):
        s = m.group(0).decode("ascii", "replace")
        vistos.append(s)
        if len(vistos) >= limite:
            break
    return vistos


def analizar_muestra(datos: bytes, nombre: str = "") -> dict:
    """Informe estático de una muestra (bytes). No ejecuta nada. Devuelve dict + lista de Hallazgo honestos."""
    datos = datos or b""
    strings = _mu_strings(datos)
    blob = b"\n".join(s.encode("ascii", "replace") for s in strings)
    urls = sorted({m.group(0).decode("ascii", "replace") for m in _MU_RE_URL.finditer(datos)})
    ips = sorted({m.group(0).decode("ascii", "replace") for m in _MU_RE_IP.finditer(blob)})
    apis = sorted({a for a in _MU_APIS_SOSPECHOSAS if a.encode() in blob or a.lower().encode() in blob.lower()})
    entropia = _mu_entropia(datos)
    formato = _mu_formato(datos)

    hallazgos = []
    if entropia >= 7.2 and len(datos) >= 256:
        hallazgos.append(Hallazgo("mu-entropia", f"Entropía alta ({entropia})", estado="STATIC_FINDING",
                                  severidad="media", detalle="posible empaque/cifrado; revisá si está packed.",
                                  limitaciones=["indicio estático; no confirma malicia"]))
    if urls or ips:
        hallazgos.append(Hallazgo("mu-net", "Indicadores de red embebidos", estado="STATIC_FINDING",
                                  severidad="media", detalle=f"URLs: {len(urls)}, IPs: {len(ips)} (posible C2 o descarga).",
                                  limitaciones=["son strings; no se contactó ninguno (análisis estático)"]))
    if apis:
        hallazgos.append(Hallazgo("mu-api", "APIs/cadenas sensibles", estado="STATIC_FINDING", severidad="media",
                                  detalle="presentes: " + ", ".join(apis[:10]),
                                  limitaciones=["su presencia no implica comportamiento malicioso"]))

    return {
        "nombre": nombre,
        "tamano": len(datos),
        "md5": _mu_hashlib.md5(datos).hexdigest(),       # identificador/IOC (no uso de seguridad)
        "sha1": _mu_hashlib.sha1(datos).hexdigest(),
        "sha256": _mu_hashlib.sha256(datos).hexdigest(),
        "formato": formato,
        "entropia": entropia,
        "strings": len(strings),
        "urls": urls[:50],
        "ips": ips[:50],
        "apis_sospechosas": apis,
        "hallazgos": hallazgos,
        "nota": "ANÁLISIS ESTÁTICO: la muestra NO fue ejecutada. Para análisis dinámico hace falta una VM aislada.",
    }


def generar_regla_yara(nombre_regla: str, strings_clave: list, descripcion: str = "") -> str:
    """Genera una regla YARA de DETECCIÓN a partir de strings observados (defensivo, para cazar la familia)."""
    nombre_regla = re.sub(r"\W+", "_", (nombre_regla or "muestra").strip()) or "muestra"
    claves = [s for s in (strings_clave or []) if 4 <= len(s) <= 120][:10]
    if not claves:
        claves = ["CAMBIAME_string_representativa"]
    lineas = [f"rule {nombre_regla}", "{", "    meta:",
              f'        description = "{(descripcion or "deteccion generada por REAPER (revisar antes de usar)")}"',
              '        author = "REAPER (blue-team)"', "    strings:"]
    for i, s in enumerate(claves):
        escapada = s.replace("\\", "\\\\").replace('"', '\\"')
        lineas.append(f'        $s{i} = "{escapada}" ascii wide')
    lineas += ["    condition:", f"        {('any' if len(claves) > 3 else 'all')} of them", "}"]
    return "\n".join(lineas)
