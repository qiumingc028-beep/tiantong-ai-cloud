import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const guardScript=readFileSync(new URL('../frontend/rbac-navigation.js',import.meta.url),'utf8');

const designer={role:'designer',menus:[
  {label:'AI素材中心',href:'/ai-assets.html',permission:'menu.ai_assets'},
  {label:'AI工作流',href:'/workflows.html',permission:'menu.workflows'}
]};
const adminPermissions=['dashboard','employees','stores','jd_data','ads','metrics','import','ai_assets','skills_center','computer_executor','tiancang','workflows','ai_employees','account_center','knowledge_center','device_center','settings'];
const admin={role_code:'admin',menus:adminPermissions.map(permission=>({permission:`menu.${permission}`}))};

function page({path='/index.html',user=admin,status=200,reject=false}={}){
  const removed=[];
  const menu={innerHTML:''};
  const logoutButton={addEventListener(){}};
  const documentElement={style:{}};
  const body={innerHTML:'PROTECTED_PAGE_CONTENT'};
  const document={
    documentElement,
    body,
    querySelectorAll(){return []},
    getElementById(id){return id==='rbacLogout'?logoutButton:null}
  };
  const context={
    console,
    admin,
    designer,
    menu,
    document,
    location:{pathname:path,href:'',origin:'https://127.0.0.1:28443'},
    localStorage:{removeItem(key){removed.push(key)}},
    sessionStorage:{clear(){}},
    fetch:async url=>{
      if(reject)throw new Error('network failed');
      if(url==='/api/me')return {ok:status===200,status,json:async()=>user};
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
  for(const path of ['/index.html','/brain-center.html','/task-center.html','/tool-permissions.html','/deploy-center.html'])assert.ok(paths.includes(path),path);
});

test('owner alias keeps server-authorized navigation',()=>{
  const {run}=page();
  const count=run(`TiantongRbac.navigationFor({role:'boss',menus:admin.menus}).length`);
  assert.equal(count,37);
});

test('unauthenticated and unknown roles see no protected navigation',()=>{
  const {run}=page();
  assert.equal(run('TiantongRbac.navigationFor(null).length'),0);
  assert.equal(run(`TiantongRbac.navigationFor({role:'new_super_role',menus:admin.menus}).length`),0);
});

test('non-admin roles neither inherit admin routes nor lose authorized legacy routes',()=>{
  const {run}=page();
  for(const [role,permissions] of [
    ['operator',['dashboard','stores','jd_data','ads','metrics','import','workflows']],
    ['customer_service',['dashboard','metrics']],
    ['finance',['dashboard','metrics','import']]
  ]){
    const paths=run(`TiantongRbac.navigationFor({role:${JSON.stringify(role)},menus:${JSON.stringify(permissions.map(permission=>({permission:`menu.${permission}`})))} }).map(([,path])=>path)`);
    for(const forbidden of ['/brain-center.html','/brain-orchestrator.html','/task-center.html','/auto-dispatch-center.html'])assert.ok(!paths.includes(forbidden),`${role}:${forbidden}`);
    if(role==='operator')for(const allowed of ['/jd-integrations.html','/template-center.html','/brands.html','/store-groups.html'])assert.ok(paths.includes(allowed),`${role}:${allowed}`);
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
  assert.doesNotMatch(context.document.body.innerHTML,/PROTECTED_PAGE_CONTENT/);
  assert.match(context.document.body.innerHTML,/无权访问/);
});

test('authorized direct route becomes visible after the guard',async()=>{
  const {context,run}=page({path:'/ai-assets.html',user:designer});
  const result=await run('TiantongRbac.ready');
  assert.equal(result.allowed,true);
  assert.equal(context.document.body.innerHTML,'PROTECTED_PAGE_CONTENT');
  assert.equal(context.document.documentElement.style.visibility,'visible');
});

test('account switch replaces privileged navigation without residue',()=>{
  const {menu,run}=page();
  run('TiantongRbac.renderNavigation(menu,admin)');
  assert.match(menu.innerHTML,/tool-permissions\.html/);
  run('TiantongRbac.renderNavigation(menu,designer)');
  assert.match(menu.innerHTML,/ai-assets\.html/);
  assert.doesNotMatch(menu.innerHTML,/tool-permissions\.html|deploy-center\.html|control\.html/);
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
