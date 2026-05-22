"""测试 quality.py 的清洗模式。"""

from kafed.server.quality import clean_text


def test_clean_html_br():
    assert clean_text("hello<br>world") == "hello world"


def test_clean_html_tags():
    result = clean_text("<b>bold</b> text <i>italic</i>")
    assert "bold" in result
    assert "<b>" not in result
    assert "<i>" not in result


def test_clean_registered_trademark():
    result = clean_text("Some |®| text with [®] symbols")
    assert "®" not in result


def test_clean_bracketed_single_words():
    result = clean_text("[The] quick [brown] fox")
    assert "The quick brown fox" in result


def test_clean_figure_refs():
    result = clean_text("See Figure[5.1] for details")
    assert "5.1" in result
    assert "[" not in result


def test_clean_multi_newline():
    result = clean_text("a\n\n\n\n\nb")
    assert result == "a\n\nb"


def test_ligature_fixes():
    # \ufb00=ff, \ufb01=fi, \ufb02=fl, \ufb03=ffi, \ufb04=ffl
    result = clean_text("\ufb00\ufb01\ufb02\ufb03\ufb04")
    # Each ligature is replaced independently
    assert "ff" in result  # \ufb00
    assert "fi" in result  # \ufb01
    assert "fl" in result  # \ufb02
    assert "ffi" in result  # \ufb03
    assert "ffl" in result  # \ufb04


def test_clean_noise_general():
    """集成测试：模拟 PM 书中的噪声文本。"""
    noisy = (
        "# Page 1\n"
        "Copyright 2024 SAP AG. All rights reserved.\n"
        "Printed in Germany.\n"
        "<br>Notification Type M1<br>\n"
        "[The] quick [brown] fox\n"
        "Page 5\n"
        "|®| table artifact\n"
        "\n\n\n\n"
    )
    result = clean_text(noisy)
    assert "Copyright" not in result
    assert "All rights reserved" not in result
    assert "<br>" not in result
    assert "Notification Type M1" in result
    assert "[The]" not in result
    assert "|®|" not in result
    assert "\n\n\n\n" not in result
