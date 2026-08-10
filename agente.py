import os
import json
import time
import inspect
import shlex
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List

from dotenv import load_dotenv
from openai import OpenAI

from instrucciones import instrucciones_agente

import herramientas
from herramientas import (
    analizar_requisitos,
    revisar_codigo,
    generar_pruebas,
    validar_alcance,
    detectar_cambios_significativos,
    generar_plan_trabajo,
    listar_directorio,
    leer_archivo,
    escribir_archivo,
    editar_archivo,
    buscar_en_proyecto,
    ejecutar_comando_bash,
    command_sanitizer,
)

load_dotenv()


def _read_positive_int_env(name: str, default: int, maximum: int) -> int:
    """Lee un entero positivo de entorno y lo limita a un rango seguro."""
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


# El límite es una red de seguridad, no una cuota del proveedor. Se puede ajustar
# en .env para tareas excepcionalmente largas sin permitir ciclos ilimitados.
DEFAULT_MAX_TOOL_ITERATIONS = _read_positive_int_env(
    "MAX_TOOL_ITERATIONS", default=40, maximum=100
)
MAX_REPEATED_TOOL_CALLS = _read_positive_int_env(
    "MAX_REPEATED_TOOL_CALLS", default=3, maximum=10
)

ARTIFACT_RUNTIME_REQUIREMENTS = {
    (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", "package.json"): {"node", "npm"},
    (".py", "pyproject.toml", "requirements.txt"): {"python3"},
}

RUNTIME_TECHNOLOGIES = {"node": "node", "npm": "node", "python3": "python"}


@dataclass
class TaskChangeState:
    """Estado efímero y observacional de los cambios exitosos de una sesión."""
    created_files: set[str] = field(default_factory=set)
    modified_files: set[str] = field(default_factory=set)
    deleted_files: set[str] = field(default_factory=set)
    restored_files: set[str] = field(default_factory=set)
    created_then_deleted_files: set[str] = field(default_factory=set)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    _initial_hashes: dict[str, str] = field(default_factory=dict, repr=False)
    _sequence: int = field(default=0, repr=False)

    def _event(self, path: str, operation: str) -> None:
        self._sequence += 1
        self.events.append({"sequence": self._sequence, "path": path, "operation": operation})

    def record_decision(self, decision: str) -> None:
        self._sequence += 1
        self.decisions.append({"sequence": self._sequence, "decision": decision})

    def record_write(self, path: str, operation: str, existed_before: bool, before_hash: Optional[str], after_hash: Optional[str]) -> None:
        if existed_before and before_hash:
            self._initial_hashes.setdefault(path, before_hash)
        if path in self.deleted_files:
            self.deleted_files.discard(path)
            self.restored_files.add(path)
        elif operation == "creado":
            self.created_files.add(path)
        elif path not in self.created_files:
            initial = self._initial_hashes.get(path)
            if initial and after_hash == initial:
                self.modified_files.discard(path)
                self.restored_files.add(path)
            else:
                self.modified_files.add(path)
                self.restored_files.discard(path)
        self._event(path, operation)

    def record_delete(self, path: str, before_hash: Optional[str]) -> None:
        if before_hash:
            self._initial_hashes.setdefault(path, before_hash)
        if path in self.created_files:
            self.created_files.discard(path)
            self.modified_files.discard(path)
            self.created_then_deleted_files.add(path)
        else:
            self.deleted_files.add(path)
            self.restored_files.discard(path)
        self._event(path, "deleted")

    def summary(self) -> dict[str, Any]:
        return {
            "created_files": sorted(self.created_files),
            "modified_files": sorted(self.modified_files),
            "deleted_files": sorted(self.deleted_files),
            "restored_files": sorted(self.restored_files),
            "created_then_deleted_files": sorted(self.created_then_deleted_files),
            "decisions": list(self.decisions),
            "events": list(self.events),
        }


MAX_REPAIR_ATTEMPTS = 3


@dataclass
class TaskExecutionState:
    """Estado efímero del ciclo de vida y verificación de la tarea activa."""
    goal: str = ""
    status: str = "IDLE"  # IDLE, ACTIVE, COMPLETED, FAILED, CANCELLED
    phase: str = "INSPECTION"  # INSPECTION, IMPLEMENTATION, VERIFICATION, REPAIR, COMPLETION
    repair_attempts: int = 0
    verification_required: bool = False
    verification_possible: bool = True
    verification_completed: bool = False
    verification_status: str = "PENDING"  # PENDING, PASSED, FAILED, RUNTIMES_UNAVAILABLE, ENVIRONMENT_BLOCKED, SECURITY_BLOCKED, NETWORK_BLOCKED, VERIFICATION_UNAVAILABLE, SKIPPED
    last_verification_output: str = ""
    failure_evidences: List[str] = field(default_factory=list)
    stop_reason: Optional[str] = None

    def start_task(self, goal: str, requires_verification: bool = False) -> None:
        self.goal = goal
        self.status = "ACTIVE"
        self.phase = "INSPECTION"
        self.repair_attempts = 0
        self.verification_required = requires_verification
        self.verification_possible = True
        self.verification_completed = False
        self.verification_status = "PENDING" if requires_verification else "SKIPPED"
        self.last_verification_output = ""
        self.failure_evidences = []
        self.stop_reason = None

    def mark_completed(self, reason: str = "Tarea completada exitosamente.") -> None:
        self.status = "COMPLETED"
        self.phase = "COMPLETION"
        self.stop_reason = reason

    def mark_failed(self, reason: str) -> None:
        self.status = "FAILED"
        self.phase = "COMPLETION"
        self.stop_reason = reason

    def mark_cancelled(self, reason: str) -> None:
        self.status = "CANCELLED"
        self.phase = "COMPLETION"
        self.stop_reason = reason


def _runtime_for_version_command(command: str) -> Optional[str]:
    """Devuelve el runtime consultado sólo para comandos de versión exactos."""
    try:
        tokens = shlex.split(command)
    except (TypeError, ValueError):
        return None
    if len(tokens) != 2:
        return None
    executable = os.path.basename(tokens[0]).lower()
    flag = tokens[1].lower()

    if executable in ("node", "npm") and flag in ("--version", "-v", "-V"):
        return executable
    if executable in ("python", "python3") and flag in ("--version", "-v", "-V"):
        return "python3"
    if executable in ("java", "javac") and flag in ("--version", "-version", "-v", "-V"):
        return "java"
    if executable == "mvn" and flag in ("--version", "-version", "-v", "-V"):
        return "maven"
    if executable == "go" and flag in ("version", "--version", "-v", "-V"):
        return "go"
    if executable in ("cargo", "rustc") and flag in ("--version", "-v", "-V"):
        return "cargo"
    if executable == "dotnet" and flag in ("--version", "-v", "-V", "version"):
        return "dotnet"
    return None


def _required_runtimes_for_path(ruta: str) -> set[str]:
    """Identifica runtimes que deben comprobarse antes de escribir artefactos ejecutables."""
    filename = os.path.basename(ruta.strip().lower())
    for artifacts, runtimes in ARTIFACT_RUNTIME_REQUIREMENTS.items():
        if filename in artifacts or filename.endswith(artifacts[:-1]):
            return runtimes
    return set()


def _technology_for_runtimes(runtimes: set[str]) -> Optional[str]:
    """Obtiene la tecnología asociada a un conjunto de runtimes requerido."""
    technologies = {RUNTIME_TECHNOLOGIES[runtime] for runtime in runtimes}
    return technologies.pop() if len(technologies) == 1 else None


def _file_hash(path: Path) -> Optional[str]:
    """Devuelve sólo el hash SHA-256 de un archivo regular, nunca su contenido."""
    try:
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None

# ── Selección de Proveedor y Modelo LLM (DeepSeek / Groq / NVIDIA / OpenAI) ───
deepseek_key = os.getenv("DEEPSEEK_API_KEY")
groq_key = os.getenv("GROQ_API_KEY")
nvidia_key = os.getenv("NVIDIA_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")

if deepseek_key:
    BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    MODEL_NAME = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    api_key = deepseek_key
elif groq_key:
    BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    api_key = groq_key
elif nvidia_key:
    BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    MODEL_NAME = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct")
    api_key = nvidia_key
else:
    BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o")
    api_key = openai_key or "dummy_key"

client = OpenAI(
    base_url=BASE_URL,
    api_key=api_key,
    timeout=60.0,
)

# ── Mapa de funciones locales ─────────────────────────────────────
funciones_disponibles = {
    "analizar_requisitos": analizar_requisitos,
    "revisar_codigo": revisar_codigo,
    "generar_pruebas": generar_pruebas,
    "validar_alcance": validar_alcance,
    "detectar_cambios_significativos": detectar_cambios_significativos,
    "generar_plan_trabajo": generar_plan_trabajo,
    "listar_directorio": listar_directorio,
    "leer_archivo": leer_archivo,
    "escribir_archivo": escribir_archivo,
    "editar_archivo": editar_archivo,
    "buscar_en_proyecto": buscar_en_proyecto,
    "ejecutar_comando_bash": ejecutar_comando_bash,
}


def _extract_param_descriptions(docstring: str) -> Dict[str, str]:
    """Extrae descripciones de parámetros desde un docstring estructurado."""
    if not docstring:
        return {}

    param_descs = {}
    lines = docstring.splitlines()
    in_args = False

    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(("args:", "parameters:", "parámetros:", "parametros:")):
            in_args = True
            continue
        if in_args:
            if stripped.lower().startswith(("returns:", "raises:", "devuelve:", "retorna:")):
                in_args = False
                continue
            if ":" in stripped:
                parts = stripped.split(":", 1)
                p_name = parts[0].strip().replace("-", "").replace("*", "")
                p_desc = parts[1].strip()
                if p_name and p_desc:
                    param_descs[p_name] = p_desc
    return param_descs


def _python_type_to_json(annotation) -> str:
    """Convierte anotaciones de tipo Python a tipos JSON Schema."""
    mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
    }
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return "array"
    return mapping.get(annotation, "string")


def _build_tool_schema(func) -> dict:
    """Construye el esquema de herramienta OpenAI con tipos y descripciones de parámetros."""
    sig = inspect.signature(func)
    properties = {}
    required = []
    docstring = func.__doc__ or ""
    param_descs = _extract_param_descriptions(docstring)

    for name, param in sig.parameters.items():
        param_type = _python_type_to_json(param.annotation)
        prop = {"type": param_type}

        prop["description"] = param_descs.get(
            name, f"Parámetro '{name}' de tipo {param_type} para la herramienta {func.__name__}."
        )

        if param_type == "array":
            args = getattr(param.annotation, "__args__", None)
            if args:
                prop["items"] = {"type": _python_type_to_json(args[0])}
            else:
                prop["items"] = {"type": "string"}

        properties[name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(name)

    func_desc = docstring.strip().split("\n")[0] if docstring.strip() else f"Herramienta {func.__name__}."

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func_desc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# Generar esquemas automáticamente desde las funciones
tools = [_build_tool_schema(func) for func in funciones_disponibles.values()]


def _solicitud_requiere_inspeccion(mensaje: str) -> bool:
    """Retorna True si la consulta del usuario requiere inspeccionar código o archivos del proyecto."""
    if not mensaje:
        return False
    msg_lower = mensaje.lower()
    keywords = [
        "revisa", "revisar", "analiza", "analizar", "inspecciona", "inspeccionar",
        "error", "errores", "bug", "bugs", "solid", "kiss", "dry", "arquitectura",
        "codigo", "código", "proyecto", "archivos", "directorio", "pruebas", "test"
    ]
    return any(kw in msg_lower for kw in keywords)


# ── Sesión de chat ────────────────────────────────────────────────
class ChatSession:
    """
    Mantiene el historial de mensajes para una conversación y gestiona el ciclo autónomo de Tool Calling,
    soporte de autorizaciones humanas interactivas y control contra bucles infinitos.
    """

    def __init__(
        self,
        max_tool_iterations: Optional[int] = None,
        confirmador_callback: Optional[Callable[[str, str], bool]] = None,
        on_tool_call: Optional[Callable[[int, str, Dict[str, Any]], None]] = None,
    ):
        self.messages = [
            {"role": "system", "content": instrucciones_agente}
        ]
        self.max_tool_iterations = (
            DEFAULT_MAX_TOOL_ITERATIONS
            if max_tool_iterations is None
            else max(1, min(max_tool_iterations, 100))
        )
        self.confirmador_callback = confirmador_callback
        self.on_tool_call = on_tool_call
        self.runtime_status: Dict[str, bool] = {}
        self.capabilities_cache: Dict[str, Dict[str, Any]] = {}
        self.last_installed_pkg_hash: Dict[str, str] = {}
        self.last_ts_verification_hash: Dict[str, str] = {}
        self.current_working_directory: str = ""
        self.task_changes = TaskChangeState()
        self.current_task = TaskExecutionState()
        self.technology_decision: Dict[str, Any] = {
            "selected": None,
            "runtime_available": None,
            "alternative": None,
            "authorization_for": None,
            "denied_for": None,
        }

    def _get_package_json_hash(self, rel_cwd: str = "") -> Optional[str]:
        """Calcula el hash MD5 del package.json para la ruta de trabajo actual."""
        target = Path(rel_cwd) / "package.json" if rel_cwd else Path("package.json")
        val = herramientas.workspace_manager.validar_ruta(str(target), must_exist=False)
        if not val["valida"]:
            return None
        p = Path(val["ruta_absoluta"])
        if p.exists() and p.is_file():
            try:
                return hashlib.md5(p.read_bytes()).hexdigest()
            except Exception:
                return None
        return None

    def _get_ts_files_hash(self, rel_cwd: str = "") -> Optional[str]:
        """Calcula un hash colectivo de los archivos .ts y .tsx del proyecto."""
        target_dir = Path(rel_cwd) if rel_cwd else Path(".")
        val = herramientas.workspace_manager.validar_ruta(str(target_dir), must_exist=False)
        if not val["valida"]:
            return None
        base_path = Path(val["ruta_absoluta"])
        if not base_path.exists() or not base_path.is_dir():
            return None

        hashes = []
        try:
            for p in sorted(base_path.rglob("*.ts*")):
                if "node_modules" in p.parts:
                    continue
                if p.is_file():
                    try:
                        hashes.append(f"{p.name}:{p.stat().st_mtime}:{p.stat().st_size}")
                    except Exception:
                        pass
        except Exception:
            return None

        if not hashes:
            return None
        return hashlib.md5(";".join(hashes).encode("utf-8")).hexdigest()

    def set_capability(self, name: str, category: str, available: bool) -> None:
        """Registra el estado real verificado de una capacidad ('runtime', 'dependency', 'tool')."""
        entry = {
            "available": available,
            "category": category,
            "name": name,
        }
        self.capabilities_cache[name] = entry
        self.capabilities_cache[f"{category}:{name}"] = entry

    def get_capability(self, name: str, category: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Obtiene la capacidad registrada en la sesión actual."""
        if category:
            key = f"{category}:{name}"
            if key in self.capabilities_cache:
                return self.capabilities_cache[key]
        return self.capabilities_cache.get(name)

    def discover_project_capabilities(self) -> Dict[str, Any]:
        """
        Inspecciona el proyecto guiándose por package.json en el directorio actual (cwd).
        Detecta dependencias declaradas e instaladas sin ejecutar barridos indiscriminados en el sandbox.
        """
        rel_cwd = self.current_working_directory or ""
        target_json = Path(rel_cwd) / "package.json" if rel_cwd else "package.json"
        val = herramientas.workspace_manager.validar_ruta(str(target_json), must_exist=False)
        if not val["valida"]:
            return {}

        pkg_json_path = Path(val["ruta_absoluta"])
        if not pkg_json_path.exists() or not pkg_json_path.is_file():
            return {}

        try:
            with open(pkg_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}

        deps = {}
        if isinstance(data.get("dependencies"), dict):
            deps.update(data["dependencies"])
        if isinstance(data.get("devDependencies"), dict):
            deps.update(data["devDependencies"])

        project_dir = pkg_json_path.parent
        node_modules_dir = project_dir / "node_modules"

        discovered = {}
        for pkg_name in deps:
            if not isinstance(pkg_name, str) or not pkg_name.strip():
                continue
            is_installed = (node_modules_dir / pkg_name).exists()
            discovered[pkg_name] = {
                "type": "dependency",
                "installed": is_installed,
                "version": deps[pkg_name],
            }
            cap = self.get_capability(pkg_name, "dependency") or {}
            cap.update({
                "type": "dependency",
                "installed": is_installed,
                "declared_version": deps[pkg_name],
            })
            self.capabilities_cache[pkg_name] = cap
            self.capabilities_cache[f"dependency:{pkg_name}"] = cap

        return discovered

    def _register_human_technology_authorization(self, mensaje_usuario: str) -> None:
        """Registra sólo una autorización humana explícita para el cambio pendiente."""
        normalized = mensaje_usuario.strip().lower()
        if normalized not in {"si", "sí", "yes", "no"}:
            return

        selected = self.technology_decision["selected"]
        alternative = self.technology_decision["alternative"]
        if selected and alternative and self.technology_decision["runtime_available"] is False:
            decision = {
                "from": selected,
                "to": alternative,
            }
            if normalized in {"si", "sí", "yes"}:
                self.technology_decision["authorization_for"] = decision
                self.technology_decision["denied_for"] = None
                self.task_changes.record_decision(f"technology_change_authorized:{selected}->{alternative}")
            else:
                self.technology_decision["denied_for"] = decision
                self.technology_decision["authorization_for"] = None
                self.task_changes.record_decision(f"technology_change_denied:{selected}->{alternative}")

    def _safe_file_context(self, rel_path: str, is_creation: bool = False) -> Optional[Dict[str, Any]]:
        """Obtiene un snapshot seguro del archivo dentro del workspace."""
        val = herramientas.workspace_manager.validar_ruta(rel_path, is_creation=is_creation)
        if not val["valida"]:
            return None

        p = Path(val["ruta_absoluta"])
        exists = p.exists() and p.is_file()
        file_hash = None
        if exists:
            try:
                file_hash = _file_hash(p)
            except Exception:
                file_hash = None

        return {
            "path": rel_path,
            "exists": exists,
            "hash": file_hash,
        }

    def _track_tool_side_effects(
        self,
        nombre: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
        resultado: Dict[str, Any]
    ) -> None:
        """Registra los efectos secundarios de herramientas mutantes de archivos."""
        if resultado.get("error"):
            return

        kind = None
        if nombre == "escribir_archivo": kind = "write"
        elif nombre == "editar_archivo": kind = "write"
        elif nombre == "ejecutar_comando_bash":
            cmd = args.get("comando", "")
            if "rm " in cmd: kind = "rm"
            elif "mv " in cmd or "cp " in cmd: kind = "move"

        if not kind:
            return

        if kind == "write":
            before = context.get("file")
            path = resultado.get("ruta_relativa")
            if before and isinstance(path, str):
                validated = self._safe_file_context(path, is_creation=True)
                self.task_changes.record_write(path, resultado.get("operacion", "modified"), before["exists"], before["hash"], validated["hash"] if validated else None)
        elif kind == "rm":
            for file_context in context.get("files", []):
                if file_context and file_context["exists"]:
                    self.task_changes.record_delete(file_context["path"], file_context["hash"])
        elif kind == "move":
            source = context.get("source")
            destination = context.get("destination")
            if source and source["exists"]:
                self.task_changes.record_delete(source["path"], source["hash"])
            if destination:
                current = self._safe_file_context(destination["path"], is_creation=True)
                if current and current["exists"]:
                    self.task_changes.record_write(destination["path"], "creado", destination["exists"], destination["hash"], current["hash"])

    def _prepare_change_context(self, nombre: str, args: Dict[str, Any]) -> Optional[dict[str, Any]]:
        """Captura metadata previa sin ejecutar ni alterar ninguna operación."""
        if nombre == "escribir_archivo":
            return {"kind": "write", "file": self._safe_file_context(args.get("ruta", ""), is_creation=True)}
        if nombre == "editar_archivo":
            return {"kind": "write", "file": self._safe_file_context(args.get("ruta", ""), is_creation=False)}
        if nombre != "ejecutar_comando_bash" or not isinstance(args.get("comando"), str):
            return None
        try:
            tokens = shlex.split(args["comando"])
        except ValueError:
            return None
        if not tokens or tokens[0] not in {"rm", "mv", "cp"}:
            return None
        paths = [token for token in tokens[1:] if not token.startswith("-")]
        if tokens[0] == "rm":
            return {"kind": "rm", "files": [self._safe_file_context(path) for path in paths]}
        if len(paths) < 2:
            return None
        return {
            "kind": tokens[0],
            "source": self._safe_file_context(paths[-2]),
            "destination": self._safe_file_context(paths[-1], is_creation=True),
        }

    def _record_successful_change(self, context: Optional[dict[str, Any]], resultado: Dict[str, Any]) -> None:
        """Actualiza el tracking únicamente después de una operación exitosa."""
        if not context or resultado.get("error"):
            return
        kind = context["kind"]
        if kind == "write":
            before = context.get("file")
            path = resultado.get("ruta_relativa")
            if before and isinstance(path, str):
                validated = self._safe_file_context(path, is_creation=True)
                self.task_changes.record_write(path, resultado.get("operacion", "modified"), before["exists"], before["hash"], validated["hash"] if validated else None)
        elif kind == "rm":
            for file_context in context.get("files", []):
                if file_context and file_context["exists"]:
                    self.task_changes.record_delete(file_context["path"], file_context["hash"])
        elif kind in {"mv", "cp"}:
            source = context.get("source")
            destination = context.get("destination")
            if kind == "mv" and source and source["exists"]:
                self.task_changes.record_delete(source["path"], source["hash"])
            if destination:
                current = self._safe_file_context(destination["path"], is_creation=True)
                if current and current["exists"]:
                    self.task_changes.record_write(destination["path"], "modified" if destination["exists"] else "creado", destination["exists"], destination["hash"], current["hash"])

        if nombre == "ejecutar_comando_bash":
            cmd = args.get("comando", "")
            rel_cwd = self.current_working_directory or ""
            try:
                tokens = shlex.split(cmd)
                if tokens:
                    exec_name = Path(tokens[0]).name.lower()
                    subcmd = tokens[1].lower() if len(tokens) > 1 else ""
                    if exec_name == "npm" and subcmd in ("install", "i", "ci") and not resultado.get("error"):
                        pkg_h = self._get_package_json_hash(rel_cwd)
                        if pkg_h:
                            self.last_installed_pkg_hash[rel_cwd] = pkg_h
                    elif (exec_name == "tsc" or (exec_name == "npx" and len(tokens) >= 2 and tokens[1].lower() == "tsc")) and not resultado.get("error"):
                        ts_h = self._get_ts_files_hash(rel_cwd)
                        if ts_h:
                            self.last_ts_verification_hash[rel_cwd] = ts_h
            except Exception:
                pass

    def _is_authorized_technology_change(self, selected: str, alternative: str) -> bool:
        """Comprueba que la autorización pertenece exactamente al cambio solicitado."""
        return self.technology_decision["authorization_for"] == {
            "from": selected,
            "to": alternative,
        }

    def _preflight_error_for_write(self, nombre: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Las escrituras de archivos (escribir_archivo, editar_archivo) corresponden a
        operaciones puras de texto en disco y NUNCA se bloquean por falta de runtimes.
        """
        return None

    def _preflight_error_for_execution(self, nombre: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Inspecciona ejecuciones de comandos en el sandbox. Evita comprobaciones redundantes
        usando el caché de la sesión y bloquea la ejecución si los runtimes/dependencias requeridos no están disponibles.
        """
        if nombre != "ejecutar_comando_bash":
            return None

        comando = args.get("comando", "")
        if not isinstance(comando, str) or not comando.strip():
            return None

        if "cwd" not in args or not args["cwd"]:
            args["cwd"] = self.current_working_directory

        # Si el comando solicita explícitamente revalidación (--recheck, --force) no se interrumpe
        if "--recheck" in comando or "--force" in comando:
            return None

        try:
            tokens = shlex.split(comando)
        except Exception:
            return None

        if not tokens:
            return None

        # Interceptación de 'cd' en preflight
        if tokens[0].lower() == "cd":
            eval_cd = command_sanitizer.validar_y_clasificar(comando, cwd=self.current_working_directory)
            if eval_cd.get("is_cd"):
                if not eval_cd.get("valido"):
                    return {
                        "error": True,
                        "codigo_error": eval_cd.get("codigo_error", "RUTA_INVALIDA"),
                        "mensaje": eval_cd["mensaje"],
                    }
                self.current_working_directory = eval_cd["new_cwd"]
                return {
                    "error": False,
                    "codigo_salida": 0,
                    "is_cd": True,
                    "new_cwd": eval_cd["new_cwd"],
                    "stdout": eval_cd["mensaje"],
                    "stderr": "",
                    "mensaje": eval_cd["mensaje"],
                    "sandbox": False,
                }

        exec_name = Path(tokens[0]).name.lower()

        # Prohibición explícita de copiar /var/pkg-cache hacia el workspace o /tmp
        if "/var/pkg-cache" in comando and any(cmd_kw in comando for cmd_kw in ("cp ", "tar ", "rsync ")):
            return {
                "error": True,
                "codigo_error": "OPERACION_PROHIBIDA",
                "mensaje": "Está estrictamente prohibido copiar o duplicar /var/pkg-cache hacia el workspace o /tmp. El almacén se utiliza directamente desde /var/pkg-cache.",
            }

        # Interceptación de comandos de red en preflight
        if command_sanitizer._is_network_command(tokens, exec_name):
            return {
                "error": True,
                "codigo_error": "NETWORK_BLOCKED",
                "mensaje": f"El comando '{comando}' fue bloqueado porque la red está desactivada en el sandbox Docker (--network none).",
            }

        rel_cwd = self.current_working_directory or ""
        subcmd = tokens[1].lower() if len(tokens) > 1 else ""

        # Deduplicar npm install si package.json no ha cambiado y node_modules existe
        if exec_name == "npm" and subcmd in ("install", "i", "ci"):
            pkg_hash = self._get_package_json_hash(rel_cwd)
            if pkg_hash and self.last_installed_pkg_hash.get(rel_cwd) == pkg_hash:
                target_json = Path(rel_cwd) / "package.json" if rel_cwd else Path("package.json")
                val = herramientas.workspace_manager.validar_ruta(str(target_json), must_exist=False)
                if val["valida"] and (Path(val["ruta_absoluta"]).parent / "node_modules").exists():
                    return {
                        "error": False,
                        "mensaje": f"Las dependencias declaradas en package.json ya están instaladas y actualizadas para '{rel_cwd or 'workspace'}'.",
                        "stdout": "npm install omitido: dependencias ya instaladas para este package.json.",
                        "cached": True
                    }

        # Deduplicar tsc --noEmit si los archivos TypeScript no han cambiado
        if exec_name == "tsc" or (exec_name == "npx" and len(tokens) >= 2 and tokens[1].lower() == "tsc"):
            ts_hash = self._get_ts_files_hash(rel_cwd)
            if ts_hash and self.last_ts_verification_hash.get(rel_cwd) == ts_hash:
                return {
                    "error": False,
                    "mensaje": "No se han detectado cambios en archivos TypeScript desde la última verificación con tsc.",
                    "stdout": "tsc omitido: sin cambios en código fuente TypeScript desde la última ejecución.",
                    "cached": True
                }

        # Deduplicar npm cache ls si la dependencia ya está registrada
        if exec_name == "npm" and subcmd == "cache" and len(tokens) >= 4 and tokens[2].lower() == "ls":
            pkg = tokens[3].lower()
            cap = self.get_capability(pkg, category="dependency")
            if cap is not None:
                return {
                    "error": False,
                    "mensaje": f"Información de la dependencia '{pkg}' ya registrada en la sesión.",
                    "stdout": f"npm cache ls {pkg}: paquete ya verificado en la sesión.",
                    "cached": True
                }

        # Interceptar consultas redundantes de whereis / which si ya están en el caché de la sesión
        if exec_name in ("whereis", "which") and len(tokens) >= 2:
            target = tokens[1].lower()
            cap = self.get_capability(target)
            if cap is not None:
                if cap["available"]:
                    return {
                        "error": False,
                        "mensaje": f"La herramienta o capacidad '{target}' ya fue comprobada y está disponible en la sesión.",
                        "stdout": f"{target}: /usr/local/bin/{target} (caché de sesión)",
                        "cached": True
                    }
                else:
                    cat = cap.get("category", "dependency")
                    cod = "DEPENDENCIA_NO_DISPONIBLE_OFFLINE" if cat == "dependency" else "RUNTIME_NO_DISPONIBLE"
                    msg = f"La dependencia '{target}' no está disponible en el almacén offline." if cat == "dependency" else f"La herramienta '{target}' no está disponible en el entorno."
                    return {
                        "error": True,
                        "codigo_error": cod,
                        "mensaje": msg,
                        "cached": True
                    }

        # Interceptar npm view / info si la dependencia ya fue verificada como NO disponible
        if exec_name == "npm" and len(tokens) >= 3 and tokens[1].lower() in ("view", "info"):
            pkg = command_sanitizer._extract_npm_package_name(tokens)
            if pkg:
                cap = self.get_capability(pkg, category="dependency")
                if cap and not cap["available"]:
                    return {
                        "error": True,
                        "codigo_error": "DEPENDENCIA_NO_DISPONIBLE_OFFLINE",
                        "mensaje": f"La dependencia '{pkg}' no está disponible en el almacén offline.",
                        "cached": True
                    }

        # Mapeo de ejecutables a nombres de runtime
        executable_runtimes = {
            "node": "node",
            "npm": "npm",
            "npx": "npm",
            "python": "python3",
            "python3": "python3",
            "pytest": "python3",
            "java": "java",
            "javac": "java",
            "mvn": "maven",
            "go": "go",
            "cargo": "cargo",
            "rustc": "cargo",
            "dotnet": "dotnet",
            "tsc": "typescript",
        }

        # Omitir wrappers
        idx = 0
        while idx < len(tokens):
            token_base = os.path.basename(tokens[idx]).lower()
            if token_base in ("env", "time", "stdbuf"):
                idx += 1
                while idx < len(tokens) and ("=" in tokens[idx] or tokens[idx].startswith("-")):
                    idx += 1
            else:
                break

        if idx >= len(tokens):
            return None

        executable = os.path.basename(tokens[idx]).lower()

        # Si es un comando de versión de runtime y YA fue verificado en la sesión
        runtime_check = _runtime_for_version_command(comando)
        if runtime_check:
            cap = self.get_capability(runtime_check, category="runtime")
            if cap and cap["available"]:
                return {
                    "error": False,
                    "mensaje": f"El runtime '{runtime_check}' ya fue verificado y está disponible en la sesión.",
                    "stdout": f"{runtime_check} disponible (caché de sesión)",
                    "cached": True
                }
            return None

        required_runtime = executable_runtimes.get(executable)
        if not required_runtime:
            return None

        # Si el runtime ya fue comprobado y NO está disponible en el entorno
        if self.runtime_status.get(required_runtime) is False or (self.get_capability(required_runtime) and not self.get_capability(required_runtime)["available"]):
            return {
                "error": True,
                "codigo_error": "RUNTIME_NO_DISPONIBLE",
                "mensaje": (
                    f"No es posible ejecutar '{comando}': el runtime o herramienta '{required_runtime}' "
                    "no está disponible en el entorno Docker. No se puede ejecutar este comando."
                ),
            }

        return None

    def _record_runtime_check(self, nombre: str, args: Dict[str, Any], resultado: Dict[str, Any]) -> None:
        """Conserva el resultado de comprobaciones de versión y capacidades en la sesión."""
        if nombre != "ejecutar_comando_bash":
            return
        command = args.get("comando", "")
        if not isinstance(command, str) or not command.strip():
            return

        is_error = bool(resultado.get("error"))
        cod_err = resultado.get("codigo_error")

        # 1. Comprobación de runtime (--version)
        runtime = _runtime_for_version_command(command)
        if runtime:
            avail = not is_error
            self.runtime_status[runtime] = avail
            self.set_capability(runtime, "runtime", avail)

            selected = self.technology_decision.get("selected")
            if selected and RUNTIME_TECHNOLOGIES.get(runtime) == selected:
                required = next(
                    (runtimes for artifacts, runtimes in ARTIFACT_RUNTIME_REQUIREMENTS.items()
                     if _technology_for_runtimes(runtimes) == selected),
                    None
                )
                if required:
                    statuses = [self.runtime_status.get(r) for r in required]
                    self.technology_decision["runtime_available"] = (
                        False if False in statuses else True if all(s is True for s in statuses) else None
                    )
            return

        # 2. Detección de dependencia no instalada o no disponible offline
        if cod_err in ("DEPENDENCIA_NO_INSTALADA", "DEPENDENCIA_NO_DISPONIBLE_OFFLINE"):
            pkg = resultado.get("paquete_faltante")
            if not pkg:
                try:
                    toks = shlex.split(command)
                    pkg = command_sanitizer._extract_npm_package_name(toks)
                except Exception:
                    pkg = None
            if pkg:
                if cod_err == "DEPENDENCIA_NO_INSTALADA":
                    self.set_capability(pkg, "dependency", False)
                    # Actualizar metadata indicando que existe offline
                    entry = self.get_capability(pkg) or {}
                    entry.update({"source": "offline", "tarball": resultado.get("tarball_offline"), "available": True, "installed": False})
                    self.capabilities_cache[pkg] = entry
                else:
                    self.set_capability(pkg, "dependency", False)
            return

        # 3. Comprobación de instalación exitosa de npm
        if not is_error and command.startswith("npm "):
            try:
                toks = shlex.split(command)
                if len(toks) >= 2 and toks[1] in ("install", "i", "ci"):
                    pkg = command_sanitizer._extract_npm_package_name(toks)
                    if pkg:
                        self.set_capability(pkg, "dependency", True)
            except Exception:
                pass

        # 4. Comprobación de binario/herramienta (whereis, which)
        try:
            tokens = shlex.split(command)
        except Exception:
            return

        if len(tokens) >= 2:
            exe = Path(tokens[0]).name.lower()
            if exe in ("whereis", "which"):
                target = tokens[1].lower()
                category = "dependency" if target in ("next", "react", "vue", "express") else "tool"
                stdout = str(resultado.get("stdout") or "").strip()
                if exe == "whereis":
                    avail = not is_error and ":" in stdout and len(stdout.split(":", 1)[1].strip()) > 0
                else:
                    avail = not is_error and len(stdout) > 0
                self.set_capability(target, category, avail)

    def _update_task_execution_state(self, nombre: str, args: Dict[str, Any], resultado: Dict[str, Any]) -> None:
        """Actualiza el estado efímero del Agent Loop según el resultado de cada herramienta."""
        if self.current_task.status not in ("ACTIVE",):
            return

        # Transición de fase por tipo de herramienta
        if nombre in ("listar_directorio", "buscar_en_proyecto", "leer_archivo", "analizar_requisitos"):
            if self.current_task.phase in ("INSPECTION", "COMPLETION"):
                self.current_task.phase = "INSPECTION"
        elif nombre in ("escribir_archivo", "editar_archivo"):
            if self.current_task.repair_attempts > 0:
                self.current_task.phase = "REPAIR"
            else:
                self.current_task.phase = "IMPLEMENTATION"

        # Manejo de errores internos del agente o herramientas (AGENT_INTERNAL_ERROR)
        if resultado.get("codigo_error") in ("AGENT_INTERNAL_ERROR", "ERROR_HERRAMIENTA", "ERROR_EJECUTOR"):
            self.current_task.verification_possible = False
            self.current_task.verification_status = "AGENT_INTERNAL_ERROR"
            self.current_task.last_verification_output = str(resultado.get("mensaje") or "Error interno del agente.")
            return

        # Interceptación de cd como actualización de contexto
        if resultado.get("is_cd"):
            if not resultado.get("error") and "new_cwd" in resultado:
                self.current_working_directory = resultado["new_cwd"]
            return

        # Manejo de denegación por usuario
        if resultado.get("codigo_error") == "PERMISO_DENEGADO_POR_USUARIO":
            self.current_task.mark_cancelled("El usuario denegó la autorización explícita para la operación.")
            return

        # Manejo de bloqueos de red (NETWORK_BLOCKED)
        if resultado.get("codigo_error") == "NETWORK_BLOCKED":
            self.current_task.verification_possible = False
            self.current_task.verification_status = "NETWORK_BLOCKED"
            self.current_task.last_verification_output = str(resultado.get("mensaje") or "Operación de red bloqueada por la política de sandbox (--network none).")
            return

        # Manejo de limitaciones del entorno (ENVIRONMENT_BLOCKED)
        if resultado.get("codigo_error") in (
            "STORAGE_LIMIT_EXCEEDED",
            "INVALID_ENVIRONMENT_QUERY",
            "DEPENDENCIA_NO_INSTALADA",
            "DEPENDENCIA_NO_DISPONIBLE_OFFLINE",
            "SANDBOX_NO_DISPONIBLE",
            "IMAGEN_SANDBOX_NO_DISPONIBLE",
        ):
            self.current_task.verification_possible = False
            self.current_task.verification_status = "ENVIRONMENT_BLOCKED"
            self.current_task.last_verification_output = str(resultado.get("mensaje") or "Limitación de entorno/almacenamiento detectada.")
            return

        # Manejo de runtime no disponible (RUNTIMES_UNAVAILABLE)
        if resultado.get("codigo_error") == "RUNTIME_NO_DISPONIBLE":
            self.current_task.verification_possible = False
            self.current_task.verification_status = "RUNTIMES_UNAVAILABLE"
            self.current_task.last_verification_output = str(resultado.get("mensaje") or "Runtime no disponible.")
            return

        # Manejo de bloqueos de seguridad (SECURITY_BLOCKED)
        if resultado.get("codigo_error") in (
            "SHELL_INJECTION_RISK",
            "COMANDO_PROHIBIDO",
            "COMANDO_NO_PERMITIDO",
            "CONFIRMACION_REQUERIDA",
            "TIPO_INVALIDO",
            "COMANDO_VACIO",
            "SINTAXIS_INVALIDA",
            "FUERA_DEL_WORKSPACE",
        ):
            self.current_task.verification_possible = False
            self.current_task.verification_status = "SECURITY_BLOCKED"
            self.current_task.last_verification_output = str(resultado.get("mensaje") or "Comando rechazado por la política de seguridad.")
            if nombre in ("ejecutar_comando_bash", "revisar_codigo", "generar_pruebas"):
                self.current_task.phase = "VERIFICATION"
            return

        # Manejo de timeouts e interrupciones de infraestructura (VERIFICATION_UNAVAILABLE)
        if resultado.get("codigo_error") in (
            "TIMEOUT",
            "TIMEOUT_ENVIRONMENT_CHECK",
            "PROCESO_INTERRUMPIDO",
            "ERROR_SANDBOX",
            "VERIFICATION_UNAVAILABLE",
        ):
            self.current_task.verification_possible = False
            self.current_task.verification_status = "VERIFICATION_UNAVAILABLE"
            self.current_task.last_verification_output = str(resultado.get("mensaje") or "Ejecución de verificación interrumpida.")
            return

        # Manejo de herramientas de ejecución / prueba (Falla real del código del proyecto vs Éxito)
        if nombre in ("ejecutar_comando_bash", "revisar_codigo", "generar_pruebas"):
            self.current_task.phase = "VERIFICATION"

            comando = args.get("comando", "") if isinstance(args.get("comando"), str) else ""
            is_version_cmd = _runtime_for_version_command(comando) is not None

            if nombre == "ejecutar_comando_bash" and (is_version_cmd or resultado.get("cached")):
                return

            # Omitir errores que no sean fallos reales de código del proyecto
            if resultado.get("codigo_error") in (
                "STORAGE_LIMIT_EXCEEDED",
                "INVALID_ENVIRONMENT_QUERY",
                "AGENT_INTERNAL_ERROR",
                "SECURITY_BLOCKED",
                "ENVIRONMENT_BLOCKED",
                "RUNTIMES_UNAVAILABLE",
                "NETWORK_BLOCKED",
                "VERIFICATION_UNAVAILABLE",
                "CONFIRMACION_REQUERIDA",
                "PERMISO_DENEGADO_POR_USUARIO",
                "SANDBOX_NO_DISPONIBLE",
                "IMAGEN_SANDBOX_NO_DISPONIBLE",
                "DEPENDENCIA_NO_INSTALADA",
                "DEPENDENCIA_NO_DISPONIBLE_OFFLINE",
                "RUNTIME_NO_DISPONIBLE",
                "TIMEOUT",
                "TIMEOUT_ENVIRONMENT_CHECK",
                "SHELL_INJECTION_RISK",
                "COMANDO_PROHIBIDO",
                "COMANDO_NO_PERMITIDO",
                "FUERA_DEL_WORKSPACE",
            ):
                return

            is_error = bool(resultado.get("error"))
            if is_error:
                diagnostic = str(resultado.get("stderr") or resultado.get("stdout") or resultado.get("mensaje") or "").strip()

                if not diagnostic:
                    self.current_task.verification_possible = False
                    self.current_task.verification_status = "VERIFICATION_UNAVAILABLE"
                    self.current_task.last_verification_output = "No se obtuvo salida de diagnóstico útil."
                    return

                self.current_task.verification_completed = True
                self.current_task.verification_status = "FAILED"
                self.current_task.last_verification_output = diagnostic
                self.current_task.failure_evidences.append(diagnostic)
                self.current_task.repair_attempts += 1

                if self.current_task.repair_attempts >= MAX_REPAIR_ATTEMPTS:
                    if len(self.current_task.failure_evidences) >= MAX_REPAIR_ATTEMPTS:
                        self.current_task.mark_failed(
                            f"Se alcanzó el límite máximo de {MAX_REPAIR_ATTEMPTS} intentos de reparación tras fallos de prueba."
                        )
                    else:
                        self.current_task.mark_failed(
                            "Verificación interrumpida: no se obtuvo una salida de verificación suficiente para determinar un fallo del proyecto."
                        )
                else:
                    self.current_task.phase = "REPAIR"
            else:
                self.current_task.verification_completed = True
                self.current_task.verification_status = "PASSED"
                self.current_task.last_verification_output = str(resultado.get("stdout") or "Pruebas superadas con éxito.")

    def enviar(self, mensaje_usuario: str) -> str:
        """
        Envía un mensaje del usuario y procesa llamadas a herramientas (Tool Calling)
        automáticamente hasta obtener una respuesta de texto o alcanzar el límite.
        """
        self.messages.append({"role": "user", "content": mensaje_usuario})
        self._register_human_technology_authorization(mensaje_usuario)

        msg_trimmed = mensaje_usuario.strip()
        msg_lower = msg_trimmed.lower()

        keywords_verification = (
            "asegúrate de que funcione", "asegurate que funcione", "asegurate de que funcione",
            "verifica", "verificar", "prueba", "pruebas", "test", "comprueba", "funcionando"
        )
        requires_verification = any(kw in msg_lower for kw in keywords_verification)


        keywords_new_task = (
            "construye", "crea un ", "crea una ", "implementa", "desarrolla",
            "haz un ", "haz una ", "nueva tarea", "revisa los errores y principios solid"
        )
        is_explicit_new_task = any(kw in msg_lower for kw in keywords_new_task)

        if self.current_task.status not in ("ACTIVE",) or is_explicit_new_task:
            self.task_changes = TaskChangeState()
            self.current_task.start_task(goal=msg_trimmed, requires_verification=requires_verification)
        else:
            if requires_verification:
                self.current_task.verification_required = True
                if self.current_task.verification_status == "SKIPPED":
                    self.current_task.verification_status = "PENDING"

        iterations = 0
        herramientas_usadas = []
        solicitud_inspeccion = _solicitud_requiere_inspeccion(mensaje_usuario)
        intento_inspeccion_forzada = False
        ultima_firma_herramientas: Optional[str] = None
        repeticiones_consecutivas = 0

        while True:
            iterations += 1

            if iterations > self.max_tool_iterations:
                resumen_usadas = ", ".join(set(herramientas_usadas)) if herramientas_usadas else "ninguna"
                return (
                    f"⚠️ La tarea alcanzó el límite de seguridad configurado de "
                    f"{self.max_tool_iterations} rondas de herramientas.\n"
                    f"• Herramientas utilizadas en el proceso: {resumen_usadas}.\n"
                    "• Estado: La tarea quedó parcialmente procesada para evitar un ciclo ilimitado. "
                    "Puedes aumentar MAX_TOOL_ITERATIONS en .env si la tarea legítimamente requiere más rondas."
                )

            time.sleep(0.5)

            response = None
            for intento in range(4):
                try:
                    response = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=self.messages,
                        tools=tools,
                        tool_choice="auto",
                    )
                    break
                except Exception as api_err:
                    err_msg = str(api_err)
                    if "429" in err_msg or "Rate limit" in err_msg:
                        wait_sec = 5.0 * (intento + 1)
                        print(f"    [Rate Limit 429] Esperando {wait_sec}s antes del reintento {intento + 1}/4...", flush=True)
                        time.sleep(wait_sec)
                    else:
                        if intento == 3:
                            return f"⚠️ Error en la llamada al modelo LLM ({MODEL_NAME}): {err_msg}"
                        time.sleep(2.0)

            if not response:
                return f"⚠️ No se pudo obtener respuesta del modelo LLM tras varios reintentos por rate limit."

            choice = response.choices[0]
            assistant_message = choice.message

            msg_dict = {
                "role": assistant_message.role,
                "content": assistant_message.content,
            }

            if assistant_message.tool_calls:
                clean_tool_calls = []
                for tc in assistant_message.tool_calls:
                    tc_dict = tc.model_dump()
                    clean_tc = {
                        "id": tc_dict["id"],
                        "type": tc_dict["type"],
                        "function": {
                            "name": tc_dict["function"]["name"],
                            "arguments": tc_dict["function"]["arguments"],
                        }
                    }
                    clean_tool_calls.append(clean_tc)
                msg_dict["tool_calls"] = clean_tool_calls

            self.messages.append(msg_dict)

            if not assistant_message.tool_calls:
                tiene_codigo_leido = False
                for m in self.messages:
                    if m.get("role") == "assistant" and m.get("tool_calls"):
                        for tc in m["tool_calls"]:
                            fn_name = tc.get("function", {}).get("name", "")
                            if fn_name in ("leer_archivo", "buscar_en_proyecto", "revisar_codigo"):
                                tiene_codigo_leido = True
                                break

                if solicitud_inspeccion and not tiene_codigo_leido and not intento_inspeccion_forzada:
                    intento_inspeccion_forzada = True
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "[REGLA DE EVIDENCIA DE CÓDIGO OBLIGATORIA] "
                            "Has listado la estructura del proyecto o aún no has leído el contenido del código. "
                            "NO estás autorizado a emitir conclusiones sobre errores, SOLID, KISS, DRY o calidad del código "
                            "basándote solo en nombres de archivos o estructura de directorios. "
                            "DEBES ejecutar 'leer_archivo' sobre los archivos fuente relevantes para examinar el código real "
                            "antes de entregar tu diagnóstico final."
                        )
                    })
                    continue

                if self.current_task.status == "ACTIVE":
                    if self.current_task.verification_status in ("PASSED", "SKIPPED", "RUNTIMES_UNAVAILABLE"):
                        self.current_task.mark_completed("Tarea completada exitosamente.")
                    elif self.current_task.verification_status == "FAILED":
                        self.current_task.mark_failed("La verificación reportó fallos pendientes.")

                return assistant_message.content or "(Sin respuesta del modelo)"

            firma_herramientas = json.dumps(
                [
                    {
                        "nombre": tool_call.function.name,
                        "argumentos": tool_call.function.arguments or "{}",
                    }
                    for tool_call in assistant_message.tool_calls
                ],
                ensure_ascii=False,
                sort_keys=True,
            )
            if firma_herramientas == ultima_firma_herramientas:
                repeticiones_consecutivas += 1
            else:
                ultima_firma_herramientas = firma_herramientas
                repeticiones_consecutivas = 1

            if repeticiones_consecutivas > MAX_REPEATED_TOOL_CALLS:
                self.current_task.mark_failed("Bucle detectado por llamadas idénticas consecutivas a herramientas.")
                return (
                    "⚠️ Se detuvo un posible bucle: el modelo solicitó la misma llamada de herramientas "
                    f"{repeticiones_consecutivas} veces consecutivas sin cambiar sus argumentos.\n"
                    f"• Herramientas involucradas: {', '.join(set(herramientas_usadas)) or 'ninguna'}.\n"
                    "• Estado: se preservó la seguridad del agente; revisa la solicitud o el resultado de la herramienta."
                )

            for tool_call in assistant_message.tool_calls:
                nombre = tool_call.function.name
                raw_args = tool_call.function.arguments
                herramientas_usadas.append(nombre)
                change_context = None

                try:
                    args = json.loads(raw_args) if raw_args else {}
                except Exception:
                    args = {}

                if self.on_tool_call is not None:
                    try:
                        self.on_tool_call(iterations, nombre, args)
                    except Exception:
                        print(f"    [Tool Iteration {iterations}] Invocando: {nombre}({raw_args})", flush=True)
                else:
                    print(f"    [Tool Iteration {iterations}] Invocando: {nombre}({raw_args})", flush=True)

                try:
                    args_parsed = json.loads(raw_args) if raw_args else {}
                except Exception as json_err:
                    resultado = {
                        "error": True,
                        "mensaje": f"Error de sintaxis JSON en argumentos de '{nombre}': {str(json_err)}"
                    }
                else:
                    change_context = self._prepare_change_context(nombre, args_parsed)
                    preflight_error = self._preflight_error_for_execution(nombre, args_parsed)
                    if preflight_error is not None:
                        resultado = preflight_error
                    elif nombre in funciones_disponibles:
                        try:
                            resultado = funciones_disponibles[nombre](**args_parsed)

                            if (
                                isinstance(resultado, dict)
                                and resultado.get("codigo_error") == "CONFIRMACION_REQUERIDA"
                            ):
                                cmd_target = resultado.get("comando") or args_parsed.get("comando", nombre)
                                msg_req = resultado.get("mensaje", "Operación requiere autorización.")
                                confirmador = getattr(self, "confirmador_callback", None)

                                if confirmador is not None:
                                    try:
                                        aprobado = confirmador(cmd_target, msg_req)
                                    except Exception as cb_err:
                                        aprobado = False
                                        resultado = {
                                            "error": True,
                                            "codigo_error": "AGENT_INTERNAL_ERROR",
                                            "mensaje": f"Excepción en callback de confirmación: {str(cb_err)}"
                                        }

                                    if resultado.get("codigo_error") != "AGENT_INTERNAL_ERROR":
                                        if aprobado:
                                            if nombre == "ejecutar_comando_bash":
                                                resultado = herramientas.command_sanitizer.ejecutar_comando(
                                                    raw_command=args_parsed.get("comando", ""),
                                                    timeout_sec=args_parsed.get("timeout_sec", 15),
                                                    aprobar_confirmacion=True,
                                                    cwd=args_parsed.get("cwd", self.current_working_directory),
                                                )
                                        else:
                                            resultado = {
                                                "error": True,
                                                "codigo_error": "PERMISO_DENEGADO_POR_USUARIO",
                                                "mensaje": f"El usuario denegó explícitamente la ejecución de '{cmd_target}'."
                                            }
                                else:
                                    resultado = {
                                        "error": True,
                                        "codigo_error": "CONFIRMACION_REQUERIDA",
                                        "mensaje": f"El comando '{cmd_target}' requiere autorización pero no hay un callback de confirmación configurado en la sesión."
                                    }

                        except TypeError as type_err:
                            resultado = {
                                "error": True,
                                "codigo_error": "AGENT_INTERNAL_ERROR",
                                "mensaje": f"Argumentos incompatibles para '{nombre}': {str(type_err)}"
                            }
                        except Exception as e:
                            resultado = {
                                "error": True,
                                "codigo_error": "AGENT_INTERNAL_ERROR",
                                "mensaje": f"Excepción durante la ejecución de '{nombre}': {str(e)}"
                            }
                    else:
                        resultado = {
                            "error": True,
                            "codigo_error": "AGENT_INTERNAL_ERROR",
                            "mensaje": f"Función '{nombre}' no registrada en funciones_disponibles."
                        }

                if isinstance(resultado, dict):
                    self._record_runtime_check(nombre, args_parsed, resultado)
                    self._record_successful_change(change_context, resultado)
                    self._update_task_execution_state(nombre, args_parsed, resultado)

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(resultado, ensure_ascii=False),
                })

                if self.current_task.status == "FAILED" and self.current_task.stop_reason:
                    return (
                        f"⚠️ Tarea detenida ({self.current_task.stop_reason}).\n"
                        f"• Última salida de verificación: {self.current_task.last_verification_output or 'ninguna'}"
                    )
                if self.current_task.status == "CANCELLED" and self.current_task.stop_reason:
                    return f"⚠️ Tarea cancelada ({self.current_task.stop_reason})."


def crear_chat(
    confirmador_callback: Optional[Callable[[str, str], bool]] = None,
    on_tool_call: Optional[Callable[[int, str, Dict[str, Any]], None]] = None,
) -> ChatSession:
    """Crea y devuelve una nueva sesión de chat."""
    return ChatSession(
        max_tool_iterations=DEFAULT_MAX_TOOL_ITERATIONS,
        confirmador_callback=confirmador_callback,
        on_tool_call=on_tool_call,
    )


def enviar_mensaje(chat: ChatSession, mensaje: str) -> str:
    """Envía un mensaje al chat y devuelve la respuesta."""
    return chat.enviar(mensaje)
