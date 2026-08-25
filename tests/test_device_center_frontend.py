from pathlib import Path


CENTER_PAGE = Path("frontend/device-center.html")
OBSERVER_PAGE = Path("frontend/desktop-observer.html")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_device_center_frontend_pages_exist():
    assert CENTER_PAGE.exists()
    assert OBSERVER_PAGE.exists()


def test_device_center_frontend_pages_are_served(client):
    center = client.get("/device-center.html")
    observer = client.get("/desktop-observer.html")

    assert center.status_code == 200
    assert observer.status_code == 200
    assert "测试设备中心" in center.text
    assert "桌面观察" in observer.text


def test_device_center_frontend_contains_required_text():
    html = read(CENTER_PAGE) + read(OBSERVER_PAGE)

    for text in [
        "测试设备中心已加载，当前为只读管理视图。",
        "桌面观察",
        "只读观察、窗口枚举、指定窗口截图、状态摘要和下一步建议。",
        "查看设备",
        "生成注册令牌",
        "批准设备",
        "禁用设备",
        "撤销设备",
        "测试设备",
        "AI 员工",
        "当前应用",
        "当前窗口",
        "下一步建议",
        "立即断开",
        "/api/v2/devices",
        "/api/v2/device-observations",
    ]:
        assert text in html


def test_device_center_frontend_has_no_dangerous_entries():
    html = read(CENTER_PAGE) + read(OBSERVER_PAGE)
    forbidden = [
        "自动点击",
        "自动输入",
        "Terminal",
        "Shell",
        "OpenClaw",
        "Password",
        "输入密码",
        "执行命令",
    ]
    for text in forbidden:
        assert text not in html
