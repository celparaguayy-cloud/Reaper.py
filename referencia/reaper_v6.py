#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REAPER v6.0.0 — agente de programación autónomo para Termux vía OpenRouter
(estilo Claude Code / Codex, con subagentes y verificación real).

Archivo único generado desde reaper_core/ con empaquetar.py.

Instalar:
    pip install httpx pyflakes      (opcionales: sin httpx usa urllib)
    pkg install nodejs              (opcional: valida archivos JS)

Clave:
    export OPENROUTER_API_KEY="tu_key"

Ejecutar:
    python3 reaper_v6.py                                  modo interactivo (/ayuda)
    python3 reaper_v6.py --proyecto ~/mi_app              abre un workspace
    python3 reaper_v6.py -p "agregá tests a utils.py"     un pedido y sale
    python3 reaper_v6.py --construir "API de notas" --auto
"""

from __future__ import annotations

__version__ = "6.0.0"

import argparse
import ast
import difflib
import fnmatch
import hashlib
import importlib.util
import io
import itertools
import json
import os
import platform
import random
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterator, Optional, Union


# ======================================================================
# MÓDULO: ui
# ======================================================================
"""Salida de consola: colores, diffs, progreso y confirmaciones. Thread-safe."""



_USAR_COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")


def _c(codigo: str) -> str:
    return codigo if _USAR_COLOR else ""


class C:
    RESET = _c("\033[0m")
    BOLD = _c("\033[1m")
    DIM = _c("\033[2m")
    CYAN = _c("\033[96m")
    VERDE = _c("\033[92m")
    AMARILLO = _c("\033[93m")
    ROJO = _c("\033[91m")
    MAGENTA = _c("\033[95m")
    AZUL = _c("\033[94m")
    GRIS = _c("\033[90m")
    BLANCO = _c("\033[97m")


SI = {"s", "si", "sí", "y", "yes"}


def recortar(texto: str, limite: int) -> str:
    texto = texto or ""
    if len(texto) <= limite:
        return texto
    mitad = max(1, limite // 2)
    return texto[:mitad].rstrip() + "\n...[recortado]...\n" + texto[-mitad:].lstrip()


class UI:
    """
    Toda la salida pasa por acá. En tests se usa UI(silencioso=True,
    respuestas=[...]) para no imprimir y contestar confirmaciones.
    """

    def __init__(
        self,
        *,
        silencioso: bool = False,
        interactivo: bool = True,
        respuestas: Optional[list] = None,
        entrada: Optional[Callable[[str], str]] = None,
    ):
        self.silencioso = silencioso
        self.interactivo = interactivo
        self._respuestas = list(respuestas or [])
        self._entrada = entrada or input
        self._lock = threading.RLock()
        self._progreso_visible = False
        self._ultimo_progreso = 0.0
        self.registro: list[str] = []

    # ------------------------------------------------------------ básico
    def _borrar_progreso(self) -> None:
        if self._progreso_visible:
            sys.stdout.write("\r\033[K" if _USAR_COLOR else "\r" + " " * 70 + "\r")
            sys.stdout.flush()
            self._progreso_visible = False

    def linea(self, texto: str = "") -> None:
        with self._lock:
            if self.silencioso:
                self.registro.append(texto)
                return
            self._borrar_progreso()
            print(texto, flush=True)

    def info(self, texto: str) -> None:
        self.linea(f"{C.CYAN}{texto}{C.RESET}")

    def ok(self, texto: str) -> None:
        self.linea(f"{C.VERDE}✓ {texto}{C.RESET}")

    def aviso(self, texto: str) -> None:
        self.linea(f"{C.AMARILLO}{texto}{C.RESET}")

    def error(self, texto: str) -> None:
        self.linea(f"{C.ROJO}✗ {texto}{C.RESET}")

    def tenue(self, texto: str) -> None:
        self.linea(f"{C.GRIS}{texto}{C.RESET}")

    def titulo(self, texto: str) -> None:
        self.linea(f"\n{C.CYAN}{C.BOLD}══ {texto} ══{C.RESET}")

    # ------------------------------------------------------------ agentes
    def agente(self, etiqueta: str, texto: str) -> None:
        self.linea(f"{C.MAGENTA}{C.BOLD}[{etiqueta}]{C.RESET} {texto}")

    def pensamiento(self, etiqueta: str, texto: str, limite: int = 700) -> None:
        texto = (texto or "").strip()
        if not texto:
            return
        self.linea(f"{C.MAGENTA}[{etiqueta}]{C.RESET} {C.BLANCO}{recortar(texto, limite)}{C.RESET}")

    def herramienta(self, etiqueta: str, nombre: str, detalle: str = "") -> None:
        detalle = detalle.replace("\n", " ")
        if len(detalle) > 90:
            detalle = detalle[:87] + "..."
        self.linea(f"{C.GRIS}  [{etiqueta}]{C.RESET} {C.AZUL}⚙ {nombre}{C.RESET} {C.GRIS}{detalle}{C.RESET}")

    def resultado_herramienta(self, ok: bool, texto: str) -> None:
        primera = (texto or "").strip().splitlines()[0] if (texto or "").strip() else ""
        if len(primera) > 110:
            primera = primera[:107] + "..."
        color = C.VERDE if ok else C.ROJO
        marca = "✓" if ok else "✗"
        self.linea(f"      {color}{marca}{C.RESET} {C.GRIS}{primera}{C.RESET}")

    def diff(self, texto: str, max_lineas: int = 60) -> None:
        lineas = (texto or "").splitlines()
        for linea in lineas[:max_lineas]:
            if linea.startswith("+") and not linea.startswith("+++"):
                self.linea(f"      {C.VERDE}{linea}{C.RESET}")
            elif linea.startswith("-") and not linea.startswith("---"):
                self.linea(f"      {C.ROJO}{linea}{C.RESET}")
            elif linea.startswith("@@"):
                self.linea(f"      {C.CYAN}{linea}{C.RESET}")
            else:
                self.linea(f"      {C.GRIS}{linea}{C.RESET}")
        if len(lineas) > max_lineas:
            self.tenue(f"      ... {len(lineas) - max_lineas} líneas más (/diff para ver todo)")

    def progreso(self, etiqueta: str, caracteres: int) -> None:
        if self.silencioso or not sys.stdout.isatty():
            return
        ahora = time.monotonic()
        if ahora - self._ultimo_progreso < 0.15:
            return
        self._ultimo_progreso = ahora
        with self._lock:
            sys.stdout.write(f"\r{C.GRIS}  [{etiqueta}] generando… {caracteres} caracteres{C.RESET}")
            sys.stdout.flush()
            self._progreso_visible = True

    def fin_progreso(self) -> None:
        with self._lock:
            self._borrar_progreso()

    # ------------------------------------------------------------ entrada
    def confirmar(self, pregunta: str, defecto: bool = False) -> bool:
        if self._respuestas:
            respuesta = self._respuestas.pop(0)
            return bool(respuesta) if not isinstance(respuesta, str) else respuesta.strip().lower() in SI
        if not self.interactivo:
            return defecto
        with self._lock:
            self._borrar_progreso()
            try:
                texto = self._entrada(f"{C.AMARILLO}{pregunta} (s/n) {C.RESET}")
            except EOFError:
                return defecto
        return texto.strip().lower() in SI

    def preguntar(self, pregunta: str) -> str:
        if self._respuestas:
            return str(self._respuestas.pop(0))
        if not self.interactivo:
            return ""
        with self._lock:
            self._borrar_progreso()
            try:
                return self._entrada(f"{C.AMARILLO}{pregunta}{C.RESET}\n{C.VERDE}› {C.RESET}").strip()
            except EOFError:
                return ""


# ======================================================================
# MÓDULO: config
# ======================================================================
"""Rutas, modelos y configuración persistente de REAPER."""



BASE_DIR = Path(os.getenv("REAPER_HOME") or (Path.home() / "reaper")).expanduser()
PROJECTS_DIR = BASE_DIR / "proyectos"
CHECKPOINTS_DIR = BASE_DIR / "checkpoints"
SESIONES_DIR = BASE_DIR / "sesiones"
CONFIG_FILE = BASE_DIR / "config.json"
ESTADO_FILE = BASE_DIR / "estado.json"

API_URL = os.getenv("REAPER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

MODELOS = {
    "venice": "cognitivecomputations/dolphin-mistral-24b-venice-edition",
    "venice-free": "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "hermes": "nousresearch/hermes-3-llama-3.1-70b",
    "qwen": "qwen/qwen-2.5-coder-32b-instruct",
    "qwen72": "qwen/qwen-2.5-72b-instruct",
    "deepseek": "deepseek/deepseek-chat",
}

MODOS = ("confirmar", "auto-edicion", "auto")


def resolver_modelo(nombre: str) -> str:
    nombre = (nombre or "").strip()
    return MODELOS.get(nombre.lower(), nombre)


@dataclass
class Settings:
    # Modelo principal y overrides por rol, p. ej. {"revisor": "qwen"}.
    modelo: str = MODELOS["venice"]
    modelos_rol: dict = field(default_factory=dict)
    # Modelos de respaldo si el principal falla (404, 402, caídas persistentes).
    fallbacks: list = field(default_factory=list)

    temperatura: float = 0.2
    max_tokens: int = 6000
    # Venice 24B tiene 32k de contexto: REAPER compacta antes de llegar al límite.
    contexto_tokens: int = 32768
    timeout: int = 180
    reintentos: int = 4

    # confirmar: pregunta antes de editar y de correr comandos.
    # auto-edicion: edita solo (con checkpoint para /deshacer), pregunta comandos.
    # auto: todo automático salvo comandos bloqueados.
    modo: str = "auto-edicion"

    max_pasos: int = 40
    max_pasos_sub: int = 25
    max_profundidad: int = 1
    max_llamadas_turno: int = 4
    max_reparaciones: int = 3
    max_revisiones: int = 2
    max_tareas: int = 8
    paralelo: int = 2
    qa: bool = True

    exec_timeout: int = 90
    tests_timeout: int = 300

    def modelo_para(self, rol: str) -> str:
        return resolver_modelo(self.modelos_rol.get(rol) or self.modelo)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def desde_dict(cls, data: dict) -> "Settings":
        base = cls()
        tipos = {f.name: type(getattr(base, f.name)) for f in fields(cls)}
        valores = {}
        for clave, valor in (data or {}).items():
            tipo = tipos.get(clave)
            if tipo is None:
                continue
            if tipo is float and isinstance(valor, int):
                valor = float(valor)
            if isinstance(valor, tipo) and not (tipo is int and isinstance(valor, bool)):
                valores[clave] = valor
        return cls(**valores)


def asegurar_dirs() -> None:
    for carpeta in (BASE_DIR, PROJECTS_DIR, CHECKPOINTS_DIR, SESIONES_DIR):
        carpeta.mkdir(parents=True, exist_ok=True)


def cargar_settings(ruta: Optional[Path] = None) -> Settings:
    ruta = ruta or CONFIG_FILE
    settings = Settings()
    if ruta.exists():
        try:
            settings = Settings.desde_dict(json.loads(ruta.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            settings = Settings()

    if os.getenv("MODEL_NAME"):
        settings.modelo = resolver_modelo(os.environ["MODEL_NAME"])
    if os.getenv("REAPER_MODO") in MODOS:
        settings.modo = os.environ["REAPER_MODO"]
    if settings.modo not in MODOS:
        settings.modo = "auto-edicion"
    return settings


def guardar_settings(settings: Settings, ruta: Optional[Path] = None) -> None:
    ruta = ruta or CONFIG_FILE
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ruta)


def cargar_estado() -> dict:
    try:
        data = json.loads(ESTADO_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_estado(**valores) -> None:
    data = cargar_estado()
    data.update({k: v for k, v in valores.items()})
    try:
        ESTADO_FILE.parent.mkdir(parents=True, exist_ok=True)
        ESTADO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# ======================================================================
# MÓDULO: llm
# ======================================================================
"""Cliente OpenRouter: streaming, reintentos con backoff, modelos de respaldo y uso."""




try:  # httpx es opcional: sin él se usa urllib (streaming igual).
    import httpx
except ImportError:  # pragma: no cover - depende del entorno
    httpx = None


class LLMError(RuntimeError):
    def __init__(self, mensaje: str, *, probar_otro_modelo: bool = False):
        super().__init__(mensaje)
        self.probar_otro_modelo = probar_otro_modelo


class _Transitorio(Exception):
    """Error que vale la pena reintentar (429, 5xx, red, respuesta vacía)."""

    def __init__(self, mensaje: str, espera: Optional[float] = None):
        super().__init__(mensaje)
        self.espera = espera


@dataclass
class Respuesta:
    texto: str
    finish_reason: Optional[str] = None
    modelo: str = ""


@dataclass
class Uso:
    llamadas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo: float = 0.0


MENSAJES_HTTP = {
    400: "Pedido rechazado por el proveedor (¿contexto demasiado largo?).",
    401: "Clave API inválida, revocada o ausente.",
    402: "La cuenta no tiene crédito suficiente para este modelo.",
    403: "Acceso denegado por el proveedor (moderación o permisos).",
    404: "Modelo o endpoint no disponible.",
    408: "El proveedor tardó demasiado.",
    429: "Límite de solicitudes alcanzado.",
}

TRANSITORIOS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}


def _lanzar_http(status: int, cuerpo: str, retry_after: Optional[str]) -> None:
    detalle = " ".join((cuerpo or "").split())[:400]
    motivo = MENSAJES_HTTP.get(status, "Error HTTP del proveedor.")
    if status in TRANSITORIOS:
        espera = None
        try:
            espera = float(retry_after) if retry_after else None
        except ValueError:
            espera = None
        raise _Transitorio(f"{motivo} HTTP {status}. {detalle}".strip(), espera)
    raise LLMError(
        f"{motivo} HTTP {status}. {detalle}".strip(),
        probar_otro_modelo=status in (400, 402, 403, 404),
    )


def _transporte_httpx(url: str, headers: dict, payload: dict, timeout: int) -> Iterator[str]:
    try:
        with httpx.stream(
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=httpx.Timeout(timeout, connect=30),
        ) as r:
            if r.status_code >= 400:
                # En streaming hay que leer el cuerpo antes de usarlo.
                cuerpo = r.read().decode("utf-8", "replace")
                _lanzar_http(r.status_code, cuerpo, r.headers.get("retry-after"))
            for linea in r.iter_lines():
                yield linea
    except httpx.TimeoutException as e:
        raise _Transitorio(f"El modelo no respondió dentro de {timeout}s.") from e
    except httpx.RequestError as e:
        raise _Transitorio(f"Error de red hablando con OpenRouter: {e}") from e


def _transporte_urllib(url: str, headers: dict, payload: dict, timeout: int) -> Iterator[str]:
    datos = json.dumps(payload).encode("utf-8")
    pedido = urllib.request.Request(url, data=datos, headers=headers, method="POST")
    try:
        respuesta = urllib.request.urlopen(pedido, timeout=timeout)
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace") if e.fp else ""
        _lanzar_http(e.code, cuerpo, e.headers.get("Retry-After") if e.headers else None)
        return
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        raise _Transitorio(f"Error de red hablando con OpenRouter: {e}") from e

    with respuesta:
        try:
            for crudo in respuesta:
                yield crudo.decode("utf-8", "replace").rstrip("\r\n")
        except (socket.timeout, TimeoutError, ConnectionError) as e:
            raise _Transitorio(f"Se cortó el streaming: {e}") from e


def parsear_linea_sse(linea: str):
    """Devuelve dict del evento, la cadena 'DONE' o None si la línea no aporta nada."""
    if not linea or not linea.startswith("data:"):
        return None
    datos = linea[5:].strip()
    if datos == "[DONE]":
        return "DONE"
    try:
        obj = json.loads(datos)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


Transporte = Callable[[str, dict, dict, int], Iterator[str]]


class LLMClient:
    def __init__(
        self,
        api_key: str,
        settings: Settings,
        url: str = API_URL,
        transporte: Optional[Transporte] = None,
    ):
        self.api_key = api_key
        self.settings = settings
        self.url = url
        self.uso = Uso()
        self._lock = threading.Lock()
        self._transporte = transporte or (_transporte_httpx if httpx else _transporte_urllib)
        self.dormir = time.sleep

    def chat(
        self,
        mensajes: list[dict],
        *,
        modelo: Optional[str] = None,
        temperatura: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> Respuesta:
        principal = resolver_modelo(modelo or self.settings.modelo)
        candidatos = [principal]
        for respaldo in self.settings.fallbacks:
            respaldo = resolver_modelo(respaldo)
            if respaldo and respaldo not in candidatos:
                candidatos.append(respaldo)

        ultimo: Optional[LLMError] = None
        for candidato in candidatos:
            try:
                return self._con_reintentos(
                    candidato, mensajes, temperatura, max_tokens, stop, on_progress
                )
            except LLMError as e:
                ultimo = e
                if not e.probar_otro_modelo:
                    raise
        assert ultimo is not None
        raise ultimo

    def _con_reintentos(self, modelo, mensajes, temperatura, max_tokens, stop, on_progress):
        payload = {
            "model": modelo,
            "messages": mensajes,
            "temperature": self.settings.temperatura if temperatura is None else temperatura,
            "max_tokens": max_tokens or self.settings.max_tokens,
            "stream": True,
            "usage": {"include": True},
        }
        if stop:
            payload["stop"] = stop

        intentos = max(0, int(self.settings.reintentos))
        for intento in range(intentos + 1):
            try:
                return self._una_vez(modelo, payload, on_progress)
            except _Transitorio as e:
                if intento >= intentos:
                    raise LLMError(
                        f"{e} (después de {intentos + 1} intentos)",
                        probar_otro_modelo=True,
                    ) from e
                espera = e.espera
                if espera is None:
                    espera = min(60.0, 2.0 * (2 ** intento)) + random.uniform(0, 1)
                self.dormir(min(espera, 120.0))
        raise LLMError("No se obtuvo respuesta del modelo.")  # pragma: no cover

    def _una_vez(self, modelo: str, payload: dict, on_progress) -> Respuesta:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "REAPER",
        }
        partes: list[str] = []
        total = 0
        finish = None

        for linea in self._transporte(self.url, headers, payload, self.settings.timeout):
            evento = parsear_linea_sse(linea)
            if evento is None:
                continue
            if evento == "DONE":
                break

            if "error" in evento:
                err = evento["error"]
                mensaje = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                codigo = err.get("code") if isinstance(err, dict) else None
                if codigo is None or codigo in TRANSITORIOS:
                    raise _Transitorio(f"Error del proveedor durante el streaming: {mensaje}")
                raise LLMError(f"Error del proveedor: {mensaje}", probar_otro_modelo=True)

            uso = evento.get("usage")
            if isinstance(uso, dict):
                self._registrar_uso(uso)

            for choice in evento.get("choices") or []:
                delta = choice.get("delta") or {}
                contenido = delta.get("content")
                if contenido:
                    partes.append(contenido)
                    total += len(contenido)
                    if on_progress:
                        on_progress(total)
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]

        with self._lock:
            self.uso.llamadas += 1

        texto = "".join(partes)
        if not texto.strip():
            raise _Transitorio("El modelo devolvió una respuesta vacía.")
        return Respuesta(texto=texto, finish_reason=finish, modelo=modelo)

    def _registrar_uso(self, uso: dict) -> None:
        with self._lock:
            self.uso.tokens_entrada += int(uso.get("prompt_tokens") or 0)
            self.uso.tokens_salida += int(uso.get("completion_tokens") or 0)
            try:
                self.uso.costo += float(uso.get("cost") or 0.0)
            except (TypeError, ValueError):
                pass


# ======================================================================
# MÓDULO: protocol
# ======================================================================
"""
Protocolo de herramientas en texto, estilo XML.

Por qué texto y no "function calling" nativo: Venice 24B (y muchos modelos
de OpenRouter) no soportan tools nativas de forma confiable. Las etiquetas
XML no necesitan escapar comillas ni saltos de línea, así que el modelo puede
escribir código crudo dentro de <content> sin romper nada (el gran punto
débil del JSON multiarchivo de v5).

El parser es tolerante: acepta alias de herramientas y parámetros, el formato
<tool name="x">, un único parámetro sin etiqueta, bloques ``` alrededor del
código y, como último recurso, un objeto JSON {"tool": ..., "args": {...}}.
"""



# Nunca usar como alias nombres que coincidan con parámetros (task, path, diff...).
ALIAS_HERRAMIENTAS = {
    "read": "read_file",
    "cat": "read_file",
    "open_file": "read_file",
    "view_file": "read_file",
    "leer_archivo": "read_file",
    "ls": "list_files",
    "list_dir": "list_files",
    "list_directory": "list_files",
    "listar_archivos": "list_files",
    "grep": "search_files",
    "search": "search_files",
    "buscar": "search_files",
    "outline": "code_outline",
    "repo_map": "code_outline",
    "write_file": "write_to_file",
    "create_file": "write_to_file",
    "escribir_archivo": "write_to_file",
    "edit_file": "replace_in_file",
    "apply_diff": "replace_in_file",
    "editar_archivo": "replace_in_file",
    "run_command": "execute_command",
    "bash": "execute_command",
    "shell": "execute_command",
    "ejecutar_comando": "execute_command",
    "run_test": "run_tests",
    "todo_write": "update_todo",
    "spawn_agent": "delegate",
    "subagent": "delegate",
    "delegar": "delegate",
    "finish": "attempt_completion",
    "final_answer": "attempt_completion",
    "complete": "attempt_completion",
    "terminar": "attempt_completion",
    "ask_followup_question": "ask_user",
    "preguntar": "ask_user",
}

ALIAS_PARAMS = {
    "path": ("file", "filepath", "file_path", "filename", "ruta", "archivo"),
    "command": ("cmd", "comando"),
    "content": ("contenido", "code", "codigo", "text"),
    "regex": ("pattern", "query", "patron"),
    "desde": ("start_line", "start", "linea_inicio"),
    "hasta": ("end_line", "end", "linea_fin"),
    "result": ("answer", "summary", "respuesta", "informe"),
    "role": ("rol", "agent", "agente"),
    "task": ("tarea", "prompt", "instrucciones"),
    "files": ("archivos",),
    "question": ("pregunta",),
    "diff": ("diffs", "changes", "cambios", "edits"),
    "items": ("todos", "lista"),
    "paths": ("rutas",),
}

_CORTE_RESULTADO = re.compile(
    r"<\s*(resultado|tool_result|observation|function_results?)\b", re.I
)
_FENCE = re.compile(r"\A\s*```[\w+#.-]*[ \t]*\r?\n(.*?)\r?\n?```\s*\Z", re.S)
_CDATA = re.compile(r"\A\s*<!\[CDATA\[(.*)\]\]>\s*\Z", re.S)


@dataclass
class Llamada:
    nombre: str
    params: dict = field(default_factory=dict)
    completa: bool = True
    crudo: str = ""


@dataclass
class Analisis:
    llamadas: list
    texto: str
    respuesta_limpia: str


# esquemas: {"write_to_file": [("path", False), ("content", True)], ...}
Esquemas = dict


def limpiar_largo(valor: str) -> str:
    v = valor
    if v.startswith("\r\n"):
        v = v[2:]
    elif v.startswith("\n"):
        v = v[1:]
    v = v.rstrip(" \t")
    if v.endswith("\r\n"):
        v = v[:-2]
    elif v.endswith("\n"):
        v = v[:-1]
    for patron in (_CDATA, _FENCE):
        m = patron.match(v)
        if m:
            v = m.group(1)
    return v


def _apertura(tag: str) -> re.Pattern:
    return re.compile(r"<\s*" + re.escape(tag) + r"\s*>", re.I)


def _cierre(tag: str) -> re.Pattern:
    return re.compile(r"<\s*/\s*" + re.escape(tag) + r"\s*>", re.I)


def _extraer_params(cuerpo: str, definicion: list) -> tuple[dict, bool]:
    params: dict = {}
    completa = True
    enmascarado = cuerpo

    # Primero los parámetros largos (código), y se enmascaran para que un
    # "<path>" dentro del código no se confunda con el parámetro path.
    ordenados = sorted(definicion, key=lambda d: not d[1])
    for nombre, largo in ordenados:
        for tag in (nombre, *ALIAS_PARAMS.get(nombre, ())):
            ap = _apertura(tag).search(enmascarado)
            if not ap:
                continue
            if largo:
                cierres = list(_cierre(tag).finditer(enmascarado, ap.end()))
                if cierres:
                    fin_valor, fin_total = cierres[-1].start(), cierres[-1].end()
                else:
                    fin_valor = fin_total = len(enmascarado)
                    completa = False
                params[nombre] = limpiar_largo(cuerpo[ap.end():fin_valor])
                enmascarado = (
                    enmascarado[:ap.start()]
                    + " " * (fin_total - ap.start())
                    + enmascarado[fin_total:]
                )
            else:
                c = _cierre(tag).search(enmascarado, ap.end())
                if c:
                    valor = cuerpo[ap.end():c.start()]
                else:
                    valor = cuerpo[ap.end():].split("\n", 1)[0]
                params[nombre] = valor.strip().strip("`'\"").strip()
            break

    if not params and definicion and cuerpo.strip():
        # Atajo: <read_file>app.py</read_file> o <attempt_completion>texto</attempt_completion>
        nombre, largo = definicion[0]
        if largo or not re.search(r"<\s*\w+\s*>", cuerpo):
            params[nombre] = limpiar_largo(cuerpo) if largo else cuerpo.strip()

    return params, completa


def _objetos_json(texto: str) -> list[dict]:
    candidatos = re.findall(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", texto, re.S)
    limpio = texto.strip()
    if limpio.startswith("{") and limpio.endswith("}"):
        candidatos.append(limpio)
    objetos = []
    for c in candidatos:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objetos.append(obj)
    return objetos


def _canonico_param(nombre: str) -> str:
    nombre = nombre.lower()
    for real, alias in ALIAS_PARAMS.items():
        if nombre == real or nombre in alias:
            return real
    return nombre


def analizar(texto: str, esquemas: Esquemas) -> Analisis:
    limpio = texto or ""
    corte = _CORTE_RESULTADO.search(limpio)
    if corte:
        # El modelo empezó a inventar el resultado de la herramienta: se descarta.
        limpio = limpio[:corte.start()].rstrip()

    nombres = {n.lower(): n for n in esquemas}
    for alias, real in ALIAS_HERRAMIENTAS.items():
        if real in esquemas:
            nombres.setdefault(alias, real)

    alternativas = "|".join(re.escape(n) for n in sorted(nombres, key=len, reverse=True))
    apertura = re.compile(
        r"<\s*(?:tool\s+name\s*=\s*[\"']?([A-Za-z_][\w-]*)[\"']?|(" + alternativas + r"))\s*>",
        re.I,
    )

    llamadas: list[Llamada] = []
    fuera: list[str] = []
    pos = 0
    while True:
        m = apertura.search(limpio, pos)
        if not m:
            fuera.append(limpio[pos:])
            break
        fuera.append(limpio[pos:m.start()])

        generico = m.group(1) is not None
        tag = m.group(1) or m.group(2)
        real = nombres.get(tag.lower(), tag.lower())
        cierre = _cierre("tool" if generico else tag)

        c = cierre.search(limpio, m.end())
        if c:
            cuerpo = limpio[m.end():c.start()]
            pos = c.end()
        else:
            siguiente = apertura.search(limpio, m.end())
            fin = siguiente.start() if siguiente else len(limpio)
            cuerpo = limpio[m.end():fin]
            pos = fin

        params, completa = _extraer_params(cuerpo, esquemas.get(real, []))
        llamadas.append(Llamada(real, params, completa, limpio[m.start():pos]))

    if not llamadas:
        for obj in _objetos_json(limpio):
            nombre = obj.get("tool") or obj.get("name") or obj.get("herramienta")
            if not isinstance(nombre, str):
                continue
            args = obj.get("args") or obj.get("arguments") or obj.get("parameters") or obj.get("params")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {k: v for k, v in obj.items() if k not in ("tool", "name", "herramienta")}
            real = ALIAS_HERRAMIENTAS.get(nombre.lower(), nombre.lower())
            params = {_canonico_param(k): v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                      for k, v in args.items()}
            llamadas.append(Llamada(real, params, True, json.dumps(obj, ensure_ascii=False)))
        if llamadas:
            fuera = []

    return Analisis(llamadas=llamadas, texto="".join(fuera).strip(), respuesta_limpia=limpio)


# ======================================================================
# MÓDULO: edits
# ======================================================================
"""
Motor de ediciones SEARCH/REPLACE tolerante.

Para un modelo de 24B, reescribir archivos completos es la principal fuente
de destrozos (se cortan, ponen "...resto igual", pierden funciones). Los
bloques SEARCH/REPLACE solo tocan lo necesario y, si el texto no coincide,
REAPER devuelve las líneas más parecidas para que el modelo corrija.

Estrategia de coincidencia (en orden):
1. texto exacto (debe ser único)
2. línea por línea ignorando espacios al final
3. línea por línea ignorando la indentación (y reindenta el reemplazo)
4. si el REPLACE ya está en el archivo, se considera ya aplicado
"""



_INICIO = re.compile(r"^\s*<{5,}\s*(SEARCH|BUSCAR|ORIGINAL)\s*$", re.I)
_SEPARADOR = re.compile(r"^\s*={5,}\s*$")
_FIN = re.compile(r"^\s*>{5,}\s*(REPLACE|REEMPLAZAR|UPDATED)?\s*$", re.I)
_NUMERO_LINEA = re.compile(r"^\s*\d+\s?[|│]\s?")

_MARCADORES_PEREZOSOS = re.compile(
    r"^\s*(#|//|/\*|<!--|--|;)?\s*(\.\.\.|…)\s*"
    r"(resto|el resto|existing|rest of|previous|unchanged|same|sin cambios|"
    r"c[oó]digo (anterior|existente|original)|igual|as before|remaining)"
    r"|^\s*(#|//|/\*|<!--)\s*(\.\.\.\s*)?(el )?(resto del (c[oó]digo|archivo)|rest of (the )?(code|file))",
    re.I | re.M,
)


class ErrorEdicion(ValueError):
    pass


@dataclass
class Bloque:
    buscar: str
    reemplazar: str


def tiene_marcadores_perezosos(texto: str) -> Optional[str]:
    m = _MARCADORES_PEREZOSOS.search(texto or "")
    return m.group(0).strip() if m else None


def parsear_bloques(diff: str) -> list[Bloque]:
    bloques: list[Bloque] = []
    estado = None
    buscar: list[str] = []
    reemplazar: list[str] = []

    for linea in (diff or "").splitlines(keepends=True):
        sin_fin = linea.rstrip("\r\n")
        if estado is None:
            if _INICIO.match(sin_fin):
                estado, buscar, reemplazar = "buscar", [], []
            continue
        if estado == "buscar":
            if _SEPARADOR.match(sin_fin):
                estado = "reemplazar"
            elif _INICIO.match(sin_fin):
                raise ErrorEdicion("Bloque mal formado: '<<<<<<< SEARCH' dos veces sin '======='.")
            else:
                buscar.append(linea)
            continue
        if estado == "reemplazar":
            if _FIN.match(sin_fin):
                bloques.append(Bloque("".join(buscar), "".join(reemplazar)))
                estado = None
            elif _INICIO.match(sin_fin):
                # Faltó el cierre ">>>>>>> REPLACE": se acepta y empieza otro bloque.
                bloques.append(Bloque("".join(buscar), "".join(reemplazar)))
                estado, buscar, reemplazar = "buscar", [], []
            else:
                reemplazar.append(linea)

    if estado == "reemplazar":
        bloques.append(Bloque("".join(buscar), "".join(reemplazar)))
    elif estado == "buscar":
        raise ErrorEdicion("Bloque incompleto: falta '=======' y la parte REPLACE.")

    if not bloques:
        raise ErrorEdicion(
            "No encontré bloques SEARCH/REPLACE. Formato obligatorio:\n"
            "<<<<<<< SEARCH\n(texto exacto actual)\n=======\n(texto nuevo)\n>>>>>>> REPLACE"
        )
    return [_quitar_numeros_de_linea(b) for b in bloques]


def _quitar_numeros_de_linea(bloque: Bloque) -> Bloque:
    """Si el modelo copió las líneas con el prefijo '  12| ' de read_file, se quita."""

    def limpiar(texto: str) -> str:
        lineas = texto.splitlines(keepends=True)
        no_vacias = [l for l in lineas if l.strip()]
        if no_vacias and all(_NUMERO_LINEA.match(l) for l in no_vacias):
            return "".join(_NUMERO_LINEA.sub("", l, count=1) if l.strip() else l for l in lineas)
        return texto

    return Bloque(limpiar(bloque.buscar), limpiar(bloque.reemplazar))


def _sin_lineas_vacias_extremas(lineas: list[str]) -> list[str]:
    inicio, fin = 0, len(lineas)
    while inicio < fin and not lineas[inicio].strip():
        inicio += 1
    while fin > inicio and not lineas[fin - 1].strip():
        fin -= 1
    return lineas[inicio:fin]


def _indent(linea: str) -> str:
    return linea[: len(linea) - len(linea.lstrip())]


def _reindentar(reemplazo: list[str], indent_buscar: str, indent_archivo: str) -> list[str]:
    if indent_buscar == indent_archivo:
        return reemplazo
    if indent_archivo.startswith(indent_buscar):
        extra = indent_archivo[len(indent_buscar):]
        return [extra + l if l.strip() else l for l in reemplazo]
    if indent_buscar.startswith(indent_archivo):
        sobra = len(indent_buscar) - len(indent_archivo)
        salida = []
        for l in reemplazo:
            quitar = min(sobra, len(_indent(l)))
            salida.append(l[quitar:] if l.strip() else l)
        return salida
    return reemplazo


def _buscar_ventanas(archivo: list[str], buscar: list[str], norm) -> list[int]:
    n = len(buscar)
    objetivo = [norm(l) for l in buscar]
    normalizado = [norm(l) for l in archivo]
    return [
        i for i in range(0, len(archivo) - n + 1)
        if normalizado[i:i + n] == objetivo
    ]


def lineas_parecidas(contenido: str, buscar: str, max_lineas: int = 18) -> str:
    archivo = contenido.splitlines()
    patron = _sin_lineas_vacias_extremas(buscar.splitlines())
    if not archivo or not patron or len(archivo) > 8000:
        return ""
    n = len(patron)
    objetivo = "\n".join(l.strip() for l in patron)
    candidatos = []
    for i in range(0, max(1, len(archivo) - n + 1)):
        ventana = "\n".join(l.strip() for l in archivo[i:i + n])
        sm = SequenceMatcher(None, objetivo, ventana, autojunk=False)
        candidatos.append((sm.quick_ratio(), i, ventana))
    candidatos.sort(reverse=True)
    mejor_ratio, mejor_i = 0.0, 0
    for _, i, ventana in candidatos[:25]:
        r = SequenceMatcher(None, objetivo, ventana, autojunk=False).ratio()
        if r > mejor_ratio:
            mejor_ratio, mejor_i = r, i
    if mejor_ratio < 0.35:
        return ""
    fin = min(len(archivo), mejor_i + max(n, 1))
    fin = min(fin, mejor_i + max_lineas)
    return "\n".join(f"{k + 1:>5}| {archivo[k]}" for k in range(mejor_i, fin))


def _aplicar_uno(contenido: str, bloque: Bloque) -> tuple[str, Optional[str]]:
    buscar, reemplazar = bloque.buscar, bloque.reemplazar

    if not buscar.strip():
        if not contenido.strip():
            return reemplazar, None
        raise ErrorEdicion(
            "SEARCH vacío solo sirve para archivos nuevos o vacíos. "
            "Para agregar texto, poné en SEARCH unas líneas existentes y repetilas en REPLACE junto con lo nuevo."
        )

    veces = contenido.count(buscar)
    if veces == 1:
        return contenido.replace(buscar, reemplazar, 1), None
    if veces > 1:
        raise ErrorEdicion(
            f"El texto de SEARCH aparece {veces} veces. Agregá líneas de contexto vecinas para que sea único."
        )

    archivo = contenido.splitlines(keepends=True)
    patron = _sin_lineas_vacias_extremas(buscar.splitlines())
    reemplazo = reemplazar.splitlines()
    if patron:
        for norm, reindentar in ((str.rstrip, False), (str.strip, True)):
            coincidencias = _buscar_ventanas(
                [l.rstrip("\r\n") for l in archivo], patron, norm
            )
            if len(coincidencias) > 1:
                raise ErrorEdicion(
                    f"El texto de SEARCH coincide en {len(coincidencias)} lugares. "
                    "Agregá contexto para hacerlo único."
                )
            if len(coincidencias) == 1:
                i = coincidencias[0]
                nuevas = reemplazo
                if reindentar:
                    j = next((k for k, l in enumerate(patron) if l.strip()), 0)
                    nuevas = _reindentar(
                        reemplazo, _indent(patron[j]), _indent(archivo[i + j].rstrip("\r\n"))
                    )
                fin = i + len(patron)
                ultima_sin_salto = fin == len(archivo) and not archivo[-1].endswith("\n")
                texto_nuevo = "".join(l + "\n" for l in nuevas)
                if ultima_sin_salto and texto_nuevo.endswith("\n"):
                    texto_nuevo = texto_nuevo[:-1]
                nota = None if not reindentar else "coincidencia ignorando indentación"
                return "".join(archivo[:i]) + texto_nuevo + "".join(archivo[fin:]), nota

    # Reintento de una edición que ya se aplicó: el REPLACE ya está en el archivo.
    # Solo con reemplazos suficientemente específicos para no dar falsos positivos.
    especifico = len([l for l in reemplazo if l.strip()]) >= 2 or len(reemplazar.strip()) >= 40
    if especifico and reemplazar.strip() in contenido:
        return contenido, "ya estaba aplicado"

    parecido = lineas_parecidas(contenido, buscar)
    mensaje = "No encontré el texto de SEARCH en el archivo. Copiá el texto EXACTO actual (sin números de línea)."
    if parecido:
        mensaje += "\nLas líneas más parecidas del archivo son:\n" + parecido
    else:
        mensaje += " Volvé a leer el archivo con read_file."
    raise ErrorEdicion(mensaje)


def aplicar_bloques(contenido: str, bloques: list[Bloque]) -> tuple[str, list[str]]:
    """Aplica todos los bloques o ninguno. Devuelve (nuevo_contenido, notas)."""
    notas: list[str] = []
    actual = contenido
    for numero, bloque in enumerate(bloques, start=1):
        try:
            actual, nota = _aplicar_uno(actual, bloque)
        except ErrorEdicion as e:
            prefijo = f"Bloque {numero} de {len(bloques)}: " if len(bloques) > 1 else ""
            raise ErrorEdicion(
                f"{prefijo}{e}\n(No se aplicó ningún cambio de esta edición.)"
            ) from None
        if nota:
            notas.append(f"bloque {numero}: {nota}")
    return actual, notas


# ======================================================================
# MÓDULO: workspace
# ======================================================================
"""Workspace seguro: rutas confinadas, escritura atómica, listado y checkpoints con deshacer."""



IGNORAR_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "env", "node_modules", "dist", "build",
    ".next", ".cache", "coverage", ".idea", ".vscode", ".reaper", ".tox",
    ".gradle", "target",
}

ARCHIVOS_SENSIBLES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "credentials.json", "secrets.json", ".netrc",
}

EXTENSIONES_TEXTO = {
    ".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".html", ".htm",
    ".css", ".scss", ".sql", ".go", ".rs", ".java", ".kt", ".php", ".rb",
    ".c", ".h", ".cpp", ".hpp", ".lua", ".ini", ".cfg", ".xml", ".svg",
    ".webmanifest", ".csv", ".env.example", ".gitignore",
}

NOMBRES_TEXTO = {
    "Makefile", "Dockerfile", "requirements.txt", "package.json",
    "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", "README",
    "LICENSE", ".gitignore", "REAPER.md",
}

PATRONES_SECRETOS = [
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\b(\s*[:=]\s*)[\"']?([^\s\"']{6,})"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]

MAX_BYTES_LECTURA = 1_000_000


class ErrorRuta(ValueError):
    pass


def redactar_secretos(texto: str) -> str:
    limpio = PATRONES_SECRETOS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTADO]", texto)
    for patron in PATRONES_SECRETOS[1:]:
        limpio = patron.sub("[REDACTADO]", limpio)
    return limpio


def escritura_atomica(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, temporal = tempfile.mkstemp(prefix=f".{ruta.name}.", suffix=".tmp", dir=str(ruta.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        if ruta.exists():
            try:
                shutil.copymode(ruta, temporal)
            except OSError:
                pass
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def es_binario(ruta: Path) -> bool:
    try:
        with open(ruta, "rb") as f:
            return b"\0" in f.read(2048)
    except OSError:
        return True


def diff_unificado(antes: str, despues: str, rel: str) -> str:
    return "".join(
        difflib.unified_diff(
            antes.splitlines(keepends=True),
            despues.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            n=2,
        )
    )


class Workspace:
    def __init__(self, raiz: Path, checkpoints_dir: Optional[Path] = None):
        self.raiz = Path(raiz).expanduser().resolve()
        if not self.raiz.is_dir():
            raise ErrorRuta(f"No es una carpeta: {self.raiz}")
        if checkpoints_dir is None:
            pass
            checkpoints_dir = CHECKPOINTS_DIR
        clave = hashlib.sha1(str(self.raiz).encode()).hexdigest()[:10]
        self.checkpoints = Checkpoints(self, Path(checkpoints_dir) / f"{self.raiz.name}_{clave}")
        self._ignorar: list[str] = []
        self._gitignore_mtime: Optional[float] = None

    # ------------------------------------------------------------ rutas
    def ruta(self, rel: str, *, escribir: bool = False) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise ErrorRuta("Ruta vacía.")
        texto = rel.strip().strip("`'\"").strip()
        if texto.startswith("./"):
            texto = texto[2:]
        candidato = Path(os.path.expandvars(texto)).expanduser()
        if not candidato.is_absolute():
            candidato = self.raiz / candidato
        destino = candidato.resolve()
        try:
            relativa = destino.relative_to(self.raiz)
        except ValueError:
            raise ErrorRuta(f"Ruta fuera del workspace: {rel}") from None
        if escribir:
            if destino.name in ARCHIVOS_SENSIBLES:
                raise ErrorRuta(f"Archivo sensible protegido: {rel}")
            if relativa.parts and relativa.parts[0] == ".git":
                raise ErrorRuta("No se escribe dentro de .git")
            if destino == self.raiz:
                raise ErrorRuta("La ruta apunta a la raíz del workspace, no a un archivo.")
        return destino

    def rel(self, ruta: Path) -> str:
        try:
            return Path(ruta).resolve().relative_to(self.raiz).as_posix()
        except ValueError:
            return str(ruta)

    # ------------------------------------------------------------ lectura/escritura
    def leer(self, rel: str) -> str:
        ruta = self.ruta(rel)
        if not ruta.is_file():
            raise FileNotFoundError(rel)
        if ruta.stat().st_size > MAX_BYTES_LECTURA:
            raise ValueError(f"Archivo demasiado grande para leer entero ({ruta.stat().st_size} bytes).")
        return ruta.read_text(encoding="utf-8", errors="replace")

    def escribir(self, rel: str, contenido: str) -> Path:
        ruta = self.ruta(rel, escribir=True)
        if ruta.is_dir():
            raise ErrorRuta(f"{rel} es una carpeta.")
        self.checkpoints.registrar(self.rel(ruta))
        escritura_atomica(ruta, contenido)
        return ruta

    # ------------------------------------------------------------ listado
    def _patrones_gitignore(self) -> list[str]:
        """Se recarga si .gitignore cambia (el agente o el usuario pueden editarlo en la sesión)."""
        archivo = self.raiz / ".gitignore"
        try:
            mtime = archivo.stat().st_mtime
        except OSError:
            self._ignorar, self._gitignore_mtime = [], None
            return self._ignorar
        if mtime != self._gitignore_mtime:
            patrones = []
            try:
                for linea in archivo.read_text(encoding="utf-8").splitlines():
                    linea = linea.strip()
                    if linea and not linea.startswith(("#", "!")):
                        patrones.append(linea)
            except OSError:
                pass
            self._ignorar, self._gitignore_mtime = patrones, mtime
        return self._ignorar

    def ignorado(self, rel: str, es_dir: bool) -> bool:
        nombre = rel.rsplit("/", 1)[-1]
        if es_dir and nombre in IGNORAR_DIRS:
            return True
        for patron in self._patrones_gitignore():
            solo_dir = patron.endswith("/")
            p = patron.strip("/")
            if solo_dir and not es_dir:
                continue
            if "/" in p:
                if fnmatch.fnmatch(rel, p):
                    return True
            elif fnmatch.fnmatch(nombre, p):
                return True
        return False

    def iterar(self, sub: str = ".", limite: int = 2000) -> Iterator[Path]:
        base = self.ruta(sub) if sub not in ("", ".") else self.raiz
        if base.is_file():
            yield base
            return
        contador = 0
        for actual, dirs, archivos in os.walk(base):
            rel_actual = self.rel(Path(actual))
            rel_actual = "" if rel_actual == "." else rel_actual
            dirs[:] = sorted(
                d for d in dirs
                if not self.ignorado(f"{rel_actual}/{d}".lstrip("/"), True)
            )
            for nombre in sorted(archivos):
                rel = f"{rel_actual}/{nombre}".lstrip("/")
                if self.ignorado(rel, False):
                    continue
                yield Path(actual) / nombre
                contador += 1
                if contador >= limite:
                    return

    def es_texto(self, ruta: Path) -> bool:
        if ruta.name in ARCHIVOS_SENSIBLES:
            return False
        return ruta.suffix.lower() in EXTENSIONES_TEXTO or ruta.name in NOMBRES_TEXTO

    def archivos_codigo(self, limite: int = 400) -> list[str]:
        return [self.rel(p) for p in self.iterar(limite=limite * 3) if self.es_texto(p)][:limite]

    def arbol(self, limite: int = 120) -> str:
        lineas = []
        total = 0
        for ruta in self.iterar(limite=5000):
            total += 1
            if len(lineas) < limite:
                lineas.append(self.rel(ruta))
        if not lineas:
            return "(workspace vacío)"
        if total > limite:
            lineas.append(f"... y {total - limite} archivos más (usá list_files o search_files)")
        return "\n".join(lineas)

    def es_git(self) -> bool:
        return (self.raiz / ".git").exists()

    def memoria(self, limite: int = 4000) -> str:
        for nombre in ("REAPER.md", "CLAUDE.md", "AGENTS.md"):
            ruta = self.raiz / nombre
            if ruta.is_file():
                try:
                    texto = ruta.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                return f"({nombre})\n" + texto[:limite]
        return ""

    def config_local(self) -> dict:
        ruta = self.raiz / ".reaper" / "config.json"
        try:
            data = json.loads(ruta.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}


class Checkpoints:
    """
    Antes de cada escritura se guarda el original del archivo dentro del
    checkpoint activo. Un checkpoint por pedido (o por tarea en /construir);
    los checkpoints de una misma build comparten 'grupo' para deshacerla entera.
    """

    def __init__(self, ws: Workspace, carpeta: Path):
        self.ws = ws
        self.carpeta = carpeta
        self.actual: Optional[int] = None
        self._lock = threading.RLock()

    def _dir(self, cid: int) -> Path:
        return self.carpeta / f"{cid:05d}"

    def _manifiesto(self, cid: int) -> dict:
        try:
            return json.loads((self._dir(cid) / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"id": cid, "etiqueta": "?", "grupo": cid, "fecha": "", "archivos": {}}

    def _guardar(self, cid: int, manifiesto: dict) -> None:
        destino = self._dir(cid) / "manifest.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        escritura_atomica(destino, json.dumps(manifiesto, ensure_ascii=False, indent=1))

    def ids(self) -> list[int]:
        if not self.carpeta.is_dir():
            return []
        return sorted(int(p.name) for p in self.carpeta.iterdir() if p.is_dir() and p.name.isdigit())

    def iniciar(self, etiqueta: str, grupo: Optional[int] = None) -> int:
        with self._lock:
            existentes = self.ids()
            cid = (existentes[-1] + 1) if existentes else 1
            self._guardar(cid, {
                "id": cid,
                "etiqueta": etiqueta[:120],
                "grupo": grupo if grupo is not None else cid,
                "fecha": datetime.now().isoformat(timespec="seconds"),
                "archivos": {},
            })
            self.actual = cid
            return cid

    def registrar(self, rel: str) -> None:
        with self._lock:
            if self.actual is None:
                self.iniciar("cambios sueltos")
            cid = self.actual
            man = self._manifiesto(cid)
            if rel in man["archivos"]:
                return
            origen = self.ws.raiz / rel
            if origen.is_file():
                copia = f"files/{len(man['archivos']):04d}"
                destino = self._dir(cid) / copia
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origen, destino)
                man["archivos"][rel] = {"nuevo": False, "copia": copia}
            else:
                man["archivos"][rel] = {"nuevo": True}
            self._guardar(cid, man)

    def descartar_si_vacio(self, cid: int) -> None:
        with self._lock:
            if cid in self.ids() and not self._manifiesto(cid)["archivos"]:
                shutil.rmtree(self._dir(cid), ignore_errors=True)
                if self.actual == cid:
                    self.actual = None

    def listar(self) -> list[dict]:
        return [self._manifiesto(c) for c in self.ids()]

    def archivos_desde(self, cid: int) -> list[str]:
        vistos: dict[str, None] = {}
        for c in self.ids():
            if c >= cid:
                for rel in self._manifiesto(c)["archivos"]:
                    vistos.setdefault(rel, None)
        return list(vistos)

    def _origen(self, rel: str, desde: int) -> tuple[str, Optional[Path]]:
        """('nuevo', None) si no existía, ('copia', ruta_backup) o ('sin_cambios', None)."""
        for c in self.ids():
            if c < desde:
                continue
            info = self._manifiesto(c)["archivos"].get(rel)
            if info is None:
                continue
            if info.get("nuevo"):
                return "nuevo", None
            return "copia", self._dir(c) / info["copia"]
        return "sin_cambios", None

    def original(self, rel: str, desde: int) -> Optional[str]:
        """Contenido de rel al inicio del checkpoint 'desde' (None si no existía)."""
        tipo, copia = self._origen(rel, desde)
        if tipo == "nuevo":
            return None
        ruta = copia if tipo == "copia" else self.ws.raiz / rel
        try:
            return ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def diff_desde(self, cid: int, rels: Optional[list[str]] = None) -> str:
        partes = []
        for rel in rels or self.archivos_desde(cid):
            antes = self.original(rel, cid) or ""
            ruta = self.ws.raiz / rel
            despues = ruta.read_text(encoding="utf-8", errors="replace") if ruta.is_file() else ""
            if antes != despues:
                partes.append(diff_unificado(antes, despues, rel))
        return "\n".join(partes)

    def inicio_grupo(self, cid: Optional[int] = None) -> Optional[int]:
        ids = self.ids()
        if not ids:
            return None
        objetivo = cid if cid is not None else ids[-1]
        grupo = self._manifiesto(objetivo).get("grupo", objetivo)
        return min(c for c in ids if self._manifiesto(c).get("grupo", c) == grupo or c == objetivo)

    def deshacer(self, cid: Optional[int] = None) -> list[str]:
        """Restaura el estado previo a 'cid' (por defecto, el último grupo). Devuelve archivos tocados."""
        with self._lock:
            desde = cid if cid is not None else self.inicio_grupo()
            if desde is None:
                return []
            tocados = []
            for rel in self.archivos_desde(desde):
                tipo, copia = self._origen(rel, desde)
                ruta = self.ws.raiz / rel
                if tipo == "nuevo":
                    if ruta.is_file():
                        ruta.unlink()
                        tocados.append(rel)
                elif tipo == "copia" and copia is not None and copia.is_file():
                    if not ruta.is_file() or ruta.read_bytes() != copia.read_bytes():
                        ruta.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(copia, ruta)
                        tocados.append(rel)
            for c in self.ids():
                if c >= desde:
                    shutil.rmtree(self._dir(c), ignore_errors=True)
            self.actual = None
            return tocados


# ======================================================================
# MÓDULO: validators
# ======================================================================
"""
Validadores reales y ejecución de comandos/tests.

Nada de "el modelo dice que anda": cada archivo que se escribe pasa por
validadores concretos (compilación, imports, nombres indefinidos, node
--check, JSON...) y el resultado real vuelve al agente.
"""




try:
    from pyflakes import api as _pyflakes_api
    from pyflakes import reporter as _pyflakes_reporter
except ImportError:  # pragma: no cover - opcional
    _pyflakes_api = None

_ENV_SECRETO = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)
_CACHE_MODULOS: dict[str, bool] = {}
_LOCK_IMPORTS = threading.Lock()


@dataclass
class Resultado:
    ok: bool
    comando: str
    codigo: int = 0
    stdout: str = ""
    stderr: str = ""
    timeout: bool = False
    omitido: bool = False
    archivo: str = ""

    def resumen(self, limite: int = 4000) -> str:
        partes = [f"$ {self.comando}", f"exit code: {self.codigo}"]
        if self.timeout:
            partes.append("estado: TIMEOUT")
        if self.stdout.strip():
            partes.append("STDOUT:\n" + recortar(self.stdout.strip(), limite))
        if self.stderr.strip():
            partes.append("STDERR:\n" + recortar(self.stderr.strip(), limite))
        return "\n".join(partes)

    def linea(self) -> str:
        if self.omitido:
            return f"↷ {self.comando}: {(self.stdout or self.stderr).strip()[:120]}"
        if self.ok:
            return f"✓ {self.comando}"
        detalle = (self.stderr or self.stdout).strip().splitlines()
        return f"✗ {self.comando}: {detalle[-1][:160] if detalle else 'exit ' + str(self.codigo)}"


def entorno_seguro() -> dict:
    """Entorno para subprocesos sin claves API (el modelo nunca debe verlas)."""
    env = {k: v for k, v in os.environ.items() if not _ENV_SECRETO.search(k)}
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return env


def ejecutar(
    cmd: Union[str, list],
    *,
    cwd: Path,
    timeout: int = 60,
    shell: bool = False,
) -> Resultado:
    etiqueta = cmd if isinstance(cmd, str) else " ".join(shlex.quote(str(c)) for c in cmd)
    try:
        proceso = subprocess.Popen(
            cmd,
            shell=shell,
            executable=(shutil.which("bash") if shell else None),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=entorno_seguro(),
            start_new_session=True,
        )
    except FileNotFoundError:
        nombre = cmd.split()[0] if isinstance(cmd, str) else cmd[0]
        return Resultado(False, etiqueta, 127, stderr=f"No existe el ejecutable: {nombre}")
    except OSError as e:
        return Resultado(False, etiqueta, 1, stderr=f"{type(e).__name__}: {e}")

    try:
        out, err = proceso.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proceso.pid, signal.SIGKILL)
        except OSError:
            proceso.kill()
        out, err = proceso.communicate()
        return Resultado(
            False, etiqueta, 124, out or "",
            (err or "") + f"\nTiempo agotado después de {timeout}s (¿programa interactivo o servidor?).",
            timeout=True,
        )
    return Resultado(proceso.returncode == 0, etiqueta, proceso.returncode, out or "", err or "")


# ==================================================================
# PYTHON
# ==================================================================
def _nodos_protegidos(arbol: ast.AST) -> set[int]:
    """Imports dentro de try/except ImportError o if TYPE_CHECKING no se exigen."""
    protegidos: set[int] = set()
    for nodo in ast.walk(arbol):
        bloques = []
        if isinstance(nodo, ast.Try):
            for handler in nodo.handlers:
                tipo = ast.unparse(handler.type) if handler.type is not None else ""
                if not tipo or any(n in tipo for n in ("ImportError", "ModuleNotFoundError", "Exception")):
                    bloques.append(nodo.body)
                    break
        elif isinstance(nodo, ast.If) and "TYPE_CHECKING" in ast.unparse(nodo.test):
            bloques.append(nodo.body)
        for bloque in bloques:
            for sentencia in bloque:
                for sub in ast.walk(sentencia):
                    protegidos.add(id(sub))
    return protegidos


def imports_faltantes(ws: Workspace, ruta: Path, arbol: ast.AST) -> list[str]:
    protegidos = _nodos_protegidos(arbol)
    modulos: set[str] = set()
    for nodo in ast.walk(arbol):
        if id(nodo) in protegidos:
            continue
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                modulos.add(alias.name.split(".")[0])
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            modulos.add(nodo.module.split(".")[0])

    carpetas = [ws.raiz, ws.raiz / "src"]
    actual = ruta.parent
    while True:
        carpetas.append(actual)
        if actual == ws.raiz or ws.raiz not in actual.parents:
            break
        actual = actual.parent

    estandar = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
    faltan = []
    for modulo in sorted(modulos):
        if modulo in estandar or modulo == "__future__":
            continue
        if any((d / f"{modulo}.py").is_file() or (d / modulo).is_dir() for d in carpetas):
            continue
        with _LOCK_IMPORTS:
            if modulo not in _CACHE_MODULOS:
                try:
                    _CACHE_MODULOS[modulo] = importlib.util.find_spec(modulo) is not None
                except (ImportError, ValueError):
                    _CACHE_MODULOS[modulo] = False
            if not _CACHE_MODULOS[modulo]:
                faltan.append(modulo)
    return faltan


def _nombres_indefinidos(ws: Workspace, rel: str, texto: str) -> Optional[Resultado]:
    ruff = shutil.which("ruff")
    if ruff:
        r = ejecutar(
            [ruff, "check", "--isolated", "--no-cache", "--select", "E9,F63,F7,F82",
             "--output-format", "concise", rel],
            cwd=ws.raiz,
            timeout=30,
        )
        if r.codigo in (0, 1):
            r.comando = f"ruff (nombres indefinidos) {rel}"
            r.archivo = rel
            if r.ok:
                r.stdout = ""
            return r
        return None
    if _pyflakes_api is not None:
        salida, errores = io.StringIO(), io.StringIO()
        _pyflakes_api.check(texto, rel, _pyflakes_reporter.Reporter(salida, errores))
        graves = [
            l for l in salida.getvalue().splitlines()
            if "undefined name" in l or "undefined local" in l
        ]
        return Resultado(not graves, f"pyflakes (nombres indefinidos) {rel}",
                         0 if not graves else 1, stderr="\n".join(graves), archivo=rel)
    return None


def _validar_python(ws: Workspace, ruta: Path, rel: str) -> list[Resultado]:
    texto = ruta.read_text(encoding="utf-8", errors="replace")
    try:
        arbol = ast.parse(texto, filename=rel)
        compile(arbol, rel, "exec", dont_inherit=True)
    except SyntaxError as e:
        detalle = f"{type(e).__name__}: {e.msg} (línea {e.lineno}, columna {e.offset})"
        if e.text:
            detalle += f"\n    {e.text.rstrip()}\n    {' ' * max(0, (e.offset or 1) - 1)}^"
        return [Resultado(False, f"py_compile {rel}", 1, stderr=detalle, archivo=rel)]
    except ValueError as e:
        return [Resultado(False, f"py_compile {rel}", 1, stderr=str(e), archivo=rel)]

    resultados = [Resultado(True, f"py_compile {rel}", 0, archivo=rel)]
    indefinidos = _nombres_indefinidos(ws, rel, texto)
    if indefinidos is not None:
        resultados.append(indefinidos)
    faltan = imports_faltantes(ws, ruta, arbol)
    resultados.append(Resultado(
        not faltan,
        f"imports {rel}",
        0 if not faltan else 1,
        stderr=("Módulos no instalados ni presentes en el proyecto: " + ", ".join(faltan)
                + "\n(Instalalos con pip o usá la librería estándar.)") if faltan else "",
        archivo=rel,
    ))
    return resultados


# ==================================================================
# JS / HTML / OTROS
# ==================================================================
_ERRORES_ESM = ("Cannot use import statement outside a module", "Unexpected token 'export'",
                "await is only valid", "Cannot use 'import.meta' outside a module")


def _node_check_texto(ws: Workspace, codigo: str, sufijo: str) -> Resultado:
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / f"check{sufijo}"
        destino.write_text(codigo, encoding="utf-8")
        return ejecutar(["node", "--check", str(destino)], cwd=ws.raiz, timeout=30)


def _validar_js(ws: Workspace, ruta: Path, rel: str) -> list[Resultado]:
    if not shutil.which("node"):
        return [Resultado(True, f"node --check {rel}", 0, omitido=True,
                          stdout="node no está instalado (pkg install nodejs)", archivo=rel)]
    r = ejecutar(["node", "--check", rel], cwd=ws.raiz, timeout=30)
    if not r.ok and any(m in r.stderr for m in _ERRORES_ESM) and ruta.suffix == ".js":
        # JS de navegador con import/export: se revalida como módulo ES.
        r2 = _node_check_texto(ws, ruta.read_text(encoding="utf-8", errors="replace"), ".mjs")
        r2.stderr = r2.stderr.replace(r2.comando.split()[-1], rel)
        r = r2
    r.comando = f"node --check {rel}"
    r.archivo = rel
    return [r]


_SCRIPT_HTML = re.compile(r"<script(?![^>]*\bsrc\s*=)([^>]*)>(.*?)</script\s*>", re.S | re.I)


def _validar_html(ws: Workspace, ruta: Path, rel: str) -> list[Resultado]:
    if not shutil.which("node"):
        return []
    texto = ruta.read_text(encoding="utf-8", errors="replace")
    resultados = []
    for numero, m in enumerate(_SCRIPT_HTML.finditer(texto), start=1):
        atributos, codigo = m.group(1).lower(), m.group(2)
        tipo = re.search(r"type\s*=\s*[\"']?([\w/+-]+)", atributos)
        tipo = tipo.group(1) if tipo else ""
        if tipo and tipo not in ("module", "text/javascript", "application/javascript"):
            continue
        if not codigo.strip():
            continue
        linea_inicio = texto.count("\n", 0, m.start(2))
        # Se rellena con saltos de línea para que los números de línea coincidan con el HTML.
        r = _node_check_texto(ws, "\n" * linea_inicio + codigo, ".mjs" if tipo == "module" else ".js")
        if not r.ok and any(e in r.stderr for e in _ERRORES_ESM):
            r = _node_check_texto(ws, "\n" * linea_inicio + codigo, ".mjs")
        r.comando = f"node --check <script #{numero}> {rel}"
        r.archivo = rel
        resultados.append(r)
    return resultados


def _validar_css(ruta: Path, rel: str) -> list[Resultado]:
    texto = re.sub(r"/\*.*?\*/", "", ruta.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    texto = re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", "", texto)
    nivel = 0
    for numero, linea in enumerate(texto.splitlines(), start=1):
        for ch in linea:
            if ch == "{":
                nivel += 1
            elif ch == "}":
                nivel -= 1
                if nivel < 0:
                    return [Resultado(False, f"css-llaves {rel}", 1,
                                      stderr=f"'}}' sin abrir en la línea {numero}", archivo=rel)]
    if nivel:
        return [Resultado(False, f"css-llaves {rel}", 1,
                          stderr=f"Faltan {nivel} '}}' de cierre", archivo=rel)]
    return [Resultado(True, f"css-llaves {rel}", 0, archivo=rel)]


def validar_archivo(ws: Workspace, rel: str) -> list[Resultado]:
    try:
        ruta = ws.ruta(rel)
    except ValueError as e:
        return [Resultado(False, f"validar {rel}", 2, stderr=str(e), archivo=rel)]
    rel = ws.rel(ruta)
    if not ruta.is_file():
        return [Resultado(False, f"validar {rel}", 2, stderr="El archivo no existe.", archivo=rel)]

    sufijo = ruta.suffix.lower()
    try:
        if sufijo == ".py":
            return _validar_python(ws, ruta, rel)
        if sufijo in (".sh", ".bash"):
            r = ejecutar(["bash", "-n", rel], cwd=ws.raiz, timeout=20)
            r.archivo = rel
            return [r]
        if sufijo in (".js", ".mjs", ".cjs"):
            return _validar_js(ws, ruta, rel)
        if sufijo in (".html", ".htm"):
            return _validar_html(ws, ruta, rel)
        if sufijo == ".css":
            return _validar_css(ruta, rel)
        if sufijo in (".json", ".webmanifest"):
            try:
                json.loads(ruta.read_text(encoding="utf-8"))
                return [Resultado(True, f"json {rel}", 0, archivo=rel)]
            except (ValueError, UnicodeDecodeError) as e:
                return [Resultado(False, f"json {rel}", 1, stderr=f"JSON inválido: {e}", archivo=rel)]
        if sufijo == ".toml":
            try:
                import tomllib
            except ImportError:
                return []
            try:
                tomllib.loads(ruta.read_text(encoding="utf-8"))
                return [Resultado(True, f"toml {rel}", 0, archivo=rel)]
            except (ValueError, UnicodeDecodeError) as e:
                return [Resultado(False, f"toml {rel}", 1, stderr=f"TOML inválido: {e}", archivo=rel)]
    except OSError as e:
        return [Resultado(False, f"validar {rel}", 1, stderr=f"{type(e).__name__}: {e}", archivo=rel)]
    return []


def validar_archivos(ws: Workspace, rels: list[str]) -> list[Resultado]:
    resultados = []
    for rel in rels:
        if (ws.raiz / rel).is_file():
            resultados.extend(validar_archivo(ws, rel))
    return resultados


def fallos(resultados: list[Resultado]) -> list[Resultado]:
    return [r for r in resultados if not r.ok]


def resumen_validacion(resultados: list[Resultado], limite: int = 3000) -> str:
    if not resultados:
        return "sin validadores aplicables"
    malos = fallos(resultados)
    if not malos:
        return "OK (" + ", ".join(r.comando.split(" ")[0] for r in resultados if not r.omitido) + ")"
    return "\n\n".join(r.resumen(limite) for r in malos)


# ==================================================================
# TESTS
# ==================================================================
def detectar_comando_tests(ws: Workspace) -> Optional[tuple[str, str]]:
    raiz = ws.raiz
    local = ws.config_local().get("comando_tests")
    if isinstance(local, str) and local.strip():
        return local.strip(), "config .reaper"

    py = shlex.quote(sys.executable)
    hay_tests_py = (
        (raiz / "tests").is_dir()
        or (raiz / "test").is_dir()
        or any(raiz.glob("test_*.py"))
        or any(raiz.glob("*_test.py"))
    )
    if hay_tests_py:
        if importlib.util.find_spec("pytest") is not None:
            return f"{py} -m pytest -q -x -p no:cacheprovider", "pytest"
        for carpeta in ("tests", "test"):
            if (raiz / carpeta).is_dir():
                if (raiz / carpeta / "__init__.py").is_file():
                    return f"{py} -m unittest discover -s {carpeta} -t .", "unittest"
                return f"{py} -m unittest discover -s {carpeta}", "unittest"
        return f"{py} -m unittest discover", "unittest"

    paquete = raiz / "package.json"
    if paquete.is_file():
        try:
            datos = json.loads(paquete.read_text(encoding="utf-8"))
            script = (datos.get("scripts") or {}).get("test")
            if script and "no test specified" not in script and shutil.which("npm"):
                return "npm test --silent", "npm test"
        except (OSError, ValueError):
            pass
    if shutil.which("node") and any((raiz / d).is_dir() for d in ("tests", "test")):
        js = [p for d in ("tests", "test") for p in (raiz / d).glob("*.test.*js")]
        if js:
            return "node --test", "node --test"
    if (raiz / "go.mod").is_file() and shutil.which("go"):
        return "go test ./...", "go test"
    if (raiz / "Cargo.toml").is_file() and shutil.which("cargo"):
        return "cargo test", "cargo test"
    makefile = raiz / "Makefile"
    if makefile.is_file() and shutil.which("make"):
        try:
            if re.search(r"^test\s*:", makefile.read_text(encoding="utf-8"), re.M):
                return "make test", "make test"
        except OSError:
            pass
    return None


def ejecutar_tests(ws: Workspace, timeout: int = 300) -> Optional[Resultado]:
    detectado = detectar_comando_tests(ws)
    if not detectado:
        return None
    comando, _nombre = detectado
    r = ejecutar(comando, cwd=ws.raiz, timeout=timeout, shell=True)
    combinado = r.stdout + r.stderr
    if r.codigo == 5 or "NO TESTS RAN" in combinado or re.search(r"\bRan 0 tests?\b", combinado):
        r.ok, r.omitido = True, True
        r.stdout = "No se encontraron tests para ejecutar. " + r.stdout
    return r


def es_crash_real(r: Resultado) -> bool:
    """Un exit != 0 controlado (uso incorrecto, validación) no es un bug a reparar."""
    if r.timeout or r.codigo in (126, 127) or r.codigo < 0:
        return True
    combinado = f"{r.stdout}\n{r.stderr}"
    patrones = (
        "Traceback (most recent call last)", "SyntaxError", "IndentationError",
        "ModuleNotFoundError", "ImportError", "NameError", "UnboundLocalError",
        "AttributeError", "TypeError:", "RecursionError", "ReferenceError",
        "Segmentation fault",
    )
    return any(p in combinado for p in patrones)


# ======================================================================
# MÓDULO: tools
# ======================================================================
"""Herramientas que los agentes usan para trabajar sobre el workspace real."""




MAX_LINEAS_LECTURA = 400
MAX_SALIDA = 9000


class ErrorHerramienta(Exception):
    pass


@dataclass
class Contexto:
    ws: Workspace
    settings: Settings
    ui: UI
    etiqueta: str = "agente"
    cambios: set = field(default_factory=set)
    todo: list = field(default_factory=list)
    cid_inicio: Optional[int] = None


@dataclass
class Param:
    nombre: str
    descripcion: str
    requerido: bool = True
    largo: bool = False


@dataclass
class Herramienta:
    nombre: str
    descripcion: str
    params: list
    ejemplo: str
    fn: Optional[Callable] = None
    escribe: bool = False


REGISTRO: dict[str, Herramienta] = {}


def herramienta(nombre: str, descripcion: str, params: list, ejemplo: str, escribe: bool = False):
    def decorador(fn):
        REGISTRO[nombre] = Herramienta(nombre, descripcion, params, ejemplo.strip(), fn, escribe)
        return fn
    return decorador


def esquemas(nombres: Optional[list] = None) -> dict:
    return {
        n: [(p.nombre, p.largo) for p in h.params]
        for n, h in REGISTRO.items()
        if nombres is None or n in nombres
    }


def documentacion(nombres: list) -> str:
    partes = []
    for nombre in nombres:
        h = REGISTRO.get(nombre)
        if not h:
            continue
        params = ", ".join(
            f"{p.nombre}{'' if p.requerido else ' (opcional)'}: {p.descripcion}" for p in h.params
        ) or "sin parámetros"
        partes.append(f"## {h.nombre}\n{h.descripcion}\nParámetros: {params}\n{h.ejemplo}")
    return "\n\n".join(partes)


# ==================================================================
# HELPERS
# ==================================================================
def _sugerir_ruta(ctx: Contexto, rel: str) -> str:
    nombre = Path(rel).name
    archivos = ctx.ws.archivos_codigo(limite=800)
    parecidos = difflib.get_close_matches(rel, archivos, n=3, cutoff=0.5)
    parecidos += [a for a in archivos if Path(a).name == nombre and a not in parecidos][:3]
    return f" ¿Quisiste decir: {', '.join(parecidos)}?" if parecidos else ""


def _entero(valor, defecto: Optional[int]) -> Optional[int]:
    try:
        return int(str(valor).strip()) if str(valor or "").strip() else defecto
    except ValueError:
        return defecto


def _permiso_edicion(ctx: Contexto, rel: str, diff: str, nuevo: bool) -> None:
    if ctx.settings.modo != "confirmar":
        return
    ctx.ui.aviso(f"  {ctx.etiqueta} quiere {'crear' if nuevo else 'modificar'} {rel}:")
    ctx.ui.diff(diff, max_lineas=40)
    if not ctx.ui.confirmar("  ¿Aplicar este cambio?"):
        raise ErrorHerramienta(
            f"El usuario rechazó el cambio en {rel}. No insistas con lo mismo: "
            "preguntá qué prefiere (ask_user) o seguí con otra parte."
        )


def _escribir(ctx: Contexto, rel: str, contenido: str) -> None:
    try:
        ctx.ws.escribir(rel, contenido)
    except (ErrorRuta, IsADirectoryError, PermissionError) as e:
        raise ErrorHerramienta(f"No pude escribir {rel}: {e}")


def _post_escritura(ctx: Contexto, rel: str, antes: Optional[str], despues: str, notas: list) -> str:
    ctx.cambios.add(rel)
    lineas = despues.count("\n") + (0 if despues.endswith("\n") or not despues else 1)
    diff = diff_unificado(antes or "", despues, rel)
    if antes is None:
        ctx.ui.tenue(f"      + {rel} (nuevo, {lineas} líneas)")
    else:
        ctx.ui.diff(diff, max_lineas=24)

    resultados = validar_archivo(ctx.ws, rel)
    malos = fallos(resultados)
    accion = "Creé" if antes is None else "Modifiqué"
    texto = f"{accion} {rel} ({lineas} líneas)."
    if notas:
        texto += " Notas: " + "; ".join(notas) + "."
    if antes is not None and diff:
        texto += "\nDiff aplicado:\n" + recortar(diff, 2500)
    if not resultados:
        texto += "\nValidación: no hay validador automático para este tipo de archivo."
    elif malos:
        texto += "\nVALIDACIÓN FALLÓ (corregilo antes de seguir):\n" + resumen_validacion(resultados)
    else:
        texto += "\nValidación: " + resumen_validacion(resultados)
    return texto


# ==================================================================
# LECTURA
# ==================================================================
@herramienta(
    "read_file",
    "Lee un archivo de texto. Devuelve las líneas numeradas ('  12| código'); los números NO son parte del archivo.",
    [Param("path", "ruta relativa al workspace"),
     Param("desde", "primera línea a mostrar", requerido=False),
     Param("hasta", "última línea a mostrar", requerido=False)],
    "<read_file>\n<path>src/app.py</path>\n</read_file>",
)
def read_file(ctx: Contexto, p: dict) -> str:
    rel = p["path"]
    try:
        ruta = ctx.ws.ruta(rel)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if ruta.is_dir():
        raise ErrorHerramienta(f"{rel} es una carpeta. Usá list_files.")
    if not ruta.is_file():
        raise ErrorHerramienta(f"No existe {rel}.{_sugerir_ruta(ctx, rel)}")
    if ruta.name in (".env", "id_rsa", "id_ed25519"):
        raise ErrorHerramienta("Archivo sensible: no se lee.")
    if es_binario(ruta):
        raise ErrorHerramienta(f"{rel} es binario ({ruta.stat().st_size} bytes).")
    try:
        lineas = ctx.ws.leer(rel).splitlines()
    except ValueError as e:
        raise ErrorHerramienta(str(e))
    total = len(lineas)
    if total == 0:
        return f"{ctx.ws.rel(ruta)} está vacío."
    desde = max(1, _entero(p.get("desde"), 1))
    hasta = min(total, _entero(p.get("hasta"), desde + MAX_LINEAS_LECTURA - 1))
    hasta = min(hasta, desde + MAX_LINEAS_LECTURA - 1)
    cuerpo = "\n".join(f"{i:>5}| {lineas[i - 1]}" for i in range(desde, hasta + 1))
    pie = ""
    if desde > 1 or hasta < total:
        pie = f"\n(mostrando líneas {desde}-{hasta} de {total}; usá desde/hasta para ver el resto)"
    return f"{ctx.ws.rel(ruta)} ({total} líneas)\n{cuerpo}{pie}"


@herramienta(
    "list_files",
    "Lista archivos del workspace (ignora .git, node_modules, venv, etc.).",
    [Param("path", "carpeta relativa (por defecto la raíz)", requerido=False),
     Param("recursive", "true/false (por defecto true)", requerido=False)],
    "<list_files>\n<path>.</path>\n</list_files>",
)
def list_files(ctx: Contexto, p: dict) -> str:
    rel = p.get("path") or "."
    try:
        base = ctx.ws.ruta(rel) if rel not in (".", "") else ctx.ws.raiz
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if base.is_file():
        raise ErrorHerramienta(f"{rel} es un archivo. Usá read_file.")
    if not base.is_dir():
        raise ErrorHerramienta(f"No existe la carpeta {rel}.{_sugerir_ruta(ctx, rel)}")
    recursivo = str(p.get("recursive", "true")).strip().lower() not in ("false", "no", "0")
    if not recursivo:
        entradas = []
        for hijo in sorted(base.iterdir()):
            r = ctx.ws.rel(hijo)
            if ctx.ws.ignorado(r, hijo.is_dir()):
                continue
            entradas.append(r + ("/" if hijo.is_dir() else ""))
        return "\n".join(entradas) or "(carpeta vacía)"
    rutas = [ctx.ws.rel(x) for x in ctx.ws.iterar(rel, limite=301)]
    if not rutas:
        return "(sin archivos)"
    extra = "\n... (más de 300 archivos; filtrá con path o usá search_files)" if len(rutas) > 300 else ""
    return "\n".join(rutas[:300]) + extra


@herramienta(
    "search_files",
    "Busca una expresión regular (Python) en los archivos de texto. Devuelve archivo:línea: texto.",
    [Param("regex", "expresión a buscar, p. ej. def procesar|class Cliente"),
     Param("path", "carpeta o archivo donde buscar (opcional)", requerido=False),
     Param("file_pattern", "filtro de nombre tipo *.py (opcional)", requerido=False)],
    "<search_files>\n<regex>def guardar_</regex>\n<file_pattern>*.py</file_pattern>\n</search_files>",
)
def search_files(ctx: Contexto, p: dict) -> str:
    patron_txt = p["regex"]
    nota = ""
    try:
        patron = re.compile(patron_txt)
    except re.error:
        patron = re.compile(re.escape(patron_txt))
        nota = "(regex inválida: se buscó como texto literal)\n"
    filtro = (p.get("file_pattern") or "").strip()

    def buscar(rx: re.Pattern) -> list[str]:
        hallazgos = []
        for ruta in ctx.ws.iterar(p.get("path") or ".", limite=3000):
            if filtro and not Path(ruta.name).match(filtro):
                continue
            if not ctx.ws.es_texto(ruta) or ruta.stat().st_size > 400_000:
                continue
            try:
                texto = ruta.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n, linea in enumerate(texto.splitlines(), start=1):
                if rx.search(linea):
                    hallazgos.append(f"{ctx.ws.rel(ruta)}:{n}: {linea.strip()[:200]}")
                    if len(hallazgos) >= 80:
                        return hallazgos
        return hallazgos

    try:
        hallazgos = buscar(patron)
        if not hallazgos and not nota:
            hallazgos = buscar(re.compile(patron.pattern, re.I))
            if hallazgos:
                nota = "(sin coincidencias exactas; resultados ignorando mayúsculas)\n"
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if not hallazgos:
        return nota + "Sin coincidencias."
    extra = "\n... (hay más; afiná la búsqueda)" if len(hallazgos) >= 80 else ""
    return nota + "\n".join(hallazgos) + extra


def _outline_python(texto: str) -> list[str]:
    try:
        arbol = ast.parse(texto)
    except SyntaxError as e:
        return [f"(error de sintaxis en línea {e.lineno}: {e.msg})"]
    salida = []
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pref = "async def" if isinstance(nodo, ast.AsyncFunctionDef) else "def"
            salida.append(f"{nodo.lineno}: {pref} {nodo.name}({ast.unparse(nodo.args)})")
        elif isinstance(nodo, ast.ClassDef):
            salida.append(f"{nodo.lineno}: class {nodo.name}")
            for sub in nodo.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    salida.append(f"{sub.lineno}:     def {sub.name}({ast.unparse(sub.args)})")
        elif isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    salida.append(f"{nodo.lineno}: {t.id} = ...")
    return salida


_JS_SIMBOLOS = re.compile(
    r"^\s*(export\s+(default\s+)?)?(async\s+)?(function\*?\s+[\w$]+\s*\([^)]*\)|class\s+[\w$]+"
    r"|(const|let|var)\s+[\w$]+\s*=\s*(async\s*)?(\([^)]*\)|[\w$]+)\s*=>"
    r"|(const|let|var)\s+[\w$]+\s*=\s*(async\s+)?function)"
)


def outline(ruta: Path) -> list[str]:
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if ruta.suffix == ".py":
        return _outline_python(texto)
    if ruta.suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
        return [f"{n}: {l.strip()[:120]}" for n, l in enumerate(texto.splitlines(), 1) if _JS_SIMBOLOS.match(l)]
    return []


@herramienta(
    "code_outline",
    "Mapa rápido de un archivo o carpeta: clases, funciones y firmas con número de línea. Más barato que leer todo.",
    [Param("path", "archivo o carpeta (por defecto la raíz)", requerido=False)],
    "<code_outline>\n<path>src</path>\n</code_outline>",
)
def code_outline(ctx: Contexto, p: dict) -> str:
    rel = p.get("path") or "."
    try:
        objetivo = ctx.ws.ruta(rel) if rel not in (".", "") else ctx.ws.raiz
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    if not objetivo.exists():
        raise ErrorHerramienta(f"No existe {rel}.{_sugerir_ruta(ctx, rel)}")
    rutas = [objetivo] if objetivo.is_file() else list(ctx.ws.iterar(rel, limite=600))
    partes, total = [], 0
    for ruta in rutas:
        simbolos = outline(ruta)
        if not simbolos:
            continue
        bloque = ctx.ws.rel(ruta) + "\n" + "\n".join("  " + s for s in simbolos[:40])
        if len(simbolos) > 40:
            bloque += f"\n  ... {len(simbolos) - 40} símbolos más"
        partes.append(bloque)
        total += len(bloque)
        if total > MAX_SALIDA:
            partes.append("... (salida recortada; pedí una carpeta más específica)")
            break
    return "\n".join(partes) or "No encontré símbolos (solo se analizan .py y .js/.ts)."


# ==================================================================
# ESCRITURA
# ==================================================================
@herramienta(
    "write_to_file",
    "Crea un archivo o lo reemplaza ENTERO. Para archivos existentes preferí replace_in_file. "
    "El contenido debe ser COMPLETO: prohibido '...' o 'resto igual'.",
    [Param("path", "ruta relativa"), Param("content", "contenido completo del archivo", largo=True)],
    "<write_to_file>\n<path>utils/fechas.py</path>\n<content>\nfrom datetime import date\n\n\n"
    "def hoy() -> str:\n    return date.today().isoformat()\n</content>\n</write_to_file>",
    escribe=True,
)
def write_to_file(ctx: Contexto, p: dict) -> str:
    rel, contenido = p["path"], p["content"]
    try:
        ruta = ctx.ws.ruta(rel, escribir=True)
    except ErrorRuta as e:
        raise ErrorHerramienta(str(e))
    rel = ctx.ws.rel(ruta)
    antes = None
    if ruta.is_file():
        antes = ruta.read_text(encoding="utf-8", errors="replace")
        marcador = tiene_marcadores_perezosos(contenido)
        if marcador and not tiene_marcadores_perezosos(antes):
            raise ErrorHerramienta(
                f"El contenido tiene un marcador de código omitido ('{marcador}'). "
                "Eso borraría código real. Usá replace_in_file para cambiar solo una parte, "
                "o escribí el archivo COMPLETO."
            )
    if contenido and not contenido.endswith("\n"):
        contenido += "\n"
    if antes == contenido:
        return f"{rel} ya tenía exactamente ese contenido; no hubo cambios."

    notas = []
    if antes is not None:
        viejas, nuevas = antes.count("\n"), contenido.count("\n")
        if viejas >= 40 and nuevas < viejas * 0.4:
            notas.append(f"ATENCIÓN: el archivo pasó de {viejas} a {nuevas} líneas; verificá que no se perdió código")
    _permiso_edicion(ctx, rel, diff_unificado(antes or "", contenido, rel), antes is None)
    _escribir(ctx, rel, contenido)
    return _post_escritura(ctx, rel, antes, contenido, notas)


@herramienta(
    "replace_in_file",
    "Edita partes de un archivo existente con uno o más bloques SEARCH/REPLACE. "
    "SEARCH debe copiar el texto actual EXACTO (sin números de línea) y ser único; incluí 2-3 líneas de contexto. "
    "Se aplican todos los bloques o ninguno.",
    [Param("path", "ruta relativa"), Param("diff", "bloques SEARCH/REPLACE", largo=True)],
    "<replace_in_file>\n<path>app.py</path>\n<diff>\n<<<<<<< SEARCH\ndef total(items):\n    return sum(items)\n"
    "=======\ndef total(items):\n    return sum(i.precio for i in items)\n>>>>>>> REPLACE\n</diff>\n</replace_in_file>",
    escribe=True,
)
def replace_in_file(ctx: Contexto, p: dict) -> str:
    rel = p["path"]
    try:
        ruta = ctx.ws.ruta(rel, escribir=True)
        bloques = parsear_bloques(p["diff"])
    except (ErrorRuta, ErrorEdicion) as e:
        raise ErrorHerramienta(str(e))
    rel = ctx.ws.rel(ruta)
    existe = ruta.is_file()
    if not existe and not (len(bloques) == 1 and not bloques[0].buscar.strip()):
        raise ErrorHerramienta(f"No existe {rel}. Para crearlo usá write_to_file.{_sugerir_ruta(ctx, rel)}")
    antes = ruta.read_text(encoding="utf-8", errors="replace") if existe else ""
    for b in bloques:
        marcador = tiene_marcadores_perezosos(b.reemplazar)
        if marcador and marcador not in antes:
            raise ErrorHerramienta(
                f"El REPLACE contiene '{marcador}' (código omitido). Escribí el código real completo."
            )
    try:
        despues, notas = aplicar_bloques(antes, bloques)
    except ErrorEdicion as e:
        raise ErrorHerramienta(str(e))
    if despues == antes:
        return f"Sin cambios en {rel} ({'; '.join(notas) or 'el contenido ya era ese'})."
    _permiso_edicion(ctx, rel, diff_unificado(antes, despues, rel), not existe)
    _escribir(ctx, rel, despues)
    return _post_escritura(ctx, rel, antes if existe else None, despues, notas)


# ==================================================================
# EJECUCIÓN Y VERIFICACIÓN
# ==================================================================
_BLOQUEADOS = [
    re.compile(p) for p in (
        r"\bsudo\b", r"(^|[;&|]\s*)su(\s|$)", r"\bmkfs", r"\bdd\s+if=", r":\(\)\s*\{",
        r"\b(shutdown|reboot|poweroff|halt)\b",
        r"\brm\s+(-\w+\s+)*(/|~|\$HOME|\*|\.)/?\*?(\s|$)",
        r"(curl|wget)\b[^|;]*\|\s*(ba|z|da)?sh\b", r">\s*/dev/(sd|block|mmc)",
        r"\bchmod\s+(-R\s+)?777\s+/", r"\bgit\s+push\b.*(--force|-f\b)",
        r"\bgit\s+(reset\s+--hard|clean\s+-\w*f)",
        r"\b(printenv|env)\s*($|[|;>])", r"\bcat\s+[^|;]*\.env\b",
    )
]

_SEGUROS = (
    "ls", "pwd", "cat ", "head ", "tail ", "wc ", "tree", "file ", "stat ", "du ",
    "grep ", "rg ", "which ", "echo ", "python -m py_compile", "python3 -m py_compile",
    "python -m pytest", "python3 -m pytest", "python -m unittest", "python3 -m unittest",
    "pytest", "node --check", "node --test", "npm test", "ruff check", "git status",
    "git diff", "git log", "git show", "pip list", "pip show", "python --version",
    "python3 --version", "node --version",
)


def comando_bloqueado(comando: str) -> Optional[str]:
    for patron in _BLOQUEADOS:
        if patron.search(comando):
            return patron.pattern
    return None


def comando_seguro(comando: str) -> bool:
    c = comando.strip()
    if any(s in c for s in (";", "&&", "||", "|", ">", "<", "`", "$(")):
        return False
    return any(c == s.strip() or c.startswith(s) for s in _SEGUROS)


@herramienta(
    "execute_command",
    "Ejecuta un comando de shell (bash) en la raíz del workspace, sin entrada interactiva. "
    "Para tests preferí run_tests. Servidores o programas interactivos se cortan por timeout.",
    [Param("command", "comando a ejecutar"),
     Param("timeout", "segundos (opcional, máx 600)", requerido=False)],
    "<execute_command>\n<command>python3 main.py --ayuda</command>\n</execute_command>",
)
def execute_command(ctx: Contexto, p: dict) -> str:
    comando = p["command"].strip()
    if not comando:
        raise ErrorHerramienta("Comando vacío.")
    patron = comando_bloqueado(comando)
    if patron:
        raise ErrorHerramienta(f"Comando bloqueado por seguridad (coincide con {patron}).")
    if ctx.settings.modo != "auto" and not comando_seguro(comando):
        ctx.ui.aviso(f"  {ctx.etiqueta} quiere ejecutar: {comando}")
        if not ctx.ui.confirmar("  ¿Ejecutar?"):
            raise ErrorHerramienta(
                "El usuario no aprobó el comando (o no hay usuario para aprobarlo). "
                "Seguí sin él o usá run_tests / validate."
            )
    timeout = min(600, _entero(p.get("timeout"), ctx.settings.exec_timeout) or ctx.settings.exec_timeout)
    r = ejecutar(comando, cwd=ctx.ws.raiz, timeout=timeout, shell=True)
    return r.resumen(limite=MAX_SALIDA // 2)


@herramienta(
    "run_tests",
    "Detecta y ejecuta la suite de tests del proyecto (pytest, unittest, npm test, node --test...).",
    [],
    "<run_tests>\n</run_tests>",
)
def run_tests(ctx: Contexto, p: dict) -> str:
    detectado = detectar_comando_tests(ctx.ws)
    if not detectado:
        return (
            "No hay tests detectados. Para Python creá tests/test_<modulo>.py con unittest "
            "(librería estándar); para JS, tests/*.test.mjs con node:test."
        )
    r = ejecutar_tests(ctx.ws, timeout=ctx.settings.tests_timeout)
    assert r is not None
    estado = "SIN TESTS" if r.omitido else ("PASARON" if r.ok else "FALLARON")
    return f"Tests {estado} ({detectado[1]}).\n" + r.resumen(limite=MAX_SALIDA // 2)


@herramienta(
    "validate",
    "Corre los validadores reales (sintaxis, imports, nombres indefinidos, node --check, JSON) "
    "sobre archivos. Sin paths valida lo que cambiaste en esta tarea.",
    [Param("paths", "rutas separadas por coma (opcional)", requerido=False)],
    "<validate>\n<paths>app.py, utils.py</paths>\n</validate>",
)
def validate(ctx: Contexto, p: dict) -> str:
    texto = p.get("paths") or ""
    rels = [r.strip() for r in re.split(r"[,\n]", texto) if r.strip()] or sorted(ctx.cambios)
    if not rels:
        return "No cambiaste archivos todavía; indicá paths para validar."
    resultados = validar_archivos(ctx.ws, rels)
    if not resultados:
        return "Ninguno de esos archivos tiene validador automático (o no existen)."
    return "\n".join(r.linea() for r in resultados) + (
        "\n\nDETALLE DE FALLOS:\n" + resumen_validacion(resultados) if fallos(resultados) else ""
    )


@herramienta(
    "view_diff",
    "Muestra el diff real de los cambios hechos desde que empezó la tarea actual.",
    [],
    "<view_diff>\n</view_diff>",
)
def view_diff(ctx: Contexto, p: dict) -> str:
    cid = ctx.cid_inicio if ctx.cid_inicio is not None else ctx.ws.checkpoints.actual
    if cid is None:
        return "No hay cambios registrados."
    diff = ctx.ws.checkpoints.diff_desde(cid)
    return recortar(diff, MAX_SALIDA) if diff.strip() else "No hay cambios todavía."


# ==================================================================
# PLANIFICACIÓN, SUBAGENTES Y CIERRE (los maneja el bucle del agente)
# ==================================================================
@herramienta(
    "update_todo",
    "Mantiene tu lista de tareas. Mandá la lista COMPLETA cada vez: '[x]' hecho, '[ ]' pendiente, '[>]' en curso.",
    [Param("items", "una tarea por línea", largo=True)],
    "<update_todo>\n<items>\n[x] Leer la estructura\n[>] Agregar validación de email\n[ ] Escribir tests\n</items>\n</update_todo>",
)
def update_todo(ctx: Contexto, p: dict) -> str:
    items = []
    for linea in (p.get("items") or "").splitlines():
        linea = re.sub(r"^\s*([-*]|\d+[.)])\s*", "", linea).strip()
        if not linea:
            continue
        m = re.match(r"^\[(.)\]\s*(.+)$", linea)
        estado, texto = (m.group(1).lower(), m.group(2)) if m else (" ", linea)
        estado = {"x": "x", "✓": "x", ">": ">", "~": ">"}.get(estado, " ")
        items.append((estado, texto))
    ctx.todo[:] = items
    for estado, texto in items:
        marca = {"x": "✓", ">": "▸"}.get(estado, "○")
        ctx.ui.tenue(f"      {marca} {texto}")
    hechos = sum(1 for e, _ in items if e == "x")
    return f"Lista actualizada: {hechos}/{len(items)} hechas."


@herramienta(
    "delegate",
    "Lanza un SUBAGENTE con contexto limpio para una tarea acotada. Roles: explorador (investiga, solo lectura), "
    "implementador (escribe código), revisor (revisa, solo lectura), qa (tests), reparador (arregla fallos). "
    "Varios <delegate> de solo lectura en el MISMO mensaje corren EN PARALELO. Devuelve el informe del subagente.",
    [Param("role", "explorador | implementador | revisor | qa | reparador"),
     Param("task", "instrucciones completas y autocontenidas", largo=True),
     Param("files", "archivos relevantes separados por coma (opcional)", requerido=False)],
    "<delegate>\n<role>explorador</role>\n<task>Encontrá dónde se valida el login y qué funciones lo llaman.</task>\n</delegate>",
)
def delegate(ctx: Contexto, p: dict) -> str:  # pragma: no cover - lo intercepta el agente
    raise ErrorHerramienta("delegate solo puede usarlo un agente con permiso para delegar.")


@herramienta(
    "ask_user",
    "Hace una pregunta al usuario cuando falta información imprescindible. No la uses para pedir permiso.",
    [Param("question", "pregunta concreta")],
    "<ask_user>\n<question>¿Querés guardar los datos en JSON o en SQLite?</question>\n</ask_user>",
)
def ask_user(ctx: Contexto, p: dict) -> str:
    if not ctx.ui.interactivo:
        return "El usuario no está disponible. Elegí la opción más simple y segura, y dejala anotada en el informe."
    respuesta = ctx.ui.preguntar(f"  [{ctx.etiqueta}] {p['question']}")
    return f"Respuesta del usuario: {respuesta or '(sin respuesta)'}"


@herramienta(
    "attempt_completion",
    "Termina la tarea. Solo cuando verificaste el resultado. REAPER valida los archivos cambiados antes de aceptar.",
    [Param("result", "informe final: qué hiciste, archivos, cómo se verificó, pendientes", largo=True)],
    "<attempt_completion>\n<result>\nAgregué hoy() en utils/fechas.py y su test. run_tests: 3 tests pasaron.\n</result>\n</attempt_completion>",
)
def attempt_completion(ctx: Contexto, p: dict) -> str:  # pragma: no cover - lo intercepta el agente
    return p.get("result", "")


def resumen_params(nombre: str, params: dict) -> str:
    if nombre in ("read_file", "write_to_file", "replace_in_file", "code_outline", "list_files"):
        detalle = params.get("path", "")
        if nombre == "read_file" and (params.get("desde") or params.get("hasta")):
            detalle += f" [{params.get('desde', '')}-{params.get('hasta', '')}]"
        return detalle
    if nombre == "search_files":
        return f"/{params.get('regex', '')}/ {params.get('file_pattern', '')}"
    if nombre == "execute_command":
        return params.get("command", "")
    if nombre == "delegate":
        return f"{params.get('role', '?')}: {params.get('task', '')[:70]}"
    if nombre == "validate":
        return params.get("paths", "(cambios)")
    return ""


# ======================================================================
# MÓDULO: roles
# ======================================================================
"""Roles de agentes y construcción del system prompt."""




LECTURA = ("read_file", "list_files", "search_files", "code_outline")
ESCRITURA = ("write_to_file", "replace_in_file")
VERIFICACION = ("validate", "run_tests")


@dataclass(frozen=True)
class Rol:
    nombre: str
    mision: str
    herramientas: tuple
    temperatura: float
    solo_lectura: bool = False
    puede_delegar: bool = False


ROLES = {
    "principal": Rol(
        "principal",
        """Sos el AGENTE PRINCIPAL. Resolvé el pedido del usuario de punta a punta: entender, explorar lo
necesario, editar, verificar con herramientas reales y reportar.
- Si el pedido es solo una pregunta que no requiere tocar archivos, respondé directo en texto, sin herramientas.
- Para tareas de varios pasos, armá una lista con update_todo y mantenela al día.
- Para entender un proyecto grande, delegá a subagentes 'explorador' EN PARALELO (varios <delegate> en el mismo
  mensaje, cada uno con una pregunta distinta): así no llenás tu contexto leyendo archivos enteros.
- Podés delegar una parte acotada a un 'implementador' o pedir una revisión a un 'revisor'.
- Antes de terminar, corré validate y, si hay tests, run_tests.""",
        LECTURA + ESCRITURA + VERIFICACION
        + ("execute_command", "view_diff", "update_todo", "delegate", "ask_user", "attempt_completion"),
        0.2,
        puede_delegar=True,
    ),
    "explorador": Rol(
        "explorador",
        """Sos un EXPLORADOR (solo lectura). Investigá el código para responder la tarea, nada más.
Sé eficiente: list_files, search_files y code_outline antes de leer archivos enteros; leé solo lo necesario.
Tu attempt_completion es un INFORME para otro agente que no vio nada. Incluí:
1. Archivos relevantes con rutas exactas y qué contiene cada uno.
2. Funciones/clases clave con número de línea y cómo se conectan.
3. Convenciones del proyecto (estilo, framework, cómo se testea, cómo se ejecuta).
4. Riesgos o dudas.
No escribas código nuevo largo.""",
        LECTURA + ("attempt_completion",),
        0.2,
        solo_lectura=True,
    ),
    "arquitecto": Rol(
        "arquitecto",
        """Sos el ARQUITECTO (solo lectura). Convertí el pedido en un plan de tareas pequeñas, concretas y
verificables, ordenadas por dependencia. Cada tarea toca pocos archivos y la puede hacer un implementador
que solo lee esa tarea. Verificá con herramientas qué existe antes de planificar cambios sobre ello.
Tu attempt_completion DEBE contener el plan EXACTAMENTE con este formato:
<plan>
<objetivo>una frase</objetivo>
<tarea id="1" archivos="ruta/a.py, ruta/b.py">Qué hacer: funciones, firmas, comportamiento, casos borde.</tarea>
<tarea id="2" archivos="tests/test_a.py">...</tarea>
<criterios>
- criterio de aceptación comprobable con un test o un comando
</criterios>
</plan>""",
        LECTURA + ("attempt_completion",),
        0.3,
        solo_lectura=True,
    ),
    "implementador": Rol(
        "implementador",
        """Sos el IMPLEMENTADOR. Implementá SOLO la tarea asignada con código real, completo y funcionando.
Flujo: leé los archivos involucrados → editá (replace_in_file para existentes, write_to_file para nuevos) →
mirá la validación que devuelve cada edición y corregí errores → si hay tests, run_tests → attempt_completion.
No toques archivos fuera de la tarea salvo que sea imprescindible (y decilo en el informe).
Informe final: archivos tocados, qué hiciste, cómo lo verificaste (resultados reales).""",
        LECTURA + ESCRITURA + VERIFICACION + ("execute_command", "update_todo", "attempt_completion"),
        0.15,
    ),
    "revisor": Rol(
        "revisor",
        """Sos el REVISOR senior (solo lectura). Revisá los cambios contra la tarea: bugs de lógica, imports,
rutas, manejo de errores, casos borde, estado, seguridad de archivos, compatibilidad Termux y coherencia
entre archivos. Confirmá leyendo el código real; no inventes problemas ni pidas cambios de estilo.
Tu attempt_completion DEBE empezar con UNA de estas líneas:
VEREDICTO: APROBADO
VEREDICTO: CAMBIOS
Si es CAMBIOS, seguí con una lista numerada: archivo, problema concreto, corrección exacta.""",
        LECTURA + ("view_diff", "validate", "attempt_completion"),
        0.2,
        solo_lectura=True,
    ),
    "qa": Rol(
        "qa",
        """Sos QA. Escribí tests automáticos REALES que verifiquen los criterios de aceptación y ejecutalos.
- Python: unittest de la librería estándar en tests/test_<modulo>.py (salvo que el proyecto ya use pytest).
- JavaScript: el runner que ya exista o node:test en tests/<modulo>.test.mjs.
- Tests deterministas, sin red, sin input() y rápidos; usá archivos temporales (tempfile) si hace falta.
Ejecutalos con run_tests. Si falla porque el TEST está mal, corregí el test. Si falla porque el CÓDIGO tiene
un bug, NO toques el código ni debilites el test: describilo en el informe con el error real.""",
        LECTURA + ESCRITURA + VERIFICACION + ("execute_command", "attempt_completion"),
        0.2,
    ),
    "reparador": Rol(
        "reparador",
        """Sos el REPARADOR. Recibís diagnósticos REALES de validadores y tests. Leé el código, encontrá la
causa raíz y corregila con el cambio mínimo. Nunca borres, saltees ni debilites tests para que pasen.
Después de corregir, ejecutá validate y run_tests para confirmar.
Informe: causa raíz, cambio hecho y resultado real de la verificación.""",
        LECTURA + ESCRITURA + VERIFICACION + ("execute_command", "attempt_completion"),
        0.15,
    ),
}

ROLES_DELEGABLES = ("explorador", "implementador", "revisor", "qa", "reparador", "arquitecto")

BASE = """Sos REAPER, un agente de programación autónomo. Trabajás DENTRO de un workspace real usando
herramientas: leés, editás y ejecutás de verdad. Respondés siempre en español.

PRINCIPIOS
1. Verificá, no supongas: leé antes de editar. No inventes archivos, APIs, paquetes, comandos ni resultados.
2. Nunca afirmes que algo funciona o que un test pasó si no lo viste en un <resultado> real.
3. Cambios mínimos y precisos; no reescribas lo que ya funciona.
4. Manejá errores de forma explícita (nada de `except: pass`).
5. Entorno Termux/Android: sin sudo, sin systemd, sin /usr/bin; preferí la librería estándar.
6. Seguridad ofensiva solo en sistemas propios, laboratorios, CTF o con autorización explícita.

CÓMO USAR LAS HERRAMIENTAS
- Escribí la herramienta como etiquetas XML, igual que en los ejemplos. Podés poner 1-3 frases de
  razonamiento antes.
- Máximo {max_llamadas} herramientas por mensaje. Después FRENÁ: REAPER las ejecuta y te contesta con
  <resultado ...>. NUNCA escribas <resultado> vos ni inventes su contenido.
- Archivo existente: primero read_file, después replace_in_file con SEARCH copiado EXACTO (sin los
  números de línea "  12| ").
- Archivo nuevo: write_to_file con el contenido COMPLETO. Prohibido "...", "resto igual" o similares.
- Si un archivo nuevo es muy largo (más de ~250 líneas), creá una base y agregá el resto con replace_in_file.
- Cada edición devuelve la validación real. Si dice VALIDACIÓN FALLÓ, corregí eso primero.
- Al terminar usá attempt_completion con un informe concreto.

EJEMPLO
Pedido: agregá una función resta a calc.py
Vos:
Leo calc.py para ver su contenido.
<read_file>
<path>calc.py</path>
</read_file>
(REAPER contesta con <resultado> y el archivo; recién entonces seguís)
Vos:
<replace_in_file>
<path>calc.py</path>
<diff>
<<<<<<< SEARCH
def suma(a, b):
    return a + b
=======
def suma(a, b):
    return a + b


def resta(a, b):
    return a - b
>>>>>>> REPLACE
</diff>
</replace_in_file>"""


def _entorno() -> str:
    termux = "com.termux" in os.getenv("PREFIX", "") or os.path.isdir("/data/data/com.termux")
    sistema = "Termux en Android" if termux else f"{platform.system()} {platform.release()}"
    herramientas = [n for n in ("node", "npm", "git", "ruff", "go", "cargo", "make") if shutil.which(n)]
    return (
        f"- Sistema: {sistema}\n"
        f"- Python: {sys.version.split()[0]} ({sys.executable})\n"
        f"- Herramientas disponibles: {', '.join(herramientas) or 'solo python'}"
    )


def system_prompt(rol: Rol, ws: Workspace, max_llamadas: int = 4, arbol: bool = True) -> str:
    partes = [
        BASE.replace("{max_llamadas}", str(max_llamadas)),
        f"\n# TU ROL: {rol.nombre.upper()}\n{rol.mision}",
        "\n# HERRAMIENTAS DISPONIBLES\n" + documentacion(list(rol.herramientas)),
        f"\n# ENTORNO\n- Workspace: {ws.raiz}\n{_entorno()}",
    ]
    memoria = ws.memoria()
    if memoria:
        partes.append(f"\n# MEMORIA DEL PROYECTO\n{memoria}")
    if arbol:
        partes.append(f"\n# ARCHIVOS DEL WORKSPACE (parcial)\n{ws.arbol(limite=80)}")
    return "\n".join(partes)


# ======================================================================
# MÓDULO: agent
# ======================================================================
"""
Bucle de agente con herramientas (estilo Claude Code / Codex) y subagentes.

Cada agente:
  1. recibe una tarea y un system prompt con su rol y sus herramientas
  2. el modelo responde con razonamiento corto + llamadas a herramientas
  3. REAPER ejecuta las herramientas de verdad y devuelve <resultado>
  4. repite hasta attempt_completion, que solo se acepta si la validación
     real de los archivos cambiados pasa

Trucos para que un modelo de 24B rinda:
  - contexto chico por subagente (cada uno arranca limpio)
  - stop en "<resultado" para que no invente resultados
  - lecturas viejas se reemplazan cuando el archivo cambia (evita SEARCH obsoletos)
  - compactación automática antes de llenar los 32k de contexto
  - detección de bucles y recordatorios de formato
"""




STOP = ["<resultado", "<tool_result"]
MAX_OBSERVACION = 9000
CARACTERES_POR_TOKEN = 3.0

CANCELAR = threading.Event()

ALIAS_ROLES = {
    "explorer": "explorador", "explore": "explorador", "investigador": "explorador",
    "implementer": "implementador", "coder": "implementador", "programador": "implementador",
    "developer": "implementador", "reviewer": "revisor", "review": "revisor",
    "tester": "qa", "test": "qa", "fixer": "reparador", "debugger": "reparador",
    "architect": "arquitecto", "planner": "arquitecto", "planificador": "arquitecto",
}

RECORDATORIO = """No usaste ninguna herramienta (o el formato no se entendió). Escribí la herramienta con etiquetas XML, por ejemplo:
<read_file>
<path>archivo.py</path>
</read_file>
Para crear o cambiar archivos usá write_to_file o replace_in_file (no pegues código suelto en el chat).
Si ya terminaste:
<attempt_completion>
<result>tu informe</result>
</attempt_completion>"""

SUFIJO_SUBTAREA = (
    "\n\nSos un subagente con contexto limpio: trabajá solo en esta tarea y terminá con "
    "attempt_completion y un informe autocontenido (quien lo lea no vio tu trabajo)."
)

_RE_RESULTADO = re.compile(r'(<resultado herramienta="[^"]*"[^>]*>\n)(.*?)(\n</resultado>)', re.S)
_RE_LARGO = re.compile(r"(<(content|diff)>)(.*?)(</\2>)", re.S)


class Cancelado(Exception):
    pass


@dataclass
class ResultadoAgente:
    ok: bool
    resumen: str
    cambios: list = field(default_factory=list)
    pasos: int = 0
    motivo: str = "completado"
    rol: str = ""
    contexto: str = ""  # último razonamiento suelto del modelo (por si dejó info fuera del informe)


_contadores: dict = {}
_lock_contadores = threading.Lock()


def _etiqueta(rol: str) -> str:
    with _lock_contadores:
        contador = _contadores.setdefault(rol, itertools.count(1))
        return f"{rol}#{next(contador)}"


def _stub_resultado(m: re.Match) -> str:
    cuerpo = m.group(2)
    if len(cuerpo) <= 600:
        return m.group(0)
    cabeza = "\n".join(cuerpo.splitlines()[:6])[:400]
    return (m.group(1) + cabeza
            + "\n[... resultado recortado para ahorrar contexto; repetí la herramienta si lo necesitás]"
            + m.group(3))


def _stub_largo(m: re.Match) -> str:
    if len(m.group(3)) <= 800:
        return m.group(0)
    return m.group(1) + "\n[... contenido omitido: ya fue procesado ...]\n" + m.group(4)


class Agente:
    def __init__(
        self,
        rol: str,
        llm,
        ws: Workspace,
        settings: Settings,
        ui: UI,
        *,
        profundidad: int = 0,
        etiqueta: Optional[str] = None,
        mostrar_progreso: bool = True,
        cid_inicio: Optional[int] = None,
    ):
        self.rol = ROLES[rol]
        self.llm = llm
        self.ws = ws
        self.settings = settings
        self.ui = ui
        self.profundidad = profundidad
        self.etiqueta = etiqueta or _etiqueta(rol)
        self.mostrar_progreso = mostrar_progreso
        self.ctx = Contexto(ws, settings, ui, self.etiqueta, set(), [], cid_inicio)
        self.max_pasos = settings.max_pasos if rol == "principal" else settings.max_pasos_sub
        self.mensajes: list[dict] = []
        # Se parsean TODAS las herramientas para poder decirle al modelo cuáles no tiene permitidas.
        self._esquemas = esquemas()
        self._lecturas: list[tuple[int, str]] = []
        self._indice_tarea = 0
        self._rechazos = 0
        self._ultimo_texto = ""

    # ------------------------------------------------------------ API
    def ejecutar(self, tarea: str, cid_inicio: Optional[int] = None) -> ResultadoAgente:
        if cid_inicio is not None:
            self.ctx.cid_inicio = cid_inicio
        prompt = system_prompt(self.rol, self.ws, self.settings.max_llamadas_turno)
        if self.mensajes:
            self.mensajes[0] = {"role": "system", "content": prompt}
        else:
            self.mensajes = [{"role": "system", "content": prompt}]
        self._agregar_usuario(tarea)
        self._indice_tarea = len(self.mensajes) - 1
        self.ctx.cambios = set()
        self._rechazos = 0

        sin_herramienta = 0
        repeticiones: dict = {}
        self._ultimo_texto = ""

        for paso in range(1, self.max_pasos + 1):
            if CANCELAR.is_set():
                raise Cancelado()
            self._compactar()
            respuesta = self._llamar_modelo()
            analisis = analizar(respuesta.texto, self._esquemas)
            self.mensajes.append({
                "role": "assistant",
                "content": analisis.respuesta_limpia.strip() or "(respuesta vacía)",
            })
            if analisis.texto:
                self._ultimo_texto = analisis.texto
                self.ui.pensamiento(self.etiqueta, analisis.texto)

            if not analisis.llamadas:
                texto = analisis.texto.strip()
                es_respuesta_directa = (
                    self.rol.nombre == "principal"
                    and texto
                    and respuesta.finish_reason != "length"
                    and ((paso == 1 and "```" not in texto) or sin_herramienta >= 1)
                )
                if es_respuesta_directa:
                    return self._cerrar(texto, paso, "respuesta")
                sin_herramienta += 1
                if sin_herramienta > 2:
                    return self._cerrar(texto or "El agente no produjo un resultado.", paso, "sin_herramientas")
                aviso = RECORDATORIO
                if respuesta.finish_reason == "length":
                    aviso = ("Tu respuesta se cortó por longitud. Escribí menos por mensaje: "
                             "archivos largos en partes (base + replace_in_file).\n\n") + aviso
                self._agregar_usuario(aviso)
                continue

            sin_herramienta = 0
            limite = max(1, self.settings.max_llamadas_turno)
            llamadas, excedentes = analisis.llamadas[:limite], analisis.llamadas[limite:]
            observaciones: list[str] = []
            hubo_error = False
            final: Optional[tuple[str, bool]] = None

            i = 0
            while i < len(llamadas):
                llamada = llamadas[i]
                if llamada.nombre == "delegate":
                    grupo = [llamada]
                    while i + len(grupo) < len(llamadas) and llamadas[i + len(grupo)].nombre == "delegate":
                        grupo.append(llamadas[i + len(grupo)])
                    obs, error = self._delegar(grupo)
                    observaciones.extend(obs)
                    hubo_error |= error
                    i += len(grupo)
                    continue
                if llamada.nombre == "attempt_completion" and "attempt_completion" in self.rol.herramientas:
                    aceptado, obs, ok_final = self._intentar_terminar(hubo_error)
                    if aceptado:
                        informe = (llamada.params.get("result") or "").strip() or analisis.texto
                        final = (informe, ok_final)
                        break
                    observaciones.append(obs)
                    i += 1
                    continue
                obs, error = self._ejecutar_herramienta(llamada, repeticiones)
                observaciones.append(obs)
                hubo_error |= error
                i += 1

            if final is not None:
                return self._cerrar(final[0], paso, "completado", ok=final[1])

            if excedentes:
                observaciones.append(
                    f"(Ignoré {len(excedentes)} herramienta(s) extra: máximo {limite} por mensaje. "
                    "Repetilas si siguen haciendo falta.)"
                )
            if respuesta.finish_reason == "length":
                observaciones.append("(Tu mensaje se cortó por longitud: escribí menos por mensaje.)")
            restantes = self.max_pasos - paso
            if 0 < restantes <= 3:
                observaciones.append(f"(Te quedan {restantes} pasos: cerrá pronto con attempt_completion.)")
            self._agregar_usuario("\n\n".join(observaciones))

        return self._cerrar(
            "Se alcanzó el límite de pasos sin terminar. Último razonamiento: " + recortar(self._ultimo_texto, 800),
            self.max_pasos,
            "max_pasos",
            ok=False,
        )

    # ------------------------------------------------------------ internos
    def _cerrar(self, resumen: str, pasos: int, motivo: str, ok: Optional[bool] = None) -> ResultadoAgente:
        if ok is None:
            ok = motivo in ("completado", "respuesta")
            if self.ctx.cambios:
                ok = ok and not fallos(validar_archivos(self.ws, sorted(self.ctx.cambios)))
        return ResultadoAgente(ok, resumen, sorted(self.ctx.cambios), pasos, motivo, self.rol.nombre,
                               self._ultimo_texto)

    def _llamar_modelo(self) -> Respuesta:
        progreso = (lambda n: self.ui.progreso(self.etiqueta, n)) if self.mostrar_progreso else None
        try:
            return self.llm.chat(
                self.mensajes,
                modelo=self.settings.modelo_para(self.rol.nombre),
                temperatura=self.rol.temperatura,
                stop=STOP,
                on_progress=progreso,
            )
        finally:
            if self.mostrar_progreso:
                self.ui.fin_progreso()

    def _agregar_usuario(self, texto: str) -> None:
        if self.mensajes and self.mensajes[-1]["role"] == "user":
            self.mensajes[-1]["content"] += "\n\n" + texto
        else:
            self.mensajes.append({"role": "user", "content": texto})

    def _ejecutar_herramienta(self, llamada: Llamada, repeticiones: dict) -> tuple[str, bool]:
        nombre = llamada.nombre
        h = REGISTRO.get(nombre)

        def obs(texto: str, attrs: str = "") -> str:
            return f'<resultado herramienta="{nombre}"{attrs}>\n{texto}\n</resultado>'

        if h is None or nombre not in self.rol.herramientas:
            disponibles = ", ".join(self.rol.herramientas)
            self.ui.resultado_herramienta(False, f"herramienta no disponible: {nombre}")
            return obs(f"ERROR: '{nombre}' no existe o no está disponible para tu rol. Disponibles: {disponibles}"), True
        if not llamada.completa:
            self.ui.resultado_herramienta(False, f"{nombre}: llamada incompleta")
            return obs(
                f"ERROR: la llamada a {nombre} quedó incompleta (falta la etiqueta de cierre o se cortó tu "
                "respuesta). Si el archivo es largo, creá una base corta y agregá secciones con replace_in_file."
            ), True

        faltan = []
        for p in h.params:
            if not p.requerido:
                continue
            valor = llamada.params.get(p.nombre)
            if valor is None or (not p.largo and not str(valor).strip()):
                faltan.append(p.nombre)
        if faltan:
            self.ui.resultado_herramienta(False, f"{nombre}: faltan {', '.join(faltan)}")
            return obs(f"ERROR: faltan parámetros: {', '.join(faltan)}. Uso correcto:\n{h.ejemplo}"), True

        clave = nombre + json.dumps(llamada.params, sort_keys=True, ensure_ascii=False)
        repeticiones[clave] = repeticiones.get(clave, 0) + 1
        if repeticiones[clave] >= 3 and not h.escribe:
            self.ui.resultado_herramienta(False, f"{nombre}: llamada repetida")
            return obs(
                f"ERROR: ya hiciste exactamente esta llamada {repeticiones[clave]} veces y el resultado no cambia. "
                "Cambiá de enfoque o terminá con lo que sabés."
            ), True

        self.ui.herramienta(self.etiqueta, nombre, resumen_params(nombre, llamada.params))
        error = False
        try:
            salida = h.fn(self.ctx, llamada.params)
        except ErrorHerramienta as e:
            salida, error = f"ERROR: {e}", True
        except (Cancelado, KeyboardInterrupt):
            raise
        except Exception as e:  # una herramienta rota no debe tumbar al agente
            salida, error = f"ERROR inesperado en {nombre}: {type(e).__name__}: {e}", True
        if not error and "VALIDACIÓN FALLÓ" in salida:
            error = True
        self.ui.resultado_herramienta(not error, salida)
        salida = redactar_secretos(recortar(salida, MAX_OBSERVACION))

        attrs = ""
        ruta = None
        if "path" in llamada.params:
            try:
                ruta = self.ws.rel(self.ws.ruta(llamada.params["path"]))
            except (ErrorRuta, ValueError):
                ruta = None
        if nombre == "read_file" and ruta and not error:
            attrs = f' ruta="{ruta}"'
            self._lecturas.append((len(self.mensajes), ruta))
        if h.escribe and ruta and not salida.startswith("ERROR"):
            self._marcar_lecturas_viejas(ruta)
        return obs(salida, attrs), error

    def _marcar_lecturas_viejas(self, ruta: str) -> None:
        patron = re.compile(
            r'<resultado herramienta="read_file" ruta="' + re.escape(ruta) + r'">\n.*?\n</resultado>', re.S
        )
        reemplazo = (
            f'<resultado herramienta="read_file" ruta="{ruta}">\n'
            f"[contenido viejo de {ruta} omitido: el archivo cambió después. Releelo si necesitás editarlo otra vez.]\n"
            "</resultado>"
        )
        quedan = []
        for indice, r in self._lecturas:
            if r == ruta and indice < len(self.mensajes):
                mensaje = self.mensajes[indice]
                mensaje["content"] = patron.sub(lambda _m: reemplazo, mensaje["content"])
            else:
                quedan.append((indice, r))
        self._lecturas = quedan

    def _intentar_terminar(self, hubo_error: bool) -> tuple[bool, str, bool]:
        def obs(texto: str) -> str:
            return f'<resultado herramienta="attempt_completion">\n{texto}\n</resultado>'

        if hubo_error and self._rechazos < 2:
            self._rechazos += 1
            return False, obs(
                "No acepto el cierre todavía: hubo errores en herramientas de este mismo mensaje. "
                "Revisá esos resultados y corregí antes de terminar."
            ), False

        ok = True
        if self.ctx.cambios:
            resultados = validar_archivos(self.ws, sorted(self.ctx.cambios))
            if fallos(resultados):
                if self._rechazos < 2:
                    self._rechazos += 1
                    self.ui.aviso(f"  [{self.etiqueta}] cierre rechazado: la validación real falla")
                    return False, obs(
                        "No podés terminar todavía: la validación REAL de los archivos que cambiaste falla:\n"
                        + resumen_validacion(resultados)
                    ), False
                ok = False
        return True, "", ok

    def _delegar(self, grupo: list) -> tuple[list[str], bool]:
        def obs(texto: str, rol: str = "?") -> str:
            return f'<resultado herramienta="delegate" rol="{rol}">\n{texto}\n</resultado>'

        if not self.rol.puede_delegar or self.profundidad >= self.settings.max_profundidad:
            return [obs("ERROR: no podés lanzar subagentes desde acá; hacé la tarea vos.")] * len(grupo), True

        salida: list[Optional[str]] = [None] * len(grupo)
        specs = []
        error = False
        for k, llamada in enumerate(grupo):
            rol = (llamada.params.get("role") or "").strip().lower()
            rol = ALIAS_ROLES.get(rol, rol)
            tarea = (llamada.params.get("task") or "").strip()
            if rol not in ROLES_DELEGABLES or not tarea:
                salida[k] = obs(
                    f"ERROR: rol inválido o tarea vacía. Roles válidos: {', '.join(ROLES_DELEGABLES)}", rol or "?"
                )
                error = True
                continue
            specs.append((k, rol, tarea, llamada.params.get("files") or ""))

        resultados = ejecutar_subagentes(
            [(rol, tarea, archivos) for _, rol, tarea, archivos in specs],
            self.llm, self.ws, self.settings, self.ui,
            profundidad=self.profundidad + 1,
            cid_inicio=self.ctx.cid_inicio,
        )
        for (k, rol, _tarea, _archivos), res in zip(specs, resultados):
            self.ctx.cambios.update(res.cambios)
            estado = "COMPLETADO" if res.ok else f"NO COMPLETADO ({res.motivo})"
            salida[k] = obs(
                f"Subagente {rol}: {estado} en {res.pasos} pasos.\n"
                f"Archivos cambiados: {', '.join(res.cambios) or 'ninguno'}\n"
                f"Informe:\n{recortar(redactar_secretos(res.resumen), 6000)}",
                rol,
            )
            error |= not res.ok
        return [s or obs("ERROR interno") for s in salida], error

    # ------------------------------------------------------------ contexto
    def _tamano(self) -> int:
        return sum(len(m["content"]) for m in self.mensajes)

    def _compactar(self) -> None:
        limite = int((self.settings.contexto_tokens - self.settings.max_tokens) * 0.85 * CARACTERES_POR_TOKEN)
        if self._tamano() <= limite:
            return
        proteger = max(self._indice_tarea + 1, len(self.mensajes) - 6)

        # Fase 1: resultados viejos largos → resumen corto.
        for i in range(1, proteger):
            m = self.mensajes[i]
            if m["role"] == "user" and "<resultado" in m["content"]:
                m["content"] = _RE_RESULTADO.sub(_stub_resultado, m["content"])
                if self._tamano() <= limite:
                    return
        # Fase 2: código ya aplicado en mensajes viejos del modelo.
        for i in range(1, proteger):
            m = self.mensajes[i]
            if m["role"] == "assistant":
                m["content"] = _RE_LARGO.sub(_stub_largo, m["content"])
                if self._tamano() <= limite:
                    return
        # Fase 3: descartar el medio de la conversación (se conserva la tarea y la cola).
        if self._indice_tarea >= proteger:
            cola = self.mensajes[self._indice_tarea:]
            descartados = self._indice_tarea - 1
            nuevos = [self.mensajes[0]] + cola
            indice = 1
        else:
            inicio = proteger
            while inicio < len(self.mensajes) and self.mensajes[inicio]["role"] != "assistant":
                inicio += 1
            descartados = inicio - self._indice_tarea - 1
            nuevos = [self.mensajes[0], dict(self.mensajes[self._indice_tarea])] + self.mensajes[inicio:]
            indice = 1
        if descartados > 0:
            todo = "\n".join(f"[{e}] {t}" for e, t in self.ctx.todo)
            nota = f"\n\n[REAPER: se omitieron {descartados} mensajes anteriores para ahorrar contexto."
            if todo:
                nota += f" Tu lista de tareas actual:\n{todo}"
            if self.ctx.cambios:
                nota += f"\nArchivos que ya cambiaste: {', '.join(sorted(self.ctx.cambios))}"
            nuevos[indice] = {"role": "user", "content": nuevos[indice]["content"] + nota + "]"}
        self.mensajes = nuevos
        self._indice_tarea = indice
        self._lecturas = []
        # Último recurso: recortar todo resultado salvo el del último mensaje.
        if self._tamano() > limite:
            for m in self.mensajes[1:-1]:
                if m["role"] == "user":
                    m["content"] = _RE_RESULTADO.sub(_stub_resultado, m["content"])
                else:
                    m["content"] = _RE_LARGO.sub(_stub_largo, m["content"])


def _titulo(tarea: str) -> str:
    """Primera línea útil de la tarea (saltea encabezados tipo 'PEDIDO DEL USUARIO:')."""
    for linea in tarea.splitlines():
        linea = linea.strip()
        if linea and not (linea.endswith(":") and linea.upper() == linea):
            return linea[:100] + ("…" if len(linea) > 100 else "")
    return "(sin descripción)"


def ejecutar_subagentes(
    specs: list,
    llm,
    ws: Workspace,
    settings: Settings,
    ui: UI,
    *,
    profundidad: int = 1,
    cid_inicio: Optional[int] = None,
) -> list[ResultadoAgente]:
    """
    Corre subagentes. specs: (rol, tarea, archivos[, título]).
    Si todos son de solo lectura (explorador, revisor,
    arquitecto) corren en paralelo; si alguno escribe, van en secuencia
    para no pisarse archivos.
    """
    paralelo = (
        len(specs) > 1
        and settings.paralelo > 1
        and all(ROLES[spec[0]].solo_lectura for spec in specs)
    )

    def correr(spec, progreso: bool) -> ResultadoAgente:
        rol, tarea, archivos, *extra = spec
        titulo = extra[0] if extra else _titulo(tarea)
        agente = Agente(rol, llm, ws, settings, ui, profundidad=profundidad,
                        mostrar_progreso=progreso, cid_inicio=cid_inicio)
        ui.agente(agente.etiqueta, f"↳ {titulo}")
        texto = tarea + (f"\n\nArchivos relevantes: {archivos}" if archivos else "") + SUFIJO_SUBTAREA
        try:
            res = agente.ejecutar(texto)
        except (Cancelado, KeyboardInterrupt, LLMError):
            # Si el modelo no responde (después de reintentos y respaldos) no tiene sentido seguir.
            raise
        except Exception as e:
            res = ResultadoAgente(False, f"{type(e).__name__}: {e}", sorted(agente.ctx.cambios), 0, "error", rol)
        ui.agente(agente.etiqueta, ("✓ terminó" if res.ok else f"✗ no completó ({res.motivo})") + f" · {res.pasos} pasos")
        return res

    if not paralelo:
        return [correr(s, True) for s in specs]

    ui.tenue(f"  ⇉ {len(specs)} subagentes en paralelo (máx {settings.paralelo} a la vez)")
    ejecutor = ThreadPoolExecutor(max_workers=min(settings.paralelo, len(specs)))
    try:
        futuros = [ejecutor.submit(correr, s, False) for s in specs]
        return [f.result() for f in futuros]
    except (KeyboardInterrupt, Cancelado):
        CANCELAR.set()
        raise
    finally:
        ejecutor.shutdown(wait=not CANCELAR.is_set(), cancel_futures=True)


# ======================================================================
# MÓDULO: pipeline
# ======================================================================
"""
Pipeline /construir: un equipo de subagentes con verificación real.

    PEDIDO
      ↓
    Exploradores (en paralelo, solo lectura) → informe del código real
      ↓
    Arquitecto → plan en tareas pequeñas + criterios de aceptación
      ↓
    confirmación del usuario (puede pedir cambios al plan)
      ↓
    por cada tarea:  checkpoint → Implementador (herramientas reales, valida
                     cada edición) → Revisor (lee el diff real) → correcciones
      ↓
    QA → escribe y corre tests reales
      ↓
    verificación: validadores + suite de tests
      ↓ ¿falló?
    Reparador (diagnóstico real) → re-verificar  (hasta N veces)
      ↓
    BUILD VERIFICADA / FALLIDA + informe + /deshacer de toda la build
"""




_RE_TAREA = re.compile(r"<\s*(tarea|task)\b([^>]*)>(.*?)<\s*/\s*\1\s*>", re.S | re.I)
_RE_ATTR = re.compile(r"(\w+)\s*=\s*[\"']([^\"']*)[\"']")
_RE_OBJETIVO = re.compile(r"<\s*objetivo\s*>(.*?)<\s*/\s*objetivo\s*>", re.S | re.I)
_RE_CRITERIOS = re.compile(r"<\s*criterios\s*>(.*?)<\s*/\s*criterios\s*>", re.S | re.I)
_RE_VEREDICTO = re.compile(r"VEREDICTO\s*:?\s*\**\s*(APROBADO|CAMBIOS|RECHAZADO)", re.I)

EXTENSIONES_TESTEABLES = (".py", ".js", ".mjs", ".cjs", ".ts")


@dataclass
class Tarea:
    id: str
    descripcion: str
    archivos: list = field(default_factory=list)


@dataclass
class Plan:
    objetivo: str
    tareas: list
    criterios: list
    texto: str = ""

    def como_texto(self, actual: Optional[int] = None, hechas: int = 0) -> str:
        lineas = [f"Objetivo: {self.objetivo}"]
        for i, t in enumerate(self.tareas):
            marca = "✓" if i < hechas else ("▸" if i == actual else " ")
            archivos = f" [{', '.join(t.archivos)}]" if t.archivos else ""
            lineas.append(f"[{marca}] {t.id}. {recortar(t.descripcion, 400)}{archivos}")
        if self.criterios:
            lineas.append("Criterios de aceptación:")
            lineas.extend(f"- {c}" for c in self.criterios)
        return "\n".join(lineas)


def parsear_plan(texto: str, pedido: str, max_tareas: int = 8) -> Plan:
    texto = texto or ""
    m = _RE_OBJETIVO.search(texto)
    objetivo = m.group(1).strip() if m else recortar(pedido.strip().splitlines()[0], 200)

    tareas: list[Tarea] = []
    for m in _RE_TAREA.finditer(texto):
        attrs = {k.lower(): v for k, v in _RE_ATTR.findall(m.group(2))}
        lista = attrs.get("archivos") or attrs.get("files") or ""
        archivos = [a.strip() for a in re.split(r"[,;\s]+", lista) if a.strip()]
        descripcion = m.group(3).strip()
        if descripcion:
            tareas.append(Tarea(attrs.get("id") or str(len(tareas) + 1), descripcion, archivos))

    if not tareas:
        sin_criterios = _RE_CRITERIOS.sub("", texto)
        for linea in sin_criterios.splitlines():
            m = re.match(r"^\s*(?:tarea\s*)?(\d+)[.):-]\s+(.{8,})$", linea, re.I)
            if m:
                tareas.append(Tarea(m.group(1), m.group(2).strip(), []))
    if not tareas:
        tareas = [Tarea("1", pedido.strip(), [])]

    if len(tareas) > max_tareas:
        sobrantes = tareas[max_tareas - 1:]
        tareas = tareas[: max_tareas - 1] + [Tarea(
            sobrantes[0].id,
            "\n".join(f"- {t.descripcion}" for t in sobrantes),
            sorted({a for t in sobrantes for a in t.archivos}),
        )]

    criterios = []
    m = _RE_CRITERIOS.search(texto)
    if m:
        for linea in m.group(1).splitlines():
            linea = re.sub(r"^\s*([-*•]|\d+[.)])\s*", "", linea).strip()
            if linea:
                criterios.append(linea)
    return Plan(objetivo, tareas, criterios, texto)


def veredicto(informe: str) -> tuple[bool, bool]:
    """(aprobado, claro). Si el revisor no respeta el formato se aprueba para no entrar en bucles."""
    m = _RE_VEREDICTO.search(informe or "")
    if not m:
        return True, False
    return m.group(1).upper() == "APROBADO", True


@dataclass
class Verificacion:
    ok: bool
    validaciones: list
    tests: Optional[Resultado]
    diagnostico: str
    archivos: list


@dataclass
class InformeBuild:
    estado: str
    plan: Optional[Plan] = None
    archivos: list = field(default_factory=list)
    tests: Optional[Resultado] = None
    diagnostico: str = ""
    cid: Optional[int] = None
    ruta_informe: Optional[Path] = None
    notas: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.estado in ("verificada", "validada")


def _diffstat(diff: str) -> str:
    stats: dict[str, list[int]] = {}
    actual = None
    for linea in diff.splitlines():
        if linea.startswith("+++ b/"):
            actual = linea[6:]
            stats.setdefault(actual, [0, 0])
        elif actual and linea.startswith("+") and not linea.startswith("+++"):
            stats[actual][0] += 1
        elif actual and linea.startswith("-") and not linea.startswith("---"):
            stats[actual][1] += 1
    return "\n".join(f"  {a}  +{m} -{n}" for a, (m, n) in stats.items())


class Orquestador:
    def __init__(self, llm, ws: Workspace, settings: Settings, ui: UI):
        self.llm = llm
        self.ws = ws
        self.settings = settings
        self.ui = ui

    def _sub(self, rol: str, tarea: str, cid: Optional[int], archivos: str = "", titulo: str = "") -> ResultadoAgente:
        spec = (rol, tarea, archivos, titulo) if titulo else (rol, tarea, archivos)
        return ejecutar_subagentes(
            [spec], self.llm, self.ws, self.settings, self.ui,
            profundidad=1, cid_inicio=cid,
        )[0]

    # ------------------------------------------------------------ fases
    def explorar(self, pedido: str) -> str:
        archivos = self.ws.archivos_codigo(limite=500)
        if not archivos:
            return "El workspace está vacío: hay que crear todo desde cero."
        if len(archivos) <= 6:
            # Proyecto chico: un mapa directo sale gratis y no gasta llamadas al modelo.
            partes = ["Proyecto chico; mapa completo:"]
            for rel in archivos:
                simbolos = outline(self.ws.raiz / rel)
                partes.append(rel + ("\n" + "\n".join("  " + s for s in simbolos[:30]) if simbolos else ""))
            return "\n".join(partes)

        specs = [(
            "explorador",
            f"PEDIDO DEL USUARIO:\n{pedido}\n\nInvestigá qué partes del código tocan este pedido: archivos, "
            "funciones y clases involucradas, cómo se conectan y qué convenciones hay que respetar.",
            "",
            "código relacionado con el pedido",
        )]
        if len(archivos) > 15 and self.settings.paralelo > 1:
            specs.append((
                "explorador",
                f"PEDIDO DEL USUARIO:\n{pedido}\n\nNO analices la lógica del pedido. Investigá cómo se ejecuta y "
                "cómo se prueba este proyecto: puntos de entrada, dependencias, tests existentes y su comando, "
                "estructura de carpetas y configuración.",
                "",
                "cómo se ejecuta y se prueba el proyecto",
            ))
        resultados = ejecutar_subagentes(specs, self.llm, self.ws, self.settings, self.ui, profundidad=1)
        return "\n\n".join(
            f"### Informe explorador {i}\n{r.resumen}" for i, r in enumerate(resultados, start=1)
        )

    def planificar(self, pedido: str, exploracion: str, feedback: str = "", anterior: Optional[Plan] = None) -> Plan:
        detectado = detectar_comando_tests(self.ws)
        tarea = (
            f"PEDIDO DEL USUARIO:\n{pedido}\n\n"
            f"INFORME DE EXPLORACIÓN (código real):\n{recortar(exploracion, 7000)}\n\n"
            f"Comando de tests detectado: {detectado[0] if detectado else 'ninguno (habrá que crear tests)'}\n"
            f"Armá el plan con un máximo de {self.settings.max_tareas} tareas."
        )
        if anterior and feedback:
            tarea += (
                f"\n\nPLAN ANTERIOR:\n{anterior.como_texto()}\n\n"
                f"EL USUARIO PIDIÓ ESTOS CAMBIOS AL PLAN:\n{feedback}"
            )
        res = self._sub("arquitecto", tarea, None, titulo="diseña el plan de tareas")
        texto = res.resumen
        if not _RE_TAREA.search(texto) and _RE_TAREA.search(res.contexto):
            texto = res.contexto + "\n" + texto
        plan = parsear_plan(texto, pedido, self.settings.max_tareas)
        if not res.ok:
            self.ui.aviso("El arquitecto no terminó limpio; uso lo que produjo.")
        return plan

    def implementar(self, pedido: str, plan: Plan, indice: int, exploracion: str,
                    cid: int, correcciones: str = "") -> ResultadoAgente:
        tarea = plan.tareas[indice]
        texto = (
            f"PEDIDO ORIGINAL DEL USUARIO:\n{pedido}\n\n"
            f"PLAN GENERAL:\n{plan.como_texto(actual=indice, hechas=indice)}\n\n"
            f"TU TAREA AHORA (#{tarea.id}):\n{tarea.descripcion}\n\n"
            f"CONTEXTO DE EXPLORACIÓN:\n{recortar(exploracion, 3500)}\n\n"
            "Implementá SOLO esta tarea (las demás las hacen otros). Leé antes de editar."
        )
        if correcciones:
            texto += (
                "\n\nUN REVISOR YA REVISÓ TU TRABAJO EN ESTA TAREA Y PIDIÓ CAMBIOS. Aplicalos (si alguno es "
                f"incorrecto, explicá por qué en el informe):\n{recortar(correcciones, 4000)}"
            )
        titulo = f"tarea {tarea.id}: {recortar(tarea.descripcion.splitlines()[0], 90)}"
        if correcciones:
            titulo = f"corrige tarea {tarea.id} según el revisor"
        return self._sub("implementador", texto, cid, ", ".join(tarea.archivos), titulo)

    def revisar(self, pedido: str, tarea: Tarea, diff: str, cid: int) -> tuple[bool, str]:
        rels = self.ws.checkpoints.archivos_desde(cid)
        validacion = resumen_validacion(validar_archivos(self.ws, rels), limite=1500)
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"TAREA REVISADA (#{tarea.id}):\n{tarea.descripcion}\n\n"
            f"DIFF REAL DE LOS CAMBIOS:\n```diff\n{recortar(diff, 12000)}\n```\n\n"
            f"Validación automática de los archivos cambiados: {validacion}\n\n"
            "Leé los archivos completos si necesitás contexto. Empezá tu informe con la línea VEREDICTO."
        )
        res = self._sub("revisor", texto, cid, titulo=f"revisa el diff de la tarea {tarea.id}")
        aprobado, claro = veredicto(res.resumen)
        if not claro:
            self.ui.tenue("  (el revisor no usó el formato VEREDICTO: se toma como aprobado)")
        return aprobado, res.resumen

    def qa(self, pedido: str, plan: Plan, archivos: list, cid: int) -> ResultadoAgente:
        detectado = detectar_comando_tests(self.ws)
        criterios = "\n".join(f"- {c}" for c in plan.criterios) or "- (derivalos del pedido)"
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"CRITERIOS DE ACEPTACIÓN:\n{criterios}\n\n"
            f"ARCHIVOS CAMBIADOS EN ESTA BUILD: {', '.join(archivos)}\n"
            f"Comando de tests detectado: {detectado[0] if detectado else 'ninguno todavía'}\n\n"
            "Escribí (o completá) tests automáticos que verifiquen los criterios y corrélos con run_tests. "
            "Reportá el resultado REAL."
        )
        return self._sub("qa", texto, cid, titulo="escribe y corre tests de aceptación")

    def verificar(self, cid: int) -> Verificacion:
        archivos = [r for r in self.ws.checkpoints.archivos_desde(cid) if (self.ws.raiz / r).is_file()]
        validaciones = validar_archivos(self.ws, archivos)
        tests = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout)
        malos = fallos(validaciones)
        tests_ok = tests is None or tests.ok
        partes = [r.resumen(2500) for r in malos]
        if tests is not None and not tests.ok:
            partes.append("TESTS:\n" + tests.resumen(5000))
        return Verificacion(not malos and tests_ok, validaciones, tests, "\n\n".join(partes), archivos)

    def reparar(self, pedido: str, verif: Verificacion, cid: int, base_fallaba: bool) -> ResultadoAgente:
        texto = (
            f"PEDIDO ORIGINAL:\n{pedido}\n\n"
            f"La build tiene fallos REALES. Diagnóstico de validadores/tests:\n{verif.diagnostico}\n\n"
            f"Archivos cambiados en esta build: {', '.join(verif.archivos)}\n"
        )
        if base_fallaba:
            texto += "Ojo: la suite de tests ya fallaba ANTES de esta build; priorizá los fallos causados por los cambios.\n"
        texto += "Encontrá la causa raíz y corregila. No debilites ni borres tests."
        return self._sub("reparador", texto, cid, titulo="arregla los fallos reales de la verificación")

    # ------------------------------------------------------------ flujos
    def _mostrar_plan(self, plan: Plan) -> None:
        self.ui.titulo("PLAN")
        self.ui.linea(plan.como_texto())

    def obtener_plan(self, pedido: str, confirmar: bool) -> tuple[Optional[Plan], str]:
        self.ui.titulo("FASE 1 · Exploración")
        exploracion = self.explorar(pedido)
        self.ui.titulo("FASE 2 · Arquitectura")
        plan = self.planificar(pedido, exploracion)
        for _ in range(3):
            self._mostrar_plan(plan)
            if not confirmar or self.ui.confirmar("¿Aprobás el plan y arrancamos?", defecto=True):
                return plan, exploracion
            feedback = self.ui.preguntar("¿Qué cambiarías del plan? (Enter vacío = cancelar)")
            if not feedback:
                return None, exploracion
            plan = self.planificar(pedido, exploracion, feedback, plan)
        return None, exploracion

    def solo_plan(self, pedido: str) -> Optional[Path]:
        plan, exploracion = self.obtener_plan(pedido, confirmar=False)
        if plan is None:
            return None
        carpeta = self.ws.raiz / ".reaper" / "planes"
        ruta = carpeta / f"plan_{datetime.now():%Y%m%d_%H%M%S}.md"
        escritura_atomica(ruta, (
            f"# Plan REAPER\n\n## Pedido\n{pedido}\n\n## Plan\n```\n{plan.como_texto()}\n```\n\n"
            f"## Exploración\n{exploracion}\n\n## Respuesta del arquitecto\n{plan.texto}\n"
        ))
        return ruta

    def construir(self, pedido: str, confirmar: bool = True) -> InformeBuild:
        base = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout)
        base_fallaba = base is not None and not base.ok
        if base_fallaba:
            self.ui.aviso("Atención: la suite de tests YA falla antes de empezar; se tendrá en cuenta.")

        plan, exploracion = self.obtener_plan(pedido, confirmar)
        if plan is None:
            self.ui.tenue("Construcción cancelada; no se tocó ningún archivo.")
            return InformeBuild("cancelada")

        grupo = self.ws.checkpoints.iniciar(f"construir: {pedido[:80]}")
        informe = InformeBuild("fallida", plan=plan, cid=grupo)

        self.ui.titulo("FASE 3 · Implementación")
        for i, tarea in enumerate(plan.tareas):
            self.ui.info(f"\n▸ Tarea {i + 1}/{len(plan.tareas)}: {recortar(tarea.descripcion.splitlines()[0], 120)}")
            tcid = grupo if i == 0 else self.ws.checkpoints.iniciar(f"tarea {tarea.id}", grupo=grupo)
            res = self.implementar(pedido, plan, i, exploracion, tcid)
            if not res.ok:
                informe.notas.append(f"Tarea {tarea.id}: el implementador no terminó limpio ({res.motivo}).")
            for ronda in range(self.settings.max_revisiones):
                diff = self.ws.checkpoints.diff_desde(tcid)
                if not diff.strip():
                    informe.notas.append(f"Tarea {tarea.id}: sin cambios en archivos.")
                    break
                aprobado, revision = self.revisar(pedido, tarea, diff, tcid)
                if aprobado:
                    self.ui.ok(f"Revisor aprobó la tarea {tarea.id}")
                    break
                self.ui.aviso(f"  Revisor pidió cambios en la tarea {tarea.id} (ronda {ronda + 1})")
                if ronda + 1 >= self.settings.max_revisiones:
                    informe.notas.append(f"Tarea {tarea.id}: quedaron observaciones del revisor sin resolver.")
                    break
                self.implementar(pedido, plan, i, exploracion, tcid, correcciones=revision)

        archivos = [r for r in self.ws.checkpoints.archivos_desde(grupo) if (self.ws.raiz / r).is_file()]
        testeable = any(a.endswith(EXTENSIONES_TESTEABLES) for a in archivos)
        if self.settings.qa and testeable:
            self.ui.titulo("FASE 4 · QA (tests reales)")
            qcid = self.ws.checkpoints.iniciar("qa", grupo=grupo)
            self.qa(pedido, plan, archivos, qcid)

        self.ui.titulo("FASE 5 · Verificación real")
        verif = self.verificar(grupo)
        self._mostrar_verificacion(verif)
        diagnosticos_vistos: list[str] = []
        intento = 0
        while not verif.ok and intento < self.settings.max_reparaciones:
            if diagnosticos_vistos.count(verif.diagnostico) >= 2:
                informe.notas.append("La reparación no logró avances (mismo diagnóstico repetido).")
                break
            diagnosticos_vistos.append(verif.diagnostico)
            intento += 1
            self.ui.titulo(f"REPARACIÓN {intento}/{self.settings.max_reparaciones}")
            rcid = self.ws.checkpoints.iniciar(f"reparación {intento}", grupo=grupo)
            self.reparar(pedido, verif, rcid, base_fallaba)
            verif = self.verificar(grupo)
            self._mostrar_verificacion(verif)

        informe.archivos = verif.archivos
        informe.tests = verif.tests
        informe.diagnostico = verif.diagnostico
        if verif.ok:
            informe.estado = "verificada" if verif.tests is not None and not verif.tests.omitido else "validada"
        informe.ruta_informe = self._guardar_informe(pedido, informe)
        self._mostrar_cierre(informe)
        return informe

    # ------------------------------------------------------------ salida
    def _mostrar_verificacion(self, verif: Verificacion) -> None:
        for r in verif.validaciones:
            if not r.ok:
                self.ui.error(r.linea()[2:])
        malos = len(fallos(verif.validaciones))
        self.ui.linea(f"  validadores: {len(verif.validaciones) - malos}/{len(verif.validaciones)} OK")
        if verif.tests is None:
            self.ui.aviso("  tests: no hay suite detectada")
        elif verif.tests.omitido:
            self.ui.aviso("  tests: la suite no encontró tests")
        elif verif.tests.ok:
            self.ui.ok(f"tests: pasaron ({verif.tests.comando})")
        else:
            self.ui.error(f"tests: fallaron ({verif.tests.comando})")
            self.ui.tenue(recortar((verif.tests.stdout + "\n" + verif.tests.stderr).strip(), 1500))

    def _guardar_informe(self, pedido: str, informe: InformeBuild) -> Optional[Path]:
        try:
            diff = self.ws.checkpoints.diff_desde(informe.cid) if informe.cid else ""
            tests = informe.tests.resumen(4000) if informe.tests else "sin suite de tests"
            contenido = (
                f"# Build REAPER — {informe.estado.upper()}\n\n"
                f"Fecha: {datetime.now():%Y-%m-%d %H:%M}\n\n## Pedido\n{pedido}\n\n"
                f"## Plan\n```\n{informe.plan.como_texto() if informe.plan else '-'}\n```\n\n"
                f"## Archivos\n```\n{_diffstat(diff) or '-'}\n```\n\n"
                f"## Tests\n```\n{tests}\n```\n\n"
                + (f"## Diagnóstico pendiente\n```\n{informe.diagnostico}\n```\n\n" if informe.diagnostico else "")
                + ("## Notas\n" + "\n".join(f"- {n}" for n in informe.notas) + "\n" if informe.notas else "")
            )
            ruta = self.ws.raiz / ".reaper" / "informes" / f"build_{datetime.now():%Y%m%d_%H%M%S}.md"
            escritura_atomica(ruta, contenido)
            return ruta
        except OSError as e:
            self.ui.aviso(f"No pude guardar el informe: {e}")
            return None

    def _mostrar_cierre(self, informe: InformeBuild) -> None:
        if informe.estado == "verificada":
            self.ui.titulo("✓ BUILD VERIFICADA (validadores + tests reales)")
        elif informe.estado == "validada":
            self.ui.titulo("✓ BUILD VALIDADA (validadores OK, sin tests que correr)")
        else:
            self.ui.titulo("✗ BUILD FALLIDA")
        diff = self.ws.checkpoints.diff_desde(informe.cid) if informe.cid else ""
        if diff:
            self.ui.linea(_diffstat(diff))
        for nota in informe.notas:
            self.ui.aviso(f"  • {nota}")
        if informe.ruta_informe:
            self.ui.tenue(f"  informe: {informe.ruta_informe}")
        self.ui.tenue("  /diff para ver los cambios · /deshacer revierte TODA la build\n")

    def revisar_proyecto(self, foco: str = "") -> str:
        archivos = [a for a in self.ws.archivos_codigo(limite=400)
                    if a.endswith((".py", ".js", ".mjs", ".ts", ".sh", ".html", ".css"))]
        if not archivos:
            return "No hay archivos de código para revisar."
        grupos = max(1, min(self.settings.paralelo, (len(archivos) + 11) // 12))
        lotes = [archivos[i::grupos] for i in range(grupos)]
        specs = []
        for lote in lotes:
            specs.append((
                "revisor",
                "Revisión general del proyecto (no hay diff). Revisá estos archivos buscando bugs reales, "
                "errores de manejo de excepciones, problemas de compatibilidad con Termux y riesgos de seguridad. "
                + (f"Foco pedido por el usuario: {foco}. " if foco else "")
                + "Empezá con VEREDICTO (APROBADO si no hay problemas graves) y después: hallazgos confirmados "
                "(archivo:línea), riesgos probables marcados como inferidos y qué arreglar primero.\n\n"
                f"Archivos asignados: {', '.join(lote)}",
                "",
                f"revisa {len(lote)} archivos",
            ))
        resultados = ejecutar_subagentes(specs, self.llm, self.ws, self.settings, self.ui, profundidad=1)
        return "\n\n".join(f"### Revisor {i}\n{r.resumen}" for i, r in enumerate(resultados, start=1))


# ======================================================================
# MÓDULO: cli
# ======================================================================
"""REPL interactivo y modo línea de comandos de REAPER v6."""




BANNER = f"""{C.CYAN}{C.BOLD}
  ╔══════════════════════════════════════════════════╗
  ║   {C.MAGENTA}R E A P E R  v6{C.CYAN} · agente autónomo para Termux   ║
  ╚══════════════════════════════════════════════════╝{C.RESET}"""

AYUDA = f"""{C.CYAN}{C.BOLD} USO {C.RESET}
  Escribí lo que necesitás en lenguaje natural: el agente lee, edita, ejecuta
  y verifica en el proyecto activo (puede lanzar subagentes en paralelo).
  Texto de varias líneas: empezá y terminá con una línea que diga \"\"\"
  {C.VERDE}!comando{C.RESET}              corre un comando de shell vos mismo (interactivo)

{C.CYAN}{C.BOLD} EQUIPO {C.RESET}
  {C.VERDE}/construir{C.RESET} <pedido>   exploradores → arquitecto → implementador+revisor por tarea
                         → QA → validadores+tests reales → reparador
  {C.VERDE}/plan{C.RESET} <pedido>        solo exploración + plan (se guarda en .reaper/planes)
  {C.VERDE}/agente{C.RESET} <rol> <tarea> corre un subagente suelto ({", ".join(ROLES_DELEGABLES)})
  {C.VERDE}/revisar{C.RESET} [foco]       revisores en paralelo sobre todo el proyecto
  {C.VERDE}/init{C.RESET}                 genera REAPER.md (memoria del proyecto)

{C.CYAN}{C.BOLD} PROYECTO {C.RESET}
  {C.VERDE}/proyecto{C.RESET} [ruta]      cambia de workspace
  {C.VERDE}/scan{C.RESET}                 validadores sobre todo el proyecto
  {C.VERDE}/tests{C.RESET}                corre la suite de tests detectada
  {C.VERDE}/validar{C.RESET} [archivos]   valida archivos puntuales
  {C.VERDE}/correr{C.RESET} <archivo> [args]  ejecuta y ofrece reparar si crashea
  {C.VERDE}/diff{C.RESET}                 cambios del último pedido/build
  {C.VERDE}/deshacer{C.RESET}             revierte el último pedido/build completo
  {C.VERDE}/checkpoints{C.RESET}          historial de checkpoints

{C.CYAN}{C.BOLD} AJUSTES {C.RESET}
  {C.VERDE}/modo{C.RESET} [{"|".join(MODOS)}]
  {C.VERDE}/modelo{C.RESET} [alias]  ·  /modelo <rol> <alias>  (ej: /modelo revisor qwen)
  {C.VERDE}/modelos{C.RESET}  {C.VERDE}/config{C.RESET} [clave valor]  {C.VERDE}/uso{C.RESET}  {C.VERDE}/todo{C.RESET}  {C.VERDE}/estado{C.RESET}  {C.VERDE}/reset{C.RESET}  {C.VERDE}/salir{C.RESET}
"""

INIT_TAREA = """Analizá este proyecto y redactá el contenido de un archivo REAPER.md: la memoria del proyecto
que leerán otros agentes de IA antes de trabajar. Secciones:
# <nombre del proyecto>
## Descripción (2-3 líneas)
## Cómo ejecutar
## Cómo testear (comando exacto; si no hay tests, decilo)
## Estructura (archivos clave y para qué sirven)
## Convenciones (lenguaje, estilo, librerías, idioma de la interfaz)
Máximo 60 líneas y SOLO hechos que verificaste leyendo el código.
Tu attempt_completion debe contener ÚNICAMENTE el markdown del archivo."""


def mostrar_markdown(ui: UI, texto: str) -> None:
    pos = 0
    for m in re.finditer(r"```([\w+#.-]*)\n(.*?)```", texto, re.S):
        antes = texto[pos:m.start()].strip()
        if antes:
            ui.linea(f"{C.BLANCO}{antes}{C.RESET}")
        etiqueta = f" {m.group(1) or 'código'} "
        ui.linea(f"{C.GRIS}┌{etiqueta}{'─' * max(0, 50 - len(etiqueta))}{C.RESET}")
        ui.linea(m.group(2).rstrip("\n"))
        ui.linea(f"{C.GRIS}└{'─' * 50}{C.RESET}")
        pos = m.end()
    resto = texto[pos:].strip()
    if resto:
        ui.linea(f"{C.BLANCO}{resto}{C.RESET}")


def resolver_workspace(texto: str) -> Path:
    ruta = Path(os.path.expandvars(texto.strip())).expanduser().resolve()
    if not ruta.exists():
        raise ErrorRuta(f"No existe: {ruta}")
    if not ruta.is_dir():
        raise ErrorRuta(f"No es una carpeta: {ruta}")
    if not os.getenv("REAPER_LIBRE"):
        home = Path.home().resolve()
        if ruta != home and home not in ruta.parents:
            raise ErrorRuta(
                f"Por seguridad el proyecto debe estar dentro de {home} (o exportá REAPER_LIBRE=1)."
            )
    return ruta


class App:
    def __init__(self, settings: Settings, llm, ui: UI, ws: Workspace, persistir: bool = True):
        self.settings = settings
        self.llm = llm
        self.ui = ui
        self.ws = ws
        self.persistir = persistir
        self.aviso_sesion = ""
        self.principal = self._nuevo_principal()
        if persistir:
            self._cargar_sesion()

    # ------------------------------------------------------------ sesión
    def _nuevo_principal(self) -> Agente:
        return Agente("principal", self.llm, self.ws, self.settings, self.ui, etiqueta="reaper")

    def _ruta_sesion(self) -> Path:
        return SESIONES_DIR / f"{self.ws.checkpoints.carpeta.name}.json"

    def _guardar_sesion(self) -> None:
        if not self.persistir:
            return
        try:
            SESIONES_DIR.mkdir(parents=True, exist_ok=True)
            mensajes = self.principal.mensajes[1:][-60:]
            while mensajes and mensajes[0]["role"] != "user":
                mensajes = mensajes[1:]
            datos = {"mensajes": mensajes, "todo": self.principal.ctx.todo}
            self._ruta_sesion().write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            self.ui.aviso(f"No pude guardar la sesión: {e}")

    def _cargar_sesion(self) -> None:
        try:
            datos = json.loads(self._ruta_sesion().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        mensajes = [m for m in datos.get("mensajes", [])
                    if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
        if mensajes:
            self.principal.mensajes = [{"role": "system", "content": ""}] + mensajes
            self.principal.ctx.todo[:] = [tuple(t) for t in datos.get("todo", []) if len(t) == 2]
            self.aviso_sesion = f"  retomé la sesión anterior de este proyecto ({len(mensajes)} mensajes) · /reset para empezar de cero"

    def cambiar_workspace(self, ruta: Path) -> None:
        self._guardar_sesion()
        self.ws = Workspace(ruta)
        self.principal = self._nuevo_principal()
        if self.persistir:
            guardar_estado(proyecto=str(self.ws.raiz))
            self._cargar_sesion()
            if self.aviso_sesion:
                self.ui.tenue(self.aviso_sesion)

    # ------------------------------------------------------------ acciones
    def turno(self, texto: str) -> bool:
        cid = self.ws.checkpoints.iniciar(f"pedido: {texto[:80]}")
        try:
            res = self.principal.ejecutar(texto, cid_inicio=cid)
        finally:
            self._guardar_sesion()
            self.ws.checkpoints.descartar_si_vacio(cid)
        self.ui.linea("")
        self.ui.linea(f"{C.MAGENTA}{C.BOLD}reaper »{C.RESET}")
        mostrar_markdown(self.ui, res.resumen)
        if res.cambios:
            self.ui.tenue(
                f"\n  {len(res.cambios)} archivo(s) cambiados: {', '.join(res.cambios[:8])}"
                f"{' ...' if len(res.cambios) > 8 else ''} · /diff · /deshacer"
            )
        if not res.ok:
            self.ui.aviso(f"  (terminó con estado: {res.motivo})")
        self.ui.linea("")
        return res.ok

    def construir(self, pedido: str, confirmar: bool = True) -> bool:
        informe = Orquestador(self.llm, self.ws, self.settings, self.ui).construir(pedido, confirmar)
        return informe.ok

    # ------------------------------------------------------------ comandos
    def comando(self, entrada: str) -> Optional[str]:
        partes = entrada.split(maxsplit=1)
        cmd = partes[0].lower()
        arg = partes[1].strip() if len(partes) > 1 else ""
        metodo = getattr(self, "cmd_" + cmd[1:].replace("-", "_"), None)
        alias = {"/help": self.cmd_ayuda, "/exit": self.cmd_salir, "/quit": self.cmd_salir,
                 "/equipo": self.cmd_plan, "/undo": self.cmd_deshacer, "/build": self.cmd_construir}
        metodo = metodo or alias.get(cmd)
        if metodo is None:
            self.ui.error(f"Comando desconocido: {cmd} (probá /ayuda)")
            return None
        return metodo(arg)

    def cmd_ayuda(self, arg: str) -> None:
        self.ui.linea(AYUDA)

    def cmd_salir(self, arg: str) -> str:
        self._guardar_sesion()
        self.ui.tenue("Chau (sesión guardada).")
        return "salir"

    def cmd_construir(self, arg: str) -> None:
        if not arg:
            self.ui.tenue("Uso: /construir <qué querés construir>")
            return
        self.construir(arg)

    def cmd_plan(self, arg: str) -> None:
        if not arg:
            self.ui.tenue("Uso: /plan <qué querés diseñar>")
            return
        ruta = Orquestador(self.llm, self.ws, self.settings, self.ui).solo_plan(arg)
        if ruta:
            self.ui.ok(f"Plan guardado en {ruta}")

    def cmd_agente(self, arg: str) -> None:
        partes = arg.split(maxsplit=1)
        if len(partes) < 2 or partes[0].lower() not in ROLES_DELEGABLES:
            self.ui.tenue(f"Uso: /agente <{'|'.join(ROLES_DELEGABLES)}> <tarea>")
            return
        cid = self.ws.checkpoints.iniciar(f"agente {partes[0]}: {partes[1][:60]}")
        res = ejecutar_subagentes([(partes[0].lower(), partes[1], "")], self.llm, self.ws,
                                  self.settings, self.ui, profundidad=1, cid_inicio=cid)[0]
        self.ws.checkpoints.descartar_si_vacio(cid)
        self.ui.linea("")
        mostrar_markdown(self.ui, res.resumen)
        self.ui.linea("")

    def cmd_revisar(self, arg: str) -> None:
        informe = Orquestador(self.llm, self.ws, self.settings, self.ui).revisar_proyecto(arg)
        self.ui.titulo("REVISIÓN")
        mostrar_markdown(self.ui, informe)

    def cmd_init(self, arg: str) -> None:
        destino = self.ws.raiz / "REAPER.md"
        if destino.exists() and not self.ui.confirmar("REAPER.md ya existe. ¿Regenerarlo?"):
            return
        res = ejecutar_subagentes([("explorador", INIT_TAREA, "")], self.llm, self.ws,
                                  self.settings, self.ui, profundidad=1)[0]
        contenido = res.resumen.strip()
        m = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*?)\n```", contenido, re.S)
        if m:
            contenido = m.group(1)
        if len(contenido) < 40:
            self.ui.error("El explorador no produjo un REAPER.md utilizable.")
            return
        cid = self.ws.checkpoints.iniciar("init REAPER.md")
        self.ws.escribir("REAPER.md", contenido.rstrip() + "\n")
        self.ws.checkpoints.descartar_si_vacio(cid)
        self.ui.ok("REAPER.md creado: los agentes lo leen en cada tarea (editalo cuando quieras).")

    def cmd_proyecto(self, arg: str) -> None:
        if not arg:
            self.ui.info(f"Proyecto activo: {self.ws.raiz}")
            return
        try:
            ruta = resolver_workspace(arg)
        except ErrorRuta as e:
            self.ui.error(str(e))
            return
        self.cambiar_workspace(ruta)
        detectado = detectar_comando_tests(self.ws)
        self.ui.ok(f"Proyecto: {self.ws.raiz}")
        self.ui.tenue(f"  {len(self.ws.archivos_codigo())} archivos de texto · tests: "
                      f"{detectado[0] if detectado else 'no detectados'}"
                      f"{' · memoria: REAPER.md' if self.ws.memoria() else ' · tip: /init crea REAPER.md'}")

    def cmd_scan(self, arg: str) -> None:
        archivos = self.ws.archivos_codigo(limite=400)
        por_ext: dict[str, int] = {}
        for a in archivos:
            ext = Path(a).suffix or Path(a).name
            por_ext[ext] = por_ext.get(ext, 0) + 1
        self.ui.info(f"Proyecto: {self.ws.raiz}")
        self.ui.tenue("  " + " · ".join(f"{k}:{v}" for k, v in sorted(por_ext.items(), key=lambda kv: -kv[1])[:12]))
        resultados = validar_archivos(self.ws, archivos)
        malos = fallos(resultados)
        self.ui.linea(f"  validaciones: {len(resultados) - len(malos)}/{len(resultados)} OK")
        for r in malos[:25]:
            self.ui.error(r.linea()[2:])
            self.ui.tenue(recortar(r.stderr or r.stdout, 600))
        detectado = detectar_comando_tests(self.ws)
        self.ui.tenue(f"  tests: {detectado[0] if detectado else 'no detectados'}")

    def cmd_tests(self, arg: str) -> None:
        detectado = detectar_comando_tests(self.ws)
        if not detectado:
            self.ui.aviso("No detecté una suite de tests.")
            return
        self.ui.info(f"Ejecutando {detectado[0]} ...")
        r = ejecutar_tests(self.ws, timeout=self.settings.tests_timeout)
        self.ui.linea(recortar((r.stdout + "\n" + r.stderr).strip(), 6000))
        (self.ui.ok if r.ok else self.ui.error)(f"tests {'OK' if r.ok else 'FALLARON'} (exit {r.codigo})")

    def cmd_validar(self, arg: str) -> None:
        rels = shlex.split(arg) if arg else self.ws.checkpoints.archivos_desde(self.ws.checkpoints.inicio_grupo() or 1)
        if not rels:
            self.ui.tenue("Uso: /validar archivo.py [otro.js ...]")
            return
        for r in validar_archivos(self.ws, rels):
            (self.ui.ok if r.ok else self.ui.error)(r.linea()[2:])
            if not r.ok:
                self.ui.tenue(recortar(r.stderr or r.stdout, 1500))

    def cmd_correr(self, arg: str) -> None:
        try:
            tokens = shlex.split(arg)
        except ValueError as e:
            self.ui.error(f"Argumentos inválidos: {e}")
            return
        if not tokens:
            self.ui.tenue("Uso: /correr archivo.py [args...]   (para programas interactivos usá !python3 archivo.py)")
            return
        try:
            ruta = self.ws.ruta(tokens[0])
        except ErrorRuta as e:
            self.ui.error(str(e))
            return
        lanzadores = {".py": [sys.executable], ".sh": ["bash"], ".js": ["node"], ".mjs": ["node"], ".cjs": ["node"]}
        if not ruta.is_file() or ruta.suffix not in lanzadores:
            self.ui.error("Archivo inexistente o tipo no ejecutable (.py .sh .js .mjs .cjs).")
            return
        rel = self.ws.rel(ruta)
        for intento in range(1, 4):
            r = ejecutar(lanzadores[ruta.suffix] + [rel] + tokens[1:], cwd=self.ws.raiz,
                             timeout=self.settings.exec_timeout)
            self.ui.linea(recortar(r.stdout.strip(), 6000))
            if r.stderr.strip():
                self.ui.aviso(recortar(r.stderr.strip(), 4000))
            self.ui.tenue(f"exit code: {r.codigo}")
            if r.ok:
                self.ui.ok("Ejecución correcta.")
                return
            if not es_crash_real(r):
                self.ui.aviso("Terminó con error controlado (sin traceback): no lo trato como bug.")
                return
            if intento == 3 or not self.ui.confirmar("Crash detectado. ¿Lo mando al reparador?"):
                return
            cid = self.ws.checkpoints.iniciar(f"reparar {rel}")
            tarea = (f"Al ejecutar `{r.comando}` el programa falló:\n{r.resumen(4000)}\n\n"
                     f"Archivo principal: {rel}. Encontrá la causa raíz y corregila. "
                     "Podés verificar con execute_command usando el mismo comando.")
            ejecutar_subagentes([("reparador", tarea, rel)], self.llm, self.ws, self.settings,
                                self.ui, profundidad=1, cid_inicio=cid)
            self.ws.checkpoints.descartar_si_vacio(cid)
            self.ui.info("Reintentando ejecución...")

    def cmd_diff(self, arg: str) -> None:
        cid = self.ws.checkpoints.inicio_grupo()
        if cid is None:
            self.ui.tenue("No hay cambios registrados.")
            return
        diff = self.ws.checkpoints.diff_desde(cid)
        if not diff.strip():
            self.ui.tenue("El último checkpoint no tiene diferencias.")
            return
        self.ui.diff(diff, max_lineas=500)

    def cmd_deshacer(self, arg: str) -> None:
        cid = int(arg) if arg.isdigit() else self.ws.checkpoints.inicio_grupo()
        if cid is None:
            self.ui.tenue("No hay nada para deshacer.")
            return
        archivos = self.ws.checkpoints.archivos_desde(cid)
        etiqueta = next((m["etiqueta"] for m in self.ws.checkpoints.listar() if m["id"] == cid), "?")
        self.ui.aviso(f"Se revierte «{etiqueta}» y todo lo posterior: {', '.join(archivos) or '(sin archivos)'}")
        if not self.ui.confirmar("¿Confirmás?"):
            return
        tocados = self.ws.checkpoints.deshacer(cid)
        self.ui.ok(f"Revertidos {len(tocados)} archivo(s).")

    def cmd_checkpoints(self, arg: str) -> None:
        lista = self.ws.checkpoints.listar()
        if not lista:
            self.ui.tenue("Sin checkpoints.")
            return
        for m in lista[-15:]:
            grupo = f" (build {m['grupo']})" if m.get("grupo") != m["id"] else ""
            self.ui.linea(f"  {m['id']:>4}  {m['fecha']}  {len(m['archivos'])} arch.  {m['etiqueta']}{grupo}")
        self.ui.tenue("  /deshacer <id> revierte desde ese checkpoint")

    def cmd_todo(self, arg: str) -> None:
        if not self.principal.ctx.todo:
            self.ui.tenue("La lista de tareas está vacía.")
        for estado, texto in self.principal.ctx.todo:
            self.ui.linea(f"  {'✓' if estado == 'x' else '▸' if estado == '>' else '○'} {texto}")

    def cmd_modo(self, arg: str) -> None:
        if arg not in MODOS:
            self.ui.info(f"Modo actual: {self.settings.modo}  (opciones: {', '.join(MODOS)})")
            return
        self.settings.modo = arg
        guardar_settings(self.settings)
        self.ui.ok(f"Modo: {arg}")

    def cmd_modelo(self, arg: str) -> None:
        partes = arg.split()
        if not partes:
            self.ui.info(f"Modelo principal: {self.settings.modelo}")
            for rol, modelo in self.settings.modelos_rol.items():
                self.ui.tenue(f"  {rol}: {resolver_modelo(modelo)}")
            return
        if len(partes) == 2 and partes[0].lower() in ROLES:
            rol = partes[0].lower()
            if partes[1] in ("-", "default", "ninguno"):
                self.settings.modelos_rol.pop(rol, None)
            else:
                self.settings.modelos_rol[rol] = resolver_modelo(partes[1])
            self.ui.ok(f"{rol} → {self.settings.modelo_para(rol)}")
        else:
            self.settings.modelo = resolver_modelo(partes[0])
            self.ui.ok(f"Modelo principal: {self.settings.modelo}")
        guardar_settings(self.settings)

    def cmd_modelos(self, arg: str) -> None:
        for alias, modelo in MODELOS.items():
            self.ui.linea(f"  {C.VERDE}{alias:12}{C.RESET}{C.GRIS}{modelo}{C.RESET}")
        self.ui.tenue("  Cualquier id de OpenRouter sirve también: /modelo proveedor/modelo")

    def cmd_config(self, arg: str) -> None:
        if not arg:
            self.ui.linea(json.dumps(self.settings.to_dict(), ensure_ascii=False, indent=2))
            self.ui.tenue(f"  archivo: {CONFIG_FILE} · cambiar: /config <clave> <valor>")
            return
        partes = arg.split(maxsplit=1)
        if len(partes) != 2 or not hasattr(self.settings, partes[0]):
            self.ui.error("Uso: /config <clave> <valor>  (ej: /config paralelo 3)")
            return
        clave, texto = partes
        actual = getattr(self.settings, clave)
        try:
            if isinstance(actual, bool):
                valor = texto.lower() in ("1", "true", "si", "sí", "s", "on")
            elif isinstance(actual, int):
                valor = int(texto)
            elif isinstance(actual, float):
                valor = float(texto)
            elif isinstance(actual, (list, dict)):
                valor = json.loads(texto)
                if not isinstance(valor, type(actual)):
                    raise ValueError(f"se esperaba {type(actual).__name__}")
            else:
                valor = texto
        except ValueError as e:
            self.ui.error(f"Valor inválido: {e}")
            return
        setattr(self.settings, clave, valor)
        guardar_settings(self.settings)
        self.ui.ok(f"{clave} = {valor!r}")

    def cmd_uso(self, arg: str) -> None:
        u = self.llm.uso
        self.ui.info(f"Llamadas: {u.llamadas} · tokens entrada: {u.tokens_entrada} · salida: {u.tokens_salida}"
                     + (f" · costo: ${u.costo:.4f}" if u.costo else ""))

    def cmd_reset(self, arg: str) -> None:
        self.principal = self._nuevo_principal()
        try:
            self._ruta_sesion().unlink()
        except OSError:
            pass
        self.ui.aviso("Conversación reiniciada (los archivos y checkpoints no se tocan).")

    def cmd_estado(self, arg: str) -> None:
        detectado = detectar_comando_tests(self.ws)
        self.ui.info("ESTADO REAPER")
        self.ui.linea(f"  proyecto: {self.ws.raiz}")
        self.ui.linea(f"  modelo:   {self.settings.modelo}")
        self.ui.linea(f"  modo:     {self.settings.modo} · paralelo: {self.settings.paralelo}")
        self.ui.linea(f"  memoria:  {len(self.principal.mensajes)} mensajes · checkpoints: {len(self.ws.checkpoints.ids())}")
        self.ui.linea(f"  tests:    {detectado[0] if detectado else 'no detectados'}")

    def shell(self, comando: str) -> None:
        if not comando.strip():
            return
        try:
            subprocess.run(comando, shell=True, cwd=str(self.ws.raiz))
        except OSError as e:
            self.ui.error(str(e))

    # ------------------------------------------------------------ REPL
    def _leer_entrada(self) -> str:
        entrada = input(f"{C.VERDE}{C.BOLD}vos ›{C.RESET} ")
        if entrada.strip() != '"""':
            return entrada.strip()
        lineas = []
        while True:
            linea = input(f"{C.AZUL}│ {C.RESET}")
            if linea.strip() == '"""':
                return "\n".join(lineas).strip()
            lineas.append(linea)

    def repl(self) -> int:
        self.ui.linea(BANNER)
        self.ui.tenue(f"  proyecto: {self.ws.raiz}")
        self.ui.tenue(f"  modelo:   {self.settings.modelo} · modo: {self.settings.modo}")
        if self.aviso_sesion:
            self.ui.tenue(self.aviso_sesion)
        self.ui.tenue("  escribí lo que necesitás, o /ayuda\n")
        while True:
            try:
                entrada = self._leer_entrada()
            except (EOFError, KeyboardInterrupt):
                self.ui.linea("")
                self.cmd_salir("")
                return 0
            if not entrada:
                continue
            CANCELAR.clear()
            try:
                if entrada.startswith("!"):
                    self.shell(entrada[1:])
                elif entrada.startswith("/"):
                    if self.comando(entrada) == "salir":
                        return 0
                else:
                    self.turno(entrada)
            except (KeyboardInterrupt, Cancelado):
                CANCELAR.set()
                self.ui.fin_progreso()
                self.ui.aviso("\n⏹ Interrumpido. Lo ya escrito queda en disco; /diff para ver, /deshacer para revertir.")
                self._guardar_sesion()
            except LLMError as e:
                self.ui.error(f"Modelo: {e}")
            except ErrorRuta as e:
                self.ui.error(str(e))


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="reaper", description="REAPER v6 · agente de programación autónomo")
    parser.add_argument("-p", "--pedido", help="ejecuta un pedido con el agente principal y sale")
    parser.add_argument("--construir", help="corre el pipeline completo de construcción y sale")
    parser.add_argument("--plan", help="solo exploración + plan y sale")
    parser.add_argument("--proyecto", help="carpeta del workspace")
    parser.add_argument("--modelo", help="alias o id de OpenRouter (solo esta ejecución)")
    parser.add_argument("--modo", choices=MODOS, help="permisos (solo esta ejecución)")
    parser.add_argument("--auto", action="store_true", help="equivale a --modo auto y sin confirmar el plan")
    parser.add_argument("--version", action="version", version=f"REAPER {__version__}")
    args = parser.parse_args(argv)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print(f"{C.ROJO}Falta OPENROUTER_API_KEY.{C.RESET}\n  export OPENROUTER_API_KEY=\"tu_key\"")
        return 1

    asegurar_dirs()
    settings = cargar_settings()
    if args.modelo:
        settings.modelo = resolver_modelo(args.modelo)
    if args.modo:
        settings.modo = args.modo
    if args.auto:
        settings.modo = "auto"

    no_interactivo = bool(args.pedido or args.construir or args.plan)
    ui = UI(interactivo=not no_interactivo or sys.stdin.isatty())

    try:
        if args.proyecto:
            raiz = resolver_workspace(args.proyecto)
        else:
            guardado = cargar_estado().get("proyecto")
            raiz = Path(guardado) if guardado and Path(guardado).is_dir() else PROJECTS_DIR
        ws = Workspace(raiz)
    except ErrorRuta as e:
        ui.error(str(e))
        return 1

    app = App(settings, LLMClient(api_key, settings), ui, ws)
    if args.proyecto:
        guardar_estado(proyecto=str(ws.raiz))

    try:
        if args.construir:
            return 0 if app.construir(args.construir, confirmar=not args.auto) else 2
        if args.plan:
            app.cmd_plan(args.plan)
            return 0
        if args.pedido:
            return 0 if app.turno(args.pedido) else 2
        return app.repl()
    except (KeyboardInterrupt, Cancelado):
        CANCELAR.set()
        ui.aviso("\n⏹ Interrumpido.")
        return 130
    except LLMError as e:
        ui.error(f"Modelo: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
