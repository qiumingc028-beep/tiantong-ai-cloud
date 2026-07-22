import html
import json
import re
import subprocess
import tempfile
import unicodedata
from html.entities import html5
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ENTERPRISE_BRAIN = FRONTEND / "enterprise-brain-console.html"
MAX_DECODE_PASSES = 8
DANGEROUS_SCHEMES = ("javascript", "data", "vbscript", "file", "blob")
SCHEME_GAP = r"[\x00-\x20]*"
DANGEROUS_URL = re.compile(
    rf"(?:^|['\"`=]){SCHEME_GAP}"
    rf"(?:{'|'.join(SCHEME_GAP.join(scheme) for scheme in DANGEROUS_SCHEMES)})"
    rf"{SCHEME_GAP}:",
    re.IGNORECASE,
)
URL_ATTRIBUTES = {"href", "src", "action", "formaction"}
DISABLED_CLICK_BINDING = re.compile(
    r"(?:centerGrid[\s\S]{0,120}?addEventListener\s*\(\s*['\"]click"
    r"|addEventListener\s*\(\s*['\"]click[\s\S]{0,240}?"
    r"(?:closest|matches|querySelector(?:All)?)\s*\([^)]*(?:disabled|aria-disabled))",
    re.IGNORECASE,
)
ENCODED_DANGEROUS_URLS = {
    "decimal": "java&#115;cript:alert(1)",
    "hex": "java&#x73;cript:alert(1)",
    "entity-no-semicolon": "java&#115cript:alert(1)",
    "hex-entity-no-semicolon": "java&#x73cript:alert(1)",
    "percent": "java%73cript:alert(1)",
    "double-percent": "java%2573cript:alert(1)",
    "entity-percent": "java&#37;73cript:alert(1)",
    "tab": "java\tscript:alert(1)",
    "lf": "java\nscript:alert(1)",
    "cr": "java\rscript:alert(1)",
    "form-feed": "java\fscript:alert(1)",
    "vertical-tab": "java\vscript:alert(1)",
    "nul": "java\0script:alert(1)",
    "case-whitespace": "  JaVaScRiPt:alert(1)  ",
    "unicode-normalized": "ｊａｖａｓｃｒｉｐｔ:alert(1)",
}
DECODE_LIMIT_URL = "javascript:alert(1)"
for _ in range(MAX_DECODE_PASSES + 1):
    DECODE_LIMIT_URL = quote(DECODE_LIMIT_URL, safe="")
DANGEROUS_HTML_SAMPLES = {
    **{
        f"encoded-{label}": f'<a href="{value}">sample</a>'
        for label, value in ENCODED_DANGEROUS_URLS.items()
    },
    "data": '<a href="data:text/html,unsafe">sample</a>',
    "vbscript": '<a href="vbscript:msgbox(1)">sample</a>',
    "file": '<a href="file:///tmp/unsafe">sample</a>',
    "blob": '<a href="blob:https://app.example/id">sample</a>',
    "unknown-quoted": '<a href="custom-exec:payload">sample</a>',
    "unknown-unquoted": "<a href=custom-exec:payload>sample</a>",
    "unknown-formaction": "<button formaction=custom-exec:payload>sample</button>",
    "unknown-template": "<script>const link = `<a href=custom-exec:payload>sample</a>`;</script>",
    "quoted-angle": '<a title=">" href="custom-exec:payload>detail">sample</a>',
    "malformed-percent": '<a href="%zz">sample</a>',
    "malformed-entity": '<a href="&#xzz;">sample</a>',
    "unknown-entity": '<a href="&bogus;">sample</a>',
    "nested-malformed-entity": '<a href="&amp;#xzz;">sample</a>',
    "decode-limit": f'<a href="{DECODE_LIMIT_URL}">sample</a>',
}


class UrlAttributeParser(HTMLParser):
    def __init__(self, *, parse_embedded: bool = True):
        super().__init__(convert_charrefs=False)
        self.parse_embedded = parse_embedded
        self.values = []

    def handle_starttag(self, _tag, attrs):
        self.values.extend(
            value
            for name, value in attrs
            if name.casefold() in URL_ATTRIBUTES and value is not None
        )

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        if self.parse_embedded and "<" in data:
            parser = UrlAttributeParser(parse_embedded=False)
            parser.feed(data)
            self.values.extend(parser.values)


def extract_url_candidates(source: str) -> list[str]:
    parser = UrlAttributeParser()
    parser.feed(source)
    return parser.values


def validate_url_entities(value: str) -> None:
    for match in re.finditer(r"&#(?:[xX])?", value):
        suffix = value[match.end() :]
        digits = r"[0-9a-fA-F]+" if match.group(0).lower().endswith("x") else r"\d+"
        if not re.match(digits, suffix):
            raise ValueError("malformed numeric entity")
    for match in re.finditer(r"&([a-zA-Z][a-zA-Z0-9]+);", value):
        if f"{match.group(1)};" not in html5:
            raise ValueError("unknown named entity")


def normalize_policy_text(
    value: str, *, strict_percent: bool = False, strict_entities: bool = False
) -> str:
    current = unicodedata.normalize("NFKC", value)
    for _ in range(MAX_DECODE_PASSES):
        if strict_entities:
            validate_url_entities(current)
        if strict_percent and re.search(r"%(?![0-9a-f]{2})", current, re.IGNORECASE):
            raise ValueError("malformed percent encoding")
        try:
            decoded = unquote(html.unescape(current), errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("invalid encoded URL") from exc
        decoded = unicodedata.normalize("NFKC", decoded)
        if decoded == current:
            return decoded
        current = decoded
    raise ValueError("decode limit exceeded")


def find_dangerous_urls(source: str) -> list[str]:
    url_candidates = extract_url_candidates(source)
    if "<" not in source:
        url_candidates.append(source)
    try:
        normalized = normalize_policy_text(source)
    except ValueError as exc:
        return [str(exc)]
    violations = [match.group(0) for match in DANGEROUS_URL.finditer(normalized)]
    for candidate in url_candidates:
        try:
            value = normalize_policy_text(
                candidate, strict_percent=True, strict_entities=True
            ).strip()
        except ValueError as exc:
            violations.append(str(exc))
            continue
        violations.extend(match.group(0) for match in DANGEROUS_URL.finditer(value))
        if ":" not in value:
            continue
        prefix = value.split(":", 1)[0]
        scheme = re.sub(r"[\x00-\x20]", "", prefix).casefold()
        if (
            not re.search(r"[/#?]", prefix)
            and re.match(r"[a-z]", scheme)
            and scheme not in {"http", "https"}
        ):
            violations.append(value)
    return violations


def scan_html_files(paths) -> dict[str, list[str]]:
    violations = {}
    for path in paths:
        source = path.read_text()
        if matches := find_dangerous_urls(source):
            violations[path.relative_to(ROOT).as_posix()] = matches
    return violations


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

    assert find_dangerous_urls(static)
    assert find_dangerous_urls(template)
    assert find_dangerous_urls(embedded_whitespace)


def test_policy_detects_encoded_and_control_character_variants():
    assert all(find_dangerous_urls(value) for value in ENCODED_DANGEROUS_URLS.values())


def test_policy_detects_executable_schemes_and_fails_closed():
    assert all(find_dangerous_urls(value) for value in DANGEROUS_HTML_SAMPLES.values())


def test_policy_does_not_flag_safe_urls():
    safe = [
        '<a href="reports/view">relative</a>',
        '<a href="/reports/view">root relative</a>',
        '<a href="https://app.example/reports">https</a>',
        '<a href="http://app.example/reports">http</a>',
        '<a href="/reports?x=1&y=2">query</a>',
        '<a href="/reports/view:detail">path colon</a>',
        '<a href="/reports?next=custom:payload">query colon</a>',
        '<a href="reports/view?time=12:30">relative query colon</a>',
    ]

    assert [value for value in safe if find_dangerous_urls(value)] == []


def test_policy_scans_synthetic_html_once_per_file(monkeypatch):
    safe = (
        "reports/view",
        "/reports/view",
        "https://app.example/reports",
        "/reports/view:detail",
        "/reports?next=custom:payload",
        "reports/view?time=12:30",
    )
    original_read_text = Path.read_text
    reads = {}

    def counted_read_text(path, *args, **kwargs):
        reads[path] = reads.get(path, 0) + 1
        return original_read_text(path, *args, **kwargs)

    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        sample_dir = Path(directory)
        dangerous_paths = []
        for label, source in DANGEROUS_HTML_SAMPLES.items():
            path = sample_dir / f"dangerous-{label}.html"
            path.write_text(source)
            dangerous_paths.append(path)
        safe_paths = []
        for index, value in enumerate(safe):
            path = sample_dir / f"safe-{index}.html"
            path.write_text(f'<a href="{value}">sample</a>')
            safe_paths.append(path)

        monkeypatch.setattr(Path, "read_text", counted_read_text)
        violations = scan_html_files([*dangerous_paths, *safe_paths])

        assert len(violations) == len(DANGEROUS_HTML_SAMPLES)
        assert all(path.relative_to(ROOT).as_posix() in violations for path in dangerous_paths)
        assert all(path.relative_to(ROOT).as_posix() not in violations for path in safe_paths)
        assert all(reads[path] == 1 for path in [*dangerous_paths, *safe_paths])


def test_policy_fails_closed_beyond_decode_limit():
    assert find_dangerous_urls(f'<a href="{DECODE_LIMIT_URL}">unsafe</a>')


def test_policy_detects_direct_and_delegated_disabled_click_bindings():
    direct = "centerGrid.addEventListener('click', handler)"
    delegated = (
        "document.addEventListener('click', event => "
        "event.target.closest('.btn.disabled'))"
    )

    assert find_disabled_click_bindings(direct)
    assert find_disabled_click_bindings(delegated)


def test_all_frontend_html_is_free_of_javascript_urls():
    assert scan_html_files(FRONTEND.rglob("*.html")) == {}


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
