"""Read-only sanitized THEIA transport history. Never emits prompts/UI text."""
import collections
import json
import sqlite3
import sys


def diagnose(path):
    db = sqlite3.connect('file:' + path.replace('\\', '/') + '?mode=ro', uri=True)
    counts = collections.Counter()
    examples = []
    allowed = {'status', 'code', 'phase', 'request_id', 'native_call_cancelled',
               'transport_quarantined', 'worker_restarted', 'stale_responses_discarded',
               'generation', 'pending', 'superseded', 'response_drained'}
    def visit(value, found):
        if isinstance(value, dict):
            code = value.get('code')
            if isinstance(code, str) and code.startswith('worker_'):
                counts[code] += 1
                found.append({k:v for k,v in value.items() if k in allowed})
            for item in value.values():
                visit(item, found)
        elif isinstance(value, list):
            for item in value:
                visit(item, found)
    for row in db.execute("SELECT id, timestamp, content FROM messages WHERE role='tool' AND (content LIKE '%worker_transport_%' OR content LIKE '%worker_admission_timeout%') ORDER BY id"):
        try:
            value = json.loads(row[2])
        except (ValueError, TypeError):
            continue
        found=[]
        visit(value, found)
        if found and len(examples)<30:
            examples.append({'message_id':row[0], 'timestamp':row[1], 'transport':found})
    db.close()
    return {'source':'default-profile state.db tool results only', 'counts':dict(counts), 'examples':examples,
            'privacy':'Only whitelisted transport telemetry; no task text, targets, window titles, paths or pixels.'}


if __name__ == '__main__':
    print(json.dumps(diagnose(sys.argv[1]), indent=2))
