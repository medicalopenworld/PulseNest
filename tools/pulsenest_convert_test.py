"""Checks for tools/pulsenest_convert.py -- the record replayed equals the file written live.
    python tools/pulsenest_convert_test.py
A synthetic session is recorded with a scripted clock (three boards' worth of frames from one
fake board, configuration frames, console commands mid-way, a gap), in today's format and in
v0.4; each is converted from its own .pnraw and compared byte for byte. Then the frozen bench
corpus, if present: its live legacy CSVs must come back identical.
"""
import glob, io, logging, os, sys, tempfile
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(_HERE), _HERE]
from pulsenest_recorder import Recorder                       # noqa: E402
import pulsenest_convert as C                                 # noqa: E402

print(f"== {os.path.basename(__file__)} ==  .pnraw -> CSV, byte for byte")
ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))

CFG = (b"$CFG,sr=500,numav=1,led1=25.00,led2=25.00,range=50,ensepgain=1"
       b",tia1=50k,rf1_ohm=50000,cf1=5p,cf1_pF=5,stg21=off,rg1_ohm=0,rg1_x=1.0000,stage2en1=0"
       b",tia2=100k,rf2_ohm=100000,cf2=5p,cf2_pF=5,stg22=off,rg2_ohm=0,rg2_x=1.0000,stage2en2=0"
       b",ambdac=0,ri_ohm=100000,ch=LED1,fl=0.50,fh=5.00,hr2l=0.50,hr2h=5.00,hr3h=8.00"
       b",spo2a=110.0000,spo2b=25.0000,board=incunest_V18,mac=10:51:DB:50:88:50"
       b",fw=0.15,lib=0.94,build=da3cc94,libsha=f41fdf6,elfsha=0154b6e792e5323f,idfver=v6.0.1"
       b",cause=query,ts_us=48917216,hgac_rf_changes=1*00\r\n")
TCFG = (b"$TCFG,t1=6050,t2=7998,t3=6000,t4=7999,t5=50,t6=1998,t7=2050,t8=3998,t9=2000,t10=3999"
        b",t11=4050,t12=5998,t13=4,t14=1999,t15=2004,t16=3999,t17=4004,t18=5999,t19=6004,t20=7999"
        b",t21=0,t22=3,t23=2000,t24=2003,t25=4000,t26=4003,t27=6000,t28=6003*00\r\n")
LCFG = (b"$LCFG,rsqm_ot_thr=1.0000e-04,rsqm_disconn_led_sub_thr=50.0,rsqm_disconn_i_pd_thr=5.0000e-08"
        b",rsqm_probe_state_min_s=0.500,hgac_enable=1,hgac_v_tia_high2=0.900,hgac_v_tia_high1=0.750"
        b",hgac_v_tia_low1=0.200,hgac_ema_fast_tau_s=0.100,hgac_ema_slow_tau_s=2.000,hgac_ema_ambient_tau_s=2.000*00\r\n")
IP = "192.168.137.136"

def batch(cnt0, ts0):
    lines = []
    for i in range(5):
        f = [str(cnt0 + i), str(ts0 + 2000 * i)] + [str(1000 + k) for k in range(3, 34)] + ["50K", "100K"]
        lines.append("$M4," + ",".join(f) + "*00")
    return ("\r\n".join(lines) + "\r\n").encode()

class Clock:
    def __init__(self, t_mono, t_epoch): self.t = (t_mono, t_epoch)
    def __call__(self): return self.t

def record_live(root, csv_mode):
    """A scripted live session: returns its directory."""
    log = logging.getLogger("t"); log.addHandler(logging.NullHandler()); log.propagate = False
    T0_EPOCH = 1790000000_000000; T0_MONO = 5_000_000_000
    clk = Clock(T0_MONO, T0_EPOCH)
    rec = Recorder(root, "BENCH", operator="AC", raw_mode="full", csv_mode=csv_mode, hub_text="test",
                   split_s=60, log=log, clock=clk, identify_wait_s=1.0)
    t = 0
    def step(ms):
        nonlocal t
        t += ms * 1000
        clk.t = (T0_MONO + t, T0_EPOCH + t)
    cnt, ts = 1000, 20_000_000
    rec.feed(IP, CFG, *clk.t); step(5)
    rec.feed(IP, TCFG, *clk.t); step(5)
    for i in range(30):                                 # 150 rows
        rec.feed(IP, batch(cnt, ts), *clk.t); cnt += 5; ts += 10_000; step(10)
    rec.console("subject 8850 SUBJ03"); step(1)
    rec.console("cond RESTING SUBJ03"); step(1)
    rec.console("probe SUBJ03 Medle-neo"); step(1)
    rec.feed(IP, LCFG, *clk.t); step(5)                 # alg: becomes known mid-file (v0.4)
    for i in range(20):
        rec.feed(IP, batch(cnt, ts), *clk.t); cnt += 5; ts += 10_000; step(10)
    rec.console("spo2 SUBJ03 97 141"); step(1)
    cnt += 7                                            # a gap: 7 samples never arrive
    ts += 14_000
    for i in range(20):
        rec.feed(IP, batch(cnt, ts), *clk.t); cnt += 5; ts += 10_000; step(10)
    rec.console("note SUBJ03 hands on the baby"); step(1)
    rec.feed(IP, b"# STAT n=1 tx_dropped=0\r\n", *clk.t); step(1)
    for i in range(10):
        rec.feed(IP, batch(cnt, ts), *clk.t); cnt += 5; ts += 10_000; step(10)
    rec.stop("test-done")
    rec.close()
    return rec.dir

def board_csvs(d):
    return sorted(f for f in glob.glob(os.path.join(d, "*.csv"))
                  if os.path.basename(f) not in ("reference_spo2.csv", "session_events.csv"))

for mode in ("on", "v04"):
    with tempfile.TemporaryDirectory() as td:
        live_dir = record_live(os.path.join(td, "live"), mode)
        live = board_csvs(live_dir)
        check(f"[{mode}] the live session wrote one board CSV, canonical name",
              len(live) == 1 and os.path.basename(live[0]).startswith("SUBJ03_RESTING_"), str([os.path.basename(f) for f in live]))
        log = logging.getLogger("c"); log.addHandler(logging.NullHandler()); log.propagate = False
        rec = C.convert(live_dir, os.path.join(td, "out"), csv_mode=mode, split_min=1, log=log)
        res = C.verify(live_dir, rec)
        check(f"[{mode}] converted from .pnraw: identical byte for byte", res and all(v == "identical" for _n, v in res), str(res))
        text = io.open(live[0], encoding="utf-8" if mode == "v04" else "cp1252").read()
        if mode == "v04":
            check("[v04] the live file carries subject/condition only in parts opened after binding -- part 1 has neither",
                  "# subject=" not in text.split("\n# @row 0 clock")[0] or "# part=2" in text)
            check("[v04] alg: appears mid-file with cause=open when $LCFG first arrives; the gap is a gap line",
                  "alg: cause=open" in text and "gap: missing=7" in text)
            check("[v04] operator events are in place: REF_SPO2 and NOTE as `# @row N event:` lines",
                  " event: REF_SPO2 " in text and " event: NOTE " in text and "hands on the baby" in text)
        else:
            check("[on] events landed as `# event @row N:` lines with the post-notes", "# event @row" in text and "REF_SPO2" in text)

# ── the frozen bench corpus: the real acceptance test ───────────────────────────────────────
corpus = sorted(glob.glob(os.path.join(os.path.dirname(_HERE), "captures", "v04_corpus", "*", "raw")))
if corpus:
    for raw_dir in corpus:
        sdir = os.path.dirname(raw_dir)
        if not board_csvs(sdir):
            continue
        # convert in the format the live files are in: a v0.4 file starts "# format=incunest_csv"
        first = io.open(board_csvs(sdir)[0], encoding="utf-8", errors="replace").readline()
        mode = "v04" if first.startswith("# format=incunest_csv") else "on"
        with tempfile.TemporaryDirectory() as td:
            log = logging.getLogger("k"); log.addHandler(logging.NullHandler()); log.propagate = False
            rec = C.convert(sdir, td, csv_mode=mode, log=log)
            res = C.verify(sdir, rec)
            check(f"corpus {os.path.basename(sdir)} [{mode}]: {len(res)} live CSV(s) reproduced byte for byte",
                  res and all(v == "identical" for _n, v in res), str(res))
else:
    print("skip corpus: captures/v04_corpus not present")

n = sum(ok)
print(f"\n{n}/{len(ok)} checks passed" + (" -- OK" if n == len(ok) else " -- FAILURES"))
sys.exit(0 if n == len(ok) else 1)
