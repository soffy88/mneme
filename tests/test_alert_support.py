"""L6 家长端"监控→支持"：每类预警配支持动作+对话话术(对话时机)。"""

from services.alert_service import _ALERT_SUPPORT, _support_for
from services.models import AlertType


def test_all_five_alert_types_have_support_scripts():
    for at in AlertType:
        assert at.value in _ALERT_SUPPORT, f"预警 {at.value} 缺支持话术"
        sup = _ALERT_SUPPORT[at.value]
        assert sup["support_action"] and sup["conversation_script"]


def test_support_for_returns_action_and_script():
    sup = _support_for(AlertType.task_missing)
    assert "support_action" in sup and "conversation_script" in sup
    assert "拆小" in sup["support_action"] or "阻力" in sup["support_action"]


def test_scripts_are_supportive_not_blaming():
    # 抽查：不含责备式措辞（"为什么不"/"又"），体现陪伴/过程归因
    for at in AlertType:
        script = _ALERT_SUPPORT[at.value]["conversation_script"]
        assert "为什么不" not in script


def test_unknown_type_falls_back_gracefully():
    sup = _support_for(None)
    assert sup["support_action"] and sup["conversation_script"]
