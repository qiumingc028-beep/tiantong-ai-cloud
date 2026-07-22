import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ENTERPRISE_BRAIN = FRONTEND / "enterprise-brain-console.html"
JAVASCRIPT_URL = re.compile(
    r"j[\t\r\n]*a[\t\r\n]*v[\t\r\n]*a[\t\r\n]*s[\t\r\n]*"
    r"c[\t\r\n]*r[\t\r\n]*i[\t\r\n]*p[\t\r\n]*t[\t\r\n]*\s*:",
    re.IGNORECASE,
)
DISABLED_CLICK_BINDING = re.compile(
    r"(?:centerGrid[\s\S]{0,120}?addEventListener\s*\(\s*['\"]click"
    r"|addEventListener\s*\(\s*['\"]click[\s\S]{0,240}?"
    r"(?:closest|matches|querySelector(?:All)?)\s*\([^)]*(?:disabled|aria-disabled))",
    re.IGNORECASE,
)


def find_javascript_urls(source: str) -> list[str]:
    return [match.group(0) for match in JAVASCRIPT_URL.finditer(source)]


def find_disabled_click_bindings(source: str) -> list[str]:
    return [match.group(0) for match in DISABLED_CLICK_BINDING.finditer(source)]


def extract_function(source: str, name: str, next_name: str) -> str:
    match = re.search(
        rf"function\s+{name}\b[\s\S]*?(?=\nfunction\s+{next_name}\b)", source
    )
    assert match, f"missing function: {name}"
    return match.group(0)


def run_render_cases(cases: list[dict]) -> list[dict]:
    source = ENTERPRISE_BRAIN.read_text()
    functions = "\n".join(
        (
            extract_function(source, "esc", "obj"),
            extract_function(source, "fmt", "tick"),
            extract_function(source, "normalizeCenterUrl", "renderCenters"),
            extract_function(source, "renderCenters", "renderRecentActivities"),
        )
    )
    harness = f"""
const vm=require('node:vm');
const functions={json.dumps(functions)};
const cases={json.dumps(cases)};
const results=cases.map(item=>{{
  const context={{
    URL,
    location:{{origin:item.origin,href:item.origin+'/enterprise-brain-console.html'}},
    centerGrid:{{innerHTML:''}},
    statusText:{{connected:'已接入'}},
  }};
  vm.createContext(context);
  vm.runInContext(functions,context);
  context.renderCenters([{{
    url:item.value,name:'入口',description:'说明',count:0,last_updated:null,
    status:'connected',risk_level:'low',primary_action:'查看'
  }}]);
  return {{
    label:item.label,
    normalized:context.normalizeCenterUrl(item.value),
    html:context.centerGrid.innerHTML,
  }};
}});
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(
        ["node", "-e", harness], check=True, text=True, capture_output=True
    )
    return json.loads(completed.stdout)


def test_policy_detects_static_and_template_javascript_urls():
    static = '<a href="JaVaScRiPt : alert(1)">unsafe</a>'
    template = "`${disabled ? 'javascript:\\nvoid(0)' : url}`"
    embedded_whitespace = '<a href="ja\tva\nscript :alert(1)">unsafe</a>'

    assert find_javascript_urls(static)
    assert find_javascript_urls(template)
    assert find_javascript_urls(embedded_whitespace)


def test_policy_detects_direct_and_delegated_disabled_click_bindings():
    direct = "centerGrid.addEventListener('click', handler)"
    delegated = (
        "document.addEventListener('click', event => "
        "event.target.closest('.btn.disabled'))"
    )

    assert find_disabled_click_bindings(direct)
    assert find_disabled_click_bindings(delegated)


def test_all_frontend_html_is_free_of_javascript_urls():
    violations = {
        path.relative_to(ROOT).as_posix(): find_javascript_urls(path.read_text())
        for path in FRONTEND.rglob("*.html")
        if find_javascript_urls(path.read_text())
    }

    assert violations == {}


def test_enterprise_brain_disabled_action_is_noninteractive_and_accessible():
    source = ENTERPRISE_BRAIN.read_text()
    branches = re.search(
        r"const\s+action\s*=\s*disabled\s*\?\s*`(?P<disabled>.*?)`\s*"
        r":\s*`(?P<enabled>.*?)`",
        source,
        re.DOTALL,
    )

    assert branches, "renderCenters() must emit explicit disabled and enabled actions"
    disabled = branches.group("disabled")
    enabled = branches.group("enabled")

    assert "<span" in disabled
    assert 'aria-disabled="true"' in disabled
    assert not re.search(r"\bhref\s*=", disabled, re.IGNORECASE)
    assert not re.search(r"\bon[a-z]+\s*=", disabled, re.IGNORECASE)
    assert find_disabled_click_bindings(source) == []
    assert "<a" in enabled
    assert 'href="${esc(safeUrl)}"' in enabled


def test_dynamic_api_urls_are_normalized_before_real_rendering():
    cases = [
        {"label": "root-relative", "origin": "https://app.example", "value": "/safe", "expected": "https://app.example/safe"},
        {"label": "root", "origin": "https://app.example", "value": "/", "expected": "https://app.example/"},
        {"label": "relative", "origin": "https://app.example", "value": "reports/view", "expected": "https://app.example/reports/view"},
        {"label": "https-absolute", "origin": "https://app.example", "value": "https://app.example/safe", "expected": "https://app.example/safe"},
        {"label": "http-absolute", "origin": "http://app.example", "value": "http://app.example/safe", "expected": "http://app.example/safe"},
        {"label": "javascript", "origin": "https://app.example", "value": "javascript:alert(1)"},
        {"label": "javascript-case", "origin": "https://app.example", "value": "JaVaScRiPt:alert(1)"},
        {"label": "javascript-case-space", "origin": "https://app.example", "value": " JaVaScRiPt:alert(1)"},
        {"label": "javascript-control", "origin": "https://app.example", "value": "java\tscript:alert(1)"},
        {"label": "data", "origin": "https://app.example", "value": "data:text/html,unsafe"},
        {"label": "vbscript", "origin": "https://app.example", "value": "vbscript:msgbox(1)"},
        {"label": "file", "origin": "https://app.example", "value": "file:///tmp/unsafe"},
        {"label": "blob", "origin": "https://app.example", "value": "blob:https://app.example/id"},
        {"label": "unknown", "origin": "https://app.example", "value": "mailto:test@example.com"},
        {"label": "cross-origin", "origin": "https://app.example", "value": "https://evil.example/path"},
        {"label": "cross-origin-http", "origin": "https://app.example", "value": "http://evil.example/path"},
        {"label": "protocol-relative-cross-origin", "origin": "https://app.example", "value": "//evil.example/path"},
        {"label": "protocol-relative-same-origin", "origin": "https://app.example", "value": "//app.example/path"},
        {"label": "backslash-relative", "origin": "https://app.example", "value": "\\\\app.example/path"},
        {"label": "mixed-backslash-relative", "origin": "https://app.example", "value": "\\/app.example/path"},
        {"label": "root-backslash-relative", "origin": "https://app.example", "value": "/\\app.example/path"},
        {"label": "credentials", "origin": "https://app.example", "value": "https://user:pass@app.example/path"},
        {"label": "ascii-control", "origin": "https://app.example", "value": "/safe\npath"},
        {"label": "unicode-confusable", "origin": "https://app.example", "value": "java\u0455cript:alert(1)"},
        {"label": "html-entity", "origin": "https://app.example", "value": "java&#x73;cript:alert(1)"},
        {"label": "html-decimal-no-semicolon", "origin": "https://app.example", "value": "java&#115cript:alert(1)"},
        {"label": "html-hex-no-semicolon", "origin": "https://app.example", "value": "java&#x73cript:alert(1)"},
        {"label": "percent-encoded", "origin": "https://app.example", "value": "java%73cript:alert(1)"},
        {"label": "empty", "origin": "https://app.example", "value": ""},
        {"label": "hash", "origin": "https://app.example", "value": "#"},
        {"label": "null", "origin": "https://app.example", "value": None},
        {"label": "non-string", "origin": "https://app.example", "value": 7},
        {"label": "malformed", "origin": "https://app.example", "value": "http://["},
    ]

    for case, result in zip(cases, run_render_cases(cases), strict=True):
        if expected := case.get("expected"):
            assert result["normalized"] == expected, case["label"]
            assert '<a class="btn"' in result["html"], case["label"]
            assert f'href="{expected}"' in result["html"], case["label"]
        else:
            assert result["normalized"] is None, case["label"]
            assert '<span class="btn disabled" aria-disabled="true">' in result["html"], case["label"]
            assert "href=" not in result["html"], case["label"]
