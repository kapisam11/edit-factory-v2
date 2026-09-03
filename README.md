
# AI Video Factory

Generate research-backed short video packages with auto-edit support.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt

# Generate a package
python cli.py "Minecraft betrayal on SMP"

# Auto-edit from raw footage
python cli.py "Minecraft betrayal on SMP" --input-video recording.mp4 --auto-edit
```

## Entry Points

| Script | Purpose |
|--------|---------|
| `cli.py` | **Main entry point** — generate packages and run auto-edit |
| `tools/apply_polish.py` | Polish an existing package (hooks, thresholds) |
| `tools/build_dashboard.py` | Generate HTML review dashboard |
| `tools/regenerate_visual_hooks.py` | Re-score hooks across all packages |

The following scripts are **legacy / demo** and not needed for normal use:
- `main.py` — old monolithic entry point (kept for reference)
- `make_edit.py` — early prototype
- `run_all_demo.py` — batch demo runner
- `demo_learning_system.py` — learning system demo

## Architecture

```
cli.py
  └── ai_video_factory/
        ├── factory.py          # Package creation orchestrator
        ├── composer.py         # Auto-edit orchestration
        ├── segment_engine.py   # Silence detection & beat snapping
        ├── effects_engine.py   # Cinematic filters
        ├── render_engine.py    # Safe ffmpeg execution
        ├── edit_automation.py  # ffmpeg trimming helpers
        ├── hardware.py         # GPU/encoder detection
        └── ...
```

## Optional Features

- **Groq enrichment**: `export GROQ_API_KEY=...` then add `--use-groq`
- **ElevenLabs VO**: `export ELEVENLABS_API_KEY=...` then add `--elevenlabs-key ...`
- **Beat sync**: `pip install librosa` for music-aligned cuts
- **Interactive review**: add `--interactive` to tweak plan before editing

## Requirements

- Python 3.9+
- ffmpeg on PATH
- Optional: GPU for hardware-accelerated encoding (auto-detected)
