"""Offline checks for CaptureCsvWriterV04 (pulsenest_capture_csv.py) -- the v0.4 container of
capture_csv_format_spec.md. Same reason as capture_csv_test.py: a wrong special line or a wrong
column does not raise, it writes a well-formed file that means something else.
    python tools/capture_csv_v04_test.py
"""
import io, os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_capture_csv import CaptureCsvWriterV04, CAPTURE_COLS   # noqa: E402
import pulsenest_capture_dict as D                                     # noqa: E402

print(f"== {os.path.basename(__file__)} ==  the v0.4 capture CSV writer")
ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))

# ── fixtures: the three wire frames as fw 0.15 / lib 0.94 print them ────────────────────────
CFG = ("$CFG,sr=500,numav=1,led1=25.00,led2=25.00,range=50,ensepgain=1"
       ",tia1=50k,rf1_ohm=50000,cf1=5p,cf1_pF=5,stg21=off,rg1_ohm=0,rg1_x=1.0000,stage2en1=0"
       ",tia2=100k,rf2_ohm=100000,cf2=5p,cf2_pF=5,stg22=off,rg2_ohm=0,rg2_x=1.0000,stage2en2=0"
       ",ambdac=0,ri_ohm=100000,ch=LED1,fl=0.50,fh=5.00,hr2l=0.50,hr2h=5.00,hr3h=8.00"
       ",spo2a=110.0000,spo2b=25.0000,board=incunest_V18,mac=10:51:DB:50:88:50"
       ",fw=0.15,lib=0.94,build=da3cc94,libsha=f41fdf6,elfsha=0154b6e792e5323f,idfver=v6.0.1"
       ",cause=query,ts_us=48917216,hgac_rf_changes=1*00")
CFG_HGAC = CFG.replace("tia1=50k,rf1_ohm=50000", "tia1=25k,rf1_ohm=25000") \
              .replace("cause=query,ts_us=48917216,hgac_rf_changes=1", "cause=hgac,ts_us=50000000,hgac_rf_changes=2")
TCFG = ("$TCFG,t1=6050,t2=7998,t3=6000,t4=7999,t5=50,t6=1998,t7=2050,t8=3998,t9=2000,t10=3999"
        ",t11=4050,t12=5998,t13=4,t14=1999,t15=2004,t16=3999,t17=4004,t18=5999,t19=6004,t20=7999"
        ",t21=0,t22=3,t23=2000,t24=2003,t25=4000,t26=4003,t27=6000,t28=6003*00")
LCFG = ("$LCFG,rsqm_ot_thr=1.0000e-04,rsqm_disconn_led_sub_thr=50.0,rsqm_disconn_i_pd_thr=5.0000e-08"
        ",rsqm_probe_state_min_s=0.500,hgac_enable=1,hgac_v_tia_high2=0.900,hgac_v_tia_high1=0.750"
        ",hgac_v_tia_low1=0.200,hgac_ema_fast_tau_s=0.100,hgac_ema_slow_tau_s=2.000,hgac_ema_ambient_tau_s=2.000*00")

def m4(cnt, ts, rf1="50K"):
    """A $M4 whose field k holds k (so a column can be checked against its index), except the
    counter, the clock and the RF strings."""
    fields = [str(cnt), str(ts)] + [str(i) for i in range(3, 34)] + [rf1, "100K"]
    return "$M4," + ",".join(fields) + "*00"

KEYS = {"writer": "capture_csv_v04_test/1", "session_id": "20260922_1200_BENCH", "subject": "SUBJ01",
        "site": "BENCH", "condition": "RESTING", "part": 1, "led1": "IR", "led2": "RED",
        "probe": "Medle-neo", "t0_iso": "2026-09-22T12:00:00+02:00", "t0_epoch_us": 1790000000000000}

def run(frames_before_open, datagrams, keys=KEYS, keep_wire=True, events=()):
    """frames_before_open: wire lines fed before open(); datagrams: [(text, host_us)] fed after."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "x.csv")
        w = CaptureCsvWriterV04(path, keys=keys, label="test", keep_wire=keep_wire)
        for fr in frames_before_open:
            w.config(fr)
        w.open()
        for i, (dg, host) in enumerate(datagrams):
            w.write_datagram(dg, host)
            for at, text in events:
                if at == i:
                    w.add_event(text, host)
        w.close()
        raw = io.open(path, "rb").read()
        return w, raw

# ── 1. the header block ─────────────────────────────────────────────────────────────────────
w, raw = run([CFG, TCFG, LCFG], [(m4(1000, 2_000_000) + "\r\n" + m4(1001, 2_002_000) + "\r\n", 1790000000100000)])
text = raw.decode("utf-8")
lines = text.split("\n")
check("UTF-8 without BOM, LF only, no blank line inside", not raw.startswith(b"\xef\xbb\xbf")
      and b"\r" not in raw and "" not in lines[:-1] and raw.endswith(b"\n"))
check("first lines are the R26 keys, in R26 order, only the known ones",
      lines[:6] == ["# format=incunest_csv/1", "# profile=P1", "# writer=capture_csv_v04_test/1",
                    "# source_mac=10:51:DB:50:88:50", "# board=incunest_V18", "# fw=0.15"], str(lines[:6]))
check("identity read off $CFG: lib, build, libsha, elfsha, idfver present; decimation absent (unknown)",
      "# elfsha=0154b6e792e5323f" in lines and "# idfver=v6.0.1" in lines and "# libsha=f41fdf6" in lines
      and not any(l.startswith("# decimation") for l in lines))
check("the operator's keys follow: subject, site, condition, session_id, part, led1, led2, probe",
      [l for l in lines if l.startswith(("# subject", "# site", "# condition", "# session_id", "# part=",
                                          "# led1", "# led2", "# probe"))]
      == ["# subject=SUBJ01", "# site=BENCH", "# condition=RESTING", "# session_id=20260922_1200_BENCH",
          "# part=1", "# led1=IR", "# led2=RED", "# probe=Medle-neo"])
fb = [l for l in lines if l.startswith("# from-board: ")]
check("the three wire frames follow as evidence, $CFG $TCFG $LCFG, verbatim",
      [l.split(": ", 1)[1] for l in fb] == [CFG, TCFG, LCFG])
snaps = [l for l in lines if re.match(r"# @row 0 (afe|timing|alg): cause=open ", l)]
check("three FULL snapshots at @row 0, cause=open, afe then timing then alg",
      [l.split()[3] for l in snaps] == ["afe:", "timing:", "alg:"])
afe0 = snaps[0]
check("afe: one representation per register, integers in natural units (R24a)",
      " afe_rf1_ohm=50000 " in afe0 and " afe_iled1_ua=25000 " in afe0 and " afe_ambdac_ua=0 " in afe0
      and " afe_prf_hz=500 " in afe0 and "tia1" not in afe0 and "50k" not in afe0 and "." not in afe0.split("cause=open ")[1])
check("timing: the 28 registers by datasheet name plus the derived afe_prpcount=7999",
      " afe_led2stc=6050 " in snaps[1] and snaps[1].endswith(" afe_adcrstendct3=6003 afe_prpcount=7999")
      and len(snaps[1].split()) == 5 + 29)     # '#', '@row', '0', 'timing:', 'cause=open' + 28 registers + prpcount
check("alg: merges $CFG corners and $LCFG parameters; ms/mHz/mV/pA/e10 integers; reals only for spo2_cal",
      " hgac_v_tia_high2_mv=900 " in snaps[2] and " hgac_ema_fast_tau_ms=100 " in snaps[2]
      and " rsqm_ot_thr_e10=1000000 " in snaps[2] and " rsqm_disconn_i_pd_thr_pa=50000 " in snaps[2]
      and " rsqm_probe_state_min_ms=500 " in snaps[2] and " hr2_f_low_mhz=500 " in snaps[2]
      and " ppgdisp_channel=LED1 " in snaps[2] and " spo2_cal_a=110.0000 " in snaps[2]
      and "hgac_rf_changes" not in snaps[2])
for l in snaps:
    dom = l.split()[3][:-1]
    keys_in_line = [tok.split("=")[0] for tok in l.split()[5:]]
    check(f"every key of the {dom}: line is in the dictionary under that domain",
          all(D.KEY_BY_NAME.get(k) is not None and D.KEY_BY_NAME[k].domain == dom for k in keys_in_line),
          str([k for k in keys_in_line if D.KEY_BY_NAME.get(k) is None or D.KEY_BY_NAME[k].domain != dom]))
hdr_i = next(i for i, l in enumerate(lines) if not l.startswith("#"))
check("exactly one header row, the first non-# line, ASCII, canonical names, no SmpCnt/Ts_us/HOST/RF",
      lines[hdr_i].isascii() and lines[hdr_i].split(",")[:6] == ["LED2", "LED1", "ALED2", "ALED1", "LED2_SUB", "LED1_SUB"]
      and not any(x in lines[hdr_i] for x in ("SmpCnt", "Ts_us", "HOST", "RF1", "RF2", "FW_"))
      and len(lines[hdr_i].split(",")) == len(CAPTURE_COLS) - 4)
check("the opening clock anchor is written with the first row, at @row 0, from that row's own values",
      lines[hdr_i - 1] == "# @row 0 clock: smpcnt=1000 fw_ts_us=2000000 host_epoch_us=1790000000100000"
      or lines[hdr_i + 1] == "# @row 0 clock: smpcnt=1000 fw_ts_us=2000000 host_epoch_us=1790000000100000",
      f"{lines[hdr_i-1]!r} / {lines[hdr_i+1]!r}")
check("the anchor comes AFTER the header row (rows and their lines live below the header)",
      lines[hdr_i + 1].startswith("# @row 0 clock:"))
row0 = lines[hdr_i + 2].split(",")
check("each column reads its own field: LED2=3 LED1=4 ... CH_MASKS=33, verbatim",
      row0 == [str(i) for i in range(3, 34)], str(row0[:8]))
check("close: `# @row N end: gaps= stalls=` then a clock anchor tied to the LAST row (N-1)",
      lines[-3] == "# @row 2 end: gaps=0 stalls=0"
      and lines[-2] == "# @row 1 clock: smpcnt=1001 fw_ts_us=2002000 host_epoch_us=1790000000100000", str(lines[-3:]))
check("counts: 2 rows, nothing skipped", (w.count, w.skipped) == (2, 0))

# ── 2. the checks: gap, stall, restart, periodic anchor ─────────────────────────────────────
dgs = []
ts = 2_000_000
dgs.append((m4(10, ts), 1))
dgs.append((m4(11, ts + 2000), 2))
dgs.append((m4(14, ts + 8000), 3))                # gap: 12, 13 missing
dgs.append((m4(15, ts + 8000 + 87_600), 4))       # stall: contiguous counter, 87.6 ms
dgs.append((m4(16, ts + 8000 + 89_600), 5))
dgs.append((m4(17, ts + 12_000_000), 6))          # 12 s later: periodic anchor due
dgs.append((m4(3, 500), 7))                       # counter went back: restart
dgs.append((m4(4, 2500), 8))
w, raw = run([CFG, TCFG, LCFG], dgs)
L = raw.decode().split("\n")
check("gap: `# @row 2 gap: missing=2` + its own clock line at the same N, before the row",
      "# @row 2 gap: missing=2" in L and L[L.index("# @row 2 gap: missing=2") + 1] == "# @row 2 clock: smpcnt=14 fw_ts_us=2008000 host_epoch_us=3")
check("stall: `# @row 3 stall: dt=87600us` + clock",
      "# @row 3 stall: dt=87600us" in L and L[L.index("# @row 3 stall: dt=87600us") + 1].startswith("# @row 3 clock: smpcnt=15 fw_ts_us=2095600"))
check("a periodic anchor after >= 10 s of firmware time, tied to no event",
      "# @row 5 clock: smpcnt=17 fw_ts_us=14000000 host_epoch_us=6" in L)
check("restart: `# @row 6 event: board restarted smpcnt=3 host_epoch_us=7` + clock",
      "# @row 6 event: board restarted smpcnt=3 host_epoch_us=7" in L and "# @row 6 clock: smpcnt=3 fw_ts_us=500 host_epoch_us=7" in L)
check("end tallies gaps=1 stalls=2 (the 12 s jump with a contiguous counter IS a stall); note: restarts=1 missing=2",
      "# @row 8 end: gaps=1 stalls=2" in L and "# note: restarts=1 missing=2" in L, str(L[-4:]))
check("every special line obeys R10a: `# @row N <type>:` with N = rows written so far",
      all(re.match(r"# @row \d+ (afe|timing|alg|clock|gap|stall|end|event): ", l) for l in L if l.startswith("# @row")))

# ── 3. configuration after open: snapshots on change only, cause from the wire, RF via afe: ──
dgs = [(m4(1, 1000), 1), (CFG, 2), (m4(2, 3000, "25K"), 3), (CFG_HGAC, 4), (m4(3, 5000, "25K"), 5), (LCFG, 6)]
w, raw = run([CFG, TCFG, LCFG], dgs)
L = raw.decode().split("\n")
check("a repeated $CFG with the same picture writes nothing", sum(l.startswith("# @row 1 ") for l in L) == 0, str([l for l in L if "@row 1" in l]))
hg = [l for l in L if l.startswith("# @row 2 afe: cause=hgac ")]
check("HGAC's $CFG -> one FULL afe: line, cause=hgac, differing from @row 0 in RF1 only",
      len(hg) == 1 and hg[0].replace("afe_rf1_ohm=25000", "afe_rf1_ohm=50000").replace("@row 2", "@row 0").replace("cause=hgac", "cause=open") == afe0.replace("# @row 0", "# @row 0"))
check("...followed by a clock anchor at the same N, and no timing:/alg: line (nothing changed there)",
      L[L.index(hg[0]) + 1].startswith("# @row 2 clock: smpcnt=2 ") and not any(l.startswith(("# @row 2 timing", "# @row 2 alg")) for l in L))
check("configuration lines inside a datagram are not rows and not skipped", (w.count, w.skipped) == (3, 0))
check("the wire frame in the header is the LAST one seen before open; the hgac one is not re-copied",
      sum(l.startswith("# from-board: $CFG") for l in L) == 1)

# ── 4. before $LCFG arrives alg: is not written (full or nothing); it appears when it does ──
dgs = [(m4(1, 1000), 1), (LCFG, 2), (m4(2, 3000), 3)]
w, raw = run([CFG, TCFG], dgs)
L = raw.decode().split("\n")
check("without $LCFG: afe: and timing: at @row 0, no alg: (a partial picture is a wire frame again)",
      any(l.startswith("# @row 0 afe:") for l in L) and any(l.startswith("# @row 0 timing:") for l in L)
      and not any(l.startswith("# @row 0 alg:") for l in L))
check("when $LCFG arrives mid-file: `# @row 1 alg: cause=open ...` (a first picture becoming known, not a change) + clock",
      any(l.startswith("# @row 1 alg: cause=open ") and " hgac_enable=1 " in l for l in L) and any(l.startswith("# @row 1 clock: smpcnt=1 ") for l in L))
w, raw = run([CFG, TCFG, LCFG], [(m4(1, 1000), 1), (LCFG.replace("hgac_v_tia_high1=0.750", "hgac_v_tia_high1=0.780"), 2), (m4(2, 3000), 3)])
L = raw.decode().split("\n")
check("a DIFFERENT $LCFG later says cause=set (the frame carries none) and rewrites alg: in full",
      any(l.startswith("# @row 1 alg: cause=set ") and " hgac_v_tia_high1_mv=780 " in l and " rsqm_ot_thr_e10=" in l for l in L))

# ── 5. narrower frame modes: the fields they lack are EMPTY cells (R9), never -1 ───────────
w, raw = run([CFG], [("$M1,7,8,0.5*00\r\n$M2,11,12,13,14,15,16,17,18,19,20*00\r\n", 1)])
L = raw.decode().split("\n")
rows = [l for l in L if l and not l.startswith("#")][1:]
check("$M1: its single value lands in PPG (never shifted into LED2); every other cell empty",
      rows[0].split(",")[6] == "0.5" and rows[0].count(",") == len(CAPTURE_COLS) - 5 and set(rows[0].split(",")) == {"", "0.5"})
check("$M2: remapped codes, the rest empty", rows[1].split(",")[:6] == ["12", "13", "14", "15", "16", "17"] and rows[1].split(",")[6] == "")
check("a # STAT line and a $ERR line are skipped, never rows", (lambda w_: w_.skipped == 2)(run([CFG], [("# STAT n=1\r\n$ERR,x,y\r\n" + m4(1, 1), 1)])[0]))

# ── 6. events and part opening ─────────────────────────────────────────────────────────────
w, raw = run([CFG, TCFG, LCFG], [(m4(1, 1000), 5), (m4(2, 3000), 6)], events=[(0, "probe moved to  left foot")])
L = raw.decode().split("\n")
check("add_event: `# @row 1 event: <text> smpcnt=1 host_epoch_us=5`, whitespace collapsed",
      "# @row 1 event: probe moved to left foot smpcnt=1 host_epoch_us=5" in L)
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "p2.csv")
    w2 = CaptureCsvWriterV04(p, keys=dict(KEYS, part=2, prev="p01"))
    w2.config(CFG); w2.config(TCFG); w2.config(LCFG)
    w2.open(cause="part")
    w2.write_datagram(m4(1, 1000), 1); w2.close()
    L2 = io.open(p, encoding="utf-8").read().split("\n")
check("a later part: `# part=2`, `# prev=p01`, and its own snapshots with cause=part (R33)",
      "# part=2" in L2 and "# prev=p01" in L2 and sum(l.startswith("# @row 0 ") and " cause=part " in l for l in L2) == 3)

# ── 7. the frozen bench corpus, if present: replay one .pnraw part through the writer ───────
corpus = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures", "v04_corpus")
parts = sorted(p for root, _d, files in os.walk(corpus) for p in
               [os.path.join(root, f) for f in files
                if f.startswith("board_") and f.endswith("_0001.pnraw")]) if os.path.isdir(corpus) else []
# a first part (_0001) always carries the opening $CFG/$TCFG/$LCFG, so a fresh writer replaying it
# alone produces the afe:/timing: snapshots; a later part would not (config arrives once, up front).
if parts:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pulsenest_recorder import read_pnraw
    recs = [r for r in read_pnraw(parts[-1]) if r[0] == "D"]
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "c.csv")
        w = CaptureCsvWriterV04(p, keys={"writer": "test", "site": "BENCH"})
        # like the recorder: the CSV opens once the board is identified, i.e. after its $CFG
        for r in recs:
            for ln in r[-1].split(b"\n"):
                if ln.startswith((b"$CFG,", b"$TCFG,", b"$LCFG,")):
                    w.config(ln)
            if b"$CFG," in r[-1]:
                break
        w.open()
        for r in recs:
            w.write_datagram(r[-1], r[3] if isinstance(r[3], int) else None)
        w.close()
        raw = io.open(p, "rb").read()
    L = raw.decode("utf-8").split("\n")
    n_rows = sum(1 for l in L if l and not l.startswith("#")) - 1
    check(f"corpus {os.path.basename(parts[-1])}: {n_rows} rows, {w.gaps} gaps, {w.stalls} stalls, "
          f"{w.restarts} restarts; header keys came from the stream's own $CFG",
          n_rows == w.count and n_rows > 1000 and any(l.startswith("# source_mac=") for l in L)
          and any(l.startswith("# @row ") and " afe: " in l for l in L), str(L[:12]))
    n_commas = next(l for l in L if not l.startswith("#")).count(",")
    check("corpus: every row has exactly the header's column count",
          all(l.count(",") == n_commas for l in L if l and not l.startswith("#")))
else:
    print("skip corpus: captures/v04_corpus not present")

n = sum(ok)
print(f"\n{n}/{len(ok)} checks passed" + (" -- OK" if n == len(ok) else " -- FAILURES"))
sys.exit(0 if n == len(ok) else 1)
