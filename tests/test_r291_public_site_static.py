from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_site_is_separate_and_truthful():
    html = (ROOT / "public-site" / "index.html").read_text()

    assert "天统AI｜多店经营智能中台" in html
    assert "https://internal.tiantongai.com" in html
    assert "内部测试中" in html
    assert "不提供公开注册" in html
    assert "Mock" not in html
    assert "假数据" not in html
    assert "/api/" not in html


def test_public_nginx_never_proxies_internal_api():
    config = (ROOT / "nginx" / "public.conf").read_text()

    assert "server_name tiantongai.com www.tiantongai.com;" in config
    assert "server_name cloud.tiantongai.com www.cloud.tiantongai.com;" in config
    assert "proxy_pass" not in config
    assert "location = /health" in config
    assert "public-fullchain.pem" in config
    assert "legacy-fullchain.pem" in config


def test_public_compose_is_independent():
    compose = (ROOT / "docker-compose.public.yml").read_text()

    assert "name: tiantong-ai-public" in compose
    assert "Dockerfile.public" in compose
    assert "container_name: tiantong-ai-public-nginx" in compose
    assert "backend:" not in compose
    assert "postgres" not in compose
    assert "redis" not in compose
