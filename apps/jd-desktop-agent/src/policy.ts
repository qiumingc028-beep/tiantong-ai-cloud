export const ALLOWED_PAGE_PREFIXES=['/shop/home','/shop/order','/shop/afterSale','/shop/inventory','/jzt/'] as const;
export const BLOCKED_WRITE_TERMS=['submit','confirm','delete','remove','deliver','ship','refund','price','stock','inventory','campaign','promotion'];
export function isAllowedPage(url:string){try{return ALLOWED_PAGE_PREFIXES.some(p=>new URL(url).pathname.startsWith(p))}catch{return false}}
const READONLY_POST_PATHS=['/api/query','/api/search','/api/report'];
export function isBusinessWrite(url:string,method:string,body=''){const u=new URL(url);const v=`${u.pathname} ${body}`.toLowerCase();if(method.toUpperCase()==='GET')return false;if(method.toUpperCase()==='POST'&&READONLY_POST_PATHS.some(p=>u.pathname===p)&&!BLOCKED_WRITE_TERMS.some(t=>v.includes(t)))return false;return true}
