# REAPER AUTO-6-IA — AUDITORÍA PREVIA (Fase A)

**Fecha:** 2026-10-09 · **Rama:** `ccr-6e025352-3tb6n4`

Inspección real de las 6 hipótesis del §1 del MASTER SPEC contra el código de este repo (no la versión
`reaper_v8_multiapi_seguro.py` de referencia). Estados: `CONFIRMADO`, `PARCIAL`, `YA-HECHO`, `PLANNED`.

| # | Hipótesis del spec | Veredicto | Detalle / acción |
|---|---|---|---|
| 1 | `obtener_clave_api()` filtra `.clave` entre proveedores | **CONFIRMADO → CORREGIDO** | El `.clave` heredado se devolvía para cualquier proveedor. Arreglado: clave por variable de entorno del proveedor → `.clave_<proveedor>` → `.clave` heredado SOLO si declara su dueño (`REAPER_CLAVE_PROVEEDOR` o `.clave_proveedor`). `clave_de_proveedor` nunca lee el `.clave` de otro. Tests de regresión en 48m. |
| 2 | `:free` no garantiza coste cero en otros proveedores | **PARCIAL** | `es_modelo_gratis` marca `:free` como gratis; es heurística. El BudgetManager / verificación de coste cero por cuenta queda PLANNED; mientras tanto no se activan pagos solos. |
| 3 | RPM global, no por proveedor/modelo/cuenta | **CONFIRMADO (PLANNED)** | `rpm_efectivo` + `LimitadorTasa` son globales por cliente. Rate-limit por `provider+model+account` queda PLANNED; el disyuntor (05b) ya aísla fallos por modelo. |
| 4 | `INFO_MODELOS` fija no es fuente de verdad de IDs | **CONFIRMADO → PARCIAL** | Catálogo vivo OFFLINE hecho (`CatalogoModelos` 71): parser tolerante de Markdown, fichas normalizadas con nulls honestos, caché con TTL + estados de verificación, `/modelos descubrir|gratis|sincronizar`. La descarga en vivo por API oficial (ETag/allowlist) queda PLANNED (inyectable). |
| 5 | "OpenAI-compatible" ≠ soporte real de tool-calls/stream | **PARCIAL** | Las fichas de modelo marcan capacidades como desconocidas (null ≠ true). CapabilityProbe real PLANNED. |
| 6 | `/modelo` persiste alias pero no prueba conectividad | **CONFIRMADO (PARCIAL)** | `/modelo` setea alias sin probe. `/proveedores` nuevo muestra qué proveedores tienen credencial (sin exponerla); la prueba de conectividad real (`/proveedores probar`) requiere claves y queda marcada NO VERIFICADO hasta ejecutarse con consentimiento. |

## Lo que YA existía de este spec (de v9/v10/v11)

- Registro multi-proveedor + ruteo por modelo (`03b`), disyuntor/circuit-breaker por modelo (`05b`),
  router por desempeño / RoleAllocator (`55b`), TaskGraph con dependencias (`25b`), roles-juez y
  revisor≠implementer (`19`), evidencia/recibos (`62`,`64`), broker con recibos (`67`).

## Entregado en este commit (Fase A + inicio de Fase B/F)

1. `docs/REAPER_AUDITORIA_PREVIA.md` (este archivo).
2. **Fix de aislamiento de credenciales** (§1.1) con tests de regresión (una clave de un proveedor nunca
   llega a otro).
3. Proveedores free-tier añadidos como metadatos de endpoint (Groq, NVIDIA, Gemini, Mistral, Cohere,
   GitHub Models) — sin hardcodear IDs de modelo.
4. `/proveedores` — estado por proveedor SIN exponer secretos (CONFIGURADO / FALTA CLAVE / SIN CLAVE).

## Pendiente priorizado

Catálogo vivo con descubrimiento por API oficial + caché TTL (§4), CapabilityProbe real (§8),
rate-limit por proveedor/cuenta (§7.4), BudgetManager con coste-cero verificado (§7.3), y el display
"seis agentes" con métrica de independencia real (§6/§9). Nada se declara verificado sin peticiones reales.
