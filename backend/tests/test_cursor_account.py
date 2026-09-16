from app.adapters.cursor.account import normalize_usage, public_cursor_status


def test_normalize_usage_two_model_pools():
    data = normalize_usage(
        {"email": "dev@example.com", "name": "Dev"},
        {
            "membershipType": "pro",
            "individualUsage": {
                "plan": {"autoPercentUsed": 20, "apiPercentUsed": 100},
            },
        },
    )
    assert data["account"]["id"] == "dev@example.com"
    assert data["quota"]["exceeded"] is False
    assert "Cursor 模型" in data["quota"]["text"]
    assert "其他模型" in data["quota"]["text"]


def test_normalize_usage_both_pools_full():
    data = normalize_usage(
        {},
        {"individualUsage": {"plan": {"autoPercentUsed": 100, "apiPercentUsed": 100}}},
    )
    assert data["quota"]["exceeded"] is True


def test_public_cursor_status_is_not_placeholder(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.cursor.runner.describe_cursor",
        lambda: {
            "ok": False,
            "installed": True,
            "cli_present": True,
            "sdk_version": "1.0.0",
            "auth": "missing",
            "profile": None,
            "expires_at": "",
        },
    )
    data = public_cursor_status()
    assert data["engine"] == "cursor"
    assert data["fallback_reason"] != "not_implemented"
    assert "P3" not in (data.get("hint") or "")
    assert "P3" not in (data.get("auth_label") or "")
