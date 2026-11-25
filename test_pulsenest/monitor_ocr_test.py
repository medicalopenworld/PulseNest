"""Offline checks for tools/monitor_ocr.py -- the reader of the ward monitor's numbers.

The real validation of the reader is its `check` subcommand against frames a person read (HR
100 % on 349 unseen frames, 2026-11-25). Those frames are patient data and stay out of git, so
this test draws its own monitor: N17-like frames (dark screen, big green heart rate, big cyan
SpO2 with the small pulse rate to its right, big yellow respiration rate, a lit panel, a slanted
camera) with known numbers, trains the digit samples on half of them through the same `train`
subcommand an operator runs, reads the other half, never seen, through `read`, and runs `check`
and `merge` on the result. The font is not the N17's; what is checked is the pipeline: that the
numbers are found by geometry, split into digits, deskewed and classified, and that the bench's
file comes out in the format `pulsenest.hr_bench` reads.

    python test_pulsenest/monitor_ocr_test.py
"""
import csv
import os
import shutil
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import monitor_ocr as M  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  the monitor reader on a drawn monitor")
ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


W, H = 1280, 960                     # the Pixel 8a's snapshot
SCREEN = (28, 30, 34)
WALL = (190, 186, 180)               # the bright wall behind the monitor: no chroma, never a blob
GREEN, CYAN, YELLOW, PANEL = (40, 235, 60), (60, 225, 245), (245, 215, 30), (0, 120, 200)
BIG, SMALL = 100, 44                 # font sizes: digits ~72 px (0.075 H) and ~32 px
SHEAR = 0.05                         # the camera's slant, removed by deskew()

# each list covers the ten digits in its size class (big: HR and SpO2; small: PR)
TRAIN = [(102, 97, 102, 45), (134, 98, 135, 52), (156, 100, 157, 38), (178, 95, 179, 60), (190, 92, 190, 41),
         (65, 88, 64, 33), (87, 94, 86, 47), (143, 99, 148, 55), (209, 96, 203, 29), (118, 93, 119, 36)]
TEST = [(121, 96, 120, 44), (147, 91, 146, 50), (163, 100, 165, 39), (185, 89, 183, 61), (72, 94, 73, 42),
        (98, 97, 99, 35), (139, 99, 140, 48), (201, 93, 199, 54), (110, 90, 111, 30), (176, 95, 178, 37)]


def font(size):
    return ImageFont.load_default(size=size)       # Pillow >= 10.1: a scalable bundled font


CONDENSE = 0.72                      # the N17's digits are narrow (<= 0.55 h); the bundled font's are 0.7 h


def draw_number(im, x, y, text, size, colour):
    f = font(size)
    for ch in text:                                 # one glyph at a time, spaced: digits never touch
        gw, gh = int(f.getlength(ch)) + 4, int(1.3 * size)
        glyph = Image.new("L", (gw, gh), 0)
        ImageDraw.Draw(glyph).text((2, 0), ch, font=f, fill=255)
        glyph = glyph.resize((max(1, int(gw * CONDENSE)), gh), Image.BILINEAR)
        im.paste(colour, (int(x), int(y)), glyph)
        x += gw * CONDENSE + 0.12 * size
    return x


def make_frame(path, hr, spo2, pr, rr):
    im = Image.new("RGB", (W, H), SCREEN)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 180, H), fill=WALL)
    d.rectangle((300, 300, 600, 500), fill=PANEL)           # a lit tile: blob-sized, not a number
    draw_number(im, 880, 170, str(hr), BIG, GREEN)
    x = draw_number(im, 880, 285, str(spo2), BIG, CYAN)
    draw_number(im, x + 60, 330, str(pr), SMALL, CYAN)
    draw_number(im, 880, 420, str(rr), BIG, YELLOW)
    im = im.transform((W, H), Image.AFFINE, (1, SHEAR, -SHEAR * H / 2, 0, 1, 0),
                      resample=Image.BILINEAR, fillcolor=SCREEN)
    im.save(path, quality=92)


tmp = tempfile.mkdtemp(prefix="monitor_ocr_test_")
try:
    snaps = os.path.join(tmp, "Snapshots")
    os.makedirs(snaps)
    truth = {}
    eye_path = os.path.join(tmp, "SUBJ00_snapshots_eye.csv")
    with open(eye_path, "w", encoding="utf-8", newline="") as f:
        f.write("# drawn monitor, the even frames 'read by eye'\n")
        w = csv.DictWriter(f, fieldnames=["phone_time", "phone_ms", "hr_ecg", "spo2", "pr", "alarm_box", "note"])
        w.writeheader()
        for i in range(20):
            hr, spo2, pr, rr = (TRAIN if i % 2 == 0 else TEST)[i // 2]
            name = f"VideoNest_frame_Pixel8aACM_20261125_1030{2 * i:02d}_{(37 * i) % 1000:03d}.jpg"
            make_frame(os.path.join(snaps, name), hr, spo2, pr, rr)
            t, ms = M.frame_time(name)
            truth[str(ms)] = (str(hr), str(spo2), str(pr), i % 2 == 0)
            if i % 2 == 0:
                w.writerow({"phone_time": t, "phone_ms": ms, "hr_ecg": hr, "spo2": spo2, "pr": pr, "alarm_box": "", "note": ""})

    # ── the pieces ──
    t, ms = M.frame_time("VideoNest_frame_Pixel8aACM_20261125_103005_123.jpg")
    check("frame_time: clock and milliseconds from the file name", t == "10:30:05" and ms % 1000 == 123)
    check("is_yellow: the respiration number, also washed out",
          M.is_yellow(np.array(YELLOW)) and M.is_yellow(np.array((230, 220, 150))) and not M.is_yellow(np.array(CYAN)))

    bar = np.zeros((40, 30), bool)
    for y in range(40):
        bar[y, 8 + int(0.4 * y):14 + int(0.4 * y)] = True          # a slanted stroke
    ys, xs = np.nonzero(M.deskew(bar))
    skew = ((xs - xs.mean()) * (ys - ys.mean())).mean() / ((ys - ys.mean()) ** 2).mean()
    check("deskew: a slanted stroke comes out vertical", abs(skew) < 0.05, f"skew {skew:.3f}")
    check("normalise: NH x NW, aspect kept (a narrow stroke stays narrow)",
          M.normalise(bar).shape == (M.NH, M.NW) and (M.normalise(bar) > 0.5).any(axis=0).sum() < 0.5 * M.NW)

    lab, boxes, note = M.locate_frame(os.path.join(snaps, sorted(os.listdir(snaps))[0]))
    check("locate: HR, SpO2 and PR found on the drawn frame", lab is not None and all(boxes[k] is not None for k in boxes), note)
    if lab is not None and boxes["hr_ecg"] is not None:
        hr_box, sp_box, pr_box = boxes["hr_ecg"], boxes["spo2"], boxes["pr"]
        check("locate: HR above the SpO2, left-aligned; PR small and right of the SpO2",
              hr_box["y1"] <= sp_box["y0"] + 0.2 * hr_box["h"] and abs(hr_box["x0"] - sp_box["x0"]) < 0.3 * hr_box["h"]
              and pr_box is not None and pr_box["x0"] > sp_box["x1"] and pr_box["h"] < 0.7 * sp_box["h"])
        check("digit_masks: three digits in the HR 102", len(M.digit_masks(lab, hr_box)) == 3)

    # ── the subcommands, as an operator runs them ──
    npz = os.path.join(tmp, "samples.npz")
    M.main(["train", eye_path, snaps, npz, "--phone", "Pixel8aACM"])
    samples = M.load_samples(npz)
    check("train: every digit 0-9 learnt in both size classes from the ten even frames",
          sorted(samples["big"]) == [str(i) for i in range(10)] and sorted(samples["small"]) == [str(i) for i in range(10)],
          f"big {sorted(samples['big'])} small {sorted(samples['small'])}")

    out_csv = os.path.join(tmp, "ocr.csv")
    M.main(["read", npz, snaps, out_csv])
    with open(out_csv, encoding="utf-8") as f:
        got = {r["phone_ms"]: r for r in csv.DictReader(f)}
    check("read: one row per frame", len(got) == 20)
    unseen = [ms for ms, v in truth.items() if not v[3]]
    right = {k: sum(1 for ms in unseen if got[ms][k] == truth[ms][i]) for i, k in enumerate(("hr_ecg", "spo2", "pr"))}
    check("read: HR right on all ten unseen frames", right["hr_ecg"] == 10,
          f"{right['hr_ecg']}/10: " + "; ".join(f"{truth[ms][0]}->{got[ms]['hr_ecg'] or '?'} {got[ms]['note']}" for ms in unseen))
    check("read: SpO2 right on all ten unseen frames", right["spo2"] == 10,
          f"{right['spo2']}/10: " + "; ".join(f"{truth[ms][1]}->{got[ms]['spo2'] or '?'}" for ms in unseen))
    check("read: PR right on all ten unseen frames", right["pr"] == 10,
          f"{right['pr']}/10: " + "; ".join(f"{truth[ms][2]}->{got[ms]['pr'] or '?'}" for ms in unseen))
    check("read: a number is within LIMITS or withheld with a note",
          all((not r["hr_ecg"] or 30 <= int(r["hr_ecg"]) <= 300) and (not r["spo2"] or int(r["spo2"]) <= 100) for r in got.values()))

    M.main(["check", npz, snaps, eye_path])         # runs and prints; its numbers are the test above

    merged = os.path.join(tmp, "SUBJ00_merged.csv")
    M.main(["merge", out_csv, eye_path, merged])
    with open(merged, encoding="utf-8") as f:
        lines = f.readlines()
    rows = list(csv.DictReader(l for l in lines if not l.startswith("#")))
    check("merge: the eye file's comment header kept, one more line added",
          lines[0].startswith("# drawn monitor") and lines[1].startswith("# ") and not lines[2].startswith("#"))
    check("merge: the bench's columns", list(rows[0].keys()) == M.FIELDS)
    check("merge: 20 rows sorted by phone_ms, source eye on the ten read by eye, ocr on the rest",
          len(rows) == 20 and [int(r["phone_ms"]) for r in rows] == sorted(int(r["phone_ms"]) for r in rows)
          and sum(r["source"] == "eye" for r in rows) == 10 and sum(r["source"] == "ocr" for r in rows) == 10)
    check("merge: an eye row keeps the person's values; an ocr row carries the reader's",
          all((r["hr_ecg"] == truth[r["phone_ms"]][0]) for r in rows if r["source"] == "eye")
          and all(r["hr_ecg"] == got[r["phone_ms"]]["hr_ecg"] for r in rows if r["source"] == "ocr"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
