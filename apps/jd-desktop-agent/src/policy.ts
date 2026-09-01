export const ALLOWED_PAGE_PREFIXES=['/shop/home','/shop/order','/shop/afterSale','/shop/inventory','/jzt/'] as const;
export const BLOCKED_WRITE_TERMS=['submit','confirm','delete','remove','deliver','ship','refund','price','stock','inventory','campaign','promotion'];
export function isAllowedPage(url:string){try{return ALLOWED_PAGE_PREFIXES.some(p=>new URL(url).pathname.startsWith(p))}catch{return false}}
export function isBusinessWrite(url:string,method:string,body=''){const v=`${url} ${method} ${body}`.toLowerCase();return method.toUpperCase()!=='GET'||BLOCKED_WRITE_TERMS.some(t=>v.includes(t))}
