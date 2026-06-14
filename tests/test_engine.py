"""
BKT + 认知状态 验证测试
=======================
用模拟答题序列验证：
1. 连续答对 → 掌握度单调上升并收敛到高位
2. 连续答错 → 掌握度下降
3. 高掌握后偶尔答错 → 判定为「粗心」；低掌握答错 → 判定「不会」
4. forgetting-aware：长时间不练，掌握度（effective）衰减
5. AUC：BKT 预测下一题对错的判别能力优于随机(0.5)
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from oprim import bkt
from obase.cognitive_store import InMemoryStore as CognitiveStore
from omodul.cognitive import process_interaction_workflow as process_interaction
from data.guangdong_math_kc import get_bkt_prior


def test_mastery_rises_on_correct():
    s = bkt.new_state_from_prior(kc_id="GDMATH-CONIC-01", prior=get_bkt_prior("GDMATH-CONIC-01"))
    seq = []
    for _ in range(8):
        bkt.bkt_update(state=s, is_correct=True)   # 无遗忘
        seq.append(round(s.current(), 3))
    assert seq == sorted(seq), f"应单调上升: {seq}"
    assert s.current() > 0.9, f"连续答对应收敛到高掌握: {s.current()}"
    print(f"  连续答对掌握度轨迹: {seq}  ✓")


def test_mastery_falls_on_wrong():
    s = bkt.new_state_from_prior(kc_id="GDMATH-SET-01", prior=get_bkt_prior("GDMATH-SET-01"))
    # 先拉高
    for _ in range(5):
        bkt.bkt_update(state=s, is_correct=True)
    high = s.current()
    for _ in range(5):
        bkt.bkt_update(state=s, is_correct=False)
    assert s.current() < high, f"连续答错应下降: {high}->{s.current()}"
    print(f"  高掌握({high:.3f}) 连续答错后降到 {s.current():.3f}  ✓")


def test_error_classification():
    # 高掌握 + 答错 → 粗心
    s = bkt.new_state_from_prior(kc_id="GDMATH-SET-01", prior=get_bkt_prior("GDMATH-SET-01"))
    for _ in range(8):
        bkt.bkt_update(state=s, is_correct=True)
    assert bkt.classify_error(state=s) == "careless", "高掌握答错应判粗心"
    print(f"  高掌握(P={s.current():.3f})答错 → {bkt.classify_error(state=s)}  ✓")

    # 低掌握 + 答错 → 不会
    s2 = bkt.new_state_from_prior(kc_id="GDMATH-DERIV-03", prior=get_bkt_prior("GDMATH-DERIV-03"))
    assert bkt.classify_error(state=s2) == "dontknow", "低掌握答错应判不会"
    print(f"  低掌握(P={s2.current():.3f})答错 → {bkt.classify_error(state=s2)}  ✓")


def test_forgetting():
    s = bkt.new_state_from_prior(kc_id="GDMATH-CONIC-01", prior=get_bkt_prior("GDMATH-CONIC-01"))
    for _ in range(8):
        bkt.bkt_update(state=s, is_correct=True)
    mastered = s.current()
    # 模拟 21 天不练后的「记得概率」（用内置指数遗忘 halflife=7d）
    R = bkt.exp_forgetting(days_since=21)
    effective = mastered * R
    assert effective < mastered, "长期不练 effective 掌握度应衰减"
    print(f"  学会后掌握={mastered:.3f}，21天未练 effective={effective:.3f} (R={R:.3f})  ✓")


def test_auc():
    """构造一批『真实掌握 vs 未掌握』的模拟学生，看 BKT 预测能否区分。"""
    import random
    random.seed(42)
    preds, labels = [], []
    for _ in range(300):
        true_mastered = random.random() < 0.5
        s = bkt.new_state_from_prior(kc_id="GDMATH-SEQ-01", prior=get_bkt_prior("GDMATH-SEQ-01"))
        # 喂 6 道历史题：掌握者多对，未掌握者多错
        for _ in range(6):
            obs = (random.random() < 0.85) if true_mastered else (random.random() < 0.25)
            bkt.bkt_update(state=s, is_correct=obs)
        # 预测第 7 题
        p = bkt.predict_correct(state=s)
        actual = (random.random() < 0.85) if true_mastered else (random.random() < 0.25)
        preds.append(p)
        labels.append(1 if actual else 0)
    auc = _auc(preds, labels)
    assert auc > 0.65, f"AUC 应明显优于随机: {auc}"
    print(f"  下一题正确率预测 AUC = {auc:.3f} (随机=0.5)  ✓")


def _auc(scores, labels):
    pos = [s for s, label in zip(scores, labels) if label == 1]
    neg = [s for s, label in zip(scores, labels) if label == 0]
    if not pos or not neg:
        return 0.5
    wins = sum(1 for p in pos for n in neg if p > n)
    ties = sum(1 for p in pos for n in neg if p == n)
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


@pytest.mark.asyncio
async def test_end_to_end_with_fsrs():
    """端到端：通过协调器跑一遍 KT+FSRS 统一流程。"""
    from omodul.cognitive import InteractionConfig, InteractionInput
    store = CognitiveStore()
    sid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    config = InteractionConfig()
    
    # 学生在椭圆上做错一道
    input1 = InteractionInput(student_id=sid, kc_id="GDMATH-CONIC-01", is_correct=False, struggled=True, now=now)
    res1 = await process_interaction(config, input1, store)
    r1 = res1["findings"]
    
    assert r1.error_type in ("careless", "dontknow")
    assert r1.next_review_due is not None
    
    # 第二天回顾答对
    input2 = InteractionInput(student_id=sid, kc_id="GDMATH-CONIC-01", is_correct=True, now=now + timedelta(days=1))
    res2 = await process_interaction(config, input2, store)
    r2 = res2["findings"]
    
    assert r2.p_mastery > r1.p_mastery, "回顾答对掌握度应上升"
    print(f"  端到端: 首次错(P={r1.p_mastery}, {r1.error_type}) "
          f"→ 次日对(P={r2.p_mastery}), 下次复习={r2.next_review_due[:10]}  ✓")


if __name__ == "__main__":
    print("=" * 60)
    print("BKT + 认知状态引擎 验证")
    print("=" * 60)
    for name, fn in [
        ("1. 连续答对掌握度上升", test_mastery_rises_on_correct),
        ("2. 连续答错掌握度下降", test_mastery_falls_on_wrong),
        ("3. 粗心 vs 不会 判定", test_error_classification),
        ("4. forgetting-aware 遗忘衰减", test_forgetting),
        ("5. AUC 预测判别力", test_auc),
        ("6. KT+FSRS 端到端", test_end_to_end_with_fsrs),
    ]:
        print(f"\n[{name}]")
        fn()
    print("\n" + "=" * 60)
    print("全部通过 ✓")
    print("=" * 60)
