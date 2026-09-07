from ops.r297_ci_redact import redact
import xml.etree.ElementTree as ET


def test_ci_redactor_removes_credentials_from_uploaded_text(tmp_path):
    artifact = tmp_path / "results.xml"
    artifact.write_text(
        '<testsuite><failure message="authorization: Bearer bearer-value '
        'password=pass-value postgresql://user:db-value@db.example/test"/></testsuite>',
        encoding="utf-8",
    )

    redact(artifact)

    result = artifact.read_text(encoding="utf-8")
    assert "bearer-value" not in result
    assert "pass-value" not in result
    assert "db-value" not in result
    assert result.count("[REDACTED]") >= 3
    assert "authorization: Bearer [REDACTED]" in result
    ET.fromstring(result)


def test_ci_redactor_masks_json_values_escaped_inside_junit_xml(tmp_path):
    artifact = tmp_path / "results.xml"
    artifact.write_text(
        '<testsuite><failure message="{&quot;token&quot;: &quot;TOPSECRET&quot;, '
        '&quot;password&quot;: &quot;PASSSECRET&quot;, '
        '&quot;cookie&quot;: &quot;ABC&amp;TAILSECRET&quot;, '
        '&quot;access_token&quot;: &quot;ACCESSSECRET&quot;, '
        '&quot;Authorization&quot;: &quot;Bearer AUTHSECRET&quot;, '
        '&quot;api_key&quot;: &quot;APISECRET&quot;}">'
        "{'secret': 'REPRSECRET', 'refresh_token': 'REFRESHSECRET'}"
        "</failure></testsuite>",
        encoding="utf-8",
    )

    redact(artifact)

    result = artifact.read_text(encoding="utf-8")
    assert "TOPSECRET" not in result
    assert "PASSSECRET" not in result
    assert "TAILSECRET" not in result
    assert "REPRSECRET" not in result
    assert "ACCESSSECRET" not in result
    assert "AUTHSECRET" not in result
    assert "APISECRET" not in result
    assert "REFRESHSECRET" not in result
    assert result.count("[REDACTED]") == 8
    ET.fromstring(result)


def test_ci_redactor_handles_mixed_escaped_and_truncated_values_without_breaking_xml(tmp_path):
    artifact = tmp_path / "results.xml"
    artifact.write_text(
        '<testsuite><failure message="{&quot;password&quot;: &quot;ABC\\&quot;TAILSECRET&quot;}">'
        "{'password': \"MIXEDSECRET\"} "
        '{"token": "TRUNCATEDSECRET...'
        "</failure></testsuite>",
        encoding="utf-8",
    )

    redact(artifact)

    result = artifact.read_text(encoding="utf-8")
    assert "TAILSECRET" not in result
    assert "MIXEDSECRET" not in result
    assert "TRUNCATEDSECRET" not in result
    ET.fromstring(result)


def test_ci_redactor_masks_bare_assignments_and_preserves_lines_after_truncated_json(tmp_path):
    artifact = tmp_path / "results.log"
    artifact.write_text(
        'access_token: "BAREJSONSECRET"\n'
        "password='ENVSECRET'\n"
        'Config(client_secret="CONFIGSECRET")\n'
        "ACCESS_TOKEN = SPACESECRET\n"
        '{"token":"TRUNCATEDSECRET...\n'
        'NEXT_DIAGNOSTIC={"status":"failed","code":17}\n',
        encoding="utf-8",
    )

    redact(artifact)

    result = artifact.read_text(encoding="utf-8")
    for secret in (
        "BAREJSONSECRET",
        "ENVSECRET",
        "CONFIGSECRET",
        "SPACESECRET",
        "TRUNCATEDSECRET",
    ):
        assert secret not in result
    assert 'NEXT_DIAGNOSTIC={"status":"failed","code":17}' in result


def test_ci_redactor_masks_multiline_dotted_and_non_string_sensitive_values(tmp_path):
    artifact = tmp_path / "results.xml"
    artifact.write_text(
        '<testsuite><failure message="{&quot;client_secret&quot;:&quot;FIRST&#10;ATTRTAILSECRET&quot;}">'
        '{"private_key":"BEGIN\nLINE2SECRET\nEND"}\n'
        'private_key="BEGIN\nLOGTAILSECRET\nEND"\n'
        '{"client.secret":"DOTSECRET","token":123456}'
        "</failure></testsuite>",
        encoding="utf-8",
    )

    redact(artifact)

    result = artifact.read_text(encoding="utf-8")
    for secret in (
        "ATTRTAILSECRET",
        "LINE2SECRET",
        "LOGTAILSECRET",
        "DOTSECRET",
        "123456",
    ):
        assert secret not in result
    ET.fromstring(result)


def test_ci_redactor_masks_complete_http_auth_and_cookie_headers(tmp_path):
    artifact = tmp_path / "results.log"
    artifact.write_text(
        "Authorization: Basic BASICSECRET\n"
        "Authorization: AWS4-HMAC-SHA256 Credential=AWSSECRET,SignedHeaders=host\n"
        "Cookie: theme=dark; session=COOKIESECRET; csrf=CSRFSECRET\n",
        encoding="utf-8",
    )

    redact(artifact)

    result = artifact.read_text(encoding="utf-8")
    for secret in ("BASICSECRET", "AWSSECRET", "COOKIESECRET", "CSRFSECRET"):
        assert secret not in result
    assert result.count("[REDACTED]") == 3


def test_ci_redactor_handles_driver_urls_and_unquoted_private_key_blocks(tmp_path):
    artifact = tmp_path / "results.log"
    artifact.write_text(
        "postgresql+psycopg2://readonly:DBVALUE@localhost/database\n"
        "redis://:REDISVALUE@localhost/0\n"
        "-----BEGIN PRIVATE KEY-----\nSYNTHETICKEYBODY\n-----END PRIVATE KEY-----\n"
        "NEXT_DIAGNOSTIC=failed\n",
        encoding="utf-8",
    )
    redact(artifact)
    result = artifact.read_text(encoding="utf-8")
    for value in ("DBVALUE", "REDISVALUE", "SYNTHETICKEYBODY"):
        assert value not in result
    assert "NEXT_DIAGNOSTIC=failed" in result
