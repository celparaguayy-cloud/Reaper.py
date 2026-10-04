"""
Base de conocimiento: pistas concretas para errores frecuentes y guías
cortas por lenguaje.

Cuando una herramienta devuelve un error real (traceback, salida de tests,
error de npm/pip...), REAPER le agrega al agente 1-3 pistas específicas en
español. Un modelo de 24B suele saber arreglar el error si alguien le dice
qué significa: esto ahorra pasos de "probar cosas al azar".
"""


@dataclass(frozen=True)
class Pista:
    patron: str
    texto: str
    categoria: str = "general"

    @functools.cached_property
    def regex(self) -> re.Pattern:
        return re.compile(self.patron, re.I | re.M)


PISTAS: list[Pista] = [
    # ------------------------------------------------------------ Python: imports y módulos
    Pista(r"ModuleNotFoundError: No module named '(requests|flask|numpy|pandas|bs4|yaml|dotenv|rich|colorama)'",
          "El módulo externo no está instalado. En Termux: `pip install <modulo>`. Si es para un script simple, "
          "preferí la librería estándar (urllib.request en vez de requests, json/csv en vez de pandas).", "python"),
    Pista(r"ModuleNotFoundError: No module named '([\w.]+)'",
          "Python no encuentra ese módulo. Si es un archivo del proyecto, revisá el nombre exacto, que exista "
          "un __init__.py en la carpeta del paquete y que el comando se ejecute desde la raíz del proyecto.", "python"),
    Pista(r"ImportError: cannot import name '(\w+)' from '([\w.]+)'",
          "El módulo existe pero no define ese nombre: revisá cómo se llama realmente la función/clase en el "
          "módulo (usá read_symbol o search_files) o si hay un import circular entre los dos archivos.", "python"),
    Pista(r"ImportError: attempted relative import with no known parent package",
          "Import relativo (from .x import y) en un archivo ejecutado como script. Ejecutalo con "
          "`python3 -m paquete.modulo` desde la raíz o usá imports absolutos.", "python"),
    Pista(r"partially initialized module .* \(most likely due to a circular import\)",
          "Import circular: dos módulos se importan entre sí al cargar. Mové el import adentro de la función que "
          "lo usa o extraé lo compartido a un tercer módulo.", "python"),
    # ------------------------------------------------------------ Python: nombres y tipos
    Pista(r"NameError: name '(\w+)' is not defined",
          "Se usa un nombre que no existe en ese ámbito: falta un import, la variable se define más abajo, "
          "está mal escrita o es un atributo que necesita `self.`.", "python"),
    Pista(r"UnboundLocalError: (?:local variable|cannot access local variable) '(\w+)'",
          "La función asigna esa variable en algún lugar, entonces Python la considera local en TODA la función. "
          "Inicializala al principio o usá `global`/`nonlocal` si querías la de afuera.", "python"),
    Pista(r"AttributeError: 'NoneType' object has no attribute '(\w+)'",
          "Algo que se esperaba un objeto vale None: una función que no hace `return`, un `.get()` que no "
          "encontró la clave o un `re.match` sin coincidencia. Buscá de dónde sale ese valor.", "python"),
    Pista(r"AttributeError: '(\w+)' object has no attribute '(\w+)'",
          "El objeto no tiene ese atributo/método: revisá el nombre exacto en la clase (read_symbol) y que el "
          "atributo se inicialice en __init__ antes de usarse.", "python"),
    Pista(r"AttributeError: module '(\w+)' has no attribute '(\w+)'",
          "El módulo no tiene ese atributo. Ojo con archivos del proyecto que se llaman igual que un módulo "
          "estándar (random.py, json.py, test.py): lo tapan.", "python"),
    Pista(r"TypeError: (\w+)\(\) missing (\d+) required positional argument",
          "Se llama a la función con menos argumentos de los que define. Si es un método, revisá que se llame "
          "sobre una instancia (obj.metodo()) y no sobre la clase.", "python"),
    Pista(r"TypeError: (\w+)\(\) takes (\d+) positional arguments? but (\d+) (?:was|were) given",
          "Sobran argumentos. En métodos, el primer parámetro debe ser `self`; si falta, Python cuenta la "
          "instancia como argumento extra.", "python"),
    Pista(r"TypeError: (\w+)\(\) got an unexpected keyword argument '(\w+)'",
          "La función no acepta ese parámetro con nombre: revisá su firma real con read_symbol.", "python"),
    Pista(r"TypeError: unsupported operand type\(s\) for ([+\-*/]): '(\w+)' and '(\w+)'",
          "Operación entre tipos incompatibles (p. ej. str + int). Convertí explícitamente con int(), float() "
          "o str(); los valores de input() y de archivos siempre llegan como texto.", "python"),
    Pista(r"TypeError: can only concatenate str \(not \"(\w+)\"\) to str",
          "Concatenación de texto con un número: usá f-strings (f\"{valor}\") o str(valor).", "python"),
    Pista(r"TypeError: '(\w+)' object is not subscriptable",
          "Se usa [ ] sobre algo que no es lista/dict (a menudo None o una función sin llamar: f en vez de f()).",
          "python"),
    Pista(r"TypeError: '(\w+)' object is not callable",
          "Se está llamando con () a algo que no es función: una variable pisó el nombre de una función o "
          "builtin (p. ej. `list = [...]` y después `list(x)`).", "python"),
    Pista(r"TypeError: '(\w+)' object is not iterable",
          "Se itera algo que no es iterable (un int o None). Revisá el valor que llega al for / al unpacking.",
          "python"),
    Pista(r"TypeError: Object of type (\w+) is not JSON serializable",
          "json.dumps no sabe convertir ese tipo: pasá a dict con asdict()/vars(), datetime con .isoformat(), "
          "set con list(), o usá default=str.", "python"),
    Pista(r"KeyError: ",
          "Se accede a una clave que no existe en el diccionario: usá .get(clave, defecto) o verificá con "
          "`if clave in d`. Revisá también mayúsculas y espacios en la clave.", "python"),
    Pista(r"IndexError: list index out of range",
          "Índice fuera de rango: la lista tiene menos elementos de lo esperado (¿lista vacía?). Verificá len() "
          "antes de acceder o recorré con for.", "python"),
    Pista(r"ValueError: invalid literal for int\(\) with base 10: '(.*?)'",
          "int() recibió texto que no es un número (vacío, con espacios o decimales). Usá .strip(), validá "
          "con .isdigit() o atrapá ValueError y mostrá un mensaje claro.", "python"),
    Pista(r"ValueError: too many values to unpack|ValueError: not enough values to unpack",
          "El desempaquetado no coincide con la cantidad de elementos (a, b = x). Revisá la forma real del dato.",
          "python"),
    Pista(r"ZeroDivisionError",
          "División por cero: validá el divisor antes (if total == 0) y decidí qué devolver en ese caso.", "python"),
    Pista(r"RecursionError: maximum recursion depth exceeded",
          "Recursión infinita: falta el caso base o una propiedad/método se llama a sí mismo (p. ej. un "
          "@property que usa self.nombre en vez de self._nombre).", "python"),
    Pista(r"FileNotFoundError: \[Errno 2\] No such file or directory: '(.*?)'",
          "El archivo no existe en esa ruta relativa al directorio actual. Construí la ruta desde el archivo: "
          "Path(__file__).parent / 'datos.json', y creá carpetas con mkdir(parents=True, exist_ok=True).", "python"),
    Pista(r"PermissionError: \[Errno 13\] Permission denied",
          "Sin permisos: en Termux usá rutas dentro de $HOME o, para /sdcard, corré `termux-setup-storage`. "
          "No se puede escribir en /usr ni /system.", "python"),
    Pista(r"IsADirectoryError", "Se intentó abrir una carpeta como archivo: revisá la ruta.", "python"),
    Pista(r"UnicodeDecodeError: 'utf-8' codec can't decode",
          "El archivo no está en UTF-8: abrilo con encoding='utf-8', errors='replace' o con el encoding correcto "
          "(latin-1).", "python"),
    Pista(r"json\.decoder\.JSONDecodeError|JSONDecodeError: Expecting",
          "El texto no es JSON válido (vacío, con comas finales o comillas simples). Si el archivo puede estar "
          "vacío o no existir, manejá ese caso y devolvé un valor por defecto.", "python"),
    Pista(r"sqlite3\.OperationalError: no such table",
          "La tabla no existe: ejecutá el CREATE TABLE IF NOT EXISTS al iniciar la conexión.", "python"),
    Pista(r"sqlite3\.OperationalError: database is locked",
          "Otra conexión dejó la base bloqueada: cerrá conexiones con `with`, hacé commit() y no compartas una "
          "conexión entre hilos.", "python"),
    Pista(r"IndentationError|TabError",
          "Error de indentación: usá 4 espacios en todo el archivo (sin tabs) y revisá que los bloques "
          "después de ':' estén indentados.", "python"),
    Pista(r"SyntaxError: f-string",
          "Error dentro de un f-string: no reutilices el mismo tipo de comilla adentro y cerrá todas las llaves.",
          "python"),
    Pista(r"SyntaxError: '(\(|\[|\{)' was never closed|SyntaxError: unexpected EOF",
          "Falta cerrar un paréntesis/corchete/llave, o el archivo quedó cortado: revisá el final del archivo.",
          "python"),
    Pista(r"EOFError: EOF when reading a line",
          "El programa pidió input() pero no hay entrada (tests o ejecución automática). Para probarlo pasale "
          "argumentos por línea de comandos, o en tests usá unittest.mock.patch('builtins.input').", "python"),
    Pista(r"AssertionError",
          "Un assert de test falló. Compará el valor esperado y el obtenido que muestra el test: decidí si el "
          "bug está en el código (lo normal) o si el test espera algo distinto a lo pedido.", "tests"),
    Pista(r"RuntimeError: dictionary changed size during iteration",
          "Se modifica un dict mientras se lo recorre: iterá sobre list(d.items()) o armá uno nuevo.", "python"),
    Pista(r"RuntimeWarning: coroutine '(\w+)' was never awaited",
          "Se llamó a una función async sin await: usá `await f()` dentro de async o asyncio.run(f()).", "python"),
    Pista(r"OSError: \[Errno 98\] Address already in use|address already in use",
          "El puerto ya está ocupado (otra instancia del servidor). Usá otro puerto o terminá el proceso anterior.",
          "red"),
    Pista(r"ConnectionRefusedError|Connection refused",
          "No hay nada escuchando en ese host/puerto: el servidor no está corriendo o el puerto es otro.", "red"),
    Pista(r"urllib\.error\.URLError|getaddrinfo failed|Temporary failure in name resolution|Name or service not known",
          "Sin conexión o DNS fallando. Los tests no deben depender de la red: simulá las respuestas con "
          "unittest.mock.", "red"),
    Pista(r"ssl\.SSLCertVerificationError|CERTIFICATE_VERIFY_FAILED",
          "Error de certificados. En Termux: `pkg install ca-certificates`. No desactives la verificación SSL.",
          "red"),
    # ------------------------------------------------------------ unittest / pytest
    Pista(r"Ran 0 tests|no tests ran|collected 0 items",
          "No se encontró ningún test: los archivos deben llamarse test_*.py, las clases heredar de "
          "unittest.TestCase y los métodos empezar con test_.", "tests"),
    Pista(r"ImportError while importing test module|ERROR collecting",
          "El test ni siquiera se pudo importar: el error está en un import del test o del código que importa. "
          "Corregí eso primero (mirá el traceback de la colección).", "tests"),
    Pista(r"fixture '(\w+)' not found",
          "pytest no encuentra ese fixture: definilo en el mismo archivo o en conftest.py, o quitalo de la firma.",
          "tests"),
    Pista(r"AssertionError: (\d+(?:\.\d+)?) != (\d+(?:\.\d+)?)",
          "Diferencia numérica: si son floats usá assertAlmostEqual / pytest.approx; si son enteros, el cálculo "
          "del código está mal.", "tests"),
    Pista(r"TypeError: .*NoneType.* (?:test_|assert)",
          "El test recibió None: la función probada probablemente no tiene `return`.", "tests"),
    # ------------------------------------------------------------ JavaScript / Node
    Pista(r"SyntaxError: Cannot use import statement outside a module",
          "Node trata el archivo como CommonJS. Renombralo a .mjs, agregá \"type\": \"module\" a package.json, "
          "o usá require().", "js"),
    Pista(r"ReferenceError: require is not defined",
          "El archivo es un módulo ES (.mjs o type=module): usá `import x from 'y'` en vez de require().", "js"),
    Pista(r"ReferenceError: (\w+) is not defined",
          "Variable o función no declarada en ese ámbito: falta importarla/declararla, o es un global del "
          "navegador (document, window, localStorage) usado en Node.", "js"),
    Pista(r"ReferenceError: (document|window|localStorage|navigator|alert) is not defined",
          "Código de navegador ejecutado en Node. Para testear en Node separá la lógica pura en un módulo sin "
          "DOM, o verificá `typeof document !== 'undefined'`.", "js"),
    Pista(r"TypeError: Cannot read propert(?:y|ies) of (undefined|null)",
          "Se accede a un atributo de algo undefined/null: un elemento del DOM que no existe (selector mal "
          "escrito o script cargado antes del HTML), o un dato que todavía no llegó. Usá ?. o verificá antes.",
          "js"),
    Pista(r"TypeError: (\w+(?:\.\w+)*) is not a function",
          "Se llama a algo que no es función: nombre mal escrito, import con/sin llaves equivocado "
          "(default vs nombrado) o el objeto no tiene ese método.", "js"),
    Pista(r"TypeError: Assignment to constant variable",
          "Se reasigna una variable declarada con const: usá let si de verdad cambia.", "js"),
    Pista(r"SyntaxError: Unexpected token",
          "Token inesperado: falta una llave/paréntesis/coma, hay una coma de más o JSON mal formado.", "js"),
    Pista(r"SyntaxError: Identifier '(\w+)' has already been declared",
          "Se declaró dos veces la misma variable con let/const en el mismo ámbito.", "js"),
    Pista(r"SyntaxError: The requested module '(.+?)' does not provide an export named '(\w+)'",
          "Ese módulo no exporta ese nombre: revisá si es export default (import x from) o nombrado "
          "(import { x } from) y el nombre exacto.", "js"),
    Pista(r"Error \[ERR_MODULE_NOT_FOUND\]|Cannot find module '(.+?)'",
          "Node no encuentra el módulo: en ESM los imports relativos necesitan la extensión ('./util.js'); si es "
          "un paquete, falta `npm install`.", "js"),
    Pista(r"ERR_REQUIRE_ESM",
          "Se hace require() de un paquete que solo es ESM: usá import dinámico o convertí el archivo a .mjs.", "js"),
    Pista(r"UnhandledPromiseRejection|Unhandled promise rejection",
          "Una promesa falló sin catch: agregá try/catch alrededor del await o .catch().", "js"),
    Pista(r"npm ERR! missing script: test|npm error Missing script: \"test\"",
          "package.json no tiene script de test: agregá \"test\": \"node --test\" en \"scripts\".", "js"),
    Pista(r"npm ERR! code ENOENT|npm error code ENOENT",
          "npm no encuentra package.json: ejecutá el comando en la carpeta del proyecto o creá uno con npm init -y.",
          "js"),
    Pista(r"EACCES: permission denied",
          "Sin permisos: en Termux no uses `npm install -g` con sudo; instalá local al proyecto.", "js"),
    Pista(r"# fail [1-9]|✖ failing tests",
          "Hay tests de node:test fallando: leé el 'not ok' y el detalle del assert (expected vs actual).", "tests"),
    Pista(r"AssertionError \[ERR_ASSERTION\]",
          "Falló un assert de node: compará 'expected' y 'actual'; para objetos usá assert.deepStrictEqual.", "tests"),
    # ------------------------------------------------------------ Shell / Termux
    Pista(r"command not found|: not found$",
          "El comando no existe en este entorno. En Termux se instala con `pkg install <paquete>`; no hay sudo "
          "ni apt-get directo (usá pkg).", "termux"),
    Pista(r"sudo: (?:command )?not found|sudo: not found",
          "Termux no usa sudo: todo corre como tu usuario. Quitá sudo del comando.", "termux"),
    Pista(r"/usr/bin/(env|python|bash)|#!/usr/bin/python",
          "En Termux /usr/bin no existe: usá shebang `#!/usr/bin/env python3` (termux-exec lo resuelve) o "
          "ejecutá con `python3 script.py`.", "termux"),
    Pista(r"Permission denied.*(/sdcard|/storage/emulated)",
          "Para acceder al almacenamiento compartido corré `termux-setup-storage` y usá ~/storage/shared.", "termux"),
    Pista(r"systemctl|systemd",
          "Termux no tiene systemd. Para servicios usá termux-services (sv) o simplemente correlo en otra sesión.",
          "termux"),
    Pista(r"bash: .*: Permission denied",
          "El script no tiene permiso de ejecución: `chmod +x script.sh` o ejecutalo con `bash script.sh`.", "shell"),
    Pista(r"syntax error near unexpected token",
          "Error de sintaxis de bash: revisá comillas sin cerrar, `then`/`fi`/`done` faltantes y que no haya "
          "CRLF (\\r) en el archivo.", "shell"),
    Pista(r"\$'\\r': command not found|\\r: command not found",
          "El script tiene finales de línea de Windows (CRLF): convertilo con `sed -i 's/\\r$//' script.sh`.", "shell"),
    Pista(r"Tiempo agotado después de \d+s",
          "El comando no terminó: probablemente espera input() o es un servidor. Para probarlo pasá argumentos, "
          "usá un modo de prueba, o testeá las funciones directamente.", "general"),
    # ------------------------------------------------------------ pip / dependencias
    Pista(r"error: externally-managed-environment",
          "pip se niega a instalar en el Python del sistema: usá un venv (`python3 -m venv .venv`) o "
          "`pip install --user`.", "pip"),
    Pista(r"Failed building wheel for (\w+)|error: command '(?:gcc|clang)' failed",
          "El paquete necesita compilarse. En Termux: `pkg install clang make pkg-config` (y libs como "
          "libxml2, libjpeg-turbo según el paquete) o buscá una alternativa pura en Python.", "pip"),
    Pista(r"No matching distribution found for",
          "Ese paquete/versión no existe para esta plataforma o versión de Python: revisá el nombre o quitá la "
          "versión fija.", "pip"),
    # ------------------------------------------------------------ git
    Pista(r"fatal: not a git repository", "La carpeta no es un repositorio git: `git init` para crearlo.", "git"),
    Pista(r"Please tell me who you are",
          "Git no tiene identidad configurada: `git config user.name \"Nombre\"` y `git config user.email \"mail\"`.",
          "git"),
    Pista(r"CONFLICT \(content\)|Automatic merge failed",
          "Conflicto de merge: editá los archivos marcados con <<<<<<< ======= >>>>>>> y hacé commit.", "git"),
    # ------------------------------------------------------------ HTML/CSS/web
    Pista(r"recursos-html|referencia a '.*' que no existe",
          "El HTML apunta a un archivo que no existe: creá ese archivo o corregí la ruta del src/href "
          "(relativa a la carpeta del HTML).", "web"),
    Pista(r"css-llaves",
          "Llaves desbalanceadas en el CSS: buscá un bloque sin cerrar (la línea indicada o la regla anterior).",
          "web"),
    # ------------------------------------------------------------ Go / Rust / C
    Pista(r"declared and not used|declared but not used",
          "Go no permite variables sin usar: usala o reemplazala por _.", "go"),
    Pista(r"imported and not used", "Go no permite imports sin usar: quitalo.", "go"),
    Pista(r"cannot find package|no required module provides package",
          "Falta el módulo: corré `go mod init <nombre>` y `go mod tidy`.", "go"),
    Pista(r"error\[E0382\]: borrow of moved value|use of moved value",
          "Rust: el valor se movió antes. Usá una referencia (&x), .clone(), o reorganizá el orden.", "rust"),
    Pista(r"error\[E0502\]|cannot borrow .* as mutable because it is also borrowed as immutable",
          "Rust: préstamos mutable e inmutable al mismo tiempo. Acotá el alcance de la referencia inmutable.", "rust"),
    Pista(r"undefined reference to `(\w+)'",
          "C/C++: la función está declarada pero no se compiló/enlazó su definición: agregá el .c al comando o "
          "la librería con -l.", "c"),
    Pista(r"implicit declaration of function '(\w+)'",
          "C: falta el #include del header que declara esa función (o su prototipo).", "c"),
    Pista(r"segmentation fault|Segmentation fault",
          "Acceso inválido a memoria: puntero NULL, índice fuera de rango o recursión infinita.", "c"),
    # ------------------------------------------------------------ REAPER
    Pista(r"No encontré el texto de SEARCH",
          "El SEARCH no coincide con el archivo actual. Releé el tramo con read_file (o read_symbol) y copiá "
          "las líneas EXACTAS; o usá replace_symbol para reemplazar la función completa por nombre.", "reaper"),
    Pista(r"aparece \d+ veces|coincide en \d+ lugares",
          "El SEARCH es ambiguo: agregá 2-3 líneas vecinas únicas (la firma de la función, un comentario).",
          "reaper"),
    Pista(r"llamada .* quedó incompleta|se cortó tu respuesta",
          "Tu mensaje se cortó por longitud. Escribí archivos largos en partes: write_to_file con la primera "
          "parte y append_to_file para el resto (máx ~150 líneas por mensaje).", "reaper"),
    Pista(r"marcador de código omitido|código omitido",
          "Nunca uses '...' ni 'resto igual': escribí el código real o editá solo el tramo con replace_in_file "
          "/ replace_symbol.", "reaper"),
    Pista(r"está vacía \(pass/\.\.\./NotImplementedError\)",
          "Quedaron funciones sin implementar: completalas (replace_symbol con el cuerpo real) antes de terminar.",
          "reaper"),
    Pista(r"no define '(\w+)'",
          "Se importa un nombre que el módulo del proyecto no define: corregí el nombre (mirá la sugerencia) o "
          "agregá esa función al módulo.", "reaper"),
    Pista(r"no exporta '(\w+)'",
          "El módulo JS no exporta ese nombre: agregá `export` a la declaración o corregí el import.", "reaper"),
]


def pistas_para(texto: str, maximo: int = 3) -> list[str]:
    """Pistas aplicables a una salida de error, sin repetir y priorizando las más específicas."""
    if not texto:
        return []
    salida: list[str] = []
    for pista in PISTAS:
        if pista.regex.search(texto):
            if pista.texto not in salida:
                salida.append(pista.texto)
            if len(salida) >= maximo:
                break
    return salida


def anexar_pistas(texto: str, maximo: int = 2) -> str:
    pistas = pistas_para(texto, maximo)
    if not pistas:
        return texto
    return texto + "\n\nPISTAS DE REAPER:\n" + "\n".join(f"- {p}" for p in pistas)


GUIAS_LENGUAJE = {
    "python": """PYTHON
- Librería estándar primero (json, sqlite3, pathlib, argparse, unittest, urllib). Nada de pip si no hace falta.
- Rutas: Path(__file__).resolve().parent / "datos.json"; crear carpetas con mkdir(parents=True, exist_ok=True).
- Lógica en funciones puras testeables; input()/print() solo en main(). Siempre `if __name__ == "__main__": main()`.
- Tests (unittest): tests/test_<modulo>.py
    import unittest
    from <modulo> import <funcion>
    class Test<Algo>(unittest.TestCase):
        def test_caso(self):
            self.assertEqual(<funcion>(2, 3), 5)
    if __name__ == "__main__":
        unittest.main()
- Archivos temporales en tests: tempfile.TemporaryDirectory(); input simulado: unittest.mock.patch("builtins.input").""",
    "js": """JAVASCRIPT
- Node moderno: módulos ES (.mjs o "type": "module"), imports relativos CON extensión ('./util.js').
- Separá la lógica pura (sin DOM) en un módulo exportado: así se testea con node:test.
- Tests: tests/<modulo>.test.mjs
    import { test } from 'node:test';
    import assert from 'node:assert/strict';
    import { suma } from '../src/suma.js';
    test('suma dos números', () => { assert.equal(suma(2, 3), 5); });
- En el navegador: <script type="module" src="app.js"></script> y esperá el DOM (defer o DOMContentLoaded).""",
    "web": """WEB (HTML/CSS/JS)
- index.html enlaza style.css y app.js con rutas relativas que EXISTAN.
- Sin frameworks ni CDN si no se pidieron; funciona abriendo el archivo o con `python3 -m http.server`.
- Mobile first: <meta name="viewport" content="width=device-width, initial-scale=1">.
- Guardar datos del usuario: localStorage con JSON.stringify/parse y valores por defecto.""",
    "sh": """BASH
- Primera línea `#!/usr/bin/env bash` y `set -euo pipefail`.
- Comillas en todas las variables ("$var"); funciones pequeñas; `command -v x` para chequear herramientas.
- Termux: sin sudo ni systemd; paquetes con `pkg install`; $PREFIX en lugar de /usr.""",
    "go": """GO
- go.mod obligatorio (go mod init nombre). Tests en *_test.go con func TestX(t *testing.T).
- Sin variables ni imports sin usar (no compila). Errores como valores: if err != nil { return err }.""",
    "rust": """RUST
- cargo new; tests con #[cfg(test)] mod tests { use super::*; #[test] fn caso() { assert_eq!(..) } }.
- Preferí &str en parámetros, String en structs; .clone() si el borrow checker se pone difícil.""",
}

_EXTENSIONES_GUIA = {
    ".py": "python", ".js": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".jsx": "js", ".tsx": "js",
    ".html": "web", ".htm": "web", ".css": "web", ".sh": "sh", ".bash": "sh", ".go": "go", ".rs": "rust",
}


def guias_para(archivos: Iterable[str], pedido: str = "") -> str:
    claves: list[str] = []
    for a in archivos:
        clave = _EXTENSIONES_GUIA.get(Path(a).suffix.lower())
        if clave and clave not in claves:
            claves.append(clave)
    texto = (pedido or "").lower()
    for palabra, clave in (("python", "python"), ("html", "web"), ("web", "web"), ("javascript", "js"),
                           ("node", "js"), ("bash", "sh"), ("script", "sh"), ("golang", "go"), (" go ", "go"),
                           ("rust", "rust")):
        if palabra in texto and clave not in claves:
            claves.append(clave)
    if not claves:
        return ""
    return "\n\n".join(GUIAS_LENGUAJE[c] for c in claves[:3])
