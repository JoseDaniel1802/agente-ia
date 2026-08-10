"""gestor.py — Lógica de negocio del gestor de tareas.

Responsabilidad única (SRP): orquestar las operaciones de la aplicación
(crear, listar, completar, eliminar) sobre el repositorio de tareas.
"""

from gestor_tareas.modelo import Tarea
from gestor_tareas.repositorio import RepositorioTareas


class GestorTareas:
    """Gestiona las operaciones de negocio sobre un repositorio de tareas.

    Atributos:
        repositorio (RepositorioTareas): Objeto que persiste las tareas.
        tareas (list): Lista en memoria de objetos Tarea (id → índice).
    """

    def __init__(self, repositorio: RepositorioTareas) -> None:
        self.repositorio = repositorio
        self.tareas = self.repositorio.cargar()

    def crear(self, titulo: str) -> Tarea:
        """Agrega una nueva tarea y persiste los cambios.

        Args:
            titulo (str): Título de la tarea a crear.

        Returns:
            Tarea: La tarea recién creada.
        """
        tarea = Tarea(titulo=titulo)
        self.tareas.append(tarea)
        self.repositorio.guardar(self.tareas)
        return tarea

    def listar(self) -> list:
        """Devuelve todas las tareas cargadas.

        Returns:
            list: Lista de objetos Tarea.
        """
        return list(self.tareas)

    def marcar_completada(self, indice: int) -> Tarea:
        """Marca una tarea como completada según su índice (1-based).

        Args:
            indice (int): Posición de la tarea en la lista (empieza en 1).

        Raises:
            IndexError: Si el índice no corresponde a una tarea existente.
        """
        if not (1 <= indice <= len(self.tareas)):
            raise IndexError(f"Índice {indice} fuera de rango (1..{len(self.tareas)})")
        tarea = self.tareas[indice - 1]
        tarea.completada = True
        self.repositorio.guardar(self.tareas)
        return tarea

    def eliminar(self, indice: int) -> Tarea:
        """Elimina una tarea según su índice (1-based) y persiste.

        Args:
            indice (int): Posición de la tarea a eliminar (empieza en 1).

        Raises:
            IndexError: Si el índice no corresponde a una tarea existente.
        """
        if not (1 <= indice <= len(self.tareas)):
            raise IndexError(f"Índice {indice} fuera de rango (1..{len(self.tareas)})")
        tarea = self.tareas.pop(indice - 1)
        self.repositorio.guardar(self.tareas)
        return tarea
