'use strict';
let fieldSequence = 0, workflowViewVersion = 0, workflowPollTimer = null;
let token = '', state = {}, page = 'overview', selectedProject = '', selectedWorkflow = '';
const main = document.getElementById('main');
const pages = [['overview','Overview','◈'],['projects','Projects','▣'],['memory','Memory','▤'],['context','Context','◎'],['workflows','Workflows','◇'],['providers','Providers','⊞'],['activity','Activity & usage','◷'],['settings','Settings','⚙']];
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'class') node.className = value;
    else if (key === 'value') node.value = value;
    else if (value !== undefined && value !== false) node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
};
function notice(message, error = false) { const n = document.getElementById('notice'); n.textContent = message; n.className = error ? 'error' : ''; n.hidden = false; clearTimeout(notice.timer); notice.timer = setTimeout(() => { n.hidden = true; }, error ? 10000 : 5000); }
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache:'no-store', credentials:'omit', headers: {'Authorization':'Bearer '+token, ...(body !== undefined ? {'Content-Type':'application/json'} : {})}, ...(body !== undefined ? {body:JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed.');
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
const statusTag = value => {const s=text(value);return el('span',{class:'tag '+(/done|success|complete|available|approved/i.test(s)?'good':/fail|cancel|error/i.test(s)?'bad':/wait|pause|approval|block/i.test(s)?'warn':'')},s);};
function field(label,name,options={}) {const id='field-'+(++fieldSequence);const input=el(options.multiline?'textarea':options.options?'select':'input',{name,id,...(options.multiline?{}:options.options?{}:{type:options.type||'text'}),placeholder:options.placeholder,required:options.required,value:options.value, min:options.min,max:options.max,step:options.step}); if(options.options)for(const item of options.options)input.append(el('option',{value:typeof item==='string'?item:item.value},typeof item==='string'?item:item.label)); if(options.value!==undefined)input.value=options.value;return el('div',{class:'field'},el('label',{for:id},label),input,options.hint?el('p',{class:'hint'},options.hint):null);}
function form(children, label, action) {const f=el('form',{},...children,el('button',{type:'submit',class:'primary'},label));f.addEventListener('submit',async event=>{event.preventDefault();const submit=f.querySelector('[type=submit]');submit.disabled=true;try{await action(Object.fromEntries(new FormData(f)));}catch(error){notice(error.message,true);}finally{submit.disabled=false;}});return f;}
function heading(title,description,actions) {return el('div',{class:'page-head'},el('div',{},el('p',{class:'eyebrow'},'ORCHESTRATOR WORKSPACE'),el('h1',{},title),el('p',{},description)),actions?el('div',{class:'actions'},actions):null);}
function projectOptions(){return arr(state.projects).map(p=>({value:p.id,label:p.name||p.path||p.id}));}
function projectPicker(action){const f=field('Project','active-project',{options:projectOptions(),value:selectedProject});f.querySelector('select').addEventListener('change',async event=>{selectedProject=event.target.value;try{await action();}catch(error){notice(error.message,true);}});return f;}
function projectNeeded(){if(!arr(state.projects).length){main.append(empty('Start with a project','Register a local project in Projects to index files, manage memory, and assemble context.'));return true;}if(!selectedProject||!state.projects.some(p=>p.id===selectedProject))selectedProject=state.projects[0].id;return false;}
async function refresh(render=true){state=await api('/api/state');document.getElementById('updated').textContent='Updated '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});if(render)await renderPage();}
function go(name){location.hash=name;if(page===name)renderPage().catch(error=>notice(error.message,true));}
async function renderPage(){clearTimeout(workflowPollTimer);workflowViewVersion++;page=location.hash.slice(1)||'overview';if(!pages.some(x=>x[0]===page))page='overview';document.getElementById('breadcrumb').textContent='Workspace / '+pages.find(x=>x[0]===page)[1];for(const a of document.querySelectorAll('nav a'))a.setAttribute('aria-current',a.hash==='#'+page?'page':'false');main.replaceChildren();await ({overview,projects,memory,context,workflows,providers,activity,settings}[page])();}
function overview(){const projects=arr(state.projects),flows=arr(state.workflows),available=arr(state.providers).filter(p=>p.available);main.append(heading('Your work, in view.','Keep project knowledge close and coordinate agent work with explicit boundaries.'),el('div',{class:'metrics'},...[[projects.length,'Registered projects'],[flows.length,'Workflows'],[arr(state.running).length,'Active runners'],[available.length,'Available providers']].map(([n,label])=>el('div',{class:'metric'},el('p',{},label),el('strong',{class:'number'},n)))));const recent=panel('Projects',projects.length?projects.slice(0,4).map(p=>el('div',{class:'item'},el('h3',{},projectName(p)),el('p',{class:'path'},p.path||p.root),button('Open project',()=>{selectedProject=p.id;go('memory');},'quiet'))):empty('A clear place to begin','Register a local repository to build its project index.'),el('div',{class:'actions'},button('Manage projects',()=>go('projects'),'primary')));const flowsPanel=panel('Workflow queue',flows.length?flows.slice(0,4).map(w=>el('div',{class:'item'},el('h3',{},w.objective||w.id),statusTag(w.status||w.state),el('div',{class:'actions'},button('View workflow',()=>{selectedWorkflow=w.id;go('workflows');},'quiet')))):empty('No workflows yet','Define an objective and success criteria. Agent execution starts only when you run it.'));main.append(el('div',{class:'grid'},recent,flowsPanel),panel('This machine',el('p',{class:'muted'},'Machine information is local context. Refresh it when tools or the environment change.'),pre(state.machine)));}
function projects(){main.append(heading('Projects','Register a path on this computer. Indexing reads project files under the workspace’s exclusion and size policies.'));main.append(el('div',{class:'grid'},panel('Register a project',form([field('Project directory','path',{required:true,placeholder:'Absolute path to a local project'}),field('Additional exclusions, one pattern per line','exclusions',{multiline:true,placeholder:'private/**\nlarge-generated/**',hint:'Built-in credential, cache, and dependency exclusions always apply.'})],'Register project',async data=>{const p=await api('/api/projects',{path:data.path,exclusions:data.exclusions.split('\n').map(x=>x.trim()).filter(Boolean)});selectedProject=p.id;await refresh();notice('Project registered.');})),panel('Registered projects',arr(state.projects).length?arr(state.projects).map(p=>el('div',{class:'item'},el('h3',{},projectName(p)),el('p',{class:'path'},p.path||p.root),el('div',{class:'actions'},button('Build index',async()=>{const result=await api('/api/projects/'+p.id+'/index',{});notice('Index completed.');main.append(panel('Index result',pre(result)));}),button('Memory',()=>{selectedProject=p.id;go('memory');},'quiet'),button('Context',()=>{selectedProject=p.id;go('context');},'quiet')))):empty('No registered projects','Add a project directory to get started.'))));}
async function memory(){main.append(heading('Project memory','Inspect stored knowledge, search the project index, and remove records you no longer want.'));if(projectNeeded())return;main.append(projectPicker(memoryReload));await memoryReload();}
async function memoryReload(){document.getElementById('memory-content')?.remove();const container=el('div',{id:'memory-content'});main.append(container);const rows=arr(await api('/api/projects/'+selectedProject+'/memories'));const result=el('div',{});container.append(panel('Add a memory',form([field('Title','title',{required:true}),field('Instruction or note','body',{required:true,multiline:true}),field('Scope','scope',{options:['project','workflow','session','error','verification','skills','temporary']})],'Save memory',async data=>{await api('/api/projects/'+selectedProject+'/remember',data);await memoryReload();notice('Memory saved as a user instruction.');})),panel('Search knowledge',form([field('Search query','query',{required:true,placeholder:'Where is authentication configured?'}),field('Scope','scope',{placeholder:'Optional scope'})],'Search',async data=>{const found=await api('/api/projects/'+selectedProject+'/search',{query:data.query,scope:data.scope||null,limit:20});result.replaceChildren(pre(found));}),result),panel('Stored records',el('div',{class:'section-head'},el('p',{class:'muted'},rows.length+' memory records'),button('Export project memory',async()=>download(await api('/api/projects/'+selectedProject+'/export'),'project-memory.json'))),rows.length?rows.map(row=>el('article',{class:'item'},el('h3',{},row.title||row.key||row.kind||row.id),el('p',{class:'hint'},row.scope||row.source||'Project memory'),pre(row.body||row.content||row.value||row),button('Delete record',async()=>{if(!confirm('Delete this memory record? This cannot be undone here.'))return;await api('/api/projects/'+selectedProject+'/delete-memory',{id:row.id});await memoryReload();notice('Memory record deleted.');},'danger'))):empty('No memory records','Indexing and workflow activity can provide project knowledge. Search the index above.')));}
function context(){main.append(heading('Build useful context','Retrieve relevant project knowledge within an explicit budget. Critical instructions stay visible in the request.'));if(projectNeeded())return;const result=el('div',{});main.append(projectPicker(async()=>result.replaceChildren()),panel('Context request',form([field('What are you working on?','query',{required:true,multiline:true,placeholder:'Describe the task or question to ground in this project.'}),el('div',{class:'form-row'},field('Context budget','budget',{type:'number',value:2000,min:100,max:32000}),field('Critical instructions, one per line','critical',{multiline:true,placeholder:'Keep these instructions in the assembled context.'}))],'Assemble context',async data=>{const value=await api('/api/projects/'+selectedProject+'/context',{query:data.query,budget:Number(data.budget),critical:data.critical.split('\n').filter(x=>x.trim())});result.replaceChildren(panel('Assembled context',pre(value),button('Download context',()=>download(value,'context.json'))));})),result);}
async function workflows(){main.append(heading('Workflows','Turn an objective into tasks with separate execution, review, approvals, and a durable history.'));if(projectNeeded())return;const create=el('details',{},el('summary',{},'Create a workflow'),form([field('Project','project_id',{options:projectOptions(),value:selectedProject}),field('Objective','objective',{required:true,multiline:true}),field('Success criteria, one per line','criteria',{required:true,multiline:true}),el('div',{class:'form-row'},field('Maximum recorded cost','max_cost',{type:'number',value:0,min:0,step:0.01,hint:'Zero blocks live provider calls. A positive budget also requires a separate cost approval.'}),field('Token budget','max_tokens',{type:'number',value:50000,min:1})),el('div',{class:'form-row'},field('Executor','executor',{options:['codex','claude','minimax']}),field('Reviewer','reviewer',{options:['claude','codex','minimax']}))],'Create workflow',async data=>{const value=await api('/api/workflows',{project_id:data.project_id,objective:data.objective,criteria:data.criteria.split('\n').filter(x=>x.trim()),budgets:{max_cost:Number(data.max_cost),max_tokens:Number(data.max_tokens)},providers:{planner:'claude',executor:data.executor,reviewer:data.reviewer}});selectedWorkflow=value.id;await refresh();notice('Workflow created.');}));main.append(panel('',create));const flows=arr(state.workflows);if(!flows.length){main.append(empty('No workflows yet','Create an objective above. Nothing runs until you choose Run.'));return;}if(!selectedWorkflow||!flows.some(w=>w.id===selectedWorkflow))selectedWorkflow=flows[0].id;const side=el('div',{},...flows.map(w=>el('button',{class:'list-button',type:'button','aria-pressed':w.id===selectedWorkflow,onclick:()=>{selectedWorkflow=w.id;renderPage().catch(error=>notice(error.message,true));}},el('strong',{},w.objective||w.id),statusTag(w.status||w.state),el('span',{class:'hint'},w.id))));const detail=el('div',{id:'workflow-detail'});main.append(el('div',{class:'split'},side,detail));await workflowDetail(detail);}
async function workflowDetail(target) {
  clearTimeout(workflowPollTimer);
  const version = ++workflowViewVersion, id = selectedWorkflow;
  const initial = await api('/api/workflows/' + id);
  if (!target.isConnected || version !== workflowViewVersion) return;
  const live = el('div', {}), feedback = el('p', {class:'hint',role:'status'}, 'Status loaded.');
  const taskList = el('div', {}), approvalList = el('div', {}), eventList = el('div', {class:'event-stream'});
  const checkpoints = el('div', {}), cards = new Map();
  let eventSignature = '', approvalSignature = '', active = false;
  const reload = () => workflowDetail(target);
  const controls = el('div', {class:'actions'}, ...['run','pause','resume','cancel'].map(action => button(action[0].toUpperCase()+action.slice(1), async () => {
    if (action === 'cancel' && !confirm('Cancel this workflow?')) return;
    await api('/api/workflows/'+id+'/'+action, {});
    await reload();
    notice(action === 'run' ? 'Runner started. Live updates follow its progress.' : 'Workflow '+action+' requested.');
  }, action === 'run' ? 'primary' : action === 'cancel' ? 'danger' : '')), button('Refresh status', reload, 'quiet'), button('Export workflow', async () => download(await api('/api/workflows/'+id+'/export'), 'workflow.json'), 'quiet'));
  const addTask = el('details', {}, el('summary', {}, 'Add a task'), form([
    field('Task title','title',{required:true}), field('Description','description',{multiline:true}),
    el('div',{class:'form-row'},field('Executor','executor',{options:['codex','claude','minimax']}),field('Reviewer','reviewer',{options:['claude','codex','minimax']}))
  ], 'Add task', async data => {await api('/api/workflows/'+id+'/tasks', data); await reload();}));
  const approve = form([
    field('Approval type','kind',{options:['sharing','cost','native_agent_access','native_agent_write','operations','command','recovery','failover']}),
    field('Exact approval scope (JSON object)','scope',{required:true,multiline:true,value:'{"provider":"codex"}',hint:'Cost: {"provider":"minimax","max_cost":1,"max_call_cost":0.1}. Scoped patch: {"operations":["patch"]}. Review exact command scopes before approval.'})
  ], 'Approve scope', async data => {
    let scope; try {scope = JSON.parse(data.scope);} catch {throw new Error('Enter a valid JSON approval scope.');}
    if (!confirm('Approve this exact scope?\n'+JSON.stringify(scope))) return;
    await api('/api/workflows/'+id+'/approve', {kind:data.kind,scope}); await reload();
  });
  target.replaceChildren(
    panel(initial.objective || 'Workflow', el('p',{class:'path'},id), live, controls, feedback),
    panel('Tasks', taskList, addTask),
    panel('Approvals', el('p',{class:'muted'},'Approve only the exact provider or command scope you intend. Approval is a user action; agents cannot approve for you.'), approvalList, approve),
    panel('Checkpoints', button('Load checkpoints',async()=>checkpoints.replaceChildren(pre(await api('/api/workflows/'+id+'/checkpoints')))),checkpoints),
    panel('Event history',eventList)
  );
  function renderLive(w) {
    live.replaceChildren(statusTag(w.status||w.state),el('p',{class:'muted'},w.runner_error||w.reason||''),el('p',{class:'hint'},'Recorded tokens: '+text(w.usage?.recorded_tokens)+' · Recorded cost: '+text(w.usage?.recorded_cost)),el('details',{},el('summary',{},'Criteria, budgets, and usage'),pre({criteria:w.criteria,budgets:w.budgets,usage:w.usage,providers:w.providers})));
    const tasks = arr(w.tasks);
    if (!tasks.length && !cards.size) taskList.replaceChildren(empty('No tasks yet','Add an explicit task or let the approved planner produce a bounded plan when you run.'));
    for (const t of tasks) {
      if (!cards.has(t.id)) {
        if (!cards.size) taskList.replaceChildren();
        const status = el('div',{}), evidence = pre(t);
        const card = el('div',{class:'item'},el('h3',{},t.title||t.id),status,el('p',{class:'muted'},t.description||''),el('details',{},el('summary',{},'Task details'),evidence),form([
          field('Destination provider','to_provider',{options:['codex','claude','minimax'].filter(provider=>provider!==t.executor)}),
          field('Transition','transition',{options:['delegate','failover'],hint:'Failover needs a matching user approval with task_id and to_provider.'})
        ],'Apply provider transition',async data=>{if(data.transition==='failover'&&!confirm('Apply this previously approved provider failover?'))return;await api('/api/tasks/'+t.id+'/'+data.transition,{to_provider:data.to_provider});await reload();}));
        cards.set(t.id,{status,evidence}); taskList.append(card);
      }
      const card = cards.get(t.id);
      card.status.replaceChildren(statusTag(t.status||t.state),el('p',{class:'hint'},'Executor: '+text(t.executor)+' · Reviewer: '+text(t.reviewer)));
      card.evidence.textContent = JSON.stringify(t,null,2);
    }
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
      eventList.replaceChildren(...(events.length ? events.map(e=>el('div',{class:'item'},el('h3',{},e.kind||e.type||e.event||'Event'),el('p',{class:'hint'},formatDate(e.created_at||e.timestamp)),pre(e))) : [el('p',{class:'muted'},'No events returned for this workflow.')]));
      eventList.scrollTop = atEnd ? eventList.scrollHeight : position;
    }
    active = Boolean(w.runner_active || w.status === 'RUNNING');
    feedback.textContent = (active ? 'Live · refreshing every 3 seconds' : 'Up to date · no active runner') + ' · ' + new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  async function poll() {
    if (version !== workflowViewVersion || !target.isConnected || !token) return;
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

function providers(){main.append(heading('Providers','Check local availability and configure model preferences. Credential values stay outside the dashboard.'));main.append(el('div',{class:'grid three'},...arr(state.providers).map(p=>{const result=el('div',{}),saved=state.settings?.provider_config?.[p.id]||{};return panel(p.id, statusTag(p.available?'Available':'Unavailable'),el('p',{class:'muted'},p.error||p.reason||'Availability is a local configuration check, not a live model test.'),el('details',{},el('summary',{},'Capabilities'),pre(p.capabilities||p)),el('div',{class:'actions'},button('Check availability',async()=>result.replaceChildren(pre(await api('/api/providers/'+p.id+'/probe',{}))))),result,form([field('Model','model',{value:saved.model||p.model||'',placeholder:'Provider default'}),...(p.id==='minimax'?[field('API key environment variable name','api_key_env',{value:saved.api_key_env||'MINIMAX_API_KEY',hint:'Enter the variable name, never the API key.'}),field('Endpoint','endpoint',{value:saved.endpoint||'',placeholder:'Use the supported default endpoint'})]:[])],'Save configuration',async data=>{const config=Object.fromEntries(Object.entries(data).filter(([,v])=>v.trim()));await api('/api/providers/'+p.id+'/configure',{config});await refresh();notice('Provider configuration saved.');}));})));}
async function activity(){main.append(heading('Activity & usage','Inspect workflow history and recorded usage. Missing provider usage is shown as unreported, never estimated as zero.'));const flows=arr(state.workflows);if(!flows.length){main.append(empty('No activity yet','Workflow events and usage appear after you create and run work.'));return;}for(const item of flows){const w=await api('/api/workflows/'+item.id);main.append(panel(item.objective||item.id,statusTag(w.status||w.state),el('h3',{},'Usage and budgets'),pre({usage:w.usage??'Unreported',budgets:w.budgets??'Unreported'}),el('details',{},el('summary',{},'Events ('+arr(w.events).length+')'),pre(w.events||[])),button('Open workflow',()=>{selectedWorkflow=item.id;go('workflows');},'quiet')));}}
function settings(){main.append(heading('Workspace settings','Connection boundaries are enforced by the server. Provider credentials are never stored in this browser.'));main.append(el('div',{class:'grid'},panel('Connection & privacy',el('dl',{class:'data-list'},el('dt',{},'Network'),el('dd',{},'IPv4 loopback only'),el('dt',{},'Authentication'),el('dd',{},'Random bearer token, held in tab memory'),el('dt',{},'Cross-origin access'),el('dd',{},'Refused'),el('dt',{},'Request limit'),el('dd',{},'64 KiB')),button('Disconnect this tab',disconnect,'danger')),panel('Machine context',el('p',{class:'muted'},'Refresh tool and platform discovery after changing your development environment.'),button('Refresh machine information',async()=>{state.machine=await api('/api/machine/refresh',{});await renderPage();notice('Machine information refreshed.');}),pre(state.machine))),panel('Provider preferences',el('p',{class:'muted'},'Configure models and the name of a credential environment variable in Providers. Native agent access, data sharing, commands, and spending are approved per workflow.'),button('Manage providers',()=>go('providers'))));}
function download(value,name){const blob=new Blob([JSON.stringify(value,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a',{href:url,download:name});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function disconnect(){clearTimeout(workflowPollTimer);workflowViewVersion++;token='';state={};document.getElementById('workspace').hidden=true;document.getElementById('login').hidden=false;document.getElementById('token').value='';main.replaceChildren();document.getElementById('token').focus();}
for(const [name,label,icon]of pages)document.getElementById('navigation').append(el('a',{href:'#'+name},el('span',{class:'nav-icon','aria-hidden':'true'},icon),label));
document.getElementById('login-form').addEventListener('submit',async event=>{event.preventDefault();const input=document.getElementById('token');token=input.value.trim();try{await refresh(false);input.value='';document.getElementById('login').hidden=true;document.getElementById('workspace').hidden=false;await renderPage();}catch(error){token='';notice(error.message,true);}});
document.getElementById('disconnect').addEventListener('click',disconnect);
document.getElementById('refresh').addEventListener('click',()=>refresh().catch(error=>notice(error.message,true)));
window.addEventListener('hashchange',()=>{if(token)renderPage().catch(error=>notice(error.message,true));});
