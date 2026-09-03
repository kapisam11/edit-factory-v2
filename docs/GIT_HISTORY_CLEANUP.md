# Git history cleanup (optional destructive migration)

The working tree no longer contains the large FFmpeg/model runtime bundles, but older commits may still contain those blobs.

Do **not** run this automatically on the shared repository. Rewriting Git history changes commit IDs and requires a coordinated force-push; every existing clone must be re-cloned or carefully reset.

## Recommended procedure

1. Announce a maintenance window and stop pushes.
2. Make a fresh mirror clone.
3. Install `git-filter-repo`.
4. Remove verified historical runtime paths such as `.tools/ffmpeg/` and `.models/mobilenet_ssd/` and any other large generated/binary paths found during the audit.
5. Run a fresh `git fsck --full --no-reflogs` and inspect object sizes.
6. Force-push all rewritten branches/tags from the maintenance clone.
7. Rotate any secrets that may have appeared in the old history.
8. Tell existing contributors to re-clone; do not merge old clones back into the rewritten repository.

Before removing a path, verify it is not needed for source distribution or release artifacts. Prefer downloading/building runtime dependencies during setup and keep large binaries out of ordinary Git history.

This document is intentionally procedural only; the destructive rewrite is not part of normal CI or pull-request automation.
