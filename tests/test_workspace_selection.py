"""
Pruebas Unitarias e Integración para la Selección Segura de Workspace en Muss_Code.
Verifica la validación de los 7 criterios de seguridad, cambio de workspace en la CLI,
actualización de SandboxManager/CommandSanitizer, preservación de fail-closed e instrucciones del agente.
"""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

# Añadir proyecto al path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import herramientas
from herramientas import (
    workspace_manager,
    command_sanitizer,
    sandbox_manager,
    set_active_workspace,
    leer_archivo,
    escribir_archivo,
    ejecutar_comando_bash,
)
from seguridad import WorkspaceManager, CommandSanitizer
from sandbox import SandboxManager
from instrucciones import instrucciones_agente


class TestWorkspaceSelection(unittest.TestCase):
    """Suite de pruebas para la selección y validación estricta de workspace."""

    def setUp(self):
        self.original_workspace = str(workspace_manager.workspace_root)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="muss_code_ws_test_")).resolve()

    def tearDown(self):
        set_active_workspace(self.original_workspace)
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. Validación de workspace válido
    def test_validar_nuevo_workspace_valido(self):
        wm = WorkspaceManager()
        res = wm.validar_nuevo_workspace_root(self.temp_dir)
        self.assertTrue(res["valida"])
        self.assertFalse(res["error"])
        self.assertEqual(res["ruta_absoluta"], str(self.temp_dir))

    # 2. Validación de ruta no existente
    def test_validar_nuevo_workspace_no_existente(self):
        wm = WorkspaceManager()
        ruta_fake = self.temp_dir / "carpeta_no_existente_12345"
        res = wm.validar_nuevo_workspace_root(ruta_fake)
        self.assertFalse(res["valida"])
        self.assertEqual(res["codigo_error"], "RUTA_NO_EXISTE")

    # 3. Validación de archivo en lugar de directorio
    def test_validar_nuevo_workspace_es_archivo(self):
        wm = WorkspaceManager()
        archivo_test = self.temp_dir / "archivo.txt"
        archivo_test.write_text("test", encoding="utf-8")

        res = wm.validar_nuevo_workspace_root(archivo_test)
        self.assertFalse(res["valida"])
        self.assertEqual(res["codigo_error"], "NO_ES_DIRECTORIO")

    # 4. Bloqueo de raíz del sistema y /etc
    def test_validar_nuevo_workspace_directorio_sistema(self):
        wm = WorkspaceManager()
        res_root = wm.validar_nuevo_workspace_root("/")
        self.assertFalse(res_root["valida"])
        self.assertEqual(res_root["codigo_error"], "DIRECTORIO_SISTEMA_PROHIBIDO")

        res_etc = wm.validar_nuevo_workspace_root("/etc")
        self.assertFalse(res_etc["valida"])
        self.assertEqual(res_etc["codigo_error"], "DIRECTORIO_SISTEMA_PROHIBIDO")

    # 5. Bloqueo de HOME directo
    def test_validar_nuevo_workspace_home_directo(self):
        wm = WorkspaceManager()
        res_home = wm.validar_nuevo_workspace_root(Path.home())
        self.assertFalse(res_home["valida"])
        self.assertEqual(res_home["codigo_error"], "DIRECTORIO_SISTEMA_PROHIBIDO")

    # 6. Bloqueo de carpetas denylist (.git, .venv)
    def test_validar_nuevo_workspace_denylist(self):
        wm = WorkspaceManager()
        git_dir = self.temp_dir / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)

        res_git = wm.validar_nuevo_workspace_root(git_dir)
        self.assertFalse(res_git["valida"])
        self.assertEqual(res_git["codigo_error"], "DIRECTORIO_PROTEGIDO")

    # 7. Comprobación de Symlink inválido
    def test_validar_nuevo_workspace_symlink_invalid(self):
        wm = WorkspaceManager()
        symlink_path = self.temp_dir / "sym_invalid"
        target_invalid = self.temp_dir / "no_existe_target"
        try:
            os.symlink(target_invalid, symlink_path)
            res = wm.validar_nuevo_workspace_root(symlink_path)
            self.assertFalse(res["valida"])
            self.assertEqual(res["codigo_error"], "SYMLINK_INVALIDO")
        except OSError:
            pass  # En entornos restringidos de OS se omite la creación del symlink

    # 8. Cambio exitoso de workspace activo
    def test_set_active_workspace_exitoso(self):
        res = set_active_workspace(self.temp_dir)
        self.assertTrue(res["valida"])
        self.assertEqual(str(herramientas.workspace_manager.workspace_root), str(self.temp_dir))
        self.assertEqual(str(herramientas.sandbox_manager.workspace_root), str(self.temp_dir))
        self.assertEqual(str(herramientas.command_sanitizer.workspace_root), str(self.temp_dir))

        # Escribir archivo en el nuevo workspace
        res_write = escribir_archivo("test_nuevo_ws.txt", "contenido")
        self.assertFalse(res_write.get("error", False))
        self.assertTrue((self.temp_dir / "test_nuevo_ws.txt").exists())

    # 9. Cambio fallido a workspace inválido no altera el activo
    def test_set_active_workspace_fallido_mantiene_activo(self):
        ws_antes = str(herramientas.workspace_manager.workspace_root)
        res = set_active_workspace("/etc")
        self.assertFalse(res["valida"])
        self.assertEqual(str(herramientas.workspace_manager.workspace_root), ws_antes)

    # 10. Verificación del montaje Docker en el nuevo workspace
    def test_docker_command_mount_nuevo_workspace(self):
        set_active_workspace(self.temp_dir)
        sb_mgr = herramientas.sandbox_manager
        cmd_docker = sb_mgr._build_docker_command(["python3", "--version"], {})
        cmd_str = " ".join(cmd_docker)

        self.assertIn(f"-v {self.temp_dir}:/workspace:rw", cmd_str)
        self.assertIn("--network none", cmd_str)
        self.assertIn("--cap-drop ALL", cmd_str)
        self.assertIn("--security-opt no-new-privileges", cmd_str)
        self.assertIn("--read-only", cmd_str)

    # 11. Preservación del Fail-Closed cuando Docker no está activo
    def test_fail_closed_preservado(self):
        set_active_workspace(self.temp_dir)
        sb_mgr = herramientas.sandbox_manager
        sb_mgr._docker_available = False

        res = sb_mgr.execute(["ls"])
        self.assertTrue(res["error"])
        self.assertEqual(res["codigo_error"], "SANDBOX_NO_DISPONIBLE")

    # 12. Verificación de instrucciones del agente sobre el acceso a archivos
    def test_instrucciones_agente_actualizadas(self):
        self.assertIn("Posees herramientas de sistema de archivos", instrucciones_agente)
        self.assertIn("NUNCA afirmes que no tienes acceso al disco", instrucciones_agente)
        self.assertIn("/workspace /ruta/al/proyecto", instrucciones_agente)


if __name__ == "__main__":
    unittest.main()
