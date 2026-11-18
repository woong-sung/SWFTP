import codecs
import queue
import re
import threading
import time

import paramiko
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget


class SSHTerminalWorker(QThread):
    output_signal = pyqtSignal(str)
    ready_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    disconnected_signal = pyqtSignal()

    def __init__(self, ssh_client):
        super().__init__()
        self.ssh_client = ssh_client
        self.channel = None
        self.input_queue = queue.Queue()
        self.stop_event = threading.Event()

    def send_input(self, text):
        self.input_queue.put(text)

    def stop(self):
        self.stop_event.set()
        if self.channel:
            self.channel.close()

    def run(self):
        try:
            transport = self.ssh_client.get_transport()
            if not transport or not transport.is_active():
                raise paramiko.SSHException("SSH connection is not active.")
            self.channel = transport.open_session()
            self.channel.get_pty(term="xterm", width=120, height=30)
            self.channel.invoke_shell()
            self.channel.settimeout(1)
            self.ready_signal.emit()

            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            while not self.stop_event.is_set():
                try:
                    text = self.input_queue.get_nowait()
                except queue.Empty:
                    text = None
                if text is not None:
                    self.channel.sendall(text)

                if self.channel.recv_ready():
                    data = self.channel.recv(4096)
                    if not data:
                        break
                    output = decoder.decode(data)
                    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
                    output = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", output)
                    if output:
                        self.output_signal.emit(output)
                elif self.channel.closed or self.channel.exit_status_ready():
                    break
                else:
                    time.sleep(0.03)
        except Exception as e:
            if not self.stop_event.is_set():
                self.error_signal.emit(str(e))
        finally:
            if self.channel:
                self.channel.close()
            self.disconnected_signal.emit()


class SSHTerminalWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(
            "background-color: #11111b; color: #a6e3a1; "
            "font-family: 'Consolas', 'Courier New', monospace;"
        )
        layout.addWidget(self.output, 1)

        input_layout = QHBoxLayout()
        prompt = QLabel("SSH>")
        prompt.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; color: #89b4fa;"
        )
        self.input = QLineEdit()
        self.input.setPlaceholderText("SSH 연결 후 명령을 입력하세요")
        self.input.setEnabled(False)
        self.input.returnPressed.connect(self.send_input)

        self.send_button = QPushButton("전송")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_input)
        self.interrupt_button = QPushButton("Ctrl+C")
        self.interrupt_button.setEnabled(False)
        self.interrupt_button.clicked.connect(self.interrupt_command)
        clear_button = QPushButton("지우기")
        clear_button.clicked.connect(self.output.clear)

        input_layout.addWidget(prompt)
        input_layout.addWidget(self.input, 1)
        input_layout.addWidget(self.send_button)
        input_layout.addWidget(self.interrupt_button)
        input_layout.addWidget(clear_button)
        layout.addLayout(input_layout)

    def start(self, ssh_client):
        self.stop()
        self.output.clear()
        self.output.append("SSH 터미널 연결 중...")
        self.set_input_enabled(False)
        self.worker = SSHTerminalWorker(ssh_client)
        self.worker.output_signal.connect(self.append_output)
        self.worker.ready_signal.connect(self.on_ready)
        self.worker.error_signal.connect(self.on_error)
        self.worker.disconnected_signal.connect(self.on_disconnected)
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        self.set_input_enabled(False)

    def set_input_enabled(self, enabled):
        self.input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.interrupt_button.setEnabled(enabled)

    def send_input(self):
        if not self.worker or not self.worker.isRunning():
            return
        text = self.input.text()
        self.input.clear()
        self.worker.send_input(text + "\r")

    def interrupt_command(self):
        if self.worker and self.worker.isRunning():
            self.worker.send_input("\x03")

    def append_output(self, text):
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def on_ready(self):
        self.set_input_enabled(True)
        self.input.setFocus()

    def on_error(self, error):
        self.append_output(f"\n[SSH 터미널 오류] {error}\n")
        self.set_input_enabled(False)

    def on_disconnected(self):
        self.set_input_enabled(False)
