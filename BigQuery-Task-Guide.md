# คู่มือการใช้งาน BigQuery-Task.py

สร้างแผนที่ HTML แบบ Interactive จากข้อมูล OpenStreetMap บน BigQuery Public Dataset
(`bigquery-public-data.geo_openstreetmap.planet_features`)
โดยกรองข้อมูลตามเขตการปกครองของไทย (จังหวัด / อำเภอ / ตำบล) และชนิดข้อมูล (OSM tag)

แหล่งข้อมูลที่ใช้ 2 ตาราง:

| ข้อมูล | ตาราง | หมายเหตุ |
|---|---|---|
| feature (สถานที่/ถนน/อาคาร) | `geo_openstreetmap.planet_features` | ข้อมูล OSM ทั้งโลก |
| ขอบเขตการปกครอง | `overture_maps.division_area` | ใช้แทน เพราะ planet_features ไม่มี polygon ระดับอำเภอ/ตำบล |

> ขอบเขตใน Overture: จังหวัดครบ 77, อำเภอ/เขตครบ 928 (ชื่ออังกฤษ — ถ้าพิมพ์ไทย
> สคริปต์จะหาจุดศูนย์กลางอำเภอจาก OSM แล้ว match ให้อัตโนมัติ), **ตำบลมีเพียงบางส่วน**
> ถ้าไม่พบตำบลให้ถอยไปใช้ระดับอำเภอ

---

## 1. การเตรียมเครื่อง (ทำครั้งเดียว)

### 1.1 ติดตั้งไลบรารี

> เครื่องอบรมนี้เป็น Python 3.14 **แบบ 32-bit** บางแพ็กเกจไม่มี wheel สำเร็จรูป
> ต้องติดตั้งตามลำดับและเงื่อนไขด้านล่างนี้เท่านั้น (ติดตั้งใน venv ให้เรียบร้อยแล้ว)

```powershell
# เปิดใช้งาน virtual environment ก่อน
.\.venv\Scripts\Activate.ps1

# 1) cryptography ต้อง pin เวอร์ชันสุดท้ายที่มี wheel สำหรับ win32
pip install "cryptography==44.0.3" --only-binary :all:

# 2) google-crc32c ติดตั้งโหมด pure-Python (ไม่มี wheel win32)
$env:CRC32C_PURE_PYTHON = "1"
pip install google-crc32c

# 3) BigQuery client ติดตั้งแบบไม่เอา dependencies (เลี่ยง grpcio ที่ไม่มี wheel win32
#    — client ใช้ REST API จึงไม่จำเป็นต้องมี grpcio)
pip install --only-binary :all: --no-deps google-cloud-bigquery
pip install --only-binary :all: "google-api-core>=2.11" "google-auth>=2.14" `
    "google-cloud-core>=2.4" "google-resumable-media>=2.0" packaging python-dateutil requests

# 4) ไลบรารีแผนที่และเรขาคณิต
pip install --only-binary :all: folium shapely
```

ถ้าเครื่องเป็น Python **64-bit** ปกติ ติดตั้งบรรทัดเดียวจบ:

```powershell
pip install google-cloud-bigquery folium shapely
```

### 1.2 ยืนยันตัวตน Google Cloud (เลือกอย่างใดอย่างหนึ่ง)

```powershell
# วิธีที่ 1: login ด้วยบัญชี Google ของตัวเอง (ต้องติดตั้ง gcloud CLI ก่อน)
gcloud auth application-default login

# วิธีที่ 2: ใช้ไฟล์ service account JSON
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account.json"
```

### 1.3 กำหนด billing project

Dataset เป็น public แต่การ query ต้องมี GCP project สำหรับคิดโควตา
(free tier ได้ 1 TB ต่อเดือน)

```powershell
$env:GOOGLE_CLOUD_PROJECT = "your-project-id"
# หรือใส่ --project your-project-id ตอนรันก็ได้
```

### 1.4 ตั้งค่าผ่านไฟล์ `.env` (สะดวกกว่า — ตั้งครั้งเดียวใช้ได้ทุกครั้ง)

copy เทมเพลตแล้วกรอกค่าจริง สคริปต์จะอ่านให้อัตโนมัติตอนรัน:

```powershell
Copy-Item .env.example .env
notepad .env
```

```ini
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json   # เว้นว่างได้ถ้าใช้ gcloud login
```

> ไฟล์ `.env` ถูก ignore ใน git แล้ว จะไม่ถูก commit ขึ้น repo
> ลำดับความสำคัญ: ค่าที่ตั้งใน environment จริง > ค่าในไฟล์ `.env`

---

## 2. ตัวอย่างการรัน

### 2.1 พื้นฐาน — สถานที่ (amenity) ทุกชนิดในอำเภอศรีราชา จังหวัดชลบุรี

```powershell
python BigQuery-Task.py --province ชลบุรี --amphoe ศรีราชา
```

### 2.2 เจาะจงชนิดสถานที่ — โรงเรียนและโรงพยาบาล

```powershell
python BigQuery-Task.py --province ชลบุรี --amphoe ศรีราชา --key amenity --values school hospital
```

### 2.3 ทั้งจังหวัด — ถนนสายหลักของภูเก็ต

```powershell
python BigQuery-Task.py --province ภูเก็ต --key highway --values primary secondary trunk
```

### 2.4 ระดับตำบล — amenity ทุกชนิดในตำบลสุเทพ

```powershell
python BigQuery-Task.py --province เชียงใหม่ --amphoe เมืองเชียงใหม่ --tambon สุเทพ --key amenity
```

### 2.5 กรุงเทพฯ — ใช้ชื่อเขต/แขวงแทนอำเภอ/ตำบล

```powershell
python BigQuery-Task.py --province กรุงเทพมหานคร --amphoe จตุจักร --key amenity --values cafe restaurant
```

### 2.6 สถานที่ท่องเที่ยว พร้อมตั้งชื่อไฟล์ผลลัพธ์เอง

```powershell
python BigQuery-Task.py --province เชียงราย --key tourism --output chiangrai_tourism.html
```

### 2.7 เพิ่มเพดานข้อมูลเมื่อพื้นที่ใหญ่/ข้อมูลเยอะ

```powershell
python BigQuery-Task.py --province นครราชสีมา --key highway --max-features 10000 --max-gb 120
```

### 2.8 โหมด Web — เลือกเงื่อนไขผ่านเบราว์เซอร์ (ไม่ต้องพิมพ์คำสั่งซ้ำ)

```powershell
python BigQuery-Task.py --serve
```

แล้วเปิด [http://localhost:8000](http://localhost:8000) จะเจอหน้าฟอร์มให้เลือกจังหวัด/อำเภอ/ตำบล/tag
กด "สร้างแผนที่" ระบบจะ query BigQuery แล้วแสดงแผนที่ทันที (เงื่อนไขเดิมที่เคย
query แล้วจะถูก cache ไว้ ไม่เสียโควตาซ้ำ)

```powershell
# แชร์ให้เครื่องอื่นในวง LAN เดียวกันเปิดดูได้ (เช่น ให้เพื่อนในห้องอบรม)
python BigQuery-Task.py --serve --host 0.0.0.0 --port 8000
# เครื่องอื่นเข้า http://<IP เครื่องเรา>:8000
```

> ข้อควรระวัง: `--host 0.0.0.0` เปิดให้ทุกเครื่องในเครือข่ายสั่ง query ด้วยโควตา
> project ของเราได้ ใช้เฉพาะเครือข่ายที่ไว้ใจ และปิด server เมื่อเลิกใช้ (Ctrl+C)

---

## 3. ตาราง Options ทั้งหมด

| Option             | ค่าตั้งต้น        | ความหมาย                                                                                    |
| ------------------ | --------------------------- | --------------------------------------------------------------------------------------------------- |
| `--project`      | env`GOOGLE_CLOUD_PROJECT` | GCP billing project id                                                                              |
| `--province`     | `ชลบุรี`            | ชื่อจังหวัด (ไทยหรืออังกฤษ ไม่ต้องใส่คำว่า "จังหวัด") |
| `--amphoe`       | `ศรีราชา`          | ชื่ออำเภอ/เขต — ใส่`--amphoe ""` เพื่อเอาทั้งจังหวัด           |
| `--tambon`       | (ว่าง)                  | ชื่อตำบล/แขวง                                                                           |
| `--key`          | `amenity`                 | OSM tag key เช่น`amenity` `highway` `building` `tourism` `shop` `leisure`           |
| `--values`       | (ทุกค่า)              | จำกัดค่าของ tag เช่น`school hospital`                                              |
| `--max-features` | `5000`                    | จำนวน feature สูงสุดที่นำมาแสดงบนแผนที่                               |
| `--max-gb`       | `60`                      | เพดานปริมาณข้อมูลที่ยอมให้ BigQuery สแกนต่อ query (GB)             |
| `--output`       | `osm_map.html`            | ชื่อไฟล์แผนที่ผลลัพธ์ (โหมด CLI)                                           |
| `--serve`        | (ปิด)                    | เปิดเป็น web server พร้อมหน้าฟอร์มเลือกเงื่อนไข                  |
| `--host`         | `127.0.0.1`               | host ของ web server (`0.0.0.0` = แชร์ใน LAN)                                             |
| `--port`         | `8000`                    | port ของ web server                                                                              |

### OSM tag ที่ใช้บ่อย

| `--key`    | `--values` ตัวอย่าง               | ได้อะไร                           |
| ------------ | ------------------------------------------- | ---------------------------------------- |
| `amenity`  | `school hospital clinic police fuel bank` | สถานที่บริการสาธารณะ |
| `highway`  | `motorway trunk primary secondary`        | โครงข่ายถนน                   |
| `building` | `hospital school temple`                  | อาคาร (polygon)                     |
| `tourism`  | `attraction hotel museum viewpoint`       | สถานที่ท่องเที่ยว       |
| `shop`     | `convenience supermarket`                 | ร้านค้า                           |
| `waterway` | `river canal`                             | แม่น้ำลำคลอง                 |
| `landuse`  | `industrial residential farmland`         | การใช้ประโยชน์ที่ดิน |

ดูค่า tag ทั้งหมดได้ที่ [https://wiki.openstreetmap.org/wiki/Map_features](https://wiki.openstreetmap.org/wiki/Map_features)

---

## 4. กลไกควบคุมปริมาณข้อมูล (สำคัญ)

ตาราง `planet_features` เก็บข้อมูล OSM **ทั้งโลก** (หลายร้อย GB) สคริปต์จึงป้องกัน 4 ชั้น:

1. **`ST_INTERSECTSBOX` ด้วยค่าคงที่** — ตารางถูก cluster ตามคอลัมน์ geometry
   BigQuery จึงตัดข้อมูลนอกกรอบพื้นที่ออกได้ตั้งแต่ชั้น storage (ลด bytes ที่คิดเงินจริง)
2. **`ST_INTERSECTS` กับ polygon ขอบเขตจริง** — ตัดข้อมูลนอกเขตการปกครองแบบแม่นยำ
3. **`LIMIT --max-features`** — ป้องกันไฟล์ HTML ใหญ่จนเบราว์เซอร์เปิดไม่ไหว
4. **`maximum_bytes_billed --max-gb`** — ถ้า query จะสแกนเกินเพดาน BigQuery
   จะยกเลิก query ให้ **ก่อนคิดเงิน**

> ตัวเลข dry-run ที่สคริปต์พิมพ์ (`ประมาณการขอบบน ... GB`) เป็นค่า **ก่อนหัก
> cluster pruning** — ปริมาณที่คิดเงินจริง (`สแกนจริง ... GB`) มักต่ำกว่ามาก

---

## 5. การอ่านผลลัพธ์บนแผนที่

- เปิดไฟล์ `.html` ที่ได้ในเบราว์เซอร์ได้โดยตรง ไม่ต้องมี server
- **เส้นประเทา** = ขอบเขตการปกครองที่เลือก
- **จุดสี** = feature แบบจุด (รวมกลุ่มอัตโนมัติเมื่อ zoom ออก — คลิกเพื่อขยาย)
- **เส้น/พื้นที่สี** = ถนน แม่น้ำ อาคาร ฯลฯ
- คลิก feature เพื่อดู tag ทั้งหมด + ลิงก์เปิดใน openstreetmap.org
- มุมขวาบน: เปิด/ปิดชั้นข้อมูลรายหมวด, สลับแผนที่ฐาน (CartoDB / OpenStreetMap)
- กล่องซ้ายบน: legend สีประจำหมวด (8 หมวดที่พบมากที่สุด ที่เหลือรวมเป็น "อื่น ๆ")

---

## 6. แก้ปัญหาที่พบบ่อย

| อาการ                                       | สาเหตุ / ทางแก้                                                                                                                     |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `ไม่พบ Google Cloud credentials`          | ยังไม่ได้ทำข้อ 1.2                                                                                                                |
| `ยังไม่ได้ระบุ billing project`   | ยังไม่ได้ทำข้อ 1.3                                                                                                                |
| `ไม่พบจังหวัด/อำเภอ '...'`        | สะกดชื่อผิด (พิมพ์ไทยหรืออังกฤษก็ได้) หรือลองระบุจังหวัดกำกับ |
| `ไม่พบขอบเขตตำบล...`        | Overture มีขอบเขตตำบลไม่ครบทุกตำบล — เว้นช่องตำบลว่างแล้วใช้ระดับอำเภอแทน |
| `query สแกนข้อมูลเกินเพดาน` | เพิ่ม`--max-gb` หรือแคบพื้นที่/tag ลง                                                                                    |
| `ผลลัพธ์ชนเพดาน ... feature`     | ข้อมูลจริงมีมากกว่าที่แสดง — แคบพื้นที่ลง หรือเพิ่ม`--max-features`                           |
| คำเตือน`32-bit Python` ตอนเริ่ม | แจ้งเตือนเรื่องความเร็วเท่านั้น ใช้งานได้ปกติ                                                       |
| แผนที่เปิดช้า/ค้าง              | ลด`--max-features` ลง (เช่น 2000)                                                                                                     |
