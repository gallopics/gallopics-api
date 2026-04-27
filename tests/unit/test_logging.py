import structlog

from app.middleware.logging import setup_logging


def test_setup_logging_debug():
    setup_logging(debug=True)
    config = structlog.get_config()
    renderer = config["processors"][-1]
    assert isinstance(renderer, structlog.dev.ConsoleRenderer)


def test_setup_logging_production():
    setup_logging(debug=False)
    config = structlog.get_config()
    renderer = config["processors"][-1]
    assert isinstance(renderer, structlog.processors.JSONRenderer)
