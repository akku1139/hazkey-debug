#!/usr/bin/env python3
"""
hazkey-server SIGILL 再現ハーネス

akku1139さんの #27/#26 の再現手順(文頭「よ」、「あよく」、大文字U、連続入力)を
独立した hazkey-server インスタンスに対して送信し、SIGILL を検出する。

使い方:
  python3 repro_harness.py            # 全シナリオ実行
  python3 repro_harness.py fuzz       # ランダムシーケンスで探索
"""
import os, sys, time, socket, struct, subprocess, shutil, signal, random

WORK = "/tmp/hazkey-repro"
SOCK = WORK + f"/run/hazkey-server.{os.getuid()}.sock"
SERVER = "/tmp/hzfix2/usr/lib/x86_64-linux-gnu/hazkey/hazkey-server"

# ---------------- protobuf encoding helpers (pure stdlib) -------------------

def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)

def tag(field, wire):
    return varint((field << 3) | wire)

def pb_str(field, s):
    b = s.encode() if isinstance(s, str) else s
    return tag(field, 2) + varint(len(b)) + b

def pb_msg(field, b):
    return tag(field, 2) + varint(len(b)) + b

def pb_var(field, v):
    return tag(field, 0) + varint(v)

EMPTY = b""

def req_new():
    return pb_msg(1, EMPTY)                      # new_composing_text

def req_input(ch):
    return pb_msg(3, pb_str(1, ch))              # input_char{text}

def req_shift(press):
    inner = pb_var(1, 1) + pb_var(2, 1 if press else 2)   # mod_type=SHIFT, event
    return pb_msg(4, inner)

def req_move(off):
    return pb_msg(5, pb_var(1, off & 0xFFFFFFFF if off >= 0 else off))

def req_delete(left=True):
    return pb_msg(7 if left else 8, EMPTY)

def req_gcs(char_type=0, preedit=""):
    inner = pb_var(1, char_type) + pb_str(2, preedit)
    return pb_msg(9, inner)

def req_hiragana():
    return pb_msg(10, EMPTY)

def req_cands(suggest):
    return pb_msg(11, pb_var(1, 1 if suggest else 0))

def req_mode():
    return pb_msg(12, EMPTY)

def req_save():
    return pb_msg(13, EMPTY)

def req_setctx(ctx="", anchor=0):
    return pb_msg(2, pb_str(1, ctx) + pb_var(2, anchor))

def req_prefix(idx):
    return pb_msg(6, pb_var(1, idx & 0xFFFFFFFF if idx >= 0 else idx))

# ---------------- server management -----------------------------------------

class Server:
    def __init__(self):
        for d in ("run", "config", "state", "data", "cache"):
            os.makedirs(f"{WORK}/{d}", exist_ok=True)
        self.proc = None

    def env(self):
        e = dict(os.environ)
        e.update(
            XDG_RUNTIME_DIR=f"{WORK}/run",
            XDG_CONFIG_HOME=f"{WORK}/config",
            XDG_STATE_HOME=f"{WORK}/state",
            XDG_DATA_HOME=f"{WORK}/data",
            XDG_CACHE_HOME=f"{WORK}/cache",
            HAZKEY_DICTIONARY="/usr/share/hazkey/Dictionary",
            GGML_BACKEND_DIR="/usr/lib/hazkey/libllama/backends/",
        )
        return e

    def start(self):
        # 自UIDの残置インスタンスとスタイルロックを掃除(akkuのuid1000のサーバーには触れない)
        subprocess.run(["pkill", "-U", str(os.getuid()), "-f",
                        "/usr/lib/hazkey/hazkey-server"], capture_output=True)
        time.sleep(0.3)
        for f in os.listdir(f"{WORK}/run"):
            try:
                os.remove(f"{WORK}/run/{f}")
            except OSError:
                pass
        log = open(f"{WORK}/server.log", "ab")
        self.proc = subprocess.Popen([SERVER], env=self.env(),
                                     stdout=log, stderr=log)
        for _ in range(100):
            if os.path.exists(SOCK):
                break
            if self.proc.poll() is not None:
                raise RuntimeError("server died on startup")
            time.sleep(0.1)
        else:
            raise RuntimeError("socket never appeared")
        # 接続可能になるまで少し待つ
        time.sleep(0.2)
        return self

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def exitcode(self):
        return self.proc.poll() if self.proc is not None else None

    def kill(self):
        if self.proc and self.alive():
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

# ---------------- client -----------------------------------------------------

class Client:
    def __init__(self):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(60)
        self.s.connect(SOCK)

    def call(self, payload):
        data = payload.to_bytes(4, "big") + payload if False else None
        frame = struct.pack(">I", len(payload)) + payload
        self.s.sendall(frame)
        hdr = self._readn(4)
        (n,) = struct.unpack(">I", hdr)
        body = self._readn(n)
        return body

    def _readn(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("EOF")
            buf += chunk
        return buf

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass

# --- minimal response parsing -------------------------------------------------

def parse_resp(b):
    """returns (status, payload_kind, summary)"""
    status = None
    err = ""
    kind = "?"
    i = 0
    while i < len(b):
        key, i = readvar(b, i)
        f, w = key >> 3, key & 7
        if f == 1 and w == 0:
            status, i = readvar(b, i)
        elif f == 2 and w == 2:
            n, i = readvar(b, i)
            err = b[i:i+n].decode(errors="replace"); i += n
        elif f == 3 and w == 2:   # text
            kind = "text"; n, i = readvar(b, i); i += n
        elif f == 4 and w == 2:   # candidates
            kind = "candidates"; n, i = readvar(b, i); i += n
        elif f == 5 and w == 2:   # text_with_cursor
            kind = "textwithcursor"; n, i = readvar(b, i); i += n
        elif f == 6 and w == 2:   # current_input_mode_info
            kind = "mode"; n, i = readvar(b, i); i += n
        elif f == 100 and w == 2:
            kind = "config"; n, i = readvar(b, i); i += n
        elif w == 2:
            n, i = readvar(b, i); i += n
        elif w == 0:
            _, i = readvar(b, i)
        elif w == 5:
            i += 4
        elif w == 1:
            i += 8
        else:
            break
    return status, kind, err

def readvar(b, i):
    shift = res = 0
    while True:
        x = b[i]; i += 1
        res |= (x & 0x7F) << shift
        if not (x & 0x80):
            return res, i
        shift += 7

# ---------------- scenario driver ---------------------------------------------

FAILS = []

def run_seq(server, name, actions, use_new_client_each=False):
    """actions: list of ('in',ch)|('shift',bool)|('cand',suggest)|('new',)|..."""
    if not server.alive():
        print(f"[{name}] SKIP: server already dead")
        return
    c = None
    failed = False
    last_act = "?"
    try:
        c = Client()
        for act in actions:
            if not server.alive():
                print(f"[{name}] SERVER DIED before {act} (exit={server.exitcode()})")
                FAILS.append((name, act))
                return
            kind, arg = act[0], act[1] if len(act) > 1 else None
            last_act = f"{kind}{arg if arg is not None else ''}"
            if kind == "in":
                p = req_input(arg)
            elif kind == "new":
                p = req_new()
            elif kind == "cand":
                p = req_cands(arg)
            elif kind == "shift":
                p = req_shift(arg)
            elif kind == "gcs":
                p = req_gcs(arg or 0)
            elif kind == "hira":
                p = req_hiragana()
            elif kind == "del":
                p = req_delete(arg is not False)
            elif kind == "save":
                p = req_save()
            elif kind == "ctx":
                p = req_setctx(arg or "", len(arg or ""))
            elif kind == "prefix":
                p = req_prefix(arg or 0)
            else:
                continue
            body = c.call(p)
            st, kd, err = parse_resp(body)
            if st != 1:
                print(f"[{name}] {kind}{arg or ''}: status={st} err={err!r}")
    except (ConnectionError, BrokenPipeError, OSError) as e:
        failed = True
        state = "ALIVE" if server.alive() else f"DEAD(exit={server.exitcode()})"
        print(f"[{name}] connection lost ({e.__class__.__name__}) at {last_act} while server {state}")
        if not server.alive():
            FAILS.append((name, "connection"))
    finally:
        if c:
            c.close()
    if server.alive() and not failed:
        print(f"[{name}] ok")
    elif server.alive() and failed:
        print(f"[{name}] INCOMPLETE (server alive)")

ROMAJI_WORDS = ["yo", "ayoku", "U", "aiueo", "korehayoku", "watasinonamaehanodesu",
                "nyuryoku", "sisutemu", "hazkey", "zyooken", "kyoukyuu", "syori"]

JAPANESE_CONTEXTS = ["今日はいい天気ですね。", "私は毎朝コーヒーを飲みます。",
                     "会議の議事録を", "昨日のニュースで見たんですが、",
                     "https://example.com/path?q=日本語テスト"]

def scenario_list():
    S = []
    S.append(("baseline_aiueo", [("new",), ("in", "a"), ("cand", True), ("in", "i"),
                                 ("cand", True), ("in", "u"), ("cand", False),
                                 ("save",)]))
    S.append(("yoku_head_yo", [("new",), ("in", "y"), ("cand", True),
                               ("in", "o"), ("cand", True), ("in", "k"), ("in", "u"),
                               ("cand", False), ("save",)]))
    S.append(("ayoku", [("new",), ("in", "a"), ("cand", True), ("in", "y"),
                        ("cand", True), ("in", "o"), ("cand", True), ("in", "k"),
                        ("in", "u"), ("cand", True), ("cand", False), ("save",)]))
    S.append(("shift_U", [("new",), ("shift", True), ("shift", False), ("in", "U"),
                          ("cand", True), ("save",)]))
    S.append(("consecutive_words", sum(([("new",), *[("in", ch) for ch in w],
                                        ("cand", True)] for w in ROMAJI_WORDS), [])))
    S.append(("delete_and_cursor", [("new",), *[("in", ch) for ch in "konnnitiha"],
                                    ("cand", True), ("move", -2), ("cand", True),
                                    ("move", 2), ("cand", True), ("del", True),
                                    ("cand", True), ("del", False), ("cand", False)]))
    S.append(("prefix_commit", [("new",), *[("in", ch) for ch in "kyouha"],
                                ("cand", False), ("prefix", 0), ("save",),
                                ("new",)]))
    S.append(("context_yo", [("ctx", "今日はいい天気ですね。"), ("new",), ("in", "y"),
                             ("cand", True), ("in", "o"), ("cand", True), ("cand", False)]))
    for i, ctx in enumerate(JAPANESE_CONTEXTS):
        S.append((f"ctx{i}_yoku", [("ctx", ctx), ("new",), *[("in", ch) for ch in "yoku"],
                                  ("cand", True), ("cand", False)]))
    return S

def fuzz(server, rounds=200, seed=42):
    rnd = random.Random(seed)
    alphabet = list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-,.")
    for r in range(rounds):
        if not server.alive():
            print(f"fuzz round {r}: server dead")
            return
        seq = [("new",)]
        for _ in range(rnd.randint(1, 12)):
            op = rnd.random()
            ch = rnd.choice(alphabet)
            if op < 0.60:
                seq.append(("in", ch))
            elif op < 0.75:
                seq.append(("cand", rnd.random() < 0.7))
            elif op < 0.80:
                seq.append(("hira",))
            elif op < 0.84:
                seq.append(("move", rnd.randint(-5, 5)))
            elif op < 0.88:
                seq.append(("del", rnd.random() < 0.5))
            elif op < 0.92:
                seq.append(("gcs", rnd.randint(0, 4)))
            elif op < 0.96:
                seq.append(("prefix", rnd.randint(0, 8)))
            else:
                seq.append(("save",))
        seq.append(("cand", False))
        before = len(FAILS)
        run_seq_quiet(server, f"fuzz#{r}", seq)
        if len(FAILS) > before:
            print("FUZZ SEQUENCE:", seq)
            return

def run_seq_quiet(server, name, actions):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_seq(server, name, actions)
    out = buf.getvalue()
    if "ok" not in out:
        print(out, end="")

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    srv = Server().start()
    print(f"server pid={srv.proc.pid}")
    try:
        if mode in ("all", "scenarios"):
            for name, acts in scenario_list():
                if not srv.alive():
                    # restart for remaining scenarios
                    print(f"-- restarting server after crash ({name}) --")
                    srv.kill(); os.path.exists(SOCK) and os.remove(SOCK); srv.start()
                run_seq(srv, name, acts)
        if mode in ("all", "fuzz"):
            fuzz(srv)
    finally:
        srv.kill()

if __name__ == "__main__":
    main()
