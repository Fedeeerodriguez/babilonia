from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app import models, schemas
from app.database import get_db
from app.security import require_admin, hash_password

router = APIRouter(prefix="/api/users", tags=["users"])

ELEVATED = (models.UserRole.admin, models.UserRole.super_admin)


@router.get("", response_model=List[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.post("", response_model=schemas.UserOut, status_code=201)
def create_user(
    data: schemas.UserCreate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_admin),
):
    """Crea un usuario. Cualquier admin puede crear asesores; solo un
    super-admin puede crear admins o super-admins."""
    if db.query(models.User).filter(models.User.email == data.email).first():
        raise HTTPException(400, "Email ya registrado")
    if data.role in ELEVATED and actor.role != models.UserRole.super_admin:
        raise HTTPException(403, "Solo un super-admin puede crear admins o super-admins")
    user = models.User(
        email=data.email,
        full_name=data.full_name,
        operator_name=data.operator_name,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(user); db.commit(); db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: UUID,
    data: schemas.UserUpdate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_admin),
):
    """Edita un usuario. Cambiar el ROL requiere super-admin. No se puede
    dejar la plataforma sin ningún super-admin activo."""
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(404, "Usuario no encontrado")

    if data.role is not None and data.role != user.role:
        if actor.role != models.UserRole.super_admin:
            raise HTTPException(403, "Solo un super-admin puede cambiar roles")
        if user.role == models.UserRole.super_admin and data.role != models.UserRole.super_admin:
            otros = db.query(models.User).filter(
                models.User.role == models.UserRole.super_admin,
                models.User.id != user.id,
                models.User.is_active == True,  # noqa: E712
            ).count()
            if otros == 0:
                raise HTTPException(400, "No podés dejar la plataforma sin super-admins")
        user.role = data.role

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.operator_name is not None:
        user.operator_name = data.operator_name
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password:
        user.password_hash = hash_password(data.password)

    db.commit(); db.refresh(user)
    return user
