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

def loft(name, rings, seg=16, m=None, power=2.0, cap=True):
    """沿 Z 堆叠的截面放样：rings = [(z, rx, ry[, cy[, cx]]), ...]，截面为超椭圆（power=2 为椭圆，越大越方）。
    用来做有粗细变化的躯干/四肢，替代原来的方盒与直圆柱。"""
    bm = bmesh.new(); rows = []; e = 2.0 / power
    for ring in rings:
        z, rx, ry = ring[:3]
        cy = ring[3] if len(ring) > 3 else 0.0
        cx = ring[4] if len(ring) > 4 else 0.0
        row = []
        for i in range(seg):
            a = i / seg * TAU; c, sn = math.cos(a), math.sin(a)
            row.append(bm.verts.new((cx + rx * math.copysign(abs(c) ** e, c), cy + ry * math.copysign(abs(sn) ** e, sn), z)))
        rows.append(row)
    for r in range(len(rows) - 1):
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((rows[r][i], rows[r][j], rows[r + 1][j], rows[r + 1][i]))
    if cap:
        bm.faces.new(list(reversed(rows[0]))); bm.faces.new(rows[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    if m: ob.data.materials.append(m)
    return ob

def cone_panel(name, a0, a1, z0, z1, r0, r1, thick=0.012, us=4, vs=3, m=None, bulge=0.0):
    """沿着外扩的椭圆锥面切出一块有厚度的弧形甲片（a 为绕身体的角度，0 = 正前方）。
    r0/r1 = (rx, ry) 为上沿/下沿的半径；bulge 让甲片中线略微外鼓。"""
    bm = bmesh.new(); grid = []
    for side in (0, 1):
        layer = []
        for j in range(vs + 1):
            t = j / vs; z = z0 + (z1 - z0) * t
            rx = r0[0] + (r1[0] - r0[0]) * t; ry = r0[1] + (r1[1] - r0[1]) * t
            row = []
            for i in range(us + 1):
                u = i / us; a = a0 + (a1 - a0) * u
                k = 1 + bulge * math.sin(u * math.pi) + side * thick / max(rx, ry)
                row.append(bm.verts.new((math.sin(a) * rx * k, -math.cos(a) * ry * k, z)))
            layer.append(row)
        grid.append(layer)
    inner, outer = grid
    for j in range(vs):
        for i in range(us):
            bm.faces.new((outer[j][i], outer[j + 1][i], outer[j + 1][i + 1], outer[j][i + 1]))
            bm.faces.new((inner[j][i], inner[j][i + 1], inner[j + 1][i + 1], inner[j + 1][i]))
    for j in range(vs):     # 左右侧边
        bm.faces.new((inner[j][0], inner[j + 1][0], outer[j + 1][0], outer[j][0]))
        bm.faces.new((outer[j][us], outer[j + 1][us], inner[j + 1][us], inner[j][us]))
    for i in range(us):     # 上下沿
        bm.faces.new((inner[0][i], outer[0][i], outer[0][i + 1], inner[0][i + 1]))
        bm.faces.new((outer[vs][i], inner[vs][i], inner[vs][i + 1], outer[vs][i + 1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
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

# ================= 躯干（放样：腰细、胸宽、肩收，带护心镜与圆肩甲） =================
o = []
o.append(loft("body", [(0.00,.150,.112),(0.12,.160,.118),(0.24,.196,.132),(0.36,.232,.148),
                       (0.47,.242,.144),(0.555,.200,.124),(0.60,.120,.090)], seg=18, m=M_ARMOR, power=2.4))
o.append(add_sphere("chestplate", 0.15, (0, -0.118, 0.395), scale=(1.18, 0.34, 0.95), seg=16, ring=10, m=M_STEEL))
o.append(add_sphere("backplate", 0.15, (0, 0.118, 0.405), scale=(1.15, 0.30, 0.90), seg=14, ring=8, m=M_ARMOR))
o.append(add_sphere("mirror", 0.052, (0, -0.168, 0.40), scale=(1, 0.32, 1), seg=14, ring=8, m=M_TRIM))   # 护心镜
o.append(loft("collar", [(0.535,.165,.125),(0.615,.150,.112)], seg=16, m=M_ARMOR, cap=False))
o.append(loft("belt", [(0.035,.172,.130),(0.115,.176,.134)], seg=18, m=M_LEATH, power=2.2, cap=False))
o.append(add_box("buckle", (0.09, 0.03, 0.07), (0, -0.152, 0.075), bevel=0.012, seg=2, m=M_TRIM))
for s in (-1, 1):
    o.append(add_sphere("pad%d" % s, 0.13, (s * 0.268, 0, 0.545), scale=(1.0, 1.04, 0.62), seg=16, ring=10, m=M_ARMOR))
    o.append(add_sphere("padtrim%d" % s, 0.135, (s * 0.268, 0, 0.515), scale=(1.02, 1.06, 0.16), seg=16, ring=6, m=M_TRIM))
o.append(add_cyl("neck", 0.066, 0.074, 0.10, (0, 0, 0.625), seg=12, m=M_SKIN))
parts['torso'] = join(o, "torso")

# ================= 裙甲（外扩的布裙打底 + 弧形甲片两层交叠，替代原来的 8 块平板） =================
o = []
o.append(loft("underskirt", [(0.040,.168,.128),(-0.08,.190,.152),(-0.22,.222,.186),(-0.255,.230,.194)], seg=20, m=M_CLOTH, power=2.2, cap=False))
TAS = 7                                      # 前后 7 片，留出两侧开衩方便迈腿
for layer, (z0, z1, rr, sp) in enumerate([(0.035, -0.150, (0, 0), 1.00), (-0.070, -0.245, (0.010, 0.012), 0.92)]):
    for i in range(TAS):
        if i in (1, 5) and layer == 1:       # 下层在两侧（约 ±95°，迈腿方向）少两片，露出布裙
            continue
        c = (i - (TAS - 1) / 2) / TAS * TAU * 0.92 + (0 if i < TAS / 2 else 0)
        half = TAU / TAS * 0.5 * sp * 1.06
        o.append(cone_panel("tasset%d_%d" % (layer, i), c - half, c + half, z0, z1,
                            (0.176 + rr[0], 0.136 + rr[1]), (0.232 + rr[0], 0.198 + rr[1]),
                            thick=0.013, us=4, vs=3, bulge=0.05,
                            m=M_ARMOR if (i + layer) % 2 == 0 else M_TRIM if i == (TAS - 1) // 2 else M_ARMOR))
parts['skirt'] = join(o, "skirt")

# ================= 手臂（肩为轴，向下 -Z；上臂有肱二头肌鼓起，前臂收向手腕，带护腕与手指） =================
o = []
o.append(add_sphere("shoulder", 0.098, (0, 0, -0.02), scale=(1, 1, 0.95), seg=14, ring=10, m=M_ARMOR))
o.append(loft("upper", [(-0.03,.086,.082),(-0.10,.096,.090),(-0.18,.088,.081),(-0.27,.074,.070),(-0.31,.069,.066)], seg=14, m=M_CLOTH))
o.append(add_sphere("elbow", 0.073, (0, 0.004, -0.305), seg=12, ring=8, m=M_ARMOR))
o.append(loft("fore", [(-0.31,.070,.067),(-0.36,.078,.073),(-0.45,.066,.061),(-0.52,.052,.048),(-0.545,.048,.044)], seg=14, m=M_CLOTH))
o.append(loft("bracer", [(-0.37,.084,.079),(-0.44,.075,.070),(-0.505,.062,.057)], seg=14, m=M_ARMOR, power=2.3, cap=False))
o.append(loft("palm", [(-0.535,.044,.028),(-0.560,.050,.030),(-0.585,.046,.028)], seg=12, m=M_SKIN, power=2.6))
for k in range(4):   # 手指缩短，手总长与旧版 box 手一致（≈-0.605），避免穿地/改变握枪位置
    o.append(add_cyl("finger%d" % k, 0.0105, 0.009, 0.040, (-0.033 + k * 0.022, -0.006, -0.600), rot=(0.35, 0, 0), seg=6, m=M_SKIN))
o.append(add_cyl("thumb", 0.012, 0.010, 0.05, (0, -0.036, -0.575), rot=(1.05, 0, 0), seg=6, m=M_SKIN))
parts['arm'] = join(o, "arm")

# ================= 腿（髋为轴，向下 -Z；大腿收向膝，小腿肚向后鼓，护胫 + 带鞋头的靴子） =================
o = []
o.append(loft("thigh", [(0.00,.100,.100),(-0.10,.106,.101),(-0.25,.090,.086),(-0.38,.076,.072),(-0.435,.070,.068)], seg=14, m=M_CLOTH))
o.append(add_sphere("knee", 0.072, (0, -0.012, -0.43), scale=(1, 1.1, 1), seg=12, ring=8, m=M_ARMOR))
o.append(loft("shin", [(-0.44,.070,.068,0.0),(-0.52,.075,.080,0.012),(-0.66,.060,.062,0.006),(-0.79,.050,.050,0.0)], seg=14, m=M_CLOTH))
o.append(loft("greave", [(-0.47,.079,.076,-0.004),(-0.60,.070,.070,-0.004),(-0.745,.058,.056,-0.004)], seg=14, m=M_ARMOR, power=2.2, cap=False))
o.append(loft("ankle", [(-0.78,.056,.056),(-0.86,.066,.070,-0.01)], seg=14, m=M_LEATH))
o.append(add_box("boot", (0.12, 0.24, 0.08), (0, -0.045, -0.875), bevel=0.034, seg=3, m=M_LEATH))
o.append(add_sphere("toe", 0.06, (0, -0.14, -0.885), scale=(1, 1.3, 0.62), seg=12, ring=8, m=M_LEATH))
parts['leg'] = join(o, "leg")

# ================= 头 + 盔（圆颅、收窄的下颌与下巴、鼻梁、眉骨、耳；盔帽檐缩小并后移，露出脸） =================
o = []
o.append(add_sphere("cranium", 0.100, (0, 0.006, 0.775), scale=(0.95, 1.05, 1.08), seg=18, ring=12, m=M_SKIN))
o.append(loft("jaw", [(0.640,.050,.046,-0.036),(0.670,.074,.072,-0.020),(0.710,.088,.090,-0.006),(0.745,.092,.096,0.0)], seg=16, m=M_SKIN, power=2.2))
o.append(add_cyl("nose", 0.019, 0.006, 0.048, (0, -0.100, 0.735), rot=(math.radians(100), 0, 0), seg=8, m=M_SKIN))
o.append(add_box("brow", (0.160, 0.030, 0.022), (0, -0.094, 0.786), bevel=0.010, seg=2, m=M_SKIN))
for s in (-1, 1):
    o.append(add_sphere("ear%d" % s, 0.022, (s * 0.098, 0.010, 0.750), scale=(0.5, 1, 1.3), seg=8, ring=6, m=M_SKIN))
    o.append(add_box("cheekguard%d" % s, (0.020, 0.090, 0.095), (s * 0.103, -0.010, 0.735), rot=(0, 0, s * 0.18), bevel=0.008, m=M_ARMOR))
o.append(add_sphere("dome", 0.148, (0, 0.012, 0.862), scale=(1.0, 1.06, 0.80), seg=18, ring=10, m=M_ARMOR))
o.append(add_cyl("brim", 0.165, 0.170, 0.020, (0, 0.030, 0.828), seg=18, m=M_ARMOR))
o.append(add_box("neckguard", (0.27, 0.17, 0.05), (0, 0.080, 0.780), rot=(math.radians(-22), 0, 0), bevel=0.014, m=M_ARMOR))
o.append(add_box("crest", (0.028, 0.115, 0.10), (0, 0.012, 0.968), bevel=0.010, m=M_TRIM))
o.append(add_cyl("spike", 0.004, 0.022, 0.11, (0, 0.012, 1.058), seg=8, m=M_TRIM))
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

# ---- 写回产物：只替换本脚本生成的部件，GEO_B64 里其它部件（plume/halberd 等）保持不变 ----
from pathlib import Path
target = Path.cwd() / os.environ.get("TARGET", "demos/index-webgpu.html")
if target.exists():
    html = target.read_text()
    head, rest = html.split("const GEO_B64 = {", 1)
    block, tail = rest.split("\n};", 1)
    order, cur = [], {}
    for line in block.splitlines():
        if ":" not in line: continue
        k, v = line.strip().split(":", 1)
        k = k.strip(); order.append(k); cur[k] = v.strip().rstrip(",").strip('"')
    for k, v in out.items():
        if k not in cur: order.append(k)
        cur[k] = v
    block = "\n" + "\n".join('  %s: "%s",' % (k, cur[k]) for k in order)
    target.write_text(head + "const GEO_B64 = {" + block + "\n};" + tail)
    print("GEO_B64 updated in", target, "parts:", ",".join(out.keys()))
