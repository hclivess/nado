"""
NADO logo — SVG color schemes.

The mark is a twisted-tube "impossible" ring of sheared parallelograms. Rather than re-derive that geometry by
hand (it's subtle, and the original is hand-drawn / not perfectly regular), the accurate shape is the vtracer
trace of graphics/180_logo.png, kept here as `logo-source.svg`. It is a single hue (teal) whose lightness does
the 3-D shading — so every other scheme is a faithful HUE SHIFT / desaturation of that real geometry.

Regenerate:  python3 graphics/svg/generate.py graphics/svg
"""
import re, colorsys, os, sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo-source.svg")

def recolor(svg, hue=None, sat_set=None, light_add=0.0):
    def repl(m):
        c = m.group(1)
        r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        if s >= 0.06:                       # leave the near-neutral outline alone; recolor the teal facets
            if hue is not None:
                h = hue / 360.0
            if sat_set is not None:
                s = sat_set
        l = min(1.0, max(0.0, l + light_add))
        rr, gg, bb = colorsys.hls_to_rgb(h, l, s)
        return 'fill="#%02x%02x%02x"' % (round(rr * 255), round(gg * 255), round(bb * 255))
    return re.sub(r'fill="#([0-9a-fA-F]{6})"', repl, svg)

# hue in degrees (teal ≈ 168° = identity); or desaturate for the mono schemes
SCHEMES = {
    "teal":       dict(),                              # brand (unchanged trace)
    "ocean":      dict(hue=205),
    "violet":     dict(hue=266),
    "magenta":    dict(hue=322),
    "crimson":    dict(hue=6),
    "amber":      dict(hue=38),
    "lime":       dict(hue=92),
    "gold":       dict(hue=45),
    "graphite":   dict(sat_set=0.05),                  # monochrome, light bg
    "mono-light": dict(sat_set=0.04, light_add=0.18),  # lighter, for dark bg
}

if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    src = open(SRC).read()
    for name, kw in SCHEMES.items():
        open(os.path.join(outdir, f"logo-{name}.svg"), "w").write(recolor(src, **kw))
    print("wrote", len(SCHEMES), "schemes to", outdir)
