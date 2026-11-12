#!/usr/bin/env python3
"""Offline converter (#172 step 2): MakeHuman's CC0 hair and eyebrow proxies -> static/human/wear.bin + their textures.

    python3 tools/human/build_wear.py [<makehuman data dir>] [static/human]

Reads the MakeHuman 1.2.0 data tree mirrored at /root/land-research/human/mh-release/exe/makehuman/data (the packaged
release's assets, CC0 1.0 — LICENSE.md section C there; land research INDEX.md "human"): 3dobjs/base.npz (the hm08 base
mesh, 19,158 vertices with the helpers, in decimetres), targets.npz (the macro targets the body's three builds are made
of — the same three True Wind's crew.bin was built from), rigs/default.mhskel and default_weights.mhw, and for each item
<kind>/<name>/<name>.npz (its mesh: coord, fvert quads, texco, fuvs) + .mhpxy (the PROXY: each of its vertices is a
weighted mix of three base vertices plus an offset scaled per axis by the distance between two base vertices — MakeHuman's
own fitting rule, shared/proxy.py getCoords/getMatrix, re-implemented here) + its diffuse texture.

Writes one binary the page reads beside crew.bin (static/land-human-data.js parseWear): 'NHW1', u32 json length, json,
then the buffers. Per item: the vertices SPLIT by (vertex, uv) so each carries one uv; positions per build (the proxy
fitted to each build's base mesh, int16 × posScale, metres, the body's own frame); normals per build; four bone indices
and weights on the 21-bone game skeleton (the base vertices' weights, merged as True Wind merges them, mixed by the
proxy's own weights); a triangle index; the texture's file. Textures: the diffuse PNG at 512², RGBA (hair is cards with
alpha), tinted on the page by the look's hair colour.
"""
import json, os, struct, sys
import numpy as np
from PIL import Image

SRC = sys.argv[1] if len(sys.argv) > 1 else "/root/land-research/human/mh-release/exe/makehuman/data"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static", "human")
ITEMS = [("hair", n) for n in ["short02", "short04", "bob02", "long01", "ponytail01", "afro01", "braid01"]] + [("eyebrows", "eyebrow001")]
# GARMENTS (#172 step 3): MakeHuman's t-shirt-and-jeans outfits (one mesh each; the page splits it at the waist into the
# wardrobe's body and legs slots by the vertex's part) and a pair of shoes; casualsuit04 is the lightest male outfit
# (1,696 vertices), casualsuit01 the female one (2,197)
ITEMS += [("clothes", "male_casualsuit04"), ("clothes", "female_casualsuit01"), ("clothes", "shoes01")]
PART_TOP, PART_LEGS, PART_SHOES, PART_NONE = 0, 1, 2, 255
VARIANTS = [("male", "caucasian-male-young"), ("female", "caucasian-female-young"), ("heavy", "african-male-young")]
DM = 0.1                                   # MakeHuman works in decimetres; the body (crew.bin) is in metres
TEX = 512

# ---- the base mesh and its three builds
base = np.load(os.path.join(SRC, "3dobjs", "base.npz"), allow_pickle=False)
V0 = base["coord"].astype(np.float64)
T = np.load(os.path.join(SRC, "targets.npz"), allow_pickle=False)   # (the macro targets are plain arrays; the archive's other entries, pickled, are never touched)
def build(name):
    V = V0.copy()
    idx, vec = T["targets/macrodetails/%s.index" % name], T["targets/macrodetails/%s.vector" % name]
    V[idx] += vec / 1000.0                   # (compiled as int16 thousandths of a decimetre: core/algos3d.py, round(data * 1e3))
    return V
VB = [build(t) for _, t in VARIANTS]

# ---- the game skeleton's weights on every base vertex (True Wind's merge of MakeHuman's 163 bones into 21)
skel = json.load(open(os.path.join(SRC, "rigs", "default.mhskel")))
mhw = json.load(open(os.path.join(SRC, "rigs", "default_weights.mhw")))["weights"]
BONES = ["hips", "spine", "chest", "neck", "head", "shoulder.L", "shoulder.R", "upperarm.L", "upperarm.R", "forearm.L", "forearm.R",
         "hand.L", "hand.R", "fingers.L", "fingers.R", "thigh.L", "thigh.R", "shin.L", "shin.R", "foot.L", "foot.R"]
DIRECT = {"root": "hips", "pelvis.L": "hips", "pelvis.R": "hips", "spine05": "spine", "spine04": "spine", "spine03": "spine",
          "spine02": "chest", "spine01": "chest", "breast.L": "chest", "breast.R": "chest", "neck01": "neck", "neck02": "neck", "neck03": "neck", "head": "head"}
for s in "LR":
    DIRECT.update({"clavicle." + s: "shoulder." + s, "shoulder01." + s: "shoulder." + s, "upperarm01." + s: "upperarm." + s, "upperarm02." + s: "upperarm." + s,
                   "lowerarm01." + s: "forearm." + s, "lowerarm02." + s: "forearm." + s, "wrist." + s: "hand." + s, "upperleg01." + s: "thigh." + s,
                   "upperleg02." + s: "thigh." + s, "lowerleg01." + s: "shin." + s, "lowerleg02." + s: "shin." + s, "foot." + s: "foot." + s})
    for k in range(1, 5): DIRECT["metacarpal%d.%s" % (k, s)] = "hand." + s
    for j in range(1, 4): DIRECT["finger1-%d.%s" % (j, s)] = "hand." + s
    for f in range(2, 6):
        for j in range(1, 4): DIRECT["finger%d-%d.%s" % (f, j, s)] = "fingers." + s
def game_bone(b):
    while b not in DIRECT: b = skel["bones"][b]["parent"]
    return DIRECT[b]
BI = {b: i for i, b in enumerate(BONES)}
W = np.zeros((len(V0), len(BONES)))
for b, lst in mhw.items():
    gb = BI[game_bone(b)]
    for vi, w in lst:
        if vi < len(V0): W[vi, gb] += w
W /= np.maximum(W.sum(1, keepdims=True), 1e-9)

# ---- the body's frame: crew.bin's rest is the base mesh × DM with its feet at y = 0? Read what build_crew did: the
# hips/feet of crew.bin's male build against the base mesh, so the hair lands on the body the page draws
crew_path = os.path.join(OUT, "crew.bin")
with open(crew_path, "rb") as f:
    hdr_len = struct.unpack("<I", f.read(8)[4:])[0]
    crew = json.loads(f.read(hdr_len))
head_joint = {v["name"]: np.array(v["heads"][BI["head"]]) for v in crew["variants"]}
hips_joint = {v["name"]: np.array(v["heads"][BI["hips"]]) for v in crew["variants"]}
# the base mesh's head joint (the 'head' bone's head) in the same units, to find the frame shift
def joint(P, name): return P[skel["joints"][name]].mean(0)
shift = []
for (vname, _), V in zip(VARIANTS, VB):
    j = joint(V, "head____head") * DM
    shift.append(head_joint[vname] - j)                 # what build_crew added to the base coordinates (its floor and centring)
shift = np.array(shift)

# ---- the items
def fit(pxy, V):
    """The proxy's vertices on base mesh V: Σ weights·V[refs] + diag(scale)·offset (MakeHuman's getCoords)."""
    refs, w, off = pxy["ref_vIdxs"].astype(np.int64), pxy["weights"].astype(np.float64), pxy["offsets"].astype(np.float64)
    P = V[refs[:, 0]] * w[:, 0:1] + V[refs[:, 1]] * w[:, 1:2] + V[refs[:, 2]] * w[:, 2:3]
    sc, si = pxy["tmat_scale"].astype(np.float64), pxy["tmat_scale_idx"].astype(np.int64)
    m = np.ones(3)
    for n in range(3):
        if np.isfinite(sc[n]) and sc[n] > 0:
            m[n] = abs(V[si[2 * n], n] - V[si[2 * n + 1], n]) / sc[n]
    return P + off * m

items, blobs, off = [], [], 0
def put(arr):
    global off
    b = np.ascontiguousarray(arr).tobytes()
    pad = (-len(b)) % 4
    blobs.append(b + b"\0" * pad)
    o = off; off += len(b) + pad
    return [o, len(b)]
for kind, name in ITEMS:
    d = os.path.join(SRC, kind, name)
    mesh = np.load(os.path.join(d, name + ".npz"), allow_pickle=False)
    pxy = np.load(os.path.join(d, name + ".mhpxy"), allow_pickle=False)
    fv, fu, tex = mesh["fvert"].astype(np.int64), mesh["fuvs"].astype(np.int64), mesh["texco"].astype(np.float64)
    # split by (vertex, uv): one output vertex per pair, in the order met; faces as triangles (a quad with a repeated
    # corner is a triangle)
    pairs, pid, tris = {}, [], []
    def vid(v, u):
        k = (int(v), int(u))
        if k not in pairs: pairs[k] = len(pid); pid.append(k)
        return pairs[k]
    for f in range(len(fv)):
        c = [vid(fv[f, k], fu[f, k]) for k in range(4)]
        if fv[f, 3] == fv[f, 2] or fv[f, 3] == fv[f, 0]: tris.append([c[0], c[1], c[2]])
        else: tris += [[c[0], c[1], c[2]], [c[0], c[2], c[3]]]
    tris = np.array(tris, dtype=np.int64)
    src_v = np.array([k[0] for k in pid]); src_u = np.array([k[1] for k in pid])
    nV = len(pid)
    uv = np.clip(tex[src_u], 0, 1).astype(np.float32)                  # (MakeHuman's v runs up from the bottom, as three.js's flipY textures read it; a few run 0.3 % past the edge)
    # weights: the three reference vertices' game-bone weights, mixed by the proxy's own weights, top four kept
    refs, pw = pxy["ref_vIdxs"].astype(np.int64), pxy["weights"].astype(np.float64)
    Wv = (W[refs[:, 0]] * pw[:, 0:1] + W[refs[:, 1]] * pw[:, 1:2] + W[refs[:, 2]] * pw[:, 2:3])[src_v]
    top = np.argsort(-Wv, axis=1)[:, :4]
    skinI = top.astype(np.uint8); skinW = np.take_along_axis(Wv, top, axis=1); skinW /= np.maximum(skinW.sum(1, keepdims=True), 1e-9)
    skinW8 = np.clip(np.round(skinW * 255), 0, 255).astype(np.uint8)
    variants, scale = [], 0.0
    posv = []
    for vi, (vname, _) in enumerate(VARIANTS):
        P = fit(pxy, VB[vi])[src_v] * DM + shift[vi]
        posv.append(P); scale = max(scale, float(np.abs(P).max()))
    # the part each vertex belongs to: an outfit splits at the waist — a vertex under the hips joint less 8 cm (the
    # jeans' waistband; the shirt's hem hangs over it) is the trousers, over it the shirt; shoes are shoes; hair none
    if kind == "clothes" and name.startswith("shoes"): part = np.full(nV, PART_SHOES, np.uint8)
    elif kind == "clothes": part = np.where(posv[0][:, 1] < hips_joint["male"][1] - 0.08, PART_LEGS, PART_TOP).astype(np.uint8)
    else: part = np.full(nV, PART_NONE, np.uint8)
    posScale = scale / 32000.0
    for vi, (vname, _) in enumerate(VARIANTS):
        P = posv[vi]
        # normals, area-weighted over the triangles
        N = np.zeros((nV, 3))
        a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
        fn = np.cross(b - a, c - a)
        for k in range(3): np.add.at(N, tris[:, k], fn)
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        variants.append({"name": vname, "pos": put(np.round(P / posScale).astype(np.int16)), "nrm": put(N.astype(np.float32))})
    # the texture: the diffuse PNG at TEX², RGBA
    mat = open(os.path.join(d, name + ".mhmat")).read()
    texname = next((ln.split()[1] for ln in mat.splitlines() if ln.startswith("diffuseTexture")), None)
    im = Image.open(os.path.join(d, texname)).convert("RGBA").resize((TEX, TEX), Image.LANCZOS)
    texfile = "%s_%s.png" % (kind, name)
    im.save(os.path.join(OUT, texfile), optimize=True)
    # the texture's mean brightness over its opaque texels: the page tints the hair by the player's hair colour as
    # colour × (texel luminance / lum), so the painted strands keep their light and dark and a dark texture does not
    # darken a blond choice (land-human.js wearMaterial)
    px = np.asarray(im, dtype=np.float64) / 255.0
    a = px[..., 3]
    lum = float(((0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]) * a).sum() / max(1e-6, a.sum()))
    # …and per PART for an outfit (the shirt and the jeans share one atlas: the jeans' dark texels pulled the shirt's
    # mean down and the shirt came out blotchy, 2026-11-12): the mean over the texels the part's vertices sample
    Lt = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
    tx_i = np.clip((uv[:, 0] * (TEX - 1)).round().astype(int), 0, TEX - 1); ty_i = np.clip(((1 - uv[:, 1]) * (TEX - 1)).round().astype(int), 0, TEX - 1)
    lums = []
    for pt in (PART_TOP, PART_LEGS, PART_SHOES):
        sel = part == pt
        lums.append(round(float(Lt[ty_i[sel], tx_i[sel]].mean()), 4) if sel.any() else round(lum, 4))
    items.append({"kind": kind, "name": name, "nV": nV, "nT": len(tris), "posScale": posScale, "variants": variants, "lum": round(lum, 4), "lums": lums,
                  "uv": put(uv.astype(np.float32)), "skinI": put(skinI), "skinW": put(skinW8),
                  "idx": put(tris.astype(np.uint16 if nV <= 65535 else np.uint32)), "idx32": nV > 65535, "tex": texfile, "part": put(part)})
    print("%s/%s: %d vertices, %d triangles, texture %s" % (kind, name, nV, len(tris), texfile))

hdr = {"version": 1, "bones": BONES, "items": items, "licence": "MakeHuman 1.2.0 assets (CC0 1.0 Universal, LICENSE.md section C): hair, eyebrow and clothes proxies fitted to the body's three builds by this converter"}
js = json.dumps(hdr, separators=(",", ":")).encode()
js += b" " * ((-len(js)) % 4)
with open(os.path.join(OUT, "wear.bin"), "wb") as f:
    f.write(b"NHW1"); f.write(struct.pack("<I", len(js))); f.write(js)
    for b in blobs: f.write(b)
print("wrote", os.path.join(OUT, "wear.bin"), os.path.getsize(os.path.join(OUT, "wear.bin")), "bytes;", len(items), "items")
