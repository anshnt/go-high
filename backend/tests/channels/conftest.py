import pytest


@pytest.fixture(autouse=True)
def clean():
    """Overrides the suite's database cleanup: nothing in this directory touches the database."""
    yield
