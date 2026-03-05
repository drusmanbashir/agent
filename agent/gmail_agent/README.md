# Gmail Agent

Legacy Gmail-focused agent moved under the `agent` super-repo.

Run (editable install):
```bash
cd agent/gmail_agent
pip install -e .
gmail-agent --help
gmail-agent menu
```

Detailed command guide: `agent/gmail_agent/HELP.md`

New workflow command:
```bash
gmail-agent --config /home/ub/code/agent/agent/gmail_agent/config.yaml gmail-briefing --lookback-days 7
```

`gmail-briefing` uses these Google OAuth read-only scopes:
- Gmail: `https://www.googleapis.com/auth/gmail.readonly`
- Calendar: `https://www.googleapis.com/auth/calendar.readonly`
- Sheets: `https://www.googleapis.com/auth/spreadsheets.readonly`

By default it writes outside revalidation to:
- token: `/s/agent_rw/cache/gmail_token.json`
- output: `/s/agent_rw/index/gmail_briefing.json`

Central secrets source (optional, preferred):
- `/s/agent_rw/conf/agent_repo/secrets.env`
- keys: `GMAIL_OAUTH_CLIENT_JSON`, `GMAIL_TOKEN_JSON`, `GMAIL_OUTPUT_DIR`, `GMAIL_SPREADSHEET_ID`

`gmail-briefing` refuses to write token/output to any `/revalidation/` path.

Output JSON includes:
- pending email threads needing response
- calendar events for today through next 7 days
- next-week sheet assignments for assignee `UB`
- merged schedule with overlap flags
- daily and weekly notification payloads

MDT command (from `sample.ods`-style rota):
```bash
gmail-agent --config /home/ub/code/agent/agent/gmail_agent/config.yaml mdt-check --initials UB
```

Current-week desktop popup (Ubuntu):
```bash
gmail-agent --config /home/ub/code/agent/agent/gmail_agent/config.yaml mdt-check --initials UB --week current --desktop-notify
```

Friday notification mode:
```bash
gmail-agent --config /home/ub/code/agent/agent/gmail_agent/config.yaml mdt-check --initials UB --notify-friday
```

`mdt-check` reads:
- top row: weekdays
- second row: meeting names
- first column: month labels and week date ranges
- doctor assignment cells (matches initials, default `UB`)

It writes:
- `/s/agent_rw/index/mdt_next_week.json`
- on Friday with `--notify-friday`: `/s/agent_rw/index/mdt_friday_notification.txt`
