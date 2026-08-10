"""Prueba de humo: verifica que el módulo gestor_tareas y su CLI importan y corren."""
import io
import os
import sys
import tempfile
import unittest.mock
from unittest import mock

from gestor_tareas.gestor import GestorTareas
from gestor_tareas.repositorio import RepositorioTareas


def main():
    # 1. El paquete se importa correctamente.
    import gestor_tareas  # noqa: F401
    print("Paquete gestor_tareas importado: OK")

    # 2. Un gestor con archivo temporal crea/lista una tarea real.
    fd, ruta = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(ruta)
    gestor = GestorTareas(RepositorioTareas(ruta))
    gestor.crear("Compra de prueba")
    gestor.crear("Segunda tarea")
    gestor.marcar_completada(2)
    tareas = gestor.listar()
    assert len(tareas) == 2, f"Se esperaban 2 tareas, hay {len(tareas)}"
    assert tareas[0].titulo == "Compra de prueba"
    assert tareas[1].completada is True
    print("Operaciones del gestor (crear/log/ listar/completar): OK")

    # 3. La CLI se puede invocar (simulando teclas: 2=listar, 5=salir).
    entradas = ["2", "5"]
    with mock.patch("builtins.input", side_effect=entradas):
        from gestor_tareas.cli import ejecutar
        ejecutar()
    print("CLI ejecutada sin errores: OK")

    os.remove(ruta)
    print("SMOKE TEST SUPERADO")


if __name__ == "__main__":
    main()
