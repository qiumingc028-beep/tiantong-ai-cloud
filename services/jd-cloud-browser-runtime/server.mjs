import Fastify from 'fastify';
import { chromium } from 'playwright';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
const app=Fastify({logger:false}); const root=process.env.JD_PROFILE_ROOT||'/tmp/jd-cloud-profiles'; const sessions=new Map();
const key=()=>Buffer.from(process.env.JD_SESSION_MASTER_KEY||'', 'base64');
function id(p){return `${p.tenant_id}:${p.company_id}:${p.store_id}:${p.platform}`}
app.get('/internal/jd-browser/health',async()=>({ok:true,service:'jd-cloud-browser-runtime',sessions:sessions.size}));
app.post('/internal/jd-browser/capture',async(req,reply)=>{if(req.headers['x-internal-token']!==process.env.JD_BROWSER_INTERNAL_TOKEN)return reply.code(401).send({error:'UNAUTHORIZED'});const p=req.body||{},s=sessions.get(id(p));if(!s)return reply.code(409).send({status:'LOGIN_REQUIRED'});const page=s.context.pages()[0]||await s.context.newPage();await page.goto('https://shop.jd.com/jdm/home',{waitUntil:'domcontentloaded'});return {status:'OK',data:{source:'jd_cloud_playwright',captured_at:new Date().toISOString(),store_id:p.store_id}}});
app.post('/internal/jd-browser/sessions',async(req,reply)=>{if(req.headers['x-owner-token']!==process.env.JD_OWNER_TOKEN)return reply.code(403).send({error:'OWNER_REQUIRED'});const p=req.body||{},sid=id(p),dir=path.join(root,crypto.createHash('sha256').update(sid).digest('hex'));await fs.mkdir(dir,{recursive:true,mode:0o700});const context=await chromium.launchPersistentContext(dir,{headless:false});sessions.set(sid,{context,expires:Date.now()+600000});return {session_id:sid,expires_in:600}});
app.delete('/internal/jd-browser/sessions/:sid',async(req)=>{const s=sessions.get(req.params.sid);if(s){await s.context.close();sessions.delete(req.params.sid)}return {ok:true}});
app.listen({host:'0.0.0.0',port:Number(process.env.PORT||8787)});
