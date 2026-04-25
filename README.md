# works-on-my-machine

Capture a shareable machine snapshot for debugging environment-specific issues.

## What It Captures

- OS details
- Common tool versions
- Environment variables with basic sanitization
- Running services

## Usage

Run directly from the repo:

```bash
PYTHONPATH=src python3 -m works_on_my_machine.cli snapshot --output snapshot.json
```

Or install a local CLI entrypoint:

```bash
python3 -m pip install -e .
womm snapshot --output snapshot.json
```

For a compact text summary that is easier to paste into bug reports:

```bash
womm snapshot --format text
```

For issue templates and PR comments:

```bash
womm snapshot --format markdown
```

To exclude environment variables:

```bash
womm snapshot --no-env
```

JSON remains the default output for structured sharing, `--format text` emits a shorter summary for chat threads, and `--format markdown` is tuned for issue templates and PR comments.
