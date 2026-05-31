"""
动食日记 - 极简健身饮食记录
Flask + SQLite + Gemini API
"""
import json, os, sqlite3, datetime
import requests
from flask import Flask, request, jsonify, send_from_directory, g

app = Flask(__name__, static_folder="static", static_url_path="")
API_KEY = os.environ.get("AI_API_KEY", "")
DB_PATH = os.path.join(os.path.dirname(__file__), "dongshi.db")

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
        INSERT OR IGNORE INTO users (id) VALUES (1);
    """)
    db.commit()
    db.close()

# ── AI API (DeepSeek, OpenAI-compatible) ──
def call_ai(prompt, temp=0.1, max_tokens=1024):
    if not API_KEY: return None
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model":"deepseek-chat","messages":[{"role":"user","content":prompt}],
                  "temperature":temp,"max_tokens":max_tokens},
            timeout=20
        )
        return r.json()["choices"][0]["message"]["content"]
    except: return None

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

# ── Start ──
if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=8080)
