from __future__ import annotations

import json

from agent.control_plane.promptfoo_assert import assert_payload_matches_expected
from agent.control_plane.promptfoo_provider import call_api


def test_promptfoo_provider_parses_train_intent() -> None:
    payload = call_api(
        "train kits23 plan 3 fold 0 lr 0.01 val 2 hpc run smoke",
        {"config": {"operation": "parse_train_intent"}},
        {},
    )
    output = json.loads(payload["output"])

    assert output["intent"] == "train"
    assert output["project_title"] == "kits23"
    assert output["mode"] == "hpc"
    assert output["run_name"] == "smoke"
    assert output["provider_metadata"]["model_call"] is False


def test_promptfoo_assert_matches_expected_unknown_intent() -> None:
    result = assert_payload_matches_expected(
        json.dumps(
            {
                "intent": "unknown",
                "text": "summarize kits23",
                "provider_metadata": {
                    "provider": "ollama",
                    "model": "",
                    "parse_path": "deterministic_narrow",
                    "model_call": False,
                    "message": "No Ollama/LangChain model call is wired here; parsing is deterministic and narrow.",
                },
                "message": "Expected a narrow train intent like: train kits23 plan 3 fold 0 lr 0.01 val 2.",
            },
            sort_keys=True,
        ),
        {
            "vars": {
                "expected_intent": "unknown",
                "expected_message_substring": "Expected a narrow train intent",
                "expected_model_call": False,
            }
        },
    )

    assert result["pass"] is True
