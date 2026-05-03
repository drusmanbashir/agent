# Agent CLI Help

This CLI now has a nested menu:

```bash
gmail-agent menu
```

Grouped command style is also supported:
```bash
gmail-agent gmail briefing --lookback-days 7
gmail-agent gmail mdt-check --initials UB --week current
gmail-agent gmail mdt-snooze

gmail-agent linkedin run-once
gmail-agent linkedin ui-url

gmail-agent revalidation init
gmail-agent revalidation rules-show
gmail-agent revalidation advise
gmail-agent revalidation gmail-advise
```

Top level:
- `Gmail`
- `LinkedIn`
- `Revalidation`

## Gmail submenu
- `Briefing`
- `MDT Check (Current Week)`
- `MDT Check (Next Week)`
- `MDT Friday Notification File`
- `MDT Desktop Notify (Current Week)`
- `MDT Snooze Until Next Friday`
- `MDT Snooze Clear`

Direct commands:
```bash
gmail-agent gmail-briefing --lookback-days 7
gmail-agent mdt-check --initials UB --week current
gmail-agent mdt-check --initials UB --week next
gmail-agent mdt-check --initials UB --notify-friday
gmail-agent mdt-check --initials UB --week current --desktop-notify --respect-snooze
gmail-agent mdt-snooze
gmail-agent mdt-snooze --clear
```

## LinkedIn submenu
- `Run Pipeline Once via API (127.0.0.1:8080)`
- `Open Draft UI URL`

If pipeline call fails, start LinkedIn app:
```bash
cd /home/ub/code/agent/agent/linkedin
uvicorn app.main:app --reload --port 8080
```

## Revalidation submenu
- `Init`
- `Rules Show`
- `Advise`
- `Gmail Advise`

Direct commands:
```bash
gmail-agent init
gmail-agent rules-show
gmail-agent advise
gmail-agent gmail-advise
```

## Config

Default config path is:
- `agent/gmail/config.yaml`

You can override:
```bash
gmail-agent --config /path/to/config.yaml menu
```

## Quick Shortcuts / Keybindings

Show shortcuts in CLI:
```bash
gmail-agent shortcuts
```

Load prepared Bash aliases + Alt+g keybindings:
```bash
source /home/ub/code/agent/agent/gmail/keybindings.bash
```
