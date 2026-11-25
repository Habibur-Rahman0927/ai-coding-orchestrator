'use strict';
// Dependency-free real Chrome/CDP checks. No installs and no sandbox bypass flags.
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const checks = [];
const interactions = {clicks:0,field_changes:0};
let chrome, fixture, profile, session, protocol, browserVersion, backupEvidence;
const pageErrors = [], httpErrors = [];
class CDP {
  constructor(process) {
    this.process = process; this.sequence = 0; this.pending = new Map(); this.buffer = ''; this.events = [];
    process.stdio[4].on('data', bytes => {
      this.buffer += bytes.toString('utf8');
      let end;
      while ((end = this.buffer.indexOf('\0')) >= 0) {
        const raw = this.buffer.slice(0, end); this.buffer = this.buffer.slice(end + 1);
        if (!raw) continue;
        const reply = JSON.parse(raw);
        if (reply.id && this.pending.has(reply.id)) {
          const item = this.pending.get(reply.id); this.pending.delete(reply.id); clearTimeout(item.timer);
          reply.error ? item.reject(new Error(reply.error.message)) : item.resolve(reply.result);
        } else {
          if (reply.method === 'Network.responseReceived' && reply.params.response.status >= 400) httpErrors.push({path:new URL(reply.params.response.url).pathname,status:reply.params.response.status});
          if (reply.method === 'Runtime.exceptionThrown') pageErrors.push(reply.params.exceptionDetails.text + ': ' + (reply.params.exceptionDetails.exception?.description || ''));
          if (reply.method === 'Page.javascriptDialogOpening') this.send('Page.handleJavaScriptDialog', {accept:true}, reply.sessionId).catch(()=>{});
          if (reply.method === 'Fetch.requestPaused') {
            const url = reply.params.request.url;
            if(this.delayChatList && url.endsWith('/api/chats') && reply.params.request.method==='GET'){
              this.delayChatList=false;this.heldChatList={requestId:reply.params.requestId,sessionId:reply.sessionId};continue;
            }
            const permitted = /^http:\/\/127\.0\.0\.1:\d+\//.test(url);
            this.send(permitted ? 'Fetch.continueRequest' : 'Fetch.failRequest', permitted ? {requestId:reply.params.requestId} : {requestId:reply.params.requestId,errorReason:'BlockedByClient'}, reply.sessionId).catch(()=>{});
          }
        }
      }
    });
    process.stdio[3].on('error', error => this.fail(error));
    process.on('exit', (code,signal) => this.fail(new Error(`Chrome exited: ${code ?? signal}`)));
  }
  fail(error) {for(const item of this.pending.values()){clearTimeout(item.timer);item.reject(error);}this.pending.clear();}
  send(method,params={},target=session) {
    const id=++this.sequence;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error(`CDP timeout: ${method}`));},15000);
      this.pending.set(id,{resolve,reject,timer});
      this.process.stdio[3].write(JSON.stringify({id,method,params,...(target?{sessionId:target}:{})})+'\0');
    });
  }
}
async function evaluate(expression) {
  const result=await protocol.send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}
async function waitFor(expression,label,timeout=15000) {
  const until=Date.now()+timeout;
  while(Date.now()<until){if(await evaluate(expression))return;await delay(80);}
  throw new Error('Timed out: '+label);
}
async function click(text,scope='document') {
  interactions.clicks++;
  const expression=`(async()=>{const node=Array.from((${scope})?.querySelectorAll('button,a,summary')||[]).find(n=>{const copy=n.cloneNode(true);copy.querySelectorAll('[aria-hidden=true]').forEach(x=>x.remove());return copy.textContent.trim()===${JSON.stringify(text)} && n.getClientRects().length;});if(!node || node.disabled)return null;node.scrollIntoView({block:'center'});await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));const rect=node.getBoundingClientRect();const x=rect.x+rect.width/2,y=rect.y+rect.height/2;const hit=document.elementFromPoint(x,y);if(!hit || !(node===hit||node.contains(hit)))return null;return {x,y};})()`;
  await waitFor(expression,'click '+text);
  const point=await evaluate(expression);
  if(!point)throw new Error('Click target moved: '+text);
  await protocol.send('Input.dispatchMouseEvent',{type:'mouseMoved',...point});
  await protocol.send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
  await protocol.send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
}
async function fill(label,value,scope='document') {
  interactions.field_changes++;
  const expression=`(()=>{const label=Array.from((${scope})?.querySelectorAll('label')||[]).find(n=>n.textContent.trim()===${JSON.stringify(label)});const node=label&&(document.getElementById(label.htmlFor)||label.querySelector('input,textarea,select'));if(!node || !node.getClientRects().length || node.disabled)return false;if(node.type==='checkbox'){node.checked=${JSON.stringify(Boolean(value))};}else{node.value=${JSON.stringify(String(value))};}node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}));return true;})()`;
  await waitFor(expression,'fill '+label);
}
async function heading(text) {await waitFor(`Array.from(document.querySelectorAll('h1,h2,h3')).some(n=>n.textContent===${JSON.stringify(text)})`,'heading '+text);}
async function nav(text) {if(['Overview','Memory','Context','Sessions','Activity & usage'].includes(text)&&!await evaluate("document.querySelector('nav details').open"))await click('Advanced tools');await click(text,"document.querySelector('nav')");}
async function check(name,fn) {const started=Date.now(),before={...interactions};await fn();checks.push({name,status:'PASS',elapsed_ms:Date.now()-started,clicks:interactions.clicks-before.clicks,field_changes:interactions.field_changes-before.field_changes});console.error('PASS '+name);}
async function launch() {
  profile=fs.mkdtempSync(path.join(os.tmpdir(),'ccx-cdp-browser-'));
  chrome=spawn(process.env.CCX_BROWSER_EXECUTABLE || '/usr/bin/google-chrome',[
    '--headless=new','--remote-debugging-pipe','--no-first-run','--no-default-browser-check',
    '--disable-background-networking','--disable-component-update','--disable-sync',
    '--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe','pipe','pipe']});
  chrome.stderr.on('data',()=>{});
  protocol=new CDP(chrome);
  browserVersion=await protocol.send('Browser.getVersion',{},null);
  const target=await protocol.send('Target.createTarget',{url:'about:blank'},null);
  session=(await protocol.send('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
  await protocol.send('Runtime.enable');await protocol.send('Page.enable');await protocol.send('Network.enable');
  await protocol.send('Fetch.enable',{patterns:[{urlPattern:'http*',requestStage:'Request'}]});
  await protocol.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
}
async function cleanup() {
  if(fixture){try{await fixture.call('stop');}catch{}fixture.process.stdin.end();}
  if(chrome && chrome.exitCode===null){try{await protocol.send('Browser.close',{},null);}catch{} await delay(200);if(chrome.exitCode===null)chrome.kill('SIGTERM');}
  if(profile){await delay(150);try{fs.rmSync(profile,{recursive:true,force:true});}catch{}}
}
function startFixture() {
  const process=spawn(processEnvPython(),['-B',path.join(__dirname,'cdp_workspace_fixture.py')],{cwd:root,stdio:['pipe','pipe','pipe']});
  let buffer='',sequence=0,resolveReady,rejectReady;const pending=new Map();
  const ready=new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;});
  const timer=setTimeout(()=>rejectReady(new Error('Fixture server startup timeout')),15000);
  process.stderr.on('data',()=>{});
  process.stdout.on('data',chunk=>{
    buffer+=chunk.toString();let end;
    while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);if(!line)continue;
      const reply=JSON.parse(line);
      if(reply.ready){clearTimeout(timer);resolveReady(reply);}
      else if(pending.has(reply.id)){const item=pending.get(reply.id);clearTimeout(item.timer);pending.delete(reply.id);item.resolve(reply.result);}
    }
  });
  process.on('exit',(code)=>{clearTimeout(timer);const error=new Error('Fixture server exited '+code);rejectReady(error);for(const item of pending.values()){clearTimeout(item.timer);item.reject(error);}pending.clear();});
  return {process,ready,call(operation,values={}){return new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Fixture command timeout '+operation));},10000);pending.set(id,{resolve,reject,timer});process.stdin.write(JSON.stringify({id,operation,...values})+'\n');});}};
}
function processEnvPython(){return process.env.CCX_PYTHON || 'python3';}
const section=title=>`Array.from(document.querySelectorAll('section.panel')).find(n=>n.querySelector('h2')?.textContent===${JSON.stringify(title)})`;
const approvalScope=`Array.from(document.querySelectorAll('#workflow-detail form')).find(n=>Array.from(n.querySelectorAll('button')).some(b=>b.textContent==='Approve this permission'))`;
async function noticeContains(text){await waitFor(`document.querySelector('#notice')?.textContent.includes(${JSON.stringify(text)})`,'notice '+text);}
async function workflowState(status){await waitFor(`Array.from(document.querySelectorAll('#workflow-detail .tag')).some(n=>n.textContent===${JSON.stringify(status)})`,'workflow '+status,60000);}
async function approve(kind,values={}){
  const before=(await fixture.call('snapshot')).approval_count;
  await fill('Permission',kind,approvalScope);
  for(const [label,value] of Object.entries(values))await fill(label,value,approvalScope);
  await click('Approve this permission',approvalScope);
  const until=Date.now()+10000;let saved=false;
  while(Date.now()<until){if((await fixture.call('snapshot')).approval_count>before){saved=true;break;}await delay(80);}
  assert.ok(saved,'approval was persisted');
  await waitFor(`(${approvalScope})?.querySelector('select[name=kind]')?.value==='sharing' && !(${approvalScope})?.querySelector('button[type=submit]')?.disabled`,'approval form reloaded');
}
async function createWorkflow(objective){
  await heading('Workflows');
  await waitFor(`document.querySelector('[name=objective]')!==null`,'workflow form rendered');
  const isOpen=await evaluate(`document.querySelector('#main details')?.open`);
  if(!isOpen)await click('Start a task');
  await fill('What should be done?',objective);
  await fill('How will we verify it? One criterion per line','app.txt contains good');
  await fill('Orchestrator','codex');await fill('Executor','minimax');await fill('Reviewer','codex');
  const validity=await evaluate(`Array.from(document.querySelector('[name=objective]').form.elements).filter(n=>!n.checkValidity()).map(n=>({name:n.name,message:n.validationMessage}))`);assert.deepEqual(validity,[],'Workflow form validation');
  await click('Create workflow');await delay(200);console.error('WORKFLOW_UI '+JSON.stringify(await evaluate(`({notice:document.querySelector('#notice')?.textContent,invalid:Array.from(document.querySelectorAll('#main input,#main select,#main textarea')).filter(n=>!n.checkValidity()).map(n=>({name:n.name,message:n.validationMessage}))})`)));await waitFor(`document.querySelector('#workflow-detail')?.textContent.includes(${JSON.stringify(objective)})`,'created workflow');
}
async function main() {
  await launch();
  if(process.argv.includes('--smoke')) {checks.push({name:'Installed Chrome sandboxed CDP handshake',status:'PASS'});return;}
  const frontendProject=process.argv.find(value=>value.startsWith('--frontend-project='));
  if(frontendProject){
    const directory=path.resolve(frontendProject.slice('--frontend-project='.length));
    const document=path.join(directory,'index.html');
    assert.ok(fs.statSync(document).isFile(),'Frontend fixture index.html required');
    await check('Frontend counter increment and Reset acceptance in actual Chrome',async()=>{
      await protocol.send('Page.navigate',{url:require('node:url').pathToFileURL(document).href});
      await waitFor(`document.querySelector('#count')?.textContent.trim()==='0'`,'initial counter');
      await click('Increment');await click('Increment');
      assert.equal(await evaluate(`document.querySelector('#count').textContent.trim()`),'2');
      await click('Reset');
      assert.equal(await evaluate(`document.querySelector('#count').textContent.trim()`),'0');
      assert.deepEqual(pageErrors,[]);
    });
    return;
  }
  fixture=startFixture();const ready=await fixture.ready;
  await check('Bootstrap login and complete two-step setup with project preview/register/index',async()=>{
    await protocol.send('Page.navigate',{url:ready.url+'/#bootstrap='+ready.bootstrap});
    await heading('Set up your workspace');
    assert.equal(await evaluate('location.hash.includes("bootstrap")'),false);
    assert.equal(await evaluate('document.cookie'),'');
    await fill('Preferred agent','minimax');await click('Use this agent');await fill('Project directory',ready.project);
    await click('Preview project');await heading('Indexing preview');assert.equal((await fixture.call('snapshot')).projects,0);
    await click('Register this project');await waitFor(`document.querySelector('#main')?.textContent.includes('sample project')`,'registered project');
    await click('Start using workspace');await heading('Chat');
    let state=await fixture.call('snapshot');assert.equal(state.projects,1);assert.equal(state.setup.completed,true);assert.equal(state.calls.length,0);
    await protocol.send('Page.reload');await heading('Chat');
  });
  await check('Provider configuration and disposable session-only credential save/remove',async()=>{
    await nav('Providers');await heading('Providers');const card=section('minimax');
    await fill('Application model override','fixture-model',card);await click('Save configuration',card);await noticeContains('preferences saved');
    await click('Secure credential setup',card);await fill('MiniMax API key','fixture-key-only-not-a-real-credential',card);await fill('Credential storage','session',card);
    await click('Save credential',card);await noticeContains('Credential saved');
    assert.equal(await evaluate(`(${card}).querySelector('input[name=secret]').value`),'');
    assert.equal(await evaluate(`document.body.innerText.includes('fixture-key-only-not-a-real-credential')`),false);
    await click('Remove stored credential',card);
    await waitFor(`Array.from((${card})?.querySelectorAll('button')||[]).some(n=>n.textContent==='Remove stored credential'&&!n.disabled)`,'credential removal');
    const snapshot=await fixture.call('snapshot');
    assert.equal(snapshot.calls.length,0);assert.equal(snapshot.offline_registry_preserved,true);
  });
  await check('Workflow UI approval gates, actual patch/test, independent rejection and correction, refresh',async()=>{
    await nav('Workflows');await createWorkflow('Correct the sample application');
    await click('Run');await workflowState('APPROVAL_REQUIRED');assert.equal((await fixture.call('snapshot')).calls.length,0);
    await approve('sharing',{'Provider':'codex'});await approve('sharing',{'Provider':'minimax'});await approve('operations');
    await approve('command',{'Command name':'acceptance','Executable':ready.python,'Arguments, one per line':'check.py'});
    await fixture.call('hold');
    try {
      await click('Run');await workflowState('RUNNING');await protocol.send('Page.reload');await workflowState('RUNNING');
      assert.ok(await evaluate(`Array.from(document.querySelectorAll('#workflow-detail button')).find(n=>n.textContent==='Run').disabled`),'duplicate Run disabled while active');
    } finally {await fixture.call('release');}
    await workflowState('COMPLETED');
    const state=await fixture.call('snapshot');assert.equal(state.file,'good');assert.equal(state.reviews,2);assert.equal(state.executions,3);
    const workflow=state.workflows.find(w=>w.objective==='Correct the sample application');assert.equal(workflow.status,'COMPLETED');assert.equal(workflow.tasks[0].attempts,1);
    assert.equal(workflow.tasks[0].evidence.tests.commands[0].exit_code,0);
    await click('Inspect exact workflow context');await waitFor(`(${section('Workflow context')})?.textContent.includes('reported_usage')`,'context inspection');
    await click('Inspect execution results');await waitFor(`(${section('Execution results')})?.textContent.includes('output')`,'execution results');
  });
  await check('Memory add/search and context assembly through rendered controls',async()=>{
    await nav('Memory');await heading('Project memory');await fill('Title','CDP decision');await fill('Instruction or note','Keep cdp_memory_marker and do not deploy.');
    await click('Save memory');await noticeContains('Memory saved');await fill('Search query','cdp_memory_marker');await click('Search');
    await waitFor(`(${section('Search knowledge')})?.querySelector('pre')?.textContent.includes('cdp_memory_marker')`,'memory search');
    await nav('Context');await fill('What are you working on?','app good');await fill('Context for','reviewer');await click('Assemble context');await heading('Assembled context');
    assert.ok(await evaluate(`(${section('Assembled context')}).textContent.includes('cdp_memory_marker')`));
    assert.ok(await evaluate(`document.querySelector('[data-context-summary]')?.textContent.includes('estimated tokens')`));
    assert.ok(await evaluate(`(${section('Assembled context')}).textContent.includes('Why these sources')`));
    await nav('Activity & usage');await heading('Activity & usage');
    await waitFor(`document.querySelector('[data-usage-role="executor"]')?.textContent.includes('provider calls')`,'recorded role usage');
    assert.ok(await evaluate(`document.querySelector('#main').textContent.includes('Context bytes prepared')`));
    assert.ok(await evaluate(`document.querySelector('#main').textContent.includes('not measured human effort')`));
    await nav('Sessions');await heading('Provider sessions');
  });
  await check('Active workflow pause/resume/cancel and no completed status after cancellation',async()=>{
    await nav('Workflows');await createWorkflow('Control a running fixture');
    await approve('sharing',{'Provider':'codex'});await approve('sharing',{'Provider':'minimax'});
    await fixture.call('delay',{value:5});await click('Run');await workflowState('RUNNING');
    await click('Pause');await workflowState('PAUSED');
    await click('Resume');await workflowState('READY');await click('Run');await workflowState('RUNNING');
    await click('Cancel');await workflowState('CANCELLED');await fixture.call('delay',{value:.3});
    assert.equal((await fixture.call('snapshot')).workflows.find(w=>w.objective==='Control a running fixture').status,'CANCELLED');
  });
  await check('Standalone chat consent, visible streaming, refresh, and exact session continuation',async()=>{
    await nav('Chat');await click('Advanced: name a new conversation');await fill('Conversation name','Inspect the sample');await fill('Agent','minimax');await click('New conversation');await fill('Message','Explain app.txt');
    await click('Send message');await noticeContains('Authorize sharing');
    const consent='I authorize this message, relevant project context, and provider usage';
    await fill(consent,true);await click('Send message');await waitFor(`document.querySelector('.chat-message.assistant')!==null`,'chat request accepted');await protocol.send('Page.reload');
    await waitFor(`document.querySelector('.chat-message.assistant p')?.textContent.trim()==='A deterministic'`,'partial visible reply',10000);
    await waitFor(`document.querySelector('.chat-messages')?.textContent.includes('A deterministic standalone reply.')`,'complete reply',15000);
    const first=(await fixture.call('snapshot')).chats[0];
    await fill('Message','Continue the explanation');await fill(consent,true);await click('Send message');
    await waitFor(`document.querySelectorAll('.chat-message.assistant').length===2 && Array.from(document.querySelectorAll('.chat-message.assistant')).at(-1).textContent.includes('standalone reply.')`,'second reply',15000);
    const second=(await fixture.call('snapshot')).chats[0];assert.equal(second.session_id,first.session_id);assert.ok(first.session_id);
    assert.equal(await evaluate('localStorage.length'),0);assert.deepEqual(await evaluate('Object.keys(sessionStorage)'),['ccx-session-proof']);
  });
  await check('Invalid project feedback, labelled controls, responsive layout, diagnostics',async()=>{
    await nav('Projects');await click('Register a project');await fill('Project directory',ready.project+'-missing');await click('Preview project');
    await waitFor(`!document.querySelector('#notice').hidden && document.querySelector('#notice').classList.contains('error')`,'invalid project error');
    assert.equal((await fixture.call('snapshot')).projects,1);
    assert.ok(await evaluate(`Array.from(document.querySelectorAll('main input,main textarea,main select')).every(n=>n.labels?.length>0)`));
    await nav('Overview');await heading('Your work, in view.');await protocol.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
    await protocol.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await protocol.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
    assert.ok(await evaluate('document.activeElement !== document.body'));
    await protocol.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await nav('Settings');await click('Run diagnostics');await waitFor(`Array.from(document.querySelectorAll('button')).some(n=>n.textContent==='Export redacted report')`,'diagnostic report');
  });
  await check('Settings database backup creates a private file and a separate recovered copy retains project knowledge',async()=>{
    const before=await fixture.call('snapshot');
    await nav('Settings');await heading('Workspace settings');
    await click('Create database backup',section('Backup & recovery'));
    await noticeContains('Database backup created');
    await waitFor(`(${section('Backup & recovery')})?.querySelector('pre')?.textContent.includes('sha256')`,'rendered backup result');
    const result=await evaluate(`JSON.parse((${section('Backup & recovery')}).querySelector('pre').textContent)`);
    assert.match(result.sha256,/^[a-f0-9]{64}$/);
    assert.ok(result.recovery.includes('separate copy'));
    backupEvidence=await fixture.call('verify_backup',{name:path.basename(result.backup),sha256:result.sha256});
    assert.equal(backupEvidence.integrity,'ok');
    assert.equal(backupEvidence.copy_reopened,true);
    assert.equal(backupEvidence.projects_match,true);
    assert.equal(backupEvidence.project_count,1);
    assert.equal(backupEvidence.workflow_statuses_match,true);
    assert.equal(backupEvidence.workflow_count,before.workflows.length);
    assert.equal(backupEvidence.memory_marker_recovered,true);
    assert.equal(backupEvidence.verified_workflow_memory_recovered,true);
    assert.equal(backupEvidence.private_backup_mode,true);
    assert.equal(backupEvidence.original_backup_unchanged,true);
    const after=await fixture.call('snapshot');
    assert.equal(after.backup_count,before.backup_count+1);
    assert.equal(after.calls.length,before.calls.length,'backup does not dispatch a provider');
  });
  await check('A second tab cannot authenticate with cookie alone and the original tab remains usable',async()=>{
    const originalSession=session;
    const target=await protocol.send('Target.createTarget',{url:'about:blank'},null);
    try{
      session=(await protocol.send('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
      await protocol.send('Runtime.enable');await protocol.send('Page.enable');await protocol.send('Network.enable');
      await protocol.send('Fetch.enable',{patterns:[{urlPattern:'http*',requestStage:'Request'}]});
      await protocol.send('Page.navigate',{url:ready.url+'/'});
      await waitFor(`document.querySelector('#login') && !document.querySelector('#login').hidden`,'second tab requires sign-in');
      assert.equal(await evaluate(`sessionStorage.getItem('ccx-session-proof')`),null);
      assert.equal(await evaluate(`document.cookie`),'');
    }finally{
      await protocol.send('Target.closeTarget',{targetId:target.targetId},null);
      session=originalSession;
    }
    await protocol.send('Page.reload');await heading('Workspace settings');
    assert.ok(await evaluate(`sessionStorage.getItem('ccx-session-proof')`));
    await click('Run diagnostics');
    await waitFor(`Array.from(document.querySelectorAll('button')).some(n=>n.textContent==='Export redacted report')`,'original tab still authorized');
  });
  await check('Solo and Auto task proposals require explicit consent and preserve exact instruction',async()=>{
    await nav('Chat');const before=await fixture.call('snapshot');
    await fill('AI provider','minimax');await fill('Task instruction','Explain this project with Codex mentioned as reference only.');
    await fill('Working mode','auto');await click('Review task');await heading('Your execution plan');
    assert.ok(await evaluate(`(${section('Your execution plan')}).textContent.includes('Read-only conversation with minimax')`));
    assert.equal((await fixture.call('snapshot')).calls.length,before.calls.length);
    await click('Open conversation');await waitFor(`document.querySelector('[name=content]')?.value.startsWith('Explain this project')`,'instruction transferred locally');
    await click('Send message');await noticeContains('Authorize sharing');
    assert.equal((await fixture.call('snapshot')).calls.length,before.calls.length);
    await fill('I authorize this message, relevant project context, and provider usage',true);await click('Send message');
    await waitFor(`document.querySelector('.chat-messages')?.textContent.includes('A deterministic standalone reply.')`,'new Solo conversation reply',15000);
    await fill('Task instruction','A Solo question without a conversation title');const soloBefore=(await fixture.call('snapshot')).calls.length;await click('Start conversation');await waitFor(`document.querySelector('[name=content]')?.value==='A Solo question without a conversation title'`,'Solo local draft');assert.equal((await fixture.call('snapshot')).calls.length,soloBefore);
  });
  await check('Collaborate preset creates bounded workflow and runs through existing approval and verification gates',async()=>{
    await fill('AI provider','minimax');await fill('Working mode','collaborate');await fill('Workflow preset','quick_fix');
    await fill('Collaboration partner','codex');await fill('Task instruction','Use MiniMax to verify the completed repair');await fill('What must pass?','app.txt contains good');
    const before=await fixture.call('snapshot');await click('Review task');await heading('Your execution plan');
    assert.equal((await fixture.call('snapshot')).calls.length,before.calls.length);
    await click('Create reviewed workflow');await workflowState('READY');
    await click('Run');await workflowState('APPROVAL_REQUIRED');
    await approve('sharing',{'Provider':'minimax'});await approve('sharing',{'Provider':'codex'});await approve('operations');
    await approve('command',{'Command name':'acceptance','Executable':ready.python,'Arguments, one per line':'check.py'});
    await click('Run');await workflowState('COMPLETED');await heading('Verified result');
    const flow=(await fixture.call('snapshot')).workflows.find(w=>w.objective==='Use MiniMax to verify the completed repair');
    assert.equal(flow.execution_policy,'single_task');assert.equal(flow.tasks[0].status,'VERIFIED');
    await nav('Chat');await fill('Working mode','auto');await fill('Workflow preset','feature');await fill('Collaboration partner','codex');await fill('AI provider','minimax');
    await fill('Task instruction','A new feature');await fill('What must pass?','Feature acceptance tests pass');await click('Review task');await heading('Your execution plan');
    assert.ok(await evaluate(`(${section('Your execution plan')}).textContent.includes('Implement with minimax; test and review with codex')`));
    await fill('Task instruction','Continue the previous task');await click('Review task');await click('Inspect previous work');
    assert.equal((await fixture.call('snapshot')).workflows.find(w=>w.id===flow.id).status,'COMPLETED');
  });
  await check('Project switching, favorites, appearance and Help persist without cross-project conversations',async()=>{
    await nav('Projects');await click('Register a project');await fill('Project directory',ready.second_project);await click('Preview project');await click('Register this project');
    await waitFor(`Array.from(document.querySelectorAll('button')).some(n=>n.textContent==='Open second project')`,'second project indexing and registration completed');await fill('Find a project','second project');await click('Add favorite');
    await waitFor(`Array.from(document.querySelectorAll('button')).some(n=>n.textContent==='Remove favorite')`,'favorite saved before navigation');
    assert.equal((await fixture.call('snapshot')).experience.favorites.length,1);
    await click('Open second project');await heading('Chat');
    assert.equal(await evaluate(`document.querySelector('.chat-messages')`),null);
    await protocol.send('Page.reload');await heading('Chat');assert.ok(await evaluate(`document.querySelector('[name="active-project"]').selectedOptions[0].textContent.includes('second project')`));
    await nav('Projects');await fill('Find a project','second project');assert.equal((await fixture.call('snapshot')).experience.favorites.length,1);await waitFor(`Array.from(document.querySelectorAll('button')).some(n=>n.textContent==='Remove favorite')`,'favorite persisted');
    await fill('Find a project','sample project');await click('Open sample project');await heading('Chat');await waitFor(`document.querySelector('.chat-messages')!==null`,'previous project conversations restored');
    await nav('Settings');await fill('Appearance','light');await waitFor(`document.documentElement.dataset.theme==='light'`,'light appearance');await protocol.send('Page.reload');await heading('Workspace settings');assert.equal(await evaluate('document.documentElement.dataset.theme'),'light');
    if(process.env.CCX_BROWSER_SCREENSHOTS){fs.mkdirSync(process.env.CCX_BROWSER_SCREENSHOTS,{recursive:true});fs.writeFileSync(path.join(process.env.CCX_BROWSER_SCREENSHOTS,'light.png'),Buffer.from((await protocol.send('Page.captureScreenshot',{format:'png'})).data,'base64'));}
    await fill('Appearance','dark');await waitFor(`document.documentElement.dataset.theme==='dark'`,'dark appearance');
    if(process.env.CCX_BROWSER_SCREENSHOTS)fs.writeFileSync(path.join(process.env.CCX_BROWSER_SCREENSHOTS,'dark.png'),Buffer.from((await protocol.send('Page.captureScreenshot',{format:'png'})).data,'base64'));
    await nav('Help');await heading('Help');await click('Open diagnostics');await heading('Workspace settings');
  });
  await check('Delayed conversation response cannot populate a newly selected project',async()=>{
    await nav('Overview');protocol.delayChatList=true;await nav('Chat');
    const until=Date.now()+10000;while(!protocol.heldChatList&&Date.now()<until)await delay(30);assert.ok(protocol.heldChatList);
    await nav('Projects');await fill('Find a project','second project');await click('Open second project');await heading('Chat');
    const held=protocol.heldChatList;protocol.heldChatList=null;await protocol.send('Fetch.continueRequest',{requestId:held.requestId},held.sessionId);await delay(200);
    assert.equal(await evaluate(`document.querySelector('.chat-messages')`),null);
    assert.ok(await evaluate(`document.querySelector('[name="active-project"]').selectedOptions[0].textContent.includes('second project')`));
  });
  await check('Logout persists across refresh, consumed bootstrap refused, expired sessions return login',async()=>{
    await click('Disconnect');await waitFor(`!document.querySelector('#login').hidden`,'logged out');
    await protocol.send('Page.reload');await waitFor(`!document.querySelector('#login').hidden`,'logout after refresh');
    await protocol.send('Page.navigate',{url:'about:blank'});await waitFor(`location.href==='about:blank'`,'blank navigation');await protocol.send('Page.navigate',{url:ready.url+'/#bootstrap='+ready.bootstrap});await noticeContains('expired or was already used');
    const next=await fixture.call('bootstrap');await protocol.send('Page.navigate',{url:'about:blank'});await waitFor(`location.href==='about:blank'`,'fresh login navigation');await protocol.send('Page.navigate',{url:ready.url+'/#bootstrap='+next.bootstrap});await heading('Chat');
    await fixture.call('expire');await protocol.send('Page.reload');await waitFor(`!document.querySelector('#login').hidden && sessionStorage.getItem('ccx-session-proof')===null`,'expired session login and rejected proof');
  });
  await check('Disconnected backend shows actionable error without claiming request success',async()=>{
    const next=await fixture.call('bootstrap');await protocol.send('Page.navigate',{url:'about:blank'});await waitFor(`location.href==='about:blank'`,'new startup document');await protocol.send('Page.navigate',{url:ready.url+'/#bootstrap='+next.bootstrap});await heading('Chat');
    await nav('Settings');await fixture.call('disconnect');await click('Run diagnostics');await noticeContains('Workspace disconnected');
    assert.ok(await evaluate(`document.querySelector('#notice').textContent.includes('outcome is unknown')`));
  });
  assert.deepEqual(pageErrors,[]);
}
(async()=>{
 const started=Date.now();let failure,diagnostic;
 try{await main();}catch(error){failure=error;console.error(error.message);if(fixture){try{const state=await fixture.call('snapshot');diagnostic={ui:await evaluate(`({preferences:experience,project_ids:state.projects.map(p=>({id:p.id,name:p.path.split('/').pop()})),buttons:Array.from(document.querySelectorAll('#main button')).map(n=>n.textContent),notice:document.querySelector('#notice')?.textContent,fields:Array.from(document.querySelectorAll('#main input,#main select,#main textarea')).filter(n=>n.type!=='password').map(n=>({name:n.name,value:n.value,valid:n.checkValidity()}))})`),projects:state.projects,calls:state.calls,approval_count:state.approval_count,workflows:state.workflows.map(w=>({status:w.status,reason:w.reason,tasks:w.tasks.map(t=>({status:t.status,error:t.error}))}))};}catch{}}}
 finally{await cleanup();}
 const report={status:failure?'FAIL':'PASS',browser:browserVersion?.product || 'not_started',protocol:browserVersion?.protocolVersion || null,sandbox_disabled:false,provider_mode:'deterministic_offline',installed_dependencies:false,elapsed_ms:Date.now()-started,checks,page_errors:pageErrors,http_errors:httpErrors,...(backupEvidence?{backup_evidence:backupEvidence}:{}),...(failure?{error:failure.message,diagnostic}:{})};
 const reportArg=process.argv.find(x=>x.startsWith('--report='));if(reportArg)fs.writeFileSync(reportArg.slice(9),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify(report,null,2));process.exitCode=failure?1:0;
})();
