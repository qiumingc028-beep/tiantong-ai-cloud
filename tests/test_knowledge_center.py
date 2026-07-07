from backend.models import KnowledgeArticle, KnowledgeFile
from backend.knowledge_center import clear_knowledge, learn_from_execution, search_knowledge
from backend.knowledge_center.knowledge_storage import list_knowledge
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


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


def learning_report_fixture():
    return {
        "analysis": {
            "goal": "分析京东60店销量下降",
            "status": "failed",
            "result_summary": "共 2 个步骤，成功 1 个，失败 1 个。",
            "learning_loop": ["task", "execution", "evaluation", "learning", "optimization", "next_run"],
            "success_reasons": ["tiancai_data 完成 fetch_sales_data"],
            "failure_reasons": ["tiance_strategy: 缺少广告数据"],
        },
        "employee_scores": [
            {"employee_code": "tiancai_data", "overall_score": 100},
            {"employee_code": "tiance_strategy", "overall_score": 0},
        ],
        "prompt_optimization": {
            "optimization_suggestions": [
                {
                    "suggestion_code": "add_safety_gate",
                    "title": "补充 TianShen 审批门说明",
                    "reason": "风险步骤必须先输出审批建议，不能直接执行。",
                    "requires_approval": True,
                    "can_auto_apply": False,
                }
            ],
            "can_auto_update_prompt": False,
            "can_modify_production_prompt": False,
        },
    }


def test_tiancang_learns_from_tianwu_report_and_generates_long_term_memory():
    clear_knowledge()
    result = learn_from_execution(learning_report_fixture())

    assert result["center"] == "TianCang Knowledge Center"
    assert result["mode"] == "long_term_memory_append_only"
    assert result["stored_knowledge"]
    assert result["generated_sop"]
    assert result["experience_rules"]
    assert result["approval_gate"]["center"] == "TianShen"
    assert result["safety"]["append_only"] is True
    assert result["safety"]["can_auto_modify_production_rule"] is False
    assert result["safety"]["can_auto_modify_prompt"] is False
    assert all(row["requires_tian_shen_approval"] is True for row in result["stored_knowledge"])


def test_tiancang_search_finds_similar_cases_and_prompt_versions():
    clear_knowledge()
    learn_from_execution(learning_report_fixture())

    search = search_knowledge("京东60店 销量下降", limit=5)
    prompt_search = search_knowledge("审批门", knowledge_type="prompt_version")

    assert search["external_vector_db_used"] is False
    assert search["matches"]
    assert prompt_search["matches"]
    assert prompt_search["matches"][0]["knowledge_type"] == "prompt_version"


def test_command_knowledge_learn_requires_login(client):
    response = client.post("/command/knowledge/learn", json={"learning_report": learning_report_fixture()})

    assert response.status_code == 401


def test_command_knowledge_learn_rejects_low_permission(client, viewer_headers):
    response = client.post(
        "/command/knowledge/learn",
        headers=viewer_headers,
        json={"learning_report": learning_report_fixture()},
    )

    assert response.status_code == 403


def test_command_knowledge_learn_appends_only_and_does_not_queue(client, owner_headers):
    clear_knowledge()
    response = client.post(
        "/command/knowledge/learn",
        headers=owner_headers,
        json={"learning_report": learning_report_fixture()},
    )

    assert response.status_code == 200
    body = response.json()["knowledge"]
    assert body["stored_knowledge"]
    assert body["safety"]["append_only"] is True
    assert body["safety"]["can_auto_modify_prompt"] is False

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0
    assert list_knowledge()


def test_command_knowledge_search_returns_history(client, owner_headers):
    clear_knowledge()
    client.post("/command/knowledge/learn", headers=owner_headers, json={"learning_report": learning_report_fixture()})

    response = client.get("/command/knowledge/search", headers=owner_headers, params={"q": "销量下降"})

    assert response.status_code == 200
    assert response.json()["search"]["matches"]


def test_command_knowledge_learn_can_build_from_command_id(client, owner_headers):
    clear_knowledge()
    created = client.post("/command/submit", headers=owner_headers, json={"command": "分析今天京东60店销量下降原因"})
    command_id = created.json()["command"]["command_id"]

    response = client.post("/command/knowledge/learn", headers=owner_headers, json={"command_id": command_id})

    assert response.status_code == 200
    assert response.json()["knowledge"]["stored_knowledge"]
