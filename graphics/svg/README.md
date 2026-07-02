# NADO logo — SVG

The NADO mark is a twisted-tube "impossible" ring of sheared parallelograms. Rather than re-derive that subtle
geometry by hand, the accurate shape is a **vtracer trace of `graphics/180_logo.png`**, kept here as
**`logo-source.svg`** — so it faithfully matches the real logo.

The trace is a single hue (teal) whose *lightness* does the 3-D shading, so every other scheme is a faithful
**hue shift / desaturation** of that real geometry (not a redraw).

- `../logo.svg` — canonical brand logo (**teal**, = `logo-source.svg`).
- `logo-<scheme>.svg` — color variants: `teal` (brand), `ocean`, `violet`, `magenta`, `crimson`, `amber`,
  `lime`, `gold`, `graphite` (monochrome, light bg), `mono-light` (white, for dark bg).
- `logo-source.svg` — the traced ground-truth.
- `../logo-schemes.png` — preview sheet of all schemes.

Transparent background, no external fonts/assets. Regenerate or add a scheme (a hue in degrees, or a
desaturation) in one line of `generate.py`:

```
python3 graphics/svg/generate.py graphics/svg     # recolors logo-source.svg for every scheme in SCHEMES
```
