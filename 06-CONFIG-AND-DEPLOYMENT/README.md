# Configuration and deployment

Deployment metadata remains at the repository root because common Python and Docker tooling expects it there.

- `pyproject.toml` — package metadata and dependencies
- `uv.lock` — locked dependency set
- `Dockerfile` — production image build
- `docker-compose.yml` — deployment definition
- `aivf_config.json` — application configuration

This folder documents those files rather than hiding them where standard tooling would stop finding them.
