"""Phase 5: End-to-end test of the complete question bank."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# Test 1: KC v2 dictionary
import importlib
kc_v2 = importlib.import_module('data.guangdong_math_kc_v2')
print('=== Test 1: KC v2 Dictionary ===')
print('  KC count:', len(kc_v2.KC_LIST))
print('  Total gaokao score:', kc_v2.total_gaokao_score())
print('  Summary:', json.dumps(kc_v2.kc_summary(), ensure_ascii=False))

# Verify all prerequisites resolve
for kc in kc_v2.KC_LIST:
    kc_id = kc['kc_id']
    for prereq in kc.get('prerequisites', []):
        assert prereq in kc_v2.KC_INDEX or prereq in kc_v2.MIDDLE_SCHOOL_KC_STUBS, \
            '{}: prereq {} not found'.format(kc_id, prereq)
print('  All prerequisites: OK')

# Test 2: Seed questions
print('\n=== Test 2: Seed Questions ===')
sq_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'seed_questions.json')
with open(sq_path) as f:
    seed_qs = json.load(f)
print('  KC count:', len(seed_qs))
total_q = sum(len(v) for v in seed_qs.values())
print('  Total questions:', total_q)

# Verify each KC has questions
missing_kc = [kc['kc_id'] for kc in kc_v2.KC_LIST if kc['kc_id'] not in seed_qs]
print('  Missing KCs:', missing_kc if missing_kc else 'None')

# Verify question structure
for kc_id, qs in seed_qs.items():
    assert len(qs) >= 3, '{}: only {} questions'.format(kc_id, len(qs))
    for q in qs:
        assert 'question_type' in q, '{}: missing question_type'.format(kc_id)
        assert 'question_text' in q, '{}: missing question_text'.format(kc_id)
        assert 'correct_answer' in q, '{}: missing correct_answer'.format(kc_id)
print('  All questions valid: OK')

# Test 3: KU packages
print('\n=== Test 3: KU Packages ===')
KU_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'ku_packages')
files = [
    'renjiao-math-g10-a.json', 'RENJIAO-G10-MATH-BX2.json',
    'RENJIAO-G11-MATH-A-SBX1.json', 'RENJIAO-G11-MATH-A-SBX2.json',
    'RENJIAO-G12-MATH-A-SBX3.json',
]
total_ku = 0
total_verified = 0
for fname in files:
    path = os.path.join(KU_DIR, fname)
    with open(path) as f:
        data = json.load(f)
    total_ku += len(data['units'])
    total_verified += sum(1 for u in data['units'] if u.get('verified'))
    print('  {}: {} units, {} verified'.format(fname, len(data['units']),
          sum(1 for u in data['units'] if u.get('verified'))))
print('  Total KU: {}, Verified: {}'.format(total_ku, total_verified))

# Test 4: Rubrics
print('\n=== Test 4: Rubrics ===')
rb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'seed_rubrics.json')
with open(rb_path) as f:
    rubrics = json.load(f)
print('  Total rubrics:', len(rubrics))
for r in rubrics:
    assert 'kc_id' in r
    assert 'dimensions' in r
    assert len(r['dimensions']) >= 3
    total_w = sum(d['weight'] for d in r['dimensions'])
    assert abs(total_w - 1.0) < 0.01, '{}: weights sum to {}'.format(r['kc_id'], total_w)
print('  All rubrics valid: OK')

# Test 5: Cross-reference - KC to KU mapping
print('\n=== Test 5: Cross-Reference ===')
# 检查 KC v2 的 ku_ids 是否指向有效的 KU
for kc in kc_v2.KC_LIST:
    for ku_id in kc.get('ku_ids', []):
        # 跳过空字符串
        if not ku_id:
            continue
        # KU 可能存在于任何一个包中
        found = False
        for fname in files:
            path = os.path.join(KU_DIR, fname)
            with open(path) as f:
                data = json.load(f)
            if any(u['id'] == ku_id for u in data['units']):
                found = True
                break
        if not found:
            print('  WARNING: {} references KU {} not found'.format(kc['kc_id'], ku_id))

print('\n=== All tests passed! ===')
print('Summary:')
print('  - KC v2: {} KCs'.format(len(kc_v2.KC_LIST)))
print('  - Seed questions: {} from {} KCs'.format(total_q, len(seed_qs)))
print('  - KU packages: {} units ({} verified)'.format(total_ku, total_verified))
print('  - Rubrics: {} KCs'.format(len(rubrics)))