"""repositorio.py — Persistencia de tareas en un archivo JSON.

Responsabilidad única (SRP): gestionar el guardado y la carga de las tareas
desde/hacia un archivo JSON. No contiene lógica de negocio.
"""

import json
import os

from gestor_tareas.modelo import Tarea


class RepositorioTareas:
    """Se encarga de leer y escribir la lista de tareas en un archivo JSON.

    Atributos:
        ruta_archivo (str): Ruta del archivo JSON donde se persisten las tareas.
    """

    def __init__(self, ruta_archivo: str) -> None:
        self.ruta_archivo = ruta_archivo

    def cargar(self) -> list:
        """Carga las tareas desde el archivo JSON.

        Si el archivo no existe o está vacío, devuelve una lista vacía.
        Si el JSON está corrupto, se devuelve una lista vacía sin romper el programa.

        Returns:
            list: Lista de objetos Tarea.
        """
        if not os.path.exists(self.ruta_archivo):
            return []

        try:
            with open(self.ruta_archivo, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
        except (json.JSONDecodeError, OSError):
            # Archivo inexistente, vacío o corrupto: se parte de cero.
            return []

        return [Tarea.desde_dict(item) for item in datos]

    def guardar(self, tareas: list) -> None:
        """Guarda la lista de tareas en el archivo JSON.

        Args:
            tareas (list): Lista de objetos Tarea a persistir.
        """
        datos = [tarea.a_dict() for tarea in tareas]
        with open(self.ruta_archivo, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
