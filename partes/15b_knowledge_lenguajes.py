"""
Guías rápidas de más lenguajes (se suman a GUIAS_LENGUAJE). Son cortas a propósito: van en el prompt
de un modelo de 24B, así que cada línea tiene que evitar un error real y frecuente.
"""

GUIAS_LENGUAJE.update({
    "go": """GO
- go.mod obligatorio (`go mod init nombre`); imports del propio módulo como "nombre/paquete".
- Variables o imports sin usar NO compilan. Errores como valores: if err != nil { return fmt.Errorf("contexto: %w", err) }.
- Exportado = Mayúscula inicial. Un paquete por carpeta; main solo en la raíz o en cmd/<app>.
- Tests en el MISMO paquete: archivo_test.go con func TestX(t *testing.T) y tablas de casos:
    for _, c := range []struct{ in, want int }{{1, 2}} { if got := F(c.in); got != c.want { t.Errorf("F(%d)=%d", c.in, got) } }
- HTTP sin dependencias: net/http + httptest.NewServer en tests. JSON: encoding/json con tags `json:"campo"`.
- Concurrencia: sync.Mutex para mapas compartidos; `go test -race ./...` si hay goroutines.""",
    "rust": """RUST
- cargo new nombre; lógica en src/lib.rs (testeable) y src/main.rs fino que la usa (`use nombre::...`).
- Tests unitarios: #[cfg(test)] mod tests { use super::*; #[test] fn caso() { assert_eq!(f(2), 4); } }
  Tests de integración en tests/*.rs; el binario se prueba con env!("CARGO_BIN_EXE_nombre").
- Errores: enum propio + impl Display + Result<T, Error>; `?` para propagar. Nada de unwrap() en código de usuario.
- &str en parámetros, String en structs; .iter().map().collect::<Vec<_>>(); clone() si el borrow checker traba.
- Sin crates si no hacen falta (std alcanza): `cargo test --offline` anda sin red en Termux.""",
    "c": """C
- C99/C11 con `-std=c99 -Wall -Wextra`; Makefile con `CC ?= cc` (en Termux cc es clang) y objetivo `test`.
- Cabecera .h con include guard y prototipos; .c con la implementación; main.c fino.
- Strings: snprintf (nunca sprintf/strcpy/gets), tamaños con sizeof, siempre terminar en '\\0'.
- Memoria: cada malloc con su free; chequeá NULL; preferí arrays en stack si el tamaño es fijo.
- Leer líneas: fgets(buf, sizeof buf, stdin) y quitar el '\\n' con buf[strcspn(buf, "\\r\\n")] = '\\0'.
- Tests sin framework: un tests/test_x.c con macros que imprimen "ok N - nombre" / "not ok N - nombre" y exit(1) si falla.""",
    "java": """JAVA
- Sin Maven/Gradle en Termux: javac -encoding UTF-8 -d build src/*.java && java -cp build Main.
- Una clase pública por archivo, con el mismo nombre que el archivo. Sin records/var si no se pide Java moderno.
- Dinero en long (centavos) o BigDecimal, nunca double. Validá argumentos con IllegalArgumentException.
- Entrada: Scanner(System.in, "UTF-8") con hasNextLine() antes de nextLine() (si no, NoSuchElementException al cerrar stdin).
- Tests sin JUnit: clase XTest con métodos static void testAlgo() y un main que los recorre e imprime TAP.""",
    "php": """PHP
- PHP 8: declare(strict_types=1); tipos en parámetros y retornos; namespaces y require_once con __DIR__.
- Salida HTML: htmlspecialchars($x, ENT_QUOTES, 'UTF-8') SIEMPRE. SQL: PDO con prepare/execute (nunca concatenar).
- Servidor local: php -S 127.0.0.1:8000 -t public. Errores visibles en desarrollo: ini_set('display_errors', '1').
- JSON: json_encode(..., JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR) y json_decode($s, true, 512, JSON_THROW_ON_ERROR).
- Tests sin PHPUnit: tests/run.php con funciones prueba()/igual() que imprimen TAP y exit(1) si algo falla.""",
    "ruby": """RUBY
- # frozen_string_literal: true; código en lib/, ejecutable en bin/, tests en test/test_*.rb con minitest.
- require "minitest/autorun"; class TestX < Minitest::Test; def test_caso; assert_equal 4, f(2); end; end
- Correr: ruby -Ilib -Itest test/test_x.rb. Errores propios: class Error < StandardError; end y raise Error, "msg".
- Fechas: require "date"; Date.new(2024, 1, 2) y Date.iso8601. JSON: require "json"; JSON.parse / JSON.pretty_generate.""",
    "perl": """PERL
- use strict; use warnings; en TODOS los archivos. Módulos en lib/Nombre.pm terminados en `1;`.
- Tests en t/*.t con Test::More (is, like, ok, done_testing) y `prove -l t` para correrlos.
- Errores con die "mensaje\\n" y captura con eval { ... }; if ($@) { ... }.
- Entrada: while (my $linea = <STDIN>) { chomp $linea; ... } (termina solo cuando se acaba stdin).""",
    "interactivo": """PROGRAMAS INTERACTIVOS (input(), menús, REPL)
- Un EOFError al ejecutarlos SIN entrada no es un bug: es que nadie escribió. NO quites el input() para "arreglarlo".
- Probalos pasándoles la entrada: execute_command con <stdin>2\\n3\\n+\\nsalir</stdin>, o en tests
  subprocess.run([sys.executable, "app.py"], input="2\\n3\\nsalir\\n", capture_output=True, text=True, timeout=10).
- Diseño testeable: la lógica en funciones puras (calcular(a, b, op)); el bucle de input() solo llama a esas funciones.
- El bucle tiene que terminar con una opción de salida Y cuando se acaba la entrada (EOFError → salir prolijo).""",
})

_EXTENSIONES_GUIA.update({
    ".c": "c", ".h": "c", ".java": "java", ".php": "php", ".rb": "ruby", ".pl": "perl", ".pm": "perl", ".t": "perl",
})

PALABRAS_GUIA.extend([
    (" c ", "c"), (" en c", "c"), ("makefile", "c"), ("java ", "java"), ("java.", "java"), (" php", "php"),
    ("ruby", "ruby"), ("perl", "perl"), ("interactiv", "interactivo"), ("input(", "interactivo"),
    ("menú", "interactivo"), ("menu ", "interactivo"), (" repl", "interactivo"), ("calculadora", "interactivo"),
    ("eoferror", "interactivo"),
])
