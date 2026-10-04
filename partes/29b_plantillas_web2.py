"""
Más plantillas web y Node.js (sin npm install): la lógica va en módulos puros testeados con node:test y la
interfaz es HTML/CSS/JS plano que funciona abriendo el archivo o con `python3 -m http.server`.

  kanban-web       tablero kanban con columnas, mover tarjetas (también en el celular) y localStorage
  chat-sse         chat en tiempo real con Node + Server-Sent Events (sin websockets ni dependencias)
  gastos-web       panel de gastos con gráfico SVG, filtros por mes y exportación CSV
  editor-markdown  editor Markdown con vista previa en vivo y conversor propio seguro (escapa HTML)
  pong-canvas      Pong en canvas con física testeada, controles táctiles y contra la compu
"""

# ======================================================================
# kanban-web
# ======================================================================
registrar_plantilla(
    "kanban-web",
    "Tablero kanban (HTML/CSS/JS): columnas, tarjetas, mover con botones o arrastrando, localStorage. Lógica testeada.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "python3 -m http.server 8080"),
        "src/tablero.js": r'''
// Lógica pura del tablero (sin DOM): se testea con node:test.
export const COLUMNAS = ['pendiente', 'haciendo', 'hecho'];

export function tableroVacio() {
  return { siguiente: 1, tarjetas: [] };
}

export function agregar(tablero, titulo, columna = 'pendiente') {
  const limpio = String(titulo ?? '').trim();
  if (!limpio) throw new Error('la tarjeta necesita un título');
  if (!COLUMNAS.includes(columna)) throw new Error(`columna inválida: ${columna}`);
  const orden = tablero.tarjetas.filter((t) => t.columna === columna).length;
  const tarjeta = { id: tablero.siguiente, titulo: limpio.slice(0, 200), columna, orden };
  return { siguiente: tablero.siguiente + 1, tarjetas: [...tablero.tarjetas, tarjeta] };
}

function renumerar(tarjetas) {
  const salida = [];
  for (const columna of COLUMNAS) {
    tarjetas.filter((t) => t.columna === columna)
      .sort((a, b) => a.orden - b.orden)
      .forEach((t, i) => salida.push({ ...t, orden: i }));
  }
  return salida;
}

export function mover(tablero, id, columna, posicion = Infinity) {
  if (!COLUMNAS.includes(columna)) throw new Error(`columna inválida: ${columna}`);
  const tarjeta = tablero.tarjetas.find((t) => t.id === id);
  if (!tarjeta) throw new Error(`no existe la tarjeta ${id}`);
  const resto = renumerar(tablero.tarjetas.filter((t) => t.id !== id));
  const enDestino = resto.filter((t) => t.columna === columna).length;
  const pos = Math.max(0, Math.min(posicion, enDestino));
  // se corre un lugar todo lo que queda desde la posición de destino y se inserta la tarjeta ahí
  const corridas = resto.map((t) => (t.columna === columna && t.orden >= pos ? { ...t, orden: t.orden + 1 } : t));
  return { ...tablero, tarjetas: renumerar([...corridas, { ...tarjeta, columna, orden: pos }]) };
}

export function avanzar(tablero, id) {
  const tarjeta = tablero.tarjetas.find((t) => t.id === id);
  if (!tarjeta) throw new Error(`no existe la tarjeta ${id}`);
  const i = COLUMNAS.indexOf(tarjeta.columna);
  return i === COLUMNAS.length - 1 ? tablero : mover(tablero, id, COLUMNAS[i + 1]);
}

export function retroceder(tablero, id) {
  const tarjeta = tablero.tarjetas.find((t) => t.id === id);
  if (!tarjeta) throw new Error(`no existe la tarjeta ${id}`);
  const i = COLUMNAS.indexOf(tarjeta.columna);
  return i === 0 ? tablero : mover(tablero, id, COLUMNAS[i - 1]);
}

export function borrar(tablero, id) {
  return { ...tablero, tarjetas: renumerar(tablero.tarjetas.filter((t) => t.id !== id)) };
}

export function columna(tablero, nombre) {
  return tablero.tarjetas.filter((t) => t.columna === nombre).sort((a, b) => a.orden - b.orden);
}

export function cargar(texto) {
  try {
    const datos = JSON.parse(texto);
    if (!datos || !Array.isArray(datos.tarjetas)) return tableroVacio();
    const tarjetas = datos.tarjetas.filter((t) => t && COLUMNAS.includes(t.columna) && Number.isInteger(t.id));
    const siguiente = Math.max(datos.siguiente || 1, ...tarjetas.map((t) => t.id + 1), 1);
    return { siguiente, tarjetas: renumerar(tarjetas) };
  } catch {
    return tableroVacio();
  }
}
''',
        "app.js": r'''
import { COLUMNAS, agregar, avanzar, borrar, cargar, columna, mover, retroceder } from './src/tablero.js';

const CLAVE = '__PROYECTO__-tablero';
let tablero = cargar(localStorage.getItem(CLAVE) ?? '');
const NOMBRES = { pendiente: 'Pendiente', haciendo: 'Haciendo', hecho: 'Hecho' };

function guardar() {
  localStorage.setItem(CLAVE, JSON.stringify(tablero));
}

function pintar() {
  const raiz = document.querySelector('#tablero');
  raiz.replaceChildren();
  for (const nombre of COLUMNAS) {
    const col = document.createElement('section');
    col.className = 'columna';
    col.dataset.columna = nombre;
    col.innerHTML = `<h2>${NOMBRES[nombre]} <span>${columna(tablero, nombre).length}</span></h2>`;
    col.addEventListener('dragover', (e) => e.preventDefault());
    col.addEventListener('drop', (e) => {
      e.preventDefault();
      tablero = mover(tablero, Number(e.dataTransfer.getData('text/plain')), nombre);
      guardar(); pintar();
    });
    for (const t of columna(tablero, nombre)) {
      const tarjeta = document.createElement('article');
      tarjeta.className = 'tarjeta';
      tarjeta.draggable = true;
      tarjeta.addEventListener('dragstart', (e) => e.dataTransfer.setData('text/plain', String(t.id)));
      const titulo = document.createElement('p');
      titulo.textContent = t.titulo;                       // textContent: nunca HTML del usuario
      const botones = document.createElement('div');
      for (const [texto, accion] of [['◀', retroceder], ['▶', avanzar], ['✕', borrar]]) {
        const b = document.createElement('button');
        b.textContent = texto;
        b.addEventListener('click', () => { tablero = accion(tablero, t.id); guardar(); pintar(); });
        botones.append(b);
      }
      tarjeta.append(titulo, botones);
      col.append(tarjeta);
    }
    raiz.append(col);
  }
}

document.querySelector('#form').addEventListener('submit', (e) => {
  e.preventDefault();
  const entrada = document.querySelector('#titulo');
  try {
    tablero = agregar(tablero, entrada.value);
    entrada.value = '';
    guardar(); pintar();
  } catch (error) {
    entrada.setCustomValidity(error.message);
    entrada.reportValidity();
    entrada.setCustomValidity('');
  }
});

pintar();
''',
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
  <header>
    <h1>__TITULO__</h1>
    <form id="form"><input id="titulo" placeholder="Nueva tarjeta" maxlength="200" required><button>Agregar</button></form>
  </header>
  <main id="tablero"></main>
  <script type="module" src="app.js"></script>
</body>
</html>
''',
        "style.css": r'''
:root { --fondo: #101018; --col: #1a1a26; --tarjeta: #26263a; --acento: #a78bfa; --texto: #eee; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; background: var(--fondo); color: var(--texto); }
header { padding: 1rem; display: flex; flex-wrap: wrap; gap: .8rem; align-items: center; justify-content: space-between; }
h1 { margin: 0; font-size: 1.3rem; }
form { display: flex; gap: .5rem; flex: 1; max-width: 420px; }
input { flex: 1; padding: .6rem; border-radius: .5rem; border: 1px solid #333; background: var(--col); color: inherit; }
button { padding: .5rem .8rem; border: 0; border-radius: .5rem; background: var(--acento); color: #111; cursor: pointer; }
#tablero { display: grid; grid-template-columns: repeat(3, minmax(220px, 1fr)); gap: .8rem; padding: 0 1rem 1rem; overflow-x: auto; }
.columna { background: var(--col); border-radius: .8rem; padding: .6rem; min-height: 50vh; }
.columna h2 { font-size: 1rem; margin: .2rem .2rem .6rem; }
.columna h2 span { opacity: .6; font-weight: normal; }
.tarjeta { background: var(--tarjeta); border-radius: .6rem; padding: .6rem; margin-bottom: .5rem; cursor: grab; }
.tarjeta p { margin: 0 0 .4rem; word-break: break-word; }
.tarjeta div { display: flex; gap: .3rem; justify-content: flex-end; }
.tarjeta button { background: transparent; color: var(--acento); padding: .2rem .5rem; }
@media (max-width: 700px) { #tablero { grid-template-columns: 1fr; } .columna { min-height: auto; } }
''',
        "tests/tablero.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { agregar, avanzar, borrar, cargar, columna, mover, retroceder, tableroVacio } from '../src/tablero.js';

function ejemplo() {
  let t = tableroVacio();
  for (const titulo of ['a', 'b', 'c']) t = agregar(t, titulo);
  return t;
}

test('agregar valida y asigna ids', () => {
  const t = ejemplo();
  assert.deepEqual(columna(t, 'pendiente').map((x) => x.titulo), ['a', 'b', 'c']);
  assert.equal(t.siguiente, 4);
  assert.throws(() => agregar(t, '   '), /título/);
  assert.throws(() => agregar(t, 'x', 'nada'), /columna/);
});

test('mover a otra columna y posición', () => {
  let t = ejemplo();
  t = mover(t, 3, 'haciendo');
  t = mover(t, 1, 'haciendo', 0);
  assert.deepEqual(columna(t, 'haciendo').map((x) => x.titulo), ['a', 'c']);
  assert.deepEqual(columna(t, 'pendiente').map((x) => [x.titulo, x.orden]), [['b', 0]]);
});

test('reordenar dentro de la misma columna', () => {
  let t = ejemplo();
  t = mover(t, 3, 'pendiente', 0);
  assert.deepEqual(columna(t, 'pendiente').map((x) => x.titulo), ['c', 'a', 'b']);
});

test('avanzar, retroceder y borrar', () => {
  let t = ejemplo();
  t = avanzar(avanzar(avanzar(t, 1), 1), 1);        // en 'hecho' ya no avanza más
  assert.equal(columna(t, 'hecho')[0].id, 1);
  t = retroceder(t, 1);
  assert.equal(columna(t, 'haciendo')[0].id, 1);
  t = borrar(t, 2);
  assert.deepEqual(columna(t, 'pendiente').map((x) => [x.titulo, x.orden]), [['c', 0]]);
  assert.throws(() => avanzar(t, 99));
});

test('cargar tolera datos dañados', () => {
  assert.deepEqual(cargar('{roto'), tableroVacio());
  const t = cargar(JSON.stringify({ tarjetas: [{ id: 7, titulo: 'x', columna: 'hecho', orden: 5 }, { id: 'mal' }] }));
  assert.equal(t.siguiente, 8);
  assert.deepEqual(columna(t, 'hecho').map((x) => x.orden), [0]);
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="python3 -m http.server 8080",
    etiquetas=("web", "kanban", "tablero", "tareas", "localstorage"),
    requiere=("node",),
)

# ======================================================================
# chat-sse
# ======================================================================
registrar_plantilla(
    "chat-sse",
    "Chat en tiempo real con Node: Server-Sent Events, historial, nombres y límites; cliente HTML. Sin dependencias.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "node servidor.mjs"),
        "src/sala.mjs": r'''
// Estado del chat (sin red): mensajes, validación y suscriptores. Testeable sin servidor.
export const MAX_MENSAJE = 500;
export const MAX_HISTORIAL = 100;

export class Sala {
  constructor({ reloj = () => Date.now() } = {}) {
    this.reloj = reloj;
    this.mensajes = [];
    this.suscriptores = new Set();
    this.siguiente = 1;
  }

  validar(nombre, texto) {
    const n = String(nombre ?? '').trim().slice(0, 30);
    const t = String(texto ?? '').trim();
    if (!n) throw new Error('falta el nombre');
    if (!t) throw new Error('mensaje vacío');
    if (t.length > MAX_MENSAJE) throw new Error(`máximo ${MAX_MENSAJE} caracteres`);
    return { nombre: n, texto: t };
  }

  publicar(nombre, texto) {
    const datos = this.validar(nombre, texto);
    const mensaje = { id: this.siguiente++, ...datos, fecha: this.reloj() };
    this.mensajes.push(mensaje);
    if (this.mensajes.length > MAX_HISTORIAL) this.mensajes.shift();
    for (const enviar of this.suscriptores) enviar(mensaje);
    return mensaje;
  }

  suscribir(enviar) {
    this.suscriptores.add(enviar);
    return () => this.suscriptores.delete(enviar);
  }

  desde(id = 0) {
    return this.mensajes.filter((m) => m.id > id);
  }
}

export function eventoSSE(mensaje) {
  return `id: ${mensaje.id}\nevent: mensaje\ndata: ${JSON.stringify(mensaje)}\n\n`;
}
''',
        "servidor.mjs": r'''
// __TITULO__: chat con Server-Sent Events.  node servidor.mjs  →  http://127.0.0.1:8080
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { Sala, eventoSSE } from './src/sala.mjs';

export function crearServidor(sala = new Sala()) {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://local');
    try {
      if (req.method === 'GET' && url.pathname === '/') {
        res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
        res.end(await readFile(new URL('./index.html', import.meta.url)));
      } else if (req.method === 'GET' && url.pathname === '/eventos') {
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
        res.write(': conectado\n\n');                 // manda las cabeceras ya (si no, el cliente espera)
        const ultimo = Number(req.headers['last-event-id'] || url.searchParams.get('desde') || 0);
        for (const m of sala.desde(ultimo)) res.write(eventoSSE(m));       // lo que se perdió al reconectar
        const cancelar = sala.suscribir((m) => res.write(eventoSSE(m)));
        const latido = setInterval(() => res.write(': latido\n\n'), 25000);
        req.on('close', () => { cancelar(); clearInterval(latido); });
      } else if (req.method === 'POST' && url.pathname === '/mensajes') {
        let cuerpo = '';
        for await (const parte of req) {
          cuerpo += parte;
          if (cuerpo.length > 10000) throw Object.assign(new Error('cuerpo demasiado grande'), { estado: 413 });
        }
        const { nombre, texto } = JSON.parse(cuerpo || '{}');
        const mensaje = sala.publicar(nombre, texto);
        res.writeHead(201, { 'content-type': 'application/json' });
        res.end(JSON.stringify(mensaje));
      } else {
        res.writeHead(404, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ error: 'ruta inexistente' }));
      }
    } catch (error) {
      res.writeHead(error.estado || 400, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: error.message }));
    }
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const puerto = Number(process.env.PORT || 8080);
  crearServidor().listen(puerto, '127.0.0.1', () => console.log(`chat en http://127.0.0.1:${puerto}`));
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
    body { margin: 0; font-family: system-ui; background: #0f0f17; color: #eee; display: flex; flex-direction: column; height: 100vh; }
    #mensajes { flex: 1; overflow-y: auto; padding: 1rem; }
    .m { margin: .3rem 0; } .m b { color: #a78bfa; } .m small { opacity: .5; margin-left: .4rem; }
    form { display: flex; gap: .4rem; padding: .6rem; background: #17172a; }
    input { padding: .6rem; border-radius: .4rem; border: 1px solid #333; background: #0f0f17; color: inherit; }
    #texto { flex: 1; } button { padding: .6rem 1rem; border: 0; border-radius: .4rem; background: #a78bfa; }
  </style>
</head>
<body>
  <div id="mensajes"></div>
  <form id="form">
    <input id="nombre" placeholder="Tu nombre" maxlength="30" size="8" required>
    <input id="texto" placeholder="Mensaje" maxlength="500" required autocomplete="off">
    <button>Enviar</button>
  </form>
  <script>
    const lista = document.querySelector('#mensajes');
    const nombre = document.querySelector('#nombre');
    nombre.value = localStorage.getItem('nombre') || '';
    const fuente = new EventSource('/eventos');          // reconecta solo y pide lo que se perdió
    fuente.addEventListener('mensaje', (e) => {
      const m = JSON.parse(e.data);
      const fila = document.createElement('div');
      fila.className = 'm';
      const quien = document.createElement('b');
      quien.textContent = m.nombre;                       // textContent: sin inyección de HTML
      const hora = document.createElement('small');
      hora.textContent = new Date(m.fecha).toLocaleTimeString();
      fila.append(quien, ': ', m.texto, hora);
      lista.append(fila);
      lista.scrollTop = lista.scrollHeight;
    });
    document.querySelector('#form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const texto = document.querySelector('#texto');
      localStorage.setItem('nombre', nombre.value);
      const r = await fetch('/mensajes', { method: 'POST', body: JSON.stringify({ nombre: nombre.value, texto: texto.value }) });
      if (r.ok) texto.value = ''; else alert((await r.json()).error);
    });
  </script>
</body>
</html>
''',
        "tests/sala.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAX_HISTORIAL, Sala, eventoSSE } from '../src/sala.mjs';

test('publicar valida y notifica', () => {
  const sala = new Sala({ reloj: () => 1000 });
  const recibidos = [];
  const cancelar = sala.suscribir((m) => recibidos.push(m.texto));
  sala.publicar(' Ana ', ' hola ');
  cancelar();
  sala.publicar('Ana', 'no llega');
  assert.deepEqual(recibidos, ['hola']);
  assert.deepEqual(sala.mensajes[0], { id: 1, nombre: 'Ana', texto: 'hola', fecha: 1000 });
  assert.throws(() => sala.publicar('', 'x'), /nombre/);
  assert.throws(() => sala.publicar('a', 'x'.repeat(501)), /máximo/);
});

test('historial limitado y desde', () => {
  const sala = new Sala();
  for (let i = 0; i < MAX_HISTORIAL + 5; i++) sala.publicar('a', `m${i}`);
  assert.equal(sala.mensajes.length, MAX_HISTORIAL);
  assert.equal(sala.desde(MAX_HISTORIAL + 3).length, 2);
});

test('formato SSE', () => {
  assert.equal(eventoSSE({ id: 3, texto: 'x' }), 'id: 3\nevent: mensaje\ndata: {"id":3,"texto":"x"}\n\n');
});
''',
        "tests/servidor.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { crearServidor } from '../servidor.mjs';

test('POST /mensajes llega por /eventos', async () => {
  const servidor = crearServidor();
  await new Promise((ok) => servidor.listen(0, '127.0.0.1', ok));
  const base = `http://127.0.0.1:${servidor.address().port}`;
  const control = new AbortController();
  try {
    const eventos = await fetch(`${base}/eventos`, { signal: control.signal });
    assert.equal(eventos.headers.get('content-type'), 'text/event-stream');
    const lector = eventos.body.getReader();
    const r = await fetch(`${base}/mensajes`, { method: 'POST', body: JSON.stringify({ nombre: 'Ana', texto: 'hola' }) });
    assert.equal(r.status, 201);
    let texto = '';
    while (!/event: mensaje[\s\S]*\n\n/.test(texto)) texto += new TextDecoder().decode((await lector.read()).value);
    assert.match(texto, /event: mensaje/);
    assert.match(texto, /"texto":"hola"/);
    const malo = await fetch(`${base}/mensajes`, { method: 'POST', body: JSON.stringify({ nombre: 'Ana', texto: ' ' }) });
    assert.equal(malo.status, 400);
    assert.equal((await fetch(`${base}/nada`)).status, 404);
  } finally {
    control.abort();
    servidor.closeAllConnections?.();
    servidor.close();
  }
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="node servidor.mjs",
    etiquetas=("chat", "tiempo real", "sse", "node", "servidor", "web"),
    requiere=("node",),
)

# ======================================================================
# gastos-web
# ======================================================================
registrar_plantilla(
    "gastos-web",
    "Panel de gastos en el navegador: alta rápida, gráfico de barras SVG por categoría, filtro por mes y exportar CSV.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "python3 -m http.server 8080"),
        "src/gastos.js": r'''
// Lógica pura del panel (montos en centavos para no perder precisión).
export function parsearMonto(texto) {
  const t = String(texto ?? '').trim().replace(/\$/g, '').replace(/\s/g, '');
  const normalizado = t.includes(',') ? t.replace(/\./g, '').replace(',', '.') : t;
  if (!/^\d+(\.\d{1,2})?$/.test(normalizado)) throw new Error(`monto inválido: ${texto}`);
  return Math.round(Number(normalizado) * 100);
}

export function formatear(centavos) {
  const signo = centavos < 0 ? '-' : '';
  const abs = Math.abs(centavos);
  const enteros = Math.floor(abs / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return `${signo}$${enteros},${String(abs % 100).padStart(2, '0')}`;
}

export function nuevoGasto(lista, { monto, categoria, fecha, detalle = '' }) {
  const cat = String(categoria ?? '').trim().toLowerCase();
  if (!cat) throw new Error('falta la categoría');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha ?? '')) throw new Error('fecha inválida (AAAA-MM-DD)');
  const id = lista.reduce((max, g) => Math.max(max, g.id), 0) + 1;
  return [...lista, { id, monto: parsearMonto(monto), categoria: cat, fecha, detalle: String(detalle).slice(0, 120) }];
}

export const delMes = (lista, mes) => lista.filter((g) => g.fecha.startsWith(mes));

export function porCategoria(lista) {
  const totales = new Map();
  for (const g of lista) totales.set(g.categoria, (totales.get(g.categoria) ?? 0) + g.monto);
  return [...totales.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export const total = (lista) => lista.reduce((suma, g) => suma + g.monto, 0);

export function meses(lista) {
  return [...new Set(lista.map((g) => g.fecha.slice(0, 7)))].sort().reverse();
}

const escapar = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function graficoSVG(pares, ancho = 360) {
  if (!pares.length) return '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>';
  const maximo = Math.max(...pares.map(([, v]) => v), 1);
  const alto = pares.length * 30 + 10;
  const filas = pares.map(([cat, valor], i) => {
    const y = 10 + i * 30;
    const largo = Math.max(2, Math.round((ancho - 170) * valor / maximo));
    return `<text x="90" y="${y + 15}" text-anchor="end" font-size="13" fill="currentColor">${escapar(cat)}</text>` +
      `<rect x="96" y="${y}" width="${largo}" height="20" rx="4" fill="#a78bfa"></rect>` +
      `<text x="${100 + largo}" y="${y + 15}" font-size="12" fill="currentColor">${formatear(valor)}</text>`;
  });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${ancho}" height="${alto}">${filas.join('')}</svg>`;
}

export function aCSV(lista) {
  const celda = (v) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const filas = lista.map((g) => [g.fecha, (g.monto / 100).toFixed(2), g.categoria, g.detalle].map(celda).join(','));
  return ['fecha,monto,categoria,detalle', ...filas].join('\n') + '\n';
}
''',
        "app.js": r'''
import { aCSV, delMes, formatear, graficoSVG, meses, nuevoGasto, porCategoria, total } from './src/gastos.js';

const CLAVE = '__PROYECTO__-gastos';
let gastos = [];
try { gastos = JSON.parse(localStorage.getItem(CLAVE) || '[]'); } catch { gastos = []; }
const $ = (s) => document.querySelector(s);
$('#fecha').value = new Date().toISOString().slice(0, 10);

function pintar() {
  const selector = $('#mes');
  const actual = selector.value || new Date().toISOString().slice(0, 7);
  selector.replaceChildren(...[...new Set([actual, ...meses(gastos)])].map((m) => new Option(m, m, false, m === actual)));
  const del = delMes(gastos, actual);
  $('#total').textContent = formatear(total(del));
  $('#grafico').innerHTML = graficoSVG(porCategoria(del));   // el SVG escapa los textos
  const lista = $('#lista');
  lista.replaceChildren(...del.slice().reverse().map((g) => {
    const li = document.createElement('li');
    li.textContent = `${g.fecha} · ${g.categoria} · ${formatear(g.monto)} ${g.detalle}`;
    return li;
  }));
}

$('#form').addEventListener('submit', (e) => {
  e.preventDefault();
  try {
    gastos = nuevoGasto(gastos, { monto: $('#monto').value, categoria: $('#categoria').value, fecha: $('#fecha').value, detalle: $('#detalle').value });
    localStorage.setItem(CLAVE, JSON.stringify(gastos));
    $('#monto').value = ''; $('#detalle').value = '';
    pintar();
  } catch (error) { alert(error.message); }
});
$('#mes').addEventListener('change', pintar);
$('#exportar').addEventListener('click', () => {
  const enlace = document.createElement('a');
  enlace.href = URL.createObjectURL(new Blob([aCSV(gastos)], { type: 'text/csv' }));
  enlace.download = 'gastos.csv';
  enlace.click();
});
pintar();
''',
        "index.html": r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITULO__</title>
  <style>
    body { font-family: system-ui; background: #0f0f17; color: #eee; max-width: 720px; margin: auto; padding: 1rem; }
    form { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: .5rem; }
    input, select, button { padding: .6rem; border-radius: .4rem; border: 1px solid #333; background: #17172a; color: inherit; }
    button { background: #a78bfa; color: #111; border: 0; }
    .resumen { display: flex; justify-content: space-between; align-items: center; margin: 1rem 0; }
    #total { font-size: 1.6rem; font-weight: bold; } ul { padding-left: 1rem; opacity: .85; }
  </style>
</head>
<body>
  <h1>__TITULO__</h1>
  <form id="form">
    <input id="monto" placeholder="Monto" inputmode="decimal" required>
    <input id="categoria" placeholder="Categoría" list="categorias" required>
    <input id="fecha" type="date" required>
    <input id="detalle" placeholder="Detalle (opcional)">
    <button>Agregar</button>
  </form>
  <datalist id="categorias"><option>comida</option><option>transporte</option><option>servicios</option><option>ocio</option></datalist>
  <div class="resumen"><select id="mes"></select><span id="total"></span><button id="exportar" type="button">CSV</button></div>
  <div id="grafico"></div>
  <ul id="lista"></ul>
  <script type="module" src="app.js"></script>
</body>
</html>
''',
        "tests/gastos.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { aCSV, delMes, formatear, graficoSVG, meses, nuevoGasto, parsearMonto, porCategoria, total } from '../src/gastos.js';

test('montos', () => {
  assert.equal(parsearMonto('1.234,56'), 123456);
  assert.equal(parsearMonto('$ 99.9'), 9990);
  assert.equal(parsearMonto('15'), 1500);
  assert.throws(() => parsearMonto('abc'));
  assert.throws(() => parsearMonto('-3'));
  assert.equal(formatear(123456789), '$1.234.567,89');
  assert.equal(formatear(-5), '-$0,05');
});

test('alta, filtros y totales', () => {
  let g = [];
  g = nuevoGasto(g, { monto: '1500', categoria: 'Comida', fecha: '2024-03-02' });
  g = nuevoGasto(g, { monto: '300,50', categoria: 'transporte', fecha: '2024-03-05' });
  g = nuevoGasto(g, { monto: '700', categoria: 'comida', fecha: '2024-02-28' });
  assert.deepEqual(g.map((x) => x.id), [1, 2, 3]);
  assert.equal(total(delMes(g, '2024-03')), 180050);
  assert.deepEqual(porCategoria(g), [['comida', 220000], ['transporte', 30050]]);
  assert.deepEqual(meses(g), ['2024-03', '2024-02']);
  assert.throws(() => nuevoGasto(g, { monto: '1', categoria: ' ', fecha: '2024-01-01' }));
  assert.throws(() => nuevoGasto(g, { monto: '1', categoria: 'x', fecha: 'ayer' }));
});

test('gráfico escapa y CSV con comillas', () => {
  const svg = graficoSVG([['<script>', 100], ['ok', 50]]);
  assert.match(svg, /&lt;script&gt;/);
  assert.equal((svg.match(/<rect/g) || []).length, 2);
  const csv = aCSV([{ fecha: '2024-03-01', monto: 1050, categoria: 'comida', detalle: 'pan, "rico"' }]);
  assert.equal(csv, 'fecha,monto,categoria,detalle\n2024-03-01,10.50,comida,"pan, ""rico"""\n');
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="python3 -m http.server 8080",
    etiquetas=("gastos", "finanzas", "grafico", "svg", "web", "dashboard"),
    requiere=("node",),
)

# ======================================================================
# editor-markdown
# ======================================================================
registrar_plantilla(
    "editor-markdown",
    "Editor Markdown en el navegador con vista previa en vivo, conversor propio que escapa HTML, guardado y descarga.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "python3 -m http.server 8080"),
        "src/markdown.js": r'''
// Markdown → HTML (subconjunto) seguro: todo el texto se escapa antes de dar formato.
const escapar = (t) => t.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function urlSegura(url) {
  return /^(javascript|data|vbscript):/i.test(url.trim()) ? '#' : url;
}

export function enLinea(texto) {
  const codigos = [];
  let t = texto.replace(/`([^`]+)`/g, (_, c) => { codigos.push(`<code>${escapar(c)}</code>`); return `\u0000${codigos.length - 1}\u0000`; });
  t = escapar(t);
  t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, url) => `<img src="${urlSegura(url)}" alt="${alt}">`);
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, txt, url) => `<a href="${urlSegura(url)}">${txt}</a>`);
  t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/(^|[^*])\*([^*\s][^*]*?)\*/g, '$1<em>$2</em>');
  t = t.replace(/~~(.+?)~~/g, '<del>$1</del>');
  return t.replace(/\u0000(\d+)\u0000/g, (_, i) => codigos[Number(i)]);
}

export function convertir(md) {
  const lineas = md.replace(/\r\n/g, '\n').split('\n');
  const salida = [];
  let parrafo = [];
  let lista = null;
  const cerrarParrafo = () => { if (parrafo.length) { salida.push(`<p>${enLinea(parrafo.join(' '))}</p>`); parrafo = []; } };
  const cerrarLista = () => { if (lista) { salida.push(`</${lista}>`); lista = null; } };
  for (let i = 0; i < lineas.length; i++) {
    const linea = lineas[i];
    if (linea.startsWith('```')) {
      cerrarParrafo(); cerrarLista();
      const bloque = [];
      for (i++; i < lineas.length && !lineas[i].startsWith('```'); i++) bloque.push(lineas[i]);
      salida.push(`<pre><code>${escapar(bloque.join('\n'))}</code></pre>`);
      continue;
    }
    const titulo = linea.match(/^(#{1,6})\s+(.*)$/);
    const ul = linea.match(/^\s*[-*]\s+(.*)$/);
    const ol = linea.match(/^\s*\d+[.)]\s+(.*)$/);
    if (!linea.trim()) { cerrarParrafo(); cerrarLista(); }
    else if (titulo) { cerrarParrafo(); cerrarLista(); salida.push(`<h${titulo[1].length}>${enLinea(titulo[2])}</h${titulo[1].length}>`); }
    else if (/^(-{3,}|\*{3,})$/.test(linea.trim())) { cerrarParrafo(); cerrarLista(); salida.push('<hr>'); }
    else if (linea.startsWith('>')) { cerrarParrafo(); cerrarLista(); salida.push(`<blockquote>${enLinea(linea.replace(/^>\s?/, ''))}</blockquote>`); }
    else if (ul || ol) {
      cerrarParrafo();
      const tipo = ul ? 'ul' : 'ol';
      if (lista !== tipo) { cerrarLista(); salida.push(`<${tipo}>`); lista = tipo; }
      salida.push(`<li>${enLinea((ul || ol)[1])}</li>`);
    } else { cerrarLista(); parrafo.push(linea.trim()); }
  }
  cerrarParrafo(); cerrarLista();
  return salida.join('\n');
}

export function estadisticas(md) {
  const palabras = (md.match(/[\p{L}\p{N}]+/gu) || []).length;
  return { palabras, caracteres: md.length, minutos: Math.max(1, Math.round(palabras / 200)) };
}
''',
        "app.js": r'''
import { convertir, estadisticas } from './src/markdown.js';

const CLAVE = '__PROYECTO__-texto';
const editor = document.querySelector('#editor');
const vista = document.querySelector('#vista');
const info = document.querySelector('#info');
editor.value = localStorage.getItem(CLAVE) ?? '# Hola\n\nEscribí **Markdown** acá y mirá la vista previa.\n\n- listas\n- `código`\n';

let espera;
function actualizar() {
  vista.innerHTML = convertir(editor.value);     // convertir() escapa todo el HTML del usuario
  const e = estadisticas(editor.value);
  info.textContent = `${e.palabras} palabras · ${e.caracteres} caracteres · ~${e.minutos} min de lectura`;
  clearTimeout(espera);
  espera = setTimeout(() => localStorage.setItem(CLAVE, editor.value), 400);
}

editor.addEventListener('input', actualizar);
document.querySelector('#descargar').addEventListener('click', () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([editor.value], { type: 'text/markdown' }));
  a.download = 'documento.md';
  a.click();
});
actualizar();
''',
        "index.html": r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITULO__</title>
  <style>
    body { margin: 0; font-family: system-ui; background: #0f0f17; color: #eee; }
    header { display: flex; justify-content: space-between; align-items: center; padding: .6rem 1rem; background: #17172a; }
    main { display: grid; grid-template-columns: 1fr 1fr; height: calc(100vh - 52px); }
    textarea { background: #0f0f17; color: inherit; border: 0; border-right: 1px solid #333; padding: 1rem; font: 15px/1.5 monospace; resize: none; }
    #vista { padding: 1rem; overflow-y: auto; line-height: 1.6; }
    pre { background: #17172a; padding: .8rem; overflow-x: auto; } code { background: #17172a; padding: 0 .2rem; }
    button { padding: .4rem .8rem; border: 0; border-radius: .4rem; background: #a78bfa; }
    @media (max-width: 700px) { main { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; } textarea { border-right: 0; border-bottom: 1px solid #333; } }
  </style>
</head>
<body>
  <header><span id="info"></span><button id="descargar">Descargar .md</button></header>
  <main><textarea id="editor" spellcheck="false"></textarea><article id="vista"></article></main>
  <script type="module" src="app.js"></script>
</body>
</html>
''',
        "tests/markdown.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { convertir, enLinea, estadisticas } from '../src/markdown.js';

test('formato en línea', () => {
  assert.equal(enLinea('**a** *b* ~~c~~ `d*e*`'), '<strong>a</strong> <em>b</em> <del>c</del> <code>d*e*</code>');
  assert.equal(enLinea('[x](https://a.com)'), '<a href="https://a.com">x</a>');
});

test('escapa HTML y links peligrosos', () => {
  assert.equal(enLinea('<img src=x onerror=alert(1)>'), '&lt;img src=x onerror=alert(1)&gt;');
  assert.match(enLinea('[x](javascript:alert)'), /href="#"/);
});

test('bloques', () => {
  assert.equal(convertir('# T\n\nuno\ndos\n\n- a\n- b'), '<h1>T</h1>\n<p>uno dos</p>\n<ul>\n<li>a</li>\n<li>b</li>\n</ul>');
  assert.equal(convertir('```\n<b>\n```'), '<pre><code>&lt;b&gt;</code></pre>');
  assert.equal(convertir('> cita\n\n---'), '<blockquote>cita</blockquote>\n<hr>');
});

test('estadísticas', () => {
  assert.deepEqual(estadisticas('Hola mundo, año 2024'), { palabras: 4, caracteres: 20, minutos: 1 });
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="python3 -m http.server 8080",
    etiquetas=("markdown", "editor", "web", "vista previa", "notas"),
    requiere=("node",),
)

# ======================================================================
# pong-canvas
# ======================================================================
registrar_plantilla(
    "pong-canvas",
    "Pong en canvas: física pura testeada (rebotes, puntos, IA de la compu), controles táctiles y teclado.",
    "javascript",
    {
        "package.json": _PAQUETE_NODE.replace("__INICIO__", "python3 -m http.server 8080"),
        "src/pong.js": r'''
// Física y reglas de Pong sin DOM (testeables). Coordenadas en un campo de ANCHO x ALTO.
export const ANCHO = 800, ALTO = 500, PALETA = { ancho: 12, alto: 90 }, RADIO = 8, VELOCIDAD = 360;

export function nuevoJuego(azar = Math.random) {
  return { pelota: saque(1, azar), izq: ALTO / 2 - PALETA.alto / 2, der: ALTO / 2 - PALETA.alto / 2,
           puntos: [0, 0], ganador: null, golpes: 0 };
}

export function saque(direccion, azar = Math.random) {
  const angulo = (azar() - 0.5) * Math.PI / 3;              // ±30°
  return { x: ANCHO / 2, y: ALTO / 2, vx: Math.cos(angulo) * VELOCIDAD * direccion, vy: Math.sin(angulo) * VELOCIDAD };
}

export function moverPaleta(y, direccion, dt, velocidad = 420) {
  return Math.max(0, Math.min(ALTO - PALETA.alto, y + direccion * velocidad * dt));
}

export function ia(juego, dt, dificultad = 0.75) {
  const centro = juego.der + PALETA.alto / 2;
  const objetivo = juego.pelota.vx > 0 ? juego.pelota.y : ALTO / 2;
  const diferencia = objetivo - centro;
  if (Math.abs(diferencia) < 8) return juego.der;
  return moverPaleta(juego.der, Math.sign(diferencia), dt, 420 * dificultad);
}

function chocaPaleta(p, yPaleta, xPaleta) {
  return p.y + RADIO >= yPaleta && p.y - RADIO <= yPaleta + PALETA.alto &&
         p.x - RADIO <= xPaleta + PALETA.ancho && p.x + RADIO >= xPaleta;
}

export function paso(juego, dt, { azar = Math.random, aGanar = 7 } = {}) {
  if (juego.ganador !== null) return juego;
  let p = { ...juego.pelota, x: juego.pelota.x + juego.pelota.vx * dt, y: juego.pelota.y + juego.pelota.vy * dt };
  if (p.y - RADIO < 0) p = { ...p, y: RADIO, vy: Math.abs(p.vy) };
  if (p.y + RADIO > ALTO) p = { ...p, y: ALTO - RADIO, vy: -Math.abs(p.vy) };
  let golpes = juego.golpes;
  const golpe = (yPaleta, lado) => {
    const relativo = (p.y - (yPaleta + PALETA.alto / 2)) / (PALETA.alto / 2);   // -1 arriba … 1 abajo
    const rapidez = Math.min(Math.hypot(p.vx, p.vy) * 1.05, VELOCIDAD * 2.2);
    const angulo = relativo * Math.PI / 4;
    golpes += 1;
    return { ...p, vx: Math.cos(angulo) * rapidez * lado, vy: Math.sin(angulo) * rapidez };
  };
  if (p.vx < 0 && chocaPaleta(p, juego.izq, 20)) p = { ...golpe(juego.izq, 1), x: 20 + PALETA.ancho + RADIO };
  if (p.vx > 0 && chocaPaleta(p, juego.der, ANCHO - 20 - PALETA.ancho)) p = { ...golpe(juego.der, -1), x: ANCHO - 20 - PALETA.ancho - RADIO };
  const puntos = [...juego.puntos];
  if (p.x < -RADIO) { puntos[1] += 1; p = saque(-1, azar); }
  else if (p.x > ANCHO + RADIO) { puntos[0] += 1; p = saque(1, azar); }
  const ganador = puntos[0] >= aGanar ? 0 : puntos[1] >= aGanar ? 1 : null;
  return { ...juego, pelota: p, puntos, ganador, golpes };
}
''',
        "app.js": r'''
import { ALTO, ANCHO, PALETA, RADIO, ia, moverPaleta, nuevoJuego, paso } from './src/pong.js';

const lienzo = document.querySelector('canvas');
const ctx = lienzo.getContext('2d');
lienzo.width = ANCHO; lienzo.height = ALTO;
let juego = nuevoJuego();
let direccion = 0;
let toqueY = null;

addEventListener('keydown', (e) => { if (e.key === 'ArrowUp' || e.key === 'w') direccion = -1; if (e.key === 'ArrowDown' || e.key === 's') direccion = 1; if (e.key === ' ' && juego.ganador !== null) juego = nuevoJuego(); });
addEventListener('keyup', () => { direccion = 0; });
lienzo.addEventListener('pointermove', (e) => { const r = lienzo.getBoundingClientRect(); toqueY = (e.clientY - r.top) * ALTO / r.height; });
lienzo.addEventListener('pointerdown', () => { if (juego.ganador !== null) juego = nuevoJuego(); });
lienzo.addEventListener('pointerleave', () => { toqueY = null; });

let anterior = performance.now();
function cuadro(ahora) {
  const dt = Math.min(0.033, (ahora - anterior) / 1000);
  anterior = ahora;
  const izq = toqueY !== null
    ? Math.max(0, Math.min(ALTO - PALETA.alto, toqueY - PALETA.alto / 2))
    : moverPaleta(juego.izq, direccion, dt);
  juego = paso({ ...juego, izq, der: ia(juego, dt) }, dt);
  ctx.fillStyle = '#0d0d14'; ctx.fillRect(0, 0, ANCHO, ALTO);
  ctx.fillStyle = '#2a2a3a'; for (let y = 0; y < ALTO; y += 30) ctx.fillRect(ANCHO / 2 - 2, y, 4, 18);
  ctx.fillStyle = '#a78bfa';
  ctx.fillRect(20, juego.izq, PALETA.ancho, PALETA.alto);
  ctx.fillRect(ANCHO - 20 - PALETA.ancho, juego.der, PALETA.ancho, PALETA.alto);
  ctx.beginPath(); ctx.arc(juego.pelota.x, juego.pelota.y, RADIO, 0, Math.PI * 2); ctx.fill();
  ctx.font = '48px system-ui'; ctx.textAlign = 'center';
  ctx.fillText(`${juego.puntos[0]}   ${juego.puntos[1]}`, ANCHO / 2, 60);
  if (juego.ganador !== null) {
    ctx.font = '32px system-ui';
    ctx.fillText(juego.ganador === 0 ? '¡Ganaste! Tocá para jugar otra vez' : 'Ganó la compu. Tocá para revancha', ANCHO / 2, ALTO / 2);
  }
  requestAnimationFrame(cuadro);
}
requestAnimationFrame(cuadro);
''',
        "index.html": r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <title>__TITULO__</title>
  <style>
    body { margin: 0; background: #0d0d14; display: grid; place-items: center; height: 100vh; color: #888; font-family: system-ui; }
    canvas { width: min(100vw, 160vh); aspect-ratio: 8 / 5; touch-action: none; border-radius: .5rem; }
  </style>
</head>
<body>
  <canvas></canvas>
  <p>Mové el dedo sobre la cancha (o ↑/↓). Primero a 7.</p>
  <script type="module" src="app.js"></script>
</body>
</html>
''',
        "tests/pong.test.mjs": r'''
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ALTO, ANCHO, PALETA, RADIO, ia, moverPaleta, nuevoJuego, paso } from '../src/pong.js';

const fijo = () => 0.5;   // saque derecho, sin ángulo

test('rebota en el techo', () => {
  const j = { ...nuevoJuego(fijo), pelota: { x: 400, y: RADIO + 1, vx: 0, vy: -300 } };
  const s = paso(j, 0.02, { azar: fijo });
  assert.ok(s.pelota.vy > 0);
  assert.ok(s.pelota.y >= RADIO);
});

test('la paleta devuelve la pelota y acelera', () => {
  const j = { ...nuevoJuego(fijo), izq: 200, pelota: { x: 45, y: 245, vx: -300, vy: 0 } };
  const s = paso(j, 0.02, { azar: fijo });
  assert.ok(s.pelota.vx > 0);
  assert.equal(s.golpes, 1);
  assert.ok(Math.hypot(s.pelota.vx, s.pelota.vy) > 300);
});

test('punto y ganador', () => {
  let j = { ...nuevoJuego(fijo), izq: 0, puntos: [0, 6], pelota: { x: 2, y: ALTO - 20, vx: -400, vy: 0 } };
  j = paso(j, 0.05, { azar: fijo });
  assert.deepEqual(j.puntos, [0, 7]);
  assert.equal(j.ganador, 1);
  assert.equal(j.pelota.x, ANCHO / 2);
  assert.equal(paso(j, 1, { azar: fijo }), j);   // terminado: no cambia más
});

test('paletas dentro de la cancha y la IA sigue la pelota', () => {
  assert.equal(moverPaleta(5, -1, 1), 0);
  assert.equal(moverPaleta(ALTO, 1, 1), ALTO - PALETA.alto);
  const j = { ...nuevoJuego(fijo), der: 0, pelota: { x: 600, y: 400, vx: 300, vy: 0 } };
  assert.ok(ia(j, 0.1) > 0);
});
''',
    },
    comando_tests=_NODE_TESTS,
    comando_ejecutar="python3 -m http.server 8080",
    etiquetas=("juego", "pong", "canvas", "web", "tactil"),
    requiere=("node",),
)
