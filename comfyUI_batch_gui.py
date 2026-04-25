import os
import sys
import json
import time
import uuid
import urllib.request
import urllib.error

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QFileDialog,
    QMessageBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPlainTextEdit,
    QCheckBox,
    QGroupBox,
    QComboBox,
    QScrollArea,
    QFrame,
    QSplitter,
)


class PatchRowWidget(QFrame):
    def __init__(self, parent=None, default_node_id="", default_field="", default_mode="video_path", default_value=""):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QGridLayout(self)

        self.enabled_cb = QCheckBox("Enable")
        self.enabled_cb.setChecked(True)

        self.node_id_edit = QLineEdit(str(default_node_id))
        self.field_edit = QLineEdit(str(default_field))

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "video_path",
            "OutputDir / PrefixStem",
            "OutputDir / Stem / PrefixStem",
            "fixed_text",
        ])
        idx = self.mode_combo.findText(str(default_mode))
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

        self.value_edit = QLineEdit(str(default_value))
        self.value_edit.setPlaceholderText("Used only for fixed_text")

        self.remove_btn = QPushButton("Remove")

        layout.addWidget(QLabel("Node ID"), 0, 0)
        layout.addWidget(self.node_id_edit, 0, 1)

        layout.addWidget(QLabel("Field"), 0, 2)
        layout.addWidget(self.field_edit, 0, 3)

        layout.addWidget(QLabel("Patch Type"), 1, 0)
        layout.addWidget(self.mode_combo, 1, 1)

        layout.addWidget(QLabel("Fixed Value"), 1, 2)
        layout.addWidget(self.value_edit, 1, 3)

        layout.addWidget(self.enabled_cb, 0, 4)
        layout.addWidget(self.remove_btn, 1, 4)

        self.mode_combo.currentTextChanged.connect(self._update_ui)
        self._update_ui()

    def _update_ui(self):
        mode = self.mode_combo.currentText()
        self.value_edit.setEnabled(mode == "fixed_text")

    def get_data(self):
        return {
            "enabled": self.enabled_cb.isChecked(),
            "node_id": self.node_id_edit.text().strip(),
            "field": self.field_edit.text().strip(),
            "mode": self.mode_combo.currentText(),
            "value": self.value_edit.text().strip(),
        }


class BatchWorker(QThread):
    log_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    done_signal = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = config

    def log(self, text):
        self.log_signal.emit(text)

    @staticmethod
    def normalize_path(path):
        return os.path.abspath(path).replace("\\", "/")

    @staticmethod
    def deep_copy(obj):
        return json.loads(json.dumps(obj))

    @staticmethod
    def get_file_stem(file_path):
        return os.path.splitext(os.path.basename(file_path))[0]

    @staticmethod
    def build_prefixed_name(stem, prefix):
        return f"{prefix}{stem}" if prefix else stem

    def build_output_value(self, file_path, output_dir="", prefix="", mode="OutputDir / PrefixStem"):
        stem = self.get_file_stem(file_path)
        prefixed_name = self.build_prefixed_name(stem, prefix)

        if mode == "OutputDir / PrefixStem":
            if output_dir.strip():
                return self.normalize_path(os.path.join(output_dir, prefixed_name))
            return prefixed_name

        if mode == "OutputDir / Stem / PrefixStem":
            if output_dir.strip():
                return self.normalize_path(os.path.join(output_dir, stem, prefixed_name))
            return self.normalize_path(os.path.join(stem, prefixed_name))

        raise ValueError(f"Unsupported output mode: {mode}")

    @staticmethod
    def load_workflow(workflow_path):
        with open(workflow_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def parse_extensions(ext_string):
        exts = []
        for ext in ext_string.split(","):
            ext = ext.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = "." + ext
            exts.append(ext)
        return tuple(exts)

    @staticmethod
    def patch_node_input(workflow, node_id, field_name, value):
        if node_id not in workflow:
            raise ValueError(f"Node ID '{node_id}' not found in workflow")
        node = workflow[node_id]
        if "inputs" not in node:
            raise ValueError(f"Node '{node_id}' has no 'inputs' section")
        if field_name not in node["inputs"]:
            raise ValueError(f"Field '{field_name}' not found in node '{node_id}' inputs")
        before = node["inputs"][field_name]
        node["inputs"][field_name] = value
        return before, value

    @staticmethod
    def get_files(folder, supported_exts):
        return sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith(supported_exts)
        )

    @staticmethod
    def queue_prompt(comfy_url, prompt):
        prompt_url = f"{comfy_url.rstrip('/')}/prompt"
        payload = {
            "prompt": prompt,
            "client_id": str(uuid.uuid4()),
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            prompt_url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read())
            return result["prompt_id"]

    @staticmethod
    def get_history(comfy_url, prompt_id):
        history_url = f"{comfy_url.rstrip('/')}/history/{prompt_id}"
        try:
            with urllib.request.urlopen(history_url) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError:
            return None

    def wait_for_completion(self, comfy_url, prompt_id):
        self.log(f"Waiting for completion: {prompt_id}")
        while True:
            history = self.get_history(comfy_url, prompt_id)
            if history and prompt_id in history:
                self.log(f"Completed: {prompt_id}")
                return history[prompt_id]
            time.sleep(1)

    def run(self):
        try:
            cfg = self.config

            comfy_url = cfg["comfy_url"]
            input_folder = cfg["input_folder"]
            workflow_path = cfg["workflow_path"]
            output_dir = cfg["output_dir"]
            output_prefix = cfg["output_prefix"]
            extensions = self.parse_extensions(cfg["extensions"])
            write_debug = cfg["write_debug"]
            patch_rows = cfg["patch_rows"]

            workflow = self.load_workflow(workflow_path)
            files = self.get_files(input_folder, extensions)

            if not files:
                self.log("No matching files found.")
                self.done_signal.emit()
                return

            self.log(f"Found {len(files)} file(s).")

            for i, file_path in enumerate(files, start=1):
                file_norm = self.normalize_path(file_path)
                self.log("")
                self.log(f"[{i}/{len(files)}] Processing")
                self.log(f"Input file: {file_norm}")

                wf = self.deep_copy(workflow)

                for row in patch_rows:
                    if not row["enabled"]:
                        continue

                    node_id = row["node_id"]
                    field = row["field"]
                    mode = row["mode"]

                    if mode == "video_path":
                        patch_value = file_norm
                    elif mode in {"OutputDir / PrefixStem", "OutputDir / Stem / PrefixStem"}:
                        patch_value = self.build_output_value(
                            file_path=file_path,
                            output_dir=output_dir,
                            prefix=output_prefix,
                            mode=mode,
                        )
                    elif mode == "fixed_text":
                        patch_value = row["value"]
                    else:
                        raise ValueError(f"Unsupported patch mode: {mode}")

                    before, after = self.patch_node_input(wf, node_id, field, patch_value)
                    self.log(f"Patched node {node_id}.{field}: {before} -> {after}")

                if write_debug:
                    debug_json = os.path.join(os.path.dirname(workflow_path), "debug_patched_workflow.json")
                    with open(debug_json, "w", encoding="utf-8") as f:
                        json.dump(wf, f, indent=2)
                    self.log(f"Wrote debug JSON: {debug_json}")

                prompt_id = self.queue_prompt(comfy_url, wf)
                self.log(f"Queued prompt: {prompt_id}")
                self.wait_for_completion(comfy_url, prompt_id)

            self.log("")
            self.log("All files processed.")
            self.done_signal.emit()

        except Exception as e:
            self.error_signal.emit(str(e))
            self.done_signal.emit()


class ComfyBatchRunnerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Comfy Batch Runner")
        self.resize(1100, 860)
        self.worker = None
        self.patch_rows = []
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(splitter)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)

        config_group = QGroupBox("Batch Settings")
        config_layout = QGridLayout(config_group)

        self.comfy_url_edit = QLineEdit("http://127.0.0.1:8188")
        self.input_folder_edit = QLineEdit()
        self.workflow_edit = QLineEdit()
        self.output_dir_edit = QLineEdit()
        self.output_prefix_edit = QLineEdit("Up_")
        self.extensions_edit = QLineEdit(".mp4,.mov,.mkv,.avi,.webm")
        self.write_debug_cb = QCheckBox("Write debug patched JSON")
        self.write_debug_cb.setChecked(True)

        browse_input_btn = QPushButton("Browse")
        browse_workflow_btn = QPushButton("Browse")
        browse_output_btn = QPushButton("Browse")

        browse_input_btn.clicked.connect(self.pick_input_folder)
        browse_workflow_btn.clicked.connect(self.pick_workflow_json)
        browse_output_btn.clicked.connect(self.pick_output_dir)

        row = 0
        config_layout.addWidget(QLabel("ComfyUI URL"), row, 0)
        config_layout.addWidget(self.comfy_url_edit, row, 1, 1, 3)
        row += 1

        config_layout.addWidget(QLabel("Input Folder"), row, 0)
        config_layout.addWidget(self.input_folder_edit, row, 1, 1, 3)
        config_layout.addWidget(browse_input_btn, row, 5, Qt.AlignmentFlag.AlignRight)
        row += 1

        config_layout.addWidget(QLabel("Workflow API JSON"), row, 0)
        config_layout.addWidget(self.workflow_edit, row, 1, 1, 3)
        config_layout.addWidget(browse_workflow_btn, row, 5,Qt.AlignmentFlag.AlignRight )
        row += 1

        config_layout.addWidget(QLabel("Output Dir"), row, 0)
        config_layout.addWidget(self.output_dir_edit, row, 1, 1, 3)
        config_layout.addWidget(browse_output_btn, row, 5, Qt.AlignmentFlag.AlignRight)
        config_layout.addWidget(browse_output_btn, row, 5, Qt.AlignmentFlag.AlignRight)
        row += 1

        config_layout.addWidget(QLabel("Prefix"), row, 0)
        config_layout.addWidget(self.output_prefix_edit, row, 1)
        config_layout.addWidget(QLabel("Extensions"), row, 2)
        config_layout.addWidget(self.extensions_edit, row, 3)
        row += 1

        config_layout.addWidget(self.write_debug_cb, row, 0, 1, 2)

        top_layout.addWidget(config_group)

        patch_group = QGroupBox("Patch Rules")
        patch_layout = QVBoxLayout(patch_group)

        patch_btn_row = QHBoxLayout()
        self.add_patch_btn = QPushButton("Add Patch Rule")
        self.add_patch_btn.clicked.connect(lambda: self.add_patch_row())
        patch_btn_row.addWidget(self.add_patch_btn)
        patch_btn_row.addStretch()

        patch_layout.addLayout(patch_btn_row)

        self.patch_container = QVBoxLayout()
        self.patch_container.addStretch()

        patch_host = QWidget()
        patch_host.setLayout(self.patch_container)

        patch_scroll = QScrollArea()
        patch_scroll.setWidgetResizable(True)
        patch_scroll.setWidget(patch_host)

        patch_layout.addWidget(patch_scroll)
        top_layout.addWidget(patch_group, 1)

        buttons_row = QHBoxLayout()
        self.test_btn = QPushButton("Test Config")
        self.start_btn = QPushButton("Start Batch")
        self.clear_btn = QPushButton("Clear Log")

        self.test_btn.clicked.connect(self.test_config)
        self.start_btn.clicked.connect(self.start_batch)
        self.clear_btn.clicked.connect(self.clear_log)

        buttons_row.addWidget(self.test_btn)
        buttons_row.addWidget(self.start_btn)
        buttons_row.addWidget(self.clear_btn)
        buttons_row.addStretch()

        top_layout.addLayout(buttons_row)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)

        splitter.addWidget(top_widget)
        splitter.addWidget(self.log_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([560, 260])

        self.add_patch_row(default_node_id="51", default_field="video", default_mode="video_path")
        self.add_patch_row(default_node_id="1", default_field="filename_prefix", default_mode="OutputDir / PrefixStem")

    def add_patch_row(self, checked=False, default_node_id="", default_field="", default_mode="video_path", default_value=""):
        row_widget = PatchRowWidget(
            default_node_id=default_node_id,
            default_field=default_field,
            default_mode=default_mode,
            default_value=default_value,
        )
        row_widget.remove_btn.clicked.connect(lambda: self.remove_patch_row(row_widget))
        self.patch_rows.append(row_widget)
        self.patch_container.insertWidget(self.patch_container.count() - 1, row_widget)

    def remove_patch_row(self, row_widget):
        if row_widget in self.patch_rows:
            self.patch_rows.remove(row_widget)
            row_widget.setParent(None)
            row_widget.deleteLater()

    def log(self, text):
        self.log_box.appendPlainText(text)

    def clear_log(self):
        self.log_box.clear()

    def pick_input_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if path:
            self.input_folder_edit.setText(path)

    def pick_workflow_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Workflow API JSON", "", "JSON Files (*.json);;All Files (*)")
        if path:
            self.workflow_edit.setText(path)

    def pick_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self.output_dir_edit.setText(path)

    def collect_config(self):
        return {
            "comfy_url": self.comfy_url_edit.text().strip(),
            "input_folder": self.input_folder_edit.text().strip(),
            "workflow_path": self.workflow_edit.text().strip(),
            "output_dir": self.output_dir_edit.text().strip(),
            "output_prefix": self.output_prefix_edit.text().strip(),
            "extensions": self.extensions_edit.text().strip(),
            "write_debug": self.write_debug_cb.isChecked(),
            "patch_rows": [row.get_data() for row in self.patch_rows],
        }

    def validate_config(self, cfg):
        if not cfg["comfy_url"]:
            return False, "ComfyUI URL is required."
        if not cfg["input_folder"] or not os.path.isdir(cfg["input_folder"]):
            return False, "Valid input folder is required."
        if not cfg["workflow_path"] or not os.path.isfile(cfg["workflow_path"]):
            return False, "Valid workflow API JSON is required."

        enabled_rows = [r for r in cfg["patch_rows"] if r["enabled"]]
        if not enabled_rows:
            return False, "At least one enabled patch rule is required."

        for row in enabled_rows:
            if not row["node_id"]:
                return False, "Every enabled patch rule needs a node ID."
            if not row["field"]:
                return False, "Every enabled patch rule needs a field name."
            if row["mode"] == "fixed_text" and row["value"] == "":
                return False, "Fixed text patch rules need a value."

        if cfg["output_dir"]:
            os.makedirs(cfg["output_dir"], exist_ok=True)

        try:
            with open(cfg["workflow_path"], "r", encoding="utf-8") as f:
                workflow = json.load(f)
        except Exception as e:
            return False, f"Could not read workflow JSON: {e}"

        for row in enabled_rows:
            node_id = row["node_id"]
            field = row["field"]
            if node_id not in workflow:
                return False, f"Node '{node_id}' not found in workflow."
            if "inputs" not in workflow[node_id]:
                return False, f"Node '{node_id}' has no inputs."
            if field not in workflow[node_id]["inputs"]:
                return False, f"Field '{field}' not found in node '{node_id}'."

        return True, "OK"

    def test_config(self):
        cfg = self.collect_config()
        ok, msg = self.validate_config(cfg)
        if ok:
            QMessageBox.information(self, "Config Test", "Config looks good.")
        else:
            QMessageBox.critical(self, "Config Error", msg)

    def start_batch(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Busy", "Batch is already running.")
            return

        cfg = self.collect_config()
        ok, msg = self.validate_config(cfg)
        if not ok:
            QMessageBox.critical(self, "Config Error", msg)
            return

        self.start_btn.setEnabled(False)
        self.worker = BatchWorker(cfg)
        self.worker.log_signal.connect(self.log)
        self.worker.error_signal.connect(self.on_worker_error)
        self.worker.done_signal.connect(self.on_worker_done)
        self.worker.start()

    def on_worker_error(self, text):
        self.log(f"ERROR: {text}")
        QMessageBox.critical(self, "Batch Error", text)

    def on_worker_done(self):
        self.start_btn.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ComfyBatchRunnerWindow()
    window.show()
    sys.exit(app.exec())