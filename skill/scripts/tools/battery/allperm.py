#!/usr/bin/env python3
# 全縁順（n! 通り、最大 7 縁 = 5040 は多いので 6 縁まで）で表を比較し、割れる並びを列挙する
import json, subprocess, sys, itertools, tempfile, os, collections
script, graph_file = sys.argv[1], sys.argv[2]
extra = json.load(open(graph_file)).get('extra', [])
g = json.load(open(graph_file))['graph']
def run(edges):
    gg = dict(g); gg['edges'] = edges
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(gg, f); path = f.name
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        out = f.name
    p = subprocess.run(['node', script, '--graph', path, *extra, '--json', out],
                       capture_output=True, text=True)
    os.unlink(path)
    if p.returncode: return 'ERR ' + p.stderr[-200:]
    d = json.load(open(out)); os.unlink(out)
    rows = []
    for b in ['external','entries','artifacts']:
        for side in ['in','out']:
            for r in d[b][side]: rows.append(f"{r['id']}={r['bucket']}/{r['direction']}/h{r['hops']}/sw{r['switches']}/e{(r.get('evidence') or {}).get('id','-')}/mv{(r.get('movementEvidence') or {}).get('id','-')}")
    return '\n'.join(sorted(rows))
res = collections.OrderedDict()
for perm in itertools.permutations(range(len(g['edges']))):
    edges = [g['edges'][i] for i in perm]
    res[','.join('e%d' % i for i in perm)] = run(edges)
uniq = collections.defaultdict(list)
for k, v in res.items(): uniq[v].append(k)
print(f"縁順 {len(res)} 通り / 表 {len(uniq)} 通り")
for v, ks in uniq.items():
    print(f"-- {len(ks)} 通り（例: {ks[0]}）")
    for line in v.split('\n'): print('   ', line)
    if len(uniq) > 1: print('    ...')
