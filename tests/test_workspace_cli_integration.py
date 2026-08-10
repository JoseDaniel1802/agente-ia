"""
Pruebas de Integración para el Cambio de Workspace en la CLI de Muss_Code.
Verifica que los cambios de workspace mediante /workspace ejecuten set_active_workspace(),
actualicen todas las capas (WorkspaceManager, CommandSanitizer, SandboxManager),
soporten rutas con espacios y comillas, manejen rechazos, rutas inválidas y excepciones.
"""

import os
import sys
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Añadir proyecto al path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import herramientas
from cli.comandos import procesar_comando_slash


class TestWorkspaceCLIIntegration(unittest.TestCase):
    """Suite de integración específica para verificar el flujo completo de cambio de workspace desde la CLI."""

    def setUp(self):
        self.stdout_backup = sys.stdout
        self.stdout_capture = io.StringIO()
        sys.stdout = self.stdout_capture

        self.original_workspace = str(herramientas.workspace_manager.workspace_root)
        self.temp_dir_base = tempfile.mkdtemp(prefix="muss_code_test_ws_")
        self.target_dir_clean = str(Path(os.path.join(self.temp_dir_base, "Pruebas")).resolve())
        self.target_dir_espacios = str(Path(os.path.join(self.temp_dir_base, "Sexto Semestre", "Programacion Web", "Pruebas")).resolve())

        os.makedirs(self.target_dir_clean, exist_ok=True)
        os.makedirs(self.target_dir_espacios, exist_ok=True)

        # Crear archivo distinguible en el nuevo workspace de prueba
        with open(os.path.join(self.target_dir_clean, "archivo_nuevo.txt"), "w", encoding="utf-8") as f:
            f.write("contenido_de_prueba")

    def tearDown(self):
        sys.stdout = self.stdout_backup
        herramientas.set_active_workspace(self.original_workspace)
        if os.path.exists(self.temp_dir_base):
            shutil.rmtree(self.temp_dir_base, ignore_errors=True)

    def get_output(self) -> str:
        return self.stdout_capture.getvalue()

    # 1. /workspace <ruta> válida + confirmación 'sí' -> set_active_workspace() realmente se ejecuta
    @patch("questionary.confirm")
    def test_1_workspace_valido_confirmacion_si_ejecuta_set_active_workspace(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True

        res = procesar_comando_slash(f"/workspace {self.target_dir_clean}", None)
        self.assertTrue(res)

        out = self.get_output()
        self.assertIn("Workspace configurado exitosamente", out)
        self.assertIn(self.target_dir_clean, out.replace("\n", ""))

    # 2. Después del cambio: herramientas.workspace_manager.workspace_root debe ser exactamente la nueva ruta
    @patch("questionary.confirm")
    def test_2_workspace_manager_root_actualizado(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True

        procesar_comando_slash(f"/workspace {self.target_dir_clean}", None)
        actual_ws = str(herramientas.workspace_manager.workspace_root)
        self.assertEqual(actual_ws, str(Path(self.target_dir_clean).resolve()))

    # 3. Después del cambio: herramientas.command_sanitizer.workspace_root debe ser la nueva ruta
    @patch("questionary.confirm")
    def test_3_command_sanitizer_root_actualizado(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True

        procesar_comando_slash(f"/workspace {self.target_dir_clean}", None)
        sanitizer_ws = str(herramientas.command_sanitizer.workspace_root)
        sanitizer_wm_ws = str(herramientas.command_sanitizer.workspace_manager.workspace_root)
        self.assertEqual(sanitizer_ws, str(Path(self.target_dir_clean).resolve()))
        self.assertEqual(sanitizer_wm_ws, str(Path(self.target_dir_clean).resolve()))

    # 4. Después del cambio: herramientas.sandbox_manager.workspace_root debe ser la nueva ruta
    @patch("questionary.confirm")
    def test_4_sandbox_manager_root_actualizado(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True

        procesar_comando_slash(f"/workspace {self.target_dir_clean}", None)
        sandbox_ws = str(herramientas.sandbox_manager.workspace_root)
        self.assertEqual(sandbox_ws, str(Path(self.target_dir_clean).resolve()))

    # 5. La ruta puede contener espacios y comillas
    @patch("questionary.confirm")
    def test_5_ruta_con_espacios_y_comillas(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True

        # Invocación con comillas alrededor de la ruta con espacios
        cmd_con_comillas = f'/workspace "{self.target_dir_espacios}"'
        res = procesar_comando_slash(cmd_con_comillas, None)
        self.assertTrue(res)

        actual_ws = str(herramientas.workspace_manager.workspace_root)
        self.assertEqual(actual_ws, str(Path(self.target_dir_espacios).resolve()))

    # 6. Usuario responde 'no' -> workspace permanece sin cambios
    @patch("questionary.confirm")
    def test_6_usuario_responde_no_mantiene_workspace(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = False

        res = procesar_comando_slash(f"/workspace {self.target_dir_clean}", None)
        self.assertTrue(res)

        actual_ws = str(herramientas.workspace_manager.workspace_root)
        self.assertEqual(actual_ws, self.original_workspace)
        out = self.get_output()
        self.assertIn("DENEGADO", out)

    # 7. Ruta inválida -> workspace permanece sin cambios
    def test_7_ruta_invalida_mantiene_workspace(self):
        ruta_inexistente = os.path.join(self.temp_dir_base, "CarpetaFantasmaQueNoExiste")

        res = procesar_comando_slash(f"/workspace {ruta_inexistente}", None)
        self.assertTrue(res)

        actual_ws = str(herramientas.workspace_manager.workspace_root)
        self.assertEqual(actual_ws, self.original_workspace)
        out = self.get_output()
        self.assertIn("Error", out)
        self.assertIn("No se puede cambiar", out)

    # 8. Simular una excepción durante set_active_workspace() -> la CLI no debe afirmar que el cambio fue exitoso
    @patch("questionary.confirm")
    @patch("herramientas.set_active_workspace", side_effect=RuntimeError("Error simulado en disco"))
    def test_8_excepcion_en_set_active_workspace_no_afirma_exito(self, mock_set_ws, mock_confirm):
        mock_confirm.return_value.ask.return_value = True

        res = procesar_comando_slash(f"/workspace {self.target_dir_clean}", None)
        self.assertTrue(res)

        out = self.get_output()
        self.assertNotIn("Workspace configurado exitosamente", out)
        self.assertIn("Error inesperado durante el cambio de workspace", out)
        self.assertIn("Error simulado en disco", out)

    # 9. Verificar que Docker recibiría el workspace nuevo: Pruebas:/workspace:rw y NO Agente:/workspace:rw
    @patch("questionary.confirm")
    def test_9_docker_recibe_nuevo_workspace(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True

        procesar_comando_slash(f"/workspace {self.target_dir_clean}", None)

        docker_cmd = herramientas.sandbox_manager._build_docker_command(
            tokens=["ls"],
            env={}
        )

        volume_arg = None
        for i, token in enumerate(docker_cmd):
            if token == "-v" and i + 1 < len(docker_cmd):
                volume_arg = docker_cmd[i + 1]
                break

        self.assertIsNotNone(volume_arg)
        esperado_target = str(Path(self.target_dir_clean).resolve())
        self.assertTrue(volume_arg.startswith(f"{esperado_target}:/workspace"))
        self.assertNotIn(self.original_workspace, volume_arg)

    # 10. Verificar que después del cambio: listar_directorio(".") utiliza el nuevo workspace
    @patch("questionary.confirm")
    def test_10_listar_directorio_usa_nuevo_workspace(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True

        procesar_comando_slash(f"/workspace {self.target_dir_clean}", None)

        resultado = herramientas.listar_directorio(".")
        self.assertFalse(resultado.get("error", True))
        nombres = [item["nombre"] for item in resultado.get("elementos", [])]
        self.assertIn("archivo_nuevo.txt", nombres)


if __name__ == "__main__":
    unittest.main()
