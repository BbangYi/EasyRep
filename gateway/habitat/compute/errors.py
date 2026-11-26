class ComputeFailure(Exception):
    """Only a controlled diagnostic code is exposed; remote bodies and secrets stay private."""
    def __init__(self, code, *, retryable=False, status_code=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
