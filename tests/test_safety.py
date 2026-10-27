from xbot.safety import flags
def test_adult_spam_flags():
    assert flags({"text": "AI is collecting all our jobs\n\nBlowjobs:\nhttps://t.co/x"}) == ["adult"]
    assert "adult" in flags({"text": "Chudai \U0001F4A6 Create your perfect Ai girlfriend. Click here \U0001F447 https://t.co/a",
                             "xlabels": {"links": ["ourdream.ai"]}})
    assert flags({"text": "nice", "xlabels": {"links": ["ourdream.ai"]}}) == ["adult"]
    assert flags({"text": "ok", "possibly_sensitive": True}) == ["x-flags"]
    assert flags({"text": "Join my telegram for signals"}) == ["spam"]
def test_clean_and_no_false_hits():
    assert flags({"text": "Rust 2.0 ships async closures"}) == []
    assert flags({"text": "Essex devs meetup on Linux"}) == []
    assert flags({"text": "Jensen on raising kids in the age of AI"}) == []


def test_x_flags_editable():
    from xbot.safety import detail, set_topic_edits
    p = {"text": "ok", "possibly_sensitive": True}
    assert detail(p, ("adult", "x-flags")) == ['x-flags ("possibly_sensitive": marked sensitive by X)']
    assert detail(p, ("adult",)) == []
    set_topic_edits({"x-flags": {"add": [], "remove": ["possibly_sensitive"]}})
    assert flags(p) == []
    assert flags({"text": "ok", "withheld": {"country_codes": ["DE"]}}) == ["x-flags"]
    set_topic_edits({})
