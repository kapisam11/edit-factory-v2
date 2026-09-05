# Production Release Checklist

Before merging the hardening branch, all of the following must be green:

- Python 3.9–3.12 CI test matrix
- repository-wide Ruff checks for production Python
- `python cli.py --help`, `python cli_v2.py --help`, and `aivf --help`
- dependency audit
- Docker build and dashboard import smoke test
- dashboard authentication test
- secret persistence/API redaction tests
- malicious upload/path tests
- real FFmpeg render integration test
- end-to-end cancellation test on the deployment operating system
- restart/reconciliation test on the deployment operating system
- SQLite concurrent-write test
- final documentation review against implemented code

Do not call the release 10/10 until the runtime checks above have actually passed. Source
changes alone are not evidence that the runtime is healthy.
