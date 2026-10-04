const $=id=>document.getElementById(id);
async function api(url,opt={}){const r=await fetch(url,{headers:{"Content-Type":"application/json"},...opt});const d=await r.json();if(!r.ok)throw new Error(d.error||"Ошибка");return d}
function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]))}
function render(s){
$("taskCount").textContent=s.tasks.length;$("agentCount").textContent=s.agents.length;$("memoryCount").textContent=s.memory.length;
$("tasks").innerHTML=s.tasks.slice(0,8).map(t=>`<div class="item"><b>${esc(t.title)}</b><span class="status">${esc(t.status)}</span><div class="muted">${esc(t.id)}</div></div>`).join("")||'<div class="muted">Пока нет задач</div>';
$("agents").innerHTML=s.agents.slice(0,10).map(a=>`<div class="item"><b>${esc(a.name)}</b><span class="tag">${esc(a.role)}</span><div class="muted">${esc(a.status)}</div></div>`).join("")||'<div class="muted">Агенты будут создаваться по задачам</div>';
$("memory").innerHTML=s.memory.slice(0,8).map(m=>`<div class="item">${esc(m.content)}</div>`).join("")||'<div class="muted">Память пуста</div>';
$("events").innerHTML=s.events.slice(0,10).map(e=>`<div class="item"><b>${esc(e.kind)}</b> — ${esc(e.message)}<div class="muted">${new Date(e.created_at).toLocaleString()}</div></div>`).join("")||'<div class="muted">Событий нет</div>';
}
async function refresh(){try{const [s,h]=await Promise.all([api("/api/state"),api("/api/health")]);render(s);$("health").textContent="● онлайн";}catch(e){$("health").textContent="● ошибка"}}
$("runBtn").onclick=async()=>{const text=$("taskInput").value.trim();if(!text)return alert("Введите задачу");$("runBtn").disabled=true;$("result").innerHTML='<div class="plan">🧠 Анализирую задачу...</div>';try{const t=await api("/api/task",{method:"POST",body:JSON.stringify({text})});const p=t.plan;$("result").innerHTML=`<div class="plan"><b>🧠 ${esc(p.summary)}</b><h3>Команда</h3>${p.agents.map(a=>`<span class="tag">${esc(a.name)} · ${esc(a.role)}</span>`).join("")}<h3>План</h3><ol>${p.steps.map(x=>`<li>${esc(x)}</li>`).join("")}</ol><div class="muted">Требует подтверждения: ${p.needs_approval?"да":"нет"}</div></div>`;refresh()}catch(e){$("result").innerHTML=`<div class="plan">❌ ${esc(e.message)}</div>`}finally{$("runBtn").disabled=false}};
$("clearBtn").onclick=()=>{$("taskInput").value="";$("result").innerHTML=""};
$("memoryBtn").onclick=async()=>{const content=$("memoryInput").value.trim();if(!content)return;try{await api("/api/memory",{method:"POST",body:JSON.stringify({content})});$("memoryInput").value="";refresh()}catch(e){alert(e.message)}};
refresh();setInterval(refresh,15000);
