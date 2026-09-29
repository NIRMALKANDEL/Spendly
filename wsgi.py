"""WSGI entry point: `gunicorn wsgi:app` (Render) or import `app` (PythonAnywhere)."""

from app import create_app

app = create_app()
