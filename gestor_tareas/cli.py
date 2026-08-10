"""cli.py — Interfaz de línea de comandos del gestor de tareas.

Proporciona un menú interactivo sencillo para operar las tareas.
Usa únicamente la biblioteca estándar (input/print), sin dependencias externas.
"""

from gestor_tareas.gestor import GestorTareas
from gestor_tareas.repositorio import RepositorioTareas

ARCHIVO_DATOS = "tareas.json"


def ejecutar():
    """Bucle principal de la CLI del gestor de tareas."""
    repositorio = RepositorioTareas(ARCHIVO_DATOS)
    gestor = GestorTareas(repositorio)

    print("=== GESTOR DE TAREAS ===")
    while True:
        print("\nOpciones:")
        print("  1. Crear tarea")
        print("  2. Listar tareas")
        print("  3. Marcar tarea como completada")
        print("  4. Eliminar tarea")
        print("  5. Salir")

        opcion = input("\nElige una opción: ").strip()

        if opcion == "1":
            titulo = input("Título de la tarea: ").strip()
            if titulo:
                gestor.crear(titulo)
                print(f"✓ Tarea creada: {titulo}")
            else:
                print("El título no puede estar vacío.")

        elif opcion == "2":
            _mostrar_tareas(gestor.listar())

        elif opcion == "3":
            _marcar_completada(gestor)

        elif opcion == "4":
            _eliminar_tarea(gestor)

        elif opcion == "5":
            print("¡Hasta luego!")
            break

        else:
            print("Opción no válida.")


def _mostrar_tareas(tareas):
    """Imprime la lista de tareas o un aviso si está vacía."""
    if not tareas:
        print("No hay tareas registradas.")
        return
    print("\nLista de tareas:")
    for indice, tarea in enumerate(tareas, start=1):
        print(f"  {indice}. {tarea}")


def _marcar_completada(gestor):
    """Pide un índice y marca la tarea como completada."""
    _mostrar_tareas(gestor.listar())
    indice = _pedir_indice()
    if indice is None:
        return
    try:
        gestor.marcar_completada(indice)
        print(f"✓ Tarea {indice} marcada como completada.")
    except IndexError as exc:
        print(f"Error: {exc}")


def _eliminar_tarea(gestor):
    """Pide un índice y elimina la tarea."""
    _mostrar_tareas(gestor.listar())
    indice = _pedir_indice()
    if indice is None:
        return
    try:
        gestor.eliminar(indice)
        print(f"✓ Tarea {indice} eliminada.")
    except IndexError as exc:
        print(f"Error: {exc}")


def _pedir_indice():
    """Solicita e interpreta un índice entero. Devuelve None si es inválido."""
    valor = input("Número de tarea: ").strip()
    try:
        return int(valor)
    except ValueError:
        print("Debes ingresar un número válido.")
        return None
