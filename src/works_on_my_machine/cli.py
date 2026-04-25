from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

VERSION_COMMANDS: dict[str, list[str]] = {
    "python": [sys.executable, "--version"],
    "git": ["git", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "docker": ["docker", "--version"],
    "kubectl": ["kubectl", "version", "--client", "--short"],
}

SENSITIVE_ENV_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"token",
        r"secret",
        r"password",
        r"passwd",
        r"pwd",
        r"key",
        r"credential",
        r"auth",
        r"session",
        r"cookie",
        r"private",
        r"sock",
    )
)


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot = build_snapshot(include_env=args.include_env)
        payload = render_snapshot(snapshot, output_format=args.format)
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(payload + "\n", encoding="utf-8")
        else:
            print(payload)
        return 0
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="womm",
        description="Capture a shareable machine snapshot for debugging environment-specific issues.",
    )
    subparsers = parser.add_subparsers(dest="command")

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help="Capture OS, tool versions, sanitized environment variables, and running services.",
    )
    snapshot_parser.add_argument(
        "-o",
        "--output",
        help="Write the snapshot to a file instead of stdout.",
    )
    snapshot_parser.add_argument(
        "--format",
        choices=("json", "text", "markdown"),
        default="json",
        help="Choose JSON, text, or markdown output format.",
    )
    snapshot_parser.add_argument(
        "--no-env",
        action="store_false",
        dest="include_env",
        help="Exclude environment variables from the snapshot.",
    )
    snapshot_parser.set_defaults(include_env=True)

    return parser


def build_snapshot(*, include_env: bool) -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "os": collect_os_details(),
        "versions": collect_versions(),
        "environment": collect_environment() if include_env else {"included": False},
        "services": collect_services(),
    }


def render_snapshot(snapshot: dict[str, object], *, output_format: str) -> str:
    if output_format == "markdown":
        return render_snapshot_markdown(snapshot)
    if output_format == "text":
        return render_snapshot_text(snapshot)
    return json.dumps(snapshot, indent=2, sort_keys=True)


def render_snapshot_text(snapshot: dict[str, object]) -> str:
    os_details = snapshot["os"]
    versions = snapshot["versions"]
    environment = snapshot["environment"]
    services = snapshot["services"]

    lines = [
        "Works On My Machine Snapshot",
        f"Generated: {snapshot['generated_at']}",
        (
            "OS: "
            f"{os_details['system']} {os_details['release']} "
            f"({os_details['machine']}) | Python {os_details['python']} | Host {os_details['hostname']}"
        ),
        "Versions: " + format_version_summary(versions),
        "Environment: " + format_environment_summary(environment),
        "Services: " + format_services_summary(services),
    ]
    return "\n".join(lines)


def render_snapshot_markdown(snapshot: dict[str, object]) -> str:
    os_details = snapshot["os"]
    versions = snapshot["versions"]
    environment = snapshot["environment"]
    services = snapshot["services"]

    lines = [
        "## Works On My Machine Snapshot",
        "",
        f"- Generated: {snapshot['generated_at']}",
        f"- OS: {os_details['system']} {os_details['release']} ({os_details['machine']})",
        f"- Python: {os_details['python']}",
        f"- Host: {os_details['hostname']}",
        "",
        "### Versions",
        "",
    ]

    for item in format_version_summary_list(versions):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "### Environment",
            "",
            f"- {format_environment_summary(environment)}",
            "",
            "### Services",
            "",
            f"- {format_services_summary(services)}",
        ]
    )
    return "\n".join(lines)


def format_version_summary(versions: dict[str, object]) -> str:
    return "; ".join(format_version_summary_list(versions))


def format_version_summary_list(versions: dict[str, object]) -> list[str]:
    parts = []
    for name, details in versions.items():
        if not isinstance(details, dict):
            continue
        if name == "python" and "version" in details:
            parts.append(f"python={details['version']}")
            continue
        if not details.get("installed", False):
            parts.append(f"{name}=missing")
            continue
        version_line = details.get("stdout") or "installed"
        parts.append(f"{name}={version_line}")
    return parts


def format_environment_summary(environment: dict[str, object]) -> str:
    if not environment.get("included"):
        return "excluded"
    count = environment.get("count", 0)
    redacted_keys = environment.get("redacted_keys", [])
    sample_keys = list(environment.get("values", {}).keys())[:8]
    sample = ", ".join(sample_keys) if sample_keys else "none"
    return f"{count} vars, {len(redacted_keys)} redacted, sample keys: {sample}"


def format_services_summary(services: dict[str, object]) -> str:
    count = services.get("count", 0)
    provider = services.get("provider", "unknown")
    running = services.get("running", [])
    names = []
    for entry in running[:5]:
        if isinstance(entry, dict):
            names.append(
                str(
                    entry.get("label")
                    or entry.get("unit")
                    or entry.get("Name")
                    or entry.get("DisplayName")
                    or "unknown"
                )
            )
    sample = ", ".join(names) if names else "none"
    error = services.get("error")
    if error:
        return f"provider={provider}, error={error}"
    return f"provider={provider}, running={count}, sample: {sample}"


def collect_os_details() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "hostname": platform.node(),
    }


def collect_versions() -> dict[str, object]:
    versions: dict[str, object] = {
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
        }
    }

    for name, command in VERSION_COMMANDS.items():
        executable = command[0]
        if executable != sys.executable and shutil.which(executable) is None:
            versions[name] = {"installed": False}
            continue
        result = run_command(command)
        versions[name] = {
            "installed": result.returncode == 0,
            "command": command,
            "stdout": first_non_empty_line(result.stdout, result.stderr),
        }

    return versions


def collect_environment() -> dict[str, object]:
    safe_values: dict[str, str] = {}
    redacted: list[str] = []
    for key, value in sorted(os.environ.items()):
        if is_sensitive_key(key):
            safe_values[key] = "<redacted>"
            redacted.append(key)
            continue
        safe_values[key] = sanitize_env_value(key, value)

    return {
        "included": True,
        "count": len(safe_values),
        "redacted_keys": redacted,
        "values": safe_values,
    }


def is_sensitive_key(key: str) -> bool:
    return any(pattern.search(key) for pattern in SENSITIVE_ENV_PATTERNS)


def sanitize_env_value(key: str, value: str) -> str:
    if key.upper() in {"HOME", "USERPROFILE"}:
        return "<home>"
    if key.upper().endswith("PATH"):
        return sanitize_path_list(value)
    return sanitize_home_references(value)


def sanitize_path_list(value: str) -> str:
    separator = os.pathsep
    sanitized_parts = []
    for entry in value.split(separator):
        if not entry:
            sanitized_parts.append(entry)
            continue
        sanitized_parts.append(sanitize_home_references(entry))
    return separator.join(sanitized_parts)


def sanitize_home_references(value: str) -> str:
    return value.replace(str(Path.home()), "<home>")


def collect_services() -> dict[str, object]:
    system = platform.system()
    if system == "Darwin":
        return collect_macos_services()
    if system == "Linux":
        return collect_linux_services()
    if system == "Windows":
        return collect_windows_services()
    return {
        "provider": "unknown",
        "error": f"Unsupported platform: {system}",
        "running": [],
    }


def collect_macos_services() -> dict[str, object]:
    result = run_command(["launchctl", "list"])
    running = []
    if result.returncode == 0:
        for line in result.stdout.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            pid, status, label = parts
            running.append(
                {
                    "label": label,
                    "pid": pid if pid != "-" else None,
                    "status": status,
                }
            )
    return {
        "provider": "launchctl",
        "running": running,
        "count": len(running),
        "error": None if result.returncode == 0 else first_non_empty_line(result.stderr, result.stdout),
    }


def collect_linux_services() -> dict[str, object]:
    result = run_command(["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--plain"])
    running = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if not line or not line.endswith("running") and ".service" not in line:
                continue
            parts = line.split()
            if not parts or not parts[0].endswith(".service"):
                continue
            running.append(
                {
                    "unit": parts[0],
                    "load": parts[1] if len(parts) > 1 else None,
                    "active": parts[2] if len(parts) > 2 else None,
                    "sub": parts[3] if len(parts) > 3 else None,
                    "description": " ".join(parts[4:]) if len(parts) > 4 else "",
                }
            )
    return {
        "provider": "systemctl",
        "running": running,
        "count": len(running),
        "error": None if result.returncode == 0 else first_non_empty_line(result.stderr, result.stdout),
    }


def collect_windows_services() -> dict[str, object]:
    result = run_command(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Service | Where-Object {$_.Status -eq 'Running'} | Select-Object Name,DisplayName,Status | ConvertTo-Json",
        ]
    )
    running: list[object] = []
    if result.returncode == 0 and result.stdout.strip():
        try:
            payload = json.loads(result.stdout)
            if isinstance(payload, list):
                running = payload
            else:
                running = [payload]
        except json.JSONDecodeError:
            running = []
    return {
        "provider": "powershell",
        "running": running,
        "count": len(running),
        "error": None if result.returncode == 0 else first_non_empty_line(result.stderr, result.stdout),
    }


def run_command(command: list[str]) -> CommandResult:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
    except FileNotFoundError as error:
        return CommandResult(command=command, returncode=127, stdout="", stderr=str(error))
    except OSError as error:
        return CommandResult(command=command, returncode=1, stdout="", stderr=str(error))


def first_non_empty_line(*values: str) -> str:
    for value in values:
        for line in value.splitlines():
            if line.strip():
                return line.strip()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())