# Configuration and deployment

Keep deployment files at the repository root because common Python, Docker, and dependency tooling expects them there.

- `../pyproject.toml` — Python project metadata and dependencies
- `../uv.lock` — locked dependency versions
- `../Dockerfile` — production container build
- `../docker-compose.yml` — local/host deployment definition
- `../aivf_config.json` — application configuration example/data

The folder is a guide, not a container for files that would become harder for standard tooling to discover.
