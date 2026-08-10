import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pytest
from unittest.mock import MagicMock, patch

from sandbox import SandboxManager, SANDBOX_WORKDIR
from seguridad import CommandSanitizer, WorkspaceManager
from agente import ChatSession, TaskExecutionState, MAX_REPAIR_ATTEMPTS


@pytest.fixture
def temp_workspace(tmp_path):
    ws = tmp_path / "test_ws"
    ws.mkdir()
    return ws


@pytest.fixture
def sanitizer(temp_workspace):
    wm = WorkspaceManager(temp_workspace)
    return CommandSanitizer(wm)


@pytest.fixture
def sandbox(temp_workspace):
    return SandboxManager(temp_workspace)


@pytest.fixture
def session(temp_workspace):
    s = ChatSession()
    s.workspace_root = temp_workspace
    return s


# 1. node --version no requiere autorización.
def test_node_version_no_auth(sanitizer):
    res = sanitizer.validar_y_clasificar("node --version")
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "READ_ONLY"


# 2. npm --version no requiere autorización.
def test_npm_version_no_auth(sanitizer):
    res = sanitizer.validar_y_clasificar("npm --version")
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "READ_ONLY"


# 3. tsc --version no requiere autorización.
def test_tsc_version_no_auth(sanitizer):
    res = sanitizer.validar_y_clasificar("tsc --version")
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "READ_ONLY"


# 4. vite --version no requiere autorización.
def test_vite_version_no_auth(sanitizer):
    res = sanitizer.validar_y_clasificar("vite --version")
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "READ_ONLY"


# 5. vitest --version no requiere autorización.
def test_vitest_version_no_auth(sanitizer):
    res = sanitizer.validar_y_clasificar("vitest --version")
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "READ_ONLY"


# 6. pytest --version no requiere autorización.
def test_pytest_version_no_auth(sanitizer):
    res = sanitizer.validar_y_clasificar("pytest --version")
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "READ_ONLY"


# 7. npm install requiere autorización.
def test_npm_install_requires_auth(sanitizer):
    res = sanitizer.validar_y_clasificar("npm install express")
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is True
    assert res["clasificacion"] == "MUTATING"


# 8. rm requiere autorización.
def test_rm_requires_auth(sanitizer):
    res = sanitizer.validar_y_clasificar("rm temp.txt")
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is True
    assert res["clasificacion"] == "MUTATING"


# 9. curl => NETWORK_BLOCKED.
def test_curl_network_blocked(sanitizer):
    res = sanitizer.validar_y_clasificar("curl https://example.com")
    assert res["valido"] is False
    assert res["codigo_error"] == "NETWORK_BLOCKED"
    assert res["clasificacion"] == "NETWORK"


# 10. npm ping => NETWORK_BLOCKED.
def test_npm_ping_network_blocked(sanitizer):
    res = sanitizer.validar_y_clasificar("npm ping")
    assert res["valido"] is False
    assert res["codigo_error"] == "NETWORK_BLOCKED"


# 11. npm view online => NETWORK_BLOCKED.
def test_npm_view_online_network_blocked(sanitizer):
    res = sanitizer.validar_y_clasificar("npm view express version")
    assert res["valido"] is False
    assert res["codigo_error"] == "NETWORK_BLOCKED"


# 12. ENOTCACHED => DEPENDENCIA_NO_DISPONIBLE_OFFLINE.
def test_enotcached_normalization(sanitizer):
    with patch.object(SandboxManager, "is_available", return_value=True), \
         patch.object(SandboxManager, "execute", return_value={
             "error": True,
             "codigo_error": "PROCESO_FALLIDO",
             "stdout": "",
             "stderr": "npm ERR! code ENOTCACHED\nnpm ERR! express not in cache",
             "codigo_salida": 1,
         }):
        res = sanitizer.ejecutar_comando("npm view express version --offline")
        assert res["error"] is True
        assert res["codigo_error"] == "DEPENDENCIA_NO_DISPONIBLE_OFFLINE"
        assert "express" in res["mensaje"]


# 13. ENOTCACHED no incrementa repair_attempts.
def test_enotcached_does_not_increment_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "DEPENDENCIA_NO_DISPONIBLE_OFFLINE",
        "mensaje": "La dependencia 'express' no está disponible offline."
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "npm view express --offline"}, res)
    assert session.current_task.repair_attempts == 0
    assert session.current_task.verification_status == "ENVIRONMENT_BLOCKED"


# 14. timeout no incrementa repair_attempts.
def test_timeout_does_not_increment_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "TIMEOUT",
        "mensaje": "El proceso fue terminado por timeout."
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "tsc --noEmit"}, res)
    assert session.current_task.repair_attempts == 0
    assert session.current_task.verification_status == "VERIFICATION_UNAVAILABLE"


# 15. Docker failure no incrementa repair_attempts.
def test_docker_failure_does_not_increment_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "SANDBOX_NO_DISPONIBLE",
        "mensaje": "Docker no está disponible."
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, res)
    assert session.current_task.repair_attempts == 0
    assert session.current_task.verification_status == "ENVIRONMENT_BLOCKED"


# 16. resultado None no incrementa repair_attempts.
def test_none_result_does_not_increment_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, {})
    assert session.current_task.repair_attempts == 0


# 17. resultado vacío no incrementa repair_attempts.
def test_empty_result_does_not_increment_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {"error": True, "stdout": "", "stderr": "", "mensaje": ""}
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, res)
    assert session.current_task.repair_attempts == 0
    assert session.current_task.verification_status == "VERIFICATION_UNAVAILABLE"


# 18. VERIFICATION_UNAVAILABLE no entra en REPAIR.
def test_verification_unavailable_no_repair(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {"error": True, "codigo_error": "VERIFICATION_UNAVAILABLE", "mensaje": "Verificación interrumpida."}
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, res)
    assert session.current_task.phase != "REPAIR"
    assert session.current_task.repair_attempts == 0


# 19. tres resultados sin evidencia NO activan MAX_REPAIR_ATTEMPTS.
def test_three_empty_results_do_not_trigger_max_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {"error": True, "stdout": "", "stderr": "", "mensaje": ""}
    for _ in range(3):
        session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, res)
    assert session.current_task.repair_attempts == 0
    assert session.current_task.status == "ACTIVE"


# 20. tres fallos reales SÍ activan MAX_REPAIR_ATTEMPTS.
def test_three_real_failures_trigger_max_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_salida": 1,
        "stderr": "FAILED test_main.py::test_calc - AssertionError: 1 != 2",
    }
    for _ in range(MAX_REPAIR_ATTEMPTS):
        session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, res)

    assert session.current_task.repair_attempts == MAX_REPAIR_ATTEMPTS
    assert session.current_task.status == "FAILED"
    assert "Se alcanzó el límite máximo" in session.current_task.stop_reason


# 21. cd no se ejecuta como binario.
def test_cd_not_executed_as_binary(sanitizer, temp_workspace):
    subdir = temp_workspace / "subfolder"
    subdir.mkdir()
    res = sanitizer.validar_y_clasificar("cd subfolder")
    assert res["valido"] is True
    assert res.get("is_cd") is True
    assert res["new_cwd"] == "subfolder"

    exec_res = sanitizer.ejecutar_comando("cd subfolder")
    assert exec_res["error"] is False
    assert exec_res["is_cd"] is True
    assert exec_res["sandbox"] is False


# 22. cwd genera --workdir.
def test_cwd_generates_workdir(sandbox):
    cmd = sandbox._build_docker_command(tokens=["tsc", "--noEmit"], env={}, cwd="StudyHub/server")
    workdir_idx = cmd.index("--workdir")
    assert cmd[workdir_idx + 1] == "/workspace/StudyHub/server"


# 23. cwd no puede escapar de /workspace.
def test_cwd_cannot_escape_workspace(sandbox):
    with pytest.raises(ValueError):
        sandbox.validate_container_cwd("../outside")


# 24. capabilities_cache evita comprobaciones.
def test_capabilities_cache_prevents_rechecks(session):
    session.set_capability("node", "runtime", True)
    res = session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "node --version"})
    assert res is not None
    assert res["error"] is False
    assert res["cached"] is True


# 25. capabilities_cache permite invalidación.
def test_capabilities_cache_invalidation(session):
    session.set_capability("node", "runtime", True)
    assert session.get_capability("node")["available"] is True
    session.invalidate_capabilities("node")
    assert session.get_capability("node") is None


# 26. pytest real fallando entra en REPAIR.
def test_pytest_real_failure_enters_repair(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_salida": 1,
        "stderr": "FAILED test_api.py - AssertionError: 404 != 200"
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, res)
    assert session.current_task.repair_attempts == 1
    assert session.current_task.phase == "REPAIR"


# 27. TypeScript real fallando entra en REPAIR.
def test_tsc_real_failure_enters_repair(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_salida": 2,
        "stderr": "src/index.ts(10,5): error TS2322: Type 'string' is not assignable to type 'number'."
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "tsc --noEmit"}, res)
    assert session.current_task.repair_attempts == 1
    assert session.current_task.phase == "REPAIR"


# 28. Docker conserva --network none.
def test_docker_retains_network_none(sandbox):
    cmd = sandbox._build_docker_command(tokens=["ls"], env={})
    net_idx = cmd.index("--network")
    assert cmd[net_idx + 1] == "none"


# 29. Docker conserva --read-only.
def test_docker_retains_read_only(sandbox):
    cmd = sandbox._build_docker_command(tokens=["ls"], env={})
    assert "--read-only" in cmd


# 30. Docker conserva --user 1000:1000.
def test_docker_retains_user_1000(sandbox):
    cmd = sandbox._build_docker_command(tokens=["ls"], env={})
    user_idx = cmd.index("--user")
    assert cmd[user_idx + 1] == "1000:1000"


# 31. Docker solo monta /workspace.
def test_docker_mounts_only_workspace(sandbox, temp_workspace):
    cmd = sandbox._build_docker_command(tokens=["ls"], env={})
    v_idx = cmd.index("-v")
    mount_arg = cmd[v_idx + 1]
    assert mount_arg == f"{temp_workspace}:{SANDBOX_WORKDIR}:rw"


# 32. ChatSession tiene correctamente disponible confirmador_callback.
def test_chatsession_has_confirmador_callback():
    mock_cb = MagicMock(return_value=True)
    session = ChatSession(confirmador_callback=mock_cb)
    assert hasattr(session, "confirmador_callback")
    assert session.confirmador_callback == mock_cb


# 33. ejecutar_comando_bash no genera AttributeError sin confirmador_callback.
def test_ejecutar_comando_bash_no_attribute_error_without_callback():
    session = ChatSession(confirmador_callback=None)
    assert hasattr(session, "confirmador_callback")
    assert session.confirmador_callback is None


# 34. Una excepción interna se clasifica como AGENT_INTERNAL_ERROR.
def test_agent_internal_error_classification(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "AGENT_INTERNAL_ERROR",
        "mensaje": "Excepción durante la ejecución: 'ChatSession' object has no attribute 'confirmador_callback'"
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "npm install express"}, res)
    assert session.current_task.verification_possible is False
    assert session.current_task.verification_status == "AGENT_INTERNAL_ERROR"


# 35. Una excepción interna no incrementa repair_attempts.
def test_agent_internal_error_does_not_increment_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "AGENT_INTERNAL_ERROR",
        "mensaje": "Error interno del agente."
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, res)
    assert session.current_task.repair_attempts == 0
    assert session.current_task.phase != "REPAIR"


# 36. Tres excepciones internas no producen el límite de reparaciones.
def test_three_agent_internal_errors_do_not_trigger_max_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "AGENT_INTERNAL_ERROR",
        "mensaje": "Excepción interna simulada."
    }
    for _ in range(3):
        session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, res)

    assert session.current_task.repair_attempts == 0
    assert session.current_task.status == "ACTIVE"
    assert session.current_task.stop_reason is None


# 37. MODULE_NOT_FOUND con tarball disponible se clasifica como DEPENDENCIA_NO_INSTALADA.
def test_module_not_found_classified_as_dependencia_no_instalada(sanitizer):
    from seguridad import _extract_missing_module_name
    output = "Error: Cannot find module 'express'\nRequire stack:\n- /workspace/[eval]\ncode: 'MODULE_NOT_FOUND'"
    assert _extract_missing_module_name(output) == "express"

    with patch.object(SandboxManager, "is_available", return_value=True), \
         patch.object(SandboxManager, "get_offline_package_map", return_value={"express": "/var/pkg-store/express-5.2.1.tgz"}), \
         patch.object(SandboxManager, "execute", return_value={
             "error": True,
             "codigo_error": "PROCESO_FALLIDO",
             "stdout": "",
             "stderr": output,
             "codigo_salida": 1,
         }):
        res = sanitizer.ejecutar_comando("node app.js")
        assert res["error"] is True
        assert res["codigo_error"] == "DEPENDENCIA_NO_INSTALADA"
        assert res["paquete_faltante"] == "express"
        assert res["tarball_offline"] == "/var/pkg-store/express-5.2.1.tgz"


# 38. DEPENDENCIA_NO_INSTALADA no incrementa repair_attempts.
def test_dependencia_no_instalada_does_not_increment_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "DEPENDENCIA_NO_INSTALADA",
        "paquete_faltante": "express",
        "tarball_offline": "/var/pkg-store/express-5.2.1.tgz",
        "mensaje": "La dependencia 'express' no está instalada pero hay paquete offline disponible."
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "node app.js"}, res)
    assert session.current_task.repair_attempts == 0
    assert session.current_task.verification_status == "ENVIRONMENT_BLOCKED"
    assert session.current_task.phase != "REPAIR"


# 39. Módulos built-in de Node.js no se clasifican como dependencia faltante externa.
def test_node_builtin_modules_not_extracted_as_external():
    from seguridad import _extract_missing_module_name
    assert _extract_missing_module_name("Error: Cannot find module 'fs'") is None
    assert _extract_missing_module_name("Error: Cannot find module 'path'") is None
    assert _extract_missing_module_name("Error: Cannot find module './local_file.js'") is None


# 40. Tres detecciones de DEPENDENCIA_NO_INSTALADA no activan el límite de 3 reparaciones.
def test_three_dependencia_no_instalada_do_not_trigger_max_repair(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "DEPENDENCIA_NO_INSTALADA",
        "mensaje": "Dependencia express no instalada."
    }
    for _ in range(3):
        session._update_task_execution_state("ejecutar_comando_bash", {"comando": "node app.js"}, res)

    assert session.current_task.repair_attempts == 0
    assert session.current_task.status == "ACTIVE"


# 41. Subcomandos de solo lectura de npm no requieren confirmación.
@pytest.mark.parametrize("cmd", [
    "npm prefix",
    "npm root",
    "npm root -g",
    "npm cache ls",
    "npm cache ls express",
    "npm config get cache",
    "npm list -g --depth=0",
    "npm ls",
    "npm view express version",
    "npm help"
])
def test_npm_readonly_subcommands_no_auth(sanitizer, cmd):
    res = sanitizer.validar_y_clasificar(cmd)
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "READ_ONLY"


# 42. Validación de nombre de paquete npm (scopes sin paquete no son válidos).
def test_is_valid_npm_package_name_validation(sanitizer):
    from seguridad import CommandSanitizer
    assert CommandSanitizer.is_valid_npm_package_name("express") is True
    assert CommandSanitizer.is_valid_npm_package_name("@testing-library/react") is True
    assert CommandSanitizer.is_valid_npm_package_name("@nestjs/core") is True

    # Scopes solos NO son válidos como paquete
    assert CommandSanitizer.is_valid_npm_package_name("@testing-library") is False
    assert CommandSanitizer.is_valid_npm_package_name("@nestjs") is False
    assert CommandSanitizer.is_valid_npm_package_name("") is False


# 43. EINVALIDTAGNAME se clasifica como INVALID_ENVIRONMENT_QUERY.
def test_einvalidtagname_classified_as_invalid_environment_query(sanitizer):
    with patch.object(SandboxManager, "is_available", return_value=True), \
         patch.object(SandboxManager, "execute", return_value={
             "error": True,
             "codigo_error": "PROCESO_FALLIDO",
             "stdout": "",
             "stderr": "npm ERR! code EINVALIDTAGNAME\nnpm ERR! Invalid tag name '@testing-library'",
             "codigo_salida": 1,
         }):
        res = sanitizer.ejecutar_comando("npm cache ls @testing-library")
        assert res["error"] is True
        assert res["codigo_error"] == "INVALID_ENVIRONMENT_QUERY"


# 44. INVALID_ENVIRONMENT_QUERY no incrementa repair_attempts.
def test_invalid_environment_query_does_not_increment_repair_attempts(session):
    session.current_task.start_task("Test task", requires_verification=True)
    res = {
        "error": True,
        "codigo_error": "INVALID_ENVIRONMENT_QUERY",
        "mensaje": "Etiqueta de paquete inválida."
    }
    session._update_task_execution_state("ejecutar_comando_bash", {"comando": "npm cache ls @testing-library"}, res)
    assert session.current_task.repair_attempts == 0
    assert session.current_task.verification_status == "ENVIRONMENT_BLOCKED"
    assert session.current_task.phase != "REPAIR"


# 45. discover_project_capabilities lee package.json sin ejecutar comandos Docker.
def test_discover_project_capabilities_reads_package_json(session, temp_workspace):
    pkg_json = temp_workspace / "package.json"
    pkg_json.write_text('{"dependencies": {"express": "^4.21.2"}, "devDependencies": {"vitest": "^1.0.0"}}')
    node_modules = temp_workspace / "node_modules"
    node_modules.mkdir()
    (node_modules / "express").mkdir()

    session.current_working_directory = ""
    discovered = session.discover_project_capabilities()
    assert "express" in discovered
    assert discovered["express"]["installed"] is True
    assert "vitest" in discovered
    assert discovered["vitest"]["installed"] is False


# 46. Comandos de inspección pura son READ_ONLY sin confirmación.
@pytest.mark.parametrize("cmd", [
    "pwd", "ls", "ls -la", "ls -lah", "df -h /", "du -sh .",
    "which node", "whereis node", "command -v tsc",
    "cat package.json", "grep express package.json", "find . -name '*.js'",
    "git status", "git diff", "git log", "git branch",
    "node --version", "npm --version", "python3 --version", "tsc --version",
    "npm prefix", "npm root -g", "npm cache ls", "npm config get cache"
])
def test_read_only_commands_require_no_confirmation(sanitizer, cmd):
    res = sanitizer.validar_y_clasificar(cmd)
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "READ_ONLY"


# 47. Comandos de verificación son VERIFICATION sin confirmación.
@pytest.mark.parametrize("cmd", [
    "node app.js", "node -e \"console.log(1)\"", "python3 script.py", "python3 -c \"import sys\"",
    "tsc", "tsc --noEmit", "pytest", "vitest run", "npm test", "npm run build"
])
def test_verification_commands_require_no_confirmation(sanitizer, cmd):
    res = sanitizer.validar_y_clasificar(cmd)
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "VERIFICATION"


# 48. mkdir dentro de /workspace es WORKSPACE_SAFE_MUTATION sin confirmación.
@pytest.mark.parametrize("cmd", [
    "mkdir -p PawsTrack", "mkdir -p PawsTrack/src", "mkdir -p PawsTrack/server/controllers"
])
def test_mkdir_inside_workspace_safe_mutation(sanitizer, cmd):
    res = sanitizer.validar_y_clasificar(cmd)
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is False
    assert res["clasificacion"] == "WORKSPACE_SAFE_MUTATION"


# 49. mkdir fuera del workspace o con path traversal es denegado/bloqueado.
@pytest.mark.parametrize("cmd", [
    "mkdir /etc/test", "mkdir /var/test", "mkdir ../../etc", "mkdir /tmp/arbitrary"
])
def test_mkdir_outside_workspace_blocked(sanitizer, cmd):
    res = sanitizer.validar_y_clasificar(cmd)
    assert res["valido"] is False or res["codigo_error"] in ("FUERA_DEL_WORKSPACE", "RUTA_INVALIDA")


# 50. Operaciones verdaderamente mutantes mantienen requiere_confirmacion = True.
@pytest.mark.parametrize("cmd", [
    "npm install express", "npm uninstall express", "npm update",
    "pip install pytest", "rm main.py", "mv a.js b.js", "cp a.js b.js",
    "chmod 755 app.js", "chown 1000:1000 app.js"
])
def test_mutating_commands_require_confirmation(sanitizer, cmd):
    res = sanitizer.validar_y_clasificar(cmd)
    assert res["valido"] is True
    assert res["requiere_confirmacion"] is True
    assert res["clasificacion"] == "MUTATING"




