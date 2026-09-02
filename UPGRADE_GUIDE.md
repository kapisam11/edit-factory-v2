# AI Video Factory v2.0 — Upgrade Guide

## What's New

### 1. Deep Web Research (`web_browser.py`)
**Before:** Only Wikipedia + Reddit + Wikimedia
**Now:** Full DuckDuckGo search + page scraping

```python
from ai_video_factory.web_browser import deep_research

result = deep_research("Minecraft betrayal on SMP", max_search=10, max_scrape=5)
# result["articles"]      → scraped page content
# result["images"]        → image URLs found on pages
# result["videos"]        → video embeds found
# result["summary_text"]  → combined text for analysis
```

**Install:** `pip install beautifulsoup4`

---

### 2. Creator Style Learning (`style_learner.py`)
**Before:** Thumbnails were solid colors with basic text
**Now:** Analyzes top YouTube thumbnails in your niche, learns color palettes, contrast, brightness, text patterns

```python
from ai_video_factory.style_learner import learn_style

profile = learn_style("Minecraft betrayal on SMP")
# profile["recommended_style"]     → "dark_dramatic_high_contrast"
# profile["avg_brightness"]        → 0.25
# profile["avg_saturation"]        → 0.6
# profile["dominant_colors"]       → ["rgb(220,20,60)", "rgb(0,0,0)"]
# profile["text_overlay_rate"]     → 0.9 (90% use text)
```

Thumbnails now use:
- Learned gradient backgrounds
- Vignette effects
- Text with outlines/shadows
- Color palettes from successful creators

---

### 3. Royalty-Free Music (`music_fetcher.py` + `music_mixer.py`)
**Before:** Only mapped emotion → genre label. No actual music.
**Now:** Fetches + mixes copyright-free music, syncs cuts to beats

**Two sources:**
1. **Local library** — Drop MP3s into `music_library/{emotion}/`
2. **Freesound.org** — Auto-download (requires free API key)

```python
from ai_video_factory.music_fetcher import get_track_for_emotion
from ai_video_factory.music_mixer import detect_music_beats, add_music_to_video

# Get track
track = get_track_for_emotion("dramatic", freesound_key="YOUR_KEY")

# Detect BPM & beats
bpm, beats = detect_music_beats(track)

# Mix into final video
add_music_to_video("final.mp4", track, "output.mp4", music_volume=0.2)
```

**Music is automatically:**
- Matched to emotion
- Looped if shorter than video
- Faded out at the end
- Mixed with voiceover (ducking when VO speaks)

---

### 4. Natural Voiceover (`tts.py`)
**Before:** pyttsx3 — robotic, sounds like Windows Narrator
**Now:** Edge TTS — **free, natural, human-sounding**

```bash
pip install edge-tts
```

```python
from ai_video_factory.tts import generate_voiceover

# Uses Edge TTS by default (deep male documentary voice)
generate_voiceover("Nobody expected him to survive...", "vo.mp3")

# Emotion-matched voice
generate_emotional_voiceover(script, "vo.mp3", emotion="dramatic")
```

**Voices available:**
- `en-US-GuyNeural` — Deep documentary narrator (default)
- `en-US-DavisNeural` — Expressive/emotional
- `en-US-TonyNeural` — Energetic
- `en-GB-RyanNeural` — British documentary

**Fallback:** If Edge TTS not installed, falls back to pyttsx3 with a warning.

---

## Updated CLI

```bash
# Install new dependencies
pip install -r requirements.txt
pip install beautifulsoup4  # optional, for deep research
pip install librosa numpy   # optional, for music beat detection

# Full director workflow (now with everything)
python cli.py "Minecraft betrayal on SMP" --raw-video gameplay.mp4 --director

# With Groq + Freesound music
python cli.py "Topic" --raw-video clip.mp4 --director --use-groq --freesound-key $FREESOUND_KEY
```

---

## New Output Files

```
output/Topic_20260804_123456/
    ├── script.txt
    ├── plan.json                    # Now includes music_bpm, music_synced
    ├── creative_brief.json
    ├── metadata.json
    ├── human_check.json
    ├── anti_slop_warnings.json
    ├── video_analysis.json          # Now includes music_beats, music_bpm
    ├── thumbnail.png                # Learned style applied
    ├── thumbnail_vertical.png
    ├── thumbnails/
    │   ├── variant_1.png            # Style variations
    │   ├── variant_2.png
    │   └── variant_3.png
    ├── final_short.mp4              # Rendered video
    ├── final_with_music.mp4         # Video + music mixed
    ├── voiceover.mp3                # Natural Edge TTS voice
    └── music_track.mp3              # Downloaded royalty-free music
```

---

## Setup Checklist

```bash
# 1. Core dependencies
pip install pillow requests edge-tts

# 2. Optional but recommended
pip install beautifulsoup4 librosa numpy psutil

# 3. For paid features (optional)
pip install groq elevenlabs

# 4. For local music library
mkdir -p music_library/dramatic
mkdir -p music_library/emotional
mkdir -p music_library/intense
# Drop royalty-free MP3s into these folders

# 5. For Freesound downloads (free API key)
# Sign up at https://freesound.org/apiv2/apply/
export FREESOUND_API_KEY=your_key_here
```

---

## How It All Works Now

```
VideoDirector.produce()
  ├── 1. deep_research()          ← DuckDuckGo + page scraping
  ├── 2. learn_style()            ← Analyze top YouTube thumbnails
  ├── 3. create_package()         ← Research, script, plan
  ├── 4. fetch_music()            ← Local library or Freesound
  ├── 5. analyze_video()          ← Segments + music beat detection
  ├── 6. compose_short_from_video() ← Auto-edit with beat-sync
  ├── 7. generate_voiceover()     ← Edge TTS (natural voice)
  ├── 8. mix_audio()              ← Music + VO with ducking
  ├── 9. generate_thumbnail()     ← Learned style applied
  ├── 10. generate_metadata()     ← Titles, tags, hashtags
  └── 11. run_human_check()       ← 7-question QC
```
