from app.utils import split_message


def test_split_short_message():
    assert split_message("oi", 100) == ["oi"]


def test_split_long_message_respects_limit():
    text = "frase curta. " * 50
    chunks = split_message(text, 60)
    assert len(chunks) > 1
    assert all(len(chunk) <= 60 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_split_empty_message():
    assert split_message("   ", 100) == []
