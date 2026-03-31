import argparse
import json
import sys
from pathlib import Path


def show_recent(owner: str, audit_dir: Path = Path("data")) -> None:
    audit_file = audit_dir / "audit_log.jsonl"
    if not audit_file.exists():
        print(f"No audit log found at {audit_file}")
        sys.exit(1)

    latest_run_id = None
    with open(audit_file) as f:
        for line in f:
            record = json.loads(line)
            if record["type"] == "run":
                latest_run_id = record["run_id"]

    if not latest_run_id:
        print("No runs found in audit log.")
        sys.exit(1)

    with open(audit_file) as f:
        for line in f:
            record = json.loads(line)
            if record.get("run_id") != latest_run_id:
                continue
            if record["type"] == "run":
                print(f"Run: {record['run_id']} at {record['timestamp']}")
                print(f"  Issues found: {record['opportunities_with_issues']}")
                print(f"  Emails sent: {record['emails_sent']}")
                print(f"  Emails failed: {record['emails_failed']}")
                print()
            elif record["type"] == "issue" and record.get("owner_email") == owner:
                print(f"  {record['opportunity_name']} [{record['priority']}]")
                print(f"    Rules: {', '.join(record['rule_ids'])}")
                if record.get("suggested_action"):
                    print(f"    Action: {record['suggested_action']}")
                if record.get("action_rationale"):
                    print(f"    Why now: {record['action_rationale']}")
                print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Show recent Pipeline Coach audit")
    parser.add_argument("--owner", required=True, help="Owner email to filter by")
    parser.add_argument("--audit-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    show_recent(args.owner, args.audit_dir)


if __name__ == "__main__":
    main()
