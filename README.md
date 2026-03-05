# Agent Monorepo

Super-repo for multiple focused agents:
- `gmail_agent`: Gmail/Calendar/Sheets briefing + MDT rota workflows
- `linkedin_agent`: compliant content pipeline with approval-gated publishing
- `dicom_xnat_agent`: DICOM folder preparation for XNAT upload
- `hpc_agent`: HPC data folder download/upload helper
- `shared`: shared compliance/audit utilities
- `agent_hub.py`: lightweight local web hub for Gmail + LinkedIn actions

## Repo Layout
- `agent/gmail_agent/`
- `agent/linkedin_agent/`
- `agent/dicom_xnat_agent/`
- `agent/hpc_agent/`
- `agent/shared/`
- `agent_hub.py`

## Workspace
This repo uses a UV workspace:
- root workspace: `pyproject.toml`
- agent workspace: `agent/pyproject.toml`

## Quick Start
Install/run each agent from its own folder.

### Grand Agent Menu (Root)
From repo root, open one menu that launches sub-agent UIs:
```bash
python agent_menu.py
```
or:
```bash
./agent-menu
./agent-cli
```

### Gmail Agent
Path: `agent/gmail_agent`

Install:
```bash
cd agent/gmail_agent
pip install -e .
```

Main CLI:
```bash
gmail-agent --help
gmail-agent menu
```

Common commands:
```bash
gmail-agent gmail-briefing --lookback-days 7
gmail-agent mdt-check --initials UB --week current
gmail-agent mdt-check --initials UB --week next
gmail-agent mdt-check --initials UB --notify-friday
```

Default config:
- `agent/gmail_agent/config.yaml`
- shared secrets fallback: `/s/agent_rw/conf/agent_repo/secrets.env`

What it does:
- Gmail threads needing response (read-only)
- Calendar events (today + next 7 days)
- Next-week assignments from sheet for assignee (default `UB`)
- JSON outputs and optional desktop notifications

Google scopes used:
- Gmail read-only
- Calendar read-only
- Sheets read-only

Docs:
- `agent/gmail_agent/README.md`
- `agent/gmail_agent/HELP.md`

### LinkedIn Agent
Path: `agent/linkedin_agent`

Install + run:
```bash
cd agent/linkedin_agent
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
uvicorn app.main:app --reload --port 8080
```

Open:
- UI: `http://127.0.0.1:8080/ui/drafts`
- API docs: `http://127.0.0.1:8080/docs`

Core workflow:
1. Ingest from `sources/experiments`, `sources/notes`, RSS feeds
2. Score/filter relevance
3. Generate drafts (LinkedIn short/long + X variant)
4. Human approve/reject
5. Publish or export

Compliance behavior:
- no scraping/browser automation
- approval required before publish
- no auto-post by default (`auto_post_enabled: false`)
- audit logging for ingestion/generation/approval/publish attempts

Docs:
- `agent/linkedin_agent/README.md`

### DICOM XNAT Agent
Path: `agent/dicom_xnat_agent`

Install:
```bash
cd agent/dicom_xnat_agent
pip install -e .
```

CLI:
```bash
dicom-xnat-agent --help
dicom-xnat-agent menu
```

Prepare a dataset for XNAT:
```bash
dicom-xnat-agent prepare /s/insync/datasets/bones --workers 8
```

Single-process mode:
```bash
dicom-xnat-agent prepare /s/insync/datasets/bones --no-multiprocess
```

What it does:
- deletes unwanted non-DICOM files/folders (recursive)
- rewrites DICOM `PatientID` based on direct case-folder name (`1`, `2`, `3`, ...)
- multiprocessing processing of case folders
- final status: `ready to upload on xnat`

Notes:
- Uses existing functions from external sibling repos (`/home/ub/code/dicom_utils`, `/home/ub/code/utilz`) and auto-adds them to `PYTHONPATH` if available.

Docs:
- `agent/dicom_xnat_agent/README.md`

### HPC Agent
Path: `agent/hpc_agent`

Install:
```bash
cd agent/hpc_agent
pip install -e .
```

CLI:
```bash
hpc-agent --help
hpc-agent menu
```

Direct transfer commands:
```bash
hpc-agent download nodesthick /s/xnat_shadow/hpc --yes
hpc-agent upload /local/folder --yes
```

Default remote root:
- `/data/EECS-LITQ/fran_storage/datasets/xnat_shadow`
- default remote login: `<your_hpc_username>@login.hpc.qmul.ac.uk`
- default local temp backup root: `/tmp/hpc_agent_backups`

Docs:
- `agent/hpc_agent/README.md`

## Shared Utilities
Path: `agent/shared`

Purpose:
- shared compliance validators
- shared audit helpers
- cross-agent contracts/models (in progress)

## Agent Hub (Optional)
Run local web hub:
```bash
python agent_hub.py
```

URL:
- `http://127.0.0.1:8090`

Provides quick web actions for:
- Gmail / MDT workflows
- LinkedIn one-shot pipeline run
- DICOM XNAT CLI commands (`prepare`, `dcm2nifti`, `download-nifti`, `upload-resource`)
- HPC CLI commands (`download`, `upload`)

Use the top tabs in the hub to switch between agent pages.
In the MDT card, use **Open MDT Spreadsheet** to open:
- `https://docs.google.com/spreadsheets/d/<spreadsheet_id>/edit`
- `spreadsheet_id` comes from `mdt.spreadsheet_id` in `agent/gmail_agent/config.yaml` or `GMAIL_SPREADSHEET_ID` in shared secrets.

## Testing
LinkedIn tests:
```bash
cd agent/linkedin_agent
pytest -q
```

## Related Docs
- `instructions.txt`
- `instructions_gmail.txt`

## Shared Telegram Notifications (All Agents)

This repo ships reusable Telegram notification scripts for any local agent workflow.

Scripts:
- `scripts/telegram_notify.sh`
- `scripts/run_with_telegram_notify.sh`
- `scripts/setup_telegram_notify.sh`

Single secrets location (recommended):
- `/s/agent_rw/conf/agent_repo/secrets.env`
- template in repo: `config/secrets.env.example`
- optional override: `AGENT_SECRETS_FILE=/custom/path/secrets.env`

### Setup

Option A: populate shared secrets with helper
```bash
cd /home/ub/code/agent
scripts/setup_telegram_notify.sh "<BOT_TOKEN>" "<CHAT_ID>" "agent"
```

Option B: explicitly point to a non-default secrets file
```bash
export AGENT_SECRETS_FILE=/s/agent_rw/conf/agent_repo/secrets.env
```

### Send a test message
```bash
cd /home/ub/code/agent
scripts/telegram_notify.sh "agent repo notifier test"
```

### Wrap any long-running command
```bash
cd /home/ub/code/agent
scripts/run_with_telegram_notify.sh python agent_menu.py
```

This sends Telegram messages on start and completion (or failure), and rings a terminal bell.
