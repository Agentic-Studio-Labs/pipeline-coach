import argparse
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    load_dotenv(override=True)
    parser = argparse.ArgumentParser(description="Pipeline Coach")
    parser.add_argument("--once", action="store_true", help="Run the pipeline once and exit")
    parser.add_argument(
        "--config-dir", type=Path, default=Path("config"), help="Path to config directory"
    )
    args = parser.parse_args()

    if args.once:
        from pipeline_coach.run_once import run_pipeline_once

        run_pipeline_once(config_dir=args.config_dir)
    else:
        from pipeline_coach.scheduler import start_scheduler

        start_scheduler(config_dir=args.config_dir)


if __name__ == "__main__":
    main()
