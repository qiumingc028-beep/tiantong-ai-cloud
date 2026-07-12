# V1.0.1 Dependency Platform Matrix

## 结论

- amd64 wheelhouse：36 个 wheel
- arm64 wheelhouse：36 个 wheel
- 包名集合差异：0
- 包版本差异：0
- wheel 文件名与 SHA-256：按平台不同，正常差异

## 平台说明

### 平台无关 wheel

以下依赖在 amd64 / arm64 两侧均为 `py3-none-any`：

- alembic
- annotated-doc
- annotated-types
- anyio
- async-timeout
- certifi
- click
- et_xmlfile
- exceptiongroup
- fastapi
- h11
- httpcore
- httpx
- idna
- iniconfig
- Mako
- openpyxl
- packaging
- pluggy
- pydantic
- Pygments
- PyJWT
- pytest
- python-dotenv
- python-multipart
- redis
- starlette
- typing-inspection
- typing_extensions
- uvicorn

### 平台相关 wheel

- greenlet
- MarkupSafe
- psycopg2-binary
- pydantic_core
- SQLAlchemy
- tomli

### 说明

以上平台相关依赖在 amd64 与 arm64 上分别使用各自兼容的 manylinux wheel。
完整 hash 与来源快照见：

- `artifacts/wheelhouse/linux-amd64-cp312/artifact-manifest.json`
- `artifacts/wheelhouse/linux-arm64-cp312/artifact-manifest.json`
