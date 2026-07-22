import re
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
    assert 'href="${esc(center.url)}"' in enabled
