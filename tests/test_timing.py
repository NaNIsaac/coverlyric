from coverlyric import timing

SRT = """1
00:00:03,000 --> 00:00:06,000
첫 번째 줄이에요

2
00:00:06,500 --> 00:00:09,000
<i>두 번째</i> 줄은
조금 길어요

3
00:00:12,000 --> 00:00:13,000
세 번째 줄
"""

VTT = """WEBVTT

intro
00:03.000 --> 00:06.000
첫 번째 줄이에요

00:06.500 --> 00:09.000
두 번째 줄
"""


def test_from_text_drops_section_tags_and_blank_lines():
    lines = timing.from_text("[Chorus]\n첫 줄\n\n  둘째 줄  \n(Verse 2)\n")
    assert lines == [(None, "첫 줄"), (None, "둘째 줄")]


def test_lrc_round_trip():
    lines = [(3.0, "첫 줄"), (6.25, ""), (61.5, "둘째 줄")]
    text = timing.to_lrc(lines, "제목", "가수")
    assert text.startswith("[ar:가수]\n[ti:제목]\n[00:03.00]첫 줄\n")
    assert timing.parse("x.lrc", text) == lines


def test_lrc_with_several_stamps_on_one_line():
    assert timing.parse_lrc("[00:01.00][00:05.50]후렴") == [(1.0, "후렴"), (5.5, "후렴")]


def test_srt_joins_cue_lines_strips_tags_and_marks_long_gaps():
    lines = timing.parse("a.srt", SRT)
    assert lines == [
        (3.0, "첫 번째 줄이에요"),
        (6.5, "두 번째 줄은 조금 길어요"),
        (9.0, ""),
        (12.0, "세 번째 줄"),
    ]


def test_vtt_with_cue_ids_and_short_stamps():
    assert timing.parse("a.vtt", VTT) == [(3.0, "첫 번째 줄이에요"), (6.5, "두 번째 줄")]


def test_pasted_srt_without_name_is_sniffed():
    assert timing.parse("answer", SRT)[0] == (3.0, "첫 번째 줄이에요")


def test_srt_export_ends_at_next_line_and_skips_gaps():
    text = timing.to_srt([(1.0, "a"), (2.5, ""), (4.0, "b")], duration=6.0)
    assert text == "1\n00:00:01,000 --> 00:00:02,500\na\n\n2\n00:00:04,000 --> 00:00:06,000\nb\n"


def test_check_marks_changed_and_extra_lines():
    own = ["첫 번째 줄이에요", "두 번째 줄", "세 번째 줄"]
    got = [(1.0, "첫번째 줄이에요!"), (2.0, "두 번 째 줄"), (3.0, "세 번재 줄"), (4.0, "")]
    assert timing.check(own, got) == [None, None, "세 번째 줄", None]
    extra = [(1.0, "첫 번째 줄이에요"), (2.0, "없는 줄"), (3.0, "두 번째 줄"), (4.0, "세 번째 줄")]
    assert timing.check(own, extra) == [None, "", None, None]


def test_ready_rejects_untimed_lines():
    try:
        timing.ready([(1.0, "a"), (None, "b")])
    except ValueError as e:
        assert "line 2" in str(e)
    else:
        raise AssertionError("an untimed line must stop the render")


def test_prompt_holds_the_lyrics_and_the_count():
    text = timing.ai_prompt(["가", "나", "다"], "노래")
    assert "SRT" in text and "3개" in text and text.rstrip().endswith("가\n나\n다")


SUNO = """[Intro]

[Verse 1 — Conversational, rhythmic]
창문을 열면 바람이 불어
# 여기는 2절 앞에 쉬는 곳
너의 이름을 불러 (echo)

[Instrumental — Wistful guitar solo]

[Chorus]
우리 다시 만나 [softly] 그 길에서
"""


def test_suno_tags_and_hash_lines_are_not_lyrics():
    assert timing.parse("lyrics.txt", SUNO) == [
        (None, "창문을 열면 바람이 불어"),
        (None, "너의 이름을 불러 (echo)"),
        (None, "우리 다시 만나 그 길에서"),
    ]


def test_tags_in_a_pasted_chat_answer_leave_a_gap():
    answer = (
        "1\n00:00:03,000 --> 00:00:06,000\n[Verse 1 — Conversational, rhythmic]\n창문을 열면\n\n"
        "2\n00:00:06,000 --> 00:00:09,000\n[Instrumental — Wistful guitar solo]\n"
    )
    assert timing.parse("answer.srt", answer) == [(3.0, "창문을 열면"), (6.0, "")]


def test_tags_in_lrc_lines():
    assert timing.parse("x.lrc", "[00:01.00][Chorus] 후렴\n[00:05.00]# 메모\n") == [
        (1.0, "후렴"),
        (5.0, ""),
    ]


def test_with_cleaning_off_the_lyrics_stay_as_typed():
    assert timing.parse("lyrics.txt", SUNO, clean=False) == [
        (None, "[Intro]"),
        (None, "[Verse 1 — Conversational, rhythmic]"),
        (None, "창문을 열면 바람이 불어"),
        (None, "# 여기는 2절 앞에 쉬는 곳"),
        (None, "너의 이름을 불러 (echo)"),
        (None, "[Instrumental — Wistful guitar solo]"),
        (None, "[Chorus]"),
        (None, "우리 다시 만나 [softly] 그 길에서"),
    ]
    answer = "1\n00:00:03,000 --> 00:00:06,000\n[Verse 1] 창문을 열면\n"
    assert timing.parse("answer.srt", answer, clean=False) == [(3.0, "[Verse 1] 창문을 열면")]
