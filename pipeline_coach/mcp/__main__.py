from __future__ import annotations

from dotenv import load_dotenv


def main() -> None:
    load_dotenv(override=True)
    from pipeline_coach.mcp.server import mcp

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
