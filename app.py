import os, json, uuid, re
from datetime import datetime, timezone
from pathlib import Path
import requests
from flask import Flask, request, jsonify, send_from_directory

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
STATE_FILE = DATA / "state.json"

DEFAULT_STATE = {
    "tasks": [], "agents": [], "projects": [], "memory": [],
    "events": [], "settings": {"approval_required": True}
}

def now():
    return datetime.now(timezone.utc).isoformat()

def load_state():
    if not STATE_FILE.exists():
        save_state(DEFAULT_STATE)
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_STATE.copy()

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def add_event(state, kind, message):
    state["events"].insert(0, {"id": uuid.uuid4().hex[:10], "kind": kind, "message": message, "created_at": now()})
    state["events"] = state["events"][:200]

def heuristic_plan(text):
    t = text.lower()
    steps = []
    if any(x in t for x in ["создай", "разработ", "приложен", "сайт", "программа", "код"]):
        steps += [("architect", "Спроектировать решение"), ("developer", "Разработать реализацию"), ("tester", "Проверить и протестировать")]
    elif any(x in t for x in ["исслед", "найди", "анализ", "конкурент", "рынок", "osint"]):
        steps += [("researcher", "Исследовать открытые источники"), ("analyst", "Проанализировать результаты"), ("reviewer", "Проверить выводы")]
    elif any(x in t for x in ["смет", "цена", "стоимость", "расчет"]):
        steps += [("estimator", "Разобрать исходные данные"), ("analyst", "Проверить расчёт"), ("reviewer", "Провести контроль")]
    elif any(x in t for x in ["юрист", "договор", "суд", "полици", "претензи"]):
        steps += [("legal", "Проанализировать юридическую задачу"), ("researcher", "Проверить нормативную базу"), ("reviewer", "Проверить результат")]
    elif any(x in t for x in ["авито", "реклам", "маркет", "продвиж"]):
        steps += [("marketing", "Разработать стратегию"), ("analyst", "Оценить варианты"), ("reviewer", "Проверить план")]
    else:
        steps += [("analyst", "Разобрать задачу"), ("architect", "Сформировать план"), ("reviewer", "Проверить результат")]
    return steps

def call_groq(prompt):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    system = """Ты — главный управляющий AI Command Center. Твоя задача — превращать запрос пользователя в безопасный исполнимый план. Не утверждай, что выполнил действия, если инструмент не был вызван. Возвращай только JSON с полями: summary (string), agents (array объектов {role,name,instructions}), steps (array строк), risks (array строк), needs_approval (boolean). Не придумывай доступ к сервисам."""
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
                  "messages":[{"role":"system","content":system},{"role":"user","content":prompt}]},
            timeout=60
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}

def plan_task(text):
    ai = call_groq(text)
    if ai and "error" not in ai:
        return ai
    steps = heuristic_plan(text)
    roles = []
    for role, desc in steps:
        roles.append({"role": role, "name": role.title(), "instructions": desc})
    return {
        "summary": "План создан локальным оркестратором без внешнего AI API.",
        "agents": roles,
        "steps": [x[1] for x in steps],
        "risks": ["Для реального выполнения внешних действий потребуется подключить соответствующий инструмент и подтвердить доступ."],
        "needs_approval": True
    }

@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(BASE, path)

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "AI Command Center", "time": now()})

@app.get("/api/state")
def api_state():
    return jsonify(load_state())

@app.post("/api/task")
def create_task():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Введите задачу"}), 400
    state = load_state()
    plan = plan_task(text)
    task = {
        "id": "TASK-" + uuid.uuid4().hex[:10].upper(),
        "title": text[:120],
        "description": text,
        "status": "planned",
        "plan": plan,
        "created_at": now(),
        "updated_at": now()
    }
    state["tasks"].insert(0, task)
    add_event(state, "task", f"Создана задача {task['id']}")
    save_state(state)
    return jsonify(task)

@app.post("/api/task/<task_id>/status")
def task_status(task_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    allowed = {"planned","running","paused","completed","failed","cancelled"}
    if status not in allowed:
        return jsonify({"error": "Недопустимый статус"}), 400
    state = load_state()
    for task in state["tasks"]:
        if task["id"] == task_id:
            task["status"] = status
            task["updated_at"] = now()
            add_event(state, "status", f"{task_id}: {status}")
            save_state(state)
            return jsonify(task)
    return jsonify({"error": "Задача не найдена"}), 404

@app.post("/api/agent")
def create_agent():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    role = (data.get("role") or "").strip()
    instructions = (data.get("instructions") or "").strip()
    if not name or not role:
        return jsonify({"error": "Нужны name и role"}), 400
    state = load_state()
    agent = {"id":"AGENT-"+uuid.uuid4().hex[:10].upper(),"name":name,"role":role,
             "instructions":instructions,"status":"active","created_at":now()}
    state["agents"].insert(0, agent)
    add_event(state, "agent", f"Создан агент {name}")
    save_state(state)
    return jsonify(agent)

@app.post("/api/memory")
def add_memory():
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error":"Пустая память"}), 400
    state = load_state()
    item = {"id":"MEM-"+uuid.uuid4().hex[:10].upper(),"content":content,"created_at":now()}
    state["memory"].insert(0,item)
    state["memory"] = state["memory"][:500]
    save_state(state)
    return jsonify(item)

@app.post("/api/telegram/webhook")
def telegram_webhook():
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return jsonify({"ok":False}), 403
    update = request.get_json(silent=True) or {}
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = (msg.get("chat") or {}).get("id")
    if not text or not chat_id:
        return jsonify({"ok":True})
    if text == "/start":
        answer = "🧠 AI Command Center\n\nПришлите задачу обычным сообщением. Я сформирую план и команду агентов."
    else:
        task = create_task_internal(text)
        answer = f"🧠 Задача {task['id']} создана.\n\n{task['plan']['summary']}\n\n" + "\n".join("• "+x for x in task["plan"]["steps"])
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id":chat_id,"text":answer}, timeout=15)
        except Exception:
            pass
    return jsonify({"ok":True})

def create_task_internal(text):
    state = load_state()
    plan = plan_task(text)
    task = {"id":"TASK-"+uuid.uuid4().hex[:10].upper(),"title":text[:120],"description":text,
            "status":"planned","plan":plan,"created_at":now(),"updated_at":now()}
    state["tasks"].insert(0,task)
    add_event(state,"task",f"Создана задача {task['id']} через Telegram")
    save_state(state)
    return task

@app.errorhandler(Exception)
def handle_error(e):
    return jsonify({"error":"Внутренняя ошибка сервера","detail":str(e)}),500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")))
