from pathlib import Path


PAGE = Path("frontend/ai-assets.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_product_asset_page_uses_server_shops_and_real_asset_endpoints():
    html = read_page()

    assert "api('/api/ai-products/shops'" in html
    assert "api('/api/ai-products/assets'" in html
    assert "method:'POST'" in html
    assert "credentials:'include'" in html
    assert "data-required-menu=\"menu.ai_assets\"" in html


def test_product_asset_form_requires_name_and_server_returned_shop():
    html = read_page()

    assert 'id="productName"' in html
    assert 'name="product_name"' in html
    assert "required" in html
    assert 'id="shopSelect"' in html
    assert "renderShops" in html
    assert "if(!productName.value.trim())" in html


def test_product_asset_picker_documents_and_enforces_file_contract():
    html = read_page()

    assert 'accept="image/jpeg,image/png,image/webp"' in html
    assert 'multiple' in html
    assert "JPEG、PNG、WEBP" in html
    assert "最多 9 张" in html
    assert "单张不超过 10 MiB" in html
    assert "MAX_FILES=9" in html
    assert "MAX_FILE_SIZE=10*1024*1024" in html


def test_product_asset_page_supports_drop_and_local_previews():
    html = read_page()

    assert 'id="dropZone"' in html
    assert "handleDroppedFiles" in html
    assert "URL.createObjectURL" in html
    assert "URL.revokeObjectURL" in html
    assert 'id="previewGrid"' in html


def test_product_asset_page_has_upload_lifecycle_and_duplicate_submit_guard():
    html = read_page()

    for text in ["正在上传", "上传成功", "上传失败"]:
        assert text in html
    assert "let uploadInFlight=false" in html
    assert "if(uploadInFlight)return" in html
    assert "uploadInFlight=true" in html
    assert "uploadInFlight=false" in html


def test_product_asset_page_restores_persisted_assets_on_load_and_after_upload():
    html = read_page()

    assert "async function loadAssets()" in html
    assert "renderAssets" in html
    assert "await loadAssets()" in html
    assert 'id="assetList"' in html


def test_product_asset_page_does_not_add_client_roles_or_mock_results():
    html = read_page()

    for forbidden in [
        "roleMap",
        "ROLE_MAP",
        "mockSuccess",
        "mockAssets",
        "生成卖点",
        "AI文案",
    ]:
        assert forbidden not in html


def test_product_asset_page_is_served(client):
    response = client.get("/ai-assets.html")

    assert response.status_code == 200
    assert "上传商品素材" in response.text
