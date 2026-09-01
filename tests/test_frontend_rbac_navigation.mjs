import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync,readdirSync} from 'node:fs';
import {join,relative} from 'node:path';
import {createRequire} from 'node:module';
import test from 'node:test';
import vm from 'node:vm';

const securityRequire=createRequire(new URL('../tools/frontend-security/package.json',import.meta.url));
const {parse}=securityRequire('acorn');
const guardScript=readFileSync(new URL('../frontend/rbac-navigation.js',import.meta.url),'utf8');
const routePermissions=Object.fromEntries([...guardScript.matchAll(/'(\/[^']+\.html)':'(menu\.[^']+)'/g)].map(match=>[match[1],match[2]]));
const authorizationContract=Object.freeze({
  identityFields:new Set(['role','role_code','roleCode']),
  serverAuthorityFields:new Set(['menus']),
  authorizationStateFields:new Set(['permissions','routes','features','privileges','allowedActions','canAccess']),
  uiGateFields:new Set(['hidden','disabled','innerHTML','display','visibility']),
  uiGateMethods:new Set(['replaceChildren']),
  uiGateAttributeMethods:new Set(['removeAttribute','toggleAttribute']),
  uiGateStyleMethods:new Set(['removeProperty']),
  authorizationActionMethods:new Set(['addEventListener']),
  navigationFields:new Set(['href']),
  authorityGlobals:new Set(['TiantongRbac']),
  authorityStorageGlobals:new Set(['localStorage','sessionStorage']),
  uiGateClassNames:new Set(['hidden','auth-pending'])
});

function* astChildren(node){
  for(const [key,value] of Object.entries(node)){
    if(key==='start'||key==='end'||key==='loc'||key==='range')continue;
    if(Array.isArray(value)){
      for(const child of value)if(child&&typeof child==='object')yield child;
    }else if(value&&typeof value==='object')yield value;
  }
}

function findClientRoleAuthorityAst(script){
  let ast;
  try{
    ast=parse(script,{ecmaVersion:'latest',sourceType:'module',allowAwaitOutsideFunction:true,allowReturnOutsideFunction:true});
  }catch{
    try{ast=parse(script,{ecmaVersion:'latest',sourceType:'script',allowAwaitOutsideFunction:true,allowReturnOutsideFunction:true})}
    catch{return 'UNPARSABLE_JAVASCRIPT'}
  }
  const nodes=[];
  const parents=new WeakMap();
  const visit=(node,parent=null)=>{
    if(!node||typeof node!=='object')return;
    if(typeof node.type==='string'){
      if(parent)parents.set(node,parent);
      nodes.push(node);
      for(const child of astChildren(node))visit(child,node);
    }
  };
  visit(ast);
  const unwrap=node=>node?.type==='ChainExpression'?unwrap(node.expression):node;
  const propertyName=node=>{
    node=unwrap(node);
    if(!node)return null;
    if(node.type==='Identifier')return node.name;
    if(node.type==='Literal'||node.type==='TemplateLiteral'&&node.expressions.length===0)
      return node.type==='Literal'?String(node.value):node.quasis[0].value.cooked;
    return null;
  };
  const memberProperty=node=>node?.type==='MemberExpression'?propertyName(node.property):null;
  const isQualifiedStorage=node=>{
    node=unwrap(node);
    return node?.type==='MemberExpression'&&
      unwrap(node.object)?.type==='Identifier'&&
      new Set(['window','globalThis']).has(node.object.name)&&
      authorizationContract.authorityStorageGlobals.has(memberProperty(node));
  };
  const isObjectMethod=(node,objectName,methodNames)=>{
    node=unwrap(node);
    return node?.type==='CallExpression'&&
      unwrap(node.callee)?.type==='MemberExpression'&&
      unwrap(node.callee.object)?.type==='Identifier'&&
      node.callee.object.name===objectName&&
      methodNames.has(memberProperty(node.callee));
  };
  const isMappingExpression=node=>{
    node=unwrap(node);
    return node?.type==='ObjectExpression'||
      node?.type==='NewExpression'&&unwrap(node.callee)?.type==='Identifier'&&node.callee.name==='Map'||
      isObjectMethod(node,'Object',new Set(['freeze','assign','fromEntries']));
  };
  const bindings=[];
  const functions=new Map();
  const scopedFunctions=new WeakMap();
  const scopedBindings=new WeakMap();
  const isFunction=node=>/Function(?:Declaration|Expression)$/.test(node?.type)||node?.type==='ArrowFunctionExpression';
  const enclosingScope=node=>{
    for(let current=parents.get(node);current;current=parents.get(current))
      if(current.type==='Program'||current.type==='BlockStatement'||current.type==='CatchClause'||current.type==='SwitchStatement'||
        /For(?:In|Of)?Statement/.test(current.type)||isFunction(current))return current;
    return ast;
  };
  const enclosingVarScope=node=>{
    for(let current=parents.get(node);current;current=parents.get(current))
      if(current.type==='Program'||isFunction(current))return current;
    return ast;
  };
  const registerScopedFunction=(bindingNode,name,fn)=>{
    const scope=enclosingScope(bindingNode);
    const key=`${name}@${scope.start}:${fn.start}`;
    const entries=scopedFunctions.get(scope)||new Map();
    if(entries.has(name))return entries.get(name);
    entries.set(name,key);
    scopedFunctions.set(scope,entries);
    functions.set(key,fn);
    return key;
  };
  const resolveScopedFunction=(node,name)=>{
    for(let scope=enclosingScope(node);scope;scope=enclosingScope(scope)){
      const key=scopedFunctions.get(scope)?.get(name);
      if(key)return key;
      if(scope===ast)break;
    }
    return null;
  };
  const registerScopedBinding=(bindingNode,name,kind='lexical')=>{
    const scope=kind==='var'?enclosingVarScope(bindingNode):enclosingScope(bindingNode);
    const entries=scopedBindings.get(scope)||new Map();
    if(entries.has(name))return entries.get(name);
    const key=`${name}@${scope.start}:${bindingNode.start}`;
    entries.set(name,key);
    scopedBindings.set(scope,entries);
    return key;
  };
  const resolveScopedBinding=(node,name)=>{
    for(let scope=enclosingScope(node);scope;scope=enclosingScope(scope)){
      const key=scopedBindings.get(scope)?.get(name);
      if(key)return key;
      if(scope===ast)break;
    }
    return name;
  };
  const returnedNodes=functionNode=>{
    if(functionNode.body.type!=='BlockStatement')return [functionNode.body];
    const returns=[];
    const collect=(node,root=true)=>{
      if(!node||typeof node!=='object')return;
      if(!root&&/Function(?:Declaration|Expression)$/.test(node.type)||!root&&node.type==='ArrowFunctionExpression')return;
      if(node.type==='ReturnStatement'&&node.argument){returns.push(node.argument);return}
      for(const child of astChildren(node))collect(child,false);
    };
    collect(functionNode.body);
    return returns;
  };
  const patternIdentifiers=pattern=>{
    pattern=unwrap(pattern);
    if(!pattern)return [];
    if(pattern.type==='Identifier')return [pattern];
    if(pattern.type==='AssignmentPattern')return patternIdentifiers(pattern.left);
    if(pattern.type==='RestElement')return patternIdentifiers(pattern.argument);
    if(pattern.type==='ObjectPattern')return pattern.properties.flatMap(property=>patternIdentifiers(property.value||property.argument));
    if(pattern.type==='ArrayPattern')return pattern.elements.flatMap(patternIdentifiers);
    return [];
  };
  for(const node of nodes){
    if(node.type==='FunctionDeclaration'&&node.id)registerScopedFunction(node,node.id.name,node);
    if(isFunction(node))
      for(const parameter of node.params)
        for(const identifier of patternIdentifiers(parameter))registerScopedBinding(identifier,identifier.name);
    if(node.type==='CatchClause'&&node.param)
      for(const identifier of patternIdentifiers(node.param))registerScopedBinding(identifier,identifier.name);
    if(node.type==='VariableDeclarator'){
      const kind=parents.get(node)?.kind==='var'?'var':'lexical';
      for(const identifier of patternIdentifiers(node.id))registerScopedBinding(identifier,identifier.name,kind);
      if(node.id.type==='Identifier'){
        bindings.push({name:node.id.name,key:resolveScopedBinding(node,node.id.name),value:node.init,node});
        if(/FunctionExpression|ArrowFunctionExpression/.test(node.init?.type||''))registerScopedFunction(node,node.id.name,node.init);
      }
    }
    if(node.type==='AssignmentExpression'&&node.operator==='='&&node.left.type==='Identifier')
      bindings.push({name:node.left.name,value:node.right,node});
  }
  for(const binding of bindings)binding.key??=resolveScopedBinding(binding.node,binding.name);
  const mappings=new Set(bindings.filter(binding=>isMappingExpression(binding.value)).map(binding=>binding.key));
  const mappingBindings=new Map(bindings.filter(binding=>isMappingExpression(binding.value)).map(binding=>[binding.key,binding.value]));
  const roleValues=new Set();
  const mappedValues=new Set();
  const roleMappedValues=new Set();
  const serverMenusValues=new Set();
  const roleReturningFunctions=new Set();
  const mappedReturningFunctions=new Set();
  const roleMappedReturningFunctions=new Set();
  const roleMappedCaches=new Set();
  const storageAliases=new Set(authorizationContract.authorityStorageGlobals);
  const passThroughParameters=new Map();
  const returnMapKeyParameters=new Map();
  const returnMappingParameterPairs=new Map();
  const fieldAliases=new Map(bindings.flatMap(({key,value})=>{
    const field=propertyName(value);
    return value&&(value.type==='Literal'||value.type==='TemplateLiteral'&&value.expressions.length===0)?[[key,field]]:[];
  }));
  for(let changed=true;changed;){
    changed=false;
    for(const {key,value} of bindings){
      const source=value?.type==='Identifier'?resolveScopedBinding(value,value.name):null;
      if(source&&fieldAliases.has(source)&&!fieldAliases.has(key)){fieldAliases.set(key,fieldAliases.get(source));changed=true}
    }
  }
  for(let changed=true;changed;){
    changed=false;
    for(const {key,value} of bindings){
      const source=value?.type==='Identifier'?resolveScopedBinding(value,value.name):null;
      if((source&&storageAliases.has(source)||isQualifiedStorage(value))&&!storageAliases.has(key)){storageAliases.add(key);changed=true}
    }
  }
  const staticMemberProperty=node=>{
    if(node?.type!=='MemberExpression')return null;
    const propertyKey=node.computed&&node.property.type==='Identifier'?resolveScopedBinding(node.property,node.property.name):null;
    return propertyKey&&fieldAliases.has(propertyKey)?fieldAliases.get(propertyKey):memberProperty(node);
  };
  const staticPatternProperty=property=>{
    if(!property.computed)return propertyName(property.key);
    if(property.key.type==='Literal'||property.key.type==='TemplateLiteral'&&property.key.expressions.length===0)
      return propertyName(property.key);
    if(property.key.type==='Identifier'){
      const key=resolveScopedBinding(property.key,property.key.name);
      return fieldAliases.get(key)??null;
    }
    return null;
  };
  const patternPathBindings=(pattern,path=[])=>{
    pattern=unwrap(pattern);
    if(!pattern)return [];
    if(pattern.type==='Identifier')return [{identifier:pattern,path}];
    if(pattern.type==='AssignmentPattern')return patternPathBindings(pattern.left,path);
    if(pattern.type==='RestElement')return patternPathBindings(pattern.argument,path);
    if(pattern.type==='ObjectPattern'){
      const extracted=[];
      const result=[];
      for(const property of pattern.properties){
        if(property.type==='RestElement'){
          result.push(...patternPathBindings(property.argument,[...path,{objectRest:[...extracted]}]));
          continue;
        }
        const key=staticPatternProperty(property);
        if(key===null)result.push(...patternPathBindings(property.value,[...path,{unknown:true}]));
        else{
          extracted.push(key);
          result.push(...patternPathBindings(property.value,[...path,{property:key}]));
        }
      }
      return result;
    }
    if(pattern.type==='ArrayPattern'){
      const result=[];
      pattern.elements.forEach((element,index)=>{
        if(element?.type==='RestElement')
          result.push(...patternPathBindings(element.argument,[...path,{arrayRest:index}]));
        else result.push(...patternPathBindings(element,[...path,{index}]));
      });
      return result;
    }
    return [];
  };
  const dependencyKey=(index,path=[],trail=[])=>JSON.stringify([index,path,trail]);
  const dependencyParts=dependency=>typeof dependency==='number'?[dependency,[],[]]:JSON.parse(dependency);
  const appendDependencyPath=(dependencies,path)=>new Set([...dependencies].map(dependency=>{
    const [index,current,trail]=dependencyParts(dependency);
    return dependencyKey(index,[...current,...path],trail);
  }));
  const resolveObjectProperty=(input,key,seenBindings=new Set())=>{
    const node=unwrap(input);
    if(!node)return {status:'missing',values:[]};
    if(node.type==='Identifier'){
      const bindingKey=resolveScopedBinding(node,node.name);
      const binding=bindings.find(candidate=>candidate.key===bindingKey&&candidate.value);
      if(binding&&!seenBindings.has(bindingKey))
        return resolveObjectProperty(binding.value,key,new Set(seenBindings).add(bindingKey));
      return {
        status:'unknown',
        values:[{type:'MemberExpression',object:node,property:{type:'Literal',value:key},computed:true,optional:false}]
      };
    }
    if(node.type==='Task229ObjectRest')
      return node.excluded.includes(key)?
        {status:'missing',values:[]}:
        resolveObjectProperty(node.source,key,new Set(seenBindings));
    if(node.type!=='ObjectExpression')return {
      status:'unknown',
      values:[{type:'MemberExpression',object:node,property:{type:'Literal',value:key},computed:true,optional:false}]
    };
    const uncertain=[];
    for(let index=node.properties.length-1;index>=0;index--){
      const property=node.properties[index];
      if(property.type==='SpreadElement'){
        const projection=resolveObjectProperty(property.argument,key,new Set(seenBindings));
        if(projection.status==='found')return {status:'found',values:[...uncertain,...projection.values]};
        if(projection.status==='unknown')uncertain.push(...projection.values);
        continue;
      }
      const propertyKey=staticPatternProperty(property);
      if(propertyKey===null)uncertain.push(property.value);
      else if(propertyKey===key)return {status:'found',values:[...uncertain,property.value]};
    }
    return uncertain.length?{status:'unknown',values:uncertain}:{status:'missing',values:[]};
  };
  const projectObjectRest=(input,excluded,seenBindings=new Set())=>{
    const node=unwrap(input);
    if(!node)return null;
    if(node.type==='Identifier'){
      const key=resolveScopedBinding(node,node.name);
      const binding=bindings.find(candidate=>candidate.key===key&&candidate.value);
      if(binding&&!seenBindings.has(key))
        return projectObjectRest(binding.value,excluded,new Set(seenBindings).add(key));
    }
    if(node.type!=='ObjectExpression')return {type:'Task229ObjectRest',source:node,excluded};
    const properties=[];
    for(const property of node.properties){
      if(property.type==='SpreadElement'){
        const projected=projectObjectRest(property.argument,excluded,new Set(seenBindings));
        if(projected?.type==='ObjectExpression')properties.push(...projected.properties);
        else if(projected)properties.push({type:'SpreadElement',argument:projected});
      }else if(!excluded.includes(staticPatternProperty(property)))properties.push(property);
    }
    return {type:'ObjectExpression',properties};
  };
  const expandArrayElements=(input,seenBindings=new Set())=>{
    const node=unwrap(input);
    if(!node)return {elements:[],exact:true};
    if(node.type==='Identifier'){
      const key=resolveScopedBinding(node,node.name);
      const binding=bindings.find(candidate=>candidate.key===key&&candidate.value);
      if(binding&&!seenBindings.has(key))
        return expandArrayElements(binding.value,new Set(seenBindings).add(key));
    }
    if(node.type!=='ArrayExpression')
      return {elements:[{type:'Task229ArraySpread',source:node}],exact:false};
    const elements=[];
    let exact=true;
    for(const element of node.elements){
      if(element?.type==='SpreadElement'){
        const expanded=expandArrayElements(element.argument,new Set(seenBindings));
        elements.push(...expanded.elements);
        exact&&=expanded.exact;
      }else elements.push(element);
    }
    return {elements,exact};
  };
  const projectArrayIndex=(input,index,rest,seenBindings=new Set())=>{
    const {elements,exact}=expandArrayElements(input,seenBindings);
    if(exact)return rest?
      {type:'ArrayExpression',elements:elements.slice(index)}:
      elements[index]||null;
    if(rest){
      const projected=[];
      let uncertain=false;
      let minimumIndex=0;
      elements.forEach(element=>{
        if(element?.type==='Task229ArraySpread'){
          uncertain=true;
          projected.push({type:'SpreadElement',argument:element.source});
        }else{
          if(uncertain||minimumIndex>=index)projected.push(element);
          minimumIndex++;
        }
      });
      return {type:'ArrayExpression',elements:projected};
    }
    const candidates=[];
    let uncertain=false;
    let minimumIndex=0;
    elements.forEach(element=>{
      if(element?.type==='Task229ArraySpread'){
        uncertain=true;
        if(minimumIndex<=index)candidates.push(element.source);
      }else{
        if(minimumIndex===index||uncertain&&minimumIndex<=index)candidates.push(element);
        minimumIndex++;
      }
    });
    return candidates.length>1?{type:'ArrayExpression',elements:candidates}:candidates[0]||null;
  };
  const projectPath=(input,path,seenBindings=new Set())=>{
    let node=unwrap(input);
    for(let offset=0;offset<path.length;offset++){
      const segment=path[offset];
      if(!node)return null;
      if(node.type==='Identifier'){
        const key=resolveScopedBinding(node,node.name);
        const binding=bindings.find(candidate=>candidate.key===key&&candidate.value);
        if(binding&&!seenBindings.has(key)){
          const nextSeen=new Set(seenBindings).add(key);
          return projectPath(binding.value,path.slice(offset),nextSeen);
        }
      }
      if(segment.argumentsFrom!==undefined)continue;
      if(segment.unknown)return node;
      if(segment.property!==undefined){
        if(node.type==='ObjectExpression'){
          const candidates=resolveObjectProperty(node,segment.property,new Set(seenBindings)).values;
          if(candidates.length>1)return {
            type:'ArrayExpression',
            elements:candidates.map(candidate=>projectPath(candidate,path.slice(offset+1),new Set(seenBindings))).filter(Boolean)
          };
          node=candidates[0]||null;
        }else node={type:'MemberExpression',object:node,property:{type:'Literal',value:segment.property},computed:true,optional:false};
      }else if(segment.index!==undefined){
        if(node.type==='ArrayExpression'||node.type==='Identifier')
          node=projectArrayIndex(node,segment.index,false,new Set(seenBindings));
        else node={type:'MemberExpression',object:node,property:{type:'Literal',value:segment.index},computed:true,optional:false};
      }else if(segment.objectRest){
        node=projectObjectRest(node,segment.objectRest,new Set(seenBindings));
      }else if(segment.arrayRest!==undefined){
        node=projectArrayIndex(node,segment.arrayRest,true,new Set(seenBindings));
      }
    }
    return node;
  };
  const projectCallDependency=(call,dependency)=>{
    const [index,path]=dependencyParts(dependency);
    const argumentsFrom=path[0]?.argumentsFrom;
    if(argumentsFrom!==undefined)
      return projectPath({type:'ArrayExpression',elements:call.arguments.slice(argumentsFrom)},path.slice(1));
    return projectPath(call.arguments[index],path);
  };
  const objectMethods=[];
  const classMethods=[];
  const classInstances=[];
  for(const node of nodes){
    if(node.type==='VariableDeclarator'&&node.id.type==='Identifier'&&node.init?.type==='ObjectExpression')
      for(const property of node.init.properties){
        const method=propertyName(property.key);
        const value=property.value;
        if(method&&/FunctionExpression|ArrowFunctionExpression/.test(value?.type||''))objectMethods.push({name:`${node.id.name}.${method}`,bindingNode:node,fn:value});
      }
    if(node.type==='ClassDeclaration'&&node.id)
      for(const method of node.body.body){
        const name=propertyName(method.key);
        if(name&&method.value)classMethods.push({name:`${node.id.name}.${name}`,className:node.id.name,methodName:name,bindingNode:node,fn:method.value});
      }
    if(node.type==='VariableDeclarator'&&node.id.type==='Identifier'&&node.init?.type==='NewExpression'&&unwrap(node.init.callee)?.type==='Identifier')
      classInstances.push({instance:node.id.name,className:node.init.callee.name,bindingNode:node});
  }
  for(const {name,bindingNode,fn} of objectMethods)
    registerScopedFunction(bindingNode,name,fn);
  for(const {name,bindingNode,fn} of classMethods)
    registerScopedFunction(bindingNode,name,fn);
  for(const {instance,className,bindingNode} of classInstances)
    for(const {className:declaredClass,methodName} of classMethods)
      if(declaredClass===className){
        const target=resolveScopedFunction(bindingNode,`${className}.${methodName}`);
        if(target)registerScopedFunction(bindingNode,`${instance}.${methodName}`,functions.get(target));
      }
  const localCallTarget=node=>{
    const callee=unwrap(node?.callee);
    if(callee?.type==='Identifier')return resolveScopedFunction(node,callee.name);
    if(callee?.type!=='MemberExpression'||unwrap(callee.object)?.type!=='Identifier')return null;
    const method=staticMemberProperty(callee);
    return method?resolveScopedFunction(node,`${callee.object.name}.${method}`):null;
  };
  for(let changed=true;changed;){
    changed=false;
    for(const {name,value,node} of bindings){
      if(value?.type!=='Identifier')continue;
      const target=resolveScopedFunction(node,value.name);
      if(!target||resolveScopedFunction(node,name))continue;
      registerScopedFunction(node,name,functions.get(target));
      changed=true;
    }
  }
  for(const node of nodes){
    if(node.type!=='VariableDeclarator'||node.id.type!=='ObjectPattern')continue;
    for(const property of node.id.properties){
      const key=propertyName(property.key);
      if(authorizationContract.identityFields.has(key)&&property.value?.type==='Identifier')
        roleValues.add(registerScopedBinding(property.value,property.value.name));
    }
  }
  const signal=(input,seen=new Set())=>{
    const node=unwrap(input);
    if(!node||seen.has(node))return 0;
    seen.add(node);
    if(node.type==='Identifier'){
      const key=resolveScopedBinding(node,node.name);
      return (roleValues.has(key)?1:0)|
        (mappings.has(key)?2:0)|
        (mappedValues.has(key)?4:0)|
        (roleMappedValues.has(key)?8:0)|
        (serverMenusValues.has(key)?16:0);
    }
    if(node.type==='MemberExpression'){
      const propertyKey=node.computed&&node.property.type==='Identifier'?resolveScopedBinding(node.property,node.property.name):null;
      const property=propertyKey&&fieldAliases.has(propertyKey)?fieldAliases.get(propertyKey):memberProperty(node);
      const objectSignal=signal(node.object,new Set(seen));
      if(authorizationContract.identityFields.has(property))return objectSignal|1;
      if(authorizationContract.serverAuthorityFields.has(property))return objectSignal|16;
      if((objectSignal&2)&&node.computed){
        const keySignal=signal(node.property,new Set(seen));
        return 4|(keySignal&1?8:0);
      }
      return objectSignal;
    }
    if(node.type==='CallExpression'){
      const callee=unwrap(node.callee);
      const target=localCallTarget(node);
      if(target){
        let result=(roleReturningFunctions.has(target)?1:0)|
          (mappedReturningFunctions.has(target)?4:0)|
          (roleMappedReturningFunctions.has(target)?8:0);
        for(const dependency of passThroughParameters.get(target)||[])
          result|=signal(projectCallDependency(node,dependency),new Set(seen));
        for(const index of returnMapKeyParameters.get(target)||[]){
          result|=4;
          if(signal(node.arguments[index],new Set(seen))&1)result|=8;
        }
        for(const [mappingIndex,keyIndex] of returnMappingParameterPairs.get(target)||[]){
          if(signal(node.arguments[mappingIndex],new Set(seen))&2){
            result|=4;
            if(signal(node.arguments[keyIndex],new Set(seen))&1)result|=8;
          }
        }
        return result;
      }
      if(callee?.type==='MemberExpression'&&memberProperty(callee)==='get'&&(signal(callee.object,new Set(seen))&2)){
        const keySignal=signal(node.arguments[0],new Set(seen));
        const cacheName=unwrap(callee.object)?.type==='Identifier'?resolveScopedBinding(callee.object,callee.object.name):null;
        return 4|((keySignal&1)||roleMappedCaches.has(cacheName)?8:0);
      }
    }
    let result=0;
    for(const child of astChildren(node))result|=signal(child,new Set(seen));
    return result;
  };
  for(let changed=true;changed;){
    changed=false;
    for(const binding of bindings){
      const value=unwrap(binding.value);
      const source=value?.type==='Identifier'?resolveScopedBinding(value,value.name):null;
      if(source&&mappings.has(source)&&!mappings.has(binding.key)){mappings.add(binding.key);changed=true}
      const valueSignal=signal(value);
      for(const [bit,set] of [[1,roleValues],[4,mappedValues],[8,roleMappedValues],[16,serverMenusValues]])
        if(valueSignal&bit&&!set.has(binding.key)){set.add(binding.key);changed=true}
    }
    for(const [name,fn] of functions){
      const params=fn.params.map(param=>param.type==='Identifier'?param.name:null);
      const returns=returnedNodes(fn);
      const directPassThrough=new Set();
      const mapKeyParameters=new Set();
      const mappingParameterPairs=[];
      for(const returned of returns){
        const expression=unwrap(returned);
        if(expression?.type==='Identifier'&&params.includes(expression.name))directPassThrough.add(params.indexOf(expression.name));
        if(expression?.type==='MemberExpression'&&(signal(expression.object)&2)&&expression.computed&&expression.property.type==='Identifier'&&params.includes(expression.property.name))
          mapKeyParameters.add(params.indexOf(expression.property.name));
        if(expression?.type==='MemberExpression'&&expression.computed&&expression.object.type==='Identifier'&&expression.property.type==='Identifier'&&
          params.includes(expression.object.name)&&params.includes(expression.property.name))
          mappingParameterPairs.push([params.indexOf(expression.object.name),params.indexOf(expression.property.name)]);
      }
      const previousPassThrough=passThroughParameters.get(name)||new Set();
      if([...directPassThrough].some(index=>!previousPassThrough.has(index))){passThroughParameters.set(name,new Set([...previousPassThrough,...directPassThrough]));changed=true}
      const previousMapKeys=returnMapKeyParameters.get(name)||new Set();
      if([...mapKeyParameters].some(index=>!previousMapKeys.has(index))){returnMapKeyParameters.set(name,new Set([...previousMapKeys,...mapKeyParameters]));changed=true}
      const previousPairs=returnMappingParameterPairs.get(name)||[];
      if(mappingParameterPairs.some(pair=>!previousPairs.some(previous=>previous[0]===pair[0]&&previous[1]===pair[1]))){
        returnMappingParameterPairs.set(name,[...previousPairs,...mappingParameterPairs]);
        changed=true;
      }
      const returnSignal=returns.reduce((result,node)=>result|signal(node),0);
      for(const [bit,set] of [[1,roleReturningFunctions],[4,mappedReturningFunctions],[8,roleMappedReturningFunctions]])
        if(returnSignal&bit&&!set.has(name)){set.add(name);changed=true}
    }
  }
  for(const node of nodes){
    const callee=unwrap(node.type==='CallExpression'?node.callee:null);
    if(callee?.type!=='MemberExpression'||memberProperty(callee)!=='set'||unwrap(callee.object)?.type!=='Identifier')continue;
    const cacheKey=resolveScopedBinding(callee.object,callee.object.name);
    if(mappings.has(cacheKey)&&node.arguments.some(argument=>signal(argument)&8))roleMappedCaches.add(cacheKey);
  }
  const text=node=>script.slice(node.start,node.end);
  const stringIsAuthorization=value=>typeof value==='string'&&(/(?:^|[./])menu[._/]|\/api\/|\/[^'"]+\.html\b/.test(value));
  const constantString=node=>{
    node=unwrap(node);
    if(node?.type==='Literal'&&typeof node.value==='string')return node.value;
    if(node?.type==='TemplateLiteral'&&node.expressions.length===0)return node.quasis[0].value.cooked;
    if(node?.type==='Identifier'){
      const key=resolveScopedBinding(node,node.name);
      if(fieldAliases.has(key))return fieldAliases.get(key);
    }
    return null;
  };
  const containsDirectRoleSource=root=>{
    const node=unwrap(root);
    if(!node)return false;
    if(node.type==='MemberExpression'){
      const propertyKey=node.computed&&node.property.type==='Identifier'?resolveScopedBinding(node.property,node.property.name):null;
      const property=propertyKey&&fieldAliases.has(propertyKey)?fieldAliases.get(propertyKey):memberProperty(node);
      if(authorizationContract.identityFields.has(property))return true;
    }
    for(const child of astChildren(node))if(containsDirectRoleSource(child))return true;
    return false;
  };
  const hasAuthorizationMaterial=(root,seenFunctions=new Set())=>{
    let found=false;
    const inspect=node=>{
      if(found||!node)return;
      if(node.type==='Literal'&&stringIsAuthorization(node.value)){found=true;return}
      if(node.type==='TemplateElement'&&stringIsAuthorization(node.value.cooked)){found=true;return}
      if(node.type==='MemberExpression'&&authorizationContract.authorizationStateFields.has(memberProperty(node))){found=true;return}
      if(node.type==='AssignmentExpression'&&node.left.type==='MemberExpression'){
        const property=memberProperty(node.left);
        if(authorizationContract.authorizationStateFields.has(property)||authorizationContract.uiGateFields.has(property)||authorizationContract.navigationFields.has(property)){found=true;return}
      }
      if(node.type==='CallExpression'){
        const callee=unwrap(node.callee);
        let rootObject=callee?.type==='MemberExpression'?unwrap(callee.object):null;
        while(rootObject?.type==='MemberExpression')rootObject=unwrap(rootObject.object);
        if(node.arguments.some(argument=>stringIsAuthorization(constantString(argument))||constantString(argument)?.startsWith('/api/'))){found=true;return}
        if(rootObject?.type==='Identifier'&&authorizationContract.authorityGlobals.has(rootObject.name)){found=true;return}
        if(callee?.type==='MemberExpression'&&authorizationContract.uiGateMethods.has(memberProperty(callee))){found=true;return}
        if(callee?.type==='MemberExpression'&&authorizationContract.uiGateAttributeMethods.has(memberProperty(callee))&&
          node.arguments.some(argument=>constantString(argument)==='hidden')){found=true;return}
        if(callee?.type==='MemberExpression'&&authorizationContract.uiGateStyleMethods.has(memberProperty(callee))&&
          node.arguments.some(argument=>new Set(['display','visibility']).has(constantString(argument)))){found=true;return}
        if((rootObject?.type==='Identifier'&&storageAliases.has(resolveScopedBinding(rootObject,rootObject.name))||isQualifiedStorage(callee?.object))&&
          node.arguments.some(argument=>authorizationContract.authorizationStateFields.has(constantString(argument)))){found=true;return}
        if(callee?.type==='MemberExpression'&&unwrap(callee.object)?.type==='MemberExpression'&&memberProperty(callee.object)==='classList'&&
          node.arguments.some(argument=>argument.type==='Literal'&&authorizationContract.uiGateClassNames.has(String(argument.value)))){found=true;return}
        const target=localCallTarget(node);
        if(target&&!seenFunctions.has(target)){
          const nextSeen=new Set(seenFunctions).add(target);
          if(hasAuthorizationMaterial(functions.get(target).body,nextSeen)){found=true;return}
        }
      }
      for(const child of astChildren(node))inspect(child);
    };
    inspect(root);
    return found;
  };
  const mappingDefinition=(identifier,seen=new Set())=>{
    const key=resolveScopedBinding(identifier,identifier.name);
    if(seen.has(key))return null;
    seen.add(key);
    if(mappingBindings.has(key))return mappingBindings.get(key);
    const alias=bindings.find(binding=>binding.key===key&&binding.value?.type==='Identifier');
    return alias?mappingDefinition(alias.value,seen):null;
  };
  const argumentReadsAuthorizationMapping=root=>{
    let found=false;
    const inspect=node=>{
      node=unwrap(node);
      if(found||!node)return;
      if(node.type==='MemberExpression'&&node.computed&&unwrap(node.object)?.type==='Identifier'){
        const definition=mappingDefinition(unwrap(node.object));
        if(definition&&hasAuthorizationMaterial(definition)){found=true;return}
      }
      for(const child of astChildren(node))inspect(child);
    };
    inspect(root);
    return found;
  };
  const isDirectMappedAuthorizationCall=node=>{
    const mappedArguments=node.arguments.filter(argument=>signal(argument)&8);
    if(mappedArguments.length===0)return false;
    const callee=unwrap(node.callee);
    if(callee?.type==='MemberExpression'){
      const method=memberProperty(callee);
      let rootObject=unwrap(callee.object);
      while(rootObject?.type==='MemberExpression')rootObject=unwrap(rootObject.object);
      if(authorizationContract.uiGateMethods.has(method))return true;
      if(authorizationContract.authorizationActionMethods.has(method))return true;
      if((rootObject?.type==='Identifier'&&storageAliases.has(resolveScopedBinding(rootObject,rootObject.name))||isQualifiedStorage(callee.object))&&
        node.arguments.some(argument=>authorizationContract.authorizationStateFields.has(constantString(argument))))return true;
    }
    return mappedArguments.some(argumentReadsAuthorizationMapping);
  };
  const bodyHasMappedAuthorizationEffect=root=>{
    let found=false;
    const inspect=node=>{
      if(found||!node)return;
      if(node.type==='AssignmentExpression'&&node.left.type==='MemberExpression'&&(signal(node.right)&4)){
        const property=memberProperty(node.left);
        if(authorizationContract.authorizationStateFields.has(property)||authorizationContract.uiGateFields.has(property)||authorizationContract.navigationFields.has(property)){found=true;return}
      }
      for(const child of astChildren(node))inspect(child);
    };
    inspect(root);
    return found;
  };
  const patternNames=pattern=>{
    pattern=unwrap(pattern);
    if(!pattern)return [];
    if(pattern.type==='Identifier')return [pattern.name];
    if(pattern.type==='AssignmentPattern')return patternNames(pattern.left);
    if(pattern.type==='RestElement')return patternNames(pattern.argument);
    if(pattern.type==='ObjectPattern')return pattern.properties.flatMap(property=>patternNames(property.value||property.argument));
    if(pattern.type==='ArrayPattern')return pattern.elements.flatMap(patternNames);
    return [];
  };
  const functionNodes=fn=>{
    const scoped=[];
    const collect=(node,root=true)=>{
      if(!node||typeof node!=='object')return;
      if(!root&&/Function(?:Declaration|Expression)$/.test(node.type)||!root&&node.type==='ArrowFunctionExpression')return;
      scoped.push(node);
      for(const child of astChildren(node))collect(child,false);
    };
    collect(fn.body);
    return scoped;
  };
  const parameterSummaries=new Map([...functions].map(([name])=>[name,{returns:new Set(),effects:new Set()}]));
  const addAll=(target,source)=>{
    let changed=false;
    for(const value of source)if(!target.has(value)){target.add(value);changed=true}
    return changed;
  };
  const argumentDependencies=(node,dependency,dependencies)=>
    dependencies(projectCallDependency(node,dependency));
  const callDependencies=(node,dependency,dependencies,caller)=>{
    const [, ,calleeTrail]=dependencyParts(dependency);
    if(calleeTrail.includes(caller))return new Set();
    return new Set([...argumentDependencies(node,dependency,dependencies)].map(result=>{
      const [index,path,callerTrail]=dependencyParts(result);
      return dependencyKey(index,path,[...new Set([...calleeTrail,...callerTrail])]);
    }));
  };
  for(let changed=true,remaining=functions.size+2;changed;){
    if(remaining--===0)return 'UNRESOLVED_AUTHORIZATION_DATAFLOW';
    changed=false;
    for(const [name,fn] of functions){
      const scoped=functionNodes(fn).sort((left,right)=>left.start-right.start);
      const environment=new Map();
      fn.params.forEach((parameter,index)=>{
        const root=parameter.type==='RestElement'?
          patternPathBindings(parameter.argument,[{argumentsFrom:index}]):
          patternPathBindings(parameter);
        for(const {identifier,path} of root)
          environment.set(resolveScopedBinding(identifier,identifier.name),new Set([dependencyKey(index,path,[name])]));
      });
      const dependencies=input=>{
        const node=unwrap(input);
        if(!node)return new Set();
        if(node.type==='Identifier')return new Set(environment.get(resolveScopedBinding(node,node.name))||[]);
        if(node.type==='MemberExpression'){
          const source=dependencies(node.object);
          const parent=parents.get(node);
          const callParent=parent?.type==='ChainExpression'?parents.get(parent):parent;
          if(callParent?.type==='CallExpression'&&unwrap(callParent.callee)===node)return source;
          const property=staticMemberProperty(node);
          if(property===null)return source;
          const segment=node.computed&&node.property.type==='Literal'&&typeof node.property.value==='number'?
            {index:node.property.value}:{property};
          return appendDependencyPath(source,[segment]);
        }
        if(node.type==='CallExpression'){
          const summary=parameterSummaries.get(localCallTarget(node));
          if(summary){
            const result=new Set();
            for(const dependency of summary.returns)addAll(result,callDependencies(node,dependency,dependencies,name));
            return result;
          }
        }
        const result=new Set();
        for(const child of astChildren(node))addAll(result,dependencies(child));
        return result;
      };
      const nextReturns=new Set();
      const nextEffects=new Set();
      for(const node of scoped){
        if(node.type==='VariableDeclarator'&&node.init){
          const source=dependencies(node.init);
          for(const {identifier,path} of patternPathBindings(node.id))
            environment.set(resolveScopedBinding(identifier,identifier.name),appendDependencyPath(source,path));
        }
        if(node.type==='AssignmentExpression'&&node.operator==='='){
          const source=dependencies(node.right);
          for(const identifier of patternIdentifiers(node.left)){
            const key=resolveScopedBinding(identifier,identifier.name);
            let conditional=false;
            for(let parent=parents.get(node);parent&&parent!==fn;parent=parents.get(parent))
              if(/^(?:If|Conditional|Switch|For|ForIn|ForOf|While|DoWhile|Try)Statement$/.test(parent.type)){conditional=true;break}
            if(conditional){
              const target=environment.get(key)||new Set();
              addAll(target,source);
              environment.set(key,target);
            }else environment.set(key,new Set(source));
          }
        }
        if(node.type==='ReturnStatement')addAll(nextReturns,dependencies(node.argument));
        if(node.type==='AssignmentExpression'&&node.left.type==='MemberExpression'){
          const property=memberProperty(node.left);
          if(authorizationContract.authorizationStateFields.has(property)||authorizationContract.uiGateFields.has(property)||authorizationContract.navigationFields.has(property))
            addAll(nextEffects,dependencies(node.right));
        }
        if(node.type==='IfStatement'||node.type==='ConditionalExpression'){
          const branches=node.type==='IfStatement'?[node.consequent,node.alternate]:[node.consequent,node.alternate];
          if(branches.some(branch=>branch&&hasAuthorizationMaterial(branch)))addAll(nextEffects,dependencies(node.test));
        }
        if(node.type==='CallExpression'){
          const summary=parameterSummaries.get(localCallTarget(node));
          if(summary)for(const dependency of summary.effects)addAll(nextEffects,callDependencies(node,dependency,dependencies,name));
          const callee=unwrap(node.callee);
          let rootObject=callee?.type==='MemberExpression'?unwrap(callee.object):null;
          while(rootObject?.type==='MemberExpression')rootObject=unwrap(rootObject.object);
          const method=callee?.type==='MemberExpression'?memberProperty(callee):null;
          const directSink=callee?.type==='Identifier'&&callee.name==='fetch'||
            authorizationContract.uiGateMethods.has(method)||
            authorizationContract.authorizationActionMethods.has(method)||
            rootObject?.type==='Identifier'&&authorizationContract.authorityGlobals.has(rootObject.name)||
            (rootObject?.type==='Identifier'&&storageAliases.has(resolveScopedBinding(rootObject,rootObject.name))||isQualifiedStorage(callee?.object))&&
              node.arguments.some(argument=>authorizationContract.authorizationStateFields.has(constantString(argument)));
          if(directSink)for(const argument of node.arguments)addAll(nextEffects,dependencies(argument));
        }
      }
      const summary=parameterSummaries.get(name);
      if(addAll(summary.returns,nextReturns)||addAll(summary.effects,nextEffects))changed=true;
    }
  }
  for(const [name,summary] of parameterSummaries){
    const existing=passThroughParameters.get(name)||new Set();
    if(addAll(existing,summary.returns))passThroughParameters.set(name,existing);
  }
  for(let changed=true;changed;){
    changed=false;
    for(const {key,value} of bindings){
      const valueSignal=signal(value);
      for(const [bit,set] of [[1,roleValues],[4,mappedValues],[8,roleMappedValues],[16,serverMenusValues]])
        if(valueSignal&bit&&!set.has(key)){set.add(key);changed=true}
    }
  }
  for(const node of nodes){
    if(node.type==='IfStatement'||node.type==='ConditionalExpression'){
      const testSignal=signal(node.test);
      const branches=node.type==='IfStatement'?[node.consequent,node.alternate]:[node.consequent,node.alternate];
      if((testSignal&8)&&branches.some(branch=>branch&&(hasAuthorizationMaterial(branch)||bodyHasMappedAuthorizationEffect(branch))))return text(node);
      if(containsDirectRoleSource(node.test)&&branches.some(branch=>branch&&hasAuthorizationMaterial(branch)))return text(node);
    }
    if(node.type==='SwitchStatement'&&(signal(node.discriminant)&1)&&hasAuthorizationMaterial(node))return text(node);
    if(node.type==='VariableDeclarator'&&node.init?.type==='ConditionalExpression'&&containsDirectRoleSource(node.init.test)){
      const displayOnly=[node.init.consequent,node.init.alternate].every(branch=>branch.type==='Literal'&&typeof branch.value==='string');
      if(!displayOnly)return text(node);
    }
    if(node.type==='AssignmentExpression'&&node.left.type==='MemberExpression'&&(signal(node.right)&4)){
      const property=memberProperty(node.left);
      if(authorizationContract.authorizationStateFields.has(property)||((signal(node.right)&8)&&(authorizationContract.uiGateFields.has(property)||authorizationContract.navigationFields.has(property))))return text(node);
    }
    if(node.type==='CallExpression'&&unwrap(node.callee)?.type==='Identifier'&&node.callee.name==='fetch'&&
      node.arguments.some(argument=>(signal(argument)&8)))return text(node);
    if(node.type==='CallExpression'&&isDirectMappedAuthorizationCall(node))return text(node);
    if(node.type==='CallExpression'){
      const summary=parameterSummaries.get(localCallTarget(node));
      if(summary&&[...summary.effects].some(dependency=>signal(projectCallDependency(node,dependency))&8))return text(node);
    }
  }
  return null;
}

function assertNoClientRoleAuthority(script,message){
  assert.equal(findClientRoleAuthorityAst(script),null,message);
}

const task223OriginalMutation=Buffer.from(
  'Y29uc3QgYWNjZXNzPXtmdXR1cmU6dHJ1ZX07ZnVuY3Rpb24gcmV2ZWFsKGFsbG93ZWQpe2lmKGFsbG93ZWQpcGFnZS5oaWRkZW49ZmFsc2V9cmV2ZWFsKGFjY2Vzc1t1c2VyLnJvbGVdKQo=',
  'base64'
).toString('utf8');
const task228BlockerReproduction=
  'const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({allowed:false,decoy:access[user.role]})';

const designer={role:'designer',role_code:'designer',menus:[
  {label:'AI素材中心',href:'/ai-assets.html',permission:'menu.ai_assets'},
  {label:'AI工作流',href:'/workflows.html',permission:'menu.workflows'}
]};
const adminPaths=['/index.html','/control.html','/stores.html','/jd-dashboard.html','/ads.html','/metrics.html','/import.html','/ai-assets.html','/skill-center.html','/computer-execution-center.html','/tiancang.html','/workflows.html','/ai-employees.html','/account-center.html','/knowledge-center.html','/device-center.html','/settings.html'];
const adminMenus=adminPaths.map(href=>({label:href,href,permission:routePermissions[href]}));
const admin={role:'admin',role_code:'admin',menus:adminMenus};

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

test('administrator keeps access while compact navigation removes duplicate centers',()=>{
  const {run}=page();
  const paths=run('TiantongRbac.navigationFor(admin).map(([,path])=>path)');
  for(const path of ['/jd-dashboard.html','/stores.html','/settings.html','/control.html','/ai-assets.html'])assert.ok(paths.includes(path),path);
  for(const path of ['/index.html','/import.html','/computer-execution-center.html'])assert.ok(!paths.includes(path),path);
  for(const path of ['/brain-center.html','/task-center.html','/tool-permissions.html','/deploy-center.html'])assert.equal(run(`TiantongRbac.canOpen(admin,'${path}')`),true,path);
});

test('role aliases neither add nor remove server-authorized navigation',()=>{
  const {run}=page();
  for(const [role,roleCode] of Object.entries({boss:'owner',owner:'owner',admin:'admin',administrator:'admin',operator:'operator',ads:'operator',service:'customer_service',customer_service:'customer_service',designer:'designer',editor:'editor',finance:'finance'})){
    assert.equal(run(`TiantongRbac.navigationFor({role:${JSON.stringify(role)},role_code:${JSON.stringify(roleCode)},menus:admin.menus}).length`),14,role);
  }
});

test('unauthenticated and unknown roles fail closed even with valid server menus',async()=>{
  const {run}=page();
  assert.equal(run('TiantongRbac.navigationFor(null).length'),0);
  assert.equal(run(`TiantongRbac.navigationFor({role:'new_super_role',role_code:'new_super_role',menus:admin.menus}).length`),0);
  const denied=page({path:'/index.html',user:{role:'new_super_role',role_code:'new_super_role',menus:admin.menus},protectedScript:true});
  assert.equal((await denied.run('TiantongRbac.ready')).allowed,false);
  assert.equal(denied.context.initializerCount,0);
  assert.deepEqual(denied.context.document.registrations,[]);
  assert.doesNotMatch(denied.context.document.body.innerHTML,/PROTECTED_PAGE_CONTENT/);
});

test('invalid or conflicting identities cannot navigate or activate with valid menus',async()=>{
  const full=admin.menus,single=[{permission:'menu.dashboard'}];
  const cases=[
    ['unknown-full',{role:'new_super_role',role_code:'new_super_role',menus:full}],
    ['unknown-single',{role:'new_super_role',role_code:'new_super_role',menus:single}],
    ['missing-role',{role_code:'admin',menus:full}],
    ['null-role',{role:null,role_code:'admin',menus:full}],
    ['empty-role',{role:'',role_code:'admin',menus:full}],
    ['blank-role',{role:'   ',role_code:'admin',menus:full}],
    ['padded-canonical-role',{role:' admin ',role_code:'admin',menus:full}],
    ['padded-alias-role',{role:' boss ',role_code:'owner',menus:full}],
    ['non-string-role',{role:7,role_code:'admin',menus:full}],
    ['missing-role-code',{role:'admin',menus:full}],
    ['non-string-role-code',{role:'admin',role_code:{},menus:full}],
    ['conflicting-fields',{role:'owner',role_code:'admin',menus:full}],
    ['case-variant',{role:'Admin',role_code:'admin',menus:full}],
    ['unicode-confusable',{role:'admіn',role_code:'admin',menus:full}]
  ];
  for(const [name,user] of cases){
    const denied=page({path:'/index.html',user,protectedScript:true});
    assert.equal(denied.run('TiantongRbac.navigationFor(identityUser).length'),0,`${name}: navigation`);
    const result=await denied.run('TiantongRbac.ready');
    assert.equal(result.allowed,false,`${name}: authorization`);
    assert.equal(denied.context.initializerCount,0,`${name}: initializer`);
    assert.deepEqual(denied.context.document.registrations,[],`${name}: events`);
    assert.doesNotMatch(denied.context.document.body.innerHTML,/PROTECTED_PAGE_CONTENT/,`${name}: protected flash`);
    assert.equal(denied.context.__tiantongFrontSecurity,undefined,`${name}: activation`);
  }
});

test('non-admin roles neither inherit admin routes nor lose authorized legacy routes',()=>{
  const {run}=page();
  for(const [role,permissions] of [
    ['operator',['dashboard','stores','jd_data','ads','metrics','import','workflows','account_center']],
    ['customer_service',['dashboard','metrics']],
    ['finance',['dashboard','metrics','import']]
  ]){
    const expression=`{role:${JSON.stringify(role)},role_code:${JSON.stringify(role)},menus:${JSON.stringify(permissions.map(permission=>({permission:`menu.${permission}`})))} }`;
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
  assert.equal(run(`TiantongRbac.navigationFor({role:'operator',role_code:'operator',menus:[]}).length`),0);
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
    const {context,run}=page({path:'/index.html',user:{role:'owner',role_code:'owner',menus}});
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
  const denied=page({path:'/alpha-workflow.html',user:{role:'designer',role_code:'designer',menus:[{permission:'menu.ai_assets'}]},externalScript:true});
  assert.equal((await denied.run('TiantongRbac.ready')).allowed,false);
  assert.equal(denied.context.externalLoads,0);
});

test('account switch replaces privileged navigation without residue',()=>{
  const {menu,run}=page();
  run('TiantongRbac.renderNavigation(menu,admin)');
  assert.match(menu.innerHTML,/settings\.html/);
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
  const user={role:'admin',role_code:'admin',menus:[{permission:'menu.dashboard'},{permission:'menu.future_unknown'}]};
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
    for(const match of html.matchAll(/<script\b(?![^>]*\bsrc\s*=)[^>]*>([\s\S]*?)<\/script>/gi))
      assertNoClientRoleAuthority(match[1],file.pathname);
  }
  for(const file of visit(root).filter(file=>file.pathname.endsWith('.js')))
    assertNoClientRoleAuthority(readFileSync(file,'utf8'),file.pathname);
});

test('client role authority detector rejects authorization mappings but permits display labels',()=>{
  assert.equal(
    createHash('sha256').update(task223OriginalMutation).digest('hex'),
    '5999c5bf96780defeb2b060d82a8781436df4e08c5277e3de995a3fd7471bd27'
  );
  assert.notEqual(findClientRoleAuthorityAst(task223OriginalMutation),null,'Task223 original mutation');
  assert.equal(
    createHash('sha256').update(task228BlockerReproduction).digest('hex'),
    '095d82fc964e0a6732f3e3b7a6ce95e8e6d46813cd2840309a875cbe33f30b39'
  );
  assertNoClientRoleAuthority(task228BlockerReproduction,'Task228 original false positive');
  const parameterEffectPositiveCases=[
    `const access={future:true};function reveal(allowed){page.hidden=!allowed}reveal(access[user.role])`,
    `const access={future:true};function reveal(allowed){const alias=allowed;const next=alias;if(next)page.hidden=false}reveal(access[user.role])`,
    `const access={future:true};function pass(value){return value}page.hidden=!pass(access[user.role])`,
    `const access={future:true};function pass(value){const alias=value;return alias}const allowed=pass(access[user.role]);if(allowed)page.hidden=false`,
    `const access={future:true};function pass({value}){const alias=value;return alias}const allowed=pass({value:access[user.role]});if(allowed)page.hidden=false`,
    `const access={future:true};function pass(value){const alias=value;return alias}function wrap(value){return pass(value)}const allowed=wrap(access[user.role]);if(allowed)page.hidden=false`,
    `const access={future:true};function finish(value){if(value)page.hidden=false}function forward(value){finish(value)}forward(access[user.role])`,
    `const access={future:true};function finish(value){if(value)page.hidden=false}function second(value){finish(value)}function first(value){second(value)}first(access[user.role])`,
    `const access={future:true};function reveal(prefix,allowed,suffix){if(allowed)page.hidden=false}reveal(null,access[user.role],null)`,
    `const access={future:true};function reveal(prefix,allowed=true){if(allowed)page.hidden=false}reveal(null,access[user.role])`,
    `const access={future:true};function reveal(...values){if(values[0])page.hidden=false}reveal(access[user.role])`,
    `const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({allowed:access[user.role]})`,
    `const access={future:true};function reveal([allowed]){if(allowed)page.hidden=false}reveal([access[user.role]])`,
    `const access={future:true};const reveal=allowed=>{if(allowed)page.hidden=false};reveal(access[user.role])`,
    `const access={future:true};const reveal=function(allowed){if(allowed)page.hidden=false};reveal(access[user.role])`,
    `const access={future:true};const gates={reveal(allowed){if(allowed)page.hidden=false}};gates.reveal(access[user.role])`,
    `const access={future:true};const method='reveal';const gates={reveal(allowed){if(allowed)page.hidden=false}};gates[method](access[user.role])`,
    `const access={future:true};const gates={reveal(allowed){if(allowed)page.hidden=false}};gates.reveal?.(access[user.role])`,
    `const access={future:true};class Gate{reveal(allowed){if(allowed)page.hidden=false}}const gate=new Gate;gate.reveal(access[user.role])`,
    `const access={future:true};function reveal(allowed){if(allowed)page.hidden=false}reveal(condition&&access[user.role])`,
    `const access={future:true};function reveal(allowed){if(allowed)page.hidden=false}reveal(condition?access[user.role]:false)`,
    `const access={future:true};function reveal(allowed){if(allowed)page.hidden=false}reveal(false);reveal(access[user.role])`,
    `const access={future:true};function a(value){b(value)}function b(value){if(value)page.hidden=false;a(value)}a(access[user.role])`,
    `const access={future:true};function first(){function apply(value){if(value)page.hidden=false}apply(access[user.role])}function second(){function apply(value){console.log(value)}}first()`,
    `const access={future:true};{function apply(value){if(value)page.hidden=false}apply(access[user.role])}{function apply(value){console.log(value)}}`,
    `const access={future:true};function first(){function apply(value){if(value)page.hidden=false}const alias=apply;alias(access[user.role])}function second(){function apply(value){console.log(value)}}first()`,
    `const access={future:true};function first(){const gates={reveal(value){if(value)page.hidden=false}};gates.reveal(access[user.role])}function second(){const gates={reveal(value){console.log(value)}}}first()`,
    `const access={future:true};function first(){class Gate{reveal(value){if(value)page.hidden=false}}const gate=new Gate;gate.reveal(access[user.role])}function second(){class Gate{reveal(value){console.log(value)}}}first()`,
    `const access={future:true};function first(){const selected=access[user.role];if(selected)page.hidden=false}function second(){const selected=false;console.log(selected)}first()`,
    `const access={future:true};function reveal(value){{const selected=value;if(selected)page.hidden=false}{const selected=false;console.log(selected)}}reveal(access[user.role])`,
    `const access={future:true};function f(){if(condition){var selected=access[user.role]}if(selected)page.hidden=false}f()`,
    `const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({allowed:access[user.role]})`,
    `const access={future:true};function reveal({allowed:canView}){if(canView)page.hidden=false}reveal({allowed:access[user.role]})`,
    `const access={future:true};function reveal({permissions:{allowed}}){if(allowed)page.hidden=false}reveal({permissions:{allowed:access[user.role]}})`,
    `const access={future:true};function reveal([ignored,allowed]){if(allowed)page.hidden=false}reveal([false,access[user.role]])`,
    `const access={future:true};function reveal([ignored,allowed]){if(allowed)page.hidden=false}reveal([...[false,access[user.role]]])`,
    `const access={future:true};function reveal([a,b,c,allowed]){if(allowed)page.hidden=false}reveal([false,...items,access[user.role]])`,
    `const access={future:true};function reveal({allowed=false}){if(allowed)page.hidden=false}reveal({allowed:access[user.role]})`,
    `const access={future:true};function reveal({visible,...rest}){if(rest.allowed)page.hidden=false}reveal({visible:false,allowed:access[user.role]})`,
    `const access={future:true};function reveal({visible,...rest}){if(rest.granted)page.hidden=false}reveal({...{visible:false,granted:access[user.role]}})`,
    `const access={future:true};function reveal([ignored,...rest]){if(rest[0])page.hidden=false}reveal([false,access[user.role]])`,
    `const access={future:true};function reveal([ignored,...rest]){if(rest[0])page.hidden=false}reveal([...[false,access[user.role]]])`,
    `const access={future:true};const field='allowed';function reveal({[field]:canView}){if(canView)page.hidden=false}reveal({allowed:access[user.role]})`,
    `const access={future:true};const input={allowed:access[user.role]};function reveal({allowed}){if(allowed)page.hidden=false}reveal(input)`,
    `const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({allowed:false,...{allowed:access[user.role]}})`,
    `const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({allowed:access[user.role],...extra})`,
    `const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({allowed:access[user.role],[dynamic]:false})`
  ];
  for(const script of parameterEffectPositiveCases)
    assert.notEqual(findClientRoleAuthorityAst(script),null,script);
  const parameterEffectNegativeCases=[
    `const states={future:'Published'};function format(value){return String(value)}label.textContent=format(states[key])`,
    `const states={future:true};function translate(value){return labels[value]}label.textContent=translate(states[key])`,
    `const states={future:true};function log(value){console.log(value)}log(states[key])`,
    `const states={future:2};function total(value){return value+1}metric.textContent=total(states[key])`,
    `const states={future:true};function ignore(value){return 'constant'}ignore(states[key])`,
    `const states={future:'blue'};function color(value){return value}icon.style.color=color(states[key])`,
    `const states={future:true};function first(){function apply(value){if(value)page.hidden=false}apply(false)}function second(){function apply(value){console.log(value)}apply(states[key])}second()`,
    `const states={future:true};{function apply(value){if(value)page.hidden=false}apply(false)}{function apply(value){console.log(value)}apply(states[key])}`,
    `const states={future:true};function first(){function apply(value){if(value)page.hidden=false}apply(false)}function second(){function apply(value){console.log(value)}const alias=apply;alias(states[key])}second()`,
    `const states={future:true};function first(){const gates={reveal(value){if(value)page.hidden=false}};gates.reveal(false)}function second(){const gates={reveal(value){console.log(value)}};gates.reveal(states[key])}second()`,
    `const states={future:true};function first(){class Gate{reveal(value){if(value)page.hidden=false}}const gate=new Gate;gate.reveal(false)}function second(){class Gate{reveal(value){console.log(value)}}const gate=new Gate;gate.reveal(states[key])}second()`,
    `const access={future:true};function first(){const selected=access[user.role];console.log(selected)}function second(){const selected=false;if(selected)page.hidden=false}second()`,
    `const access={future:true};function reveal(value){{const selected=value;console.log(selected)}{const selected=false;if(selected)page.hidden=false}}reveal(access[user.role])`,
    `const access={future:true};function reveal(value){let selected=value;selected=false;if(selected)page.hidden=false}reveal(access[user.role])`,
    `const access={future:true};function reveal(value){{const value=false;if(value)page.hidden=false}}reveal(access[user.role])`,
    `const selected=access[user.role];try{throw false}catch(selected){if(selected)page.hidden=false}`,
    `const access={future:true};function reveal({allowed:{value}}){if(value)page.hidden=false}reveal({allowed:{value:false},decoy:{value:access[user.role]}})`,
    `const access={future:true};function reveal([allowed]){if(allowed)page.hidden=false}reveal([false,access[user.role]])`,
    `const access={future:true};function reveal([ignored,allowed]){if(allowed)page.hidden=false}reveal([...[access[user.role],false]])`,
    `const access={future:true};function reveal([allowed]){if(allowed)page.hidden=false}reveal([false,...items,access[user.role]])`,
    `const access={future:true};function reveal([ignored,...rest]){if(rest[0])page.hidden=false}reveal([...[access[user.role],false]])`,
    `const access={future:true};function reveal({allowed:canView}){if(canView)page.hidden=false}reveal({allowed:false,decoy:access[user.role]})`,
    `const access={future:true};function reveal({allowed=false}){if(allowed)page.hidden=false}reveal({decoy:access[user.role]})`,
    `const access={future:true};function reveal({allowed,...rest}){if(allowed)page.hidden=false}reveal({allowed:false,decoy:access[user.role]})`,
    `const access={future:true};function reveal({allowed,...rest}){if(rest.allowed)page.hidden=false}reveal({...{allowed:access[user.role]}})`,
    `const access={future:true};const field='allowed';function reveal({[field]:canView}){if(canView)page.hidden=false}reveal({allowed:false,decoy:access[user.role]})`,
    `const access={future:true};const input={allowed:false,decoy:access[user.role]};function reveal({allowed}){if(allowed)page.hidden=false}reveal(input)`,
    `const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({...{allowed:access[user.role]},allowed:false})`,
    `const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({...extra,allowed:false,decoy:access[user.role]})`,
    `const access={future:true};function reveal({allowed}){if(allowed)page.hidden=false}reveal({[dynamic]:access[user.role],allowed:false})`,
    `function render(items){items.forEach(draw)}render(user.menus)`
  ];
  for(const script of parameterEffectNegativeCases)assertNoClientRoleAuthority(script,script);
  const historicalAuthorizationCases=[
    `const ROLE_ACCESS={admin:['/settings.html']}`,
    `const roleMenus={admin:['menu.settings']}`,
    `const rolePages={designer:['/ai-assets.html']}`,
    `const rolePermissions={owner:['users.write']}`,
    `const grantsByRole={admin:['menu.settings']}`,
    `const pagesFor={designer:['/ai-assets.html']}`,
    `const grants={'admin':['menu.settings']}`,
    `const grants={'finance':['menu.metrics']}`,
    `const grants={administrator:['menu.settings']}`,
    `const byRole={regional_manager:menuSettings}`,
    `const byRole={'unlisted_role':menuSettings}`,
    `const byRole={"partner_operator":permissionSet}`,
    'const byRole={[`tenant_role_v9`]:routeList}',
    `const accessByRole/*map*/=/*open*/{/*key*/future_role/*colon*/:/*value*/permissionSet}`,
    `const routesByRole={
      // unlisted role
      future_role:
        routeList
    }`,
    `const featureFlagsByRole\t=\t{\tfuture_role\t:\ttrue\t}`,
    `const catalog=menuSettings;const authorityByRole={future_role:catalog}`,
    `const catalog=['menu.settings'];const byRole={future_role:catalog}`,
    `const byRole={future_role:true}`,
    `const roleKey='future_role';const byRole={[roleKey]:menuSettings};const granted=byRole[user.role]`,
    `const byRole={[getRoleKey()]:permissions};const granted=byRole[user.role]`,
    'const byRole={[`future_${suffix}`]:routes};const granted=byRole[user.role]',
    `const byRole={[ROLE_CONSTANT]:features};const granted=byRole[user.role]`,
    `const roleKey='future_role';const byRole=Object.freeze({[roleKey]:menuSettings});const granted=byRole[user.role]`,
    `const roleKey='future_role';const source={
      /* computed */ [ roleKey ]	:	menuSettings
    };const byRole=source;const granted=byRole?.[user.role]`,
    `const roleKey='future_role';const byRole={[roleKey]:permissions};const granted=byRole[currentUser.roleCode]`,
    `function getCurrentRole(){return user.role}const roleKey='future_role';const byRole={[roleKey]:routes};const granted=byRole[getCurrentRole()]`,
    `const {role:currentRole}=currentUser;const roleKey='future_role';const byRole={[roleKey]:features};const granted=byRole[currentRole]`,
    `function getCurrentRole(){return user.role}const roleKey='future_role';const source={[roleKey]:privileges};const alias=source;const granted=alias?.[getCurrentRole()]`,
    `const {role_code:key}=currentUser;const map={[getKey()]:payload};const selected=map[key];const permissions=selected.permissions`,
    `const key=currentUser.roleCode;const source={[getKey()]:payload};const selected=source?.[key];const privileges=selected.details`,
    `const roleKey='future_role';const matrix={[roleKey]:menuSettings};const key=user['role'];const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:'menu.settings'};const granted=matrix[user['role']]`,
    `const roleKey='future_role';const matrix={[roleKey]:"permissions.read"};const granted=matrix[user?.["role"]]`,
    'const roleKey="future_role";const matrix={[roleKey]:`routes.read`};const granted=matrix[profile?.[`roleCode`]]',
    `const roleKey='future_role';const matrix={[roleKey]:menuSettings};const key=user["role"];const granted=matrix[key]`,
    'const roleKey="future_role";const matrix={[roleKey]:menuSettings};const key=user[`role`];const granted=matrix[key]',
    `const roleKey='future_role';const matrix={[roleKey]:permissions};const key=user?.role;const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:routes};const key=user?.['role'];const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:features};const key=currentUser['roleCode'];const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:privileges};const key=sessionUser["role"];const granted=matrix[key]`,
    'const roleKey="future_role";const matrix={[roleKey]:allowedActions};const key=profile?.[`roleCode`];const granted=matrix[key]',
    `const roleKey='future_role';const matrix={[roleKey]:canAccess};let key;key=user['role'];const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:permissions};let key=user.role;const alias=key;const granted=matrix[alias]`,
    `const roleKey='future_role';const matrix={[roleKey]:routes};const {role:key}=user;const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:features};const {roleCode}=currentUser;const granted=matrix[roleCode]`,
    `const roleKey='future_role';const matrix={[roleKey]:privileges};const field='role';const key=user[field];const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:permissions};const field='role';const alias=field;const key=user[alias];const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:routes};let field;field='role';const key=user[field];const granted=matrix[key]`,
    `function getCurrentRole(){return user.role}const roleKey='future_role';const matrix=Object.freeze({[roleKey]:allowedActions});const key=getCurrentRole();const granted=matrix[key]`,
    `function readIdentity(){return user['role']}const roleKey='future_role';const matrix={[roleKey]:menuSettings};const key=readIdentity();const granted=matrix[key]`,
    `const roleKey='future_role';const matrix={[roleKey]:menuSettings};const granted=matrix[condition?a:b]`,
    'const roleKey="future_role";const matrix={[roleKey]:permissions};const granted=matrix[`role_${suffix}`]',
    `const roleKey='future_role';const matrix={[roleKey]:routes};const granted=matrix[object.value]`,
    `const roleKey='future_role';const matrix={[roleKey]:features};const granted=matrix?.[key]`,
    `const matrix=new Map([['future_role',privileges]]);const granted=matrix.get(condition?a:b)`,
    `const matrix=Object.assign({}, {future_role:permissions});const granted=matrix[key]`,
    `const matrix=Object.fromEntries([['future_role',routes]]);const granted=matrix[key]`,
    `const matrix={future_role:payload};let selected;selected=matrix[key];const permissions=selected.permissions;render(permissions)`,
    `const matrix={future_role:payload};renderPermissions(matrix[key])`,
    `const matrix={future:payload};allowedActions.add(matrix[condition?a:b])`,
    `const matrix={future:payload};permissions.registry.current.add(matrix[user.role])`,
    `const matrix={future:payload};permissions.registry[methods[index]](matrix[user.role])`,
    ...[
      '',
      'consume(matrix[key])',
      'receiver.method(matrix[key])',
      `receiver${Array.from({length:9},(_,index)=>`.layer${index}`).join('')}.method(matrix[key])`,
      'receiver[methods[index]](matrix[key])',
      'receiver?.method?.(matrix[key])',
      'new Consumer(matrix[key])',
      'function pass(value){return value}const result=pass(matrix[key])',
      'Promise.resolve().then(()=>matrix[key])',
      'const wrapped=[matrix[key]]',
      'const wrapped={value:matrix[key]}',
      'const selected=condition?matrix[left]:matrix[right]',
      'const alias=matrix;const next=alias;consume(next[key])'
    ].map(consumer=>`const matrix={future:permissions};${consumer}`),
    `const matrix=Object.freeze({future:permissions})`,
    `const matrix=Object.assign({}, {future:permissions})`,
    `const matrix=Object.fromEntries([['future',permissions]])`,
    `const roleKey='unknown_role';const matrix={[roleKey]:permissions}`,
    `const matrix={future:{nested:permissions}}`,
    `const payload={future:permissions}`,
    `const statusMap={future:permissions}`,
    `const payloadMap={future:{canDelete:true}}`,
    `const matrix={future:document.permissions}`,
    `const permissionsByRole={admin:false};const allowed=permissionsByRole[user.role]`,
    `const routePermissions={admin:null};const allowed=routePermissions[user.role]`,
    `const permissionsByRole={admin:form.permission.checked};const allowed=permissionsByRole[user.role]`,
    `const permissionEndpoints={admin:'/api/admin'};const endpoint=permissionEndpoints[user.role]`,
    `const permissions={admin:true};JSON.stringify(permissions)`,
    `const matrix={admin:false}`,
    `const routes={admin:'/api/admin'};fetch(routes[user.role])`,
    `const endpoints={admin:'/api/admin'};fetch(endpoints[user.role])`,
    `const state={admin:false};const allowed=state[user.role]`,
    `const requestBody={admin:canDelete};fetch('/api/x',{body:JSON.stringify(requestBody)})`,
    ...Array.from({length:9},(_,depth)=>`const mapping={future:permissions};receiver${Array.from({length:depth},(_,index)=>`.child${index}`).join('')}.method(mapping[key])`),
    `const mapping={future:permissions};receiver${Array.from({length:32},(_,index)=>`.child${index}`).join('')}.method(mapping[key])`,
    `const mapping={future:permissions};receiver["child"].current["method"](mapping[key])`,
    `const mapping={future:permissions};receiver?.child?.current?.method?.(mapping[key])`,
    `const mapping={future:permissions};getReceiver().registry.current.method(mapping[key])`,
    `const mapping={future:permissions};receiver.child.method(firstArg,mapping[key],thirdArg)`,
    `const mapping={future:permissions};const selected=mapping[key];receiver.child.current.method(selected)`,
    `const mapping=Object.assign({}, {future:permissions});receiver.child.current.method(mapping[key])`,
    `const mapping=Object.fromEntries([['future',routes]]);receiver.child.current.method(mapping[key])`,
    `const mapping={future:permissions};receiver.child.current.method(mapping[key].nested)`,
    `const matrix={future:payload};permissions.add(matrix[key])`,
    `const mapping={future:payload};actions.push(mapping[selector])`,
    `const source={future:payload};grantedSet.add(source[condition?left:right])`,
    `const mapping={future:permissions};receiver.method(mapping[key])`,
    `const mapping={future:permissions};optionalReceiver?.method?.(mapping[key])`,
    `const mapping={future:payload};const selected=mapping[key];allowedActions.add(selected)`,
    `const mapping={future:payload};const selected=mapping[key];const alias=selected;allowedActions.add(alias)`,
    `const mapping={future:payload};const sink=allowedActions;sink.method(mapping[key])`,
    `const mapping={future:payload};let sink;sink=allowedActions;sink.method(mapping[key])`,
    `const mapping={future:permissions};receiver.method(context,mapping[key])`,
    `const mapping={future:permissions};receiver[operation](mapping[key])`,
    `const mapping=Object.assign({}, {future:permissions});receiver.method(mapping[key])`,
    `const mapping=Object.fromEntries([['future',routes]]);receiver.method(mapping[key])`,
    `const matrix={future_role:payload};const filteredMenus=matrix[key].filter(canSee);render(filteredMenus)`,
    `function x(){return user.role}const roleKey='future_role';const matrix={[roleKey]:permissions};const key=x();const granted=matrix[key]`,
    `const x=function(){return currentUser['roleCode']};const roleKey='future_role';const matrix={[roleKey]:routes};const key=x();const granted=matrix[key]`,
    `const x=()=>user.role;const roleKey='future_role';const matrix={[roleKey]:features};const key=x();const granted=matrix[key]`,
    `const x=()=>{return user['role']};const roleKey='future_role';const matrix={[roleKey]:privileges};const key=x();const granted=matrix[key]`,
    `const x=()=>{const key=user.role;return key};const roleKey='future_role';const matrix={[roleKey]:canAccess};const granted=matrix[x()]`,
    `function a(){return user.role}function b(){return a()}const roleKey='future_role';const matrix={[roleKey]:allowedActions};const granted=matrix[b()]`,
    `function qv(){return user['role']}const alias=qv;const roleKey='future_role';const matrix={[roleKey]:permissions};const key=alias();const granted=matrix[key]`,
    `function qv(){return user['role']}const roleKey='future_role';const matrix={[roleKey]:routes};let key;key=qv();const granted=matrix[key]`,
    `function qv(){return user['role']}const roleKey='future_role';const matrix={[roleKey]:features};const alias=qv();const granted=matrix[alias]`,
    `function qv(){return user['role']}const roleKey='future_role';const matrix={[roleKey]:privileges};const first=qv();const second=first;const granted=matrix[second]`,
    `function qv(){return user['role']}const roleKey='future_role';const matrix={[roleKey]:canAccess};const granted=matrix[qv()]`,
    `function a(){return user.role}function wrapper(){return a()}const roleKey='future_role';const matrix={[roleKey]:allowedActions};const granted=matrix[wrapper()]`,
    `function qv(){return user['role']}const roleKey='future_role';const matrix={[roleKey]:permissions};const granted=matrix[qv?.()]`,
    `function qv(){return user['role']}const alias=qv;const roleKey='future_role';const matrix={[roleKey]:routes};const granted=matrix[alias?.()]`,
    `function randomValueReader(){return user?.['role']}const roleKey='future_role';const matrix={[roleKey]:permissions};const granted=matrix[randomValueReader()]`,
    `function qv/*name*/()/*body*/{/*return*/return (profile?.[\`roleCode\`])}const roleKey='future_role';const matrix={[roleKey]:routes};const granted=matrix[qv()]`,
    `function qv(){return user /*gap*/ [/*field*/'role']}const roleKey='future_role';const matrix={[roleKey]:permissions};const granted=matrix[qv()]`,
    `function qv(){return user /*a*/ ?. /*b*/ ['role']}const roleKey='future_role';const matrix={[roleKey]:routes};const granted=matrix[qv()]`,
    `function qv(){return (
      user?.['role']
    )}const roleKey='future_role';const matrix={[roleKey]:features};const granted=matrix[qv()]`,
    `const qv=()=>(
      user?.['role']
    );const roleKey='future_role';const matrix={[roleKey]:privileges};const granted=matrix[qv()]`,
    `function readLanguage(){return user['language']}const key='zh';const matrix={[key]:permissions};const selected=matrix[readLanguage()]`,
    `function readTheme(){return user.theme}const key='dark';const matrix={[key]:routes};const selected=matrix[readTheme()]`,
    `function readRoleButLanguage(){return user.language}const key='zh';const matrix={[key]:features};const selected=matrix[readRoleButLanguage()]`,
    `function a(){return b()}function b(){return a()}const key='x';const matrix={[key]:permissions};const selected=matrix[a()]`,
    `function outer(){function inner(){return user.role}return user.language}const key='x';const matrix={[key]:permissions};const selected=matrix[outer()]`,
    `function outer(){consume(function(){return user.role});return user.language}const key='x';const matrix={[key]:permissions};const selected=matrix[outer()]`,
    `function outer(){consume(()=>{return user.role});return user.language}const key='x';const matrix={[key]:permissions};const selected=matrix[outer()]`,
    `const roleKey='future_role';const $matrix={[roleKey]:permissions};const $key=user['role'];const granted=$matrix[$key]`,
    `const roleKey='future_role';const matrix={
      /* computed */[roleKey]	:	menuSettings
    };let key;key=/* source */user?.[/* field */'role'];const alias=key;const granted=matrix?.[alias]`,
    `const byRole={[keys[index]]:permissions};const granted=byRole[user.role]`,
    `const byRole={[roleKeys[getCurrentRole()]]:permissions};const granted=byRole[user.role]`,
    `const accessMatrix={future_role:permissionSet};const selected=accessMatrix[user.role]`,
    `const matrix={future_role:['orders.read']};const granted=matrix[user.role]`,
    `const matrix={future_role:flags};const chosen=matrix[user.role];if(chosen.export)open()`,
    `const key=user.role;const matrix={future_role:flags};const chosen=matrix[key]`,
    `const matrix=new Map([['future_role',flags]]);const chosen=matrix.get(user.role)`,
    `const source={future_role:flags};const matrix=source;const chosen=matrix[user.role]`,
    `const matrix=Object.freeze({future_role:permissionSet});const chosen=matrix[user.role]`,
    `const future_role=permissionSet;const matrix={future_role};const chosen=matrix[user.role]`,
    `const matrix={future_role:flags};const chosen=matrix?.[user.role]`,
    `const key=user.role;switch(key){case 'future_role':return menuSettings}`,
    `const key=user.role;if(key==='future_role')return permissionSet`,
    `const key=user?.role;if(
      key==='future_role'
    ){
      return menuSettings
    }`,
    `const permissionsByRole={future_role:'delete'};const permission=permissionsByRole[user.role]`,
    `const routesByRole={future_role:'/settings'};const route=routesByRole[user.role]`,
    'const chosen=`${user.role===\'future_role\'?menuSettings:\'\'}`',
    'const permissionsByRole=new Map([[`future_role`,permissionSet]])',
    `const buttonsByRole={admin:{delete:true}}`,
    `const grants=new Map([['admin',['menu.settings']]])`,
    `switch(user.role){case 'admin': return ['/settings.html']}`,
    `if(role==='admin')return adminMenus`,
    `if('admin'===user.role)return adminMenus`,
    `const menus=user.role==='admin'?adminMenus:[]`,
    `function accessFor(role){return roleMenus[role]||adminMenus}`,
    `function isPrivileged(){return role==='owner'}`
  ];
  const historicalSemanticPositiveCases=new Set([
    `const routes={admin:'/api/admin'};fetch(routes[user.role])`,
    `const endpoints={admin:'/api/admin'};fetch(endpoints[user.role])`,
    `switch(user.role){case 'admin': return ['/settings.html']}`,
    `const menus=user.role==='admin'?adminMenus:[]`
  ]);
  const historicalOriginTask=script=>{
    if(script.includes('methods[index]'))return 'Task217';
    if(/registry\.current|Array\.from\(\{length:32\}/.test(script))return 'Task215';
    if(/\.(?:add|push)\(|receiver\.method|optionalReceiver/.test(script))return 'Task213';
    if(/\bfunction\b|=>/.test(script))return 'Task202';
    if(/\[['"`]role|roleCode['"`]\]|const alias=key|const \{role/.test(script))return 'Task200';
    if(/\{\s*\[|Object\.freeze/.test(script))return 'Task198';
    return 'Task196';
  };
  const r12ReclassificationLedger=historicalAuthorizationCases
    .filter(script=>!historicalSemanticPositiveCases.has(script))
    .map(script=>({
      originalTask:historicalOriginTask(script),
      originalExpectation:'DETECTED',
      currentExpectation:'NOT_DETECTED',
      authorizationDataflow:false,
      reason:'R12 requires an explicit authorization decision; object shape, names, and unused lookup results are insufficient.',
      script
    }));
  assert.equal(r12ReclassificationLedger.length,historicalAuthorizationCases.length-historicalSemanticPositiveCases.size);
  for(const record of r12ReclassificationLedger){
    assert.equal(record.authorizationDataflow,false);
    assertNoClientRoleAuthority(record.script,record.reason);
  }
  for(const script of historicalSemanticPositiveCases)
    assert.throws(()=>assertNoClientRoleAuthority(script,script),script);
  for(const script of [
    `const access={future:true};if(access[user.role])navigation.hidden=false`,
    `const key='future';const access={[key]:true};if(access[user['role']])navigation.disabled=false`,
    `function identity(){return currentUser?.['roleCode']}const access={future:true};if(access[identity()])navigation.hidden=false`,
    `const access=Object.freeze({future:true});const alias=access;if(alias?.[user.role])navigation.hidden=false`,
    `const access=Object.assign({}, {future:true});if(access[user.role])navigation.hidden=false`,
    `const access=Object.fromEntries([['future',true]]);if(access[user.role])navigation.hidden=false`,
    `const access=new Map([['future',true]]);if(access.get(user.role))navigation.hidden=false`,
    `const access={future:true};const selected=access[user.role];const alias=selected;if(alias)navigation.hidden=false`,
    `const access={future:true};if(access[user.role])security.permissions.registry[methods[index]]()`,
    `const access={future:true};session.permissions=access[user.role]`,
    `const access={future:'/api/protected'};fetch(access[user.role])`,
    `const access={future:true};if(access[user.role])location.href='/protected.html'`,
    `const access={future:true};if(access?.[profile?.['roleCode']])navigation.hidden=false`,
    `function choose(key){return access[key]}const access={future:true};if(choose(user.role))navigation.hidden=false`,
    `function choose(mapping,key){return mapping[key]}const access={future:true};if(choose(access,user.role))navigation.hidden=false`,
    `function choose(mapping,key){return mapping[key]}const alias=choose;const access={future:true};if(alias(access,user.role))navigation.hidden=false`,
    `const field='role';const alias=field;const access={future:true};if(access[user[alias]])navigation.hidden=false`,
    `const access={future:true};if(access[user.role])TiantongRbac.bindActions({save:['click',save]})`,
    `function initialize(){page.hidden=false}const access={future:true};if(access[user.role])initialize()`,
    `const access={future:true};if(access[user.role])menu.classList.remove('hidden')`,
    `const access={future:true};if(access[user.role])api('/api/protected')`,
    `const access={future:true};const cache=new Map();cache.set('current',access[user.role]);if(cache.get('current'))page.hidden=false`,
    `const access={future:true};if(access[user.role])menu.innerHTML='<a>Admin</a>'`,
    `const access={future:true};if(access[user.role])navigation.replaceChildren(adminLink)`,
    `const access={future:true};if(access[user.role])localStorage.setItem('permissions',access[user.role])`,
    `const access={future:true};const protectedUrl='/api/protected';if(access[user.role])api(protectedUrl)`,
    `const access={future:true};const protectedPath='/admin.html';if(access[user.role])location.assign(protectedPath)`,
    `const byRole={future:permissions};localStorage.setItem('permissions',byRole[user.role])`,
    `const byRole={future:adminLink};navigation.replaceChildren(byRole[user.role])`,
    `const byRole={future:'/api/admin'};api(byRole[user.role])`,
    `const byRole={future:save};button.addEventListener('click',byRole[user.role])`,
    `const byRole={future:'block'};menu.style.display=byRole[user.role]`,
    `const access={future:true};if(access[user.role])menu.style.display='block'`,
    `const access={future:true};if(access[user.role])page.style.visibility='visible'`,
    `const access={future:true};if(access[user.role])menu.removeAttribute('hidden')`,
    `const access={future:true};if(access[user.role])menu.toggleAttribute('hidden',false)`,
    `const access={future:true};if(access[user.role])menu.style.removeProperty('display')`,
    `const storage=localStorage;const byRole={future:permissions};storage.setItem('permissions',byRole[user.role])`,
    `const byRole={future:permissions};window.localStorage.setItem('permissions',byRole[user.role])`,
    `const byRole={future:permissions};globalThis.sessionStorage.setItem('permissions',byRole[user.role])`,
    `const storage=window.localStorage;const byRole={future:permissions};storage.setItem('permissions',byRole[user.role])`
  ])assert.throws(()=>assertNoClientRoleAuthority(script,script),script);
  for(const script of [
    `const orderStatusMap={draft:true,published:false,archived:true}`,
    `const productState={draft:true,published:false}`,
    `const advertisingState={queued:true,running:false}`,
    `const logisticsState={packed:true,shipped:false}`,
    `const afterSalesState={opened:true,closed:false}`,
    `function roleCode(user){return user.role_code}; const roleLabels={owner:'老板',designer:'设计师'}; label.textContent=roleLabels[roleCode(user)]||user.role_label`,
    `const byRole={future_role:'未来角色'}`,
    'const roleLabels={[`future_role`]:`未来角色`}',
    `const departmentMenuLabels={regional_manager:'区域经理'}`,
    `const roleLabels={future_role:'Menu Manager'}`,
    `const roleMetadata={future_role:{menuLabel:'Settings'}}`,
    `const labelsByRole={future_role:'Permission manager'};label.textContent=labelsByRole[user.role]`,
    `const labelsByRole={future_role:i18n.permissionManager};label.textContent=labelsByRole[user.role]`,
    `const roleMetadata={future_role:{menuLabel:translations.settings}}`,
    `const key=user.role;if(key==='future_role')label.textContent='Permission manager'`,
    `const roleKey='future_role';const roleLabels={[roleKey]:i18n.futureRole};label.textContent=roleLabels[user.role]`,
    `const themeKey='dark';const colors={[themeKey]:'#000'};const selected=colors[currentTheme]`,
    `const localeKey='zh-CN';const languages={[localeKey]:'中文'};const selected=languages[currentLocale]`,
    `const displayKey='future_role';const displayNames={[displayKey]:'未来角色'};label.textContent=displayNames[user.role]`,
    `const objectKey=getObjectKey();const values={[objectKey]:payload};const selected=values[currentSelection]`,
    `const config={maxRetries:3};schedule(config.maxRetries)`,
    `const endpoints={overview:'/api/overview',employee:'/api/employee'}`,
    `const state={summary:{},logs:[]}`,
    `const requestBody={default_permissions:form.permissions.value};fetch('/api/settings',{method:'POST',body:JSON.stringify(requestBody)})`,
    `const projection={department:state.departments,risk:state.risks}`,
    `const widgets={a:makeWidget()};render(widgets.a);const permissions=user.menus`,
    `const config={retry:{max:3}};consume(config.retry,permissions)`,
    `const pageSizes={compact:20,comfortable:40}`,
    `const accessibilityOptions={contrast:true}`,
    `const themeKey='dark';const themes={[themeKey]:darkTheme};const selected=themes[condition?a:b];applyTheme(selected)`,
    `const preferences={compact:true,animations:false};const enabled=preferences[key]`,
    `const themes=Object.assign({}, {dark:darkTheme});applyTheme(themes[key])`,
    `const colors=Object.fromEntries([['brand',palette]]);applyColors(colors[key])`,
    `const values={future:payload};items.push(values[key])`,
    `const values={future:payload};items.allow(values[key])`,
    `const values={future:payload};transactions.push(values[key])`,
    `const values={future:payload};formatter.write(values[key])`,
    `const messages={future:logEntry};logger.info(messages[key])`,
    `const copy={future:i18n.future};ui.render(copy[key])`,
    `const copy={future:i18n.future};ui${Array.from({length:8},(_,index)=>`.layer${index}`).join('')}.render(copy[key])`,
    `const translations={future:i18n.future};logEntries.add(translations[key])`,
    `const labels={future:'Future'};displayList.add(labels[key])`,
    `const key='x';const statusMap={[key]:statusPayload};const selected=statusMap[user.role]`,
    `const roleKey='future_role';const themesByRole={[roleKey]:darkTheme};const selected=themesByRole[user.role]`,
    `const roleKey='future_role';const colorsByRole={[roleKey]:palette};const selected=colorsByRole[user.role]`,
    `const roleKey='future_role';const languagesByRole={[roleKey]:translation};const selected=languagesByRole[user.role]`,
    `const roleKey='future_role';const themesByRole={[keys[index]]:darkTheme};const selected=themesByRole[user.role]`,
    `const labels={zh:'中文'};const selected=labels[user['language']]`,
    `const themes={dark:palette};const selected=themes[user["theme"]]`,
    `const field='language';const labels={zh:i18n.zh};const selected=labels[user[field]]`,
    `const field='theme';const themes={[field]:palette};const selected=themes[user[field]]`,
    `const roleKey='x';const themes={[roleKey]:darkTheme};const selected=themes[user.role];if(selected)applyTheme(selected)`,
    `const themesByRole={future:darkTheme/* permissions */};const selected=themesByRole[user.role]`,
    `const colorsByRole={future:palette/* menu.settings */};const selected=colorsByRole[user.role]`,
    `const statusMap={future:statusPayload/* permission */};const selected=statusMap[user.role]`,
    `const themesByRole={future:darkTheme/* "menu.settings" */};const selected=themesByRole[user.role]`,
    `const statusMap={future:statusPayload/* "/settings.html" */};const selected=statusMap[user.role]`,
    `const readRegion=()=>user.region;const regions={north:'华北'};label.textContent=regions[readRegion()]`,
    `const readDisplayName=function(){return user.displayName};label.textContent=readDisplayName()`,
    `function randomValueReader(){return user.role}label.textContent=randomValueReader()`,
    `function readMenus(){return user.menus}const serverMenus=readMenus();const allowed=serverMenus.some(item=>item.permission===requiredMenu)`,
    `function pageRole(){return user.language}const label=pageRole()`,
    `function accessFor(){return theme.palette}applyTheme(accessFor())`,
    `function canOpenDeploy(){return false}const visible=canOpenDeploy()`,
    `function readOrder(){return order.id}const rows={a:payload};const selected=rows[readOrder()]`,
    `const fixture="function readIdentity(){return user['role']} const granted=matrix[readIdentity()]"`,
    `// function readIdentity(){return user['role']} const granted=matrix[readIdentity()]
    const harmless=true`,
    `const serverMenus=user.menus;const allowed=serverMenus.some(item=>item.permission===requiredMenu)`,
    `const fixture="const roleKey='future_role'; const byRole={[roleKey]:menuSettings}"`,
    `const fixture="if(currentRole===x)return permissions"`,
    `// if(currentRole===x)return permissions
    const harmless=true`,
    `// const roleKey='future_role';const matrix={[roleKey]:permissions};const key=user['role'];const granted=matrix[key]
    const harmless=true`,
    `const fixture="const roleKey='future_role';const matrix={[roleKey]:permissions};const key=user['role'];const granted=matrix[key]"`,
    `const fixture=\`safe
    const roleKey='future_role';const matrix={[roleKey]:permissions};const key=user['role'];const granted=matrix[key]\``,
    `// const roleKey='future_role'; const byRole={[roleKey]:menuSettings}
    const harmless=true`,
    `if(user.role==='admin')label.textContent='管理员'`,
    `const label=user.role==='admin'?'管理员':'员工'`,
    `switch(user.role){case 'admin': return '管理员'; default: return '员工'}`,
    `const serverMenus=user.menus.filter(item=>item&&item.permission);const allowed=serverMenus.some(item=>item.permission===requiredMenu)`,
    `const ROUTE_PERMISSIONS={'/settings.html':'menu.settings'};const permissions=new Set(user.menus.map(item=>item.permission));permissions.has(ROUTE_PERMISSIONS[path])`
  ])assertNoClientRoleAuthority(script,script);
  assert.doesNotMatch(`${findClientRoleAuthorityAst}`,/\b(?:owner|admin|designer|regional_manager)\b/i,'detector must not hardcode role names');
  const removedLexerSymbols=[['mask','NonExecutable'],['scan','Quoted'],['scan','Code']].map(parts=>parts.join(''));
  assert.ok(removedLexerSymbols.every(symbol=>!`${findClientRoleAuthorityAst}`.includes(symbol)),'detector must use Acorn instead of a handwritten lexer');
  assert.doesNotMatch(`${findClientRoleAuthorityAst}`,/\b(?:eval|new Function|vm\.)\b/,'detector must not execute scanned code');
});

test('server-returned rows, never page-open permission, prove broader employee scope',()=>{
  for(const name of ['employee-evolution-center.html','review-learning-center.html']){
    const html=readFileSync(new URL(`../frontend/${name}`,import.meta.url),'utf8');
    assert.doesNotMatch(html,/function hasServerScope\(\)[^{]*\{[^}]*TiantongRbac\.canOpen/s,name);
    assert.match(html,/function hasServerScope\(\)[\s\S]*?\.some\(row=>row\.employee_code&&row\.employee_code!==username\)/,name);
  }
});

test('all 318 protected-page handlers are migrated without inline event code',()=>{
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
  assert.equal(migrated,318);
  assert.equal(literalActions,255);
  assert.equal(dynamicActions,63);
  assert.equal(migratedHandlerIds.size,318);
  assert.equal(sharedLogoutBindings,42);
  assert.equal(files.reduce((count,file)=>count+(readFileSync(file,'utf8').match(/-disabled-entry/g)||[]).length,0),16);
  const research=readFileSync(new URL('../frontend/research-records.html',import.meta.url),'utf8');
  assert.equal((research.match(/TiantongRbac\.registerDynamicAction\(/g)||[]).length,1);
});

test('shared guard contains no dynamic event attributes or string execution',()=>{
  assert.doesNotMatch(guardScript,/\.on[a-z]+\s*=/i);
  assert.doesNotMatch(guardScript,/setAttribute\s*\(\s*['"]on/i);
  assert.doesNotMatch(guardScript,/\beval\s*\(|\bnew\s+Function\b/);
});

test('store table dynamic action attributes remain quoted',()=>{
  const html=readFileSync(new URL('../frontend/stores.html',import.meta.url),'utf8');
  assert.equal((html.match(/;\}\)\}\">/g)||[]).length,2);
  assert.doesNotMatch(html,/;\}\)\}\}>/);
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
