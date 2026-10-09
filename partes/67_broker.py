"""
ExecutionBroker (REAPER v11, §9): ejecución estructurada con evidencia y revalidación de alcance.

Es el único camino "con recibos" para correr comandos: recibe una SolicitudEjecucion TIPADA (argv como lista,
nunca una cadena de shell armada con texto no confiable), aplica las barreras en ESTE orden y de forma
independiente del LLM:

  1. argv debe ser una lista de strings  → si no, INVALID_ARGV y no ejecuta.
  2. bloqueos de dispositivo (sudo, rm -rf, dd, ...) → BLOCKED_DEVICE y no ejecuta (protegen el equipo).
  3. si requires_network: consulta la PuertaAlcance (gate de Fase 1). Fuera de alcance → no ejecuta y el
     recibo queda con veredicto SCOPE_REQUIRED / BLOCKED_BY_SCOPE / EXPIRED / DENIED.
  4. recién entonces ejecuta con shell=False, timeout y tope de salida; captura stdout/stderr/exit code.

Devuelve un ReciboEjecucion (part 64) con hashes de la salida + revisión de git + veredicto de alcance:
evidencia que un modelo no puede fabricar. No compone shell; no eleva privilegios; no toca la red salvo que
el comando lo haga y el gate lo permita.
"""


@dataclass
class SolicitudEjecucion:
    argv: list                              # SIEMPRE lista de strings (shell=False)
    cwd: str = "."
    timeout_s: int = 60
    max_output_bytes: int = 200_000
    scope_id: str = ""
    requires_network: bool = False
    host: str = ""                          # objetivo, si requires_network
    puerto: Optional[int] = None
    operacion: str = ""
    read_only: bool = False                 # metadato (enforcement duro requiere sandbox: PLANNED)
    expected_exit_codes: tuple = (0,)
    task_id: str = ""


class BrokerEjecucion:
    def __init__(self, puerta=None, raiz=None):
        self.puerta = puerta                # PuertaAlcance (part 64); None = sin alcance → red activa denegada
        self.raiz = raiz                    # raíz del proyecto, para revision_git en el recibo

    def _recibo(self, sol, run_id, veredicto, *, exit_code=None, stdout="", stderr="", artefactos=None):
        r = recibo_de_ejecucion(run_id, list(sol.argv), cwd=str(sol.cwd), exit_code=exit_code,
                                stdout=stdout, stderr=stderr, artefactos=artefactos or [], raiz=self.raiz,
                                scope_id=sol.scope_id, veredicto=veredicto, task_id=sol.task_id)
        return r

    def ejecutar(self, sol: SolicitudEjecucion) -> ReciboEjecucion:
        run_id = f"run-{uuid.uuid4().hex[:12]}"

        # 1) argv tipado (nada de componer shell con texto no confiable)
        if not isinstance(sol.argv, (list, tuple)) or not sol.argv or not all(isinstance(a, str) for a in sol.argv):
            return self._recibo(sol, run_id, "INVALID_ARGV")

        # 2) bloqueos de dispositivo (protegen el equipo; se aplican siempre, también en modo seguridad)
        patron = comando_bloqueado(" ".join(sol.argv))
        if patron:
            return self._recibo(sol, run_id, "BLOCKED_DEVICE")

        # 3) gate de alcance para operaciones activas de red (independiente del LLM)
        if sol.requires_network:
            puerta = self.puerta if self.puerta is not None else PuertaAlcance()
            decision = puerta.decidir(sol.host, sol.puerto, sol.operacion)
            if not decision.permitido:
                return self._recibo(sol, run_id, decision.estado)
            veredicto = decision.estado          # ALLOW
        else:
            veredicto = "LOCAL_NO_NETWORK"

        if CANCELAR.is_set():
            return self._recibo(sol, run_id, "CANCELLED")

        # 4) ejecución real, shell=False, con timeout y tope de salida
        try:
            proc = subprocess.run(
                list(sol.argv), cwd=str(sol.cwd or "."), capture_output=True, text=True,
                timeout=max(1, int(sol.timeout_s)), shell=False, check=False,
            )
        except subprocess.TimeoutExpired as e:
            return self._recibo(sol, run_id, veredicto + "|TIMEOUT", exit_code=-1,
                                stdout=(e.stdout or "")[: sol.max_output_bytes] if isinstance(e.stdout, str) else "",
                                stderr=f"TIMEOUT tras {sol.timeout_s}s")
        except (OSError, ValueError) as e:
            return self._recibo(sol, run_id, veredicto + "|EXEC_ERROR", exit_code=-1, stderr=f"{type(e).__name__}: {e}")

        tope = max(0, int(sol.max_output_bytes))
        out, err = (proc.stdout or "")[:tope], (proc.stderr or "")[:tope]
        if proc.returncode not in sol.expected_exit_codes:
            veredicto += "|UNEXPECTED_EXIT"
        return self._recibo(sol, run_id, veredicto, exit_code=proc.returncode, stdout=out, stderr=err)
