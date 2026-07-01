from backend.models import KnowledgeArticle, KnowledgeFile


def test_knowledge_center_upload_ai_generate_publish_and_search(client, owner_headers, test_db):
    uploaded = client.post(
        "/api/knowledge/files",
        headers=owner_headers,
        files={"file": ("store-sop.txt", b"SOP: check ad ROI and refund cases every morning.", "text/plain")},
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()["id"]

    summarized = client.post(f"/api/knowledge/files/{file_id}/summarize", headers=owner_headers)
    assert summarized.status_code == 200
    assert summarized.json()["file"]["summary"]

    classified = client.post(f"/api/knowledge/files/{file_id}/classify", headers=owner_headers)
    assert classified.status_code == 200
    assert classified.json()["file"]["category"]

    generated = client.post(f"/api/knowledge/files/{file_id}/article", headers=owner_headers)
    assert generated.status_code == 200
    article_id = generated.json()["article"]["id"]
    assert generated.json()["sop"]["title"]
    assert generated.json()["prompt"]["prompt_text"]
    assert generated.json()["bug_case"]["solution"]
    assert generated.json()["course"]["outline"]

    published = client.post(f"/api/knowledge/articles/{article_id}/publish", headers=owner_headers)
    assert published.status_code == 200
    assert published.json()["article"]["status"] == "published"

    search = client.get("/api/knowledge/search?q=store-sop&status=已发布", headers=owner_headers)
    assert search.status_code == 200
    assert search.json()["articles"][0]["id"] == article_id

    for path in ("/api/knowledge/sops", "/api/knowledge/prompts", "/api/knowledge/bug-cases", "/api/knowledge/courses"):
        response = client.get(path, headers=owner_headers)
        assert response.status_code == 200
        assert response.json()

    db = test_db()
    try:
        assert db.query(KnowledgeFile).count() == 1
        assert db.query(KnowledgeArticle).filter(KnowledgeArticle.status == "published").count() == 1
    finally:
        db.close()


def test_viewer_cannot_access_knowledge_center(client, viewer_headers):
    response = client.get("/api/knowledge/files", headers=viewer_headers)
    assert response.status_code == 403
