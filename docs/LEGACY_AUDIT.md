# Legacy/archive audit

The `archive/` and `legacy/` areas are intentionally retained until their imports and historical references are verified. Deleting them blindly could remove compatibility code or examples still referenced by tests/tools.

Before removal, search the repository for imports and path references, then delete only paths with no live dependencies. This is lower priority than the production correctness/security work.
