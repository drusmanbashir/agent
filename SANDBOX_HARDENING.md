# Agent Sandbox Hardening Checklist

Use this checklist to reduce risk and restrict the agent to approved write locations.

## Why `/tmp` was writable
The runtime sandbox currently allows writes to these roots:
- `/home/ub/code/agent`
- `/tmp`

`/tmp` access comes from sandbox configuration, not from agent choice.

## How to restrict write scope
1. Set writable roots to only approved folders.
   - Example: only `/home/ub/code/agent`
   - Remove `/tmp` unless explicitly needed.

2. Keep sandbox mode strict.
   - Use `workspace-write` or stricter.
   - Avoid unrestricted modes.

3. Require approval for escalated commands.
   - Keep escalation behind explicit user confirmation.

4. Use a dedicated low-privilege user or container.
   - Mount only approved paths.
   - Do not pass sensitive environment variables by default.

5. Block network access unless required.
   - Reduces exfiltration risk from malicious prompts/code.

6. Add launcher-level path allowlisting.
   - Reject any command that reads/writes outside approved roots.
   - Log blocked attempts for auditability.

## Recommended baseline policy
- Writable roots: only project folder(s)
- No `/tmp` write access by default
- Escalation: explicit approval required
- Network: off by default
- Runtime: isolated user/container
