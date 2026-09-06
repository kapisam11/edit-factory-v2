# Main code

This area explains the primary application code.

The production Python packages `ai_video_factory/` and `app/` stay at the repository root because Python packaging and runtime imports depend on those package names being directly importable.

- `ai_video_factory/` — core video-production pipeline
- `app/` — CLI, web application, WSGI, and worker implementations
