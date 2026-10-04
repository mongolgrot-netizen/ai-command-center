import os, json, uuid
from datetime import datetime, timezone
from pathlib import Path
import requests
from flask import Flask, request, jsonify, send_from_directory

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
STATE_FILE = DATA / "state.json"
DEFAULT_STATE = {"tasks":[],"agents":[],"projects":[],"memory":[],"events":[],"settings":{"approval_required":True}}

def now(): return datetime.now(timezone.utc).isoformat()
def load_state():
    if not STATE_FILE.exists(): save_state(DEFAULT_STATE)
    try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception: return json.loads(json.dumps(DEFAULT_STATE))
def save_state(s): STATE_FILE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")
def add_event(s,k,m):
    s["events"].insert(0,{"id":uuid.uuid4().hex[:10],"kind":k,"message":m,"created_at":now()}); s["events"]=s["events"][:200]

def heuristic_plan(text):
    t=text.lower()
    if any(x in t for x in ["создай","разработ","приложен","сайт","программа","код"]): return [("architect","Спроектировать решение"),("developer","Разработать реализацию"),("tester","Проверить и протестировать")]
    if any(x in t for x in ["исслед","найди","анализ","конкурент","рынок","osint"]): return [("researcher","Исследовать открытые источники"),("analyst","Проанализировать результаты"),("reviewer","Проверить выводы")]
    if any(x in t for x in ["смет","цена","стоимость","расчет"]): return [("estimator","Разобрать исходные данные"),("analyst","Проверить расчёт"),("reviewer","Провести контроль")]
    if any(x in t for x in ["юрист","договор","суд","полици","претензи"]): return [("legal","Проанализировать юридическую задачу"),("researcher","Проверить нормативную базу"),("reviewer","Проверить результат")]
    if any(x in t for x in ["авито","реклам","маркет","продвиж"]): return [("marketing","Разработать стратегию"),("analyst","Оценить варианты"),("reviewer","Проверить план")]
    return [("analyst","Разобрать задачу"),("architect","Сформировать план"),("reviewer","Проверить результат")]

def call_groq(prompt, system="Ты специализированный агент внутри AI Command Center. Не выдумывай выполненные действия."):
    key=os.getenv("GROQ_API_KEY")
    if not key: return None
    try:
        r=requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
            json={"model":os.getenv("GROQ_MODEL","openai/gpt-oss-120b"),"temperature":0.2,
                  "messages":[{"role":"system","content":system},{"role":"user","content":prompt}]},timeout=60)
        r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
    except Exception as e: return {"error":str(e)}

def plan_task(text):
    key=os.getenv("GROQ_API_KEY")
    if key:
        try:
            system='''Ты — главный управляющий AI Command Center. Преврати запрос пользователя в безопасный план.
Верни JSON с полями summary, agents (массив объектов role,name,instructions), steps, risks, needs_approval. Не утверждай выполнение внешних действий без инструмента.'''
            r=requests.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                json={"model":os.getenv("GROQ_MODEL","openai/gpt-oss-120b"),"temperature":0.2,"response_format":{"type":"json_object"},
                      "messages":[{"role":"system","content":system},{"role":"user","content":text}]},timeout=60)
            r.raise_for_status(); return json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            return {"summary":"Ошибка AI API: "+str(e),"agents":[],"steps":[],"risks":["AI API не ответил. Проверь GROQ_API_KEY, GROQ_MODEL и логи Render."],"needs_approval":True,"ai_error":True}
    steps=heuristic_plan(text)
    return {"summary":"План создан локальным оркестратором без AI API.","agents":[{"role":r,"name":r.title(),"instructions":d} for r,d in steps],
            "steps":[d for _,d in steps],"risks":["Внешние действия выполняются только после подключения соответствующего инструмента."],"needs_approval":True}

def create_task_internal(text):
    s=load_state(); plan=plan_task(text)
    task={"id":"TASK-"+uuid.uuid4().hex[:10].upper(),"title":text[:120],"description":text,"status":"planned","plan":plan,"outputs":[],"created_at":now(),"updated_at":now()}
    s["tasks"].insert(0,task)
    for a in plan.get("agents",[]):
        s["agents"].insert(0,{"id":"AGENT-"+uuid.uuid4().hex[:10].upper(),"name":a.get("name","Agent"),"role":a.get("role","specialist"),
                              "instructions":a.get("instructions",""),"task_id":task["id"],"status":"assigned","created_at":now()})
    add_event(s,"task",f"Создана задача {task['id']} и сформирована AI-команда"); save_state(s); return task

app=Flask(__name__)
@app.route("/")
def index(): return send_from_directory(BASE,"index.html")
@app.route("/<path:path>")
def static_files(path): return send_from_directory(BASE,path)
@app.get("/api/health")
def health(): return jsonify({"ok":True,"service":"AI Command Center","time":now()})
@app.get("/api/state")
def state(): return jsonify(load_state())
@app.post("/api/task")
def create_task():
    text=(request.get_json(silent=True) or {}).get("text","").strip()
    if not text: return jsonify({"error":"Введите задачу"}),400
    return jsonify(create_task_internal(text))
@app.post("/api/task/<task_id>/status")
def task_status(task_id):
    status=(request.get_json(silent=True) or {}).get("status")
    if status not in {"planned","running","paused","completed","failed","cancelled"}: return jsonify({"error":"Недопустимый статус"}),400
    s=load_state()
    for t in s["tasks"]:
        if t["id"]==task_id:
            t["status"]=status;t["updated_at"]=now();add_event(s,"status",f"{task_id}: {status}");save_state(s);return jsonify(t)
    return jsonify({"error":"Задача не найдена"}),404
@app.post("/api/task/<task_id>/run")
def run_task(task_id):
    s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
    if not task:return jsonify({"error":"Задача не найдена"}),404
    if s["settings"].get("approval_required",True):return jsonify({"error":"Требуется подтверждение запуска","task":task}),409
    task["status"]="running"; task["outputs"]=[]
    for a in task["plan"].get("agents",[]):
        result=call_groq(f"Задача: {task['description']}\nРоль: {a.get('role')}\nИнструкция: {a.get('instructions')}\nДай конкретный результат в рамках роли.")
        task["outputs"].append({"agent":a,"result":result or "AI API не подключён; доступно только планирование.","created_at":now()})
    task["status"]="completed";task["updated_at"]=now();add_event(s,"task",f"{task_id}: команда завершила доступные этапы");save_state(s);return jsonify(task)
@app.post("/api/memory")
def memory():
    content=(request.get_json(silent=True) or {}).get("content","").strip()
    if not content:return jsonify({"error":"Пустая память"}),400
    s=load_state();item={"id":"MEM-"+uuid.uuid4().hex[:10].upper(),"content":content,"created_at":now()};s["memory"].insert(0,item);s["memory"]=s["memory"][:500];save_state(s);return jsonify(item)
@app.post("/api/agent")
def agent():
    d=request.get_json(silent=True) or {};name=d.get("name","").strip();role=d.get("role","").strip()
    if not name or not role:return jsonify({"error":"Нужны name и role"}),400
    s=load_state();a={"id":"AGENT-"+uuid.uuid4().hex[:10].upper(),"name":name,"role":role,"instructions":d.get("instructions","").strip(),"status":"active","created_at":now()};s["agents"].insert(0,a);add_event(s,"agent",f"Создан агент {name}");save_state(s);return jsonify(a)
@app.post("/api/telegram/webhook")
def telegram_webhook():
    secret=os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token")!=secret:return jsonify({"ok":False}),403
    u=request.get_json(silent=True) or {};m=u.get("message") or {};text=m.get("text","").strip();chat_id=(m.get("chat") or {}).get("id")
    if not text or not chat_id:return jsonify({"ok":True})
    if text=="/start":answer="🧠 AI Command Center\n\nПришлите задачу обычным сообщением."
    else:
        t=create_task_internal(text);answer=f"🧠 {t['id']} создана.\n\n{t['plan']['summary']}\n\n"+"\n".join("• "+x for x in t["plan"]["steps"])
    token=os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        try: requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat_id,"text":answer},timeout=15)
        except Exception: pass
    return jsonify({"ok":True})
@app.errorhandler(Exception)
def error(e): return jsonify({"error":"Внутренняя ошибка сервера","detail":str(e)}),500
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")))
