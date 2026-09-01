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
  'wl.jd.com',
  'sgm-static.jd.com',
  'gias.jd.com',
  'seq.jd.com',
  'jcap.m.jd.com',
  'jrsecstatic.jdpay.com',
  'pageframe.jd.com',
  'sff.jd.com',
  'img10.360buyimg.com',
  'img11.360buyimg.com',
  'img12.360buyimg.com',
  'img13.360buyimg.com',
  'img14.360buyimg.com'
]));

// Only these official JD document hosts may replace the visible top-level page.
// Subresources may use the broader exact-host list above, but they never gain
// top-level navigation authority.
const JD_TOP_LEVEL_HOSTS = Object.freeze(new Set([
  'shop.jd.com',
  'passport.shop.jd.com',
  'passport.jd.com',
  'jshopx.jd.com',
  'jm.jd.com',
  'sz.jd.com',
  'jzt.jd.com',
  'trade-order-jdm.jd.com',
  'ware.shop.jd.com',
  'mkt.shop.jd.com'
]));

const JD_AUTHENTICATION_PAGE_HOSTS = Object.freeze(new Set([
  'passport.shop.jd.com',
  'passport.jd.com',
  'jshopx.jd.com'
]));

// Human authentication is not authorized at host scope. Both the visible main
// frame and the POST target must match one of these reviewed host/path pairs.
const JD_AUTH_ROUTES = Object.freeze([
  Object.freeze({ hostname: 'passport.jd.com', pathname: '/new/login.aspx' }),
  Object.freeze({ hostname: 'passport.shop.jd.com', pathname: '/login/index.action' }),
  Object.freeze({ hostname: 'passport.shop.jd.com', pathname: '/login/index.action/jdm' })
]);

// Exact, visible merchant-shell documents reviewed for read-only navigation.
// Keep this separate from API/static authority: matching one of these routes
// never grants XHR/fetch access and never permits a non-GET business request.
const JD_MAIN_FRAME_ROUTES = Object.freeze([
  Object.freeze({ hostname: 'shop.jd.com', pathname: '/' }),
  Object.freeze({ hostname: 'shop.jd.com', pathname: '/jdm/home' }),
  Object.freeze({ hostname: 'shop.jd.com', pathname: '/jdm/home/' })
]);

// The current official 京麦 login page performs its configuration and
// credential exchange through these exact first-party authentication targets.
// Access is still conditional on the active visible main frame being one of
// JD_AUTH_ROUTES, so this authority disappears as soon as login completes.
const JD_AUTH_API_HOSTS = Object.freeze(new Set([
  'passport.shop.jd.com',
  'passport.jd.com'
]));
const JD_AUTH_API_ROUTES = Object.freeze([
  Object.freeze({ hostname: 'sff.jd.com', pathname: '/api' })
]);
const JD_AUTH_API_OPERATIONS = Object.freeze(new Set([
  'dsm.account.service.VenderAccountConfigFacade.getConfig',
  'dsm.account.service.LoginFacade.login'
]));
const JD_AUTH_API_OPERATION_PREFIXES = Object.freeze([]);
const JD_READ_ONLY_RPC_METHOD_PREFIXES = Object.freeze([]);
const JD_READ_ONLY_RPC_OPERATIONS = Object.freeze(new Set(['dsm.order.queryOrderList']));
const JD_WRITE_RPC_MARKERS = Object.freeze([
  'create', 'update', 'save', 'delete', 'remove', 'add', 'set',
  'submit', 'commit', 'confirm', 'cancel', 'close', 'refund',
  'return', 'ship', 'deliver', 'publish', 'modify', 'edit', 'change',
  'bind', 'unbind', 'pay', 'upload', 'import', 'export', 'sync',
  'execute', 'batch', 'operate', 'enable', 'disable', 'approve',
  'reject', 'adjust', 'lock', 'unlock', 'write', 'send', 'issue',
  'grant', 'revoke'
]);
const AUTHENTICATION_METHODS = Object.freeze(new Set(['GET', 'HEAD', 'POST', 'OPTIONS']));

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
  'wl.jd.com',
  'sgm-static.jd.com',
  'gias.jd.com',
  'seq.jd.com',
  'jcap.m.jd.com',
  'jrsecstatic.jdpay.com',
  'pageframe.jd.com',
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

function isAuthenticationApiTarget(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  if (!parsed) return false;
  if (JD_AUTH_API_HOSTS.has(parsed.hostname)) return true;
  const isExactGatewayRoute = JD_AUTH_API_ROUTES.some(
    (route) => route.hostname === parsed.hostname && route.pathname === parsed.pathname
  );
  const operation = parsed.searchParams.get('api') || '';
  const isAccountOperation = JD_AUTH_API_OPERATION_PREFIXES.some(
    (prefix) => operation.startsWith(prefix)
  );
  return isExactGatewayRoute && (
    JD_AUTH_API_OPERATIONS.has(operation) || isAccountOperation
  );
}

function isSffAuthenticationAccountTarget(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  return Boolean(
    parsed &&
    parsed.hostname === 'sff.jd.com' &&
    parsed.pathname === '/api' &&
    JD_AUTH_API_OPERATION_PREFIXES.some(
      (prefix) => (parsed.searchParams.get('api') || '').startsWith(prefix)
    )
  );
}

function isSffReadOnlyRpcTarget(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  if (!parsed || parsed.hostname !== 'sff.jd.com' || parsed.pathname !== '/api') {
    return false;
  }
  const operation = parsed.searchParams.get('api') || '';
  if (!/^[A-Za-z0-9._-]{1,200}$/.test(operation)) return false;
  const methodName = operation.split('.').pop().toLowerCase();
  if (JD_WRITE_RPC_MARKERS.some((marker) => methodName.includes(marker))) {
    return false;
  }
  return JD_READ_ONLY_RPC_OPERATIONS.has(operation) || JD_READ_ONLY_RPC_METHOD_PREFIXES.some(
    (prefix) => methodName.startsWith(prefix)
  );
}

function isSffWriteRpcTarget(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  if (!parsed || parsed.hostname !== 'sff.jd.com' || parsed.pathname !== '/api') {
    return false;
  }
  const operation = parsed.searchParams.get('api') || '';
  if (!/^[A-Za-z0-9._-]{1,200}$/.test(operation)) return false;
  const methodName = operation.split('.').pop().toLowerCase();
  return JD_WRITE_RPC_MARKERS.some((marker) => methodName.includes(marker));
}

function isAuthenticationPreflightTarget(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  return Boolean(parsed && JD_AUTH_API_ROUTES.some(
    (route) => route.hostname === parsed.hostname && route.pathname === parsed.pathname
  ));
}

function isTrustedAuthenticationInitiator(rawUrl, currentMainFrameUrl) {
  try {
    const initiator = new URL(rawUrl);
    const currentFrame = parseAllowedHttpsUrl(currentMainFrameUrl);
    const validPort = initiator.port === '' || initiator.port === '443';
    const hasNoEmbeddedCredentials = initiator.username === '' && initiator.password === '';
    if (
      !currentFrame ||
      initiator.protocol !== 'https:' ||
      !validPort ||
      !hasNoEmbeddedCredentials
    ) {
      return false;
    }
    return initiator.origin === currentFrame.origin && (
      initiator.hostname === 'shop.jd.com' ||
      initiator.hostname === 'passport.shop.jd.com' ||
      initiator.hostname === 'passport.jd.com'
    );
  } catch (_error) {
    return false;
  }
}

function isMerchantAuthenticationBootstrapRoute(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  return Boolean(parsed && parsed.hostname === 'shop.jd.com' && (
    parsed.pathname === '/jdm/home' || parsed.pathname === '/jdm/home/'
  ));
}

function isAuthenticationContextRoute(rawUrl) {
  return isExactAuthenticationRoute(rawUrl) || isMerchantAuthenticationBootstrapRoute(rawUrl);
}

function isAuditedMainFrameRoute(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  return Boolean(parsed && JD_TOP_LEVEL_HOSTS.has(parsed.hostname));
}

function isAuthenticationPage(rawUrl) {
  const parsed = parseAllowedHttpsUrl(rawUrl);
  return Boolean(parsed && JD_AUTHENTICATION_PAGE_HOSTS.has(parsed.hostname));
}

function classifyRequest({
  url,
  method,
  resourceType,
  currentMainFrameUrl,
  isActive,
  isMainFrameSource,
  initiator
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
  // Chromium sends a CORS OPTIONS request before the current 京麦 login
  // exchange. That preflight has no business payload and may not carry a frame
  // object in Electron, so authorize it only when its target, visible page and
  // initiator origin all exactly match the reviewed authentication flow.
  if (
    normalizedMethod === 'OPTIONS' &&
    isAuthenticationContextRoute(currentMainFrameUrl) &&
    isTrustedAuthenticationInitiator(initiator, currentMainFrameUrl) &&
    isAuthenticationPreflightTarget(target.href)
  ) {
    return Object.freeze({ allow: true, code: 'HUMAN_AUTHENTICATION_PREFLIGHT' });
  }

  // Preflight never carries the business payload. Allow it only while the
  // exact reviewed JD shell/login route is visible; the actual request is
  // classified independently below and write operations still fail closed.
  if (
    normalizedMethod === 'OPTIONS' &&
    isAuthenticationContextRoute(currentMainFrameUrl)
  ) {
    return Object.freeze({ allow: true, code: 'READ_ONLY_PREFLIGHT' });
  }

  // This is a narrowly scoped human-login exception, not a business-write
  // exception. It is available only to the active view while its visible main
  // frame is an exact audited JD login route. Query strings, headers, bodies,
  // cookies and credentials are never inspected or copied by the workbench.
  if (
    AUTHENTICATION_METHODS.has(normalizedMethod) &&
    isAuthenticationContextRoute(currentMainFrameUrl) &&
    isAuthenticationApiTarget(target.href) &&
    (
      isMainFrameSource === true ||
      isTrustedAuthenticationInitiator(initiator, currentMainFrameUrl) ||
      (
        normalizedMethod !== 'OPTIONS' &&
        isSffAuthenticationAccountTarget(target.href)
      )
    )
  ) {
    return Object.freeze({ allow: true, code: 'HUMAN_AUTHENTICATION' });
  }

  // JD's current merchant shell uses POST for many read operations. Classify
  // those RPCs by their final operation verb, while rejecting any operation
  // containing a reviewed write marker. This keeps the shell usable without
  // granting order, product, inventory, price or after-sales mutations.
  if (
    (normalizedMethod === 'GET' || normalizedMethod === 'HEAD' || normalizedMethod === 'POST') &&
    isAuthenticationContextRoute(currentMainFrameUrl) &&
    isSffReadOnlyRpcTarget(target.href)
  ) {
    return Object.freeze({ allow: true, code: 'READ_ONLY_RPC' });
  }

  if (READ_ONLY_METHODS.has(normalizedMethod)) {
    if (resourceType === 'mainFrame' && isAuditedMainFrameRoute(target.href)) {
      return Object.freeze({ allow: true, code: 'AUDITED_MAIN_FRAME' });
    }
    if (isSffWriteRpcTarget(target.href)) {
      return Object.freeze({ allow: false, code: 'READ_ONLY_WRITE_BLOCKED' });
    }
    if (STATIC_RESOURCE_TYPES.has(resourceType) && JD_STATIC_HOSTS.has(target.hostname)) {
      return Object.freeze({ allow: true, code: 'STATIC_RESOURCE' });
    }
    if (resourceType !== 'mainFrame') {
      return Object.freeze({ allow: true, code: 'READ_ONLY_HTTPS' });
    }
    return Object.freeze({ allow: false, code: 'ENDPOINT_NOT_AUDITED' });
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

function shouldRevokeForBlockedRequest(code, resourceType) {
  return code !== 'INACTIVE_PARTITION' && (
    resourceType === 'mainFrame' || code === 'READ_ONLY_WRITE_BLOCKED'
  );
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
  JD_TOP_LEVEL_HOSTS,
  JD_AUTH_ROUTES,
  JD_MAIN_FRAME_ROUTES,
  READ_ONLY_METHODS,
  STATIC_RESOURCE_TYPES,
  classifyRequest,
  detectHumanActionFromUrl,
  hostnameForStatus,
  isAuditedMainFrameRoute,
  isAuthenticationApiTarget,
  isAuthenticationPreflightTarget,
  isAuthenticationContextRoute,
  isAuthenticationPage,
  isExactAuthenticationRoute,
  isMerchantAuthenticationBootstrapRoute,
  isSffAuthenticationAccountTarget,
  isSffReadOnlyRpcTarget,
  isSffWriteRpcTarget,
  isTrustedAuthenticationInitiator,
  parseAllowedHttpsUrl,
  shouldRevokeForBlockedRequest
});
