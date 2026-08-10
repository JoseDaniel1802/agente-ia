import os
import re
import sys
import shlex
import fnmatch
import datetime
import subprocess
from pathlib import Path
from typing import Dict, Any, Union, Optional, List

from sandbox import SandboxManager


class WorkspaceManager:
    """
    Gestor de seguridad centralizado para el aislamiento de rutas (Sandbox del Workspace).
    Garantiza que todas las operaciones de archivos ocurran exclusivamente dentro del workspace_root
    y no accedan a recursos protegidos ni fuera del límite autorizado.
    """

    # Patrones de exclusión centralizados para archivos y carpetas sensibles
    DENYLIST_PATTERNS = [
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "id_rsa",
        "id_rsa.*",
        "id_ed25519",
        "id_ed25519.*",
        "credentials.json",
        "*.secret",
        ".git",
        ".git/*",
        ".venv",
        ".venv/*",
        "__pycache__",
        "__pycache__/*",
        ".opencode",
        ".opencode/*",
    ]

    def __init__(self, workspace_root: Optional[Union[str, Path]] = None):
        """
        Inicializa el WorkspaceManager.
        Si no se proporciona workspace_root, consulta la variable de entorno WORKSPACE_ROOT
        o utiliza el directorio de trabajo actual canonicalizado.
        """
        if workspace_root is None:
            workspace_root = os.getenv("WORKSPACE_ROOT", os.getcwd())

        try:
            self.workspace_root = Path(workspace_root).resolve()
        except Exception:
            self.workspace_root = Path(os.getcwd()).resolve()

    def _is_denylisted(self, rel_path: Path, real_target: Path) -> bool:
        """
        Verifica de forma implacable si una ruta o su destino físico coinciden con la DenyList.
        Evalúa el nombre base y cada segmento del camino tanto en la ruta relativa como en la real.
        """
        check_paths = [rel_path, real_target]

        for p in check_paths:
            filename = p.name
            for pattern in self.DENYLIST_PATTERNS:
                if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                    return True

            for part in p.parts:
                for pattern in self.DENYLIST_PATTERNS:
                    if fnmatch.fnmatch(part.lower(), pattern.lower()):
                        return True
        return False

    def validar_nuevo_workspace_root(self, nueva_ruta: Any) -> Dict[str, Any]:
        """
        Valida rigurosamente si una ruta recibida es apta para convertirse en el nuevo workspace_root.
        Verifica los 7 criterios de seguridad: existencia, directorio, resolución canónica,
        no pertenecer a rutas de sistema/HOME directo, no coincidir con denylists y no ser un symlink roto.
        """
        if nueva_ruta is None or str(nueva_ruta).strip() == "":
            return {
                "valida": False,
                "error": True,
                "codigo_error": "ENTRADA_NULA",
                "mensaje": "La ruta para el nuevo workspace no puede estar vacía."
            }

        input_path = Path(nueva_ruta)

        # 1. Comprobar enlace simbólico roto antes de resolver
        if input_path.is_symlink():
            try:
                sym_target = input_path.resolve()
                if not sym_target.exists() or not sym_target.is_dir():
                    return {
                        "valida": False,
                        "error": True,
                        "codigo_error": "SYMLINK_INVALIDO",
                        "mensaje": f"El enlace simbólico '{nueva_ruta}' apunta a un destino inválido o no existente."
                    }
            except Exception as s_err:
                return {
                    "valida": False,
                    "error": True,
                    "codigo_error": "SYMLINK_INVALIDO",
                    "mensaje": f"Error al verificar el enlace simbólico '{nueva_ruta}': {str(s_err)}"
                }

        try:
            target_path = input_path.resolve()
        except Exception as err:
            return {
                "valida": False,
                "error": True,
                "codigo_error": "ERROR_RESOLUCION_RUTA",
                "mensaje": f"No se pudo resolver la ruta '{nueva_ruta}': {str(err)}"
            }

        # 2. Comprobar existencia
        if not target_path.exists():
            return {
                "valida": False,
                "error": True,
                "codigo_error": "RUTA_NO_EXISTE",
                "mensaje": f"La ruta solicitada '{nueva_ruta}' no existe físicamente en el disco."
            }

        # 3. Comprobar que sea un directorio
        if not target_path.is_dir():
            return {
                "valida": False,
                "error": True,
                "codigo_error": "NO_ES_DIRECTORIO",
                "mensaje": f"La ruta solicitada '{nueva_ruta}' es un archivo, no un directorio."
            }

        # 4. Comprobar rutas prohibidas del sistema y HOME directo
        target_str = str(target_path)
        prohibited_roots = {
            "/", "/etc", "/usr", "/bin", "/sbin", "/System",
            "/Library", "/boot", "/dev", "/proc", "/sys", "/root",
            "/private/etc"
        }

        if target_str in prohibited_roots or target_str == str(Path.home()):
            return {
                "valida": False,
                "error": True,
                "codigo_error": "DIRECTORIO_SISTEMA_PROHIBIDO",
                "mensaje": f"Acceso denegado: '{target_str}' es un directorio del sistema o el HOME directo y no puede ser usado como workspace."
            }

        for p_root in ("/etc", "/bin", "/sbin", "/System", "/Library", "/boot", "/dev", "/proc", "/sys", "/root", "/private/etc"):
            if target_str == p_root or target_str.startswith(p_root + "/"):
                return {
                    "valida": False,
                    "error": True,
                    "codigo_error": "DIRECTORIO_SISTEMA_PROHIBIDO",
                    "mensaje": f"Acceso denegado: La ruta '{target_str}' pertenece a un directorio restringido del sistema."
                }

        # 5. Comprobar patrones denylist (.git, .venv, .opencode, etc.)
        if self._is_denylisted(target_path, target_path):
            return {
                "valida": False,
                "error": True,
                "codigo_error": "DIRECTORIO_PROTEGIDO",
                "mensaje": f"Acceso denegado: La ruta '{target_str}' es un directorio protegido (ej: .git, .venv, .opencode)."
            }

        return {
            "valida": True,
            "error": False,
            "mensaje": f"El directorio '{target_str}' ha sido verificado y es un workspace válido.",
            "ruta_absoluta": target_str,
            "path_obj": target_path,
        }

    def validar_ruta(
        self,
        ruta_solicitada: Any,
        must_exist: bool = False,
        is_creation: bool = False
    ) -> Dict[str, Any]:
        """
        Valida de forma estricta si una ruta recibida es segura y cae dentro del workspace.

        Args:
            ruta_solicitada: Ruta enviada por el caller (str o Path).
            must_exist: Si es True, la ruta debe existir físicamente en el disco.
            is_creation: Si es True, se valida la pertenencia del directorio padre para la creación.

        Returns:
            Dict estructurado con el estado de la validación.
        """
        if ruta_solicitada is None:
            return {
                "valida": False,
                "error": True,
                "codigo_error": "ENTRADA_NULA",
                "mensaje": "La ruta solicitada no puede ser None."
            }

        if not isinstance(ruta_solicitada, (str, Path)):
            return {
                "valida": False,
                "error": True,
                "codigo_error": "TIPO_INVALIDO",
                "mensaje": f"Se esperaba un parámetro de tipo 'str' o 'Path', se recibió '{type(ruta_solicitada).__name__}'."
            }

        ruta_str = str(ruta_solicitada).strip()
        if not ruta_str:
            return {
                "valida": False,
                "error": True,
                "codigo_error": "RUTA_VACIA",
                "mensaje": "La ruta solicitada no puede estar vacía."
            }

        try:
            input_path = Path(ruta_str)

            if not input_path.is_absolute():
                combined_path = self.workspace_root / input_path
            else:
                combined_path = input_path

            try:
                rel_initial = combined_path.relative_to(self.workspace_root)
            except ValueError:
                rel_initial = input_path

            if self._is_denylisted(rel_initial, rel_initial):
                return {
                    "valida": False,
                    "error": True,
                    "codigo_error": "ARCHIVO_PROTEGIDO",
                    "mensaje": f"Acceso denegado: La ruta '{ruta_str}' coincide con un archivo o directorio sensible protegido por la política de seguridad.",
                    "detalles": {
                        "ruta_solicitada": ruta_str,
                        "archivo_protegido": str(rel_initial)
                    }
                }

            existe = combined_path.exists() or combined_path.is_symlink()

            if must_exist and not existe:
                return {
                    "valida": False,
                    "error": True,
                    "codigo_error": "ARCHIVO_NO_ENCONTRADO",
                    "mensaje": f"La ruta solicitada '{ruta_str}' no existe físicamente en el disco."
                }

            if existe:
                real_target = combined_path.resolve()
            else:
                parent = combined_path.parent
                try:
                    parent_real = parent.resolve()
                except Exception as p_err:
                    return {
                        "valida": False,
                        "error": True,
                        "codigo_error": "PADRE_INVALIDO",
                        "mensaje": f"El directorio padre de la ruta '{ruta_str}' es inválido: {str(p_err)}"
                    }

                curr = parent
                while not curr.exists() and curr != curr.parent:
                    curr = curr.parent
                
                ancestro_real = curr.resolve()
                
                try:
                    if not ancestro_real.is_relative_to(self.workspace_root):
                        return {
                            "valida": False,
                            "error": True,
                            "codigo_error": "FUERA_DEL_WORKSPACE",
                            "mensaje": f"Acceso denegado: El directorio padre de '{ruta_str}' se resuelve fuera del workspace autorizado.",
                        }
                except ValueError:
                    return {
                        "valida": False,
                        "error": True,
                        "codigo_error": "FUERA_DEL_WORKSPACE",
                        "mensaje": f"Acceso denegado: El directorio padre de '{ruta_str}' se resuelve fuera del workspace autorizado.",
                    }

                rel_parent = combined_path.relative_to(self.workspace_root) if combined_path.is_absolute() and combined_path.is_relative_to(self.workspace_root) else input_path
                real_target = (self.workspace_root / rel_parent).resolve() if not input_path.is_absolute() else combined_path.resolve()

        except Exception as err:
            return {
                "valida": False,
                "error": True,
                "codigo_error": "ERROR_RESOLUCION_RUTA",
                "mensaje": f"Error procesando la ruta '{ruta_str}': {str(err)}"
            }

        try:
            if not real_target.is_relative_to(self.workspace_root):
                return {
                    "valida": False,
                    "error": True,
                    "codigo_error": "FUERA_DEL_WORKSPACE",
                    "mensaje": f"Acceso denegado: La ruta '{ruta_str}' se resuelve fuera del workspace autorizado.",
                    "detalles": {
                        "ruta_solicitada": ruta_str,
                        "ruta_resuelta": str(real_target),
                        "workspace_root": str(self.workspace_root)
                    }
                }
        except ValueError:
            return {
                "valida": False,
                "error": True,
                "codigo_error": "FUERA_DEL_WORKSPACE",
                "mensaje": f"Acceso denegado: La ruta '{ruta_str}' se resuelve fuera del workspace autorizado."
            }

        try:
            rel_to_workspace = real_target.relative_to(self.workspace_root)
        except ValueError:
            rel_to_workspace = input_path

        if self._is_denylisted(rel_to_workspace, real_target):
            return {
                "valida": False,
                "error": True,
                "codigo_error": "ARCHIVO_PROTEGIDO",
                "mensaje": f"Acceso denegado: La ruta '{ruta_str}' coincide con un archivo o directorio sensible protegido por la política de seguridad.",
                "detalles": {
                    "ruta_solicitada": ruta_str,
                    "archivo_protegido": str(rel_to_workspace)
                }
            }

        return {
            "valida": True,
            "error": False,
            "mensaje": f"Ruta '{ruta_str}' verificada y autorizada dentro del workspace.",
            "ruta_absoluta": str(real_target),
            "ruta_relativa": str(rel_to_workspace),
            "existe": existe
        }


class AuditLogger:
    """
    Registrador de auditoría append-only con sanitización de secretos y prevención de Log Injection.
    """
    def __init__(self, log_file: Optional[Path] = None):
        if log_file is None:
            workspace_root = os.getenv("WORKSPACE_ROOT", os.getcwd())
            log_file = Path(workspace_root) / ".agente_audit.log"
        self.log_file = Path(log_file)

    def log(self, herramienta: str, clasificacion: str, estado: str, comando_o_ruta: str, detalles: str = ""):
        try:
            clean_cmd = re.sub(r"(key|token|password|secret|api_key)=\S+", r"\1=***MASCARADO***", str(comando_o_ruta), flags=re.IGNORECASE)
            clean_details = re.sub(r"(key|token|password|secret|api_key)=\S+", r"\1=***MASCARADO***", str(detalles), flags=re.IGNORECASE)

            # Prevención de Log Injection / Log Forgery
            clean_cmd = clean_cmd.replace("\r", " ").replace("\n", " ")
            clean_details = clean_details.replace("\r", " ").replace("\n", " ")

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            entry = f"[{timestamp}] [{herramienta}] [{clasificacion}] [{estado}] CMD='{clean_cmd}' {clean_details}\n"

            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass


class CommandSanitizer:
    """
    Sanitizador y ejecutor seguro de comandos Bash (Shell Sandbox).
    Fuerza shell=False, valida ejecutables contra una política estricta,
    aísla el entorno de variables (env), previene PATH hijacking y destruye procesos en timeout.
    """

    BLOCKED_BINARIES = {
        "sudo", "su", "chmod", "chown", "dd", "mkfs", "shutdown", "reboot",
        "nc", "ncat", "netcat", "nmap", "curl", "wget", "vim", "vi", "nano", "emacs"
    }

    ALLOWED_BINARIES = {
        "pwd", "ls", "dir", "pytest", "grep", "find", "wc", "head", "tail", "cat"
    }

    VERSION_COMMANDS = {"node", "npm", "python", "python3"}

    def __init__(self, workspace_manager: WorkspaceManager):
        self.workspace_manager = workspace_manager
        self.workspace_root = workspace_manager.workspace_root
        self.audit_logger = AuditLogger(self.workspace_root / ".agente_audit.log")
        self.sandbox_manager = SandboxManager(self.workspace_root)

    def _contains_shell_injection(self, raw_command: str) -> bool:
        """Comprueba si la cadena raw contiene operadores de inyección de shell o subshells."""
        for op in ["$(", "`", ";", "&&", "||", "|", ">", ">>", "<", "2>"]:
            if op in raw_command:
                return True
        return False

    @classmethod
    def _is_informational_command(cls, tokens: List[str], executable_name: str) -> bool:
        """Reconoce consultas exactas que no cambian el estado del sandbox."""
        if executable_name == "which":
            return all(not token.startswith("-") for token in tokens[1:])
        if executable_name in cls.VERSION_COMMANDS:
            return len(tokens) == 2 and tokens[1] in ("--version", "-v", "-V")
        return executable_name == "git" and len(tokens) == 2 and tokens[1] == "--version"

    def validar_y_clasificar(self, raw_command: Any) -> Dict[str, Any]:
        """
        Valida, tokeniza y clasifica un comando enviando argumentos de ruta a WorkspaceManager.
        """
        if raw_command is None:
            return {"valido": False, "codigo_error": "COMANDO_VACIO", "mensaje": "El comando no puede ser None."}

        if not isinstance(raw_command, str):
            return {"valido": False, "codigo_error": "TIPO_INVALIDO", "mensaje": "El comando debe ser una cadena de texto."}

        cmd_str = raw_command.strip()
        if not cmd_str:
            return {"valido": False, "codigo_error": "COMANDO_VACIO", "mensaje": "El comando no puede estar vacío."}

        # 1. Chequeo de inyección de shell en la cadena raw
        if self._contains_shell_injection(cmd_str):
            self.audit_logger.log("CommandSanitizer", "INYECCION", "BLOQUEADO", cmd_str, "Sintaxis de shell no permitida")
            return {
                "valido": False,
                "codigo_error": "SHELL_INJECTION_RISK",
                "mensaje": "Sintaxis de shell o inyección detectada: El uso de operadores de shell (;, &&, ||, |, >, >>, $()) no está permitido."
            }

        # 2. Tokenización sintáctica con shlex
        try:
            tokens = shlex.split(cmd_str)
        except Exception as e:
            return {
                "valido": False,
                "codigo_error": "SHELL_INJECTION_RISK",
                "mensaje": f"Error al parsear tokens del comando con shlex: {str(e)}"
            }

        if not tokens:
            return {"valido": False, "codigo_error": "COMANDO_VACIO", "mensaje": "No se encontraron tokens en el comando."}

        executable_token = tokens[0].lower()
        executable_name = Path(executable_token).name

        is_python_test = False

        # Si se invoca 'pytest', convertir a '[python_interpreter, -m, pytest]' para evadir problema de shebang con espacios en macOS
        if executable_name == "pytest":
            tokens = ["python3", "-m", "unittest"] + tokens[1:]
            is_python_test = True
            executable_name = "python"

        # 3. Prevención de PATH Hijacking: Verificar si existe un archivo falso ejecutable en la raíz del workspace
        local_fake_bin = self.workspace_root / executable_name
        if local_fake_bin.exists() and local_fake_bin.is_file() and ".venv" not in str(local_fake_bin):
            self.audit_logger.log("CommandSanitizer", "PATH_HIJACKING", "BLOQUEADO", cmd_str, f"Binario local sospechoso {local_fake_bin}")
            return {
                "valido": False,
                "codigo_error": "COMANDO_NO_PERMITIDO",
                "mensaje": f"Secuestro de PATH detectado: Existe un ejecutable local '{executable_name}' dentro del workspace."
            }

        # 4. Verificar si el ejecutable está en la lista negra de prohibidos
        if executable_name in self.BLOCKED_BINARIES:
            self.audit_logger.log("CommandSanitizer", "PROHIBIDO", "BLOQUEADO", cmd_str, f"Binario {executable_name} prohibido")
            return {
                "valido": False,
                "codigo_error": "COMANDO_NO_PERMITIDO",
                "mensaje": f"El ejecutable '{executable_name}' está estrictamente prohibido por la política de seguridad."
            }

        # 5. Auditoría de Flags Peligrosos para comandos específicos (find y git)
        if executable_name == "find":
            for t in tokens[1:]:
                if t.lower() in ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-L", "-follow", "-fls", "-fprint"):
                    self.audit_logger.log("CommandSanitizer", "FLAG_PROHIBIDO", "BLOQUEADO", cmd_str, f"Flag find '{t}' prohibido")
                    return {
                        "valido": False,
                        "codigo_error": "COMANDO_NO_PERMITIDO",
                        "mensaje": f"El flag '{t}' en 'find' está prohibido por riesgo de seguridad."
                    }

        if executable_name == "git":
            for t in tokens[1:]:
                if t.startswith("-c") or t.startswith("--config") or t.startswith("--exec-path") or t.startswith("--upload-pack"):
                    self.audit_logger.log("CommandSanitizer", "FLAG_PROHIBIDO", "BLOQUEADO", cmd_str, f"Flag git '{t}' prohibido")
                    return {
                        "valido": False,
                        "codigo_error": "COMANDO_NO_PERMITIDO",
                        "mensaje": f"El flag de git '{t}' está prohibido por riesgo de seguridad."
                    }

        # 6. Invocaciones de Python (ej: python -c "..." o python script.py)
        if executable_name in ("python", "python3"):
            if len(tokens) > 1 and tokens[1] == "-c":
                self.audit_logger.log("CommandSanitizer", "PROHIBIDO", "BLOQUEADO", cmd_str, "python -c prohibido")
                return {
                    "valido": False,
                    "codigo_error": "COMANDO_NO_PERMITIDO",
                    "mensaje": "La ejecución arbitraria inline ('python -c') no está permitida."
                }
            if len(tokens) > 2 and tokens[1] == "-m" and tokens[2] in ("pytest", "unittest"):
                is_python_test = True
            elif len(tokens) > 1 and not tokens[1].startswith("-"):
                script_path_token = tokens[1]
                val_script = self.workspace_manager.validar_ruta(script_path_token, must_exist=True)
                if not val_script["valida"]:
                    self.audit_logger.log("CommandSanitizer", "INVALID_PATH", "BLOQUEADO", cmd_str, val_script["mensaje"])
                    return {
                        "valido": False,
                        "codigo_error": val_script.get("codigo_error", "ARGUMENTO_DE_RUTA_INVALIDO"),
                        "mensaje": f"El script Python '{script_path_token}' no es válido: {val_script['mensaje']}"
                    }
                return {
                    "valido": True,
                    "requiere_confirmacion": True,
                    "tokens": tokens,
                    "comando_limpio": cmd_str,
                    "clasificacion": "script_python"
                }

        # 7. Validar argumentos de ruta para binarios estándar
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            if "/" in token or ("." in token and not token.isdigit()):
                val_arg = self.workspace_manager.validar_ruta(token)
                if not val_arg["valida"] and val_arg["codigo_error"] in ("FUERA_DEL_WORKSPACE", "ARCHIVO_PROTEGIDO"):
                    self.audit_logger.log("CommandSanitizer", "ARG_OUT_OF_BOUNDS", "BLOQUEADO", cmd_str, val_arg["mensaje"])
                    return {
                        "valido": False,
                        "codigo_error": val_arg["codigo_error"],
                        "mensaje": f"El argumento de ruta '{token}' fue denegado: {val_arg['mensaje']}"
                    }

        # 8. Clasificar según necesidad de confirmación
        if self._is_informational_command(tokens, executable_name):
            requiere_confirmacion = False
        elif is_python_test or executable_name == "pytest":
            requiere_confirmacion = False
        elif executable_name == "git":
            subcmd = tokens[1].lower() if len(tokens) > 1 else ""
            if subcmd in ("status", "diff", "log"):
                requiere_confirmacion = False
            else:
                requiere_confirmacion = True
        elif executable_name in ("pip", "pip3", "npm", "rm", "mv", "cp", "mkdir", "rmdir"):
            requiere_confirmacion = True
        elif executable_name in self.ALLOWED_BINARIES:
            requiere_confirmacion = False
        else:
            requiere_confirmacion = True

        return {
            "valido": True,
            "requiere_confirmacion": requiere_confirmacion,
            "tokens": tokens,
            "comando_limpio": cmd_str,
            "clasificacion": "binario_estandar"
        }

    def ejecutar_comando(
        self,
        raw_command: str,
        timeout_sec: int = 15,
        aprobar_confirmacion: bool = False
    ) -> Dict[str, Any]:
        """
        Ejecuta un comando exclusivamente dentro del sandbox Docker.
        Política fail-closed: si Docker no está disponible, NO ejecuta
        el comando en el host. Retorna SANDBOX_NO_DISPONIBLE.
        """
        evaluacion = self.validar_y_clasificar(raw_command)
        if not evaluacion["valido"]:
            return {
                "error": True,
                "codigo_error": evaluacion["codigo_error"],
                "mensaje": evaluacion["mensaje"]
            }

        if evaluacion["requiere_confirmacion"] and not aprobar_confirmacion:
            self.audit_logger.log("CommandSanitizer", "CONFIRMACION", "REQUIERE_AUTORIZACION", raw_command)
            return {
                "error": True,
                "codigo_error": "CONFIRMACION_REQUERIDA",
                "comando": evaluacion["comando_limpio"],
                "mensaje": f"El comando '{evaluacion['comando_limpio']}' requiere autorización explícita del usuario para ser ejecutado."
            }

        timeout_final = max(1, min(int(timeout_sec), 30))
        tokens = evaluacion["tokens"]
        cmd_str = evaluacion["comando_limpio"]

        # ── Política fail-closed: SOLO ejecución en sandbox ──────
        if not self.sandbox_manager.is_available():
            self.audit_logger.log(
                "CommandSanitizer", "SIN_SANDBOX", "BLOQUEADO", cmd_str,
                "Sandbox Docker no disponible. Comando NO ejecutado en el host."
            )
            return {
                "error": True,
                "codigo_error": "SANDBOX_NO_DISPONIBLE",
                "mensaje": (
                    "No es posible ejecutar comandos porque el sandbox Docker "
                    "no está disponible. Inicia Docker Desktop manualmente "
                    "para habilitar la ejecución segura de comandos."
                )
            }

        # ── Ejecución dentro del sandbox Docker ──────────────────
        self.audit_logger.log(
            "CommandSanitizer", "SANDBOX", "EJECUTANDO", cmd_str, "Docker sandbox"
        )
        result = self.sandbox_manager.execute(
            tokens=tokens,
            timeout_sec=timeout_final,
        )
        result["requirio_confirmacion"] = evaluacion["requiere_confirmacion"]
        self.audit_logger.log(
            "CommandSanitizer",
            "SANDBOX",
            "EXITO" if not result.get("error") else result.get("codigo_error", "ERROR"),
            cmd_str,
            f"exit_code={result.get('codigo_salida', '?')}"
        )
        return result
