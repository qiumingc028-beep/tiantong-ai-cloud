import Fastify from 'fastify';
import { chromium } from 'playwright';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
const app=Fastify({logger:false}); const root=process.env.JD_PROFILE_ROOT||'/tmp/jd-cloud-profiles'; const sessions=new Map();
const internal=process.env.JD_BROWSER_INTERNAL_TOKEN||''; if(Buffer.byteLength(internal)<32) throw new Error('JD_BROWSER_INTERNAL_TOKEN_REQUIRED');
if(!process.env.JD_SESSION_MASTER_KEY || Buffer.from(process.env.JD_SESSION_MASTER_KEY,'base64').length!==32) throw new Error('JD_SESSION_MASTER_KEY_REQUIRED');
const key=()=>Buffer.from(process.env.JD_SESSION_MASTER_KEY, 'base64');
const auth=(req,reply)=>{const got=Buffer.from(String(req.headers['x-internal-token']||''));const expected=Buffer.from(internal);if(got.length!==expected.length||!crypto.timingSafeEqual(got,expected))return reply.code(401).send({error:'UNAUTHORIZED'});};
function id(p){return `${p.tenant_id}:${p.company_id}:${p.store_id}:${p.platform}`}
app.get('/internal/jd-browser/health',async(req,reply)=>{auth(req,reply);return {ok:true,service:'jd-cloud-browser-runtime',sessions:sessions.size}});
app.post('/internal/jd-browser/capture',async(req,reply)=>{auth(req,reply);const p=req.body||{},s=sessions.get(id(p));if(!s)return reply.code(409).send({status:'LOGIN_REQUIRED',data:{}});const page=s.context.pages()[0]||await s.context.newPage();await page.goto('https://shop.jd.com/jdm/home',{waitUntil:'domcontentloaded'});const metrics=await page.evaluate(()=>Object.fromEntries([...document.querySelectorAll('[data-metric]')].map(n=>[n.getAttribute('data-metric'),n.textContent?.trim()]).filter(([k,v])=>k&&v)));if(!Object.keys(metrics).length)return reply.code(422).send({status:'JD_METRIC_NOT_FOUND',data:{}});return {status:'OK',data:{source:'jd_cloud_playwright',captured_at:new Date().toISOString(),store_id:p.store_id,metrics}}});
app.post('/internal/jd-browser/sessions',async(req,reply)=>{auth(req,reply);const p=req.body||{},sid=id(p),dir=path.join(root,crypto.createHash('sha256').update(sid).digest('hex'));await fs.mkdir(dir,{recursive:true,mode:0o700});const context=await chromium.launchPersistentContext(dir,{headless:false});sessions.set(sid,{context,expires:Date.now()+600000});return {session_id:sid,expires_in:600}});
app.get('/internal/jd-browser/sessions/:sid',async(req,reply)=>{auth(req,reply);return {status:sessions.has(req.params.sid)?'ACTIVE':'REVOKED'}});
app.delete('/internal/jd-browser/sessions/:sid',async(req,reply)=>{auth(req,reply);const s=sessions.get(req.params.sid);if(s){await s.context.close();sessions.delete(req.params.sid)}return {ok:true}});
app.listen({host:'0.0.0.0',port:Number(process.env.PORT||8787)});
