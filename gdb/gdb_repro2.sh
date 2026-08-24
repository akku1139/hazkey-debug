#!/bin/bash
BASE=/tmp/hz-gdb2
rm -rf $BASE
for d in run config/hazkey state/hazkey data/hazkey cache/hazkey; do mkdir -p $BASE/$d; done
cp /tmp/hz-verify/config.json $BASE/config/hazkey/config.json
cp -r /tmp/memory.pristine $BASE/state/hazkey/memory
export XDG_RUNTIME_DIR=$BASE/run XDG_CONFIG_HOME=$BASE/config XDG_STATE_HOME=$BASE/state \
       XDG_DATA_HOME=$BASE/data XDG_CACHE_HOME=$BASE/cache \
       HAZKEY_DICTIONARY=/usr/share/hazkey/Dictionary \
       GGML_BACKEND_DIR=/usr/lib/hazkey/libllama/backends/
pkill -U $(id -u) -x hazkey-server 2>/dev/null; sleep 0.5
rm -f $BASE/run/*
gdb -q -batch \
  -ex 'handle SIGILL stop nopass' \
  -ex 'run' \
  -ex 'echo \n=== BT ===\n' \
  -ex 'bt 20' \
  /tmp/hzfix/usr/lib/x86_64-linux-gnu/hazkey/hazkey-server > /tmp/gdb2.out 2>&1 &
GDBPID=$!
for i in $(seq 80); do [ -S $BASE/run/hazkey-server.$(id -u).sock ] && break; sleep 0.25; done
sleep 1
python3 - <<'PYEOF'
import sys, os
sys.path.insert(0,'/home/ai-agent/work/hazkey-debug')
import repro_harness_fixed as rh
rh.SOCK = "/tmp/hz-gdb2/run/hazkey-server.%d.sock" % os.getuid()
c = rh.Client()
for payload in [rh.req_new(), rh.req_shift(True), rh.req_shift(False), rh.req_input("U"), rh.req_cands(True)]:
    try:
        c.call(payload)
    except Exception as e:
        print("client stopped:", e.__class__.__name__); break
PYEOF
wait $GDBPID
grep -A25 'BT' /tmp/gdb2.out | head -30
