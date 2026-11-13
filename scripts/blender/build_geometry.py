"""用 Blender 生成《无双·虎牢关》的角色部件几何，导出为 base64 供单文件 HTML 内嵌。

用法：
    blender -b -P scripts/blender/build_geometry.py
    # 或在 Blender 里：运行脚本，设置环境变量 PARTS_OUT

导出格式（每个部件一条 base64）：
    [nv:u32][ni:u32][pos: f32 x nv*3][col: u8 x nv*4][idx: u16 x ni*3]
    坐标系：Blender Z-up → three.js Y-up，映射 (x, z, -y)
    原点：躯干/裙甲/头在髋关节；手臂/腿在关节枢轴；兵器在手
"""
import bpy, bmesh, math, json, base64, struct, os
from mathutils import Vector, Matrix

TAU = math.pi * 2

def clear():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for d in (bpy.data.meshes, bpy.data.materials, bpy.data.curves):
        for x in list(d):
            try: d.remove(x)
            except Exception: pass

def mat(name, rgb, rough=0.6, metal=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = [n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'][0]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*rgb, 1)
    return m

def add_box(name, size, loc, rot=(0,0,0), bevel=0.0, seg=2, m=None, taper=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if taper:
        # taper: (top_scale_x, top_scale_y, bottom_scale_x, bottom_scale_y)
        tx, ty, bx, by = taper
        for v in bm.verts:
            t = (v.co.z / size[2]) + 0.5
            v.co.x *= bx + (tx - bx) * t
            v.co.y *= by + (ty - by) * t
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                        offset=bevel, segments=seg, profile=0.5, affect='EDGES')
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.location = loc; ob.rotation_euler = rot
    if m: ob.data.materials.append(m)
    return ob

def add_cyl(name, r1, r2, depth, loc, rot=(0,0,0), seg=10, m=None, cap=True):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=False, segments=seg,
                          radius1=r1, radius2=r2, depth=depth)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.location = loc; ob.rotation_euler = rot
    if m: ob.data.materials.append(m)
    return ob

def add_sphere(name, r, loc, scale=(1,1,1), seg=12, ring=8, m=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=ring, radius=r)
    bmesh.ops.scale(bm, vec=Vector(scale), verts=bm.verts)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    if m: ob.data.materials.append(m)
    return ob

def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    ob = bpy.context.object
    ob.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return ob


# ============================================================
# 部件定义
# ============================================================

clear()

# ---- 调色板（顶点色 = 材质明暗乘子；实例色提供阵营色相） ----
M_ARMOR  = mat("armor",  (0.90, 0.91, 0.94), 0.42, 0.55)
M_CLOTH  = mat("cloth",  (0.74, 0.74, 0.76), 0.92, 0.0)
M_TRIM   = mat("trim",   (1.00, 0.82, 0.42), 0.35, 0.85)
M_LEATH  = mat("leath",  (0.36, 0.32, 0.29), 0.85, 0.0)
M_STEEL  = mat("steel",  (0.96, 0.98, 1.00), 0.22, 1.0)
M_WOOD   = mat("wood",   (0.42, 0.29, 0.17), 0.80, 0.0)
M_SKIN   = mat("skin",   (0.78, 0.60, 0.45), 0.70, 0.0)
M_DARK   = mat("dark",   (0.16, 0.17, 0.19), 0.55, 0.45)

parts = {}

# ================= 躯干 =================
o = []
o.append(add_box("chest", (0.42, 0.26, 0.40), (0, 0, 0.36), bevel=0.035, seg=2, m=M_ARMOR,
                 taper=(0.96, 0.96, 0.82, 0.86)))
o.append(add_box("chestplate", (0.30, 0.05, 0.26), (0, -0.135, 0.38), bevel=0.015, m=M_STEEL))
o.append(add_box("backplate", (0.30, 0.04, 0.24), (0, 0.135, 0.40), bevel=0.015, m=M_ARMOR))
o.append(add_box("collar", (0.30, 0.22, 0.09), (0, 0, 0.565), bevel=0.02, m=M_ARMOR))
o.append(add_box("belt", (0.44, 0.29, 0.075), (0, 0, 0.075), bevel=0.012, m=M_LEATH))
o.append(add_box("buckle", (0.09, 0.03, 0.07), (0, -0.152, 0.075), bevel=0.008, m=M_TRIM))
for s in (-1, 1):
    o.append(add_box("pad%d" % s, (0.21, 0.25, 0.10), (s * 0.255, 0, 0.555),
                     rot=(0, s * 0.30, 0), bevel=0.03, m=M_ARMOR))
    o.append(add_box("padtrim%d" % s, (0.215, 0.255, 0.028), (s * 0.255, 0, 0.505),
                     rot=(0, s * 0.30, 0), bevel=0.008, m=M_TRIM))
o.append(add_cyl("neck", 0.072, 0.078, 0.10, (0, 0, 0.625), seg=10, m=M_SKIN))
parts['torso'] = join(o, "torso")

# ================= 裙甲 =================
o = []
for i in range(8):
    a = i / 8 * TAU
    r = 0.155
    px, py = math.sin(a) * r, -math.cos(a) * r
    ob = add_box("tasset%d" % i, (0.135, 0.028, 0.27), (px, py, -0.10),
                 rot=(math.radians(11), 0, -a), bevel=0.008, m=M_CLOTH if i % 2 else M_ARMOR)
    o.append(ob)
parts['skirt'] = join(o, "skirt")

# ================= 手臂（肩为轴，向下 -Z） =================
o = []
o.append(add_sphere("shoulder", 0.088, (0, 0, -0.02), scale=(1, 1, 0.95), m=M_ARMOR))
o.append(add_cyl("upper", 0.072, 0.062, 0.28, (0, 0, -0.16), seg=9, m=M_CLOTH))
o.append(add_sphere("elbow", 0.066, (0, 0, -0.305), m=M_ARMOR))
o.append(add_cyl("fore", 0.062, 0.052, 0.23, (0, 0, -0.425), seg=9, m=M_CLOTH))
o.append(add_box("hand", (0.085, 0.085, 0.10), (0, -0.005, -0.555), bevel=0.02, m=M_SKIN))
parts['arm'] = join(o, "arm")

# ================= 腿（髋为轴，向下 -Z） =================
o = []
o.append(add_cyl("thigh", 0.098, 0.082, 0.42, (0, 0, -0.21), seg=9, m=M_CLOTH))
o.append(add_sphere("knee", 0.082, (0, -0.005, -0.43), m=M_ARMOR))
o.append(add_cyl("shin", 0.082, 0.068, 0.35, (0, 0, -0.615), seg=9, m=M_CLOTH))
o.append(add_box("boot", (0.145, 0.25, 0.11), (0, -0.035, -0.855), bevel=0.02, m=M_LEATH))
parts['leg'] = join(o, "leg")

# ================= 头 + 盔 =================
o = []
o.append(add_box("skull", (0.195, 0.215, 0.235), (0, 0, 0.755), bevel=0.04, seg=3, m=M_SKIN,
                 taper=(0.95, 0.95, 0.88, 0.9)))
o.append(add_box("jaw", (0.155, 0.19, 0.075), (0, -0.012, 0.665), bevel=0.025, m=M_SKIN))
o.append(add_sphere("dome", 0.155, (0, 0.005, 0.855), scale=(1.0, 1.06, 0.82), m=M_ARMOR))
o.append(add_cyl("brim", 0.192, 0.20, 0.028, (0, 0.005, 0.812), seg=14, m=M_ARMOR))
o.append(add_box("neckguard", (0.27, 0.17, 0.05), (0, 0.075, 0.775), rot=(math.radians(-22), 0, 0),
                 bevel=0.012, m=M_ARMOR))
o.append(add_box("crest", (0.028, 0.115, 0.10), (0, 0.01, 0.965), bevel=0.008, m=M_TRIM))
o.append(add_cyl("spike", 0.004, 0.022, 0.11, (0, 0.01, 1.055), seg=6, m=M_TRIM))
parts['head'] = join(o, "head")

# ================= 刀（手为原点，沿 Z） =================
o = []
o.append(add_cyl("grip", 0.026, 0.028, 0.24, (0, 0, -0.02), seg=8, m=M_LEATH))
o.append(add_box("guard", (0.11, 0.035, 0.025), (0, 0, 0.105), bevel=0.006, m=M_TRIM))
blade = add_box("blade", (0.045, 0.012, 0.52), (0, 0, 0.38), bevel=0.006, m=M_STEEL,
                taper=(0.25, 0.7, 1.0, 1.0))
o.append(blade)
parts['dao'] = join(o, "dao")

# ================= 长枪（手为原点，沿 Z，全长 2.5） =================
o = []
o.append(add_cyl("shaft", 0.028, 0.030, 2.5, (0, 0, 0), seg=8, m=M_WOOD))
o.append(add_cyl("butt", 0.034, 0.030, 0.10, (0, 0, -1.24), seg=8, m=M_STEEL))
o.append(add_cyl("collar", 0.042, 0.042, 0.05, (0, 0, 1.20), seg=8, m=M_TRIM))
o.append(add_cyl("leaf", 0.001, 0.055, 0.36, (0, 0, 1.42), seg=4, m=M_STEEL))
o.append(add_box("ridge", (0.012, 0.012, 0.30), (0, 0, 1.40), bevel=0.003, m=M_STEEL))
parts['spear'] = join(o, "spear")

# ================= 弓 =================
o = []
prev = None
for i in range(7):
    t = i / 6
    a = (t - 0.5) * 1.9
    px, pz = math.sin(a) * 0.46, math.cos(a) * 0.46 - 0.46
    ob = add_box("bow%d" % i, (0.045, 0.05, 0.19), (px, 0, pz),
                 rot=(0, -a, 0), bevel=0.008, m=M_WOOD)
    o.append(ob)
o.append(add_box("grip", (0.055, 0.06, 0.14), (0, 0, 0.0), bevel=0.012, m=M_LEATH))
o.append(add_box("string", (0.008, 0.008, 0.90), (0, 0, -0.02), m=M_STEEL))
parts['bow'] = join(o, "bow")

result = {"parts": list(parts.keys()), "tris": {k: len(v.data.polygons) for k, v in parts.items()}}


# ============================================================
# 导出
# ============================================================
import bpy, math, json, base64, struct


def s2l(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def export_part(ob, name):
    me = ob.data
    me.calc_loop_triangles()
    if not me.color_attributes:
        attr = me.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
    else:
        attr = me.color_attributes[0]
    mats = me.materials
    for poly in me.polygons:
        m = mats[poly.material_index] if poly.material_index < len(mats) else None
        c = m.diffuse_color if m else (0.8, 0.8, 0.8, 1.0)
        lin = (s2l(c[0]), s2l(c[1]), s2l(c[2]), 1.0)
        for li in poly.loop_indices:
            attr.data[li].color = lin
    me.update()

    # 去重顶点（按位置量化后合并）
    key_map = {}
    verts = []
    for v in me.vertices:
        co = v.co
        key = (round(co.x, 4), round(co.y, 4), round(co.z, 4))
        i = key_map.get(key)
        if i is None:
            i = len(verts)
            key_map[key] = i
            verts.append((co.x, co.z, -co.y))
    idx = []
    cols = []
    vcol = [None] * len(verts)
    for poly in me.polygons:
        ids = []
        for vi in poly.vertices:
            co = me.vertices[vi].co
            k = (round(co.x, 4), round(co.y, 4), round(co.z, 4))
            ids.append(key_map[k])
        # 面颜色：取第一个 loop 的颜色
        li = poly.loop_indices[0]
        c = attr.data[li].color
        for vi in ids:
            if vcol[vi] is None:
                vcol[vi] = (c[0], c[1], c[2])
        for t in range(1, len(ids) - 1):
            idx.append((ids[0], ids[t], ids[t + 1]))
    for i in range(len(verts)):
        if vcol[i] is None:
            vcol[i] = (0.8, 0.8, 0.8)
    cols = vcol

    nv, ni = len(verts), len(idx)
    buf = bytearray()
    buf += struct.pack('<II', nv, ni)
    for v in verts:
        buf += struct.pack('<fff', *v)
    for c in cols:
        buf += struct.pack('<BBBB', *[max(0, min(255, int(round(x * 255)))) for x in c], 255)
    for t in idx:
        buf += struct.pack('<HHH', *t)
    return base64.b64encode(bytes(buf)).decode(), nv, ni

out = {}
for name, ob in parts.items():
    b64, nv, ni = export_part(ob, name)
    out[name] = b64
    print(name, "verts", nv, "tris", ni, "b64", len(b64))

import os
out_path = os.environ.get('PARTS_OUT', '/tmp/parts.json')
open(out_path, 'w').write(json.dumps(out))
print('written', out_path)
result = {"ok": True, "total_b64": sum(len(v) for v in out.values())}
