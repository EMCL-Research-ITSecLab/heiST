"""Image-operation lease namespace shared with challenge provisioning."""
import os
from heist.infrastructure.locking import operation_guard


def template_guard(template_id, *, shared=False):
    return operation_guard(os.getenv('HEIST_TEMPLATE_LOCK_DIRECTORY', '/run/heist-template-operations'), template_id, shared=shared)
