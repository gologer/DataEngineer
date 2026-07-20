# -*- coding: utf-8 -*-
"""
BigQuery-Task.py
================
ดึงข้อมูล OpenStreetMap จาก BigQuery Public Dataset
    `bigquery-public-data.geo_openstreetmap.planet_features`
แล้วสร้างแผนที่ HTML แบบ Interactive (folium/Leaflet)

ตาราง planet_features มีขนาดใหญ่มาก (ทั้งโลก, หลายร้อย GB) จึง "ต้อง" กรองข้อมูลก่อนเสมอ
สคริปต์นี้ควบคุมปริมาณข้อมูล 4 ชั้น:

  1. กรองเชิงพื้นที่ด้วยขอบเขตการปกครอง (จังหวัด / อำเภอ / ตำบล)
     - ST_INTERSECTSBOX ด้วยค่าคงที่ -> BigQuery ตัด partition/cluster ของ geometry ออกได้
       (ตารางนี้ cluster ตามคอลัมน์ geometry) ทำให้สแกนข้อมูลน้อยลงมาก
     - ST_INTERSECTS กับ polygon ขอบเขตจริง -> ตัดข้อมูลนอกเขตออกแบบแม่นยำ
  2. กรองชนิดข้อมูลด้วย OSM tag (เช่น amenity=school, highway=primary)
  3. LIMIT จำนวน feature สูงสุดที่จะนำมาแสดงบนแผนที่ (--max-features)
  4. เพดานค่าสแกนข้อมูล maximum_bytes_billed + dry-run แสดงประมาณการก่อนรันจริง

การเตรียมเครื่องก่อนใช้งาน
---------------------------
  1) ติดตั้งไลบรารี:   pip install google-cloud-bigquery folium shapely
  2) ยืนยันตัวตน Google Cloud (เลือกอย่างใดอย่างหนึ่ง):
       - gcloud auth application-default login
       - ตั้ง env GOOGLE_APPLICATION_CREDENTIALS ชี้ไปที่ไฟล์ service account JSON
  3) ตั้งชื่อ project สำหรับคิดค่าใช้จ่าย (billing project):
       - env GOOGLE_CLOUD_PROJECT=<your-project-id>  หรือใช้ --project

ตัวอย่างการรัน
--------------
  # โรงเรียน+โรงพยาบาลในอำเภอศรีราชา จังหวัดชลบุรี
  python BigQuery-Task.py --province ชลบุรี --amphoe ศรีราชา --key amenity --values school hospital

  # ถนนสายหลักทั้งจังหวัดภูเก็ต
  python BigQuery-Task.py --province ภูเก็ต --key highway --values primary secondary trunk

  # amenity ทุกชนิดในตำบลสุเทพ อำเภอเมืองเชียงใหม่
  python BigQuery-Task.py --province เชียงใหม่ --amphoe เมืองเชียงใหม่ --tambon สุเทพ --key amenity
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

# กัน UnicodeEncodeError เวลา print ภาษาไทยผ่าน console/pipe ของ Windows
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def load_dotenv(path=None):
    """อ่านไฟล์ .env (KEY=VALUE ทีละบรรทัด) เข้า os.environ
    ค่าใน environment จริงมีลำดับความสำคัญสูงกว่า ไม่ถูกเขียนทับ"""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if value and key not in os.environ:
                os.environ[key] = value


load_dotenv()

try:
    import folium
    from folium.plugins import MarkerCluster
    from google.cloud import bigquery
    from google.api_core.exceptions import BadRequest, Forbidden
    from google.auth.exceptions import DefaultCredentialsError
    from shapely.geometry import Point, shape
except ImportError as e:
    sys.exit(
        f"ยังไม่ได้ติดตั้งไลบรารีที่จำเป็น ({e.name})\n"
        "โปรดรัน:  pip install google-cloud-bigquery folium shapely"
    )

# ---------------------------------------------------------------------------
# ค่าตั้งต้น (แก้ตรงนี้ หรือ override ผ่าน command line ก็ได้)
# ---------------------------------------------------------------------------
DEFAULT_PROVINCE = "ชลบุรี"      # จังหวัด (จำเป็นอย่างน้อย 1 ระดับ)
DEFAULT_AMPHOE = "ศรีราชา"       # อำเภอ (เว้นว่าง "" = ทั้งจังหวัด)
DEFAULT_TAMBON = ""              # ตำบล (เว้นว่าง "" = ทั้งอำเภอ)
DEFAULT_TAG_KEY = "amenity"      # OSM tag key ที่ต้องการ เช่น amenity, highway, building
DEFAULT_TAG_VALUES: list = []    # จำกัดค่า tag เช่น ["school","hospital"] (ว่าง = ทุกค่า)
DEFAULT_MAX_FEATURES = 5000      # จำนวน feature สูงสุดบนแผนที่
DEFAULT_MAX_GB_BILLED = 60       # เพดานปริมาณข้อมูลที่ยอมให้สแกนต่อ query (GB)
DEFAULT_OUTPUT = "osm_map.html"

TABLE = "`bigquery-public-data.geo_openstreetmap.planet_features`"

# กรอบประเทศไทยแบบค่าคงที่ ใช้ให้ BigQuery ตัด cluster ของ geometry (ลด bytes ที่สแกน)
TH_BBOX = (97.0, 5.5, 106.0, 21.0)  # (xmin, ymin, xmax, ymax)

# คำนำหน้าชื่อเขตปกครองที่ต้องตัดออกก่อนเทียบชื่อ
NAME_PREFIX_RE = r"^(จังหวัด|อำเภอ|กิ่งอำเภอ|ตำบล|เขต|แขวง)\s*"

# พาเลตสีเชิงหมวดหมู่ (ผ่านการตรวจ colorblind-safe แล้ว, เรียงลำดับตายตัว)
PALETTE = ["#2a78d6", "#008300", "#e87ba4", "#eda100",
           "#1baf7a", "#eb6834", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#898781"   # หมวด "อื่น ๆ"
BOUNDARY_COLOR = "#52514e"


def strip_prefix(name: str) -> str:
    return re.sub(NAME_PREFIX_RE, "", name.strip())


class TaskError(Exception):
    """ข้อผิดพลาดที่อธิบายให้ผู้ใช้ได้ — CLI พิมพ์แล้วจบ, โหมด web แสดงเป็นหน้า error"""


# ---------------------------------------------------------------------------
# ส่วนติดต่อ BigQuery
# ---------------------------------------------------------------------------
def make_client(project: str) -> bigquery.Client:
    if not project:
        raise TaskError(
            "ยังไม่ได้ระบุ billing project\n"
            "ตั้งค่าใน .env (GOOGLE_CLOUD_PROJECT) หรือรันด้วย --project <project-id>"
        )
    try:
        return bigquery.Client(project=project)
    except DefaultCredentialsError:
        raise TaskError(
            "ไม่พบ Google Cloud credentials\n"
            "เลือกอย่างใดอย่างหนึ่ง:\n"
            "  1) gcloud auth application-default login\n"
            "  2) ตั้ง GOOGLE_APPLICATION_CREDENTIALS ใน .env ชี้ไปที่ไฟล์ service account JSON"
        )


def run_query(client, sql, params, max_gb, label):
    """dry-run แสดงประมาณการก่อน แล้วรันจริงภายใต้เพดาน maximum_bytes_billed

    หมายเหตุ: ตาราง planet_features ถูก cluster ตามคอลัมน์ geometry
    ตัวเลข dry-run จึงเป็น "ขอบบนก่อนหัก cluster pruning" — ปริมาณที่คิดเงินจริง
    มักต่ำกว่านี้มาก เพดานที่บังคับจริงคือ maximum_bytes_billed ตอนรัน
    """
    dry = client.query(
        sql, job_config=bigquery.QueryJobConfig(
            query_parameters=params, dry_run=True, use_query_cache=False)
    )
    est_gb = dry.total_bytes_processed / 2**30
    print(f"  [{label}] ประมาณการขอบบน {est_gb:,.2f} GB "
          f"(ก่อน cluster pruning; เพดานคิดเงินจริง {max_gb} GB)")
    job = client.query(
        sql, job_config=bigquery.QueryJobConfig(
            query_parameters=params,
            maximum_bytes_billed=int(max_gb * 2**30))
    )
    try:
        rows = list(job.result())
    except (Forbidden, BadRequest) as e:
        if "bytes billed" in str(e).lower():
            raise TaskError(
                f"query สแกนข้อมูลเกินเพดาน {max_gb} GB ที่ตั้งไว้ จึงถูกยกเลิก (ยังไม่ถูกคิดเงิน)\n"
                "ลดขอบเขตพื้นที่/แคบ tag ลง หรือเพิ่มเพดาน (--max-gb)"
            )
        raise TaskError(f"BigQuery ปฏิเสธการรัน: {e}")
    print(f"  [{label}] สแกนจริง {job.total_bytes_processed / 2**30:,.2f} GB, "
          f"ได้ {len(rows):,} แถว")
    return rows


# แหล่งขอบเขตการปกครอง: planet_features เก็บ relation ของ boundary=administrative
# ไม่สมบูรณ์ (ไม่มี polygon ระดับอำเภอ/ตำบล) จึงใช้ Overture Maps division_area แทน
# subtype ของไทย: region = จังหวัด (ชื่อไทย), county = อำเภอ/เขต (928 แห่ง แต่ชื่ออังกฤษ),
# locality = ตำบล/เทศบาล (มีเพียงบางส่วน)
OVERTURE = "`bigquery-public-data.overture_maps.division_area`"


def fetch_admin_areas(client, name, subtype, max_gb, label):
    """หา polygon เขตปกครองจาก Overture ตามชื่อ (เทียบทุกภาษา ตัดคำนำหน้าก่อน)"""
    sql = f"""
    SELECT
      names.primary AS name,
      ST_ASGEOJSON(ST_SIMPLIFY(geometry, 50)) AS geojson,
      ST_AREA(geometry) AS area_m2
    FROM {OVERTURE}
    WHERE country = 'TH' AND subtype = @subtype AND class = 'land'
      AND (
        LOWER(REGEXP_REPLACE(names.primary, r'{NAME_PREFIX_RE}', '')) = LOWER(@area_name)
        OR EXISTS(
          SELECT 1 FROM UNNEST(names.common.key_value) kv
          WHERE LOWER(REGEXP_REPLACE(kv.value, r'{NAME_PREFIX_RE}', '')) = LOWER(@area_name))
      )
    """
    params = [
        bigquery.ScalarQueryParameter("subtype", "STRING", subtype),
        bigquery.ScalarQueryParameter("area_name", "STRING", strip_prefix(name)),
    ]
    rows = run_query(client, sql, params, max_gb, label)
    return [
        {"name": r["name"], "geom": shape(json.loads(r["geojson"])), "area": r["area_m2"]}
        for r in rows
    ]


def find_amphoe_by_place_node(client, name, province_geom, max_gb):
    """แผนสำรองสำหรับชื่ออำเภอภาษาไทย (county ใน Overture มีแต่ชื่ออังกฤษ):
    หาจุดศูนย์กลางอำเภอจาก OSM place node (มีชื่อไทย) แล้วเลือก county ที่ครอบจุดนั้น"""
    if province_geom is not None:
        xmin, ymin, xmax, ymax = province_geom.bounds
    else:
        xmin, ymin, xmax, ymax = TH_BBOX
    sql = f"""
    SELECT ST_X(geometry) AS lon, ST_Y(geometry) AS lat
    FROM {TABLE}
    WHERE feature_type = 'points'
      AND ST_INTERSECTSBOX(geometry, {xmin:.6f}, {ymin:.6f}, {xmax:.6f}, {ymax:.6f})
      AND EXISTS(SELECT 1 FROM UNNEST(all_tags) t
                 WHERE t.key IN ('name', 'name:th')
                   AND REGEXP_REPLACE(t.value, r'{NAME_PREFIX_RE}', '') = @place_name)
      AND EXISTS(SELECT 1 FROM UNNEST(all_tags) t WHERE t.key = 'place')
    LIMIT 5
    """
    params = [bigquery.ScalarQueryParameter("place_name", "STRING", strip_prefix(name))]
    points = run_query(client, sql, params, max_gb, "place-node")

    for p in points:
        if province_geom is not None and not province_geom.contains(Point(p["lon"], p["lat"])):
            continue
        sql2 = f"""
        SELECT names.primary AS name,
               ST_ASGEOJSON(ST_SIMPLIFY(geometry, 50)) AS geojson,
               ST_AREA(geometry) AS area_m2
        FROM {OVERTURE}
        WHERE country = 'TH' AND subtype = 'county' AND class = 'land'
          AND ST_CONTAINS(geometry, ST_GEOGPOINT(@lon, @lat))
        """
        params2 = [bigquery.ScalarQueryParameter("lon", "FLOAT64", p["lon"]),
                   bigquery.ScalarQueryParameter("lat", "FLOAT64", p["lat"])]
        rows = run_query(client, sql2, params2, max_gb, "county-at-point")
        if rows:
            r = rows[0]
            return [{"name": r["name"], "geom": shape(json.loads(r["geojson"])),
                     "area": r["area_m2"]}]
    return []


def resolve_boundary(client, province, amphoe, tambon, max_gb):
    """หา polygon ของพื้นที่เป้าหมายระดับลึกสุดที่ระบุ (จังหวัด > อำเภอ > ตำบล)"""
    province_b = None
    if province:
        print(f"ขั้นที่ 1: ค้นหาขอบเขตจังหวัด{strip_prefix(province)}")
        cands = fetch_admin_areas(client, province, "region", max_gb, "province")
        if not cands:
            raise TaskError(f"ไม่พบจังหวัด '{province}' — ตรวจสอบการสะกด (ไทย/อังกฤษ)")
        province_b = max(cands, key=lambda c: c["area"])
        if not (amphoe or tambon):
            print(f"  ใช้ขอบเขต: {province_b['name']} "
                  f"({province_b['area'] / 1e6:,.0f} ตร.กม.)")
            return province_b, f"จังหวัด{strip_prefix(province)}"

    parent_geom = province_b["geom"] if province_b else None

    if amphoe:
        label = f"อำเภอ{strip_prefix(amphoe)}"
        print(f"ขั้นที่ 1.1: ค้นหาขอบเขต{label}")
        cands = fetch_admin_areas(client, amphoe, "county", max_gb, "amphoe")
        if parent_geom is not None:
            cands = [c for c in cands
                     if parent_geom.contains(c["geom"].representative_point())]
        if not cands:  # ชื่อไทยไม่มีใน Overture -> หาผ่าน OSM place node
            cands = find_amphoe_by_place_node(client, amphoe, parent_geom, max_gb)
        if not cands:
            raise TaskError(
                f"ไม่พบ{label}" + (f" ในจังหวัด{strip_prefix(province)}" if province else "")
                + " — ตรวจสอบการสะกด หรือลองระบุจังหวัดให้ตรง")
        amphoe_b = max(cands, key=lambda c: c["area"])
        if not tambon:
            print(f"  ใช้ขอบเขต: {amphoe_b['name']} "
                  f"({amphoe_b['area'] / 1e6:,.0f} ตร.กม.)")
            return amphoe_b, label
        parent_geom = amphoe_b["geom"]

    label = f"ตำบล{strip_prefix(tambon)}"
    print(f"ขั้นที่ 1.2: ค้นหาขอบเขต{label}")
    cands = fetch_admin_areas(client, tambon, "locality", max_gb, "tambon")
    if parent_geom is not None:
        cands = [c for c in cands
                 if parent_geom.contains(c["geom"].representative_point())]
    if not cands:
        raise TaskError(
            f"ไม่พบขอบเขต{label} — ขอบเขตระดับตำบลใน Overture ยังมีไม่ครบทุกตำบล\n"
            "แนะนำให้ใช้ระดับอำเภอแทน (เว้นช่องตำบลว่าง)")
    chosen = max(cands, key=lambda c: c["area"])
    print(f"  ใช้ขอบเขต: {chosen['name']} ({chosen['area'] / 1e6:,.1f} ตร.กม.)")
    return chosen, label


def fetch_features(client, boundary_geom, tag_key, tag_values, max_features, max_gb):
    """ดึง feature ภายในขอบเขต ตาม tag ที่กำหนด"""
    xmin, ymin, xmax, ymax = boundary_geom.bounds
    pad = 0.01  # กันขอบ bbox ตัด geometry ที่คาบเส้น
    value_clause = "AND t.value IN UNNEST(@tag_values)" if tag_values else ""
    sql = f"""
    SELECT
      osm_id,
      osm_way_id,
      feature_type,
      (SELECT value FROM UNNEST(all_tags) WHERE key = 'name' LIMIT 1) AS name,
      (SELECT value FROM UNNEST(all_tags) WHERE key = @tag_key LIMIT 1) AS category,
      TO_JSON_STRING(all_tags) AS tags_json,
      ST_ASGEOJSON(ST_SIMPLIFY(geometry, 10)) AS geojson
    FROM {TABLE}
    WHERE ST_INTERSECTSBOX(geometry,
            {xmin - pad:.6f}, {ymin - pad:.6f}, {xmax + pad:.6f}, {ymax + pad:.6f})
      AND ST_INTERSECTS(geometry, ST_GEOGFROMGEOJSON(@boundary, make_valid => TRUE))
      AND EXISTS(SELECT 1 FROM UNNEST(all_tags) t
                 WHERE t.key = @tag_key {value_clause})
    LIMIT {int(max_features)}
    """
    params = [
        bigquery.ScalarQueryParameter("tag_key", "STRING", tag_key),
        bigquery.ScalarQueryParameter("boundary", "STRING",
                                      json.dumps(boundary_geom.__geo_interface__)),
    ]
    if tag_values:
        params.append(bigquery.ArrayQueryParameter("tag_values", "STRING", tag_values))
    return run_query(client, sql, params, max_gb, "features")


# ---------------------------------------------------------------------------
# สร้างแผนที่ folium
# ---------------------------------------------------------------------------
def osm_url(row) -> str:
    if row["osm_way_id"] is not None:
        return f"https://www.openstreetmap.org/way/{row['osm_way_id']}"
    kind = "node" if row["feature_type"] == "points" else "relation"
    return f"https://www.openstreetmap.org/{kind}/{row['osm_id']}"


def popup_html(row) -> str:
    tags = {t["key"]: t["value"] for t in json.loads(row["tags_json"])}
    name = row["name"] or "(ไม่มีชื่อ)"
    lines = [f"<b>{name}</b>", f"<i>{row['category'] or ''}</i>", "<hr style='margin:4px 0'>"]
    for k, v in list(tags.items())[:12]:
        lines.append(f"{k} = {v}<br>")
    if len(tags) > 12:
        lines.append(f"... และอีก {len(tags) - 12} tag<br>")
    lines.append(f"<a href='{osm_url(row)}' target='_blank'>เปิดใน OSM</a>")
    return f"<div style='max-width:280px;word-wrap:break-word'>{''.join(lines)}</div>"


def build_map(rows, boundary, area_label, tag_key):
    center = boundary["geom"].representative_point()
    m = folium.Map(location=[center.y, center.x], zoom_start=11,
                   tiles="CartoDB positron", control_scale=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)

    # ชั้นขอบเขตการปกครอง
    folium.GeoJson(
        boundary["geom"].__geo_interface__,
        name=f"ขอบเขต{area_label}",
        style_function=lambda f: {"color": BOUNDARY_COLOR, "weight": 2.5,
                                  "dashArray": "6 4", "fill": False},
    ).add_to(m)

    # จัดหมวดสี: 8 หมวดที่พบมากที่สุดได้สีประจำตัว ที่เหลือรวมเป็น "อื่น ๆ"
    counts = Counter((r["category"] or "(ไม่ระบุ)") for r in rows)
    top = [c for c, _ in counts.most_common(len(PALETTE))]
    color_of = {c: PALETTE[i] for i, c in enumerate(top)}

    groups = {}
    for row in rows:
        cat = row["category"] or "(ไม่ระบุ)"
        key = cat if cat in color_of else "อื่น ๆ"
        color = color_of.get(cat, OTHER_COLOR)
        if key not in groups:
            n = counts[cat] if key != "อื่น ๆ" else sum(
                v for c, v in counts.items() if c not in color_of)
            fg = folium.FeatureGroup(name=f"{key} ({n:,})")
            groups[key] = {"fg": fg, "cluster": MarkerCluster().add_to(fg), "color": color}
            fg.add_to(m)
        g = groups[key]

        geom = json.loads(row["geojson"])
        popup = folium.Popup(popup_html(row), max_width=320)
        if geom["type"] == "Point":
            lon, lat = geom["coordinates"]
            folium.CircleMarker(
                location=[lat, lon], radius=6, color=g["color"], weight=1.5,
                fill=True, fill_color=g["color"], fill_opacity=0.85,
                tooltip=row["name"] or cat, popup=popup,
            ).add_to(g["cluster"])
        else:
            folium.GeoJson(
                geom,
                style_function=lambda f, c=g["color"]: {
                    "color": c, "weight": 2, "fillColor": c, "fillOpacity": 0.25},
                tooltip=row["name"] or cat, popup=popup,
            ).add_to(g["fg"])

    # แถบหัวเรื่อง + คำอธิบายสี
    legend_rows = "".join(
        f"<div><span style='display:inline-block;width:12px;height:12px;"
        f"border-radius:3px;background:{color_of.get(c, OTHER_COLOR)};"
        f"margin-right:6px'></span>{c} ({counts[c]:,})</div>"
        for c in top)
    other_n = sum(v for c, v in counts.items() if c not in color_of)
    if other_n:
        legend_rows += (f"<div><span style='display:inline-block;width:12px;height:12px;"
                        f"border-radius:3px;background:{OTHER_COLOR};margin-right:6px'>"
                        f"</span>อื่น ๆ ({other_n:,})</div>")
    m.get_root().html.add_child(folium.Element(f"""
    <div style="position:fixed;top:12px;left:60px;z-index:9999;background:#fcfcfbEE;
                padding:10px 14px;border-radius:8px;border:1px solid rgba(11,11,11,.10);
                font-family:system-ui,'Segoe UI',sans-serif;font-size:13px;color:#0b0b0b;
                max-height:70vh;overflow-y:auto;box-shadow:0 1px 4px rgba(0,0,0,.15)">
      <div style="font-weight:600;font-size:14px">OSM: {tag_key} — {area_label}</div>
      <div style="color:#52514e;margin-bottom:6px">{len(rows):,} features
        · bigquery-public-data.geo_openstreetmap</div>
      {legend_rows}
    </div>"""))

    xmin, ymin, xmax, ymax = boundary["geom"].bounds
    m.fit_bounds([[ymin, xmin], [ymax, xmax]])
    folium.LayerControl(collapsed=False).add_to(m)
    return m


def generate_map(client, province, amphoe, tambon, tag_key, tag_values,
                 max_features, max_gb):
    """orchestrate ทั้ง 3 ขั้น — ใช้ร่วมกันทั้งโหมด CLI และโหมด web"""
    if not (province or amphoe or tambon):
        raise TaskError("ต้องระบุพื้นที่อย่างน้อย 1 ระดับ (จังหวัด/อำเภอ/ตำบล)")

    boundary, area_label = resolve_boundary(client, province, amphoe, tambon, max_gb)

    print(f"ขั้นที่ 2: ดึง feature ({tag_key}"
          + (f" ใน {tag_values}" if tag_values else " ทุกค่า")
          + f") ภายใน{area_label}")
    rows = fetch_features(client, boundary["geom"], tag_key, tag_values,
                          max_features, max_gb)
    if not rows:
        raise TaskError(
            f"ไม่พบ feature ที่มี tag '{tag_key}' ใน{area_label} "
            "ลองเปลี่ยน tag หรือขยายพื้นที่")
    if len(rows) >= max_features:
        print(f"  คำเตือน: ผลลัพธ์ชนเพดาน {max_features:,} feature "
              "(ข้อมูลจริงอาจมีมากกว่านี้)")

    print("ขั้นที่ 3: สร้างแผนที่")
    return build_map(rows, boundary, area_label, tag_key), area_label, len(rows)


# ---------------------------------------------------------------------------
# โหมด Web — เปิดหน้าฟอร์มในเบราว์เซอร์ เลือกพื้นที่/tag แล้วแสดงแผนที่ทันที
# ใช้ http.server ใน stdlib จึงไม่ต้องติดตั้งไลบรารีเพิ่ม
# ---------------------------------------------------------------------------
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

FORM_PAGE = """<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OSM BigQuery Map</title>
<style>
  body {{ font-family: system-ui, 'Segoe UI', sans-serif; background: #f9f9f7;
         color: #0b0b0b; margin: 0; display: flex; justify-content: center; }}
  main {{ background: #fcfcfb; border: 1px solid rgba(11,11,11,.10); border-radius: 12px;
          padding: 28px 32px; margin: 40px 16px; max-width: 520px; width: 100%;
          box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  p.sub {{ color: #52514e; font-size: 13px; margin: 0 0 20px; }}
  label {{ display: block; font-size: 13px; font-weight: 600; margin: 14px 0 4px; }}
  small {{ color: #898781; font-weight: 400; }}
  input, select {{ width: 100%; box-sizing: border-box; padding: 8px 10px; font-size: 14px;
           border: 1px solid #c3c2b7; border-radius: 6px; background: #fff; }}
  .row {{ display: flex; gap: 12px; }} .row > div {{ flex: 1; }}
  button {{ margin-top: 22px; width: 100%; padding: 11px; font-size: 15px; font-weight: 600;
            color: #fff; background: #2a78d6; border: 0; border-radius: 8px; cursor: pointer; }}
  button:hover {{ background: #256abf; }}
  #busy {{ display: none; position: fixed; inset: 0; background: #fcfcfbee; z-index: 99;
           flex-direction: column; align-items: center; justify-content: center; gap: 14px; }}
  .spin {{ width: 36px; height: 36px; border: 4px solid #e1e0d9; border-top-color: #2a78d6;
           border-radius: 50%; animation: r 0.9s linear infinite; }}
  @keyframes r {{ to {{ transform: rotate(360deg); }} }}
</style></head><body>
<main>
  <h1>แผนที่ OSM จาก BigQuery</h1>
  <p class="sub">bigquery-public-data.geo_openstreetmap.planet_features</p>
  <form action="/map" onsubmit="document.getElementById('busy').style.display='flex'">
    <label>จังหวัด</label>
    <input name="province" value="{province}" placeholder="เช่น ชลบุรี">
    <div class="row">
      <div><label>อำเภอ/เขต <small>(ว่าง = ทั้งจังหวัด)</small></label>
        <input name="amphoe" value="{amphoe}"></div>
      <div><label>ตำบล/แขวง <small>(ว่าง = ทั้งอำเภอ)</small></label>
        <input name="tambon" value="{tambon}"></div>
    </div>
    <div class="row">
      <div><label>OSM tag key</label>
        <select name="key">
          <option>amenity</option><option>highway</option><option>building</option>
          <option>tourism</option><option>shop</option><option>leisure</option>
          <option>waterway</option><option>landuse</option><option>natural</option>
        </select></div>
      <div><label>ค่า tag <small>(เว้นวรรคคั่น, ว่าง = ทุกค่า)</small></label>
        <input name="values" placeholder="เช่น school hospital"></div>
    </div>
    <div class="row">
      <div><label>feature สูงสุด</label>
        <input name="max_features" type="number" value="{max_features}" min="100" max="50000"></div>
      <div><label>เพดานสแกน (GB)</label>
        <input name="max_gb" type="number" value="{max_gb}" min="1" max="500"></div>
    </div>
    <button>สร้างแผนที่</button>
  </form>
</main>
<div id="busy"><div class="spin"></div>
  <div>กำลัง query BigQuery... อาจใช้เวลา 10–60 วินาที</div></div>
</body></html>"""

ERROR_PAGE = """<!doctype html>
<html lang="th"><head><meta charset="utf-8"><title>เกิดข้อผิดพลาด</title>
<style>body{{font-family:system-ui,'Segoe UI',sans-serif;background:#f9f9f7;color:#0b0b0b;
display:flex;justify-content:center}}main{{background:#fcfcfb;max-width:520px;width:100%;
margin:40px 16px;padding:24px 28px;border-radius:12px;border:1px solid rgba(11,11,11,.10)}}
h1{{font-size:17px;color:#d03b3b}}pre{{white-space:pre-wrap;font-family:inherit;
color:#52514e}}a{{color:#2a78d6}}</style></head><body><main>
<h1>สร้างแผนที่ไม่สำเร็จ</h1><pre>{message}</pre>
<a href="/">← กลับไปแก้เงื่อนไข</a></main></body></html>"""

BACK_BUTTON = """<a href="/" style="position:fixed;bottom:18px;left:12px;z-index:9999;
background:#2a78d6;color:#fff;text-decoration:none;font-family:system-ui,sans-serif;
font-size:13px;font-weight:600;padding:8px 14px;border-radius:8px;
box-shadow:0 1px 4px rgba(0,0,0,.25)">◀ ค้นหาใหม่</a>"""


class MapHandler(BaseHTTPRequestHandler):
    client = None          # ตั้งค่าจาก serve()
    defaults = {}
    cache = {}             # จำผลลัพธ์เดิม จะได้ไม่ query ซ้ำเมื่อเงื่อนไขเดิม

    def _send_html(self, code, html):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._send_html(200, FORM_PAGE.format(**self.defaults))
        elif url.path == "/map":
            self.handle_map(parse_qs(url.query))
        else:
            self._send_html(404, ERROR_PAGE.format(message="ไม่พบหน้านี้"))

    def handle_map(self, qs):
        def val(key, default=""):
            return qs.get(key, [default])[0].strip()
        try:
            province = val("province")
            amphoe = val("amphoe")
            tambon = val("tambon")
            tag_key = val("key", DEFAULT_TAG_KEY) or DEFAULT_TAG_KEY
            tag_values = val("values").split()
            max_features = min(int(val("max_features") or DEFAULT_MAX_FEATURES), 50000)
            max_gb = min(float(val("max_gb") or self.defaults["max_gb"]), 500)

            cache_key = (province, amphoe, tambon, tag_key,
                         tuple(tag_values), max_features)
            if cache_key not in self.cache:
                m, _, _ = generate_map(self.client, province, amphoe, tambon,
                                       tag_key, tag_values, max_features, max_gb)
                if len(self.cache) >= 20:      # กันหน่วยความจำบวม
                    self.cache.pop(next(iter(self.cache)))
                self.cache[cache_key] = m.get_root().render()
            html = self.cache[cache_key].replace("</body>", BACK_BUTTON + "</body>")
            self._send_html(200, html)
        except TaskError as e:
            self._send_html(400, ERROR_PAGE.format(message=str(e)))
        except Exception as e:                 # กัน server ตายจาก error ไม่คาดคิด
            self._send_html(500, ERROR_PAGE.format(message=f"{type(e).__name__}: {e}"))

    def log_message(self, fmt, *a):
        print(f"  [web] {self.address_string()} {fmt % a}")


def serve(client, host, port, args):
    MapHandler.client = client
    MapHandler.defaults = {
        "province": args.province, "amphoe": args.amphoe, "tambon": args.tambon,
        "max_features": args.max_features, "max_gb": int(args.max_gb),
    }
    server = ThreadingHTTPServer((host, port), MapHandler)
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print(f"เปิดเบราว์เซอร์ที่  http://{shown}:{port}  (หยุด server ด้วย Ctrl+C)")
    if host == "0.0.0.0":
        print("  โหมดแชร์ใน LAN: เครื่องอื่นในวงเดียวกันเข้าผ่าน http://<IP เครื่องนี้>:"
              f"{port} ได้")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nหยุด server แล้ว")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="สร้างแผนที่ interactive จาก BigQuery OSM planet_features",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
                    help="GCP billing project id")
    ap.add_argument("--province", default=DEFAULT_PROVINCE, help="ชื่อจังหวัด (ไทย/อังกฤษ)")
    ap.add_argument("--amphoe", default=DEFAULT_AMPHOE, help="ชื่ออำเภอ/เขต (เว้นว่าง = ทั้งจังหวัด)")
    ap.add_argument("--tambon", default=DEFAULT_TAMBON, help="ชื่อตำบล/แขวง (เว้นว่าง = ทั้งอำเภอ)")
    ap.add_argument("--key", default=DEFAULT_TAG_KEY,
                    help="OSM tag key ที่ต้องการ เช่น amenity, highway, building, tourism")
    ap.add_argument("--values", nargs="*", default=DEFAULT_TAG_VALUES,
                    help="จำกัดค่า tag เช่น school hospital (ว่าง = ทุกค่า)")
    ap.add_argument("--max-features", type=int, default=DEFAULT_MAX_FEATURES,
                    help="จำนวน feature สูงสุดบนแผนที่")
    ap.add_argument("--max-gb", type=float, default=DEFAULT_MAX_GB_BILLED,
                    help="เพดานปริมาณข้อมูลที่ยอมให้สแกนต่อ query (GB)")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help="ชื่อไฟล์ HTML ผลลัพธ์ (โหมด CLI)")
    ap.add_argument("--serve", action="store_true",
                    help="เปิดเป็น web server: เลือกเงื่อนไขผ่านฟอร์มในเบราว์เซอร์")
    ap.add_argument("--host", default="127.0.0.1",
                    help="host ของ web server (ใช้ 0.0.0.0 เพื่อแชร์ใน LAN)")
    ap.add_argument("--port", type=int, default=8000, help="port ของ web server")
    args = ap.parse_args()

    try:
        client = make_client(args.project)
        if args.serve:
            serve(client, args.host, args.port, args)
            return
        m, _, _ = generate_map(client, args.province, args.amphoe, args.tambon,
                               args.key, args.values, args.max_features, args.max_gb)
        m.save(args.output)
        print(f"\nเสร็จสิ้น: เปิดไฟล์ {os.path.abspath(args.output)} ในเบราว์เซอร์ได้เลย")
    except TaskError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
