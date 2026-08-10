from flask import g


def set_current_org(org):
    g.current_org = org


def get_current_org():
    return getattr(g, "current_org", None)