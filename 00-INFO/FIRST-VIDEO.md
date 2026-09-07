# Make Your First Video

This is the fastest path for a completely new user.

## 1. Install

From the repository root:

```bash
python -m venv .venv
python -m pip install -e './01-MAIN-CODE[web,dev]'
```

## 2. Check the CLI

```bash
python 01-MAIN-CODE/cli.py --help
aivf --help
```

The help command only checks that the application is available. It does not start a production workload.

## 3. Run a small example

```bash
python 01-MAIN-CODE/cli.py "Minecraft betrayal on SMP"
```

For a real editing job with source footage:

```bash
python 01-MAIN-CODE/cli.py "Minecraft betrayal on SMP" --input-video recording.mp4 --auto-edit
```

## What you should expect

The application researches/plans the topic, builds the script and hook material, makes editing decisions, runs the video-processing pipeline, and produces the resulting package in the configured runtime output location.

## Where to go next

- **CLI options:** `03-USING-THE-CLI.md`
- **Dashboard:** `04-USING-THE-DASHBOARD.md`
- **File locations:** `05-PROJECT-MAP.md`
- **Problems:** `07-TROUBLESHOOTING.md`

## Important beginner rule

Do not copy commands from old notes or old commits without checking the current `--help` output. The numbered folder structure is the current layout, and the documentation in `00-INFO/` is the starting point.