"""AI Video Factory — Asset Management System.

Manages reusable assets: music, SFX, fonts, overlays.
Assets are referenced by URI: assets://music/dramatic/track_01
"""
import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional


class AssetManager:
    """Central manager for all reusable assets.

    Directory structure:
        assets/
          music/
            dramatic/
              track_01.mp3
              track_01.json  # BPM, duration, tags
            emotional/
            intense/
          sfx/
            whoosh.mp3
            impact.mp3
          fonts/
            bold_title.ttf
          overlays/
            subscribe_button.png
    """

    def __init__(self, root_dir: str = "assets"):
        self.root = Path(root_dir)
        self._ensure_structure()

    def _ensure_structure(self):
        for subdir in ["music/dramatic", "music/emotional", "music/intense",
                       "sfx", "fonts", "overlays"]:
            (self.root / subdir).mkdir(parents=True, exist_ok=True)

    def resolve(self, uri: str) -> Optional[Path]:
        """Resolve an asset URI to a filesystem path.

        URI format: assets://category/subcategory/filename
        Example: assets://music/dramatic/track_01.mp3
        """
        if not uri.startswith("assets://"):
            # Assume it's already a path
            p = Path(uri)
            return p if p.exists() else None
        parts = uri.replace("assets://", "").split("/")
        path = self.root
        for part in parts:
            path = path / part
        return path if path.exists() else None

    def list_assets(self, category: str, subcategory: Optional[str] = None) -> List[Dict]:
        """List all assets in a category with metadata."""
        base = self.root / category
        if subcategory:
            base = base / subcategory
        if not base.exists():
            return []

        results = []
        for f in base.iterdir():
            if f.suffix in (".mp3", ".wav", ".ogg", ".ttf", ".otf", ".png", ".jpg", ".jpeg"):
                meta_file = f.with_suffix(".json")
                meta = {}
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                results.append({
                    "name": f.name,
                    "path": str(f),
                    "uri": f"assets://{category}/{subcategory or ''}/{f.name}".replace("//", "/"),
                    "size_bytes": f.stat().st_size,
                    **meta,
                })
        return results

    def import_asset(self, source_path: str, category: str, subcategory: Optional[str] = None,
                     metadata: Optional[Dict] = None) -> str:
        """Import an external file into the asset library."""
        src = Path(source_path)
        dest_dir = self.root / category
        if subcategory:
            dest_dir = dest_dir / subcategory
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)

        if metadata:
            meta_path = dest.with_suffix(".json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

        return f"assets://{category}/{subcategory or ''}/{src.name}".replace("//", "/")

    def get_random_music(self, mood: str) -> Optional[str]:
        """Get a random music track for a mood."""
        tracks = self.list_assets("music", mood)
        if not tracks:
            return None
        import random
        return random.choice(tracks)["uri"]

    def get_sfx(self, name: str) -> Optional[str]:
        """Get an SFX by name."""
        sfx_dir = self.root / "sfx"
        for ext in (".mp3", ".wav", ".ogg"):
            candidate = sfx_dir / f"{name}{ext}"
            if candidate.exists():
                return f"assets://sfx/{candidate.name}"
        return None
