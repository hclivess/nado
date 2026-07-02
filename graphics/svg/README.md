# NADO logo — SVG

Vector rebuild of the NADO mark (the faceted 3D torus / the "O" in the wordmark), generated parametrically so
it stays crisp at any size and is trivial to recolor.

- `../logo.svg` — canonical brand logo (**teal**).
- `logo-<scheme>.svg` — color variants: `teal` (brand), `ocean`, `violet`, `magenta`, `crimson`, `amber`,
  `lime`, `gold`, `graphite` (monochrome, light bg), `mono-light` (white, for dark bg), and `rainbow`
  (per-segment hue).
- `../logo-schemes.png` — preview sheet of all schemes.

Transparent background, no external fonts/assets. Regenerate or add schemes with:

```
python3 graphics/svg/generate.py graphics/svg     # writes logo-<scheme>.svg for every scheme in SCHEMES
```

Each scheme is `(color-fn, outline)` in `generate.py`; `solid(dark, light)` shades every facet between two
hex colors by its 3D normal, so a new palette is one line.
