__all__ = [
    "datasource_ready",
    "local_job_crash_packet",
    "local_job_list",
    "local_job_status",
    "project_ready",
    "train_retry_local",
]


def __getattr__(name: str):
    if name in __all__:
        from agent.control_plane import service

        return service.__dict__[name]
    raise AttributeError(name)
