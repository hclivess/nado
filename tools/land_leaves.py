#!/usr/bin/env python3
"""Build Land's leaf clusters (static/vendor/leaves/) from PHOTO-SCANNED leaves — ambientCG, CC0 1.0 (public domain).

Operator 2026-11-25: "trees liok like 2002 garbage", "yours looks like some fucking Nintendo ripoff. the reference looks
real". Every crown's leaves were vector shapes painted by code (land.js paintLeaves: flat fills, a drawn midrib) — the
look of a cartoon however they were tinted. These clusters are built from scans of real leaves (veins, blemishes, the
colour varying across a blade): ambientCG LeafSet009 (an ovate, serrated broadleaf — hazel-like) at 1K.

The clusters fill the leaf atlas's top row the page already uses (2 x 2 tiles of 512 px; tile 0 broadleaf, tile 1 birch —
land-trees LEAF_TILE): twigs from the heart, then leaves pointing outward, painted back to front, each darker the deeper in
the cluster it sits and the earlier it is laid (a crown's own shade — a cluster lit evenly reads flat), with a small
per-leaf hue and value jitter. One RGBA PNG (alpha = the scan's opacity), 1024 x 512.

  python3 tools/land_leaves.py <dir holding LeafSet009_1K-JPG_Color.jpg and LeafSet009_1K-JPG_Opacity.jpg>

SOURCE.txt records the original's URL and MD5 and the output's SHA-256;
tests/test_a_crowns_leaves_are_photo_scans_not_painted_shapes.mjs pins them and the page's use.
"""
import hashlib
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageEnhance

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "vendor", "leaves")
ASSET = "LeafSet009"
URL = "https://ambientcg.com/get?file=LeafSet009_1K-JPG.zip"
T = 512                                     # one atlas tile (land.js paintLeaves: S = 1024, T = 512)


def leaves_from(scan_dir):
    """The scan's separate leaves as RGBA crops, stem down (as scanned), found as the opacity map's connected blobs."""
    col = Image.open(os.path.join(scan_dir, f"{ASSET}_1K-JPG_Color.jpg")).convert("RGB")
    op = Image.open(os.path.join(scan_dir, f"{ASSET}_1K-JPG_Opacity.jpg")).convert("L")
    W, H = op.size
    px = op.load()
    seen = bytearray(W * H)
    out = []
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
            if len(xs) < 2000:                # specks, not leaves
                continue
            box = (min(xs) - 2, min(ys) - 2, max(xs) + 3, max(ys) + 3)
            leaf = col.crop(box).convert("RGBA")
            leaf.putalpha(op.crop(box))
            out.append(leaf)
    return out


def cluster(leaves, rng, n, size, twigs, value, hue_jitter):
    """One 512 px cluster as BRANCH SPRAYS, not a disc: `twigs` twigs of uneven length from the heart, each with side shoots,
    and n leaves hung alternately along the twigs and shoots, stem on the wood, tip outward. The outline follows the wood —
    ragged, with sky between the sprays — where a disc of leaves, repeated card after card, read as a crown of rosettes
    (photographed at 60 m, 2026-11-25). The nearer the heart and the earlier laid, the darker (a crown's own shade)."""
    tile = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    c = T / 2
    wood = []                                   # every twig and shoot as a polyline segment (x0, y0, x1, y1, r0, length)
    for _ in range(twigs):
        a = rng.random() * math.tau
        ln = 120 + rng.random() * 110
        ex, ey = c + math.cos(a) * ln, c + math.sin(a) * ln
        d.line([(c, c), (ex, ey)], fill=(74, 56, 38, 255), width=3)
        wood.append((c, c, ex, ey, 0.0, ln))
        for f in (0.3, 0.5, 0.7, 0.85):
            if rng.random() < 0.25:
                continue
            b = a + (0.5 + rng.random() * 0.6) * (1 if rng.random() < 0.5 else -1)
            sl = (40 + rng.random() * 60) * (1.1 - f * 0.5)
            sx, sy = c + math.cos(a) * ln * f, c + math.sin(a) * ln * f
            tx, ty = sx + math.cos(b) * sl, sy + math.sin(b) * sl
            d.line([(sx, sy), (tx, ty)], fill=(74, 56, 38, 255), width=2)
            wood.append((sx, sy, tx, ty, ln * f, sl))
    total = sum(w[5] for w in wood)
    spots = []
    for _ in range(n):
        # a point along the wood, length-weighted; the leaf sits on it, its tip away from the twig, alternating sides
        t, acc = rng.random() * total, 0.0
        for w in wood:
            acc += w[5]
            if acc >= t:
                break
        x0, y0, x1, y1, r0, ln = w
        f = 0.15 + rng.random() * 0.85
        x, y = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
        along = math.atan2(y1 - y0, x1 - x0)
        side = along + (math.pi / 2) * (1 if rng.random() < 0.5 else -1) * (0.55 + rng.random() * 0.5)
        r = math.hypot(x - c, y - c)
        spots.append((r, x, y, side))
    spots.sort(key=lambda p: p[0])             # the heart first: outer leaves are laid over inner ones
    for k, (r, x, y, side) in enumerate(spots):
        leaf = leaves[rng.randrange(len(leaves))]
        ln = size[0] + rng.random() * (size[1] - size[0])
        s = ln / leaf.height
        lf = leaf.resize((max(2, int(leaf.width * s)), max(2, int(leaf.height * s))), Image.LANCZOS)
        # the scan is stem-down; turn it so its tip points along `side` (screen y down), its stem on the wood
        lf = lf.rotate(-math.degrees(side) - 90, resample=Image.BICUBIC, expand=True)
        depth = min(1.0, r / 220) * 0.6 + (k / n) * 0.4
        rgb, alpha = lf.convert("RGB"), lf.getchannel("A")
        rgb = ImageEnhance.Brightness(rgb).enhance(value * (0.55 + 0.55 * depth) * (0.92 + rng.random() * 0.16))
        if hue_jitter:
            rgb = ImageEnhance.Color(rgb).enhance(0.85 + rng.random() * 0.3)
        lf = rgb.convert("RGBA"); lf.putalpha(alpha)
        off = ln * 0.45                         # the leaf's centre half its length out from the wood, along its side
        tile.alpha_composite(lf, (int(x + math.cos(side) * off - lf.width / 2), int(y + math.sin(side) * off - lf.height / 2)))
    return tile


def match_mean(tile, target):
    """Scale the tile's colour per channel so its leaves' mean (alpha-weighted, sRGB) is `target` — the scans are leaves lit
    flat on a scanner, lighter and yellower than a crown's; the page's crown light (LEAF_LIT, the far cards' bake) was set
    against the painted clusters' colour, so the scans take that mean and keep their own detail."""
    rgb, a = tile.convert("RGB"), tile.getchannel("A")
    px, al = list(rgb.getdata()), list(a.getdata())
    w = sum(al) or 1
    mean = [sum(p[i] * q for p, q in zip(px, al)) / w for i in range(3)]
    k = [target[i] / max(1e-6, mean[i]) for i in range(3)]
    out = Image.merge("RGB", [ch.point(lambda v, kk=k[i]: min(255, int(v * kk + 0.5))) for i, ch in enumerate(rgb.split())])
    out = out.convert("RGBA"); out.putalpha(a)
    return out


# the painted clusters' mean colour, sRGB — the mean of paintLeaves' own ranges, broadleaf hsl(100-122, 36-52 %, 22-34 %) and
# birch hsl(80-100, 50-65 %, 28-40 %), sampled (20,000 draws). (A first guess of (52, 72, 34) / (70, 90, 40) rendered the
# vale's wood at 0.7 of its green, murky, 2026-11-25.)
TARGET = {"broadleaf": (50, 103, 40), "birch": (87, 136, 37)}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    leaves = leaves_from(src)
    if len(leaves) < 3:
        sys.exit(f"found {len(leaves)} leaves in the scan — expected its six")
    rng = random.Random(20261125)
    atlas = Image.new("RGBA", (2 * T, T), (0, 0, 0, 0))
    # 0: broadleaf — large leaves, deep; 1: birch — smaller, more, lighter
    # LEAVES AT THEIR TRUE SIZE (2026-11-25): a card is ~1.6-2.5 m across (land-species card x CARD_SCALE), so leaves 70-110 px
    # of a 512 px tile were drawn 30-50 cm long — a real hazel or oak leaf is 8-12 cm, birch 4-7 cm. Oversized leaves are the
    # cartoon's tell; now 22-34 px (~10-15 cm) for the broadleaf, 14-22 px for the birch, and many more of them
    atlas.alpha_composite(match_mean(cluster(leaves, rng, 1000, (22, 34), 12, 0.92, True), TARGET["broadleaf"]), (0, 0))
    atlas.alpha_composite(match_mean(cluster(leaves, rng, 1900, (14, 22), 15, 1.05, True), TARGET["birch"]), (T, 0))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "leaves.png")
    atlas.save(path, optimize=True)
    md5 = {f: hashlib.md5(open(os.path.join(src, f), "rb").read()).hexdigest()
           for f in (f"{ASSET}_1K-JPG_Color.jpg", f"{ASSET}_1K-JPG_Opacity.jpg")}
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    with open(os.path.join(OUT, "SOURCE.txt"), "w") as f:
        f.write("Land's leaf clusters: ambientCG (https://ambientcg.com), CC0 1.0 Universal (public domain).\n")
        f.write(f"Built by tools/land_leaves.py from {ASSET} ({URL}): its leaves cut out by their opacity and laid into clusters.\n\n")
        f.write("# originals (file md5)\n")
        for k, v in md5.items():
            f.write(f"{k} {v}\n")
        f.write("\n# outputs (file sha256)\n")
        f.write(f"leaves.png {sha}\n")
    print(f"{len(leaves)} scanned leaves -> {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
