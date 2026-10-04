"""
Integración con git: un commit por cada build verificada, en una rama aparte.

REAPER guarda una foto del proyecto en la rama `reaper/builds` (configurable)
SIN tocar tu rama actual, tu índice ni tus archivos: usa un índice temporal y
los comandos de bajo nivel de git (read-tree, add, write-tree, commit-tree,
update-ref). Así podés ver el historial de lo que hizo REAPER, comparar o
recuperar cualquier build con:

    git log reaper/builds
    git diff reaper/builds~1 reaper/builds
    git checkout reaper/builds -- archivo.py
"""


def es_repo_git(ws: Workspace) -> bool:
    return (ws.raiz / ".git").exists() and shutil.which("git") is not None


def git(ws: Workspace, *args: str, env: Optional[dict] = None, timeout: int = 60,
        entrada: Optional[str] = None) -> Resultado:
    # Estos comandos los corre REAPER (no el modelo): se usa el entorno completo para respetar la config de git.
    entorno = dict(os.environ)
    entorno.setdefault("GIT_TERMINAL_PROMPT", "0")
    if env:
        entorno.update(env)
    try:
        proceso = subprocess.run(
            ["git", *args], cwd=str(ws.raiz), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, env=entorno, input=entrada,
        )
    except FileNotFoundError:
        return Resultado(False, "git " + " ".join(args), 127, stderr="git no está instalado (pkg install git)")
    except subprocess.TimeoutExpired:
        return Resultado(False, "git " + " ".join(args), 124, stderr="git tardó demasiado", timeout=True)
    return Resultado(proceso.returncode == 0, "git " + " ".join(args), proceso.returncode,
                     proceso.stdout, proceso.stderr)


def _identidad(ws: Workspace) -> dict:
    """Si el repo no tiene user.name/email, se firma como REAPER (solo para estos commits)."""
    env = {}
    nombre = git(ws, "config", "user.name").stdout.strip()
    correo = git(ws, "config", "user.email").stdout.strip()
    if not nombre:
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "REAPER"
    if not correo:
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "reaper@localhost"
    return env


def snapshot_build(ws: Workspace, rama: str = "reaper/builds", mensaje: str = "build REAPER") -> Optional[str]:
    """
    Guarda el estado actual del working tree (respetando .gitignore) como un
    commit nuevo en 'rama'. Devuelve el hash del commit o None si no hubo
    cambios desde la foto anterior. Lanza RuntimeError si git falla.
    """
    if not es_repo_git(ws):
        raise RuntimeError("El proyecto no es un repositorio git.")
    if not re.fullmatch(r"[\w./-]+", rama) or ".." in rama:
        raise RuntimeError(f"Nombre de rama inválido: {rama}")
    git_dir = git(ws, "rev-parse", "--git-dir")
    if not git_dir.ok:
        raise RuntimeError(git_dir.stderr.strip() or "git rev-parse falló")
    carpeta_git = Path(git_dir.stdout.strip())
    if not carpeta_git.is_absolute():
        carpeta_git = ws.raiz / carpeta_git
    indice = carpeta_git / "reaper_index_tmp"
    env = {"GIT_INDEX_FILE": str(indice), **_identidad(ws)}
    try:
        base = git(ws, "rev-parse", "--verify", "-q", f"refs/heads/{rama}")
        padre = base.stdout.strip() if base.ok else ""
        if not padre:
            head = git(ws, "rev-parse", "--verify", "-q", "HEAD")
            padre = head.stdout.strip() if head.ok else ""
        r = git(ws, "read-tree", padre, env=env) if padre else git(ws, "read-tree", "--empty", env=env)
        if not r.ok:
            raise RuntimeError(r.stderr.strip())
        r = git(ws, "add", "-A", env=env, timeout=180)
        if not r.ok:
            raise RuntimeError(r.stderr.strip())
        arbol = git(ws, "write-tree", env=env)
        if not arbol.ok:
            raise RuntimeError(arbol.stderr.strip())
        arbol_id = arbol.stdout.strip()
        if padre:
            arbol_padre = git(ws, "rev-parse", f"{padre}^{{tree}}").stdout.strip()
            if arbol_padre == arbol_id and base.ok:
                return None
        args = ["commit-tree", arbol_id, "-m", mensaje[:2000]]
        if padre:
            args[2:2] = ["-p", padre]
        commit = git(ws, *args, env=env)
        if not commit.ok:
            raise RuntimeError(commit.stderr.strip())
        commit_id = commit.stdout.strip()
        actualizar = ["update-ref", f"refs/heads/{rama}", commit_id] + ([base.stdout.strip()] if base.ok else [])
        r = git(ws, *actualizar)
        if not r.ok:
            raise RuntimeError(r.stderr.strip())
        return commit_id
    finally:
        try:
            indice.unlink()
        except OSError:
            pass


def log_rama(ws: Workspace, rama: str = "reaper/builds", n: int = 15) -> str:
    r = git(ws, "log", f"-{n}", "--date=format:%Y-%m-%d %H:%M", "--pretty=format:%h  %ad  %s", rama, "--")
    if not r.ok:
        return "Todavía no hay builds guardadas en git." if "unknown revision" in r.stderr else r.stderr.strip()
    return r.stdout.strip() or "Sin commits."


def diff_desde_snapshot(ws: Workspace, rama: str = "reaper/builds") -> str:
    """Diferencias entre la última build guardada y el working tree actual."""
    r = git(ws, "diff", rama, "--", ".")
    return r.stdout if r.ok else r.stderr


def estado_git(ws: Workspace) -> str:
    rama = git(ws, "rev-parse", "--abbrev-ref", "HEAD")
    estado = git(ws, "status", "--short")
    if not estado.ok:
        return estado.stderr.strip()
    lineas = estado.stdout.strip().splitlines()
    return (f"rama: {rama.stdout.strip() or '?'} · {len(lineas)} archivo(s) con cambios\n"
            + "\n".join(lineas[:30]))


def inicializar_repo(ws: Workspace) -> Resultado:
    r = git(ws, "init")
    if r.ok and not (ws.raiz / ".gitignore").exists():
        try:
            escritura_atomica(ws.raiz / ".gitignore", "__pycache__/\n*.pyc\n.venv/\nnode_modules/\n.reaper/sandboxes/\n")
        except OSError:
            pass
    return r
