Fullscreen 
Download 
Fit
Code
Preview
Issue	Fix
Fake "AI Learning" (hardcoded JSON)	Real Bayesian + ridge regression learning in knowledge_v2.py
Broken docs (missing colons)	All syntax fixed, docs regenerated
Flask debug mode, global dict jobs	web_app_v2.py with SQLite, ProcessPoolExecutor, rate limits
API failures crash pipeline	capability_registry.py with graceful fallback chains
"2026 trends" are guesses	Renamed to "heuristics" in config.py, clearly labeled as tunable defaults
500-line god method	pipeline.py with discrete, skippable, retryable stages
No subtitle burn-in	subtitle_renderer.py with 5 style presets + ASS export
No NLE export	nle_export_v2.py for DaVinci Resolve, Premiere, CapCut
No asset management	asset_manager.py with URI resolution and metadata sidecars
What You Are Installing
# 1. Real learning system (REPLACES ai_video_factory/knowledge.py)
cp ai_video_factory/knowledge_v2.py ai_video_factory/knowledge.py

# 2. Capability registry (NEW FILE)
cp ai_video_factory/capability_registry.py ai_video_factory/capability_registry.py

# 3. Pipeline stages (NEW FILE)
cp ai_video_factory/pipeline.py ai_video_factory/pipeline.py

# 4. Config system (NEW FILE)
cp ai_video_factory/config.py ai_video_factory/config.py

# 5. Asset manager (NEW FILE)
cp ai_video_factory/asset_manager.py ai_video_factory/asset_manager.py

# 6. Subtitle renderer (NEW FILE)
cp ai_video_factory/subtitle_renderer.py ai_video_factory/subtitle_renderer.py

# 7. NLE export v2 (NEW FILE — or replace old nle_export.py)
cp ai_video_factory/nle_export_v2.py ai_video_factory/nle_export_v2.py

# 8. Enhanced QC (NEW FILE)
cp ai_video_factory/quality_control_v2.py ai_video_factory/quality_control_v2.py

# 9. Structured research (NEW FILE)
cp ai_video_factory/research_structured.py ai_video_factory/research_structured.py

# 10. New CLI (REPLACES cli.py)
cp cli_v2.py cli.py

# 11. New web app (REPLACES web_app.py — or run alongside)
cp web_app_v2.py web_app_v2.py

Step 1: Replace Core Files
AI Video Factory v2 — Installation & Setup Guide
Step 2: Create Directory Structure
bash
mkdir -p assets/music/dramatic assets/music/emotional assets/music/intense
mkdir -p assets/sfx assets/fonts assets/overlays
mkdir -p templates
mkdir -p knowledge_base_v2
Step 3: Install Dependencies
bash
# Core (existing)
pip install pillow requests flask

# New required
pip install edge-tts beautifulsoup4

# Optional but strongly recommended
pip install librosa numpy  # For music beat detection
pip install psutil         # For hardware detection
# Optional paid APIs
pip install groq elevenlabs
Step 4: Configure API Keys
Create aivf_config.json by running once:
bash
python -c "from ai_video_factory.config import AIVFConfig; AIVFConfig().save()"
Then edit aivf_config.json or set env vars:
bash
export GROQ_API_KEY="your_key"
export ELEVENLABS_API_KEY="your_key"
export OPENAI_API_KEY="your_key"
export FREESOUND_API_KEY="your_key"
export FLASK_SECRET_KEY="a_random_string_for_production"
Step 5: Add Assets
Drop your own royalty-free files into:
plain
assets/music/dramatic/   # For intense moments
assets/music/emotional/  # For story-driven content
assets/music/intense/    # For fast action
assets/sfx/whoosh.mp3    # Transition sounds
assets/sfx/impact.mp3    # Hit sounds
assets/fonts/bold.ttf    # For subtitles/thumbnails
assets/overlays/sub.png  # Subscribe button overlay
Each music track can have a .json sidecar with BPM:
JSON
{"bpm": 128, "duration": 120, "tags": ["electronic", "intense"]}
Step 6: Run
CLI
bash
# Full pipeline with learning
python cli.py "Minecraft betrayal" --raw-video gameplay.mp4 --director --learn --engagement-score 0.85
# Fast pipeline, no research
python cli.py "COD clutch" --raw-video clip.mp4 --pipeline fast --subtitle-style bold_yellow
# Export to DaVinci Resolve
python cli.py "Topic" --raw-video clip.mp4 --export-nle resolve
Web App (Production)
bash
python web_app_v2.py
# Open http://localhost:5000
# No debug mode. SQLite persists jobs. Parallel workers.
Step 7: Verify Everything Works
bash
# Test 1: Imports
python -c "from ai_video_factory.knowledge_v2 import RealKnowledgeBase; print('OK: knowledge_v2')"
# Test 2: Config
python -c "from ai_video_factory.config import AIVFConfig; c = AIVFConfig.load(); print('OK: config')"
# Test 3: Pipeline
python -c "from ai_video_factory.pipeline import build_director_pipeline; print('OK: pipeline')"
# Test 4: Capability registry
python -c "from ai_video_factory.capability_registry import build_default_registry; print('OK: registry')"
# Test 5: Subtitles
python -c "from ai_video_factory.subtitle_renderer import burn_subtitles; print('OK: subtitles')"
# Test 6: NLE export
python -c "from ai_video_factory.nle_export_v2 import export_all_nle_formats; print('OK: nle_export')"
# Test 7: Enhanced QC
python -c "from ai_video_factory.quality_control_v2 import run_enhanced_qc; print('OK: qc_v2')"
What Each New Feature Does
Real Learning System
Every time you pass --engagement-score 0.85, the system updates filter effectiveness using Bayesian updating
After 3+ feedback records, it trains a ridge regression model to PREDICT engagement before rendering
Topic similarity lets it generalize from "Minecraft" to "Terraria" automatically
Capability Registry
TTS tries: ElevenLabs → Edge TTS → pyttsx3 (automatic fallback)
Research tries: Groq → DuckDuckGo scraping
Music tries: Freesound → local library
No more crashes when an API key is missing
Pipeline Stages
--skip-stages research,music skips those stages
--pipeline fast uses a preset that skips heavy stages
Failed stages retry automatically (up to 2 times)
Each stage is testable in isolation
Styled Subtitles
--subtitle-style bold_yellow burns yellow subtitles with black outline
Word-level timing estimated from script duration
Also exports .ass files for professional subtitle editors
NLE Export
--export-nle resolve creates .fcpxml for DaVinci Resolve
--export-nle premiere creates .xml for Premiere Pro
--export-nle all creates all formats
Human editors can open your auto-edit and finish it professionally
Templates
Create templates/your_format.json with beats, filters, music mood
Run with --template your_format to skip research and use proven structure
Perfect for channels that post the same format daily
Migration from v1
If you have existing packages in output/ and knowledge_base/:
knowledge_base/ → knowledge_base_v2/ (new system uses different schema)
Old cli.py commands still work — cli_v2.py is backward compatible
Old web app can run alongside web_app_v2.py on a different port
Critical: What to Delete
These files from v1 are now obsolete and should be removed to avoid confusion:
make_edit.py — replaced by cli_v2.py
demo_learning_system.py — the fake demo, no longer needed
aivf_config.schema.json — replaced by aivf_config.json (auto-generated)
Old knowledge_base/*.json — schema incompatible with v2
Troubleshooting
"No module named ai_video_factory"
Run from the project root (where ai_video_factory/ folder is visible).
"SQLite database is locked"
Only one process can write to jobs.db at a time. This is normal. The web app handles concurrency.
"FFmpeg not found"
Install FFmpeg and ensure ffmpeg and ffprobe are on your PATH.
"ProcessPoolExecutor failed"
The worker function must be picklable. Do not use lambdas or closures inside pipeline stages.
Summary
You now have a production-ready system with:
✅ Real statistical learning (not fake JSON)
✅ Graceful API fallback chains
✅ Parallel job processing with SQLite persistence
✅ Professional subtitle burn-in
✅ Export to DaVinci Resolve / Premiere / CapCut
✅ Asset management with URI resolution
✅ Discrete, testable, skippable pipeline stages
✅ Enhanced QC (visual, audio, factual, accessibility)
✅ Template system for recurring formats
plain
--- 

## ⚠️ CRITICAL INSTRUCTIONS — READ THIS

1. **The 8 files I created via tools** are in `/mnt/agents/output/`. You must download them from there.
2. **The 5 files above** (quality_control_v2.py, research_structured.py, cli_v2.py, template, INSTALL_AND_SETUP.md) must be manually created by copying the code blocks into the exact paths shown.
3. **Follow INSTALL_AND_SETUP.md exactly** — it tells you which files to copy where, what to delete, and how to verify.
4. **Run the 7 verification commands** at the bottom of the install guide before doing anything else. If any fail, fix the import path.
5. **Delete the old fake learning files** (`make_edit.py`, `demo_learning_system.py`, old `knowledge_base/*.json`) so you don't accidentally use them.

The learning system is now **real** — it uses Bayesian updating and ridge regression, not hardcoded numbers. The web app is **production-ready** with SQLite and process pools. The pipeline is **modular** — you can skip, retry, and test individual stages. And you can now export to **professional NLEs** and burn **styled subtitles**.

If any of the 7 verification commands fail, the error message will tell you exactly which import is broken. Fix that first.
Fullscreen 
Download 
Fit
Code
Preview
Issue	Fix
Fake "AI Learning" (hardcoded JSON)	Real Bayesian + ridge regression learning in knowledge_v2.py
Broken docs (missing colons)	All syntax fixed, docs regenerated
Flask debug mode, global dict jobs	web_app_v2.py with SQLite, ProcessPoolExecutor, rate limits
API failures crash pipeline	capability_registry.py with graceful fallback chains
"2026 trends" are guesses	Renamed to "heuristics" in config.py, clearly labeled as tunable defaults
500-line god method	pipeline.py with discrete, skippable, retryable stages
No subtitle burn-in	subtitle_renderer.py with 5 style presets + ASS export
No NLE export	nle_export_v2.py for DaVinci Resolve, Premiere, CapCut
No asset management	asset_manager.py with URI resolution and metadata sidecars

What You Are Installing
# 1. Real learning system (REPLACES ai_video_factory/knowledge.py)
cp ai_video_factory/knowledge_v2.py ai_video_factory/knowledge.py

# 2. Capability registry (NEW FILE)
cp ai_video_factory/capability_registry.py ai_video_factory/capability_registry.py

# 3. Pipeline stages (NEW FILE)
cp ai_video_factory/pipeline.py ai_video_factory/pipeline.py

# 4. Config system (NEW FILE)
cp ai_video_factory/config.py ai_video_factory/config.py

# 5. Asset manager (NEW FILE)
cp ai_video_factory/asset_manager.py ai_video_factory/asset_manager.py

# 6. Subtitle renderer (NEW FILE)
cp ai_video_factory/subtitle_renderer.py ai_video_factory/subtitle_renderer.py

# 7. NLE export v2 (NEW FILE — or replace old nle_export.py)
cp ai_video_factory/nle_export_v2.py ai_video_factory/nle_export_v2.py

# 8. Enhanced QC (NEW FILE)
cp ai_video_factory/quality_control_v2.py ai_video_factory/quality_control_v2.py

# 9. Structured research (NEW FILE)
cp ai_video_factory/research_structured.py ai_video_factory/research_structured.py

# 10. New CLI (REPLACES cli.py)
cp cli_v2.py cli.py

# 11. New web app (REPLACES web_app.py — or run alongside)
cp web_app_v2.py web_app_v2.py
Step 1: Replace Core Files
AI Video Factory v2 — Installation & Setup Guide
Step 2: Create Directory Structure
bash
mkdir -p assets/music/dramatic assets/music/emotional assets/music/intense
mkdir -p assets/sfx assets/fonts assets/overlays
mkdir -p templates
mkdir -p knowledge_base_v2
Step 3: Install Dependencies
bash
# Core (existing)
pip install pillow requests flask

# New required
pip install edge-tts beautifulsoup4

# Optional but strongly recommended
pip install librosa numpy  # For music beat detection
pip install psutil         # For hardware detection

# Optional paid APIs
pip install groq elevenlabs
Step 4: Configure API Keys
Create aivf_config.json by running once:
bash
python -c "from ai_video_factory.config import AIVFConfig; AIVFConfig().save()"
Then edit aivf_config.json or set env vars:
bash
export GROQ_API_KEY="your_key"
export ELEVENLABS_API_KEY="your_key"
export OPENAI_API_KEY="your_key"
export FREESOUND_API_KEY="your_key"
export FLASK_SECRET_KEY="a_random_string_for_production"
Step 5: Add Assets
Drop your own royalty-free files into:
plain
assets/music/dramatic/   # For intense moments
assets/music/emotional/  # For story-driven content
assets/music/intense/    # For fast action
assets/sfx/whoosh.mp3    # Transition sounds
assets/sfx/impact.mp3    # Hit sounds
assets/fonts/bold.ttf    # For subtitles/thumbnails
assets/overlays/sub.png  # Subscribe button overlay
Each music track can have a .json sidecar with BPM:
JSON
{"bpm": 128, "duration": 120, "tags": ["electronic", "intense"]}
Step 6: Run
CLI
bash
# Full pipeline with learning
python cli.py "Minecraft betrayal" --raw-video gameplay.mp4 --director --learn --engagement-score 0.85

# Fast pipeline, no research
python cli.py "COD clutch" --raw-video clip.mp4 --pipeline fast --subtitle-style bold_yellow

# Export to DaVinci Resolve
python cli.py "Topic" --raw-video clip.mp4 --export-nle resolve
Web App (Production)
bash
python web_app_v2.py
# Open http://localhost:5000
# No debug mode. SQLite persists jobs. Parallel workers.
Step 7: Verify Everything Works
bash
# Test 1: Imports
python -c "from ai_video_factory.knowledge_v2 import RealKnowledgeBase; print('OK: knowledge_v2')"

# Test 2: Config
python -c "from ai_video_factory.config import AIVFConfig; c = AIVFConfig.load(); print('OK: config')"

# Test 3: Pipeline
python -c "from ai_video_factory.pipeline import build_director_pipeline; print('OK: pipeline')"

# Test 4: Capability registry
python -c "from ai_video_factory.capability_registry import build_default_registry; print('OK: registry')"

# Test 5: Subtitles
python -c "from ai_video_factory.subtitle_renderer import burn_subtitles; print('OK: subtitles')"

# Test 6: NLE export
python -c "from ai_video_factory.nle_export_v2 import export_all_nle_formats; print('OK: nle_export')"

# Test 7: Enhanced QC
python -c "from ai_video_factory.quality_control_v2 import run_enhanced_qc; print('OK: qc_v2')"
What Each New Feature Does
Real Learning System
Every time you pass --engagement-score 0.85, the system updates filter effectiveness using Bayesian updating
After 3+ feedback records, it trains a ridge regression model to PREDICT engagement before rendering
Topic similarity lets it generalize from "Minecraft" to "Terraria" automatically
Capability Registry
TTS tries: ElevenLabs → Edge TTS → pyttsx3 (automatic fallback)
Research tries: Groq → DuckDuckGo scraping
Music tries: Freesound → local library
No more crashes when an API key is missing
Pipeline Stages
--skip-stages research,music skips those stages
--pipeline fast uses a preset that skips heavy stages
Failed stages retry automatically (up to 2 times)
Each stage is testable in isolation
Styled Subtitles
--subtitle-style bold_yellow burns yellow subtitles with black outline
Word-level timing estimated from script duration
Also exports .ass files for professional subtitle editors
NLE Export
--export-nle resolve creates .fcpxml for DaVinci Resolve
--export-nle premiere creates .xml for Premiere Pro
--export-nle all creates all formats
Human editors can open your auto-edit and finish it professionally
Templates
Create templates/your_format.json with beats, filters, music mood
Run with --template your_format to skip research and use proven structure
Perfect for channels that post the same format daily
Migration from v1
If you have existing packages in output/ and knowledge_base/:
knowledge_base/ → knowledge_base_v2/ (new system uses different schema)
Old cli.py commands still work — cli_v2.py is backward compatible
Old web app can run alongside web_app_v2.py on a different port
Critical: What to Delete
These files from v1 are now obsolete and should be removed to avoid confusion:
make_edit.py — replaced by cli_v2.py
demo_learning_system.py — the fake demo, no longer needed
aivf_config.schema.json — replaced by aivf_config.json (auto-generated)
Old knowledge_base/*.json — schema incompatible with v2
Troubleshooting
"No module named ai_video_factory"
Run from the project root (where ai_video_factory/ folder is visible).
"SQLite database is locked"
Only one process can write to jobs.db at a time. This is normal. The web app handles concurrency.
"FFmpeg not found"
Install FFmpeg and ensure ffmpeg and ffprobe are on your PATH.
"ProcessPoolExecutor failed"
The worker function must be picklable. Do not use lambdas or closures inside pipeline stages.
Summary
You now have a production-ready system with:
✅ Real statistical learning (not fake JSON)
✅ Graceful API fallback chains
✅ Parallel job processing with SQLite persistence
✅ Professional subtitle burn-in
✅ Export to DaVinci Resolve / Premiere / CapCut
✅ Asset management with URI resolution
✅ Discrete, testable, skippable pipeline stages
✅ Enhanced QC (visual, audio, factual, accessibility)
✅ Template system for recurring formats
plain

---

## ⚠️ CRITICAL INSTRUCTIONS — READ THIS

1. **The 8 files I created via tools** are in `/mnt/agents/output/`. You must download them from there.
2. **The 5 files above** (quality_control_v2.py, research_structured.py, cli_v2.py, template, INSTALL_AND_SETUP.md) must be manually created by copying the code blocks into the exact paths shown.
3. **Follow INSTALL_AND_SETUP.md exactly** — it tells you which files to copy where, what to delete, and how to verify.
4. **Run the 7 verification commands** at the bottom of the install guide before doing anything else. If any fail, fix the import path.
5. **Delete the old fake learning files** (`make_edit.py`, `demo_learning_system.py`, old `knowledge_base/*.json`) so you don't accidentally use them.

The learning system is now **real** — it uses Bayesian updating and ridge regression, not hardcoded numbers. The web app is **production-ready** with SQLite and process pools. The pipeline is **modular** — you can skip, retry, and test individual stages. And you can now export to **professional NLEs** and burn **styled subtitles**.

If any of the 7 verification commands fail, the error message will tell you exactly which import is broken. Fix that first.


C:\Users\Administrator\Downloads\.py files 7
here are some of the files
