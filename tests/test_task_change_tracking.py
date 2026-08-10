"""Pruebas del tracking efímero de cambios por ChatSession."""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import herramientas
from agente import ChatSession


class TestTaskChangeTracking(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.original = str(herramientas.workspace_manager.workspace_root)
        herramientas.set_active_workspace(self.workspace.name)
        self.session = ChatSession()

    def tearDown(self):
        herramientas.set_active_workspace(self.original)
        self.workspace.cleanup()

    def _write(self, route, content, overwrite=False):
        context = self.session._prepare_change_context("escribir_archivo", {"ruta": route})
        result = herramientas.escribir_archivo(route, content, sobrescribir=overwrite)
        self.session._record_successful_change(context, result)

    def _edit(self, route, old, new):
        context = self.session._prepare_change_context("editar_archivo", {"ruta": route})
        result = herramientas.editar_archivo(route, old, new)
        self.session._record_successful_change(context, result)

    def _rm(self, route, success=True):
        context = self.session._prepare_change_context("ejecutar_comando_bash", {"comando": f"rm {route}"})
        if success:
            (Path(self.workspace.name) / route).unlink()
        self.session._record_successful_change(context, {"error": not success})

    def test_create_modify_delete_and_created_then_deleted(self):
        self._write("new.txt", "one")
        self._write("new.txt", "two", overwrite=True)
        self._rm("new.txt")
        summary = self.session.task_changes.summary()
        self.assertEqual(summary["created_files"], [])
        self.assertEqual(summary["created_then_deleted_files"], ["new.txt"])
        self.assertEqual([event["operation"] for event in summary["events"]], ["creado", "modificado", "deleted"])

    def test_existing_file_modify_then_restore(self):
        Path(self.workspace.name, "existing.txt").write_text("original")
        self._edit("existing.txt", "original", "changed")
        self._edit("existing.txt", "changed", "original")
        summary = self.session.task_changes.summary()
        self.assertEqual(summary["modified_files"], [])
        self.assertEqual(summary["restored_files"], ["existing.txt"])

    def test_delete_existing_file_and_failed_command_only_after_success(self):
        Path(self.workspace.name, "existing.txt").write_text("original")
        context = self.session._prepare_change_context("ejecutar_comando_bash", {"comando": "rm existing.txt"})
        self.session._record_successful_change(context, {"error": True})
        self.assertEqual(self.session.task_changes.events, [])
        Path(self.workspace.name, "existing.txt").unlink()
        self.session._record_successful_change(context, {"error": False})
        self.assertEqual(self.session.task_changes.summary()["deleted_files"], ["existing.txt"])

    def test_read_blocked_and_outside_operations_are_not_recorded(self):
        herramientas.leer_archivo("missing.txt")
        context = self.session._prepare_change_context("escribir_archivo", {"ruta": "/tmp/outside.txt"})
        result = herramientas.escribir_archivo("/tmp/outside.txt", "x")
        self.session._record_successful_change(context, result)
        self._rm("missing.txt", success=False)
        self.assertEqual(self.session.task_changes.events, [])

    def test_new_session_is_empty_and_events_have_no_content(self):
        self._write("nested/file.txt", "secret content")
        summary = self.session.task_changes.summary()
        self.assertEqual(ChatSession().task_changes.summary()["events"], [])
        self.assertEqual(summary["created_files"], ["nested/file.txt"])
        self.assertTrue(all("content" not in event for event in summary["events"]))
        self.assertTrue(all(not Path(event["path"]).is_absolute() for event in summary["events"]))

    def test_mv_cp_only_record_after_success_and_decisions_are_ordered(self):
        self._write("source.txt", "x")
        source = Path(self.workspace.name, "source.txt")
        destination = Path(self.workspace.name, "copy.txt")
        context = self.session._prepare_change_context("ejecutar_comando_bash", {"comando": "cp source.txt copy.txt"})
        destination.write_text(source.read_text())
        self.session._record_successful_change(context, {"error": False})
        self.session.technology_decision.update({"selected": "node", "alternative": "python", "runtime_available": False})
        self.session._register_human_technology_authorization("sí")
        summary = self.session.task_changes.summary()
        self.assertIn("copy.txt", summary["created_files"])
        self.assertEqual(summary["decisions"][0]["decision"], "technology_change_authorized:node->python")
        self.assertEqual(sorted({event["path"] for event in summary["events"]}), sorted(summary["created_files"]))


if __name__ == "__main__":
    unittest.main()
