<div align="center">

```
█▀▀▄ █▀▀▀ ▄▀▀▄ █▀▀▄ █▀▀▀ █▀▀▄
█▄▄▀ █▄▄  █▄▄█ █▄▄▀ █▄▄  █▄▄▀
█  █ █▄▄▄ █  █ █    █▄▄▄ █  █
```

### 🐉 REAPER · agente de programación autónomo para tu teléfono

*Un solo archivo de Python. Corre en Termux. Habla español. No miente sobre lo que hizo.*

![versión](https://img.shields.io/badge/versión-8.10-8b5cf6)
![python](https://img.shields.io/badge/python-3.11%20–%203.14-3776ab)
![autotests](https://img.shields.io/badge/autotests-954%20OK-2ea44f)
![plataforma](https://img.shields.io/badge/Termux%20·%20Android-sin%20root-10b981)
![un archivo](https://img.shields.io/badge/distribución-un%20solo%20archivo-f59e0b)
![estado](https://img.shields.io/badge/estado-experimental-orange)

</div>

---

## ¿Qué es?

**REAPER** es un agente de programación que trabaja **dentro de un proyecto real**: lee, edita y ejecuta
de verdad, escribe tests, repara lo que falla y **verifica** antes de decir que terminó. Está pensado para
correr en un **teléfono con Termux** (sin root, con poca RAM) y para enrutar a **varios proveedores de modelos**
—los que vos elijas, gratuitos o de pago— en vez de atarte a uno solo.

Su obsesión es la **honestidad**: no declara una build "verificada" sin tests reales en verde, no finge que
una suite pasó cuando en realidad se salteó, y un **juez de entrega** revisa al final que lo construido
**cumpla el pedido tal como se pidió**.

> [!NOTE]
> Es un proyecto **experimental**. El andamiaje está probado con 954 autotests; la calidad del código que
> produzca depende del modelo que le conectes. Mirá **[Estado honesto](#-estado-honesto)**.

---

## ✨ Qué trae

- 🧩 **Un solo archivo** — `reaper_8.10_fusionado.py`. Lo copiás al teléfono y lo corrés. Sin instalar nada raro.
- 🤖 **Equipo de 8 agentes** — coordinador, arquitecto, implementador, revisor, QA y reparador, con **respaldo
  entre modelos** + un **8.º agente: el juez de entrega**.
- ⚖️ **Juez de entrega (motor central)** — define el contrato desde tu pedido, vigila la cobertura, juzga la
  entrega contra ese contrato y, si falta algo, **interviene** para cerrarlo. De muy bajo costo: es
  mayormente determinista y solo gasta tokens cuando hace falta.
- 🧪 **Tests primero** — escribe la especificación ejecutable antes de implementar (cuando el proyecto lo amerita).
- 🏆 **Torneo por tarea** — varios implementadores compiten en copias aisladas; gana el que pasa más tests.
- 🧭 **Grafo de tareas** — ordena por dependencias y descompone proyectos grandes por módulo.
- 🔁 **Reparación con escalada** — ante un fallo repetido, sube a un modelo más fuerte.
- 🔌 **Multi-proveedor** — ruteo por modelo a distintos endpoints/claves (OpenRouter, Groq, Gemini, NVIDIA…).
- 🛡️ **Honestidad a prueba de falsos verdes** — ✓ solo con `exit 0` y tests reales; 0 tests ≠ éxito.
- 🎨 **Linda en la terminal** — dragón de arranque, panel de estado, fases con acento y **5 temas**
  (`dragon`, `oceano`, `matrix`, `clasico`, `mono`).

---

## 🚀 Empezar (Termux)

```bash
# 1) Descargá el archivo único
curl -fL -o reaper.py \
  https://raw.githubusercontent.com/celparaguayy-cloud/Reaper.py/ccr-6e025352-3tb6n4/entrega_fusion/reaper_8.10_fusionado.py

# 2) Configurá al menos una clave de proveedor (una sola vez, por entorno)
export OPENROUTER_API_KEY=...        # o GROQ_API_KEY / GEMINI_API_KEY / NVIDIA_API_KEY ...

# 3) Corré
python3 reaper.py                    # modo interactivo
python3 reaper.py --autotest         # corre la batería de pruebas
python3 reaper.py --doctor           # chequeo del entorno
python3 reaper.py --instalar         # deja el comando `reaper` listo
```

Dentro, escribí en lenguaje natural o usá un comando:

```
❯ construí una web con login y listado de productos
❯ /construir una API de tareas con SQLite y tests
❯ /validar          ·  revisa tu config de modelos/equipo (sin tocar la red)
❯ /diagnostico      ·  reporte para pegar si algo falla (nunca incluye tus claves)
❯ /equipo           ·  ves los 8 agentes y a qué modelo apunta cada uno
❯ /ayuda            ·  todos los comandos
```

---

## ⚖️ El juez de entrega, en una línea

> Verifica que **la orden se haya hecho y se entregue tal como se pidió** — y si no, interviene.
> Solo puede **endurecer** el resultado (verde → parcial): **nunca** convierte una build roja en verde.

---

## 🧱 Cómo está hecho

REAPER se escribe en piezas (`partes/NN_*.py`) y se **empaqueta** en un único archivo:

```bash
python3 empaquetar.py        # partes/*.py  →  reaper_v8.py  (130 partes, un solo espacio de nombres)
python3 reaper_v8.py --autotest
```

Así es fácil de leer y mantener por módulos, pero se distribuye como **un archivo** que corre en cualquier
lado sin dependencias de paquetería.

---

## 🧰 Comandos (muestra)

| Comando | Qué hace |
|---|---|
| `/construir <pedido>` | explora → planifica → tests primero → torneo → verifica → repara → juez |
| `/plan <pedido>` | solo exploración + plan (se guarda en `.reaper/planes`) |
| `/equipo` · `/equipo probar` | ruteo de los 8 agentes · prueba real de conectividad |
| `/modelo` · `/modelo elegir` · `/modelo buscar <texto>` | modelo principal/por rol · selector · búsqueda |
| `/validar` · `/diagnostico` | valida la config de modelos · reporte redactado (sin claves) |
| `/tema <nombre>` | cambia la paleta de colores |
| `/deshacer` · `/diff` | revierte la última build · ve los cambios |

Hay **64** comandos en total; `/ayuda` los lista todos.

---

## 🔎 Estado honesto

Lo que **sí** está verificado y lo que **no**, sin maquillaje:

- ✅ **954 autotests OK** en Python **3.11, 3.12 y 3.13** (y en el Termux real del usuario con 3.14). Prueban la
  **orquestación** de forma determinista: ediciones y procesos reales, parseo de tests, gates de honestidad,
  Ctrl+C, plazos, el juez. Usan un **modelo simulado** (MockLLM) para la red de modelos.
- ⚠️ **No verificado con modelos reales** en este repositorio (sin claves): la **calidad del código** que
  produzca depende del modelo que conectes. El andamiaje sube el piso; no inventa capacidad que el modelo no tenga.
- ⚠️ **"Proyectos grandes"**: el andamiaje para escala existe (mapa de archivos relevantes, subagentes por tarea,
  grafo de dependencias, reanudación entre sesiones, compactación de contexto). Que un proyecto grande salga
  **bien** sigue dependiendo del modelo elegido.

En resumen: **la máquina no te va a mentir sobre lo que hizo**; la calidad la pone el modelo.

---

## 🤝 Desarrollo

```bash
# editás en partes/, re-empaquetás y corrés la suite
python3 empaquetar.py && python3 reaper_v8.py --autotest
# filtrar una clase de tests
REAPER_AUTOTEST=juez python3 reaper_v8.py --autotest
```

Reglas que se mantienen entre versiones: no declarar éxito sin evidencia ejecutada, no modificar tests para
ocultar defectos, los mocks nunca como única evidencia, no aflojar permisos ni autorizaciones, y las **claves
solo por entorno** — nunca en el repo, los logs o los diagnósticos.

<div align="center">

---

*Hecho para programar desde el teléfono, con honestidad.* 🐉

</div>
