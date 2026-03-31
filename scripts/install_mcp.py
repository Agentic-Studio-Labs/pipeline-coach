"""Install Pipeline Coach MCP server config for Claude Desktop, Claude Code, and Cursor."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)

VENV_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")
SYSTEM_PYTHON = sys.executable

MCP_CONFIG = {
    "command": VENV_PYTHON if Path(VENV_PYTHON).exists() else SYSTEM_PYTHON,
    "args": ["-m", "pipeline_coach.mcp"],
    "cwd": str(PROJECT_ROOT),
    "env": {},
}

# Build env from .env file — only include keys that are set
ENV_KEYS = [
    "TWENTY_API_URL",
    "TWENTY_API_KEY",
    "RESEND_API_KEY",
    "EMAIL_FROM",
    "LLM_API_KEY",
    "LLM_MODEL",
    "CRM_PUBLIC_URL",
]


def _build_env() -> dict[str, str]:
    env = {}
    for key in ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = val
    return env


def _get_client_paths() -> dict[str, Path]:
    """Return config paths for each supported client."""
    system = platform.system()
    home = Path.home()
    clients: dict[str, Path] = {}

    # Claude Desktop
    if system == "Darwin":
        clients["Claude Desktop"] = (
            home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        )
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            clients["Claude Desktop"] = Path(appdata) / "Claude" / "claude_desktop_config.json"

    # Claude Code (project-level)
    clients["Claude Code"] = PROJECT_ROOT / ".mcp.json"

    # Cursor (project-level)
    clients["Cursor"] = PROJECT_ROOT / ".cursor" / "mcp.json"

    return clients


def _upsert_config(path: Path, server_name: str, server_config: dict) -> bool:
    """Add or update the MCP server entry in a config file. Returns True if modified."""
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}

    servers = existing.setdefault("mcpServers", {})
    old = servers.get(server_name)
    servers[server_name] = server_config

    if old == server_config:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n")
    return True


def main() -> None:
    print("Pipeline Coach MCP Installer")
    print("=" * 40)
    print()

    env = _build_env()
    if not env.get("TWENTY_API_URL") or not env.get("TWENTY_API_KEY"):
        print("WARNING: TWENTY_API_URL or TWENTY_API_KEY not found in .env")
        print("  CRM-backed tools won't work until these are set.")
        print(f"  Looked for: {PROJECT_ROOT / '.env'}")
        print()

    config = {**MCP_CONFIG, "env": env}
    clients = _get_client_paths()

    print(f"Python:  {config['command']}")
    print(f"Project: {PROJECT_ROOT}")
    print(f"Env vars: {len(env)} loaded from .env")
    print()

    installed = []
    skipped = []

    for name, path in clients.items():
        # Skip if parent dir doesn't exist (client not installed) — except project-level configs
        is_project_level = path.is_relative_to(PROJECT_ROOT)
        if not is_project_level and not path.parent.exists():
            skipped.append((name, "not installed"))
            continue

        if _upsert_config(path, "pipeline-coach", config):
            installed.append((name, path))
            print(f"  [+] {name}: {path}")
        else:
            installed.append((name, path))
            print(f"  [=] {name}: {path} (already up to date)")

    for name, reason in skipped:
        print(f"  [-] {name}: {reason}")

    print()
    if installed:
        print("Done! Restart your AI client to connect to Pipeline Coach.")
        print()
        print('Test it by asking: "What deals need attention?"')
    else:
        print("No clients found. Install Claude Desktop, Claude Code, or Cursor first.")


if __name__ == "__main__":
    main()
