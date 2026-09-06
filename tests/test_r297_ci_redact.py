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
