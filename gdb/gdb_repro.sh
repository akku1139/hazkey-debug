#!/bin/bash
BASE=/tmp/hz-iso-cpu_mem
export XDG_RUNTIME_DIR=$BASE/run XDG_CONFIG_HOME=$BASE/config XDG_STATE_HOME=$BASE/state \
       XDG_DATA_HOME=$BASE/data XDG_CACHE_HOME=$BASE/cache \
       HAZKEY_DICTIONARY=/usr/share/hazkey/Dictionary \
       GGML_BACKEND_DIR=/usr/lib/hazkey/libllama/backends/
pkill -U $(id -u) -x hazkey-server 2>/dev/null; sleep 0.5
rm -f $BASE/run/*
gdb -q -batch \
  -ex 'handle SIGILL stop nopass' \
  -ex 'run' \
  -ex 'echo \n=== BACKTRACE ===\n' \
  -ex 'bt 25' \
  -ex 'echo \n=== REGISTERS ===\n' \
  -ex 'info registers rip rax rbx rcx rdx rsi rdi r12 r13 r14 r15' \
  -ex 'x/4i $pc' \
  /usr/lib/hazkey/hazkey-server > /tmp/gdb.out 2>&1 &
GDBPID=$!
for i in $(seq 60); do [ -S $BASE/run/hazkey-server.$(id -u).sock ] && break; sleep 0.25; done
sleep 1
python3 - <<'PYEOF'
import sys
sys.path.insert(0,'.')
import repro_harness_user as rh
rh.SOCK = "/tmp/hz-iso-cpu_mem/run/hazkey-server.%d.sock" % __import__('os').getuid()
import os
c = rh.Client()
for payload in [rh.req_new(), *[rh.req_input(ch) for ch in "U"], rh.req_shift(True), rh.req_new(), rh.req_shift(True), rh.req_shift(False), rh.req_input("U"), rh.req_cands(True)]:
    try:
        c.call(payload)
    except Exception as e:
        print("client stopped:", e.__class__.__name__); break
PYEOF
wait $GDBPID
grep -A40 'BACKTRACE' /tmp/gdb.out | head -50
