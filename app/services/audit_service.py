import uuid
from typing import Optional

import structlog

audit_logger = structlog.get_logger("audit")


def log_audit(
    action: str,
    actor_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    details: Optional[dict] = None,
):
    audit_logger.info(
        "audit_event",
        action=action,
        actor_id=str(actor_id),
        resource_type=resource_type,
        resource_id=str(resource_id),
        details=details,
    )
