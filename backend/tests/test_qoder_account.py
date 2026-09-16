from app.adapters.qoder.account import normalize_usage


def test_normalize_usage_plan_remaining():
    data = normalize_usage(
        {
            "userId": "user@example.com",
            "userType": "pro",
            "userQuota": {"used": 10, "total": 100, "remaining": 90, "unit": "credits"},
            "expiresAt": 1710000000,
        }
    )
    assert data["account"]["id"] == "user@example.com"
    assert data["quota"]["exceeded"] is False
    assert data["quota"]["plan"]["remaining"] == 90
    assert "套餐内" in data["quota"]["text"]


def test_normalize_usage_all_buckets_empty_is_exceeded():
    data = normalize_usage(
        {
            "userQuota": {"used": 10, "total": 10, "remaining": 0},
            "addOnQuota": {"used": 1, "total": 1, "remaining": 0},
        }
    )
    assert data["quota"]["exceeded"] is True
