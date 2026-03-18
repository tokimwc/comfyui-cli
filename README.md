# comfyui-cli

CLI tool for ComfyUI - manage workflows, models, and generation from your terminal.

## Install

```bash
pip install -e .
```

## Usage

```bash
comfyui status          # Server status & GPU info
comfyui models          # List model folders
comfyui models clip     # List CLIP models
comfyui queue           # Queue status
comfyui run wf.json     # Execute workflow
comfyui interrupt       # Stop current generation
comfyui history         # Execution history
```
