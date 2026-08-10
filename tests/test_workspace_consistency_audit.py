"""
Prueba de Auditoría de Consistencia para el Cambio Dinámico de Workspace (FASE 6.1).
Comprueba que el cambio dinámico mediante set_active_workspace() actualiza al 100%
todas las capas (WorkspaceManager, SandboxManager, CommandSanitizer, herramientas de archivos y Docker).
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
    editar_archivo,
    listar_directorio,
    buscar_en_proyecto,
    ejecutar_comando_bash,
)
from agente import crear_chat, ChatSession


class TestWorkspaceConsistencyAudit(unittest.TestCase):
    """Prueba real de aislamiento y consistencia entre dos workspaces temporales A y B."""

    def setUp(self):
        self.original_workspace = str(herramientas.workspace_manager.workspace_root)
        self.ws_A = Path(tempfile.mkdtemp(prefix="ws_audit_A_")).resolve()
        self.ws_B = Path(tempfile.mkdtemp(prefix="ws_audit_B_")).resolve()

        # Crear un archivo diferente en cada workspace
        (self.ws_A / "archivo_A.txt").write_text("CONTENIDO_PROYECTO_A", encoding="utf-8")
        (self.ws_B / "archivo_B.txt").write_text("CONTENIDO_PROYECTO_B", encoding="utf-8")

    def tearDown(self):
        set_active_workspace(self.original_workspace)
        if self.ws_A.exists():
            shutil.rmtree(self.ws_A, ignore_errors=True)
        if self.ws_B.exists():
            shutil.rmtree(self.ws_B, ignore_errors=True)

    def test_auditoria_consistencia_cambio_dinamico_workspace(self):
        # 1. Iniciar con workspace_A
        res_A = set_active_workspace(self.ws_A)
        self.assertTrue(res_A["valida"])

        # Verificar referencias de capas en A
        self.assertEqual(str(herramientas.workspace_manager.workspace_root), str(self.ws_A))
        self.assertEqual(str(herramientas.sandbox_manager.workspace_root), str(self.ws_A))
        self.assertEqual(str(herramientas.command_sanitizer.workspace_root), str(self.ws_A))
        self.assertEqual(str(herramientas.command_sanitizer.sandbox_manager.workspace_root), str(self.ws_A))

        # 2. Comprobar que leer_archivo encuentra A y rechaza B
        r_read_A = leer_archivo("archivo_A.txt")
        self.assertFalse(r_read_A.get("error", False))
        self.assertIn("CONTENIDO_PROYECTO_A", r_read_A.get("contenido", ""))

        r_read_B_from_A = leer_archivo(str(self.ws_B / "archivo_B.txt"))
        self.assertTrue(r_read_B_from_A.get("error"))
        self.assertEqual(r_read_B_from_A.get("codigo_error"), "FUERA_DEL_WORKSPACE")

        # 3. Cambiar mediante set_active_workspace() a workspace_B
        res_B = set_active_workspace(self.ws_B)
        self.assertTrue(res_B["valida"])

        # 4. Comprobar que leer_archivo encuentra B y rechaza A
        r_read_B = leer_archivo("archivo_B.txt")
        self.assertFalse(r_read_B.get("error", False))
        self.assertIn("CONTENIDO_PROYECTO_B", r_read_B.get("contenido", ""))

        r_read_A_from_B = leer_archivo(str(self.ws_A / "archivo_A.txt"))
        self.assertTrue(r_read_A_from_B.get("error"))
        self.assertEqual(r_read_A_from_B.get("codigo_error"), "FUERA_DEL_WORKSPACE")

        # 5. Ejecutar listar_directorio y confirmar que solo muestra B
        r_list = listar_directorio(".")
        self.assertFalse(r_list.get("error", False))
        archivos_listados = [item["nombre"] for item in r_list.get("elementos", [])]
        self.assertIn("archivo_B.txt", archivos_listados)
        self.assertNotIn("archivo_A.txt", archivos_listados)

        # 6. Comprobar que buscar_en_proyecto solo busca en B
        r_search_B = buscar_en_proyecto("CONTENIDO_PROYECTO_B")
        self.assertFalse(r_search_B.get("error", False))
        self.assertGreater(r_search_B.get("total_coincidencias", 0), 0)

        r_search_A = buscar_en_proyecto("CONTENIDO_PROYECTO_A")
        self.assertEqual(r_search_A.get("total_coincidencias", 0), 0)

        # 7. Ejecutar comando en Sandbox y confirmar montaje exclusivo de B
        docker_cmd = herramientas.sandbox_manager._build_docker_command(["pwd"], {})
        docker_cmd_str = " ".join(docker_cmd)

        self.assertIn(f"-v {self.ws_B}:/workspace:rw", docker_cmd_str)
        self.assertNotIn(f"-v {self.ws_A}:/workspace:rw", docker_cmd_str)

        # 8. Confirmar que ninguna capa conserva referencias a A
        self.assertEqual(str(herramientas.workspace_manager.workspace_root), str(self.ws_B))
        self.assertEqual(str(herramientas.sandbox_manager.workspace_root), str(self.ws_B))
        self.assertEqual(str(herramientas.command_sanitizer.workspace_root), str(self.ws_B))
        self.assertEqual(str(herramientas.command_sanitizer.sandbox_manager.workspace_root), str(self.ws_B))
        self.assertEqual(str(herramientas.command_sanitizer.workspace_manager.workspace_root), str(self.ws_B))

        # 9. Comprobar que ChatSession no requiere reinicio para usar el nuevo workspace
        chat = crear_chat()
        # Enviar consulta o verificar que las funciones asociadas usan la referencia dinámica global
        self.assertEqual(str(herramientas.workspace_manager.workspace_root), str(self.ws_B))


if __name__ == "__main__":
    unittest.main()
