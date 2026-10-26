from ticket_agent.ecommerce.subtitles import build_storyboard_webvtt


def test_storyboard_webvtt_uses_scene_timeline() -> None:
    data, cue_count = build_storyboard_webvtt(
        [
            (3.0, "先看关键卖点"),
            (5.0, "桌面护眼阅读灯 & 无级调光"),
            (7.0, "点击查看详情"),
        ]
    )

    text = data.decode("utf-8")
    assert cue_count == 3
    assert text.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:03.000" in text
    assert "00:00:03.000 --> 00:00:08.000" in text
    assert "00:00:08.000 --> 00:00:15.000" in text
    assert "桌面护眼阅读灯 &amp; 无级调光" in text
