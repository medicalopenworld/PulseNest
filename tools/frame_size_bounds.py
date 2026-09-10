"""Worst-case length of every $M frame, derived from the format strings in src/main.cpp.

The frames carry numbers as variable-length text, so what a frame *measured on the bench* takes is
not what the format *can* produce. This computes the provable upper bound per mode and compares it
against the three limits it has to respect:

  1. the snprintf call's own limit, `sizeof(buf) - 6`. Exceeding it is not a truncated frame, it is
     memory corruption: snprintf returns the length it WOULD have written, and the code then does
     `frame_xor_chk(buf + 1, n - 1)` (out-of-bounds read) and `snprintf(buf + n, sizeof(buf) - n,
     ...)` where `sizeof(buf) - n` underflows to a huge size_t (out-of-bounds write).
  2. UDP_QUEUE_FRAME_SIZE, the per-frame slot of the UDP queue (288 B). `udp_send()` copies with
     strlcpy, so an overrun is truncated silently and the tail glues onto the next frame: two
     BAD CHK at the host.
  3. the MTU share, UDP_MTU / UDP_BATCH_SIZE, for the batched datagram.

Bounds used per conversion (the values come from `float` fields, promoted to double by varargs, so
the magnitude is still bounded by a float's range):

  %ld  int32                     -> 11  ("-2147483648")
  %lu  uint32                    -> 10  ("4294967295")
  %d   int32                     -> 11
  %u   uint32                    -> 10
  %.Ne float                     -> 7+N  (sign, digit, dot, N digits, 'e', sign, 2 exponent digits;
                                          a float cannot exceed e+38 / e-45, so 2 digits suffice)
  %.Nf float                     -> 41+N ** UNBOUNDED IN PRACTICE **: a float's integer part has up
                                          to 39 digits (3.4e38), plus sign and dot. This is the
                                          whole problem: there is no way to cap a %f with a format
                                          specifier, because width is a MINIMUM, not a maximum.
  %04X packed uint8_t masks      -> 5   (four uint8_t OR-ed at shifts 0/4/8/12 reach 0xFFFFF)
  %s   afeRFToStr()              -> 4   ("100K"/"250K"/"500K")

Usage:  python tools/frame_size_bounds.py
Exit code 1 if any mode's worst case exceeds any of its limits.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "src", "main.cpp")

FLOAT_MAX_INT_DIGITS = 39   # 3.4028235e38
INT32_CHARS, UINT32_CHARS = 11, 10
RF_STR_CHARS = 4
CH_MASKS_CHARS = 5


def extract(src, tag):
    """The format string of one mode, plus its buffer size, from main.cpp."""
    i = src.index(f'"${tag},')
    buf = int(re.search(r"char buf\[(\d+)\];", src[:i]).group(1)
              if False else re.findall(r"char buf\[(\d+)\];", src[:i])[-1])
    # concatenate the adjacent string literals that make up the format
    fmt, j = "", i
    while True:
        m = re.compile(r'"((?:[^"\\]|\\.)*)"').match(src, j)
        if not m:
            nxt = re.compile(r'\s*').match(src, j).end()
            m = re.compile(r'"((?:[^"\\]|\\.)*)"').match(src, nxt)
            if not m:
                break
            j = nxt
        fmt += m.group(1)
        j = m.end()
    slim = re.search(r"sizeof\(buf\) - (\d+)", src[i - 400:i])
    return fmt, buf, buf - (int(slim.group(1)) if slim else 6)


def bound(spec):
    """(min, max, note) characters for one conversion specifier."""
    m = re.fullmatch(r"%\.(\d+)([ef])", spec)
    if m:
        n = int(m.group(1))
        if m.group(2) == "e":
            return 3, 7 + n, "acotado"
        return 1, 1 + FLOAT_MAX_INT_DIGITS + 1 + n, "SIN ACOTAR"
    if spec in ("%ld", "%d"):
        return 1, INT32_CHARS, "acotado"
    if spec in ("%lu", "%u"):
        return 1, UINT32_CHARS, "acotado"
    if spec == "%04X":
        return 4, CH_MASKS_CHARS, "acotado"
    if spec == "%s":
        return 1, RF_STR_CHARS, "acotado"
    raise SystemExit(f"especificador no contemplado: {spec}")


def main():
    src = open(MAIN, encoding="utf-8", errors="replace").read()
    slot = int(re.search(r"#define UDP_QUEUE_FRAME_SIZE\s+(\d+)", src).group(1))
    mtu = int(re.search(r"#define UDP_MTU\s+(\d+)", src).group(1))
    batch = int(re.search(r"#define UDP_BATCH_SIZE\s+(\d+)", src).group(1))
    print(f"limites del firmware: hueco por frame {slot} B | MTU {mtu} B | lote {batch}"
          f" -> {mtu // batch} B por frame en el datagrama\n")

    bad = False
    for tag in ("M1", "M2", "M3", "M4"):
        fmt, bufsize, snlimit = extract(src, tag)
        specs = re.findall(r"%[0-9.]*[a-zA-Z]+", fmt)
        literal = len(re.sub(r"%[0-9.]*[a-zA-Z]+", "", fmt))
        lo = hi = literal
        unbounded = []
        for s in specs:
            a, b, note = bound(s)
            lo += a
            hi += b
            if note == "SIN ACOTAR":
                unbounded.append((s, b))
        # *XX + CR + LF are appended by the second snprintf
        lo += 5
        hi += 5
        limits = {"snprintf (corrupcion de memoria)": snlimit,
                  f"hueco de {slot} B (truncado silencioso)": slot,
                  f"MTU/{batch} ({mtu // batch} B)": mtu // batch}
        worst_off = [f"{k}: EXCEDIDO por {hi - v} B" for k, v in limits.items() if hi > v]
        print(f"${tag}: {len(specs)} campos, {literal} B literales, buf[{bufsize}] limite {snlimit}")
        print(f"   longitud minima posible  {lo:5d} B")
        print(f"   longitud MAXIMA posible  {hi:5d} B")
        if unbounded:
            n_ub = len(unbounded)
            print(f"   campos SIN ACOTAR: {n_ub} x %f -> {sum(b for _, b in unbounded)} B de los {hi}")
            print(f"      {', '.join(sorted(set(s for s, _ in unbounded)))}")
        else:
            print("   todos los campos acotados por el formato")
        for w in worst_off:
            print(f"   !! {w}")
            bad = True
        if not worst_off:
            print(f"   dentro de todos los limites (margen minimo {min(v - hi for v in limits.values())} B)")
        print()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
