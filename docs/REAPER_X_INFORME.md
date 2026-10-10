# REAPER X — informe de implementación (estado: EXPERIMENTAL)

Fecha: 2026-10-10. Base: este repositorio (`partes/` → `reaper_v8.py`). La especificación menciona versiones
(`reaper_v8_7ias_estable.py`, `reaper_v8_7ias_dolphin.py`, adaptador FreeModel) que **no están en este
repositorio**; todo lo de abajo se hizo y se probó sobre la base disponible.

**No es "REAPER X ESTABLE".** Según la condición final de la especificación, falta el ensayo OFICIORADAR de
extremo a extremo con modelos reales (requiere las claves del usuario) y las fases de persistencia/reanudación.

## Cómo se usa

```
/equipo x on        activa los 10 roles en /construir
/equipo             10 roles · modelos configurados · modelos VERIFICADOS (solo tras /equipo probar)
/equipo probar      prueba real de cada rol (los 10 con REAPER X)
/modelo director <alias|proveedor:id>   asignar modelo a un rol nuevo
```

## Registro de defectos de la especificación, contra ESTE repositorio

| ID | ¿Aplica aquí? | Estado | Prueba |
|---|---|---|---|
| BUG-001 clave anterior al cambiar proveedor | Sí (mitigado antes: claves por proveedor) | Corregido en commits previos | 48m, 48w |
| BUG-002 `api_url` del proyecto | Parcial | Precedencia de config corregida; el endpoint de proveedores no activos es fijo | 48w |
| BUG-003 LAN privada como "local" | Sí | Corregido: solo loopback cuenta como local (LAN/`.local` = sale del teléfono) | 48v |
| BUG-004/005 auto-asignación/ping | Sí | Conteos separados: configurados vs verificados; el ping sigue siendo conectividad, no aptitud | 48z |
| BUG-006 cierre rechazado por rojo TDD | Sí (reproducido en tu corrida) | Corregido con clasificación tipada | 48x, 48y |
| BUG-007 respuestas vacías, implementador sin archivos | Sí (reproducido) | 2 vacías → otra IA del equipo; razonamiento sin contenido → otra IA | 48x |
| BUG-008 ✓ con exit ≠ 0 | Sí | Corregido: ✗ + código de salida | 48y |
| BUG-009 ruta `src/db.py</script>` | Sí (reproducido) | Se limpia la etiqueta | 48x |
| BUG-010 test gaming (`sqlite3.Row.__str__`) | Comportamiento del modelo | **Pendiente**: sin detector específico | — |
| BUG-011 conexión SQLite compartida | Código generado por el modelo | **Pendiente**: sin regla específica | — |
| BUG-012 seguir tras tarea fallida | Sí | Corregido: dependientes BLOQUEADAS, build PARCIAL | 48y |
| BUG-013/014/016 Dolphin/alias "siete" | No existen en este repo | N/A | — |
| BUG-015 `--perfil estable` | No existe en este repo | N/A | — |
| BUG-017 claves compartidas en chat | Operativo | Rotar las claves expuestas (lo hace el usuario) | — |

Además, de la corrida real del usuario: 413 de Groq abortaba `/construir` (corregido: respaldo entre IAs y
roles de apoyo no fatales) y pytest abortaba la colección (corregido: `--continue-on-collection-errors`).

## Qué se implementó (con tests)

- **10 roles**: `director`, `supervisor`, `integrador`, `seguridad` (revisión defensiva del código del
  proyecto), `auditor_entrega`, más los existentes `arquitecto`, `implementador`, `revisor`, `qa`, `reparador`.
- **Contratos tipados** (`Dictamen`): JSON obligatorio, decisión del enum, `APPROVE` exige `evidence_ids`
  existentes, `REJECT/REWORK` exigen razones; `confidence=high` no cambia nada. Texto libre nunca se ejecuta.
- **Controlador determinista**: el estado final lo decide la verificación real; el supervisor solo objeta.
- Director (directiva) y supervisor (revisión del plan, con una replanificación si pide rehacer) antes de
  construir; seguridad, auditor y supervisor sobre evidencia al final; el integrador hace la reparación final.
- Modelo pedido vs servido declarado cuando responde un respaldo.
- Conteos honestos: 10 roles ≠ 10 IAs; OpenRouter cuenta como un proveedor; verificados solo tras prueba.
- 0 tests recolectados con archivos de test presentes ≠ éxito.

## Qué NO se implementó (pendiente, en orden sugerido)

1. Ensayo OFICIORADAR E2E con servidor HTTP real y modelos reales (necesita tus claves y cuota).
2. Descubrimiento y benchmark de modelos para integrador/seguridad/auditor desde catálogos oficiales.
3. Journal SQLite de ejecuciones, `/construir --reanudar`, locks por archivo.
4. Detector de test gaming, matriz de caos completa.
5. Migración a paquete modular (`reaper_x/`): la especificación pide hacerla gradual; no se empezó.

## Evidencia

`python3 reaper_v8.py --autotest` → 736 tests OK en Python 3.11, 3.12 y 3.13 (sin red, transportes simulados).
Smoke test de los 76 comandos (556 invocaciones): 0 excepciones, 0 archivos escritos fuera del proyecto.
