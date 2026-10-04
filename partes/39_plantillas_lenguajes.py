"""
Plantillas en otros lenguajes (todas con tests que pasan y disponibles en Termux con `pkg install`):

  bash-notas       notas desde la terminal (bash puro, tests TAP sin dependencias)
  go-tareas        CLI de tareas con persistencia JSON (go test)
  go-api           API REST de notas con net/http y httptest (sin dependencias)
  rust-inventario  inventario con CSV y REPL interactivo (cargo test, sin crates)
  c-rpn            calculadora RPN en C99 con Makefile y tests TAP
  java-banco       cuentas y transferencias en Java sin Maven (runner de tests propio)
  php-carrito      carrito de compras en PHP 8 con tests sin PHPUnit
  ruby-biblioteca  préstamos de libros en Ruby con minitest
  perl-conversor   conversor de unidades en Perl con Test::More (prove)

Los programas interactivos (REPL, menús) se prueban pasando la entrada por stdin: las plantillas lo
muestran en sus tests y en su REAPER.md, así el modelo no los "arregla" quitándoles la interactividad.
"""

# ======================================================================
# bash-notas
# ======================================================================
registrar_plantilla(
    "bash-notas",
    "Notas desde la terminal en bash puro: agregar, listar, buscar, borrar. Lógica en lib/, tests TAP.",
    "bash",
    {
        "notas.sh": r'''#!/usr/bin/env bash
# __TITULO__: notas rápidas desde la terminal (Termux / Linux).
# Uso: bash notas.sh ayuda
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/notas_lib.sh
source "$DIR/lib/notas_lib.sh"

ARCHIVO="${NOTAS_ARCHIVO:-$HOME/.__PROYECTO___notas.txt}"

ayuda() {
  cat <<'TEXTO'
Uso: notas.sh COMANDO [ARGUMENTOS]

  agregar TEXTO     guarda una nota nueva
  listar            muestra todas las notas numeradas
  buscar PALABRA    muestra las notas que contienen PALABRA (sin distinguir mayúsculas)
  borrar NUMERO     borra la nota NUMERO
  contar            cantidad de notas
  exportar          imprime las notas en Markdown
  ayuda             esta ayuda

El archivo se elige con la variable NOTAS_ARCHIVO.
TEXTO
}

main() {
  local comando="${1:-ayuda}"
  shift || true
  case "$comando" in
    agregar)
      [[ $# -gt 0 ]] || { echo "uso: notas.sh agregar TEXTO" >&2; return 2; }
      nota_agregar "$ARCHIVO" "$*"
      echo "nota guardada (#$(nota_contar "$ARCHIVO"))"
      ;;
    listar) nota_listar "$ARCHIVO" ;;
    buscar)
      [[ $# -gt 0 ]] || { echo "uso: notas.sh buscar PALABRA" >&2; return 2; }
      nota_buscar "$ARCHIVO" "$1" || { echo "sin resultados para: $1"; return 1; }
      ;;
    borrar)
      [[ $# -gt 0 ]] || { echo "uso: notas.sh borrar NUMERO" >&2; return 2; }
      nota_borrar "$ARCHIVO" "$1"
      ;;
    contar) nota_contar "$ARCHIVO" ;;
    exportar) nota_exportar_md "$ARCHIVO" ;;
    ayuda|-h|--help) ayuda ;;
    *)
      echo "comando desconocido: $comando" >&2
      ayuda >&2
      return 2
      ;;
  esac
}

main "$@"
''',
        "lib/notas_lib.sh": r'''#!/usr/bin/env bash
# Funciones puras (testeables) de __TITULO__. Formato del archivo: una nota por línea, "FECHA|TEXTO".

# Fecha actual; NOTAS_FECHA la fija (para tests reproducibles).
nota_fecha() {
  if [[ -n "${NOTAS_FECHA:-}" ]]; then
    printf '%s' "$NOTAS_FECHA"
  else
    date '+%Y-%m-%d %H:%M'
  fi
}

# Una nota no puede tener saltos de línea ni el separador "|" (rompería el formato).
nota_normalizar() {
  local texto="$1"
  texto="${texto//$'\n'/ }"
  texto="${texto//$'\r'/ }"
  texto="${texto//|/\/}"
  # recorta espacios al principio y al final
  texto="${texto#"${texto%%[![:space:]]*}"}"
  texto="${texto%"${texto##*[![:space:]]}"}"
  printf '%s' "$texto"
}

nota_agregar() {
  local archivo="$1" texto
  texto="$(nota_normalizar "$2")"
  if [[ -z "$texto" ]]; then
    echo "la nota está vacía" >&2
    return 2
  fi
  mkdir -p "$(dirname "$archivo")"
  printf '%s|%s\n' "$(nota_fecha)" "$texto" >> "$archivo"
}

nota_contar() {
  local archivo="$1"
  if [[ ! -s "$archivo" ]]; then
    echo 0
    return 0
  fi
  grep -c '' "$archivo"
}

# Imprime "N. [FECHA] TEXTO" para cada línea que recibe por stdin como "N|FECHA|TEXTO".
_nota_formatear() {
  local numero fecha texto
  while IFS='|' read -r numero fecha texto; do
    printf '%s. [%s] %s\n' "$numero" "$fecha" "$texto"
  done
}

nota_listar() {
  local archivo="$1"
  if [[ ! -s "$archivo" ]]; then
    echo "(sin notas)"
    return 0
  fi
  awk '{ print NR "|" $0 }' "$archivo" | _nota_formatear
}

# Devuelve 1 si no hay coincidencias (como grep).
nota_buscar() {
  local archivo="$1" palabra="$2"
  [[ -s "$archivo" ]] || return 1
  local salida
  salida="$(awk -v p="$palabra" 'BEGIN { p = tolower(p) } index(tolower($0), p) > 0 { print NR "|" $0 }' "$archivo")"
  [[ -n "$salida" ]] || return 1
  printf '%s\n' "$salida" | _nota_formatear
}

nota_borrar() {
  local archivo="$1" numero="$2" total
  if ! [[ "$numero" =~ ^[0-9]+$ ]]; then
    echo "número inválido: $numero" >&2
    return 2
  fi
  total="$(nota_contar "$archivo")"
  if (( numero < 1 || numero > total )); then
    echo "no existe la nota $numero (hay $total)" >&2
    return 1
  fi
  local temporal
  temporal="$(mktemp "${archivo}.XXXXXX")"
  awk -v n="$numero" 'NR != n' "$archivo" > "$temporal"
  mv "$temporal" "$archivo"
  echo "nota $numero borrada"
}

nota_exportar_md() {
  local archivo="$1"
  echo "# Notas"
  echo
  if [[ ! -s "$archivo" ]]; then
    echo "_(sin notas)_"
    return 0
  fi
  local fecha texto
  while IFS='|' read -r fecha texto; do
    printf -- '- **%s** %s\n' "$fecha" "$texto"
  done < "$archivo"
}
''',
        "tests/test_notas.sh": r'''#!/usr/bin/env bash
# Tests de __TITULO__ en formato TAP, sin dependencias. Ejecutar: bash tests/test_notas.sh
set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../lib/notas_lib.sh
source "$RAIZ/lib/notas_lib.sh"

TOTAL=0
FALLAS=0

afirmar_igual() {  # esperado obtenido nombre
  TOTAL=$((TOTAL + 1))
  if [[ "$1" == "$2" ]]; then
    echo "ok $TOTAL - $3"
  else
    echo "not ok $TOTAL - $3"
    echo "#   esperado: $1"
    echo "#   obtenido: $2"
    FALLAS=$((FALLAS + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export NOTAS_FECHA="2024-01-02 10:00"
A="$TMP/notas.txt"

afirmar_igual "(sin notas)" "$(nota_listar "$A")" "listar sin archivo"
afirmar_igual "0" "$(nota_contar "$A")" "contar sin archivo"

nota_agregar "$A" "comprar pan"
nota_agregar "$A" "Llamar a Ana"
nota_agregar "$A" "  pagar | luz  "
afirmar_igual "3" "$(nota_contar "$A")" "contar después de agregar"
afirmar_igual "1. [2024-01-02 10:00] comprar pan" "$(nota_listar "$A" | head -n 1)" "formato de listar"
afirmar_igual "3. [2024-01-02 10:00] pagar / luz" "$(nota_listar "$A" | tail -n 1)" "normaliza separador y espacios"
afirmar_igual "2. [2024-01-02 10:00] Llamar a Ana" "$(nota_buscar "$A" "ANA")" "buscar sin distinguir mayúsculas"

nota_buscar "$A" "zzz" > /dev/null
afirmar_igual "1" "$?" "buscar sin resultados devuelve 1"

nota_agregar "$A" "   " 2> /dev/null
afirmar_igual "2" "$?" "nota vacía se rechaza"

afirmar_igual "nota 1 borrada" "$(nota_borrar "$A" 1)" "borrar"
afirmar_igual "1. [2024-01-02 10:00] Llamar a Ana" "$(nota_listar "$A" | head -n 1)" "renumera después de borrar"

nota_borrar "$A" 9 2> /dev/null
afirmar_igual "1" "$?" "borrar fuera de rango"
nota_borrar "$A" abc 2> /dev/null
afirmar_igual "2" "$?" "borrar con número inválido"

afirmar_igual "- **2024-01-02 10:00** Llamar a Ana" "$(nota_exportar_md "$A" | sed -n 3p)" "exportar en Markdown"

# La CLI completa, como la usaría una persona
export NOTAS_ARCHIVO="$TMP/cli.txt"
bash "$RAIZ/notas.sh" agregar hola mundo > /dev/null
afirmar_igual "1. [2024-01-02 10:00] hola mundo" "$(bash "$RAIZ/notas.sh" listar)" "CLI agregar + listar"
bash "$RAIZ/notas.sh" desconocido > /dev/null 2>&1
afirmar_igual "2" "$?" "CLI comando desconocido sale con 2"

echo "1..$TOTAL"
echo "# tests $TOTAL"
echo "# pass $((TOTAL - FALLAS))"
echo "# fail $FALLAS"
[[ $FALLAS -eq 0 ]]
''',
        "README.md": """# __TITULO__

Notas rápidas desde la terminal, en bash puro.

```bash
bash notas.sh agregar "comprar pan"
bash notas.sh listar
bash notas.sh buscar pan
bash notas.sh borrar 1
bash tests/test_notas.sh      # tests (TAP)
```

Tip Termux: `ln -s "$PWD/notas.sh" $PREFIX/bin/notas` para usarlo como comando.
""",
    },
    comando_tests="bash tests/test_notas.sh",
    comando_ejecutar="bash notas.sh ayuda",
    etiquetas=("bash", "cli", "termux"),
    requiere=("bash",),
)

# ======================================================================
# go-tareas
# ======================================================================
registrar_plantilla(
    "go-tareas",
    "CLI de tareas en Go con prioridades y persistencia JSON atómica. Paquete tareas/ con tests (go test).",
    "go",
    {
        "go.mod": "module __PROYECTO__\n\ngo 1.18\n",
        "tareas/tareas.go": r'''// Package tareas maneja una lista de tareas con prioridad, persistida en JSON.
package tareas

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Tarea es un pendiente con prioridad 1 (baja) a 3 (alta).
type Tarea struct {
	ID        int       `json:"id"`
	Titulo    string    `json:"titulo"`
	Hecha     bool      `json:"hecha"`
	Prioridad int       `json:"prioridad"`
	Creada    time.Time `json:"creada"`
}

// Lista es el estado completo que se guarda en disco.
type Lista struct {
	Tareas  []Tarea `json:"tareas"`
	Proximo int     `json:"proximo"`
}

var (
	ErrNoExiste    = errors.New("la tarea no existe")
	ErrTituloVacio = errors.New("el título no puede estar vacío")
	ErrYaHecha     = errors.New("la tarea ya estaba hecha")
)

// Nueva devuelve una lista vacía.
func Nueva() *Lista { return &Lista{Proximo: 1} }

func limitarPrioridad(p int) int {
	if p < 1 {
		return 1
	}
	if p > 3 {
		return 3
	}
	return p
}

// Agregar crea una tarea nueva y la devuelve.
func (l *Lista) Agregar(titulo string, prioridad int, ahora time.Time) (Tarea, error) {
	titulo = strings.Join(strings.Fields(titulo), " ")
	if titulo == "" {
		return Tarea{}, ErrTituloVacio
	}
	if l.Proximo < 1 {
		l.Proximo = 1
	}
	t := Tarea{ID: l.Proximo, Titulo: titulo, Prioridad: limitarPrioridad(prioridad), Creada: ahora}
	l.Tareas = append(l.Tareas, t)
	l.Proximo++
	return t, nil
}

func (l *Lista) indice(id int) (int, error) {
	for i, t := range l.Tareas {
		if t.ID == id {
			return i, nil
		}
	}
	return -1, fmt.Errorf("%w: %d", ErrNoExiste, id)
}

// Completar marca la tarea como hecha.
func (l *Lista) Completar(id int) error {
	i, err := l.indice(id)
	if err != nil {
		return err
	}
	if l.Tareas[i].Hecha {
		return ErrYaHecha
	}
	l.Tareas[i].Hecha = true
	return nil
}

// Borrar elimina la tarea (los IDs no se reutilizan).
func (l *Lista) Borrar(id int) error {
	i, err := l.indice(id)
	if err != nil {
		return err
	}
	l.Tareas = append(l.Tareas[:i], l.Tareas[i+1:]...)
	return nil
}

// Pendientes devuelve las tareas sin hacer, primero las de mayor prioridad y después por ID.
func (l *Lista) Pendientes() []Tarea {
	var salida []Tarea
	for _, t := range l.Tareas {
		if !t.Hecha {
			salida = append(salida, t)
		}
	}
	sort.SliceStable(salida, func(a, b int) bool {
		if salida[a].Prioridad != salida[b].Prioridad {
			return salida[a].Prioridad > salida[b].Prioridad
		}
		return salida[a].ID < salida[b].ID
	})
	return salida
}

// Buscar devuelve las tareas cuyo título contiene el texto (sin distinguir mayúsculas).
func (l *Lista) Buscar(texto string) []Tarea {
	texto = strings.ToLower(strings.TrimSpace(texto))
	var salida []Tarea
	for _, t := range l.Tareas {
		if strings.Contains(strings.ToLower(t.Titulo), texto) {
			salida = append(salida, t)
		}
	}
	return salida
}

// LimpiarHechas borra las tareas hechas y devuelve cuántas borró.
func (l *Lista) LimpiarHechas() int {
	quedan := l.Tareas[:0]
	borradas := 0
	for _, t := range l.Tareas {
		if t.Hecha {
			borradas++
			continue
		}
		quedan = append(quedan, t)
	}
	l.Tareas = quedan
	return borradas
}

// Resumen devuelve un texto como "3 tareas: 1 hecha, 2 pendientes".
func (l *Lista) Resumen() string {
	hechas := 0
	for _, t := range l.Tareas {
		if t.Hecha {
			hechas++
		}
	}
	plural := func(n int, uno, varios string) string {
		if n == 1 {
			return uno
		}
		return varios
	}
	total := len(l.Tareas)
	return fmt.Sprintf("%d %s: %d %s, %d %s", total, plural(total, "tarea", "tareas"),
		hechas, plural(hechas, "hecha", "hechas"), total-hechas, plural(total-hechas, "pendiente", "pendientes"))
}

// Formatear devuelve la línea que muestra la CLI para una tarea.
func Formatear(t Tarea) string {
	marca := " "
	if t.Hecha {
		marca = "x"
	}
	return fmt.Sprintf("[%s] %3d %s %s", marca, t.ID, strings.Repeat("!", t.Prioridad), t.Titulo)
}

// Cargar lee la lista desde disco; si el archivo no existe devuelve una lista vacía.
func Cargar(ruta string) (*Lista, error) {
	datos, err := os.ReadFile(ruta)
	if errors.Is(err, os.ErrNotExist) {
		return Nueva(), nil
	}
	if err != nil {
		return nil, err
	}
	l := Nueva()
	if err := json.Unmarshal(datos, l); err != nil {
		return nil, fmt.Errorf("archivo de tareas dañado (%s): %w", ruta, err)
	}
	maximo := 0
	for _, t := range l.Tareas {
		if t.ID > maximo {
			maximo = t.ID
		}
	}
	if l.Proximo <= maximo {
		l.Proximo = maximo + 1
	}
	return l, nil
}

// Guardar escribe la lista de forma atómica (archivo temporal + rename).
func (l *Lista) Guardar(ruta string) error {
	datos, err := json.MarshalIndent(l, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(ruta), 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(ruta), ".tareas-*.json")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(append(datos, '\n')); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), ruta)
}
''',
        "tareas/tareas_test.go": r'''package tareas

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

var ahora = time.Date(2024, 1, 2, 10, 0, 0, 0, time.UTC)

func listaDeEjemplo(t *testing.T) *Lista {
	t.Helper()
	l := Nueva()
	for _, d := range []struct {
		titulo    string
		prioridad int
	}{{"comprar pan", 1}, {"pagar la luz", 3}, {"llamar a Ana", 2}} {
		if _, err := l.Agregar(d.titulo, d.prioridad, ahora); err != nil {
			t.Fatal(err)
		}
	}
	return l
}

func TestAgregarAsignaIDsYNormaliza(t *testing.T) {
	l := Nueva()
	a, _ := l.Agregar("  comprar   pan ", 9, ahora)
	b, _ := l.Agregar("otra", 0, ahora)
	if a.ID != 1 || b.ID != 2 {
		t.Fatalf("IDs = %d, %d", a.ID, b.ID)
	}
	if a.Titulo != "comprar pan" {
		t.Errorf("título = %q", a.Titulo)
	}
	if a.Prioridad != 3 || b.Prioridad != 1 {
		t.Errorf("prioridades = %d, %d (se limitan a 1..3)", a.Prioridad, b.Prioridad)
	}
}

func TestTituloVacio(t *testing.T) {
	if _, err := Nueva().Agregar("   ", 1, ahora); !errors.Is(err, ErrTituloVacio) {
		t.Fatalf("err = %v", err)
	}
}

func TestPendientesOrdenadasPorPrioridad(t *testing.T) {
	l := listaDeEjemplo(t)
	if err := l.Completar(3); err != nil {
		t.Fatal(err)
	}
	p := l.Pendientes()
	if len(p) != 2 || p[0].Titulo != "pagar la luz" || p[1].Titulo != "comprar pan" {
		t.Fatalf("pendientes = %+v", p)
	}
}

func TestCompletarDosVecesYNoExiste(t *testing.T) {
	l := listaDeEjemplo(t)
	if err := l.Completar(1); err != nil {
		t.Fatal(err)
	}
	if err := l.Completar(1); !errors.Is(err, ErrYaHecha) {
		t.Errorf("segunda vez: %v", err)
	}
	if err := l.Completar(99); !errors.Is(err, ErrNoExiste) {
		t.Errorf("inexistente: %v", err)
	}
}

func TestBorrarNoReutilizaIDs(t *testing.T) {
	l := listaDeEjemplo(t)
	if err := l.Borrar(3); err != nil {
		t.Fatal(err)
	}
	nueva, _ := l.Agregar("cuarta", 1, ahora)
	if nueva.ID != 4 {
		t.Fatalf("ID = %d, se esperaba 4", nueva.ID)
	}
	if err := l.Borrar(3); !errors.Is(err, ErrNoExiste) {
		t.Errorf("borrar dos veces: %v", err)
	}
}

func TestBuscarSinMayusculas(t *testing.T) {
	r := listaDeEjemplo(t).Buscar("ANA")
	if len(r) != 1 || r[0].ID != 3 {
		t.Fatalf("buscar = %+v", r)
	}
}

func TestResumenYLimpiar(t *testing.T) {
	l := listaDeEjemplo(t)
	_ = l.Completar(2)
	if got := l.Resumen(); got != "3 tareas: 1 hecha, 2 pendientes" {
		t.Errorf("resumen = %q", got)
	}
	if n := l.LimpiarHechas(); n != 1 {
		t.Errorf("limpiadas = %d", n)
	}
	if got := l.Resumen(); got != "2 tareas: 0 hechas, 2 pendientes" {
		t.Errorf("resumen = %q", got)
	}
}

func TestFormatear(t *testing.T) {
	got := Formatear(Tarea{ID: 7, Titulo: "x", Prioridad: 2, Hecha: true})
	if got != "[x]   7 !! x" {
		t.Errorf("formatear = %q", got)
	}
}

func TestGuardarYCargar(t *testing.T) {
	ruta := filepath.Join(t.TempDir(), "sub", "tareas.json")
	l := listaDeEjemplo(t)
	_ = l.Completar(1)
	if err := l.Guardar(ruta); err != nil {
		t.Fatal(err)
	}
	c, err := Cargar(ruta)
	if err != nil {
		t.Fatal(err)
	}
	if len(c.Tareas) != 3 || !c.Tareas[0].Hecha || c.Proximo != 4 {
		t.Fatalf("cargada = %+v", c)
	}
}

func TestCargarInexistenteYDaniado(t *testing.T) {
	dir := t.TempDir()
	l, err := Cargar(filepath.Join(dir, "no.json"))
	if err != nil || len(l.Tareas) != 0 {
		t.Fatalf("inexistente: %v %+v", err, l)
	}
	mala := filepath.Join(dir, "mala.json")
	_ = os.WriteFile(mala, []byte("{no es json"), 0o644)
	if _, err := Cargar(mala); err == nil {
		t.Fatal("se esperaba error con JSON dañado")
	}
}

func TestCargarRecalculaProximo(t *testing.T) {
	ruta := filepath.Join(t.TempDir(), "t.json")
	_ = os.WriteFile(ruta, []byte(`{"tareas":[{"id":5,"titulo":"a","prioridad":1}],"proximo":0}`), 0o644)
	l, err := Cargar(ruta)
	if err != nil {
		t.Fatal(err)
	}
	if l.Proximo != 6 {
		t.Fatalf("próximo = %d", l.Proximo)
	}
}
''',
        "main.go": r'''// __TITULO__: lista de tareas desde la terminal.
//
//	go run . agregar "comprar pan" -p 2
//	go run . listar | pendientes | hecha 3 | borrar 3 | buscar pan | limpiar
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"__PROYECTO__/tareas"
)

func rutaDatos() string {
	if r := os.Getenv("TAREAS_ARCHIVO"); r != "" {
		return r
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "tareas.json"
	}
	return filepath.Join(home, ".__PROYECTO__.json")
}

func uso() {
	fmt.Println(`Uso: __PROYECTO__ COMANDO
  agregar TÍTULO [-p 1|2|3]   nueva tarea (prioridad 3 = alta)
  listar                      todas las tareas
  pendientes                  pendientes por prioridad
  hecha ID                    marcar como hecha
  borrar ID                   borrar
  buscar TEXTO                buscar por título
  limpiar                     borrar las hechas`)
}

func id(args []string) (int, error) {
	if len(args) == 0 {
		return 0, fmt.Errorf("falta el ID")
	}
	return strconv.Atoi(args[0])
}

func correr(args []string, ruta string) error {
	if len(args) == 0 {
		uso()
		return nil
	}
	lista, err := tareas.Cargar(ruta)
	if err != nil {
		return err
	}
	comando, resto := args[0], args[1:]
	cambio := false
	switch comando {
	case "agregar":
		prioridad := 1
		var palabras []string
		for i := 0; i < len(resto); i++ {
			if resto[i] == "-p" && i+1 < len(resto) {
				p, err := strconv.Atoi(resto[i+1])
				if err != nil {
					return fmt.Errorf("prioridad inválida: %s", resto[i+1])
				}
				prioridad = p
				i++
				continue
			}
			palabras = append(palabras, resto[i])
		}
		t, err := lista.Agregar(strings.Join(palabras, " "), prioridad, time.Now())
		if err != nil {
			return err
		}
		fmt.Println("agregada:", tareas.Formatear(t))
		cambio = true
	case "listar":
		if len(lista.Tareas) == 0 {
			fmt.Println("(sin tareas)")
		}
		for _, t := range lista.Tareas {
			fmt.Println(tareas.Formatear(t))
		}
		fmt.Println(lista.Resumen())
	case "pendientes":
		for _, t := range lista.Pendientes() {
			fmt.Println(tareas.Formatear(t))
		}
	case "hecha", "borrar":
		n, err := id(resto)
		if err != nil {
			return err
		}
		if comando == "hecha" {
			err = lista.Completar(n)
		} else {
			err = lista.Borrar(n)
		}
		if err != nil {
			return err
		}
		fmt.Println("listo")
		cambio = true
	case "buscar":
		for _, t := range lista.Buscar(strings.Join(resto, " ")) {
			fmt.Println(tareas.Formatear(t))
		}
	case "limpiar":
		fmt.Printf("borradas %d tareas hechas\n", lista.LimpiarHechas())
		cambio = true
	case "ayuda", "-h", "--help":
		uso()
	default:
		uso()
		return fmt.Errorf("comando desconocido: %s", comando)
	}
	if cambio {
		return lista.Guardar(ruta)
	}
	return nil
}

func main() {
	if err := correr(os.Args[1:], rutaDatos()); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
''',
        "main_test.go": r'''package main

import (
	"path/filepath"
	"testing"

	"__PROYECTO__/tareas"
)

func TestCorrerFlujoCompleto(t *testing.T) {
	ruta := filepath.Join(t.TempDir(), "t.json")
	pasos := [][]string{
		{"agregar", "comprar", "pan", "-p", "3"},
		{"agregar", "llamar"},
		{"hecha", "2"},
		{"listar"},
	}
	for _, args := range pasos {
		if err := correr(args, ruta); err != nil {
			t.Fatalf("%v: %v", args, err)
		}
	}
	l, err := tareas.Cargar(ruta)
	if err != nil {
		t.Fatal(err)
	}
	if l.Resumen() != "2 tareas: 1 hecha, 1 pendiente" {
		t.Fatalf("resumen = %q", l.Resumen())
	}
	if l.Tareas[0].Prioridad != 3 || l.Tareas[0].Titulo != "comprar pan" {
		t.Fatalf("primera = %+v", l.Tareas[0])
	}
}

func TestCorrerErrores(t *testing.T) {
	ruta := filepath.Join(t.TempDir(), "t.json")
	for _, args := range [][]string{{"hecha", "9"}, {"borrar"}, {"agregar", "x", "-p", "alta"}, {"volar"}} {
		if err := correr(args, ruta); err == nil {
			t.Errorf("%v: se esperaba error", args)
		}
	}
}
''',
        "README.md": """# __TITULO__

Lista de tareas en Go, sin dependencias.

```bash
go run . agregar "pagar la luz" -p 3
go run . pendientes
go test ./...
go build -o __PROYECTO__ . && ./__PROYECTO__ listar
```

En Termux: `pkg install golang`.
""",
    },
    comando_tests="go test ./...",
    comando_ejecutar="go run . listar",
    etiquetas=("go", "cli", "json"),
    requiere=("go",),
)

# ======================================================================
# go-api
# ======================================================================
registrar_plantilla(
    "go-api",
    "API REST de notas en Go con net/http (sin dependencias): store concurrente, validación y tests httptest.",
    "go",
    {
        "go.mod": "module __PROYECTO__\n\ngo 1.18\n",
        "notas/store.go": r'''// Package notas guarda notas en memoria de forma segura para varias goroutines.
package notas

import (
	"errors"
	"sort"
	"strings"
	"sync"
	"time"
)

// Nota es lo que expone la API.
type Nota struct {
	ID         int       `json:"id"`
	Titulo     string    `json:"titulo"`
	Texto      string    `json:"texto"`
	Etiquetas  []string  `json:"etiquetas"`
	Creada     time.Time `json:"creada"`
	Modificada time.Time `json:"modificada"`
}

// Datos es lo que manda el cliente para crear o modificar.
type Datos struct {
	Titulo    string   `json:"titulo"`
	Texto     string   `json:"texto"`
	Etiquetas []string `json:"etiquetas"`
}

var (
	ErrNoExiste = errors.New("la nota no existe")
	ErrInvalida = errors.New("datos inválidos")
)

// Store es un almacén en memoria con lock.
type Store struct {
	mu      sync.RWMutex
	notas   map[int]Nota
	proximo int
	reloj   func() time.Time
}

// NuevoStore crea un store vacío. reloj puede ser nil (usa time.Now).
func NuevoStore(reloj func() time.Time) *Store {
	if reloj == nil {
		reloj = time.Now
	}
	return &Store{notas: map[int]Nota{}, proximo: 1, reloj: reloj}
}

func normalizar(d Datos) (Datos, error) {
	d.Titulo = strings.TrimSpace(d.Titulo)
	if d.Titulo == "" || len(d.Titulo) > 200 {
		return d, ErrInvalida
	}
	vistas := map[string]bool{}
	etiquetas := []string{}
	for _, e := range d.Etiquetas {
		e = strings.ToLower(strings.TrimSpace(e))
		if e != "" && !vistas[e] {
			vistas[e] = true
			etiquetas = append(etiquetas, e)
		}
	}
	sort.Strings(etiquetas)
	d.Etiquetas = etiquetas
	return d, nil
}

// Crear agrega una nota.
func (s *Store) Crear(d Datos) (Nota, error) {
	d, err := normalizar(d)
	if err != nil {
		return Nota{}, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	ahora := s.reloj()
	n := Nota{ID: s.proximo, Titulo: d.Titulo, Texto: d.Texto, Etiquetas: d.Etiquetas, Creada: ahora, Modificada: ahora}
	s.notas[n.ID] = n
	s.proximo++
	return n, nil
}

// Obtener devuelve una nota por ID.
func (s *Store) Obtener(id int) (Nota, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	n, ok := s.notas[id]
	if !ok {
		return Nota{}, ErrNoExiste
	}
	return n, nil
}

// Actualizar reemplaza título, texto y etiquetas.
func (s *Store) Actualizar(id int, d Datos) (Nota, error) {
	d, err := normalizar(d)
	if err != nil {
		return Nota{}, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	n, ok := s.notas[id]
	if !ok {
		return Nota{}, ErrNoExiste
	}
	n.Titulo, n.Texto, n.Etiquetas, n.Modificada = d.Titulo, d.Texto, d.Etiquetas, s.reloj()
	s.notas[id] = n
	return n, nil
}

// Borrar elimina una nota.
func (s *Store) Borrar(id int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.notas[id]; !ok {
		return ErrNoExiste
	}
	delete(s.notas, id)
	return nil
}

// Listar devuelve las notas ordenadas por ID, filtrando por etiqueta y/o texto (vacíos = todas).
func (s *Store) Listar(etiqueta, texto string) []Nota {
	etiqueta = strings.ToLower(strings.TrimSpace(etiqueta))
	texto = strings.ToLower(strings.TrimSpace(texto))
	s.mu.RLock()
	defer s.mu.RUnlock()
	salida := []Nota{}
	for _, n := range s.notas {
		if etiqueta != "" && !contiene(n.Etiquetas, etiqueta) {
			continue
		}
		if texto != "" && !strings.Contains(strings.ToLower(n.Titulo+" "+n.Texto), texto) {
			continue
		}
		salida = append(salida, n)
	}
	sort.Slice(salida, func(a, b int) bool { return salida[a].ID < salida[b].ID })
	return salida
}

func contiene(lista []string, x string) bool {
	for _, e := range lista {
		if e == x {
			return true
		}
	}
	return false
}
''',
        "api/api.go": r'''// Package api expone el store de notas como API REST JSON.
//
//	GET    /salud
//	GET    /notas?etiqueta=x&q=texto
//	POST   /notas            {"titulo": "...", "texto": "...", "etiquetas": ["..."]}
//	GET    /notas/{id}
//	PUT    /notas/{id}
//	DELETE /notas/{id}
package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"__PROYECTO__/notas"
)

const maxCuerpo = 1 << 20

// Nuevo devuelve el handler HTTP de la API.
func Nuevo(store *notas.Store) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/salud", func(w http.ResponseWriter, r *http.Request) {
		responder(w, http.StatusOK, map[string]string{"estado": "ok"})
	})
	mux.HandleFunc("/notas", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			q := r.URL.Query()
			responder(w, http.StatusOK, store.Listar(q.Get("etiqueta"), q.Get("q")))
		case http.MethodPost:
			var d notas.Datos
			if !leer(w, r, &d) {
				return
			}
			n, err := store.Crear(d)
			if err != nil {
				fallar(w, err)
				return
			}
			w.Header().Set("Location", "/notas/"+strconv.Itoa(n.ID))
			responder(w, http.StatusCreated, n)
		default:
			metodoNoPermitido(w, "GET, POST")
		}
	})
	mux.HandleFunc("/notas/", func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.Atoi(strings.TrimPrefix(r.URL.Path, "/notas/"))
		if err != nil || id < 1 {
			responder(w, http.StatusNotFound, map[string]string{"error": "ruta inexistente"})
			return
		}
		switch r.Method {
		case http.MethodGet:
			n, err := store.Obtener(id)
			if err != nil {
				fallar(w, err)
				return
			}
			responder(w, http.StatusOK, n)
		case http.MethodPut:
			var d notas.Datos
			if !leer(w, r, &d) {
				return
			}
			n, err := store.Actualizar(id, d)
			if err != nil {
				fallar(w, err)
				return
			}
			responder(w, http.StatusOK, n)
		case http.MethodDelete:
			if err := store.Borrar(id); err != nil {
				fallar(w, err)
				return
			}
			w.WriteHeader(http.StatusNoContent)
		default:
			metodoNoPermitido(w, "GET, PUT, DELETE")
		}
	})
	return mux
}

func leer(w http.ResponseWriter, r *http.Request, destino interface{}) bool {
	decodificador := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxCuerpo))
	decodificador.DisallowUnknownFields()
	if err := decodificador.Decode(destino); err != nil {
		responder(w, http.StatusBadRequest, map[string]string{"error": "JSON inválido: " + err.Error()})
		return false
	}
	return true
}

func fallar(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, notas.ErrNoExiste):
		responder(w, http.StatusNotFound, map[string]string{"error": err.Error()})
	case errors.Is(err, notas.ErrInvalida):
		responder(w, http.StatusUnprocessableEntity, map[string]string{"error": "el título es obligatorio (máx. 200 caracteres)"})
	default:
		responder(w, http.StatusInternalServerError, map[string]string{"error": "error interno"})
	}
}

func metodoNoPermitido(w http.ResponseWriter, permitidos string) {
	w.Header().Set("Allow", permitidos)
	responder(w, http.StatusMethodNotAllowed, map[string]string{"error": "método no permitido"})
}

func responder(w http.ResponseWriter, estado int, cuerpo interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(estado)
	_ = json.NewEncoder(w).Encode(cuerpo)
}
''',
        "api/api_test.go": r'''package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"__PROYECTO__/notas"
)

func servidor(t *testing.T) *httptest.Server {
	t.Helper()
	reloj := func() time.Time { return time.Date(2024, 1, 2, 10, 0, 0, 0, time.UTC) }
	s := httptest.NewServer(Nuevo(notas.NuevoStore(reloj)))
	t.Cleanup(s.Close)
	return s
}

func pedir(t *testing.T, s *httptest.Server, metodo, ruta, cuerpo string) (*http.Response, map[string]interface{}) {
	t.Helper()
	req, err := http.NewRequest(metodo, s.URL+ruta, strings.NewReader(cuerpo))
	if err != nil {
		t.Fatal(err)
	}
	r, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Body.Close()
	var datos map[string]interface{}
	if r.StatusCode != http.StatusNoContent {
		_ = json.NewDecoder(r.Body).Decode(&datos)
	}
	return r, datos
}

func TestCrearYObtener(t *testing.T) {
	s := servidor(t)
	r, n := pedir(t, s, "POST", "/notas", `{"titulo":" Compras ","texto":"pan","etiquetas":["Casa","casa","hoy"]}`)
	if r.StatusCode != http.StatusCreated {
		t.Fatalf("estado = %d", r.StatusCode)
	}
	if r.Header.Get("Location") != "/notas/1" {
		t.Errorf("Location = %q", r.Header.Get("Location"))
	}
	if n["titulo"] != "Compras" {
		t.Errorf("titulo = %v", n["titulo"])
	}
	if etiquetas := n["etiquetas"].([]interface{}); len(etiquetas) != 2 || etiquetas[0] != "casa" {
		t.Errorf("etiquetas = %v", etiquetas)
	}
	r, n = pedir(t, s, "GET", "/notas/1", "")
	if r.StatusCode != http.StatusOK || n["texto"] != "pan" {
		t.Fatalf("GET = %d %v", r.StatusCode, n)
	}
}

func TestValidaciones(t *testing.T) {
	s := servidor(t)
	if r, _ := pedir(t, s, "POST", "/notas", `{"titulo":"  "}`); r.StatusCode != http.StatusUnprocessableEntity {
		t.Errorf("título vacío: %d", r.StatusCode)
	}
	if r, _ := pedir(t, s, "POST", "/notas", `{no json`); r.StatusCode != http.StatusBadRequest {
		t.Errorf("JSON roto: %d", r.StatusCode)
	}
	if r, _ := pedir(t, s, "POST", "/notas", `{"titulo":"x","otro":1}`); r.StatusCode != http.StatusBadRequest {
		t.Errorf("campo desconocido: %d", r.StatusCode)
	}
	if r, _ := pedir(t, s, "PATCH", "/notas", ``); r.StatusCode != http.StatusMethodNotAllowed {
		t.Errorf("método: %d", r.StatusCode)
	}
	if r, _ := pedir(t, s, "GET", "/notas/abc", ``); r.StatusCode != http.StatusNotFound {
		t.Errorf("id inválido: %d", r.StatusCode)
	}
}

func TestActualizarBorrarYFiltrar(t *testing.T) {
	s := servidor(t)
	pedir(t, s, "POST", "/notas", `{"titulo":"Compras","etiquetas":["casa"]}`)
	pedir(t, s, "POST", "/notas", `{"titulo":"Trabajo","texto":"informe","etiquetas":["oficina"]}`)
	r, n := pedir(t, s, "PUT", "/notas/1", `{"titulo":"Compras del finde","etiquetas":["casa","finde"]}`)
	if r.StatusCode != http.StatusOK || n["titulo"] != "Compras del finde" {
		t.Fatalf("PUT = %d %v", r.StatusCode, n)
	}
	req, _ := http.NewRequest("GET", s.URL+"/notas?etiqueta=finde", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	var lista []map[string]interface{}
	_ = json.NewDecoder(resp.Body).Decode(&lista)
	resp.Body.Close()
	if len(lista) != 1 || lista[0]["id"].(float64) != 1 {
		t.Fatalf("filtro etiqueta = %v", lista)
	}
	if r, _ := pedir(t, s, "DELETE", "/notas/2", ""); r.StatusCode != http.StatusNoContent {
		t.Fatalf("DELETE = %d", r.StatusCode)
	}
	if r, _ := pedir(t, s, "DELETE", "/notas/2", ""); r.StatusCode != http.StatusNotFound {
		t.Fatalf("DELETE repetido = %d", r.StatusCode)
	}
}

func TestStoreConcurrente(t *testing.T) {
	store := notas.NuevoStore(nil)
	listo := make(chan bool)
	for i := 0; i < 20; i++ {
		go func() {
			_, _ = store.Crear(notas.Datos{Titulo: "x"})
			listo <- true
		}()
	}
	for i := 0; i < 20; i++ {
		<-listo
	}
	if n := len(store.Listar("", "")); n != 20 {
		t.Fatalf("notas = %d", n)
	}
}
''',
        "main.go": r'''// __TITULO__: API REST de notas. PORT elige el puerto (por defecto 8080).
package main

import (
	"log"
	"net/http"
	"os"
	"time"

	"__PROYECTO__/api"
	"__PROYECTO__/notas"
)

func main() {
	puerto := os.Getenv("PORT")
	if puerto == "" {
		puerto = "8080"
	}
	servidor := &http.Server{
		Addr:              "127.0.0.1:" + puerto,
		Handler:           api.Nuevo(notas.NuevoStore(nil)),
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("API de notas en http://%s/notas (Ctrl+C para salir)", servidor.Addr)
	log.Fatal(servidor.ListenAndServe())
}
''',
        "README.md": """# __TITULO__

API REST de notas en Go (solo librería estándar).

```bash
go run .                                   # http://127.0.0.1:8080
curl -X POST localhost:8080/notas -d '{"titulo":"Compras","etiquetas":["casa"]}'
curl 'localhost:8080/notas?etiqueta=casa'
go test ./...
```
""",
    },
    comando_tests="go test ./...",
    comando_ejecutar="go run .",
    etiquetas=("go", "api", "http", "rest"),
    requiere=("go",),
)

# ======================================================================
# rust-inventario
# ======================================================================
registrar_plantilla(
    "rust-inventario",
    "Inventario en Rust sin crates: productos, stock, CSV y un REPL interactivo (se prueba por stdin).",
    "rust",
    {
        "Cargo.toml": """[package]
name = "__PROYECTO__"
version = "0.1.0"
edition = "2021"

[dependencies]
""",
        "src/lib.rs": r'''//! Inventario de productos con stock y precio, importable/exportable como CSV.

use std::collections::BTreeMap;
use std::fmt;

/// Un producto del inventario. El precio se guarda en centavos para no perder precisión.
#[derive(Debug, Clone, PartialEq)]
pub struct Producto {
    pub nombre: String,
    pub cantidad: u32,
    pub precio_centavos: u64,
}

impl Producto {
    pub fn valor(&self) -> u64 {
        self.cantidad as u64 * self.precio_centavos
    }
}

/// Errores posibles de las operaciones.
#[derive(Debug, PartialEq)]
pub enum Error {
    NombreVacio,
    NoExiste(String),
    StockInsuficiente { nombre: String, hay: u32, pedido: u32 },
    PrecioInvalido(String),
    LineaInvalida(usize, String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Error::NombreVacio => write!(f, "el nombre no puede estar vacío"),
            Error::NoExiste(n) => write!(f, "no existe el producto '{}'", n),
            Error::StockInsuficiente { nombre, hay, pedido } => {
                write!(f, "stock insuficiente de '{}': hay {}, pediste {}", nombre, hay, pedido)
            }
            Error::PrecioInvalido(p) => write!(f, "precio inválido: '{}'", p),
            Error::LineaInvalida(n, l) => write!(f, "línea {} inválida: '{}'", n, l),
        }
    }
}

impl std::error::Error for Error {}

/// Convierte "12.5", "12,50" o "3" en centavos.
pub fn parsear_precio(texto: &str) -> Result<u64, Error> {
    let t = texto.trim().replace(',', ".");
    let invalido = || Error::PrecioInvalido(texto.to_string());
    if t.is_empty() || t.starts_with('-') {
        return Err(invalido());
    }
    let mut partes = t.splitn(2, '.');
    let enteros: u64 = partes.next().unwrap_or("").parse().map_err(|_| invalido())?;
    let centavos = match partes.next() {
        None => 0,
        Some(dec) if dec.is_empty() || dec.len() > 2 || !dec.chars().all(|c| c.is_ascii_digit()) => {
            return Err(invalido())
        }
        Some(dec) if dec.len() == 1 => dec.parse::<u64>().map_err(|_| invalido())? * 10,
        Some(dec) => dec.parse::<u64>().map_err(|_| invalido())?,
    };
    Ok(enteros * 100 + centavos)
}

/// Formatea centavos como "$12.50".
pub fn formatear_precio(centavos: u64) -> String {
    format!("${}.{:02}", centavos / 100, centavos % 100)
}

fn normalizar(nombre: &str) -> Result<String, Error> {
    let n = nombre.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase();
    if n.is_empty() {
        Err(Error::NombreVacio)
    } else {
        Ok(n)
    }
}

#[derive(Debug, Default)]
pub struct Inventario {
    productos: BTreeMap<String, Producto>,
}

impl Inventario {
    pub fn new() -> Self {
        Self::default()
    }

    /// Agrega stock. Si el producto ya existe suma la cantidad y actualiza el precio.
    pub fn agregar(&mut self, nombre: &str, cantidad: u32, precio_centavos: u64) -> Result<&Producto, Error> {
        let clave = normalizar(nombre)?;
        let p = self.productos.entry(clave.clone()).or_insert(Producto {
            nombre: clave,
            cantidad: 0,
            precio_centavos,
        });
        p.cantidad += cantidad;
        p.precio_centavos = precio_centavos;
        Ok(p)
    }

    /// Saca stock (ventas, roturas...). Falla si no alcanza.
    pub fn quitar(&mut self, nombre: &str, cantidad: u32) -> Result<u32, Error> {
        let clave = normalizar(nombre)?;
        let p = self.productos.get_mut(&clave).ok_or_else(|| Error::NoExiste(clave.clone()))?;
        if p.cantidad < cantidad {
            return Err(Error::StockInsuficiente { nombre: clave, hay: p.cantidad, pedido: cantidad });
        }
        p.cantidad -= cantidad;
        Ok(p.cantidad)
    }

    pub fn eliminar(&mut self, nombre: &str) -> Result<Producto, Error> {
        let clave = normalizar(nombre)?;
        self.productos.remove(&clave).ok_or(Error::NoExiste(clave))
    }

    pub fn obtener(&self, nombre: &str) -> Option<&Producto> {
        normalizar(nombre).ok().and_then(|c| self.productos.get(&c))
    }

    pub fn productos(&self) -> impl Iterator<Item = &Producto> {
        self.productos.values()
    }

    pub fn len(&self) -> usize {
        self.productos.len()
    }

    pub fn is_empty(&self) -> bool {
        self.productos.is_empty()
    }

    pub fn valor_total(&self) -> u64 {
        self.productos.values().map(Producto::valor).sum()
    }

    /// Productos con cantidad menor o igual al umbral, de menor a mayor stock.
    pub fn bajo_stock(&self, umbral: u32) -> Vec<&Producto> {
        let mut v: Vec<&Producto> = self.productos.values().filter(|p| p.cantidad <= umbral).collect();
        v.sort_by(|a, b| a.cantidad.cmp(&b.cantidad).then(a.nombre.cmp(&b.nombre)));
        v
    }

    /// CSV con cabecera: nombre;cantidad;precio
    pub fn a_csv(&self) -> String {
        let mut salida = String::from("nombre;cantidad;precio\n");
        for p in self.productos.values() {
            salida.push_str(&format!("{};{};{}.{:02}\n", p.nombre, p.cantidad, p.precio_centavos / 100, p.precio_centavos % 100));
        }
        salida
    }

    /// Lee el formato de `a_csv` (ignora líneas vacías y la cabecera).
    pub fn desde_csv(texto: &str) -> Result<Self, Error> {
        let mut inv = Inventario::new();
        for (i, linea) in texto.lines().enumerate() {
            let linea = linea.trim();
            if linea.is_empty() || (i == 0 && linea.starts_with("nombre;")) {
                continue;
            }
            let campos: Vec<&str> = linea.split(';').collect();
            if campos.len() != 3 {
                return Err(Error::LineaInvalida(i + 1, linea.to_string()));
            }
            let cantidad: u32 = campos[1].trim().parse().map_err(|_| Error::LineaInvalida(i + 1, linea.to_string()))?;
            let precio = parsear_precio(campos[2])?;
            inv.agregar(campos[0], cantidad, precio)?;
        }
        Ok(inv)
    }
}

/// Ejecuta un comando del REPL y devuelve el texto a mostrar (o None para salir).
pub fn ejecutar_comando(inv: &mut Inventario, linea: &str) -> Option<String> {
    let partes: Vec<&str> = linea.split_whitespace().collect();
    let respuesta = match partes.as_slice() {
        [] => String::new(),
        ["salir"] | ["exit"] | ["q"] => return None,
        ["ayuda"] => "comandos: agregar NOMBRE CANTIDAD PRECIO | quitar NOMBRE CANTIDAD | eliminar NOMBRE | \
                      listar | bajo UMBRAL | total | salir"
            .to_string(),
        ["agregar", nombre, cantidad, precio] => match (cantidad.parse::<u32>(), parsear_precio(precio)) {
            (Ok(c), Ok(p)) => match inv.agregar(nombre, c, p) {
                Ok(prod) => format!("{}: {} u. a {}", prod.nombre, prod.cantidad, formatear_precio(prod.precio_centavos)),
                Err(e) => format!("error: {}", e),
            },
            (Err(_), _) => format!("error: cantidad inválida '{}'", cantidad),
            (_, Err(e)) => format!("error: {}", e),
        },
        ["quitar", nombre, cantidad] => match cantidad.parse::<u32>() {
            Ok(c) => match inv.quitar(nombre, c) {
                Ok(queda) => format!("quedan {}", queda),
                Err(e) => format!("error: {}", e),
            },
            Err(_) => format!("error: cantidad inválida '{}'", cantidad),
        },
        ["eliminar", nombre] => match inv.eliminar(nombre) {
            Ok(p) => format!("eliminado {}", p.nombre),
            Err(e) => format!("error: {}", e),
        },
        ["listar"] => {
            if inv.is_empty() {
                "(inventario vacío)".to_string()
            } else {
                inv.productos()
                    .map(|p| format!("{:<20} {:>5} u. {:>10}", p.nombre, p.cantidad, formatear_precio(p.precio_centavos)))
                    .collect::<Vec<_>>()
                    .join("\n")
            }
        }
        ["bajo", umbral] => match umbral.parse::<u32>() {
            Ok(u) => {
                let v = inv.bajo_stock(u);
                if v.is_empty() {
                    "nada con stock bajo".to_string()
                } else {
                    v.iter().map(|p| format!("{} ({})", p.nombre, p.cantidad)).collect::<Vec<_>>().join(", ")
                }
            }
            Err(_) => format!("error: umbral inválido '{}'", umbral),
        },
        ["total"] => format!("valor total: {}", formatear_precio(inv.valor_total())),
        _ => "comando no reconocido (escribí 'ayuda')".to_string(),
    };
    Some(respuesta)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ejemplo() -> Inventario {
        let mut inv = Inventario::new();
        inv.agregar("Pan", 10, 150).unwrap();
        inv.agregar("leche", 2, 999).unwrap();
        inv.agregar("  Yerba  Mate ", 0, 2500).unwrap();
        inv
    }

    #[test]
    fn precios() {
        assert_eq!(parsear_precio("12.5"), Ok(1250));
        assert_eq!(parsear_precio("12,05"), Ok(1205));
        assert_eq!(parsear_precio("3"), Ok(300));
        assert!(parsear_precio("-1").is_err());
        assert!(parsear_precio("1.234").is_err());
        assert!(parsear_precio("abc").is_err());
        assert_eq!(formatear_precio(1205), "$12.05");
    }

    #[test]
    fn agregar_suma_y_normaliza() {
        let mut inv = ejemplo();
        inv.agregar("PAN", 5, 200).unwrap();
        let pan = inv.obtener("pan").unwrap();
        assert_eq!(pan.cantidad, 15);
        assert_eq!(pan.precio_centavos, 200);
        assert!(inv.obtener("yerba mate").is_some());
        assert_eq!(inv.agregar("   ", 1, 1).unwrap_err(), Error::NombreVacio);
    }

    #[test]
    fn quitar_y_errores() {
        let mut inv = ejemplo();
        assert_eq!(inv.quitar("pan", 4), Ok(6));
        assert_eq!(
            inv.quitar("leche", 5),
            Err(Error::StockInsuficiente { nombre: "leche".into(), hay: 2, pedido: 5 })
        );
        assert_eq!(inv.quitar("arroz", 1), Err(Error::NoExiste("arroz".into())));
    }

    #[test]
    fn valor_y_bajo_stock() {
        let inv = ejemplo();
        assert_eq!(inv.valor_total(), 10 * 150 + 2 * 999);
        let bajos: Vec<&str> = inv.bajo_stock(2).iter().map(|p| p.nombre.as_str()).collect();
        assert_eq!(bajos, vec!["yerba mate", "leche"]);
    }

    #[test]
    fn csv_ida_y_vuelta() {
        let inv = ejemplo();
        let csv = inv.a_csv();
        assert!(csv.starts_with("nombre;cantidad;precio\n"));
        let otra = Inventario::desde_csv(&csv).unwrap();
        assert_eq!(otra.len(), 3);
        assert_eq!(otra.valor_total(), inv.valor_total());
        assert!(matches!(Inventario::desde_csv("nombre;cantidad;precio\npan;x;1"), Err(Error::LineaInvalida(2, _))));
    }

    #[test]
    fn repl() {
        let mut inv = Inventario::new();
        assert_eq!(ejecutar_comando(&mut inv, "agregar pan 3 1.5").unwrap(), "pan: 3 u. a $1.50");
        assert_eq!(ejecutar_comando(&mut inv, "quitar pan 1").unwrap(), "quedan 2");
        assert_eq!(ejecutar_comando(&mut inv, "total").unwrap(), "valor total: $3.00");
        assert!(ejecutar_comando(&mut inv, "quitar pan 9").unwrap().starts_with("error: stock insuficiente"));
        assert!(ejecutar_comando(&mut inv, "volar").unwrap().contains("ayuda"));
        assert_eq!(ejecutar_comando(&mut inv, "salir"), None);
    }
}
''',
        "src/main.rs": r'''//! REPL de inventario: lee comandos de stdin (escribí "ayuda"). Guarda en inventario.csv al salir.
//! Probar sin teclado:  printf 'agregar pan 3 1.5\nlistar\nsalir\n' | cargo run -q

use std::fs;
use std::io::{self, BufRead, Write};

use __PROYECTO__::{ejecutar_comando, Inventario};

const ARCHIVO: &str = "inventario.csv";

fn main() {
    let mut inv = match fs::read_to_string(ARCHIVO) {
        Ok(texto) => Inventario::desde_csv(&texto).unwrap_or_else(|e| {
            eprintln!("aviso: {} ({}); empiezo vacío", e, ARCHIVO);
            Inventario::new()
        }),
        Err(_) => Inventario::new(),
    };
    println!("Inventario ({} productos). Escribí 'ayuda'.", inv.len());
    let stdin = io::stdin();
    loop {
        print!("> ");
        let _ = io::stdout().flush();
        let mut linea = String::new();
        match stdin.lock().read_line(&mut linea) {
            Ok(0) => break, // fin de la entrada (Ctrl+D o stdin agotado): se sale guardando
            Ok(_) => {}
            Err(e) => {
                eprintln!("error leyendo: {}", e);
                break;
            }
        }
        match ejecutar_comando(&mut inv, linea.trim()) {
            Some(respuesta) if !respuesta.is_empty() => println!("{}", respuesta),
            Some(_) => {}
            None => break,
        }
    }
    if let Err(e) = fs::write(ARCHIVO, inv.a_csv()) {
        eprintln!("no pude guardar {}: {}", ARCHIVO, e);
        std::process::exit(1);
    }
    println!("guardado en {}", ARCHIVO);
}
''',
        "tests/repl_stdin.rs": r'''// Prueba el binario real como lo usaría una persona, pasándole la entrada por stdin.
use std::io::Write;
use std::process::{Command, Stdio};

#[test]
fn sesion_por_stdin() {
    let dir = std::env::temp_dir().join(format!("inv_test_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let mut hijo = Command::new(env!("CARGO_BIN_EXE___PROYECTO__"))
        .current_dir(&dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("no se pudo lanzar el binario");
    hijo.stdin.as_mut().unwrap().write_all(b"agregar pan 3 1.5\nlistar\ntotal\nsalir\n").unwrap();
    let salida = hijo.wait_with_output().unwrap();
    let texto = String::from_utf8_lossy(&salida.stdout);
    assert!(salida.status.success());
    assert!(texto.contains("pan: 3 u. a $1.50"), "{}", texto);
    assert!(texto.contains("valor total: $4.50"), "{}", texto);
    let csv = std::fs::read_to_string(dir.join("inventario.csv")).unwrap();
    assert!(csv.contains("pan;3;1.50"));
    let _ = std::fs::remove_dir_all(&dir);
}
''',
        "README.md": """# __TITULO__

Inventario en Rust sin dependencias, con REPL interactivo.

```bash
cargo run                                            # escribí 'ayuda'
printf 'agregar pan 3 1.5\\nlistar\\nsalir\\n' | cargo run -q   # sin teclado
cargo test
```

En Termux: `pkg install rust`.
""",
    },
    comando_tests="cargo test --offline -q",
    comando_ejecutar="cargo run",
    etiquetas=("rust", "cli", "csv", "repl"),
    requiere=("cargo",),
)

# ======================================================================
# c-rpn
# ======================================================================
registrar_plantilla(
    "c-rpn",
    "Calculadora RPN en C99: pila, evaluador con mensajes de error, REPL por stdin, Makefile y tests TAP.",
    "c",
    {
        "Makefile": (
            "CC ?= cc\n"
            "CFLAGS ?= -std=c99 -Wall -Wextra -Wpedantic -O2\n"
            "LDLIBS = -lm\n"
            "SRC = src/pila.c src/rpn.c\n"
            "CABECERAS = src/pila.h src/rpn.h\n"
            "\n"
            "all: calc\n"
            "\n"
            "calc: $(SRC) src/main.c $(CABECERAS)\n"
            "\t$(CC) $(CFLAGS) -o calc $(SRC) src/main.c $(LDLIBS)\n"
            "\n"
            "tests/test_rpn: $(SRC) tests/test_rpn.c $(CABECERAS)\n"
            "\t$(CC) $(CFLAGS) -Isrc -o tests/test_rpn $(SRC) tests/test_rpn.c $(LDLIBS)\n"
            "\n"
            "test: tests/test_rpn calc\n"
            "\t./tests/test_rpn\n"
            "\tprintf '3 4 +\\n2 0 /\\nsalir\\n' | ./calc | grep -q '= 7'\n"
            "\n"
            "clean:\n"
            "\trm -f calc tests/test_rpn\n"
            "\n"
            ".PHONY: all test clean\n"
        ),
        "src/pila.h": r'''#ifndef PILA_H
#define PILA_H

#include <stddef.h>

#define PILA_CAPACIDAD 64

typedef enum {
    PILA_OK = 0,
    PILA_LLENA,
    PILA_VACIA
} pila_estado;

typedef struct {
    double datos[PILA_CAPACIDAD];
    size_t tope;
} pila;

void pila_iniciar(pila *p);
pila_estado pila_apilar(pila *p, double valor);
pila_estado pila_desapilar(pila *p, double *valor);
pila_estado pila_ver(const pila *p, double *valor);
size_t pila_tamano(const pila *p);

#endif
''',
        "src/pila.c": r'''#include "pila.h"

void pila_iniciar(pila *p) {
    p->tope = 0;
}

pila_estado pila_apilar(pila *p, double valor) {
    if (p->tope >= PILA_CAPACIDAD) {
        return PILA_LLENA;
    }
    p->datos[p->tope++] = valor;
    return PILA_OK;
}

pila_estado pila_desapilar(pila *p, double *valor) {
    if (p->tope == 0) {
        return PILA_VACIA;
    }
    *valor = p->datos[--p->tope];
    return PILA_OK;
}

pila_estado pila_ver(const pila *p, double *valor) {
    if (p->tope == 0) {
        return PILA_VACIA;
    }
    *valor = p->datos[p->tope - 1];
    return PILA_OK;
}

size_t pila_tamano(const pila *p) {
    return p->tope;
}
''',
        "src/rpn.h": r'''#ifndef RPN_H
#define RPN_H

#include <stddef.h>

/*
 * Evalúa una expresión en notación polaca inversa, p. ej. "3 4 + 2 *" -> 14.
 * Operadores: + - * / ^ %   funciones: sqrt neg abs   constantes: pi e
 * Devuelve 0 si salió bien (y deja el valor en *resultado) o -1 con un mensaje en error.
 */
int rpn_evaluar(const char *expresion, double *resultado, char *error, size_t tam_error);

#endif
''',
        "src/rpn.c": r'''#include "rpn.h"

#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pila.h"

#define MAX_TOKEN 64

static int fallar(char *error, size_t tam, const char *mensaje, const char *token) {
    if (error && tam) {
        if (token) {
            snprintf(error, tam, "%s: '%s'", mensaje, token);
        } else {
            snprintf(error, tam, "%s", mensaje);
        }
    }
    return -1;
}

static int es_numero(const char *token, double *valor) {
    char *fin = NULL;
    errno = 0;
    *valor = strtod(token, &fin);
    return fin != token && *fin == '\0' && errno == 0;
}

static int aplicar_binario(pila *p, char op, char *error, size_t tam, const char *token) {
    double a, b;
    if (pila_desapilar(p, &b) != PILA_OK || pila_desapilar(p, &a) != PILA_OK) {
        return fallar(error, tam, "faltan operandos para", token);
    }
    double r;
    switch (op) {
        case '+': r = a + b; break;
        case '-': r = a - b; break;
        case '*': r = a * b; break;
        case '/':
            if (b == 0.0) {
                return fallar(error, tam, "división por cero", NULL);
            }
            r = a / b;
            break;
        case '%':
            if (b == 0.0) {
                return fallar(error, tam, "módulo por cero", NULL);
            }
            r = fmod(a, b);
            break;
        case '^': r = pow(a, b); break;
        default: return fallar(error, tam, "operador desconocido", token);
    }
    if (pila_apilar(p, r) != PILA_OK) {
        return fallar(error, tam, "pila llena", NULL);
    }
    return 0;
}

static int aplicar_funcion(pila *p, const char *nombre, char *error, size_t tam) {
    double a;
    if (pila_desapilar(p, &a) != PILA_OK) {
        return fallar(error, tam, "falta el operando para", nombre);
    }
    double r;
    if (strcmp(nombre, "sqrt") == 0) {
        if (a < 0) {
            return fallar(error, tam, "raíz de número negativo", NULL);
        }
        r = sqrt(a);
    } else if (strcmp(nombre, "neg") == 0) {
        r = -a;
    } else if (strcmp(nombre, "abs") == 0) {
        r = fabs(a);
    } else {
        return fallar(error, tam, "función desconocida", nombre);
    }
    pila_apilar(p, r);
    return 0;
}

int rpn_evaluar(const char *expresion, double *resultado, char *error, size_t tam_error) {
    pila p;
    pila_iniciar(&p);
    if (error && tam_error) {
        error[0] = '\0';
    }
    const char *c = expresion ? expresion : "";
    char token[MAX_TOKEN];
    int tokens = 0;
    while (*c) {
        while (*c && isspace((unsigned char)*c)) {
            c++;
        }
        if (!*c) {
            break;
        }
        size_t n = 0;
        while (c[n] && !isspace((unsigned char)c[n])) {
            n++;
        }
        if (n >= MAX_TOKEN) {
            return fallar(error, tam_error, "token demasiado largo", NULL);
        }
        memcpy(token, c, n);
        token[n] = '\0';
        c += n;
        tokens++;

        double valor;
        if (es_numero(token, &valor)) {
            if (pila_apilar(&p, valor) != PILA_OK) {
                return fallar(error, tam_error, "pila llena", NULL);
            }
        } else if (strcmp(token, "pi") == 0) {
            pila_apilar(&p, 3.14159265358979323846);
        } else if (strcmp(token, "e") == 0) {
            pila_apilar(&p, 2.71828182845904523536);
        } else if (strlen(token) == 1 && strchr("+-*/^%", token[0])) {
            if (aplicar_binario(&p, token[0], error, tam_error, token) != 0) {
                return -1;
            }
        } else if (isalpha((unsigned char)token[0])) {
            if (aplicar_funcion(&p, token, error, tam_error) != 0) {
                return -1;
            }
        } else {
            return fallar(error, tam_error, "token inválido", token);
        }
    }
    if (tokens == 0) {
        return fallar(error, tam_error, "expresión vacía", NULL);
    }
    if (pila_tamano(&p) != 1) {
        return fallar(error, tam_error, "sobran operandos (faltan operadores)", NULL);
    }
    pila_desapilar(&p, resultado);
    return 0;
}
''',
        "src/main.c": r'''/*
 * __TITULO__: calculadora RPN.
 *   ./calc "3 4 + 2 *"          evalúa una expresión
 *   ./calc                      modo interactivo (una expresión por línea, "salir" para terminar)
 *   printf '3 4 +\nsalir\n' | ./calc   (así se prueba sin teclado)
 */
#include <stdio.h>
#include <string.h>

#include "rpn.h"

static int evaluar_e_imprimir(const char *linea) {
    double r;
    char error[128];
    if (rpn_evaluar(linea, &r, error, sizeof error) == 0) {
        printf("= %.10g\n", r);
        return 0;
    }
    printf("error: %s\n", error);
    return 1;
}

int main(int argc, char **argv) {
    if (argc > 1) {
        char expresion[1024] = "";
        for (int i = 1; i < argc; i++) {
            strncat(expresion, argv[i], sizeof expresion - strlen(expresion) - 2);
            strncat(expresion, " ", sizeof expresion - strlen(expresion) - 1);
        }
        return evaluar_e_imprimir(expresion);
    }
    char linea[1024];
    printf("Calculadora RPN (ej: 3 4 + 2 *). 'salir' para terminar.\n");
    while (1) {
        printf("> ");
        fflush(stdout);
        if (!fgets(linea, sizeof linea, stdin)) {
            printf("\n");
            break; /* fin de la entrada */
        }
        linea[strcspn(linea, "\r\n")] = '\0';
        if (strcmp(linea, "salir") == 0 || strcmp(linea, "q") == 0) {
            break;
        }
        if (linea[0] == '\0') {
            continue;
        }
        evaluar_e_imprimir(linea);
    }
    return 0;
}
''',
        "tests/test_rpn.c": r'''/* Tests de la calculadora RPN con salida TAP. Ejecutar: make test */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "pila.h"
#include "rpn.h"

static int total = 0, fallas = 0;

static void verificar(int condicion, const char *nombre) {
    total++;
    if (condicion) {
        printf("ok %d - %s\n", total, nombre);
    } else {
        printf("not ok %d - %s\n", total, nombre);
        fallas++;
    }
}

static void resultado(const char *expr, double esperado) {
    double r = 0;
    char error[128];
    int ok = rpn_evaluar(expr, &r, error, sizeof error) == 0 && fabs(r - esperado) < 1e-9;
    char nombre[160];
    snprintf(nombre, sizeof nombre, "'%s' = %g", expr, esperado);
    verificar(ok, nombre);
    if (!ok) {
        printf("#   obtenido: %g (%s)\n", r, error);
    }
}

static void error_con(const char *expr, const char *fragmento) {
    double r;
    char error[128] = "";
    int ok = rpn_evaluar(expr, &r, error, sizeof error) == -1 && strstr(error, fragmento) != NULL;
    char nombre[160];
    snprintf(nombre, sizeof nombre, "'%s' da error con '%s'", expr, fragmento);
    verificar(ok, nombre);
    if (!ok) {
        printf("#   mensaje: %s\n", error);
    }
}

int main(void) {
    pila p;
    double v;
    pila_iniciar(&p);
    verificar(pila_desapilar(&p, &v) == PILA_VACIA, "pila vacía");
    for (int i = 0; i < PILA_CAPACIDAD; i++) {
        pila_apilar(&p, i);
    }
    verificar(pila_apilar(&p, 1) == PILA_LLENA, "pila llena");
    verificar(pila_ver(&p, &v) == PILA_OK && v == PILA_CAPACIDAD - 1, "ver el tope");

    resultado("3 4 +", 7);
    resultado("5 1 2 + 4 * + 3 -", 14);
    resultado("2 3 ^", 8);
    resultado("10 3 %", 1);
    resultado("-2.5 neg", 2.5);
    resultado("16 sqrt", 4);
    resultado("pi 2 *", 6.283185307179586);
    resultado("  7   ", 7);

    error_con("2 0 /", "división por cero");
    error_con("1 +", "faltan operandos");
    error_con("1 2", "sobran operandos");
    error_con("", "vacía");
    error_con("2 hola", "función desconocida");
    error_con("-4 sqrt", "negativo");
    error_con("3 #", "token inválido");

    printf("1..%d\n# tests %d\n# pass %d\n# fail %d\n", total, total, total - fallas, fallas);
    return fallas ? 1 : 0;
}
''',
        "README.md": """# __TITULO__

Calculadora RPN en C99.

```bash
make                 # compila ./calc
./calc "3 4 + 2 *"   # = 14
./calc               # modo interactivo
make test            # tests TAP + prueba del REPL por stdin
```

En Termux: `pkg install clang make`.
""",
    },
    comando_tests="make test",
    comando_ejecutar="make && ./calc",
    etiquetas=("c", "cli", "makefile", "repl"),
    requiere=("make",),
)

# ======================================================================
# java-banco
# ======================================================================
registrar_plantilla(
    "java-banco",
    "Cuentas, depósitos, extracciones y transferencias en Java (sin Maven ni JUnit): runner de tests propio.",
    "java",
    {
        "src/Cuenta.java": r'''import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Cuenta bancaria. Los montos se manejan en centavos (long) para no perder precisión. */
public class Cuenta {
    private final String numero;
    private final String titular;
    private long saldoCentavos;
    private final List<String> movimientos = new ArrayList<>();

    public Cuenta(String numero, String titular) {
        if (numero == null || numero.trim().isEmpty()) {
            throw new IllegalArgumentException("el número de cuenta es obligatorio");
        }
        if (titular == null || titular.trim().isEmpty()) {
            throw new IllegalArgumentException("el titular es obligatorio");
        }
        this.numero = numero.trim();
        this.titular = titular.trim();
    }

    public String getNumero() { return numero; }
    public String getTitular() { return titular; }
    public long getSaldoCentavos() { return saldoCentavos; }
    public List<String> getMovimientos() { return Collections.unmodifiableList(movimientos); }

    public void depositar(long centavos) {
        if (centavos <= 0) {
            throw new IllegalArgumentException("el monto debe ser positivo");
        }
        saldoCentavos += centavos;
        movimientos.add("depósito " + Dinero.formatear(centavos));
    }

    public void extraer(long centavos) {
        if (centavos <= 0) {
            throw new IllegalArgumentException("el monto debe ser positivo");
        }
        if (centavos > saldoCentavos) {
            throw new SaldoInsuficienteException(numero, saldoCentavos, centavos);
        }
        saldoCentavos -= centavos;
        movimientos.add("extracción " + Dinero.formatear(centavos));
    }

    void registrar(String movimiento) {
        movimientos.add(movimiento);
    }

    @Override
    public String toString() {
        return numero + " (" + titular + "): " + Dinero.formatear(saldoCentavos);
    }
}
''',
        "src/SaldoInsuficienteException.java": r'''public class SaldoInsuficienteException extends RuntimeException {
    public SaldoInsuficienteException(String cuenta, long saldo, long pedido) {
        super("saldo insuficiente en " + cuenta + ": hay " + Dinero.formatear(saldo)
              + ", se pidió " + Dinero.formatear(pedido));
    }
}
''',
        "src/Dinero.java": r'''/** Conversión entre texto ("12,50" / "12.5") y centavos. */
public final class Dinero {
    private Dinero() {}

    public static long parsear(String texto) {
        if (texto == null) {
            throw new IllegalArgumentException("monto vacío");
        }
        String t = texto.trim().replace(',', '.').replace("$", "");
        if (!t.matches("\\d+(\\.\\d{1,2})?")) {
            throw new IllegalArgumentException("monto inválido: " + texto);
        }
        String[] partes = t.split("\\.");
        long enteros = Long.parseLong(partes[0]);
        long centavos = 0;
        if (partes.length == 2) {
            String dec = partes[1].length() == 1 ? partes[1] + "0" : partes[1];
            centavos = Long.parseLong(dec);
        }
        return enteros * 100 + centavos;
    }

    public static String formatear(long centavos) {
        String signo = centavos < 0 ? "-" : "";
        long abs = Math.abs(centavos);
        return String.format("%s$%d.%02d", signo, abs / 100, abs % 100);
    }
}
''',
        "src/Banco.java": r'''import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Conjunto de cuentas con transferencias atómicas (o se hace todo o nada). */
public class Banco {
    private final Map<String, Cuenta> cuentas = new LinkedHashMap<>();

    public Cuenta abrir(String numero, String titular) {
        if (cuentas.containsKey(numero)) {
            throw new IllegalArgumentException("ya existe la cuenta " + numero);
        }
        Cuenta c = new Cuenta(numero, titular);
        cuentas.put(c.getNumero(), c);
        return c;
    }

    public Cuenta buscar(String numero) {
        Cuenta c = cuentas.get(numero);
        if (c == null) {
            throw new IllegalArgumentException("no existe la cuenta " + numero);
        }
        return c;
    }

    public void transferir(String origen, String destino, long centavos) {
        if (origen.equals(destino)) {
            throw new IllegalArgumentException("origen y destino son la misma cuenta");
        }
        Cuenta a = buscar(origen);
        Cuenta b = buscar(destino);
        a.extraer(centavos); // si falla, no se tocó nada
        b.depositar(centavos);
        a.registrar("transferencia enviada a " + destino);
        b.registrar("transferencia recibida de " + origen);
    }

    public long totalCentavos() {
        long total = 0;
        for (Cuenta c : cuentas.values()) {
            total += c.getSaldoCentavos();
        }
        return total;
    }

    public List<Cuenta> listar() {
        return new ArrayList<>(cuentas.values());
    }
}
''',
        "src/Main.java": r'''import java.util.Scanner;

/**
 * Menú interactivo. Se prueba sin teclado pasando la entrada por stdin:
 *   printf 'abrir 1 Ana\ndepositar 1 100\nlistar\nsalir\n' | java -cp build Main
 */
public class Main {
    public static String ejecutar(Banco banco, String linea) {
        String[] p = linea.trim().split("\\s+");
        try {
            switch (p[0]) {
                case "abrir":
                    return "abierta " + banco.abrir(p[1], p[2]);
                case "depositar":
                    banco.buscar(p[1]).depositar(Dinero.parsear(p[2]));
                    return banco.buscar(p[1]).toString();
                case "extraer":
                    banco.buscar(p[1]).extraer(Dinero.parsear(p[2]));
                    return banco.buscar(p[1]).toString();
                case "transferir":
                    banco.transferir(p[1], p[2], Dinero.parsear(p[3]));
                    return "listo";
                case "listar":
                    StringBuilder sb = new StringBuilder();
                    for (Cuenta c : banco.listar()) {
                        sb.append(c).append('\n');
                    }
                    sb.append("total: ").append(Dinero.formatear(banco.totalCentavos()));
                    return sb.toString();
                case "ayuda":
                    return "abrir NUM TITULAR | depositar NUM MONTO | extraer NUM MONTO | "
                         + "transferir DESDE HACIA MONTO | listar | salir";
                default:
                    return "comando desconocido (escribí 'ayuda')";
            }
        } catch (ArrayIndexOutOfBoundsException e) {
            return "error: faltan datos (escribí 'ayuda')";
        } catch (IllegalArgumentException | SaldoInsuficienteException e) {
            return "error: " + e.getMessage();
        }
    }

    public static void main(String[] args) {
        Banco banco = new Banco();
        Scanner in = new Scanner(System.in, "UTF-8");
        System.out.println("__TITULO__ — escribí 'ayuda'");
        while (true) {
            System.out.print("> ");
            if (!in.hasNextLine()) {
                break; // fin de la entrada
            }
            String linea = in.nextLine().trim();
            if (linea.equals("salir")) {
                break;
            }
            if (!linea.isEmpty()) {
                System.out.println(ejecutar(banco, linea));
            }
        }
    }
}
''',
        "tests/BancoTest.java": r'''import java.lang.reflect.Method;

/** Runner de tests mínimo (sin JUnit): cada método static void test*() es un test. Salida TAP. */
public class BancoTest {
    static void igual(Object esperado, Object obtenido) {
        if (esperado == null ? obtenido != null : !esperado.equals(obtenido)) {
            throw new AssertionError("esperado <" + esperado + "> pero fue <" + obtenido + ">");
        }
    }

    static void lanza(Class<? extends Throwable> tipo, Runnable codigo) {
        try {
            codigo.run();
        } catch (Throwable t) {
            if (tipo.isInstance(t)) {
                return;
            }
            throw new AssertionError("se esperaba " + tipo.getSimpleName() + " pero fue " + t);
        }
        throw new AssertionError("se esperaba " + tipo.getSimpleName());
    }

    static void testDinero() {
        igual(1250L, Dinero.parsear("12,5"));
        igual(1205L, Dinero.parsear("$12.05"));
        igual("$0.07", Dinero.formatear(7));
        igual("-$1.50", Dinero.formatear(-150));
        lanza(IllegalArgumentException.class, () -> Dinero.parsear("1.234"));
        lanza(IllegalArgumentException.class, () -> Dinero.parsear("-3"));
    }

    static void testDepositoYExtraccion() {
        Cuenta c = new Cuenta("1", "Ana");
        c.depositar(10000);
        c.extraer(2550);
        igual(7450L, c.getSaldoCentavos());
        igual(2, c.getMovimientos().size());
        lanza(SaldoInsuficienteException.class, () -> c.extraer(999999));
        lanza(IllegalArgumentException.class, () -> c.depositar(0));
        igual(7450L, c.getSaldoCentavos());
    }

    static void testTransferenciaAtomica() {
        Banco b = new Banco();
        b.abrir("1", "Ana").depositar(5000);
        b.abrir("2", "Luis");
        b.transferir("1", "2", 2000);
        igual(3000L, b.buscar("1").getSaldoCentavos());
        igual(2000L, b.buscar("2").getSaldoCentavos());
        lanza(SaldoInsuficienteException.class, () -> b.transferir("2", "1", 5000));
        igual(2000L, b.buscar("2").getSaldoCentavos());
        igual(5000L, b.totalCentavos());
        lanza(IllegalArgumentException.class, () -> b.transferir("1", "1", 1));
        lanza(IllegalArgumentException.class, () -> b.abrir("1", "Otra"));
    }

    static void testValidaciones() {
        lanza(IllegalArgumentException.class, () -> new Cuenta(" ", "Ana"));
        lanza(IllegalArgumentException.class, () -> new Banco().buscar("9"));
    }

    static void testComandosDelMenu() {
        Banco b = new Banco();
        igual("abierta 1 (Ana): $0.00", Main.ejecutar(b, "abrir 1 Ana"));
        igual("1 (Ana): $100.00", Main.ejecutar(b, "depositar 1 100"));
        igual("error: faltan datos (escribí 'ayuda')", Main.ejecutar(b, "depositar 1"));
        Main.ejecutar(b, "abrir 2 Luis");
        igual("listo", Main.ejecutar(b, "transferir 1 2 40,5"));
        igual("1 (Ana): $59.50\n2 (Luis): $40.50\ntotal: $100.00", Main.ejecutar(b, "listar"));
        if (!Main.ejecutar(b, "extraer 2 1000").startsWith("error: saldo insuficiente")) {
            throw new AssertionError("extraer de más debía dar error");
        }
    }

    public static void main(String[] args) throws Exception {
        int total = 0;
        int fallas = 0;
        for (Method m : BancoTest.class.getDeclaredMethods()) {
            if (!m.getName().startsWith("test")) {
                continue;
            }
            total++;
            try {
                m.invoke(null);
                System.out.println("ok " + total + " - " + m.getName());
            } catch (java.lang.reflect.InvocationTargetException e) {
                fallas++;
                System.out.println("not ok " + total + " - " + m.getName());
                System.out.println("#   " + e.getCause());
            }
        }
        System.out.println("1.." + total);
        System.out.println("# tests " + total);
        System.out.println("# pass " + (total - fallas));
        System.out.println("# fail " + fallas);
        System.exit(fallas == 0 ? 0 : 1);
    }
}
''',
        "tests/run_tests.sh": "#!/bin/sh\n# Compila y corre los tests (sin Maven).\nset -e\ncd \"$(dirname \"$0\")/..\"\nrm -rf build\njavac -encoding UTF-8 -d build src/*.java tests/*.java\njava -cp build BancoTest\n",
        "README.md": """# __TITULO__

Banco de juguete en Java, sin Maven ni JUnit.

```bash
javac -encoding UTF-8 -d build src/*.java && java -cp build Main
printf 'abrir 1 Ana\\ndepositar 1 100\\nlistar\\nsalir\\n' | java -cp build Main   # sin teclado
sh tests/run_tests.sh
```

En Termux: `pkg install openjdk-17`.
""",
    },
    comando_tests="sh tests/run_tests.sh",
    comando_ejecutar="javac -encoding UTF-8 -d build src/*.java && java -cp build Main",
    etiquetas=("java", "poo", "cli"),
    requiere=("javac", "java"),
)

# ======================================================================
# php-carrito
# ======================================================================
registrar_plantilla(
    "php-carrito",
    "Carrito de compras en PHP 8: productos, cupones, impuestos, JSON y una página web (php -S). Tests sin PHPUnit.",
    "php",
    {
        "src/Carrito.php": r'''<?php
declare(strict_types=1);

namespace App;

use InvalidArgumentException;

/** Carrito de compras. Los precios se manejan en centavos (int). */
final class Carrito
{
    /** @var array<string, array{nombre: string, precio: int, cantidad: int}> */
    private array $items = [];
    private ?string $cupon = null;

    /** Cupones disponibles: código => porcentaje de descuento. */
    public const CUPONES = ['BIENVENIDA' => 10, 'MITAD' => 50];
    public const IVA = 21;

    public function agregar(string $codigo, string $nombre, int $precio, int $cantidad = 1): void
    {
        $codigo = strtoupper(trim($codigo));
        if ($codigo === '' || trim($nombre) === '') {
            throw new InvalidArgumentException('código y nombre son obligatorios');
        }
        if ($precio < 0 || $cantidad < 1) {
            throw new InvalidArgumentException('precio o cantidad inválidos');
        }
        if (isset($this->items[$codigo])) {
            $this->items[$codigo]['cantidad'] += $cantidad;
            return;
        }
        $this->items[$codigo] = ['nombre' => trim($nombre), 'precio' => $precio, 'cantidad' => $cantidad];
    }

    public function quitar(string $codigo, int $cantidad = 1): void
    {
        $codigo = strtoupper(trim($codigo));
        if (!isset($this->items[$codigo])) {
            throw new InvalidArgumentException("no está en el carrito: $codigo");
        }
        $this->items[$codigo]['cantidad'] -= $cantidad;
        if ($this->items[$codigo]['cantidad'] <= 0) {
            unset($this->items[$codigo]);
        }
    }

    public function aplicarCupon(string $codigo): int
    {
        $codigo = strtoupper(trim($codigo));
        if (!array_key_exists($codigo, self::CUPONES)) {
            throw new InvalidArgumentException("cupón inválido: $codigo");
        }
        $this->cupon = $codigo;
        return self::CUPONES[$codigo];
    }

    public function cantidadTotal(): int
    {
        return array_sum(array_column($this->items, 'cantidad'));
    }

    public function subtotal(): int
    {
        $total = 0;
        foreach ($this->items as $item) {
            $total += $item['precio'] * $item['cantidad'];
        }
        return $total;
    }

    public function descuento(): int
    {
        if ($this->cupon === null) {
            return 0;
        }
        return intdiv($this->subtotal() * self::CUPONES[$this->cupon], 100);
    }

    public function impuestos(): int
    {
        return (int) round(($this->subtotal() - $this->descuento()) * self::IVA / 100);
    }

    public function total(): int
    {
        return $this->subtotal() - $this->descuento() + $this->impuestos();
    }

    public function vacio(): bool
    {
        return $this->items === [];
    }

    /** @return array<string, mixed> */
    public function resumen(): array
    {
        return [
            'items' => $this->items,
            'cupon' => $this->cupon,
            'subtotal' => $this->subtotal(),
            'descuento' => $this->descuento(),
            'impuestos' => $this->impuestos(),
            'total' => $this->total(),
        ];
    }

    public function aJson(): string
    {
        return json_encode($this->resumen(), JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    }

    public static function desdeJson(string $json): self
    {
        $datos = json_decode($json, true, 16, JSON_THROW_ON_ERROR);
        $c = new self();
        foreach ($datos['items'] ?? [] as $codigo => $item) {
            $c->agregar((string) $codigo, $item['nombre'], (int) $item['precio'], (int) $item['cantidad']);
        }
        if (!empty($datos['cupon'])) {
            $c->aplicarCupon($datos['cupon']);
        }
        return $c;
    }

    public static function formatear(int $centavos): string
    {
        return '$' . number_format($centavos / 100, 2, ',', '.');
    }
}
''',
        "public/index.php": r'''<?php
declare(strict_types=1);

require __DIR__ . '/../src/Carrito.php';

use App\Carrito;

session_start();
$carrito = isset($_SESSION['carrito']) ? Carrito::desdeJson($_SESSION['carrito']) : new Carrito();
$catalogo = [
    'MATE' => ['Mate de calabaza', 450000],
    'YERBA' => ['Yerba 1 kg', 320000],
    'TERMO' => ['Termo 1 L', 1890000],
];
$mensaje = '';
try {
    $accion = $_POST['accion'] ?? '';
    if ($accion === 'agregar' && isset($catalogo[$_POST['codigo'] ?? ''])) {
        [$nombre, $precio] = $catalogo[$_POST['codigo']];
        $carrito->agregar($_POST['codigo'], $nombre, $precio);
    } elseif ($accion === 'quitar') {
        $carrito->quitar($_POST['codigo'] ?? '');
    } elseif ($accion === 'cupon') {
        $mensaje = 'Cupón aplicado: ' . $carrito->aplicarCupon($_POST['cupon'] ?? '') . '%';
    }
} catch (InvalidArgumentException $e) {
    $mensaje = $e->getMessage();
}
$_SESSION['carrito'] = $carrito->aJson();
$r = $carrito->resumen();
$e = fn (string $t): string => htmlspecialchars($t, ENT_QUOTES, 'UTF-8');
?>
<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<style>body{font-family:system-ui;max-width:640px;margin:2rem auto;padding:0 1rem}td,th{padding:.3rem .6rem}</style>
</head>
<body>
<h1>__TITULO__</h1>
<?php if ($mensaje): ?><p><strong><?= $e($mensaje) ?></strong></p><?php endif ?>
<h2>Catálogo</h2>
<?php foreach ($catalogo as $codigo => [$nombre, $precio]): ?>
  <form method="post" style="display:inline">
    <input type="hidden" name="accion" value="agregar"><input type="hidden" name="codigo" value="<?= $e($codigo) ?>">
    <button><?= $e($nombre) ?> (<?= Carrito::formatear($precio) ?>)</button>
  </form>
<?php endforeach ?>
<h2>Carrito</h2>
<table>
<?php foreach ($r['items'] as $codigo => $item): ?>
  <tr><td><?= $e($item['nombre']) ?></td><td>× <?= $item['cantidad'] ?></td>
  <td><form method="post"><input type="hidden" name="accion" value="quitar">
  <input type="hidden" name="codigo" value="<?= $e($codigo) ?>"><button>quitar</button></form></td></tr>
<?php endforeach ?>
</table>
<p>Subtotal: <?= Carrito::formatear($r['subtotal']) ?> · Descuento: <?= Carrito::formatear($r['descuento']) ?>
 · IVA: <?= Carrito::formatear($r['impuestos']) ?> · <strong>Total: <?= Carrito::formatear($r['total']) ?></strong></p>
<form method="post"><input type="hidden" name="accion" value="cupon">
<input name="cupon" placeholder="cupón"><button>aplicar</button></form>
</body>
</html>
''',
        "tests/run.php": r'''<?php
declare(strict_types=1);

// Tests sin PHPUnit, salida TAP. Ejecutar: php tests/run.php
require __DIR__ . '/../src/Carrito.php';

use App\Carrito;

$total = 0;
$fallas = 0;

function prueba(string $nombre, callable $fn): void
{
    global $total, $fallas;
    $total++;
    try {
        $fn();
        echo "ok $total - $nombre\n";
    } catch (Throwable $e) {
        $fallas++;
        echo "not ok $total - $nombre\n#   " . $e->getMessage() . "\n";
    }
}

function igual($esperado, $obtenido): void
{
    if ($esperado !== $obtenido) {
        throw new RuntimeException('esperado ' . var_export($esperado, true) . ' pero fue ' . var_export($obtenido, true));
    }
}

function lanza(callable $fn): void
{
    try {
        $fn();
    } catch (InvalidArgumentException $e) {
        return;
    }
    throw new RuntimeException('se esperaba InvalidArgumentException');
}

function ejemplo(): Carrito
{
    $c = new Carrito();
    $c->agregar('mate', 'Mate', 450000);
    $c->agregar('YERBA', 'Yerba', 320000, 2);
    return $c;
}

prueba('subtotal y cantidades', function () {
    $c = ejemplo();
    igual(1090000, $c->subtotal());
    igual(3, $c->cantidadTotal());
});

prueba('agregar el mismo código suma cantidad', function () {
    $c = ejemplo();
    $c->agregar(' Mate ', 'Mate', 450000);
    igual(4, $c->cantidadTotal());
});

prueba('quitar hasta sacar el producto', function () {
    $c = ejemplo();
    $c->quitar('yerba');
    igual(2, $c->cantidadTotal());
    $c->quitar('yerba');
    $c->quitar('mate');
    igual(true, $c->vacio());
    lanza(fn () => $c->quitar('mate'));
});

prueba('cupón, IVA y total', function () {
    $c = ejemplo();
    igual(10, $c->aplicarCupon('bienvenida'));
    igual(109000, $c->descuento());
    igual(206010, $c->impuestos());
    igual(1187010, $c->total());
    lanza(fn () => $c->aplicarCupon('TRUCHO'));
});

prueba('validaciones', function () {
    $c = new Carrito();
    lanza(fn () => $c->agregar('', 'x', 1));
    lanza(fn () => $c->agregar('A', 'x', -1));
    lanza(fn () => $c->agregar('A', 'x', 1, 0));
});

prueba('JSON ida y vuelta', function () {
    $c = ejemplo();
    $c->aplicarCupon('MITAD');
    $otro = Carrito::desdeJson($c->aJson());
    igual($c->total(), $otro->total());
    igual($c->resumen(), $otro->resumen());
});

prueba('formatear', function () {
    igual('$4.500,00', Carrito::formatear(450000));
    igual('$0,05', Carrito::formatear(5));
});

echo "1..$total\n# tests $total\n# pass " . ($total - $fallas) . "\n# fail $fallas\n";
exit($fallas === 0 ? 0 : 1);
''',
        "README.md": """# __TITULO__

Carrito de compras en PHP 8 sin dependencias.

```bash
php -S 127.0.0.1:8000 -t public     # abrir http://127.0.0.1:8000
php tests/run.php                   # tests (TAP)
```

En Termux: `pkg install php`.
""",
    },
    comando_tests="php tests/run.php",
    comando_ejecutar="php -S 127.0.0.1:8000 -t public",
    etiquetas=("php", "web", "carrito"),
    requiere=("php",),
)

# ======================================================================
# ruby-biblioteca
# ======================================================================
registrar_plantilla(
    "ruby-biblioteca",
    "Préstamos de libros en Ruby: catálogo, préstamos con vencimiento, multas y CLI. Tests con minitest.",
    "ruby",
    {
        "lib/biblioteca.rb": r'''# frozen_string_literal: true

require "date"
require "json"

# Préstamos de libros con vencimiento y multas.
module Biblioteca
  class Error < StandardError; end

  Libro = Struct.new(:isbn, :titulo, :autor, :prestado_a, :vence, keyword_init: true) do
    def disponible?
      prestado_a.nil?
    end

    def vencido?(hoy)
      !disponible? && hoy > vence
    end

    def to_h_json
      { "isbn" => isbn, "titulo" => titulo, "autor" => autor, "prestado_a" => prestado_a,
        "vence" => vence&.iso8601 }
    end
  end

  class Catalogo
    DIAS_PRESTAMO = 14
    MULTA_POR_DIA = 50 # centavos
    MAX_PRESTAMOS = 3

    def initialize
      @libros = {}
    end

    def agregar(isbn:, titulo:, autor:)
      isbn = isbn.to_s.delete("-").strip
      raise Error, "ISBN inválido: #{isbn}" unless isbn.match?(/\A\d{10}(\d{3})?\z/)
      raise Error, "ya existe el ISBN #{isbn}" if @libros.key?(isbn)
      raise Error, "el título es obligatorio" if titulo.to_s.strip.empty?

      @libros[isbn] = Libro.new(isbn: isbn, titulo: titulo.strip, autor: autor.to_s.strip)
    end

    def libro(isbn)
      @libros.fetch(isbn.to_s.delete("-")) { raise Error, "no existe el libro #{isbn}" }
    end

    def buscar(texto)
      t = texto.to_s.downcase
      @libros.values.select { |l| l.titulo.downcase.include?(t) || l.autor.downcase.include?(t) }
                    .sort_by(&:titulo)
    end

    def disponibles
      @libros.values.select(&:disponible?).sort_by(&:titulo)
    end

    def prestamos_de(socio)
      @libros.values.reject(&:disponible?).select { |l| l.prestado_a == socio }
    end

    def prestar(isbn, socio, hoy: Date.today)
      l = libro(isbn)
      raise Error, "\"#{l.titulo}\" ya está prestado" unless l.disponible?
      raise Error, "#{socio} ya tiene #{MAX_PRESTAMOS} libros" if prestamos_de(socio).size >= MAX_PRESTAMOS
      raise Error, "#{socio} tiene libros vencidos" if prestamos_de(socio).any? { |x| x.vencido?(hoy) }

      l.prestado_a = socio
      l.vence = hoy + DIAS_PRESTAMO
      l
    end

    # Devuelve la multa en centavos (0 si se devolvió a tiempo).
    def devolver(isbn, hoy: Date.today)
      l = libro(isbn)
      raise Error, "\"#{l.titulo}\" no estaba prestado" if l.disponible?

      atraso = (hoy - l.vence).to_i
      l.prestado_a = nil
      l.vence = nil
      atraso.positive? ? atraso * MULTA_POR_DIA : 0
    end

    def vencidos(hoy: Date.today)
      @libros.values.select { |l| l.vencido?(hoy) }.sort_by(&:vence)
    end

    def to_json(*_args)
      JSON.pretty_generate(@libros.values.map(&:to_h_json))
    end

    def self.desde_json(texto)
      c = new
      JSON.parse(texto).each do |h|
        l = c.agregar(isbn: h["isbn"], titulo: h["titulo"], autor: h["autor"])
        l.prestado_a = h["prestado_a"]
        l.vence = h["vence"] && Date.iso8601(h["vence"])
      end
      c
    end
  end

  def self.formatear_multa(centavos)
    format("$%<p>d.%<c>02d", p: centavos / 100, c: centavos % 100)
  end
end
''',
        "bin/biblioteca": r'''#!/usr/bin/env ruby
# frozen_string_literal: true

# __TITULO__ — uso: ruby bin/biblioteca COMANDO   (ayuda para ver los comandos)
$LOAD_PATH.unshift(File.expand_path("../lib", __dir__))
require "biblioteca"

ARCHIVO = ENV.fetch("BIBLIOTECA_ARCHIVO", File.expand_path("~/.__PROYECTO__.json"))

def cargar
  File.exist?(ARCHIVO) ? Biblioteca::Catalogo.desde_json(File.read(ARCHIVO)) : Biblioteca::Catalogo.new
end

def guardar(catalogo)
  File.write("#{ARCHIVO}.tmp", catalogo.to_json)
  File.rename("#{ARCHIVO}.tmp", ARCHIVO)
end

comando, *args = ARGV
catalogo = cargar
begin
  case comando
  when "agregar"
    l = catalogo.agregar(isbn: args[0], titulo: args[1], autor: args[2])
    guardar(catalogo)
    puts "agregado: #{l.titulo}"
  when "prestar"
    l = catalogo.prestar(args[0], args[1])
    guardar(catalogo)
    puts "prestado hasta #{l.vence}"
  when "devolver"
    multa = catalogo.devolver(args[0])
    guardar(catalogo)
    puts multa.zero? ? "devuelto a tiempo" : "multa: #{Biblioteca.formatear_multa(multa)}"
  when "buscar"
    catalogo.buscar(args.join(" ")).each { |l| puts "#{l.isbn}  #{l.titulo} — #{l.autor}" }
  when "disponibles"
    catalogo.disponibles.each { |l| puts "#{l.isbn}  #{l.titulo}" }
  when "vencidos"
    catalogo.vencidos.each { |l| puts "#{l.titulo}: #{l.prestado_a} (venció #{l.vence})" }
  else
    puts "comandos: agregar ISBN TITULO AUTOR | prestar ISBN SOCIO | devolver ISBN | buscar TEXTO | disponibles | vencidos"
  end
rescue Biblioteca::Error => e
  warn "error: #{e.message}"
  exit 1
end
''',
        "test/test_biblioteca.rb": r'''# frozen_string_literal: true

require "minitest/autorun"
require "biblioteca"

class TestBiblioteca < Minitest::Test
  HOY = Date.new(2024, 3, 1)

  def setup
    @c = Biblioteca::Catalogo.new
    @c.agregar(isbn: "978-0-306-40615-7", titulo: "Rayuela", autor: "Julio Cortázar")
    @c.agregar(isbn: "9780306406158", titulo: "Ficciones", autor: "Jorge Luis Borges")
    @c.agregar(isbn: "0306406152", titulo: "El Aleph", autor: "Jorge Luis Borges")
  end

  def test_agregar_valida
    assert_raises(Biblioteca::Error) { @c.agregar(isbn: "123", titulo: "x", autor: "y") }
    assert_raises(Biblioteca::Error) { @c.agregar(isbn: "9780306406157", titulo: "otro", autor: "y") }
    assert_raises(Biblioteca::Error) { @c.agregar(isbn: "9781111111111", titulo: " ", autor: "y") }
  end

  def test_buscar_por_titulo_o_autor
    assert_equal ["El Aleph", "Ficciones"], @c.buscar("borges").map(&:titulo)
    assert_equal ["Rayuela"], @c.buscar("RAY").map(&:titulo)
  end

  def test_prestar_y_devolver_a_tiempo
    l = @c.prestar("9780306406157", "ana", hoy: HOY)
    assert_equal HOY + 14, l.vence
    refute l.disponible?
    assert_equal 2, @c.disponibles.size
    assert_equal 0, @c.devolver("9780306406157", hoy: HOY + 14)
    assert l.disponible?
  end

  def test_multa_por_atraso
    @c.prestar("9780306406158", "luis", hoy: HOY)
    assert_equal [@c.libro("9780306406158")], @c.vencidos(hoy: HOY + 20)
    assert_equal 6 * 50, @c.devolver("9780306406158", hoy: HOY + 20)
    assert_equal "$3.00", Biblioteca.formatear_multa(300)
  end

  def test_reglas_de_prestamo
    @c.prestar("9780306406157", "ana", hoy: HOY)
    err = assert_raises(Biblioteca::Error) { @c.prestar("9780306406157", "luis", hoy: HOY) }
    assert_match(/ya está prestado/, err.message)
    @c.prestar("9780306406158", "ana", hoy: HOY)
    err = assert_raises(Biblioteca::Error) { @c.prestar("0306406152", "ana", hoy: HOY + 30) }
    assert_match(/vencidos/, err.message)
    assert_raises(Biblioteca::Error) { @c.devolver("0306406152", hoy: HOY) }
  end

  def test_json_ida_y_vuelta
    @c.prestar("0306406152", "ana", hoy: HOY)
    otro = Biblioteca::Catalogo.desde_json(@c.to_json)
    assert_equal "ana", otro.libro("0306406152").prestado_a
    assert_equal HOY + 14, otro.libro("0306406152").vence
    assert_equal 2, otro.disponibles.size
  end
end
''',
        "README.md": """# __TITULO__

Préstamos de libros en Ruby (solo librería estándar + minitest).

```bash
ruby bin/biblioteca agregar 9780306406157 Rayuela "Julio Cortázar"
ruby bin/biblioteca prestar 9780306406157 ana
ruby -Ilib -Itest test/test_biblioteca.rb
```

En Termux: `pkg install ruby`.
""",
    },
    comando_tests="ruby -Ilib -Itest test/test_biblioteca.rb",
    comando_ejecutar="ruby bin/biblioteca",
    etiquetas=("ruby", "cli", "json"),
    requiere=("ruby",),
)

# ======================================================================
# perl-conversor
# ======================================================================
registrar_plantilla(
    "perl-conversor",
    "Conversor de unidades en Perl (temperatura, longitud, peso, datos) con CLI y tests Test::More (prove).",
    "perl",
    {
        "lib/Conversor.pm": r'''package Conversor;
# Conversión de unidades. Todas las funciones son puras y testeables.
use strict;
use warnings;
use Exporter 'import';

our @EXPORT_OK = qw(convertir unidades redondear categoria_de);

# factor a la unidad base de cada categoría
my %FACTORES = (
    longitud => { mm => 0.001, cm => 0.01, m => 1, km => 1000, in => 0.0254, ft => 0.3048, mi => 1609.344 },
    peso     => { g => 0.001, kg => 1, t => 1000, lb => 0.45359237, oz => 0.028349523125 },
    datos    => { b => 1, kb => 1024, mb => 1024**2, gb => 1024**3, tb => 1024**4 },
);
my %TEMPERATURA = map { $_ => 1 } qw(c f k);

sub categoria_de {
    my ($unidad) = @_;
    $unidad = lc($unidad // '');
    return 'temperatura' if $TEMPERATURA{$unidad};
    for my $cat (sort keys %FACTORES) {
        return $cat if exists $FACTORES{$cat}{$unidad};
    }
    return undef;
}

sub unidades {
    my %todas = (temperatura => [qw(c f k)]);
    $todas{$_} = [sort keys %{ $FACTORES{$_} }] for keys %FACTORES;
    return \%todas;
}

sub _a_celsius {
    my ($v, $u) = @_;
    return $v if $u eq 'c';
    return ($v - 32) * 5 / 9 if $u eq 'f';
    return $v - 273.15;
}

sub _desde_celsius {
    my ($v, $u) = @_;
    return $v if $u eq 'c';
    return $v * 9 / 5 + 32 if $u eq 'f';
    return $v + 273.15;
}

sub convertir {
    my ($valor, $desde, $hasta) = @_;
    die "valor inválido: " . ($valor // 'undef') . "\n"
        unless defined $valor && $valor =~ /^-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/;
    ($desde, $hasta) = (lc $desde, lc $hasta);
    my $cat_desde = categoria_de($desde) or die "unidad desconocida: $desde\n";
    my $cat_hasta = categoria_de($hasta) or die "unidad desconocida: $hasta\n";
    die "no se puede convertir $cat_desde en $cat_hasta\n" if $cat_desde ne $cat_hasta;
    if ($cat_desde eq 'temperatura') {
        my $c = _a_celsius($valor, $desde);
        die "temperatura bajo el cero absoluto\n" if $c < -273.15 - 1e-9;
        return _desde_celsius($c, $hasta);
    }
    die "no puede ser negativo\n" if $valor < 0;
    return $valor * $FACTORES{$cat_desde}{$desde} / $FACTORES{$cat_hasta}{$hasta};
}

sub redondear {
    my ($valor, $decimales) = @_;
    $decimales //= 2;
    my $r = sprintf("%.${decimales}f", $valor);
    $r =~ s/\.?0+$// if $r =~ /\./;
    return $r eq '-0' ? '0' : $r;
}

1;
''',
        "bin/conversor.pl": r'''#!/usr/bin/env perl
# __TITULO__: perl bin/conversor.pl 100 c f   |   perl bin/conversor.pl   (modo interactivo)
use strict;
use warnings;
use FindBin;
use lib "$FindBin::Bin/../lib";
use Conversor qw(convertir unidades redondear);

sub responder {
    my ($linea) = @_;
    my ($valor, $desde, $hasta) = split ' ', $linea;
    return "uso: VALOR DESDE HASTA (ej: 100 c f)" unless defined $hasta;
    my $r = eval { redondear(convertir($valor, $desde, $hasta), 4) };
    return $@ ? "error: $@" =~ s/\n$//r : "$valor $desde = $r $hasta";
}

if (@ARGV) {
    print responder("@ARGV"), "\n";
    exit 0;
}

my $u = unidades();
print "Unidades: ", join("; ", map { "$_: @{ $u->{$_} }" } sort keys %$u), "\n";
print "Escribí VALOR DESDE HASTA (ej: 100 c f) o 'salir'.\n";
while (1) {
    print "> ";
    my $linea = <STDIN>;
    last unless defined $linea;    # fin de la entrada
    chomp $linea;
    last if $linea eq 'salir';
    next if $linea =~ /^\s*$/;
    print responder($linea), "\n";
}
''',
        "t/conversor.t": r'''use strict;
use warnings;
use Test::More;
use FindBin;
use lib "$FindBin::Bin/../lib";
use Conversor qw(convertir redondear categoria_de);

is(redondear(convertir(100, 'c', 'f')), '212', '100 °C = 212 °F');
is(redondear(convertir(32, 'F', 'C')), '0', 'mayúsculas: 32 °F = 0 °C');
is(redondear(convertir(0, 'k', 'c')), '-273.15', '0 K = -273.15 °C');
is(redondear(convertir(1, 'km', 'm')), '1000', '1 km = 1000 m');
is(redondear(convertir(1, 'mi', 'km'), 3), '1.609', '1 milla = 1.609 km');
is(redondear(convertir(2, 'lb', 'kg'), 3), '0.907', '2 lb = 0.907 kg');
is(redondear(convertir(1, 'gb', 'mb')), '1024', '1 GB = 1024 MB');
is(redondear(convertir(1.5, 'm', 'cm')), '150', 'decimales');
is(categoria_de('oz'), 'peso', 'categoría de oz');
ok(!defined categoria_de('parsec'), 'unidad desconocida');

eval { convertir(1, 'kg', 'm') };
like($@, qr/no se puede convertir/, 'categorías distintas');
eval { convertir('abc', 'm', 'cm') };
like($@, qr/valor inválido/, 'valor no numérico');
eval { convertir(-300, 'c', 'k') };
like($@, qr/cero absoluto/, 'bajo el cero absoluto');
eval { convertir(-1, 'm', 'cm') };
like($@, qr/negativo/, 'longitud negativa');

my $salida = `printf '100 c f\\n1 kg m\\nsalir\\n' | $^X $FindBin::Bin/../bin/conversor.pl`;
like($salida, qr/100 c = 212 f/, 'REPL por stdin convierte');
like($salida, qr/error: no se puede convertir/, 'REPL por stdin informa errores');

done_testing();
''',
        "README.md": """# __TITULO__

Conversor de unidades en Perl (solo módulos estándar).

```bash
perl bin/conversor.pl 100 c f      # 100 c = 212 f
perl bin/conversor.pl              # modo interactivo
prove -l t                         # tests
```

En Termux: `pkg install perl`.
""",
    },
    comando_tests="prove -l t",
    comando_ejecutar="perl bin/conversor.pl",
    etiquetas=("perl", "cli", "conversor"),
    requiere=("perl", "prove"),
)
