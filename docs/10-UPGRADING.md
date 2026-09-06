# 10 — Upgrading

Use this guide when you already have an older Edit Factory checkout.

## 1. Back up runtime data

Back up your generated outputs and persistent state before replacing the application.

## 2. Update the source

Fetch the new repository version and use the current `README.md` and numbered documentation as the source of truth.

Do not blindly copy old commands from older setup documents. Earlier versions had different entry points and implementation details.

## 3. Reinstall dependencies

From the updated checkout:

```bash
python -m pip install -e ".[web,dev]"
```

## 4. Check the CLI

```bash
python cli.py --help
aivf --help
```

## 5. Check the dashboard

Confirm the production deployment uses `wsgi:app` with the supported one-worker configuration.

## 6. Run a real smoke test

Before trusting the upgrade, run one real media job and verify the output. For production hosts, also perform the cancellation, restart, persistence, and shutdown checks described in [06 — Production Deployment](06-PRODUCTION-DEPLOYMENT.md).

## If something changed unexpectedly

Read [07 — Troubleshooting](07-TROUBLESHOOTING.md) and [05 — Project Map](05-PROJECT-MAP.md) before changing code.
