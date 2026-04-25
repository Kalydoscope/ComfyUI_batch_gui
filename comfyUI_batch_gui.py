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

    def run(self):
        try:
            # Get the current working directory
            current_dir = os.getcwd()
            
            # Create a unique output directory for this batch run
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_dir = os.path.join(current_dir, f"batch_output_{timestamp}")
            os.makedirs(output_dir, exist_ok=True)
            
            self.log_signal.emit(f"Output directory: {output_dir}")
            
            # Load the workflow template
            workflow_path = self.config.get("workflow_path", "")
            if not workflow_path or not os.path.exists(workflow_path):
                raise Exception("Invalid workflow path")
                
            with open(workflow_path, 'r') as f:
                workflow = json.load(f)
                
            # Get input directory and file list
            input_dir = self.config.get("input_dir", "")
            if not input_dir or not os.path.exists(input_dir):
                raise Exception("Invalid input directory")
                
            files = [f for f in os.listdir(input_dir) 
                    if os.path.isfile(os.path.join(input_dir, f))]
            
            # Process each file
            for i, filename in enumerate(files):
                self.log_signal.emit(f"Processing {filename} ({i+1}/{len(files)})")
                
                # Create a copy of the workflow
                workflow_copy = json.loads(json.dumps(workflow))
                
                # Apply patches to the workflow
                patches = self.config.get("patches", [])
                for patch in patches:
                    if not patch.get("enabled", True):
                        continue
                        
                    node_id = patch.get("node_id", "")
                    field = patch.get("field", "")
                    mode = patch.get("mode", "video_path")
                    value = patch.get("value", "")
                    
                    # Apply the patch based on mode
                    if mode == "video_path":
                        # Find and replace video path in the workflow
                        for node_id_key, node_data in workflow_copy.items():
                            if node_id_key == node_id:
                                if field in node_data:
                                    node_data[field] = os.path.join(input_dir, filename)
                    elif mode == "OutputDir / PrefixStem":
                        # Apply to OutputDir and PrefixStem fields
                        for node_id_key, node_data in workflow_copy.items():
                            if node_id_key == node_id:
                                if field in node_data:
                                    node_data[field] = os.path.join(output_dir, filename)
                    elif mode == "OutputDir / Stem / PrefixStem":
                        # Apply to OutputDir, Stem and PrefixStem fields
                        for node_id_key, node_data in workflow_copy.items():
                            if node_id_key == node_id:
                                if field in node_data:
                                    node_data[field] = os.path.join(output_dir, filename)
                    elif mode == "fixed_text":
                        # Replace with fixed text value
                        for node_id_key, node_data in workflow_copy.items():
                            if node_id_key == node_id:
                                if field in node_data:
                                    node_data[field] = value
                
                # Save the modified workflow to a temporary file
                temp_workflow_path = os.path.join(output_dir, f"temp_workflow_{uuid.uuid4()}.json")
                with open(temp_workflow_path, 'w') as f:
                    json.dump(workflow_copy, f, indent=2)
                
                # Here you would typically call ComfyUI to process the workflow
                # For now, we'll just simulate this with a delay
                self.log_signal.emit(f"Simulating processing of {filename}")
                time.sleep(0.5)  # Simulate processing time
                
                # Clean up temporary file
                os.remove(temp_workflow_path)
                
            self.log_signal.emit("Batch processing completed successfully")
            self.done_signal.emit()
            
        except Exception as e:
            self.error_signal.emit(f"Error during batch processing: {str(e)}")
            self.done_signal.emit()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComfyUI Batch Processing GUI")
        self.resize(800, 600)
        
        # Store the current workflow path
        self.workflow_path = ""
        self.input_dir = ""
        
        # Create the main layout
        layout = QVBoxLayout(self)
        
        # Workflow selection section
        workflow_group = QGroupBox("Workflow Selection")
        workflow_layout = QHBoxLayout()
        
        self.workflow_label = QLabel("Workflow Path:")
        self.workflow_edit = QLineEdit()
        self.workflow_button = QPushButton("Browse...")
        
        workflow_layout.addWidget(self.workflow_label)
        workflow_layout.addWidget(self.workflow_edit)
        workflow_layout.addWidget(self.workflow_button)
        
        workflow_group.setLayout(workflow_layout)
        layout.addWidget(workflow_group)
        
        # Input directory selection section
        input_group = QGroupBox("Input Directory")
        input_layout = QHBoxLayout()
        
        self.input_label = QLabel("Input Directory:")
        self.input_edit = QLineEdit()
        self.input_button = QPushButton("Browse...")
        
        input_layout.addWidget(self.input_label)
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.input_button)
        
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
        
        # Patch configuration section
        patch_group = QGroupBox("Patch Configuration")
        patch_layout = QVBoxLayout()
        
        self.patches_container = QVBoxLayout()
        self.patch_rows = []
        
        # Add a button to add new patch rows
        self.add_patch_button = QPushButton("Add Patch Row")
        self.add_patch_button.clicked.connect(self.add_patch_row)
        
        patch_layout.addLayout(self.patches_container)
        patch_layout.addWidget(self.add_patch_button)
        patch_group.setLayout(patch_layout)
        layout.addWidget(patch_group)
        
        # Log output section
        log_group = QGroupBox("Log Output")
        log_layout = QVBoxLayout()
        
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("Start Batch Processing")
        self.start_button.clicked.connect(self.start_batch_processing)
        
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_batch_processing)
        self.stop_button.setEnabled(False)
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout)
        
        # Connect signals
        self.workflow_button.clicked.connect(self.browse_workflow)
        self.input_button.clicked.connect(self.browse_input_dir)
        
        # Initialize with one patch row
        self.add_patch_row()
        
    def add_patch_row(self):
        """Add a new patch row to the UI"""
        patch_row = PatchRowWidget()
        self.patches_container.addWidget(patch_row)
        self.patch_rows.append(patch_row)
        
    def browse_workflow(self):
        """Open file dialog to select workflow file"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Workflow File",
            "",
            "JSON Files (*.json)"
        )
        if filename:
            self.workflow_edit.setText(filename)
            self.workflow_path = filename
            
    def browse_input_dir(self):
        """Open directory dialog to select input directory"""
        dir_name = QFileDialog.getExistingDirectory(
            self,
            "Select Input Directory"
        )
        if dir_name:
            self.input_edit.setText(dir_name)
            self.input_dir = dir_name
            
    def start_batch_processing(self):
        """Start the batch processing"""
        # Get configuration from UI
        config = {
            "workflow_path": self.workflow_edit.text().strip(),
            "input_dir": self.input_edit.text().strip(),
            "patches": [patch.get_data() for patch in self.patch_rows]
        }
        
        # Validate configuration
        if not config["workflow_path"]:
            QMessageBox.warning(self, "Error", "Please select a workflow file")
            return
            
        if not config["input_dir"]:
            QMessageBox.warning(self, "Error", "Please select an input directory")
            return
            
        if not os.path.exists(config["workflow_path"]):
            QMessageBox.warning(self, "Error", "Workflow file does not exist")
            return
            
        if not os.path.exists(config["input_dir"]):
            QMessageBox.warning(self, "Error", "Input directory does not exist")
            return
            
        # Disable controls during processing
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        # Create and start the worker thread
        self.worker = BatchWorker(config)
        self.worker.log_signal.connect(self.update_log)
        self.worker.error_signal.connect(self.handle_error)
        self.worker.done_signal.connect(self.batch_processing_finished)
        
        self.worker.start()
        
    def stop_batch_processing(self):
        """Stop the batch processing"""
        # In a real implementation, you would need to implement stopping logic
        # For now, we'll just enable the start button again
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
    def update_log(self, message):
        """Update the log output"""
        self.log_output.appendPlainText(message)
        
    def handle_error(self, error_message):
        """Handle errors during batch processing"""
        QMessageBox.critical(self, "Error", error_message)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
    def batch_processing_finished(self):
        """Called when batch processing is finished"""
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
    def closeEvent(self, event):
        """Handle window closing"""
        # Stop any running worker thread
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.terminate()
        event.accept()


def main():
    app = QApplication(sys.argv)
    
    # Create and show the main window
    window = MainWindow()
    window.show()
    
    # Run the application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()