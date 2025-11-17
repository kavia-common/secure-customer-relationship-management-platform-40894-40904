from __future__ import annotations

from fastapi import HTTPException, status


# PUBLIC_INTERFACE
class AppError(Exception):
    """Generic application error."""


# PUBLIC_INTERFACE
def bad_request(detail: str = "Bad request") -> HTTPException:
    """Return an HTTP 400 Bad Request exception."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# PUBLIC_INTERFACE
def unauthorized(detail: str = "Unauthorized") -> HTTPException:
    """Return an HTTP 401 Unauthorized exception."""
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


# PUBLIC_INTERFACE
def forbidden(detail: str = "Forbidden") -> HTTPException:
    """Return an HTTP 403 Forbidden exception."""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# PUBLIC_INTERFACE
def not_found(detail: str = "Not found") -> HTTPException:
    """Return an HTTP 404 Not Found exception."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# PUBLIC_INTERFACE
def server_error(detail: str = "Internal server error") -> HTTPException:
    """Return an HTTP 500 Internal Server Error exception."""
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)
