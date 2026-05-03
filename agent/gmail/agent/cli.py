from __future__ import annotations
from pathlib import Path
import argparse
import os
from datetime import date, timedelta
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

from agent.config import load_config
from agent.gmail_briefing import run_gmail_briefing
from agent.secret_store import load_shared_secrets
from agent.mdt_schedule import (
    build_friday_notification,
    build_mdt_sheet_view_urls,
    extract_mdt_meetings_for_week,
    extract_next_week_mdt_meetings,
    refresh_mdt_sheet_from_google,
    write_mdt_output,
)
from agent.paths import Paths, assert_read_only_source
from agent.revalidation.gmail_advisor import run_gmail_advisor
from agent.revalidation.rules import init_rules_if_missing, rules_show
from agent.revalidation.advise import advise


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config.yaml"


def _path_under_revalidation(path: Path) -> bool:
    return "/revalidation/" in str(path.resolve()).replace("\\", "/")


def _next_friday(today: date) -> date:
    days = (4 - today.weekday()) % 7
    if days == 0:
        days = 7
    return today + timedelta(days=days)


def _is_snoozed(snooze_file: Path, today: date) -> bool:
    if not snooze_file.exists():
        return False
    try:
        until = date.fromisoformat(snooze_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    return today <= until


def _rewrite_grouped_args(argv: list[str]) -> list[str]:
    cmd_idx = -1
    for i, token in enumerate(argv):
        if not token.startswith("-"):
            cmd_idx = i
            break
    if cmd_idx < 0:
        return argv

    cmd = argv[cmd_idx]
    if cmd == "gmail" and cmd_idx + 1 < len(argv):
        sub = argv[cmd_idx + 1]
        mapping = {
            "briefing": "gmail-briefing",
            "mdt-check": "mdt-check",
            "mdt-snooze": "mdt-snooze",
        }
        if sub in mapping:
            return argv[:cmd_idx] + [mapping[sub]] + argv[cmd_idx + 2 :]

    if cmd == "linkedin" and cmd_idx + 1 < len(argv):
        sub = argv[cmd_idx + 1]
        mapping = {
            "run-once": "linkedin-run-once",
            "ui-url": "linkedin-ui-url",
        }
        if sub in mapping:
            return argv[:cmd_idx] + [mapping[sub]] + argv[cmd_idx + 2 :]

    if cmd == "revalidation" and cmd_idx + 1 < len(argv):
        sub = argv[cmd_idx + 1]
        mapping = {
            "init": "init",
            "rules-show": "rules-show",
            "advise": "advise",
            "gmail-advise": "gmail-advise",
        }
        if sub in mapping:
            return argv[:cmd_idx] + [mapping[sub]] + argv[cmd_idx + 2 :]

    return argv


def _menu_prompt(title: str, options: list[str]) -> int:
    print(f"\n{title}")
    for i, opt in enumerate(options, start=1):
        print(f"  {i}) {opt}")
    print("  0) Back/Exit")
    while True:
        raw = input("Select option: ").strip()
        if raw.isdigit():
            n = int(raw)
            if 0 <= n <= len(options):
                return n
        print("Invalid choice, try again.")


def _run_linkedin_once_via_api() -> None:
    req = urllib.request.Request(
        "http://127.0.0.1:8080/api/run-once",
        data=b"",
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", errors="ignore")
            print("LinkedIn run-once result:")
            print(body)
    except urllib.error.URLError:
        print("LinkedIn API is not reachable at http://127.0.0.1:8080")
        print("Start it with: cd /home/ub/code/agent/agent/linkedin && uvicorn app.main:app --reload --port 8080")


def _run_menu(config_path: str) -> int:
    while True:
        top = _menu_prompt(
            "Top-Level Menu",
            ["Gmail", "LinkedIn", "Revalidation"],
        )
        if top == 0:
            return 0

        if top == 1:
            while True:
                c = _menu_prompt(
                    "Gmail Menu",
                    [
                        "Briefing",
                        "MDT Check (Current Week)",
                        "MDT Check (Next Week)",
                        "MDT Friday Notification File",
                        "MDT Desktop Notify (Current Week)",
                        "MDT Snooze Until Next Friday",
                        "MDT Snooze Clear",
                    ],
                )
                if c == 0:
                    break
                if c == 1:
                    main(["--config", config_path, "gmail-briefing", "--lookback-days", "7"])
                elif c == 2:
                    main(["--config", config_path, "mdt-check", "--initials", "UB", "--week", "current"])
                elif c == 3:
                    main(["--config", config_path, "mdt-check", "--initials", "UB", "--week", "next"])
                elif c == 4:
                    main(["--config", config_path, "mdt-check", "--initials", "UB", "--notify-friday"])
                elif c == 5:
                    main(
                        [
                            "--config",
                            config_path,
                            "mdt-check",
                            "--initials",
                            "UB",
                            "--week",
                            "current",
                            "--desktop-notify",
                            "--respect-snooze",
                        ]
                    )
                elif c == 6:
                    main(["--config", config_path, "mdt-snooze"])
                elif c == 7:
                    main(["--config", config_path, "mdt-snooze", "--clear"])
            continue

        if top == 2:
            while True:
                c = _menu_prompt(
                    "LinkedIn Menu",
                    [
                        "Run Pipeline Once via API (127.0.0.1:8080)",
                        "Open Draft UI URL",
                    ],
                )
                if c == 0:
                    break
                if c == 1:
                    main(["linkedin-run-once"])
                elif c == 2:
                    main(["linkedin-ui-url"])
            continue

        if top == 3:
            while True:
                c = _menu_prompt(
                    "Revalidation Menu",
                    [
                        "Init",
                        "Rules Show",
                        "Advise",
                        "Gmail Advise",
                    ],
                )
                if c == 0:
                    break
                if c == 1:
                    main(["--config", config_path, "init"])
                elif c == 2:
                    main(["--config", config_path, "rules-show"])
                elif c == 3:
                    main(["--config", config_path, "advise"])
                elif c == 4:
                    main(["--config", config_path, "gmail-advise"])
            continue


def main(argv=None) -> int:
    load_shared_secrets()
    if argv is None:
        argv = sys.argv[1:]
    argv = _rewrite_grouped_args(list(argv))

    ap = argparse.ArgumentParser(prog="agent")
    ap.add_argument("--config", default=str(_default_config_path()))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create required agent_rw folders + seed CPD rules")
    sub.add_parser("rules-show", help="print CPD rules summary")
    sub.add_parser("advise", help="generate revalidation advice markdown (minimal)")
    gmail_brief = sub.add_parser(
        "gmail-briefing",
        help="run Gmail/Calendar/Sheets assistant workflow and write JSON summary",
    )
    gmail_brief.add_argument("--lookback-days", type=int, default=7)
    gmail_brief.add_argument(
        "--spreadsheet-id",
        default=os.getenv("GMAIL_SPREADSHEET_ID", "1BF6awvgWG4PZdugdB3u1P_1e6w3slXQNBqAk9jM4U5Y"),
    )
    gmail_brief.add_argument("--calendar-id", default="primary")
    gmail_brief.add_argument("--assignee", default="UB")
    gmail_brief.add_argument("--out", default="")
    gmail_brief.add_argument("--oauth-client-json", default="")
    gmail_brief.add_argument("--token-json", default="")
    mdt_check = sub.add_parser(
        "mdt-check",
        help="parse MDT ODS sheet and report next week's meetings for an initials code",
    )
    mdt_check.add_argument("--sheet", default="")
    mdt_check.add_argument("--spreadsheet-id", default="")
    mdt_check.add_argument("--oauth-client-json", default="")
    mdt_check.add_argument("--token-json", default="")
    mdt_check.add_argument("--initials", default="UB")
    mdt_check.add_argument("--today", default="")
    mdt_check.add_argument("--week", choices=["current", "next"], default="next")
    mdt_check.add_argument("--out", default="")
    mdt_check.add_argument("--notify-friday", action="store_true")
    mdt_check.add_argument("--desktop-notify", action="store_true")
    mdt_check.add_argument("--open-sheet-view", action="store_true")
    mdt_check.add_argument("--respect-snooze", action="store_true")
    mdt_check.add_argument("--snooze-file", default="")
    mdt_check.add_argument("--notification-out", default="")
    mdt_snooze = sub.add_parser(
        "mdt-snooze",
        help="snooze MDT desktop notifications until next Friday or clear snooze",
    )
    mdt_snooze.add_argument("--clear", action="store_true")
    mdt_snooze.add_argument("--snooze-file", default="")
    sub.add_parser(
        "linkedin-run-once",
        help="run LinkedIn pipeline once via local API at 127.0.0.1:8080",
    )
    sub.add_parser(
        "linkedin-ui-url",
        help="print LinkedIn draft UI URL",
    )
    sub.add_parser(
        "menu",
        help="interactive nested CLI menu for gmail/linkedin/revalidation",
    )
    sub.add_parser(
        "shortcuts",
        help="print quick command aliases and Bash keybindings",
    )
    sub.add_parser(
        "gmail-advise",
        help="scan Gmail headers (last 12 months) and build LLM payload",
    )

    args = ap.parse_args(argv)

    if args.cmd == "menu":
        return _run_menu(args.config)

    if args.cmd == "shortcuts":
        print("Aliases:")
        print("  alias gam='gmail-agent menu'")
        print("  alias gab='gmail-agent gmail briefing --lookback-days 7'")
        print("  alias gac='gmail-agent gmail mdt-check --initials UB --week current'")
        print("  alias gan='gmail-agent gmail mdt-check --initials UB --week next'")
        print("  alias gas='gmail-agent gmail mdt-snooze'")
        print("  alias gal='gmail-agent linkedin run-once'")
        print("")
        print("Readline keybindings (Alt+g then key):")
        print(r"  bind '\"\egm\":\"gmail-agent menu\C-m\"'")
        print(r"  bind '\"\egb\":\"gmail-agent gmail briefing --lookback-days 7\C-m\"'")
        print(r"  bind '\"\egc\":\"gmail-agent gmail mdt-check --initials UB --week current\C-m\"'")
        print(r"  bind '\"\egn\":\"gmail-agent gmail mdt-check --initials UB --week next\C-m\"'")
        print(r"  bind '\"\egs\":\"gmail-agent gmail mdt-snooze\C-m\"'")
        print(r"  bind '\"\egl\":\"gmail-agent linkedin run-once\C-m\"'")
        print("")
        print("Load prepared file:")
        print("  source /home/ub/code/agent/agent/gmail/keybindings.bash")
        return 0

    if args.cmd == "linkedin-ui-url":
        print("http://127.0.0.1:8080/ui/drafts")
        return 0

    if args.cmd == "linkedin-run-once":
        _run_linkedin_once_via_api()
        return 0

    if args.cmd == "gmail-briefing":
        config_path = Path(args.config)
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}
        gm = raw.get("gmail", {})

        default_oauth = Path(
            os.getenv("GMAIL_OAUTH_CLIENT_JSON", str(Path.home() / ".config" / "gmail-agent" / "oauth_client.json"))
        )
        default_token = Path(os.getenv("GMAIL_TOKEN_JSON", "/s/agent_rw/cache/gmail_token.json"))
        default_output_dir = Path(os.getenv("GMAIL_OUTPUT_DIR", "/s/agent_rw/index"))

        oauth_client_json = Path(args.oauth_client_json or gm.get("oauth_client_json", default_oauth))
        token_json = Path(args.token_json or gm.get("token_json", default_token))
        output_dir = Path(gm.get("output_dir", default_output_dir))
        out_path = Path(args.out) if args.out else (output_dir / "gmail_briefing.json")

        if _path_under_revalidation(token_json) or _path_under_revalidation(out_path):
            raise ValueError(
                "gmail-briefing must not write to revalidation paths; use gmail token/output paths outside /revalidation/"
            )

        out = run_gmail_briefing(
            oauth_client_json=oauth_client_json,
            token_json=token_json,
            lookback_days=args.lookback_days,
            spreadsheet_id=args.spreadsheet_id,
            calendar_id=args.calendar_id,
            assignee=args.assignee,
            out_path=out_path,
        )
        print(f"wrote {out}")
        return 0

    if args.cmd == "mdt-check":
        config_path = Path(args.config)
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}
        gm = raw.get("gmail", {})
        mdt_cfg = raw.get("mdt", {})

        default_sheet = Path("/home/ub/code/agent/sample.ods")
        default_out = Path("/s/agent_rw/index/mdt_next_week.json")
        default_notification = Path("/s/agent_rw/index/mdt_friday_notification.txt")
        default_snooze = Path("/s/agent_rw/index/mdt_snooze_until.txt")
        default_oauth = Path(
            os.getenv("GMAIL_OAUTH_CLIENT_JSON", str(Path.home() / ".config" / "gmail-agent" / "oauth_client.json"))
        )
        default_token = Path(os.getenv("GMAIL_TOKEN_JSON", "/s/agent_rw/cache/gmail_token.json"))

        sheet_path = Path(args.sheet or mdt_cfg.get("sheet", default_sheet))
        spreadsheet_id = args.spreadsheet_id or mdt_cfg.get(
            "spreadsheet_id",
            os.getenv("GMAIL_SPREADSHEET_ID", "1BF6awvgWG4PZdugdB3u1P_1e6w3slXQNBqAk9jM4U5Y"),
        )
        oauth_client_json = Path(args.oauth_client_json or gm.get("oauth_client_json", default_oauth))
        token_json = Path(args.token_json or gm.get("token_json", default_token))
        out_path = Path(args.out or mdt_cfg.get("output_json", default_out))
        notification_path = Path(
            args.notification_out or mdt_cfg.get("notification_out", default_notification)
        )
        snooze_path = Path(args.snooze_file or mdt_cfg.get("snooze_file", default_snooze))
        refresh_mdt_sheet_from_google(
            sheet_path=sheet_path,
            spreadsheet_id=spreadsheet_id,
            oauth_client_json=oauth_client_json,
            token_json=token_json,
        )

        run_today = date.fromisoformat(args.today) if args.today else date.today()
        meetings = extract_mdt_meetings_for_week(
            ods_path=sheet_path,
            initials=args.initials,
            week_mode=args.week,
            today=run_today,
        )
        write_mdt_output(out_json=out_path, meetings=meetings, initials=args.initials, today=run_today)
        print(f"wrote {out_path}")

        if meetings:
            for m in meetings:
                print(f"{m.date_iso} ({m.weekday}) | {m.meeting_name} | {m.assignment}")
        else:
            print(f"No MDT meetings found for {args.initials} in the {args.week} week.")

        if args.desktop_notify:
            if args.respect_snooze and _is_snoozed(snooze_path, run_today):
                print(f"desktop notifications snoozed until {snooze_path.read_text(encoding='utf-8').strip()}")
                return 0
            if shutil.which("notify-send"):
                if meetings:
                    body = "\n".join(
                        f"{m.date_iso} {m.weekday}: {m.meeting_name}"
                        for m in meetings
                    )
                else:
                    body = f"No MDT meetings for {args.initials} in the {args.week} week."
                subprocess.run(
                    ["notify-send", "MDT Schedule", body],
                    check=False,
                )
                print("sent desktop notification")
            else:
                print("notify-send not found; skipped desktop notification")
        if args.open_sheet_view:
            urls = build_mdt_sheet_view_urls(
                meetings=meetings,
                spreadsheet_id=spreadsheet_id,
                oauth_client_json=oauth_client_json,
                token_json=token_json,
            )
            if urls and shutil.which("xdg-open"):
                for url in urls:
                    subprocess.run(["xdg-open", url], check=False)
                print("opened live sheet view")
            elif urls:
                for url in urls:
                    print(url)
            else:
                print("no matching rows to open in Google Sheets")

        if args.notify_friday:
            if run_today.weekday() == 4:
                next_week_meetings = extract_next_week_mdt_meetings(
                    ods_path=sheet_path,
                    initials=args.initials,
                    today=run_today,
                )
                msg = build_friday_notification(
                    meetings=next_week_meetings,
                    initials=args.initials,
                    today=run_today,
                )
                notification_path.parent.mkdir(parents=True, exist_ok=True)
                notification_path.write_text(msg + "\n", encoding="utf-8")
                print(f"wrote {notification_path}")
            else:
                print("Skipped Friday notification: today is not Friday.")
        return 0

    if args.cmd == "mdt-snooze":
        config_path = Path(args.config)
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}
        mdt_cfg = raw.get("mdt", {})
        snooze_path = Path(args.snooze_file or mdt_cfg.get("snooze_file", "/s/agent_rw/index/mdt_snooze_until.txt"))

        if args.clear:
            if snooze_path.exists():
                snooze_path.unlink()
                print(f"cleared snooze: {snooze_path}")
            else:
                print("no active snooze")
            return 0

        today = date.today()
        until = _next_friday(today)
        snooze_path.parent.mkdir(parents=True, exist_ok=True)
        snooze_path.write_text(until.isoformat(), encoding="utf-8")
        print(f"snoozed until {until.isoformat()} in {snooze_path}")
        return 0

    cfg = load_config(Path(args.config))
    assert_read_only_source(cfg.source_root)

    p = Paths(cfg.source_root, cfg.agent_root)
    p.ensure_dirs()

    if args.cmd == "init":
        init_rules_if_missing(p)
        return 0

    if args.cmd == "rules-show":
        rules_show(p)
        return 0

    if args.cmd == "advise":
        advise(p)
        return 0

    if args.cmd == "gmail-advise":
        with Path(args.config).open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        rv = raw["revalidation"]
        gm = raw["gmail"]

        year = int(rv["year"])
        evidence_dir = Path(rv["evidence_root"]) / str(year)

        oauth_client_json = Path(
            gm.get(
                "oauth_client_json",
                os.getenv("GMAIL_OAUTH_CLIENT_JSON", str(Path.home() / ".config" / "gmail-agent" / "oauth_client.json")),
            )
        )
        token_json = Path(gm.get("token_json", os.getenv("GMAIL_TOKEN_JSON", "/s/agent_rw/cache/gmail_token.json")))

        out = run_gmail_advisor(
            agent_root=p.agent_root,
            year=year,
            evidence_dir=evidence_dir,
            guidelines_dir=Path(rv["guidelines_dir"]),
            oauth_client_json=oauth_client_json,
            token_json=token_json,
            out_dir=p.index_dir,
        )

        print(f"wrote {out}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
