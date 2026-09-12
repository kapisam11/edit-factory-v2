"""Application entrypoint implementations for Edit Factory v2."""

from .upload_cleanup import cleanup_orphan_uploads

__all__ = ["cleanup_orphan_uploads"]
