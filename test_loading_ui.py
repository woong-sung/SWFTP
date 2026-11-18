import ast
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox
from app import SFTPClientApp


class FakeWorker(QObject):
    finished_signal = pyqtSignal(str, object)
    error_signal = pyqtSignal(str, str)
    finished = pyqtSignal()
    action = "list_dir"

    def start(self):
        self.started = True


class LoadingWindow(QMainWindow):
    start_worker = SFTPClientApp.start_worker
    finish_loading = SFTPClientApp.finish_loading

    def __init__(self):
        super().__init__()
        self.loading_dialogs = {}


class LoadingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_loading_closes_on_success_error_and_thread_exit(self):
        window = LoadingWindow()
        for signal, args in (("finished_signal", ("list_dir", [])),
                             ("error_signal", ("list_dir", "failure")),
                             ("finished", ())):
            worker = FakeWorker()
            window.start_worker(worker)
            dialog = window.loading_dialogs[worker]
            self.assertTrue(dialog.isVisible())
            self.assertTrue(worker.started)
            self.assertEqual(dialog.windowModality(), Qt.WindowModality.WindowModal)
            getattr(worker, signal).emit(*args)
            self.assertFalse(dialog.isVisible())
            self.assertEqual(window.loading_dialogs, {})
        window.close()

    def test_all_confirmation_calls_default_to_yes_and_enter_accepts(self):
        tree = ast.parse(Path("app.py").read_text(encoding="utf-8"))
        questions = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute)
                     and isinstance(node.func.value, ast.Name)
                     and node.func.value.id == "QMessageBox" and node.func.attr == "question"]
        self.assertTrue(questions)
        for question in questions:
            self.assertEqual(ast.unparse(question.args[4]), "QMessageBox.StandardButton.Yes")
        box = QMessageBox()
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        QTimer.singleShot(0, lambda: QTest.keyClick(box, Qt.Key.Key_Return))
        self.assertEqual(box.exec(), QMessageBox.StandardButton.Yes)


if __name__ == "__main__":
    unittest.main()
