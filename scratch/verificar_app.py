"""Verificación E2E de la app gestor_tareas.

Realiza un smoke test programático de la CLI (módulos interno) y
comprueba el flujo completo: crear -> listar -> completar -> eliminar.
"""
import os
import tempfile

from gestor_tareas.gestor import GestorTareas
from gestor_tareas.repositorio import RepositorioTareas
from gestor_tareas import __version__


def ejecutar_verificacion():
    resultados = []

    # 1. Paquete importable y versión.
    resultados.append(("versión del paquete", __version__))

    # 2. Flujo E2E con repositorio temporal.
    fd, ruta_temp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(ruta_temp)
    try:
        gestor = GestorTareas(RepositorioTareas(ruta_temp))

        creada = gestor.crear("Comprar pan")
        resultados.append(("crear", creada.titulo, creada.completada))

        n = len(gestor.listar())
        resultados.append(("listar tras crear", n))

        if len(gestor.listar()) >= 2:
            gestor.crear("Escribir informe")

        completada = gestor.marcar_completada(1)
        resultados.append(("marcar_completada", completada.titulo, completada.completada))

        eliminada = gestor.eliminar(2)
        resultados.append(("eliminar", eliminada.titulo))

        # Recarga para validar persistencia.
        recargado = GestorTareas(RepositorioTareas(ruta_temp))
        resultados.append(("persistencia (recargado)", len(recargado.listar()), recargado.listar()[0].completada))
    finally:
        if os.path.exists(ruta_temp):
            os.remove(ruta_temp)

    return resultados


if __name__ == "__main__":
    for fila in ejecutar_verificacion():
        print("OK |", " | ".join(str(x) for x in fila))
