"""Gunicorn production entry point."""
from orbitguard.api import create_app

app = create_app()
