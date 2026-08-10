"""
Suite de Pruebas Unitarias e Integración para Agent Loop / Task Execution Engine.
Cubre las 13 condiciones y escenarios del ciclo de vida de tareas en Muss_Code.
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Añadir proyecto al path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import agente
from agente import ChatSession, TaskExecutionState, TaskChangeState


class TestAgentLoop(unittest.TestCase):
    """Pruebas del ciclo autónomo de ejecución de tareas (Agent Loop)."""

    def setUp(self):
        self.session = ChatSession()
        self.mock_client_patcher = patch("agente.client.chat.completions.create")
        self.mock_create = self.mock_client_patcher.start()

        # Mock predeterminado: respuesta simple sin tool calls
        mock_msg = MagicMock()
        mock_msg.role = "assistant"
        mock_msg.content = "Tarea procesada."
        mock_msg.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]

        self.mock_create.return_value = mock_resp

    def tearDown(self):
        self.mock_client_patcher.stop()

    # 1. Tarea exitosa
    def test_1_tarea_exitosa(self):
        self.session.enviar("Construye una solución simple")
        self.assertIn(self.session.current_task.status, ("ACTIVE", "COMPLETED"))

    # 2. Inspección -> Implementación -> Verificación
    def test_2_inspeccion_implementacion_verificacion(self):
        self.session.enviar("Construye un módulo y asegúrate de que funcione")
        self.session.current_task.status = "ACTIVE"
        self.assertTrue(self.session.current_task.verification_required)

        # Transición a Inspección
        self.session._update_task_execution_state("leer_archivo", {"ruta": "main.py"}, {"error": False})
        self.assertEqual(self.session.current_task.phase, "INSPECTION")

        # Transición a Implementación
        self.session._update_task_execution_state("escribir_archivo", {"ruta": "main.py"}, {"error": False})
        self.assertEqual(self.session.current_task.phase, "IMPLEMENTATION")

        # Transición a Verificación
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "python3 -m unittest"}, {"error": False, "stdout": "OK"})
        self.assertEqual(self.session.current_task.phase, "VERIFICATION")
        self.assertEqual(self.session.current_task.verification_status, "PASSED")

    # 3. Fallo -> Reparación -> Éxito
    def test_3_fallo_reparacion_exito(self):
        self.session.enviar("Construye app y verifica que funcione")
        self.session.current_task.status = "ACTIVE"

        # Primer intento de verificación falla
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "python3 main.py"}, {"error": True, "stderr": "SyntaxError"})
        self.assertEqual(self.session.current_task.repair_attempts, 1)
        self.assertEqual(self.session.current_task.phase, "REPAIR")
        self.assertEqual(self.session.current_task.verification_status, "FAILED")

        # Intento de edición pasa a REPAIR
        self.session._update_task_execution_state("editar_archivo", {"ruta": "main.py"}, {"error": False})
        self.assertEqual(self.session.current_task.phase, "REPAIR")

        # Re-verificación exitosa
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "python3 main.py"}, {"error": False, "stdout": "Success"})
        self.assertEqual(self.session.current_task.verification_status, "PASSED")

    # 4. Tres reparaciones fallidas -> Detención
    def test_4_tres_reparaciones_fallidas_detencion(self):
        self.session.enviar("Construye app y asegúrate de que funcione")
        self.session.current_task.status = "ACTIVE"

        # Fallo 1
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, {"error": True, "stderr": "Error 1"})
        self.assertEqual(self.session.current_task.repair_attempts, 1)
        self.assertEqual(self.session.current_task.status, "ACTIVE")

        # Fallo 2
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, {"error": True, "stderr": "Error 2"})
        self.assertEqual(self.session.current_task.repair_attempts, 2)
        self.assertEqual(self.session.current_task.status, "ACTIVE")

        # Fallo 3
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, {"error": True, "stderr": "Error 3"})
        self.assertEqual(self.session.current_task.repair_attempts, 3)
        self.assertEqual(self.session.current_task.status, "FAILED")

    # 5. Límite de iteraciones
    def test_5_limite_15_iteraciones(self):
        session = ChatSession(max_tool_iterations=2)
        mock_tool_msg = MagicMock()
        mock_tool_msg.role = "assistant"
        mock_tool_msg.content = None
        tc = MagicMock()
        tc.id = "call_1"
        tc.type = "function"
        tc.function.name = "listar_directorio"
        tc.function.arguments = '{"ruta": "."}'
        tc.model_dump.return_value = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "listar_directorio", "arguments": '{"ruta": "."}'}
        }
        mock_tool_msg.tool_calls = [tc]

        mock_choice = MagicMock()
        mock_choice.message = mock_tool_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]

        self.mock_create.return_value = mock_resp

        res = session.enviar("Tarea larga")
        self.assertIn("alcanzó el límite de seguridad", res)

    # 6. Llamadas idénticas repetidas
    def test_6_llamadas_identicas_repetidas(self):
        session = ChatSession()
        mock_tool_msg = MagicMock()
        mock_tool_msg.role = "assistant"
        mock_tool_msg.content = None
        tc = MagicMock()
        tc.id = "call_1"
        tc.type = "function"
        tc.function.name = "leer_archivo"
        tc.function.arguments = '{"ruta": "app.py"}'
        tc.model_dump.return_value = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "leer_archivo", "arguments": '{"ruta": "app.py"}'}
        }
        mock_tool_msg.tool_calls = [tc]

        mock_choice = MagicMock()
        mock_choice.message = mock_tool_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]

        self.mock_create.return_value = mock_resp

        res = session.enviar("Lee app.py")
        self.assertIn("Se detuvo un posible bucle", res)
        self.assertEqual(session.current_task.status, "FAILED")

    # 7. Autorización humana denegada
    def test_7_autorizacion_humana_denegada(self):
        self.session.enviar("Ejecuta comando peligroso")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "rm -rf ."}, {"codigo_error": "PERMISO_DENEGADO_POR_USUARIO"})
        self.assertEqual(self.session.current_task.status, "CANCELLED")

    # 8. Runtime inexistente
    def test_8_runtime_inexistente(self):
        self.session.enviar("Ejecuta comando en runtime ausente")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "node app.js"}, {"error": True, "codigo_error": "RUNTIME_NO_DISPONIBLE"})
        self.assertFalse(self.session.current_task.verification_possible)
        self.assertEqual(self.session.current_task.verification_status, "RUNTIMES_UNAVAILABLE")

    # 9. Tarea que no requiere ejecución
    def test_9_tarea_que_no_requiere_ejecucion(self):
        self.session.enviar("Refactoriza la documentación")
        self.assertFalse(self.session.current_task.verification_required)
        self.assertEqual(self.session.current_task.verification_status, "SKIPPED")

    # 10. Verificación requerida pero imposible
    def test_10_verificacion_requerida_pero_imposible(self):
        self.session.enviar("Construye app Node y asegúrate de que funcione")
        self.session.current_task.status = "ACTIVE"
        self.assertTrue(self.session.current_task.verification_required)
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "node app.js"}, {"error": True, "codigo_error": "RUNTIME_NO_DISPONIBLE"})
        self.assertEqual(self.session.current_task.verification_status, "RUNTIMES_UNAVAILABLE")

    # 11. Nueva tarea reinicia correctamente el estado
    def test_11_nueva_tarea_reinicia_estado(self):
        self.session.enviar("Construye tarea 1")
        self.session.task_changes.record_write("archivo1.txt", "creado", False, None, "hash1")
        self.assertEqual(len(self.session.task_changes.created_files), 1)

        # Nueva tarea explícita
        self.session.enviar("Construye tarea 2")
        self.assertEqual(len(self.session.task_changes.created_files), 0)
        self.assertEqual(self.session.current_task.goal, "Construye tarea 2")

    # 12. Continuación de tarea activa conserva estado
    def test_12_continuacion_tarea_activa_conserva_estado(self):
        self.session.enviar("Construye un módulo")
        self.session.current_task.status = "ACTIVE"
        self.session.current_task.repair_attempts = 1
        self.session.task_changes.record_write("mod.py", "creado", False, None, "hash1")

        # Mensaje de continuación
        self.session.enviar("corrige el error sintáctico de mod.py")
        self.assertEqual(self.session.current_task.repair_attempts, 1)
        self.assertEqual(len(self.session.task_changes.created_files), 1)

    # 13. TaskChangeState sigue registrando cambios
    def test_13_task_change_tracking_registra_cambios(self):
        self.session.enviar("Crea archivos de prueba")
        self.session.task_changes.record_write("test.py", "creado", False, None, "hash123")
        summary = self.session.task_changes.summary()
        self.assertIn("test.py", summary["created_files"])

    # 14. SHELL_INJECTION_RISK no incrementa repair_attempts
    def test_14_shell_injection_risk_no_incrementa_repair_attempts(self):
        self.session.enviar("Construye app")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "node app.js && echo OK"}, {"error": True, "codigo_error": "SHELL_INJECTION_RISK", "mensaje": "Sintaxis de shell no permitida"})
        self.assertEqual(self.session.current_task.repair_attempts, 0)

    # 15. COMANDO_PROHIBIDO no incrementa repair_attempts
    def test_15_comando_prohibido_no_incrementa_repair_attempts(self):
        self.session.enviar("Construye app")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "curl http://example.com"}, {"error": True, "codigo_error": "COMANDO_PROHIBIDO", "mensaje": "Comando prohibido"})
        self.assertEqual(self.session.current_task.repair_attempts, 0)

    # 16. TIPO_INVALIDO no incrementa repair_attempts
    def test_16_tipo_invalido_no_incrementa_repair_attempts(self):
        self.session.enviar("Construye app")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": 123}, {"error": True, "codigo_error": "TIPO_INVALIDO", "mensaje": "Tipo inválido"})
        self.assertEqual(self.session.current_task.repair_attempts, 0)

    # 17. COMANDO_VACIO no incrementa repair_attempts
    def test_17_comando_vacio_no_incrementa_repair_attempts(self):
        self.session.enviar("Construye app")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": ""}, {"error": True, "codigo_error": "COMANDO_VACIO", "mensaje": "Comando vacío"})
        self.assertEqual(self.session.current_task.repair_attempts, 0)

    # 18. El estado NO pasa a REPAIR ante bloqueos de seguridad de comando
    def test_18_no_pasa_a_repair_ante_bloqueos_seguridad(self):
        self.session.enviar("Construye app")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "python3 main.py; ls"}, {"error": True, "codigo_error": "SHELL_INJECTION_RISK", "mensaje": "Operadores no permitidos"})
        self.assertNotEqual(self.session.current_task.phase, "REPAIR")
        self.assertEqual(self.session.current_task.phase, "VERIFICATION")

    # 19. El mensaje del bloqueo queda disponible para el siguiente ciclo
    def test_19_mensaje_bloqueo_disponible_para_siguiente_ciclo(self):
        self.session.enviar("Construye app")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "python3 main.py && echo OK"}, {"error": True, "codigo_error": "SHELL_INJECTION_RISK", "mensaje": "Sintaxis de shell no permitida"})
        self.assertIn("Sintaxis de shell no permitida", self.session.current_task.last_verification_output)

    # 20. Un comando seguro posterior puede ejecutarse normalmente
    def test_20_comando_seguro_posterior_ejecuta_normalmente(self):
        self.session.enviar("Construye app y asegúrate de que funcione")
        self.session.current_task.status = "ACTIVE"
        # Rechazo inicial por operador encadenado
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "python3 main.py && echo OK"}, {"error": True, "codigo_error": "SHELL_INJECTION_RISK", "mensaje": "Bloqueado"})
        self.assertEqual(self.session.current_task.repair_attempts, 0)
        # Comando atómico seguro posterior
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "python3 main.py"}, {"error": False, "stdout": "OK"})
        self.assertEqual(self.session.current_task.verification_status, "PASSED")

    # 21. Un fallo real de pytest SÍ incrementa repair_attempts
    def test_21_fallo_real_pytest_incrementa_repair_attempts(self):
        self.session.enviar("Construye app y verifica que funcione")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, {"error": True, "stderr": "AssertionError"})
        self.assertEqual(self.session.current_task.repair_attempts, 1)
        self.assertEqual(self.session.current_task.phase, "REPAIR")

    # 22. Un fallo real de compilación SÍ puede entrar en REPAIR
    def test_22_fallo_real_compilacion_entra_en_repair(self):
        self.session.enviar("Construye app Go")
        self.session.current_task.status = "ACTIVE"
        self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "go test ./..."}, {"error": True, "stderr": "build error"})
        self.assertEqual(self.session.current_task.repair_attempts, 1)
        self.assertEqual(self.session.current_task.phase, "REPAIR")

    # 23. Tres fallos reales de reparación siguen deteniendo la tarea
    def test_23_tres_fallos_reales_detienen_tarea(self):
        self.session.enviar("Construye app")
        self.session.current_task.status = "ACTIVE"
        for i in range(3):
            self.session._update_task_execution_state("ejecutar_comando_bash", {"comando": "pytest"}, {"error": True, "stderr": f"Error {i}"})
        self.assertEqual(self.session.current_task.repair_attempts, 3)
        self.assertEqual(self.session.current_task.status, "FAILED")

    # 24. CommandSanitizer continúa bloqueando &&, ;, ||, |, >, >> y $()
    def test_24_command_sanitizer_bloquea_operadores_shell(self):
        sanitizer = agente.command_sanitizer
        for op in ["ls && cat", "ls ; cat", "ls || cat", "ls | cat", "echo a > b", "echo a >> b", "echo $(whoami)", "echo `whoami`"]:
            res = sanitizer.validar_y_clasificar(op)
            self.assertFalse(res["valido"])
            self.assertEqual(res["codigo_error"], "SHELL_INJECTION_RISK")

    # 25. No aparecen parámetros de bypass en las definiciones de herramientas
    def test_25_no_parametros_bypass_en_herramientas(self):
        prohibited_params = {"force", "bypass", "skip_preflight", "approve", "aprobar"}
        for tool in agente.tools:
            fn = tool.get("function", {})
            props = fn.get("parameters", {}).get("properties", {})
            for p in prohibited_params:
                self.assertNotIn(p, props, f"Parámetro prohibido '{p}' encontrado en herramienta '{fn.get('name')}'")


if __name__ == "__main__":
    unittest.main()
