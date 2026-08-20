"""Azure Functions application entry point."""

from intake_workers.function_app import app, configure_hosts
from intake_workers.runtime import worker_hosts_from_environment

configure_hosts(worker_hosts_from_environment)

__all__ = ["app"]
