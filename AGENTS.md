# AGENTS.md

## Deep-Mode
- Deep-mode is off by default.

- Implemented changes esp in ~/scripts, must be verified silently on your end before telling me theyr work.
- After approved changes to ~/scripts/ folder, git push, if you're on mac a next necessary step is to ssh into ubuntu and git pull
- Distinguish confirmed facts from assumptions before proposing mitigation or redesign.
- The trigger for deep-mode is `/dm`, if that token is available in the user message.
- Only execute the instructions in this Deep-Mode section after I explicitly toggle it with `/dm`.
- When deep-mode is toggled on, first echo exactly: `DEEP-MODE on`
- After that echo, print this Deep-Mode section so I can see the active instructions.
- While deep-mode is on, do broader investigation and validation than usual:
  - inspect adjacent config/code paths that may affect the issue
  - run clean-environment or reproduction checks when relevant
  - verify behavior after edits, not just read back changed lines
  - report assumptions, residual uncertainty, and skipped checks
- When deep-mode is off, do not perform deep-mode-only checks. For simple config/text edits, a direct edit plus a small readback is enough unless I ask for testing.

## XNAT Ruleset (Required)
- For any XNAT upload/download task that matches file metadata to subject IDs, load and follow:
  `automation/xnat/workflows/matching_rules.v1.yaml`
- Enforce this ruleset before matching begins.
- Matching parser is fixed to `info_from_filename` from `~/code/utilz/utilz/helpers.py`.
- Before any XNAT upload action, show a preflight sample of 1 to 3 files in chat:
  filename, parsed `(project, subject_id, date, description)`, and planned action.
- Before any XNAT upload action, explicitly ask:
  create new subject if missing, or skip missing subjects.
- Before any XNAT download action, show a preflight sample of 1 to 3 items in chat:
  planned project/subject/label targets and destination path.

