from flask_login import UserMixin


class User(UserMixin):
    def __init__(
        self,
        id,
        org_id,
        full_name,
        email,
        username,
        password_hash,
        role_name,
        is_active=True
    ):
        self.id = str(id)
        self.org_id = org_id
        self.full_name = full_name
        self.email = email
        self.username = username
        self.password_hash = password_hash
        self.role_name = role_name
        self.is_active_flag = is_active

    @property
    def is_active(self):
        return bool(self.is_active_flag)