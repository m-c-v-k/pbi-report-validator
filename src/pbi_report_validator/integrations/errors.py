"""Exceptions shared by the modules in ``integrations`` that read inputs."""


class ProjectLoadError(Exception):
    """Base class for errors that prevent loading a project."""
