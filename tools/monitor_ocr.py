"""Read the ward monitor's numbers (ECG heart rate, SpO2, pulse rate) off the VideoNest snapshots
of a subject, locally and without tokens: every frame, not one per 10 s.

The Mindray BeneVision N17 shows, in its right column, the heart rate (big, green), the SpO2 (big,
cyan, with the monitor's own pulse rate small to its right) and the respiration rate (big, yellow).
VideoNest's own OCR reads only the SpO2; the heart rate was read by eye until 2026-11-25
(`captures/sessions/BIAS_ANALYSIS_SUBJ10_SUBJ11/ocr_vs_eye/SUBJnn_snapshots_eye.csv`, one frame per
10 s). This program reads every frame and keeps that file's format, so `pulsenest.hr_bench` and the
studies in `experiments/` need no change.

How it works, in order:
  1. blobs:  lit, coloured pixels (V > 130, chroma > 25) on the dark screen; a blob is kept when the
             unlit pixels inside its box and around it are screen-dark (the wall behind the monitor
             is bright) and its shape is digit-like.
  2. groups: blobs of similar height, overlapping in y and close in x, form one number.
  3. locate: HR and SpO2 are the two vertically adjacent, left-aligned tall groups, the upper one not
             yellow; the PR is the small, wide group right of the SpO2 in its band. Colour is used
             only to drop the yellow number: the J6+ camera saturates the greens to near white.
  4. digits: a number's own pixels are split into digits (touching digits are cut at the valleys of
             the column profile); every digit is deskewed (principal axis made vertical, which
             removes the camera's slant) and scaled to 24 x 40.
  5. read:   nearest neighbours (k = 3) among the digits of the frames read by eye, one sample set per
             size class (big: HR and SpO2; small: PR). A number is withheld when its worst digit is
             farther than --max-dist from every sample.
Tesseract 5 was tried first (2026-11-25) and dropped: on these digits it read '171' as 71, 1 or 7
depending on the scale.

Validated on 2026-11-25 (train on the even frames read by eye, test on the odd ones, never seen):
HR 171/171, 84/84, 96/96 right for SUBJ12/13/14 (coverage 93-96 %), SpO2 100 / 98.8 / 97.6 %
(the rare error drops a digit: 100 -> 10), PR 88-92 % (digit confusions at 22-40 px: use the PR
as a plausibility check, not as a reference).

    python tools/monitor_ocr.py train <eye_csv> <snapshot_dir> <samples.npz> [--phone Pixel8aACM]
    python tools/monitor_ocr.py read  <samples.npz> <snapshot_dir> <out_csv> [--max-dist 0.1]
    python tools/monitor_ocr.py check <samples.npz> <snapshot_dir> <eye_csv> [--max-dist 0.1]
    python tools/monitor_ocr.py merge <ocr_csv> <eye_csv> <out_csv>

`train` learns the digit samples from the frames a person read (`eye_csv`: phone_time, phone_ms,
hr_ecg, spo2, pr, ...); `read` reads every snapshot; `check` reads and compares with a person's
readings; `merge` writes the bench's file (`SUBJnn_snapshots_eye.csv` format, one row per frame,
`source` = eye where a person read the frame, else ocr).
"""
import argparse
import csv
import datetime as dt
import glob
import os
import re

import numpy as np
from PIL import Image
from scipy import ndimage

NW, NH = 24, 40          # normalised digit
KNN = 3
TZ = dt.timezone(dt.timedelta(hours=1))
LIMITS = {"hr_ecg": (30, 300), "spo2": (0, 100), "pr": (30, 300)}
SIZE_CLASS = {"hr_ecg": "big", "spo2": "big", "pr": "small"}
FIELDS = ["phone_time", "phone_ms", "hr_ecg", "spo2", "pr", "alarm_box", "note", "source"]


# ----------------------------------------------------------------------------- localisation

def blobs(a):
    """Lit coloured blobs with a dark surround. Returns (label image, list of blob dicts)."""
    r, g, b = (a[..., i].astype(np.int16) for i in range(3))
    v = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    bright = (v > 130) & ((v - mn) > 25)
    lab, _ = ndimage.label(bright)
    out = []
    H, W = v.shape
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        if h < 0.02 * H or h > 0.25 * H or w > 2.5 * h:
            continue                                # not a digit (or a few touching digits)
        m = max(2, h // 3)
        Y0, Y1, X0, X1 = max(0, y0 - m), min(H, y1 + m), max(0, x0 - m), min(W, x1 + m)
        ring = v[Y0:Y1, X0:X1].copy()
        ring_lit = bright[Y0:Y1, X0:X1].copy()
        ring[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = -1
        ring_lit[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = True
        bg = ring[(ring >= 0) & ~ring_lit]
        if bg.size < 0.3 * (ring >= 0).sum() or np.median(bg) > 150:
            continue                                # not on the dark screen
        inside = v[y0:y1, x0:x1][~bright[y0:y1, x0:x1]]
        if inside.size < 0.2 * h * w or np.median(inside) > 120:
            continue                                # a lit tile (wall, sign), not strokes on a screen
        mask = lab[y0:y1, x0:x1] == i
        rgb = np.array([c[y0:y1, x0:x1][mask].mean() for c in (r, g, b)])
        out.append({"id": i, "y0": y0, "y1": y1, "x0": x0, "x1": x1, "h": h, "rgb": rgb})
    return lab, out


def group_lines(bl):
    """Blobs of similar height whose y ranges overlap and that sit close in x form one number."""
    bl = sorted(bl, key=lambda t: t["x0"])
    used = [False] * len(bl)
    groups = []
    for i in range(len(bl)):
        if used[i]:
            continue
        used[i] = True
        g = [i]
        changed = True
        while changed:
            changed = False
            gy0 = min(bl[k]["y0"] for k in g); gy1 = max(bl[k]["y1"] for k in g)
            gx0 = min(bl[k]["x0"] for k in g); gx1 = max(bl[k]["x1"] for k in g)
            gh = gy1 - gy0
            for j, b in enumerate(bl):
                if used[j]:
                    continue
                bh = b["h"]
                if abs(bh - gh) > 0.35 * max(gh, bh):
                    continue
                if min(gy1, b["y1"]) - max(gy0, b["y0"]) < 0.5 * min(gh, bh):
                    continue
                if max(b["x0"] - gx1, gx0 - b["x1"]) > 0.9 * max(gh, bh):
                    continue
                used[j] = True; g.append(j); changed = True
        y0 = min(bl[k]["y0"] for k in g); y1 = max(bl[k]["y1"] for k in g)
        x0 = min(bl[k]["x0"] for k in g); x1 = max(bl[k]["x1"] for k in g)
        groups.append({"y0": y0, "y1": y1, "x0": x0, "x1": x1, "h": y1 - y0, "n": len(g),
                       "rgb": np.mean([bl[k]["rgb"] for k in g], axis=0), "ids": [bl[k]["id"] for k in g]})
    return groups


def is_yellow(rgb):
    """Yellow: red and green alike, blue clearly lower (the respiration number, also when washed out)."""
    r, g, b = rgb
    return r > 0.8 * g and b < 0.85 * min(r, g)


def is_greenish(rgb):
    r, g, b = rgb
    return g > r and g > b


def _merge_pieces(groups, hmax):
    """Join groups that are pieces of one number: y overlap >= 50 % of the smaller, x gap < 0.6 hmax."""
    gs = [dict(g) for g in groups]
    changed = True
    while changed:
        changed = False
        for i in range(len(gs)):
            for j in range(i + 1, len(gs)):
                a, b = gs[i], gs[j]
                ov = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
                gap = max(b["x0"] - a["x1"], a["x0"] - b["x1"])
                if ov >= 0.5 * min(a["h"], b["h"]) and gap < 0.6 * hmax:
                    a["y0"], a["y1"] = min(a["y0"], b["y0"]), max(a["y1"], b["y1"])
                    a["x0"], a["x1"] = min(a["x0"], b["x0"]), max(a["x1"], b["x1"])
                    a["h"] = a["y1"] - a["y0"]; a["n"] += b["n"]; a["ids"] = a["ids"] + b["ids"]
                    gs.pop(j); changed = True
                    break
            if changed:
                break
    return gs


def locate(a):
    """(label image, HR box, SpO2 box, PR box or None each, note)."""
    lab, bl = blobs(a)
    gs = group_lines(bl)
    H = a.shape[0]
    # digit-sized groups only (0.03-0.14 of the frame height): the monitor's panels and trend boxes
    # are lit too, far taller, and would otherwise set the scale
    cand = [g for g in gs if 0.03 * H <= g["h"] <= 0.14 * H]
    if not cand:
        return lab, None, None, None, "no numbers"
    hmax = max(g["h"] for g in cand)
    tall = _merge_pieces([g for g in cand if g["h"] >= 0.55 * hmax], hmax)
    tall = [g for g in tall if g["h"] >= 0.55 * hmax and not is_yellow(g["rgb"])]
    tall.sort(key=lambda g: g["y0"])
    best = None
    for i, up in enumerate(tall):
        for dn in tall[i + 1:]:
            gap = dn["y0"] - up["y1"]
            xov = min(up["x1"], dn["x1"]) - max(up["x0"], dn["x0"])
            if (-0.2 * up["h"] <= gap <= 0.7 * up["h"] and abs(up["x0"] - dn["x0"]) < 0.8 * hmax
                    and xov > 0.3 * min(up["x1"] - up["x0"], dn["x1"] - dn["x0"])):
                score = up["h"] + dn["h"] + (0.5 * up["h"] if is_greenish(up["rgb"]) else 0.0)
                if best is None or score > best[0]:
                    best = (score, up, dn)
    if best is None:
        return lab, (tall[0] if tall else None), None, None, "partial"
    _, hr, sp = best
    pr = None
    cands = [g for g in gs if g["x0"] > sp["x1"] and 0.25 * sp["h"] <= g["h"] <= 0.7 * sp["h"]
             and g["y0"] < sp["y1"] and g["y1"] > sp["y0"] and (g["x1"] - g["x0"]) >= 0.8 * g["h"]]
    if cands:
        pr = max(cands, key=lambda g: g["x0"])       # the probe icon sits between SpO2 and PR
    return lab, hr, sp, pr, ""


# ----------------------------------------------------------------------------- digits

def digit_masks(lab, g):
    """Left-to-right list of boolean masks (each in its own bbox) of the digits of a number group."""
    y0, y1, x0, x1 = g["y0"], g["y1"], g["x0"], g["x1"]
    own = np.isin(lab[y0:y1, x0:x1], g["ids"])
    h = y1 - y0
    pieces = []
    sub_lab, _ = ndimage.label(own)
    for i, sl in enumerate(ndimage.find_objects(sub_lab), start=1):
        m = sub_lab[sl] == i
        if m.sum() < 0.02 * h * h:
            continue                                  # speck
        px0 = sl[1].start
        w = m.shape[1]
        if w > 0.62 * h:                              # touching digits (one is <= 0.55 h wide): cut at valleys
            k = max(2, int(round(w / (0.45 * h))))
            prof = m.sum(axis=0).astype(float)
            cuts = []
            for j in range(1, k):
                c = int(round(j * w / k))
                lo, hi = max(1, c - int(0.15 * w)), min(w - 1, c + int(0.15 * w))
                cuts.append(lo + int(np.argmin(prof[lo:hi])))
            edges = [0] + cuts + [w]
            for a0, a1 in zip(edges, edges[1:]):
                part = m[:, a0:a1]
                if part.any():
                    pieces.append((px0 + a0, part))
        else:
            pieces.append((px0, m))
    pieces.sort(key=lambda t: t[0])
    out = []
    for _, m in pieces:
        ys, xs = np.where(m)
        out.append(m[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
    return out


def deskew(mask):
    """Shear the mask so that its principal axis is vertical (removes the camera's slant)."""
    ys, xs = np.nonzero(mask)
    if len(ys) < 10:
        return mask
    yc, xc = ys.mean(), xs.mean()
    var_y = ((ys - yc) ** 2).mean()
    if var_y <= 0:
        return mask
    skew = float(np.clip(((xs - xc) * (ys - yc)).mean() / var_y, -0.6, 0.6))
    h, w = mask.shape
    pad = int(abs(skew) * h) + 2
    canvas = np.zeros((h, w + 2 * pad), np.float32)
    canvas[:, pad:pad + w] = mask.astype(np.float32)
    out = ndimage.affine_transform(canvas, np.array([[1.0, 0.0], [skew, 1.0]]), offset=(0.0, -skew * yc), order=1)
    out = out > 0.5
    ys, xs = np.nonzero(out)
    if len(ys) == 0:
        return mask
    return out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def normalise(mask):
    """Digit mask -> NH x NW float array, deskewed, aspect kept (a narrow '1' stays narrow, centred)."""
    mask = deskew(mask)
    h, w = mask.shape
    nw = max(1, min(NW, int(round(w * NH / h))))
    img = Image.fromarray((mask * 255).astype(np.uint8)).resize((nw, NH), Image.BILINEAR)
    out = np.zeros((NH, NW), np.float32)
    x = (NW - nw) // 2
    out[:, x:x + nw] = np.asarray(img).astype(np.float32) / 255.0
    return out


def classify(mask, samples_of_size):
    """(digit, distance): majority of the KNN nearest training digits (mean squared difference);
    distance = that of the nearest sample of the winning digit."""
    v = normalise(mask).reshape(-1)
    cands = []
    for ch, samples in samples_of_size.items():
        d = np.mean((samples - v) ** 2, axis=1)
        k = min(KNN, len(d))
        cands.extend((float(x), ch) for x in np.partition(d, k - 1)[:k])
    if not cands:
        return None, 1e9
    cands.sort()
    top = cands[:KNN]
    votes = {}
    for _, ch in top:
        votes[ch] = votes.get(ch, 0) + 1
    best = max(votes, key=lambda c: (votes[c], -min(d for d, cc in top if cc == c)))
    return best, min(d for d, ch in top if ch == best)


def read_number(lab, g, samples_of_size, max_dist):
    masks = digit_masks(lab, g)
    if not masks or len(masks) > 4:
        return "", "digits"
    res = [classify(m, samples_of_size) for m in masks]
    if any(ch is None for ch, _ in res):
        return "", "no samples"
    # an extra piece (the probe icon next to the SpO2, a broken stroke) is far from every sample AND
    # small next to the digits; a real digit is never dropped for being far (the number is withheld)
    area = [int(m.sum()) for m in masks]
    while len(res) > 1:
        worst_i = max(range(len(res)), key=lambda i: res[i][1])
        small = area[worst_i] < 0.5 * max(area)
        if len(res) > 3 or (res[worst_i][1] > max_dist and small):
            res.pop(worst_i); area.pop(worst_i)
        else:
            break
    s = "".join(ch for ch, _ in res)
    worst = max(d for _, d in res)
    if worst > max_dist:
        return "", f"far:{worst:.3f}"
    return s, ""


# ----------------------------------------------------------------------------- frames and files

def frame_time(name):
    m = re.search(r"_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(\d{3})\.jpg$", name)
    t = dt.datetime(*map(int, m.groups()[:6]), tzinfo=TZ)
    return t.strftime("%H:%M:%S"), int(t.timestamp() * 1000) + int(m.group(7))


def frames(snapshot_dir, phone=None):
    for p in sorted(glob.glob(os.path.join(snapshot_dir, "VideoNest_frame_*.jpg"))):
        if phone and f"_{phone}_" not in os.path.basename(p):
            continue
        yield p


def locate_frame(p):
    im = Image.open(p).convert("RGB")
    if im.width < im.height:
        return None, None, "portrait"
    lab, hr, sp, pr, note = locate(np.asarray(im))
    return lab, {"hr_ecg": hr, "spo2": sp, "pr": pr}, note


def eye_rows(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


def load_samples(path):
    z = np.load(path)
    out = {"big": {}, "small": {}}
    for k in z.files:
        size, ch = k.split("_")
        out[size][ch] = z[k]
    return out


def train(args):
    eye = {r["phone_ms"]: r for r in eye_rows(args.eye_csv)}
    acc = {}
    used = skipped = 0
    for p in frames(args.snapshot_dir, args.phone):
        _, ms = frame_time(os.path.basename(p))
        r = eye.get(str(ms))
        if r is None:
            continue
        lab, boxes, _ = locate_frame(p)
        if lab is None:
            continue
        for key, g in boxes.items():
            label = r.get(key, "").strip()
            if g is None or not label.isdigit():
                continue
            masks = digit_masks(lab, g)
            if len(masks) != len(label):
                skipped += 1
                continue
            for ch, m in zip(label, masks):
                acc.setdefault((SIZE_CLASS[key], ch), []).append(normalise(m).reshape(-1))
            used += 1
    out, counts = {}, {}
    for (size, ch), arrs in acc.items():
        out[f"{size}_{ch}"] = np.stack(arrs)
        counts[f"{size}_{ch}"] = len(arrs)
    np.savez(args.samples, **out)
    print(f"samples from {used} numbers ({skipped} skipped: digit count != label):",
          {k: counts[k] for k in sorted(counts)})


def read(args):
    samples = load_samples(args.samples)
    rows = []
    for p in frames(args.snapshot_dir):
        name = os.path.basename(p)
        t, ms = frame_time(name)
        row = {"file": name, "phone_time": t, "phone_ms": ms, "hr_ecg": "", "spo2": "", "pr": "", "note": ""}
        lab, boxes, note = locate_frame(p)
        row["note"] = note
        if lab is not None:
            for key, g in boxes.items():
                if g is None:
                    continue
                s, why = read_number(lab, g, samples[SIZE_CLASS[key]], args.max_dist)
                if s and LIMITS[key][0] <= int(s) <= LIMITS[key][1]:
                    row[key] = s
                else:
                    row["note"] = (row["note"] + f" {key}:{why or '?' + s}").strip()
        rows.append(row)
    return rows


def write_rows(rows, out_csv, fieldnames):
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def check(args):
    byms = {str(r["phone_ms"]): r for r in read(args)}
    eye = eye_rows(args.eye_csv)
    for key in ("hr_ecg", "spo2", "pr"):
        both = agree = eye_only = ocr_only = 0; bad = []
        for e in eye:
            o = byms.get(e["phone_ms"])
            if o is None:
                continue
            ev, ov = e[key].strip(), o[key].strip()
            if ev and ov:
                both += 1
                if ev == ov:
                    agree += 1
                else:
                    bad.append((e["phone_time"], ev, ov, o["note"]))
            elif ev:
                eye_only += 1
            elif ov:
                ocr_only += 1
        print(f"{key}: both {both}, agree {agree} ({100 * agree / max(both, 1):.1f} %), eye-only {eye_only}, ocr-only {ocr_only}")
        for b in bad[:10]:
            print("   mismatch", b)


def merge(args):
    """The bench's file: every frame, a person's reading where there is one, else the OCR's."""
    eye = {r["phone_ms"]: r for r in eye_rows(args.eye_csv)}
    header = [l for l in open(args.eye_csv, encoding="utf-8") if l.startswith("#")]
    rows = []
    with open(args.ocr_csv, encoding="utf-8") as f:
        for o in csv.DictReader(f):
            e = eye.get(o["phone_ms"])
            if e is not None:
                r = dict(e); r["source"] = "eye"
            else:
                r = {"phone_time": o["phone_time"], "phone_ms": o["phone_ms"], "hr_ecg": o["hr_ecg"],
                     "spo2": o["spo2"], "pr": o["pr"], "alarm_box": "", "note": o["note"], "source": "ocr"}
            rows.append(r)
    rows.sort(key=lambda r: int(r["phone_ms"]))
    with open(args.out_csv, "w", encoding="utf-8", newline="") as f:
        f.writelines(header)
        f.write(f"# {dt.date.today().isoformat()}: every frame, read by tools/monitor_ocr.py (source=ocr), "
                "the frames a person read kept as they were (source=eye). OCR validated on the frames a person "
                "read: HR 100 %, SpO2 98-100 %, PR 88-92 % (use the PR as a plausibility check only).\n")
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    n_eye = sum(1 for r in rows if r["source"] == "eye")
    print(f"{len(rows)} rows ({n_eye} eye, {len(rows) - n_eye} ocr); hr_ecg in "
          f"{sum(1 for r in rows if r['hr_ecg'].strip())}, pr in {sum(1 for r in rows if r['pr'].strip())}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("train"); a.add_argument("eye_csv"); a.add_argument("snapshot_dir"); a.add_argument("samples")
    a.add_argument("--phone", default=None)
    b = sub.add_parser("read"); b.add_argument("samples"); b.add_argument("snapshot_dir"); b.add_argument("out_csv")
    b.add_argument("--max-dist", type=float, default=0.1)
    c = sub.add_parser("check"); c.add_argument("samples"); c.add_argument("snapshot_dir"); c.add_argument("eye_csv")
    c.add_argument("--max-dist", type=float, default=0.1)
    d = sub.add_parser("merge"); d.add_argument("ocr_csv"); d.add_argument("eye_csv"); d.add_argument("out_csv")
    args = ap.parse_args(argv)
    if args.cmd == "train":
        train(args)
    elif args.cmd == "read":
        write_rows(read(args), args.out_csv, ["file", "phone_time", "phone_ms", "hr_ecg", "spo2", "pr", "note"])
        print("written", args.out_csv)
    elif args.cmd == "check":
        check(args)
    else:
        merge(args)


if __name__ == "__main__":
    main()
