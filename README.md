# hazkey-server SIGILL デバッグツール一式

7ka-Hiira/hazkey の SIGILL (invalid opcode / ud2) クラッシュおよび #26 フリーズを
解析するために作成・使用したツール群。

調査記録本体: issues/1 のコメント参照。

## ディレクトリ構成

    proto/       hazkey-serverのprotobufプロトコル定義(本家から取得)
    harness/     プロトコル直叩き再現ハーネス(Python, 依存なし)
    gdb/         gdbバッチスクリプト(クラッシュ時バックトレース自動取得)
    analysis/    変数切り分け・学習データ二分探索スクリプト

## ハーネスの使い方

harness/ の各ファイルは同一コードのターゲット違い。先頭付近の
WORK(作業ディレクトリ)と SERVER(バイナリパス)を書き換えて使う。
実UIDごとに独立したサーバーインスタンスが立つため、実環境(fcitx5配下)に影響を与えず検証可能。

| ファイル | 用途 |
|---|---|
| repro_harness_original_binary.py | インストール済み v0.2.1 (/usr/lib/hazkey/) 検証用 |
| repro_harness_patched_v02.py | completePrefix修正のみ適用版 検証用 |
| repro_harness_user_config.py | **ユーザー設定+学習履歴**での再現用(#27型発現に必須) |
| repro_harness_fixed_final.py | 全修正適用版(LOUDS guard + state + socketManager) 回帰確認用 |

    # シナリオ実行
    python3 repro_harness_user_config.py scenarios

    # ランダムシーケンス探索(prefix等でクラッシュを発掘)
    python3 repro_harness_original_binary.py fuzz

    # dmesg監視は別ターミナルで: sudo dmesg -w > /tmp/dmesg-live

### 再現シナリオ(#27)

    seq = [("new",), ("shift",True), ("shift",False), ("in","U"), ("cand",True)]
    # → 学習履歴(memory/)がある環境で getCandidates 処理中に SIGILL
    #   dmesg ipオフセット 53a57a / 53a592 (報告と同一シグネチャ)

### 再現シナリオ(completePrefix境界チェック欠如)

    seq = [("new",), *[("in",c) for c in "kyou"], ("cand", True), ("prefix", 99)]
    # → dmesg ipオフセット 76e4f0 で SIGILL (exit=-4)

## analysis/

| ファイル | 役割 |
|---|---|
| isolate_test.py | 変数切り分け(Vulkan/CPU × 学習履歴あり/なし)。結果: Vulkan無関係、学習履歴がトリガー |
| exp_trigger.py | 入力パターン別の切り分け(E1〜E5)。直接入力モード+英字で発火することを特定 |
| bisect_mem.py | memory/*.loudstxt3 の二分探索。memory70.loudstxt3 単独がトリガーと特定 |

## gdb/

サーバーをgdb配下で起動し、ハーネスでクラッシュさせ、バックトレースを自動保存する。
strippedバイナリでもeh_frame(FDE)経由で呼び出しチェーンが取れる。

    ./gdb_repro2.sh   # 結果は /tmp/gdb2.out

## 静的解析チートシート(stripped Swiftバイナリ向け)

    # 1. dmesgのipからPIEベース差し引きでオフセット算出
    #    ip:55c4b705b592 in hazkey-server[53a592,55c4b6b21000+...] → オフセット 0x53a592

    # 2. ud2確認(Swiftランタイムトラップ)
    objdump -d --start-address=0x53a570 --stop-address=0x53a5b0 /usr/lib/hazkey/hazkey-server

    # 3. 関数境界(.eh_frame FDE — strippedでも残る)
    readelf --debug-dump=frames-interp exe | grep 'pc=0000000000539'

    # 4. ud2への分岐種別: jo/js/jae=オーバーフロー・境界違反, je等=precondition失敗
    # 5. 関数先頭へのcallを全逆アセンブルからgrepして静的コールグラフ復元
