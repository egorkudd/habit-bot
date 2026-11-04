"""Живые проверки внешних сервисов: запускаются только в отдельном задании CI (LIVE_SERVICES=1)."""

import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(reason="живые сервисы проверяются только в задании «Внешние сервисы» (LIVE_SERVICES=1)")
    for item in items:
        if "/live/" in str(item.fspath):
            item.add_marker(pytest.mark.live)
            if os.environ.get("LIVE_SERVICES") != "1":
                item.add_marker(skip)
