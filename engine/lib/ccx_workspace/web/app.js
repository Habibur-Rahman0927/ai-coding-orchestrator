'use strict';
let fieldSequence = 0, workflowViewVersion = 0, workflowPollTimer = null;
let token = '', csrf = sessionStorage.getItem('ccx-session-proof') || '', authenticated = false, state = {}, setupState = {}, page = 'overview', selectedProject = '', selectedWorkflow = '', selectedChat = '';
// Consume the fragment before any network request; a bootstrap secret never remains in history.
let bootstrapCredential = new URLSearchParams(location.hash.slice(1)).get('bootstrap');
if (bootstrapCredential) history.replaceState(null, '', location.pathname);
const main = document.getElementById('main');
const pages = [['overview','Overview','◈'],['chat','Chat','◌'],['projects','Projects','▣'],['memory','Memory','▤'],['context','Context','◎'],['workflows','Workflows','◇'],['providers','Providers','⊞'],['sessions','Sessions','◷'],['approvals','Approvals','✓'],['activity','Activity & usage','◷'],['settings','Settings','⚙']];
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
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache:'no-store', credentials:'same-origin', headers: {...(token?{'Authorization':'Bearer '+token}:{}), ...(csrf?{'X-CSRF-Token':csrf}:{}), ...(body !== undefined ? {'Content-Type':'application/json'} : {})}, ...(body !== undefined ? {body:JSON.stringify(body)} : {})});
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
function projectOptions(){return arr(state.projects).map(p=>({value:p.id,label:p.name||p.path||p.id}));}
function projectPicker(action){const f=field('Project','active-project',{options:projectOptions(),value:selectedProject});f.querySelector('select').addEventListener('change',async event=>{selectedProject=event.target.value;try{await action();}catch(error){notice(error.message,true);}});return f;}
function projectNeeded(){if(!arr(state.projects).length){main.append(empty('Start with a project','Register a local project in Projects to index files, manage memory, and assemble context.'));return true;}if(!selectedProject||!state.projects.some(p=>p.id===selectedProject))selectedProject=state.projects[0].id;return false;}
async function refresh(render=true){state=await api('/api/state');setupState=await api('/api/setup');document.getElementById('updated').textContent='Updated '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});if(render)await renderPage();}
function go(name){location.hash=name;if(page===name)renderPage().catch(error=>notice(error.message,true));}
async function renderPage(){document.getElementById('notice').hidden=true;clearTimeout(workflowPollTimer);workflowViewVersion++;page=location.hash.slice(1)||'overview';if(!setupState.completed && page==='overview')page='setup';if(!pages.some(x=>x[0]===page)&&page!=='setup')page='overview';document.getElementById('breadcrumb').textContent='Workspace / '+(page==='setup'?'Setup':pages.find(x=>x[0]===page)[1]);for(const a of document.querySelectorAll('nav a'))a.setAttribute('aria-current',a.hash==='#'+page?'page':'false');main.replaceChildren();await ({overview,projects,memory,context,workflows,providers,activity,settings,setup,chat,sessions,approvals}[page])();}
function overview(){const projects=arr(state.projects),flows=arr(state.workflows),available=arr(state.providers).filter(p=>p.available);main.append(heading('Your work, in view.','Keep project knowledge close and coordinate agent work with explicit boundaries.'),el('div',{class:'metrics'},...[[projects.length,'Registered projects'],[flows.length,'Workflows'],[arr(state.running).length,'Active runners'],[available.length,'Locally available providers']].map(([n,label])=>el('div',{class:'metric'},el('p',{},label),el('strong',{class:'number'},n)))));const recent=panel('Projects',projects.length?projects.slice(0,4).map(p=>el('div',{class:'item'},el('h3',{},projectName(p)),el('p',{class:'path'},p.path||p.root),button('Open project',()=>{selectedProject=p.id;go('memory');},'quiet'))):empty('A clear place to begin','Register a local repository to build its project index.'),el('div',{class:'actions'},button('Manage projects',()=>go('projects'),'primary')));const flowsPanel=panel('Workflow queue',flows.length?flows.slice(0,4).map(w=>el('div',{class:'item'},el('h3',{},w.objective||w.id),statusTag(w.status||w.state),el('div',{class:'actions'},button('View workflow',()=>{selectedWorkflow=w.id;go('workflows');},'quiet')))):empty('No workflows yet','Define an objective and success criteria. Agent execution starts only when you run it.'));main.append(el('div',{class:'grid'},recent,flowsPanel),panel('This machine',el('p',{class:'muted'},'Machine information is local context. Refresh it when tools or the environment change.'),machineSummary(state.machine)));}
async function memory(){main.append(heading('Project memory','Inspect stored knowledge, search the project index, and remove records you no longer want.'));if(projectNeeded())return;main.append(projectPicker(memoryReload));await memoryReload();}
async function memoryReload(){document.getElementById('memory-content')?.remove();const container=el('div',{id:'memory-content'});main.append(container);const rows=arr(await api('/api/projects/'+selectedProject+'/memories'));const result=el('div',{});container.append(panel('Add a memory',form([field('Title','title',{required:true}),field('Instruction or note','body',{required:true,multiline:true}),field('Scope','scope',{options:['project','workflow','session','error','verification','skills','temporary']})],'Save memory',async data=>{await api('/api/projects/'+selectedProject+'/remember',data);await memoryReload();notice('Memory saved as a user instruction.');})),panel('Search knowledge',form([field('Search query','query',{required:true,placeholder:'Where is authentication configured?'}),field('Scope','scope',{placeholder:'Optional scope'})],'Search',async data=>{const found=await api('/api/projects/'+selectedProject+'/search',{query:data.query,scope:data.scope||null,limit:20});result.replaceChildren(pre(found));}),result),panel('Stored records',el('div',{class:'section-head'},el('p',{class:'muted'},rows.length+' memory records'),button('Export project memory',async()=>download(await api('/api/projects/'+selectedProject+'/export'),'project-memory.json'))),rows.length?rows.map(row=>el('article',{class:'item'},el('h3',{},row.title||row.key||row.kind||row.id),el('p',{class:'hint'},row.scope||row.source||'Project memory'),pre(row.body||row.content||row.value||row),button('Delete record',async()=>{if(!confirm('Delete this memory record? This cannot be undone here.'))return;await api('/api/projects/'+selectedProject+'/delete-memory',{id:row.id});await memoryReload();notice('Memory record deleted.');},'danger'))):empty('No memory records','Indexing and workflow activity can provide project knowledge. Search the index above.')));}
function context(){main.append(heading('Build useful context','Retrieve relevant project knowledge within an explicit budget. Critical instructions stay visible in the request.'));if(projectNeeded())return;const result=el('div',{});main.append(projectPicker(async()=>result.replaceChildren()),panel('Context request',form([field('What are you working on?','query',{required:true,multiline:true,placeholder:'Describe the task or question to ground in this project.'}),el('div',{class:'form-row'},field('Context budget','budget',{type:'number',value:2000,min:100,max:32000}),field('Critical instructions, one per line','critical',{multiline:true,placeholder:'Keep these instructions in the assembled context.'}))],'Assemble context',async data=>{const value=await api('/api/projects/'+selectedProject+'/context',{query:data.query,budget:Number(data.budget),critical:data.critical.split('\n').filter(x=>x.trim())});result.replaceChildren(panel('Assembled context',pre(value),button('Download context',()=>download(value,'context.json'))));})),result);}
async function workflows(){
  main.append(heading('Workflows','Choose a project, agent roles, and a verifiable objective. Creating a task never starts a provider call.'));
  if(projectNeeded())return;
  const d=defaults();
  const create=el('details',{open:!arr(state.workflows).length},el('summary',{},'Start a task'),form([
    field('Project','project_id',{options:projectOptions(),value:selectedProject}),
    field('What should be done?','objective',{required:true,multiline:true}),
    field('How will we verify it? One criterion per line','criteria',{required:true,multiline:true}),
    el('div',{class:'grid three'},field('Orchestrator','planner',{options:providerOptions(),value:d.planner}),field('Executor','executor',{options:providerOptions(),value:d.executor}),field('Reviewer','reviewer',{options:providerOptions(),value:d.reviewer})),
    el('div',{class:'form-row'},field('Spending reservation limit','max_cost',{type:'number',value:d.max_cost,min:0,step:.01,hint:'Zero blocks live calls. A positive limit still requires provider spending approval.'}),field('Token budget','max_tokens',{type:'number',value:d.max_tokens,min:128})),
    el('div',{class:'form-row'},field('Context budget','context_budget',{type:'number',value:d.context_budget,min:128,max:32000}),field('Maximum duration (seconds)','max_seconds',{type:'number',value:d.max_seconds,min:1,max:86400})),
    el('details',{},el('summary',{},'Optional execution policy and model overrides'),
      field('Execution policy','execution_policy',{options:[{value:'standard',label:'Plan, implement, test, and independently review'},{value:'single_task',label:'Single task: skip planning, retain tests and review'}],hint:'A single task avoids the planning call. Your selected provider roles are preserved.'}),
      field('Orchestrator model override','planner_model',{placeholder:'Inherit application or provider default'}),
      field('Executor model override','executor_model',{placeholder:'Inherit application or provider default'}),
      field('Reviewer model override','reviewer_model',{placeholder:'Inherit application or provider default'}))
  ],'Create workflow',async data=>{
    const value=await api('/api/workflows',{project_id:data.project_id,objective:data.objective,criteria:data.criteria.split('\n').filter(x=>x.trim()),budgets:{max_cost:Number(data.max_cost),max_tokens:Number(data.max_tokens),max_context_tokens:Number(data.context_budget),max_seconds:Number(data.max_seconds)},providers:{planner:data.planner,executor:data.executor,reviewer:data.reviewer},execution_policy:data.execution_policy,model_overrides:Object.fromEntries(['planner','executor','reviewer'].filter(role=>data[role+'_model']?.trim()).map(role=>[role,data[role+'_model'].trim()]))});
    selectedWorkflow=value.id;await refresh();notice('Workflow created. Review its approvals before starting.');
  }));
  main.append(panel('',create));const flows=arr(state.workflows);
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

async function activity(){main.append(heading('Activity & usage','Inspect workflow history and recorded usage. Missing provider usage is shown as unreported, never estimated as zero.'));const flows=arr(state.workflows);if(!flows.length){main.append(empty('No activity yet','Workflow events and usage appear after you create and run work.'));return;}for(const item of flows){const w=await api('/api/workflows/'+item.id);main.append(panel(item.objective||item.id,statusTag(w.status||w.state),el('h3',{},'Usage and budgets'),pre({usage:w.usage??'Unreported',budgets:w.budgets??'Unreported'}),el('details',{},el('summary',{},'Events ('+arr(w.events).length+')'),pre(w.events||[])),button('Open workflow',()=>{selectedWorkflow=item.id;go('workflows');},'quiet')));}}
function settings(){
  const diagnostics=el('div',{});
  main.append(heading('Workspace settings','Manage onboarding, session security, and local diagnostics.'),
    panel('Getting started',el('p',{class:'muted'},'Reopen the setup wizard to inspect tools and change application defaults. Existing provider login stays untouched.'),button('Reopen setup',async()=>{await api('/api/setup',{step:1});await refresh(false);go('setup');},'primary')),
    el('div',{class:'grid'},panel('Connection & privacy',el('dl',{class:'data-list'},el('dt',{},'Network'),el('dd',{},'IPv4 loopback only'),el('dt',{},'Authentication'),el('dd',{},token?'Manual token in tab memory':'Expiring local browser session'),el('dt',{},'Cross-origin access'),el('dd',{},'Refused')),button('Sign out',disconnect,'danger'),button('Rotate browser credentials',async()=>{if(!confirm('Invalidate all dashboard sessions? Reopen the workspace from its startup command to sign in again.'))return;await api('/api/auth/rotate',{});await disconnect();},'quiet')),
    panel('Machine context',button('Refresh machine information',async()=>{state.machine=await api('/api/machine/refresh',{});await renderPage();}),machineSummary(state.machine))),
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
for(const [name,label,icon]of pages)document.getElementById('navigation').append(el('a',{href:'#'+name},el('span',{class:'nav-icon','aria-hidden':'true'},icon),label));
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
function providerStatus(p){return String(p.connection_status||p.status||(p.available?'Authentication unknown':'Unavailable')).replaceAll('_',' ');}
async function setup(){
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
      el('div',{class:'form-row'},field('Context budget (estimated tokens)','context_budget',{type:'number',min:128,max:32000,value:d.context_budget}),field('Token budget','max_tokens',{type:'number',min:128,value:d.max_tokens})),
      el('div',{class:'form-row'},field('Spending reservation limit','max_cost',{type:'number',min:0,step:.01,value:d.max_cost,hint:'Zero blocks paid workflows. This is not a provider-enforced billing cap.'}),field('Maximum duration (seconds)','max_seconds',{type:'number',min:1,max:86400,value:d.max_seconds})),
      field('Approval policy','approval_policy',{options:[{value:'ask',label:'Ask for each new permission scope'},{value:'reuse_scoped',label:'Reuse bounded workflow approvals'}],value:d.approval_policy||'ask',hint:'Both policies require initial authorization. No destructive, deployment, or billing permission is implied.'})
    ],'Save defaults and continue',async data=>{await api('/api/setup',{step:5,defaults:{...data,fallback_provider:data.fallback_provider||null,context_budget:Number(data.context_budget),max_tokens:Number(data.max_tokens),max_cost:Number(data.max_cost),max_seconds:Number(data.max_seconds)}});await refresh(false);await renderPage();})));
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
  field('Additional exclusions, one pattern per line','exclusions',{multiline:true,placeholder:'private/**\nlarge-generated/**',hint:'Credential, dependency, cache, and linked-file exclusions always apply.'})
],'Preview project',async data=>{
  const request={path:data.path,exclusions:data.exclusions.split('\n').map(x=>x.trim()).filter(Boolean)};
  const result=await api('/api/projects/preview',request);
  preview.replaceChildren(panel('Indexing preview',pre(result),button('Register this project',async()=>{const p=await api('/api/projects',request);selectedProject=p.id;notice('Project registered. Building its initial index…');const indexed=await api('/api/projects/'+p.id+'/index',{});await refresh(false);preview.replaceChildren(panel('Project ready',pre(indexed)));if(page==='setup')await renderPage();else await projects();},'primary')));
});}
function projects(){
  main.replaceChildren(heading('Projects','Preview and register an approved Git repository. Indexing excludes sensitive and unrelated files.'));
  const preview=el('div',{});
  main.append(el('div',{class:'grid'},panel('Register a project',projectRegistrationForm(preview)),panel('Registered projects',arr(state.projects).length?arr(state.projects).map(p=>el('div',{class:'item'},el('h3',{},projectName(p)),el('p',{class:'path'},p.path),el('div',{class:'actions'},button('Build index',async()=>{notice('Indexing changed files…');const result=await api('/api/projects/'+p.id+'/index',{});preview.replaceChildren(panel('Index complete',pre(result)));notice('Index completed.');}),button('Memory',()=>{selectedProject=p.id;go('memory');},'quiet'),button('Context',()=>{selectedProject=p.id;go('context');},'quiet')))):empty('No registered projects','Preview a repository directory first.'))),preview);
}
function renderProviderCards(container){
  container.append(el('div',{class:'grid three'},...arr(state.providers).map(p=>{
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
  const flows=arr(state.workflows);
  if(!flows.length){main.append(empty('No workflows','Create a workflow before granting scoped permissions.'));return;}
  for(const flow of flows){const w=await api('/api/workflows/'+flow.id);main.append(panel(w.objective,statusTag(w.status),el('p',{class:'muted'},w.reason||'No current blocker reported.'),button('Inspect workflow',()=>{selectedWorkflow=w.id;go('workflows');},'quiet'),el('details',{},el('summary',{},'Manage permissions'),approvalForm(w.id,async()=>{await refresh(false);await renderPage();})),pre(arr(w.approvals))));}
}
async function sessions(){
  main.append(heading('Sessions','Inspect stored provider session mappings and continue conversations in their original project.'));
  const result=await api('/api/sessions');main.append(panel('Provider sessions',arr(result.sessions||result).length?pre(result):empty('No sessions yet','A session appears after authorized provider execution.')));
}
async function chat(){
  main.append(heading('Chat','Ask one agent about your selected project. Switching to orchestration is an explicit action.'));
  if(projectNeeded())return;
  const chats=arr(await api('/api/chats'));
  const create=form([field('Project','project_id',{options:projectOptions(),value:selectedProject}),field('Agent','provider',{options:providerOptions(),value:defaults().executor}),field('Conversation name','title',{required:true,placeholder:'Investigate this project'})],'New conversation',async data=>{const c=await api('/api/chats',{...data,mode:'standalone'});selectedChat=c.id;await renderPage();});
  main.append(panel('Start a standalone conversation',create));
  if(!chats.length){main.append(empty('No conversations','Creating a conversation is local. Sending each message requires explicit sharing and usage approval.'));return;}
  if(!selectedChat||!chats.some(c=>c.id===selectedChat))selectedChat=chats[0].id;
  const select=field('Conversation','conversation',{options:chats.map(c=>({value:c.id,label:(c.title||c.id)+' · '+c.provider})),value:selectedChat});select.querySelector('select').addEventListener('change',event=>{selectedChat=event.target.value;renderPage().catch(error=>notice(error.message,true));});main.append(select);
  const id=selectedChat,version=++workflowViewVersion,messages=el('div',{class:'chat-messages','aria-live':'polite'}),status=el('p',{class:'hint',role:'status'},'Loading conversation…');
  const initial=await api('/api/chats/'+id);
  const sender=form([field('Message','content',{required:true,multiline:true,placeholder:'What would you like to understand or investigate?'}),check('I authorize this message, relevant project context, and provider usage','confirmed','Native CLI access may be broader than filtered project context. Sending can use subscription allowance or incur API charges.'),field('Maximum response tokens','max_output_tokens',{type:'number',min:16,max:2048,value:256})],'Send message',async data=>{
    if(data.confirmed!=='yes')throw new Error('Authorize sharing and provider usage for this message first.');
    await api('/api/chats/'+id+'/messages',{content:data.content,confirmed:true,max_output_tokens:Number(data.max_output_tokens),timeout:60});sender.querySelector('[name=content]').value='';sender.querySelector('[name=confirmed]').checked=false;await poll();
  });
  main.append(panel(initial.title||'Conversation',el('p',{class:'hint'},'Agent: '+initial.provider+' · Standalone, read-only conversation'),status,messages,sender,button('Cancel current response',async()=>{await api('/api/chats/'+id+'/cancel',{});await poll();},'quiet'),button('Use this conversation to create a workflow',async()=>{
    if(!confirm('Switch deliberately to orchestration? A new workflow will be created, but it will not run until you approve and start it.'))return;
    const objective=prompt('What should the workflow implement?');if(!objective)return;
    const criteria=prompt('What must be verified before completion?');if(!criteria)return;
    const d=defaults();const w=await api('/api/workflows',{project_id:initial.project_id,objective,criteria:[criteria],providers:{planner:d.planner,executor:d.executor,reviewer:d.reviewer},budgets:{max_cost:d.max_cost,max_tokens:d.max_tokens}});selectedWorkflow=w.id;await refresh(false);go('workflows');
  },'quiet')));
  let signature='';
  function renderConversation(value){const list=arr(value.messages);const next=JSON.stringify(list);if(signature!==next){signature=next;messages.replaceChildren(...list.map(message=>el('article',{class:'chat-message '+(message.role||'' )},el('h3',{},message.role==='user'?'You':value.provider||'Agent'),el('p',{},message.content||message.output||''),message.error?el('p',{class:'error'},message.error):null)));}status.textContent=value.running?'Agent is responding…':value.error||(['FAILED','TIMEOUT','INTERRUPTED','OUTPUT_LIMIT'].includes(value.status)?'Response '+value.status.toLowerCase()+'. Inspect provider diagnostics before sending again.':'Conversation '+(value.status==='CANCELLED'?'cancelled':'saved')+'. No agent is currently running.');return Boolean(value.running);}
  async function poll(){if(version!==workflowViewVersion||!authenticated||!messages.isConnected)return;try{const running=renderConversation(await api('/api/chats/'+id));if(running)workflowPollTimer=setTimeout(poll,1500);}catch{status.textContent='Connection interrupted. Your conversation is saved; retrying…';workflowPollTimer=setTimeout(poll,3000);}}
  if(renderConversation(initial))workflowPollTimer=setTimeout(poll,1500);
}
