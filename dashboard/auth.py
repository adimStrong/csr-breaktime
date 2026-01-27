"""
CSR Breaktime Dashboard - Authentication System
Simple JWT-based authentication with role-based access.
"""

import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict
from dataclasses import dataclass

# Simple JWT-like token (no external dependencies)
SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_hex(32))
TOKEN_EXPIRE_HOURS = 24

# User roles
ROLES = {
    'admin': ['read', 'write', 'delete', 'manage_users', 'export', 'alerts'],
    'supervisor': ['read', 'write', 'export', 'alerts'],
    'agent': ['read']
}

# In-memory user store (replace with DB in production)
USERS_DB: Dict[str, dict] = {
    'admin': {
        'password_hash': hashlib.sha256('admin123'.encode()).hexdigest(),
        'role': 'admin',
        'full_name': 'Administrator'
    },
    'supervisor': {
        'password_hash': hashlib.sha256('super123'.encode()).hexdigest(),
        'role': 'supervisor',
        'full_name': 'Team Supervisor'
    }
}


@dataclass
class User:
    username: str
    role: str
    full_name: str
    permissions: list


def hash_password(password: str) -> str:
    """Hash a password."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return hash_password(password) == password_hash


def create_token(username: str, role: str) -> str:
    """Create a simple token."""
    import base64
    import json

    payload = {
        'username': username,
        'role': role,
        'exp': (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)).isoformat(),
        'iat': datetime.utcnow().isoformat()
    }

    # Simple encoding (not secure for production - use proper JWT)
    data = json.dumps(payload)
    token_data = base64.b64encode(data.encode()).decode()
    signature = hashlib.sha256(f"{token_data}{SECRET_KEY}".encode()).hexdigest()[:16]

    return f"{token_data}.{signature}"


def verify_token(token: str) -> Optional[Dict]:
    """Verify and decode a token."""
    import base64
    import json

    try:
        parts = token.split('.')
        if len(parts) != 2:
            return None

        token_data, signature = parts

        # Verify signature
        expected_sig = hashlib.sha256(f"{token_data}{SECRET_KEY}".encode()).hexdigest()[:16]
        if signature != expected_sig:
            return None

        # Decode payload
        data = base64.b64decode(token_data).decode()
        payload = json.loads(data)

        # Check expiration
        exp = datetime.fromisoformat(payload['exp'])
        if datetime.utcnow() > exp:
            return None

        return payload
    except Exception:
        return None


def authenticate(username: str, password: str) -> Optional[str]:
    """Authenticate user and return token."""
    user = USERS_DB.get(username)
    if not user:
        return None

    if not verify_password(password, user['password_hash']):
        return None

    return create_token(username, user['role'])


def get_current_user(token: str) -> Optional[User]:
    """Get current user from token."""
    payload = verify_token(token)
    if not payload:
        return None

    username = payload['username']
    user_data = USERS_DB.get(username)
    if not user_data:
        return None

    return User(
        username=username,
        role=user_data['role'],
        full_name=user_data['full_name'],
        permissions=ROLES.get(user_data['role'], [])
    )


def has_permission(user: User, permission: str) -> bool:
    """Check if user has a specific permission."""
    return permission in user.permissions


# FastAPI integration
def get_auth_router():
    """Return authentication API router."""
    from fastapi import APIRouter, HTTPException, Depends, Header
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/auth", tags=["Authentication"])

    class LoginRequest(BaseModel):
        username: str
        password: str

    class TokenResponse(BaseModel):
        access_token: str
        token_type: str = "bearer"
        expires_in: int = TOKEN_EXPIRE_HOURS * 3600
        user: dict

    @router.post("/login", response_model=TokenResponse)
    async def login(request: LoginRequest):
        """Login and get access token."""
        token = authenticate(request.username, request.password)
        if not token:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        user = get_current_user(token)
        return TokenResponse(
            access_token=token,
            user={
                "username": user.username,
                "role": user.role,
                "full_name": user.full_name,
                "permissions": user.permissions
            }
        )

    @router.get("/me")
    async def get_me(authorization: str = Header(None)):
        """Get current user info."""
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")

        token = authorization.replace("Bearer ", "")
        user = get_current_user(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        return {
            "username": user.username,
            "role": user.role,
            "full_name": user.full_name,
            "permissions": user.permissions
        }

    @router.post("/logout")
    async def logout():
        """Logout (client should discard token)."""
        return {"message": "Logged out successfully"}

    return router


# Dependency for protected routes
def require_auth(authorization: str = None):
    """Dependency to require authentication."""
    from fastapi import Header, HTTPException

    def _require_auth(authorization: str = Header(None)):
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")

        token = authorization.replace("Bearer ", "")
        user = get_current_user(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        return user

    return _require_auth


def require_permission(permission: str):
    """Dependency to require specific permission."""
    from fastapi import Header, HTTPException

    def _require_permission(authorization: str = Header(None)):
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")

        token = authorization.replace("Bearer ", "")
        user = get_current_user(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        if not has_permission(user, permission):
            raise HTTPException(status_code=403, detail="Permission denied")

        return user

    return _require_permission
