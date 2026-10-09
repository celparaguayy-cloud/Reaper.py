# REAPER v11 — BASELINE (Fase 0)

**Fecha:** 2026-10-09 · **Rama:** `ccr-6e025352-3tb6n4` · **Archivo empaquetado:** `reaper_v8.py` (~43k líneas, 93 partes)

Diagnóstico REAL del repositorio antes de implementar v11. No se declara nada como "hecho" sin código y
pruebas asociadas. Estados: `PRESENTE` (existe y con autotests), `PARCIAL` (existe parte), `AUSENTE` (por
construir), `NO-OBJETIVO` (el propio spec lo prohíbe).

## Cómo está construido REAPER

- **Bundle de una sola pieza:** `partes/NN_nombre.py` → `empaquetar.py` → `reaper_v8.py`. Todas las partes
  cargan en UN namespace compartido (los nombres de nivel superior no pueden colisionar; el empaquetador lo
  verifica y falla si hay duplicados).
- **Autotests internos:** `python3 reaper_v8.py --autotest` (sin API, con MockLLM). Hoy: **472 en verde**.
- **Workflow de commit:** empaquetar → autotest → commit/push solo si pasa.
- **Entorno objetivo:** Termux/Android, stdlib preferida (sin dependencias pesadas, sin `yaml` garantizado).

## Mapeo spec v11 → estado actual

| Área del spec v11 | Estado | Dónde / nota |
|---|---|---|
| §3 Principios de calidad (implementador no se autoaprueba, test verde ≠ spec, etc.) | **PRESENTE** | Evidence Core (62), Spec Core (63), roles-juez (19) |
| §4 Seis roles de IA | **PARCIAL** | Roles: principal, explorador, arquitecto, especificador, implementador, revisor, qa, reparador, consultor, **adversarial_critic, spec_judge, evidence_judge** (19). Falta orquestar explícitamente "6 roles" en un blackboard estructurado |
| §4 Proveedores desacoplados + router | **PRESENTE** | Registro multi-proveedor (03b), disyuntor/circuit breaker (05b), router por desempeño (55b) |
| §4 `ModelProvider` Protocol async | **PARCIAL** | REAPER usa `LLMClient` sync sobre endpoints OpenAI-compatibles; cumple la intención (healthcheck/costos parcial), no la firma async literal |
| §5 Security Scope Gate (fuera del LLM, no ampliable por el modelo) | **PARCIAL→** | `modo_seguridad`+`/pentest` daban postura por prompt. **Fase 1 v11 agrega `PoliticaAlcance` + `PuertaAlcance` reales en código (64_scope.py)** |
| §6 Tool Forge (pipeline intención→…→catálogo) | **AUSENTE** | Existe `write_large_file`/torneo, pero no el pipeline con `tool.yaml`, catálogo versionado y gate de calidad |
| §7 Discovery / Vulnerability Research + etiquetas | **PARCIAL→** | **Fase 1 v11 agrega las etiquetas de hallazgo honestas (`EstadoHallazgo`) en 64_scope.py.** Auditores (RepoAuditor, DependencyAuditor…) AUSENTES |
| §8/§23 Lab Challenge Engine + fixtures + flag sintético | **PRESENTE** | `MotorLab` (66): 3 escenarios sintéticos, juez independiente (ground truth del motor), fixtures efímeros con reset, `LAB_FLAG` no falsificable. CLI `/lab`. Positivo/negativo/falso-positivo discriminados |
| §9 ExecutionBroker / LocalRunner / Receipts con hash+git | **PARCIAL** | `execute_command`/`run_tests` ejecutan de verdad con bloqueos de dispositivo (17); `ToolReceipt` existe (62) pero no ligado a git-rev+hashes de artefactos; falta broker que revalide alcance por operación |
| §9 SSHRunner / LabRunner (VM aislada) | **AUSENTE** | Opt-in, requiere config del operador |
| §10 Análisis de malware estático (defensivo) | **AUSENTE** | Por construir; nunca ejecutar muestras |
| §11/§24.7 Privacidad / `/privacy report` / redacción de secretos | **PARCIAL** | `redactar_secretos` existe (sanea stdout); falta `/privacy report` y política `no_upload_sensitive_artifacts` |
| §12 Máquina de estados de tareas en SQLite | **PARCIAL** | Hay checkpoints/sesiones; falta la FSM `CREATED→…→SUCCEEDED/PARTIAL/FAILED/BLOCKED` persistida |
| §13 Tests anti-mock / anti-falso-verde | **PRESENTE** | Test Intelligence (15c), discriminación en torneo (22), Evidence Gate (62) |
| §21 Adaptadores de herramientas (import offline de resultados) | **AUSENTE** | `NmapAdapter`/`NucleiAdapter`/… como parsers OFFLINE de artefactos guardados |
| §22 Dynamic Tool Forge + descubrimiento GitHub confiable | **AUSENTE** | `CapabilityPlanner`/`ToolResolver`/`SupplyChainGate`/… |

## Bloqueos de dispositivo ya presentes (NO son del gate de alcance; protegen el teléfono)

`partes/17_tools.py::_BLOQUEADOS`: `sudo`, `su`, `mkfs`, `dd if=`, fork bomb, `shutdown/reboot`, `rm -rf /|~|*`,
`curl|sh`, escribir a `/dev/sd*`, `chmod 777 /`, `git push --force`, `git reset --hard`, volcar env, `cat .env`.
Estos se conservan siempre; no frenan trabajo ofensivo, evitan que un error del modelo dañe el equipo.

## No-objetivos (el propio spec los prohíbe — NO se implementan)

Troyanos/ransomware/spyware desplegables, robo de credenciales, persistencia/evasión/movimiento lateral,
compromiso automático de IP/URL arbitrarias, ejecutar muestras de malware en el teléfono, o cualquier
mecanismo para saltarse salvaguardas de modelos. Autorización = `PoliticaAlcance` verificable, nunca una IP
suelta ni una afirmación de un modelo.

## Plan de implementación (orden del spec, por fases verificables)

1. **Fase 0 (esta):** baseline + backup por commit. ✅
2. **Fase 1 (en curso):** `PoliticaAlcance` + `PuertaAlcance` (gate fuera del LLM, no ampliable) + `EstadoHallazgo`
   + `Hallazgo` + `ReciboEjecucion` ligado a git-rev. Autotests de denegación. ← **entrega de este commit**
3. **Fase 2+:** ExecutionBroker con revalidación de alcance por operación; adaptadores OFFLINE (parsers de
   XML/JSON/PCAP guardados); Lab Challenge Engine con fixtures sintéticos y evaluador independiente; Tool Forge.
   Cada una con pruebas reales; lo no probado se marca `PLANNED`/`PARTIAL`/`NOT_VERIFIED`.
