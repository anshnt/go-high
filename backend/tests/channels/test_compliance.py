from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from app import compliance
from app.compliance import Consent, Refusal, can_send, email_risk, keyword, phone_zones, quiet_until, sms_segments

NY = "America/New_York"


# keywords

@pytest.mark.parametrize("word", ["STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "REVOKE", "OPTOUT"])
def test_every_stop_keyword(word):
    assert keyword(word) == "stop" == keyword(word.lower()) == keyword(word.title())


@pytest.mark.parametrize("word", ["START", "YES", "UNSTOP"])
def test_every_start_keyword(word):
    assert keyword(word) == "start" == keyword(word.lower()) == keyword(word.title())


@pytest.mark.parametrize("word", ["HELP", "INFO"])
def test_every_help_keyword(word):
    assert keyword(word) == "help" == keyword(word.lower()) == keyword(word.title())


@pytest.mark.parametrize("body", ["  stop  ", "\nSTOP\n", "\tStop\r\n", "stop ", " UNSUBSCRIBE ", " sToP "])
def test_case_and_surrounding_whitespace_do_not_matter(body):
    assert keyword(body) == "stop"


@pytest.mark.parametrize("body", [
    "", "   ", "\n", "hello", "please stop", "stop please", "STOP texting me", "I said STOP",
    "stop stop", "STOP ALL", "st op", "s​top", "stopped", "stops", "yes please", "yes yes", "no", "helpme",
    "information", "quit it", "end of story", "opt out", "opt-out", "un-subscribe",
    "STOP\nSTOP", "cancel my order", "STOPALLL"])
def test_only_a_message_that_is_the_keyword_counts(body):
    assert keyword(body) is None


@pytest.mark.parametrize("body, expected", [
    ("stop.", "stop"), ("STOP!", "stop"), ("Stop,", "stop"), ("‘STOP’", "stop"), ('"STOP"', "stop"),
    ("yes!", "start"), ("info?", "help"), ("...unsubscribe...", "stop")])
def test_surrounding_punctuation_is_ignored(body, expected):
    assert keyword(body) == expected


def test_the_keyword_lists_do_not_overlap():
    assert not (compliance.STOP & compliance.START or compliance.STOP & compliance.HELP
                or compliance.START & compliance.HELP)


# quiet hours

def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def local(*args, tz=NY) -> datetime:
    return datetime(*args, tzinfo=ZoneInfo(tz))


@pytest.mark.parametrize("now", [local(2026, 10, 17, 8, 0), local(2026, 10, 17, 12, 0), local(2026, 10, 17, 20, 59, 59),
                                 local(2026, 10, 17, 14, 30)])
def test_daytime_is_not_quiet(now):
    assert quiet_until(now, NY) is None


@pytest.mark.parametrize("now, expected", [
    (local(2026, 10, 17, 21, 0), local(2026, 10, 18, 8, 0)),  # the start is already quiet
    (local(2026, 10, 17, 23, 30), local(2026, 10, 18, 8, 0)),
    (local(2026, 10, 17, 23, 59, 59), local(2026, 10, 18, 8, 0)),
    (local(2026, 10, 18, 0, 0), local(2026, 10, 18, 8, 0)),  # after midnight it is today's morning
    (local(2026, 10, 18, 3, 15), local(2026, 10, 18, 8, 0)),
    (local(2026, 10, 18, 7, 59, 59), local(2026, 10, 18, 8, 0)),
    (local(2026, 12, 31, 22, 0), local(2027, 1, 1, 8, 0)),  # across a year end
    (local(2026, 2, 28, 22, 0), local(2026, 3, 1, 8, 0)),  # and a month end
])
def test_quiet_hours_end_at_the_next_morning(now, expected):
    got = quiet_until(now, NY)
    assert got == expected and got.utcoffset() == expected.utcoffset()
    assert got.tzinfo == ZoneInfo(NY)  # answered in the contact's zone


def test_the_input_may_be_in_any_zone_the_contact_zone_decides():
    now = utc(2026, 10, 18, 3, 30)  # 23:30 in New York, 12:30 in Tokyo, 03:30 UTC
    assert quiet_until(now, NY) == local(2026, 10, 18, 8, 0)
    assert quiet_until(now, "Asia/Tokyo") is None
    assert quiet_until(now, "UTC") == utc(2026, 10, 18, 8, 0)
    assert quiet_until(now.astimezone(ZoneInfo("Asia/Tokyo")), NY) == local(2026, 10, 18, 8, 0)
    assert quiet_until(now, ZoneInfo(NY)) == local(2026, 10, 18, 8, 0)  # a tzinfo works as well as a name


def test_spring_forward_the_night_is_an_hour_shorter():
    # New York skips 02:00-03:00 on 2026-03-08: 08:00 that day is EDT (12:00 UTC), not EST (13:00 UTC)
    # 22:00 EST, 01:30 EST and 07:59 EDT
    for now in (utc(2026, 3, 8, 3, 0), utc(2026, 3, 8, 6, 30), utc(2026, 3, 8, 11, 59)):
        assert quiet_until(now, NY) == utc(2026, 3, 8, 12, 0)
    evening_before = local(2026, 3, 7, 22, 0)
    got = quiet_until(evening_before, NY)
    assert got == utc(2026, 3, 8, 12, 0) and got.hour == 8 and got.utcoffset().total_seconds() == -4 * 3600
    assert quiet_until(utc(2026, 3, 8, 12, 0), NY) is None  # 08:00 EDT sharp: allowed


def test_fall_back_the_night_is_an_hour_longer():
    # New York repeats 01:00-02:00 on 2026-11-01: 08:00 that day is EST (13:00 UTC), not EDT (12:00 UTC)
    for now in (utc(2026, 11, 1, 1, 0), utc(2026, 11, 1, 4, 30), utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 6, 30),
                utc(2026, 11, 1, 12, 59)):  # 21:00 EDT, 00:30 EDT, 01:30 EDT, 01:30 EST, 07:59 EST
        assert quiet_until(now, NY) == utc(2026, 11, 1, 13, 0)
    got = quiet_until(local(2026, 10, 31, 21, 0), NY)
    assert got.hour == 8 and got.utcoffset().total_seconds() == -5 * 3600
    assert quiet_until(utc(2026, 11, 1, 13, 0), NY) is None  # 08:00 EST sharp: allowed


def test_the_repeated_hour_is_judged_by_the_instant_not_the_wall_clock():
    first = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo(NY), fold=0)  # EDT
    second = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo(NY), fold=1)  # EST
    assert quiet_until(first, NY) == quiet_until(second, NY) == utc(2026, 11, 1, 13, 0)
    # a window that ends inside the repeated hour opens at its first occurrence
    # (compared as UTC: Python never calls two zones' datetimes equal inside a repeated hour)
    assert quiet_until(utc(2026, 11, 1, 4, 10), NY, "23:00", "01:30").astimezone(UTC) == utc(2026, 11, 1, 5, 30)


def test_a_window_end_inside_the_skipped_hour_moves_forward_to_a_real_time():
    got = quiet_until(local(2026, 3, 8, 0, 30), NY, "23:00", "02:30")  # 02:30 never happens on 2026-03-08
    assert got == utc(2026, 3, 8, 7, 30) and (got.hour, got.minute) == (3, 30)


def test_a_zone_without_dst_and_a_half_hour_offset():
    kolkata = "Asia/Kolkata"  # UTC+05:30
    assert quiet_until(utc(2026, 10, 17, 15, 30), kolkata) == utc(2026, 10, 18, 2, 30)  # 21:00 IST -> 08:00 IST
    assert quiet_until(utc(2026, 10, 17, 15, 29), kolkata) is None


def test_southern_hemisphere_dst():
    sydney = "Australia/Sydney"  # DST starts 2026-10-04 at 02:00 (+10 -> +11)
    assert quiet_until(utc(2026, 10, 3, 14, 0), sydney) == utc(2026, 10, 3, 21, 0)  # 00:00 AEST -> 08:00 AEDT


def test_custom_and_non_wrapping_windows():
    assert quiet_until(local(2026, 10, 17, 22, 30), NY, "22:30", "07:15") == local(2026, 10, 18, 7, 15)
    assert quiet_until(local(2026, 10, 17, 22, 29), NY, "22:30", "07:15") is None
    assert quiet_until(local(2026, 10, 17, 13, 0), NY, "12:00", "14:00") == local(2026, 10, 17, 14, 0)
    assert quiet_until(local(2026, 10, 17, 11, 59), NY, "12:00", "14:00") is None
    assert quiet_until(local(2026, 10, 17, 14, 0), NY, "12:00", "14:00") is None
    assert quiet_until(local(2026, 10, 17, 23, 0), NY, "12:00", "14:00") is None


def test_equal_start_and_end_means_no_quiet_hours():
    assert quiet_until(local(2026, 10, 17, 3, 0), NY, "08:00", "08:00") is None


def test_quiet_until_needs_an_aware_time_and_a_real_zone():
    with pytest.raises(ValueError):
        quiet_until(datetime(2026, 10, 17, 23, 0), NY)
    with pytest.raises(ZoneInfoNotFoundError):
        quiet_until(utc(2026, 10, 17, 23, 0), "Mars/Olympus")
    with pytest.raises(ValueError):
        quiet_until(utc(2026, 10, 17, 23, 0), NY, "9pm", "8am")


# segments

GSM_ONLY = compliance.GSM_BASIC


def test_the_gsm_basic_table_has_127_characters_and_the_extension_table_ten():
    assert len(GSM_ONLY) == 127 == len(set(GSM_ONLY)) and len(compliance.GSM_EXTENSION) == 10
    assert not set(GSM_ONLY) & set(compliance.GSM_EXTENSION)


def test_empty_text_is_no_segments():
    assert sms_segments("") == ("gsm7", 0, 0)


@pytest.mark.parametrize("size, segments", [(1, 1), (159, 1), (160, 1), (161, 2), (306, 2), (307, 3), (459, 3),
                                            (460, 4)])
def test_gsm7_limits_are_160_then_153(size, segments):
    assert sms_segments("a" * size) == ("gsm7", segments, size)


def test_every_basic_character_costs_one_unit():
    assert sms_segments(GSM_ONLY) == ("gsm7", 1, 127)
    assert sms_segments("\n\r@$_ ") == ("gsm7", 1, 6)


@pytest.mark.parametrize("char", list("^{}\\[~]|€\f"))
def test_extension_characters_cost_two_units(char):
    assert sms_segments(char) == ("gsm7", 1, 2)
    assert sms_segments("a" * 158 + char) == ("gsm7", 1, 160)
    assert sms_segments("a" * 159 + char) == ("gsm7", 2, 161)


def test_extension_characters_at_the_160_boundary():
    assert sms_segments("{" * 80) == ("gsm7", 1, 160)
    assert sms_segments("{" * 81) == ("gsm7", 2, 162)
    assert sms_segments("€" * 76 + "a" * 8) == ("gsm7", 1, 160)
    assert sms_segments("Pay €5 {now}") == ("gsm7", 1, 15)


def test_an_escape_pair_is_never_split_across_segments():
    # 306 units would fit two segments of 153, but the "{" would have to straddle them: it moves to the next one
    assert sms_segments("a" * 152 + "{" + "a" * 152) == ("gsm7", 3, 306)
    assert sms_segments("a" * 152 + "{" + "a" * 150) == ("gsm7", 2, 304)
    assert sms_segments("a" * 151 + "{" + "a" * 153) == ("gsm7", 2, 306)


@pytest.mark.parametrize("text", ["ç", "á", "ê", "ô", "’", "“quoted”", "a–b", "wait…",
                                  "₹100", "你好", " ", "Çç", "café crème brûlée"])
def test_one_character_outside_the_gsm_tables_makes_the_whole_message_ucs2(text):
    assert sms_segments(text)[0] == "ucs2"


def test_characters_that_look_unusual_but_are_gsm():
    # these are in the basic table: accented capitals, a few lowercase accents, and the currency signs
    assert sms_segments("ÄÖÑÜäöñüàèéùìòÇÅåÆæßÉ") == ("gsm7", 1, 21)
    assert sms_segments("£¥$¤")[0] == "gsm7"


@pytest.mark.parametrize("size, segments", [(1, 1), (70, 1), (71, 2), (134, 2), (135, 3), (201, 3), (202, 4)])
def test_ucs2_limits_are_70_then_67(size, segments):
    assert sms_segments("ç" * size) == ("ucs2", segments, size)


def test_an_emoji_forces_ucs2_and_counts_two_units():
    assert sms_segments("\U0001f600") == ("ucs2", 1, 2)
    assert sms_segments("Hello \U0001f44b") == ("ucs2", 1, 8)  # six GSM characters become eight UCS-2 units
    assert sms_segments("a" * 159 + "\U0001f600") == ("ucs2", 3, 161)  # was one segment of 159 in GSM-7
    assert sms_segments("\U0001f600" * 35) == ("ucs2", 1, 70)
    assert sms_segments("\U0001f600" * 36) == ("ucs2", 2, 72)


def test_a_surrogate_pair_is_never_split_across_segments():
    assert sms_segments("ç" * 66 + "\U0001f600" + "ç" * 66) == ("ucs2", 3, 134)
    assert sms_segments("ç" * 66 + "\U0001f600" + "ç" * 3) == ("ucs2", 2, 71)


def test_the_euro_sign_is_gsm_but_the_rupee_sign_is_not():
    assert sms_segments("€")[0] == "gsm7" and sms_segments("₹")[0] == "ucs2"


# email risk

def codes(*args, **kwargs) -> list[str]:
    return [r.code for r in email_risk(*args, **kwargs)]


GOOD_HTML = '<p>Hi Sam</p><a href="https://example.com/invoice">View it</a><a href="https://example.com/u">Unsubscribe</a>'
GOOD_TEXT = "Hi Sam\nView it: https://example.com/invoice\nUnsubscribe: https://example.com/u"


def test_a_clean_message_has_no_warnings():
    assert email_risk("Your April invoice", GOOD_HTML, GOOD_TEXT, bulk=True) == []
    assert email_risk("Your April invoice", "", "Plain text only") == []
    assert email_risk("", "", "") == []


def test_html_without_a_text_part():
    assert codes("Hi", "<p>Hello</p>", "") == ["missing_text"]
    assert codes("Hi", "<p>Hello</p>", "  \n ") == ["missing_text"]
    assert codes("Hi", "", "text") == [] and codes("Hi", "   ", "") == []


@pytest.mark.parametrize("html, text, found", [
    ("<p>x</p>", "x", False), ("<a href='https://x.test/u'>Unsubscribe</a>", "x", True),
    ("<p>x</p>", "UNSUBSCRIBE: link", True),
    ("", "Click to unsubscribe", True), ("<p>un-subscribe</p>", "x", False), ("<p>subscribe</p>", "x", False)])
def test_bulk_mail_needs_an_unsubscribe_link(html, text, found):
    assert ("missing_unsubscribe" not in codes("Hi", html, text, bulk=True)) is found
    assert "missing_unsubscribe" not in codes("Hi", html, text)  # one-to-one mail does not


def links(n: int) -> str:
    return "".join(f'<a href="https://example.com/{i}">l{i}</a>' for i in range(n))


def test_too_many_links():
    assert "many_links" not in codes("Hi", links(10), "x")
    assert "many_links" in codes("Hi", links(11), "x")
    assert "many_links" in codes("Hi", links(11).replace('"', "'").upper(), "x")
    assert "many_links" in codes("Hi", "", " ".join(f"https://example.com/{i}" for i in range(11)))
    assert "many_links" not in codes("Hi", "", " ".join(f"https://example.com/{i}" for i in range(10)))
    assert "many_links" not in codes("Hi", "<p>" + "text " * 100 + "</p>", "x")


@pytest.mark.parametrize("subject, shouting", [
    ("URGENT: ACT NOW", True), ("FREE", True), ("50% OFF EVERYTHING", True), ("ÜBER", True), ("Free", False),
    ("Act now", False), ("Re: Q3", False), ("SMS", False), ("2026 AGM", False), ("", False),
    ("12345", False), ("Your ORDER has shipped", False), ("NASA update", False)])
def test_all_caps_subjects(subject, shouting):
    assert ("all_caps_subject" in codes(subject, "", "x")) is shouting


@pytest.mark.parametrize("url, short", [
    ("https://bit.ly/3abc", True), ("http://www.tinyurl.com/x", True), ("https://t.co/zzz", True),
    ("https://go.bit.ly/x", True), ("https://rebrand.ly/sale", True), ("https://BIT.LY/ABC", True),
    ("https://orbit.ly/x", False), ("https://example.com/?u=bit.ly", False), ("https://notbit.ly.example.com/", False),
    ("https://example.com/bit.ly", False), ("https://bitly.com/", False)])
def test_url_shorteners(url, short):
    assert ("url_shortener" in codes("Hi", f'<a href="{url}">go</a>', "x")) is short
    assert ("url_shortener" in codes("Hi", "", f"see {url} now")) is short


def test_shorteners_are_named_once_each_in_order():
    [risk] = [r for r in email_risk("Hi", '<a href="https://t.co/a">1</a><a href="https://bit.ly/b">2</a>'
                                    '<a href="https://t.co/c">3</a>', "x") if r.code == "url_shortener"]
    assert "bit.ly, t.co" in risk.message and risk.message.count("t.co") == 1


def test_several_warnings_come_back_together_in_a_stable_order():
    html = links(11) + '<a href="https://bit.ly/x">x</a>'
    assert codes("BUY NOW", html, "", bulk=True) == ["missing_text", "missing_unsubscribe", "many_links",
                                                    "all_caps_subject", "url_shortener"]
    risk = email_risk("Hi", "<p>x</p>", "")[0]
    assert risk.code == "missing_text" and risk.message and risk == ("missing_text", risk.message)


# can_send

DAY = datetime(2026, 10, 17, 19, 0, tzinfo=UTC)  # 12:00 in Los Angeles, 15:00 in New York
NIGHT = datetime(2026, 10, 17, 5, 0, tzinfo=UTC)  # 22:00 on the 16th in Los Angeles
LA = ("America/Los_Angeles",)


def opted(status: str, source: str = "stop") -> Consent:
    return Consent(status, source, datetime(2026, 10, 3, 12, 0, tzinfo=UTC))


def test_a_contact_nobody_has_restricted_may_be_messaged():
    assert can_send("sms", DAY, zones=LA) is None
    assert can_send("email", NIGHT) is None and can_send("webchat", NIGHT) is None


@pytest.mark.parametrize("source,who", [("stop", "STOP"), ("unsubscribe", "unsubscribe"),
                                        ("complaint", "a spam complaint"), ("manual", "staff"), ("other", "other")])
def test_an_opt_out_is_refused_with_who_and_when(source, who):
    refusal = can_send("sms", DAY, consent=opted("opted_out", source))
    assert refusal == Refusal("opted_out", f"Opted out by {who} on Oct 3")  # nothing to wait for


def test_do_not_disturb_is_refused_and_opted_in_is_allowed():
    assert can_send("sms", DAY, consent=opted("dnd", "manual")) == Refusal("dnd", "Do not disturb is on for sms")
    assert can_send("email", DAY, consent=opted("dnd", "manual")).reason == "Do not disturb is on for email"
    assert can_send("sms", DAY, consent=opted("opted_in", "start")) is None


def test_an_opt_out_wins_over_everything_else():
    refusal = can_send("sms", NIGHT, consent=opted("opted_out"), zones=LA, sent=99, cap=(1, 24))
    assert refusal.code == "opted_out"


def test_quiet_hours_wait_for_the_window_in_the_contacts_zone():
    refusal = can_send("sms", NIGHT, zones=LA)
    assert refusal.code == "quiet_hours" and refusal.retry_at == quiet_until(NIGHT, LA[0])
    assert refusal.retry_at == datetime(2026, 10, 17, 15, 0, tzinfo=UTC)  # 08:00 in Los Angeles
    assert "America/Los_Angeles" in refusal.reason and "08:00" in refusal.reason
    assert can_send("whatsapp", NIGHT, zones=LA).code == "quiet_hours"
    assert can_send("sms", NIGHT, zones=("Australia/Sydney",)) is None  # 16:00 there
    assert can_send("sms", DAY, zones=LA) is None


def test_quiet_hours_do_not_bind_email_or_chat_or_a_contact_who_just_wrote_or_unknown_zones():
    assert can_send("email", NIGHT, zones=LA) is None and can_send("webchat", NIGHT, zones=LA) is None
    assert can_send("sms", NIGHT, zones=LA, replying=True) is None
    assert can_send("sms", NIGHT) is None  # no zone known: nothing to check against
    assert can_send("sms", NIGHT, zones=("Not/AZone",)) is None  # a name that is not a zone counts as unknown


def test_quiet_hours_can_be_changed_or_switched_off():
    assert can_send("sms", NIGHT, zones=LA, quiet=("22:30", "23:30")) is None  # 22:00 is outside this window
    assert can_send("sms", NIGHT, zones=LA, quiet=("20:00", "23:00")).code == "quiet_hours"
    assert can_send("sms", NIGHT, zones=LA, quiet=("09:00", "09:00")) is None  # start == end: none


def test_when_the_zone_is_uncertain_any_zone_in_quiet_hours_waits_for_the_latest_end():
    at = datetime(2026, 10, 17, 14, 30, tzinfo=UTC)  # 07:30 in Los Angeles, 10:30 in New York
    refusal = can_send("sms", at, zones=("America/New_York", "America/Los_Angeles"))
    assert refusal.code == "quiet_hours" and refusal.retry_at == datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
    assert can_send("sms", at, zones=("America/New_York",)) is None


def test_the_frequency_cap_counts_what_was_sent_in_its_window():
    assert can_send("sms", DAY, sent=2, cap=(3, 24)) is None
    refusal = can_send("sms", DAY, sent=3, cap=(3, 24))
    assert refusal == Refusal("frequency_cap", "Frequency cap reached: 3 messages in 24 hours")
    assert can_send("sms", DAY, sent=999, cap=(0, 24)) is None and can_send("sms", DAY, sent=999) is None
    assert can_send("sms", NIGHT, zones=LA, replying=True, sent=3, cap=(3, 24)).code == "frequency_cap"


def test_quiet_hours_are_checked_before_the_cap():
    assert can_send("sms", NIGHT, zones=LA, sent=9, cap=(3, 24)).code == "quiet_hours"


@pytest.mark.parametrize("number,zone", [("+14155550123", "America/Los_Angeles"), ("+12125550123", "America/New_York"),
                                         ("+442071234567", "Europe/London"), ("+61412345678", "Australia/Sydney")])
def test_a_phone_number_gives_its_time_zones(number, zone):
    assert zone in phone_zones(number)


@pytest.mark.parametrize("number", ["", "nope", "+0", "12345", "+999999999999999"])
def test_a_number_that_cannot_be_placed_gives_no_zone(number):
    assert phone_zones(number) == ()


def test_the_reply_window_is_a_day():
    assert compliance.REPLY_WINDOW == timedelta(hours=24)
