# คู่มือ Git CLI ฉบับใช้งานจริง

รวมคำสั่ง git ที่ใช้บ่อย เรียงตามลำดับการทำงานจริง พร้อมคำอธิบายภาษาไทย

---

## 1. ตั้งค่าครั้งแรก (ทำครั้งเดียวต่อเครื่อง)

```bash
git config --global user.name "ชื่อของคุณ"
git config --global user.email "you@example.com"

# ดูค่าที่ตั้งไว้ทั้งหมด
git config --list

# ตั้ง editor และชื่อ branch เริ่มต้น (แนะนำ)
git config --global init.defaultBranch main
git config --global core.editor "code --wait"
```

---

## 2. เริ่มต้น repository

```bash
# สร้าง repo ใหม่ในโฟลเดอร์ปัจจุบัน
git init

# หรือ clone repo ที่มีอยู่แล้ว
git clone https://github.com/user/repo.git
git clone https://github.com/user/repo.git ชื่อโฟลเดอร์ปลายทาง
```

---

## 3. วงจรงานประจำวัน: status → add → commit

```bash
# ดูสถานะไฟล์ (ใช้บ่อยที่สุด — พิมพ์ก่อนทำอะไรเสมอ)
git status
git status --short        # แบบย่อ: ?? = ยังไม่ track, M = แก้ไข, A = staged

# เลือกไฟล์เข้า staging area
git add ไฟล์.py           # ทีละไฟล์
git add src/              # ทั้งโฟลเดอร์
git add .                 # ทุกไฟล์ที่เปลี่ยน (ระวัง: ตรวจ git status ก่อน)

# บันทึก commit
git commit -m "อธิบายว่าทำอะไร"

# add + commit ไฟล์ที่ track อยู่แล้วในคำสั่งเดียว (ไฟล์ใหม่ไม่รวม)
git commit -am "ข้อความ"
```

**เขียน commit message ที่ดี**: บอก "ทำอะไร-เพราะอะไร" สั้น กระชับ เช่น
`เพิ่ม filter ระดับตำบลใน BigQuery-Task` ดีกว่า `update code`

---

## 4. ดูประวัติและความเปลี่ยนแปลง

```bash
git log                       # ประวัติ commit เต็ม
git log --oneline             # บรรทัดเดียวต่อ commit
git log --oneline --graph     # พร้อมผังกิ่ง branch
git log -5                    # 5 commit ล่าสุด
git log -- ไฟล์.py            # ประวัติเฉพาะไฟล์

git diff                      # สิ่งที่แก้แต่ยังไม่ add
git diff --staged             # สิ่งที่ add แล้วแต่ยังไม่ commit
git diff main..feature-x      # ต่างกันระหว่าง 2 branch

git show a934e74              # ดูรายละเอียด commit นั้น ๆ
git blame ไฟล์.py             # ใครแก้บรรทัดไหน commit ไหน
```

---

## 5. Branch — แยกงานไม่ให้ปนกัน

```bash
git branch                    # ดู branch ทั้งหมด (* = อยู่ที่ไหน)
git branch feature-map        # สร้าง branch ใหม่ (ยังไม่ย้ายไป)
git switch feature-map        # ย้ายไป branch นั้น
git switch -c feature-map     # สร้าง + ย้ายไปในคำสั่งเดียว
git switch -                  # กลับ branch ก่อนหน้า

# รวมงานจาก branch อื่นเข้า branch ปัจจุบัน
git switch main
git merge feature-map

# ลบ branch ที่ merge แล้ว
git branch -d feature-map
git branch -D feature-map     # บังคับลบแม้ยังไม่ merge (ระวัง)
```

**เมื่อ merge แล้ว conflict**: git จะแทรกเครื่องหมาย `<<<<<<<` / `=======` / `>>>>>>>`
ในไฟล์ที่ชนกัน — แก้ไฟล์ให้ถูกต้อง ลบเครื่องหมายออก แล้ว `git add` + `git commit`

---

## 6. Remote — ทำงานกับ GitHub/GitLab

```bash
git remote -v                                  # ดู remote ที่ผูกไว้
git remote add origin https://github.com/user/repo.git

git push -u origin main       # push ครั้งแรก (-u = จำปลายทางไว้)
git push                      # ครั้งต่อไปพิมพ์แค่นี้

git pull                      # ดึงงานล่าสุดจาก remote มารวม (fetch + merge)
git fetch                     # ดึงมาดูก่อนแต่ยังไม่รวม
```

**ลำดับที่ปลอดภัย**: `git pull` ก่อน `git push` เสมอ เพื่อรวมงานคนอื่นก่อนส่งของเรา

---

## 7. แก้ตัว — ย้อน/ยกเลิกสิ่งที่ทำ

```bash
# เอาไฟล์ออกจาก staging (ยกเลิก git add — ไฟล์ไม่หาย)
git restore --staged ไฟล์.py

# ทิ้งการแก้ไขในไฟล์ กลับไปเป็นเหมือน commit ล่าสุด (ระวัง: งานที่แก้หายจริง)
git restore ไฟล์.py

# แก้ commit ล่าสุด (เปลี่ยนข้อความ หรือเพิ่มไฟล์ที่ลืม add)
git add ไฟล์ที่ลืม.py
git commit --amend -m "ข้อความใหม่"
# ห้าม amend commit ที่ push ไปแล้ว

# สร้าง commit ใหม่ที่ผลลัพธ์ตรงข้ามกับ commit เดิม (ปลอดภัย ใช้กับงานที่ push แล้วได้)
git revert a934e74

# ถอย branch กลับไปยัง commit หนึ่ง
git reset --soft HEAD~1       # ถอย 1 commit, งานยังอยู่ใน staging
git reset --mixed HEAD~1      # ถอย 1 commit, งานยังอยู่แต่ไม่ staged (ค่าตั้งต้น)
git reset --hard HEAD~1       # ถอย 1 commit และทิ้งงานทั้งหมด (อันตราย — คิดก่อนใช้)

# พักงานชั่วคราวโดยไม่ commit (เช่น ต้องสลับ branch ด่วน)
git stash                     # เก็บงานเข้าลิ้นชัก
git stash list                # ดูของในลิ้นชัก
git stash pop                 # เอางานล่าสุดกลับมา
```

**หลงทางแล้วอยากกู้**: `git reflog` แสดงทุกจุดที่ HEAD เคยอยู่ —
ใช้ `git reset --hard HEAD@{n}` กลับไปจุดนั้นได้แม้หลัง reset ผิด

---

## 8. .gitignore — บอก git ว่าไฟล์ไหนไม่ต้องสน

สร้างไฟล์ชื่อ `.gitignore` ที่ root ของ repo หนึ่งบรรทัดต่อหนึ่ง pattern:

```gitignore
.venv/              # ทั้งโฟลเดอร์
__pycache__/
*.pyc               # ทุกไฟล์นามสกุลนี้
*.html              # ผลลัพธ์ที่ generate ได้ใหม่ ไม่ต้อง commit
.env                # ไฟล์ข้อมูลลับ — ห้าม commit เด็ดขาด
*credentials*.json
```

```bash
# ถ้าเผลอ commit ไฟล์ไปก่อนใส่ .gitignore — เอาออกจาก git แต่เก็บไฟล์ไว้ในเครื่อง
git rm --cached ไฟล์.html
git rm -r --cached .venv/
git commit -m "เอาไฟล์ generated ออกจาก git"

# ตรวจว่าไฟล์หนึ่งโดน ignore เพราะ pattern ไหน
git check-ignore -v ไฟล์.html
```

---

## 9. Workflow มาตรฐานสรุปสั้น ๆ

```bash
git pull                          # 1) ดึงงานล่าสุดก่อนเริ่ม
git switch -c feature-ชื่องาน     # 2) แยก branch ทำงาน
# ...แก้โค้ด...
git status                        # 3) ตรวจว่าแก้อะไรไปบ้าง
git add ไฟล์ที่เกี่ยวข้อง          # 4) เลือกเฉพาะไฟล์ที่ตั้งใจแก้
git commit -m "อธิบายงาน"         # 5) บันทึก
git switch main && git pull       # 6) กลับ main + อัปเดต
git merge feature-ชื่องาน          # 7) รวมงาน
git push                          # 8) ส่งขึ้น remote
```

---

## 10. คำสั่งช่วยชีวิตเมื่อไม่แน่ใจ

| สถานการณ์ | คำสั่ง |
|---|---|
| ตอนนี้อยู่ตรงไหน มีอะไรค้าง | `git status` |
| เมื่อกี้ทำอะไรไปบ้าง | `git log --oneline -10` |
| แก้ไฟล์ไหนไปบ้าง แก้ตรงไหน | `git diff` |
| อยากยกเลิก add | `git restore --staged <ไฟล์>` |
| อยากทิ้งการแก้ไข | `git restore <ไฟล์>` (งานหายจริง คิดก่อน) |
| reset ผิด อยากกู้ | `git reflog` แล้ว `git reset --hard HEAD@{n}` |
| ดู help ของคำสั่งใด ๆ | `git help <คำสั่ง>` เช่น `git help merge` |
