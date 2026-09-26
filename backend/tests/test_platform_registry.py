from services.platform_registry import normalize_platform


def test_x_display_names_normalize_to_twitter_slug():
    assert normalize_platform("twitter") == "twitter"
    assert normalize_platform("X") == "twitter"
    assert normalize_platform("X (Twitter)") == "twitter"
    assert normalize_platform("Twitter/X") == "twitter"
