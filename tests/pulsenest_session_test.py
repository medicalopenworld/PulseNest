"""Offscreen checks for tools/pulsenest_session.py -- the launcher a non-expert opens.

Part 1 drives the Qt-free model (Fleet, cots_in, the command lines) with synthetic datagrams and
a temporary configs folder. Part 2 builds the real window offscreen against a fake hub client and
a fake process spawner, presses the buttons the way a person does and reads the table back: what
is on the air, which cot matches which board, which phone was heard, and that START runs exactly
the runbook's command line as a detached process and never twice for the same cot.
    python tests/pulsenest_session_test.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tools.pulsenest_session as S          # noqa: E402
from PyQt5 import QtWidgets                  # noqa: E402

ok = []


def check(msg, cond, detail=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg + (f"  [{detail}]" if detail and not cond else ""))


print(f"== {os.path.basename(__file__)} ==  session launcher, offscreen")

CFG_A = b"$CFG,sr=500,board=incunest_V18,mac=10:51:DB:50:88:50,fw=0.22,lib=0.104,build=385ae27,libsha=82444cd,elfsha=cd1ccf587e65b403*00\r\n"
CFG_B = b"$CFG,sr=500,board=incunest_V18,mac=10:51:DB:50:87:A4,fw=0.22,lib=0.104,build=385ae27,libsha=82444cd,elfsha=cd1ccf587e65b403*00\r\n"
CFG_C_OLD = b"$CFG,sr=500,board=incunest_V18,mac=10:51:DB:50:82:5C,fw=0.21,lib=0.103,build=f73b10c,libsha=b97b945,elfsha=5cac9204719dba20*00\r\n"
M4 = b"$M4,1,0,1,2,3,4,5,6*00\r\n" * 5
VN = b"$VN1,12,97.0,0.91,2026-09-22 00:21:26.261,1758500486261,1,J6plusACM*5A\r\n"

# ── Part 1: the model ──────────────────────────────────────────────────────────────────────
fl = S.Fleet()
t0 = 100.0
fl.feed("192.168.137.8", CFG_A, t0)
fl.feed("192.168.137.24", CFG_B, t0)
fl.feed("192.168.137.9", VN, t0)
for i in range(50):
    fl.feed("192.168.137.8", M4, t0 + i * 0.02)
fl.tick(t0 + 1.0)
check("two boards identified by MAC", set(fl.by_mac()) == {"10:51:DB:50:88:50", "10:51:DB:50:87:A4"}, str(set(fl.by_mac())))
check("a phone is a phone, not a board", "192.168.137.9" not in fl.boards and fl.phone_heard("J6plusACM"))
check("datagram rate per board", abs(fl.boards["192.168.137.8"].rate - 50) < 1, str(fl.boards["192.168.137.8"].rate))
agree, text = fl.firmware_agreement()
check("same image on every board -> OK", agree and "fw 0.22" in text and "cd1ccf587e65b403" in text, text)
fl.feed("192.168.137.228", CFG_C_OLD, t0)
agree, text = fl.firmware_agreement()
check("one board on another image -> CHECK, naming it", not agree and "82:5C" in text and "0.21" in text, text)
check("suffix 8850 matches one board", fl.match_board("8850") == ("ok", "10:51:DB:50:88:50"), str(fl.match_board("8850")))
check("suffix 1234 is not on the air", fl.match_board("1234") == ("none", ""))
check("suffix 50 (ends 88:50 AND ... no: 87:A4 no) -> ok; suffix 'DB:50:8' style ambiguous via 8",
      fl.match_board("50")[0] == "ok" and fl.match_board("A4")[0] == "ok")
fl.feed("192.168.137.30", b"$CFG,mac=AA:BB:CC:DD:88:50,fw=0.22,elfsha=cd1ccf587e65b403*00\r\n", t0)
check("two boards ending in 8850 -> AMBIGUOUS, both named",
      fl.match_board("8850")[0] == "ambiguous" and "AA:BB:CC:DD:88:50" in fl.match_board("8850")[1])
check("blank board field", fl.match_board("") == ("blank", ""))
# a new DHCP lease: same MAC, newer address wins
fl.feed("192.168.137.77", CFG_A, t0 + 5)
check("same MAC on a new address is one board, the freshest address",
      fl.by_mac()["10:51:DB:50:88:50"].ip == "192.168.137.77")
check("silent after LOST_S", fl.boards["192.168.137.24"].silent(t0 + S.LOST_S + 1) and not fl.boards["192.168.137.24"].silent(t0 + 1))

tmp = tempfile.mkdtemp()
open(os.path.join(tmp, "subj01.toml"), "w", encoding="utf-8").write(
    'location = "HOSP01"\noperator = "AC"\nboard = "8850"\nsubject = "SUBJ01"\n[ref]\nvideonest = "J6plusACM"\n')
open(os.path.join(tmp, "subj02.toml"), "w", encoding="utf-8").write(
    'location = "HOSP01"\noperator = "AC"\nboard = "1234"\nsubject = "SUBJ02"\n[ref]\nvideonest = "Pixel8aACM"\n')
open(os.path.join(tmp, "broken.toml"), "w", encoding="utf-8").write('location = "HOSP01\nboard = \n')
open(os.path.join(tmp, S.EXAMPLE_NAME), "w", encoding="utf-8").write('location = "HOSP01"\nboard = "8850"\nsubject = "SUBJ67"\n')
cots = S.cots_in(tmp)
check("every .toml listed, example last", [c.name for c in cots] == ["broken.toml", "subj01.toml", "subj02.toml", S.EXAMPLE_NAME], str([c.name for c in cots]))
c1 = next(c for c in cots if c.name == "subj01.toml")
cb = next(c for c in cots if c.name == "broken.toml")
check("fields read through the recorder's own loader", c1.field("board") == "8850" and c1.field("ref_videonest") == "J6plusACM" and c1.field("subject") == "SUBJ01")
check("a broken file shows its error instead of vanishing", cb.cfg is None and "TOMLDecodeError" in cb.error, cb.error)
check("empty folder -> no cots, no exception", S.cots_in(os.path.join(tmp, "nope")) == [])

hub = ("127.0.0.1", S.UDP_DATA_PORT)
cmd = S.cot_command(c1, hub)
check("START is the runbook's command line: pythonw recorder_gui --config <file>, no --hub by default",
      cmd[1] == S.RECORDER_GUI and cmd[2:4] == ["--config", c1.path] and len(cmd) == 4
      and os.path.basename(cmd[0]).lower().startswith("python"), str(cmd))
cmd2 = S.cot_command(c1, ("192.168.1.5", 5005))
check("a non-default hub is passed on", cmd2[-2:] == ["--hub", "192.168.1.5:5005"])
check("fleet monitor runs under console python (never pythonw)",
      not os.path.basename(S.monitor_command(hub)[0]).lower().startswith("pythonw") and S.monitor_command(hub)[1] == S.FLEET_MONITOR)
check("viewer command", S.viewer_command(hub)[1] == S.PPG_VIEWER)
text, colour = S.disk_line(3)
check("disk line says GB free and hours for 3 boards", "GB free" in text and "for 3 board" in text, text)

# ── Part 2: the window ─────────────────────────────────────────────────────────────────────
S.SETTINGS_FILE = os.path.join(tmp, "session_test.ini")


class FakeClient:
    def __init__(self):
        self.queue = []
        self.closed = False

    def recv(self, _):
        return self.queue.pop(0) if self.queue else None

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, cmd, console):
        self.cmd, self.console, self.pid, self.rc = cmd, console, 4242, None

    def poll(self):
        return self.rc


spawned = []


def fake_spawn(cmd, console=False):
    p = FakeProc(cmd, console)
    spawned.append(p)
    return p


S.spawn = fake_spawn
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
client = FakeClient()
w = S.Launcher(tmp, hub, client)
w.show()
app.processEvents()
check("window builds: one row per cot", w.table.rowCount() == 4, str(w.table.rowCount()))
r1 = [c.name for c in w.cots].index("subj01.toml")
r2 = [c.name for c in w.cots].index("subj02.toml")
check("no board yet: 'not on the air' in amber", w.table.item(r1, 3).text() == "not on the air")
check("phone not heard yet", "NOT heard" in w.table.item(r1, 4).text())

client.queue += [("192.168.137.8", CFG_A), ("192.168.137.8", M4), ("192.168.137.9", VN)]
w.drain()
w.refresh()
app.processEvents()
check("boards table shows the board with its MAC and elfsha",
      w.boards.rowCount() == 1 and w.boards.item(0, 1).text() == "10:51:DB:50:88:50" and w.boards.item(0, 5).text() == "cd1ccf587e65b403")
check("cot 1 matched to its MAC", w.table.item(r1, 3).text() == "10:51:DB:50:88:50")
check("cot 1's phone heard", w.table.item(r1, 4).text() == "J6plusACM heard")
check("cot 2 still not on the air, its phone not heard", w.table.item(r2, 3).text() == "not on the air" and "NOT heard" in w.table.item(r2, 4).text())
check("firmware line OK for one board", w.firmware.text().startswith("OK"))
check("phones line names the phone", "J6plusACM" in w.phones.text())
rb = [c.name for c in w.cots].index("broken.toml")
check("broken file: error in the row, START disabled",
      "TOMLDecodeError" in w.table.item(rb, 1).text() and not w.table.cellWidget(rb, 6).isEnabled())

w.table.cellWidget(r1, 6).click()
app.processEvents()
check("START spawns the recorder GUI for that cot, detached (not console)",
      len(spawned) == 1 and spawned[0].cmd == S.cot_command(w.cots[r1], hub) and spawned[0].console is False)
check("row shows running, START disabled",
      w.table.item(r1, 5).text().startswith("running") and not w.table.cellWidget(r1, 6).isEnabled()
      and w.table.cellWidget(r1, 6).text() == "RUNNING")
w.table.cellWidget(r1, 6).click()
w.start_cot(w.cots[r1])
check("a running cot cannot be started twice", len(spawned) == 1)
w.start_all()
app.processEvents()
check("START ALL starts the other valid cot only (not the running one, not the broken, not the example)",
      len(spawned) == 2 and spawned[1].cmd[3] == w.cots[r2].path)
spawned[0].rc = 0
w.refresh()
check("a cot that exited shows rc and can be started again",
      w.table.item(r1, 5).text() == "exited rc=0" and w.table.cellWidget(r1, 6).isEnabled())
w.reload_configs()
check("RELOAD keeps the process handle of a running cot", w.cots[r2].running and w.table.item(r2, 5).text().startswith("running"))
w.btn_monitor.click()
app.processEvents()
check("FLEET MONITOR spawns with a console of its own", spawned[-1].console is True and spawned[-1].cmd[1] == S.FLEET_MONITOR
      and not w.btn_monitor.isEnabled())
w.btn_viewer.click()
app.processEvents()
check("PPG VIEWER spawns detached", spawned[-1].console is False and spawned[-1].cmd[1] == S.PPG_VIEWER)
check("extra status line", "monitor: running" in w.extra_status.text() and "viewer: running" in w.extra_status.text())
w.close()
app.processEvents()
check("closing the launcher closes its hub client and leaves the processes alone",
      client.closed and all(p.rc is None for p in spawned[1:]))
check("geometry saved", os.path.exists(S.SETTINGS_FILE))

n = len(ok)
print(f"\n{sum(ok)}/{n} checks passed -- " + ("OK" if all(ok) else "FAILURES"))
sys.exit(0 if all(ok) else 1)
