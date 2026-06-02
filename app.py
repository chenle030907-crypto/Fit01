"""
Fit No.1 - 极简健身饮食记录
Flask + SQLite + Gemini API
"""
import json, os, sqlite3, datetime
import requests
from flask import Flask, request, jsonify, send_from_directory, g

app = Flask(__name__, static_folder="static", static_url_path="")
API_KEY = os.environ.get("AI_API_KEY", "sk-9ea9964ac43747a58f962748888f69ee")
DB_PATH = os.path.join(os.environ.get("DATA_DIR", os.path.dirname(__file__)), "dongshi.db")
PORT = int(os.environ.get("PORT", 8080))

# ── DB helpers ──
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    g.pop("db", None)

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, nickname TEXT DEFAULT '健身者',
            gender INTEGER DEFAULT 1, height REAL DEFAULT 170,
            current_weight REAL DEFAULT 70, target_weight REAL DEFAULT 65,
            birth_date TEXT DEFAULT '1995-01-01', activity_level REAL DEFAULT 1.55,
            training_intensity TEXT DEFAULT '中强度',
            workout_type TEXT DEFAULT 'happy'
        );
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, meal_type TEXT NOT NULL, time TEXT,
            foods TEXT NOT NULL, note TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, start_time TEXT, duration INTEGER,
            type TEXT, exercises TEXT, calories INTEGER, note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS dishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE, foods TEXT NOT NULL,
            calories INTEGER, protein REAL, carbs REAL, fat REAL,
            tags TEXT, use_count INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, weight REAL, body_fat REAL,
            note TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS water (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, amount INTEGER NOT NULL, drink_type TEXT DEFAULT 'water',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT OR IGNORE INTO users (id) VALUES (1);
    """)
    db.commit()
    db.close()

# ── JSON cleanup ──
import re as _re
def extract_json(text):
    """从混合文本中暴力提取 JSON，支持对象和数组"""
    if not text: return None
    text = _re.sub(r'```(?:json)?\s*', '', text)
    text = _re.sub(r'```', '', text)
    text = _re.sub(r'^\*[^\n]*\n', '', text, flags=_re.MULTILINE)
    text = _re.sub(r'\(Self-correction:[^)]*\)', '', text)
    # Try array first
    arr_start = text.find('[')
    arr_end = text.rfind(']')
    if arr_start != -1 and arr_end > arr_start:
        return text[arr_start:arr_end+1]
    # Try object
    obj_start = text.find('{')
    obj_end = text.rfind('}')
    if obj_start != -1 and obj_end > obj_start:
        return text[obj_start:obj_end+1]
    return None

def parse_ai_json(reply):
    if not reply: return None
    try:
        chunk = extract_json(reply)
        if chunk: return json.loads(chunk)
    except: pass
    return None

# 硬编码兜底
PHOTO_FALLBACK = {"name":"未识别菜品（点击修改）","estimated_grams":300,"ingredients":[],"confidence":"low","calories":0,"protein":0,"carbs":0,"fat":0}

def normalize_photo_result(obj):
    """统一字段名：food_name→name, estimated_weight_g→estimated_grams"""
    d = {}
    d["name"] = obj.get("name") or obj.get("food_name") or obj.get("dish_name") or ""
    if not d["name"]: d["name"] = PHOTO_FALLBACK["name"]
    d["estimated_grams"] = obj.get("estimated_grams") or obj.get("estimated_weight_g") or obj.get("weight_g") or obj.get("grams") or 300
    d["ingredients"] = obj.get("ingredients") or obj.get("foods") or []
    d["confidence"] = obj.get("confidence") or "medium"
    d["calories"] = obj.get("calories") or (obj.get("nutrition") or {}).get("calories_kcal") or 0
    d["protein"] = obj.get("protein") or (obj.get("nutrition") or {}).get("protein_g") or 0
    d["carbs"] = obj.get("carbs") or (obj.get("nutrition") or {}).get("carbs_g") or 0
    d["fat"] = obj.get("fat") or (obj.get("nutrition") or {}).get("fat_g") or 0
    return d

# ── AI APIs (Qwen) ──
SYSTEM_PROMPT = """Role: 你是一位拥有10年经验的高级运动营养师与王牌体能教练。
Task: 负责计算用户的每日营养目标或单次运动的卡路里消耗。
Rule: 你必须基于用户的具体身高、体重、运动项目、强度、组数次数进行精准的生理学估算。拒绝给出模糊范围，必须给出明确的整数数值。
Output Format: 必须严格只返回JSON字符串，不要包含任何Markdown标记、解释或闲聊。"""

def call_ai(prompt, temp=0.1, max_tokens=1024, json_mode=False):
    if not API_KEY: return None
    try:
        body = {"model":"qwen3.6-flash","messages":[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":prompt}
        ],"temperature":temp,"max_tokens":max_tokens,"enable_thinking":False}
        if json_mode: body["response_format"] = {"type": "json_object"}
        r = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json=body, timeout=20
        )
        return r.json()["choices"][0]["message"]["content"]
    except: return None

def call_vision(prompt, image_base64, temp=0.1, max_tokens=512):
    if not API_KEY: return None
    try:
        r = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model":"qwen3.6-flash","messages":[{"role":"user","content":[
                {"type":"text","text":prompt},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image_base64}"}}
            ]}],"temperature":temp,"max_tokens":max_tokens,
            "enable_thinking":False},
            timeout=15
        )
        data = r.json()
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
            print(f"[vision] OK, {len(content)} chars: {content[:100]}")
            return content
        err = data.get("error", {})
        print(f"[vision] API error: {err.get('message', str(err)[:200])}")
        return None
    except Exception as e:
        print(f"[vision] exception: {e}")
        return None

# ── Static files ──
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ── User API ──
@app.route("/api/user", methods=["GET","POST"])
def user():
    db = get_db()
    if request.method == "GET":
        u = db.execute("SELECT * FROM users WHERE id=1").fetchone()
        return jsonify(dict(u) if u else {})
    data = request.get_json()
    fields = ["nickname","gender","height","current_weight","target_weight","birth_date","activity_level","training_intensity","workout_type","target_date"]
    vals = {k: data[k] for k in fields if k in data}
    if vals:
        cols = ", ".join(f"{k}=?" for k in vals)
        db.execute(f"UPDATE users SET {cols} WHERE id=1", list(vals.values()))
        db.commit()
    return jsonify({"ok":True})

# ── Meals API ──
@app.route("/api/meals", methods=["GET","POST"])
def meals():
    db = get_db()
    if request.method == "GET":
        date = request.args.get("date", datetime.date.today().isoformat())
        rows = db.execute("SELECT * FROM meals WHERE date=? ORDER BY time", [date]).fetchall()
        return jsonify([dict(r) for r in rows])
    data = request.get_json()
    db.execute("INSERT INTO meals (date,meal_type,time,foods,note) VALUES (?,?,?,?,?)",
        [data.get("date",str(datetime.date.today())), data.get("meal_type","lunch"),
         data.get("time","12:00"), json.dumps(data.get("foods",[])), data.get("note","")])
    db.commit()
    return jsonify({"ok":True, "id": db.execute("SELECT last_insert_rowid()").fetchone()[0]})

@app.route("/api/meals/<int:id>", methods=["DELETE"])
def delete_meal(id):
    db = get_db()
    db.execute("DELETE FROM meals WHERE id=?", [id])
    db.commit()
    return jsonify({"ok":True})

# ── Workouts API ──
@app.route("/api/workouts", methods=["GET","POST"])
def workouts():
    db = get_db()
    if request.method == "GET":
        date = request.args.get("date", datetime.date.today().isoformat())
        rows = db.execute("SELECT * FROM workouts WHERE date=? ORDER BY start_time", [date]).fetchall()
        return jsonify([dict(r) for r in rows])
    data = request.get_json()
    db.execute("INSERT INTO workouts (date,start_time,duration,type,exercises,calories,note) VALUES (?,?,?,?,?,?,?)",
        [data.get("date",str(datetime.date.today())), data.get("start_time",""), data.get("duration",0),
         data.get("type","strength"), json.dumps(data.get("exercises",[])),
         data.get("calories",0), data.get("note","")])
    db.commit()
    return jsonify({"ok":True, "id": db.execute("SELECT last_insert_rowid()").fetchone()[0]})

@app.route("/api/workouts/<int:id>", methods=["DELETE"])
def delete_workout(id):
    db = get_db()
    db.execute("DELETE FROM workouts WHERE id=?", [id])
    db.commit()
    return jsonify({"ok":True})

# ── Dishes API ──
@app.route("/api/dishes", methods=["GET","POST"])
def dishes():
    db = get_db()
    if request.method == "GET":
        tag = request.args.get("tag","")
        if tag:
            rows = db.execute("SELECT * FROM dishes WHERE tags LIKE ? ORDER BY use_count DESC", [f"%{tag}%"]).fetchall()
        else:
            rows = db.execute("SELECT * FROM dishes ORDER BY use_count DESC LIMIT 30").fetchall()
        return jsonify([dict(r) for r in rows])
    data = request.get_json()
    existing = db.execute("SELECT * FROM dishes WHERE name=?", [data.get("name")]).fetchone()
    if existing:
        db.execute("UPDATE dishes SET foods=?,calories=?,protein=?,carbs=?,fat=?,tags=?,use_count=use_count+1 WHERE id=?",
            [json.dumps(data.get("foods",[])), data.get("calories",0), data.get("protein",0),
             data.get("carbs",0), data.get("fat",0), data.get("tags",""), existing["id"]])
    else:
        db.execute("INSERT INTO dishes (name,foods,calories,protein,carbs,fat,tags) VALUES (?,?,?,?,?,?,?)",
            [data.get("name"), json.dumps(data.get("foods",[])), data.get("calories",0),
             data.get("protein",0), data.get("carbs",0), data.get("fat",0), data.get("tags","")])
    db.commit()
    return jsonify({"ok":True})

@app.route("/api/dishes/<int:id>", methods=["DELETE"])
def delete_dish(id):
    db = get_db()
    db.execute("DELETE FROM dishes WHERE id=?", [id])
    db.commit()
    return jsonify({"ok":True})

# ── Measurements API ──
@app.route("/api/measurements", methods=["GET","POST"])
def measurements():
    db = get_db()
    if request.method == "GET":
        try:
            rows = db.execute("SELECT * FROM measurements GROUP BY date ORDER BY date DESC LIMIT 90").fetchall()
        except:
            rows = db.execute("SELECT * FROM measurements ORDER BY date DESC LIMIT 90").fetchall()
        return jsonify([dict(r) for r in rows])
    try:
        data = request.get_json()
        date = data.get("date", str(datetime.date.today()))
        weight = float(data.get("weight", 0))
        body_fat = data.get("body_fat")
        if body_fat is not None: body_fat = float(body_fat)
        note = data.get("note", "")
        existing = db.execute("SELECT id FROM measurements WHERE date=?", [date]).fetchone()
        if existing:
            db.execute("UPDATE measurements SET weight=?,body_fat=?,note=? WHERE id=?",
                [weight, body_fat, note, existing["id"]])
        else:
            db.execute("INSERT INTO measurements (date,weight,body_fat,note) VALUES (?,?,?,?)",
                [date, weight, body_fat, note])
        if weight:
            db.execute("UPDATE users SET current_weight=? WHERE id=1", [weight])
        db.commit()
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ── Gemini AI API ──
@app.route("/api/parse-food", methods=["POST"])
def parse_food():
    text = request.get_json().get("text","").strip()
    if not text: return jsonify({"error":"empty"}), 400
    prompt = f"""你是营养数据库。解析输入的食物，返回JSON数组。每个对象: name(中文), amount(克), unit("g"), calories, protein, carbs, fat, fiber, category("grains"|"meat"|"seafood"|"vegetables"|"fruits"|"dairy"|"legumes"|"snacks"|"beverages"|"oils"|"condiments"|"dishes")。只返回JSON数组。
输入: {text}"""
    reply = call_ai(prompt)
    if not reply: return jsonify({"error":"gemini failed"}), 500
    m = __import__("re").search(r"\[[\s\S]*\]", reply)
    if not m: return jsonify({"error":"parse", "raw":reply}), 422
    return jsonify({"foods": json.loads(m.group(0))})

@app.route("/api/recommend", methods=["POST"])
def recommend():
    data = request.get_json()
    mode = data.get("mode","happy")
    user = data.get("user",{})
    eaten = data.get("eaten",{})
    goals = data.get("goals",{})
    remaining = {
        "cal": max(0, goals.get("calories",2000) - eaten.get("calories",0)),
        "protein": max(0, goals.get("protein",90) - eaten.get("protein",0)),
        "carbs": max(0, goals.get("carbs",250) - eaten.get("carbs",0)),
        "fat": max(0, goals.get("fat",55) - eaten.get("fat",0)),
    }
    mn = {"cardio":"有氧日-高碳水","strength":"无氧日-高蛋白","happy":"休息日-低卡","cheat":"放纵日-大吃"}
    prompt = f"""健身饮食顾问。今天是{mn.get(mode,mode)}。用户{user.get('weight',70)}kg,{user.get('height',170)}cm。剩余热量:{remaining}。推荐3-5道中餐。返回JSON:{{"recommendations":[{{"name","calories","protein","carbs","fat","serving","reason","ingredients":[]}}],"summary":"一句话"}}。只返回JSON。"""
    reply = call_ai(prompt, temp=0.4, max_tokens=2048)
    if not reply: return jsonify({"error":"gemini failed"}), 500
    m = __import__("re").search(r"\{[\s\S]*\}", reply)
    if not m: return jsonify({"error":"parse","raw":reply}), 422
    return jsonify(json.loads(m.group(0)))

# ── Nutrition calc ──
@app.route("/api/nutrition", methods=["POST"])
def calc_nutrition():
    data = request.get_json()
    w = data.get("current_weight",70)
    h = data.get("height",170)
    bw = data.get("birth_date","1995-01-01")
    g = data.get("gender",1)
    al = data.get("activity_level",1.55)
    tw = data.get("target_weight",65)
    ti = data.get("training_intensity","中强度")
    td = data.get("target_date","")
    cd = data.get("current_date", str(datetime.date.today()))
    mode = data.get("mode","happy")
    age = datetime.date.today().year - int(bw[:4])
    weight_phase = "减脂/刷脂期" if tw < w else ("增肌期" if tw > w else "维持期")
    time_info = ""
    if td:
        try:
            target_dt = datetime.date.fromisoformat(td)
            current_dt = datetime.date.fromisoformat(cd)
            days = (target_dt - current_dt).days
            weeks = round(days/7, 1)
            time_info = f"\n- 目标达成时限: 从{cd}到{td},共{days}天({weeks}周)"
            weight_diff = abs(tw - w)
            if weight_diff > 0 and weeks > 0:
                weekly_rate = round(weight_diff/weeks, 1)
                time_info += f"\n- 需每周改变约{weekly_rate}kg"
                if weekly_rate > 1:
                    time_info += "（⚠️ 速度偏激进，请AI重点提醒健康风险）"
                elif weekly_rate > 0.5:
                    time_info += "（中等速度，需严格饮食控制）"
                else:
                    time_info += "（安全平稳区间）"
        except: pass
    prompt = f"""【用户生理状态与阶段目标】
- 身高: {h}cm, 当前体重: {w}kg, 目标体重: {tw}kg, 年龄: {age}岁, 性别: {'男' if g==1 else '女'}
- 体重阶段: {weight_phase}
- 长期总体训练强度基调: {ti}{time_info}

【今日选定模式】{mode}（{'有氧日-大幅放大热量' if mode=='cardio' else '无氧日-主打高蛋白' if mode=='strength' else 'Happy休息日-基础代谢维护' if mode=='happy' else '放纵日-补偿机制放大消耗'}）

【AI营养师计算要求】
1. 根据身高、当前体重、年龄算出基础代谢BMR
2. 根据体重差值和目标时限评估任务难度
3. 如果时限紧迫: 收紧热量摄入，最大化蛋白质防肌肉流失
4. 如果时限充裕: 分配平稳可持续的每日热量与营养素
5. 如果时限过于极端（如1周瘦10kg），在coachAdvice中给出专业警告

只返回纯JSON:{{"bmr":数字,"tdee":数字,"target_calories":数字,"protein":数字,"carbs":数字,"fat":数字,"fiber":数字,"coachAdvice":"基于时间跨度的专业指导建议"}}"""
    reply = call_ai(prompt, temp=0.1, max_tokens=300, json_mode=True)
    result = parse_ai_json(reply)
    if result: return jsonify(result)
    # Fallback
    bmr = int(10*w + 6.25*h - 5*age + (5 if g==1 else -161))
    tdee = int(bmr * al)
    adj = -500 if (tw-w)<-5 else (-300 if (tw-w)<-2 else (400 if (tw-w)>5 else 0))
    mode_mult = {"cardio":1.15,"strength":1.10,"happy":1.0,"cheat":1.30}
    target_cal = max(1200, int((tdee + adj) * mode_mult.get(mode, 1.0)))
    ppk = {"cardio":1.4,"strength":2.0,"happy":1.2,"cheat":1.0}.get(mode,1.2)
    protein = int(w * ppk); fat = int(w * 0.9); carbs = max(0, int((target_cal - protein*4 - fat*9)/4))
    return jsonify({"bmr":bmr,"tdee":tdee,"target_calories":target_cal,"protein":protein,"carbs":carbs,"fat":fat,"fiber":30 if g==1 else 25,"coachAdvice":"保持均衡饮食，坚持训练"})

# ── Hydration efficiency lookup ──
HYDRATION_EFFICIENCY = {
    "矿泉水":1.0,"水":1.0,"纯净水":1.0,"白开水":1.0,"温水":1.0,"凉白开":1.0,
    "电解质水":0.95,"运动饮料":0.9,"功能饮料":0.85,
    "黑咖啡":0.75,"咖啡":0.75,"美式":0.75,"拿铁":0.7,"卡布奇诺":0.7,
    "绿茶":0.85,"红茶":0.85,"乌龙茶":0.85,"花茶":0.85,"抹茶":0.8,
    "全脂牛奶":0.85,"脱脂牛奶":0.9,"牛奶":0.88,"豆奶":0.88,"豆浆":0.88,
    "椰子水":0.9,"果汁":0.82,"橙汁":0.82,"苹果汁":0.82,
    "可乐":0.78,"雪碧":0.78,"汽水":0.78,"苏打水":0.95,
    "蛋白粉水":0.85,"蛋白饮":0.85,
}

HYDRATION_CACHE = {}
def get_hydration(drink_type, amount, api_key=None):
    if not drink_type: return amount
    key = drink_type.strip()
    if key in HYDRATION_EFFICIENCY: return int(amount * HYDRATION_EFFICIENCY[key])
    for k, v in HYDRATION_EFFICIENCY.items():
        if k in key or key in k: return int(amount * v)
    # Cache hit
    if key in HYDRATION_CACHE: return int(amount * HYDRATION_CACHE[key])
    # AI fallback
    if api_key:
        try:
            prompt = f"""你是营养学专家。请评估"{key}"这种饮品的水合效率（hydration efficiency）。水合效率是指：喝下该饮品后，实际被身体吸收利用的水分比例。纯水=1.0，咖啡因利尿约0.75，高糖饮料约0.78，牛奶约0.88，运动饮料约0.9。只返回一个0到1之间的小数，不要解释。"""
            reply = call_ai(prompt, temp=0.1, max_tokens=16)
            if reply:
                match = __import__("re").search(r"0?\.\d+", reply)
                if match:
                    eff = float(match.group(0))
                    HYDRATION_CACHE[key] = eff
                    return int(amount * eff)
        except: pass
    return amount

# ── Daily Records History ──
@app.route("/api/user/recent-records", methods=["GET"])
def recent_records():
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=1").fetchone()
    if not u: return jsonify([])
    u = dict(u)
    target_date = u.get("target_date", "")
    end_date = datetime.date.today()
    if target_date:
        try: end_date = min(end_date, datetime.date.fromisoformat(target_date))
        except: pass
    start_date = end_date - datetime.timedelta(days=6)
    records = []
    current = start_date
    while current <= end_date:
        ds = current.isoformat()
        meals = db.execute("SELECT * FROM meals WHERE date=?", [ds]).fetchall()
        workouts = db.execute("SELECT * FROM workouts WHERE date=?", [ds]).fetchall()
        total_in = 0
        for m in meals:
            try:
                for f in json.loads(m["foods"]): total_in += f.get("calories", 0)
            except: pass
        total_burn = sum(w["calories"] or 0 for w in workouts)
        mode = u.get("workout_type", "happy")
        mode_names = {"cardio":"有氧日","strength":"无氧日","happy":"Happy日","cheat":"放纵日"}
        records.append({
            "date": ds,
            "mode": mode_names.get(mode, mode),
            "actualCaloriesIn": total_in,
            "actualCaloriesBurn": total_burn,
            "targetCalories": 2000
        })
        current += datetime.timedelta(days=1)
    records.reverse()
    return jsonify(records)

# ── AI Dish Recommendations ──
@app.route("/api/ai/recommend-dishes", methods=["POST"])
def recommend_dishes():
    data = request.get_json()
    ingredient = data.get("inputIngredient","").strip()
    meal_type = data.get("mealType","午餐")
    remaining = data.get("remainingTargets",{})
    user = data.get("userProfile",{})
    rc = remaining.get("calories",500); rp = remaining.get("protein",30)
    rcarb = remaining.get("carbon",50); rf = remaining.get("fat",20)
    weight = user.get("currentWeight",70); height = user.get("height",170)
    tw = user.get("targetWeight",65); ti = data.get("trainingIntensity","中强度")

    # Detect "empty day" scenario: if remaining calories > 80% of estimated daily target
    estimated_daily = int((10*weight + 6.25*height - 5*25 + 5) * 1.55)
    is_empty_day = rc > estimated_daily * 0.8
    meal_ratios = {"早餐":"25%-30%","午餐":"35%-40%","晚餐":"30%-35%"}
    ratio_info = ""
    if is_empty_day:
        ratio_info = f"""
⚠️ 检测到用户今天前几餐可能漏记（剩余缺口几乎等于全天总量）。
请启动【单餐比例锁】：针对当前餐时【{meal_type}】，严格将推荐总热量控制在用户全天合理总热量（约{estimated_daily}kcal）的{meal_ratios.get(meal_type,'30%')}以内。
严禁把全天热量堆到这一顿饭里！每道菜的热量必须是单餐合理分量（300-700kcal）。"""
    else:
        ratio_info = f"\n用户前面已正常记录饮食，请精准填补剩余缺口。"

    hint = f'用户想吃的食材: {ingredient}。' if ingredient else '请根据当前餐时自由推荐适合该餐的健康食物。'

    prompt = f"""你是AI智能餐单规划师。用户当前选择【{meal_type}】, 身高{height}cm, 体重{weight}kg, 目标{tw}kg, 训练强度{ti}。
今日剩余营养素: {rc}kcal, 蛋白{rp}g, 碳水{rcarb}g, 脂肪{rf}g。{hint}{ratio_info}

请推荐5道适合【{meal_type}】的菜品。返回纯JSON数组:
[{{"name":"菜名(含克数)","mealType":"{meal_type}","calories":数字,"carbon":数字,"protein":数字,"fat":数字,"source":"ai"}}]"""
    reply = call_ai(prompt, temp=0.3, max_tokens=800, json_mode=True)
    print(f"[AI-API-Call] recommend_dishes raw({len(reply) if reply else 0}): {reply[:300] if reply else 'None'}")
    result = parse_ai_json(reply)
    if isinstance(result, list): return jsonify(result)
    if isinstance(result, dict):
        for key in ["dishes","recommendations","items"]:
            if key in result and isinstance(result[key], list): return jsonify(result[key])
    # AI failed — return empty, frontend shows "暂无推荐，点换一批重试"
    print(f"[AI-API-Call] recommend_dishes FAILED to parse, reply was: {reply[:300] if reply else 'None'}")
    return jsonify([])

# ── AI Recipe Generator ──
@app.route("/api/ai/generate-recipe", methods=["POST"])
def generate_recipe():
    data = request.get_json()
    name = data.get("dishName","").strip()
    calories = data.get("calories", 500)
    if not name: return jsonify({"error":"no dish name"}), 400
    prompt = f"""你是精通少油减脂健康的专业大厨。用户选中菜品:{name},总热量锁死在{calories}kcal。
1. 根据热量约束倒推食材精准克数(含调料如橄榄油5g)
2. 严格控油盐糖
3. 输出不超过4步的极简做法

只返回纯JSON:{{"ingredientsList":[{{"name":"食材名","weight":"xxg"}}],"steps":["步骤1","步骤2","步骤3"]}}"""
    reply = call_ai(prompt, temp=0.1, max_tokens=800)
    print(f"[AI-API-Call] generate_recipe raw({len(reply) if reply else 0}): {reply[:200] if reply else 'None'}")
    result = parse_ai_json(reply)
    if result: return jsonify(result)
    print(f"[AI-API-Call] generate_recipe FAILED")
    return jsonify({"ingredientsList":[],"steps":[]})

# ── Dish Nutrition AI ──
@app.route("/api/ai/estimate-diet", methods=["POST"])
def estimate_diet():
    data = request.get_json()
    name = data.get("dishName","").strip()
    grams = data.get("weightGrams",0)
    u = data.get("userProfile",{})
    cw = u.get("currentWeight",70); tw = u.get("targetWeight",65); h = u.get("height",170)
    if not name or grams <= 0: return jsonify({"error":"missing fields"}), 400
    prompt = f"""【Role】你是一位拥有10年临床经验的高级运动营养师。
【Context】用户身高{h}cm,当前体重{cw}kg,目标体重{tw}kg({'减脂期' if tw<cw else '增肌期' if tw>cw else '维持期'})。
【Task】用户吃了一盘中餐:{name},总重量{grams}克。

【计算要求】
1. 根据常识拆解该菜品在{grams}g下的典型食材配比
2. 计算该重量下的总卡路里、碳水、蛋白质、脂肪
3. 如果用户在减脂期，建议是否适合

只返回纯JSON:{{"calories":数字,"carbon":数字,"protein":数字,"fat":数字,"advice":"一句话建议"}}"""
    reply = call_ai(prompt, temp=0.1, max_tokens=256, json_mode=True)
    result = parse_ai_json(reply)
    if result: return jsonify(result)
    return jsonify({"calories":500,"carbon":50,"protein":20,"fat":15,"advice":"注意控制油盐摄入"})

# ── Photo Food Analysis ──
@app.route("/api/analyze-photo", methods=["POST"])
def analyze_photo():
    data = request.get_json()
    image_base64 = data.get("image", "")
    if not image_base64: return jsonify({"error": "no image"}), 400
    prompt = """你是一个资深 AI 营养师。识别图片中的菜品，严格计算该分量下的真实热量和三大营养素。
返回纯JSON，不要markdown标记：
{"name":"精准菜品名称","estimated_grams":450,"calories":715,"protein":29,"carbs":76,"fat":28,"ingredients":["食材1","食材2"],"confidence":"high"}
热量和营养素必须是你根据菜品分量动态计算出的精确值。"""
    reply = call_vision(prompt, image_base64, temp=0.1, max_tokens=256)
    print(f"[photo] raw({len(reply) if reply else 0}): {reply[:200] if reply else 'None'}")
    if reply:
        result = parse_ai_json(reply)
        if result:
            normalized = normalize_photo_result(result)
            print(f"[photo] success: {normalized['name']} {normalized['estimated_grams']}g")
            return jsonify(normalized)
        print(f"[photo] extract failed, using fallback")
    else:
        print(f"[photo] AI call failed, using fallback")
    return jsonify(PHOTO_FALLBACK)

# ── Recalculate nutrition for adjusted grams ──
@app.route("/api/recalc-nutrition", methods=["POST"])
def recalc_nutrition():
    data = request.get_json()
    name = data.get("name","")
    grams = data.get("grams",300)
    prompt = f"""你是资深 AI 营养师。菜品"{name}"，用户指定分量{grams}克。请根据该分量精确计算热量和三大营养素。只返回纯JSON：{{"calories":数字,"protein":数字,"carbs":数字,"fat":数字}}。不要任何其他文字。"""
    reply = call_ai(prompt, temp=0.1, max_tokens=256, json_mode=True)
    result = parse_ai_json(reply)
    if result: return jsonify(result)
    return jsonify({"calories":500,"protein":20,"carbs":50,"fat":15})

# ── Workout Calorie AI ──
@app.route("/api/workout-calories", methods=["POST"])
def workout_calories():
    data = request.get_json()
    weight = float(data.get("weight", 70))
    height = float(data.get("height", 170))
    tp = data.get("type", "strength")
    dur = int(data.get("duration", 0))
    exercises = data.get("exercises", [])
    segments = data.get("segments", [])
    desc = data.get("description", "")

    # Validation
    if tp == "cardio":
        if dur <= 0: return jsonify({"calories": 0, "note": "请输入运动时间"})
    else:
        if not exercises: return jsonify({"calories": 0, "note": "请先添加训练动作"})
        has_valid = any(e.get("name") and e.get("sets", 0) > 0 for e in exercises)
        if not has_valid: return jsonify({"calories": 0, "note": "请填写动作名称和组数"})

    if tp == "cardio":
        seg_desc = ", ".join(f"{s.get('name','有氧')}{s.get('minutes',0)}分钟" for s in segments) if segments else f"有氧{dur}分钟"
        prompt = f"""你是运动科学专家。用户{weight}kg/{height}cm。有氧训练:{seg_desc}。根据运动科学公式精确计算消耗热量(考虑体重、时长、运动强度)。只返回JSON:{{"calories":数字,"note":"说明"}}"""
    else:
        ex_desc = ", ".join(f"{e.get('name','训练')}{e.get('sets',0)}组×{e.get('reps',0)}次×{e.get('weight',0)}kg" for e in exercises)
        total_volume = sum(e.get("sets",0)*e.get("reps",0)*e.get("weight",0) for e in exercises)
        prompt = f"""你是运动科学专家。用户{weight}kg/{height}cm。力量训练:{ex_desc}。总训练量{total_volume}kg。根据运动科学公式精确计算消耗热量(考虑体重、训练量、动作复合度)。只返回JSON:{{"calories":数字,"note":"说明"}}"""

    reply = call_ai(prompt, temp=0.1, max_tokens=256, json_mode=True)
    result = parse_ai_json(reply)
    if result: return jsonify(result)
    # Fallback formula
    if tp == "cardio":
        cal = max(50, int(dur * 7 * weight / 70))
        return jsonify({"calories": cal, "note": f"{dur}分钟有氧 · {cal}kcal"})
    else:
        total_vol = sum(e.get("sets",0)*e.get("reps",0)*e.get("weight",0) for e in exercises)
        cal = max(30, int(total_vol * 0.1 * weight / 70 + len(exercises) * 30))
        return jsonify({"calories": cal, "note": f"{len(exercises)}个动作 · {cal}kcal"})

# ── Water API ──
@app.route("/api/water", methods=["GET","POST"])
def water():
    db = get_db()
    if request.method == "GET":
        date = request.args.get("date", str(datetime.date.today()))
        rows = db.execute("SELECT * FROM water WHERE date=? ORDER BY created_at", [date]).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["effective_ml"] = get_hydration(d.get("drink_type",""), d.get("amount",0), API_KEY)
            result.append(d)
        return jsonify(result)
    data = request.get_json()
    db.execute("INSERT INTO water (date,amount,drink_type) VALUES (?,?,?)",
        [data.get("date",str(datetime.date.today())), data.get("amount",250), data.get("drink_type","water")])
    db.commit()
    return jsonify({"ok":True})

@app.route("/api/water/<int:id>", methods=["DELETE"])
def delete_water(id):
    db = get_db()
    db.execute("DELETE FROM water WHERE id=?", [id])
    db.commit()
    return jsonify({"ok":True})

@app.route("/api/water-target", methods=["POST"])
def water_target():
    data = request.get_json()
    w = data.get("weight", 70)
    af = data.get("activity_level", 1.55)
    base = int(w * 33)
    act_bonus = int((af - 1.2) * 500)
    target = base + act_bonus
    prompt = f"""你是营养顾问。用户{w}kg，活动系数{af}。推荐每日饮水目标(ml)，并列出5种常见饮品每250ml的热量。返回JSON:{{"target_ml":数字,"drinks":[{{"name":"水/咖啡/电解质水/椰子水/牛奶等","calories_per_250ml":数字,"note":"一句话"}}]}}"""
    reply = call_ai(prompt, temp=0.2, max_tokens=512)
    drinks = [{"name":"矿泉水","calories_per_250ml":0,"note":"零卡补水首选"},{"name":"黑咖啡","calories_per_250ml":5,"note":"提神,几乎零卡"},{"name":"电解质水","calories_per_250ml":15,"note":"运动后补充电解质"},{"name":"椰子水","calories_per_250ml":46,"note":"天然电解质"},{"name":"全脂牛奶","calories_per_250ml":155,"note":"补充蛋白质和钙"}]
    ai_target = target
    if reply:
        try:
            m = __import__("re").search(r"\{[\s\S]*\}", reply)
            if m:
                ai = json.loads(m.group(0))
                ai_target = ai.get("target_ml", target)
                if ai.get("drinks"): drinks = ai["drinks"]
        except: pass
    return jsonify({"target_ml": ai_target, "drinks": drinks})

# ── Start ──
if __name__ == "__main__":
    init_db()
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args()
    app.run(host="0.0.0.0", port=args.port, debug=False)
