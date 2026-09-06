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
    assert result.count("[REDACTED]") == 3
    ET.fromstring(result)


def test_ci_redactor_masks_json_values_escaped_inside_junit_xml(tmp_path):
    artifact = tmp_path / "results.xml"
    artifact.write_text(
        '<testsuite><failure message="{&quot;token&quot;: &quot;TOPSECRET&quot;, '
        '&quot;password&quot;: &quot;PASSSECRET&quot;}"/></testsuite>',
        encoding="utf-8",
    )

    redact(artifact)

    result = artifact.read_text(encoding="utf-8")
    assert "TOPSECRET" not in result
    assert "PASSSECRET" not in result
    assert result.count("[REDACTED]") == 2
    ET.fromstring(result)
