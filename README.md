# ComfyUI Batch GUI

A GUI tool to batch process ComfyUI workflows on a folder of inputs.

## Features
- Graphical interface for configuring batch processing
- Support for multiple patch types (video path, output directory, fixed text)
- Real-time logging during batch processing
- Configurable workflow templates

## Usage

### Prerequisites
- Python 3.7 or higher
- PyQt6 library
- ComfyUI installation

### Installation
1. Install required dependencies:
   ```bash
   pip install PyQt6
   ```

2. Clone or download this repository

### Running the Tool
1. Have your comfyUI running. 

2. Run the script:
   ```bash
   python comfyUI_batch_gui.py
   ```

3. In the GUI, select your workflow JSON file and input directory

4. Configure patches to modify the workflow: Use **NODE ID** and **FIELD NAME**
    - Patch the input nodes and video/ image field with the video_path to iterate through the input folder.
    - Patch the output node's file prefix with different permutations:
        - OutputDir/ PrefixStem (preferred for videos), where stem `filename` in `path/filename.mp4` input file.
        - Output/ Stem/ PrefixStem (preferred for image sequences)
    - You can add more patch fields if needed.

5. Click "Start Batch Processing" to begin

### Configuration Options
- **Workflow Path**: Select the ComfyUI workflow template (JSON format)
- **Input Directory**: Select the folder containing input files to process
- **Patch Rows**: Add rows to define how to modify the workflow for each input:
  - Node ID: The node in the workflow to modify
  - Field: The field within the node to modify
  - Patch Type: How to apply the modification (video_path, OutputDir, fixed_text)
  - Fixed Value: For fixed_text mode, the value to use

### Tips for Use
1. Ensure your workflow template is properly configured before batch processing
2. Test with a small set of input files first
3. Monitor the log output for any errors during processing
4. The output directory will be automatically created with a timestamped name
5. For large batches, consider running in smaller chunks to avoid memory issues

### File Structure
- `comfyUI_batch_gui.py` - Main GUI application
- `LICENSE` - License information

## License
This project is licensed under the MIT License.
