class ServiceError(Exception):
    def __init__(self, code, message, *, retryable=False, retry_after=0, ambiguous=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after
        self.ambiguous = ambiguous


class Canceled(ServiceError):
    def __init__(self):
        super().__init__("canceled", "انتقال لغو شد.")


class LostClaim(ServiceError):
    def __init__(self):
        super().__init__("lost_claim", "مالکیت کار تغییر کرده است.")
