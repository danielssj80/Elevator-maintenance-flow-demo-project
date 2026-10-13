"""Production exports traces only; metrics and logs can be switched off per signal.

Production sends OTLP straight to Grafana Cloud with no Collector to filter it,
and the free tier's series and log limits were sized for what the local
Collector selects. So the backend has to be able to stop producing a signal at
the source, while local keeps all three.

Each case runs in a fresh interpreter: the OpenTelemetry global providers can
be set once per process, and this suite's session already set them.
"""

import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

PROBE = textwrap.dedent(
    """
    import json, logging, os, sys
    from opentelemetry import metrics
    from opentelemetry._logs import get_logger_provider
    from opentelemetry.instrumentation.logging.handler import LoggingHandler
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk.metrics import MeterProvider

    import app.main  # configure_telemetry() runs at import time
    from app.core import telemetry as t

    print(json.dumps({
        "traces": t._tracer_provider is not None,
        "metrics": isinstance(metrics.get_meter_provider(), MeterProvider),
        "logs": isinstance(get_logger_provider(), LoggerProvider),
        "log_handler": any(
            isinstance(h, LoggingHandler) for h in logging.getLogger().handlers
        ),
        "console": any(
            type(h) is logging.StreamHandler for h in logging.getLogger().handlers
        ),
    }))
    sys.stdout.flush()
    # No shutdown: flushing to an endpoint nobody listens on only adds retries.
    os._exit(0)
    """
)


def _signals(**env_overrides: str) -> dict[str, bool]:
    env = {
        **os.environ,
        "OTEL_ENABLED": "true",
        # Nothing listens here; export failures are logged, never raised.
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9",
        "OTEL_BSP_SCHEDULE_DELAY": "60000",
        "OTEL_METRIC_EXPORT_INTERVAL": "600000",
    }
    env.pop("OTEL_METRICS_ENABLED", None)
    env.pop("OTEL_LOGS_ENABLED", None)
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        env=env,
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).parents[2],
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_all_three_signals_are_on_by_default():
    """Local is unchanged: the Collector selects what leaves the machine."""
    assert _signals() == {
        "traces": True,
        "metrics": True,
        "logs": True,
        "log_handler": True,
        "console": True,
    }


def test_production_shape_exports_traces_only():
    signals = _signals(OTEL_METRICS_ENABLED="false", OTEL_LOGS_ENABLED="false")

    assert signals["traces"] is True
    assert signals["metrics"] is False
    assert signals["logs"] is False
    assert signals["log_handler"] is False
    # Turning off log *export* must not turn off the log: stdout is what
    # `docker compose logs` reads when the exporter is what broke.
    assert signals["console"] is True


@pytest.mark.parametrize(
    ("switch", "off", "still_on"),
    [
        ("OTEL_METRICS_ENABLED", "metrics", "logs"),
        ("OTEL_LOGS_ENABLED", "logs", "metrics"),
    ],
)
def test_each_switch_turns_off_only_its_own_signal(switch, off, still_on):
    signals = _signals(**{switch: "false"})

    assert signals[off] is False
    assert signals[still_on] is True
    assert signals["traces"] is True
