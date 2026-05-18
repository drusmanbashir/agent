from __future__ import annotations

import json

from agent.control_plane.cli_app import ask_text, parse_train_intent


def call_api(prompt: str, options: dict, context: dict) -> dict[str, str]:
    config = options["config"]
    operation = "parse_train_intent"
    if "operation" in config:
        operation = str(config["operation"])
    if operation == "parse_train_intent":
        payload = parse_train_intent(prompt)
    elif operation == "ask_text":
        submit = False
        if "submit" in config:
            submit = bool(config["submit"])
        payload = ask_text(prompt, submit=submit)
    else:
        raise ValueError(f"Unsupported promptfoo operation: {operation}")
    return {"output": json.dumps(payload, sort_keys=True)}
