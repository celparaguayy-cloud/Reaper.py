"""Plantillas web y Node.js (sin dependencias de npm): lógica pura testeable con node:test."""

_NODE_TESTS = "node --test"
_PAQUETE_NODE = r'''
{
  "name": "__PROYECTO__",
  "version": "0.1.0",
  "type": "module",
  "private": true,
  "scripts": {
    "test": "node --test",
    "start": "__INICIO__"
  }
}
'''

# ======================================================================
# web-tareas
# ======================================================================
registrar_plantilla(
    "web-tareas",
    "App web de tareas (HTML/CSS/JS sin frameworks): filtros, edición, guardado en localStorage y lógica testeada.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "python3 -m http.server 8080"),
        "index.html": r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITULO__</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main class="app">
    <h1>__TITULO__</h1>
    <form id="form-nueva">
      <input id="texto" placeholder="¿Qué hay que hacer?" autocomplete="off" required maxlength="200">
      <button type="submit">Agregar</button>
    </form>
    <nav class="filtros">
      <button data-filtro="todas" class="activo">Todas</button>
      <button data-filtro="pendientes">Pendientes</button>
      <button data-filtro="hechas">Hechas</button>
    </nav>
    <ul id="lista"></ul>
    <footer><span id="contador"></span><button id="limpiar">Borrar hechas</button></footer>
  </main>
  <script type="module" src="app.js"></script>
</body>
</html>
''',
        "style.css": r'''
:root { --fondo: #14141c; --tarjeta: #1f1f2b; --texto: #ececf1; --acento: #ff8c28; --tenue: #8a8aa0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; background: var(--fondo); color: var(--texto); }
.app { max-width: 34rem; margin: 0 auto; padding: 1rem; }
h1 { color: var(--acento); }
form { display: flex; gap: .5rem; }
input { flex: 1; padding: .7rem; border-radius: .5rem; border: 1px solid #333; background: var(--tarjeta); color: inherit; }
button { padding: .6rem .9rem; border: 0; border-radius: .5rem; background: var(--acento); color: #111; cursor: pointer; }
.filtros { display: flex; gap: .4rem; margin: 1rem 0; }
.filtros button { background: var(--tarjeta); color: var(--tenue); }
.filtros button.activo { color: var(--texto); outline: 1px solid var(--acento); }
ul { list-style: none; padding: 0; }
li { display: flex; align-items: center; gap: .6rem; padding: .6rem; margin-bottom: .4rem; background: var(--tarjeta); border-radius: .5rem; }
li.hecha span { text-decoration: line-through; color: var(--tenue); }
li span { flex: 1; word-break: break-word; }
li .borrar { background: transparent; color: var(--tenue); }
footer { display: flex; justify-content: space-between; color: var(--tenue); }
''',
        "src/tareas.js": r'''
// Lógica pura (sin DOM): se testea con node:test.

let siguienteId = 1;

export function crearTarea(texto, ahora = Date.now()) {
  const limpio = String(texto ?? '').trim().replace(/\s+/g, ' ');
  if (!limpio) throw new Error('la tarea no puede estar vacía');
  if (limpio.length > 200) throw new Error('máximo 200 caracteres');
  return { id: `${ahora}-${siguienteId++}`, texto: limpio, hecha: false, creada: ahora };
}

export function agregar(tareas, texto, ahora) {
  return [...tareas, crearTarea(texto, ahora)];
}

export function alternar(tareas, id) {
  return tareas.map((t) => (t.id === id ? { ...t, hecha: !t.hecha } : t));
}

export function editar(tareas, id, texto) {
  const limpio = String(texto ?? '').trim();
  if (!limpio) return tareas.filter((t) => t.id !== id);
  return tareas.map((t) => (t.id === id ? { ...t, texto: limpio } : t));
}

export function borrar(tareas, id) {
  return tareas.filter((t) => t.id !== id);
}

export function borrarHechas(tareas) {
  return tareas.filter((t) => !t.hecha);
}

export function filtrar(tareas, filtro) {
  if (filtro === 'pendientes') return tareas.filter((t) => !t.hecha);
  if (filtro === 'hechas') return tareas.filter((t) => t.hecha);
  return tareas;
}

export function contarPendientes(tareas) {
  const n = tareas.filter((t) => !t.hecha).length;
  return n === 1 ? '1 pendiente' : `${n} pendientes`;
}

export function serializar(tareas) {
  return JSON.stringify(tareas);
}

export function deserializar(texto) {
  try {
    const datos = JSON.parse(texto ?? '[]');
    return Array.isArray(datos) ? datos.filter((t) => t && typeof t.texto === 'string') : [];
  } catch {
    return [];
  }
}
''',
        "app.js": r'''
// Conecta la lógica con el DOM y localStorage.
import * as T from './src/tareas.js';

const CLAVE = '__PROYECTO__-tareas';
let tareas = T.deserializar(localStorage.getItem(CLAVE));
let filtro = 'todas';

const $ = (sel) => document.querySelector(sel);

function guardar() {
  localStorage.setItem(CLAVE, T.serializar(tareas));
}

function render() {
  const lista = $('#lista');
  lista.replaceChildren();
  for (const t of T.filtrar(tareas, filtro)) {
    const li = document.createElement('li');
    li.className = t.hecha ? 'hecha' : '';
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = t.hecha;
    check.addEventListener('change', () => { tareas = T.alternar(tareas, t.id); guardar(); render(); });
    const span = document.createElement('span');
    span.textContent = t.texto;
    span.addEventListener('dblclick', () => {
      const nuevo = prompt('Editar tarea', t.texto);
      if (nuevo !== null) { tareas = T.editar(tareas, t.id, nuevo); guardar(); render(); }
    });
    const borrar = document.createElement('button');
    borrar.className = 'borrar';
    borrar.textContent = '✕';
    borrar.addEventListener('click', () => { tareas = T.borrar(tareas, t.id); guardar(); render(); });
    li.append(check, span, borrar);
    lista.append(li);
  }
  $('#contador').textContent = T.contarPendientes(tareas);
}

$('#form-nueva').addEventListener('submit', (e) => {
  e.preventDefault();
  try {
    tareas = T.agregar(tareas, $('#texto').value);
    $('#texto').value = '';
    guardar();
    render();
  } catch (error) {
    alert(error.message);
  }
});

document.querySelectorAll('[data-filtro]').forEach((boton) => {
  boton.addEventListener('click', () => {
    filtro = boton.dataset.filtro;
    document.querySelectorAll('[data-filtro]').forEach((b) => b.classList.toggle('activo', b === boton));
    render();
  });
});

$('#limpiar').addEventListener('click', () => { tareas = T.borrarHechas(tareas); guardar(); render(); });
render();
''',
        "tests/tareas.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as T from '../src/tareas.js';

test('crear normaliza y valida', () => {
  assert.equal(T.crearTarea('  comprar   pan ').texto, 'comprar pan');
  assert.throws(() => T.crearTarea('   '), /vacía/);
  assert.throws(() => T.crearTarea('x'.repeat(201)), /200/);
});

test('agregar, alternar y borrar no mutan', () => {
  const vacia = [];
  const una = T.agregar(vacia, 'a', 1);
  assert.equal(vacia.length, 0);
  const id = una[0].id;
  const hecha = T.alternar(una, id);
  assert.equal(una[0].hecha, false);
  assert.equal(hecha[0].hecha, true);
  assert.equal(T.borrar(hecha, id).length, 0);
});

test('filtros, contador y limpiar', () => {
  let ts = T.agregar(T.agregar([], 'a'), 'b');
  ts = T.alternar(ts, ts[0].id);
  assert.equal(T.filtrar(ts, 'hechas').length, 1);
  assert.equal(T.filtrar(ts, 'pendientes').length, 1);
  assert.equal(T.filtrar(ts, 'todas').length, 2);
  assert.equal(T.contarPendientes(ts), '1 pendiente');
  assert.equal(T.borrarHechas(ts).length, 1);
});

test('editar vacío borra la tarea', () => {
  const ts = T.agregar([], 'a');
  assert.equal(T.editar(ts, ts[0].id, 'b')[0].texto, 'b');
  assert.equal(T.editar(ts, ts[0].id, '  ').length, 0);
});

test('serializar es tolerante a datos rotos', () => {
  const ts = T.agregar([], 'persistir');
  assert.deepEqual(T.deserializar(T.serializar(ts)), ts);
  assert.deepEqual(T.deserializar('{roto'), []);
  assert.deepEqual(T.deserializar(null), []);
  assert.deepEqual(T.deserializar('[{"x":1}]'), []);
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="python3 -m http.server 8080  (y abrí http://127.0.0.1:8080)",
    etiquetas=("web", "html", "javascript", "tareas", "todo", "localstorage", "frontend", "pagina"),
    requiere=("node",),
)

# ======================================================================
# node-cli
# ======================================================================
registrar_plantilla(
    "node-cli",
    "CLI en Node.js (ESM, sin dependencias): parser de argumentos propio, subcomandos, colores y tests.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "node bin/cli.mjs --ayuda"),
        "src/argumentos.js": r'''
// Parser de argumentos mínimo: posicionales, --flag, --clave=valor, --clave valor y -abc.
export function parsear(argv, { booleanos = [] } = {}) {
  const resultado = { _: [], opciones: {} };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--') {
      resultado._.push(...argv.slice(i + 1));
      break;
    }
    if (arg.startsWith('--')) {
      const [clave, valor] = arg.slice(2).split(/=(.*)/s);
      if (valor !== undefined) resultado.opciones[clave] = valor;
      else if (booleanos.includes(clave) || i + 1 >= argv.length || argv[i + 1].startsWith('-')) resultado.opciones[clave] = true;
      else resultado.opciones[clave] = argv[++i];
    } else if (arg.startsWith('-') && arg.length > 1) {
      for (const letra of arg.slice(1)) resultado.opciones[letra] = true;
    } else {
      resultado._.push(arg);
    }
  }
  return resultado;
}
''',
        "src/comandos.js": r'''
export function contarPalabras(texto) {
  const palabras = texto.toLowerCase().match(/[\p{L}\p{N}']+/gu) ?? [];
  const conteo = new Map();
  for (const p of palabras) conteo.set(p, (conteo.get(p) ?? 0) + 1);
  return [...conteo.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function invertir(texto) {
  return [...texto].reverse().join('');
}

export function capitalizar(texto) {
  return texto.replace(/(^|\s)(\p{L})/gu, (_, espacio, letra) => espacio + letra.toUpperCase());
}

export const COMANDOS = {
  contar: { ayuda: 'palabras más frecuentes', correr: (texto, op) => contarPalabras(texto).slice(0, Number(op.n ?? 5)).map(([p, n]) => `${n} ${p}`).join('\n') },
  invertir: { ayuda: 'invierte el texto', correr: (texto) => invertir(texto) },
  capitalizar: { ayuda: 'mayúscula inicial en cada palabra', correr: (texto) => capitalizar(texto) },
};
''',
        "bin/cli.mjs": r'''
#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { parsear } from '../src/argumentos.js';
import { COMANDOS } from '../src/comandos.js';

const { _: [comando, ...resto], opciones } = parsear(process.argv.slice(2), { booleanos: ['ayuda'] });
if (!comando || opciones.ayuda || !COMANDOS[comando]) {
  console.log('uso: cli <comando> [texto | --archivo ruta] [--n 5]\n');
  for (const [nombre, c] of Object.entries(COMANDOS)) console.log(`  ${nombre.padEnd(12)} ${c.ayuda}`);
  process.exit(comando && !COMANDOS[comando] ? 1 : 0);
}
let texto = resto.join(' ');
if (opciones.archivo) {
  try {
    texto = readFileSync(opciones.archivo, 'utf8');
  } catch (e) {
    console.error(`error: no pude leer ${opciones.archivo}`);
    process.exit(1);
  }
}
console.log(COMANDOS[comando].correr(texto, opciones));
''',
        "tests/cli.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { parsear } from '../src/argumentos.js';
import { capitalizar, contarPalabras, invertir } from '../src/comandos.js';

test('parsear argumentos', () => {
  const r = parsear(['contar', '--n', '3', '--archivo=a.txt', '-vx', 'hola', '--', '--literal'], { booleanos: [] });
  assert.deepEqual(r._, ['contar', 'hola', '--literal']);
  assert.deepEqual(r.opciones, { n: '3', archivo: 'a.txt', v: true, x: true });
  assert.equal(parsear(['--ayuda', 'x'], { booleanos: ['ayuda'] }).opciones.ayuda, true);
});

test('comandos de texto', () => {
  assert.deepEqual(contarPalabras('Sol luna SOL')[0], ['sol', 2]);
  assert.equal(invertir('ñandú'), 'údnañ');
  assert.equal(capitalizar('hola árbol viejo'), 'Hola Árbol Viejo');
});

test('cli de punta a punta', () => {
  const salida = execFileSync(process.execPath, ['bin/cli.mjs', 'invertir', 'abc'], { encoding: 'utf8' });
  assert.equal(salida.trim(), 'cba');
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="node bin/cli.mjs contar 'hola hola mundo'",
    etiquetas=("node", "javascript", "cli", "terminal", "comandos", "argumentos"),
    requiere=("node",),
)

# ======================================================================
# node-api
# ======================================================================
registrar_plantilla(
    "node-api",
    "API REST en Node.js con el módulo http (sin Express): router, JSON, validación, CORS y tests con fetch.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "node src/servidor.js"),
        "src/router.js": r'''
// Router mínimo con parámetros (/items/:id).
export class Router {
  constructor() {
    this.rutas = [];
  }

  agregar(metodo, patron, manejador) {
    const nombres = [];
    const regex = new RegExp('^' + patron.replace(/:(\w+)/g, (_, n) => { nombres.push(n); return '([^/]+)'; }) + '/?$');
    this.rutas.push({ metodo, regex, nombres, manejador });
    return this;
  }

  buscar(metodo, ruta) {
    let metodoIncorrecto = false;
    for (const r of this.rutas) {
      const m = ruta.match(r.regex);
      if (!m) continue;
      if (r.metodo !== metodo) { metodoIncorrecto = true; continue; }
      const params = Object.fromEntries(r.nombres.map((n, i) => [n, decodeURIComponent(m[i + 1])]));
      return { manejador: r.manejador, params };
    }
    return { estado: metodoIncorrecto ? 405 : 404 };
  }
}
''',
        "src/almacen.js": r'''
export class Almacen {
  constructor() {
    this.items = new Map();
    this.siguiente = 1;
  }

  validar(datos) {
    if (!datos || typeof datos.nombre !== 'string' || !datos.nombre.trim()) throw new Error('nombre es obligatorio');
    if (datos.precio !== undefined && (typeof datos.precio !== 'number' || datos.precio < 0)) throw new Error('precio inválido');
    return { nombre: datos.nombre.trim(), precio: datos.precio ?? 0 };
  }

  crear(datos) {
    const item = { id: this.siguiente++, ...this.validar(datos) };
    this.items.set(item.id, item);
    return item;
  }

  listar() { return [...this.items.values()]; }
  obtener(id) { return this.items.get(Number(id)) ?? null; }

  actualizar(id, datos) {
    const actual = this.obtener(id);
    if (!actual) return null;
    const nuevo = { ...actual, ...this.validar({ ...actual, ...datos }) };
    this.items.set(actual.id, nuevo);
    return nuevo;
  }

  borrar(id) { return this.items.delete(Number(id)); }
}
''',
        "src/servidor.js": r'''
import http from 'node:http';
import { pathToFileURL } from 'node:url';
import { Almacen } from './almacen.js';
import { Router } from './router.js';

async function leerJSON(req, limite = 1_000_000) {
  let cuerpo = '';
  for await (const trozo of req) {
    cuerpo += trozo;
    if (cuerpo.length > limite) throw new Error('cuerpo demasiado grande');
  }
  return cuerpo ? JSON.parse(cuerpo) : {};
}

export function crearApp(almacen = new Almacen()) {
  const router = new Router()
    .agregar('GET', '/items', () => [200, almacen.listar()])
    .agregar('POST', '/items', (_p, datos) => [201, almacen.crear(datos)])
    .agregar('GET', '/items/:id', ({ id }) => { const i = almacen.obtener(id); return i ? [200, i] : [404, { error: 'no existe' }]; })
    .agregar('PUT', '/items/:id', ({ id }, datos) => { const i = almacen.actualizar(id, datos); return i ? [200, i] : [404, { error: 'no existe' }]; })
    .agregar('DELETE', '/items/:id', ({ id }) => (almacen.borrar(id) ? [204, null] : [404, { error: 'no existe' }]));

  return http.createServer(async (req, res) => {
    const enviar = (estado, datos) => {
      res.writeHead(estado, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
      res.end(datos === null ? '' : JSON.stringify(datos));
    };
    if (req.method === 'OPTIONS') return enviar(204, null);
    const { pathname } = new URL(req.url, 'http://localhost');
    const encontrado = router.buscar(req.method, pathname);
    if (!encontrado.manejador) return enviar(encontrado.estado, { error: encontrado.estado === 405 ? 'método no permitido' : 'ruta desconocida' });
    try {
      const datos = ['POST', 'PUT'].includes(req.method) ? await leerJSON(req) : undefined;
      const [estado, cuerpo] = encontrado.manejador(encontrado.params, datos);
      enviar(estado, cuerpo);
    } catch (e) {
      enviar(400, { error: e instanceof SyntaxError ? 'JSON inválido' : e.message });
    }
  });
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const puerto = Number(process.env.PUERTO ?? 3000);
  crearApp().listen(puerto, () => console.log(`API en http://127.0.0.1:${puerto}/items`));
}
''',
        "tests/api.test.mjs": r'''
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { crearApp } from '../src/servidor.js';
import { Router } from '../src/router.js';

let servidor;
let base;

before(async () => {
  servidor = crearApp();
  await new Promise((ok) => servidor.listen(0, '127.0.0.1', ok));
  base = `http://127.0.0.1:${servidor.address().port}`;
});
after(() => new Promise((ok) => servidor.close(ok)));

const pedir = async (metodo, ruta, datos) => {
  const r = await fetch(base + ruta, { method: metodo, headers: { 'Content-Type': 'application/json' }, body: datos === undefined ? undefined : (typeof datos === 'string' ? datos : JSON.stringify(datos)) });
  const texto = await r.text();
  return [r.status, texto ? JSON.parse(texto) : null];
};

test('router con parámetros y 405', () => {
  const r = new Router().agregar('GET', '/a/:id', () => 'ok');
  assert.deepEqual(r.buscar('GET', '/a/7').params, { id: '7' });
  assert.equal(r.buscar('POST', '/a/7').estado, 405);
  assert.equal(r.buscar('GET', '/b').estado, 404);
});

test('CRUD completo', async () => {
  const [estado, item] = await pedir('POST', '/items', { nombre: ' Mate ', precio: 10 });
  assert.equal(estado, 201);
  assert.equal(item.nombre, 'Mate');
  assert.equal((await pedir('GET', `/items/${item.id}`))[1].precio, 10);
  assert.equal((await pedir('PUT', `/items/${item.id}`, { precio: 12 }))[1].precio, 12);
  assert.equal((await pedir('GET', '/items'))[1].length, 1);
  assert.equal((await pedir('DELETE', `/items/${item.id}`))[0], 204);
  assert.equal((await pedir('GET', `/items/${item.id}`))[0], 404);
});

test('errores', async () => {
  assert.equal((await pedir('POST', '/items', { precio: 1 }))[0], 400);
  assert.equal((await pedir('POST', '/items', '{roto'))[1].error, 'JSON inválido');
  assert.equal((await pedir('PATCH', '/items'))[0], 405);
  assert.equal((await pedir('GET', '/nada'))[0], 404);
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="node src/servidor.js",
    etiquetas=("node", "api", "rest", "servidor", "backend", "http", "javascript"),
    requiere=("node",),
)

# ======================================================================
# juego-canvas (breakout)
# ======================================================================
registrar_plantilla(
    "juego-canvas",
    "Juego Breakout en canvas para el navegador del celular (táctil y teclado) con física testeada en Node.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "python3 -m http.server 8080"),
        "index.html": r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <title>__TITULO__</title>
  <style>
    body { margin: 0; background: #0d0d14; display: flex; flex-direction: column; align-items: center; color: #eee; font-family: system-ui; }
    canvas { background: #14141f; max-width: 100vw; touch-action: none; }
    #info { padding: .5rem; }
  </style>
</head>
<body>
  <div id="info">Puntaje: <span id="puntaje">0</span> · Vidas: <span id="vidas">3</span></div>
  <canvas id="lienzo" width="360" height="480"></canvas>
  <script type="module" src="app.js"></script>
</body>
</html>
''',
        "src/motor.js": r'''
// Física y reglas del Breakout, sin DOM ni tiempo real.
export function crearJuego(ancho = 360, alto = 480, filas = 5, columnas = 7) {
  const ladrillos = [];
  const anchoLadrillo = (ancho - 20) / columnas;
  for (let f = 0; f < filas; f++) {
    for (let c = 0; c < columnas; c++) {
      ladrillos.push({ x: 10 + c * anchoLadrillo, y: 40 + f * 22, w: anchoLadrillo - 4, h: 18, vivo: true, puntos: (filas - f) * 10 });
    }
  }
  return {
    ancho, alto, ladrillos, puntaje: 0, vidas: 3, estado: 'jugando',
    paleta: { x: ancho / 2 - 40, y: alto - 30, w: 80, h: 10 },
    pelota: { x: ancho / 2, y: alto - 50, r: 6, vx: 3, vy: -3 },
  };
}

export function moverPaleta(juego, x) {
  juego.paleta.x = Math.max(0, Math.min(juego.ancho - juego.paleta.w, x - juego.paleta.w / 2));
}

function choca(p, r) {
  return p.x + p.r > r.x && p.x - p.r < r.x + r.w && p.y + p.r > r.y && p.y - p.r < r.y + r.h;
}

export function paso(juego) {
  if (juego.estado !== 'jugando') return juego;
  const p = juego.pelota;
  p.x += p.vx;
  p.y += p.vy;
  if (p.x - p.r < 0 || p.x + p.r > juego.ancho) { p.vx = -p.vx; p.x = Math.max(p.r, Math.min(juego.ancho - p.r, p.x)); }
  if (p.y - p.r < 0) { p.vy = Math.abs(p.vy); p.y = p.r; }
  const paleta = juego.paleta;
  if (p.vy > 0 && choca(p, paleta)) {
    const desde_centro = (p.x - (paleta.x + paleta.w / 2)) / (paleta.w / 2);
    p.vx = desde_centro * 4;
    p.vy = -Math.abs(p.vy);
  }
  for (const l of juego.ladrillos) {
    if (l.vivo && choca(p, l)) {
      l.vivo = false;
      juego.puntaje += l.puntos;
      p.vy = -p.vy;
      break;
    }
  }
  if (p.y - p.r > juego.alto) {
    juego.vidas -= 1;
    if (juego.vidas <= 0) juego.estado = 'perdido';
    else Object.assign(p, { x: juego.ancho / 2, y: juego.alto - 50, vx: 3, vy: -3 });
  }
  if (juego.ladrillos.every((l) => !l.vivo)) juego.estado = 'ganado';
  return juego;
}
''',
        "app.js": r'''
import { crearJuego, moverPaleta, paso } from './src/motor.js';

const lienzo = document.getElementById('lienzo');
const ctx = lienzo.getContext('2d');
let juego = crearJuego(lienzo.width, lienzo.height);

function dibujar() {
  ctx.clearRect(0, 0, lienzo.width, lienzo.height);
  for (const l of juego.ladrillos) {
    if (!l.vivo) continue;
    ctx.fillStyle = `hsl(${l.y * 2}, 80%, 60%)`;
    ctx.fillRect(l.x, l.y, l.w, l.h);
  }
  ctx.fillStyle = '#ff8c28';
  ctx.fillRect(juego.paleta.x, juego.paleta.y, juego.paleta.w, juego.paleta.h);
  ctx.beginPath();
  ctx.arc(juego.pelota.x, juego.pelota.y, juego.pelota.r, 0, Math.PI * 2);
  ctx.fillStyle = '#fff';
  ctx.fill();
  document.getElementById('puntaje').textContent = juego.puntaje;
  document.getElementById('vidas').textContent = juego.vidas;
  if (juego.estado !== 'jugando') {
    ctx.fillStyle = '#fff';
    ctx.font = '24px system-ui';
    ctx.fillText(juego.estado === 'ganado' ? '¡Ganaste! Tocá para jugar' : 'Fin. Tocá para reiniciar', 40, lienzo.height / 2);
  }
}

function bucle() {
  paso(juego);
  dibujar();
  requestAnimationFrame(bucle);
}

const posicion = (e) => {
  const rect = lienzo.getBoundingClientRect();
  const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
  return x * (lienzo.width / rect.width);
};
lienzo.addEventListener('pointermove', (e) => moverPaleta(juego, posicion(e)));
lienzo.addEventListener('touchmove', (e) => moverPaleta(juego, posicion(e)), { passive: true });
lienzo.addEventListener('click', () => { if (juego.estado !== 'jugando') juego = crearJuego(lienzo.width, lienzo.height); });
document.addEventListener('keydown', (e) => {
  const delta = { ArrowLeft: -25, ArrowRight: 25 }[e.key];
  if (delta) moverPaleta(juego, juego.paleta.x + juego.paleta.w / 2 + delta);
});
bucle();
''',
        "tests/motor.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { crearJuego, moverPaleta, paso } from '../src/motor.js';

test('crea el tablero', () => {
  const j = crearJuego(360, 480, 2, 3);
  assert.equal(j.ladrillos.length, 6);
  assert.equal(j.estado, 'jugando');
});

test('la paleta no se sale', () => {
  const j = crearJuego();
  moverPaleta(j, -500);
  assert.equal(j.paleta.x, 0);
  moverPaleta(j, 5000);
  assert.equal(j.paleta.x, j.ancho - j.paleta.w);
});

test('rebota en la pared y en la paleta', () => {
  const j = crearJuego();
  Object.assign(j.pelota, { x: 3, vx: -3, vy: 0, y: 300 });
  paso(j);
  assert.ok(j.pelota.vx > 0);
  Object.assign(j.pelota, { x: j.paleta.x + j.paleta.w / 2, y: j.paleta.y - 4, vx: 0, vy: 3 });
  paso(j);
  assert.ok(j.pelota.vy < 0);
});

test('romper ladrillos suma y gana', () => {
  const j = crearJuego(360, 480, 1, 1);
  const l = j.ladrillos[0];
  Object.assign(j.pelota, { x: l.x + 10, y: l.y + l.h + 5, vx: 0, vy: -3 });
  for (let i = 0; i < 5 && j.estado === 'jugando'; i++) paso(j);
  assert.equal(j.puntaje, 10);
  assert.equal(j.estado, 'ganado');
});

test('perder vidas', () => {
  const j = crearJuego();
  for (let v = 0; v < 3; v++) {
    Object.assign(j.pelota, { x: 10, y: j.alto + 20, vx: 0, vy: 1 });
    paso(j);
  }
  assert.equal(j.estado, 'perdido');
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="python3 -m http.server 8080  (abrí http://127.0.0.1:8080 en el navegador)",
    etiquetas=("juego", "canvas", "web", "breakout", "arkanoid", "javascript", "navegador", "html"),
    requiere=("node",),
)

# ======================================================================
# calculadora-web
# ======================================================================
registrar_plantilla(
    "calculadora-web",
    "Calculadora web con evaluador de expresiones propio (tokenizador + shunting-yard, sin eval) e historial.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "python3 -m http.server 8080"),
        "src/evaluador.js": r'''
// Evaluador seguro de expresiones: + - * / ^ %, paréntesis, unario, sqrt(), y constantes pi/e. Sin eval().
const PRECEDENCIA = { '+': 1, '-': 1, '*': 2, '/': 2, '%': 2, '^': 3, 'neg': 4 };
const DERECHA = new Set(['^', 'neg']);
const FUNCIONES = { sqrt: Math.sqrt, sin: Math.sin, cos: Math.cos, abs: Math.abs, ln: Math.log };
const CONSTANTES = { pi: Math.PI, e: Math.E };

export function tokenizar(texto) {
  const tokens = [];
  const re = /\s*(\d+(?:[.,]\d+)?|[a-z]+|[-+*/^%()])/giy;
  let m;
  let pos = 0;
  while (pos < texto.length) {
    re.lastIndex = pos;
    m = re.exec(texto);
    if (!m) {
      if (/^\s*$/.test(texto.slice(pos))) break;
      throw new Error(`carácter inesperado: "${texto[pos]}"`);
    }
    tokens.push(m[1].replace(',', '.'));
    pos = re.lastIndex;
  }
  return tokens;
}

export function aPostfija(tokens) {
  const salida = [];
  const pila = [];
  let previo = null;
  for (const t of tokens) {
    if (/^\d/.test(t)) salida.push(Number(t));
    else if (t in CONSTANTES) salida.push(CONSTANTES[t]);
    else if (t in FUNCIONES) pila.push(t);
    else if (t === '(') pila.push(t);
    else if (t === ')') {
      while (pila.length && pila.at(-1) !== '(') salida.push(pila.pop());
      if (!pila.length) throw new Error('paréntesis sin abrir');
      pila.pop();
      if (pila.length && pila.at(-1) in FUNCIONES) salida.push(pila.pop());
    } else if (t in PRECEDENCIA) {
      const unario = t === '-' && (previo === null || previo in PRECEDENCIA || previo === '(');
      const op = unario ? 'neg' : t;
      if (unario || t !== '+' || !(previo === null || previo in PRECEDENCIA || previo === '(')) {
        while (pila.length && pila.at(-1) in PRECEDENCIA &&
               (PRECEDENCIA[pila.at(-1)] > PRECEDENCIA[op] || (PRECEDENCIA[pila.at(-1)] === PRECEDENCIA[op] && !DERECHA.has(op)))) {
          salida.push(pila.pop());
        }
        pila.push(op);
      }
    } else {
      throw new Error(`no conozco "${t}"`);
    }
    previo = t;
  }
  while (pila.length) {
    const op = pila.pop();
    if (op === '(') throw new Error('falta cerrar un paréntesis');
    salida.push(op);
  }
  return salida;
}

export function evaluarPostfija(postfija) {
  const pila = [];
  for (const t of postfija) {
    if (typeof t === 'number') pila.push(t);
    else if (t === 'neg') pila.push(-pila.pop());
    else if (t in FUNCIONES) pila.push(FUNCIONES[t](pila.pop()));
    else {
      const b = pila.pop();
      const a = pila.pop();
      if (a === undefined || b === undefined) throw new Error('expresión incompleta');
      if ((t === '/' || t === '%') && b === 0) throw new Error('división por cero');
      pila.push({ '+': a + b, '-': a - b, '*': a * b, '/': a / b, '%': a % b, '^': a ** b }[t]);
    }
  }
  if (pila.length !== 1 || Number.isNaN(pila[0])) throw new Error('expresión inválida');
  return pila[0];
}

export function calcular(texto) {
  const resultado = evaluarPostfija(aPostfija(tokenizar(texto.toLowerCase())));
  return Math.round(resultado * 1e10) / 1e10;
}
''',
        "index.html": r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITULO__</title>
  <style>
    body { font-family: system-ui; background: #111; color: #eee; max-width: 24rem; margin: auto; padding: 1rem; }
    #pantalla { width: 100%; font-size: 1.6rem; padding: .6rem; background: #1d1d26; color: #fff; border: 0; border-radius: .5rem; }
    #resultado { font-size: 2rem; text-align: right; min-height: 2.4rem; color: #ff8c28; }
    .teclas { display: grid; grid-template-columns: repeat(4, 1fr); gap: .4rem; }
    button { padding: 1rem; font-size: 1.2rem; border: 0; border-radius: .5rem; background: #262633; color: #fff; }
    ol { color: #999; }
  </style>
</head>
<body>
  <input id="pantalla" placeholder="2*(3+4)^2" autocomplete="off">
  <div id="resultado"></div>
  <div class="teclas" id="teclas"></div>
  <ol id="historial"></ol>
  <script type="module">
    import { calcular } from './src/evaluador.js';
    const pantalla = document.getElementById('pantalla');
    const resultado = document.getElementById('resultado');
    for (const t of ['7', '8', '9', '/', '4', '5', '6', '*', '1', '2', '3', '-', '0', '.', '(', '+', ')', '^', 'C', '=']) {
      const b = document.createElement('button');
      b.textContent = t;
      b.onclick = () => {
        if (t === 'C') pantalla.value = '';
        else if (t === '=') resolver();
        else pantalla.value += t;
      };
      document.getElementById('teclas').append(b);
    }
    function resolver() {
      try {
        const r = calcular(pantalla.value);
        resultado.textContent = r;
        const li = document.createElement('li');
        li.textContent = `${pantalla.value} = ${r}`;
        document.getElementById('historial').prepend(li);
      } catch (e) {
        resultado.textContent = e.message;
      }
    }
    pantalla.addEventListener('keydown', (e) => { if (e.key === 'Enter') resolver(); });
  </script>
</body>
</html>
''',
        "tests/evaluador.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { calcular, tokenizar } from '../src/evaluador.js';

test('precedencia y asociatividad', () => {
  assert.equal(calcular('2+3*4'), 14);
  assert.equal(calcular('(2+3)*4'), 20);
  assert.equal(calcular('2^3^2'), 512);
  assert.equal(calcular('10-4-3'), 3);
  assert.equal(calcular('7 % 4'), 3);
});

test('unarios, decimales con coma y funciones', () => {
  assert.equal(calcular('-3+5'), 2);
  assert.equal(calcular('2*-3'), -6);
  assert.equal(calcular('-(2+3)'), -5);
  assert.equal(calcular('1,5*2'), 3);
  assert.equal(calcular('sqrt(16)+abs(-2)'), 6);
  assert.equal(calcular('2*pi'), 6.2831853072);
  assert.equal(calcular('+4'), 4);
});

test('errores claros', () => {
  assert.throws(() => calcular('1/0'), /cero/);
  assert.throws(() => calcular('(1+2'), /paréntesis/);
  assert.throws(() => calcular('1+2)'), /paréntesis/);
  assert.throws(() => calcular('2 $ 3'), /inesperado/);
  assert.throws(() => calcular('2+'), /incompleta|inválida/);
  assert.throws(() => calcular('alert(1)'), /no conozco/);
});

test('tokenizar', () => {
  assert.deepEqual(tokenizar('12.5*(3)'), ['12.5', '*', '(', '3', ')']);
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="python3 -m http.server 8080",
    etiquetas=("calculadora", "web", "javascript", "expresiones", "matematica", "html"),
    requiere=("node",),
)

# ======================================================================
# pwa-notas
# ======================================================================
registrar_plantilla(
    "pwa-notas",
    "PWA de notas que funciona offline (manifest + service worker), instalable en Android, con búsqueda y exportación.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "python3 -m http.server 8080"),
        "manifest.webmanifest": r'''
{
  "name": "__TITULO__",
  "short_name": "Notas",
  "start_url": "./index.html",
  "display": "standalone",
  "background_color": "#14141c",
  "theme_color": "#ff8c28",
  "icons": []
}
''',
        "sw.js": r'''
// Service worker: guarda la app en caché para usarla sin conexión.
const CACHE = '__PROYECTO__-v1';
const ARCHIVOS = ['./', './index.html', './app.js', './src/notas.js', './manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ARCHIVOS)));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((claves) => Promise.all(claves.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
});

self.addEventListener('fetch', (e) => {
  e.respondWith(caches.match(e.request).then((r) => r ?? fetch(e.request)));
});
''',
        "src/notas.js": r'''
export function nuevaNota(titulo, cuerpo = '', ahora = Date.now()) {
  const t = String(titulo ?? '').trim();
  if (!t) throw new Error('la nota necesita título');
  return { id: `n${ahora}${Math.floor(Math.random() * 1000)}`, titulo: t, cuerpo: String(cuerpo), creada: ahora, editada: ahora, fijada: false };
}

export function actualizar(notas, id, cambios, ahora = Date.now()) {
  return notas.map((n) => (n.id === id ? { ...n, ...cambios, editada: ahora } : n));
}

export function ordenar(notas) {
  return [...notas].sort((a, b) => Number(b.fijada) - Number(a.fijada) || b.editada - a.editada);
}

export function buscar(notas, texto) {
  const q = texto.trim().toLowerCase();
  if (!q) return ordenar(notas);
  return ordenar(notas.filter((n) => `${n.titulo}\n${n.cuerpo}`.toLowerCase().includes(q)));
}

export function exportarMarkdown(notas) {
  return ordenar(notas).map((n) => `# ${n.titulo}\n\n${n.cuerpo}`.trim()).join('\n\n---\n\n') + '\n';
}
''',
        "index.html": r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#ff8c28">
  <link rel="manifest" href="manifest.webmanifest">
  <title>__TITULO__</title>
  <style>
    body { font-family: system-ui; background: #14141c; color: #eee; max-width: 36rem; margin: auto; padding: 1rem; }
    input, textarea { width: 100%; box-sizing: border-box; background: #1f1f2b; color: #eee; border: 1px solid #333; border-radius: .4rem; padding: .6rem; margin-bottom: .5rem; }
    button { background: #ff8c28; border: 0; border-radius: .4rem; padding: .5rem .8rem; }
    article { background: #1f1f2b; border-radius: .5rem; padding: .6rem; margin: .5rem 0; }
  </style>
</head>
<body>
  <input id="buscar" placeholder="Buscar...">
  <input id="titulo" placeholder="Título">
  <textarea id="cuerpo" rows="4" placeholder="Escribí..."></textarea>
  <button id="guardar">Guardar</button> <button id="exportar">Exportar .md</button>
  <section id="lista"></section>
  <script type="module" src="app.js"></script>
</body>
</html>
''',
        "app.js": r'''
import { buscar, exportarMarkdown, nuevaNota } from './src/notas.js';

const CLAVE = '__PROYECTO__-notas';
let notas = JSON.parse(localStorage.getItem(CLAVE) ?? '[]');
const $ = (id) => document.getElementById(id);

function render() {
  $('lista').replaceChildren(...buscar(notas, $('buscar').value).map((n) => {
    const a = document.createElement('article');
    const h = document.createElement('h3');
    h.textContent = (n.fijada ? '📌 ' : '') + n.titulo;
    const p = document.createElement('p');
    p.textContent = n.cuerpo;
    a.append(h, p);
    a.onclick = () => { notas = notas.map((x) => (x.id === n.id ? { ...x, fijada: !x.fijada } : x)); guardar(); };
    return a;
  }));
}

function guardar() {
  localStorage.setItem(CLAVE, JSON.stringify(notas));
  render();
}

$('guardar').onclick = () => {
  try {
    notas = [...notas, nuevaNota($('titulo').value, $('cuerpo').value)];
    $('titulo').value = $('cuerpo').value = '';
    guardar();
  } catch (e) {
    alert(e.message);
  }
};
$('buscar').oninput = render;
$('exportar').onclick = () => {
  const enlace = document.createElement('a');
  enlace.href = URL.createObjectURL(new Blob([exportarMarkdown(notas)], { type: 'text/markdown' }));
  enlace.download = 'notas.md';
  enlace.click();
};
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js');
render();
''',
        "tests/notas.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { actualizar, buscar, exportarMarkdown, nuevaNota, ordenar } from '../src/notas.js';

test('crear y validar', () => {
  assert.equal(nuevaNota(' Compras ', 'pan', 1).titulo, 'Compras');
  assert.throws(() => nuevaNota(''), /título/);
});

test('ordenar con fijadas primero', () => {
  const a = nuevaNota('a', '', 1);
  const b = { ...nuevaNota('b', '', 2), fijada: true };
  const c = nuevaNota('c', '', 3);
  assert.deepEqual(ordenar([a, b, c]).map((n) => n.titulo), ['b', 'c', 'a']);
});

test('buscar y actualizar', () => {
  let notas = [nuevaNota('Receta', 'harina y huevos', 1), nuevaNota('Ideas', 'app de notas', 2)];
  assert.deepEqual(buscar(notas, 'HUEVO').map((n) => n.titulo), ['Receta']);
  notas = actualizar(notas, notas[0].id, { cuerpo: 'nuevo' }, 10);
  assert.equal(notas[0].editada, 10);
  assert.equal(buscar(notas, '').length, 2);
});

test('exportar markdown', () => {
  const md = exportarMarkdown([nuevaNota('Uno', 'texto', 1)]);
  assert.equal(md, '# Uno\n\ntexto\n');
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="python3 -m http.server 8080  (abrí en Chrome y 'Agregar a la pantalla de inicio')",
    etiquetas=("pwa", "web", "notas", "offline", "android", "service worker", "javascript", "app"),
    requiere=("node",),
)
