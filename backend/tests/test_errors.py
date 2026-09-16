from app.engine.errors import classify_engine_error, is_quota_error


def test_quota_markers():
    assert is_quota_error("insufficient_quota")
    assert is_quota_error("额度已用完")
    assert classify_engine_error("credits exhausted") == "quota"


def test_login_and_other_markers():
    assert classify_engine_error("not authenticated") == "login"
    assert classify_engine_error("unauthenticated") == "login"
    assert classify_engine_error("boom") == "engine"
