class GallopicsException(Exception):
    def __init__(self, detail: str, status_code: int = 500):
        self.detail = detail
        self.status_code = status_code


class NotFoundError(GallopicsException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(detail=detail, status_code=404)


class ConflictError(GallopicsException):
    def __init__(self, detail: str = "Conflict"):
        super().__init__(detail=detail, status_code=409)


class ForbiddenError(GallopicsException):
    def __init__(self, detail: str = "Forbidden"):
        super().__init__(detail=detail, status_code=403)


class UnauthorizedError(GallopicsException):
    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(detail=detail, status_code=401)


class BadRequestError(GallopicsException):
    def __init__(self, detail: str = "Bad request"):
        super().__init__(detail=detail, status_code=400)


class ExternalServiceError(GallopicsException):
    def __init__(self, detail: str = "External service error"):
        super().__init__(detail=detail, status_code=502)


class RateLimitError(GallopicsException):
    def __init__(self, detail: str = "Rate limit exceeded"):
        super().__init__(detail=detail, status_code=429)
