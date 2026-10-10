#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REAPER v8.0.0 «Dragón» — agente de programación autónomo para Termux vía OpenRouter
(estilo Claude Code / Codex / Antigravity, pensado para sacarle el máximo a un modelo de 24B).

Archivo único generado desde partes/ con empaquetar.py.

QUÉ TRAE LA v7
  1. Tests primero + torneo: el QA escribe la especificación ejecutable ANTES de
     implementar; por tarea compiten N implementadores en copias aisladas del
     proyecto (temperaturas 0.1 / 0.4 / 0.7) y gana el que pasa más tests reales.
  2. Escalada: si una tarea falla la verificación 2 veces, un modelo más fuerte
     (deepseek, qwen...) lee el error real y escribe el diagnóstico; Venice aplica.
  3. Lecciones entre sesiones: cada reparación real deja una lección de una línea
     en .reaper/lecciones.md (proyecto) y ~/reaper/lecciones.md (general).
  4. Archivos largos sin romperse: escritura por partes, continuación automática
     cuando el modelo se corta, esqueleto + relleno por función (replace_symbol).
  5. read_symbol / replace_symbol / find_references, mapa de archivos relevantes
     según el pedido, arreglos automáticos sin modelo, snapshots git por build.

v8 (reparación con método, en vez de prueba y error)
  - Guardia de regresión: una edición que deja los tests peor que el mejor
    estado visto se revierte sola (en el chat y en /construir), y el modelo
    recibe qué se revirtió y por qué. Antes, un "arreglo" podía llevar de 2
    a 13 fallos y quedar aplicado.
  - Modo forense (/forense, o automático al trabarse o antes de rendirse):
    aísla cada test que falla, lo repite para detectar estado que persiste
    entre corridas, compara la suite en orden directo e inverso, muestra
    variables locales, fixtures y el árbol de llamadas con lo que devolvió
    cada función, detecta archivos de datos que los tests escriben en el
    proyecto, busca por bisección el cambio que introdujo una regresión y
    pide hipótesis con experimentos que REAPER ejecuta de verdad.
  - También: modo plan, "permitir siempre", procesos en segundo plano,
    plantillas y tests en 10 lenguajes, recetas ejecutables, /manual y
    /evaluar comportamiento.

v7.1 (bugs vistos en uso real)
  - Tool loop: con "2+2" obtenía 4 y repetía execute_command. La respuesta en
    texto después de una herramienta ahora ES la respuesta final; una llamada
    idéntica sin cambios en el proyecto reutiliza el resultado y un bucle se corta.
  - Repeticiones según el estado del workspace: después de editar, volver a
    correr run_tests o releer un archivo está permitido.
  - Cumplimiento falso: un informe que dice "validé / los tests pasan" sin una
    ejecución real (o con la última fallida o bloqueada) se rechaza o se marca.
  - "Responde únicamente cuánto es 5+5. No crees archivos ni ejecutes comandos."
    → responde en texto; las prohibiciones explícitas del usuario se respetan.
  - Programas interactivos: EOFError → pista "no lo modifiques, probalo con
    <stdin>"; execute_command y run_python aceptan entrada estándar.
  - /construir: re-pide el plan si el arquitecto devuelve una sola tarea gigante;
    una tarea que no terminó tiene que mostrar progreso; no se revisa (ni se
    aprueba) una tarea cuya verificación real falla.
  - Parser: `python3 -c "print(2+2)"` ya no pierde la comilla final; se aceptan
    llamadas con etiquetas de cierre olvidadas; se ocultan los ```xml``` vacíos.

Instalar:
    pip install httpx pyflakes      (opcionales: sin httpx usa urllib)
    pkg install nodejs git          (opcionales: validan JS y guardan builds en git)

Clave:
    export OPENROUTER_API_KEY="tu_key"

Ejecutar:
    python3 reaper_v8.py                                  modo interactivo (/ayuda)
    python3 reaper_v8.py --proyecto ~/mi_app              abre un workspace
    python3 reaper_v8.py -p "agregá tests a utils.py"     un pedido y sale
    python3 reaper_v8.py --construir "API de notas" --auto
    python3 reaper_v8.py --autotest                       verifica REAPER sin gastar API
    python3 reaper_v8.py --instalar                       crea el comando `reaper`
"""

from __future__ import annotations

__version__ = "8.0.0"
__codename__ = "Dragón"

import argparse
import atexit
import ast
import base64
import collections
import contextlib
import copy
import difflib
import fnmatch
import functools
import hashlib
import heapq
import importlib.util
import io
import ipaddress
import itertools
import json
import keyword
import math
import os
import platform
import queue
import random
import re
import shlex
import shutil
import signal
import socket
import string
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import traceback
import unicodedata
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence, Union

if sys.version_info < (3, 9):  # pragma: no cover - Termux trae Python moderno
    sys.stderr.write("REAPER necesita Python 3.9 o superior (pkg upgrade python).\n")
    sys.exit(1)
