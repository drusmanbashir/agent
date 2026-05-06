from __future__ import annotations

from agent.control_plane.models import BLOCKED, READY


def decide_train_workflow(
    *,
    project_title: str,
    plan: int,
    readiness: dict[str, object],
    provider: str = "ollama",
    model: str = "",
) -> dict[str, object]:
    if readiness["status"] == READY:
        action = "submit_local_train"
        message = f"{project_title} plan {plan} is ready; submit local train."
    elif readiness["status"] == BLOCKED and readiness["breakpoint"] == "preproc":
        action = "submit_preproc"
        message = f"{project_title} plan {plan} needs preprocessing before train; submit preproc and observe briefly."
    else:
        action = "return_blocked"
        message = str(readiness["message"])

    return {
        "provider": provider,
        "model": model,
        "intent": "train",
        "action": action,
        "message": message,
        "details": {"readiness": readiness},
    }
