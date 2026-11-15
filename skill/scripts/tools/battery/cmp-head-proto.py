# HEAD の report.mjs と候補版の出力を行単位で比べる。向き変え回数以外が動いていないかも見る。
import json,os,pathlib,subprocess,sys,tempfile
from collections import Counter
import _inputs as IN

if len(sys.argv)<3: raise SystemExit('使い方: python3 skill/scripts/tools/battery/cmp-head-proto.py <旧 report.mjs> <新 report.mjs>')
OLD=str(IN.require_script(sys.argv[1])); NEW=str(IN.require_script(sys.argv[2]))
REPO=IN.repo_root()
BASE=IN.resolve_cli_path(os.environ.get('CGD_AUDIT_BASE'),
                         default='skill/scripts/tools/battery/baseline-v1')
BUCKETS=['external.in','external.out','entries.in','entries.out','artifacts.in','artifacts.out','sameApi','siblingEndpoints','wiring']
FIELDS=('bucket','direction','tier','hops','switches','evidence','path')
def rows_of(r):
    out={}
    for b in BUCKETS:
        part=r[b.split('.')[0]][b.split('.')[1]] if '.' in b else r[b]
        for x in part:
            out[x['id']]={'bucket':b,'direction':x['direction'],'tier':x['tier'],'hops':x['hops'],
                          'switches':x['switches'],'evidence':(x['evidence'] or {}).get('id'),
                          'path':'->'.join(x['path'])}
    return out
def run(script,args,out):
    p=subprocess.run(['node',script]+args+['--json',out],cwd=REPO,capture_output=True,text=True)
    if p.returncode!=0: raise SystemExit(f'{script} 失敗 {args}: {p.stderr[-400:]}')
    return json.loads(pathlib.Path(out).read_text())
field=Counter(); percond=[]; sw2=Counter()
with tempfile.TemporaryDirectory() as td:
    REPORTS=IN.report_paths(BASE, expect=18, what='v1 基準の 18 条件')
    for p in REPORTS:
        doc=json.loads(p.read_text()); s=doc['summary']
        args=['--graph',str(IN.graph_path(s['graph'])),'--hops',str(s['hops']),'--wiring-hops',str(s['wiringHops']),
              '--limit',str(s.get('limit') or 100000)]
        for item in doc['starts']: args+=['--from',item['id']]
        a=run(OLD,args,td+'/a.json'); b=run(NEW,args,td+'/b.json')
        ra,rb=rows_of(a),rows_of(b)
        for x in list(ra.values())+list(rb.values()):
            if x['switches']>=2: sw2[p.name]+=1
        n=0
        for k in sorted(set(ra)|set(rb)):
            if ra.get(k)!=rb.get(k):
                n+=1
                if k in ra and k in rb:
                    for f in FIELDS:
                        if ra[k][f]!=rb[k][f]: field[f]+=1
                else: field['行の増減']+=1
        if n: percond.append((p.name,n))
        for k in ('secondOrder','externalCount','primaryCount'):
            if a['summary'].get(k)!=b['summary'].get(k): field['summary.'+k]+=1
print('条件数',len(REPORTS),' 差分のある条件',len(percond))
for name,n in percond: print(' -',name,'差分',n,'行')
print('動いた項目',dict(field))
print('switches>=2 の行',dict(sw2))

# 差分があれば終了 1（読み手で合否を決めさせない。第 51 ラウンド双人レビューの系統）。
# 第 52 ラウンド Codex P2: 行の差分 `percond` だけ見ていたため、`summary.primaryCount` を
# 18 条件すべてで変えた負の対照が「動いた項目 {\'summary.primaryCount\': 18}」で終了 0 だった。
# 集計の差分も終了判定に入れる
sys.exit(1 if (percond or field) else 0)
