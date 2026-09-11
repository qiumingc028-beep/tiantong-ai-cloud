'use strict';

// R294 only retains explicitly allowlisted operating metrics. It never returns
// raw page text, form values, cookies, credentials, buyer names, phone numbers
// or delivery addresses.
const METRIC_DEFINITIONS = Object.freeze([
  Object.freeze({ key: 'sales_amount', label: '成交金额', category: 'sales', aliases: ['成交金额', '成交额'] }),
  Object.freeze({ key: 'sales_orders', label: '成交单量', category: 'orders', aliases: ['成交单量', '成交订单量', '成交订单数'] }),
  Object.freeze({ key: 'sales_customers', label: '成交客户数', category: 'sales', aliases: ['成交客户数', '成交客户'] }),
  Object.freeze({ key: 'conversion_rate', label: '成交转化率', category: 'sales', aliases: ['成交转化率', '转化率'] }),
  Object.freeze({ key: 'product_units', label: '成交商品件数', category: 'sales', aliases: ['成交商品件数', '成交件数'] }),
  Object.freeze({ key: 'visitors', label: '店铺访客数', category: 'sales', aliases: ['店铺访客数', '访客数'] }),
  Object.freeze({ key: 'page_views', label: '店铺浏览量', category: 'sales', aliases: ['店铺浏览量', '浏览量'] }),
  Object.freeze({ key: 'month_sales', label: '月成交', category: 'sales', aliases: ['月成交'] }),
  Object.freeze({ key: 'year_sales', label: '年成交', category: 'sales', aliases: ['年成交'] }),
  Object.freeze({ key: 'ad_spend', label: '快车花费', category: 'promotion', aliases: ['快车花费', '广告消耗'] }),
  Object.freeze({ key: 'ad_impressions', label: '快车展现数', category: 'promotion', aliases: ['快车展现数', '展现数'] }),
  Object.freeze({ key: 'ad_clicks', label: '快车点击数', category: 'promotion', aliases: ['快车点击数', '点击数'] }),
  Object.freeze({ key: 'ad_ctr', label: '快车点击率', category: 'promotion', aliases: ['快车点击率', '点击率'] }),
  Object.freeze({ key: 'ad_cpm', label: '快车千次展现成本', category: 'promotion', aliases: ['快车千次展现成本', '千次展现成本'] }),
  Object.freeze({ key: 'ad_cpc', label: '快车平均点击成本', category: 'promotion', aliases: ['快车平均点击成本', '平均点击成本'] }),
  Object.freeze({ key: 'pending_shipments', label: '待发货订单', category: 'orders', aliases: ['近三月待发货', '待发货订单', '待出库'] }),
  Object.freeze({ key: 'pending_refunds', label: '待处理售后', category: 'refunds', aliases: ['待处理售后', '待审核售后', '待收货售后'] }),
  Object.freeze({ key: 'inventory_risk', label: '库存风险', category: 'inventory', aliases: ['库存风险', '缺货预警'] })
]);

const VALUE_PATTERN = /^(?:[¥￥]\s*)?(?:[-—]+|\d[\d,]*(?:\.\d+)?(?:%|万|亿|元|笔|单|人|次|件|个|SKU)?)$/i;

function normalizeLine(value) {
  return String(value || '').replace(/[\u00a0\u2000-\u200b]/g, ' ').replace(/\s+/g, ' ').trim();
}

function sanitizeValue(value) {
  const cleaned = normalizeLine(value).replace(/^([¥￥])\s+/, '$1');
  return cleaned.length <= 32 && VALUE_PATTERN.test(cleaned) ? cleaned : null;
}

function extractMetricsFromLines(rawLines) {
  const lines = Array.from(rawLines || [], normalizeLine).filter(Boolean).slice(0, 12000);
  const metrics = [];
  for (const definition of METRIC_DEFINITIONS) {
    let found = null;
    for (const alias of [...definition.aliases].sort((a, b) => b.length - a.length)) {
      for (let index = 0; index < lines.length && !found; index += 1) {
        const line = lines[index];
        if (line === alias) {
          for (let offset = 1; offset <= 5 && index + offset < lines.length; offset += 1) {
            const candidate = sanitizeValue(lines[index + offset]);
            if (candidate !== null) {
              found = candidate;
              break;
            }
          }
        } else if (line.startsWith(alias)) {
          const candidate = sanitizeValue(line.slice(alias.length).replace(/^[:：\s]+/, ''));
          if (candidate !== null) found = candidate;
        }
      }
      if (found !== null) break;
    }
    if (found !== null) {
      metrics.push(Object.freeze({
        key: definition.key,
        label: definition.label,
        category: definition.category,
        value: found
      }));
    }
  }
  return Object.freeze(metrics);
}

function detectPageType(rawUrl, title = '', bodySample = '') {
  let hostname = '';
  let pathname = '';
  try {
    const parsed = new URL(rawUrl);
    hostname = parsed.hostname;
    pathname = parsed.pathname.toLowerCase();
  } catch (_error) {
    return 'UNKNOWN';
  }
  const hints = `${title} ${bodySample}`;
  if (hostname === 'shop.jd.com' && (pathname === '/' || pathname.startsWith('/jdm/home'))) return 'JDM_HOME';
  if (hostname === 'sz.jd.com' || /京东商智|经营概览/.test(hints)) return 'BUSINESS_INTELLIGENCE';
  if (/订单导出/.test(hints) || pathname.includes('export')) return 'ORDER_EXPORT';
  if (hostname === 'trade-order-jdm.jd.com' || pathname.includes('order')) return 'ORDERS';
  if (/售后|退款/.test(hints)) return 'REFUNDS';
  if (/库存|仓储/.test(hints)) return 'INVENTORY';
  if (hostname === 'jzt.jd.com' || pathname.includes('promotion')) return 'PROMOTION';
  if (/商品/.test(hints) || hostname === 'ware.shop.jd.com') return 'PRODUCTS';
  return 'JD_PAGE';
}

function buildRecognizerScript() {
  const definitions = JSON.stringify(METRIC_DEFINITIONS);
  return `(() => {
    const definitions = ${definitions};
    const valuePattern = /^(?:[¥￥]\\s*)?(?:[-—]+|\\d[\\d,]*(?:\\.\\d+)?(?:%|万|亿|元|笔|单|人|次|件|个|SKU)?)$/i;
    const normalize = (value) => String(value || '').replace(/[\\u00a0\\u2000-\\u200b]/g, ' ').replace(/\\s+/g, ' ').trim();
    const sanitize = (value) => {
      const cleaned = normalize(value).replace(/^([¥￥])\\s+/, '$1');
      return cleaned.length <= 32 && valuePattern.test(cleaned) ? cleaned : null;
    };
    const bodyText = document.body ? String(document.body.innerText || '') : '';
    const lines = bodyText.split(/\\r?\\n/).map(normalize).filter(Boolean).slice(0, 12000);
    const metrics = [];
    for (const definition of definitions) {
      let found = null;
      const aliases = [...definition.aliases].sort((a, b) => b.length - a.length);
      for (const alias of aliases) {
        for (let index = 0; index < lines.length && found === null; index += 1) {
          const line = lines[index];
          if (line === alias) {
            for (let offset = 1; offset <= 5 && index + offset < lines.length; offset += 1) {
              const candidate = sanitize(lines[index + offset]);
              if (candidate !== null) { found = candidate; break; }
            }
          } else if (line.startsWith(alias)) {
            const candidate = sanitize(line.slice(alias.length).replace(/^[:：\\s]+/, ''));
            if (candidate !== null) found = candidate;
          }
        }
        if (found !== null) break;
      }
      if (found !== null) metrics.push({ key: definition.key, label: definition.label, category: definition.category, value: found });
    }
    const title = String(document.title || '').slice(0, 160);
    const url = String(location.href || '').slice(0, 2048);
    const hints = title + ' ' + lines.slice(0, 150).join(' ');
    const host = String(location.hostname || '');
    const path = String(location.pathname || '').toLowerCase();
    let pageType = 'JD_PAGE';
    if (host === 'shop.jd.com' && (path === '/' || path.startsWith('/jdm/home'))) pageType = 'JDM_HOME';
    else if (host === 'sz.jd.com' || /京东商智|经营概览/.test(hints)) pageType = 'BUSINESS_INTELLIGENCE';
    else if (/订单导出/.test(hints) || path.includes('export')) pageType = 'ORDER_EXPORT';
    else if (host === 'trade-order-jdm.jd.com' || path.includes('order')) pageType = 'ORDERS';
    else if (/售后|退款/.test(hints)) pageType = 'REFUNDS';
    else if (/库存|仓储/.test(hints)) pageType = 'INVENTORY';
    else if (host === 'jzt.jd.com' || path.includes('promotion')) pageType = 'PROMOTION';
    else if (/商品/.test(hints) || host === 'ware.shop.jd.com') pageType = 'PRODUCTS';
    return { url, title, pageType, metrics };
  })()`;
}

module.exports = Object.freeze({
  METRIC_DEFINITIONS,
  buildRecognizerScript,
  detectPageType,
  extractMetricsFromLines
});
