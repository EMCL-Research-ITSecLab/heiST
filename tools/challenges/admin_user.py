import os
from dotenv import load_dotenv, find_dotenv
from .get_authenticated_session import get_authenticated_session

env_file = find_dotenv()
load_dotenv(env_file)

DEFAULT_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

class AdminUser:
    def __init__(self, username=None, password=None):
        self.username = username if username else DEFAULT_ADMIN_USERNAME
        self.password = password if password else DEFAULT_ADMIN_PASSWORD
        if not self.password:
            raise ValueError('Provide an operator password explicitly or through ADMIN_PASSWORD')
        self.session = get_authenticated_session(self.username, self.password)

        if not self.session:
            raise Exception("Failed to create admin user session.")

    def get_session(self):
        return self.session
