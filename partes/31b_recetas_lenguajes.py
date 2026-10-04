"""
Recetas de otros lenguajes, también como programas completos con verificación incorporada
(si algo no da lo esperado, terminan con código de salida != 0).
comando_receta() arma el comando para compilar y ejecutar cada una.
"""

_EXTENSION_RECETA = {"python": "py", "go": "go", "rust": "rs", "c": "c", "java": "java", "php": "php", "ruby": "rb",
                     "bash": "sh", "javascript": "mjs", "perl": "pl", "html": "html", "css": "css"}
_REQUIERE_RECETA = {"go": "go", "rust": "rustc", "c": "cc", "java": "java", "php": "php", "ruby": "ruby", "bash": "bash",
                    "javascript": "node", "perl": "perl", "python": "python3"}


def comando_receta(r: Receta, ruta: str) -> str:
    q = shlex.quote(ruta)
    binario = shlex.quote(str(Path(ruta).with_suffix("")))
    return {
        "python": f"{shlex.quote(sys.executable)} {q}",
        "go": f"go run {q}",
        "rust": f"rustc --edition 2021 -O -o {binario} {q} && {binario}",
        "c": f"cc -std=c99 -Wall -Wextra -o {binario} {q} -lm && {binario}",
        "java": f"java {q}",
        "php": f"php {q}",
        "ruby": f"ruby {q}",
        "bash": f"bash {q}",
        "javascript": f"node {q}",
        "perl": f"perl {q}",
    }[r.lenguaje]


def receta_disponible(r: Receta) -> bool:
    return shutil.which(_REQUIERE_RECETA.get(r.lenguaje, r.lenguaje)) is not None


# ======================================================================== GO
receta_ejecutable("Go: worker pool con goroutines", "go", "go, golang, goroutine, concurrencia, paralelo, worker, canal",
                  "N trabajadores procesan tareas de un canal; resultados y errores en orden de llegada, con WaitGroup.", r'''
package main

import (
	"errors"
	"fmt"
	"os"
	"sort"
	"sync"
)

type resultado struct {
	entrada int
	salida  int
	err     error
}

func procesar(n int) (int, error) {
	if n < 0 {
		return 0, errors.New("número negativo")
	}
	return n * n, nil
}

func pool(entradas []int, trabajadores int) []resultado {
	tareas := make(chan int)
	resultados := make(chan resultado)
	var wg sync.WaitGroup
	for i := 0; i < trabajadores; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for n := range tareas {
				s, err := procesar(n)
				resultados <- resultado{n, s, err}
			}
		}()
	}
	go func() {
		for _, n := range entradas {
			tareas <- n
		}
		close(tareas)
	}()
	go func() {
		wg.Wait()
		close(resultados)
	}()
	var todos []resultado
	for r := range resultados {
		todos = append(todos, r)
	}
	sort.Slice(todos, func(a, b int) bool { return todos[a].entrada < todos[b].entrada })
	return todos
}

func main() {
	rs := pool([]int{3, -1, 2, 5}, 3)
	errores, suma := 0, 0
	for _, r := range rs {
		if r.err != nil {
			errores++
			continue
		}
		suma += r.salida
	}
	fmt.Println("suma:", suma, "errores:", errores)
	if suma != 38 || errores != 1 || len(rs) != 4 {
		os.Exit(1)
	}
}
''')

receta_ejecutable("Go: guardar y cargar JSON con structs", "go", "go, golang, json, archivo, guardar, cargar, struct",
                  "Tags json, escritura atómica y error claro si el archivo está dañado.", r'''
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

type Config struct {
	Nombre  string   `json:"nombre"`
	Puerto  int      `json:"puerto"`
	Debug   bool     `json:"debug,omitempty"`
	Usuarios []string `json:"usuarios"`
}

func cargar(ruta string) (Config, error) {
	c := Config{Puerto: 8080} // valores por defecto
	datos, err := os.ReadFile(ruta)
	if errors.Is(err, os.ErrNotExist) {
		return c, nil
	}
	if err != nil {
		return c, err
	}
	if err := json.Unmarshal(datos, &c); err != nil {
		return c, fmt.Errorf("config dañada en %s: %w", ruta, err)
	}
	return c, nil
}

func guardar(ruta string, c Config) error {
	datos, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	tmp := ruta + ".tmp"
	if err := os.WriteFile(tmp, append(datos, '\n'), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, ruta)
}

func main() {
	dir, _ := os.MkdirTemp("", "cfg")
	defer os.RemoveAll(dir)
	ruta := filepath.Join(dir, "config.json")
	c, err := cargar(ruta)
	if err != nil || c.Puerto != 8080 {
		os.Exit(1)
	}
	c.Nombre, c.Usuarios = "app", []string{"ana"}
	if err := guardar(ruta, c); err != nil {
		os.Exit(1)
	}
	otra, err := cargar(ruta)
	if err != nil || otra.Nombre != "app" || len(otra.Usuarios) != 1 {
		os.Exit(1)
	}
	_ = os.WriteFile(ruta, []byte("{roto"), 0o644)
	if _, err := cargar(ruta); err == nil {
		os.Exit(1)
	}
	fmt.Println("ok")
}
''')

receta_ejecutable("Go: cliente HTTP con timeout y contexto", "go", "go, golang, http, cliente, timeout, api, request",
                  "http.Client con Timeout, context para cancelar y chequeo del código de estado.", r'''
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"time"
)

func obtenerJSON(ctx context.Context, cliente *http.Client, url string, destino interface{}) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	resp, err := cliente.Do(req)
	if err != nil {
		return fmt.Errorf("pedido a %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		cuerpo, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, cuerpo)
	}
	return json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(destino)
}

func main() {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/lento" {
			time.Sleep(300 * time.Millisecond)
		}
		if r.URL.Path == "/error" {
			http.Error(w, "no", http.StatusTeapot)
			return
		}
		fmt.Fprint(w, `{"temp": 21}`)
	}))
	defer srv.Close()
	cliente := &http.Client{Timeout: 100 * time.Millisecond}
	var datos struct{ Temp int `json:"temp"` }
	if err := obtenerJSON(context.Background(), cliente, srv.URL+"/clima", &datos); err != nil || datos.Temp != 21 {
		fmt.Println("fallo:", err)
		os.Exit(1)
	}
	if err := obtenerJSON(context.Background(), cliente, srv.URL+"/lento", &datos); err == nil {
		os.Exit(1)
	}
	if err := obtenerJSON(context.Background(), cliente, srv.URL+"/error", &datos); err == nil {
		os.Exit(1)
	}
	fmt.Println("ok")
}
''')

# ======================================================================== RUST
receta_ejecutable("Rust: contar palabras con HashMap", "rust", "rust, hashmap, contar, palabras, frecuencia, texto",
                  "entry().or_insert, normalización y orden por frecuencia y luego alfabético.", r'''
use std::collections::HashMap;

fn frecuencias(texto: &str) -> Vec<(String, usize)> {
    let mut conteo: HashMap<String, usize> = HashMap::new();
    for palabra in texto
        .split(|c: char| !c.is_alphanumeric())
        .filter(|p| !p.is_empty())
        .map(|p| p.to_lowercase())
    {
        *conteo.entry(palabra).or_insert(0) += 1;
    }
    let mut v: Vec<(String, usize)> = conteo.into_iter().collect();
    v.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    v
}

fn main() {
    let v = frecuencias("El mate, el MATE y el termo. ¡Mate!");
    println!("{:?}", &v[..2]);
    assert_eq!(v[0], ("el".to_string(), 3));
    assert_eq!(v[1], ("mate".to_string(), 3));
    assert_eq!(v.len(), 4);
}
''')

receta_ejecutable("Rust: tipo propio con FromStr y Display", "rust", "rust, fromstr, display, parsear, tipo, struct, hora",
                  "Parsear '12:30' a un struct con errores descriptivos y mostrarlo con formato.", r'''
use std::fmt;
use std::str::FromStr;

#[derive(Debug, PartialEq, Clone, Copy)]
struct Hora {
    h: u8,
    m: u8,
}

#[derive(Debug, PartialEq)]
enum ErrorHora {
    Formato,
    Rango(String),
}

impl fmt::Display for ErrorHora {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ErrorHora::Formato => write!(f, "formato inválido, se esperaba HH:MM"),
            ErrorHora::Rango(s) => write!(f, "hora fuera de rango: {}", s),
        }
    }
}

impl FromStr for Hora {
    type Err = ErrorHora;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let (h, m) = s.trim().split_once(':').ok_or(ErrorHora::Formato)?;
        let h: u8 = h.parse().map_err(|_| ErrorHora::Formato)?;
        let m: u8 = m.parse().map_err(|_| ErrorHora::Formato)?;
        if h > 23 || m > 59 {
            return Err(ErrorHora::Rango(s.to_string()));
        }
        Ok(Hora { h, m })
    }
}

impl fmt::Display for Hora {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:02}:{:02}", self.h, self.m)
    }
}

impl Hora {
    fn sumar_minutos(self, minutos: u32) -> Hora {
        let total = (self.h as u32 * 60 + self.m as u32 + minutos) % (24 * 60);
        Hora { h: (total / 60) as u8, m: (total % 60) as u8 }
    }
}

fn main() {
    let h: Hora = "9:05".parse().unwrap();
    assert_eq!(h.to_string(), "09:05");
    assert_eq!(h.sumar_minutos(1000).to_string(), "01:45");
    assert_eq!("25:00".parse::<Hora>(), Err(ErrorHora::Rango("25:00".into())));
    assert_eq!("hola".parse::<Hora>(), Err(ErrorHora::Formato));
    println!("ok {}", ErrorHora::Formato);
}
''')

receta_ejecutable("Rust: errores con enum, From y el operador ?", "rust", "rust, error, result, from, operador, propagar, io",
                  "Un enum de error que envuelve io::Error y ParseIntError; ? convierte solo gracias a From.", r'''
use std::fmt;
use std::fs;
use std::io;
use std::num::ParseIntError;

#[derive(Debug)]
enum Error {
    Io(io::Error),
    Numero { linea: usize, fuente: ParseIntError },
    Vacio,
}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Io(e)
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Io(e) => write!(f, "no pude leer el archivo: {}", e),
            Error::Numero { linea, fuente } => write!(f, "línea {}: {}", linea, fuente),
            Error::Vacio => write!(f, "el archivo no tiene números"),
        }
    }
}

fn promedio_de_archivo(ruta: &str) -> Result<f64, Error> {
    let texto = fs::read_to_string(ruta)?; // io::Error → Error por From
    let mut numeros = Vec::new();
    for (i, linea) in texto.lines().enumerate().filter(|(_, l)| !l.trim().is_empty()) {
        let n: i64 = linea.trim().parse().map_err(|e| Error::Numero { linea: i + 1, fuente: e })?;
        numeros.push(n);
    }
    if numeros.is_empty() {
        return Err(Error::Vacio);
    }
    Ok(numeros.iter().sum::<i64>() as f64 / numeros.len() as f64)
}

fn main() {
    let dir = std::env::temp_dir().join(format!("receta_{}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let ok = dir.join("ok.txt");
    fs::write(&ok, "10\n20\n\n30\n").unwrap();
    assert_eq!(promedio_de_archivo(ok.to_str().unwrap()).unwrap(), 20.0);
    let malo = dir.join("malo.txt");
    fs::write(&malo, "1\nx\n").unwrap();
    let e = promedio_de_archivo(malo.to_str().unwrap()).unwrap_err();
    assert!(e.to_string().starts_with("línea 2:"), "{}", e);
    assert!(matches!(promedio_de_archivo("/no/existe"), Err(Error::Io(_))));
    fs::remove_dir_all(&dir).unwrap();
    println!("ok");
}
''')

# ======================================================================== C
receta_ejecutable("C: lista enlazada sin fugas de memoria", "c", "c, lista, enlazada, malloc, free, memoria, puntero",
                  "Insertar al final, borrar por valor y liberar todo; cada malloc chequeado.", r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct nodo {
    char nombre[32];
    struct nodo *sig;
} nodo;

static int agregar(nodo **cabeza, const char *nombre) {
    nodo *n = malloc(sizeof *n);
    if (!n) {
        return -1;
    }
    snprintf(n->nombre, sizeof n->nombre, "%s", nombre);
    n->sig = NULL;
    nodo **p = cabeza;
    while (*p) {
        p = &(*p)->sig;
    }
    *p = n;
    return 0;
}

static int borrar(nodo **cabeza, const char *nombre) {
    for (nodo **p = cabeza; *p; p = &(*p)->sig) {
        if (strcmp((*p)->nombre, nombre) == 0) {
            nodo *viejo = *p;
            *p = viejo->sig;
            free(viejo);
            return 1;
        }
    }
    return 0;
}

static size_t largo(const nodo *n) {
    size_t c = 0;
    for (; n; n = n->sig) {
        c++;
    }
    return c;
}

static void liberar(nodo **cabeza) {
    nodo *n = *cabeza;
    while (n) {
        nodo *sig = n->sig;
        free(n);
        n = sig;
    }
    *cabeza = NULL;
}

int main(void) {
    nodo *lista = NULL;
    agregar(&lista, "ana");
    agregar(&lista, "luis");
    agregar(&lista, "eva");
    if (largo(lista) != 3 || !borrar(&lista, "luis") || borrar(&lista, "zoe") || largo(lista) != 2) {
        return 1;
    }
    if (strcmp(lista->nombre, "ana") != 0 || strcmp(lista->sig->nombre, "eva") != 0) {
        return 1;
    }
    liberar(&lista);
    printf("ok\n");
    return lista == NULL ? 0 : 1;
}
''')

receta_ejecutable("C: leer un archivo entero en memoria", "c", "c, archivo, leer, fread, realloc, memoria, buffer",
                  "Lee por bloques agrandando el buffer (sirve también para stdin) y siempre termina en '\\0'.", r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Devuelve un buffer terminado en '\0' que el llamador libera con free(), o NULL si falla. */
static char *leer_todo(FILE *f, size_t *largo) {
    size_t cap = 4096, n = 0;
    char *buf = malloc(cap);
    if (!buf) {
        return NULL;
    }
    size_t leidos;
    while ((leidos = fread(buf + n, 1, cap - n - 1, f)) > 0) {
        n += leidos;
        if (cap - n - 1 == 0) {
            char *nuevo = realloc(buf, cap * 2);
            if (!nuevo) {
                free(buf);
                return NULL;
            }
            buf = nuevo;
            cap *= 2;
        }
    }
    if (ferror(f)) {
        free(buf);
        return NULL;
    }
    buf[n] = '\0';
    if (largo) {
        *largo = n;
    }
    return buf;
}

int main(void) {
    FILE *tmp = tmpfile();
    if (!tmp) {
        return 1;
    }
    for (int i = 0; i < 2000; i++) {
        fputs("linea de prueba\n", tmp);
    }
    rewind(tmp);
    size_t n = 0;
    char *texto = leer_todo(tmp, &n);
    fclose(tmp);
    if (!texto || n != 2000 * strlen("linea de prueba\n") || texto[n] != '\0') {
        free(texto);
        return 1;
    }
    printf("ok (%zu bytes)\n", n);
    free(texto);
    return 0;
}
''')

# ======================================================================== JAVA
receta_ejecutable("Java: archivos con Files y try-with-resources", "java", "java, archivo, leer, escribir, files, recursos, lineas",
                  "Leer/escribir texto UTF-8 y procesar líneas sin dejar archivos abiertos.", r'''
import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

public class Archivos {
    static long contarLineasCon(Path ruta, String palabra) throws IOException {
        long n = 0;
        try (BufferedReader lector = Files.newBufferedReader(ruta, StandardCharsets.UTF_8)) {
            String linea;
            while ((linea = lector.readLine()) != null) {
                if (linea.toLowerCase().contains(palabra.toLowerCase())) {
                    n++;
                }
            }
        }
        return n;
    }

    public static void main(String[] args) throws IOException {
        Path dir = Files.createTempDirectory("receta");
        Path ruta = dir.resolve("notas.txt");
        Files.write(ruta, List.of("Comprar mate", "llamar a Ana", "MATE cocido"), StandardCharsets.UTF_8);
        long n = contarLineasCon(ruta, "mate");
        Files.writeString(dir.resolve("resumen.txt"), "líneas con mate: " + n);
        String resumen = Files.readString(dir.resolve("resumen.txt"));
        Files.delete(dir.resolve("resumen.txt"));
        Files.delete(ruta);
        Files.delete(dir);
        if (n != 2 || !resumen.equals("líneas con mate: 2")) {
            System.exit(1);
        }
        System.out.println("ok");
    }
}
''')

receta_ejecutable("Java: agrupar y contar con streams", "java", "java, stream, agrupar, contar, map, collectors, lista",
                  "groupingBy + counting, ordenar un Map por valor y sumar con mapToLong.", r'''
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

public class Streams {
    static class Gasto {
        final String categoria;
        final long centavos;
        Gasto(String categoria, long centavos) { this.categoria = categoria; this.centavos = centavos; }
    }

    public static void main(String[] args) {
        List<Gasto> gastos = List.of(new Gasto("comida", 1500), new Gasto("viaje", 4000),
                                     new Gasto("comida", 2500), new Gasto("ocio", 800));
        Map<String, Long> porCategoria = gastos.stream()
            .collect(Collectors.groupingBy(g -> g.categoria, Collectors.summingLong(g -> g.centavos)));
        Map<String, Long> ordenado = porCategoria.entrySet().stream()
            .sorted(Map.Entry.<String, Long>comparingByValue().reversed())
            .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue, (a, b) -> a, LinkedHashMap::new));
        long total = gastos.stream().mapToLong(g -> g.centavos).sum();
        Map<String, Long> cantidad = gastos.stream()
            .collect(Collectors.groupingBy(g -> g.categoria, Collectors.counting()));
        System.out.println(ordenado);
        if (!ordenado.keySet().iterator().next().equals("viaje") || total != 8800 || cantidad.get("comida") != 2) {
            System.exit(1);
        }
    }
}
''')

# ======================================================================== PHP
receta_ejecutable("PHP: SQLite con PDO y consultas preparadas", "php", "php, pdo, sqlite, sql, base de datos, preparada, seguridad",
                  "Nunca concatenar SQL: prepare/execute, transacciones y fetch asociativo.", r'''
<?php
declare(strict_types=1);

function conectar(string $dsn = 'sqlite::memory:'): PDO
{
    $pdo = new PDO($dsn, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $pdo->exec('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, email TEXT UNIQUE)');
    return $pdo;
}

function crearUsuario(PDO $pdo, string $nombre, string $email): int
{
    $st = $pdo->prepare('INSERT INTO usuarios (nombre, email) VALUES (:nombre, :email)');
    $st->execute([':nombre' => $nombre, ':email' => $email]);
    return (int) $pdo->lastInsertId();
}

function buscar(PDO $pdo, string $texto): array
{
    $st = $pdo->prepare('SELECT id, nombre FROM usuarios WHERE nombre LIKE ? ORDER BY nombre');
    $st->execute(['%' . $texto . '%']);
    return $st->fetchAll();
}

$pdo = conectar();
$pdo->beginTransaction();
crearUsuario($pdo, 'Ana', 'ana@x.com');
crearUsuario($pdo, "Robert'); DROP TABLE usuarios;--", 'bobby@x.com');
$pdo->commit();
try {
    crearUsuario($pdo, 'Otra Ana', 'ana@x.com');
    exit(1);
} catch (PDOException $e) {
    // email duplicado: la restricción UNIQUE lo impide
}
$r = buscar($pdo, 'Ana');
$total = (int) $pdo->query('SELECT COUNT(*) FROM usuarios')->fetchColumn();
if (count($r) !== 1 || $r[0]['nombre'] !== 'Ana' || $total !== 2) {
    exit(1);
}
echo "ok\n";
''')

receta_ejecutable("PHP: validar y limpiar datos de un formulario", "php", "php, formulario, validar, sanitizar, post, email, html",
                  "filter_var para email/números, trim, límites y mensajes por campo; escape al mostrar.", r'''
<?php
declare(strict_types=1);

function validarRegistro(array $datos): array
{
    $errores = [];
    $limpio = [];
    $nombre = trim((string) ($datos['nombre'] ?? ''));
    if ($nombre === '' || mb_strlen($nombre) > 60) {
        $errores['nombre'] = 'El nombre es obligatorio (máx. 60 caracteres).';
    }
    $limpio['nombre'] = $nombre;
    $email = filter_var(trim((string) ($datos['email'] ?? '')), FILTER_VALIDATE_EMAIL);
    if ($email === false) {
        $errores['email'] = 'Email inválido.';
    }
    $limpio['email'] = $email ?: '';
    $edad = filter_var($datos['edad'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 13, 'max_range' => 120]]);
    if ($edad === false) {
        $errores['edad'] = 'La edad debe ser un número entre 13 y 120.';
    }
    $limpio['edad'] = $edad === false ? null : $edad;
    return [$limpio, $errores];
}

function e(string $texto): string
{
    return htmlspecialchars($texto, ENT_QUOTES, 'UTF-8');
}

[$ok, $errores] = validarRegistro(['nombre' => '  Ana ', 'email' => 'ana@mail.com', 'edad' => '30']);
[$malo, $errores2] = validarRegistro(['nombre' => '', 'email' => 'no-es-email', 'edad' => '7']);
if ($errores !== [] || $ok['nombre'] !== 'Ana' || $ok['edad'] !== 30) {
    exit(1);
}
if (array_keys($errores2) !== ['nombre', 'email', 'edad']) {
    exit(1);
}
if (e('<script>"x"</script>') !== '&lt;script&gt;&quot;x&quot;&lt;/script&gt;') {
    exit(1);
}
echo "ok\n";
''')

# ======================================================================== RUBY
receta_ejecutable("Ruby: JSON, group_by y sumas", "ruby", "ruby, json, agrupar, group_by, sumar, hash, datos",
                  "Leer y escribir JSON, agrupar registros y totalizar con sum y transform_values.", r'''
require "json"
require "tmpdir"

def resumen(gastos)
  gastos.group_by { |g| g["categoria"] }
        .transform_values { |lista| lista.sum { |g| g["monto"] } }
        .sort_by { |cat, total| [-total, cat] }
        .to_h
end

Dir.mktmpdir do |dir|
  ruta = File.join(dir, "gastos.json")
  datos = [
    { "categoria" => "comida", "monto" => 1500 },
    { "categoria" => "viaje", "monto" => 4000 },
    { "categoria" => "comida", "monto" => 2500 },
  ]
  File.write(ruta, JSON.pretty_generate(datos))
  leidos = JSON.parse(File.read(ruta))
  r = resumen(leidos)
  abort("mal: #{r}") unless r == { "comida" => 4000, "viaje" => 4000 }
  abort("orden") unless r.keys == %w[comida viaje]
  begin
    JSON.parse("{roto")
    abort("debía fallar")
  rescue JSON::ParserError
    puts "ok"
  end
end
''')

# ======================================================================== BASH
receta_ejecutable("Bash: opciones con getopts y ayuda", "bash", "bash, getopts, opciones, argumentos, flags, script, ayuda",
                  "Parsear -v -n NUM -o ARCHIVO con validación y un uso claro.", r'''
#!/usr/bin/env bash
set -euo pipefail

uso() {
  echo "uso: $(basename "$0") [-v] [-n NUM] [-o ARCHIVO] ARGS..." >&2
}

parsear() {
  VERBOSE=0 NUM=1 SALIDA="-"
  local OPTIND opt
  while getopts ":vn:o:h" opt; do
    case "$opt" in
      v) VERBOSE=1 ;;
      n) [[ "$OPTARG" =~ ^[0-9]+$ ]] || { echo "-n necesita un número" >&2; return 2; }
         NUM="$OPTARG" ;;
      o) SALIDA="$OPTARG" ;;
      h) uso; return 3 ;;
      :) echo "falta el valor de -$OPTARG" >&2; return 2 ;;
      \?) echo "opción desconocida: -$OPTARG" >&2; uso; return 2 ;;
    esac
  done
  shift $((OPTIND - 1))
  RESTO=("$@")
}

parsear -v -n 3 -o out.txt a b
[[ $VERBOSE == 1 && $NUM == 3 && $SALIDA == out.txt && "${RESTO[*]}" == "a b" ]] || exit 1
parsear -n x 2>/dev/null && exit 1
parsear -z 2>/dev/null && exit 1
parsear
[[ $VERBOSE == 0 && $NUM == 1 && ${#RESTO[@]} == 0 ]] || exit 1
echo ok
''')

receta_ejecutable("Bash: limpieza con trap y temporales", "bash", "bash, trap, temporal, mktemp, limpieza, salir, error",
                  "mktemp + trap EXIT: los temporales se borran aunque el script falle o se interrumpa. "
                  "Ojo: trap RETURN con variables local NO sirve (la variable ya no existe cuando corre).", r'''
#!/usr/bin/env bash
set -euo pipefail

# El cuerpo entre ( ) corre en un subshell: su trap EXIT se dispara al terminar la función,
# aunque falle un comando por set -e. En un script entero alcanza con: trap 'rm -rf "$tmp"' EXIT
procesar() (
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  printf 'b\na\nc\n' > "$tmp/datos.txt"
  sort "$tmp/datos.txt" > "$tmp/orden.txt"
  echo "$tmp"                        # solo para comprobar que después ya no existe
  paste -sd, "$tmp/orden.txt"
)

salida="$(procesar)"
dir="$(head -n1 <<<"$salida")"
[[ "$(tail -n1 <<<"$salida")" == "a,b,c" ]] || exit 1
[[ ! -e "$dir" ]] || { echo "no se limpió $dir"; exit 1; }
echo ok
''')

receta_ejecutable("Bash: reintentar un comando con espera creciente", "bash", "bash, reintentar, retry, backoff, red, comando, fallos",
                  "reintentar N comando...: espera 1, 2, 4... segundos entre intentos y devuelve el último código.", r'''
#!/usr/bin/env bash
set -uo pipefail

reintentar() {
  local intentos="$1"; shift
  local espera="${ESPERA_INICIAL:-1}" n=1 codigo=0
  while true; do
    "$@" && return 0
    codigo=$?
    (( n >= intentos )) && return "$codigo"
    echo "intento $n falló (código $codigo); reintento en ${espera}s" >&2
    sleep "$espera"
    espera=$(( espera * 2 ))
    n=$(( n + 1 ))
  done
}

CONTADOR="$(mktemp)"
trap 'rm -f "$CONTADOR"' EXIT
echo 0 > "$CONTADOR"
falla_dos_veces() {
  local n; n=$(( $(cat "$CONTADOR") + 1 )); echo "$n" > "$CONTADOR"
  (( n >= 3 ))
}
ESPERA_INICIAL=0 reintentar 5 falla_dos_veces 2>/dev/null || exit 1
[[ "$(cat "$CONTADOR")" == 3 ]] || exit 1
ESPERA_INICIAL=0 reintentar 2 false 2>/dev/null && exit 1
echo ok
''')

# ======================================================================== JAVASCRIPT
receta_ejecutable("JS: fetch con timeout (AbortController)", "javascript", "javascript, node, fetch, timeout, api, abort, http",
                  "Node 18+ trae fetch: AbortSignal.timeout corta pedidos colgados; chequear res.ok.", r'''
import http from 'node:http';
import assert from 'node:assert/strict';

export async function obtenerJSON(url, { timeoutMs = 3000 } = {}) {
  const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs), headers: { accept: 'application/json' } });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} en ${url}`);
  }
  return res.json();
}

const servidor = http.createServer((req, res) => {
  if (req.url === '/lento') { setTimeout(() => res.end('{}'), 500); return; }
  if (req.url === '/error') { res.writeHead(500); res.end('x'); return; }
  res.setHeader('content-type', 'application/json');
  res.end(JSON.stringify({ temp: 21 }));
});
await new Promise((ok) => servidor.listen(0, '127.0.0.1', ok));
const base = `http://127.0.0.1:${servidor.address().port}`;
try {
  assert.deepEqual(await obtenerJSON(`${base}/clima`), { temp: 21 });
  await assert.rejects(obtenerJSON(`${base}/lento`, { timeoutMs: 100 }), { name: 'TimeoutError' });
  await assert.rejects(obtenerJSON(`${base}/error`), /HTTP 500/);
  console.log('ok');
} finally {
  servidor.closeAllConnections?.();
  servidor.close();
}
''')

receta_ejecutable("JS: debounce y throttle", "javascript", "javascript, debounce, throttle, eventos, input, scroll, navegador",
                  "Para buscar mientras se escribe (debounce) o limitar eventos de scroll (throttle).", r'''
import assert from 'node:assert/strict';

export function debounce(fn, ms) {
  let id;
  return (...args) => {
    clearTimeout(id);
    id = setTimeout(() => fn(...args), ms);
  };
}

export function throttle(fn, ms) {
  let ultimo = -Infinity;
  return (...args) => {
    const ahora = Date.now();
    if (ahora - ultimo >= ms) {
      ultimo = ahora;
      fn(...args);
    }
  };
}

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
const llamadas = [];
const buscar = debounce((q) => llamadas.push(q), 30);
buscar('m'); buscar('ma'); buscar('mat'); buscar('mate');
await esperar(60);
assert.deepEqual(llamadas, ['mate']);

let veces = 0;
const scroll = throttle(() => veces++, 1000);
for (let i = 0; i < 50; i++) scroll();
assert.equal(veces, 1);
console.log('ok');
''')

receta_ejecutable("JS: router por hash para una página de una sola vista", "javascript", "javascript, router, spa, hash, navegacion, rutas, web",
                  "Rutas con parámetros (#/nota/12) sin frameworks; la lógica de match se testea en Node.", r'''
import assert from 'node:assert/strict';

export function crearRouter(rutas) {
  const compiladas = Object.entries(rutas).filter(([patron]) => patron !== '*').map(([patron, vista]) => {
    const nombres = [];
    const regex = new RegExp('^' + patron.replace(/:(\w+)/g, (_, n) => { nombres.push(n); return '([^/]+)'; }) + '$');
    return { regex, nombres, vista };
  });
  return function resolver(hash) {
    const ruta = (hash || '#/').replace(/^#/, '') || '/';
    for (const { regex, nombres, vista } of compiladas) {
      const m = ruta.match(regex);
      if (m) {
        const params = Object.fromEntries(nombres.map((n, i) => [n, decodeURIComponent(m[i + 1])]));
        return vista(params);
      }
    }
    return rutas['*'] ? rutas['*']({ ruta }) : null;
  };
}

// En el navegador:
//   const resolver = crearRouter({...});
//   const pintar = () => { document.querySelector('#app').innerHTML = resolver(location.hash); };
//   addEventListener('hashchange', pintar); pintar();
const resolver = crearRouter({
  '/': () => 'inicio',
  '/nota/:id': ({ id }) => `nota ${id}`,
  '/buscar/:q': ({ q }) => `buscar ${q}`,
  '*': ({ ruta }) => `404 ${ruta}`,
});
assert.equal(resolver(''), 'inicio');
assert.equal(resolver('#/nota/12'), 'nota 12');
assert.equal(resolver('#/buscar/mate%20cocido'), 'buscar mate cocido');
assert.equal(resolver('#/nada'), '404 /nada');
console.log('ok');
''')

# ======================================================================== PERL
receta_ejecutable("Perl: leer un archivo y contar con un hash", "perl", "perl, hash, contar, archivo, lineas, palabras, log",
                  "open con manejo de error, chomp, conteo con hash y orden por valor.", r'''
use strict;
use warnings;
use File::Temp qw(tempfile);

sub contar_niveles {
    my ($ruta) = @_;
    open(my $fh, '<:encoding(UTF-8)', $ruta) or die "no pude abrir $ruta: $!\n";
    my %conteo;
    while (my $linea = <$fh>) {
        chomp $linea;
        next unless $linea =~ /\b(INFO|WARN|ERROR)\b/;
        $conteo{$1}++;
    }
    close $fh;
    return \%conteo;
}

my ($fh, $ruta) = tempfile(UNLINK => 1);
print $fh "10:00 INFO inicio\n10:01 ERROR falló\n10:02 INFO sigue\n10:03 WARN lento\nbasura\n";
close $fh;
my $c = contar_niveles($ruta);
my @orden = sort { $c->{$b} <=> $c->{$a} || $a cmp $b } keys %$c;
die "mal\n" unless "@orden" eq "INFO ERROR WARN" && $c->{INFO} == 2;
eval { contar_niveles('/no/existe') };
die "debía fallar\n" unless $@ =~ /no pude abrir/;
print "ok\n";
''')
