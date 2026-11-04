"""Public API failures carry safe messages, never infrastructure exceptions."""
class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status
