# ランダムな小グラフで縁順により表示が変わるものを探す。HEAD 版で割れる例を取り出し、
# 回帰テストの材料にする（第 43 ラウンド双人レビュー指摘 1 の系譜を広く拾う）
import json,os,random,subprocess,sys,tempfile,pathlib
REPO=os.path.abspath('.')
if len(sys.argv)<2: print('使い方: python3 skill/scripts/tools/battery/find-splits.py <report.mjs> <試行> <種> <出力 json>'); raise SystemExit(1)
SCRIPT=sys.argv[1]
TRIALS=int(sys.argv[2]) if len(sys.argv)>2 else 250
SEED=int(sys.argv[3]) if len(sys.argv)>3 else 1
BUCKETS=['external.in','external.out','entries.in','entries.out','artifacts.in','artifacts.out','sameApi','siblingEndpoints','wiring']
KINDS=['calls','triggers','invokes','references','handler']
PROV=['static','static','static','llm','human','terraform']
def rows_of(r):
    out={}
    for b in BUCKETS:
        part=r[b.split('.')[0]][b.split('.')[1]] if '.' in b else r[b]
        for x in part:
            out[x['id']]=(b,x['direction'],x['tier'],x['hops'],x['switches'],(x['evidence'] or {}).get('id'),'->'.join(x['path']))
    return out
def run(g,td,name,extra):
    gp=pathlib.Path(td)/'g.json'; op=pathlib.Path(td)/'r.json'
    gp.write_text(json.dumps(g))
    p=subprocess.run(['node',SCRIPT,'--graph',str(gp)]+extra+['--json',str(op)],cwd=REPO,capture_output=True,text=True)
    if p.returncode!=0: return None
    return rows_of(json.loads(op.read_text()))
rng=random.Random(SEED)
splits=[]
with tempfile.TemporaryDirectory() as td:
    for t in range(TRIALS):
        n=rng.randint(5,9)
        nodes=[{'id':f'member:N{i}','kind':'member','name':f'N{i}','label':f'N{i}'} for i in range(n)]
        edges=[]
        for k in range(rng.randint(n, n+3)):
            a,b=rng.sample(range(n),2)
            edges.append({'id':f'e{k}','source':f'member:N{a}','target':f'member:N{b}','kind':rng.choice(KINDS),
                          'provenance':rng.choice(PROV),'metadata':{}})
        g={'nodes':nodes,'edges':edges}
        extra=['--from','member:N0','--hops',str(rng.randint(3,4))]
        a=run(g,td,'a',extra)
        if a is None: continue
        b=run({**g,'edges':list(reversed(edges))},td,'b',extra)
        if b is None: continue
        if a!=b:
            diff=[k for k in set(a)|set(b) if a.get(k)!=b.get(k)]
            splits.append({'trials':t,'graph':g,'extra':extra,'diff':sorted(diff),
                           'sample':{k:{'fwd':a.get(k),'rev':b.get(k)} for k in sorted(diff)[:3]}})
            if len(splits)>=6: break
print('入れ替えで割れた例', len(splits), '/ 試行', TRIALS, ' 版', SCRIPT)
if len(sys.argv)<5: print('出力先の json を 4 番目の引数で指定してください（前のラウンドの結果に上書き書き込みしない）'); raise SystemExit(1)
pathlib.Path(sys.argv[4]).write_text(json.dumps(splits,ensure_ascii=False,indent=1))
for s in splits[:3]:
    print('---', ' '.join(s['extra']), '差分', len(s['diff']), s['diff'][:4])
    for k,v in s['sample'].items(): print('   ',k,'\n      fwd',v['fwd'],'\n      rev',v['rev'])
