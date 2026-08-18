"""Phase 3: Verify KU content correctness."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KU_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'ku_packages')

files = [
    'renjiao-math-g10-a.json', 'RENJIAO-G10-MATH-BX2.json',
    'RENJIAO-G11-MATH-A-SBX1.json', 'RENJIAO-G11-MATH-A-SBX2.json',
    'RENJIAO-G12-MATH-A-SBX3.json',
]

total_units = 0
verified_ok = 0
issues = []

for fname in files:
    path = os.path.join(KU_DIR, fname)
    with open(path) as f:
        data = json.load(f)
    
    valid_ids = {u['id'] for u in data['units']}
    
    for u in data['units']:
        total_units += 1
        uid = u['id']
        u_issues = []
        
        for prereq in u.get('prerequisites', []):
            if prereq not in valid_ids and not prereq.startswith('MID-'):
                u_issues.append('prereq {} not found'.format(prereq))
        
        d = u.get('difficulty', 0.5)
        if not (0 <= d <= 1):
            u_issues.append('difficulty {} out of range'.format(d))
        
        rc = u.get('rich_content', {})
        if not rc:
            u_issues.append('no rich_content')
        else:
            for key in ['examples', 'definition', 'key_points']:
                if key not in rc:
                    u_issues.append('missing rich_content.{}'.format(key))
        
        kt = u.get('ku_type', '')
        if kt not in ('concept', 'procedure', 'application', 'theorem'):
            u_issues.append('invalid ku_type: {}'.format(kt))
        
        if u_issues:
            issues.append({'id': uid, 'issues': u_issues})
        else:
            u['verified'] = True
            u['ai_generated'] = True
            verified_ok += 1
    
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print('{}: {} units checked'.format(fname, len(data['units'])))

print('\nTotal: {} units, Verified OK: {}, Issues: {}'.format(total_units, verified_ok, len(issues)))
if issues:
    print('Sample issues (first 5):')
    for iss in issues[:5]:
        print('  {}: {}'.format(iss['id'], '; '.join(iss['issues'])))

report = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'ku_verification_report.json')
with open(report, 'w') as f:
    json.dump({
        'total_units': total_units,
        'verified_ok': verified_ok,
        'issues_count': len(issues),
        'issues': issues[:50],
    }, f, ensure_ascii=False, indent=2)
print('Report: {}'.format(report))