"""
Pruebas de Regresión para la Arquitectura Environment First.
Verifica que la creación/edición de archivos fuente (HTML, CSS, JS, Python, Java, Go, etc.)
se realice libremente sin exigir la presencia de runtimes, mientras que la EJECUCIÓN
de comandos (node app.js, python3 app.py, java Main, etc.) valide y bloquee si el runtime no está disponible.
"""

import sys
import unittest
from pathlib import Path

# Añadir proyecto al path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import agente
from agente import ChatSession


class TestEnvironmentFirstRegression(unittest.TestCase):
    """Suite de regresión para desacoplar creación de archivos de la ejecución de runtimes."""

    def setUp(self):
        self.session = ChatSession()

    # 1. Proyecto frontend estático: crear index.html, styles.css, app.js sin Node/npm
    def test_frontend_vanilla_creacion_archivos_sin_node(self):
        self.session.runtime_status["node"] = False
        self.session.runtime_status["npm"] = False

        res_html = self.session._preflight_error_for_write("escribir_archivo", {"ruta": "index.html"})
        res_css = self.session._preflight_error_for_write("escribir_archivo", {"ruta": "styles.css"})
        res_js = self.session._preflight_error_for_write("escribir_archivo", {"ruta": "app.js"})

        self.assertIsNone(res_html)
        self.assertIsNone(res_css)
        self.assertIsNone(res_js)

    # 2. Proyecto Python: crear main.py sin Python3
    def test_crear_main_py_sin_python(self):
        self.session.runtime_status["python3"] = False

        res_py = self.session._preflight_error_for_write("escribir_archivo", {"ruta": "main.py"})
        self.assertIsNone(res_py)

    # 3. Proyecto Java: crear Main.java sin Java
    def test_crear_main_java_sin_java(self):
        self.session.runtime_status["java"] = False

        res_java = self.session._preflight_error_for_write("escribir_archivo", {"ruta": "Main.java"})
        self.assertIsNone(res_java)

    # 4. Proyecto Go: crear main.go sin Go
    def test_crear_main_go_sin_go(self):
        self.session.runtime_status["go"] = False

        res_go = self.session._preflight_error_for_write("escribir_archivo", {"ruta": "main.go"})
        self.assertIsNone(res_go)

    # 5. Ejecución: node app.js sin Node debe ser bloqueada
    def test_ejecutar_node_app_js_sin_node_bloqueado(self):
        self.session.runtime_status["node"] = False

        res_exec = self.session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "node app.js"})
        self.assertIsNotNone(res_exec)
        self.assertTrue(res_exec.get("error"))
        self.assertEqual(res_exec.get("codigo_error"), "RUNTIME_NO_DISPONIBLE")
        self.assertIn("node", res_exec.get("mensaje", ""))

    # 6. Ejecución: python3 app.py sin Python3 debe ser bloqueada
    def test_ejecutar_python_script_sin_python_bloqueado(self):
        self.session.runtime_status["python3"] = False

        res_exec = self.session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "python3 app.py"})
        self.assertIsNotNone(res_exec)
        self.assertTrue(res_exec.get("error"))
        self.assertEqual(res_exec.get("codigo_error"), "RUNTIME_NO_DISPONIBLE")
        self.assertIn("python3", res_exec.get("mensaje", ""))

    # 7. Ejecución: java Main sin Java debe ser bloqueada
    def test_ejecutar_java_main_sin_java_bloqueado(self):
        self.session.runtime_status["java"] = False

        res_exec = self.session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "java Main"})
        self.assertIsNotNone(res_exec)
        self.assertTrue(res_exec.get("error"))
        self.assertEqual(res_exec.get("codigo_error"), "RUNTIME_NO_DISPONIBLE")

    # 8. Verificación de versión (node --version) no se bloquea por preflight
    def test_version_command_no_se_bloquea(self):
        self.session.runtime_status["node"] = False

        res_exec = self.session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "node --version"})
        self.assertIsNone(res_exec)

    # 9. Bypass con wrapper env node app.js debe ser detectado y bloqueado
    def test_wrapper_env_node_bloqueado(self):
        self.session.runtime_status["node"] = False

        res_exec = self.session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "env node app.js"})
        self.assertIsNotNone(res_exec)
        self.assertEqual(res_exec.get("codigo_error"), "RUNTIME_NO_DISPONIBLE")

    # 10. Preflight para cargo test y dotnet test
    def test_cargo_y_dotnet_bloqueados_si_runtime_ausente(self):
        self.session.runtime_status["cargo"] = False
        self.session.runtime_status["dotnet"] = False

        res_cargo = self.session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "cargo test"})
        res_dotnet = self.session._preflight_error_for_execution("ejecutar_comando_bash", {"comando": "dotnet test"})

        self.assertIsNotNone(res_cargo)
        self.assertEqual(res_cargo.get("codigo_error"), "RUNTIME_NO_DISPONIBLE")
        self.assertIsNotNone(res_dotnet)
        self.assertEqual(res_dotnet.get("codigo_error"), "RUNTIME_NO_DISPONIBLE")

    # 11. Descubrimiento de version check para go version, java -version, cargo --version, dotnet --version
    def test_reconocimiento_ampliado_version_commands(self):
        self.assertEqual(agente._runtime_for_version_command("go version"), "go")
        self.assertEqual(agente._runtime_for_version_command("java -version"), "java")
        self.assertEqual(agente._runtime_for_version_command("cargo --version"), "cargo")
        self.assertEqual(agente._runtime_for_version_command("dotnet --version"), "dotnet")


if __name__ == "__main__":
    unittest.main()
