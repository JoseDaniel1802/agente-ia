"""Paquete gestor_tareas: gestión simple de tareas con persistencia JSON.

Módulos:
- modelo: definición de la clase Tarea.
- repositorio: carga y guardado de tareas en archivo JSON.
- gestor: operaciones de negocio (crear, listar, completar, eliminar).
"""

from gestor_tareas.modelo import Tarea
from gestor_tareas.repositorio import RepositorioTareas
from gestor_tareas.gestor import GestorTareas

__all__ = ["Tarea", "RepositorioTareas", "GestorTareas"]
__version__ = "1.0.0"
