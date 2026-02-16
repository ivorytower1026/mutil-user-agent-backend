"""Authentication API endpoints."""
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.auth import verify_password, get_password_hash, create_access_token
from src.config import settings
from src.database import get_db, User

router = APIRouter()


class UserRegister(BaseModel):
    """User registration request."""
    username: str
    password: str


class UserLogin(BaseModel):
    """User login request."""
    username: str
    password: str


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str


class RegisterResponse(BaseModel):
    """Registration response."""
    message: str
    user_id: str


@router.post("/register", response_model=RegisterResponse)
async def register(user: UserRegister, db: Session = Depends(get_db)):
    """Register a new user.
    
    Args:
        user: User registration data (username, password)
        db: Database session
        
    Returns:
        RegisterResponse with success message and user_id
    """
    # Check if username already exists
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Create new user
    user_id = str(uuid.uuid4())
    
    workspace_dir = os.path.join(
        Path(settings.WORKSPACE_ROOT).expanduser().absolute(),
        user_id
    )
    os.makedirs(workspace_dir, exist_ok=True)
    
    db_user = User(
        user_id=user_id,
        username=user.username,
        password_hash=get_password_hash(user.password)
    )
    db.add(db_user)
    db.commit()
    
    return RegisterResponse(
        message="User registered successfully",
        user_id=user_id
    )


@router.post("/login", response_model=Token)
async def login(user: UserLogin, db: Session = Depends(get_db)):
    """Login and get JWT token.
    
    Args:
        user: User login data (username, password)
        db: Database session
        
    Returns:
        Token with access_token
    """
    # Find user by username
    db_user = db.query(User).filter(User.username == user.username).first()
    
    # Verify user exists and password is correct
    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password"
        )
    
    # Create JWT token
    access_token = create_access_token(data={"sub": db_user.user_id})
    
    return Token(access_token=access_token, token_type="bearer")
