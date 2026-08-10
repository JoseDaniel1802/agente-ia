"""modelo.py — Definición del dominio (dato) de una tarea.

Responsabilidad única (SRP): representar la estructura de datos de una tarea
sin lógica de negocio ni de persistencia.
"""


class Tarea:
    """Representa una tarea del gestor.

    Atributos:
        titulo (str): Descripción o nombre de la tarea.
        completada (bool): Indica si la tarea fue marcada como completada.
    """

    def __init__(self, titulo: str, completada: bool = False) -> None:
        self.titulo = titulo
        self.completada = completada

    def a_dict(self) -> dict:
        """Convierte la tarea a un dict serializable en JSON."""
        return {"titulo": self.titulo, "completada": self.completada}

    @classmethod
    def desde_dict(cls, datos: dict) -> "Tarea":
        """Reconstruye una Tarea desde un dict (deserialización JSON)."""
        return cls(
            titulo=datos["titulo"],
            completada=bool(datos.get("completada", False)),
        )

    def __repr__(self) -> str:
        estado = "✔" if self.completada else "✘"
        return f"[{estado}] {self.titulo}"
