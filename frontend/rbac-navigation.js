(function(global){
  'use strict';

  const ADMIN_ROLES=['owner','admin'];
  const ACCOUNT_ROLES=['owner','admin','operator'];
  const navigation=[
    ['老板驾驶舱','/index.html','menu.dashboard'],
    ['老板控制中心','/control.html','menu.employees'],
    ['天统AI Brain Center','/brain-center.html',null,ADMIN_ROLES],
    ['Brain Orchestrator','/brain-orchestrator.html',null,ADMIN_ROLES],
    ['店铺管理','/stores.html','menu.stores'],
    ['京东60店数据中心','/jd-dashboard.html','menu.jd_data'],
    ['京东数据接入','/jd-integrations.html','menu.jd_data',ACCOUNT_ROLES],
    ['AI员工工作台','/employee-workspace.html',null,ADMIN_ROLES],
    ['AI员工能力档案','/employee-capabilities.html',null,ADMIN_ROLES],
    ['多模型路由中心','/model-routing.html',null,ADMIN_ROLES],
    ['AI工具调用权限中心','/tool-permissions.html',null,ADMIN_ROLES],
    ['Tool Center 工具中心','/tool-center.html',null,ADMIN_ROLES],
    ['Tool Market 工具市场','/tool-market.html',null,ADMIN_ROLES],
    ['Tool Router 工具路由中心','/tool-router.html',null,ADMIN_ROLES],
    ['SOP / Skill 绑定中心','/sop-skill-center.html',null,ADMIN_ROLES],
    ['天赋：Skill / 插件赋能中心','/skill-plugin-center.html',null,ADMIN_ROLES],
    ['AI执行日志中心','/employee-activity-log.html',null,ADMIN_ROLES],
    ['AI执行追溯中心','/employee-activity-trace.html',null,ADMIN_ROLES],
    ['AI任务中心','/task-center.html',null,ADMIN_ROLES],
    ['AI自动派单中心','/auto-dispatch-center.html',null,ADMIN_ROLES],
    ['广告中心','/ads.html','menu.ads'],
    ['今日数据录入','/metrics.html','menu.metrics'],
    ['Excel导入','/import.html','menu.import'],
    ['AI素材中心','/ai-assets.html','menu.ai_assets'],
    ['AI工作流中心','/workflows.html','menu.workflows'],
    ['AI员工名册','/ai-employees.html','menu.ai_employees'],
    ['天盾部署中心','/deploy-center.html',null,ADMIN_ROLES],
    ['账号资料中心','/account-center.html','menu.account_center'],
    ['模板中心','/template-center.html',null,ACCOUNT_ROLES],
    ['品牌中心','/brands.html',null,ACCOUNT_ROLES],
    ['店铺分组','/store-groups.html',null,ACCOUNT_ROLES],
    ['天藏：知识资产中心','/knowledge-center.html','menu.knowledge_center'],
    ['技能中心','/skill-center.html','menu.skills_center'],
    ['电脑执行中心','/computer-execution-center.html','menu.computer_executor'],
    ['天藏：知识资产中心','/tiancang.html','menu.tiancang'],
    ['测试设备中心','/device-center.html','menu.device_center'],
    ['系统设置','/settings.html','menu.settings']
  ];
  const roleAliases={boss:'owner',administrator:'admin'};
  const knownRoles=new Set(['owner','admin','operator','customer_service','designer','editor','finance']);
  const protectedRoutes=new Set(navigation.map(([,path])=>path));

  function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]))}
  function normalize(path){return path==='/'?'/index.html':String(path||'').split(/[?#]/,1)[0]}
  function roleOf(user){const role=String((user&&(user.role_code||user.role))||'').trim();return roleAliases[role]||role}
  function permissionsOf(user){
    if(!knownRoles.has(roleOf(user))||!Array.isArray(user&&user.menus))return new Set();
    return new Set(user.menus.flatMap(item=>item&&typeof item.permission==='string'&&item.permission.startsWith('menu.')?[item.permission]:[]));
  }
  function navigationFor(user){
    const permissions=permissionsOf(user),role=roleOf(user);
    if(!knownRoles.has(role)||!Array.isArray(user&&user.menus)||permissions.size===0)return [];
    return navigation.filter(([,path,permission,roles])=>protectedRoutes.has(path)&&(!permission||permissions.has(permission))&&(!roles||roles.includes(role)));
  }
  function canOpen(user,path){const target=normalize(path);return navigationFor(user).some(([,route])=>route===target)}
  function renderNavigation(target,user,path=global.location&&global.location.pathname){
    const current=normalize(path);
    target.innerHTML=navigationFor(user).map(([label,href])=>`<a class="${href===current?'active':''}" href="${escapeHtml(href)}">${escapeHtml(label)}</a>`).join('');
  }
  function filterNavigation(user,root=global.document){
    const allowed=new Set(navigationFor(user).map(([,path])=>path));
    root.querySelectorAll('.menu a, nav a').forEach(link=>{const path=normalize(link.getAttribute('href'));if(protectedRoutes.has(path)&&!allowed.has(path))link.remove()});
  }
  async function logout(){
    try{['token','tiantong_token','session','tiantong_session'].forEach(key=>global.localStorage.removeItem(key));global.sessionStorage.clear()}catch(e){}
    try{await global.fetch('/api/logout',{method:'POST',credentials:'include'})}catch(e){}
    global.location.href='/login.html';
  }
  function deny(user){
    const links=navigationFor(user).map(([label,href])=>`<a href="${escapeHtml(href)}">${escapeHtml(label)}</a>`).join('');
    global.document.body.innerHTML=`<aside><nav class="menu">${links}</nav></aside><main><h1>无权访问</h1><button id="rbacLogout" type="button">退出登录</button></main>`;
    global.document.getElementById('rbacLogout').addEventListener('click',logout);
  }
  function domReady(){return global.document.readyState==='loading'?new Promise(resolve=>global.document.addEventListener('DOMContentLoaded',resolve,{once:true})):Promise.resolve()}
  async function guard(){
    let user=null;
    try{
      await domReady();
      const response=await global.fetch('/api/me',{credentials:'include'});
      if(!response.ok)throw new Error('identity unavailable');
      user=await response.json();
      if(!canOpen(user,global.location.pathname)){deny(user);return {allowed:false,user}}
      filterNavigation(user);
      return {allowed:true,user};
    }catch(error){deny(null);return {allowed:false,user:null,error}}
    finally{global.document.documentElement.style.visibility='visible'}
  }

  global.document.documentElement.style.visibility='hidden';
  global.TiantongRbac={canOpen,filterNavigation,guard,logout,navigationFor,renderNavigation};
  global.TiantongRbac.ready=guard();
})(window);
