const $=id=>document.getElementById(id);
let selectedTaskId=null;
async function api(url,opt={}){const r=await fetch(url,{headers:{"Content-Type":"application/json",...(opt.headers||{})},...opt});const d=await r.json().catch(()=>({error:"Сервер вернул не JSON"}));if(!r.ok)throw new Error(d.error||"Ошибка");return d}
function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]))}
function render(s){
$("taskCount").textContent=s.tasks.length;const activeAgents=s.agents.filter(a=>a.status!=="archived");$("agentCount").textContent=activeAgents.length;$("memoryCount").textContent=s.memory.length;$("projectCount").textContent=(s.projects||[]).length;
$("tasks").innerHTML=s.tasks.slice(0,8).map(t=>`<div class="item"><b>${esc(t.title)}</b><span class="status">${esc(t.status)}</span><div class="muted">${esc(t.id)}</div>${t.status==="planned"?`<button class="approveBtn" data-id="${esc(t.id)}">▶ Подтвердить и запустить</button>`:t.status==="approved"?`<button class="approveBtn" data-id="${esc(t.id)}">▶ Запустить</button>`:(t.status==="failed"||t.status==="cancelled")?`<button class="approveBtn" data-id="${esc(t.id)}">↻ Повторить запуск</button>`: ""}</div>`).join("")||'<div class="muted">Пока нет задач</div>';
$("agents").innerHTML=activeAgents.slice(0,10).map(a=>`<div class="item"><b>${esc(a.name)}</b><span class="tag">${esc(a.role)}</span><div class="muted">${esc(a.status)}</div></div>`).join("")||'<div class="muted">Агенты будут создаваться по задачам</div>';
$("memory").innerHTML=s.memory.slice(0,8).map(m=>`<div class="item">${esc(m.content)}</div>`).join("")||'<div class="muted">Память пуста</div>';
$("events").innerHTML=s.events.slice(0,10).map(e=>`<div class="item"><b>${esc(e.kind)}</b> — ${esc(e.message)}<div class="muted">${new Date(e.created_at).toLocaleString()}</div></div>`).join("")||'<div class="muted">Событий нет</div>';
}
function showOutputs(t){
 selectedTaskId=t?.id||selectedTaskId;
 const outs=t.outputs||[];
 const live=t.current_agent?'<div class="plan">⚙️ Сейчас работает: <b>'+esc(t.current_agent)+'</b> · '+esc(t.current_role||"agent")+' · раунд '+esc(t.current_round||1)+'</div>':"";
 $("result").innerHTML='<div class="plan"><b>🤖 '+esc(t.status)+' — '+esc(t.id)+'</b>'+live+outs.map((o,i)=>'<div class="item"><b>'+(i+1)+'. '+esc(o.agent?.name||o.agent?.role||"Agent")+'</b><div class="muted">'+esc(o.agent?.role||"")+'</div><p>'+esc(typeof o.result==="string"?o.result:JSON.stringify(o.result))+'</p></div>').join("")+'</div>';
}
function bindApproveButtons(){
 document.querySelectorAll(".approveBtn").forEach(b=>b.onclick=async()=>{
  const id=b.dataset.id;b.disabled=true;b.textContent="⏳ Запуск...";
  $("result").innerHTML='<div class="plan">⏳ Задача запущена. Команда AI работает...</div>';
  try{
   await api(`/api/task/${id}/approve`,{method:"POST"});
   // Важно: запуск отдельным запросом после успешного подтверждения.
   const result=await api(`/api/task/${id}/run`,{method:"POST"});
   showOutputs(result);
   await refresh();
  }catch(e){
   $("result").innerHTML=`<div class="plan">❌ ${esc(e.message)}</div>`;
   await refresh();
   b.disabled=false;b.textContent="▶ Повторить запуск";
  }
 });
}
async function refresh(){
 try{
  const [s,h]=await Promise.all([api("/api/state"),api("/api/health")]);
  render(s);bindApproveButtons();$("health").textContent="● онлайн";
  if(selectedTaskId){
   const current=s.tasks.find(t=>t.id===selectedTaskId);
   if(current) showOutputs(current);
  }
  return s
 }
 catch(e){$("health").textContent="● ошибка";return null}
}
$("runBtn").onclick=async()=>{
 const text=$("taskInput").value.trim();if(!text)return alert("Введите задачу");
 $("runBtn").disabled=true;$("result").innerHTML='<div class="plan">🧠 Анализирую задачу...</div>';
 try{const t=await api("/api/task",{method:"POST",body:JSON.stringify({text})});selectedTaskId=t.id;const p=t.plan;
 $("result").innerHTML=`<div class="plan"><b>🧠 ${esc(p.summary)}</b><h3>Команда</h3>${p.agents.map(a=>`<span class="tag">${esc(a.name)} · ${esc(a.role)}</span>`).join("")}<h3>План</h3><ol>${p.steps.map(x=>`<li>${esc(x)}</li>`).join("")}</ol><div class="muted">Требует подтверждения: ${p.needs_approval?"да":"нет"}</div></div>`;await refresh()
 }catch(e){$("result").innerHTML=`<div class="plan">❌ ${esc(e.message)}</div>`}finally{$("runBtn").disabled=false}
};
$("clearBtn").onclick=()=>{$("taskInput").value="";$("result").innerHTML=""};
$("memoryBtn").onclick=async()=>{const content=$("memoryInput").value.trim();if(!content)return;try{await api("/api/memory",{method:"POST",body:JSON.stringify({content})});$("memoryInput").value="";await refresh()}catch(e){alert(e.message)}};
refresh();setInterval(refresh,5000);
