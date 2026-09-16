import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROOT_ENV = "HERMES_AGENT_PROVIDER_ROOT"


@pytest.fixture
def hermes_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    cfg.joinpath("default.yaml").write_text(
        "server:\n  host: 127.0.0.1\n  port: 8765\n"
        "engines:\n  default: qoder\n  models:\n    qoder: qmodel_38max\n    cursor: grok-4.6\n"
        "paths:\n  workspace: data/workspace\n"
        "auth:\n  users:\n    - { username: admin, role: admin }\n",
        encoding="utf-8",
    )
    cfg.joinpath("secrets.env").write_text(
        "PROXY_API_KEY=test-proxy-key\nSESSION_SECRET=test-session\nSETTINGS_PASSWORD=admin\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ROOT_ENV, str(tmp_path))
    monkeypatch.delenv("PROXY_API_KEY", raising=False)
    return tmp_path
