from app.parser import parse_webhook


def _payload(message, *, from_me=False, jid="5511999999999@s.whatsapp.net", event="messages.upsert"):
    return {
        "event": event,
        "instance": "teste",
        "data": {
            "key": {"remoteJid": jid, "fromMe": from_me, "id": "ABC123"},
            "pushName": "Fulano",
            "message": message,
        },
    }


def test_parse_simple_text():
    messages = parse_webhook(_payload({"conversation": "Ola"}))
    assert len(messages) == 1
    msg = messages[0]
    assert msg.text == "Ola"
    assert msg.number == "5511999999999"
    assert msg.event_id == "teste:ABC123"
    assert not msg.is_group
    assert msg.from_me is False


def test_parse_extended_text_with_quote():
    payload = _payload({"extendedTextMessage": {"text": "Quanto custa?"}})
    assert parse_webhook(payload)[0].text == "Quanto custa?"


def test_parse_image_with_caption_and_media():
    payload = _payload(
        {
            "imageMessage": {
                "caption": "Veja isso",
                "mimetype": "image/jpeg",
                "base64": "aGVsbG8=",
            }
        }
    )
    msg = parse_webhook(payload)[0]
    assert msg.text == "Veja isso"
    assert msg.media[0].kind == "image"
    assert msg.media[0].mime == "image/jpeg"
    assert msg.media[0].base64_data == "aGVsbG8="


def test_parse_ephemeral_message():
    payload = _payload({"ephemeralMessage": {"message": {"conversation": "sumiu"}}})
    assert parse_webhook(payload)[0].text == "sumiu"


def test_parse_group():
    payload = _payload({"conversation": "oi grupo"}, jid="12345@g.us")
    msg = parse_webhook(payload)[0]
    assert msg.is_group
    assert msg.number == "12345@g.us"


def test_ignore_non_message_event():
    assert parse_webhook({"event": "connection.update", "data": {}}) == []


def test_ignore_broadcast_and_status():
    assert parse_webhook(_payload({"conversation": "x"}, jid="status@broadcast")) == []
    assert parse_webhook(_payload({"conversation": "x"}, jid="1@broadcast")) == []


def test_from_me_flag():
    msg = parse_webhook(_payload({"conversation": "eu"}, from_me=True))[0]
    assert msg.from_me is True


def test_list_of_data_items():
    payload = _payload({"conversation": "primeira"})
    second = {
        "key": {"remoteJid": "5511888888888@s.whatsapp.net", "fromMe": False, "id": "DEF"},
        "message": {"conversation": "segunda"},
    }
    payload["data"] = [payload["data"], second]
    messages = parse_webhook(payload)
    assert [m.text for m in messages] == ["primeira", "segunda"]
