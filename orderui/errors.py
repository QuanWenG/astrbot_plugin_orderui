class OrderUIError(Exception):
    def __init__(self, message, code="validation", *, trace_id=None, details=None):
        super().__init__(message)
        self.code = code
        self.trace_id = trace_id
        self.details = details

    def as_dict(self):
        return {
            "code": self.code,
            "message": str(self),
            "trace_id": self.trace_id,
            "details": self.details,
        }


class UncertainWrite(OrderUIError):
    def __init__(self, message="请求结果不明，请回读核对后再操作", **kwargs):
        super().__init__(message, "uncertain", **kwargs)
