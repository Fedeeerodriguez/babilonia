import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app import models

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(p: str) -> str:
    return pwd_context.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd_context.verify(p, h)


def create_access_token(data: dict, expires_minutes: Optional[int] = None) -> str:
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    cred_exc = HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = UUID(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise cred_exc
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.is_active:
        raise cred_exc
    return user


# admin y super_admin tienen acceso completo a la plataforma.
ADMIN_ROLES = (models.UserRole.admin, models.UserRole.super_admin)


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role not in ADMIN_ROLES:
        raise HTTPException(403, "Requiere rol administrador")
    return user


def require_super_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != models.UserRole.super_admin:
        raise HTTPException(403, "Requiere rol super administrador")
    return user
