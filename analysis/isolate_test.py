import sys, os, shutil, json, time
sys.path.insert(0,'.')
import repro_harness_user as rh

REPRO27 = [
    ("head_yo", [("new",), ("in","y"), ("cand",True)]),
    ("ayoku",  [("new",), *[("in",c) for c in "ayo"], ("cand",True)]),
    ("shiftU", [("new",), ("shift",True), ("shift",False), ("in","U"), ("cand",True)]),
]

def setup(tag, device, with_mem):
    base = f"/tmp/hz-iso-{tag}"
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(f"{base}/run"); os.makedirs(f"{base}/config/hazkey")
    os.makedirs(f"{base}/state/hazkey"); os.makedirs(f"{base}/data/hazkey")
    os.makedirs(f"{base}/cache/hazkey")
    conf = json.load(open("/tmp/hz-verify/config.json"))
    if device is None:
        conf[0]["zenzaiBackendDeviceName"] = ""   # CPU fallback
    else:
        conf[0]["zenzaiBackendDeviceName"] = device
    json.dump(conf, open(f"{base}/config/hazkey/config.json","w"))
    if with_mem:
        shutil.copytree("/tmp/memory.pristine", f"{base}/state/hazkey/memory")
    return base

def run_case(tag, device, with_mem, rounds=3):
    base = setup(tag, device, with_mem)
    rh.WORK = base
    rh.SOCK = f"{base}/run/hazkey-server.{os.getuid()}.sock"
    results = []
    srv = rh.Server(); srv.start()
    for name, seq in REPRO27 * rounds:
        alive_before = srv.alive()
        if not alive_before:
            srv.kill(); srv = rh.Server(); srv.start()
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rh.run_seq(srv, name, seq)
        crashed = "DEAD" in buf.getvalue() or "connection lost" in buf.getvalue()
        results.append((name, "CRASH" if crashed else "ok"))
    srv.kill()
    crashes = sum(1 for _,r in results if r=="CRASH")
    print(f"[{tag}] device={device or 'CPU'} mem={with_mem}: {crashes}/{len(results)} crashes -> {results}")

if __name__ == "__main__":
    which = sys.argv[1]
    if which == "vulkan_only":   run_case("vulkan_only", "Vulkan0", False)
    elif which == "cpu_mem":     run_case("cpu_mem", None, True)
    elif which == "vulkan_mem":  run_case("vulkan_mem", "Vulkan0", True)
