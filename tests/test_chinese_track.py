"""L4 语文双轨分类(纯函数)：记诵轨 FSRS / 素养轨 策略。"""

from oprim.chinese_track import chinese_track, is_fsrs_eligible


def test_recite_track_types():
    for t in ("wenyan_word", "chengyu", "zixing_ziyin", "mingju", "wenhua_changshi"):
        assert chinese_track(t) == "recite"
        assert is_fsrs_eligible(t) is True


def test_literacy_track_types():
    for t in (
        "xiezuo",
        "shici_jianshang",
        "jixuwen_yuedu",
        "xiaoshuo_yuedu",
        "xinxi_yuedu",
    ):
        assert chinese_track(t) == "literacy"
        assert is_fsrs_eligible(t) is False


def test_unknown_reading_writing_falls_to_literacy():
    assert chinese_track("some_yuedu_new") == "literacy"
    assert chinese_track("xiezuo_gaoji") == "literacy"


def test_unknown_default_recite():
    assert chinese_track("mystery") == "recite"
    assert chinese_track(None) == "recite"
