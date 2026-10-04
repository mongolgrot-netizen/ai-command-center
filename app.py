import os, json, uuid, time, re, threading
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

def call_groq(prompt, system="Ты специализированный агент внутри AI Command Center. Не выдумывай выполненные действия.", max_tokens=1200, retries=3):
    key=os.getenv("GROQ_API_KEY")
    if not key: return None
    for attempt in range(retries):
        try:
            r=requests.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                json={"model":os.getenv("GROQ_MODEL","openai/gpt-oss-120b"),"temperature":0.2,
                      "max_tokens":max_tokens,
                      "messages":[{"role":"system","content":system},{"role":"user","content":prompt}]},timeout=60)
            r.raise_for_status()
            data=r.json()
            return data["choices"][0]["message"]["content"]
        except requests.HTTPError as e:
            body=""
            try: body=e.response.text[:1200]
            except Exception: pass
            status=e.response.status_code if e.response is not None else None
            if status==429 and attempt < retries-1:
                m=re.search(r"try again in ([0-9.]+)s", body, re.I)
                wait=float(m.group(1)) if m else 5.0
                time.sleep(min(max(wait+0.5,1.0),20.0))
                continue
            return {"error":f"Groq HTTP {status or '?'}: {body or str(e)}"}
        except Exception as e:
            if attempt < retries-1:
                time.sleep(2)
                continue
            return {"error":f"{type(e).__name__}: {str(e)}"}
    return {"error":"Groq: превышено число попыток"}


GITHUB_API="https://api.github.com"

def github_headers():
    token=os.getenv("GITHUB_TOKEN","").strip()
    return {"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","Content-Type":"application/json"}

def github_configured():
    return bool(os.getenv("GITHUB_TOKEN","").strip() and os.getenv("GITHUB_REPO","").strip())

def github_api(method,path,payload=None):
    if not github_configured(): return {"error":"GitHub не подключён. Нужны GITHUB_TOKEN и GITHUB_REPO в Render."}
    try:
        r=requests.request(method,GITHUB_API+path,headers=github_headers(),json=payload,timeout=30)
        data=r.json() if r.text else {}
        if not r.ok: return {"error":f"GitHub HTTP {r.status_code}: {data.get('message',r.text[:500])}"}
        return data
    except Exception as e: return {"error":f"GitHub: {type(e).__name__}: {e}"}

def github_get_file(path,ref=None):
    repo=os.getenv("GITHUB_REPO","").strip()
    q=f"?ref={requests.utils.quote(ref,safe='')}" if ref else ""
    return github_api("GET",f"/repos/{repo}/contents/{path.lstrip('/')}"+q)

def github_write_file(path,content,message,sha=None,branch=None):
    repo=os.getenv("GITHUB_REPO","").strip()
    import base64
    payload={"message":message,"content":base64.b64encode(content.encode("utf-8")).decode("ascii")}
    if sha: payload["sha"]=sha
    if branch: payload["branch"]=branch
    return github_api("PUT",f"/repos/{repo}/contents/{path.lstrip('/')}",payload)

def github_execute_actions(actions,task_id):
    if os.getenv("GITHUB_WRITE_ENABLED","").lower() not in ("1","true","yes"):
        return {"executed":0,"skipped":len(actions),"reason":"GITHUB_WRITE_ENABLED не включён"}
    results=[]
    for action in actions[:10]:
        if action.get("action") not in ("write_file","create_file","update_file"):
            results.append({"action":action.get("action"),"ok":False,"error":"Недопустимое действие"}); continue
        path=str(action.get("path","")).strip().lstrip("/")
        file_content=action.get("content")
        if not path or not isinstance(file_content,str):
            results.append({"path":path,"ok":False,"error":"Нужны path и content"}); continue
        if ".." in Path(path).parts or path.startswith(".git/"):
            results.append({"path":path,"ok":False,"error":"Недопустимый путь"}); continue
        existing=github_get_file(path)
        if existing.get("error") and "HTTP 404" not in existing.get("error",""):
            results.append({"path":path,"ok":False,"error":existing["error"]}); continue
        sha=existing.get("sha")
        out=github_write_file(path,file_content,f"AI Command Center: {task_id} — {action.get('action')}",sha=sha)
        if out.get("error"): results.append({"path":path,"ok":False,"error":out["error"]})
        else: results.append({"path":path,"ok":True,"commit":out.get("commit",{}).get("sha")})
    return {"executed":sum(1 for x in results if x.get("ok")),"results":results}

def github_project_context():
    if not github_configured():
        return "GitHub-контекст недоступен."
    parts=[]
    for path in ("index.html","style.css","app.js","requirements.txt","README.md"):
        data=github_get_file(path)
        if data.get("content"):
            import base64
            try:
                raw=base64.b64decode(data["content"]).decode("utf-8","replace")
            except Exception:
                raw=str(data.get("content",""))
            parts.append(f"--- {path} ---\n{raw[:700]}")
    return "\n".join(parts)[:3500] or "Файлы проекта не прочитаны."

def extract_github_actions(text):
    try:
        m=re.search(r"\`\`\`json\s*(\{.*?\})\s*\`\`\`",text,re.S)
        raw=m.group(1) if m else text[text.find("{"):text.rfind("}")+1]
        if not raw: return []
        raw=re.sub(r"\\(?=[<>=/])","",raw)
        obj=json.loads(raw)
        return obj.get("actions",[]) if isinstance(obj,dict) and isinstance(obj.get("actions",[]),list) else []
    except Exception:
        return []
def plan_task(text):
    key=os.getenv("GROQ_API_KEY")
    if key:
        try:
            system='''Ты — главный управляющий AI Command Center. Преврати запрос пользователя в безопасный исполнимый план.
Верни JSON с полями summary, agents (массив объектов role,name,instructions), steps, risks, needs_approval.
Если задача связана с разработкой, кодом, сайтом или приложением, обязательно сформируй команду в порядке: architect → developer (или backend_developer/frontend_developer) → tester → debugger → reviewer.
Debugger должен исправлять проблемы, найденные tester, а reviewer — делать финальную проверку.
Для остальных задач подбирай подходящую специализированную команду.
Не утверждай выполнение внешних действий без инструмента.'''
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
    task={"id":"TASK-"+uuid.uuid4().hex[:10].upper(),"title":text[:120],"description":text,"status":"planned","plan":plan,"outputs":[],"approved":False,"created_at":now(),"updated_at":now()}
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
def state():
    s=load_state()
    # Самовосстановление: если все агенты задачи завершены, задача не может оставаться running.
    changed=False
    for task in s["tasks"]:
        if task.get("status")=="running":
            task_agents=[a for a in s["agents"] if a.get("task_id")==task.get("id")]
            if task_agents and all(a.get("status")=="completed" for a in task_agents):
                task["status"]="completed"
                task["updated_at"]=now()
                add_event(s,"status",f'{task["id"]}: статус автоматически синхронизирован → completed')
                changed=True
    if changed: save_state(s)
    return jsonify(s)
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
@app.post("/api/task/<task_id>/approve")
def approve_task(task_id):
    s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
    if not task:return jsonify({"error":"Задача не найдена"}),404
    task["approved"]=True; task["status"]="approved"; task["updated_at"]=now()
    add_event(s,"approval",f"{task_id}: запуск подтверждён пользователем");save_state(s)
    return jsonify(task)
def execute_task(task_id):
    max_rounds=3
    previous=""
    for round_no in range(1,max_rounds+1):
        s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
        if not task: return
        agents=task["plan"].get("agents",[])
        # В первом раунде выполняем полную команду. В следующих — только исправление,
        # повторная проверка и финальный reviewer.
        if round_no==1:
            run_agents=agents
        else:
            run_agents=[a for a in agents if a.get("role") in ("debugger","tester","reviewer")]
        for idx,a in enumerate(run_agents,1):
            role=a.get("role","specialist")
            prompt=f"""Ты агент AI Command Center. Раунд {round_no}.
Исходная задача: {task["description"]}
Твоя роль: {role}
Твоя инструкция: {a.get("instructions","")}
Предыдущие результаты команды:
{previous[-10000:]}
Контекст текущего GitHub-проекта:
{github_project_context()}
Работай по задаче. Нельзя утверждать, что файл изменён, commit сделан или код запущен, если это не подтверждено инструментом.
КРИТИЧЕСКИ ВАЖНО для developer/coder/backend_developer/frontend_developer/debugger:
если требуется изменить проект, ты ОБЯЗАН предложить полный JSON-блок в конце:
{{"actions":[{{"action":"write_file","path":"...","content":"полное содержимое файла"}}]}}
Используй существующий проект как основу и создавай только необходимые файлы.
Tester должен проверять состояние GitHub после предыдущих изменений и честно дать PASS/FAIL.
Reviewer обязан дать строку VERDICT: PASS или VERDICT: FAIL.
Если FAIL — перечисли конкретные исправления для Debugger.
"""
            result=call_groq(prompt, system=f"Ты {role}. Ты обязан дать практический результат, а не общий совет.", max_tokens=(2600 if role in ("developer","coder","backend_developer","frontend_developer","debugger") else 1200))
            if isinstance(result,dict) and result.get("error"):
                s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
                if task:
                    err=result["error"]; task["status"]="failed"; task["updated_at"]=now()
                    task["outputs"].append({"agent":a,"result":err,"error":True,"created_at":now()})
                    add_event(s,"error",f"{task_id}: ошибка агента {a.get('name',role)} — {err[:500]}"); save_state(s)
                return
            out=result or "AI API не подключён."
            if role in ("developer","coder","backend_developer","frontend_developer","debugger") and isinstance(out,str):
                actions=extract_github_actions(out)
                if actions:
                    gh=github_execute_actions(actions,task_id)
                    out += "\n\n[GITHUB EXECUTION]\n" + json.dumps(gh,ensure_ascii=False)
                    s=load_state(); add_event(s,"github",f"{task_id}: GitHub действий выполнено {gh.get('executed',0)}"); save_state(s)
                else:
                    out += "\n\n[GITHUB EXECUTION]\n" + json.dumps({"executed":0,"error":"Агент не предоставил actions для изменения проекта"},ensure_ascii=False)
            s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
            if not task: return
            task["outputs"].append({"agent":a,"result":out,"round":round_no,"created_at":now()})
            previous += f"\n\n[round {round_no} {role}]\n{out}"
            agent_rec=next((x for x in s["agents"] if x.get("task_id")==task_id and x.get("role")==role),None)
            if agent_rec: agent_rec["status"]="completed"
            save_state(s)
        # Определяем итог reviewer. PASS завершает задачу; FAIL запускает новый repair round.
        reviewer_outputs=[o for o in task.get("outputs",[]) if o.get("agent",{}).get("role")=="reviewer"]
        verdict=""
        if reviewer_outputs:
            verdict=(reviewer_outputs[-1].get("result") or "").upper()
        if "VERDICT: PASS" in verdict or ("PASS" in verdict and "FAIL" not in verdict[-200:]):
            s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
            if task:
                task["status"]="completed"; task["updated_at"]=now()
                add_event(s,"task",f"{task_id}: Reviewer подтвердил PASS, задача завершена"); save_state(s)
            return
        if round_no<max_rounds:
            s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
            if task:
                task["status"]="running"; task["updated_at"]=now()
                add_event(s,"loop",f"{task_id}: Reviewer дал FAIL — запускается раунд исправления {round_no+1}"); save_state(s)
                continue
        s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
        if task:
            task["status"]="failed"; task["updated_at"]=now()
            add_event(s,"task",f"{task_id}: Reviewer не подтвердил PASS после {max_rounds} раундов"); save_state(s)
        return

@app.post("/api/task/<task_id>/run")
def run_task(task_id):
    s=load_state(); task=next((x for x in s["tasks"] if x["id"]==task_id),None)
    if not task:return jsonify({"error":"Задача не найдена"}),404
    if s["settings"].get("approval_required",True) and not task.get("approved",False):
        return jsonify({"error":"Требуется подтверждение запуска","task":task}),409
    task["status"]="running"; task["outputs"]=[]; task["updated_at"]=now()
    add_event(s,"status",f"{task_id}: выполнение запущено"); save_state(s)
    threading.Thread(target=execute_task,args=(task_id,),daemon=True).start()
    return jsonify(task),202

@app.get("/api/github/status")
def github_status():
    configured=github_configured()
    if not configured:
        return jsonify({"connected":False,"write_enabled":False,"repo":os.getenv("GITHUB_REPO","")})
    repo=os.getenv("GITHUB_REPO","").strip()
    info=github_api("GET",f"/repos/{repo}")
    return jsonify({"connected":"error" not in info,"write_enabled":os.getenv("GITHUB_WRITE_ENABLED","").lower() in ("1","true","yes"),"repo":repo,"name":info.get("full_name"),"private":info.get("private"),"error":info.get("error")})

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