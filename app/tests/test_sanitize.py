from app.ai.sanitize import has_tool_markup, strip_tool_markup

FW = "\uff5c"
SAMPLE = (
    f"<{FW}DSML{FW} calls>\n"
    f'<{FW}DSML{FW} invoke name="bash">\n'
    f'<{FW}DSML{FW} parameter name="command" string="true">'
    f'curl -s "https://wttr.in/Belo+Horizonte"</{FW}DSML{FW} parameter>\n'
    f"</{FW}DSML{FW} invoke>\n"
    f"</{FW}DSML{FW} calls>"
)


def test_detects_dsml_sample():
    assert has_tool_markup(SAMPLE) is True


def test_removes_dsml_only_response():
    assert strip_tool_markup(SAMPLE) == ""


def test_keeps_text_around_dsml():
    text = f"Segundo a busca, a cotacao e R$ 5,40.\n{SAMPLE}"
    assert strip_tool_markup(text) == "Segundo a busca, a cotacao e R$ 5,40."


def test_removes_ascii_tool_marker():
    text = 'Clima: <|DSML| invoke name="bash">curl x</|DSML| invoke>'
    assert strip_tool_markup(text) == "Clima:"


def test_normal_text_is_untouched():
    text = "Ola! Tudo bem? A cotacao do dolar hoje e R$ 5,40."
    assert has_tool_markup(text) is False
    assert strip_tool_markup(text) == text
