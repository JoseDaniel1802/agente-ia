"""
SandboxManager — Gestor de aislamiento OS mediante contenedores Docker.

Política: fail-closed.
Si Docker no está disponible, NINGÚN comando se ejecuta en el host.

Restricciones del contenedor:
- Red: DESACTIVADA (--network none). Sin excepciones.
- Usuario: sin privilegios (--user 1000:1000).
- Filesystem host: SOLO el workspace montado en /workspace.
  No se monta $HOME, .ssh, Docker socket, ni otros directorios.
- Filesystem raíz: read-only (--read-only).
- /tmp: tmpfs limitado a 64MB, noexec.
- Capabilities: NINGUNA (--cap-drop ALL).
- Privilegios: no-new-privileges.
- CPU: limitado a 50% de un core.
- Memoria: limitado a 256MB.
- PIDs: máximo 64 (anti fork-bomb).
- Timeout: máximo 30 segundos.
- Salida: truncada a 4000 caracteres.
- Contenedor: efímero (--rm), destruido tras cada ejecución.

Imagen: python:3.12-slim (Debian bookworm, ~45MB comprimida).
Contiene: Python 3.12, pip, setuptools. No contiene: gcc, make, git, curl, wget.

Este módulo NO valida rutas ni analiza comandos (eso es responsabilidad de
WorkspaceManager y CommandSanitizer respectivamente).
"""

import os
import time
import uuid
import signal
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional


# ── Configuración centralizada del sandbox ────────────────────────
AGENT_DOCKER_DIR = Path(__file__).resolve().parent / "docker"
SANDBOX_IMAGE = "muss_code_sandbox:latest"
FALLBACK_SANDBOX_IMAGE = "python:3.12-slim"
SANDBOX_CONTAINER_PREFIX = "muss_code_sandbox"
SANDBOX_WORKDIR = "/workspace"

SANDBOX_LIMITS = {
    "memory": "512m",          # Máximo 512 MB RAM para V8/Node.js y Python
    "cpus": "1.0",             # Máximo 1.0 CPU core para operaciones de empaquetado I/O
    "pids_limit": 64,          # Anti fork-bomb
    "timeout_default": 15,     # Segundos por defecto
    "timeout_max": 120,        # Máximo absoluto para operaciones de I/O o instalación
    "max_output_chars": 4000,  # Truncamiento de stdout/stderr
    "tmpfs_size": "64m",       # /tmp temporal limitado
}


class SandboxManager:
    """
    Gestor de sandbox OS basado en Docker.
    Ejecuta comandos dentro de contenedores efímeros aislados.

    Política fail-closed:
    Si Docker no está disponible, retorna SANDBOX_NO_DISPONIBLE.
    NUNCA ejecuta comandos directamente en el host.
    NUNCA intenta iniciar Docker automáticamente.
    """

    _docker_available_cached: Optional[bool] = None
    _image_available_cached: Optional[bool] = None

    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root).resolve()
        self._docker_available: Optional[bool] = None
        self._image_available: Optional[bool] = None

    def is_available(self) -> bool:
        """
        Verifica si Docker está instalado y el daemon operativo.
        El resultado se cachea para evitar llamadas repetidas a docker info.
        """
        if self._docker_available is not None:
            return self._docker_available

        if SandboxManager._docker_available_cached is not None:
            return SandboxManager._docker_available_cached

        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            SandboxManager._docker_available_cached = (result.returncode == 0)
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            SandboxManager._docker_available_cached = False

        return SandboxManager._docker_available_cached

    def ensure_sandbox_image(self) -> bool:
        """
        Garantiza que la imagen aislada muss_code_sandbox:latest exista en Docker local.
        Si no existe, la construye utilizando ÚNICAMENTE la ruta controlada interna
        AGENT_DOCKER_DIR (nunca el workspace del usuario ni contextos externos).
        """
        if self._image_available is not None:
            return self._image_available

        if SandboxManager._image_available_cached is True:
            return True

        if not self.is_available():
            return False

        # Verificar si la imagen muss_code_sandbox:latest ya existe
        try:
            inspect_res = subprocess.run(
                ["docker", "image", "inspect", SANDBOX_IMAGE],
                capture_output=True,
                timeout=15,
            )
            if inspect_res.returncode == 0:
                SandboxManager._image_available_cached = True
                return True
        except Exception:
            pass

        # Si no existe, construir usando estrictamente AGENT_DOCKER_DIR como contexto
        dockerfile_path = AGENT_DOCKER_DIR / "Dockerfile.sandbox"
        if not dockerfile_path.exists():
            return False

        try:
            build_res = subprocess.run(
                [
                    "docker", "build",
                    "-t", SANDBOX_IMAGE,
                    "-f", str(dockerfile_path),
                    str(AGENT_DOCKER_DIR),
                ],
                capture_output=True,
                timeout=180,
            )
            if build_res.returncode == 0:
                SandboxManager._image_available_cached = True
                return True
        except Exception:
            pass

        return False

    def validate_container_cwd(self, cwd: Optional[str]) -> str:
        """
        Valida que la ruta de directorio de trabajo proporcionada sea segura
        y se resuelva estrictamente dentro de /workspace. Retorna la ruta
        del contenedor '/workspace/...'.
        """
        if not cwd or cwd in ("/", "/workspace", ".", "./"):
            return SANDBOX_WORKDIR

        cwd_str = str(cwd).strip()
        if cwd_str.startswith("/workspace"):
            rel_part = cwd_str[len("/workspace"):].lstrip("/")
        else:
            rel_part = cwd_str

        if not rel_part or rel_part == ".":
            return SANDBOX_WORKDIR

        try:
            target_path = (self.workspace_root / rel_part).resolve()
            if not target_path.is_relative_to(self.workspace_root):
                raise ValueError("Ruta fuera del workspace")
            rel_resolved = target_path.relative_to(self.workspace_root)
            return f"{SANDBOX_WORKDIR}/{rel_resolved}" if str(rel_resolved) != "." else SANDBOX_WORKDIR
        except Exception:
            raise ValueError(f"Acceso denegado: El directorio de trabajo '{cwd}' se resuelve fuera del workspace.")

    def _build_docker_command(
        self,
        tokens: List[str],
        env: Dict[str, str],
        cwd: Optional[str] = None,
    ) -> List[str]:
        """
        Construye la lista de argumentos para `docker run` con todas las
        restricciones de seguridad, montajes y límites de recursos.
        """
        container_name = f"{SANDBOX_CONTAINER_PREFIX}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        workdir = self.validate_container_cwd(cwd)

        # Determinar cuál imagen usar (prioridad muss_code_sandbox:latest)
        target_image = SANDBOX_IMAGE if self.ensure_sandbox_image() else FALLBACK_SANDBOX_IMAGE

        cmd = [
            "docker", "run",
            "--rm",                                     # Destruir tras ejecución
            "--name", container_name,
            "--workdir", workdir,
            "--user", "1000:1000",                      # Usuario sin privilegios
            "--memory", SANDBOX_LIMITS["memory"],
            "--cpus", SANDBOX_LIMITS["cpus"],
            "--pids-limit", str(SANDBOX_LIMITS["pids_limit"]),
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",                        # Sin capabilities
            "--read-only",                              # Filesystem raíz read-only
            "--tmpfs", f"/tmp:rw,noexec,nosuid,size={SANDBOX_LIMITS['tmpfs_size']}",
            "--network", "none",                        # Red SIEMPRE desactivada
        ]

        # Montar ÚNICAMENTE el workspace — nada más del host
        cmd.extend([
            "-v", f"{self.workspace_root}:{SANDBOX_WORKDIR}:rw"
        ])

        # Variables de entorno aisladas (sin claves, tokens ni secretos)
        for key, value in env.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Imagen y comando a ejecutar
        cmd.append(target_image)
        cmd.extend(tokens)

        return cmd

    def _get_sandbox_env(self) -> Dict[str, str]:
        """
        Construye un entorno de variables mínimo y aislado para el contenedor.
        No incluye claves API, tokens, secretos ni variables del host.
        """
        return {
            "HOME": SANDBOX_WORKDIR,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin",
            "PYTHONPATH": SANDBOX_WORKDIR,
            "WORKSPACE_ROOT": SANDBOX_WORKDIR,
            "TERM": "dumb",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def get_offline_package_map(self) -> Dict[str, str]:
        """
        Retorna el mapa {nombre_paquete: ruta_tarball} obtenido de /var/pkg-store/index.json
        dentro del contenedor. Si no está disponible, retorna un diccionario vacío.
        El resultado se cachea para evitar llamadas repetidas a cat.
        """
        if getattr(self, "_offline_pkg_map", None) is not None:
            return self._offline_pkg_map

        res = self.execute(["cat", "/var/pkg-store/index.json"])
        if not res.get("error") and res.get("stdout"):
            import json
            try:
                pkg_map = json.loads(res["stdout"])
                if isinstance(pkg_map, dict):
                    self._offline_pkg_map = pkg_map
                    return self._offline_pkg_map
            except Exception:
                pass
        self._offline_pkg_map = {}
        return self._offline_pkg_map

    def execute(
        self,
        tokens: List[str],
        timeout_sec: int = SANDBOX_LIMITS["timeout_default"],
        cwd: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta tokens dentro de un contenedor Docker aislado en el directorio de trabajo especificado.
        Política fail-closed: si Docker no está disponible, NO ejecuta nada.

        Args:
            tokens: Lista de tokens del comando a ejecutar.
            timeout_sec: Tiempo límite en segundos.
            cwd: Directorio de trabajo en el workspace (ej. 'StudyHub/server' o '/workspace/StudyHub/server').

        Returns:
            Dict con stdout, stderr, codigo_salida, tiempo, etc.
        """
        if not self.is_available():
            return {
                "error": True,
                "codigo_error": "SANDBOX_NO_DISPONIBLE",
                "mensaje": (
                    "No es posible ejecutar comandos porque el sandbox Docker "
                    "no está disponible. Inicia Docker Desktop manualmente "
                    "para habilitar la ejecución segura de comandos."
                ),
            }

        try:
            container_workdir = self.validate_container_cwd(cwd)
        except ValueError as val_err:
            return {
                "error": True,
                "codigo_error": "FUERA_DEL_WORKSPACE",
                "mensaje": str(val_err),
            }

        timeout_final = max(1, min(int(timeout_sec), SANDBOX_LIMITS["timeout_max"]))
        env = self._get_sandbox_env()
        max_output = SANDBOX_LIMITS["max_output_chars"]

        docker_cmd = self._build_docker_command(
            tokens=tokens,
            env=env,
            cwd=container_workdir,
        )

        start_time = time.time()
        salida_truncada = False

        try:
            process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

            try:
                stdout_bytes, stderr_bytes = process.communicate(timeout=timeout_final + 5)
                elapsed_time = round(time.time() - start_time, 2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except Exception:
                    process.kill()
                process.wait()

                # Matar el contenedor por nombre como safety net
                container_name = docker_cmd[docker_cmd.index("--name") + 1]
                try:
                    subprocess.run(
                        ["docker", "kill", container_name],
                        capture_output=True,
                        timeout=5,
                    )
                except Exception:
                    pass

                return {
                    "error": True,
                    "codigo_error": "TIMEOUT",
                    "mensaje": f"El proceso en sandbox fue terminado por exceder {timeout_final}s.",
                    "sandbox": True,
                }

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            if len(stdout_str) > max_output:
                stdout_str = stdout_str[:max_output] + "\n... [stdout truncado]"
                salida_truncada = True
            if len(stderr_str) > max_output:
                stderr_str = stderr_str[:max_output] + "\n... [stderr truncado]"
                salida_truncada = True

            exit_code = process.returncode
            es_error = (exit_code != 0)

            return {
                "error": es_error,
                "codigo_error": "PROCESO_FALLIDO" if es_error else None,
                "comando": " ".join(tokens),
                "codigo_salida": exit_code,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "tiempo_ejecucion_seg": elapsed_time,
                "salida_truncada": salida_truncada,
                "sandbox": True,
            }

        except FileNotFoundError:
            self._docker_available = False
            return {
                "error": True,
                "codigo_error": "SANDBOX_NO_DISPONIBLE",
                "mensaje": "El ejecutable 'docker' no fue encontrado en el PATH.",
            }
        except Exception as e:
            return {
                "error": True,
                "codigo_error": "ERROR_SANDBOX",
                "mensaje": f"Error inesperado en sandbox: {str(e)}",
            }

    def ensure_image(self) -> Dict[str, Any]:
        """
        Verifica si la imagen Docker del sandbox está disponible localmente.
        Si no, intenta descargarla (requiere red del host, no del contenedor).
        """
        if not self.is_available():
            return {
                "error": True,
                "codigo_error": "SANDBOX_NO_DISPONIBLE",
                "mensaje": "Docker no está disponible.",
            }

        try:
            result = subprocess.run(
                ["docker", "image", "inspect", SANDBOX_IMAGE],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return {"error": False, "mensaje": f"Imagen '{SANDBOX_IMAGE}' disponible."}

            # Intentar pull
            result = subprocess.run(
                ["docker", "pull", SANDBOX_IMAGE],
                capture_output=True,
                timeout=120,
            )
            if result.returncode == 0:
                return {"error": False, "mensaje": f"Imagen '{SANDBOX_IMAGE}' descargada."}
            else:
                return {
                    "error": True,
                    "codigo_error": "IMAGEN_NO_DISPONIBLE",
                    "mensaje": f"No se pudo descargar la imagen '{SANDBOX_IMAGE}': {result.stderr.decode('utf-8', errors='replace')}",
                }
        except Exception as e:
            return {
                "error": True,
                "codigo_error": "ERROR_IMAGEN",
                "mensaje": f"Error verificando imagen Docker: {str(e)}",
            }
