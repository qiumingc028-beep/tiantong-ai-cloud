import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {join,relative} from 'node:path';
import test from 'node:test';
import vm from 'node:vm';

const guardScript=readFileSync(new URL('../frontend/rbac-navigation.js',import.meta.url),'utf8');
const routePermissions=Object.fromEntries([...guardScript.matchAll(/'(\/[^']+\.html)':'(menu\.[^']+)'/g)].map(match=>[match[1],match[2]]));

const designer={role:'designer',menus:[
  {label:'AI素材中心',href:'/ai-assets.html',permission:'menu.ai_assets'},
  {label:'AI工作流',href:'/workflows.html',permission:'menu.workflows'}
]};
const adminPermissions=['dashboard','employees','stores','jd_data','ads','metrics','import','ai_assets','skills_center','computer_executor','tiancang','workflows','ai_employees','account_center','knowledge_center','device_center','settings'];
const admin={role_code:'admin',menus:adminPermissions.map(permission=>({permission:`menu.${permission}`}))};

function page({path='/index.html',user=admin,status=200,reject=false,timeout=false,protectedScript=false,externalScript=false,externalFailure=false,deferExternal=false}={}){
  const removed=[];
  const storage=new Map();
  let context;
  const serialize=node=>node.href||node.textContent||(node.children||[]).map(serialize).join('|');
  const makeNode=name=>({
    name,children:[],attributes:{},listeners:{},textContent:'',className:'',href:'',innerHTML:'',removed:false,
    addEventListener(type,handler){this.listeners[type]=handler},setAttribute(key,value){this.attributes[key]=value;if(key==='src')this.src=value},
    remove(){this.removed=true},
    appendChild(...nodes){this.children.push(...nodes)},append(...nodes){this.children.push(...nodes)},
    replaceChildren(...nodes){this.children=[...nodes];this.innerHTML=nodes.map(serialize).join('|')}
  });
  const menu=makeNode('nav');
  const logoutButton=makeNode('button');
  const documentElement={style:{},dataset:{requiredMenu:routePermissions[path]}};
  const body=makeNode('body');body.innerHTML='PROTECTED_PAGE_CONTENT';
  body.classList={removed:[],remove(name){this.removed.push(name)}};
  const protectedScripts=protectedScript?[{
    attributes:[],src:'',textContent:'initializerCount += 1',
    parentNode:{insertBefore(script){vm.runInContext(script.textContent,context)}}
  }]:externalScript?[{
    attributes:[{name:'src',value:'/alpha-workflow.js'},{name:'defer',value:''}],src:'/alpha-workflow.js',textContent:'',
    parentNode:{insertBefore(script){context.externalAttributes=script.attributes;vm.runInContext(script.textContent,context)}}
  }]:[];
  const document={
    listeners:{},registrations:[],liveActions:new Set(),
    readyState:'complete',
    documentElement,
    body,
    addEventListener(type,handler){this.listeners[type]=handler;this.registrations.push(type)},
    removeEventListener(type){delete this.listeners[type]},
    querySelector(selector){const match=selector.match(/^\[data-rbac-action="([a-z0-9-]+)"\]$/i);return match&&this.liveActions.has(match[1])?{}:null},
    querySelectorAll(selector){return selector==='script[data-rbac-protected]'?protectedScripts:[]},
    createElement:makeNode,
    getElementById(id){return id==='rbacLogout'?logoutButton:null}
  };
  context={
    console,
    admin,
    designer,
    menu,
    document,
    location:{pathname:path,href:'',origin:'https://127.0.0.1:28443'},
    identityUser:user,
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,String(value)),removeItem(key){removed.push(key);storage.delete(key)}},
    sessionStorage:{clear(){}},
    initializerCount:0,
    externalLoads:0,
    externalExecuted:0,
    externalAttributes:null,
    pendingExternalScripts:[],
    windowListeners:{},
    addEventListener(type,handler){this.windowListeners[type]=handler},
    dynamicObserver:null,
    MutationObserver:class{
      constructor(callback){this.callback=callback;context.dynamicObserver=this}
      observe(){}
      disconnect(){this.disconnected=true}
    },
    AbortController,
    setTimeout:timeout?(callback=>{callback();return 1}):setTimeout,
    clearTimeout,
    fetch:async (url,options={})=>{
      if(reject)throw new Error('network failed');
      if(options.signal&&options.signal.aborted)throw new Error('request aborted');
      if(url==='/api/me')return {ok:status===200,status,json:async()=>context.identityUser};
      if(url==='/alpha-workflow.js'){
        context.externalLoads+=1;
        const response={ok:!externalFailure,status:externalFailure?500:200,text:async()=>'externalExecuted += 1'};
        if(deferExternal)return await new Promise((resolve,rejectLoad)=>{
          const pending={aborted:false,resolve:()=>resolve(response)};
          options.signal.addEventListener('abort',()=>{pending.aborted=true;rejectLoad(new Error('request aborted'))},{once:true});
          context.pendingExternalScripts.push(pending);
        });
        return response;
      }
      return {ok:true,status:200,json:async()=>({})};
    }
  };
  context.window=context;
  vm.createContext(context);
  vm.runInContext(guardScript,context);
  return {context,menu,removed,run:code=>vm.runInContext(code,context)};
}

test('designer sees only server-authorized navigation',()=>{
  const {menu,run}=page({path:'/ai-assets.html',user:designer});
  run('TiantongRbac.renderNavigation(menu,designer)');
  assert.match(menu.innerHTML,/ai-assets\.html|workflows\.html/);
  assert.doesNotMatch(menu.innerHTML,/control\.html|stores\.html|tool-permissions\.html|deploy-center\.html/);
});

test('administrator keeps the prior legitimate navigation set',()=>{
  const {run}=page();
  const paths=run('TiantongRbac.navigationFor(admin).map(([,path])=>path)');
  for(const path of ['/index.html','/settings.html','/control.html','/ai-assets.html'])assert.ok(paths.includes(path),path);
  for(const path of ['/brain-center.html','/task-center.html','/tool-permissions.html','/deploy-center.html'])assert.equal(run(`TiantongRbac.canOpen(admin,'${path}')`),true,path);
});

test('role aliases neither add nor remove server-authorized navigation',()=>{
  const {run}=page();
  const count=run(`TiantongRbac.navigationFor({role:'boss',menus:admin.menus}).length`);
  assert.equal(count,37);
});

test('unauthenticated users fail closed while unknown roles use only server menus',()=>{
  const {run}=page();
  assert.equal(run('TiantongRbac.navigationFor(null).length'),0);
  assert.equal(run(`TiantongRbac.navigationFor({role:'new_super_role',menus:admin.menus}).length`),37);
});

test('non-admin roles neither inherit admin routes nor lose authorized legacy routes',()=>{
  const {run}=page();
  for(const [role,permissions] of [
    ['operator',['dashboard','stores','jd_data','ads','metrics','import','workflows','account_center']],
    ['customer_service',['dashboard','metrics']],
    ['finance',['dashboard','metrics','import']]
  ]){
    const expression=`{role:${JSON.stringify(role)},menus:${JSON.stringify(permissions.map(permission=>({permission:`menu.${permission}`})))} }`;
    for(const forbidden of ['/brain-center.html','/brain-orchestrator.html','/task-center.html','/auto-dispatch-center.html'])assert.equal(run(`TiantongRbac.canOpen(${expression},'${forbidden}')`),false,`${role}:${forbidden}`);
    if(role==='operator')for(const allowed of ['/jd-integrations.html','/template-center.html','/brands.html','/store-groups.html'])assert.equal(run(`TiantongRbac.canOpen(${expression},'${allowed}')`),true,`${role}:${allowed}`);
  }
});

test('missing and malformed permissions fail closed',()=>{
  const {run}=page();
  const count=run(`TiantongRbac.navigationFor({role:'designer',menus:[
    {href:'/control.html'},
    {permission:'admin.everything'},
    {permission:null}
  ]}).length`);
  assert.equal(count,0);
  assert.equal(run(`TiantongRbac.navigationFor({role:'admin'}).length`),0);
  assert.equal(run(`TiantongRbac.navigationFor({role:'operator',menus:[]}).length`),0);
  assert.equal(run(`TiantongRbac.navigationFor({role:'admin',menus:[{permission:null}]}).length`),0);
});

test('direct unauthorized admin route never exposes protected content',async()=>{
  const {context,run}=page({path:'/tool-permissions.html',user:designer});
  const result=await run('TiantongRbac.ready');
  assert.equal(result.allowed,false);
  assert.doesNotMatch(context.document.body.innerHTML,/PROTECTED_PAGE_CONTENT/);
  assert.match(context.document.body.innerHTML,/无权访问/);
});

test('identity loading failure denies before revealing protected content',async()=>{
  const {context,run}=page({path:'/index.html',status:500});
  const result=await run('TiantongRbac.ready');
  assert.equal(result.allowed,false);
  assert.deepEqual(context.document.registrations,[]);
  assert.doesNotMatch(context.document.body.innerHTML,/PROTECTED_PAGE_CONTENT/);
  assert.match(context.document.body.innerHTML,/无权访问/);
});

test('identity timeout fails closed before protected initialization',async()=>{
  const {context,run}=page({path:'/index.html',timeout:true});
  const result=await run('TiantongRbac.ready');
  assert.equal(result.allowed,false);
  assert.doesNotMatch(context.document.body.innerHTML,/PROTECTED_PAGE_CONTENT/);
});

test('malformed and unknown menu responses deny the direct route',async()=>{
  for(const menus of [null,[{permission:null}],[{permission:'menu.dashboard'},{permission:'menu.unknown'}]]){
    const {context,run}=page({path:'/index.html',user:{role:'owner',menus}});
    assert.equal((await run('TiantongRbac.ready')).allowed,false);
    assert.deepEqual(context.document.registrations,[]);
  }
});

test('permission loading starts with the protected document hidden',()=>{
  const {context}=page({path:'/index.html'});
  assert.equal(context.document.documentElement.style.visibility,'hidden');
});

test('authorized direct route becomes visible after the guard',async()=>{
  const {context,run}=page({path:'/ai-assets.html',user:designer,protectedScript:true});
  const result=await run('TiantongRbac.ready');
  assert.equal(result.allowed,true);
  assert.equal(context.initializerCount,1);
  assert.deepEqual(context.document.body.classList.removed,['auth-pending']);
  assert.equal(context.document.body.innerHTML,'PROTECTED_PAGE_CONTENT');
  assert.equal(context.document.documentElement.style.visibility,'visible');
});

test('denied routes never activate protected page scripts',async()=>{
  const {context,run}=page({path:'/settings.html',user:designer,protectedScript:true});
  assert.equal((await run('TiantongRbac.ready')).allowed,false);
  assert.equal(context.initializerCount,0);
  assert.deepEqual(Object.keys(context.document.listeners),[]);
});

test('authorized external protected scripts load once through a cancellable boundary',async()=>{
  const {context,run}=page({path:'/alpha-workflow.html',user:designer,externalScript:true});
  assert.equal((await run('TiantongRbac.ready')).allowed,true);
  assert.equal(context.externalLoads,1);
  assert.equal(context.externalExecuted,1);
  assert.deepEqual(context.externalAttributes,{});
});

test('external script load failure remains denied and a denied route never requests it',async()=>{
  const failed=page({path:'/alpha-workflow.html',user:designer,externalScript:true,externalFailure:true});
  assert.equal((await failed.run('TiantongRbac.ready')).allowed,false);
  assert.equal(failed.context.externalLoads,1);
  const denied=page({path:'/alpha-workflow.html',user:{role:'designer',menus:[{permission:'menu.ai_assets'}]},externalScript:true});
  assert.equal((await denied.run('TiantongRbac.ready')).allowed,false);
  assert.equal(denied.context.externalLoads,0);
});

test('account switch replaces privileged navigation without residue',()=>{
  const {menu,run}=page();
  run('TiantongRbac.renderNavigation(menu,admin)');
  assert.match(menu.innerHTML,/tool-permissions\.html/);
  run('TiantongRbac.renderNavigation(menu,designer)');
  assert.match(menu.innerHTML,/ai-assets\.html/);
  assert.doesNotMatch(menu.innerHTML,/tool-permissions\.html|settings\.html|control\.html/);
});

test('logout clears cached identity data before redirect',async()=>{
  const {context,removed,run}=page();
  await run('TiantongRbac.logout()');
  assert.deepEqual(removed,['token','tiantong_token','session','tiantong_session']);
  assert.equal(context.location.href,'/login.html');
});

test('every protected navigation destination loads the shared guard first',()=>{
  const {run}=page();
  const paths=run('TiantongRbac.navigationFor(admin).map(([,path])=>path)');
  for(const path of paths){
    const file=new URL(`../frontend${path}`,import.meta.url);
    const html=readFileSync(file,'utf8');
    assert.match(html,/<head>[\s\S]*?<style>html\{visibility:hidden\}<\/style><script src="\/rbac-navigation\.js"><\/script>/,path);
  }
});

test('role fields cannot grant a route absent from server menus',()=>{
  const {run}=page();
  const user={role:'owner',role_code:'admin',menus:[{permission:'menu.ai_assets'}]};
  assert.equal(run(`TiantongRbac.canOpen(${JSON.stringify(user)},'/settings.html')`),false);
  assert.equal(run(`TiantongRbac.canOpen(${JSON.stringify(user)},'/brain-center.html')`),false);
});

test('unknown server menu identifiers invalidate the complete permission response',()=>{
  const {run}=page();
  const user={role:'admin',menus:[{permission:'menu.dashboard'},{permission:'menu.future_unknown'}]};
  assert.equal(run(`TiantongRbac.navigationFor(${JSON.stringify(user)}).length`),0);
  assert.equal(run(`TiantongRbac.canOpen(${JSON.stringify(user)},'/index.html')`),false);
});

test('all non-login HTML entries declare a fail-closed preinitialization guard',()=>{
  const root=new URL('../frontend/',import.meta.url);
  const files=[];
  const visit=dir=>{
    for(const entry of readdirSync(dir,{withFileTypes:true})){
      const path=join(dir.pathname,entry.name);
      if(entry.isDirectory())visit(new URL(`${entry.name}/`,dir));
      else if(entry.name.endsWith('.html'))files.push(path);
    }
  };
  visit(root);
  assert.equal(files.length,77);
  for(const file of files){
    const name=relative(root.pathname,file);
    const html=readFileSync(file,'utf8');
    if(name==='login.html'){
      assert.doesNotMatch(html,/data-required-menu=/);
      continue;
    }
    assert.match(html,/<html\b[^>]*\bdata-required-menu="menu\.[a-z_]+"/i,name);
    assert.match(html,/<head>\s*<style>html\{visibility:hidden\}<\/style><script src="\/rbac-navigation\.js"><\/script>/i,name);
    const executableScripts=[...html.matchAll(/<script\b(?![^>]*src="\/rbac-navigation\.js")[^>]*>/gi)]
      .map(match=>match[0])
      .filter(tag=>!tag.includes('data-rbac-protected'));
    assert.deepEqual(executableScripts,[],`${name}: protected scripts must stay inert until authorization`);
  }
});

test('activated page scripts contain no client role-to-route authority',()=>{
  const root=new URL('../frontend/',import.meta.url);
  const visit=dir=>readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?visit(new URL(`${entry.name}/`,dir)):[new URL(entry.name,dir)]);
  for(const file of visit(root).filter(file=>file.pathname.endsWith('.html'))){
    const html=readFileSync(file,'utf8');
    for(const match of html.matchAll(/<script\b[^>]*data-rbac-protected[^>]*>([\s\S]*?)<\/script>/gi)){
      const script=match[1];
      if(script.includes('__tiantongFrontSecurity'))continue;
      assert.doesNotMatch(script,/ROLE_ACCESS|pageRole|canOpenDeploy|function canOpen\([^)]*(?:role|r),href/,file.pathname);
    }
  }
});

test('all 316 protected-page handlers are migrated without inline event code',()=>{
  const root=new URL('../frontend/',import.meta.url);
  const visit=dir=>readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?visit(new URL(`${entry.name}/`,dir)):[new URL(entry.name,dir)]);
  const files=visit(root).filter(file=>file.pathname.endsWith('.html')&&!file.pathname.endsWith('/login.html'));
  let migrated=0,literalActions=0,dynamicActions=0,sharedLogoutBindings=0;
  const migratedHandlerIds=new Set();
  for(const file of files){
    const html=readFileSync(file,'utf8');
    assert.doesNotMatch(html,/\bon[a-z]+\s*=/i,file.pathname);
    if(html.includes('data-rbac-action=')){
      assert.doesNotMatch(html,/javascript\s*:/i,file.pathname);
      assert.doesNotMatch(html,/\beval\s*\(|\bnew\s+Function\b/i,file.pathname);
      assert.doesNotMatch(html,/setAttribute\s*\(\s*['"]on|\.on[a-z]+\s*=/i,file.pathname);
    }
    migrated+=(html.match(/data-rbac-action\s*=/g)||[]).length;
    const literal=[...html.matchAll(/data-rbac-action="([a-z0-9-]+)"/gi)].map(match=>match[1]);
    const definitions=new Set([...html.matchAll(/"([a-z0-9-]+)":\["(?:click|change|input)",function\(event\)/gi)].map(match=>match[1]));
    for(const id of literal){
      assert.ok(definitions.has(id),`${file.pathname}: missing binding for ${id}`);
      assert.equal(migratedHandlerIds.has(id),false,`${file.pathname}: duplicate manifest handler ${id}`);
      migratedHandlerIds.add(id);
    }
    literalActions+=literal.length;
    const dynamic=[...html.matchAll(/TiantongRbac\.registerDynamicAction\("([a-z0-9-]+)","(click|change|input)",function\(event\)/gi)];
    dynamicActions+=dynamic.length;
    for(const match of dynamic){
      assert.equal(migratedHandlerIds.has(match[1]),false,`${file.pathname}: duplicate manifest handler ${match[1]}`);
      migratedHandlerIds.add(match[1]);
    }
    sharedLogoutBindings+=(html.match(/return TiantongRbac\.logout\(\)/g)||[]).length;
    for(const match of html.matchAll(/<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi))assert.doesNotThrow(()=>new vm.Script(match[1]),file.pathname);
  }
  assert.equal(files.length,76);
  assert.equal(migrated,316);
  assert.equal(literalActions,252);
  assert.equal(dynamicActions,64);
  assert.equal(migratedHandlerIds.size,316);
  assert.equal(sharedLogoutBindings,41);
  assert.equal(files.reduce((count,file)=>count+(readFileSync(file,'utf8').match(/-disabled-entry/g)||[]).length,0),20);
  const research=readFileSync(new URL('../frontend/research-records.html',import.meta.url),'utf8');
  assert.equal((research.match(/TiantongRbac\.registerDynamicAction\(/g)||[]).length,1);
});

test('shared guard contains no dynamic event attributes or string execution',()=>{
  assert.doesNotMatch(guardScript,/\.on[a-z]+\s*=/i);
  assert.doesNotMatch(guardScript,/setAttribute\s*\(\s*['"]on/i);
  assert.doesNotMatch(guardScript,/\beval\s*\(|\bnew\s+Function\b/);
});

test('authorized actions preserve behavior and bind each event type once',async()=>{
  const {context,run}=page({path:'/index.html'});
  assert.deepEqual(context.document.registrations,[]);
  assert.equal((await run('TiantongRbac.ready')).allowed,true);
  run(`globalThis.actionCalls=0;TiantongRbac.bindActions({fixture:['click',function(){actionCalls+=1;return false}]})`);
  run(`TiantongRbac.bindActions({fixture:['click',function(){actionCalls+=1;return false}]})`);
  assert.deepEqual(context.document.registrations,['click']);
  const flags={prevented:false,stopped:false};
  const target={getAttribute:name=>name==='data-rbac-action'?'fixture':null,parentElement:null};
  context.document.listeners.click({type:'click',target,preventDefault(){flags.prevented=true},stopPropagation(){flags.stopped=true}});
  assert.equal(context.actionCalls,1);
  assert.deepEqual(flags,{prevented:true,stopped:true});
  const dynamicId=run(`TiantongRbac.registerDynamicAction('fixture-change','change',function(){actionCalls+=this.value})`);
  context.document.liveActions.add(dynamicId);
  await Promise.resolve();
  const dynamicTarget={value:4,getAttribute:name=>name==='data-rbac-action'?dynamicId:null,parentElement:null};
  context.document.listeners.change({type:'change',target:dynamicTarget,preventDefault(){},stopPropagation(){}});
  assert.equal(context.actionCalls,5);
  assert.deepEqual(context.document.registrations,['click','change']);
});

test('concurrent authorization shares one activation promise',async()=>{
  const {context,run}=page({path:'/alpha-workflow.html',user:designer,externalScript:true,deferExternal:true});
  const second=run('TiantongRbac.guard()');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(context.externalLoads,1);
  assert.equal(context.pendingExternalScripts.length,1);
  context.pendingExternalScripts[0].resolve();
  assert.equal((await run('TiantongRbac.ready')).allowed,true);
  assert.equal((await second).allowed,true);
});

test('dynamic rerender removes stale closures without duplicate listeners',async()=>{
  const {context,run}=page({path:'/index.html'});
  assert.equal((await run('TiantongRbac.ready')).allowed,true);
  run('globalThis.actionCalls=0');
  const first=run(`TiantongRbac.registerDynamicAction('row-detail','click',function(){actionCalls+=1})`);
  context.document.liveActions.add(first);
  await Promise.resolve();
  context.document.liveActions.clear();
  const second=run(`TiantongRbac.registerDynamicAction('row-detail','click',function(){actionCalls+=10})`);
  context.document.liveActions.add(second);
  await Promise.resolve();
  assert.notEqual(first,second);
  const dispatch=id=>context.document.listeners.click({type:'click',target:{getAttribute:name=>name==='data-rbac-action'?id:null,parentElement:null},preventDefault(){},stopPropagation(){}});
  dispatch(second);
  assert.equal(context.actionCalls,10);
  assert.deepEqual(context.document.registrations,['click']);
  context.document.liveActions.clear();
  context.dynamicObserver.callback();
  await Promise.resolve();
  dispatch(second);
  assert.equal(context.actionCalls,10);
});

test('one manifest handler safely binds multiple rendered instances',async()=>{
  const {context,run}=page({path:'/index.html'});
  assert.equal((await run('TiantongRbac.ready')).allowed,true);
  run('globalThis.actionCalls=0');
  const first=run(`TiantongRbac.registerDynamicAction('row-toggle','click',function(){actionCalls+=1})`);
  const second=run(`TiantongRbac.registerDynamicAction('row-toggle','click',function(){actionCalls+=10})`);
  context.document.liveActions.add(first);context.document.liveActions.add(second);
  await Promise.resolve();
  const dispatch=id=>context.document.listeners.click({type:'click',target:{getAttribute:name=>name==='data-rbac-action'?id:null,parentElement:null},preventDefault(){},stopPropagation(){}});
  dispatch(first);dispatch(second);
  assert.equal(context.actionCalls,11);
  assert.deepEqual(context.document.registrations,['click']);
});

test('authorization revocation cancels a pending external activation',async()=>{
  const {context,run}=page({path:'/alpha-workflow.html',user:designer,externalScript:true,deferExternal:true});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(context.pendingExternalScripts.length,1);
  const pending=context.pendingExternalScripts[0];
  await run('TiantongRbac.logout()');
  assert.equal(pending.aborted,true);
  assert.equal(context.externalExecuted,0);
  assert.equal((await run('TiantongRbac.ready')).allowed,false);
});

test('logout, token changes, and account changes clear authorized bindings',async()=>{
  for(const change of ['logout','token','account']){
    const {context,run}=page({path:'/ai-assets.html',user:{id:1,...admin,menus:[{permission:'menu.ai_assets'}]}});
    assert.equal((await run('TiantongRbac.ready')).allowed,true);
    run(`TiantongRbac.bindActions({fixture:['click',function(){}]})`);
    assert.deepEqual(context.document.registrations,['click']);
    if(change==='logout')await run('TiantongRbac.logout()');
    else{
      if(change==='token')context.localStorage.setItem('token','replacement');
      else context.identityUser={id:2,...designer};
      assert.equal((await run('TiantongRbac.guard()')).allowed,false);
    }
    assert.deepEqual(Object.keys(context.document.listeners),[],change);
  }
});

test('focus and BFCache restoration automatically revalidate without duplicate activation',async()=>{
  const same=page({path:'/ai-assets.html',user:{id:1,...designer},protectedScript:true});
  assert.equal((await same.run('TiantongRbac.ready')).allowed,true);
  assert.equal((await same.context.windowListeners.pageshow({type:'pageshow',persisted:true})).allowed,true);
  assert.equal(same.context.initializerCount,1);

  const changed=page({path:'/ai-assets.html',user:{id:1,...designer}});
  assert.equal((await changed.run('TiantongRbac.ready')).allowed,true);
  changed.run(`TiantongRbac.bindActions({fixture:['click',function(){}]})`);
  changed.context.identityUser={id:2,...designer};
  assert.equal((await changed.context.windowListeners.focus({type:'focus'})).allowed,false);
  assert.deepEqual(Object.keys(changed.context.document.listeners),[]);
  assert.match(changed.context.document.body.innerHTML,/无权访问/);

  const cleared=page({path:'/ai-assets.html',user:{id:1,...designer}});
  assert.equal((await cleared.run('TiantongRbac.ready')).allowed,true);
  cleared.context.identityUser={id:2,...designer};
  assert.equal((await cleared.context.windowListeners.storage({type:'storage',key:null})).allowed,false);
});
