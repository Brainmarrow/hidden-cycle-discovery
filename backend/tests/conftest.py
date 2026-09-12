"""Pytest fixtures shared across tests."""
import os
import sys

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use CPU for tests
os.environ.setdefault("DEVICE", "cpu")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
