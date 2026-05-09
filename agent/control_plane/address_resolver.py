from __future__ import annotations

import os
import sys

DEFAULT_FRAN_WEBAPP_APP_DIR = "/home/ub/code/fran"
DEFAULT_FRAN_WEBAPP_APP = "agent.webapp.api.main:app"
DEFAULT_FRAN_WEBAPP_HOST = "127.0.0.1"
DEFAULT_FRAN_WEBAPP_PORT = "8000"
DEFAULT_FRAN_JOBS_PATH = "/hpc/jobs"


def _env_or_default(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def fran_webapp_app_dir() -> str:
    return _env_or_default("FRAN_WEBAPP_APP_DIR", DEFAULT_FRAN_WEBAPP_APP_DIR)


def fran_webapp_app() -> str:
    return _env_or_default("FRAN_WEBAPP_APP", DEFAULT_FRAN_WEBAPP_APP)


def fran_webapp_host() -> str:
    return _env_or_default("FRAN_WEBAPP_HOST", DEFAULT_FRAN_WEBAPP_HOST)


def fran_webapp_port() -> str:
    return _env_or_default("FRAN_WEBAPP_PORT", DEFAULT_FRAN_WEBAPP_PORT)


def fran_jobs_page_url() -> str:
    override = os.environ.get("FRAN_JOBS_PAGE_URL", "").strip()
    if override:
        return override
    return f"http://{fran_webapp_host()}:{fran_webapp_port()}{DEFAULT_FRAN_JOBS_PATH}"


def fran_uvicorn_pattern() -> str:
    return (
        f"uvicorn --app-dir {fran_webapp_app_dir()} {fran_webapp_app()} "
        f"--host {fran_webapp_host()} --port {fran_webapp_port()}"
    )


def _usage() -> int:
    print(
        "usage: python -m agent.control_plane.address_resolver "
        "[jobs-url|uvicorn-app-dir|uvicorn-app|uvicorn-host|uvicorn-port|uvicorn-pattern]",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        return _usage()

    command = args[0]
    if command == "jobs-url":
        print(fran_jobs_page_url())
        return 0
    if command == "uvicorn-app-dir":
        print(fran_webapp_app_dir())
        return 0
    if command == "uvicorn-app":
        print(fran_webapp_app())
        return 0
    if command == "uvicorn-host":
        print(fran_webapp_host())
        return 0
    if command == "uvicorn-port":
        print(fran_webapp_port())
        return 0
    if command == "uvicorn-pattern":
        print(fran_uvicorn_pattern())
        return 0
    return _usage()


if __name__ == "__main__":
    raise SystemExit(main())
