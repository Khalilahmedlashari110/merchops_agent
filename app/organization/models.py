class Organization:
    def __init__(self, row):
        self.id = row.id
        self.name = row.name
        self.code = row.code

        self.db_server = row.db_server
        self.db_name = row.db_name
        self.db_driver = row.db_driver

        self.email = row.email
        self.smtp_server = row.smtp_server
        self.smtp_port = row.smtp_port
        self.email_password = row.email_password

    def get_connection_string(self):
        return (
            f"DRIVER={{{self.db_driver}}};"
            f"SERVER={self.db_server};"
            f"DATABASE={self.db_name};"
            "Trusted_Connection=yes;"
        )