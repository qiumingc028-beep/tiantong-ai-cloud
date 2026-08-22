from pathlib import Path


PAGE = Path("frontend/task-center.html")


def test_task_rows_render_static_owner_scoped_detail_action():
    html = PAGE.read_text(encoding="utf-8")

    assert 'data-rbac-action="task-center-009"' in html
    assert 'data-task-id="${esc(t.id)}"' in html
    assert 'loadDetail(Number(this.dataset.taskId))' in html
    assert 'registerDynamicAction("task-center-009"' not in html


def test_task_detail_uses_existing_owner_scoped_endpoints_and_fail_closed_copy():
    html = PAGE.read_text(encoding="utf-8")

    for contract in [
        "/api/task-center/tasks/${id}",
        "/api/task-center/tasks/${id}/audit-logs",
        "加载任务详情失败",
        "当前账号无权使用该功能。",
        "分析记录或任务不存在。",
        "任务类型：",
        "创建时间：",
        "更新时间：",
        "t.source||'暂无数据'",
    ]:
        assert contract in html

    assert "127.0.0.1:59200" not in html
