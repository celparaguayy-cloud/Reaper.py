"""
TaskGraph (v9, Fase 8): ordenar las tareas del plan respetando sus dependencias.

El arquitecto puede marcar <tarea id="3" deps="1,2"> para decir que la 3 necesita la 1 y la 2 hechas. El
GrafoTareas ordena las tareas de forma que cada una corra después de aquellas de las que depende (orden
topológico estable: ante empate respeta el orden del plan) y agrupa en OLAS las que podrían correr en
paralelo sin pisarse (sin dependencia entre ellas y sin compartir archivos declarados). Es defensivo: deps
que apuntan a ids inexistentes se ignoran con una nota, y si hay un ciclo cae al orden del plan sin perder
ninguna tarea.
"""


class GrafoTareas:
    def __init__(self, tareas: Sequence["Tarea"]):
        self.tareas = list(tareas)
        self.por_id = {t.id: t for t in self.tareas}
        self.problemas: list = []
        self._idx = {t.id: i for i, t in enumerate(self.tareas)}
        self._deps = self._normalizar()

    def _normalizar(self) -> dict:
        deps: dict = {}
        for t in self.tareas:
            validas = []
            for d in getattr(t, "deps", []) or []:
                if d == t.id or d in validas:
                    continue
                if d in self.por_id:
                    validas.append(d)
                else:
                    self.problemas.append(f"tarea {t.id}: depende de '{d}', que no existe (ignorada)")
            deps[t.id] = validas
        return deps

    def _hijos(self) -> dict:
        hijos: dict = collections.defaultdict(list)
        for tid, deps in self._deps.items():
            for d in deps:
                hijos[d].append(tid)
        return hijos

    def dependencias(self, tid: str) -> list:
        """Ids de las tareas de las que depende `tid` (solo las válidas)."""
        return list(self._deps.get(tid, []))

    def tiene_ciclo(self) -> bool:
        return len(self._orden_ids()) < len(self.tareas)

    def _orden_ids(self) -> list:
        indeg = {t.id: len(self._deps[t.id]) for t in self.tareas}
        hijos = self._hijos()
        listos = sorted([tid for tid, g in indeg.items() if g == 0], key=lambda x: self._idx[x])
        salida: list = []
        while listos:
            tid = listos.pop(0)
            salida.append(tid)
            nuevos = False
            for h in hijos[tid]:
                indeg[h] -= 1
                if indeg[h] == 0:
                    listos.append(h)
                    nuevos = True
            if nuevos:
                listos.sort(key=lambda x: self._idx[x])
        return salida

    def orden(self) -> list:
        """Las tareas en orden topológico estable. Si hay ciclo, agrega las restantes en orden del plan."""
        ids = self._orden_ids()
        if len(ids) < len(self.tareas):
            faltan = [t.id for t in self.tareas if t.id not in ids]
            self.problemas.append("ciclo de dependencias entre: " + ", ".join(faltan) + " (uso el orden del plan)")
            ids += faltan
        return [self.por_id[i] for i in ids]

    def olas(self) -> list:
        """Grupos de tareas que pueden correr en paralelo sin pisarse (deps cumplidas + archivos disjuntos)."""
        hechas: set = set()
        restantes = [t.id for t in self.tareas]
        olas: list = []
        guard = 0
        while restantes and guard <= len(self.tareas) + 1:
            guard += 1
            disponibles = [tid for tid in restantes if all(d in hechas for d in self._deps[tid])]
            if not disponibles:                       # ciclo: lo que queda va en una última ola
                olas.append([self.por_id[t] for t in restantes])
                break
            ola, archivos_ola = [], set()
            for tid in disponibles:
                arch = set(self.por_id[tid].archivos)
                if not ola:
                    ola.append(tid)
                    archivos_ola = set(arch)
                    if not arch:                      # footprint desconocido: corre sola
                        break
                elif arch and not (arch & archivos_ola):
                    ola.append(tid)
                    archivos_ola |= arch
            for tid in ola:
                hechas.add(tid)
                restantes.remove(tid)
            olas.append([self.por_id[t] for t in ola])
        return olas

    def resumen(self) -> str:
        lineas = [" → ".join(t.id for t in self.orden())]
        olas = self.olas()
        if any(len(o) > 1 for o in olas):
            lineas.append("olas: " + " | ".join("[" + ", ".join(t.id for t in o) + "]" for o in olas))
        if self.problemas:
            lineas.append("avisos: " + "; ".join(self.problemas))
        return "\n".join(lineas)
