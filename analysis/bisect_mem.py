import sys, os, shutil, json, glob
sys.path.insert(0,'.')
import repro_harness_user as rh

SRC_MEM="/tmp/memory.pristine"
FILES = sorted(glob.glob(SRC_MEM+"/*.loudstxt3"),
               key=lambda p: int(os.path.basename(p).replace("memory","").split(".")[0]))

def trial(keep, tag):
    """keep: set of indices to KEEP"""
    base=f"/tmp/hz-bisect"
    shutil.rmtree(base, ignore_errors=True)
    for d in ["run","config/hazkey","state/hazkey","data/hazkey","cache/hazkey"]:
        os.makedirs(f"{base}/{d}")
    shutil.copy("/tmp/hz-verify/config.json", f"{base}/config/hazkey/config.json")
    # 全体をcopyし、除外対象だけ削除(構造ファイルも必要)
    shutil.copytree(SRC_MEM, f"{base}/state/hazkey/memory")
    memdir = f"{base}/state/hazkey/memory"
    for i, p in enumerate(FILES):
        if i not in keep:
            b = os.path.basename(p)
            for suf in ["", ".2"]:
                fp = f"{memdir}/{b}{suf}"
                if os.path.exists(fp):
                    os.remove(fp)
    rh.WORK=base
    rh.SOCK=f"{base}/run/hazkey-server.{os.getuid()}.sock"
    srv=rh.Server(); srv.start()
    import io, contextlib
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf):
        rh.run_seq(srv,"t",[("new",),("shift",True),("shift",False),("in","U"),("cand",True)])
    srv.kill()
    crashed=("DEAD" in buf.getvalue()) or ("connection lost" in buf.getvalue())
    return crashed

if __name__=="__main__":
    n=len(FILES)
    lo=set(range(n))
    print(f"total files={n}")
    print("sanity all:", "CRASH" if trial(lo,"all") else "ok")
    # 二分探索: クラッシュが消える最小除外を求める(各半分を外して試す)
    import random
    random.seed(1)
    cur=lo
    for it in range(8):
        lst=sorted(cur)
        if len(lst)<=3: break
        half=set(lst[:len(lst)//2])
        c1 = trial(cur-half, f"it{it}a")
        print(f"iter{it}: drop-first-half({len(half)} files) -> {'CRASH' if c1 else 'ok'}")
        if c1:   # 半分除いてもクラッシュ → 犯人は残り半分に含まれる
            cur = cur - half
        else:    # 半分除いたら治った → 犯人は除いた半分
            cur = half
    print("suspect files:", sorted(cur))
