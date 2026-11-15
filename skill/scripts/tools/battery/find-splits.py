# ランダムな小グラフで縁順により表示が変わるものを探す。HEAD 版で割れる例を取り出し、
# 回帰テストの材料にする（第 43 ラウンド双人レビュー指摘 1 の系譜を広く拾う）
import json,os,random,subprocess,sys,tempfile,pathlib
import _inputs as IN

USE = '使い方: python3 skill/scripts/tools/battery/find-splits.py <report.mjs> <試行> <種> <出力 json>'
# 引数の不足と対象の不在は**試行を回す前に**調べる（第 51 ラウンド双人レビュー agy P3。
# 250 試行を走らせてから出力先を要求していた）
if len(sys.argv) < 5: print(USE); raise SystemExit(1)
SCRIPT = str(IN.require_script(sys.argv[1]))
REPO = IN.repo_root()
TRIALS = int(sys.argv[2])
SEED = int(sys.argv[3])
OUT = IN.resolve_cli_path(sys.argv[4], default=None)
if TRIALS < 1: print('試行は 1 以上'); raise SystemExit(1)
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
    p=subprocess.run(['node',SCRIPT,'--graph',str(gp)]+extra+['--json',str(op)],cwd=str(REPO),capture_output=True,text=True)
    # 失敗を None（= その試行は無かった）にしない。全滅でも「割れた例 0」で通っていた
    # （第 51 ラウンド双人レビュー Codex P2）
    if p.returncode!=0:
        raise SystemExit(f'report.mjs 失敗 (exit {p.returncode}) 試行 {name}: {p.stderr[-800:]}')
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
        b=run({**g,'edges':list(reversed(edges))},td,'b',extra)
        if a!=b:
            diff=[k for k in set(a)|set(b) if a.get(k)!=b.get(k)]
            splits.append({'trials':t,'graph':g,'extra':extra,'diff':sorted(diff),
                           'sample':{k:{'fwd':a.get(k),'rev':b.get(k)} for k in sorted(diff)[:3]}})
            if len(splits)>=6: break
print('入れ替えで割れた例', len(splits), '/ 試行', TRIALS, ' 版', SCRIPT, ' 種', SEED)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(splits,ensure_ascii=False,indent=1))
print('割れた例の書き出し先:', OUT)
for s in splits[:3]:
    print('---', ' '.join(s['extra']), '差分', len(s['diff']), s['diff'][:4])
    for k,v in s['sample'].items(): print('   ',k,'\n      fwd',v['fwd'],'\n      rev',v['rev'])

# 割れた例が見つかったら終了 1（検査器は終了コードで合否を返す）
sys.exit(1 if splits else 0)
