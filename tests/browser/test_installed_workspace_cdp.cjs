'use strict';
// Focused installed-CLI lifecycle smoke. Built-in Node modules and installed Chrome only.
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let chrome,profile,session,fixture,cdp,providerActions=null;
const checks=[],pageErrors=[];
function channel(process,read,write,separator){
  let buffer='',sequence=0;const pending=new Map();let onEvent=()=>{};
  read.on('data',chunk=>{buffer+=chunk.toString();let end;while((end=buffer.indexOf(separator))>=0){const raw=buffer.slice(0,end);buffer=buffer.slice(end+separator.length);if(!raw)continue;const reply=JSON.parse(raw);if(pending.has(reply.id)){const item=pending.get(reply.id);pending.delete(reply.id);clearTimeout(item.timer);reply.error?item.reject(new Error(reply.error.message)):item.resolve(reply.result);}else onEvent(reply);}});
  const fail=error=>{for(const item of pending.values()){clearTimeout(item.timer);item.reject(error);}pending.clear();};
  process.on('exit',code=>fail(new Error('Owned test process exited '+code)));write.on('error',fail);
  return {events(handler){onEvent=handler;},send(value){return new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Protocol operation timed out'));},45000);pending.set(id,{resolve,reject,timer});write.write(JSON.stringify({id,...value})+separator);});}};
}
async function call(method,params={},target=session){return cdp.send({method,params,...(target?{sessionId:target}:{})});}
async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.text);return r.result.value;}
async function wait(expression,label){const end=Date.now()+15000;while(Date.now()<end){if(await evaluate(expression))return;await sleep(80);}throw new Error('Timed out: '+label);}
async function click(text){
  const expr=`(async()=>{const n=Array.from(document.querySelectorAll('button,summary')).find(n=>n.textContent.trim()===${JSON.stringify(text)}&&n.getClientRects().length&&!n.disabled);if(!n)return null;n.scrollIntoView({block:'center'});await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));const b=n.getBoundingClientRect(),x=b.x+b.width/2,y=b.y+b.height/2,h=document.elementFromPoint(x,y);return h&&(n===h||n.contains(h))?{x,y}:null;})()`;
  await wait(expr,'click '+text);const point=await evaluate(expr);assert.ok(point);
  await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
}
async function fill(label,value){await wait(`(()=>{const l=Array.from(document.querySelectorAll('label')).find(n=>n.textContent.trim()===${JSON.stringify(label)});const n=l&&document.getElementById(l.htmlFor);if(!n||!n.getClientRects().length)return false;n.value=${JSON.stringify(value)};n.dispatchEvent(new Event('input',{bubbles:true}));n.dispatchEvent(new Event('change',{bubbles:true}));return true;})()`,'fill '+label);}
async function heading(title){await wait(`Array.from(document.querySelectorAll('h1,h2')).some(n=>n.textContent===${JSON.stringify(title)})`,'heading '+title);}
async function check(name,action){const start=Date.now();await action();checks.push({name,status:'PASS',elapsed_ms:Date.now()-start});console.error('PASS '+name);}
async function main(){
  fixture=spawn(process.env.CCX_PYTHON||'python3',['-B',path.join(__dirname,'cdp_installed_fixture.py')],{stdio:['pipe','pipe','pipe']});
  fixture.stderr.on('data',()=>{});
  const control=channel(fixture,fixture.stdout,fixture.stdin,'\n');fixture.control=control;
  const ready=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Installed CLI fixture startup timed out')),45000);control.events(value=>{if(value.ready){clearTimeout(timer);resolve(value);}});fixture.once('exit',()=>{clearTimeout(timer);reject(new Error('Installed CLI fixture exited during startup'));});});
  assert.equal(ready.install_exit,0);assert.equal(ready.start_exit,0);
  assert.equal(ready.duplicate_open_reused,true);
  profile=fs.mkdtempSync(path.join(os.tmpdir(),'ccx-installed-cdp-chrome-'));
  chrome=spawn(process.env.CCX_BROWSER_EXECUTABLE||'/usr/bin/google-chrome',['--headless=new','--remote-debugging-pipe','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe','pipe','pipe']});
  chrome.stderr.on('data',()=>{});cdp=channel(chrome,chrome.stdio[4],chrome.stdio[3],'\0');
  cdp.events(value=>{
    if(value.method==='Runtime.exceptionThrown')pageErrors.push(value.params.exceptionDetails.text);
    if(value.method==='Fetch.requestPaused'){const requestId=value.params.requestId;const allowed=/^http:\/\/127\.0\.0\.1:\d+\//.test(value.params.request.url);call(allowed?'Fetch.continueRequest':'Fetch.failRequest',allowed?{requestId}:{requestId,errorReason:'BlockedByClient'},value.sessionId).catch(()=>{});}
  });
  const version=await call('Browser.getVersion',{},null);const target=await call('Target.createTarget',{url:'about:blank'},null);session=(await call('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
  await call('Page.enable');await call('Runtime.enable');await call('Fetch.enable',{patterns:[{urlPattern:'http*',requestStage:'Request'}]});await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await check('Installed launcher starts actual backend and browser completes setup/project indexing',async()=>{
    await call('Page.navigate',{url:ready.url});await heading('Set up your workspace');
    assert.equal(await evaluate('location.hash.includes("bootstrap")'),false);assert.equal(await evaluate('document.cookie'),'');
    await click('Use this agent');await fill('Project directory',ready.project);await click('Preview project');await heading('Indexing preview');
    assert.equal((await control.send({operation:'snapshot'})).projects,0);
    await click('Register this project');await click('Start using workspace');await heading('Chat');
    await call('Page.reload');await heading('Chat');
    const state=await control.send({operation:'snapshot'});assert.equal(state.projects,1);assert.equal(state.setup_completed,true);assert.equal(state.provider_actions,0);providerActions=state.provider_actions;assert.equal(state.installed_import,true);
  });
  await check('Actual installed backend restart preserves setup and project across fresh browser bootstrap',async()=>{
    const state=await control.send({operation:'restart'});assert.equal(state.restart_exit,0);
    await call('Page.navigate',{url:'about:blank'});await wait(`location.href==='about:blank'`,'blank page');await call('Page.navigate',{url:state.url});await heading('Chat');
    assert.ok(await evaluate(`document.querySelector('[name=\"active-project\"]')?.selectedOptions[0]?.textContent.includes('approved project')`));
    const snapshot=await control.send({operation:'snapshot'});assert.equal(snapshot.projects,1);assert.equal(snapshot.setup_completed,true);assert.equal(snapshot.provider_actions,0);providerActions=snapshot.provider_actions;
  });
  await check('Isolated uninstall removes launcher and preserves registered project knowledge/database',async()=>{
    const state=await control.send({operation:'uninstall'});assert.equal(state.uninstall_exit,0);assert.equal(state.launcher_removed,true);assert.equal(state.database_preserved,true);assert.equal(state.projects_preserved,1);assert.equal(state.database_integrity,'ok');
  });
  assert.deepEqual(pageErrors,[]);return version.product;
}
(async()=>{
  const started=Date.now();let error,browser;
  try{browser=await main();}catch(problem){error=problem.message;console.error(error);}
  finally{
    if(chrome&&chrome.exitCode===null){try{await call('Browser.close',{},null);}catch{}await sleep(150);if(chrome.exitCode===null)chrome.kill('SIGTERM');}
    if(fixture&&fixture.exitCode===null){fixture.stdin.end();await sleep(300);}
    if(profile){try{fs.rmSync(profile,{recursive:true,force:true});}catch{}}
  }
  const report={status:error?'FAIL':'PASS',browser,sandbox_disabled:false,dependency_installs:false,product_installation:'disposable local prefix only',provider_action_records:providerActions,live_provider_operations_requested:false,elapsed_ms:Date.now()-started,checks,page_errors:pageErrors,...(error?{error}:{})};
  const output=process.argv.find(a=>a.startsWith('--report='));if(output)fs.writeFileSync(output.slice(9),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));process.exitCode=error?1:0;
})();
