"""Which deployment environments count as production.

The classification is an allow-list of non-production names, and everything
else is production. The previous rule was `environment != "production"`, which
put `prod`, `Production` and every typo on the open side of the gate.

Matching is exact on purpose. Normalising case or whitespace would be friendlier
and every normalisation is one more way for an unexpected value to land on the
open side; `Local` reaching production's closed side costs one log line.
"""

import pytest

from app.core.config import NON_PRODUCTION_ENVIRONMENTS, is_production


@pytest.mark.parametrize("environment", ["local", "test", "ci"])
def test_the_allow_listed_names_are_not_production(environment: str):
    assert is_production(environment) is False


@pytest.mark.parametrize(
    "environment",
    [
        "production",
        "prod",
        "Production",
        "PRODUCTION",
        "staging",
        "development",
        "Local",
        "LOCAL",
        "",
        " local",
        "local ",
        "local\n",
    ],
)
def test_everything_else_is_production(environment: str):
    assert is_production(environment) is True


def test_the_allow_list_is_exactly_the_three_documented_names():
    """A name added here opens the write endpoints wherever it is used.

    Pinning the set makes that a deliberate, reviewed edit rather than a
    convenience someone slips in to make a local setup work.
    """
    assert NON_PRODUCTION_ENVIRONMENTS == frozenset({"local", "test", "ci"})
