#!/usr/bin/env python3
"""Build Land's grass-clump card (static/vendor/grass/) from PHOTO-SCANNED grass blades — Poly Haven grass_medium_02, CC0 1.0.

Operator 2026-11-25: the scene "looks like some fucking Nintendo ripoff. the reference looks real"; asked what next, "Grass".
Every meadow clump's card was 28 strips of a flat colour gradient painted by code (land.js grassCardTexture). This card is
built from scans of real blades (their own colour along the blade, the midrib, dry tips): the blades are cut out of the scan's
alpha, kept if upright (taller than 3x their width), and stood along the card's foot — heights 45-100 % of the card, a little
lean, most green and one in six dry. Each pixel then takes the painted card's light along the blade (dark at the root, 0.10 +
0.30 t^0.8 of white at the tip: the reference's grass is dark to the ground), and the whole card is matched to the painted
card's mean colour, so the meadow keeps the colour it was measured to and gains the scan's detail. One RGBA PNG, 512 x 512.

  python3 tools/land_grass.py <dir holding grass_medium_02_diff_1k.jpg and grass_medium_02_alpha_1k.png>

SOURCE.txt records the originals' URLs and MD5s and the output's SHA-256;
tests/test_the_meadows_grass_is_photo_scanned_blades_not_painted_strips.mjs pins them and the page's use.
"""
import hashlib
import os
import random
import sys

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "vendor", "grass")
SRC = {"grass_medium_02_diff_1k.jpg": "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/grass_medium_02/grass_medium_02_diff_1k.jpg",
       "grass_medium_02_alpha_1k.png": "https://dl.polyhaven.org/file/ph-assets/Models/png/1k/grass_medium_02/grass_medium_02_alpha_1k.png"}
N = 512
# the painted card's mean colour over its blades (sRGB): rgb (0.82 L, L, 0.34 L) with L = 0.10 + 0.30 t^0.8 over a blade that
# tapers to its tip (area weight 1 - t): mean L = 0.219
TARGET = (46, 56, 19)


def blades_from(src):
    """The scan's separate blades as RGBA crops, upright (taller than 3x their width), root at the bottom as scanned."""
    col = Image.open(os.path.join(src, "grass_medium_02_diff_1k.jpg")).convert("RGB")
    al = Image.open(os.path.join(src, "grass_medium_02_alpha_1k.png")).convert("L").resize(col.size)
    W, H = al.size
    px, seen, out = al.load(), bytearray(W * H), []
    for y0 in range(0, H, 2):
        for x0 in range(0, W, 2):
            if px[x0, y0] < 128 or seen[y0 * W + x0]:
                continue
            stack, xs, ys = [(x0, y0)], [], []
            seen[y0 * W + x0] = 1
            while stack:
                x, y = stack.pop()
                xs.append(x); ys.append(y)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < W and 0 <= ny < H and not seen[ny * W + nx] and px[nx, ny] >= 128:
                        seen[ny * W + nx] = 1
                        stack.append((nx, ny))
            w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
            if len(xs) < 800 or h < 3 * w:
                continue
            box = (min(xs) - 1, min(ys) - 1, max(xs) + 2, max(ys) + 2)
            b = col.crop(box).convert("RGBA")
            # the scan's colour darkens at a blade's edge where its alpha still holds it: a 1 px trim, or every blade wears a
            # dark outline (photographed in the first build)
            b.putalpha(al.crop(box).filter(ImageFilter.MinFilter(3)))
            r, g, bl = [sum(c) / max(1, len(c)) for c in (b.getchannel("R").getdata(), b.getchannel("G").getdata(), b.getchannel("B").getdata())]
            out.append((b, r > g))                    # (dry: redder than it is green)
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    blades = blades_from(src)
    green = [b for b, dry in blades if not dry] or [b for b, _ in blades]
    dry = [b for b, d in blades if d] or green
    if len(green) < 3:
        sys.exit(f"found {len(blades)} upright blades in the scan — expected about ten")
    rng = random.Random(20261126)
    card = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    for _ in range(60):
        pool = dry if rng.random() < 1 / 6 else green
        b = pool[rng.randrange(len(pool))]
        h = int(N * (0.45 + rng.random() * 0.55))
        s = h / b.height
        # blades ~1 cm wide on a 0.7 m card, not 2-4 (scaled up whole they read as straps — the painted card's lesson too)
        bb = b.resize((max(2, int(b.width * s * 0.45)), h), Image.LANCZOS)
        if rng.random() < 0.5:
            bb = bb.transpose(Image.FLIP_LEFT_RIGHT)
        lean = (rng.random() - 0.5) * 24              # degrees, about its root
        bb = bb.rotate(lean, resample=Image.BICUBIC, expand=True, center=(bb.width / 2, bb.height))
        x = int(N / 2 + (rng.random() - 0.5) * N * 0.55 - bb.width / 2)
        card.alpha_composite(bb, (max(0, min(N - bb.width, x)), N - bb.height))
    # the painted card's light along the blade, root (y = N) to tip (y = 0), then its mean colour
    px = card.load()
    for y in range(N):
        t = 1 - y / N
        k = (0.10 + 0.30 * t ** 0.8) / 0.4
        for x in range(N):
            r, g, b, a = px[x, y]
            if a:
                px[x, y] = (int(r * k), int(g * k), int(b * k), a)
    tot = [0.0, 0.0, 0.0]
    w = 0
    for y in range(N):
        for x in range(N):
            r, g, b, a = px[x, y]
            if a > 128:
                tot[0] += r; tot[1] += g; tot[2] += b; w += 1
    mean = [v / max(1, w) for v in tot]
    kk = [TARGET[i] / max(1e-6, mean[i]) for i in range(3)]
    for y in range(N):
        for x in range(N):
            r, g, b, a = px[x, y]
            if a:
                px[x, y] = (min(255, int(r * kk[0] + 0.5)), min(255, int(g * kk[1] + 0.5)), min(255, int(b * kk[2] + 0.5)), a)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "grass.png")
    card.save(path, optimize=True)
    md5 = {f: hashlib.md5(open(os.path.join(src, f), "rb").read(), usedforsecurity=False).hexdigest() for f in SRC}   # (download check)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    with open(os.path.join(OUT, "SOURCE.txt"), "w") as f:
        f.write("Land's grass card: Poly Haven (https://polyhaven.com), grass_medium_02, CC0 1.0 Universal (public domain).\n")
        f.write("Built by tools/land_grass.py: the scan's upright blades cut out by their alpha and stood along a card's foot.\n\n")
        f.write("# originals (url md5)\n")
        for k, u in SRC.items():
            f.write(f"{u} {md5[k]}\n")
        f.write("\n# outputs (file sha256)\n")
        f.write(f"grass.png {sha}\n")
    print(f"{len(green)} green and {len(dry) if dry is not green else 0} dry blades -> {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
