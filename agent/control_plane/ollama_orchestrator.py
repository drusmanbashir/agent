from __future__ import annotations


def decide_train_workflow(
    *,
    project_title: str,
    plan: int,
    readiness: dict[str, object],
    provider: str = "ollama",
    model: str = "",
) -> dict[str, object]:
    if readiness["status"] == "ready":
        return {
            "provider": provider,
            "model": model,
            "intent": "train",
            "action": "submit_local_train",
            "breakpoint": None,
            "message": f"{project_title} plan {plan} is ready; submit local train.",
            "details": {"readiness": readiness},
        }
    return {
        "provider": provider,
        "model": model,
        "intent": "train",
        "action": "return_breakpoint",
        "breakpoint": readiness["breakpoint"],
        "message": readiness["message"],
        "details": {"readiness": readiness},
    }
