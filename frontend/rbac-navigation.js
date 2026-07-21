(function(global){
  'use strict';

  const NAVIGATION=[
    ['老板驾驶舱','/index.html'],['员工中心','/control.html'],
    ['天统AI Brain Center','/brain-center.html'],['Brain Orchestrator','/brain-orchestrator.html'],
    ['店铺管理','/stores.html'],['京东数据中心','/jd-dashboard.html'],
    ['京东数据接入','/jd-integrations.html'],['AI员工工作台','/employee-workspace.html'],
    ['AI员工能力档案','/employee-capabilities.html'],['多模型路由中心','/model-routing.html'],
    ['AI工具调用权限中心','/tool-permissions.html'],['Tool Center 工具中心','/tool-center.html'],
    ['Tool Market 工具市场','/tool-market.html'],['Tool Router 工具路由中心','/tool-router.html'],
    ['SOP / Skill 绑定中心','/sop-skill-center.html'],['天赋：Skill / 插件赋能中心','/skill-plugin-center.html'],
    ['AI执行日志中心','/employee-activity-log.html'],['AI执行追溯中心','/employee-activity-trace.html'],
    ['AI任务中心','/task-center.html'],['AI自动派单中心','/auto-dispatch-center.html'],
    ['广告中心','/ads.html'],['今日数据录入','/metrics.html'],['Excel导入','/import.html'],
    ['AI素材中心','/ai-assets.html'],['AI工作流中心','/workflows.html'],
    ['AI员工名册','/ai-employees.html'],['天盾部署中心','/deploy-center.html'],
    ['账号资料中心','/account-center.html'],['模板中心','/template-center.html'],
    ['品牌中心','/brands.html'],['店铺分组','/store-groups.html'],
    ['天藏：知识资产中心','/knowledge-center.html'],['技能中心','/skill-center.html'],
    ['电脑执行中心','/computer-execution-center.html'],['天藏：知识资产中心','/tiancang.html'],
    ['测试设备中心','/device-center.html'],['系统设置','/settings.html']
  ];
  const ROUTE_PERMISSIONS={
    '/account-center.html':'menu.account_center','/ads.html':'menu.ads','/agent-runtime.html':'menu.ai_employees',
    '/ai-assets.html':'menu.ai_assets','/ai-employee-capability.html':'menu.ai_employees','/ai-employee-dashboard.html':'menu.ai_employees',
    '/ai-employee-detail.html':'menu.ai_employees','/ai-employee-growth-system.html':'menu.ai_employees','/ai-employee-growth.html':'menu.ai_employees',
    '/ai-employee-health.html':'menu.ai_employees','/ai-employee-memory.html':'menu.ai_employees','/ai-employees.html':'menu.ai_employees',
    '/ai-execution.html':'menu.ai_employees','/ai-workforce-center.html':'menu.ai_employees','/ai-workforce.html':'menu.ai_employees',
    '/alpha-workflow-detail.html':'menu.workflows','/alpha-workflow.html':'menu.workflows','/auto-dispatch-center.html':'menu.settings',
    '/brain-center.html':'menu.settings','/brain-orchestrator.html':'menu.settings','/brands.html':'menu.account_center',
    '/browser-readonly-test.html':'menu.computer_executor','/capability-center.html':'menu.ai_employees',
    '/computer-action-approval.html':'menu.computer_executor','/computer-action-test.html':'menu.computer_executor',
    '/computer-execution-center.html':'menu.computer_executor','/computer-execution-detail.html':'menu.computer_executor',
    '/computer-workflow-center.html':'menu.computer_executor','/computer-workflow-detail.html':'menu.computer_executor',
    '/control.html':'menu.employees','/dashboard/employees.html':'menu.dashboard','/dashboard/organization.html':'menu.dashboard',
    '/dashboard/overview.html':'menu.dashboard','/dashboard/workflow.html':'menu.dashboard','/deploy-center.html':'menu.settings',
    '/desktop-observer.html':'menu.computer_executor','/device-center.html':'menu.device_center','/device-monitoring.html':'menu.device_center',
    '/employee-activity-log.html':'menu.ai_employees','/employee-activity-trace.html':'menu.ai_employees',
    '/employee-capabilities.html':'menu.ai_employees','/employee-evolution-center.html':'menu.ai_employees','/employee-workspace.html':'menu.ai_employees',
    '/enterprise-brain-console.html':'menu.settings','/execution-quality.html':'menu.settings','/execution-records.html':'menu.settings',
    '/import.html':'menu.import','/index.html':'menu.dashboard','/jd-dashboard.html':'menu.jd_data','/jd-integrations.html':'menu.jd_data',
    '/knowledge-asset-center.html':'menu.knowledge_center','/knowledge-asset-detail.html':'menu.knowledge_center','/knowledge-center.html':'menu.knowledge_center',
    '/metrics.html':'menu.metrics','/model-routing.html':'menu.settings','/orchestrator.html':'menu.settings','/release-center.html':'menu.settings',
    '/research-records.html':'menu.settings','/review-learning-center.html':'menu.settings','/security-incidents.html':'menu.settings',
    '/security-ops-center.html':'menu.settings','/settings.html':'menu.settings','/skill-center.html':'menu.skills_center',
    '/skill-detail.html':'menu.skills_center','/skill-plugin-center.html':'menu.settings','/sop-skill-center.html':'menu.settings',
    '/store-groups.html':'menu.stores','/stores.html':'menu.stores','/task-center.html':'menu.settings','/template-center.html':'menu.account_center',
    '/tiancang.html':'menu.tiancang','/tool-center.html':'menu.settings','/tool-market.html':'menu.settings',
    '/tool-permissions.html':'menu.settings','/tool-router.html':'menu.settings','/workflows.html':'menu.workflows'
  };
  const KNOWN_PERMISSIONS=new Set(Object.values(ROUTE_PERMISSIONS));
  const FETCH_TIMEOUT_MS=10000;

  function normalize(path){return path==='/'?'/index.html':String(path||'').split(/[?#]/,1)[0]}
  function permissionsOf(user){
    if(!user||!Array.isArray(user.menus)||user.menus.length===0)return null;
    const permissions=new Set();
    for(const item of user.menus){
      if(!item||typeof item.permission!=='string'||!KNOWN_PERMISSIONS.has(item.permission)||permissions.has(item.permission))return null;
      permissions.add(item.permission);
    }
    return permissions;
  }
  function navigationFor(user){
    const permissions=permissionsOf(user);
    if(!permissions)return [];
    return NAVIGATION.filter(([,path])=>permissions.has(ROUTE_PERMISSIONS[path]));
  }
  function canOpen(user,path){
    const permission=ROUTE_PERMISSIONS[normalize(path)];
    const permissions=permissionsOf(user);
    return Boolean(permission&&permissions&&permissions.has(permission));
  }
  function element(name,text){const node=global.document.createElement(name);if(text!==undefined)node.textContent=text;return node}
  function renderNavigation(target,user,path=global.location&&global.location.pathname){
    const current=normalize(path);
    const links=navigationFor(user).map(([label,href])=>{
      const link=element('a',label);link.href=href;if(href===current)link.className='active';return link;
    });
    target.replaceChildren(...links);
  }
  function filterNavigation(user,root=global.document){
    const allowed=new Set(navigationFor(user).map(([,path])=>path));
    root.querySelectorAll('.menu a, nav a').forEach(link=>{
      const path=normalize(link.getAttribute('href'));if(ROUTE_PERMISSIONS[path]&&!allowed.has(path))link.remove();
    });
  }
  async function logout(){
    try{['token','tiantong_token','session','tiantong_session'].forEach(key=>global.localStorage.removeItem(key));global.sessionStorage.clear()}catch(error){}
    try{await global.fetch('/api/logout',{method:'POST',credentials:'include'})}catch(error){}
    global.location.href='/login.html';
  }
  function deny(){
    const aside=element('aside'),nav=element('nav'),main=element('main'),title=element('h1','无权访问'),button=element('button','退出登录');
    nav.className='menu';aside.appendChild(nav);button.id='rbacLogout';button.type='button';button.addEventListener('click',logout);
    main.append(title,button);global.document.body.replaceChildren(aside,main);
  }
  function domReady(){return global.document.readyState==='loading'?new Promise(resolve=>global.document.addEventListener('DOMContentLoaded',resolve,{once:true})):Promise.resolve()}
  async function identity(){
    const controller=new global.AbortController();
    const timer=global.setTimeout(()=>controller.abort(),FETCH_TIMEOUT_MS);
    try{
      const response=await global.fetch('/api/me',{credentials:'include',signal:controller.signal});
      if(!response.ok)throw new Error('identity unavailable');
      return await response.json();
    }finally{global.clearTimeout(timer)}
  }
  async function activateProtectedScripts(){
    global.__tiantongFrontSecurity=true;
    for(const source of global.document.querySelectorAll('script[data-rbac-protected]')){
      const script=global.document.createElement('script');
      for(const attribute of source.attributes||[]){
        if(!['type','data-rbac-protected'].includes(attribute.name))script.setAttribute(attribute.name,attribute.value);
      }
      if(source.src){script.async=false;await new Promise((resolve,reject)=>{script.onload=resolve;script.onerror=reject;source.parentNode.insertBefore(script,source.nextSibling)})}
      else{script.textContent=source.textContent;source.parentNode.insertBefore(script,source.nextSibling)}
    }
  }
  async function guard(){
    let user=null;
    try{
      await domReady();
      user=await identity();
      const path=normalize(global.location.pathname);
      const declared=global.document.documentElement.dataset.requiredMenu;
      if(!declared||ROUTE_PERMISSIONS[path]!==declared||!canOpen(user,path)){deny();return {allowed:false,user}}
      await activateProtectedScripts();
      global.document.body.classList.remove('auth-pending');
      global.logout=logout;
      global.document.querySelectorAll('.menu, nav#menu').forEach(target=>renderNavigation(target,user,path));
      filterNavigation(user);
      return {allowed:true,user};
    }catch(error){deny();return {allowed:false,user:null,error}}
    finally{global.document.documentElement.style.visibility='visible'}
  }

  global.document.documentElement.style.visibility='hidden';
  global.TiantongRbac={canOpen,filterNavigation,guard,logout,navigationFor,renderNavigation,routePermissions:ROUTE_PERMISSIONS};
  global.TiantongRbac.ready=guard();
})(window);
