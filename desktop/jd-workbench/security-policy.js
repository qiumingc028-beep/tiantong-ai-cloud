'use strict';

// This is deliberately an exact-host list. Never replace it with suffix matching
// or a wildcard. Newly observed JD hosts must be reviewed and shipped in a signed
// client release before the remote page may contact them.
const JD_HTTPS_HOSTS = Object.freeze(new Set([
  'shop.jd.com',
  'passport.shop.jd.com',
  'passport.jd.com',
  'jshopx.jd.com',
  'jm.jd.com',
  'sz.jd.com',
  'jzt.jd.com',
  'trade-order-jdm.jd.com',
  'ware.shop.jd.com',
  'mkt.shop.jd.com',
  'storage.jd.com',
  'storage.360buyimg.com',
  'static.360buyimg.com',
  'misc.360buyimg.com',
  'img10.360buyimg.com',
  'img11.360buyimg.com',
  'img12.360buyimg.com',
  'img13.360buyimg.com',
  'img14.360buyimg.com'
]));

// Human authentication is not authorized at host scope. Both the visible main
// frame and the POST target must match one of these reviewed host/path pairs.
const JD_AUTH_ROUTES = Object.freeze([
  Object.freeze({ hostname: 'passport.jd.com', pathname: '/new/login.aspx' }),
  Object.freeze({ hostname: 'passport.shop.jd.com', pathname: '/login/index.action/jdm' })
]);

const READ_ONLY_METHODS = Object.freeze(new Set(['GET', 'HEAD']));
const BLOCKED_RESOURCE_TYPES = Object.freeze(new Set(['webSocket', 'ping', 'cspReport']));
const STATIC_RESOURCE_TYPES = Object.freeze(new Set(['stylesheet', 'script', 'image', 'font', 'media']));
const JD_STATIC_HOSTS = Object.freeze(new Set([
  'shop.jd.com',
  'passport.shop.jd.com',
  'passport.jd.com',
  'storage.jd.com',
  'storage.360buyimg.com',
  'static.360buyimg.com',
  'misc.360buyimg.com',
  'img10.360buyimg.com',
  'img11.360buyimg.com',
  'img12.360buyimg.com',
  'img13.360buyimg.com',
  'img14.360buyimg.com'
]));
const HUMAN_ACTION_MARKERS = Object.freeze([
  'captcha',
  'challenge',
  'risk-control',
  'riskcontrol',
  'safe-verify',
  'security-check',
  'verify-code',
  'verifycode'
]);

function parseAllowedHttpsUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    const validPort = parsed.port === '' || parsed.port === '443';
    const hasNoEmbeddedCredentials = parsed.username === '' && parsed.password === '';
    if (
      parsed.protocol !== 'https:' ||
      !validPort ||
      !hasNoEmbeddedCredentials ||
      !JD_HTTPS_HOSTS.has(parsed.hostname)
    ) {
      return null;
    }
    return parsed;
  } catch (_error) {
    return null;
  }
}

function isExactAuthenticationRoute(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  return Boolean(parsed && JD_AUTH_ROUTES.some(
    (route) => route.hostname === parsed.hostname && route.pathname === parsed.pathname
  ));
}

function isAuditedMainFrameRoute(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  if (!parsed) return false;
  if (isExactAuthenticationRoute(parsed.href)) return true;
  return parsed.hostname === 'shop.jd.com' && parsed.pathname === '/';
}

function classifyRequest({
  url,
  method,
  resourceType,
  currentMainFrameUrl,
  isActive,
  isMainFrameSource
}) {
  // Partition activity is checked before URL or method. A detached, locked or
  // background store session has no network capability, including cached pages,
  // service workers and otherwise allowlisted GET requests.
  if (isActive !== true) {
    return Object.freeze({ allow: false, code: 'INACTIVE_PARTITION' });
  }

  const target = parseAllowedHttpsUrl(url);
  if (!target) {
    return Object.freeze({ allow: false, code: 'UNKNOWN_DOMAIN' });
  }

  if (BLOCKED_RESOURCE_TYPES.has(resourceType)) {
    return Object.freeze({ allow: false, code: 'BACKGROUND_CHANNEL_BLOCKED' });
  }

  const normalizedMethod = String(method || '').toUpperCase();
  if (READ_ONLY_METHODS.has(normalizedMethod)) {
    if (resourceType === 'mainFrame' && isAuditedMainFrameRoute(target.href)) {
      return Object.freeze({ allow: true, code: 'AUDITED_MAIN_FRAME' });
    }
    if (STATIC_RESOURCE_TYPES.has(resourceType) && JD_STATIC_HOSTS.has(target.hostname)) {
      return Object.freeze({ allow: true, code: 'STATIC_RESOURCE' });
    }
    return Object.freeze({ allow: false, code: 'ENDPOINT_NOT_AUDITED' });
  }

  // The only non-idempotent exception is a human-entered login request from an
  // exact reviewed JD login path to another exact reviewed JD login path. It
  // must originate from the active view's main frame. Once the main frame leaves
  // the reviewed path this exception closes automatically.
  if (
    normalizedMethod === 'POST' &&
    isMainFrameSource === true &&
    isExactAuthenticationRoute(currentMainFrameUrl) &&
    isExactAuthenticationRoute(target.href)
  ) {
    return Object.freeze({ allow: true, code: 'HUMAN_AUTHENTICATION' });
  }

  return Object.freeze({ allow: false, code: 'READ_ONLY_WRITE_BLOCKED' });
}

function detectHumanActionFromUrl(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  if (!parsed) {
    return 'UNKNOWN_DOMAIN';
  }
  const route = `${parsed.pathname}${parsed.search}`.toLowerCase();
  return HUMAN_ACTION_MARKERS.some((marker) => route.includes(marker))
    ? 'RISK_OR_CAPTCHA'
    : null;
}

function hostnameForStatus(rawUrl) {
  try {
    return new URL(rawUrl).hostname || 'unknown';
  } catch (_error) {
    return 'unknown';
  }
}

module.exports = Object.freeze({
  JD_HTTPS_HOSTS,
  JD_AUTH_ROUTES,
  READ_ONLY_METHODS,
  STATIC_RESOURCE_TYPES,
  classifyRequest,
  detectHumanActionFromUrl,
  hostnameForStatus,
  isAuditedMainFrameRoute,
  isExactAuthenticationRoute,
  parseAllowedHttpsUrl
});
