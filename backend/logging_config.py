import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("method", "path", "status_code", "duration_ms", "client_ip", "event"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_json_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(getattr(handler.formatter, "_tiantong_json", False) for handler in root.handlers):
        root.setLevel(level)
        return

    handler = logging.StreamHandler()
    formatter = JsonFormatter()
    formatter._tiantong_json = True
    handler.setFormatter(formatter)
    root.handlers = [handler]
    root.setLevel(level)
