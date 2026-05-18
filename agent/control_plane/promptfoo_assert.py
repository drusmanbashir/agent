from __future__ import annotations

import json


def _intent_payload(payload: dict[str, object]) -> dict[str, object]:
    intent = payload["intent"]
    if isinstance(intent, dict):
        return intent
    return payload


def assert_payload_matches_expected(output: str, context: dict) -> dict[str, object]:
    payload = json.loads(output)
    vars_dict = context["vars"]
    intent_payload = _intent_payload(payload)

    failures = []

    if "expected_intent" in vars_dict and intent_payload["intent"] != vars_dict["expected_intent"]:
        failures.append(f"intent={intent_payload['intent']}")
    if "expected_project_title" in vars_dict and intent_payload["project_title"] != vars_dict["expected_project_title"]:
        failures.append(f"project_title={intent_payload['project_title']}")
    if "expected_plan" in vars_dict and intent_payload["plan"] != vars_dict["expected_plan"]:
        failures.append(f"plan={intent_payload['plan']}")
    if "expected_mode" in vars_dict and intent_payload["mode"] != vars_dict["expected_mode"]:
        failures.append(f"mode={intent_payload['mode']}")
    if "expected_fold" in vars_dict and intent_payload["fold"] != vars_dict["expected_fold"]:
        failures.append(f"fold={intent_payload['fold']}")
    if "expected_learning_rate" in vars_dict and intent_payload["learning_rate"] != vars_dict["expected_learning_rate"]:
        failures.append(f"learning_rate={intent_payload['learning_rate']}")
    if "expected_val_every_n_epochs" in vars_dict and intent_payload["val_every_n_epochs"] != vars_dict["expected_val_every_n_epochs"]:
        failures.append(f"val_every_n_epochs={intent_payload['val_every_n_epochs']}")
    if "expected_train_indices" in vars_dict and intent_payload["train_indices"] != vars_dict["expected_train_indices"]:
        failures.append(f"train_indices={intent_payload['train_indices']}")
    if "expected_run_name" in vars_dict and intent_payload["run_name"] != vars_dict["expected_run_name"]:
        failures.append(f"run_name={intent_payload['run_name']}")

    provider_metadata = payload["provider_metadata"]
    if "expected_model_call" in vars_dict and provider_metadata["model_call"] != vars_dict["expected_model_call"]:
        failures.append(f"model_call={provider_metadata['model_call']}")

    if "expected_message_substring" in vars_dict and vars_dict["expected_message_substring"] not in payload["message"]:
        failures.append(f"message={payload['message']}")

    passed = len(failures) == 0
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "ok" if passed else "; ".join(failures),
    }
