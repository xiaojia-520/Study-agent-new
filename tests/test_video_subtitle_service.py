from src.application.video.subtitle_service import funasr_result_to_segments
from src.infrastructure.audio import subtitle_segments_to_srt


def test_funasr_character_timestamps_are_merged_into_subtitle_segment():
    result = {
        "text": "开 放 时 间 早 上 九 点 至 下 午 五 点",
        "timestamp": [
            [710, 950],
            [990, 1230],
            [1250, 1450],
            [1450, 1690],
            [1850, 2090],
            [2110, 2350],
            [2550, 2790],
            [2810, 3050],
            [3270, 3510],
            [3870, 4110],
            [4230, 4470],
            [4490, 4730],
            [4770, 5245],
        ],
    }

    segments = funasr_result_to_segments(result)

    assert len(segments) == 1
    assert segments[0].text == "开放时间早上九点至下午五点"
    assert segments[0].start_ms == 710
    assert segments[0].end_ms == 5245


def test_funasr_character_timestamps_split_when_subtitle_gets_too_long():
    result = {
        "text": "一 二 三 四 五 六 七 八 九 十",
        "timestamp": [
            [0, 100],
            [100, 200],
            [200, 300],
            [300, 400],
            [400, 500],
            [500, 600],
            [600, 700],
            [700, 800],
            [800, 900],
            [900, 1000],
        ],
    }

    segments = funasr_result_to_segments(result, max_chars=4)

    assert [segment.text for segment in segments] == ["一二三四", "五六七八", "九十"]
    assert [(segment.start_ms, segment.end_ms) for segment in segments] == [
        (0, 400),
        (400, 800),
        (800, 1000),
    ]


def test_sentence_info_is_used_when_available():
    result = {
        "text": "ignored",
        "timestamp": [[0, 100]],
        "sentence_info": [
            {"text": "第一句。", "start": 100, "end": 1200},
            {"text": "第二句。", "start": 1300, "end": 2200},
        ],
    }

    segments = funasr_result_to_segments(result)

    assert [segment.text for segment in segments] == ["第一句。", "第二句。"]
    assert [(segment.start_ms, segment.end_ms) for segment in segments] == [
        (100, 1200),
        (1300, 2200),
    ]


def test_subtitle_segments_to_srt_uses_srt_time_format():
    srt = subtitle_segments_to_srt(
        [
            {"start_ms": 710, "end_ms": 5245, "text": "开放时间"},
        ]
    )

    assert srt == "1\n00:00:00,710 --> 00:00:05,245\n开放时间\n"
