#!/usr/bin/env python3
"""Build Land's material textures (static/vendor/textures/) from Poly Haven originals — CC0 1.0 (public domain), no
attribution required, recorded anyway in SOURCE.txt. "Realistic (PBR)" was the operator's choice (2026-11-06).

Each material has a colour map and an OpenGL normal map, re-encoded smaller for the browser: the ground's six at 1024 px
(seen up close, underfoot), building materials and bark at 512 px; JPEG quality 82. Roughness is a constant per material
in static/land.js (its maps were 5 MB of the first 32). SOURCE.txt records every original's URL and MD5 (as Poly Haven
publishes them) and every output's SHA-256; tests/test_the_land_textures_are_the_recorded_cc0_sources.py pins them.

  python3 tools/land_textures.py <dir of originals named <asset>__Diffuse.jpg / <asset>__nor_gl.jpg> <plan.json>
  python3 tools/land_textures.py --phone        (the 512 px ground for phones, from the outputs; main() runs it too)
plan.json: {asset: {"Diffuse": [url, size, md5], "nor_gl": [url, size, md5]}} — the Poly Haven /files answers used.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "vendor", "textures")
# material key -> (Poly Haven asset, pixels)
MATERIALS = {
    "grass": ("leafy_grass", 1024), "dirt": ("dirt", 1024), "rock": ("cliff_side", 1024),
    "sand": ("coast_sand_01", 1024), "snow": ("snow_02", 1024), "gravel": ("gravel", 1024),
    "planks": ("brown_planks_07", 512), "darkwood": ("dark_wooden_planks", 512), "brick": ("red_brick", 512),
    "plaster": ("painted_plaster_wall", 512), "tiles": ("clay_roof_tiles", 512), "cobble": ("cobblestone_01", 512),
    "stonebrick": ("castle_brick_07", 512), "bark": ("bark_brown_02", 512), "birch": ("bark_willow", 512),
    # a wood's floor (2026-11-25, operator: trees "2002 garbage" — under the canopy the ground was the meadow's grass tinted
    # green, a flat olive): leaf litter, twigs and moss, at the ground's 1024 px
    "forest": ("forest_floor", 1024),
}
QUALITY = 82
# A PHONE GETS THE GROUND AT 512 px (#139/#150, measured 2026-11-16: a fresh phone load is 7 MB, 2.2 MB of it these
# textures, the seven ground maps a page loads 1.48 MB of it at 1024 px, 0.37 MB at 512): the phone profile draws at 1.25× and close ground covers ~130 px a
# metre of screen, against 320 texels a metre at 1024 px over the near repeat (3.2 m) — 512 px still ~1:1, a quarter of
# the bytes and of the GPU memory. Made from the 1024 px outputs (pinned below them), named <key>_<tag>_512.jpg.
PHONE_PX = 512


def main():
    from PIL import Image          # here, not at import: the texture test reads MATERIALS where Pillow is not installed
    src, plan = sys.argv[1], json.load(open(sys.argv[2]))
    os.makedirs(OUT, exist_ok=True)
    lines = ["Land's material textures: Poly Haven (https://polyhaven.com), every asset CC0 1.0 Universal (public domain).",
             "Built by tools/land_textures.py: originals at 1k JPG, resized and re-encoded at quality %d." % QUALITY,
             "", "# originals (url md5)"]
    outs = []
    for key, (asset, px) in sorted(MATERIALS.items()):
        for kind, tag in (("Diffuse", "col"), ("nor_gl", "nor")):
            url, size, md5 = plan[asset][kind]
            data = open(os.path.join(src, f"{asset}__{kind}.jpg"), "rb").read()
            if hashlib.md5(data, usedforsecurity=False).hexdigest() != md5:   # (Poly Haven publishes MD5s: a download check, not security)
                raise SystemExit(f"{asset} {kind}: the original does not match Poly Haven's MD5")
            lines.append(f"{url} {md5}")
            im = Image.open(os.path.join(src, f"{asset}__{kind}.jpg")).convert("RGB").resize((px, px), Image.LANCZOS)
            path = os.path.join(OUT, f"{key}_{tag}.jpg")
            im.save(path, "JPEG", quality=QUALITY, optimize=True, progressive=True)
            outs.append((hashlib.sha256(open(path, "rb").read()).hexdigest(), f"{key}_{tag}.jpg"))
    lines += ["", "# outputs (sha256  file)"] + [f"{h}  {f}" for h, f in outs]
    open(os.path.join(OUT, "SOURCE.txt"), "w").write("\n".join(lines) + "\n")
    print(f"{len(outs)} files, {sum(os.path.getsize(os.path.join(OUT, f)) for _, f in outs) / 1e6:.1f} MB")
    phone()


def phone_files():
    """The phone set's names: every map of a material larger than PHONE_PX, as <key>_<tag>_512.jpg."""
    return sorted(f"{k}_{t}_{PHONE_PX}.jpg" for k, (_, px) in MATERIALS.items() if px > PHONE_PX for t in ("col", "nor"))


def phone():
    """The phone set, from the 1024 px outputs already in the folder; its pins appended to SOURCE.txt (replaced if there).
      python3 tools/land_textures.py --phone"""
    from PIL import Image
    outs = []
    for f in phone_files():
        big = f.replace(f"_{PHONE_PX}.jpg", ".jpg")
        im = Image.open(os.path.join(OUT, big)).convert("RGB").resize((PHONE_PX, PHONE_PX), Image.LANCZOS)
        path = os.path.join(OUT, f)
        im.save(path, "JPEG", quality=QUALITY, optimize=True, progressive=True)
        outs.append((hashlib.sha256(open(path, "rb").read()).hexdigest(), f))
    src = open(os.path.join(OUT, "SOURCE.txt")).read().split("\n# phone")[0].rstrip("\n")
    head = f"# phone ({PHONE_PX} px, made from the outputs above; sha256  file)"
    open(os.path.join(OUT, "SOURCE.txt"), "w").write(src + "\n\n" + head + "\n" + "\n".join(f"{h}  {f}" for h, f in outs) + "\n")
    print(f"phone: {len(outs)} files, {sum(os.path.getsize(os.path.join(OUT, f)) for _, f in outs) / 1e6:.2f} MB")


if __name__ == "__main__":
    phone() if sys.argv[1:] == ["--phone"] else main()
