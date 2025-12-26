from better_debug.gui import _extract_tag


def test_extract_tag_simple():
    assert _extract_tag("[debug]cmd") == "debug"


def test_extract_tag_with_timestamp_prefix():
    assert _extract_tag("[00:11:22][debug]usercmd") == "debug"


def test_extract_tag_only_timestamp_returns_none():
    assert _extract_tag("[00:11:22]hello") is None


def test_extract_tag_requires_ascii_letter_first_char():
    assert _extract_tag("[00:11:22][123]usercmd") is None
    assert _extract_tag("[00:11:22][_debug]usercmd") is None
    assert _extract_tag("[00:11:22][debug1]usercmd") == "debug1"
