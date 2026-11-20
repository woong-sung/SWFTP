import sys
import os
import posixpath
import stat
import datetime
import json
import shutil
import tempfile
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QProgressBar, QProgressDialog, QStatusBar, QGroupBox, QMenu, QInputDialog, QComboBox,
    QAbstractItemView, QCheckBox, QTextEdit, QDialog, QGridLayout, QDialogButtonBox, QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QMimeData, QUrl, QFileSystemWatcher, QItemSelection, QItemSelectionModel, QEvent
from PyQt6.QtGui import QColor, QAction, QDrag, QFont, QKeySequence, QIcon
import paramiko
from sftp_encoding import EncodingSFTPClient
from ftp_client import FTPClient
from oz_client import OZClient, OZ_PROTOCOL, normalize_server_url
from file_operations import delete_local_item, delete_remote_item, upload_directory
from ssh_terminal import SSHTerminalWidget
from app_version import APP_VERSION
from auto_update import UpdateWorker, install_on_exit

APP_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ftp_icon.ico")

# Define styling using modern Dark QSS
DARK_THEME_QSS = """
QMainWindow {
    background-color: #1e1e2e;
}
QTabWidget::pane {
    border: 1px solid #45475a;
}
QTabBar::tab {
    background-color: #252538;
    color: #f5f5f5;
    padding: 7px 14px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:!selected {
    color: #f5f5f5;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #ffffff;
    font-weight: bold;
    border-bottom: 2px solid #89b4fa;
}
QTabBar::tab:hover {
    background-color: #36364d;
}
QWidget {
    color: #cdd6f4;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QGroupBox {
    background-color: #252538;
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 5px;
    padding-top: 15px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 15px;
    padding: 0 5px;
}
QLineEdit {
    background-color: #11111b;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 10px;
    color: #cdd6f4;
}
QLineEdit:focus {
    border: 1px solid #89b4fa;
}
QComboBox {
    background-color: #11111b;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 5px 10px;
    color: #cdd6f4;
    min-width: 150px;
}
QComboBox QAbstractItemView {
    background-color: #11111b;
    selection-background-color: #45475a;
    color: #cdd6f4;
}
QPushButton {
    background-color: #89b4fa;
    color: #11111b;
    border: none;
    border-radius: 4px;
    padding: 6px 15px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #b4befe;
}
QPushButton:pressed {
    background-color: #74c7ec;
}
QPushButton:disabled {
    background-color: #313244;
    color: #585b70;
}
QTableWidget {
    background-color: #181825;
    border: 1px solid #313244;
    gridline-color: #313244;
    border-radius: 6px;
    alternate-background-color: #1e1e2e;
}
QTableWidget::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}
QHeaderView::section {
    background-color: #252538;
    color: #89b4fa;
    padding: 6px;
    border: 1px solid #313244;
    font-weight: bold;
}
QScrollBar:vertical {
    border: none;
    background: #11111b;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #585b70;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
}
QProgressBar {
    border: 1px solid #45475a;
    border-radius: 4px;
    text-align: center;
    background-color: #11111b;
    color: #cdd6f4;
}
QProgressBar::chunk {
    background-color: #a6e3a1;
}
QStatusBar {
    background-color: #11111b;
    color: #a6adc8;
    border-top: 1px solid #313244;
}
QMenu {
    background-color: #252538;
    border: 1px solid #45475a;
    color: #cdd6f4;
    padding: 5px;
}
QMenu::item {
    padding: 6px 25px 6px 20px;
    background-color: transparent;
}
QMenu::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}
QMenu::separator {
    height: 1px;
    background-color: #45475a;
    margin: 4px 0px;
}
QDialog, QMessageBox {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QDialog QLabel, QMessageBox QLabel {
    color: #cdd6f4;
}
QDialog QPushButton, QMessageBox QPushButton {
    background-color: #89b4fa;
    color: #11111b;
    border: none;
    border-radius: 4px;
    padding: 6px 15px;
    font-weight: bold;
    min-width: 75px;
}
QDialog QPushButton:hover, QMessageBox QPushButton:hover {
    background-color: #b4befe;
}
QDialog QPushButton:pressed, QMessageBox QPushButton:pressed {
    background-color: #74c7ec;
}
"""

class SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, text, sort_value):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, SortableTableWidgetItem):
            try:
                return self.sort_value < other.sort_value
            except Exception:
                return str(self.sort_value) < str(other.sort_value)
        return super().__lt__(other)


class FilePropertiesDialog(QDialog):
    def __init__(self, parent, name, is_remote, path, size_kb, date_str, owner_group, raw_mode=None):
        super().__init__(parent)
        self.setWindowTitle(f"Properties - {name}")
        self.resize(380, 420)
        self.is_remote = is_remote
        self.selection_drag_anchor = None
        self.path = path
        self.new_mode = None

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setSpacing(10)

        grid.addWidget(QLabel("<b>Name:</b>"), 0, 0)
        grid.addWidget(QLabel(name), 0, 1)

        grid.addWidget(QLabel("<b>Location:</b>"), 1, 0)
        grid.addWidget(QLabel(path), 1, 1)

        grid.addWidget(QLabel("<b>Type:</b>"), 2, 0)
        grid.addWidget(QLabel("Remote File/Folder" if is_remote else "Local File/Folder"), 2, 1)

        grid.addWidget(QLabel("<b>Size:</b>"), 3, 0)
        grid.addWidget(QLabel(f"{size_kb} KB" if size_kb >= 0 else "N/A"), 3, 1)

        grid.addWidget(QLabel("<b>Modified:</b>"), 4, 0)
        grid.addWidget(QLabel(date_str), 4, 1)

        grid.addWidget(QLabel("<b>Owner/Group:</b>"), 5, 0)
        grid.addWidget(QLabel(owner_group), 5, 1)

        layout.addLayout(grid)

        # Permissions Group Box
        self.perm_group = QGroupBox("Permissions")
        perm_layout = QGridLayout(self.perm_group)
        perm_layout.setHorizontalSpacing(15)
        perm_layout.setVerticalSpacing(8)

        perm_layout.addWidget(QLabel("<b>User</b>"), 0, 1)
        perm_layout.addWidget(QLabel("<b>Group</b>"), 0, 2)
        perm_layout.addWidget(QLabel("<b>Others</b>"), 0, 3)

        perm_layout.addWidget(QLabel("Read"), 1, 0)
        perm_layout.addWidget(QLabel("Write"), 2, 0)
        perm_layout.addWidget(QLabel("Execute"), 3, 0)

        self.cb_ur = QCheckBox()
        self.cb_uw = QCheckBox()
        self.cb_ux = QCheckBox()

        self.cb_gr = QCheckBox()
        self.cb_gw = QCheckBox()
        self.cb_gx = QCheckBox()

        self.cb_or = QCheckBox()
        self.cb_ow = QCheckBox()
        self.cb_ox = QCheckBox()

        perm_layout.addWidget(self.cb_ur, 1, 1)
        perm_layout.addWidget(self.cb_uw, 2, 1)
        perm_layout.addWidget(self.cb_ux, 3, 1)

        perm_layout.addWidget(self.cb_gr, 1, 2)
        perm_layout.addWidget(self.cb_gw, 2, 2)
        perm_layout.addWidget(self.cb_gx, 3, 2)

        perm_layout.addWidget(self.cb_or, 1, 3)
        perm_layout.addWidget(self.cb_ow, 2, 3)
        perm_layout.addWidget(self.cb_ox, 3, 3)

        # Populate permissions checkboxes
        if raw_mode is not None:
            # Mask out permission bits
            mode = stat.S_IMODE(raw_mode)
            self.cb_ur.setChecked(bool(mode & stat.S_IRUSR))
            self.cb_uw.setChecked(bool(mode & stat.S_IWUSR))
            self.cb_ux.setChecked(bool(mode & stat.S_IXUSR))

            self.cb_gr.setChecked(bool(mode & stat.S_IRGRP))
            self.cb_gw.setChecked(bool(mode & stat.S_IWGRP))
            self.cb_gx.setChecked(bool(mode & stat.S_IXGRP))

            self.cb_or.setChecked(bool(mode & stat.S_IROTH))
            self.cb_ow.setChecked(bool(mode & stat.S_IWOTH))
            self.cb_ox.setChecked(bool(mode & stat.S_IXOTH))
        else:
            self.perm_group.setEnabled(False)

        layout.addWidget(self.perm_group)

        # OK / Cancel Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept_changes)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept_changes(self):
        # Calculate new octal mode
        mode = 0
        if self.cb_ur.isChecked(): mode |= stat.S_IRUSR
        if self.cb_uw.isChecked(): mode |= stat.S_IWUSR
        if self.cb_ux.isChecked(): mode |= stat.S_IXUSR

        if self.cb_gr.isChecked(): mode |= stat.S_IRGRP
        if self.cb_gw.isChecked(): mode |= stat.S_IWGRP
        if self.cb_gx.isChecked(): mode |= stat.S_IXGRP

        if self.cb_or.isChecked(): mode |= stat.S_IROTH
        if self.cb_ow.isChecked(): mode |= stat.S_IWOTH
        if self.cb_ox.isChecked(): mode |= stat.S_IXOTH

        self.new_mode = mode
        self.accept()


class InAppEditorDialog(QDialog):
    def __init__(self, parent, filename, filepath, is_remote=False, sftp_client=None):
        super().__init__(parent)
        self.setWindowTitle(f"Internal Editor - {filename}")
        self.resize(750, 550)
        self.setStyleSheet(DARK_THEME_QSS)
        self.filepath = filepath
        self.is_remote = is_remote
        self.sftp_client = sftp_client
        self.filename = filename

        layout = QVBoxLayout(self)
        
        info_lbl = QLabel(f"Editing: {filepath} ({'Remote' if is_remote else 'Local'})")
        info_lbl.setStyleSheet("font-weight: bold; color: #89b4fa;")
        layout.addWidget(info_lbl)

        self.editor = QTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setStyleSheet("background-color: #11111b; color: #cdd6f4; border: 1px solid #45475a; padding: 5px;")
        layout.addWidget(self.editor)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_content)
        save_btn.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-weight: bold;")
        
        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold;")
        
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.load_file()

    def load_file(self):
        try:
            if self.is_remote:
                with self.sftp_client.open(self.filepath, "r") as f:
                    content = f.read()
                    if isinstance(content, bytes):
                        content = content.decode('utf-8', errors='ignore')
                    self.editor.setPlainText(content)
            else:
                with open(self.filepath, "r", encoding="utf-8", errors="ignore") as f:
                    self.editor.setPlainText(f.read())
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Could not load file:\n{e}")
            self.reject()

    def save_content(self):
        try:
            text = self.editor.toPlainText()
            if self.is_remote:
                with self.sftp_client.open(self.filepath, "w") as f:
                    f.write(text)
                self.parent().log_message(f"✓ Saved and uploaded remote file: {self.filename}")
            else:
                with open(self.filepath, "w", encoding="utf-8") as f:
                    f.write(text)
                self.parent().log_message(f"✓ Saved local file: {self.filepath}")
            QMessageBox.information(self, "Saved", "File saved successfully.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save file:\n{e}")


class FileTableWidget(QTableWidget):
    def __init__(self, rows, cols, parent_app, is_remote=False):
        super().__init__(rows, cols)
        self.parent_app = parent_app
        self.is_remote = is_remote
        
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def selected_file_rows(self):
        return sorted({index.row() for index in self.selectedIndexes()
                       if not self.isRowHidden(index.row())})

    def mousePressEvent(self, event):
        row = self.rowAt(event.position().toPoint().y())
        self.selection_drag_anchor = None
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and row >= 0 and row not in self.selected_file_rows()):
            # Dragging an unselected row selects a range. Dragging an existing
            # selection retains the file transfer drag/drop behavior.
            self.selection_drag_anchor = row
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.selection_drag_anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            row = self.rowAt(event.position().toPoint().y())
            if row >= 0:
                first, last = sorted((self.selection_drag_anchor, row))
                selection = QItemSelection(self.model().index(first, 0),
                                           self.model().index(last, self.columnCount() - 1))
                self.selectionModel().select(selection,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.selection_drag_anchor = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            if not event.isAutoRepeat():
                self.parent_app.delete_selected_files(self.is_remote)
            event.accept()
            return
        prefix = "remote" if self.is_remote else "local"
        for key, method in ((QKeySequence.StandardKey.Copy, "copy_selected"),
                            (QKeySequence.StandardKey.Cut, "cut_selected"),
                            (QKeySequence.StandardKey.Paste, "paste")):
            if event.matches(key):
                getattr(self.parent_app, f"{prefix}_{method}")()
                event.accept()
                return
        super().keyPressEvent(event)

    def local_drop_paths(self, mime):
        """Read Explorer/Desktop URLs without interpreting remote URLs as files."""
        return list(dict.fromkeys(
            os.path.normpath(url.toLocalFile()) for url in mime.urls()
            if url.isLocalFile() and url.toLocalFile()
            and os.path.exists(url.toLocalFile())))

    def accept_file_drag(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            if (not self.local_drop_paths(mime)
                    or (self.is_remote and not self.parent_app.sftp_client)):
                event.ignore()
                return
            # Explorer may propose Move (e.g. Shift-drag). Uploads always copy:
            # accepting Move would allow the source application to delete files.
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        elif (mime.hasFormat("application/x-qabstractitemmodeldatalist")
              and isinstance(event.source(), FileTableWidget)):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragEnterEvent(self, event):
        self.accept_file_drag(event)

    def dragMoveEvent(self, event):
        self.accept_file_drag(event)

    def startDrag(self, supportedActions):
        selected_indexes = self.selectedIndexes()
        if not selected_indexes:
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        
        if not self.is_remote:
            urls = []
            rows = set(idx.row() for idx in selected_indexes)
            for row in rows:
                item = self.item(row, 0)
                if item:
                    local_path = item.data(Qt.ItemDataRole.UserRole)
                    if os.path.exists(local_path):
                        urls.append(QUrl.fromLocalFile(local_path))
            mime_data.setUrls(urls)
            
        mime_data.setData("application/x-qabstractitemmodeldatalist", b"custom_sftp_drag")
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)

    def dropEvent(self, event):
        mime = event.mimeData()
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        target_row = self.rowAt(pos.y())
        
        if mime.hasUrls():
            local_paths = self.local_drop_paths(mime)
            if not local_paths or (self.is_remote and not self.parent_app.sftp_client):
                event.ignore()
                return
            if local_paths:
                if self.is_remote:
                    target_dir = self.parent_app.current_remote_dir
                    if target_row != -1:
                        name_item = self.item(target_row, 0)
                        if name_item:
                            target_name, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
                            if is_dir:
                                target_dir = posixpath.normpath(posixpath.join(
                                    self.parent_app.current_remote_dir, target_name))
                    self.parent_app.upload_multiple_files(local_paths, target_dir)
                else:
                    target_dir = self.parent_app.current_local_dir
                    if target_row != -1:
                        name_item = self.item(target_row, 0)
                        if name_item:
                            local_path = name_item.data(Qt.ItemDataRole.UserRole)
                            if os.path.isdir(local_path):
                                target_dir = local_path
                    self.parent_app.copy_local_files(local_paths, target_dir)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            
        elif mime.hasFormat("application/x-qabstractitemmodeldatalist"):
            source = event.source()
            if not isinstance(source, FileTableWidget):
                event.ignore()
                return

            if source == self:
                if target_row == -1:
                    event.ignore()
                    return
                
                name_item = self.item(target_row, 0)
                if not name_item:
                    event.ignore()
                    return
                
                selected_rows = set(idx.row() for idx in self.selectedIndexes())
                if target_row in selected_rows:
                    event.ignore()
                    return

                if self.is_remote:
                    target_name, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
                    if is_dir:
                        target_dir = self.parent_app.current_remote_dir.rstrip('/') + "/" + target_name
                        remote_paths = []
                        for row in selected_rows:
                            item = self.item(row, 0)
                            if item:
                                fname, _ = item.data(Qt.ItemDataRole.UserRole)
                                remote_paths.append(self.parent_app.current_remote_dir.rstrip('/') + "/" + fname)
                        if remote_paths:
                            self.parent_app.move_remote_files(remote_paths, target_dir)
                        event.acceptProposedAction()
                else:
                    local_target_dir = name_item.data(Qt.ItemDataRole.UserRole)
                    if os.path.isdir(local_target_dir):
                        local_paths = []
                        for row in selected_rows:
                            item = self.item(row, 0)
                            if item:
                                local_paths.append(item.data(Qt.ItemDataRole.UserRole))
                        if local_paths:
                            self.parent_app.move_local_files(local_paths, local_target_dir)
                        event.acceptProposedAction()
                return

            msg_box = QMessageBox(self.parent_app)
            msg_box.setWindowTitle("File Transfer Option")
            msg_box.setText("Choose action for selected items:")
            copy_btn = msg_box.addButton("Copy", QMessageBox.ButtonRole.YesRole)
            move_btn = msg_box.addButton("Move (Cut & Paste)", QMessageBox.ButtonRole.NoRole)
            cancel_btn = msg_box.addButton(QMessageBox.StandardButton.Cancel)
            msg_box.setDefaultButton(copy_btn)
            
            msg_box.setStyleSheet(DARK_THEME_QSS)
            msg_box.exec()
            clicked = msg_box.clickedButton()
            
            if clicked == cancel_btn:
                event.ignore()
                return
            
            is_move = (clicked == move_btn)

            if self.is_remote and not source.is_remote:
                target_dir = self.parent_app.current_remote_dir
                if target_row != -1:
                    name_item = self.item(target_row, 0)
                    if name_item:
                        target_name, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
                        if is_dir:
                            target_dir = self.parent_app.current_remote_dir.rstrip('/') + "/" + target_name

                selected_rows = set(idx.row() for idx in source.selectedIndexes())
                local_paths = []
                for row in selected_rows:
                    item = source.item(row, 0)
                    if item:
                        local_paths.append(item.data(Qt.ItemDataRole.UserRole))
                if local_paths:
                    self.parent_app.upload_multiple_files(local_paths, target_dir, delete_source=is_move)
                event.acceptProposedAction()
            
            elif not self.is_remote and source.is_remote:
                target_dir = self.parent_app.current_local_dir
                if target_row != -1:
                    name_item = self.item(target_row, 0)
                    if name_item:
                        local_path = name_item.data(Qt.ItemDataRole.UserRole)
                        if os.path.isdir(local_path):
                            target_dir = local_path

                selected_rows = set(idx.row() for idx in source.selectedIndexes())
                filenames = []
                for row in selected_rows:
                    item = source.item(row, 0)
                    if item:
                        filename, is_dir = item.data(Qt.ItemDataRole.UserRole)
                        if not is_dir:
                            filenames.append(filename)
                if filenames:
                    self.parent_app.download_multiple_files(filenames, target_dir, delete_source=is_move)
                event.acceptProposedAction()

def is_text_file(filename):
    exts = {'.txt', '.py', '.json', '.ini', '.cfg', '.conf', '.yaml', '.yml', '.xml', '.html', '.css', '.js', '.sh', '.env', '.md', '.log'}
    _, ext = os.path.splitext(filename.lower())
    return ext in exts


class SingleFileTransferWorker(QThread):
    progress_signal = pyqtSignal(int, int, float)  # transferred, total, speed (bytes/sec)
    finished_signal = pyqtSignal(bool, str)        # success, error_message

    def __init__(self, sftp_client, direction, source, dest, size):
        super().__init__()
        self.sftp_client = sftp_client
        self.direction = direction  # "upload" or "download"
        self.source = source
        self.dest = dest
        self.size = size
        self.is_cancelled = False
        self.last_time = datetime.datetime.now()
        self.last_bytes = 0

    def progress_callback(self, transferred, total):
        if self.is_cancelled:
            raise Exception("Cancelled")
        
        now = datetime.datetime.now()
        dt = (now - self.last_time).total_seconds()
        if dt >= 0.5 or transferred == total:
            bytes_sent = transferred - self.last_bytes
            speed = bytes_sent / dt if dt > 0 else 0
            self.progress_signal.emit(transferred, total, speed)
            self.last_time = now
            self.last_bytes = transferred

    def run(self):
        try:
            if self.direction == "upload":
                if os.path.isdir(self.source):
                    upload_directory(self.sftp_client, self.source, self.dest,
                                     self.progress_callback, lambda: self.is_cancelled)
                else:
                    self.sftp_client.put(self.source, self.dest, callback=self.progress_callback)
            else:
                self.sftp_client.get(self.source, self.dest, callback=self.progress_callback)
            
            if self.is_cancelled:
                self.finished_signal.emit(False, "Cancelled")
            else:
                self.finished_signal.emit(True, "")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class SFTPWorker(QThread):
    finished_signal = pyqtSignal(str, object)  # action, result
    progress_signal = pyqtSignal(int, int)    # transferred, total
    error_signal = pyqtSignal(str, str)        # action, error_msg

    def __init__(self, action, credentials=None, **kwargs):
        super().__init__()
        self.action = action
        self.credentials = credentials
        self.args = kwargs
        self.ssh = None
        self.sftp = None

    def run(self):
        try:
            if self.action == "connect":
                host, port, user, pwd, key_path, otp = self.credentials
                if self.args.get("protocol") == OZ_PROTOCOL:
                    client = OZClient(host, user, pwd, self.args.get("use_usl", False))
                    self.finished_signal.emit("connect", (None, client))
                    return
                if self.args.get("protocol") == "FTP":
                    ftp = FTPClient(host, port, user, pwd, self.args.get("encoding", "utf-8"))
                    self.finished_signal.emit("connect", (None, ftp))
                    return
                self.ssh = paramiko.SSHClient()
                self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                pkey = None
                if key_path and os.path.exists(key_path):
                    for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]:
                        try:
                            pkey = key_class.from_private_key_file(key_path, password=pwd)
                            break
                        except Exception:
                            try:
                                pkey = key_class.from_private_key_file(key_path)
                                break
                            except Exception:
                                continue

                try:
                    # OTP-enabled servers normally use SSH keyboard-interactive
                    # authentication.  Answer each challenge by its prompt text.
                    if otp:
                        def open_transport():
                            new_transport = paramiko.Transport((host, port))
                            new_transport.start_client(timeout=10)
                            return new_transport

                        def make_interactive_handler(start_count=0):
                            challenge_count = start_count

                            def interactive_handler(title, instructions, prompt_list):
                                nonlocal challenge_count
                                answers = []
                                for prompt, _echo in prompt_list:
                                    prompt_lower = prompt.lower()
                                    if any(word in prompt_lower for word in ("verification", "otp", "token", "code")):
                                        answers.append(otp)
                                    elif "password" in prompt_lower:
                                        answers.append(pwd)
                                    else:
                                        answers.append(pwd if challenge_count == 0 else otp)
                                    challenge_count += 1
                                return answers

                            return interactive_handler

                        # Match SSH Secure Shell's configured preference:
                        # Public Key -> Keyboard Interactive -> Password.
                        transport = open_transport()
                        try:
                            if pkey:
                                transport.auth_publickey(user, pkey)
                            if not transport.is_authenticated():
                                transport.auth_interactive(user, make_interactive_handler())
                        except paramiko.AuthenticationException:
                            # Compatibility fallback for servers that implement
                            # password and OTP as two separate auth methods.
                            transport.close()
                            transport = open_transport()
                            remaining = transport.auth_password(user, pwd)
                            if remaining and not transport.is_authenticated():
                                transport.auth_interactive(user, make_interactive_handler(1))

                        if not transport.is_authenticated():
                            raise paramiko.AuthenticationException("Password/OTP authentication failed")

                        self.ssh._transport = transport
                        sftp = EncodingSFTPClient.from_transport(transport)
                        self.finished_signal.emit("connect", (self.ssh, sftp))
                        return

                    if pkey:
                        self.ssh.connect(host, port=port, username=user, pkey=pkey, timeout=10)
                    else:
                        self.ssh.connect(host, port=port, username=user, password=pwd, timeout=10, allow_agent=False, look_for_keys=False)
                    sftp = EncodingSFTPClient.from_transport(self.ssh.get_transport())
                    self.finished_signal.emit("connect", (self.ssh, sftp))
                except paramiko.ssh_exception.AuthenticationException as auth_err:
                    if not pkey and pwd:
                        try:
                            transport = paramiko.Transport((host, port))
                            transport.start_client()
                            
                            def interactive_handler(title, instructions, prompt_list):
                                return [pwd] * len(prompt_list)
                            
                            transport.auth_interactive_dumb(user, interactive_handler)
                            sftp = EncodingSFTPClient.from_transport(transport)
                            self.finished_signal.emit("connect", (self.ssh, sftp))
                        except Exception:
                            raise auth_err
                    else:
                        raise auth_err

            elif self.action == "get_stats":
                sftp = self.args.get("sftp")
                if not sftp:
                    self.finished_signal.emit("get_stats", None)
                    return
                
                transport = sftp.get_channel().get_transport()
                
                # Exec memory info
                mem_info = "N/A"
                for cmd in ["free -m", "/usr/bin/free -m", "/bin/free -m"]:
                    try:
                        chan = transport.open_session(timeout=5)
                        chan.settimeout(3)
                        chan.exec_command(cmd)
                        output = chan.makefile('r').read()
                        err = chan.makefile_stderr('r').read()
                        chan.close()
                        
                        if isinstance(output, bytes):
                            output = output.decode('utf-8', errors='ignore')
                        if isinstance(err, bytes):
                            err = err.decode('utf-8', errors='ignore')
                        
                        lines = output.strip().split('\n')
                        if len(lines) >= 2:
                            parts = lines[1].split()
                            if len(parts) >= 3 and parts[0].startswith("Mem:"):
                                total_mem = int(parts[1])
                                used_mem = int(parts[2])
                                mem_info = f"{used_mem} / {total_mem} MB ({round((used_mem/total_mem)*100, 1)}%)"
                                break
                    except Exception:
                        continue

                # Exec disk info
                disk_info = "N/A"
                for cmd in ["df -h .", "/bin/df -h .", "/usr/bin/df -h ."]:
                    try:
                        chan = transport.open_session(timeout=5)
                        chan.settimeout(3)
                        chan.exec_command(cmd)
                        output = chan.makefile('r').read()
                        err = chan.makefile_stderr('r').read()
                        chan.close()
                        
                        if isinstance(output, bytes):
                            output = output.decode('utf-8', errors='ignore')
                        if isinstance(err, bytes):
                            err = err.decode('utf-8', errors='ignore')
                        
                        lines = output.strip().split('\n')
                        if len(lines) >= 2:
                            for line in lines[1:]:
                                parts = line.split()
                                pct_idx = -1
                                for idx, part in enumerate(parts):
                                    if part.endswith('%'):
                                        pct_idx = idx
                                        break
                                if pct_idx != -1 and pct_idx >= 2:
                                    percent = parts[pct_idx]
                                    used = parts[pct_idx - 2]
                                    size = parts[pct_idx - 3]
                                    disk_info = f"{used} / {size} ({percent})"
                                    break
                            if disk_info != "N/A":
                                break
                    except Exception:
                        continue

                self.finished_signal.emit("get_stats", {"mem": mem_info, "disk": disk_info})

            elif self.action == "list_dir":
                sftp = self.args.get("sftp")
                path = self.args.get("path")
                files = []
                for entry in sftp.listdir_attr(path):
                    is_dir = stat.S_ISDIR(entry.st_mode)
                    if stat.S_ISLNK(entry.st_mode):
                        # Keep the link path for navigation and file operations.
                        target_is_dir = getattr(entry, "target_is_dir", None)
                        if target_is_dir is not None:
                            is_dir = target_is_dir
                        else:
                            try:
                                target = sftp.stat(posixpath.join(path, entry.filename))
                                is_dir = stat.S_ISDIR(target.st_mode)
                            except OSError:
                                # A broken or inaccessible link must not hide the listing.
                                pass
                    size = entry.st_size
                    mtime = entry.st_mtime
                    mode = stat.filemode(entry.st_mode)
                    
                    owner = str(entry.st_uid)
                    group = str(entry.st_gid)
                    if entry.longname:
                        parts = entry.longname.split()
                        if len(parts) >= 4:
                            owner = parts[2]
                            group = parts[3]
                            
                    files.append({
                        "name": entry.filename,
                        "is_dir": is_dir,
                        "size": size,
                        "mtime": mtime,
                        "mode": mode,
                        "raw_mode": entry.st_mode,
                        "owner": owner,
                        "group": group
                    })
                files.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
                self.finished_signal.emit("list_dir", files)

            elif self.action in ["download", "upload"]:
                sftp = self.args.get("sftp")
                remote_path = self.args.get("remotepath")
                local_path = self.args.get("localpath")
                progress_callback = lambda transferred, total: self.progress_signal.emit(transferred, total)

                if self.action == "download":
                    sftp.get(remote_path, local_path, callback=progress_callback)
                    self.finished_signal.emit("download", local_path)
                else:
                    sftp.put(local_path, remote_path, callback=progress_callback)
                    self.finished_signal.emit("upload", remote_path)

            elif self.action == "run_command":
                sftp = self.args.get("sftp")
                if isinstance(sftp, (FTPClient, OZClient)):
                    raise ValueError("This operation requires an SFTP/SSH connection.")
                cmd = self.args.get("cmd")
                transport = sftp.get_channel().get_transport()
                chan = transport.open_session()
                chan.settimeout(15)
                chan.exec_command(cmd)
                stdout = chan.makefile('r').read()
                stderr = chan.makefile_stderr('r').read()
                chan.close()
                if isinstance(stdout, bytes):
                    stdout = stdout.decode('utf-8', errors='ignore')
                if isinstance(stderr, bytes):
                    stderr = stderr.decode('utf-8', errors='ignore')
                self.finished_signal.emit("run_command", {"stdout": stdout, "stderr": stderr, "cmd": cmd})

            elif self.action == "download_multiple":
                sftp = self.args.get("sftp")
                remotepaths = self.args.get("remotepaths")
                localdir = self.args.get("localdir")
                delete_source = self.args.get("delete_source", False)
                total = len(remotepaths)
                for idx, rpath in enumerate(remotepaths):
                    filename = os.path.basename(rpath)
                    lpath = os.path.join(localdir, filename)
                    sftp.get(rpath, lpath)
                    if delete_source:
                        sftp.remove(rpath)
                    self.progress_signal.emit(idx + 1, total)
                self.finished_signal.emit("download_multiple", localdir)

            elif self.action == "upload_multiple":
                sftp = self.args.get("sftp")
                localpaths = self.args.get("localpaths")
                remotedir = self.args.get("remotedir")
                delete_source = self.args.get("delete_source", False)
                total = len(localpaths)
                for idx, lpath in enumerate(localpaths):
                    if os.path.isdir(lpath):
                        continue
                    filename = os.path.basename(lpath)
                    rpath = remotedir.rstrip('/') + "/" + filename
                    sftp.put(lpath, rpath)
                    if delete_source:
                        os.remove(lpath)
                    self.progress_signal.emit(idx + 1, total)
                self.finished_signal.emit("upload_multiple", remotedir)

            elif self.action == "move_remote_multiple":
                sftp = self.args.get("sftp")
                remotepaths = self.args.get("remotepaths")
                destdir = self.args.get("destdir")
                total = len(remotepaths)
                for idx, rpath in enumerate(remotepaths):
                    filename = os.path.basename(rpath)
                    destpath = destdir.rstrip('/') + "/" + filename
                    sftp.rename(rpath, destpath)
                    self.progress_signal.emit(idx + 1, total)
                self.finished_signal.emit("move_remote_multiple", destdir)

            elif self.action == "copy_remote_multiple":
                sftp = self.args.get("sftp")
                remotepaths = self.args.get("remotepaths")
                destdir = self.args.get("destdir")
                transport = None if isinstance(sftp, (FTPClient, OZClient)) else sftp.get_channel().get_transport()
                total = len(remotepaths)
                for idx, rpath in enumerate(remotepaths):
                    filename = os.path.basename(rpath)
                    destpath = destdir.rstrip('/') + "/" + filename
                    if posixpath.normpath(rpath) == posixpath.normpath(destpath):
                        raise ValueError("Source and destination are the same file.")
                    if isinstance(sftp, (FTPClient, OZClient)):
                        with tempfile.TemporaryDirectory(prefix="ftp_copy_") as directory:
                            local_path = os.path.join(directory, "content")
                            sftp.get(rpath, local_path)
                            sftp.put(local_path, destpath)
                        self.progress_signal.emit(idx + 1, total)
                        continue
                    # Copy via SSH execution
                    chan = transport.open_session()
                    chan.settimeout(5)
                    chan.exec_command(f"cp -r '{rpath}' '{destpath}'")
                    chan.close()
                    self.progress_signal.emit(idx + 1, total)
                self.finished_signal.emit("copy_remote_multiple", destdir)

            elif self.action == "delete_multiple":
                errors = []
                for path, is_dir in self.args["items"]:
                    try:
                        errors.extend(delete_remote_item(self.args["sftp"], path, is_dir))
                    except Exception as error:
                        errors.append(f"{path}: {error}")
                self.finished_signal.emit("delete_multiple", errors)

            elif self.action == "delete":
                sftp = self.args.get("sftp")
                path = self.args.get("path")
                is_dir = self.args.get("is_dir")
                errors = delete_remote_item(sftp, path, is_dir)
                if errors:
                    raise OSError("\n".join(errors))
                self.finished_signal.emit("delete", path)

            elif self.action == "mkdir":
                sftp = self.args.get("sftp")
                path = self.args.get("path")
                sftp.mkdir(path)
                self.finished_signal.emit("mkdir", path)

            elif self.action == "rename":
                sftp = self.args.get("sftp")
                oldpath = self.args.get("oldpath")
                newpath = self.args.get("newpath")
                sftp.rename(oldpath, newpath)
                self.finished_signal.emit("rename", newpath)

            elif self.action == "create_file":
                sftp = self.args.get("sftp")
                path = self.args.get("path")
                with sftp.open(path, "w") as f:
                    f.write("")
                self.finished_signal.emit("create_file", path)

            elif self.action == "chmod":
                sftp = self.args.get("sftp")
                path = self.args.get("path")
                mode = self.args.get("mode")
                sftp.chmod(path, mode)
                self.finished_signal.emit("chmod", path)

        except Exception as e:
            self.error_signal.emit(self.action, str(e))


class SFTPClientApp(QMainWindow):
    connection_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Client (SFTP / FTP)")
        self.setWindowIcon(QIcon(APP_ICON_PATH))
        self.resize(1200, 750)
        self.setStyleSheet(DARK_THEME_QSS)

        self.loading_dialogs = {}
        self.running_workers = set()
        self.embedded_session = False

        # Connection properties
        self.ssh_client = None
        self.sftp_client = None
        self.ssh_terminal = None
        self.current_remote_dir = "/"
        self.current_local_dir = os.path.expanduser("~")
        self.local_navigation_paths = [self.current_local_dir]
        self.local_navigation_index = 0
        self.remote_navigation_paths = []
        self.remote_navigation_index = -1
        
        # Load saved sessions config
        self.sessions_file = os.path.join(os.path.expanduser("~"), "sftp_sessions_db.json")
        self.saved_sessions = self.load_sessions()

        # Timer for resources stats
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(10000)
        self.stats_timer.timeout.connect(self.update_server_stats)

        # File watcher for remote edit-on-save
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.fileChanged.connect(self.on_watched_file_changed)
        self.watched_files = {}  # local_path -> remote_path
        self.auto_upload_timers = {}
        self.auto_upload_workers = {}
        self.pending_auto_uploads = set()

        # Clipboard property for Copy/Cut/Paste
        self.app_clipboard = None  # Struct: {"action": "copy"|"cut", "source_is_remote": bool, "paths": []}

        # Folder Bookmarks Config
        self.folder_bookmarks_file = os.path.join(os.path.expanduser("~"), "sftp_folder_bookmarks.json")
        self.local_folder_bookmarks, self.remote_folder_bookmarks = self.load_folder_bookmarks()
        self.last_remote_files = []
        self.transfer_queue = []
        self.active_workers = {}
        self.job_counter = 0

        self.init_ui()
        for is_remote, table in ((False, self.local_table), (True, self.remote_table)):
            pane = table.parentWidget()
            for widget in [pane] + pane.findChildren(QWidget):
                widget.setProperty("remote_navigation_pane", is_remote)
                widget.installEventFilter(self)
        self.populate_sessions_dropdown()
        self.populate_folder_bookmarks("local")
        self.populate_folder_bookmarks("remote")

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(10)

        # 1. Connection & Bookmarks Manager Panel
        conn_group = QGroupBox("Connection Manager")
        conn_layout = QVBoxLayout(conn_group)
        conn_layout.setSpacing(8)

        # Bookmarks row
        bookmark_row = QHBoxLayout()
        bookmark_row.addWidget(QLabel("Bookmarks:"))
        self.sessions_combo = QComboBox()
        self.sessions_combo.currentIndexChanged.connect(self.load_selected_session)
        bookmark_row.addWidget(self.sessions_combo, 1)

        self.save_session_btn = QPushButton("Save Bookmark")
        self.save_session_btn.setStyleSheet("background-color: #a6e3a1; color: #11111b;")
        self.save_session_btn.clicked.connect(self.save_current_session)
        self.del_session_btn = QPushButton("Delete")
        self.del_session_btn.setStyleSheet("background-color: #f38ba8; color: #11111b;")
        self.del_session_btn.clicked.connect(self.delete_current_session)

        bookmark_row.addWidget(self.save_session_btn)
        bookmark_row.addWidget(self.del_session_btn)
        bookmark_row.addStretch(1)
        conn_layout.addLayout(bookmark_row)

        # Server Credentials row
        cred_row = QHBoxLayout()
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["SFTP", "FTP", OZ_PROTOCOL])
        self.protocol_combo.setMinimumWidth(75)
        self.ftp_encoding_combo = QComboBox()
        self.ftp_encoding_combo.addItems(["utf-8", "cp949"])
        self.ftp_encoding_combo.setMinimumWidth(85)
        self.ftp_encoding_combo.setToolTip("FTP filename encoding (CP949 for older Korean servers)")
        self.ftp_encoding_combo.setEnabled(False)
        self.oz_usl_checkbox = QCheckBox("USL")
        self.oz_usl_checkbox.setToolTip("OZ 서버에서 USL 보안 통신을 사용하는 경우 선택하세요.")
        self.oz_usl_checkbox.setVisible(False)
        self.host_input = QLineEdit("localhost")
        self.host_input.setPlaceholderText("Host")
        self.port_input = QLineEdit("22")
        self.port_input.setFixedWidth(45)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Username")
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setPlaceholderText("Password / Passphrase")

        self.otp_input = QLineEdit()
        self.otp_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.otp_input.setPlaceholderText("Current OTP (Optional)")
        
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("Private Key (Optional)")
        self.key_btn = QPushButton("Browse...")
        self.key_btn.setFixedWidth(75)
        self.key_btn.clicked.connect(self.browse_key_file)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_sftp)

        cred_row.addWidget(self.protocol_combo)
        cred_row.addWidget(self.ftp_encoding_combo)
        cred_row.addWidget(self.oz_usl_checkbox)
        self.protocol_combo.currentTextChanged.connect(self.on_protocol_changed)
        cred_row.addWidget(QLabel("Host:"))
        cred_row.addWidget(self.host_input, 2)
        cred_row.addWidget(QLabel("Port:"))
        cred_row.addWidget(self.port_input)
        cred_row.addWidget(QLabel("User:"))
        cred_row.addWidget(self.user_input, 1)
        cred_row.addWidget(QLabel("Password:"))
        cred_row.addWidget(self.pass_input, 1)
        cred_row.addWidget(QLabel("OTP:"))
        cred_row.addWidget(self.otp_input, 1)
        cred_row.addWidget(QLabel("Key:"))
        cred_row.addWidget(self.key_input, 2)
        cred_row.addWidget(self.key_btn)
        cred_row.addWidget(self.connect_btn)
        conn_layout.addLayout(cred_row)

        main_layout.addWidget(conn_group)

        # 2. Main File Splitter (Local & Remote panes)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Local Pane
        local_widget = QWidget()
        local_layout = QVBoxLayout(local_widget)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(6)
        
        local_header = QHBoxLayout()
        self.local_path_input = QLineEdit(self.current_local_dir)
        self.local_path_input.setStyleSheet("font-weight: bold; color: #a6e3a1; background-color: #11111b; border: 1px solid #45475a;")
        self.local_path_input.returnPressed.connect(self.local_path_entered)
        
        from PyQt6.QtWidgets import QCompleter
        from PyQt6.QtGui import QFileSystemModel
        from PyQt6.QtCore import QDir
        self.local_completer = QCompleter(self)
        self.local_completer_model = QFileSystemModel(self.local_completer)
        self.local_completer_model.setRootPath("")
        self.local_completer_model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot)
        self.local_completer.setModel(self.local_completer_model)
        self.local_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.local_path_input.setCompleter(self.local_completer)
        
        self.local_bookmark_combo = QComboBox()
        self.local_bookmark_combo.setFixedWidth(130)
        self.local_bookmark_combo.currentIndexChanged.connect(self.local_bookmark_changed)
        
        local_up_btn = QPushButton("←")
        local_up_btn.setFixedWidth(40)
        local_up_btn.setStyleSheet("padding: 2px; font-size: 16px; font-weight: bold;")
        local_up_btn.clicked.connect(self.local_navigate_up)
        
        local_refresh_btn = QPushButton("⟳")
        local_refresh_btn.setFixedWidth(40)
        local_refresh_btn.setStyleSheet("padding: 2px; font-size: 16px; font-weight: bold;")
        local_refresh_btn.clicked.connect(self.populate_local_dir)
        
        local_header.addWidget(self.local_path_input, 1)
        local_header.addWidget(self.local_bookmark_combo)
        local_header.addWidget(local_up_btn)
        local_header.addWidget(local_refresh_btn)
        local_layout.addLayout(local_header)

        # Local Filter Search & Show Hidden
        local_search_lay = QHBoxLayout()
        self.local_search = QLineEdit()
        self.local_search.setPlaceholderText("🔍 Search/Filter local files...")
        self.local_search.textChanged.connect(lambda text: self.filter_table(self.local_table, text))
        
        self.local_show_hidden = QCheckBox("Show Hidden")
        self.local_show_hidden.setChecked(False)
        self.local_show_hidden.stateChanged.connect(lambda: self.populate_local_dir())
        
        local_search_lay.addWidget(self.local_search, 1)
        local_search_lay.addWidget(self.local_show_hidden)
        local_layout.addLayout(local_search_lay)

        # Local Custom Drag-Drop Table
        self.local_table = FileTableWidget(0, 5, self, is_remote=False)
        self.local_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.local_table.setHorizontalHeaderLabels(["Name", "Size (KB)", "Type", "Date Modified", "Owner/Group"])
        self.local_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.local_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.local_table.setAlternatingRowColors(True)
        self.local_table.setSortingEnabled(True)
        self.local_table.doubleClicked.connect(self.local_table_double_click)
        self.local_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.local_table.customContextMenuRequested.connect(self.show_local_context_menu)
        local_layout.addWidget(self.local_table)
        splitter.addWidget(local_widget)

        # Remote Pane
        remote_widget = QWidget()
        remote_layout = QVBoxLayout(remote_widget)
        remote_layout.setSpacing(6)

        remote_header = QHBoxLayout()
        self.remote_path_input = QLineEdit("Remote Path: Not Connected")
        self.remote_path_input.setStyleSheet("font-weight: bold; color: #f38ba8; background-color: #11111b; border: 1px solid #45475a;")
        self.remote_path_input.setEnabled(False)
        self.remote_path_input.returnPressed.connect(self.remote_path_entered)
        
        from PyQt6.QtCore import QStringListModel
        from PyQt6.QtWidgets import QCompleter
        self.remote_history = ["/"]
        self.remote_completer = QCompleter(self)
        self.remote_completer_model = QStringListModel(self.remote_history, self.remote_completer)
        self.remote_completer.setModel(self.remote_completer_model)
        self.remote_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.remote_path_input.setCompleter(self.remote_completer)
        
        self.remote_bookmark_combo = QComboBox()
        self.remote_bookmark_combo.setFixedWidth(130)
        self.remote_bookmark_combo.currentIndexChanged.connect(self.remote_bookmark_changed)
        self.remote_bookmark_combo.setEnabled(False)
        
        self.remote_up_btn = QPushButton("←")
        self.remote_up_btn.setFixedWidth(40)
        self.remote_up_btn.setStyleSheet("padding: 2px; font-size: 16px; font-weight: bold;")
        self.remote_up_btn.setEnabled(False)
        self.remote_up_btn.clicked.connect(self.remote_navigate_up)
        
        self.remote_refresh_btn = QPushButton("⟳")
        self.remote_refresh_btn.setFixedWidth(40)
        self.remote_refresh_btn.setStyleSheet("padding: 2px; font-size: 16px; font-weight: bold;")
        self.remote_refresh_btn.setEnabled(False)
        self.remote_refresh_btn.clicked.connect(self.fetch_remote_dir)
        
        remote_header.addWidget(self.remote_path_input, 1)
        remote_header.addWidget(self.remote_bookmark_combo)
        remote_header.addWidget(self.remote_up_btn)
        remote_header.addWidget(self.remote_refresh_btn)
        remote_layout.addLayout(remote_header)

        # Remote Filter Search & Show Hidden
        remote_search_lay = QHBoxLayout()
        self.remote_search = QLineEdit()
        self.remote_search.setPlaceholderText("🔍 Search/Filter remote files...")
        self.remote_search.textChanged.connect(lambda text: self.filter_table(self.remote_table, text))
        
        self.remote_show_hidden = QCheckBox("Show Hidden")
        self.remote_show_hidden.setChecked(False)
        self.remote_show_hidden.stateChanged.connect(lambda: self.populate_remote_table(self.last_remote_files))
        self.remote_show_hidden.setEnabled(False)
        
        remote_search_lay.addWidget(self.remote_search, 1)
        remote_search_lay.addWidget(self.remote_show_hidden)
        remote_layout.addLayout(remote_search_lay)

        # Remote Custom Drag-Drop Table
        self.remote_table = FileTableWidget(0, 6, self, is_remote=True)
        self.remote_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.remote_table.setHorizontalHeaderLabels(["Name", "Size (KB)", "Type", "Date Modified", "Owner/Group", "Permissions"])
        self.remote_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.remote_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.remote_table.setAlternatingRowColors(True)
        self.remote_table.setSortingEnabled(True)
        self.remote_table.doubleClicked.connect(self.remote_table_double_click)
        self.remote_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.remote_table.customContextMenuRequested.connect(self.show_remote_context_menu)
        remote_layout.addWidget(self.remote_table)
        
        # Remote Command Runner
        cmd_runner_lay = QHBoxLayout()
        self.remote_cmd_input = QLineEdit()
        self.remote_cmd_input.setPlaceholderText("💻 SSH Command (e.g. uname -a, git status)...")
        self.remote_cmd_input.returnPressed.connect(self.run_remote_command)
        self.remote_cmd_input.setEnabled(False)
        
        self.remote_cmd_btn = QPushButton("Run")
        self.remote_cmd_btn.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold;")
        self.remote_cmd_btn.setFixedWidth(60)
        self.remote_cmd_btn.clicked.connect(self.run_remote_command)
        self.remote_cmd_btn.setEnabled(False)
        
        cmd_runner_lay.addWidget(self.remote_cmd_input, 1)
        cmd_runner_lay.addWidget(self.remote_cmd_btn)
        remote_layout.addLayout(cmd_runner_lay)
        
        splitter.addWidget(remote_widget)

        main_layout.addWidget(splitter, 1)

        # 3. Bottom Resource/Progress Panel
        bottom_panel = QWidget()
        bottom_layout = QHBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(5, 5, 5, 5)

        self.server_mem_lbl = QLabel("Server RAM: Not Connected")
        self.server_mem_lbl.setStyleSheet("font-weight: bold; color: #f9e2af; padding-right: 15px;")
        self.server_disk_lbl = QLabel("Server Disk: Not Connected")
        self.server_disk_lbl.setStyleSheet("font-weight: bold; color: #f9e2af; padding-right: 15px;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setTextVisible(True)

        bottom_layout.addWidget(self.server_mem_lbl)
        bottom_layout.addWidget(self.server_disk_lbl)
        bottom_layout.addWidget(self.progress_bar, 1)

        main_layout.addWidget(bottom_panel)

        # 4. Session Logs & Transfer Queue Tabs
        self.bottom_tabs = QTabWidget()
        
        self.queue_widget = QWidget()
        queue_layout = QVBoxLayout(self.queue_widget)
        queue_layout.setContentsMargins(5, 5, 5, 5)
        
        self.queue_table = QTableWidget(0, 6)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.setHorizontalHeaderLabels(["Direction", "Source", "Destination", "Size (KB)", "Progress / Speed", "Actions"])
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.setStyleSheet("QTableWidget { background-color: #11111b; gridline-color: #313244; }")
        queue_layout.addWidget(self.queue_table)
        
        self.bottom_tabs.addTab(self.queue_widget, "📂 Active Transfers (0)")

        self.ssh_terminal = SSHTerminalWidget(self)
        self.bottom_tabs.addTab(self.ssh_terminal, "🖥 SSH Terminal")

        self.log_widget = QWidget()
        log_layout_tab = QVBoxLayout(self.log_widget)
        log_layout_tab.setContentsMargins(5, 5, 5, 5)
        
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #11111b; color: #a6e3a1; font-family: 'Consolas', 'Courier New', monospace;")
        log_layout_tab.addWidget(self.log_console)
        
        self.bottom_tabs.addTab(self.log_widget, "📝 Session Logs")
        self.bottom_tabs.setFixedHeight(180)
        
        main_layout.addWidget(self.bottom_tabs)

        self.log_message("Secure File Transfer Client initialized. Ready to connect.")

        # 5. Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        self.setStatusBar(self.status_bar)

        self.populate_local_dir()

    def log_message(self, text):
        timestamp = datetime.datetime.now().strftime("[%H:%M:%S] ")
        self.log_console.append(timestamp + text)

    def load_folder_bookmarks(self):
        if os.path.exists(self.folder_bookmarks_file):
            try:
                with open(self.folder_bookmarks_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("local", {}), data.get("remote", {})
            except Exception:
                return {}, {}
        return {}, {}

    def save_folder_bookmarks(self):
        try:
            with open(self.folder_bookmarks_file, "w", encoding="utf-8") as f:
                json.dump({
                    "local": self.local_folder_bookmarks,
                    "remote": self.remote_folder_bookmarks
                }, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log_message(f"Failed to save folder bookmarks: {e}")

    def populate_folder_bookmarks(self, target):
        combo = self.local_bookmark_combo if target == "local" else self.remote_bookmark_combo
        bookmarks = self.local_folder_bookmarks if target == "local" else self.remote_folder_bookmarks
        
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("⭐ Bookmarks")
        combo.addItem("+ Add Current Folder")
        for name in sorted(bookmarks.keys()):
            combo.addItem(name)
        combo.blockSignals(False)

    def local_bookmark_changed(self, index):
        if index == 0:
            return
        if index == 1:
            self.local_bookmark_combo.setCurrentIndex(0)
            name, ok = QInputDialog.getText(self, "Save Local Bookmark", "Enter a name for this folder:")
            if ok and name.strip():
                name = name.strip()
                self.local_folder_bookmarks[name] = self.current_local_dir
                self.save_folder_bookmarks()
                self.populate_folder_bookmarks("local")
                self.local_bookmark_combo.setCurrentText(name)
            return
        
        name = self.local_bookmark_combo.currentText()
        path = self.local_folder_bookmarks.get(name)
        if path and os.path.isdir(path):
            self.set_local_directory(path)
            self.populate_local_dir()
            self.log_message(f"Navigated to local bookmark: {name} -> {path}")
        else:
            QMessageBox.warning(self, "Bookmark Error", f"The directory '{path}' no longer exists.")

    def remote_bookmark_changed(self, index):
        if index == 0:
            return
        if index == 1:
            self.remote_bookmark_combo.setCurrentIndex(0)
            if not self.sftp_client:
                QMessageBox.warning(self, "No Connection", "Please connect to SFTP first.")
                return
            name, ok = QInputDialog.getText(self, "Save Remote Bookmark", "Enter a name for this folder:")
            if ok and name.strip():
                name = name.strip()
                self.remote_folder_bookmarks[name] = self.current_remote_dir
                self.save_folder_bookmarks()
                self.populate_folder_bookmarks("remote")
                self.remote_bookmark_combo.setCurrentText(name)
            return
        
        name = self.remote_bookmark_combo.currentText()
        path = self.remote_folder_bookmarks.get(name)
        if path:
            self.set_remote_directory(path)
            self.fetch_remote_dir()
            self.log_message(f"Navigated to remote bookmark: {name} -> {path}")

    # --- Session Bookmarks Manager ---
    def load_sessions(self):
        if os.path.exists(self.sessions_file):
            try:
                with open(self.sessions_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_sessions(self):
        try:
            with open(self.sessions_file, "w", encoding="utf-8") as f:
                json.dump(self.saved_sessions, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.status_bar.showMessage(f"Failed to save bookmarks: {e}")

    def populate_sessions_dropdown(self):
        self.sessions_combo.blockSignals(True)
        self.sessions_combo.clear()
        self.sessions_combo.addItem("-- Select a saved bookmark --")
        for name in sorted(self.saved_sessions.keys()):
            self.sessions_combo.addItem(name)
        self.sessions_combo.blockSignals(False)

    def load_selected_session(self, index):
        if index <= 0:
            return
        name = self.sessions_combo.currentText()
        sess = self.saved_sessions.get(name)
        if sess:
            self.protocol_combo.setCurrentText(sess.get("protocol", "SFTP"))
            self.ftp_encoding_combo.setCurrentText(sess.get("encoding", "utf-8"))
            self.oz_usl_checkbox.setChecked(sess.get("use_usl", False))
            self.host_input.setText(sess.get("host", "localhost"))
            self.port_input.setText(sess.get("port", "22"))
            self.user_input.setText(sess.get("user", ""))
            self.pass_input.setText(sess.get("pass", ""))
            self.otp_input.clear()
            self.key_input.setText(sess.get("key", ""))

    def save_current_session(self):
        name, ok = QInputDialog.getText(self, "Save Connection", "Enter a name for this bookmark:")
        if ok and name.strip():
            name = name.strip()
            self.saved_sessions[name] = {
                "protocol": self.protocol_combo.currentText(),
                "encoding": self.ftp_encoding_combo.currentText(),
                "use_usl": self.oz_usl_checkbox.isChecked(),
                "host": self.host_input.text(),
                "port": self.port_input.text(),
                "user": self.user_input.text(),
                "pass": self.pass_input.text(),
                "key": self.key_input.text()
            }
            self.save_sessions()
            self.populate_sessions_dropdown()
            self.sessions_combo.setCurrentText(name)
            QMessageBox.information(self, "Success", f"Bookmark '{name}' saved successfully.")

    def delete_current_session(self):
        name = self.sessions_combo.currentText()
        if self.sessions_combo.currentIndex() <= 0:
            QMessageBox.warning(self, "Selection Error", "Please select a bookmark to delete.")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Delete", f"Are you sure you want to delete the bookmark '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.saved_sessions[name]
            self.save_sessions()
            self.populate_sessions_dropdown()
            self.sessions_combo.setCurrentIndex(0)
            self.host_input.setText("localhost")
            self.port_input.setText("22")
            self.user_input.clear()
            self.pass_input.clear()
            self.otp_input.clear()
            self.key_input.clear()

    # --- Path Input Navigation Actions ---
    def eventFilter(self, watched, event):
        if (event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                             QEvent.Type.MouseButtonDblClick)
                and event.button() in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton)):
            if event.type() == QEvent.Type.MouseButtonPress:
                offset = -1 if event.button() == Qt.MouseButton.BackButton else 1
                self.navigate_folder_history(bool(watched.property("remote_navigation_pane")), offset)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def record_folder_visit(self, is_remote, path):
        prefix = "remote" if is_remote else "local"
        paths = getattr(self, f"{prefix}_navigation_paths")
        index = getattr(self, f"{prefix}_navigation_index")
        if index >= 0 and paths[index] == path:
            return
        del paths[index + 1:]
        paths.append(path)
        setattr(self, f"{prefix}_navigation_index", len(paths) - 1)

    def navigate_folder_history(self, is_remote, offset):
        prefix = "remote" if is_remote else "local"
        paths = getattr(self, f"{prefix}_navigation_paths")
        index = getattr(self, f"{prefix}_navigation_index") + offset
        if not 0 <= index < len(paths):
            return
        if is_remote:
            if not self.sftp_client or any(worker.action == "list_dir"
                                           for worker in self.running_workers
                                           if isinstance(worker, SFTPWorker)):
                return
            self.set_remote_directory(paths[index])
            self.fetch_remote_dir(history_index=index)
        else:
            path = paths[index]
            if not os.path.isdir(path):
                QMessageBox.warning(self, "Invalid Path", f"The specified local path does not exist:\n{path}")
                return
            self.set_local_directory(path, record_history=False)
            self.local_navigation_index = index
            self.populate_local_dir()

    def set_local_directory(self, path, record_history=True):
        path = os.path.normpath(os.path.abspath(path))
        if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(self.current_local_dir)):
            self.local_search.clear()
        self.current_local_dir = path
        if record_history:
            self.record_folder_visit(False, path)

    def set_remote_directory(self, path):
        path = posixpath.normpath(path)
        if posixpath.normpath(path) != posixpath.normpath(self.current_remote_dir):
            self.remote_search.clear()
        self.current_remote_dir = path

    def local_path_entered(self):
        path = self.local_path_input.text().strip()
        if os.path.isdir(path):
            self.set_local_directory(path)
            self.populate_local_dir()
        else:
            QMessageBox.warning(self, "Invalid Path", f"The specified local path does not exist:\n{path}")
            self.local_path_input.setText(self.current_local_dir)

    def remote_path_entered(self):
        if not self.sftp_client:
            return
        path = self.remote_path_input.text().strip()
        if not path:
            path = "/"
        self.set_remote_directory(path)
        self.fetch_remote_dir()

    # --- Local File System Utilities ---
    def get_local_owner_group(self, path):
        try:
            import pwd
            import grp
            stat_info = os.stat(path)
            owner = pwd.getpwuid(stat_info.st_uid).pw_name
            group = grp.getgrgid(stat_info.st_gid).gr_name
            return f"{owner}:{group}"
        except Exception:
            return "system"

    def populate_local_dir(self):
        self.local_path_input.setText(self.current_local_dir)
        self.local_table.setSortingEnabled(False)
        self.local_table.setRowCount(0)
        try:
            entries = os.listdir(self.current_local_dir)
        except Exception as e:
            self.status_bar.showMessage(f"Error accessing local dir: {str(e)}")
            self.local_table.setSortingEnabled(True)
            return

        dirs_list = []
        files_list = []
        for name in entries:
            if not self.local_show_hidden.isChecked() and name.startswith('.'):
                continue
            full_path = os.path.join(self.current_local_dir, name)
            try:
                stat_info = os.stat(full_path)
                is_dir = stat.S_ISDIR(stat_info.st_mode)
                size_kb = round(stat_info.st_size / 1024, 2)
                mtime = stat_info.st_mtime
                date_str = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                owner_group = self.get_local_owner_group(full_path)
                
                info = (name, "Folder" if is_dir else "File", size_kb, date_str, owner_group, is_dir, mtime)
                if is_dir:
                    dirs_list.append(info)
                else:
                    files_list.append(info)
            except Exception:
                continue

        dirs_list.sort(key=lambda x: x[0].lower())
        files_list.sort(key=lambda x: x[0].lower())
        sorted_entries = dirs_list + files_list

        for idx, (name, ftype, size, mtime_str, owner, is_dir, mtime) in enumerate(sorted_entries):
            self.local_table.insertRow(idx)
            
            display_name = f"📁 {name}" if is_dir else f"📄 {name}"
            
            name_item = SortableTableWidgetItem(display_name, (0 if is_dir else 1, name.lower()))
            size_sort = -1.0 if is_dir else float(size)
            size_item = SortableTableWidgetItem("" if is_dir else f"{size} KB", size_sort)
            type_item = SortableTableWidgetItem(ftype, ftype.lower())
            time_item = SortableTableWidgetItem(mtime_str, mtime)
            owner_item = SortableTableWidgetItem(owner, owner.lower())

            name_item.setData(Qt.ItemDataRole.UserRole, os.path.join(self.current_local_dir, name))

            self.local_table.setItem(idx, 0, name_item)
            self.local_table.setItem(idx, 1, size_item)
            self.local_table.setItem(idx, 2, type_item)
            self.local_table.setItem(idx, 3, time_item)
            self.local_table.setItem(idx, 4, owner_item)

        self.local_table.setSortingEnabled(True)
        self.local_table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.filter_table(self.local_table, self.local_search.text())

    def local_navigate_up(self):
        parent = os.path.dirname(self.current_local_dir)
        if parent != self.current_local_dir:
            self.set_local_directory(parent)
            self.populate_local_dir()

    def local_table_double_click(self, index):
        row = index.row()
        name_item = self.local_table.item(row, 0)
        full_path = name_item.data(Qt.ItemDataRole.UserRole)
        
        if os.path.isdir(full_path):
            self.set_local_directory(full_path)
            self.populate_local_dir()
        else:
            filename = os.path.basename(full_path)
            if is_text_file(filename):
                dialog = InAppEditorDialog(self, filename, full_path, is_remote=False)
                dialog.exec()
            else:
                try:
                    os.startfile(full_path)
                except Exception as e:
                    QMessageBox.warning(self, "Open Error", f"Cannot open file: {e}")

    # --- Search Filter Helper ---
    def filter_table(self, table, text):
        search_str = text.strip().lower()
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item:
                clean_name = item.text()[2:].lower()
                match = search_str in clean_name
                table.setRowHidden(row, not match)

    # --- Remote SFTP Functions ---
    def browse_key_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Private Key File", "", "All Files (*)")
        if file_path:
            self.key_input.setText(file_path)

    def on_protocol_changed(self, protocol):
        ftp = protocol == "FTP"
        oz = protocol == OZ_PROTOCOL
        self.port_input.setEnabled(not oz)
        self.oz_usl_checkbox.setVisible(oz)
        self.oz_usl_checkbox.setEnabled(True)
        self.host_input.setPlaceholderText("http://222.231.28.46:8080/oz80/server" if oz else "Host")
        if self.port_input.text() in ("21", "22", ""):
            self.port_input.setText("21" if ftp else "22")
        self.ftp_encoding_combo.setEnabled(ftp)
        for widget in (self.key_input, self.key_btn, self.otp_input):
            widget.setEnabled(not ftp and not oz)

    def connect_sftp(self):
        if self.connect_btn.text() == "Disconnect":
            self.disconnect_sftp()
            return

        host = self.host_input.text().strip()
        if host.lower().startswith(("http://", "https://")):
            self.protocol_combo.setCurrentText(OZ_PROTOCOL)
        port_text = self.port_input.text()
        user = self.user_input.text()
        pwd = self.pass_input.text()
        otp = self.otp_input.text().strip()
        key_path = self.key_input.text().strip()

        if not host or not user:
            QMessageBox.warning(self, "Input Error", "Please provide Host and Username.")
            return

        try:
            if self.protocol_combo.currentText() == OZ_PROTOCOL:
                host = normalize_server_url(host)
                port = 0  # The complete OZ URL supplies its own port.
            else:
                port = int(port_text)
        except ValueError:
            QMessageBox.warning(self, "Input Error", "OZ 서버 URL 또는 포트 번호를 확인해 주세요.")
            return

        self.status_bar.showMessage("Connecting...")
        self.connect_btn.setEnabled(False)

        self.worker = SFTPWorker("connect", (host, port, user, pwd, key_path, otp),
                                 protocol=self.protocol_combo.currentText(),
                                 use_usl=self.oz_usl_checkbox.isChecked(),
                                 encoding=self.ftp_encoding_combo.currentText())
        self.worker.finished_signal.connect(self.on_worker_done)
        self.worker.error_signal.connect(self.on_worker_error)
        self.start_worker(self.worker)
        self.connection_changed.emit()

    def disconnect_sftp(self):
        if self.has_running_operations():
            QMessageBox.information(self, "작업 진행 중", "진행 중인 작업이 끝난 후 연결을 해제해 주세요.")
            return
        self.ssh_terminal.stop()
        try:
            if self.sftp_client:
                self.sftp_client.close()
            if self.ssh_client:
                self.ssh_client.close()
        except Exception:
            pass
        self.stats_timer.stop()
        self.remote_refresh_btn.setEnabled(False)
        self.ssh_client = None
        self.sftp_client = None
        self.remote_navigation_paths.clear()
        self.remote_navigation_index = -1
        self.protocol_combo.setEnabled(True)
        self.on_protocol_changed(self.protocol_combo.currentText())
        self.remote_path_input.setText("Remote Path: Not Connected")
        self.remote_path_input.setStyleSheet("font-weight: bold; color: #f38ba8; background-color: #11111b; border: 1px solid #45475a;")
        self.remote_path_input.setEnabled(False)
        
        # Disable remote bookmarks and commands
        self.remote_bookmark_combo.setEnabled(False)
        self.remote_bookmark_combo.setCurrentIndex(0)
        self.remote_show_hidden.setEnabled(False)
        self.remote_show_hidden.setChecked(False)
        self.remote_cmd_input.setEnabled(False)
        self.remote_cmd_btn.setEnabled(False)
        
        self.remote_table.setRowCount(0)
        self.remote_search.clear()
        self.server_mem_lbl.setText("Server RAM: Not Connected")
        self.server_disk_lbl.setText("Server Disk: Not Connected")
        self.connect_btn.setText("Connect")
        self.connect_btn.setEnabled(True)
        self.remote_up_btn.setEnabled(False)
        self.status_bar.showMessage("Disconnected successfully")
        self.log_message("Disconnected from remote server.")
        self.connection_changed.emit()

    def has_running_operations(self):
        return (bool(self.running_workers)
                or any(job["status"] == "Queued" for job in self.transfer_queue))

    def track_worker(self, worker):
        # Retain threads until run() exits, including after their result signal.
        if not hasattr(self, "running_workers"):
            self.running_workers = set()
        self.running_workers.add(worker)
        worker.finished.connect(lambda: self.running_workers.discard(worker))

    def shutdown_session(self):
        self.stats_timer.stop()
        for timer in self.auto_upload_timers.values():
            timer.stop()
        self.pending_auto_uploads.clear()
        paths = self.file_watcher.files()
        if paths:
            self.file_watcher.removePaths(paths)
        self.disconnect_sftp()

    def fetch_remote_dir(self, *, history_index=None):
        if not self.sftp_client:
            return
        self.status_bar.showMessage("Fetching remote directory...")
        self.worker = SFTPWorker("list_dir", sftp=self.sftp_client, path=self.current_remote_dir,
                                 history_index=history_index)
        self.worker.finished_signal.connect(self.on_worker_done)
        self.worker.error_signal.connect(self.on_worker_error)
        self.start_worker(self.worker)

    def populate_remote_table(self, files):
        self.remote_path_input.setText(self.current_remote_dir)
        self.remote_table.setSortingEnabled(False)
        self.remote_table.setRowCount(0)
        self.remote_up_btn.setEnabled(True)

        row_idx = 0
        for file_info in files:
            name = file_info["name"]
            if not self.remote_show_hidden.isChecked() and name.startswith('.') and name not in ['.', '..']:
                continue
                
            self.remote_table.insertRow(row_idx)
            is_dir = file_info["is_dir"]
            display_name = f"📁 {name}" if is_dir else f"📄 {name}"
            
            name_item = SortableTableWidgetItem(display_name, (0 if is_dir else 1, name.lower()))
            size_val = round(file_info["size"] / 1024, 2)
            size_sort = -1.0 if is_dir else float(size_val)
            size_item = SortableTableWidgetItem("" if is_dir else f"{size_val} KB", size_sort)
            type_item = SortableTableWidgetItem("Folder" if is_dir else "File", "folder" if is_dir else "file")
            
            date_str = datetime.datetime.fromtimestamp(file_info["mtime"]).strftime('%Y-%m-%d %H:%M')
            time_item = SortableTableWidgetItem(date_str, file_info["mtime"])
            
            owner_group = f"{file_info['owner']}:{file_info['group']}"
            owner_item = SortableTableWidgetItem(owner_group, owner_group.lower())
            
            perm_item = SortableTableWidgetItem(file_info["mode"], file_info["mode"])

            name_item.setData(Qt.ItemDataRole.UserRole, (name, is_dir))

            self.remote_table.setItem(row_idx, 0, name_item)
            self.remote_table.setItem(row_idx, 1, size_item)
            self.remote_table.setItem(row_idx, 2, type_item)
            self.remote_table.setItem(row_idx, 3, time_item)
            self.remote_table.setItem(row_idx, 4, owner_item)
            self.remote_table.setItem(row_idx, 5, perm_item)
            row_idx += 1

        self.remote_table.setSortingEnabled(True)
        self.remote_table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.filter_table(self.remote_table, self.remote_search.text())

    def remote_navigate_up(self):
        if self.current_remote_dir == "/":
            return
        parent = os.path.dirname(self.current_remote_dir.rstrip('/'))
        if not parent:
            parent = "/"
        self.set_remote_directory(parent)
        self.fetch_remote_dir()

    def remote_table_double_click(self, index):
        row = index.row()
        name_item = self.remote_table.item(row, 0)
        filename, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
        
        if is_dir:
            if self.current_remote_dir == "/":
                self.set_remote_directory("/" + filename)
            else:
                self.set_remote_directory(self.current_remote_dir.rstrip('/') + "/" + filename)
            self.fetch_remote_dir()
        else:
            if not self.sftp_client:
                return
            
            remote_path = self.current_remote_dir.rstrip('/') + "/" + filename
            
            temp_dir = os.path.join(tempfile.gettempdir(), "sftp_client_temp")
            os.makedirs(temp_dir, exist_ok=True)
            local_path = os.path.join(temp_dir, filename)
            
            self.progress_bar.setValue(0)
            self.status_bar.showMessage(f"Opening remote file: {filename}...")
            
            self.worker = SFTPWorker("download", remotepath=remote_path, localpath=local_path, sftp=self.sftp_client)
            
            def on_double_click_download_done(action, path):
                self.finish_loading(self.sender())
                if action == "download" and path == local_path:
                    self.watched_files[local_path] = remote_path
                    self.file_watcher.addPath(local_path)
                    
                    try:
                        os.startfile(local_path)
                    except Exception as e:
                        QMessageBox.warning(self, "Open Error", f"Cannot open file: {e}")
                    try:
                        self.worker.finished_signal.disconnect(on_double_click_download_done)
                    except Exception:
                        pass
            
            self.worker.finished_signal.connect(on_double_click_download_done)
            self.worker.finished_signal.connect(self.on_worker_done)
            self.worker.progress_signal.connect(self.update_progress)
            self.worker.error_signal.connect(self.on_worker_error)
            self.start_worker(self.worker)

    # --- Drag & Drop Batch Connective Methods ---
    def upload_multiple_files(self, paths, target_dir, delete_source=False):
        if not self.sftp_client:
            QMessageBox.warning(self, "No Connection", "Please connect to SFTP first.")
            return
        
        for lpath in paths:
            lpath = os.path.normpath(lpath)
            filename = os.path.basename(lpath)
            rpath = target_dir.rstrip('/') + "/" + filename
            try:
                size = 0 if os.path.isdir(lpath) else os.path.getsize(lpath)
                self.add_to_transfer_queue("upload", lpath, rpath, size)
            except Exception as e:
                self.log_message(f"Error reading local file size: {e}")

    def download_multiple_files(self, filenames, target_dir, delete_source=False):
        if not self.sftp_client:
            return
            
        for fname in filenames:
            rpath = self.current_remote_dir.rstrip('/') + "/" + fname
            lpath = os.path.join(target_dir, fname)
            
            size = 0
            if hasattr(self, 'last_remote_files'):
                for f in self.last_remote_files:
                    if f["name"] == fname:
                        size = f["size"]
                        break
            self.add_to_transfer_queue("download", rpath, lpath, size)

    def copy_local_files(self, paths, target_dir):
        copied = 0
        for p in paths:
            try:
                dest = os.path.join(target_dir, os.path.basename(p))
                if os.path.abspath(p) == os.path.abspath(dest):
                    continue
                if os.path.isdir(p):
                    shutil.copytree(p, dest)
                else:
                    shutil.copy2(p, dest)
                copied += 1
            except Exception as e:
                print(f"Local copy error: {e}")
        if copied > 0:
            self.populate_local_dir()
            self.status_bar.showMessage(f"Copied {copied} files to local folder.")

    def move_local_files(self, paths, dest_dir):
        moved = 0
        for p in paths:
            try:
                dest = os.path.join(dest_dir, os.path.basename(p))
                if os.path.abspath(p) == os.path.abspath(dest):
                    continue
                shutil.move(p, dest_dir)
                moved += 1
            except Exception as e:
                QMessageBox.warning(self, "Move Error", f"Cannot move {os.path.basename(p)}:\n{e}")
        if moved > 0:
            self.populate_local_dir()
            self.status_bar.showMessage(f"Moved {moved} files locally.")

    def move_remote_files(self, paths, dest_dir):
        if not self.sftp_client:
            return
        
        self.progress_bar.setValue(0)
        self.status_bar.showMessage(f"Moving {len(paths)} remote items...")
        
        self.worker = SFTPWorker("move_remote_multiple", remotepaths=paths, destdir=dest_dir, sftp=self.sftp_client)
        self.worker.finished_signal.connect(self.on_worker_done)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.error_signal.connect(self.on_worker_error)
        self.start_worker(self.worker)

    def copy_remote_files(self, paths, dest_dir):
        if not self.sftp_client:
            return
        self.progress_bar.setValue(0)
        self.status_bar.showMessage(f"Copying {len(paths)} remote items...")
        
        self.worker = SFTPWorker("copy_remote_multiple", remotepaths=paths, destdir=dest_dir, sftp=self.sftp_client)
        self.worker.finished_signal.connect(self.on_worker_done)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.error_signal.connect(self.on_worker_error)
        self.start_worker(self.worker)

    # --- Clipboard Event Handlers (Copy / Cut / Paste) ---
    def local_copy_selected(self):
        selected_rows = self.local_table.selected_file_rows()
        paths = []
        for r in selected_rows:
            item = self.local_table.item(r, 0)
            if item:
                paths.append(item.data(Qt.ItemDataRole.UserRole))
        if paths:
            self.app_clipboard = {"action": "copy", "source_is_remote": False, "paths": paths}
            self.status_bar.showMessage(f"Copied {len(paths)} local items to clipboard.")

    def local_cut_selected(self):
        selected_rows = self.local_table.selected_file_rows()
        paths = []
        for r in selected_rows:
            item = self.local_table.item(r, 0)
            if item:
                paths.append(item.data(Qt.ItemDataRole.UserRole))
        if paths:
            self.app_clipboard = {"action": "cut", "source_is_remote": False, "paths": paths}
            self.status_bar.showMessage(f"Cut {len(paths)} local items to clipboard.")

    def local_paste(self):
        if not self.app_clipboard or not self.app_clipboard["paths"]:
            return
        
        src_is_remote = self.app_clipboard["source_is_remote"]
        paths = self.app_clipboard["paths"]
        action = self.app_clipboard["action"]

        if src_is_remote:
            # Remote -> Local (Download)
            filenames = [os.path.basename(p) for p in paths]
            self.download_multiple_files(filenames, self.current_local_dir, delete_source=(action == "cut"))
        else:
            # Local -> Local (Copy or Move)
            if action == "copy":
                self.copy_local_files(paths, self.current_local_dir)
            else:
                self.move_local_files(paths, self.current_local_dir)

        if action == "cut":
            self.app_clipboard = None # Clear clipboard on cut-paste

    def remote_copy_selected(self):
        selected_rows = self.remote_table.selected_file_rows()
        paths = []
        for r in selected_rows:
            item = self.remote_table.item(r, 0)
            if item:
                filename, _ = item.data(Qt.ItemDataRole.UserRole)
                paths.append(self.current_remote_dir.rstrip('/') + "/" + filename)
        if paths:
            self.app_clipboard = {"action": "copy", "source_is_remote": True, "paths": paths}
            self.status_bar.showMessage(f"Copied {len(paths)} remote items to clipboard.")

    def remote_cut_selected(self):
        if isinstance(self.sftp_client, OZClient):
            QMessageBox.information(self, "OZ Report", "OZ 연결에서는 잘라내기·이동을 지원하지 않습니다. 복사를 사용해 주세요.")
            return
        selected_rows = self.remote_table.selected_file_rows()
        paths = []
        for r in selected_rows:
            item = self.remote_table.item(r, 0)
            if item:
                filename, _ = item.data(Qt.ItemDataRole.UserRole)
                paths.append(self.current_remote_dir.rstrip('/') + "/" + filename)
        if paths:
            self.app_clipboard = {"action": "cut", "source_is_remote": True, "paths": paths}
            self.status_bar.showMessage(f"Cut {len(paths)} remote items to clipboard.")

    def remote_paste(self):
        if not self.app_clipboard or not self.app_clipboard["paths"]:
            return
        
        src_is_remote = self.app_clipboard["source_is_remote"]
        paths = self.app_clipboard["paths"]
        action = self.app_clipboard["action"]

        if src_is_remote:
            # Remote -> Remote
            if action == "copy":
                self.copy_remote_files(paths, self.current_remote_dir)
            else:
                self.move_remote_files(paths, self.current_remote_dir)
        else:
            # Local -> Remote (Upload)
            self.upload_multiple_files(paths, self.current_remote_dir, delete_source=(action == "cut"))

        if action == "cut":
            self.app_clipboard = None

    def change_remote_permissions(self, row):
        name_item = self.remote_table.item(row, 0)
        filename, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
        remote_path = self.current_remote_dir.rstrip('/') + "/" + filename
        
        val, ok = QInputDialog.getText(self, "Change Permissions (chmod)", f"Enter octal permissions for '{filename}' (e.g. 755):")
        if ok and val.strip():
            try:
                mode = int(val.strip(), 8)
                self.status_bar.showMessage(f"Changing permissions of {filename} to {val.strip()}...")
                self.worker = SFTPWorker("chmod", path=remote_path, mode=mode, sftp=self.sftp_client)
                self.worker.finished_signal.connect(self.on_worker_done)
                self.worker.error_signal.connect(self.on_worker_error)
                self.start_worker(self.worker)
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", "Permissions must be a valid octal number (e.g. 755, 644).")

    # --- Worker Thread Feedback ---
    def start_worker(self, worker):
        labels = {
            "connect": "서버에 접속 중입니다...",
            "list_dir": "폴더를 불러오는 중입니다...",
            "download": "파일을 다운로드하는 중입니다...",
            "upload": "파일을 업로드하는 중입니다...",
            "run_command": "원격 작업을 처리하는 중입니다...",
        }
        dialog = QProgressDialog(labels.get(worker.action, "작업을 처리하는 중입니다..."),
                                 "", 0, 0, self)
        dialog.setWindowTitle("로딩 중")
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModality.NonModal if getattr(self, "embedded_session", False)
                                 else Qt.WindowModality.WindowModal)
        dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        self.loading_dialogs[worker] = dialog
        worker.finished_signal.connect(lambda *_: self.finish_loading(worker))
        worker.error_signal.connect(lambda *_: self.finish_loading(worker))
        worker.finished.connect(lambda: self.finish_loading(worker))
        dialog.show()
        SFTPClientApp.track_worker(self, worker)
        worker.start()

    def finish_loading(self, worker):
        dialog = self.loading_dialogs.pop(worker, None)
        if dialog is not None:
            dialog.hide()
            dialog.deleteLater()

    def on_worker_done(self, action, result):
        self.finish_loading(self.sender())
        if action == "connect":
            self.ssh_client, self.sftp_client = result
            ftp = isinstance(self.sftp_client, (FTPClient, OZClient))
            self.protocol_combo.setEnabled(False)
            self.ftp_encoding_combo.setEnabled(False)
            self.oz_usl_checkbox.setEnabled(False)
            # OTP codes are short-lived and must never remain in the UI/bookmarks.
            self.otp_input.clear()
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setEnabled(True)
            self.connection_changed.emit()
            self.remote_refresh_btn.setEnabled(True)
            self.remote_path_input.setEnabled(True)
            self.remote_path_input.setStyleSheet("font-weight: bold; color: #a6e3a1; background-color: #11111b; border: 1px solid #45475a;")
            
            # Enable remote-only controls
            self.remote_bookmark_combo.setEnabled(True)
            self.remote_show_hidden.setEnabled(True)
            self.remote_cmd_input.setEnabled(not ftp)
            self.remote_cmd_btn.setEnabled(not ftp)
            if not ftp:
                self.ssh_terminal.start(self.ssh_client)
            
            self.status_bar.showMessage("Connected successfully!")
            endpoint = self.host_input.text() if isinstance(self.sftp_client, OZClient) else f"{self.host_input.text()}:{self.port_input.text()}"
            self.log_message(f"Successfully connected to {endpoint} as user {self.user_input.text()}")
            
            # Start keepalive
            if self.sftp_client and not ftp:
                transport = self.sftp_client.get_channel().get_transport()
                if transport:
                    transport.set_keepalive(30)
                    self.log_message("SSH Keep-Alive set to 30 seconds.")
            
            self.set_remote_directory(self.sftp_client.initial_directory if ftp else "/")
            self.fetch_remote_dir()
            
            if not ftp:
                self.update_server_stats()
                self.stats_timer.start()
            else:
                self.server_mem_lbl.setText("Server RAM: Unavailable for this connection")
                self.server_disk_lbl.setText("Server Disk: Unavailable for this connection")

        elif action == "list_dir":
            worker = self.sender()
            args = worker.args if isinstance(worker, SFTPWorker) else {}
            if args.get("path", self.current_remote_dir) != self.current_remote_dir:
                return
            index = args.get("history_index")
            if (index is not None and 0 <= index < len(self.remote_navigation_paths)
                    and self.remote_navigation_paths[index] == self.current_remote_dir):
                self.remote_navigation_index = index
            else:
                self.record_folder_visit(True, self.current_remote_dir)
            self.last_remote_files = result
            self.populate_remote_table(result)
            self.status_bar.showMessage("Directory updated.")
            self.log_message(f"Fetched remote directory: {self.current_remote_dir} ({len(result)} items found)")
            
            if hasattr(self, 'remote_history') and self.current_remote_dir not in self.remote_history:
                self.remote_history.append(self.current_remote_dir)
                self.remote_completer_model.setStringList(self.remote_history)
            
        elif action == "get_stats":
            if result:
                self.server_mem_lbl.setText(f"Server RAM: {result['mem']}")
                self.server_disk_lbl.setText(f"Server Disk: {result['disk']}")

        elif action == "run_command":
            stdout = result["stdout"]
            stderr = result["stderr"]
            cmd = result["cmd"]
            if stdout:
                self.log_message(f"Command '{cmd}' output:\n{stdout}")
            if stderr:
                self.log_message(f"Command '{cmd}' error:\n{stderr}")
            if not stdout and not stderr:
                self.log_message(f"Command '{cmd}' executed (no output).")
            self.fetch_remote_dir()

        elif action in ["download", "upload", "download_multiple", "upload_multiple", "move_remote_multiple", "copy_remote_multiple", "chmod"]:
            self.progress_bar.setValue(100)
            self.status_bar.showMessage(f"Action '{action}' finished.")
            self.log_message(f"Action '{action}' completed successfully.")
            self.populate_local_dir()
            self.fetch_remote_dir()

        elif action in ["delete", "delete_multiple", "mkdir", "rename", "create_file"]:
            self.status_bar.showMessage(f"Action '{action}' completed.")
            self.log_message(f"Action '{action}' completed successfully.")
            self.fetch_remote_dir()
            if action == "delete_multiple" and result:
                QMessageBox.critical(self, "Delete Error", "Could not delete:\n" + "\n".join(result))

    def on_worker_error(self, action, err_msg):
        self.finish_loading(self.sender())
        self.connect_btn.setEnabled(True)
        self.connection_changed.emit()
        if action == "list_dir":
            worker = self.sender()
            if isinstance(worker, SFTPWorker) and worker.args.get("path") != self.current_remote_dir:
                return
            if self.remote_navigation_index >= 0:
                self.set_remote_directory(self.remote_navigation_paths[self.remote_navigation_index])
            self.remote_path_input.setText(self.current_remote_dir)
        QMessageBox.critical(self, f"Error on {action}", f"An error occurred: {err_msg}")
        self.status_bar.showMessage(f"Error: {err_msg}")

    def update_progress(self, transferred, total):
        if total > 0:
            percentage = int((transferred / total) * 100)
            self.progress_bar.setValue(percentage)

    # --- Context Menus & Actions ---
    def show_local_context_menu(self, position):
        row = self.local_table.rowAt(position.y())
        menu = QMenu(self)
        
        upload_action = QAction("📤 Upload to Remote", self)
        copy_action = QAction("✂ Copy", self)
        cut_action = QAction("✂ Cut (Move)", self)
        paste_action = QAction("📋 Paste", self)
        
        rename_action = QAction("📝 Rename Local File", self)
        delete_action = QAction("❌ Delete Local File", self)
        create_file_action = QAction("📄 Create Empty File", self)
        create_folder_action = QAction("📁 Create Folder", self)
        properties_action = QAction("🔍 Properties", self)

        # Handle Copy/Cut availability
        if row != -1:
            name_item = self.local_table.item(row, 0)
            local_path = name_item.data(Qt.ItemDataRole.UserRole)
            
            upload_action.triggered.connect(self.upload_selected_files)
            copy_action.triggered.connect(self.local_copy_selected)
            cut_action.triggered.connect(self.local_cut_selected)
            rename_action.triggered.connect(lambda: self.rename_local_item(local_path))
            delete_action.triggered.connect(lambda: self.delete_selected_files(False))
            properties_action.triggered.connect(lambda: self.show_local_properties(row))
            
            menu.addAction(upload_action)
            menu.addAction(copy_action)
            menu.addAction(cut_action)
            menu.addAction(rename_action)
            menu.addAction(delete_action)
            menu.addAction(properties_action)
            menu.addSeparator()
        else:
            # If right clicked on empty space, allow copying the folder path or just paste
            pass

        # Handle Paste availability
        paste_action.triggered.connect(self.local_paste)
        if not self.app_clipboard:
            paste_action.setEnabled(False)
        menu.addAction(paste_action)
        menu.addSeparator()

        create_file_action.triggered.connect(self.create_local_file)
        create_folder_action.triggered.connect(self.create_local_folder)
        menu.addAction(create_file_action)
        menu.addAction(create_folder_action)
        
        menu.exec(self.local_table.viewport().mapToGlobal(position))

    def show_remote_context_menu(self, position):
        if not self.sftp_client:
            return
        row = self.remote_table.rowAt(position.y())
        menu = QMenu(self)

        download_action = QAction("📥 Download to Local", self)
        copy_action = QAction("✂ Copy", self)
        cut_action = QAction("✂ Cut (Move)", self)
        paste_action = QAction("📋 Paste", self)
        
        rename_action = QAction("📝 Rename", self)
        delete_action = QAction("❌ Delete", self)
        chmod_action = QAction("🔒 Change Permissions (chmod)", self)
        
        create_file_action = QAction("📄 Create Empty File", self)
        mkdir_action = QAction("📁 Create New Folder Here", self)
        
        properties_action = QAction("🔍 Properties", self)
        compress_zip_action = QAction("📦 Compress to ZIP", self)
        compress_tar_action = QAction("📦 Compress to TAR.GZ", self)
        decompress_action = QAction("📂 Decompress Archive", self)
        calc_size_action = QAction("📊 Calculate Folder Size", self)
        if isinstance(self.sftp_client, (FTPClient, OZClient)):
            for action in (compress_zip_action, compress_tar_action,
                           decompress_action, calc_size_action):
                action.setEnabled(False)
        if isinstance(self.sftp_client, OZClient):
            for action in (cut_action, rename_action, chmod_action):
                action.setEnabled(False)
        
        if row != -1:
            name_item = self.remote_table.item(row, 0)
            filename, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
            remote_path = self.current_remote_dir.rstrip('/') + "/" + filename

            download_action.triggered.connect(self.download_selected_files)
            copy_action.triggered.connect(self.remote_copy_selected)
            cut_action.triggered.connect(self.remote_cut_selected)
            rename_action.triggered.connect(lambda: self.rename_remote_item(remote_path, filename))
            delete_action.triggered.connect(lambda: self.delete_selected_files(True))
            chmod_action.triggered.connect(lambda: self.change_remote_permissions(row))
            
            properties_action.triggered.connect(lambda: self.show_remote_properties(row))
            compress_zip_action.triggered.connect(lambda: self.compress_remote_item(row, "zip"))
            compress_tar_action.triggered.connect(lambda: self.compress_remote_item(row, "tar"))
            decompress_action.triggered.connect(lambda: self.decompress_remote_item(row))
            calc_size_action.triggered.connect(lambda: self.calculate_remote_folder_size(row))
            
            if not is_dir:
                calc_size_action.setEnabled(False)
                ext = filename.lower()
                is_archive = ext.endswith('.zip') or ext.endswith('.tar.gz') or ext.endswith('.tgz') or ext.endswith('.tar')
                if not is_archive:
                    decompress_action.setEnabled(False)
            else:
                decompress_action.setEnabled(False)
            
            menu.addAction(download_action)
            menu.addAction(copy_action)
            menu.addAction(cut_action)
            menu.addAction(rename_action)
            menu.addAction(delete_action)
            menu.addAction(chmod_action)
            menu.addSeparator()
            menu.addAction(properties_action)
            menu.addAction(compress_zip_action)
            menu.addAction(compress_tar_action)
            menu.addAction(decompress_action)
            menu.addAction(calc_size_action)
            menu.addSeparator()

        paste_action.triggered.connect(self.remote_paste)
        if not self.app_clipboard:
            paste_action.setEnabled(False)
        menu.addAction(paste_action)
        menu.addSeparator()

        create_file_action.triggered.connect(self.create_remote_file)
        mkdir_action.triggered.connect(self.create_remote_dir)
        
        menu.addAction(create_file_action)
        menu.addAction(mkdir_action)

        menu.exec(self.remote_table.viewport().mapToGlobal(position))

    # --- Convenience Local Implementations ---
    def delete_selected_files(self, is_remote):
        table = self.remote_table if is_remote else self.local_table
        if is_remote and not self.sftp_client:
            return
        items = []
        for row in table.selected_file_rows():
            item = table.item(row, 0)
            if item is None:
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if is_remote:
                name, is_dir = data
                items.append((posixpath.join(self.current_remote_dir, name), is_dir))
            elif data:
                items.append((data, os.path.isdir(data)))
        self.delete_file_items(items, is_remote)

    def delete_file_items(self, items, is_remote):
        if not items:
            return
        names = [os.path.basename(path) for path, _ in items]
        preview = "\n".join(names[:10])
        if len(names) > 10:
            preview += f"\n… 외 {len(names) - 10}개"
        location = "원격" if is_remote else "로컬"
        folder_notice = "\n폴더 안의 모든 하위 폴더와 파일도 함께 삭제됩니다." if any(is_dir for _, is_dir in items) else ""
        reply = QMessageBox.question(
            self, "Confirm Delete", f"선택한 {location} 항목 {len(items)}개를 삭제하시겠습니까?{folder_notice}\n\n{preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if is_remote:
            if not self.sftp_client:
                return
            self.worker = SFTPWorker("delete_multiple", items=items, sftp=self.sftp_client)
            self.worker.finished_signal.connect(self.on_worker_done)
            self.worker.error_signal.connect(self.on_worker_error)
            self.start_worker(self.worker)
            return
        errors = []
        for path, is_dir in items:
            try:
                delete_local_item(path)
            except Exception as error:
                errors.append(f"{path}: {error}")
        self.populate_local_dir()
        if errors:
            QMessageBox.critical(self, "Delete Error", "Could not delete:\n" + "\n".join(errors))

    def upload_selected_files(self):
        paths = [self.local_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                 for row in self.local_table.selected_file_rows()]
        self.upload_multiple_files(paths, self.current_remote_dir)

    def download_selected_files(self):
        files = [self.remote_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                 for row in self.remote_table.selected_file_rows()]
        self.download_multiple_files([name for name, is_dir in files if not is_dir],
                                     self.current_local_dir)

    def rename_local_item(self, path):
        old_name = os.path.basename(path)
        new_name, ok = QInputDialog.getText(self, "Rename", f"Rename '{old_name}' to:", text=old_name)
        if ok and new_name.strip():
            new_path = os.path.join(os.path.dirname(path), new_name.strip())
            try:
                os.rename(path, new_path)
                self.populate_local_dir()
            except Exception as e:
                QMessageBox.critical(self, "Rename Error", f"Could not rename file: {e}")

    def delete_local_item(self, path):
        self.delete_file_items([(path, os.path.isdir(path))], False)

    def create_local_file(self):
        name, ok = QInputDialog.getText(self, "Create File", "Enter new file name:")
        if ok and name.strip():
            full_path = os.path.join(self.current_local_dir, name.strip())
            try:
                with open(full_path, "w") as f:
                    f.write("")
                self.populate_local_dir()
            except Exception as e:
                QMessageBox.critical(self, "Create Error", f"Could not create file: {e}")

    def create_local_folder(self):
        name, ok = QInputDialog.getText(self, "Create Folder", "Enter new folder name:")
        if ok and name.strip():
            full_path = os.path.join(self.current_local_dir, name.strip())
            try:
                os.makedirs(full_path, exist_ok=True)
                self.populate_local_dir()
            except Exception as e:
                QMessageBox.critical(self, "Create Error", f"Could not create folder: {e}")

    # --- Remote SFTP Action Implementations ---
    def upload_file(self, row):
        if not self.sftp_client:
            QMessageBox.warning(self, "No Connection", "Please connect to SFTP first.")
            return

        name_item = self.local_table.item(row, 0)
        local_path = name_item.data(Qt.ItemDataRole.UserRole)

        self.upload_multiple_files([local_path], self.current_remote_dir)

    def download_file(self, row):
        name_item = self.remote_table.item(row, 0)
        filename, is_dir = name_item.data(Qt.ItemDataRole.UserRole)

        if is_dir:
            QMessageBox.warning(self, "Not Supported", "Directory download is not supported in this version.")
            return

        self.download_multiple_files([filename], self.current_local_dir)

    def rename_remote_item(self, path, old_name):
        new_name, ok = QInputDialog.getText(self, "Rename", f"Rename '{old_name}' to:", text=old_name)
        if ok and new_name.strip():
            new_path = os.path.dirname(path).rstrip('/') + "/" + new_name.strip()
            self.status_bar.showMessage(f"Renaming remote file...")
            self.worker = SFTPWorker("rename", oldpath=path, newpath=new_path, sftp=self.sftp_client)
            self.worker.finished_signal.connect(self.on_worker_done)
            self.worker.error_signal.connect(self.on_worker_error)
            self.start_worker(self.worker)

    def create_remote_file(self):
        name, ok = QInputDialog.getText(self, "Create File", "Enter name of empty file:")
        if ok and name.strip():
            remote_path = self.current_remote_dir.rstrip('/') + "/" + name.strip()
            self.status_bar.showMessage(f"Creating remote file...")
            self.worker = SFTPWorker("create_file", path=remote_path, sftp=self.sftp_client)
            self.worker.finished_signal.connect(self.on_worker_done)
            self.worker.error_signal.connect(self.on_worker_error)
            self.start_worker(self.worker)

    def delete_remote_item(self, row):
        if not self.sftp_client:
            return
        name, is_dir = self.remote_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self.delete_file_items([(posixpath.join(self.current_remote_dir, name), is_dir)], True)

    def create_remote_dir(self):
        name, ok = QInputDialog.getText(self, 'New Folder', 'Enter folder name:')
        if ok and name.strip():
            remote_path = self.current_remote_dir.rstrip('/') + "/" + name.strip()
            self.status_bar.showMessage(f"Creating folder {name}...")
            self.worker = SFTPWorker("mkdir", path=remote_path, sftp=self.sftp_client)
            self.worker.finished_signal.connect(self.on_worker_done)
            self.worker.error_signal.connect(self.on_worker_error)
            self.start_worker(self.worker)

    # --- Server Resources Statistics ---
    def update_server_stats(self):
        if not self.sftp_client or isinstance(self.sftp_client, (FTPClient, OZClient)):
            return
        if any(getattr(worker, "action", None) == "get_stats"
               for worker in self.running_workers):
            return
        self.stats_worker = SFTPWorker("get_stats", sftp=self.sftp_client)
        self.stats_worker.finished_signal.connect(self.on_worker_done)
        self.stats_worker.error_signal.connect(self.on_worker_error)
        self.track_worker(self.stats_worker)
        self.stats_worker.start()

    # --- Edit-On-Save File Watcher Handler ---
    def on_watched_file_changed(self, path):
        if path not in self.watched_files:
            return

        self.file_watcher.removePath(path)
        self.status_bar.showMessage(f"Waiting for {os.path.basename(path)} to finish saving...")
        self.schedule_auto_upload(path)

    def schedule_auto_upload(self, path):
        timer = self.auto_upload_timers.get(path)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda watched_path=path: self.start_auto_upload(watched_path))
            self.auto_upload_timers[path] = timer
        timer.start(750)

    def start_auto_upload(self, path):
        timer = self.auto_upload_timers.pop(path, None)
        if timer:
            timer.deleteLater()

        remote_path = self.watched_files.get(path)
        if not remote_path:
            return

        filename = os.path.basename(path)
        if not self.sftp_client:
            self.status_bar.showMessage(f"Failed to auto-upload {filename}: Disconnected")
            return
        if not os.path.isfile(path):
            self.status_bar.showMessage(f"Cannot auto-upload {filename}: local file is unavailable")
            return

        if path in self.auto_upload_workers:
            self.pending_auto_uploads.add(path)
            self.file_watcher.addPath(path)
            self.status_bar.showMessage(f"Another save of {filename} is queued for upload...")
            return

        self.file_watcher.addPath(path)
        worker = SFTPWorker("upload", localpath=path, remotepath=remote_path, sftp=self.sftp_client)
        self.auto_upload_workers[path] = worker
        worker.progress_signal.connect(
            lambda transferred, total, watched_path=path:
                self.update_auto_upload_progress(watched_path, transferred, total)
        )
        worker.finished_signal.connect(
            lambda action, result, watched_path=path, target_path=remote_path, upload_worker=worker:
                self.on_auto_upload_finished(watched_path, target_path, upload_worker, action, result)
        )
        worker.error_signal.connect(
            lambda action, error, watched_path=path, upload_worker=worker:
                self.on_auto_upload_error(watched_path, upload_worker, action, error)
        )
        worker.finished.connect(
            lambda watched_path=path, upload_worker=worker:
                self.on_auto_upload_worker_stopped(watched_path, upload_worker)
        )
        self.progress_bar.setValue(0)
        self.status_bar.showMessage(f"Auto-uploading changes for {filename}...")
        self.track_worker(worker)
        worker.start()

    def update_auto_upload_progress(self, path, transferred, total):
        if total > 0:
            self.progress_bar.setValue(int(transferred * 100 / total))
            self.status_bar.showMessage(
                f"Auto-uploading {os.path.basename(path)}: {int(transferred * 100 / total)}%"
            )

    def on_auto_upload_finished(self, path, remote_path, worker, action, result):
        if action == "upload" and result == remote_path:
            filename = os.path.basename(path)
            self.progress_bar.setValue(100)
            self.status_bar.showMessage(f"Auto-uploaded changes for {filename} successfully!")
            self.log_message(f"Auto-uploaded changes for {filename} successfully.")
            self.fetch_remote_dir()

    def on_auto_upload_error(self, path, worker, action, error):
        filename = os.path.basename(path)
        self.status_bar.showMessage(f"Auto-upload failed for {filename}: {error}")
        self.log_message(f"Auto-upload failed for {filename}: {error}")
        QMessageBox.warning(self, f"Error on {action}", f"Could not auto-upload {filename}:\n{error}")

    def on_auto_upload_worker_stopped(self, path, worker):
        if self.auto_upload_workers.get(path) is worker:
            del self.auto_upload_workers[path]
        if path in self.pending_auto_uploads:
            self.pending_auto_uploads.remove(path)
            self.schedule_auto_upload(path)

    def show_local_properties(self, row):
        name_item = self.local_table.item(row, 0)
        local_path = name_item.data(Qt.ItemDataRole.UserRole)
        name = os.path.basename(local_path)
        try:
            stat_info = os.stat(local_path)
            size_kb = round(stat_info.st_size / 1024, 2)
            date_str = datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M')
            owner_group = self.get_local_owner_group(local_path)
            raw_mode = stat_info.st_mode
            
            dialog = FilePropertiesDialog(self, name, False, local_path, size_kb, date_str, owner_group, raw_mode)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if dialog.new_mode is not None:
                    os.chmod(local_path, dialog.new_mode)
                    self.populate_local_dir()
                    self.log_message(f"Changed local permissions of '{name}' to {oct(dialog.new_mode)}")
        except Exception as e:
            QMessageBox.warning(self, "Properties Error", f"Could not read local file properties: {e}")

    def show_remote_properties(self, row):
        name_item = self.remote_table.item(row, 0)
        filename, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
        remote_path = self.current_remote_dir.rstrip('/') + "/" + filename
        
        file_info = None
        for f in self.last_remote_files:
            if f["name"] == filename:
                file_info = f
                break
        
        if not file_info:
            QMessageBox.warning(self, "Properties Error", "Could not locate file metadata.")
            return
            
        size_kb = round(file_info["size"] / 1024, 2)
        date_str = datetime.datetime.fromtimestamp(file_info["mtime"]).strftime('%Y-%m-%d %H:%M')
        owner_group = f"{file_info['owner']}:{file_info['group']}"
        raw_mode = file_info["raw_mode"]
        if isinstance(self.sftp_client, OZClient):
            raw_mode = None
        
        dialog = FilePropertiesDialog(self, filename, True, remote_path, size_kb, date_str, owner_group, raw_mode)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.new_mode is not None:
                self.status_bar.showMessage(f"Changing permissions of {filename}...")
                self.log_message(f"Changing remote permissions of '{filename}' to {oct(dialog.new_mode)}")
                self.worker = SFTPWorker("chmod", path=remote_path, mode=dialog.new_mode, sftp=self.sftp_client)
                self.worker.finished_signal.connect(self.on_worker_done)
                self.worker.error_signal.connect(self.on_worker_error)
                self.start_worker(self.worker)

    def compress_remote_item(self, row, archive_type):
        name_item = self.remote_table.item(row, 0)
        filename, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
        parent_dir = self.current_remote_dir.rstrip('/')
        remote_path = parent_dir + "/" + filename
        
        archive_name, ok = QInputDialog.getText(
            self, "Compress Item", 
            f"Enter name of the archive (without extension):",
            text=f"{filename}"
        )
        if ok and archive_name.strip():
            archive_name = archive_name.strip()
            if archive_type == "zip":
                cmd = f"cd '{parent_dir}' && zip -r '{archive_name}.zip' '{filename}'"
                success_msg = f"Compressed '{filename}' to '{archive_name}.zip'"
            else:
                cmd = f"cd '{parent_dir}' && tar -czf '{archive_name}.tar.gz' '{filename}'"
                success_msg = f"Compressed '{filename}' to '{archive_name}.tar.gz'"
                
            self.run_ssh_command_async(cmd, success_msg)

    def decompress_remote_item(self, row):
        name_item = self.remote_table.item(row, 0)
        filename, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
        parent_dir = self.current_remote_dir.rstrip('/')
        remote_path = parent_dir + "/" + filename
        
        ext = filename.lower()
        if ext.endswith('.zip'):
            cmd = f"cd '{parent_dir}' && unzip '{filename}'"
            success_msg = f"Extracted ZIP archive '{filename}'"
        elif ext.endswith('.tar.gz') or ext.endswith('.tgz'):
            cmd = f"cd '{parent_dir}' && tar -xzf '{filename}'"
            success_msg = f"Extracted TAR archive '{filename}'"
        elif ext.endswith('.tar'):
            cmd = f"cd '{parent_dir}' && tar -xf '{filename}'"
            success_msg = f"Extracted TAR archive '{filename}'"
        else:
            return
            
        self.run_ssh_command_async(cmd, success_msg)

    def run_ssh_command_async(self, cmd, success_msg):
        self.status_bar.showMessage("Running remote operation...")
        self.log_message(f"Running: {cmd}")
        self.cmd_worker = SFTPWorker("run_command", cmd=cmd, sftp=self.sftp_client)
        
        def on_cmd_done(action, result):
            self.finish_loading(self.sender())
            if action == "run_command" and result["cmd"] == cmd:
                if result["stderr"]:
                    self.log_message(f"Error executing command: {result['stderr']}")
                    QMessageBox.warning(self, "Remote Operation Error", f"Command completed with error:\n{result['stderr']}")
                else:
                    self.log_message(success_msg)
                    self.status_bar.showMessage("Operation completed successfully.")
                self.fetch_remote_dir()
                try:
                    self.cmd_worker.finished_signal.disconnect(on_cmd_done)
                except Exception:
                    pass
        self.cmd_worker.finished_signal.connect(on_cmd_done)
        self.cmd_worker.error_signal.connect(self.on_worker_error)
        self.start_worker(self.cmd_worker)

    def calculate_remote_folder_size(self, row):
        name_item = self.remote_table.item(row, 0)
        filename, is_dir = name_item.data(Qt.ItemDataRole.UserRole)
        if not is_dir:
            return
        remote_path = self.current_remote_dir.rstrip('/') + "/" + filename
        self.status_bar.showMessage(f"Calculating size of {filename}...")
        self.log_message(f"Calculating directory size: {remote_path}")
        
        self.size_worker = SFTPWorker("run_command", cmd=f"du -sh '{remote_path}'", sftp=self.sftp_client)
        
        def on_size_done(action, result):
            self.finish_loading(self.sender())
            if action == "run_command" and "du -sh" in result["cmd"]:
                stdout = result["stdout"].strip()
                if stdout:
                    size_str = stdout.split()[0]
                    QMessageBox.information(self, "Folder Size", f"Total size of remote folder '{filename}':\n\n{size_str}")
                    self.status_bar.showMessage(f"Folder size: {size_str}")
                else:
                    QMessageBox.warning(self, "Folder Size Error", "Could not calculate folder size.")
                try:
                    self.size_worker.finished_signal.disconnect(on_size_done)
                except Exception:
                    pass
        self.size_worker.finished_signal.connect(on_size_done)
        self.size_worker.error_signal.connect(self.on_worker_error)
        self.start_worker(self.size_worker)

    def run_remote_command(self):
        if not self.sftp_client:
            QMessageBox.warning(self, "No Connection", "Please connect to SFTP first.")
            return
        cmd = self.remote_cmd_input.text().strip()
        if not cmd:
            return
        self.log_message(f"Running command: {cmd}")
        self.remote_cmd_input.clear()
        
        self.cmd_worker = SFTPWorker("run_command", cmd=cmd, sftp=self.sftp_client)
        self.cmd_worker.finished_signal.connect(self.on_worker_done)
        self.cmd_worker.error_signal.connect(self.on_worker_error)
        self.start_worker(self.cmd_worker)

    def add_to_transfer_queue(self, direction, source, dest, size):
        self.job_counter += 1
        job_id = self.job_counter
        job = {
            "id": job_id,
            "direction": direction,
            "source": source,
            "dest": dest,
            "size": size,
            "status": "Queued",
            "progress": 0,
            "speed": 0.0
        }
        self.transfer_queue.append(job)
        self.log_message(f"Queued {direction}: {os.path.basename(source)}")
        self.refresh_queue_table()
        self.process_next_queue_item()

    def refresh_queue_table(self):
        self.queue_table.setRowCount(0)
        queued_count = sum(1 for j in self.transfer_queue if j["status"] in ["Queued", "Active"])
        self.bottom_tabs.setTabText(0, f"📂 Active Transfers ({queued_count})")
        
        for idx, job in enumerate(self.transfer_queue):
            self.queue_table.insertRow(idx)
            
            dir_item = QTableWidgetItem("📤 Upload" if job["direction"] == "upload" else "📥 Download")
            src_item = QTableWidgetItem(job["source"])
            dst_item = QTableWidgetItem(job["dest"])
            size_val = round(job["size"] / 1024, 2)
            size_item = QTableWidgetItem(f"{size_val} KB")
            
            status = job["status"]
            if status == "Active":
                prog_text = f"{job['progress']}% ({round(job['speed'] / 1024, 2)} KB/s)"
            elif status == "Queued":
                prog_text = "Queued"
            elif status == "Completed":
                prog_text = "✓ Completed"
            elif status == "Cancelled":
                prog_text = "⚠️ Cancelled"
            else:
                prog_text = f"❌ Failed"
                
            prog_item = QTableWidgetItem(prog_text)
            
            self.queue_table.setItem(idx, 0, dir_item)
            self.queue_table.setItem(idx, 1, src_item)
            self.queue_table.setItem(idx, 2, dst_item)
            self.queue_table.setItem(idx, 3, size_item)
            self.queue_table.setItem(idx, 4, prog_item)
            
            if status in ["Queued", "Active"]:
                cancel_btn = QPushButton("Cancel")
                cancel_btn.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold; padding: 2px;")
                cancel_btn.clicked.connect(lambda checked, j_id=job["id"]: self.cancel_transfer(j_id))
                self.queue_table.setCellWidget(idx, 5, cancel_btn)
            else:
                self.queue_table.setItem(idx, 5, QTableWidgetItem("-"))

    def process_next_queue_item(self):
        if len(self.active_workers) >= 1:
            return
            
        queued_job = None
        for job in self.transfer_queue:
            if job["status"] == "Queued":
                queued_job = job
                break
                
        if not queued_job:
            return
            
        if not self.sftp_client:
            queued_job["status"] = "Failed"
            self.refresh_queue_table()
            return
            
        queued_job["status"] = "Active"
        job_id = queued_job["id"]
        
        worker = SingleFileTransferWorker(
            self.sftp_client,
            queued_job["direction"],
            queued_job["source"],
            queued_job["dest"],
            queued_job["size"]
        )
        self.active_workers[job_id] = worker
        
        worker.progress_signal.connect(lambda trans, tot, spd, j_id=job_id: self.on_transfer_progress(j_id, trans, tot, spd))
        worker.finished_signal.connect(lambda success, err, j_id=job_id: self.on_transfer_finished(j_id, success, err))
        
        self.track_worker(worker)
        worker.start()
        self.refresh_queue_table()

    def on_transfer_progress(self, job_id, transferred, total, speed):
        for job in self.transfer_queue:
            if job["id"] == job_id:
                job["size"] = total
                pct = int((transferred / total) * 100) if total > 0 else 0
                job["progress"] = pct
                job["speed"] = speed
                self.progress_bar.setValue(pct)
                break
        self.refresh_queue_table()

    def on_transfer_finished(self, job_id, success, error_msg):
        if job_id in self.active_workers:
            del self.active_workers[job_id]
            
        for job in self.transfer_queue:
            if job["id"] == job_id:
                if success:
                    job["status"] = "Completed"
                    self.log_message(f"✓ Transfer completed: {os.path.basename(job['source'])}")
                else:
                    if error_msg == "Cancelled":
                        job["status"] = "Cancelled"
                        self.log_message(f"⚠️ Transfer cancelled by user: {os.path.basename(job['source'])}")
                    else:
                        job["status"] = "Failed"
                        self.log_message(f"❌ Transfer failed for {os.path.basename(job['source'])}: {error_msg}")
                break
                
        self.progress_bar.setValue(0)
        self.refresh_queue_table()
        self.populate_local_dir()
        self.fetch_remote_dir()
        
        self.process_next_queue_item()

    def cancel_transfer(self, job_id):
        if job_id in self.active_workers:
            self.active_workers[job_id].is_cancelled = True
        else:
            for job in self.transfer_queue:
                if job["id"] == job_id and job["status"] == "Queued":
                    job["status"] = "Cancelled"
                    self.log_message(f"⚠️ Cancelled queued transfer: {os.path.basename(job['source'])}")
                    break
        self.refresh_queue_table()
        self.process_next_queue_item()


class TabbedFTPClientApp(QMainWindow):
    """Each page owns its clients, workers, paths and transfer queue."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Client (SFTP / FTP)")
        self.setWindowIcon(QIcon(APP_ICON_PATH))
        self.resize(1280, 850)
        self.setStyleSheet(DARK_THEME_QSS)
        self.connection_tabs = QTabWidget()
        self.connection_tabs.setTabsClosable(True)
        self.connection_tabs.setMovable(True)
        self.connection_tabs.tabCloseRequested.connect(self.close_connection_tab)
        self.setCentralWidget(self.connection_tabs)
        add_button = QPushButton("+ 새 연결")
        add_button.clicked.connect(self.add_connection_tab)
        self.connection_tabs.setCornerWidget(add_button)
        new_action = QAction("새 연결 탭", self)
        new_action.setShortcut("Ctrl+T")
        new_action.triggered.connect(self.add_connection_tab)
        self.addAction(new_action)
        close_action = QAction("연결 탭 닫기", self)
        close_action.setShortcut("Ctrl+W")
        close_action.triggered.connect(
            lambda: self.close_connection_tab(self.connection_tabs.currentIndex()))
        self.addAction(close_action)
        self.add_connection_tab()
        self.setWindowTitle(f"File Transfer Client (SFTP / FTP) {APP_VERSION}")
        self.pending_update = None
        self.update_worker = None
        self.close_after_update_check = False
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            self.update_worker = UpdateWorker(self, check_only=True)
            self.update_worker.available.connect(self.on_update_available)
            self.update_worker.ready.connect(self.on_update_ready)
            self.update_worker.message.connect(lambda message: self.statusBar().showMessage(message))
            self.update_worker.finished.connect(self.finish_update_check)
            self.update_worker.start()

    def on_update_available(self, release):
        # Let the checking thread finish before replacing its reference.
        QTimer.singleShot(0, lambda: self.confirm_update(release))

    def confirm_update(self, release):
        if self.close_after_update_check:
            return
        if self.update_worker is not None and self.update_worker.isRunning():
            QTimer.singleShot(100, lambda: self.confirm_update(release))
            return
        answer = QMessageBox.question(
            self, "새 버전 알림",
            f"새 버전이 있습니다. ({release['tag_name']})\n업데이트하시겠습니까?\n"
            "업데이트가 완료되면 프로그램이 자동으로 재시작됩니다.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok)
        if answer != QMessageBox.StandardButton.Ok:
            return
        self.update_worker = UpdateWorker(self, release=release)
        self.update_worker.ready.connect(self.on_update_ready)
        self.update_worker.message.connect(lambda message: self.statusBar().showMessage(message))
        self.update_worker.finished.connect(self.finish_update_check)
        self.update_worker.start()
        self.statusBar().showMessage("새 버전을 다운로드하고 있습니다…")

    def on_update_ready(self, path, digest, version):
        self.pending_update = (path, digest)
        self.statusBar().showMessage(f"{version} 다운로드 완료. 업데이트 후 재시작합니다…")

    def finish_update_check(self):
        if self.close_after_update_check:
            self.close()
        elif self.pending_update:
            self.restart_for_update()

    def restart_for_update(self):
        if not self.pending_update:
            return
        sessions = [self.connection_tabs.widget(i)
                    for i in range(self.connection_tabs.count())]
        if any(session.has_running_operations() for session in sessions):
            self.statusBar().showMessage("진행 중인 작업이 끝나면 업데이트 후 재시작합니다…")
            QTimer.singleShot(1000, self.restart_for_update)
            return
        self.close()

    def add_connection_tab(self):
        session = SFTPClientApp()
        session.embedded_session = True
        index = self.connection_tabs.addTab(session, "새 연결")
        session.connection_changed.connect(lambda: self.update_tab_title(session))
        self.connection_tabs.setCurrentIndex(index)
        return session

    def update_tab_title(self, session):
        index = self.connection_tabs.indexOf(session)
        if index < 0:
            return
        host = session.host_input.text().strip()
        if session.sftp_client:
            title = f"{session.protocol_combo.currentText()} · {host}"
        elif not session.connect_btn.isEnabled():
            title = f"{host} · 연결 중…"
        else:
            title = f"{host} · 연결 안 됨" if host else "새 연결"
        self.connection_tabs.setTabText(index, title)
        self.connection_tabs.setTabToolTip(index, title)

    def close_connection_tab(self, index):
        session = self.connection_tabs.widget(index)
        if session is None:
            return
        if session.has_running_operations():
            QMessageBox.information(self, "작업 진행 중",
                                    "이 탭의 연결 또는 전송 작업이 끝난 후 닫아 주세요.")
            return
        session.shutdown_session()
        self.connection_tabs.removeTab(index)
        session.deleteLater()
        if self.connection_tabs.count() == 0:
            self.add_connection_tab()

    def closeEvent(self, event):
        sessions = [self.connection_tabs.widget(i)
                    for i in range(self.connection_tabs.count())]
        if any(session.has_running_operations() for session in sessions):
            QMessageBox.information(self, "작업 진행 중",
                                    "모든 탭의 연결 또는 전송 작업이 끝난 후 종료해 주세요.")
            event.ignore()
            return
        for session in sessions:
            session.shutdown_session()
        if self.update_worker is not None and self.update_worker.isRunning():
            self.close_after_update_check = True
            self.update_worker.requestInterruption()
            self.statusBar().showMessage("업데이트 확인을 정리한 후 종료합니다…")
            event.ignore()
            return
        if self.pending_update:
            try:
                install_on_exit(*self.pending_update, restart=True)
                self.pending_update = None
            except Exception as error:
                self.statusBar().showMessage(f"업데이트 적용 실패: {error}")
                event.ignore()
                return
        event.accept()


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FTPClient.Desktop")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(APP_ICON_PATH))
    client = TabbedFTPClientApp()
    client.show()
    sys.exit(app.exec())
