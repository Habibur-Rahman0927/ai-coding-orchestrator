'use strict';
let fieldSequence = 0, workflowViewVersion = 0, workflowPollTimer = null;
let token = '', csrf = sessionStorage.getItem('ccx-session-proof') || '', authenticated = false, state = {}, setupState = {}, experience = {}, page = 'chat', selectedProject = '', selectedWorkflow = '', selectedChat = '', selectedTaskId = '';
// Consume the fragment before any network request; a bootstrap secret never remains in history.
let bootstrapCredential = new URLSearchParams(location.hash.slice(1)).get('bootstrap');
if (bootstrapCredential) history.replaceState(null, '', location.pathname);
const main = document.getElementById('main');
const pages = [['overview','Overview','◈'],['chat','Chat','◌'],['tasks','Tasks','✓'],['projects','Projects','▣'],['memory','Memory','▤'],['context','Context','◎'],['workflows','Workflows','◇'],['providers','Providers','⊞'],['sessions','Sessions','◷'],['approvals','Approvals','✓'],['activity','Activity & usage','◷'],['settings','Settings','⚙'],['help','Help','?']];
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'class') node.className = value;
    else if (key === 'value') { if (value !== undefined && value !== null) node.value = value; }
    else if (value !== undefined && value !== false) node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
};
function notice(message, error = false) { const n = document.getElementById('notice'); n.textContent = message; n.className = error ? 'error' : ''; n.hidden = false; clearTimeout(notice.timer); notice.timer = setTimeout(() => { n.hidden = true; }, error ? 10000 : 5000); }
async function api(path, body) {
  let response;
  try{response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache:'no-store', credentials:'same-origin', headers: {...(token?{'Authorization':'Bearer '+token}:{}), ...(csrf?{'X-CSRF-Token':csrf}:{}), ...(body !== undefined ? {'Content-Type':'application/json'} : {})}, ...(body !== undefined ? {body:JSON.stringify(body)} : {})});}
  catch{throw new Error('Workspace disconnected. Reopen the application, then inspect saved progress before retrying. The request outcome is unknown; your form entries remain here.');}
  const data = await response.json();
  if (!response.ok) {
    if (response.status===401 && authenticated) notice('Your session expired. Reopen the workspace from its startup command.',true);
    throw new Error(data.error || 'Request failed.');
  }
  return data;
}

const button = (label, action, style = '') => el('button',{type:'button',class:style,onclick:async event=>{const b=event.currentTarget;b.disabled=true;try{await action();}catch(error){notice(error.message,true);}finally{b.disabled=false;}}},label);
const panel = (title, ...children) => el('section',{class:'panel'}, title ? el('h2',{},title) : null,...children);
const empty = (title, description) => el('div',{class:'empty'},el('h3',{},title),el('p',{},description));
const pre = value => el('pre',{class:'result'}, typeof value === 'string' ? value : JSON.stringify(value,null,2));
const arr = value => Array.isArray(value) ? value : [];
const formatDate = value => !value ? '' : new Date(typeof value === 'number' ? value*1000 : value).toLocaleString();
const projectName = p => p.name || String(p.path||p.root||p.id).split(/[\\/]/).filter(Boolean).pop();
const text = value => value === null || value === undefined ? 'Not recorded' : String(value);
const statusTag = value => {const s=text(value);return el('span',{class:'tag '+(/^(done|success|completed?|available|approved|connection verified)$/i.test(s)?'good':/fail|cancel|error|unavailable/i.test(s)?'bad':/wait|pause|approval|block|unknown|restricted/i.test(s)?'warn':'')},s);};
function field(label,name,options={}) {const id='field-'+(++fieldSequence);const input=el(options.multiline?'textarea':options.options?'select':'input',{name,id,...(options.multiline?{}:options.options?{}:{type:options.type||'text'}),placeholder:options.placeholder,required:options.required,value:options.value, min:options.min,max:options.max,step:options.step}); if(options.options)for(const item of options.options)input.append(el('option',{value:typeof item==='string'?item:item.value},typeof item==='string'?item:item.label)); if(options.value!==undefined)input.value=options.value;return el('div',{class:'field'},el('label',{for:id},label),input,options.hint?el('p',{class:'hint'},options.hint):null);}
function form(children, label, action) {const f=el('form',{},...children,el('button',{type:'submit',class:'primary'},label));f.addEventListener('submit',async event=>{event.preventDefault();const submit=f.querySelector('[type=submit]');submit.disabled=true;try{await action(Object.fromEntries(new FormData(f)));}catch(error){notice(error.message,true);}finally{submit.disabled=false;}});return f;}
function heading(title,description,actions) {return el('div',{class:'page-head'},el('div',{},el('p',{class:'eyebrow'},'ORCHESTRATOR WORKSPACE'),el('h1',{},title),el('p',{},description)),actions?el('div',{class:'actions'},actions):null);}
function projectOptions(){return arr(state.projects).map(p=>({value:p.id,label:projectName(p)}));}
function projectPicker(action){const f=field('Project','active-project',{options:projectOptions(),value:selectedProject});f.querySelector('select').addEventListener('change',async event=>{selectedProject=event.target.value;selectedChat='';selectedWorkflow='';try{experience=await api('/api/experience',{project:selectedProject});await action();}catch(error){notice(error.message,true);}});return f;}
function projectNeeded(){if(!arr(state.projects).length){main.append(empty('Start with a project','Choose an approved repository to keep its conversations and context together.'),button('Choose a project',()=>go('projects'),'primary'));return true;}if(!selectedProject||!state.projects.some(p=>p.id===selectedProject))selectedProject=state.projects[0].id;return false;}
async function refresh(render=true){[state,setupState,experience]=await Promise.all([api('/api/state'),api('/api/setup'),api('/api/experience')]);if(!selectedProject)selectedProject=experience.project||'';applyAppearance();document.getElementById('updated').textContent='Updated '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});if(render)await renderPage();}
function go(name){if(location.hash==='#'+name)renderPage().catch(error=>notice(error.message,true));else location.hash=name;}
async function renderPage(){document.body.classList.remove('extension-chat','extension-tasks');document.getElementById('notice').hidden=true;clearTimeout(workflowPollTimer);workflowViewVersion++;page=location.hash.slice(1)||'chat';if(!pages.some(x=>x[0]===page)&&page!=='setup')page='chat';document.getElementById('breadcrumb').textContent='Workspace / '+(page==='setup'?'Setup':pages.find(x=>x[0]===page)[1]);for(const a of document.querySelectorAll('nav a'))a.setAttribute('aria-current',a.hash==='#'+(page==='tasks'?'chat':page)?'page':'false');main.replaceChildren();await ({overview,projects,memory,context,workflows,providers,activity,settings,setup,chat,tasks,sessions,approvals,help}[page])();}
function overview(){const projects=arr(state.projects),flows=arr(state.workflows),available=arr(state.providers).filter(p=>p.available);main.append(heading('Your work, in view.','Keep project knowledge close and coordinate agent work with explicit boundaries.'),el('div',{class:'metrics'},...[[projects.length,'Registered projects'],[flows.length,'Workflows'],[arr(state.running).length,'Active runners'],[available.length,'Locally available providers']].map(([n,label])=>el('div',{class:'metric'},el('p',{},label),el('strong',{class:'number'},n)))));const recent=panel('Projects',projects.length?projects.slice(0,4).map(p=>el('div',{class:'item'},el('h3',{},projectName(p)),el('p',{class:'path'},p.path||p.root),button('Open project',()=>{selectedProject=p.id;go('memory');},'quiet'))):empty('A clear place to begin','Register a local repository to build its project index.'),el('div',{class:'actions'},button('Manage projects',()=>go('projects'),'primary')));const flowsPanel=panel('Workflow queue',flows.length?flows.slice(0,4).map(w=>el('div',{class:'item'},el('h3',{},w.objective||w.id),statusTag(w.status||w.state),el('div',{class:'actions'},button('View workflow',()=>{selectedWorkflow=w.id;go('workflows');},'quiet')))):empty('No workflows yet','Define an objective and success criteria. Agent execution starts only when you run it.'));main.append(el('div',{class:'grid'},recent,flowsPanel),panel('This machine',el('p',{class:'muted'},'Machine information is local context. Refresh it when tools or the environment change.'),machineSummary(state.machine)));}
async function memory(){main.append(heading('Project memory','Inspect stored knowledge, search the project index, and remove records you no longer want.'));if(projectNeeded())return;main.append(projectPicker(memoryReload));await memoryReload();}
async function memoryReload(){document.getElementById('memory-content')?.remove();const container=el('div',{id:'memory-content'});main.append(container);const rows=arr(await api('/api/projects/'+selectedProject+'/memories'));const result=el('div',{});container.append(panel('Add a memory',form([field('Title','title',{required:true}),field('Instruction or note','body',{required:true,multiline:true}),field('Scope','scope',{options:['project','workflow','session','error','verification','skills','temporary']})],'Save memory',async data=>{await api('/api/projects/'+selectedProject+'/remember',data);await memoryReload();notice('Memory saved as a user instruction.');})),panel('Search knowledge',form([field('Search query','query',{required:true,placeholder:'Where is authentication configured?'}),field('Scope','scope',{placeholder:'Optional scope'})],'Search',async data=>{const found=await api('/api/projects/'+selectedProject+'/search',{query:data.query,scope:data.scope||null,limit:20});result.replaceChildren(pre(found));}),result),panel('Stored records',el('div',{class:'section-head'},el('p',{class:'muted'},rows.length+' memory records'),button('Export project memory',async()=>download(await api('/api/projects/'+selectedProject+'/export'),'project-memory.json'))),rows.length?rows.map(row=>el('article',{class:'item'},el('h3',{},row.title||row.key||row.kind||row.id),el('p',{class:'hint'},row.scope||row.source||'Project memory'),pre(row.body||row.content||row.value||row),button('Delete record',async()=>{if(!confirm('Delete this memory record? This cannot be undone here.'))return;await api('/api/projects/'+selectedProject+'/delete-memory',{id:row.id});await memoryReload();notice('Memory record deleted.');},'danger'))):empty('No memory records','Indexing and workflow activity can provide project knowledge. Search the index above.')));}
function context(){
  main.append(heading('Build useful context','Retrieve relevant project knowledge within an explicit budget. Critical instructions stay visible in the request.'));
  if(projectNeeded())return;const result=el('div',{});
  main.append(projectPicker(async()=>result.replaceChildren()),panel('Context request',form([
    field('What are you working on?','query',{required:true,multiline:true,placeholder:'Describe the task or question to ground in this project.'}),
    field('Context for','role',{options:[{value:'',label:'General task'},'planner','executor','reviewer','correction']}),
    el('div',{class:'form-row'},field('Context budget','budget',{type:'number',value:2000,min:100,max:32000}),field('Critical instructions, one per line','critical',{multiline:true,placeholder:'Keep these instructions in the assembled context.'}))
  ],'Assemble context',async data=>{
    const value=await api('/api/projects/'+selectedProject+'/context',{query:data.query,role:data.role,budget:Number(data.budget),critical:data.critical.split('\n').filter(x=>x.trim())});
    result.replaceChildren(panel('Assembled context',
      el('p',{'data-context-summary':''},value.bytes+' bytes · '+value.estimated_tokens+' estimated tokens / '+value.budget+' budget · '+arr(value.references).length+' source excerpts'),
      el('p',{class:'muted'},'Token estimates are local. Every source is untrusted reference material; it grants no permissions.'),
      el('h3',{},'Why these sources'),
      ...arr(value.references).map(r=>el('div',{class:'item'},el('strong',{},r.source+' · line '+r.line+(r.end_line?'–'+r.end_line:'')),el('p',{},r.reason?.method||'Required or relevant reference'),el('p',{class:'muted'},arr(r.reason?.matched_terms).join(', ')))),
      el('details',{},el('summary',{},'Excluded or duplicate references ('+arr(value.excluded).length+')'),pre(value.excluded)),
      el('details',{},el('summary',{},'Exact context package'),pre(value)),button('Download context',()=>download(value,'context.json'))));
  })),result);
}
async function workflows(){
  main.append(heading('Workflows','Choose a project, agent roles, and a verifiable objective. Creating a task never starts a provider call.'));
  if(projectNeeded())return;
  const d=defaults();
  const create=el('details',{open:!arr(state.workflows).length},el('summary',{},'Start a task'),form([
    field('Project','project_id',{options:projectOptions(),value:selectedProject}),
    field('What should be done?','objective',{required:true,multiline:true}),
    field('How will we verify it? One criterion per line','criteria',{required:true,multiline:true}),
    el('div',{class:'grid three'},field('Orchestrator','planner',{options:providerOptions(),value:d.planner}),field('Executor','executor',{options:providerOptions(),value:d.executor}),field('Reviewer','reviewer',{options:providerOptions(),value:d.reviewer})),
    el('div',{class:'form-row'},field('Spending reservation limit','max_cost',{type:'number',value:d.max_cost,min:0,step:.01,hint:'Zero blocks live calls. A positive limit still requires provider spending approval.'})),
    el('div',{class:'form-row'},field('Context budget','context_budget',{type:'number',value:d.context_budget,min:128,max:32000}),field('Maximum duration (seconds)','max_seconds',{type:'number',value:d.max_seconds,min:1,max:86400})),
    el('details',{},el('summary',{},'Optional execution policy and model overrides'),
      field('Execution policy','execution_policy',{options:[{value:'standard',label:'Plan, implement, test, and independently review'},{value:'single_task',label:'Single task: skip planning, retain tests and review'}],hint:'A single task avoids the planning call. Your selected provider roles are preserved.'}),
      field('Orchestrator model override','planner_model',{placeholder:'Inherit application or provider default'}),
      field('Executor model override','executor_model',{placeholder:'Inherit application or provider default'}),
      field('Reviewer model override','reviewer_model',{placeholder:'Inherit application or provider default'}))
  ],'Create workflow',async data=>{
    const value=await api('/api/workflows',{project_id:data.project_id,objective:data.objective,criteria:data.criteria.split('\n').filter(x=>x.trim()),budgets:{max_cost:Number(data.max_cost),max_tokens:d.max_tokens,max_context_tokens:Number(data.context_budget),max_seconds:Number(data.max_seconds)},providers:{planner:data.planner,executor:data.executor,reviewer:data.reviewer},execution_policy:data.execution_policy,model_overrides:Object.fromEntries(['planner','executor','reviewer'].filter(role=>data[role+'_model']?.trim()).map(role=>[role,data[role+'_model'].trim()]))});
    selectedWorkflow=value.id;await refresh();notice('Workflow created. Review its approvals before starting.');
  }));
  main.append(panel('',create));const flows=arr(state.workflows).filter(w=>w.project_id===selectedProject);
  if(!flows.length){main.append(empty('No workflows yet','Describe a task above. Nothing runs until you choose Run.'));return;}
  if(!selectedWorkflow||!flows.some(w=>w.id===selectedWorkflow))selectedWorkflow=flows[0].id;
  const side=el('div',{},...flows.map(w=>el('button',{class:'list-button',type:'button','aria-pressed':w.id===selectedWorkflow,onclick:()=>{selectedWorkflow=w.id;renderPage().catch(error=>notice(error.message,true));}},el('strong',{},w.objective||w.id),statusTag(w.status||w.state),el('span',{class:'hint'},w.id))));
  const detail=el('div',{id:'workflow-detail'});main.append(el('div',{class:'split'},side,detail));await workflowDetail(detail);
}
async function workflowDetail(target) {
  clearTimeout(workflowPollTimer);
  const version = ++workflowViewVersion, id = selectedWorkflow;
  const initial = await api('/api/workflows/' + id);
  if (!target.isConnected || version !== workflowViewVersion) return;
  const live = el('div', {}), feedback = el('p', {class:'hint',role:'status'}, 'Status loaded.');
  const taskList = el('div', {}), approvalList = el('div', {}), eventList = el('div', {class:'event-stream'});
  const checkpoints = el('div', {}), contextReport=el('div',{}), executionResults=el('div',{}), requestList=el('div',{}), cards = new Map();
  let eventSignature = '', approvalSignature = '', active = false, previousStatus = '';
  const reload = () => workflowDetail(target);
  const controls = el('div', {class:'actions'}, ...['run','pause','resume','retry','cancel'].map(action => button(action[0].toUpperCase()+action.slice(1), async () => {
    if (action === 'cancel' && !confirm('Cancel this workflow?')) return;
    await api('/api/workflows/'+id+'/'+action, {});
    await reload();
    notice(action === 'run' ? 'Runner started. Live updates follow its progress.' : 'Workflow '+action+' requested.');
  }, action === 'run' ? 'primary' : action === 'cancel' ? 'danger' : '')), button('Refresh status', reload, 'quiet'), button('Export workflow', async () => download(await api('/api/workflows/'+id+'/export'), 'workflow.json'), 'quiet'));
  const addTask = el('details', {}, el('summary', {}, 'Add a task'), form([
    field('Task title','title',{required:true}), field('Description','description',{multiline:true}),
    el('div',{class:'form-row'},field('Executor','executor',{options:['codex','claude','minimax']}),field('Reviewer','reviewer',{options:['claude','codex','minimax']}))
  ], 'Add task', async data => {await api('/api/workflows/'+id+'/tasks', data); await reload();}));
  const approve = approvalForm(id,reload);
  target.replaceChildren(
    panel(initial.objective || 'Workflow', el('p',{class:'path'},id), live, controls, feedback),
    panel('Tasks', taskList, addTask),
    panel('Approval requests',requestList),
    panel('Approvals', el('p',{class:'muted'},'Approve only the exact provider or command scope you intend. Approval is a user action; agents cannot approve for you.'), approvalList, approve),
    panel('Checkpoints', button('Load checkpoints',async()=>checkpoints.replaceChildren(pre(await api('/api/workflows/'+id+'/checkpoints')))),checkpoints),
    panel('Workflow context',button('Inspect exact workflow context',async()=>contextReport.replaceChildren(pre(await api('/api/workflows/'+id+'/context')))),contextReport),
    panel('Execution results',button('Inspect execution results',async()=>executionResults.replaceChildren(pre(await api('/api/workflows/'+id+'/results')))),executionResults),
    panel('Provider handoff',el('p',{class:'hint'},'Handoff preserves executor sessions and needs a matching failover permission plus destination sharing/spending approval.'),form([field('Role to hand off','role',{options:[{value:'planner',label:'Orchestrator'},{value:'reviewer',label:'Reviewer'}]}),field('New provider','to_provider',{options:providerOptions(),value:defaults().fallback_provider||undefined})],'Apply approved handoff',async data=>{if(!confirm('Apply this previously approved provider handoff?'))return;await api('/api/workflows/'+id+'/transition-role',data);await reload();})),
    panel('Event history',eventList)
  );
  function renderLive(w) {
    if(previousStatus && previousStatus!==w.status && ['COMPLETED','APPROVAL_REQUIRED','BLOCKED','PAUSED','FAILED','RECOVERY_REQUIRED'].includes(w.status))notice('Workflow '+w.status.toLowerCase().replaceAll('_',' ')+(w.reason?': '+w.reason:''),['FAILED','RECOVERY_REQUIRED'].includes(w.status));
    previousStatus=w.status;
    const running=Boolean(w.runner_active||w.status==='RUNNING'),terminal=['COMPLETED','CANCELLED','FAILED'].includes(w.status);
    const allowedControls=[!terminal&&!running&&['READY','APPROVAL_REQUIRED'].includes(w.status),!terminal&&w.status!=='PAUSED',!terminal&&!running&&['PAUSED','BLOCKED','RECOVERY_REQUIRED','BUDGET_EXHAUSTED'].includes(w.status),!terminal&&!running&&['BLOCKED','RECOVERY_REQUIRED'].includes(w.status),!terminal];
    [...controls.querySelectorAll('button')].slice(0,5).forEach((control,index)=>{control.disabled=!allowedControls[index];});
    addTask.querySelector('[type=submit]').disabled=terminal||running;
    live.replaceChildren(statusTag(w.status||w.state),el('p',{class:'muted'},w.runner_error||w.reason||''),el('p',{class:'hint'},'Recorded tokens: '+text(w.usage?.recorded_tokens)+' · Recorded cost: '+text(w.usage?.recorded_cost)),el('details',{},el('summary',{},'Criteria, budgets, and usage'),pre({criteria:w.criteria,budgets:w.budgets,usage:w.usage,providers:w.providers})));
    const tasks = arr(w.tasks);
    if(w.status==='COMPLETED'){
      const commands=tasks.flatMap(t=>arr(t.evidence?.tests?.commands));
      live.append(panel('Verified result',el('h3',{},w.objective),el('p',{},tasks.filter(t=>t.status==='VERIFIED').length+' tasks verified · '+commands.filter(c=>c.exit_code===0).length+' recorded commands passed.'),
        el('p',{class:'hint'},'Project knowledge records verified workflow evidence. Source changes and limitations remain in the execution and review details.'),
        el('details',{},el('summary',{},'Tests and review findings'),pre(tasks.map(t=>({task:t.title,tests:t.evidence?.tests,review:t.evidence?.review,execution:t.evidence?.execution}))))));
    }
    live.append(el('p',{class:'hint'},'Orchestrator: '+text(w.providers?.planner)+' · Executor: '+text(w.providers?.executor)+' · Reviewer: '+text(w.providers?.reviewer)),el('p',{class:'hint'},tasks.filter(t=>t.status==='VERIFIED').length+' of '+tasks.length+' tasks verified'+(w.started_at?' · Elapsed '+Math.max(0,Math.floor((Date.now()/1000-w.started_at)/60))+' min':'')));
    if (!tasks.length && !cards.size) taskList.replaceChildren(empty('No tasks yet','Add an explicit task or let the approved planner produce a bounded plan when you run.'));
    for (const t of tasks) {
      if (!cards.has(t.id)) {
        if (!cards.size) taskList.replaceChildren();
        const status = el('div',{}), evidence = pre(t);
        const card = el('div',{class:'item'},el('h3',{},t.title||t.id),status,el('p',{class:'muted'},t.description||''),el('details',{},el('summary',{},'Task details'),evidence),form([
          field('Destination provider','to_provider',{options:['codex','claude','minimax'].filter(provider=>provider!==t.executor)}),
          field('Transition','transition',{options:['delegate','failover'],hint:'Failover needs a matching user approval with task_id and to_provider.'})
        ],'Apply provider transition',async data=>{if(data.transition==='failover'&&!confirm('Apply this previously approved provider failover?'))return;await api('/api/tasks/'+t.id+'/'+data.transition,{to_provider:data.to_provider});await reload();}));
        cards.set(t.id,{status,evidence,transition:card.querySelector('[type=submit]')}); taskList.append(card);
      }
      const card = cards.get(t.id);
      card.status.replaceChildren(statusTag(t.status||t.state),el('p',{class:'hint'},'Executor: '+text(t.executor)+' · Reviewer: '+text(t.reviewer)));
      card.evidence.textContent = JSON.stringify(t,null,2);
      card.transition.disabled=running||terminal||!['PENDING','BLOCKED'].includes(t.status);
    }
    requestList.replaceChildren(...(arr(w.approval_requests).length?arr(w.approval_requests).map(request=>el('div',{class:'item'},el('h3',{},request.kind),el('p',{},request.reason),el('p',{class:'hint'},'Agent request only; no permission has been granted.'),pre(request.scope),el('div',{class:'actions'},button('Approve requested scope',async()=>{if(!confirm('Approve this exact requested scope?\n'+JSON.stringify(request.scope,null,2)))return;await api('/api/workflows/'+id+'/resolve-request',{request_id:request.id,decision:'approve'});await reload();},'primary'),button('Deny request',async()=>{await api('/api/workflows/'+id+'/resolve-request',{request_id:request.id,decision:'deny'});await reload();},'danger')))):[el('p',{class:'hint'},'No pending agent permission requests.')]));
    const approvals = arr(w.approvals), nextApprovals = JSON.stringify(approvals);
    if (nextApprovals !== approvalSignature) {
      approvalSignature = nextApprovals;
      approvalList.replaceChildren(...(approvals.length ? approvals.map(a=>el('div',{class:'item'},el('div',{class:'section-head'},el('h3',{},a.kind),statusTag(a.revoked?'Revoked':'Approved')),pre(a.scope),!a.revoked?button('Revoke approval',async()=>{if(!confirm('Revoke this approval?'))return;await api('/api/workflows/'+id+'/revoke',{approval_id:a.id});await reload();},'danger'):null)) : [el('p',{class:'hint'},'No approval records returned.')]));
    }
    const events = arr(w.events), nextEvents = JSON.stringify(events);
    if (nextEvents !== eventSignature) {
      eventSignature = nextEvents;
      const atEnd = eventList.scrollHeight-eventList.scrollTop-eventList.clientHeight < 40;
      const position = eventList.scrollTop;
      eventList.replaceChildren(...(events.length ? events.map(eventCard) : [el('p',{class:'muted'},'No events returned for this workflow.')]));
      eventList.scrollTop = atEnd ? eventList.scrollHeight : position;
    }
    active = Boolean(w.runner_active || w.status === 'RUNNING');
    feedback.textContent = (active ? 'Live · refreshing every 3 seconds' : 'Up to date · no active runner') + ' · ' + new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  async function poll() {
    if (version !== workflowViewVersion || !target.isConnected || !authenticated) return;
    try {
      if (document.visibilityState !== 'hidden') {
        const fresh = await api('/api/workflows/'+id);
        if (version !== workflowViewVersion || !target.isConnected) return;
        renderLive(fresh);
      }
    } catch {
      feedback.textContent = 'Updates unavailable · retrying in 3 seconds. Your form entries are preserved.';
    }
    if (active && version === workflowViewVersion && target.isConnected) workflowPollTimer = setTimeout(poll,3000);
  }
  renderLive(initial);
  if (active) workflowPollTimer = setTimeout(poll,3000);
}

async function activity(){
  main.append(heading('Activity & usage','Reported tokens, local estimates and unknown usage are shown separately. Cached input is not eliminated input.'));
  const flows=arr(state.workflows);if(!flows.length){main.append(empty('No activity yet','Workflow events and usage appear after you create and run work.'));return;}
  for(const item of flows){const [w,u]=await Promise.all([api('/api/workflows/'+item.id),api('/api/workflows/'+item.id+'/usage')]);
    main.append(panel(item.objective||item.id,statusTag(w.status||w.state),el('h3',{},'Provider usage by role'),
      ...Object.entries(u.role_totals||{}).map(([role,value])=>el('div',{class:'item','data-usage-role':role},el('h3',{},role),el('p',{},value.provider_calls+' provider calls'),el('p',{},'Reported input: '+text(value.reported_totals?.input_tokens)+' · output: '+text(value.reported_totals?.output_tokens)+' · cached input: '+text(value.reported_totals?.cached_tokens)))),
      el('p',{},'Context bytes prepared: '+text(u.context_bytes_prepared)+' · approval events: '+text(u.approval_events)+' · correction rounds: '+text(u.correction_rounds)),
      el('p',{class:'muted'},'Approval events are recorded actions, not measured human effort. Native session occupancy and native file reads are unknown. Cost savings are unverified.'),
      el('details',{},el('summary',{},'Exact usage and budgets'),pre({usage:u,budgets:w.budgets})),
      el('details',{},el('summary',{},'Events ('+arr(w.events).length+')'),pre(w.events||[])),button('Open workflow',()=>{selectedWorkflow=item.id;go('workflows');},'quiet')));
  }
}
function settings(){
  const developerTools=el('details',{class:'developer-tools'},el('summary',{},'Developer tools'),el('nav',{'aria-label':'Developer tools'},...pages.filter(([name])=>!['chat','tasks','projects','settings'].includes(name)).map(([name,label])=>el('a',{href:'#'+name},label))));
  const diagnostics=el('div',{}),backupResult=el('div',{}),appearance=field('Appearance','appearance',{options:['system','light','dark'],value:experience.appearance||'system'});appearance.querySelector('select').addEventListener('change',async event=>{try{experience=await api('/api/experience',{appearance:event.target.value});applyAppearance();}catch(error){notice(error.message,true);}});
  main.append(heading('Workspace settings','Manage onboarding, session security, and local diagnostics.'),panel('Appearance',appearance),developerTools,
    panel('Getting started',el('p',{class:'muted'},'Use connection help in Chat or inspect advanced workflow defaults. Existing provider login stays untouched.'),button('Advanced workflow defaults',async()=>{await api('/api/setup',{step:4});await refresh(false);go('setup');},'quiet'),button('Reopen setup',async()=>{await api('/api/setup',{step:1});await refresh(false);go('setup');},'primary')),
    el('div',{class:'grid'},panel('Connection & privacy',el('dl',{class:'data-list'},el('dt',{},'Network'),el('dd',{},'IPv4 loopback only'),el('dt',{},'Authentication'),el('dd',{},token?'Manual token in tab memory':'Expiring local browser session'),el('dt',{},'Cross-origin access'),el('dd',{},'Refused')),button('Sign out',disconnect,'danger'),button('Rotate browser credentials',async()=>{if(!confirm('Invalidate all dashboard sessions? Reopen the workspace from its startup command to sign in again.'))return;await api('/api/auth/rotate',{});await disconnect();},'quiet')),
    panel('Machine context',button('Refresh machine information',async()=>{state.machine=await api('/api/machine/refresh',{});await renderPage();}),machineSummary(state.machine))),
    panel('Backup & recovery',el('p',{class:'muted'},'Create a private database backup. It includes project knowledge and workflow state, but not project files or provider credentials. Recovery requires stopping the current service and reopening a separate backup copy.'),button('Create database backup',async()=>{const result=await api('/api/backups',{});backupResult.replaceChildren(pre(result));notice('Database backup created.');}),backupResult),
    panel('System health',el('p',{class:'muted'},'Check storage, indexing, interrupted workflows, and provider configuration without printing credentials.'),button('Run diagnostics',async()=>{const report=await api('/api/doctor');diagnostics.replaceChildren(pre(report),button('Export redacted report',()=>download(report,'workspace-diagnostics.json')));}),diagnostics));
}
function download(value,name){const blob=new Blob([JSON.stringify(value,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a',{href:url,download:name});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function disconnect(){
  try {await api('/api/auth/logout',{});} catch {}
  clearTimeout(workflowPollTimer);workflowViewVersion++;token='';csrf='';sessionStorage.removeItem('ccx-session-proof');authenticated=false;state={};
  document.getElementById('workspace').hidden=true;document.getElementById('login').hidden=false;
  document.getElementById('token').value='';main.replaceChildren();document.getElementById('token').focus();
}
async function enterWorkspace(){
  await refresh(false);authenticated=true;
  document.getElementById('token').value='';document.getElementById('login').hidden=true;
  document.getElementById('workspace').hidden=false;await renderPage();
}
for(const [name,label,icon]of pages){if(!['chat','projects','settings'].includes(name))continue;document.getElementById('navigation').append(el('a',{href:'#'+name},el('span',{class:'nav-icon','aria-hidden':'true'},icon),name==='chat'?'Workspace':label));}
document.getElementById('login-form').addEventListener('submit',async event=>{event.preventDefault();token=document.getElementById('token').value.trim();try{await enterWorkspace();}catch(error){token='';notice(error.message,true);}});
document.getElementById('disconnect').addEventListener('click',disconnect);
document.getElementById('refresh').addEventListener('click',()=>refresh().catch(error=>notice(error.message,true)));
window.addEventListener('hashchange',()=>{if(authenticated)renderPage().catch(error=>notice(error.message,true));});
async function initializeLogin(){
  try {
    const session=bootstrapCredential ? await api('/api/auth/bootstrap',{credential:bootstrapCredential}) : await api('/api/auth/session');
    csrf=session.csrf || session.csrf_token || '';if(csrf)sessionStorage.setItem('ccx-session-proof',csrf);await enterWorkspace();
  } catch(error) {
    csrf='';sessionStorage.removeItem('ccx-session-proof');
    if(bootstrapCredential)notice('This sign-in link expired or was already used. Open a fresh link from the workspace command.',true);
  } finally {bootstrapCredential=null;}
}
initializeLogin();

function eventCard(event){
  let data=event.data||{};if(typeof data==='string'){try{data=JSON.parse(data);}catch{data={};}}
  const title=event.event==='PROVIDER_EVENT'?[data.provider,data.role,data.type].filter(Boolean).join(' · '):String(event.kind||event.type||event.event||'Event').replaceAll('_',' ');
  return el('div',{class:'item'},el('h3',{},title),el('p',{class:'hint'},formatDate(event.created_at||event.timestamp)),data.text?el('p',{class:'event-text'},data.text):pre(data));
}
function machineSummary(machine={}){
  const tools=Object.entries(machine.tools||{}).filter(([,available])=>available).map(([name])=>name).join(', ')||'None detected';
  return el('dl',{class:'data-list'},el('dt',{},'System'),el('dd',{},[machine.os,machine.architecture].filter(Boolean).join(' · ')||'Unknown'),el('dt',{},'Python'),el('dd',{},machine.python||'Unknown'),el('dt',{},'Available tools'),el('dd',{},tools),el('dt',{},'Free storage'),el('dd',{},typeof machine.disk_free_bytes==='number'?(machine.disk_free_bytes/(1024**3)).toFixed(1)+' GiB':'Not reported'),el('dt',{},'Sharing'),el('dd',{},'Stored locally; not shared automatically'));
}
const providerOptions = () => arr(state.providers).map(p=>({value:p.id,label:p.id}));
const defaults = () => ({planner:'codex',executor:'codex',reviewer:'codex',context_budget:2000,max_cost:0,max_tokens:50000,max_seconds:1800,...setupState.defaults});
const check = (label,name,hint='') => el('div',{class:'field'},el('label',{class:'inline-check'},el('input',{type:'checkbox',name,value:'yes'}),el('span',{},label)),hint?el('p',{class:'hint'},hint):null);
function providerStatus(p){const status=p.connection_status||p.status;return ({connection_verified:'Connection previously verified',not_installed:'Setup needed',not_configured:'Sign-in or configuration needed',authentication_unknown:'Sign-in not checked',configured:'Configured · connection not tested',usage_restricted:'Usage limit reached',unavailable:'Temporarily unavailable'})[status]||String(status||(p.available?'Sign-in not checked':'Setup needed')).replaceAll('_',' ');}
function applyAppearance(){const appearance=experience.appearance||'system';document.documentElement.dataset.theme=appearance==='system'?(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'):appearance;}matchMedia('(prefers-color-scheme: light)').addEventListener('change',applyAppearance);
async function setup(){if(setupState.step===4)return advancedSetup();return chat();}
function help(){
  main.append(heading('Help','A short guide to doing useful work safely.'),
    ...[
      ['Get started','Choose one provider, register an approved Git repository, then open Chat. Existing Codex and Claude sign-in is reused by their installed CLI; detected is not authenticated.'],
      ['Ask or Build','Ask sends one read-only message. Build shows one approval card, then implements, tests and reviews using separate sessions. Choose another reviewer in Advanced task options if needed.'],
      ['Approve a task once','Approve & start records the exact sharing, usage, file access and test commands shown in the task card. Changed scopes require another approval. Remembered preferences do not grant permissions.'],
      ['Continue previous work','Choose the same project in Chat to recover its conversations. Open an unfinished workflow to inspect progress and use Resume. Completed work is not restarted. Unknown actions require inspection before retrying.'],
      ['Recover safely','Settings can create a private database backup. Stop the service before reopening a separate verified backup copy. A database restore does not undo source files or provider actions.'],
      ['Update your installation','Use the signed distribution CLI to preview and apply trusted updates. Stop active services and runners first. This development candidate has no production update feed or trusted signature.'],
      ['Keyboard access','Use Tab and Shift+Tab to move through controls, Enter to activate, and the Skip to workspace link to reach the main view. No browser or IDE shortcuts are overridden.'],
      ['Troubleshoot','Open Providers for local diagnostics. Live connection tests require explicit consent and may consume usage. Settings → Run diagnostics exports a redacted report. If the backend disconnects, reopen the workspace using its startup command.']
    ].map(([title,body])=>panel(title,el('p',{},body))),button('Open diagnostics',()=>go('settings'),'primary'));
}
async function advancedSetup(){
  const steps=['Environment','Discover providers','Configure providers','Workflow defaults','Register project','Ready'];
  const step=Math.max(1,Math.min(6,Number(setupState.step)||1));
  main.append(heading('Set up your workspace','Connect the tools you choose, set bounded defaults, and add an approved project. No provider request runs during setup.'),
    el('ol',{class:'setup-steps','aria-label':'Setup progress'},...steps.map((name,i)=>el('li',{'aria-current':i+1===step?'step':undefined,class:i+1===step?'current':''},el('span',{},String(i+1)),name))));
  const content=el('div',{id:'setup-step'});main.append(content);
  const advance=async next=>{setupState=await api('/api/setup',{step:next});await refresh(false);await renderPage();};
  if(step===1){
    const env=setupState.environment||setupState.machine||state.machine;
    content.append(panel('Your environment',el('p',{class:'muted'},'Detection stays on this computer. Only repositories you register are indexed.'),machineSummary(env),panel('Credential storage',el('p',{},setupState.credential_facilities?.os?.available?setupState.credential_facilities.os.name+' is available; access may require an operating system prompt.':'No OS credential store detected. You can explicitly use session-only or environment credentials.'),el('p',{class:'hint'},'Keys are never saved in ordinary configuration files.')),el('details',{},el('summary',{},'Application storage'),pre(setupState.storage||{}))));
  } else if(step===2){
    content.append(panel('Choose the providers you already use',el('p',{class:'muted'},'One provider is enough. Installed does not mean authenticated or live-verified.'),...arr(state.providers).map(p=>el('div',{class:'item'},el('h3',{},p.id),statusTag(providerStatus(p)),el('p',{class:'hint'},p.reason||p.limitation||'Authentication will be checked separately.'),button('Inspect '+p.id,async()=>{const result=await api('/api/providers/'+p.id+'/diagnostics');details.replaceChildren(pre(result));},'quiet')))));
    const details=el('div',{});content.append(details);
  } else if(step===3){
    content.append(panel('Configure only what you need',el('p',{class:'muted'},'Existing CLI login and model preferences are preserved. MiniMax can use secure credential storage or an explicitly selected session-only key.')));
    renderProviderCards(content);
  } else if(step===4){
    const d=defaults();
    content.append(panel('Your default workflow',form([
      el('div',{class:'grid three'},field('Default orchestrator','planner',{options:providerOptions(),value:d.planner}),field('Default executor','executor',{options:providerOptions(),value:d.executor}),field('Default reviewer','reviewer',{options:providerOptions(),value:d.reviewer})),
      field('Optional fallback','fallback_provider',{options:[{value:'',label:'No automatic fallback'},...providerOptions()],value:d.fallback_provider||''}),
      el('div',{class:'form-row'},field('Context budget (estimated tokens)','context_budget',{type:'number',min:128,max:32000,value:d.context_budget})),
      el('div',{class:'form-row'},field('Spending reservation limit','max_cost',{type:'number',min:0,step:.01,value:d.max_cost,hint:'Zero blocks paid workflows. This is not a provider-enforced billing cap.'}),field('Maximum duration (seconds)','max_seconds',{type:'number',min:1,max:86400,value:d.max_seconds})),
      field('Approval policy','approval_policy',{options:[{value:'ask',label:'Ask for each new permission scope'},{value:'reuse_scoped',label:'Reuse bounded workflow approvals'}],value:d.approval_policy||'ask',hint:'Both policies require initial authorization. No destructive, deployment, or billing permission is implied.'})
    ],'Save defaults and continue',async data=>{await api('/api/setup',{step:5,defaults:{...data,fallback_provider:data.fallback_provider||null,context_budget:Number(data.context_budget),max_tokens:d.max_tokens,max_cost:Number(data.max_cost),max_seconds:Number(data.max_seconds)}});await refresh(false);await renderPage();})));
  } else if(step===5){
    const preview=el('div',{});
    content.append(panel('Preview an approved repository',projectRegistrationForm(preview)),preview,
      panel('Registered projects',arr(state.projects).length?arr(state.projects).map(p=>el('div',{class:'item'},el('h3',{},projectName(p)),el('p',{class:'path'},p.path))):el('p',{class:'hint'},'No projects yet. Preview and register a project to continue.')));
  } else {
    content.append(panel('Ready when you are',el('p',{},'Your settings and project registrations are saved. Provider calls remain behind explicit approval.'),
      el('dl',{class:'data-list'},el('dt',{},'Projects'),el('dd',{},arr(state.projects).length),el('dt',{},'Default agent'),el('dd',{},defaults().executor)),
      el('div',{class:'actions'},...['Open dashboard','Start a workflow','Test configured providers','Review settings'].map((label,i)=>button(label,async()=>{await api('/api/setup',{completed:true,step:6});await refresh(false);go(['overview','workflows','providers','settings'][i]);},i===0?'primary':'')))));
  }
  main.append(el('div',{class:'actions'},step>1?button('Back',()=>advance(step-1),'quiet'):null,step<6&&step!==4?el('button',{type:'button',class:'primary',disabled:step===5&&!arr(state.projects).length,onclick:()=>advance(step+1).catch(error=>notice(error.message,true))},'Continue'):null));
}
function projectRegistrationForm(preview){return form([
  field('Project directory','path',{required:true,placeholder:'Paste the absolute path of an approved Git repository'}),
  el('details',{},el('summary',{},'Additional indexing exclusions'),field('Additional exclusions, one pattern per line','exclusions',{multiline:true,placeholder:'private/**\nlarge-generated/**',hint:'Credential, dependency, cache, and linked-file exclusions always apply.'}))
],'Preview project',async data=>{
  const request={path:data.path,exclusions:data.exclusions.split('\n').map(x=>x.trim()).filter(Boolean)};
  const view=workflowViewVersion;const result=await api('/api/projects/preview',request);
  if(view!==workflowViewVersion||!preview.isConnected)return;
  preview.replaceChildren(panel('Indexing preview',pre(result),button('Register this project',async()=>{const p=await api('/api/projects',request);if(view!==workflowViewVersion||!preview.isConnected)return;selectedProject=p.id;notice('Project registered. Building its initial index…');const indexed=await api('/api/projects/'+p.id+'/index',{});if(view!==workflowViewVersion||!preview.isConnected)return;await refresh(false);if(view!==workflowViewVersion||!preview.isConnected)return;experience=await api('/api/experience',{project:p.id});await api('/api/setup',{completed:true,step:6});go('chat');},'primary')));
});}
function projects(){
  main.replaceChildren(heading('Projects','Your repositories stay separate. Switching restores context without rebuilding the index.'));
  const preview=el('div',{}),list=el('div',{}),search=field('Find a project','project_search',{placeholder:'Search by name or path'});
  const render=()=>{const query=search.querySelector('input').value.toLowerCase();const favorites=experience.favorites||[],recent=experience.recent||[];
    const sorted=arr(state.projects).slice().sort((a,b)=>Number(favorites.includes(b.id))-Number(favorites.includes(a.id))||(recent.indexOf(a.id)<0?999:recent.indexOf(a.id))-(recent.indexOf(b.id)<0?999:recent.indexOf(b.id)));
    list.replaceChildren(...sorted.filter(p=>(projectName(p)+' '+p.path).toLowerCase().includes(query)).map(p=>el('article',{class:'item'},el('h3',{},projectName(p)),el('p',{class:'path'},p.path),el('p',{class:'hint'},(p.id===experience.project?'Last active project · ':'')+arr(state.workflows).filter(w=>w.project_id===p.id&&!['COMPLETED','CANCELLED'].includes(w.status)).length+' unfinished workflows'),
      el('div',{class:'actions'},button('Open '+projectName(p),async()=>{selectedProject=p.id;selectedChat='';selectedWorkflow='';experience=await api('/api/experience',{project:p.id});go('chat');},'primary'),button(favorites.includes(p.id)?'Remove favorite':'Add favorite',async()=>{experience=await api('/api/experience',{favorite:p.id});render();},'quiet'),button('Refresh context',async()=>{notice('Updating project context…');const result=await api('/api/projects/'+p.id+'/index',{});preview.replaceChildren(panel('Project knowledge ready',pre(result)));notice('Project knowledge updated.');},'quiet')))));
    if(!list.childElementCount)list.append(empty('No matching projects','Register a repository below or change your search.'));
  };search.querySelector('input').addEventListener('input',render);render();
  main.append(panel('Recent and favorite projects',search,list),el('details',{open:!arr(state.projects).length},el('summary',{},'Register a project'),projectRegistrationForm(preview)),preview);
}
function renderProviderCards(container, onlyProvider=null){
  container.append(el('div',{class:'grid three'},...arr(state.providers).filter(p=>!onlyProvider||p.id===onlyProvider).map(p=>{
    const result=el('div',{}),saved=state.settings?.provider_config?.[p.id]||{},providerState=el('div',{},statusTag(providerStatus(p))),verifiedNote=el('p',{class:'hint'},'Last verified: '+(p.last_verified_at?formatDate(p.last_verified_at):'Not verified'));
    const updateDiagnostic=value=>{providerState.replaceChildren(statusTag(providerStatus(value)));verifiedNote.textContent='Last verified: '+(value.last_verified_at?formatDate(value.last_verified_at):'Not verified');};
    const card=panel(p.id,providerState,el('p',{class:'muted'},p.reason||p.limitation||'Local discovery only; no live connection has been verified.'),
      verifiedNote,
      el('details',{},el('summary',{},'Capabilities and authentication'),pre(p)),
      el('div',{class:'actions'},button('Check local setup',async()=>{const diagnostic=await api('/api/providers/'+p.id+'/diagnostics');updateDiagnostic(diagnostic);result.replaceChildren(pre(diagnostic));}),button('Test live connection',async()=>{
        const diagnostic=await api('/api/providers/'+p.id+'/diagnostics');updateDiagnostic(diagnostic);result.replaceChildren(pre(diagnostic));
        if(!confirm('Run this live connection test for '+p.id+'?\n'+JSON.stringify(diagnostic.plan||{},null,2)+'\nThis can consume subscription usage or API credits. No project context is sent. Native CLI access uses its existing account/settings. Billing cannot be capped by this application.'))return;
        notice('Testing '+p.id+'…');result.replaceChildren(pre(await api('/api/providers/'+p.id+'/diagnostics',{confirmed:true,provider:p.id,max_calls:1,native_agent_access:p.id!=='minimax'})));updateDiagnostic(await api('/api/providers/'+p.id+'/diagnostics'));await refresh(false);
      },'quiet')),result,
      form([field('Application model override','model',{value:saved.model||'',placeholder:'Inherit provider default',hint:p.id==='minimax'?'Enter an exact model identifier supported by your account.':'Leave blank to inherit the CLI preference. Native login/settings are not changed.'}),...(p.id==='minimax'?[field('Environment variable name (optional)','api_key_env',{value:saved.api_key_env||'MINIMAX_API_KEY'}),field('Endpoint','endpoint',{value:saved.endpoint||'https://api.minimax.io/v1/chat/completions'})]:[])],
        'Save configuration',async data=>{const config=Object.fromEntries(Object.entries(data).filter(([,v])=>v.trim()));if(p.id==='minimax'&&saved.credential_mode)config.credential_mode=saved.credential_mode;await api('/api/providers/'+p.id+'/configure',{config});await refresh(false);notice('Application provider preferences saved.');})
    );
    if(p.id==='minimax'){
      const keyForm=form([field('MiniMax API key','secret',{type:'password',required:true,hint:'Only sent to this local authenticated server. Never shown again or stored in browser storage.'}),field('Credential storage','mode',{options:[{value:'os',label:'OS credential store'},{value:'session',label:'This server session only'}],hint:'If the OS store is unavailable, choose session-only explicitly. No plaintext fallback is used.'})],'Save credential',async data=>{
        if(!confirm('Store or replace the MiniMax credential using '+(data.mode==='os'?'the operating system credential store':'memory for this server session only')+'?'))return;
        const secret=data.secret;keyForm.querySelector('[name=secret]').value='';
        const value=await api('/api/providers/minimax/credentials',{action:'save',secret,mode:data.mode,confirmed:true});result.replaceChildren(pre(value));notice('Credential saved. A live connection has not been tested.');await refresh(false);
      });
      keyForm.querySelector('[name=secret]').setAttribute('autocomplete','new-password');
      card.append(el('details',{},el('summary',{},'Secure credential setup'),keyForm,button('Remove stored credential',async()=>{if(!confirm('Remove the MiniMax credential managed by this workspace?'))return;result.replaceChildren(pre(await api('/api/providers/minimax/credentials',{action:'remove',confirmed:true})));await refresh(false);},'danger')));
    }
    return card;
  })));
}
function providers(){main.append(heading('Providers','Keep existing CLI authentication. Configure only the agents you need, and verify live connections explicitly.'));renderProviderCards(main);}
function approvalForm(id,reload){
  const kindField=field('Permission','kind',{options:[{value:'sharing',label:'Share project context with a provider'},{value:'cost',label:'Reserve provider spending'},{value:'native_agent_access',label:'Use native agent access'},{value:'native_agent_write',label:'Allow native agent file changes'},{value:'operations',label:'Allow scoped patches'},{value:'command',label:'Run an exact test command'},{value:'recovery',label:'Resolve an interrupted action'},{value:'failover',label:'Allow provider failover'}]});
  const dynamic=el('div',{});
  const build=()=>{
    const kind=kindField.querySelector('select').value;dynamic.replaceChildren();
    if(['sharing','cost','native_agent_access','native_agent_write'].includes(kind))dynamic.append(field('Provider','provider',{options:providerOptions()}));
    if(kind==='cost')dynamic.append(field('Total spending reservation','max_cost',{type:'number',min:.01,step:.01,required:true,value:1}),field('Maximum reservation per call','max_call_cost',{type:'number',min:.01,step:.01,required:true,value:.1}),el('p',{class:'hint'},'Reservations limit dispatch, not upstream billing. Choose limits you understand.'));
    if(kind==='native_agent_access')dynamic.append(el('p',{class:'hint'},'The native CLI can access files outside the filtered project tools. Its own sandbox/settings still apply.'));
    if(kind==='native_agent_write'||kind==='operations')dynamic.append(el('p',{class:'hint'},'Authorize code changes in this selected workflow. Commit, push, and deployment are not implied.'));
    if(kind==='command')dynamic.append(field('Command name','name',{required:true,placeholder:'unit-tests'}),field('Executable','executable',{required:true,placeholder:'python3'}),field('Arguments, one per line','arguments',{multiline:true,placeholder:'-m\nunittest\ndiscover'}),field('Working directory within project','cwd',{value:'.',required:true}),field('Timeout (seconds)','timeout',{type:'number',min:1,max:600,value:60}),el('p',{class:'hint'},'This program can perform anything its arguments permit. Arguments are passed directly, without a shell.'));
    if(kind==='recovery')dynamic.append(field('Interrupted action ID','action_id',{required:true}),field('Recovery decision','decision',{options:[{value:'retry',label:'Authorize retry after inspecting effects'},{value:'fail',label:'Mark this action failed'}]}),el('p',{class:'hint'},'Inspect actual files and provider history before retrying. An unknown outcome may already have changed files.'));
    if(kind==='failover')dynamic.append(field('Transition target','transition_target',{options:[{value:'task',label:'Task executor'},{value:'planner',label:'Workflow orchestrator'},{value:'reviewer',label:'Workflow reviewer'}]}),field('Task ID (for a task transition)','task_id'),field('Destination provider','to_provider',{options:providerOptions()}));
  };
  kindField.querySelector('select').addEventListener('change',build);build();
  return form([kindField,dynamic],'Approve this permission',async data=>{
    let scope={};
    if(data.provider)scope.provider=data.provider;
    if(data.kind==='cost')Object.assign(scope,{max_cost:Number(data.max_cost),max_call_cost:Number(data.max_call_cost)});
    if(data.kind==='operations')scope.operations=['patch'];
    if(data.kind==='command')scope={name:data.name,argv:[data.executable,...data.arguments.split('\n').filter(x=>x.length)],cwd:data.cwd,timeout:Number(data.timeout)};
    if(data.kind==='recovery')scope={action_id:data.action_id,decision:data.decision};
    if(data.kind==='failover'){if(data.transition_target==='task'&&!data.task_id.trim())throw new Error('Enter the selected task ID.');scope=data.transition_target==='task'?{task_id:data.task_id,to_provider:data.to_provider}:{role:data.transition_target,to_provider:data.to_provider};}
    if(!confirm('Approve '+data.kind+' for this workflow?\n'+JSON.stringify(scope,null,2)))return;
    await api('/api/workflows/'+id+'/approve',{kind:data.kind,scope});await reload();
  });
}
async function approvals(){
  main.append(heading('Approval center','Inspect blockers and authorize only the exact capabilities needed for a workflow.'));
  const flows=arr(state.workflows).filter(w=>w.project_id===selectedProject);
  if(!flows.length){main.append(empty('No workflows','Create a workflow before granting scoped permissions.'));return;}
  for(const flow of flows){const w=await api('/api/workflows/'+flow.id);main.append(panel(w.objective,statusTag(w.status),el('p',{class:'muted'},w.reason||'No current blocker reported.'),button('Inspect workflow',()=>{selectedWorkflow=w.id;go('workflows');},'quiet'),el('details',{},el('summary',{},'Manage permissions'),approvalForm(w.id,async()=>{await refresh(false);await renderPage();})),pre(arr(w.approvals))));}
}
async function sessions(){
  main.append(heading('Sessions','Inspect stored provider session mappings and continue conversations in their original project.'));
  const result=await api('/api/sessions');main.append(panel('Provider sessions',arr(result.sessions||result).length?pre(result):empty('No sessions yet','A session appears after authorized provider execution.')));
}

// Drafts and retry identities stay in this tab; credentials never enter these records.
const taskDrafts = new Map();
function taskDraft(project){
  if(!taskDrafts.has(project))taskDrafts.set(project,{content:'',mode:'build',newConversation:false});
  return taskDrafts.get(project);
}
function submissionKey(){return crypto.randomUUID();}
function pendingSubmission(project,value){const key='ccx-pending-'+project;if(value===null){sessionStorage.removeItem(key);return;}if(value){sessionStorage.setItem(key,JSON.stringify(value));return;}try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch{return null;}}
function connectAgent(container,agent){
  const commands={codex:['brew install --cask codex','codex login'],claude:['claude auth login']};
  const card=panel('Connect '+agent,el('p',{class:'muted'},'Your existing provider account stays with that tool. Setup does not send project data or run a paid test.'));
  for(const command of commands[agent]||[])card.append(el('div',{class:'command-row'},el('code',{},command),button('Copy',async()=>{await navigator.clipboard.writeText(command);notice('Command copied. Run it in your terminal.');},'quiet')));
  if(agent==='claude')card.append(el('p',{class:'hint'},'Install Claude Code from its official installation guide if the command is missing.'),el('a',{href:'https://code.claude.com/docs/en/setup',target:'_blank',rel:'noopener noreferrer'},'Claude Code installation guide'));
  card.append(button('Check again',async()=>{const result=await api('/api/providers/'+agent+'/diagnostics');await refresh(false);await renderPage();notice(result.remediation||providerStatus(result));},'primary'));
  const detail=el('details',{open:agent==='minimax'},el('summary',{},'Connection settings'));
  renderProviderCards(detail,agent);card.append(detail);container.append(card);
}
// Render a deliberately small Markdown subset with DOM nodes, never HTML injection.
function chatMarkdown(value){
  const root=el('div',{class:'chat-markdown'});
  function inline(parent,text){
    const pattern=/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\))/g;let offset=0;
    for(const match of text.matchAll(pattern)){
      parent.append(document.createTextNode(text.slice(offset,match.index)));
      const token=match[0];
      if(token.startsWith('`'))parent.append(el('code',{},token.slice(1,-1)));
      else if(token.startsWith('**'))parent.append(el('strong',{},token.slice(2,-2)));
      else{const link=token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);let url;
        try{url=new URL(link[2]);}catch{}
        if(url&&['https:','http:'].includes(url.protocol))parent.append(el('a',{href:url.href,target:'_blank',rel:'noopener noreferrer'},link[1]));
        else parent.append(document.createTextNode(token));}
      offset=match.index+token.length;
    }
    parent.append(document.createTextNode(text.slice(offset)));
  }
  let paragraph=[],list=null,code=null;
  const flush=()=>{if(paragraph.length){const p=el('p',{});inline(p,paragraph.join('\n'));root.append(p);paragraph=[];}list=null;};
  const lines=String(value||'').split('\n');
  const cells=line=>line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell=>cell.trim());
  for(let index=0;index<lines.length;index++){
    const line=lines[index];
    if(/^\s*```/.test(line)){
      flush();if(code!==null){root.append(el('pre',{},el('code',{},code.join('\n'))));code=null;}else code=[];continue;
    }
    if(code!==null){code.push(line);continue;}
    if(!line.trim()){flush();continue;}
    if(line.includes('|')&&index+1<lines.length&&cells(lines[index+1]).length>1&&cells(lines[index+1]).every(cell=>/^:?-{3,}:?$/.test(cell))){
      flush();const headers=cells(line),table=el('table',{}),head=el('tr',{}),body=el('tbody',{});
      for(const title of headers){const cell=el('th',{scope:'col'});inline(cell,title);head.append(cell);}
      table.append(el('thead',{},head),body);index++;
      while(index+1<lines.length&&lines[index+1].includes('|')&&lines[index+1].trim()){
        const values=cells(lines[++index]),row=el('tr',{});
        for(let column=0;column<headers.length;column++){const cell=el('td',{});inline(cell,values[column]||'');row.append(cell);}body.append(row);
      }
      root.append(el('div',{class:'chat-table'},table));continue;
    }

    const heading=line.match(/^#{1,6}\s+(.+)$/),item=line.match(/^\s*(?:([-*+])|\d+\.)\s+(.+)$/);
    if(heading){flush();const h=el('h3',{});inline(h,heading[1]);root.append(h);}
    else if(item){if(paragraph.length)flush();const tag=item[1]?'ul':'ol';if(!list||list.tagName.toLowerCase()!==tag){list=el(tag,{});root.append(list);}const li=el('li',{});inline(li,item[2]);list.append(li);}
    else{list=null;paragraph.push(line);}
  }
  flush();if(code!==null)root.append(el('pre',{},el('code',{},code.join('\n'))));return root;
}
function tokenUsageText(usage,visible,start,end,now=Date.now()/1000){
  const known=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0;
  const elapsed=start?Math.max(0,(end||now)-start):0;
  const reported=known(usage?.output_tokens);
  const output=reported?usage.output_tokens:visible?Math.ceil(new TextEncoder().encode(visible).length/4):null;
  const parts=[];
  if(known(usage?.input_tokens))parts.push(usage.input_tokens.toLocaleString()+' input tokens reported');
  if(output!==null)parts.push(reported?output.toLocaleString()+' output tokens reported':'~'+output.toLocaleString()+' visible output tokens (estimate)');
  else parts.push('Waiting for provider token usage');
  if(output!==null&&elapsed>0)parts.push((output/elapsed).toFixed(1)+' tokens/s · '+(output/elapsed/1000).toFixed(3)+' tokens/ms · average'+(reported?'':' estimate'));
  if(elapsed>0)parts.push(elapsed.toFixed(1)+'s elapsed');
  return parts.join(' · ');
}
function workflowTokenUsage(w){
  const events=arr(w.events),start=events.filter(e=>e.event==='ACTION_STARTED').at(-1);
  if(!start)return 'Token usage appears when an agent starts. Command execution does not itself consume model tokens.';
  const observed=events.filter(e=>e.action_id===start.action_id);
  const usage=observed.filter(e=>e.event==='PROVIDER_EVENT'&&e.data?.type==='usage').reduce((value,e)=>({...value,...e.data.usage}),{});
  const text=observed.filter(e=>e.event==='PROVIDER_EVENT'&&e.data?.type==='text').reduce((value,e)=>e.data.snapshot?e.data.text:value+(e.data.text||''),'');
  const ended=observed.find(e=>['ACTION_COMPLETED','ACTION_OUTCOME_UNCERTAIN'].includes(e.event));
  const end=ended?.created_at||(!w.runner_active&&w.status!=='RUNNING'?w.updated_at:null);
  return (end?'Last call · ':'Live call · ')+(start.data?.provider||'Agent')+' · '+(start.data?.role||'call')+' · '+tokenUsageText(usage,text,start.created_at,end);
}
function chatMessage(message,agent){
  agent=message.metadata?.provider||agent;
  const node=el('article',{class:'chat-message '+message.role},el('h3',{},message.role==='user'?'You':agent),message.role==='user'?el('p',{},message.content||''):chatMarkdown(message.content));
  if(message.id)node.dataset.messageId=message.id;
  const metadata=message.metadata||{};
  if(message.role==='assistant'&&metadata.provider_started_at)node.append(el('p',{class:'hint token-meter',title:'Average output tokens over wall-clock provider-call time, including waiting and tools. Visible-text estimates exclude hidden reasoning, tool output and input tokens.'},tokenUsageText(message.usage,metadata.output_received?message.content:'',metadata.provider_started_at,metadata.provider_finished_at)));
  if(message.role==='assistant'&&arr(metadata.activity).length){
    const events=arr(metadata.activity),last=events[events.length-1];
    node.append(el('details',{class:'live-activity',open:!message.content||last.phase==='running'},el('summary',{},'Activity · '+last.label),
      el('p',{class:'hint'},'Observed workspace/provider events. Some providers expose fewer details.'),
      el('ol',{},...events.slice(-12).map(item=>el('li',{},el('span',{},item.label+' · '+item.phase),item.detail?el('code',{},item.detail):null,item.output?pre(item.output):null)))));
  }
  if(message.role==='assistant'&&metadata.sources){
    node.append(el('p',{class:'hint'},'Requested: '+(metadata.requested_model||'provider default')+' · effort '+(metadata.requested_effort||'default')));
    const sources=Array.from(new Set(arr(metadata.sources).map(r=>r.source+':'+r.line)));
    node.append(el('details',{},el('summary',{},'Context supplied · '+sources.length+' source excerpts'),el('p',{class:'hint'},'These sources were supplied to the model; they do not verify its answer. '+metadata.indexed_text_files+' text files indexed.'),el('ul',{},...sources.map(source=>el('li',{},el('code',{},source))))));
  }
  return node;
}
function chatTabs(){
  const tabs=el('div',{class:'workspace-chat-tabs',role:'tablist','aria-label':'Chat workspace'});
  for(const [target,label] of [['chat','Chat'],['tasks','Tasks']]){
    const tab=button(label,()=>go(target),'quiet');
    tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(page===target));
    tab.tabIndex=page===target?0:-1;
    tab.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();go(target==='chat'?'tasks':'chat');}});
    tabs.append(tab);
  }
  return tabs;
}
async function chat(){
  const version=workflowViewVersion;
  if(!arr(state.projects).length)main.append(heading('Open your project','Connect an agent and choose a local project to begin.'));
  else document.body.classList.add('extension-chat');
  if(!arr(state.projects).length){
    const pick=field('Agent','first-agent',{options:providerOptions(),value:defaults().executor||'codex'}),connection=el('div',{});
    const draw=()=>{connection.replaceChildren();connectAgent(connection,pick.querySelector('select').value);};
    pick.querySelector('select').addEventListener('change',async event=>{draw();try{await api('/api/setup',{defaults:{executor:event.target.value}});}catch(error){notice(error.message,true);}});draw();
    const preview=el('div',{});
    main.append(pick,connection,panel('Choose your project',el('p',{class:'hint'},'Paste the path of your Git project. Preview shows what can be indexed; nothing is shared with an agent yet.'),projectRegistrationForm(preview)),preview);
    return;
  }
  if(!state.projects.some(p=>p.id===selectedProject))selectedProject=experience.project||state.projects[0].id;
  if(!state.projects.some(p=>p.id===selectedProject))selectedProject=state.projects[0].id;
  const project=selectedProject,draft=taskDraft(project);
  if(!draft.loaded){Object.assign(draft,await api('/api/projects/'+project+'/draft'));draft.loaded=true;}
  let projectAccess=await api('/api/projects/'+project+'/access');
  let draftTimer;
  const saveDraft=()=>{clearTimeout(draftTimer);const payload=Object.fromEntries(['content','mode','teams','chatOptions','newConversation'].filter(k=>draft[k]!==undefined).map(k=>[k,draft[k]]));return api('/api/projects/'+project+'/draft',payload);};
  const scheduleDraft=()=>{clearTimeout(draftTimer);draftTimer=setTimeout(()=>saveDraft().catch(error=>notice('Draft could not be saved: '+error.message,true)),250);};
  const current=()=>workflowViewVersion===version&&selectedProject===project;
  let agent=experience.agents?.[project]||defaults().executor||'codex';
  const agentField=field('Agent','task-agent',{options:providerOptions(),value:agent});
  let unresolvedSubmission=false;
  const pending=pendingSubmission(project);
  if(pending&&!draft.messageRequest){
    try{const recovered=await api('/api/tasks/submission/'+encodeURIComponent(pending.key));if(!current())return;
      if(recovered.chat_id&&recovered.submitted&&!recovered.workflow_id){selectedChat=recovered.chat_id;draft.newConversation=false;pendingSubmission(project,null);}
      else if(recovered.workflow_id){selectedTaskId=recovered.workflow_id;selectedChat=recovered.chat_id||'';draft.newConversation=false;pendingSubmission(project,null);}
      else unresolvedSubmission=true;
    }catch{unresolvedSubmission=true;}
  }
  if(unresolvedSubmission)main.append(panel('Previous submission needs inspection',el('p',{},'The previous request may have reached the server. No work has been resent. Inspect recent work before starting another request.'),button('Check saved state',()=>renderPage(),'primary'),button('I inspected; start a new request',()=>{pendingSubmission(project,null);return renderPage();},'quiet')));
  const controls=el('div',{class:'chat-top-toolbar'},projectPicker(()=>renderPage()),agentField,button('New chat',()=>{selectedChat='';draft.newConversation=true;draft.content='';saveDraft();return renderPage();},'quiet'));
  main.append(chatTabs(),controls);
  const choices=arr(await api('/api/chats')).filter(c=>c.project_id===project);
  if(!current())return;
  const saved=experience.conversations?.[project];
  if(!draft.newConversation&&!choices.some(c=>c.id===selectedChat))selectedChat=choices.find(c=>c.id===saved)?.id||choices[0]?.id||'';
  if(draft.newConversation)selectedChat='';
  agentField.querySelector('select').addEventListener('change',async event=>{
    try{experience=await api('/api/experience',{project,agent:event.target.value});draft.newConversation=false;await renderPage();}catch(error){notice(error.message,true);}
  });
  const provider=arr(state.providers).find(p=>p.id===agent);
  controls.append(el('span',{class:'chat-connection',title:providerStatus(provider||{})},provider?.available?'● Agent available':'○ Connect agent'));
  if(!provider?.available){document.body.classList.remove('extension-chat');connectAgent(main,agent);return;}
  const connection=el('details',{},el('summary',{},'Connection help'));connectAgent(connection,agent);controls.append(connection);
  if(choices.length){
    const selector=field('Conversation','task-conversation',{options:[{value:'',label:'New conversation'},...choices.map(c=>({value:c.id,label:c.title||c.id}))],value:selectedChat});
    selector.querySelector('select').addEventListener('change',async event=>{
      try{selectedChat=event.target.value;draft.newConversation=!selectedChat;if(selectedChat)experience=await api('/api/experience',{project,agent,conversation:selectedChat});await renderPage();}catch(error){notice(error.message,true);}
    });controls.append(el('details',{class:'chat-history'},el('summary',{},'History'),selector));
  }
  const available=await api('/api/chat/options/'+agent);if(!current())return;
  const savedChoice=choices.find(c=>c.id===selectedChat)||{};
  draft.chatOptions=draft.chatOptions||{};
  const optionKey=agent;
  const options=draft.chatOptions[optionKey]||(draft.chatOptions[optionKey]={model:savedChoice.provider===agent?savedChoice.model||'':'',effort:savedChoice.provider===agent?savedChoice.effort||'':''});
  const modelNames=Array.from(new Set([...arr(available.models),...(options.model?[options.model]:[])]));
  const modelField=field('Model','chat-model',{options:[{value:'',label:'Provider default'},...modelNames,{value:'custom',label:'Custom model…'}],value:options.model});
  const customModel=field('Model ID','chat-model-id',{placeholder:'Exact model ID from your provider',value:options.model});customModel.hidden=true;
  const effortField=field('Reasoning effort','chat-effort',{options:[{value:'',label:'Provider default'},...arr(available.efforts)],value:options.effort});
  effortField.querySelector('select').disabled=!arr(available.efforts).length;
  const settingsSummary=el('summary',{'aria-label':'Chat settings'},el('span',{},'⚙ Settings'),el('span',{class:'chat-settings-value'}));
  const chatSettings=el('details',{'data-chat-settings':'',class:'chat-settings'},settingsSummary,el('div',{class:'form-row'},modelField,effortField),customModel,el('p',{class:'hint'},arr(available.efforts).length?'Optional: default follows your provider settings. Higher effort may take longer and use more allowance. Model and effort availability depend on your account and CLI.':'This provider does not expose reasoning effort here. Choose a model or keep its configured default.'));
  modelField.querySelector('select').addEventListener('change',event=>{customModel.hidden=event.target.value!=='custom';customModel.querySelector('input').required=!customModel.hidden;options.model=customModel.hidden?event.target.value:customModel.querySelector('input').value;});
  customModel.querySelector('input').addEventListener('input',event=>{options.model=event.target.value.trim();});
  effortField.querySelector('select').addEventListener('change',event=>{options.effort=event.target.value;});
  const updateSettingsSummary=()=>{settingsSummary.querySelector('.chat-settings-value').textContent=(options.model||'Default model')+' · '+(options.effort||'Default effort');};
  chatSettings.addEventListener('input',updateSettingsSummary);chatSettings.addEventListener('change',updateSettingsSummary);updateSettingsSummary();
  const transcript=el('div',{class:'chat-messages chat-transcript','aria-live':'polite',role:'log','aria-label':'Conversation messages'}),responseStatus=el('p',{class:'hint',role:'status'});
  if(!selectedChat)transcript.append(el('div',{class:'chat-welcome'},el('h2',{},'Let’s work on your project'),el('p',{},'Ask a question, explore your code, or describe a change.')));
  main.append(transcript,responseStatus);
  const messageField=field('Your task','content',{multiline:true,required:true,value:draft.content,placeholder:'Explain this project, fix a bug, or describe what you want to build.'});
  const modeField=field('Action','action',{options:[{value:'ask',label:'Ask · no changes'},{value:'build',label:'Build · make changes'}],value:draft.mode});
  draft.teams=draft.teams||{};
  const team=draft.teams[agent]||(draft.teams[agent]={mode:'auto',partner:agent,executor_model:'',reviewer_model:'',planning:false});
  const teamMode=field('Team mode','team-mode',{options:[{value:'auto',label:'Auto · selected agent + separate review'},{value:'custom',label:'Custom team'}],value:team.mode});
  const reviewer=field('Review agent','review-agent',{options:providerOptions(),value:team.partner});
  const implementModel=field('Implementation model','implementation-model',{value:team.executor_model,placeholder:'Provider default'});
  const reviewModel=field('Review model','review-model',{value:team.reviewer_model,placeholder:'Provider default'});
  const modelList=el('datalist',{id:'implementation-models'},...arr(available.models).map(name=>el('option',{value:name})));
  implementModel.querySelector('input').setAttribute('list','implementation-models');
  const reviewList=el('datalist',{id:'review-models'});reviewModel.querySelector('input').setAttribute('list','review-models');
  let reviewOptionsVersion=0;
  async function loadReviewModels(){const version=++reviewOptionsVersion;try{const value=await api('/api/chat/options/'+team.partner);if(current()&&version===reviewOptionsVersion)reviewList.replaceChildren(...arr(value.models).map(name=>el('option',{value:name})));}catch(error){if(current())notice(error.message,true);}}
  const customTeam=el('div',{class:'team-fields'},el('p',{class:'hint'},'Implement with '+agent+'. Review uses a separate session, even with the same agent.'),reviewer,implementModel,reviewModel,modelList,reviewList);
  const planning=field('Task planning','task-planning',{options:[{value:'direct',label:'Direct · implement, test, review'},{value:'subtasks',label:'Plan subtasks · run each with separate sessions'}],value:team.planning?'subtasks':'direct'});
  const teamSummary=el('summary',{'aria-label':'Build team'},'Auto team');
  const teamSettings=el('details',{class:'chat-settings build-team'},teamSummary,teamMode,customTeam,planning,el('p',{class:'hint'},'After approval, the engine runs the selected team within task and usage limits. Subtasks run sequentially; this does not enable native CLI sub-agents.'));
  const teamDescription=()=>team.mode==='auto'?agent+' → '+agent+' review':agent+(team.executor_model?' / '+team.executor_model:'')+' → '+team.partner+(team.reviewer_model?' / '+team.reviewer_model:'');
  function updateTeam(){teamSummary.textContent=team.mode==='auto'?'Auto team · '+agent:'Team · '+teamDescription();teamSummary.title=teamDescription();customTeam.hidden=team.mode!=='custom';}
  teamMode.querySelector('select').addEventListener('change',event=>{team.mode=event.target.value;updateTeam();});
  reviewer.querySelector('select').addEventListener('change',event=>{team.partner=event.target.value;team.reviewer_model='';reviewModel.querySelector('input').value='';updateTeam();loadReviewModels();});
  implementModel.querySelector('input').addEventListener('input',event=>{team.executor_model=event.target.value.trim();updateTeam();});
  reviewModel.querySelector('input').addEventListener('input',event=>{team.reviewer_model=event.target.value.trim();updateTeam();});
  planning.querySelector('select').addEventListener('change',event=>{team.planning=event.target.value==='subtasks';});
  updateTeam();await loadReviewModels();if(!current())return;
  const teamInput=()=>({partner:team.mode==='custom'?team.partner:agent,planning:team.planning,model_overrides:team.mode==='custom'?{...(team.executor_model?{executor:team.executor_model,planner:team.executor_model}:{}),...(team.reviewer_model?{reviewer:team.reviewer_model}:{})}:{}});
  const consent=el('p',{class:'hint chat-consent'}),reviewArea=el('div',{'data-task-review':''});
  const limitPolicy=field('Usage limits','task-limits',{options:[{value:'unlimited',label:'No workspace cap'},{value:'limited',label:'Set workspace limits'}],value:team.budget_policy||'unlimited'});
  const limitCost=field('Total cost reservation','task-cost',{type:'number',min:0,step:.1,value:team.max_cost||3}),limitCall=field('Per-call reservation','task-call-cost',{type:'number',min:0,step:.01,value:team.max_call_cost||.25}),limitTime=field('Time limit (seconds)','task-time',{type:'number',min:1,value:team.max_seconds||3600});
  const limitValues=el('div',{},limitCost,limitCall,limitTime);limitValues.hidden=limitPolicy.querySelector('select').value!=='limited';
  const usageSettings=el('details',{},el('summary',{},'Optional usage limits'),limitPolicy,limitValues,el('p',{class:'hint'},'Workspace reservations are not a provider billing cap. Provider limits still apply.'));
  usageSettings.addEventListener('change',()=>{team.budget_policy=limitPolicy.querySelector('select').value;team.max_cost=Number(limitCost.querySelector('input').value);team.max_call_cost=Number(limitCall.querySelector('input').value);team.max_seconds=Number(limitTime.querySelector('input').value);limitValues.hidden=team.budget_policy!=='limited';});
  chatSettings.append(teamMode,customTeam,planning,usageSettings);
  const accessArea=el('div',{class:'project-access-settings'});
  function drawAccess(){accessArea.replaceChildren(el('p',{class:'hint'},projectAccess.enabled?'Project coding access: '+projectAccess.providers.join(', '):'Project coding access is off. Your first coding request will ask once.'),projectAccess.enabled?button('Revoke project access',async()=>{projectAccess=await api('/api/projects/'+project+'/access',{confirmed:true,enabled:false});drawAccess();updateMode();},'quiet'):button('Enable project coding',async()=>{projectAccess=await api('/api/projects/'+project+'/access',{confirmed:true,enabled:true,providers:Array.from(new Set([agent,team.mode==='custom'?team.partner:agent]))});drawAccess();},'primary'),el('p',{class:'hint'},'Enabling access permits the selected team to share project context, edit files and run commands for your coding requests, using your provider allowance.'));}
  chatSettings.append(el('details',{},el('summary',{},'Project access'),accessArea));drawAccess();
  chatSettings.addEventListener('input',scheduleDraft);chatSettings.addEventListener('change',scheduleDraft);
  const toolbar=el('div',{class:'chat-composer-toolbar'},modeField,chatSettings);
  async function sendBuild(input){
    const requested={...input,chat_id:selectedChat||null,confirmed:true};
    if(!draft.buildRequest||JSON.stringify(draft.buildRequest.input)!==JSON.stringify(requested))draft.buildRequest={input:requested,key:submissionKey()};
    pendingSubmission(project,{key:draft.buildRequest.key});
    const reply=await api('/api/tasks/submit',{...requested,idempotency_key:draft.buildRequest.key});
    pendingSubmission(project,null);selectedChat=reply.chat_id;selectedTaskId=reply.workflow_id;draft.newConversation=false;draft.content='';draft.buildRequest=null;await saveDraft();
    await refresh(false);if(current())await renderPage();
  }
  function requestProjectAccess(input){
    const names=Array.from(new Set([agent,input.partner||agent]));
    reviewArea.replaceChildren(panel('Allow coding in this project',el('p',{},projectAccess.root),el('p',{},'Allow '+names.join(' and ')+' to use project context, edit files and run commands for requests you send. Provider charges apply. Native CLI permissions still apply; commands are not sandboxed by the project directory.'),el('p',{class:'hint'},'Saved for this project. Revoke access in Agent settings. New providers require another approval.'),el('div',{class:'actions'},button('Allow project & send',async()=>{projectAccess=await api('/api/projects/'+project+'/access',{confirmed:true,enabled:true,providers:Array.from(new Set([...projectAccess.providers,...names]))});await sendBuild(input);},'primary'),button('Review this task only',async()=>{const proposal=await api('/api/tasks/preview',{...input,chat_id:selectedChat||null});renderTaskApproval(reviewArea,proposal,{...input,chat_id:selectedChat||null},current);},'quiet'),button('Cancel',()=>reviewArea.replaceChildren(),'quiet'))));
  }

  let responseRunning=false,transcriptLoaded=false,transcriptSignature='';
  const composer=form([messageField,toolbar,el('details',{class:'chat-access'},el('summary',{},'Access & usage · sends context using your provider allowance'),consent)],'Send',async data=>{
    draft.content=data.content;draft.mode=data.action;
    if(data.action==='ask'){
      const requested={project_id:project,provider:agent,content:data.content,chat_id:selectedChat||null,confirmed:true,model:options.model||null,effort:options.effort||null};
      // Preserve the exact identity across an ambiguous response. Do not turn retry into a second call.
      if(!draft.messageRequest||JSON.stringify(draft.messageRequest.input)!==JSON.stringify(requested))draft.messageRequest={input:requested,key:submissionKey()};
      pendingSubmission(project,{key:draft.messageRequest.key});
      const reply=await api('/api/tasks/message',{...draft.messageRequest.input,idempotency_key:draft.messageRequest.key});
      if(!current())return;
      pendingSubmission(project,null);selectedChat=reply.chat_id;draft.newConversation=false;draft.content='';draft.messageRequest=null;
      await saveDraft();await refresh(false);if(current())await renderPage();
    }else{
      const input={project_id:project,provider:agent,instruction:data.content,...teamInput(),budget_policy:team.budget_policy||'unlimited',...(team.budget_policy==='limited'?{max_cost:team.max_cost,max_call_cost:team.max_call_cost,max_seconds:team.max_seconds}:{})};
      if(options.model&&!input.model_overrides.executor){input.model_overrides.executor=options.model;input.model_overrides.planner=options.model;}
      if(options.effort)input.effort_overrides={executor:options.effort,planner:options.effort};
      projectAccess=await api('/api/projects/'+project+'/access');
      if(projectAccess.enabled&&[agent,input.partner].every(name=>projectAccess.providers.includes(name)))await sendBuild(input);
      else if(current()){requestProjectAccess(input);reviewArea.scrollIntoView({block:'nearest'});}
    }
  });
  composer.classList.add('chat-composer');
  messageField.querySelector('textarea').addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key==='Enter'&&!event.isComposing){event.preventDefault();if(!composer.querySelector('[type=submit]').disabled)composer.requestSubmit();}});
  teamSettings.append(button('Done',()=>{teamSettings.open=false;messageField.querySelector('textarea').focus();},'quiet'));
  chatSettings.append(button('Done',()=>{chatSettings.open=false;messageField.querySelector('textarea').focus();},'quiet'));
  customModel.querySelector('input').addEventListener('invalid',()=>{chatSettings.open=true;});
  const submit=composer.querySelector('[type=submit]');submit.disabled=unresolvedSubmission;toolbar.append(submit);
  teamSettings.addEventListener('input',()=>reviewArea.replaceChildren());teamSettings.addEventListener('change',()=>reviewArea.replaceChildren());
  function updateMode(){
    draft.mode=modeField.querySelector('select').value;
    teamMode.hidden=draft.mode!=='build';customTeam.hidden=draft.mode!=='build'||team.mode!=='custom';planning.hidden=draft.mode!=='build';customModel.querySelector('input').required=!customModel.hidden;
    submit.textContent='Send';
    composer.querySelector('.chat-access summary').textContent=draft.mode==='ask'?'Access & usage · sends context using your provider allowance':'Access & usage · project coding permissions';
    consent.textContent=draft.mode==='ask'?'Send authorizes this message and relevant project context to '+agent+', using your subscription allowance or API credits. This is a read-only conversation; native CLI access can be broader than filtered context.':'Send starts coding with saved project access, or asks you to enable access first. Busy projects queue follow-ups. Tests and a separate review session are included.';
    reviewArea.replaceChildren();
  }
  modeField.querySelector('select').addEventListener('change',()=>{updateMode();saveDraft().catch(error=>notice(error.message,true));});updateMode();
  messageField.querySelector('textarea').addEventListener('input',event=>{draft.content=event.target.value;scheduleDraft();reviewArea.replaceChildren();});
  const dock=el('div',{class:'chat-dock'},composer);main.append(dock,reviewArea);
  const cancel=button('Cancel response',async()=>{if(selectedChat)await api('/api/chats/'+selectedChat+'/cancel',{});await pollConversation();},'quiet');cancel.hidden=true;main.append(cancel);
const linkedTasks=el('div',{class:'conversation-tasks'}),liveTask=el('div',{class:'conversation-task-shell'}),liveDetail=el('div',{class:'conversation-task-detail'});liveTask.append(liveDetail);
  let linkedSignature='',openWorkflow='';
  async function pollConversation(){
    if(!current()||!selectedChat)return;
    try{
      const value=await api('/api/chats/'+selectedChat);if(!current())return;
      const linked=await api('/api/chats/'+selectedChat+'/tasks');if(!current())return;
      const visible=linked.find(w=>w.queue_state==='running'&&!['COMPLETED','CANCELLED','FAILED'].includes(w.status))||linked.at(-1);
      const linkSignature=JSON.stringify(linked);
      if(linkSignature!==linkedSignature){linkedSignature=linkSignature;linkedTasks.replaceChildren(...linked.filter(w=>w.id!==visible?.id).map(w=>el('div',{class:'actions'},button(w.objective+' · '+(w.queue_state==='queued'?'Queued':w.status.toLowerCase()),()=>{selectedTaskId=w.id;go('tasks');},'quiet'),w.queue_state==='queued'?button('Cancel queued task',async()=>{await api('/api/workflows/'+w.id+'/cancel',{});await pollConversation();},'quiet'):null)));}
      if(visible&&visible.id!==openWorkflow){openWorkflow=visible.id;inlineTask(liveDetail,visible.id,()=>current()&&openWorkflow===visible.id).catch(error=>notice(error.message,true));}
      const followLatest=!transcriptLoaded||(transcript.closest('.chat-stream')||transcript).scrollHeight-(transcript.closest('.chat-stream')||transcript).scrollTop-(transcript.closest('.chat-stream')||transcript).clientHeight<80;
      const nextSignature=JSON.stringify(value.messages);
      if(nextSignature!==transcriptSignature){
        const expanded=new Map(Array.from(transcript.children).map(node=>[node.dataset.messageId,Array.from(node.querySelectorAll('details')).map(d=>d.open)]));
        transcript.replaceChildren(...arr(value.messages).map(m=>chatMessage(m,agent)));
        for(const node of transcript.children){const saved=expanded.get(node.dataset.messageId);if(saved)Array.from(node.querySelectorAll('details')).forEach((d,i)=>{if(i<saved.length)d.open=saved[i];});}
        transcriptSignature=nextSignature;
      }
      if(!followLatest)latest.hidden=false;
      if(followLatest){const scroll=transcript.closest('.chat-stream')||transcript;scroll.scrollTop=scroll.scrollHeight;}
      for(const message of arr(value.messages)){
        const node=Array.from(transcript.children).find(n=>n.dataset.messageId===message.id),meter=node?.querySelector('.token-meter'),m=message.metadata||{};
        if(meter)meter.textContent=tokenUsageText(message.usage,m.output_received?message.content:'',m.provider_started_at,m.provider_finished_at);
      }
      transcriptLoaded=true;
      responseRunning=value.running;submit.disabled=responseRunning||unresolvedSubmission;cancel.hidden=!responseRunning;
      responseStatus.textContent=responseRunning?'Responding…':(['FAILED','TIMEOUT','INTERRUPTED','OUTPUT_LIMIT'].includes(value.status)?'Response '+value.status.toLowerCase()+'. Your conversation is saved. Inspect it before sending again.':'Conversation saved.');
      if(responseRunning||linked.length)workflowPollTimer=setTimeout(pollConversation,responseRunning?350:1200);
    }catch(error){if(current()){responseStatus.textContent='Connection lost. The outcome may be unknown; no message was resent.';workflowPollTimer=setTimeout(pollConversation,3000);}}
  }

  const stream=el('section',{class:'chat-stream','aria-label':'Conversation'},transcript,linkedTasks,liveTask,responseStatus,reviewArea);
  main.insertBefore(stream,dock);dock.append(cancel);
  const latest=button('Jump to latest',()=>{stream.scrollTop=stream.scrollHeight;latest.hidden=true;},'quiet jump-latest');
  latest.hidden=true;dock.prepend(latest);
  stream.addEventListener('scroll',()=>{latest.hidden=stream.scrollHeight-stream.scrollTop-stream.clientHeight<80;});
  await pollConversation();
  if(current()){stream.scrollTop=stream.scrollHeight;messageField.querySelector('textarea').focus({preventScroll:true});}

}
async function tasks(){
  const version=workflowViewVersion;
  document.body.classList.add('extension-chat','extension-tasks');
  main.append(el('div',{class:'task-tab-header'},chatTabs(),button('New task',()=>{if(selectedProject)taskDraft(selectedProject).mode='build';go('chat');},'primary')));
  if(projectNeeded())return;
  const project=selectedProject,current=()=>workflowViewVersion===version&&page==='tasks'&&selectedProject===project;
  const filter=field('Show tasks','task-filter',{options:[{value:'all',label:'All tasks'},{value:'active',label:'Active'},{value:'attention',label:'Needs attention'},{value:'done',label:'Completed'}]});
  const search=field('Find task','task-search',{placeholder:'Search task titles'});
  const list=el('div',{class:'task-list'}),detail=el('div',{class:'task-detail'}),feedback=el('p',{class:'hint'});
  const jump=button('Jump to latest',()=>{detail.scrollTop=detail.scrollHeight;jump.hidden=true;},'quiet');jump.hidden=true;
  detail.addEventListener('scroll',()=>{jump.hidden=detail.scrollHeight-detail.scrollTop-detail.clientHeight<80;});
  main.append(el('div',{class:'form-row tasks-toolbar'},projectPicker(()=>{selectedTaskId='';return renderPage();}),filter,search),feedback,el('div',{class:'tasks-layout'},list,el('div',{class:'task-detail-shell','data-task-progress':''},detail,jump)));
  let rows=[],opened='',signature='',timer;
  function draw(){
    const query=search.querySelector('input').value.toLowerCase(),mode=filter.querySelector('select').value;
    const shown=rows.filter(w=>(w.objective||'').toLowerCase().includes(query)&&(mode==='all'||mode==='active'&&['READY','RUNNING'].includes(w.status)||mode==='done'&&w.status==='COMPLETED'||mode==='attention'&&!['READY','RUNNING','COMPLETED','CANCELLED'].includes(w.status)));
    list.replaceChildren(...shown.map(w=>{const row=button((w.objective||'Task')+' · '+(w.queue_state==='queued'?'queued':w.status.toLowerCase().replaceAll('_',' ')),()=>{selectedTaskId=w.id;return openTask(w.id);},'list-button');row.dataset.workflowId=w.id;row.setAttribute('aria-current',String(w.id===selectedTaskId));return row;}));
    if(!shown.length)list.append(empty('No tasks here',query?'Try another search.':'Start a task from Chat.'));
    feedback.textContent=rows.length+' tasks in this project';
  }
  async function openTask(id){opened=id;for(const row of list.querySelectorAll('[data-workflow-id]'))row.setAttribute('aria-current',String(row.dataset.workflowId===id));detail.replaceChildren();await inlineTask(detail,id,()=>current()&&opened===id);}
  filter.querySelector('select').addEventListener('change',draw);search.querySelector('input').addEventListener('input',draw);
  async function pollList(){
    clearTimeout(timer);if(!current())return;
    try{const value=await api('/api/state');if(!current())return;rows=arr(value.workflows).filter(w=>w.project_id===project);
      const next=JSON.stringify(rows.map(w=>[w.id,w.status,w.objective,w.queue_state]));if(next!==signature){signature=next;draw();}
      if(selectedTaskId&&opened!==selectedTaskId&&rows.some(w=>w.id===selectedTaskId))await openTask(selectedTaskId);
    }catch(error){if(current())feedback.textContent='Connection interrupted. Your tasks remain saved.';}
    if(current())timer=setTimeout(pollList,3000);
  }
  await pollList();
}

function renderTaskApproval(container,initial,input,current){
  let proposal=initial,version=0,key=submissionKey(),timer;
  const card=panel('Review task'),error=el('p',{class:'error',role:'status'}),summary=el('div',{});
  const criteria=field('What should work when finished?','criteria',{multiline:true,value:initial.workflow.criteria.join('\n'),required:true});
  const total=field('Total usage reservation','max_cost',{type:'number',min:0,step:.01,value:initial.workflow.budgets.max_cost});
  const perCall=field('Per-call reservation','max_call_cost',{type:'number',min:0,step:.01,value:initial.max_call_cost});
  const reviewModel=field('Reviewer model','reviewer_model',{options:[{value:'',label:'Provider default'},...(input.model_overrides?.reviewer?[input.model_overrides.reviewer]:[]),{value:'custom',label:'Custom model…'}],value:input.model_overrides?.reviewer||''});
  const customReviewModel=field('Custom reviewer model','custom_reviewer_model',{placeholder:'Exact model ID'});customReviewModel.hidden=true;
  const advanced=el('details',{},el('summary',{},'Advanced task options'),
    field('Reviewer','partner',{options:providerOptions(),value:input.partner||input.provider}),reviewModel,customReviewModel,
    field('Planning','planning',{options:[{value:'no',label:'Direct implementation'},{value:'yes',label:'Plan multiple steps first'}],value:input.planning?'yes':'no'}));
  const cancelPreview=button('Cancel',()=>{clearTimeout(timer);version++;proposal=null;container.replaceChildren();main.querySelector('textarea[name=content]')?.focus({preventScroll:true});},'quiet');
  const start=button('Approve & start',async()=>{
    if(!current()||!container.isConnected||!proposal||proposal.blockers.length)return;
    pendingSubmission(input.project_id,{key});
    let result;cancelPreview.disabled=true;
    try{result=await api('/api/tasks/start',{proposal_id:proposal.proposal_id,revision:proposal.revision,confirmed:true,idempotency_key:key});}finally{cancelPreview.disabled=false;}
    if(!current())return;
    pendingSubmission(input.project_id,null);selectedTaskId=result.workflow_id;const draft=taskDraft(input.project_id);draft.content='';
    if(result.chat_id){selectedChat=result.chat_id;draft.newConversation=false;experience=await api('/api/experience',{project:input.project_id,agent:input.provider,conversation:result.chat_id});}
    await api('/api/projects/'+input.project_id+'/draft',Object.fromEntries(['content','mode','teams','chatOptions','newConversation'].filter(k=>draft[k]!==undefined).map(k=>[k,draft[k]])));
    await refresh(false);if(current()){if(result.chat_id)await renderPage();else go('tasks');}
    if(result.notice)notice(result.notice);
  },'primary');
  function selectedReviewModel(){
    const choice=reviewModel.querySelector('select').value,value=choice==='custom'?customReviewModel.querySelector('input').value.trim():choice;
    if(choice==='custom'&&!value)throw new Error('Enter a custom reviewer model or choose Provider default.');
    return value;
  }
  const read=()=>({...input,budget_policy:allowance.querySelector('select').value==='unlimited'?'unlimited':'limited',max_seconds:Number(timeLimit.querySelector('input').value),criteria:criteria.querySelector('textarea').value,
    max_cost:Number(total.querySelector('input').value),max_call_cost:Number(perCall.querySelector('input').value),
    partner:advanced.querySelector('[name=partner]').value,model_overrides:Object.fromEntries(Object.entries({...input.model_overrides,reviewer:selectedReviewModel()}).filter(([,value])=>value)),planning:advanced.querySelector('[name=planning]').value==='yes',command_mode:'agent'});
  function show(){
    const models=Object.entries(proposal.workflow.model_overrides||{}).map(([role,model])=>role+' = '+model).join(' · ');
    summary.replaceChildren(el('p',{class:'build-objective'},proposal.workflow.objective),
      el('p',{},input.provider+' implements → '+proposal.workflow.providers.reviewer+' reviews'),
      el('p',{class:'hint'},proposal.review),...(models?[el('p',{class:'hint'},'Models: '+models)]:[]),
      el('p',{class:'build-checks'},'AI chooses commands and checks for this task. Results and command output appear live in Tasks.'),
      el('p',{class:'hint'},'Approving lets this team share project context, change files and choose/run project commands on this machine using your provider allowance.'),
      el('p',{class:'hint'},proposal.workflow.budget_policy==='unlimited'?'No workspace token, cost, time or provider-call cap. Provider limits and charges still apply.':'Workspace usage limits are enabled for this task.'),
      el('details',{},el('summary',{},'Access details'),pre(proposal.approvals)));
    error.textContent=proposal.blockers.join(' ');start.disabled=Boolean(proposal.blockers.length);
  }
  function schedule(){
    clearTimeout(timer);const revision=++version;proposal=null;start.disabled=true;error.textContent='Updating task preview…';
    timer=setTimeout(async()=>{try{const value=await api('/api/tasks/preview',read());if(!current()||!container.isConnected||revision!==version)return;proposal=value;key=submissionKey();show();}catch(err){if(current()&&revision===version){error.textContent=err.message;start.disabled=true;}}},250);
  }
  let modelsVersion=0;
  async function loadReviewerModels(){
    const request=++modelsVersion,provider=advanced.querySelector('[name=partner]').value;
    try{const data=await api('/api/chat/options/'+provider);if(!current()||!container.isConnected||request!==modelsVersion)return;
      const select=reviewModel.querySelector('select'),value=select.value;
      select.replaceChildren(el('option',{value:''},'Provider default'),...Array.from(new Set([...arr(data.models),...(value&&value!=='custom'?[value]:[])])).map(model=>el('option',{value:model},model)),el('option',{value:'custom'},'Custom model…'));select.value=value;
    }catch{if(current()&&request===modelsVersion)reviewModel.append(el('p',{class:'hint'},'Model list unavailable. Use provider default or a custom model ID.'));}
  }
  reviewModel.querySelector('select').addEventListener('change',()=>{customReviewModel.hidden=reviewModel.querySelector('select').value!=='custom';});
  advanced.querySelector('[name=partner]').addEventListener('change',()=>{reviewModel.querySelector('select').value='';customReviewModel.querySelector('input').value='';customReviewModel.hidden=true;loadReviewerModels();});
  const timeLimit=field('Task time limit (seconds)','max_seconds',{type:'number',min:1,value:initial.workflow.budgets.max_seconds});
  const savedAllowance=initial.workflow.budgets.max_cost>0&&initial.max_call_cost>0&&initial.max_call_cost<=initial.workflow.budgets.max_cost;
  const allowance=field('Usage allowance','usage-preset',{options:[{value:'unlimited',label:'No workspace usage limit (default)'},{value:'',label:'Choose a limit…'},...(savedAllowance?[{value:'saved',label:'Use previous allowance ('+initial.workflow.budgets.max_cost+' total / '+initial.max_call_cost+' per call)'}]:[]),{value:'small',label:'Small task · 1 total / 0.10 per call'},{value:'standard',label:'Larger task · 3 total / 0.25 per call'},{value:'custom',label:'Custom allowance…'}],value:initial.workflow.budget_policy==='unlimited'?'unlimited':savedAllowance?'saved':''});
  const customAllowance=el('div',{class:'form-row',hidden:true},total,perCall,timeLimit);
  allowance.querySelector('select').addEventListener('change',event=>{
    const choice=event.target.value;customAllowance.hidden=choice!=='custom';
    const values=choice==='small'?[1,.1]:choice==='standard'?[3,.25]:choice==='saved'?[initial.workflow.budgets.max_cost,initial.max_call_cost]:choice===''?[0,0]:null;
    if(values){total.querySelector('input').value=values[0];perCall.querySelector('input').value=values[1];}
  });
  card.classList.add('simple-build-card');
  card.append(summary,el('details',{},el('summary',{},'Optional usage limits'),allowance,customAllowance,el('p',{class:'hint'},'Optional workspace limits; provider billing and model context limits still apply. Preferences are remembered, permissions are per task.')),
    el('details',{},el('summary',{},'Edit expected outcome'),criteria),advanced,error,
    el('div',{class:'actions'},start,cancelPreview,button('Just ask · no file changes',()=>{taskDraft(input.project_id).mode='ask';return renderPage();},'quiet')));
  card.addEventListener('input',schedule);card.addEventListener('change',event=>{if(event.target.tagName==='SELECT')schedule();});
  container.replaceChildren(card);show();loadReviewerModels();
}
function commandOutput(text){
  const value=String(text);if(value.length<=1600&&value.split('\n').length<=20)return pre(value);
  return el('details',{class:'task-event-output'},el('summary',{},'Expand output · '+value.split('\n').length+' lines'),el('p',{class:'path'},value.slice(0,240)+'…'),pre(value));
}
function renderAgentOutput(text,command=false){
  if(command)return commandOutput(text);
  try{
    const data=JSON.parse(text),body=el('div',{class:'agent-readable-output'});
    if(Array.isArray(data.tasks))for(const task of data.tasks)body.append(el('h3',{},task.title||'Task'),el('p',{},task.description||''));
    else if(data.summary||data.rationale)body.append(chatMarkdown(data.summary||data.rationale));
    else return chatMarkdown(text);
    body.append(el('details',{},el('summary',{},'Structured response'),pre(JSON.stringify(data,null,2))));return body;
  }catch{return chatMarkdown(text);}
}
async function inlineTask(container,id,current){
  const card=panel('Task progress'),status=el('p',{role:'status',class:'task-status'}),details=el('div',{}),requests=el('div',{}),result=el('div',{});
  let timer,signature='',loadedResults=false,firstRender=true,lastResultsAt=0,timelineLimit=30;
  const timeline=el('section',{class:'task-live-output','aria-label':'Live output'});let timelineHeader=null,eventCursor=0;const eventCache=new Map();
  const controls=el('div',{class:'actions'},button('Pause task',async()=>{await api('/api/workflows/'+id+'/pause',{});await poll();},'quiet'),button('Cancel task',async()=>{await api('/api/workflows/'+id+'/cancel',{});await poll();},'danger'));
  const meter=el('p',{class:'hint token-meter',title:'Current or latest provider call. Rates are averages over elapsed call time, not instantaneous billing or hardware throughput. Visible output estimates exclude hidden reasoning and tool output.'});
  const pinned=el('div',{class:'task-run-controls'},status,controls,meter);
  container.parentElement.querySelector('.task-run-controls')?.remove();container.parentElement.prepend(pinned);
  card.append(details,requests,result);container.replaceChildren(card);
  const alive=()=>current()&&card.isConnected&&!container.closest('[hidden]');
  async function poll(){
    clearTimeout(timer);if(!alive())return;
    try{
      const update=await api('/api/tasks/'+id+'/updates',{cursor:eventCursor});if(!alive())return;
      if(update.reset)eventCache.clear();for(const event of update.events)eventCache.set(event.id,event);eventCursor=update.cursor;
      const w={...update.state,events:Array.from(eventCache.values()).sort((a,b)=>a.id-b.id)};
      meter.textContent=workflowTokenUsage(w);
      const scroll=container.closest('.chat-stream')||container;
      const follow=firstRender||scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<80;
      const scrollTop=scroll.scrollTop;
      const active=w.runner_active||w.status==='RUNNING',queued=w.queue_state==='queued';
      for(const item of main.querySelectorAll('[data-workflow-id]'))if(item.dataset.workflowId===id)item.textContent=(w.objective||'Task')+' · '+(w.queue_state==='queued'?'queued':w.status.toLowerCase().replaceAll('_',' '));
      const phases=arr(w.tasks).map(t=>t.status);
      const stage=w.status==='COMPLETED'?(arr(w.tasks).some(t=>t.evidence?.tests?.verification_mode==='review_only')?'Done · file review verified; no automated tests':'Done · tests and review verified'):w.status==='CANCELLED'?'Cancelled':w.status!=='RUNNING'?'Needs attention · '+w.status.toLowerCase().replaceAll('_',' '):phases.includes('REVIEWING')?'Reviewing':phases.includes('TESTING')?'Testing':'Working';
      status.textContent=(queued?'Queued · waiting for this project or an available runner':stage)+(w.queue_reason?' — '+w.queue_reason:w.reason?' — '+w.reason:'');
      if(page==='tasks'&&w.chat_id&&!pinned.querySelector('[data-open-conversation]'))pinned.append(button('Open conversation',async()=>{selectedChat=w.chat_id;selectedProject=w.project_id;taskDraft(w.project_id).newConversation=false;const c=await api('/api/chats/'+w.chat_id);experience=await api('/api/experience',{project:w.project_id,agent:c.provider,conversation:w.chat_id});go('chat');},'quiet'));
      pinned.querySelectorAll('button').forEach(b=>{if(b.textContent==='Open conversation')b.setAttribute('data-open-conversation','');});controls.hidden=['COMPLETED','CANCELLED','FAILED'].includes(w.status);controls.querySelector('button').hidden=!active;
      const next=JSON.stringify([w.status,w.reason,w.queue_state,w.queue_reason,w.budget_policy,w.approval_requests,w.pending_actions,w.approvals,w.tasks,w.events]);
      if(next!==signature){
        const expanded=new Map(Array.from(details.querySelectorAll('details')).map(d=>[(d.closest('[data-output-id]')?.dataset.outputId||'meta')+':'+d.querySelector('summary')?.textContent,d.open]));
        const outputScroll=new Map(Array.from(details.querySelectorAll('[data-output-id]')).map(node=>{const p=node.querySelector('pre');return[node.dataset.outputId,p?{top:p.scrollTop,bottom:p.scrollHeight-p.scrollTop-p.clientHeight<40}:null];}));
        signature=next;details.replaceChildren(el('details',{class:'task-overview'},el('summary',{},w.objective),el('p',{class:'hint'},'Working → Testing → Reviewing → Done')));
        details.querySelector('.task-overview').append(el('details',{},el('summary',{},'Team & subtasks · '+arr(w.tasks).length),...arr(w.tasks).map(task=>el('div',{class:'item'},el('strong',{},task.title),el('p',{class:'hint'},task.executor+' / '+(w.model_overrides?.executor||'default model')+' → '+task.reviewer+' / '+(w.model_overrides?.reviewer||'default model')+' · '+task.status)))));
        const allOutput=arr(w.events).filter(e=>(e.event==='PROVIDER_EVENT'&&['text','activity'].includes(e.data?.type))||e.event==='COMMAND_OUTPUT');
        const outputEvents=allOutput.slice(-timelineLimit);
        if(outputEvents.length){
          if(!timelineHeader){timelineHeader=el('h3',{},'Live output');timeline.append(timelineHeader,el('p',{class:'hint'},'Live agent activity'));}
          timelineHeader.textContent=active?'Live output':'Agent output';
          timeline.querySelector('[data-earlier]')?.remove();
          if(allOutput.length>timelineLimit){const earlier=button('Show earlier activity',()=>{timelineLimit+=30;signature='';return poll();},'quiet');earlier.dataset.earlier='';timeline.insertBefore(earlier,timelineHeader.nextSibling);}
          const retained=new Set(outputEvents.map(e=>String(e.id)));
          for(const node of timeline.querySelectorAll('[data-output-id]'))if(!retained.has(node.dataset.outputId))node.remove();
          let previous=null;
          for(const e of outputEvents){
            let node=Array.from(timeline.querySelectorAll('[data-output-id]')).find(n=>n.dataset.outputId===String(e.id));
            if(!node){node=el('article',{'data-output-id':String(e.id)});if(previous)previous.after(node);else timeline.insertBefore(node,timeline.querySelector('article'));}
            const eventSignature=JSON.stringify(e.data);
            if(node._eventSignature!==eventSignature){
              const opened=Array.from(node.querySelectorAll('details')).map(d=>d.open);
              node.replaceChildren(el('strong',{},(e.data.provider||'Agent')+' · '+(e.data.label||e.data.role||'Output')+(e.data.phase?' · '+e.data.phase:'')),
                e.data.detail?el('code',{},e.data.detail):'',e.data.text?renderAgentOutput(e.data.text,e.event==='COMMAND_OUTPUT'):'',
                e.data.output?commandOutput(e.data.output):'',e.data.exit_code!=null?el('p',{class:'hint'},'Exit code: '+e.data.exit_code):'');
              Array.from(node.querySelectorAll('details')).forEach((d,i)=>{if(opened[i])d.open=true;});node._eventSignature=eventSignature;
            }
            previous=node;
          }
          details.append(timeline);
        }else details.append(el('p',{class:'hint'},queued?'Queued. This project is busy or a runner is not available.':'Working; no new visible output yet.'));
        for(const d of details.querySelectorAll('details')){const key=(d.closest('[data-output-id]')?.dataset.outputId||'meta')+':'+d.querySelector('summary')?.textContent;if(expanded.has(key))d.open=expanded.get(key);}
        for(const node of details.querySelectorAll('[data-output-id]')){const p=node.querySelector('pre'),saved=outputScroll.get(node.dataset.outputId);if(p)p.scrollTop=!saved||saved.bottom?p.scrollHeight:saved.top;}
        requests.replaceChildren();
        for(const request of arr(w.approval_requests).filter(r=>r.status==='PENDING'))requests.append(panel('Additional permission',el('p',{},request.reason),pre(request.scope),button('Approve this scope',async()=>{await api('/api/workflows/'+id+'/resolve-request',{request_id:request.id,decision:'approve'});await poll();},'primary'),button('Deny',async()=>{await api('/api/workflows/'+id+'/resolve-request',{request_id:request.id,decision:'deny'});await poll();},'quiet')));
        if(!active)for(const action of arr(w.pending_actions)){
          const approved=arr(w.approvals).some(a=>!a.revoked&&a.kind==='recovery'&&a.scope.action_id===action.id);
          requests.append(panel('Inspect interrupted action',el('p',{},action.provider+' · '+action.role),el('p',{class:'hint'},'This action may already have changed files. Inspect the diff and provider history before allowing a retry.'),pre({action_id:action.id,state:action.state}),approved?el('p',{},'Recovery permission recorded. Resume only when ready.'):button('I inspected; allow retry of this action',async()=>{await api('/api/workflows/'+id+'/approve',{kind:'recovery',scope:{action_id:action.id,decision:'retry'}});await poll();},'primary')));
        }
        if(!active&&!queued&&!['COMPLETED','CANCELLED','FAILED'].includes(w.status)){
          const limitsEditor=el('details',{},el('summary',{},'Usage limits · '+(w.budget_policy==='unlimited'?'off':'on')));
          limitsEditor.append(form([
            field('Limit policy','policy',{options:[{value:'unlimited',label:'No workspace usage limit'},{value:'limited',label:'Set workspace limits'}],value:w.budget_policy||'limited'}),
            el('details',{},el('summary',{},'Custom limit values'),
              field('Total cost reservation','max_cost',{type:'number',min:0,step:.01,value:w.budgets.max_cost||1}),
              field('Per-call cost reservation','max_call_cost',{type:'number',min:0,step:.01,value:.1}),
              field('Time limit (seconds)','max_seconds',{type:'number',min:1,value:w.budgets.max_seconds}))
          ],'Save limits',async data=>{await api('/api/workflows/'+id+'/limits',{confirmed:true,policy:data.policy,budgets:data.policy==='limited'?{max_cost:Number(data.max_cost),max_seconds:Number(data.max_seconds)}:{},max_call_cost:Number(data.max_call_cost)});await poll();}));
          requests.append(limitsEditor);
          if(w.status==='BUDGET_EXHAUSTED'&&w.budget_policy!=='unlimited'&&!arr(w.pending_actions).length)requests.append(
            el('p',{class:'hint'},'This task stopped at a workspace usage limit. Remove it to continue; provider charges and limits still apply.'),
            button('Remove usage limits & resume',async()=>{await api('/api/workflows/'+id+'/limits',{confirmed:true,policy:'unlimited'});await api('/api/workflows/'+id+'/retry',{});loadedResults=false;await poll();},'primary'));
        }
        if(!active&&!queued&&!['COMPLETED','CANCELLED','FAILED'].includes(w.status)&&!(w.status==='BUDGET_EXHAUSTED'&&w.budget_policy!=='unlimited'&&!arr(w.pending_actions).length))requests.append(el('p',{class:'hint'},'Inspect changes before continuing. Unknown effects are never retried automatically.'),button('Resume task',async()=>{try{await api('/api/workflows/'+id+'/retry',{});}catch(error){notice(error.message,true);}loadedResults=false;await poll();},'primary'),el('details',{},el('summary',{},'Permission details'),approvalForm(id,poll)));
      }
      if((!active&&!loadedResults)||(active&&Date.now()-lastResultsAt>3000)){
        const comparison=await api('/api/tasks/'+id+'/results');if(!alive())return;loadedResults=!active;lastResultsAt=Date.now();
        const openDiff=new Set(Array.from(result.querySelectorAll('details[open]')).map(d=>d.querySelector('summary')?.textContent));
        result.replaceChildren(panel(active?'Changes so far':'Results',el('p',{},w.status==='COMPLETED'?(arr(w.tasks).some(t=>t.evidence?.tests?.verification_mode==='review_only')?'Files were independently reviewed. Some steps had no automated tests; see the verification evidence.':'Requested work passed the recorded tests and separate review.'):active?'Work is in progress. Changes below refresh while the agent works.':'Work is not verified complete.'),el('p',{class:'hint'},comparison.notice),comparison.launch_error?el('p',{class:'error'},comparison.launch_error):null,
          ...(comparison.summary?[el('h3',{},'Agent summary'),chatMarkdown(comparison.summary)]:[]),el('h3',{},'Files changed since start'),comparison.files?.length?el('ul',{},comparison.files.map(f=>el('li',{},f))):el('p',{},'No recorded changes.'),
          el('details',{},el('summary',{},'Existing changes before this task'),pre(comparison.preexisting||[])),
          el('details',{},el('summary',{},'View diff'),pre(comparison.diff||'No displayable text diff.')),
          ...arr(w.tasks).map(t=>el('details',{},el('summary',{},t.title+' · test and review evidence'),pre(t.evidence||{})))));
        if(active){const content=result.firstElementChild;result.replaceChildren(el('details',{},el('summary',{},'Live file changes'),content));}
        for(const d of result.querySelectorAll('details'))if(openDiff.has(d.querySelector('summary')?.textContent))d.open=true;
      }
      if(follow)scroll.scrollTop=scroll.scrollHeight;else scroll.scrollTop=scrollTop;
      firstRender=false;
      if(active||queued||update.more)timer=setTimeout(poll,update.more?0:active?350:1000);
    }catch(error){if(alive()){status.textContent='Connection interrupted. Saved task state will be checked; no work is repeated.';timer=setTimeout(poll,3000);}}
  }
  await poll();
}
