import sys, os, shutil, json
sys.path.insert(0,'.')
import repro_harness_user as rh

def setup(tag, with_mem=True, device=""):
    base = f"/tmp/hz-exp-{tag}"
    shutil.rmtree(base, ignore_errors=True)
    for d in ["run","config/hazkey","state/hazkey","data/hazkey","cache/hazkey"]:
        os.makedirs(f"{base}/{d}")
    conf = json.load(open("/tmp/hz-verify/config.json"))
    conf[0]["zenzaiBackendDeviceName"] = device
    json.dump(conf, open(f"{base}/config/hazkey/config.json","w"))
    if with_mem:
        shutil.copytree("/tmp/memory.pristine", f"{base}/state/hazkey/memory")
    return base

def trial(tag, with_mem=True, actions=None):
    base = setup(tag, with_mem)
    rh.WORK = base
    rh.SOCK = f"{base}/run/hazkey-server.{os.getuid()}.sock"
    srv = rh.Server(); srv.start()
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rh.run_seq(srv, tag, actions)
    srv.kill()
    crashed = ("DEAD" in buf.getvalue()) or ("connection lost" in buf.getvalue())
    print(f"[{tag}] {'CRASH' if crashed else 'ok'}")

toggle = [("shift",True), ("shift",False)]

# E1: 直接入力モードで他の大文字A
trial("e1_direct_A", True, [("new",), *toggle, ("in","A"), ("cand",True)])
# E2: ローマ字preedit "u"
trial("e2_romaji_u", True, [("new",), ("in","u"), ("cand",True)])
# E3: 直接入力モードで数字1
trial("e3_direct_1", True, [("new",), *toggle, ("in","1"), ("cand",True)])
# E4: 空メモリ+shiftU(対照)
trial("e4_empty_shiftU", False, [("new",), *toggle, ("in","U"), ("cand",True)])
# E5: ローマ字 "kyo" + メモリあり
trial("e5_romaji_kyo", True, [("new",), *[("in",c) for c in "kyo"], ("cand",True)])
