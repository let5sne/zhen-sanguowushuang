#!/usr/bin/env python3
"""角色骨骼绑定 / 蒙皮 / 动画 clip 的 Blender 生成脚本（唯一来源）。

运行：
    /Applications/Blender.app/Contents/MacOS/Blender -b -P scripts/blender/build_rig.py

它会读 demos/index.html、重建其中的 SKIN_B64（骨骼层级、四槽权重、bind pose、
10 个动画 clip），并只写回 demos/index.html。

demos/index.html 末尾的 BLENDER_RIG_PY 注释块是本文件的内嵌副本（为守住「单文件」
约束）。二者一致性用 --sync 维护：
    python3 scripts/blender/build_rig.py --sync     # 把本文件回写进产物
    python3 scripts/blender/build_rig.py --check    # 只校验（默认）
"""

import sys as _sys
from pathlib import Path as _Path


def _embedded_block(html):
    start = "<!-- BLENDER_RIG_PY\n"
    if start not in html:
        return None
    return html.split(start, 1)[1].split("\nEND_BLENDER_RIG", 1)[0]


_BODY_SENTINEL = "# ---- Blender body (below this line is embedded into demos/index.html) ----"


def _body():
    raw = _Path(__file__).read_text()
    return raw.split(_BODY_SENTINEL + "\n", 1)[1]


def _sync_or_check():
    target = _Path(__file__).resolve().parents[2] / "demos/index.html"
    html = target.read_text()
    embedded = _embedded_block(html)
    body = _body()
    if embedded is None:
        print("[FAIL] 产物里没有 BLENDER_RIG_PY 块")
        return 1
    if embedded.strip() == body.strip():
        print("[OK] 内嵌绑定脚本与 scripts/blender/build_rig.py 一致")
        return 0
    if "--sync" in _sys.argv:
        new = html.replace("<!-- BLENDER_RIG_PY\n" + embedded + "\nEND_BLENDER_RIG",
                           "<!-- BLENDER_RIG_PY\n" + body.rstrip("\n") + "\nEND_BLENDER_RIG", 1)
        target.write_text(new)
        print("[SYNC] 已把 scripts/blender/build_rig.py 回写进 demos/index.html")
        return 0
    print("[FAIL] 内嵌绑定脚本与 scripts/blender/build_rig.py 不一致；"
          "运行 `python3 scripts/blender/build_rig.py --sync` 同步")
    return 1


if "--sync" in _sys.argv or "--check" in _sys.argv:
    _sys.exit(_sync_or_check())

# Blender entry point: extract this comment and pass its text to blender --background --factory-startup --python-expr.
# It updates only demos/index.html. Original build_geometry.py GEO_B64 remains backward-readable.
# ---- Blender body (below this line is embedded into demos/index.html) ----
import base64
import json
import math
import re
import struct
from pathlib import Path
import bpy

path = Path.cwd() / "demos/index.html"
html = path.read_text()
source = html.split("const GEO_B64 = {", 1)[1].split("\n};", 1)[0]
parts = {}
for line in source.splitlines():
    if ":" not in line:
        continue
    name, encoded = line.strip().split(":", 1)
    encoded = encoded.strip().rstrip(",").strip('"')
    binary = base64.b64decode(encoded)
    nv, nt = struct.unpack_from("<II", binary)
    pos = [struct.unpack_from("<fff", binary, 8 + i * 12) for i in range(nv)]
    colors = [struct.unpack_from("<BBBB", binary, 8 + nv * 12 + i * 4) for i in range(nv)]
    faces = [struct.unpack_from("<HHH", binary, 8 + nv * 16 + i * 6) for i in range(nt)]
    if name in {"torso", "skirt", "arm", "leg", "head"}:
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(pos, [], faces)
        mesh.update()
        attribute = mesh.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
        for i, color in enumerate(colors):
            attribute.data[i].color = tuple(value / 255 for value in color)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        modifier = obj.modifiers.new("Preserve bevel silhouette", "DECIMATE")
        modifier.ratio = .42
        modifier.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        mesh = obj.data
        mesh.calc_loop_triangles()
        pos = [tuple(vertex.co) for vertex in mesh.vertices]
        colors = [tuple(max(0, min(255, round(value * 255))) for value in color.color) for color in mesh.color_attributes["Col"].data]
        faces = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    # Thin, beveled weapons are retained intact: decimating them destroys their silhouette.
    parts[name] = (pos, colors, faces)

parents = [255,0,1,2,3,4,3,6,7,8,3,10,11,12,1,14,15,1,17,18,13]
local = [(0,0,0),(0,.92,0),(0,.22,0),(0,.25,0),(0,.17,0),(0,.11,0),(-.29,.11,0),(0,0,0),(0,-.30,0),(0,-.255,0),(.29,.11,0),(0,0,0),(0,-.30,0),(0,-.255,0),(-.125,-.02,0),(0,-.42,0),(0,-.39,.035),(.125,-.02,0),(0,-.42,0),(0,-.39,.035),(0,-.02,0)]
world = []
for i, point in enumerate(local):
    world.append(tuple(value + (world[parents[i]][axis] if parents[i] != 255 else 0) for axis, value in enumerate(point)))
clips = []
def add_clip(name, duration, poses, loop=False, hit=None):
    tracks = []
    for joint, axis, values in poses:
        keys = []
        for time, angle in values:
            quaternion = [0.,0.,0.,math.cos(angle / 2)]
            quaternion[axis] = math.sin(angle / 2)
            keys.append((round(time * 65535), quaternion))
        tracks.append((joint, 1, keys))
    clips.append((name, duration, loop, hit, tracks))

wave = [(0,0),(.25,.62),(.5,0),(.75,-.62),(1,0)]
add_clip("idle",2.4,[(2,0,[(0,0),(.5,.018),(1,0)]),(11,0,[(0,-.48),(.5,-.50),(1,-.48)]),(11,2,[(0,.2),(1,.2)])],True)
for name, duration, amplitude in [("walk",.76,.58),("run",.50,.90)]:
    add_clip(name,duration,[(14,0,[(t,v*amplitude/.62) for t,v in wave]),(17,0,[(t,-v*amplitude/.62) for t,v in wave]),(7,0,[(t,-v*.7) for t,v in wave]),(11,0,[(t,-.5+v*.3) for t,v in wave]),(15,0,[(0,0),(.25,.55),(.5,0),(.75,.05),(1,0)]),(18,0,[(0,0),(.25,.05),(.5,0),(.75,.55),(1,0)])],True)
for index in range(3):
    add_clip("atk"+str(index+1),.4,[(11,0,[(0,-.48),(.25,-2.15),(.4,-1.3),(.56,.8),(1,-.48)]),(11,2,[(0,.2),(.25,.65),(.4,.4),(.56,-.6),(1,.2)]),(3,1,[(0,0),(.25,-.6 if index!=1 else .6),(.4,-.3),(.56,.7),(1,0)]),(12,0,[(0,0),(.25,-.35),(.4,-.25),(.56,0),(1,0)])],False,.4)
add_clip("heavy",.68,[(11,0,[(0,-.48),(.3,-2.8),(.46,-1.5),(.58,1.1),(1,-.48)]),(3,0,[(0,0),(.3,-.25),(.46,0),(.58,.3),(1,0)]),(3,1,[(0,0),(.3,-.9),(.46,-.3),(.58,.9),(1,0)])],False,.46)
add_clip("hit",.35,[(2,0,[(0,0),(.3,-.3),(1,0)]),(7,0,[(0,0),(.3,-.8),(1,0)])])
add_clip("die",.85,[(2,0,[(0,0),(.3,-.35),(1,-.55)]),(7,2,[(0,0),(1,-.5)]),(11,2,[(0,.2),(1,.65)])])
add_clip("musou",1.05,[(11,2,[(0,.2),(.25,1.35),(.75,1.35),(1,.2)]),(3,1,[(0,0),(.25,.2),(.5,0),(.75,-.2),(1,0)])],True)

def surface(color):
    red, green, blue = [value / 255 for value in color[:3]]
    if min(red,green,blue) > .65 or (red > .8 and green > .4 and blue < .3):
        return 1
    if red > .3 and red > green * 1.3 and green > blue * 1.2:
        return 2
    return 3 if max(red,green,blue) < .2 else 0

assets = {}
for variant, weapon in [("hero","spear"),("dao","dao"),("spear","spear"),("archer","bow"),("officer","halberd")]:
    vertices, colors, triangles, surfaces, weights = [], [], [], [], []
    configs = [("torso",(0,.92,0),None),("skirt",(0,.90,0),1),("head",(0,.92,0),5),("arm",(-.29,1.5,0),7),("arm",(.29,1.5,0),11),("leg",(-.125,.90,0),14),("leg",(.125,.90,0),17),(weapon,world[20],20)]
    if variant in {"hero","officer"}:
        configs.append(("plume",(0,.94,0),5))
    for name, offset, joint in configs:
        positions, source_colors, faces = parts[name]
        start = len(vertices)
        for position, color in zip(positions, source_colors):
            v = [position[axis] + offset[axis] for axis in range(3)]
            if joint == 20 and weapon in {"spear","halberd"}:
                dy, dz = v[1]-world[20][1], v[2]-world[20][2]
                v[1] = world[20][1]+dy*math.cos(1.05)-dz*math.sin(1.05)
                v[2] = world[20][2]+dy*math.sin(1.05)+dz*math.cos(1.05)
            vertices.append(v)
            category = surface(color)
            surfaces.append(category)
            colors.append([209,214,219,255] if variant=="hero" and category==0 else list(color))
            if variant == "hero" and name == "plume":
                colors[-1], surfaces[-1] = [107,4,2,255], 0
            if joint is None:
                t = max(0,min(1,(v[1]-1.06)/.32))
                weight = {1:1-t,3:t}
            elif joint in {7,11}:
                t = max(0,min(1,(1.25-v[1])/.12))
                weight = {joint:1-t,joint+1:t}
                if v[1] < 1.02:
                    weight = {joint+1:1}
                if v[1] < .99:
                    weight = {joint+2:1}
            elif joint in {14,17}:
                t = max(0,min(1,(.56-v[1])/.18))
                weight = {joint:1-t,joint+1:t}
                if v[1] < .12:
                    weight = {joint+2:1}
            else:
                weight = {joint:1}
            weights.append(weight)
        triangles.extend(tuple(start+i for i in face) for face in faces)
    if variant in {"hero","officer"}:
        start = len(vertices)
        cloak_vertices, cloak_faces = [], []
        for row in range(11):
            t = row / 10
            for column in range(9):
                u = column / 8 * 2 - 1
                cloak_vertices.append((u*(.26+.22*t),1.48-1.08*t,-.19-.26*t*t+math.sin(u*math.pi*3)*.035*t))
        for row in range(10):
            for column in range(8):
                i = row*9+column
                cloak_faces.extend([(i,i+9,i+1),(i+1,i+9,i+10)])
        cloak = bpy.data.meshes.new("Draped campaign cloak")
        cloak.from_pydata(cloak_vertices,[],cloak_faces)
        cloak.update()
        cloak.calc_loop_triangles()
        for vertex in cloak.vertices:
            point = tuple(vertex.co)
            vertices.append(point)
            colors.append([212,218,224,255] if variant=="hero" else [85,8,5,255])
            surfaces.append(0)
            t = max(0,min(1,(point[1]-.4)/1.08))
            weights.append({3:t,1:1-t})
        triangles.extend(tuple(start+i for i in triangle.vertices) for triangle in cloak.loop_triangles)
    nv, nt = len(vertices), len(triangles)
    assert nt <= 3500 and len(parents) <= 24
    binary = bytearray(struct.pack("<II",nv,nt))
    for vertex in vertices:
        binary += struct.pack("<fff",*vertex)
    for color in colors:
        binary += bytes(color)
    for triangle in triangles:
        binary += struct.pack("<HHH",*triangle)
    binary += bytes([len(parents)]) + bytes(parents)
    joints, packed_weights = [], []
    for weight_index, weight in enumerate(weights):
        groups = [(joint,value) for joint,value in weight.items() if value>0 or (variant in {"hero","officer"} and weight_index>=nv-99)]
        total = sum(value for joint,value in groups)
        packed = [(joint,round(value/total*255)) for joint,value in groups]
        joint, value = packed[0]
        packed[0] = (joint,value+255-sum(value for joint,value in packed))
        joints.extend([joint for joint,value in packed]+[0]*(4-len(packed)))
        packed_weights.extend([value for joint,value in packed]+[0]*(4-len(packed)))
    binary += bytes(joints) + bytes(packed_weights)
    for x,y,z in world:
        binary += struct.pack("<16f",1,0,0,0,0,1,0,0,0,0,1,0,-x,-y,-z,1)
    binary += bytes([len(clips)])
    for name,duration,loop,hit,tracks in clips:
        encoded = name.encode()
        binary += bytes([len(encoded)])+encoded+struct.pack("<fBfB",duration,int(loop),-1 if hit is None else hit,len(tracks))
        for joint,prop,keys in tracks:
            binary += bytes([joint,prop,len(keys)])
            for time,values in keys:
                binary += struct.pack("<H4f",time,*[round(value,5) for value in values])
    binary += bytes(surfaces)
    assets[variant] = base64.b64encode(binary).decode()
    print(variant,"vertices",nv,"triangles",nt,"bones",len(parents),"clips",len(clips))
match = re.search(r"const SKIN_B64 = (\{[^\n]+\});",html)
html = html[:match.start(1)] + json.dumps(assets,separators=(",",":")) + html[match.end(1):]
import hashlib
inline_scripts = re.findall(r"<script\b[^>]*>(.*?)</script>",html.split("<!-- BLENDER_RIG_PY",1)[0],re.S)
script_hashes = " ".join("'sha256-"+base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()+"'" for text in inline_scripts)
html = re.sub(r"script-src [^;]+;","script-src "+script_hashes+" https://cdn.jsdelivr.net/npm/three@0.160.0/;",html,count=1)
path.write_text(html)
print("Updated only",path)
