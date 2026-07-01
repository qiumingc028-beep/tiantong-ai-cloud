from backend.models import KnowledgeArticle
import pytest


def upload_sample(client, owner_headers):
    return client.post(
        "/api/tiancang/files/upload",
        headers=owner_headers,
        files={"file": ("sample.txt", b"tiancang knowledge content", "text/plain")},
    )


@pytest.fixture(autouse=True)
def test_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.tiancang.UPLOAD_DIR", tmp_path)


def test_tiancang_upload_returns_success(client, owner_headers):
    response = upload_sample(client, owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["file"]["original_name"] == "sample.txt"


def test_tiancang_file_list_returns_data(client, owner_headers):
    upload_sample(client, owner_headers)

    response = client.get("/api/tiancang/files", headers=owner_headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_tiancang_summarize_uses_mock_without_api_key(client, owner_headers, monkeypatch):
    monkeypatch.setattr("backend.routers.tiancang.get_settings", lambda: StubSettings("openai"))
    file_id = upload_sample(client, owner_headers).json()["file"]["id"]

    response = client.post(f"/api/tiancang/files/{file_id}/summarize", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "mock"
    assert "知识资产" in data["summary"]


def test_tiancang_classify_uses_mock_without_api_key(client, owner_headers, monkeypatch):
    monkeypatch.setattr("backend.routers.tiancang.get_settings", lambda: StubSettings("deepseek"))
    file_id = upload_sample(client, owner_headers).json()["file"]["id"]

    response = client.post(f"/api/tiancang/files/{file_id}/classify", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "mock"
    assert data["category"] == "AI知识库"
    assert "天藏" in data["tags"]


def test_tiancang_generate_article_creates_article(client, owner_headers, test_db):
    file_id = upload_sample(client, owner_headers).json()["file"]["id"]

    response = client.post(f"/api/tiancang/files/{file_id}/generate-article", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["article"]["title"] == "天藏知识资产中心建设方案"
    session = test_db()
    try:
        assert session.query(KnowledgeArticle).count() == 1
    finally:
        session.close()


def test_tiancang_publish_article_marks_published(client, owner_headers):
    file_id = upload_sample(client, owner_headers).json()["file"]["id"]
    article_id = client.post(f"/api/tiancang/files/{file_id}/generate-article", headers=owner_headers).json()["article"]["id"]

    response = client.post(f"/api/tiancang/articles/{article_id}/publish", headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["article"]["status"] == "published"


class StubSettings:
    def __init__(self, provider):
        self.AI_PROVIDER = provider
        self.OPENAI_API_KEY = ""
        self.DEEPSEEK_API_KEY = ""
