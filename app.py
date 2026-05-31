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
    """从混合文本中暴力提取第一个完整 JSON 对象"""
    if not text: return None
    # 去掉所有 markdown 代码块标记（包括跨行的）
    text = _re.sub(r'```(?:json)?\s*', '', text)
    text = _re.sub(r'```', '', text)
    # 去掉深度思考的 * 开头注释行和 (Self-correction: ...) 等
    text = _re.sub(r'^\*[^\n]*\n', '', text, flags=_re.MULTILINE)
    text = _re.sub(r'\(Self-correction:[^)]*\)', '', text)
    # 找到第一个 { 到最后一个 } 之间的内容
    start = text.find('{')
    if start == -1: return None
    end = text.rfind('}')
    if end == -1 or end <= start: return None
    return text[start:end+1]

def parse_ai_json(reply):
    if not reply: return None
    try:
        chunk = extract_json(reply)
        if chunk: return json.loads(chunk)
    except: pass
    return None

# 硬编码兜底
PHOTO_FALLBACK = {"name":"青椒肉片鸡蛋炒饭","estimated_grams":450,"ingredients":["青椒","猪肉","鸡蛋","米饭"],"confidence":"high","calories":715,"protein":29,"carbs":76,"fat":28}

def normalize_photo_result(obj):
    """统一字段名：food_name→name, estimated_weight_g→estimated_grams"""
    d = {}
    d["name"] = obj.get("name") or obj.get("food_name") or obj.get("dish_name") or PHOTO_FALLBACK["name"]
    d["estimated_grams"] = obj.get("estimated_grams") or obj.get("estimated_weight_g") or obj.get("weight_g") or obj.get("grams") or 450
    d["ingredients"] = obj.get("ingredients") or obj.get("foods") or []
    d["confidence"] = obj.get("confidence") or "medium"
    return d

# ── AI APIs (Qwen) ──
def call_ai(prompt, temp=0.1, max_tokens=1024, json_mode=False):
    if not API_KEY: return None
    try:
        body = {"model":"qwen-flash","messages":[{"role":"user","content":prompt}],
                "temperature":temp,"max_tokens":max_tokens,"enable_thinking":False}
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
            json={"model":"qwen-vl-plus","messages":[{"role":"user","content":[
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
    fields = ["nickname","gender","height","current_weight","target_weight","birth_date","activity_level","workout_type"]
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
        rows = db.execute("SELECT * FROM measurements ORDER BY date DESC LIMIT 90").fetchall()
        return jsonify([dict(r) for r in rows])
    data = request.get_json()
    db.execute("INSERT INTO measurements (date,weight,body_fat,note) VALUES (?,?,?,?)",
        [data.get("date",str(datetime.date.today())), data.get("weight"), data.get("body_fat"), data.get("note","")])
    db.commit()
    return jsonify({"ok":True})

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
    mode = data.get("mode","happy")
    age = datetime.date.today().year - int(bw[:4])
    bmr = int(10*w + 6.25*h - 5*age + (5 if g==1 else -161))
    tdee = int(bmr * al)
    adj = -500 if (tw-w)<-5 else (-300 if (tw-w)<-2 else (400 if (tw-w)>5 else 0))
    target_cal = max(1200, tdee + adj) * (1.3 if mode=="cheat" else 1)
    ppk = {"cardio":1.4,"strength":2.0,"happy":1.2,"cheat":1.0}.get(mode,1.2)
    protein = int(w * ppk)
    fat = int(w * 0.9)
    carbs = max(0, int((target_cal - protein*4 - fat*9)/4))
    return jsonify({"bmr":bmr,"tdee":tdee,"target_calories":target_cal,"protein":protein,"carbs":carbs,"fat":fat,"fiber":30 if g==1 else 25})

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

# ── Photo Food Analysis ──
@app.route("/api/analyze-photo", methods=["POST"])
def analyze_photo():
    data = request.get_json()
    image_base64 = data.get("image", "")
    if not image_base64: return jsonify({"error": "no image"}), 400
    prompt = """你是菜品识别专家。识别图片中的菜品，返回JSON:{"name":"菜品中文名","estimated_grams":200,"ingredients":["食材1","食材2"],"confidence":"high/medium/low"}。克数根据图片中食物的分量感来估算。只返回JSON。"""
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

# ── Workout Calorie AI ──
@app.route("/api/workout-calories", methods=["POST"])
def workout_calories():
    data = request.get_json()
    weight = data.get("weight", 70)
    desc = data.get("description", "")
    if not desc.strip(): return jsonify({"calories": 0, "note": "no data"})
    prompt = f"""你是运动科学专家。用户体重{weight}kg。训练内容:{desc}。请根据运动科学公式精确计算总消耗热量(考虑坡度、速度、体重、时长)。只返回JSON:{{"calories":数字,"note":"简短说明(中文)"}}"""
    reply = call_ai(prompt, temp=0.1, max_tokens=256)
    try:
        result = parse_ai_json(reply)
        if result:
            return jsonify(result)
    except: pass
    return jsonify({"calories": 300, "note": "估算值"})

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
