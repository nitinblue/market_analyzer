import urllib.request
import urllib.error
import json
import sys

def call_tool(tool, arguments={}, timeout=120):
    url = 'http://localhost:8080/api/chat/tool'
    data = json.dumps({'tool': tool, 'arguments': arguments}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {'error': f'HTTP {e.code}', 'body': e.read().decode()[:500]}
    except Exception as e:
        return {'error': str(e)}

tools = sys.argv[1:]
timeout = 120
for t in tools:
    parts = t.split('=', 1)
    tool_name = parts[0]
    args = {}
    if len(parts) > 1:
        args = {'id': parts[1]}
    print(f'=== {tool_name} (args={args}) ===')
    r = call_tool(tool_name, args, timeout=timeout)
    print(json.dumps(r, indent=2)[:4000])
    print()
