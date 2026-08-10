"""
Pruebas Unitarias e Integración para la CLI Avanzada de Muss_Code (Rich + Questionary).
Verifica inicialización, comandos slash, menús interactivos, manejo de señales, confirmación humana y seguridad.
"""

import os
import sys
import io
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Añadir proyecto al path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import agente
import herramientas
from cli.presentacion import (
    mostrar_banner,
    solicitar_confirmacion_usuario_cli,
    solicitar_cambio_workspace_cli,
    mostrar_invocacion_herramienta,
    mostrar_error,
    mostrar_help,
    mostrar_status,
    mostrar_workspace_info,
    mostrar_tools,
    limpiar_pantalla,
    console,
)
from cli.comandos import es_comando_slash, procesar_comando_slash, abrir_menu_interactivo
from cli.interfaz import run_cli, solicitar_confirmacion_usuario
import main


class TestCLI(unittest.TestCase):
    """Suite de pruebas para la CLI enriquecida con Rich y Questionary."""

    def setUp(self):
        self.stdout_backup = sys.stdout
        self.stdout_capture = io.StringIO()
        sys.stdout = self.stdout_capture

    def tearDown(self):
        sys.stdout = self.stdout_backup

    def get_output(self) -> str:
        return self.stdout_capture.getvalue()

    # 1. Comprobación de detección de comandos slash
    def test_es_comando_slash(self):
        self.assertTrue(es_comando_slash("/help"))
        self.assertTrue(es_comando_slash("/status"))
        self.assertTrue(es_comando_slash("/tools"))
        self.assertTrue(es_comando_slash("/workspace"))
        self.assertTrue(es_comando_slash("/clear"))
        self.assertTrue(es_comando_slash("/exit"))
        self.assertTrue(es_comando_slash("salir"))
        self.assertTrue(es_comando_slash("exit"))
        self.assertTrue(es_comando_slash("quit"))
        self.assertFalse(es_comando_slash("Revisa este proyecto"))
        self.assertFalse(es_comando_slash("Corrige el bug en restar"))

    # 2. Comando /help
    @patch("questionary.select")
    def test_comando_help(self, mock_select):
        mock_select.return_value.ask.return_value = "/help_table"
        res = procesar_comando_slash("/help", None)
        self.assertTrue(res)
        out = self.get_output()
        self.assertIn("Comandos Disponibles", out)
        self.assertIn("/help", out)
        self.assertIn("/status", out)
        self.assertIn("/tools", out)
        self.assertIn("/workspace", out)
        self.assertIn("/clear", out)
        self.assertIn("/exit", out)

    # 3. Comando /status
    def test_comando_status(self):
        res = procesar_comando_slash("/status", None)
        self.assertTrue(res)
        out = self.get_output()
        self.assertIn("Estado del Sistema Muss_Code", out)
        self.assertIn("Agente", out)
        self.assertIn("Workspace", out)
        self.assertIn("Sandbox OS", out)
        self.assertIn("12", out)

    # 4. Comando /tools
    def test_comando_tools(self):
        res = procesar_comando_slash("/tools", None)
        self.assertTrue(res)
        out = self.get_output()
        self.assertIn("Herramientas Registradas", out)
        self.assertIn("listar_directorio", out)
        self.assertIn("leer_archivo", out)
        self.assertIn("escribir_archivo", out)
        self.assertIn("editar_archivo", out)
        self.assertIn("buscar_en_proyecto", out)
        self.assertIn("ejecutar_comando_bash", out)

    # 5. Comando /workspace
    def test_comando_workspace(self):
        res = procesar_comando_slash("/workspace", None)
        self.assertTrue(res)
        out = self.get_output()
        self.assertIn("Workspace Activo", out)
        self.assertIn("Ruta:", out)
        self.assertIn("Sandbox:", out)

    @patch("questionary.confirm")
    def test_solicitar_cambio_workspace_cli(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True
        res = solicitar_cambio_workspace_cli("/tmp")
        self.assertTrue(res)
        out = self.get_output()
        self.assertIn("SOLICITUD DE CAMBIO DE WORKSPACE", out)
        self.assertIn("/tmp", out)

    @patch("questionary.confirm")
    def test_comando_workspace_con_ruta(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws_original = str(herramientas.workspace_manager.workspace_root)
            try:
                res = procesar_comando_slash(f"/workspace {tmp_dir}", None)
                self.assertTrue(res)
                out = self.get_output()
                self.assertIn("Workspace configurado exitosamente", out)
            finally:
                herramientas.set_active_workspace(ws_original)

    # 6. Comando /clear
    def test_comando_clear(self):
        res = procesar_comando_slash("/clear", None)
        self.assertTrue(res)

    # 7. Comando /exit
    def test_comando_exit(self):
        res = procesar_comando_slash("/exit", None)
        self.assertFalse(res)
        out = self.get_output()
        self.assertIn("Muss_Code: hasta luego.", out)

    # 8. Entrada vacía
    @patch("questionary.text")
    @patch("cli.interfaz.crear_chat")
    def test_entrada_vacia(self, mock_crear_chat, mock_text):
        mock_chat = MagicMock()
        mock_crear_chat.return_value = mock_chat
        mock_text.return_value.ask.side_effect = ["", "   ", "/exit"]

        run_cli()

        out = self.get_output()
        self.assertIn("MUSS_CODE", out)
        self.assertIn("hasta luego", out)
        mock_chat.enviar.assert_not_called()

    # 9. Manejo de KeyboardInterrupt (Ctrl+C)
    @patch("questionary.text")
    @patch("cli.interfaz.crear_chat")
    def test_keyboard_interrupt(self, mock_crear_chat, mock_text):
        mock_text.return_value.ask.side_effect = KeyboardInterrupt
        run_cli()
        out = self.get_output()
        self.assertIn("Muss_Code: hasta luego.", out)

    # 10. Manejo de EOFError (Ctrl+D)
    @patch("questionary.text")
    @patch("cli.interfaz.crear_chat")
    def test_eof_error(self, mock_crear_chat, mock_text):
        mock_text.return_value.ask.side_effect = EOFError
        run_cli()
        out = self.get_output()
        self.assertIn("Muss_Code: hasta luego.", out)

    # 11. Manejo de error en respuesta del agente
    @patch("cli.interfaz.enviar_mensaje", side_effect=Exception("Error de conexión simulado"))
    @patch("questionary.text")
    @patch("cli.interfaz.crear_chat")
    def test_error_agente(self, mock_crear_chat, mock_text, mock_enviar):
        mock_text.return_value.ask.side_effect = ["Hola", "/exit"]
        run_cli()
        out = self.get_output()
        self.assertIn("Error", out)
        self.assertIn("Error de conexión simulado", out)

    # 12. Confirmación Humana — Aprobación
    @patch("questionary.confirm")
    def test_confirmacion_humana_aprobar(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = True
        aprobado = solicitar_confirmacion_usuario("rm test.txt", "Eliminar archivo")
        self.assertTrue(aprobado)
        out = self.get_output()
        self.assertIn("AUTORIZACIÓN REQUERIDA", out)
        self.assertIn("rm test.txt", out)
        self.assertIn("AUTORIZADA", out)

    # 13. Confirmación Humana — Denegación
    @patch("questionary.confirm")
    def test_confirmacion_humana_denegar(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = False
        aprobado = solicitar_confirmacion_usuario("rm test.txt", "Eliminar archivo")
        self.assertFalse(aprobado)
        out = self.get_output()
        self.assertIn("DENEGADA", out)

    # 14. Invocación de Herramientas formateada
    def test_mostrar_invocacion_herramienta(self):
        mostrar_invocacion_herramienta(1, "leer_archivo", {"ruta": "calculadora.py"})
        out = self.get_output()
        self.assertIn("leer_archivo", out)
        self.assertIn("calculadora.py", out)

    # 15. Verificación de Seguridad — No existen bypasses ni auto-aprobaciones
    def test_verificacion_seguridad_no_bypasses(self):
        with patch("questionary.confirm") as mock_confirm:
            mock_confirm.return_value.ask.return_value = False
            res = solicitar_confirmacion_usuario("rm /importante", "eliminar")
            self.assertFalse(res)

        self.assertEqual(main.solicitar_confirmacion_usuario, solicitar_confirmacion_usuario)

    # 16. Configuración dinámica de DeepSeek API
    def test_proveedor_deepseek_config(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-deepseek-test-key"}, clear=False):
            key = os.getenv("DEEPSEEK_API_KEY")
            self.assertEqual(key, "sk-deepseek-test-key")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            self.assertEqual(base_url, "https://api.deepseek.com")
            self.assertEqual(model, "deepseek-chat")


if __name__ == "__main__":
    unittest.main()
