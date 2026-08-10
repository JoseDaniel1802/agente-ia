"""
Pruebas Unitarias e Integración Anti-Alucinación para Muss_Code.
Verifica que las consultas de análisis/revisión de proyecto obliguen a ejecutar herramientas
de inspección (listar_directorio, leer_archivo) antes de emitir diagnósticos y que no
se inventen funciones Python (calculadora, etc.) en proyectos JavaScript/HTML/CSS.
"""

import os
import sys
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
from herramientas import set_active_workspace, workspace_manager
import agente
from agente import ChatSession, crear_chat, _solicitud_requiere_inspeccion
from instrucciones import instrucciones_agente


class TestAntiHallucination(unittest.TestCase):
    """Suite de pruebas para prevenir alucinaciones de código y forzar inspección basada en evidencia."""

    def setUp(self):
        self.original_workspace = str(workspace_manager.workspace_root)
        self.web_project_dir = Path(tempfile.mkdtemp(prefix="muss_code_web_project_")).resolve()

        # Crear estructura de un proyecto Web JavaScript/HTML/CSS (SIN Python)
        (self.web_project_dir / "index.html").write_text("<!DOCTYPE html><html><body><h1>Web Project</h1></body></html>", encoding="utf-8")
        (self.web_project_dir / "style.css").write_text("body { font-family: sans-serif; }", encoding="utf-8")
        (self.web_project_dir / "app.js").write_text("console.log('App initialized');", encoding="utf-8")
        (self.web_project_dir / "search.js").write_text("function searchItems(query) { return []; }", encoding="utf-8")
        (self.web_project_dir / "highlight.js").write_text("function highlightText(text) { return `<b>${text}</b>`; }", encoding="utf-8")
        (self.web_project_dir / "package.json").write_text('{"name": "web-project", "version": "1.0.0"}', encoding="utf-8")

        test_dir = self.web_project_dir / "test"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / "search.test.js").write_text("test('searchItems returns array', () => { expect(searchItems('')).toEqual([]); });", encoding="utf-8")
        (test_dir / "highlight.test.js").write_text("test('highlightText bolds text', () => { expect(highlightText('a')).toBe('<b>a</b>'); });", encoding="utf-8")

        set_active_workspace(self.web_project_dir)

    def tearDown(self):
        set_active_workspace(self.original_workspace)
        if self.web_project_dir.exists():
            shutil.rmtree(self.web_project_dir, ignore_errors=True)

    # 1. Verificar la regla de detección de solicitudes que requieren inspección
    def test_solicitud_requiere_inspeccion_keywords(self):
        self.assertTrue(_solicitud_requiere_inspeccion("revises este código y me digas si tiene algún error"))
        self.assertTrue(_solicitud_requiere_inspeccion("analiza este proyecto y dime si aplica SOLID, KISS y DRY"))
        self.assertTrue(_solicitud_requiere_inspeccion("busca errores en los archivos de la app"))
        self.assertFalse(_solicitud_requiere_inspeccion("Hola, ¿cómo estás?"))
        self.assertFalse(_solicitud_requiere_inspeccion("¿Cuál es tu mascota?"))

    # 2. Verificar que las reglas anti-alucinación están presentes en el system prompt
    def test_instrucciones_sistema_anti_alucinacion(self):
        self.assertIn("OBLIGACIÓN ESTRICTA DE INSPECCIÓN Y PROHIBICIÓN DE ALUCINACIÓN", instrucciones_agente)
        self.assertIn("Está ESTRICTAMENTE PROHIBIDO inventar", instrucciones_agente)
        self.assertIn("Toda afirmación técnica sobre el proyecto DEBE poder rastrearse a evidencia empírica", instrucciones_agente)
        self.assertIn("Para SOLID, KISS y DRY, cada conclusión DEBE estar respaldada por fragmentos de código realmente inspeccionados", instrucciones_agente)

    def test_instrucciones_evitan_repeticiones_y_preservan_sandbox(self):
        """El prompt debe reducir rondas sin permitir cambios al entorno seguro."""
        self.assertIn("Conserva y reutiliza los resultados de comprobaciones", instrucciones_agente)
        self.assertIn("proyecto nuevo solicitado explícitamente", instrucciones_agente)
        self.assertIn("No cambies automáticamente de tecnología", instrucciones_agente)
        self.assertIn("Nunca instales ni intentes modificar runtimes del sistema", instrucciones_agente)
        self.assertIn("ni la configuración del sandbox", instrucciones_agente)
        self.assertIn('Indica "no aplica" o "cumplimiento parcial"', instrucciones_agente)

    # 3. Prueba de flujo: Si el modelo intenta responder sin llamar herramientas en un análisis, el sistema fuerza la inspección
    @patch("agente.client.chat.completions.create")
    def test_forzar_inspeccion_cuando_modelo_responde_sin_evidencia(self, mock_create):
        # Primer llamado del modelo: Intenta dar una respuesta directa sin tool_calls
        resp_sin_tool = MagicMock()
        resp_sin_tool.choices = [MagicMock()]
        resp_sin_tool.choices[0].message.role = "assistant"
        resp_sin_tool.choices[0].message.content = "El proyecto calculadora.py tiene un error en la función suma()."
        resp_sin_tool.choices[0].message.tool_calls = None

        # Segundo llamado del modelo (tras el mensaje forzado de evidencia): Llama a listar_directorio
        tc = MagicMock()
        tc.id = "call_123"
        tc.type = "function"
        tc.function.name = "listar_directorio"
        tc.function.arguments = '{"ruta": "."}'
        tc.model_dump.return_value = {
            "id": "call_123",
            "type": "function",
            "function": {"name": "listar_directorio", "arguments": '{"ruta": "."}'}
        }

        resp_con_tool = MagicMock()
        resp_con_tool.choices = [MagicMock()]
        resp_con_tool.choices[0].message.role = "assistant"
        resp_con_tool.choices[0].message.content = None
        resp_con_tool.choices[0].message.tool_calls = [tc]

        # Tercer llamado del modelo: Entrega respuesta basada en la evidencia obtenida
        resp_final = MagicMock()
        resp_final.choices = [MagicMock()]
        resp_final.choices[0].message.role = "assistant"
        resp_final.choices[0].message.content = "El proyecto contiene archivos JavaScript y HTML (app.js, index.html, search.js). No se detectaron errores."
        resp_final.choices[0].message.tool_calls = None

        mock_create.side_effect = [resp_sin_tool, resp_con_tool, resp_final]

        session = ChatSession()
        prompt = "hola necesito que hagas lo siguiente /ruta/Prueba esta es la ruta lo que necesito es que revises este código y me digas si tiene algún error y si se aplicó SOLID, KISS y DRY"
        respuesta = session.enviar(prompt)

        # Verificar que el mensaje forzado de evidencia fue inyectado
        roles = [m.get("role") for m in session.messages]
        contents = [str(m.get("content")) for m in session.messages]

        self.assertTrue(any("[REGLA DE EVIDENCIA" in c for c in contents))
        self.assertIn("JavaScript", respuesta)
        self.assertNotIn("calculadora", respuesta.lower())
        self.assertNotIn("def suma", respuesta.lower())

    # 4. Verificar que listar_directorio por sí solo NO permite conclusiones y exige leer_archivo
    @patch("agente.client.chat.completions.create")
    def test_impedir_conclusiones_solo_con_listar_directorio(self, mock_create):
        # El modelo primero sólo lista directorio
        tc_list = MagicMock()
        tc_list.id = "call_list"
        tc_list.type = "function"
        tc_list.function.name = "listar_directorio"
        tc_list.function.arguments = '{"ruta": "."}'
        tc_list.model_dump.return_value = {
            "id": "call_list",
            "type": "function",
            "function": {"name": "listar_directorio", "arguments": '{"ruta": "."}'}
        }

        resp_solo_list = MagicMock()
        resp_solo_list.choices = [MagicMock()]
        resp_solo_list.choices[0].message.role = "assistant"
        resp_solo_list.choices[0].message.content = None
        resp_solo_list.choices[0].message.tool_calls = [tc_list]

        # Luego intenta responder diciendo "El código cumple SOLID, KISS y DRY" sin leer_archivo
        resp_intento_conclusion = MagicMock()
        resp_intento_conclusion.choices = [MagicMock()]
        resp_intento_conclusion.choices[0].message.role = "assistant"
        resp_intento_conclusion.choices[0].message.content = "El código cumple con SOLID, KISS y DRY perfectamente."
        resp_intento_conclusion.choices[0].message.tool_calls = None

        # Luego llama a leer_archivo tras ser forzado
        tc_read = MagicMock()
        tc_read.id = "call_read"
        tc_read.type = "function"
        tc_read.function.name = "leer_archivo"
        tc_read.function.arguments = '{"ruta": "app.js"}'
        tc_read.model_dump.return_value = {
            "id": "call_read",
            "type": "function",
            "function": {"name": "leer_archivo", "arguments": '{"ruta": "app.js"}'}
        }

        resp_con_read = MagicMock()
        resp_con_read.choices = [MagicMock()]
        resp_con_read.choices[0].message.role = "assistant"
        resp_con_read.choices[0].message.content = None
        resp_con_read.choices[0].message.tool_calls = [tc_read]

        # Respuesta final tras leer_archivo
        resp_final = MagicMock()
        resp_final.choices = [MagicMock()]
        resp_final.choices[0].message.role = "assistant"
        resp_final.choices[0].message.content = "Tras leer app.js, se observó que el código es legible y cumple KISS."
        resp_final.choices[0].message.tool_calls = None

        mock_create.side_effect = [resp_solo_list, resp_intento_conclusion, resp_con_read, resp_final]

        session = ChatSession()
        prompt = "Revisa si este código tiene errores y si cumple SOLID, KISS y DRY"
        respuesta = session.enviar(prompt)

        # Confirmar que la regla de evidencia de código fue inyectada tras intentar responder con solo listar_directorio
        contents = [str(m.get("content")) for m in session.messages]
        self.assertTrue(any("[REGLA DE EVIDENCIA DE CÓDIGO OBLIGATORIA]" in c for c in contents))
        self.assertIn("app.js", respuesta)

    # 5. Verificar que /workspace soporta rutas con espacios completas
    def test_workspace_con_espacios_en_ruta(self):
        ws_espacios = Path(tempfile.mkdtemp(prefix="ws con espacios test ")).resolve()
        try:
            res_val = herramientas.workspace_manager.validar_nuevo_workspace_root(ws_espacios)
            self.assertTrue(res_val["valida"])
            self.assertEqual(res_val["ruta_absoluta"], str(ws_espacios))

            res_set = set_active_workspace(ws_espacios)
            self.assertTrue(res_set["valida"])
            self.assertEqual(str(herramientas.workspace_manager.workspace_root), str(ws_espacios))
        finally:
            set_active_workspace(self.web_project_dir)
            if ws_espacios.exists():
                shutil.rmtree(ws_espacios, ignore_errors=True)

    # 6. Prueba con API real (o integración E2E): Verificar que no se inventen funciones Python en proyectos Web
    def test_analisis_proyecto_web_sin_alucinaciones_python(self):
        session = ChatSession()
        prompt = "Analiza los archivos de este proyecto y dime qué estructura tiene y si se aplica SOLID, KISS y DRY."
        respuesta = session.enviar(prompt)

        # Verificar que se usaron herramientas de inspección o que el diagnóstico se basa en archivos reales
        self.assertNotIn("calculadora", respuesta.lower())
        self.assertNotIn("test_calculadora", respuesta.lower())


if __name__ == "__main__":
    unittest.main()
