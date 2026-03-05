from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml


REPO_ROOT = Path(__file__).resolve().parent
GMAIL_ROOT = REPO_ROOT / "agent" / "gmail_agent"
LINKEDIN_ROOT = REPO_ROOT / "agent" / "linkedin_agent"
DICOM_CLI = REPO_ROOT / "agent" / "dicom_xnat_agent" / "dicom_xnat_agent" / "cli.py"
HPC_CLI = REPO_ROOT / "agent" / "hpc_agent" / "hpc_agent" / "cli.py"
UTILZ_OVERLAY_GIF_SCRIPT = Path.home() / "code" / "utilz" / "utilz" / "overlay_grid_gif.py"

if str(GMAIL_ROOT) not in sys.path:
    sys.path.insert(0, str(GMAIL_ROOT))
if str(LINKEDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(LINKEDIN_ROOT))

from agent.gmail_briefing import run_gmail_briefing  # type: ignore  # noqa: E402
from agent.mdt_schedule import (  # type: ignore  # noqa: E402
    build_friday_notification,
    extract_mdt_meetings_for_week,
    extract_next_week_mdt_meetings,
    write_mdt_output,
)
from agent.secret_store import load_shared_secrets  # type: ignore  # noqa: E402
from app.db import init_db  # type: ignore  # noqa: E402
from app.repository import list_drafts  # type: ignore  # noqa: E402
from app.settings import load_settings  # type: ignore  # noqa: E402
from app.workflow import run_pipeline  # type: ignore  # noqa: E402

DEFAULT_SPREADSHEET_ID = "1BF6awvgWG4PZdugdB3u1P_1e6w3slXQNBqAk9jM4U5Y"
SHARED_SECRETS = load_shared_secrets()
UTILZ_DEFAULT_KEYS = (
    "rows",
    "cols",
    "num_frames",
    "fps",
    "stride",
    "panel_px",
    "gif_colors",
    "slice_axis",
    "window",
    "rotate_cw",
)


def _startup_stamp_path() -> Path:
    return Path.home() / ".cache" / "agent-hub" / "mdt_startup_last_sent.txt"


def _utilz_defaults_path() -> Path:
    return Path.home() / ".cache" / "agent-hub" / "utilz_defaults.yaml"


def _mark_startup_sent(today: date) -> None:
    stamp = _startup_stamp_path()
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(today.isoformat() + "\n", encoding="utf-8")


def _already_sent_today(today: date) -> bool:
    stamp = _startup_stamp_path()
    if not stamp.exists():
        return False
    try:
        return stamp.read_text(encoding="utf-8").strip() == today.isoformat()
    except Exception:
        return False


def _load_gmail_cfg() -> dict[str, Any]:
    cfg_path = GMAIL_ROOT / "config.yaml"
    if not cfg_path.exists():
        raw: dict[str, Any] = {}
    else:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    gm = dict(raw.get("gmail", {}) or {})
    mdt = dict(raw.get("mdt", {}) or {})

    gm.setdefault("oauth_client_json", SHARED_SECRETS.get("GMAIL_OAUTH_CLIENT_JSON", "/home/ub/.config/gmail-agent/oauth_client.json"))
    gm.setdefault("token_json", SHARED_SECRETS.get("GMAIL_TOKEN_JSON", "/s/agent_rw/cache/gmail_token.json"))
    gm.setdefault("output_dir", SHARED_SECRETS.get("GMAIL_OUTPUT_DIR", "/s/agent_rw/index"))
    mdt.setdefault("spreadsheet_id", SHARED_SECRETS.get("GMAIL_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID))

    raw["gmail"] = gm
    raw["mdt"] = mdt
    return raw


def _send_mdt_desktop_notification(
    *,
    sheet_path: Path,
    initials: str = "UB",
    week: str = "current",
    run_today: date | None = None,
) -> str:
    today = run_today or date.today()
    meetings = extract_mdt_meetings_for_week(
        ods_path=sheet_path,
        initials=initials,
        week_mode=week,
        today=today,
    )
    if meetings:
        body = "\n".join(f"{m.date_iso} {m.weekday}: {m.meeting_name}" for m in meetings)
    else:
        body = f"No MDT meetings for {initials} in {week} week."
    if not shutil.which("notify-send"):
        raise RuntimeError("notify-send not found")
    subprocess.run(["notify-send", "MDT Schedule", body], check=False)
    return body


def _drafts_table() -> str:
    s = load_settings(LINKEDIN_ROOT)
    init_db(s.db_path)
    rows = list_drafts(s.db_path)[:20]
    trs = "".join(
        f"<tr><td>{d['id']}</td><td>{escape(d['status'])}</td><td>{escape(d['audience_tag'])}</td><td>{escape(d['claim_level'])}</td></tr>"
        for d in rows
    )
    return (
        "<table><tr><th>ID</th><th>Status</th><th>Audience</th><th>Claim</th></tr>"
        f"{trs}</table>"
    )


def _is_checked(form: dict[str, str], key: str) -> bool:
    return form.get(key, "").lower() in {"1", "true", "on", "yes"}


def _run_cli_script(script: Path, args: list[str]) -> str:
    cmd = [sys.executable, str(script), *args]
    proc = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
    )
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    lines = [
        f"$ {' '.join(cmd)}",
        f"exit_code: {proc.returncode}",
    ]
    if out:
        lines.append("")
        lines.append("stdout:")
        lines.append(out)
    if err:
        lines.append("")
        lines.append("stderr:")
        lines.append(err)
    return "\n".join(lines)


def _next_indexed_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = "".join(path.suffixes)
    stem = path.name[: -len(suffix)] if suffix else path.name
    parent = path.parent
    idx = 1
    while True:
        candidate_name = f"{stem}({idx}){suffix}"
        candidate = parent / candidate_name
        if not candidate.exists():
            return candidate
        idx += 1


def _load_utilz_defaults() -> dict[str, str]:
    path = _utilz_defaults_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, str] = {}
        for k in UTILZ_DEFAULT_KEYS:
            if k in data and data[k] is not None:
                out[k] = str(data[k])
        return out
    except Exception:
        return {}


def _save_utilz_defaults(values: dict[str, str]) -> Path:
    data = {k: values.get(k, "") for k in UTILZ_DEFAULT_KEYS}
    path = _utilz_defaults_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    return path


def _render_page(result: str = "", active_page: str = "home") -> str:
    cfg = _load_gmail_cfg()
    gm = cfg.get("gmail", {})
    mdt = cfg.get("mdt", {})
    utilz_defaults = _load_utilz_defaults()
    utilz_output_default = Path("/s/fran_storage/tmp/overlay_grid.gif")
    mdt_spreadsheet_id = str(mdt.get("spreadsheet_id", DEFAULT_SPREADSHEET_ID)).strip()
    mdt_spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{mdt_spreadsheet_id}/edit"
    result_html = f"<pre>{escape(result)}</pre>" if result else ""
    active_home = "active" if active_page == "home" else ""
    active_dicom = "active" if active_page == "dicom" else ""
    active_hpc = "active" if active_page == "hpc" else ""
    active_utilz = "active" if active_page == "utilz" else ""
    home_hidden = "hidden" if active_page != "home" else ""
    dicom_hidden = "hidden" if active_page != "dicom" else ""
    hpc_hidden = "hidden" if active_page != "hpc" else ""
    utilz_hidden = "hidden" if active_page != "utilz" else ""
    return f"""<!doctype html>
<html><head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Agent Hub</title>
  <style>
    :root {{
      --bg: #f2efe8;
      --card: #fffdf8;
      --ink: #1f2937;
      --accent: #0f766e;
      --accent2: #c2410c;
      --line: #d6d3d1;
    }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 10% 10%, #fff6df 0, var(--bg) 45%);
    }}
    .wrap {{ max-width: 1100px; margin: 24px auto; padding: 0 16px; }}
    h1 {{ margin: 0 0 16px; letter-spacing: 0.5px; }}
    .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.05);
    }}
    label {{ font-size: 13px; display: block; margin: 6px 0 2px; }}
    input, select {{
      width: 100%;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-sizing: border-box;
      background: #fff;
    }}
    input[type="checkbox"], input[type="radio"] {{
      width: auto;
      margin-right: 6px;
    }}
    .inline {{ display: flex; align-items: center; gap: 14px; margin: 8px 0; font-size: 14px; }}
    button {{
      margin-top: 10px;
      padding: 9px 12px;
      border: 0;
      border-radius: 9px;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      font-weight: 600;
    }}
    a.btn {{
      display: inline-block;
      margin-top: 10px;
      padding: 9px 12px;
      border-radius: 9px;
      background: var(--accent);
      color: #fff;
      font-weight: 600;
      text-decoration: none;
    }}
    .secondary {{ background: var(--accent2); }}
    .nav {{ display: flex; gap: 8px; margin: 0 0 14px; flex-wrap: wrap; }}
    .tab {{
      display: inline-block;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      text-decoration: none;
      color: var(--ink);
      background: #fff;
      font-weight: 600;
    }}
    .tab.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .hidden {{ display: none; }}
    .hint {{ font-size: 13px; line-height: 1.35; color: #4b5563; margin: 6px 0 10px; }}
    .progress {{
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 3px;
      background: rgba(15, 118, 110, 0.18);
      display: none;
      z-index: 9999;
      overflow: hidden;
    }}
    .progress.active {{ display: block; }}
    .progress > span {{
      display: block;
      width: 35%;
      height: 100%;
      background: linear-gradient(90deg, #0f766e, #0ea5a0);
      animation: slide 1.1s infinite ease-in-out;
    }}
    @keyframes slide {{
      0% {{ transform: translateX(-120%); }}
      100% {{ transform: translateX(320%); }}
    }}
    pre {{ background: #101827; color: #e5e7eb; padding: 12px; border-radius: 12px; overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); text-align: left; padding: 6px; }}
  </style>
</head>
<body><div class="wrap">
  <div id="progress" class="progress"><span></span></div>
  <h1>Agent Hub</h1>
  <div class="nav">
    <a class="tab {active_home}" href="/?page=home">Gmail / MDT / LinkedIn</a>
    <a class="tab {active_dicom}" href="/?page=dicom">DICOM XNAT CLI</a>
    <a class="tab {active_hpc}" href="/?page=hpc">HPC CLI</a>
    <a class="tab {active_utilz}" href="/?page=utilz">utilz</a>
  </div>

  <div class="grid {home_hidden}">
    <div class="card">
      <h3>Gmail Briefing</h3>
      <form method="post" action="/run/gmail-briefing">
        <label>Lookback Days</label><input name="lookback_days" value="7" />
        <label>Spreadsheet ID</label><input name="spreadsheet_id" value="{DEFAULT_SPREADSHEET_ID}" />
        <label>Calendar ID</label><input name="calendar_id" value="primary" />
        <label>Assignee</label><input name="assignee" value="UB" />
        <label>OAuth Client JSON</label><input name="oauth_client_json" value="{escape(str(gm.get('oauth_client_json', '/home/ub/.config/gmail-agent/oauth_client.json')))}" />
        <label>Token JSON</label><input name="token_json" value="{escape(str(gm.get('token_json', '/s/agent_rw/cache/gmail_token.json')))}" />
        <label>Output JSON</label><input name="out_path" value="{escape(str(Path(gm.get('output_dir', '/s/agent_rw/index')) / 'gmail_briefing.json'))}" />
        <button type="submit">Run Gmail Briefing</button>
      </form>
    </div>

    <div class="card">
      <h3>MDT Check</h3>
      <p><a class="btn" href="{escape(mdt_spreadsheet_url)}" target="_blank" rel="noopener noreferrer">Open MDT Spreadsheet</a></p>
      <form method="post" action="/run/mdt-check">
        <label>Sheet (.ods)</label><input name="sheet_path" value="{escape(str(mdt.get('sheet', '/home/ub/code/agent/sample.ods')))}" />
        <label>Initials</label><input name="initials" value="UB" />
        <label>Week</label>
        <select name="week"><option value="current">current</option><option value="next" selected>next</option></select>
        <label>Today (YYYY-MM-DD, optional)</label><input name="today" value="" />
        <label>Output JSON</label><input name="out_path" value="{escape(str(mdt.get('output_json', '/s/agent_rw/index/mdt_next_week.json')))}" />
        <label>Friday Notification File</label><input name="notification_out" value="{escape(str(mdt.get('notification_out', '/s/agent_rw/index/mdt_friday_notification.txt')))}" />
        <button type="submit">Run MDT Check</button>
        <button class="secondary" type="submit" formaction="/run/mdt-friday">Run Friday Notify</button>
        <button class="secondary" type="submit" formaction="/run/mdt-desktop">Desktop Notify</button>
      </form>
    </div>

    <div class="card">
      <h3>LinkedIn Agent</h3>
      <form method="post" action="/run/linkedin-once">
        <button type="submit">Run Pipeline Once</button>
      </form>
      <p><a href="http://127.0.0.1:8080/ui/drafts" target="_blank">Open Full LinkedIn Draft UI (8080)</a></p>
      {_drafts_table()}
    </div>
  </div>

  <div class="grid {dicom_hidden}">
    <div class="card">
      <h3>DICOM: prepare</h3>
      <p class="hint">Use this to clean a case-folder tree and rewrite DICOM PatientID to match each direct case folder name. Set single-process mode only for debugging.</p>
      <form method="post" action="/run/dicom-prepare">
        <label>Root folder</label><input name="root_folder" value="/s/insync/datasets/bones" />
        <label>Workers</label><input name="workers" value="8" />
        <div class="inline">
          <span>Mode:</span>
          <label><input type="radio" name="multiprocess_mode" value="multi" checked />Multiprocess</label>
          <label><input type="radio" name="multiprocess_mode" value="single" />Single process</label>
        </div>
        <label class="inline"><input type="checkbox" name="debug" />Debug</label>
        <button type="submit">Run prepare</button>
      </form>
    </div>

    <div class="card">
      <h3>DICOM: dcm2nifti</h3>
      <p class="hint">Converts DICOM scans from an XNAT project into NIFTI resources. Leave <code>No interactive prompt</code> checked for non-blocking web runs. Use subject filter to limit scope.</p>
      <form method="post" action="/run/dicom-dcm2nifti">
        <label>Project ID</label><input name="project_id" value="" />
        <label>Workers</label><input name="workers" value="8" />
        <label>Subject filter (comma-separated, optional)</label><input name="subjects" value="" />
        <div class="inline">
          <span>Multiprocess:</span>
          <label><input type="radio" name="multiprocess_mode" value="multi" checked />Yes</label>
          <label><input type="radio" name="multiprocess_mode" value="single" />No</label>
        </div>
        <div class="inline">
          <span>Include date in filename:</span>
          <label><input type="radio" name="include_date" value="yes" checked />Yes</label>
          <label><input type="radio" name="include_date" value="no" />No</label>
        </div>
        <div class="inline">
          <span>Include description in filename:</span>
          <label><input type="radio" name="include_desc" value="yes" checked />Yes</label>
          <label><input type="radio" name="include_desc" value="no" />No</label>
        </div>
        <label class="inline"><input type="checkbox" name="overwrite" />Overwrite existing label</label>
        <label class="inline"><input type="checkbox" name="no_ask" checked />No interactive prompt</label>
        <button type="submit">Run dcm2nifti</button>
      </form>
    </div>

    <div class="card">
      <h3>DICOM: download-nifti</h3>
      <p class="hint">Downloads all <code>IMAGE</code> resources for one XNAT project into a local destination folder.</p>
      <form method="post" action="/run/dicom-download-nifti">
        <label>Project ID</label><input name="project_id" value="" />
        <label>Destination folder</label><input name="dest_folder" value="/tmp/xnat_downloads" />
        <label class="inline"><input type="checkbox" name="no_ask" checked />No interactive prompt</label>
        <button type="submit">Run download-nifti</button>
      </form>
    </div>

    <div class="card">
      <h3>DICOM: upload-resource</h3>
      <p class="hint">Uploads local files to matching project/subject/scan on XNAT by filename metadata. Enable <code>Create missing subject</code> only when you explicitly want new subjects created.</p>
      <form method="post" action="/run/dicom-upload-resource">
        <label>Project ID</label><input name="project_id" value="" />
        <label>Resource folder</label><input name="resource_folder" value="/tmp/xnat_resources" />
        <label>Resource label</label><input name="resource_label" value="LABELMAP" />
        <label>Errors file (optional)</label><input name="errors_file" value="" />
        <label class="inline"><input type="checkbox" name="ignore_description" />Ignore description</label>
        <label class="inline"><input type="checkbox" name="create_missing_subject" />Create missing subject</label>
        <label class="inline"><input type="checkbox" name="no_ask" checked />No interactive prompt</label>
        <button type="submit">Run upload-resource</button>
      </form>
    </div>
  </div>

  <div class="grid {hpc_hidden}">
    <div class="card">
      <h3>HPC: download</h3>
      <p class="hint">Pulls one folder from HPC to local destination using <code>rsync</code>. Keep backup enabled to preserve replaced local files under backup root.</p>
      <form method="post" action="/run/hpc-download">
        <label>Dataset folder</label><input name="dataset_folder" value="nodesthick" />
        <label>Local destination</label><input name="local_dest" value="/tmp/hpc_downloads" />
        <label>Remote login</label><input name="remote" value="mpx588@login.hpc.qmul.ac.uk" />
        <label>Remote root</label><input name="remote_root" value="/data/EECS-LITQ/fran_storage/datasets/xnat_shadow" />
        <label>Backup root</label><input name="backup_root" value="/tmp/hpc_agent_backups" />
        <label class="inline"><input type="checkbox" name="disable_backup" />Disable backup</label>
        <label class="inline"><input type="checkbox" name="yes" checked />Skip confirmation</label>
        <button type="submit">Run download</button>
      </form>
    </div>

    <div class="card">
      <h3>HPC: upload</h3>
      <p class="hint">Pushes one local folder to HPC via <code>rsync</code>. If remote subdir is empty, the local folder name is used on the remote side.</p>
      <form method="post" action="/run/hpc-upload">
        <label>Local folder</label><input name="local_folder" value="" />
        <label>Remote subdir (optional)</label><input name="remote_subdir" value="" />
        <label>Remote login</label><input name="remote" value="mpx588@login.hpc.qmul.ac.uk" />
        <label>Remote root</label><input name="remote_root" value="/data/EECS-LITQ/fran_storage/datasets/xnat_shadow" />
        <label class="inline"><input type="checkbox" name="yes" checked />Skip confirmation</label>
        <button type="submit">Run upload</button>
      </form>
    </div>
  </div>

  <div class="grid {utilz_hidden}">
    <div class="card">
      <h3>utilz: overlay grid GIF</h3>
      <p class="hint">Creates an animated overlay GIF from a dataset root that contains matching <code>images/</code> and <code>lms/</code> subfolders.</p>
      <form method="post" action="/run/utilz-overlay-gif">
        <label title="Root folder that contains images/ and lms/ with matching basenames.">Dataset root</label><input title="Root folder that contains images/ and lms/ with matching basenames." name="dataset_root" value="/s/agent_rw/datasets/example_dataset" />
        <label title="Destination GIF file path. Default uses COLD_STORAGE/tmp from config when available.">Output GIF</label><input title="Destination GIF file path. Default uses COLD_STORAGE/tmp from config when available." name="output_gif" value="{escape(str(utilz_output_default))}" />
        <label title="Grid row count for the animated panel layout.">Rows</label><input title="Grid row count for the animated panel layout." name="rows" value="{escape(utilz_defaults.get('rows', '6'))}" />
        <label title="Grid column count for the animated panel layout.">Cols</label><input title="Grid column count for the animated panel layout." name="cols" value="{escape(utilz_defaults.get('cols', '6'))}" />
        <label title="Total number of animation frames to generate.">Frames</label><input title="Total number of animation frames to generate." name="num_frames" value="{escape(utilz_defaults.get('num_frames', '90'))}" />
        <label title="Playback speed in frames per second.">FPS</label><input title="Playback speed in frames per second." name="fps" value="{escape(utilz_defaults.get('fps', '10'))}" />
        <label title="Slice step multiplier per frame; higher values scroll faster through slices.">Stride</label><input title="Slice step multiplier per frame; higher values scroll faster through slices." name="stride" value="{escape(utilz_defaults.get('stride', '1'))}" />
        <label title="Approximate output pixels per panel side. Lower values reduce GIF file size.">Panel size (px)</label><input title="Approximate output pixels per panel side. Lower values reduce GIF file size." name="panel_px" value="{escape(utilz_defaults.get('panel_px', '120'))}" />
        <label title="GIF palette colors (2-256). Lower values reduce file size.">GIF colors</label><input title="GIF palette colors (2-256). Lower values reduce file size." name="gif_colors" value="{escape(utilz_defaults.get('gif_colors', '96'))}" />
        <label title="Optional depth axis for tensor inputs: 0, 1, or 2. Leave empty to auto-infer.">Slice axis (optional: 0, 1, 2)</label><input title="Optional depth axis for tensor inputs: 0, 1, or 2. Leave empty to auto-infer." name="slice_axis" value="{escape(utilz_defaults.get('slice_axis', ''))}" />
        <label title="Window preset for image intensity scaling.">Window</label>
        <select name="window" title="Window preset for image intensity scaling.">
          <option value="lung" {"selected" if utilz_defaults.get("window", "abdomen") == "lung" else ""}>lung</option>
          <option value="abdomen" {"selected" if utilz_defaults.get("window", "abdomen") == "abdomen" else ""}>abdomen</option>
          <option value="bone" {"selected" if utilz_defaults.get("window", "abdomen") == "bone" else ""}>bone</option>
        </select>
        <label title="Rotate each frame clockwise in 90-degree steps.">&#x21bb; Rotate (clockwise)</label>
        <select name="rotate_cw" title="Rotate each frame clockwise in 90-degree steps.">
          <option value="0" {"selected" if utilz_defaults.get("rotate_cw", "0") == "0" else ""}>0 degrees</option>
          <option value="90" {"selected" if utilz_defaults.get("rotate_cw", "0") == "90" else ""}>90 degrees</option>
          <option value="180" {"selected" if utilz_defaults.get("rotate_cw", "0") == "180" else ""}>180 degrees</option>
          <option value="270" {"selected" if utilz_defaults.get("rotate_cw", "0") == "270" else ""}>270 degrees</option>
        </select>
        <label class="inline" title="Store current utilz settings as defaults for next runs (excluding dataset root and output GIF)."><input type="checkbox" name="safe_as_defaults" />Save as defaults</label>
        <button type="submit">Run utilz GIF</button>
      </form>
    </div>
  </div>

  {result_html}
</div>
<script>
  (function () {{
    var progress = document.getElementById("progress");
    var forms = document.querySelectorAll('form[method="post"]');
    for (var i = 0; i < forms.length; i++) {{
      forms[i].addEventListener("submit", function () {{
        if (progress) progress.classList.add("active");
      }});
    }}
  }})();
</script>
</body></html>"""


def _get(form: dict[str, str], key: str, default: str = "") -> str:
    return form.get(key, default)


class AgentHubHandler(BaseHTTPRequestHandler):
    def _send_html(self, html: str, code: int = 200) -> None:
        data = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parse_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")
        parsed = parse_qs(body, keep_blank_values=True)
        return {k: v[-1] for k, v in parsed.items()}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self._send_html(_render_page("Not found"), code=404)
            return
        query = parse_qs(parsed.query, keep_blank_values=True)
        page = query.get("page", ["home"])[-1] or "home"
        if page not in {"home", "dicom", "hpc", "utilz"}:
            page = "home"
        self._send_html(_render_page(active_page=page))

    def do_POST(self) -> None:  # noqa: N802
        try:
            form = self._parse_form()
            if self.path == "/run/gmail-briefing":
                out = run_gmail_briefing(
                    oauth_client_json=Path(_get(form, "oauth_client_json")),
                    token_json=Path(_get(form, "token_json")),
                    lookback_days=int(_get(form, "lookback_days", "7")),
                    spreadsheet_id=_get(form, "spreadsheet_id"),
                    calendar_id=_get(form, "calendar_id", "primary"),
                    assignee=_get(form, "assignee", "UB"),
                    out_path=Path(_get(form, "out_path")),
                )
                self._send_html(_render_page(f"Gmail briefing wrote: {out}"))
                return

            if self.path == "/run/mdt-check":
                run_today = date.fromisoformat(_get(form, "today")) if _get(form, "today") else date.today()
                initials = _get(form, "initials", "UB")
                week = _get(form, "week", "next")
                meetings = extract_mdt_meetings_for_week(
                    ods_path=Path(_get(form, "sheet_path")),
                    initials=initials,
                    week_mode=week,
                    today=run_today,
                )
                out_json = Path(_get(form, "out_path"))
                write_mdt_output(out_json=out_json, meetings=meetings, initials=initials, today=run_today)
                lines = [f"MDT wrote: {out_json}"]
                lines += [f"{m.date_iso} ({m.weekday}) | {m.meeting_name} | {m.assignment}" for m in meetings] or ["No meetings"]
                self._send_html(_render_page("\n".join(lines)))
                return

            if self.path == "/run/mdt-friday":
                run_today = date.fromisoformat(_get(form, "today")) if _get(form, "today") else date.today()
                initials = _get(form, "initials", "UB")
                meetings = extract_next_week_mdt_meetings(
                    ods_path=Path(_get(form, "sheet_path")),
                    initials=initials,
                    today=run_today,
                )
                msg = build_friday_notification(meetings=meetings, initials=initials, today=run_today)
                out = Path(_get(form, "notification_out"))
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(msg + "\n", encoding="utf-8")
                self._send_html(_render_page(f"Friday notification wrote: {out}\n\n{msg}"))
                return

            if self.path == "/run/mdt-desktop":
                run_today = date.fromisoformat(_get(form, "today")) if _get(form, "today") else date.today()
                initials = _get(form, "initials", "UB")
                week = _get(form, "week", "current")
                body = _send_mdt_desktop_notification(
                    sheet_path=Path(_get(form, "sheet_path")),
                    initials=initials,
                    week=week,
                    run_today=run_today,
                )
                self._send_html(_render_page("Desktop notification sent:\n" + body))
                return

            if self.path == "/run/linkedin-once":
                s = load_settings(LINKEDIN_ROOT)
                init_db(s.db_path)
                result = run_pipeline(
                    db_path=s.db_path,
                    experiments_dir=s.sources_experiments,
                    notes_dir=s.sources_notes,
                    feeds_config=s.feeds_config,
                    feed_cache_dir=s.sources_feeds,
                    min_score=s.min_relevance_score,
                )
                self._send_html(_render_page("LinkedIn pipeline run:\n" + json.dumps(result, indent=2)))
                return

            if self.path == "/run/dicom-prepare":
                root_folder = _get(form, "root_folder").strip()
                if not root_folder:
                    raise ValueError("root_folder is required")
                args = ["prepare", root_folder, "--workers", _get(form, "workers", "8")]
                if _get(form, "multiprocess_mode", "multi") == "single":
                    args.append("--no-multiprocess")
                if _is_checked(form, "debug"):
                    args.append("--debug")
                self._send_html(_render_page(_run_cli_script(DICOM_CLI, args), active_page="dicom"))
                return

            if self.path == "/run/dicom-dcm2nifti":
                project_id = _get(form, "project_id").strip()
                if not project_id:
                    raise ValueError("project_id is required")
                args = ["dcm2nifti", project_id, "--workers", _get(form, "workers", "8")]
                if _get(form, "multiprocess_mode", "multi") == "single":
                    args.append("--no-multiprocess")
                if _get(form, "include_date", "yes") == "no":
                    args.append("--no-date")
                if _get(form, "include_desc", "yes") == "no":
                    args.append("--no-desc")
                if _is_checked(form, "overwrite"):
                    args.append("--overwrite")
                if _is_checked(form, "no_ask"):
                    args.append("--no-ask")
                subjects = [s.strip() for s in _get(form, "subjects").split(",") if s.strip()]
                for subject in subjects:
                    args.extend(["--subject", subject])
                self._send_html(_render_page(_run_cli_script(DICOM_CLI, args), active_page="dicom"))
                return

            if self.path == "/run/dicom-download-nifti":
                project_id = _get(form, "project_id").strip()
                dest_folder = _get(form, "dest_folder").strip()
                if not project_id:
                    raise ValueError("project_id is required")
                if not dest_folder:
                    raise ValueError("dest_folder is required")
                args = ["download-nifti", project_id, dest_folder]
                if _is_checked(form, "no_ask"):
                    args.append("--no-ask")
                self._send_html(_render_page(_run_cli_script(DICOM_CLI, args), active_page="dicom"))
                return

            if self.path == "/run/dicom-upload-resource":
                project_id = _get(form, "project_id").strip()
                resource_folder = _get(form, "resource_folder").strip()
                resource_label = _get(form, "resource_label").strip()
                if not project_id:
                    raise ValueError("project_id is required")
                if not resource_folder:
                    raise ValueError("resource_folder is required")
                if not resource_label:
                    raise ValueError("resource_label is required")
                args = ["upload-resource", project_id, resource_folder, resource_label]
                errors_file = _get(form, "errors_file").strip()
                if errors_file:
                    args.extend(["--errors-file", errors_file])
                if _is_checked(form, "ignore_description"):
                    args.append("--ignore-description")
                if _is_checked(form, "create_missing_subject"):
                    args.append("--create-missing-subject")
                if _is_checked(form, "no_ask"):
                    args.append("--no-ask")
                self._send_html(_render_page(_run_cli_script(DICOM_CLI, args), active_page="dicom"))
                return

            if self.path == "/run/hpc-download":
                dataset_folder = _get(form, "dataset_folder").strip()
                local_dest = _get(form, "local_dest").strip()
                if not dataset_folder:
                    raise ValueError("dataset_folder is required")
                if not local_dest:
                    raise ValueError("local_dest is required")
                args = [
                    "download",
                    dataset_folder,
                    local_dest,
                    "--remote",
                    _get(form, "remote", "mpx588@login.hpc.qmul.ac.uk"),
                    "--remote-root",
                    _get(form, "remote_root", "/data/EECS-LITQ/fran_storage/datasets/xnat_shadow"),
                    "--backup-root",
                    _get(form, "backup_root", "/tmp/hpc_agent_backups"),
                ]
                if _is_checked(form, "disable_backup"):
                    args.append("--no-backup")
                if _is_checked(form, "yes"):
                    args.append("--yes")
                self._send_html(_render_page(_run_cli_script(HPC_CLI, args), active_page="hpc"))
                return

            if self.path == "/run/hpc-upload":
                local_folder = _get(form, "local_folder").strip()
                if not local_folder:
                    raise ValueError("local_folder is required")
                args = [
                    "upload",
                    local_folder,
                    "--remote",
                    _get(form, "remote", "mpx588@login.hpc.qmul.ac.uk"),
                    "--remote-root",
                    _get(form, "remote_root", "/data/EECS-LITQ/fran_storage/datasets/xnat_shadow"),
                ]
                remote_subdir = _get(form, "remote_subdir").strip()
                if remote_subdir:
                    args.extend(["--remote-subdir", remote_subdir])
                if _is_checked(form, "yes"):
                    args.append("--yes")
                self._send_html(_render_page(_run_cli_script(HPC_CLI, args), active_page="hpc"))
                return

            if self.path == "/run/utilz-overlay-gif":
                dataset_root = _get(form, "dataset_root").strip()
                output_gif = _get(form, "output_gif").strip()
                window = _get(form, "window", "abdomen").strip().lower() or "abdomen"
                if window not in {"lung", "abdomen", "bone"}:
                    raise ValueError("window must be one of: lung, abdomen, bone")
                rotate_cw = _get(form, "rotate_cw", "0").strip() or "0"
                if rotate_cw not in {"0", "90", "180", "270"}:
                    raise ValueError("rotate_cw must be one of: 0, 90, 180, 270")
                if not dataset_root:
                    raise ValueError("dataset_root is required")
                if not output_gif:
                    raise ValueError("output_gif is required")
                output_gif_path = _next_indexed_path(Path(output_gif).expanduser())
                utilz_form_values = {
                    "rows": _get(form, "rows", "6"),
                    "cols": _get(form, "cols", "6"),
                    "num_frames": _get(form, "num_frames", "90"),
                    "fps": _get(form, "fps", "10"),
                    "stride": _get(form, "stride", "1"),
                    "panel_px": _get(form, "panel_px", "120"),
                    "gif_colors": _get(form, "gif_colors", "96"),
                    "slice_axis": _get(form, "slice_axis", "").strip(),
                    "window": window,
                    "rotate_cw": rotate_cw,
                }
                saved_defaults_msg = ""
                if _is_checked(form, "safe_as_defaults"):
                    defaults_path = _save_utilz_defaults(utilz_form_values)
                    saved_defaults_msg = f"Saved utilz defaults: {defaults_path}\n\n"
                args = [
                    "--dataset-root",
                    dataset_root,
                    "--output-gif",
                    str(output_gif_path),
                    "--rows",
                    _get(form, "rows", "6"),
                    "--cols",
                    _get(form, "cols", "6"),
                    "--num-frames",
                    _get(form, "num_frames", "90"),
                    "--fps",
                    utilz_form_values["fps"],
                    "--stride",
                    utilz_form_values["stride"],
                    "--panel-px",
                    utilz_form_values["panel_px"],
                    "--gif-colors",
                    utilz_form_values["gif_colors"],
                    "--window",
                    window,
                    "--rotate-cw",
                    rotate_cw,
                ]
                slice_axis = utilz_form_values["slice_axis"]
                if slice_axis:
                    args.extend(["--slice-axis", slice_axis])
                run_out = _run_cli_script(UTILZ_OVERLAY_GIF_SCRIPT, args)
                if str(output_gif_path) != output_gif:
                    run_out = f"Indexed output path: {output_gif_path}\n\n{run_out}"
                self._send_html(_render_page(saved_defaults_msg + run_out, active_page="utilz"))
                return

            self._send_html(_render_page("Unknown action"), code=404)
        except Exception as exc:
            self._send_html(_render_page(f"Error:\n{exc}"), code=500)


def main() -> None:
    cfg = _load_gmail_cfg()
    mdt = cfg.get("mdt", {})
    today = date.today()
    try:
        if _already_sent_today(today):
            print(f"Startup MDT notification skipped: already sent for {today.isoformat()}")
        else:
            startup_body = _send_mdt_desktop_notification(
                sheet_path=Path(mdt.get("sheet", "/home/ub/code/agent/sample.ods")),
                initials="UB",
                week="current",
            )
            _mark_startup_sent(today)
            print("Startup MDT notification sent:")
            print(startup_body)
    except Exception as exc:
        print(f"Startup MDT notification skipped: {exc}")

    host = "127.0.0.1"
    port = 8090
    server = ThreadingHTTPServer((host, port), AgentHubHandler)
    print(f"Agent Hub running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
