# Security Review

Date: 2026-05-04

Scope reviewed:
- local web/control surfaces in `~/code/agent`
- HPC submit/poll/resubmit shell wrappers
- shared secret loading and token paths
- job metadata and registry handling

## Findings

### 1. Critical: command injection risk in job resubmit path

Files:
- [agent/hpc/cli/hpc_resubmit.sh](/home/ub/code/agent/agent/hpc/cli/hpc_resubmit.sh)
- [agent/hpc/cli/hpc_submit_poll_fetch.sh](/home/ub/code/agent/agent/hpc/cli/hpc_submit_poll_fetch.sh)

Evidence:
- `hpc_resubmit.sh` reads `submit_argv` from `job.meta`
- it then runs:
  - `eval "set -- ${submit_argv}"`

Risk:
- `job.meta` is local mutable state under `/s/agent_rw/hpc_logs/<job_id>/job.meta`
- if an attacker or accidental edit injects shell syntax into `submit_argv`, `eval` executes it before resubmission
- this is local-code-execution in the current user context

Smallest safe fix:
- stop storing replay input as shell text
- store a structured argv format instead:
  - newline-delimited args
  - or JSON array
- resubmit by parsing that structure without `eval`

Interim mitigation:
- treat `hpc_resubmit.sh` as unsafe until `eval` is removed
- do not use it on untrusted or hand-edited `job.meta`

### 2. High: localhost control surfaces have no auth or CSRF protection

Files:
- [agent/hpc/cli/hpc_dashboard_web.py](/home/ub/code/agent/agent/hpc/cli/hpc_dashboard_web.py)
- [agent/hpc/cli/hpc_dashboard_service](/home/ub/code/agent/agent/hpc/cli/hpc_dashboard_service)
- [agent_hub.py](/home/ub/code/agent/agent_hub.py)

Evidence:
- both use `ThreadingHTTPServer`
- dashboard exposes state-changing POST routes:
  - `/poll_selected`
  - `/poll_all_active`
- `agent_hub.py` exposes browser-triggerable actions with no auth
- services bind to `127.0.0.1`, which helps, but browsers can still submit cross-origin forms to localhost

Risk:
- any web page opened in the browser can attempt CSRF-style POSTs to localhost services
- on a single-user workstation this is still meaningful because these actions can:
  - trigger polling/fetches
  - open URLs
  - invoke local subprocess-backed workflows

Smallest safe fix:
- add a per-start random bearer token stored in the service state dir
- require that token on all POST actions
- reject POSTs missing the token

Good follow-up:
- also check `Origin` / `Referer` on POST
- optionally bind the service to a Unix socket instead of TCP if browser access is not required

### 3. Medium: provenance logging can capture secrets into `job.meta`

Files:
- [agent/hpc/cli/hpc_submit_poll_fetch.sh](/home/ub/code/agent/agent/hpc/cli/hpc_submit_poll_fetch.sh)

Evidence:
- submit metadata now records:
  - `submit_argv`
  - `script_args`

Risk:
- if future submit flows pass secrets, tokens, or sensitive paths on argv, they will be written in plaintext under `/s/agent_rw/hpc_logs/<job_id>/job.meta`
- this expands secret exposure from process lifetime to persistent file lifetime

Smallest safe fix:
- redact known-sensitive flags before writing provenance
- examples:
  - `--token`
  - `--password`
  - `--secret`
  - `--api-key`
- alternatively make full argv provenance opt-in for selected scripts only

Operational guidance:
- avoid passing secrets on argv in any new HPC submit flow

### 4. Medium: shared secrets are loaded without permission or ownership checks

Files:
- [agent/gmail/agent/secret_store.py](/home/ub/code/agent/agent/gmail/agent/secret_store.py)
- [agent/linkedin/publishers/linkedin.py](/home/ub/code/agent/agent/linkedin/publishers/linkedin.py)
- [agent/linkedin/publishers/x_publisher.py](/home/ub/code/agent/agent/linkedin/publishers/x_publisher.py)

Evidence:
- shared secrets default path:
  - `/s/agent_rw/conf/agent_repo/secrets.env`
- loader reads and injects values into environment without checking:
  - file mode
  - file owner
  - symlink status

Risk:
- weak filesystem permissions can turn secret exposure into a silent configuration issue
- symlink/path confusion could redirect loading to the wrong file

Smallest safe fix:
- before reading secrets:
  - reject symlinks
  - require owner == current user
  - require mode no broader than `0600`

Operational guidance:
- audit:
  - `/s/agent_rw/conf/agent_repo/secrets.env`
  - `/s/agent_rw/cache/gmail_token.json`

### 5. Medium: password-backed HPC SSH path increases secret handling surface

Files:
- [agent/hpc/cli/hpc_ssh.sh](/home/ub/code/agent/agent/hpc/cli/hpc_ssh.sh)
- [agent/hpc/tools/cli.py](/home/ub/code/agent/agent/hpc/tools/cli.py)

Evidence:
- password can be retrieved programmatically with:
  - `load_pwd --field password --show-password`
- `hpc_ssh.sh` uses `sshpass` through environment

Risk:
- expected for legacy access, but still a broader attack surface than key-only auth
- secrets may leak through logs, operator habits, or accidental wrapper reuse

Smallest safe fix:
- prefer `hpc_ssh_nopass.sh` wherever possible
- keep password path only as fallback
- gate password-backed path behind explicit opt-in env or flag

Good follow-up:
- add a warning banner whenever password-backed SSH path is used

## Lower-Priority Notes

- `agent_hub.py` and dashboard services are localhost-only by default, which reduces exposure materially. The main concern is local-browser CSRF, not direct remote reachability.
- The malformed registry rows that crashed the closed-job dashboard were a robustness problem first, not a direct security issue. The tolerant parser fix was still correct because parser crashes can hide operational state.

## Recommended Order

1. Remove `eval` from `hpc_resubmit.sh`
2. Add POST auth token to localhost web control surfaces
3. Redact or reduce argv provenance in `job.meta`
4. Enforce file-permission checks for shared secrets
5. De-emphasize password-backed SSH in favor of key-only paths

## Minimal Remediation Strategy

- Keep current registry schema
- Keep current service ports and localhost binding
- Do not redesign the whole stack
- Fix the small high-risk edges first:
  - stored-input execution
  - unauthenticated POST actions
  - persistent secret capture
