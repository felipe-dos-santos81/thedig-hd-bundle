from pathlib import Path
import pytest

BUNDLE = Path.home() / "Documents" / "The Dig®.app" / "Contents" / "Resources" / "game" / "game"
HAS_GAME = BUNDLE.is_dir()

def pytest_runtest_setup(item):
    if "game" in item.keywords and not HAS_GAME:
        pytest.skip("game bundle not found")

@pytest.fixture(scope="session")
def game_dir() -> Path:
    if not HAS_GAME:
        pytest.skip("game bundle not found")
    return BUNDLE
