import math, colorsys

def norm(v):
    m = math.sqrt(sum(c*c for c in v)) or 1.0
    return (v[0]/m, v[1]/m, v[2]/m)
def sub(a,b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def cross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def dot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def rotx(p,a):
    x,y,z=p; c,s=math.cos(a),math.sin(a); return (x, y*c - z*s, y*s + z*c)
def torus(u,v,R,r):
    return ((R+r*math.cos(v))*math.cos(u), (R+r*math.cos(v))*math.sin(u), r*math.sin(v))
def hx(rgb): return "#%02x%02x%02x" % tuple(max(0,min(255,round(c))) for c in rgb)
def hexrgb(c): return tuple(int(c[i:i+2],16) for i in (1,3,5))
def lerp(c1,c2,t):
    a,b=hexrgb(c1),hexrgb(c2); return hx(tuple(a[i]+(b[i]-a[i])*t for i in range(3)))
def hsl(h,s,l):
    r,g,b=colorsys.hls_to_rgb(h%1.0, l, s); return hx((r*255,g*255,b*255))

# color: fn(segment_i, intensity) -> fill hex
def solid(dark, light):
    return lambda i, t: lerp(dark, light, 0.12 + 0.88*t)
def rainbow(sat=0.62):
    return lambda i, t: hsl(i/10.0, sat, 0.22 + 0.55*t)

def build(colorfn, outline, N=10, M=9, R=1.0, r=0.52, tilt=36, size=256, pad=16, sw=1.1):
    tilt = math.radians(tilt)
    L = norm((-0.42,-0.78,0.66)); view=(0,0,1)
    faces=[]
    for i in range(N):
        for j in range(M):
            u0,u1=i*2*math.pi/N,(i+1)*2*math.pi/N
            v0,v1=j*2*math.pi/M,(j+1)*2*math.pi/M
            P=[rotx(torus(u,v,R,r),tilt) for (u,v) in ((u0,v0),(u1,v0),(u1,v1),(u0,v1))]
            n=norm(cross(sub(P[1],P[0]),sub(P[3],P[0])))
            if dot(n,view)<=0.02: continue
            faces.append((sum(p[2] for p in P)/4.0, P, max(0.0,dot(n,L)), i))
    faces.sort(key=lambda f:f[0])
    xs=[p[0] for _,P,_,_ in faces for p in P]; ys=[-p[1] for _,P,_,_ in faces for p in P]
    minx,maxx,miny,maxy=min(xs),max(xs),min(ys),max(ys)
    sc=(size-2*pad)/max(maxx-minx,maxy-miny)
    ox=(size-(maxx-minx)*sc)/2-minx*sc; oy=(size-(maxy-miny)*sc)/2-miny*sc
    proj=lambda p:(p[0]*sc+ox,(-p[1])*sc+oy)
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">']
    for _,P,inten,i in faces:
        pts=" ".join(f"{x:.2f},{y:.2f}" for x,y in (proj(p) for p in P))
        out.append(f'<polygon points="{pts}" fill="{colorfn(i,inten)}" stroke="{outline}" stroke-width="{sw}" stroke-linejoin="round"/>')
    out.append('</svg>')
    return "\n".join(out)

SCHEMES = {
    "teal":     (solid("#063f38","#37d6ab"), "#052c28"),   # brand
    "ocean":    (solid("#0a2f57","#45b6ef"), "#061d38"),
    "violet":   (solid("#33165c","#b884f2"), "#1f0d3a"),
    "magenta":  (solid("#4e0f39","#ff77c2"), "#2f0722"),
    "crimson":  (solid("#5a1220","#ff7a6b"), "#350a12"),
    "amber":    (solid("#6b2f0e","#ffc24a"), "#3c1806"),
    "lime":     (solid("#173d10","#9fe84a"), "#0d2409"),
    "graphite": (solid("#23282d","#c4ccd4"), "#12151a"),   # monochrome (light bg)
    "mono-light": (solid("#5b636b","#ffffff"), "#3a3f45"), # for dark bg
    "gold":     (solid("#5a3d0a","#ffe08a"), "#33220a"),
    "rainbow":  (rainbow(), "#111318"),
}

if __name__ == "__main__":
    import sys, subprocess, os
    outdir = sys.argv[1] if len(sys.argv)>1 else "."
    for name,(cf,ol) in SCHEMES.items():
        svg = build(cf, ol)
        open(os.path.join(outdir, f"logo-{name}.svg"),"w").write(svg)
    print("wrote", len(SCHEMES), "schemes")
