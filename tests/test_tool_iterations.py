"""Pruebas del presupuesto de rondas de herramientas de ChatSession."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import agente
from agente import ChatSession


def _tool_response(call_id: str, texto: str) -> MagicMock:
    """Crea una respuesta simulada que llama analizar_requisitos."""
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.type = "function"
    tool_call.function.name = "analizar_requisitos"
    tool_call.function.arguments = f'{{"texto": "{texto}"}}'
    tool_call.model_dump.return_value = {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "analizar_requisitos",
            "arguments": tool_call.function.arguments,
        },
    }
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.role = "assistant"
    response.choices[0].message.content = None
    response.choices[0].message.tool_calls = [tool_call]
    return response


def _final_response(content: str) -> MagicMock:
    """Crea una respuesta simulada sin llamadas de herramientas."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.role = "assistant"
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    return response


def _named_tool_response(call_id: str, name: str, arguments: str) -> MagicMock:
    """Crea una respuesta simulada para cualquier herramienta registrada."""
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.type = "function"
    tool_call.function.name = name
    tool_call.function.arguments = arguments
    tool_call.model_dump.return_value = {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.role = "assistant"
    response.choices[0].message.content = None
    response.choices[0].message.tool_calls = [tool_call]
    return response


class TestToolIterations(unittest.TestCase):
    """Verifica que las tareas largas no se corten por el límite histórico de 12."""

    def test_default_budget_is_higher_than_historical_limit(self):
        self.assertGreater(agente.DEFAULT_MAX_TOOL_ITERATIONS, 12)
        self.assertEqual(ChatSession().max_tool_iterations, agente.DEFAULT_MAX_TOOL_ITERATIONS)

    @patch("agente.time.sleep")
    @patch("agente.client.chat.completions.create")
    def test_valid_sequence_over_twelve_rounds_completes(self, mock_create, _mock_sleep):
        responses = [_tool_response(f"call_{number}", f"requisito {number}") for number in range(13)]
        responses.append(_final_response("Tarea finalizada tras 13 rondas."))
        mock_create.side_effect = responses

        answer = ChatSession(max_tool_iterations=40).enviar("Procesa todos los requisitos")

        self.assertEqual(answer, "Tarea finalizada tras 13 rondas.")
        self.assertEqual(mock_create.call_count, 14)

    @patch("agente.time.sleep")
    @patch("agente.client.chat.completions.create")
    def test_repeated_identical_calls_are_stopped(self, mock_create, _mock_sleep):
        mock_create.side_effect = [_tool_response(f"call_{number}", "mismo requisito") for number in range(4)]

        answer = ChatSession(max_tool_iterations=40).enviar("Procesa el requisito")

        self.assertIn("posible bucle", answer)
        self.assertEqual(mock_create.call_count, 4)

    @patch("agente.time.sleep")
    @patch("agente.client.chat.completions.create")
    def test_writing_files_allowed_without_preflight(self, mock_create, _mock_sleep):
        writer = MagicMock(return_value={"error": False})
        mock_create.side_effect = [
            _named_tool_response("write", "escribir_archivo", '{"ruta": "package.json", "contenido": "{}"}'),
            _final_response("Escritura completada."),
        ]

        with patch.dict(agente.funciones_disponibles, {"escribir_archivo": writer}):
            answer = ChatSession().enviar("Crea una aplicación Node.js")

        self.assertEqual(answer, "Escritura completada.")
        writer.assert_called_once()

    @patch("agente.time.sleep")
    @patch("agente.client.chat.completions.create")
    def test_unavailable_runtime_blocks_execution(self, mock_create, _mock_sleep):
        def unavailable_command(comando, timeout_sec=15):
            return {"error": True, "codigo_salida": 127, "stderr": "not found"}

        mock_create.side_effect = [
            _named_tool_response("node", "ejecutar_comando_bash", '{"comando": "node --version"}'),
            _named_tool_response("run", "ejecutar_comando_bash", '{"comando": "node app.js"}'),
            _final_response("Node no está disponible para ejecución."),
        ]

        with patch.dict(agente.funciones_disponibles, {
            "ejecutar_comando_bash": unavailable_command,
        }):
            answer = ChatSession().enviar("Ejecuta app.js")

        self.assertEqual(answer, "Node no está disponible para ejecución.")

    def test_preflight_for_execution_blocks_unavailable_runtime(self):
        session = ChatSession()
        session.runtime_status["node"] = False

        blocked = session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "node app.js"})
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["codigo_error"], "RUNTIME_NO_DISPONIBLE")

    def test_preflight_for_write_always_returns_none(self):
        session = ChatSession()
        for route in ("app.js", "app.py", "Main.java", "main.go", "package.json"):
            result = session._preflight_error_for_write("escribir_archivo", {"ruta": route})
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
