"""tests/test_gestor.py — Pruebas unitarias del gestor de tareas.

Se utiliza unittest (biblioteca estándar) para evitar dependencias externas.
Cada test usa un archivo JSON temporal independiente (tempfile) para no
contaminar datos reales.
"""

import os
import tempfile
import unittest

from gestor_tareas.gestor import GestorTareas
from gestor_tareas.repositorio import RepositorioTareas


class TestGestorTareasBase(unittest.TestCase):
    """Configuración común: gestor sobre un archivo temporal."""

    def setUp(self):
        # Se crea un archivo temporal y se conserva su ruta.
        fd, self.ruta_temp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.ruta_temp)  # Empezamos con un archivo inexistente.
        repositorio = RepositorioTareas(self.ruta_temp)
        self.gestor = GestorTareas(repositorio)

    def tearDown(self):
        if os.path.exists(self.ruta_temp):
            os.remove(self.ruta_temp)


class TestCrearTarea(TestGestorTareasBase):
    def test_crear_tarea_agrega_y_persiste(self):
        tarea = self.gestor.crear("Comprar pan")
        self.assertEqual(tarea.titulo, "Comprar pan")
        self.assertFalse(tarea.completada)
        # Se persiste en el archivo JSON.
        self.assertTrue(os.path.exists(self.ruta_temp))
        self.assertEqual(len(self.gestor.listar()), 1)

    def test_crear_varias_tareas(self):
        self.gestor.crear("Tarea A")
        self.gestor.crear("Tarea B")
        self.gestor.crear("Tarea C")
        self.assertEqual(len(self.gestor.listar()), 3)


class TestListarTareas(TestGestorTareasBase):
    def test_listar_vacio_al_inicio(self):
        self.assertEqual(self.gestor.listar(), [])

    def test_listar_desde_archivo_existente(self):
        # Se crea una tarea, se destruye el gestor y se recarga.
        self.gestor.crear("Persistida")
        gestor_recargado = GestorTareas(RepositorioTareas(self.ruta_temp))
        tareas = gestor_recargado.listar()
        self.assertEqual(len(tareas), 1)
        self.assertEqual(tareas[0].titulo, "Persistida")


class TestMarcarCompletada(TestGestorTareasBase):
    def test_marcar_completada_cambia_estado(self):
        self.gestor.crear("Tarea 1")
        tarea = self.gestor.marcar_completada(1)
        self.assertTrue(tarea.completada)

    def test_marcar_completada_persiste(self):
        self.gestor.crear("Tarea 1")
        self.gestor.marcar_completada(1)
        gestor_recargado = GestorTareas(RepositorioTareas(self.ruta_temp))
        self.assertTrue(gestor_recargado.listar()[0].completada)

    def test_marcar_indice_invalido_lanza_error(self):
        self.gestor.crear("Tarea 1")
        with self.assertRaises(IndexError):
            self.gestor.marcar_completada(5)


class TestEliminarTarea(TestGestorTareasBase):
    def test_eliminar_tarea(self):
        self.gestor.crear("Tarea 1")
        self.gestor.crear("Tarea 2")
        eliminada = self.gestor.eliminar(1)
        self.assertEqual(eliminada.titulo, "Tarea 1")
        self.assertEqual(len(self.gestor.listar()), 1)
        self.assertEqual(self.gestor.listar()[0].titulo, "Tarea 2")

    def test_eliminar_tarea_invalida_lanza_error(self):
        self.gestor.crear("Tarea 1")
        with self.assertRaises(IndexError):
            self.gestor.eliminar(10)


class TestPersistencia(TestGestorTareasBase):
    def test_guardar_y_recargar_estructura_completa(self):
        self.gestor.crear("Tarea A")
        self.gestor.crear("Tarea B")
        self.gestor.marcar_completada(2)

        gestor_recargado = GestorTareas(RepositorioTareas(self.ruta_temp))
        tareas = gestor_recargado.listar()
        self.assertEqual(len(tareas), 2)
        self.assertEqual(tareas[0].titulo, "Tarea A")
        self.assertEqual(tareas[1].titulo, "Tarea B")
        self.assertFalse(tareas[0].completada)
        self.assertTrue(tareas[1].completada)


class TestCargaArchivoInexistenteOAcorrupto(unittest.TestCase):
    def test_cargar_archivo_inexistente_devuelve_vacio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ruta = os.path.join(tmpdir, "no_existe.json")
            gestor = GestorTareas(RepositorioTareas(ruta))
            self.assertEqual(gestor.listar(), [])

    def test_cargar_json_corrupto_devuelve_vacio(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("esto-no-es-json-{")
            ruta = fh.name
        try:
            gestor = GestorTareas(RepositorioTareas(ruta))
            self.assertEqual(gestor.listar(), [])
        finally:
            os.remove(ruta)


if __name__ == "__main__":
    unittest.main()
