"""
NADO logo — the "impossible" faceted torus, generated as SVG.

A face-on decagonal ring whose 10 segments are isometric cubes, each rotated to follow the ring so the shading
repeats per-segment (an impossible / M.C.-Escher isometric object, not a plausible tilted torus). The cube
weave is clipped to a clean decagon annulus so the mark reads as a solid tube with crisp inner/outer edges.

Regenerate / add schemes:  python3 graphics/svg/generate.py graphics/svg
"""
import math, colorsys, sys, os

def _hexrgb(c): return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
def _hx(rgb): return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)
def shade(base, f): r, g, b = _hexrgb(base); return _hx((r * f, g * f, b * f))
def hsl(h, s, l): r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s); return _hx((r * 255, g * 255, b * 255))

def _rot(p, a, c):
    x, y = p[0] - c[0], p[1] - c[1]; ca, sa = math.cos(a), math.sin(a)
    return (c[0] + x * ca - y * sa, c[1] + x * sa + y * ca)

def _decagon(cx, cy, r, N, rot=-math.pi / 2):
    return [(cx + r * math.cos(i * 2 * math.pi / N + rot), cy + r * math.sin(i * 2 * math.pi / N + rot)) for i in range(N)]

def _isocube(cx, cy, s, ang, top, right, left, outline, sw):
    k = 0.8660254
    H = [(0, -s), (k * s, -0.5 * s), (k * s, 0.5 * s), (0, s), (-k * s, 0.5 * s), (-k * s, -0.5 * s)]
    H = [_rot((cx + x, cy + y), ang, (cx, cy)) for x, y in H]
    C = (cx, cy)
    out = []
    for pts, fill in (([H[0], H[1], C, H[5]], top), ([H[1], H[2], H[3], C], right), ([H[5], C, H[3], H[4]], left)):
        p = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        out.append(f'<polygon points="{p}" fill="{fill}" stroke="{outline}" stroke-width="{sw:.2f}" stroke-linejoin="round"/>')
    return out

def build(base, outline, N=10, Rc=72, s=44, size=256):
    cx = cy = size / 2
    Rout, Rin = Rc + s * 0.70, max(6, Rc - s * 0.60)
    outer, inner = _decagon(cx, cy, Rout, N), _decagon(cx, cy, Rin, N)
    annulus = ("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in outer) + "Z "
               "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in reversed(inner)) + "Z")
    sw = s * 0.05
    rainbow = (base == "rainbow")
    basecolor = (lambda i: hsl(i / N, 0.62, 0.52)) if rainbow else (lambda i: base)
    backing = "#181b20" if rainbow else shade(base, 0.95)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">']
    out.append(f'<defs><clipPath id="ring"><path d="{annulus}" fill-rule="evenodd"/></clipPath></defs>')
    out.append(f'<path d="{annulus}" fill-rule="evenodd" fill="{backing}"/>')
    out.append('<g clip-path="url(#ring)">')
    for i in range(N):
        th = i * 2 * math.pi / N - math.pi / 2
        px, py = cx + Rc * math.cos(th), cy + Rc * math.sin(th)
        b = basecolor(i)
        out += _isocube(px, py, s, th + math.pi / 2, shade(b, 1.30), shade(b, 0.95), shade(b, 0.60), outline, sw)
    out.append('</g>')
    out.append(f'<path d="{annulus}" fill-rule="evenodd" fill="none" stroke="{outline}" stroke-width="{sw * 1.4:.2f}" stroke-linejoin="round"/>')
    out.append('</svg>')
    return "\n".join(out)

SCHEMES = {
    "teal":       ("#12a683", "#06352d"),   # brand
    "ocean":      ("#1f8fd6", "#0a2c46"),
    "violet":     ("#8a5cf0", "#251242"),
    "magenta":    ("#e0559f", "#3f1030"),
    "crimson":    ("#e2584a", "#3a1210"),
    "amber":      ("#e8a033", "#3f2607"),
    "lime":       ("#7dc93a", "#1e3a0d"),
    "gold":       ("#d9a92e", "#3a2a08"),
    "graphite":   ("#8a929b", "#1a1e23"),   # monochrome, light bg
    "mono-light": ("#c2c8cf", "#5b636b"),   # white-ish, for dark bg
    "rainbow":    ("rainbow", "#0c1013"),
}

if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, (base, outline) in SCHEMES.items():
        open(os.path.join(outdir, f"logo-{name}.svg"), "w").write(build(base, outline))
    print("wrote", len(SCHEMES), "schemes to", outdir)
