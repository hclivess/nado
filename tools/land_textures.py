#!/usr/bin/env python3
"""Build Land's material textures (static/vendor/textures/) from Poly Haven originals — CC0 1.0 (public domain), no
attribution required, recorded anyway in SOURCE.txt. "Realistic (PBR)" was the operator's choice (2026-11-06).

Each material has a colour map and an OpenGL normal map, re-encoded smaller for the browser: the ground's six at 1024 px
(seen up close, underfoot), building materials and bark at 512 px; JPEG quality 82. Roughness is a constant per material
in static/land.js (its maps were 5 MB of the first 32). SOURCE.txt records every original's URL and MD5 (as Poly Haven
publishes them) and every output's SHA-256; tests/test_the_land_textures_are_the_recorded_cc0_sources.py pins them.

  python3 tools/land_textures.py <dir of originals named <asset>__Diffuse.jpg / <asset>__nor_gl.jpg> <plan.json>
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
}
QUALITY = 82


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
            if hashlib.md5(data).hexdigest() != md5:
                raise SystemExit(f"{asset} {kind}: the original does not match Poly Haven's MD5")
            lines.append(f"{url} {md5}")
            im = Image.open(os.path.join(src, f"{asset}__{kind}.jpg")).convert("RGB").resize((px, px), Image.LANCZOS)
            path = os.path.join(OUT, f"{key}_{tag}.jpg")
            im.save(path, "JPEG", quality=QUALITY, optimize=True, progressive=True)
            outs.append((hashlib.sha256(open(path, "rb").read()).hexdigest(), f"{key}_{tag}.jpg"))
    lines += ["", "# outputs (sha256  file)"] + [f"{h}  {f}" for h, f in outs]
    open(os.path.join(OUT, "SOURCE.txt"), "w").write("\n".join(lines) + "\n")
    print(f"{len(outs)} files, {sum(os.path.getsize(os.path.join(OUT, f)) for _, f in outs) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
