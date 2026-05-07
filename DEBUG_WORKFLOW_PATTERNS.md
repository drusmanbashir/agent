# Debug Workflow Patterns

This note captures common ways tools standardize debugging advice, control flow, and escalation.

## 1. Decision Table / Rulebook
Best when the path is mostly deterministic: if signals X and Y appear, do action Z.

Examples:
- Prometheus Alertmanager routing and inhibition rules
- Dependabot / Renovate package rules
- Semgrep rule packs for known code and config smells

Strengths:
- Fast to evaluate
- Easy to diff and review
- Good for policy-like routing and first-pass guidance

Limits:
- Weak at long-running, branching investigations
- Hard to express stateful recovery steps

## 2. Runbook Registry
Best when humans still drive the investigation, but the system should attach the right procedure.

Examples:
- PagerDuty Runbook Automation
- Rundeck job and runbook catalogs
- StackStorm action packs used as operational playbooks

Strengths:
- Clear ownership and reusable procedures
- Good bridge from alert or symptom to approved actions
- Low ceremony

Limits:
- Usually advisory unless tightly integrated with execution
- Consistency depends on runbook quality and upkeep

## 3. Rule Engine / Policy Engine
Best when debug decisions need portable policy evaluation across many contexts.

Examples:
- OPA
- Drools
- `json-rules-engine`
- Semgrep rules also fit here when used as executable detection policy

Strengths:
- Centralized logic
- Declarative and testable
- Good for gating, classification, and recommended next steps

Limits:
- Harder for operators to read than plain runbooks
- Can become opaque if rules grow without structure

## 4. Workflow Graph / State Machine
Best when debugging is multi-step, stateful, resumable, or partly automated.

Examples:
- Temporal
- AWS Step Functions
- Argo Workflows
- LangGraph
- Prefect
- Dagster

Strengths:
- Explicit state, retries, branching, and resumability
- Good for long investigations and partial automation
- Makes control flow auditable

Limits:
- More system weight
- Overkill for simple advisory flows

## 5. Case-Based Triage Registry
Best when prior incidents and saved investigation patterns are more useful than hard rules alone.

Examples:
- Sentry fingerprinting and issue grouping
- Splunk saved investigations
- Honeycomb saved investigations

Strengths:
- Captures real operational history
- Helps map current symptoms to known cases
- Useful when failures are noisy or partially unique

Limits:
- Retrieval quality depends on tagging and curation
- Can drift into a pile of anecdotes without structure

## ACP Recommendation
Likely best fit:
- A declarative advisory workflow registry for symptom -> guidance mapping
- A debug tool registry describing what each tool can inspect or execute
- A lightweight workflow / state-machine layer for multi-step debug sessions

Why this shape:
- Keeps common cases compact and reviewable
- Avoids forcing every debug path into heavyweight orchestration
- Leaves room for resumable, stateful investigations when the path is not linear

Practical interpretation:
- Use registry entries and rules for classification and recommended next actions
- Use the workflow/state-machine layer only when a debug session needs branching, retries, or persisted progress
