from flask import request
from app.organization.service import get_org_by_code
from app.core.context import set_current_org


def load_organization():
    # OPTION 1: from query param
    org_code = request.args.get("org")

    if not org_code:
        return None

    org = get_org_by_code(org_code)

    if org:
        set_current_org(org)

    return org