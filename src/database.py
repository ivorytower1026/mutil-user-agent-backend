"""Database connection and models."""
from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Integer, Float, Text, JSON, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from src.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """User model for authentication."""
    __tablename__ = "users"

    user_id = Column(String(50), primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class Thread(Base):
    """Thread model for session metadata."""
    __tablename__ = "threads"

    thread_id = Column(String(100), primary_key=True)
    user_id = Column(String(50), nullable=False, index=True)
    title = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Skill(Base):
    """Skill model for skill validation and management."""
    __tablename__ = "skills"

    skill_id = Column(String(50), primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    display_name = Column(String(100))
    description = Column(String(1024))

    status = Column(String(20), default="pending", nullable=False, index=True)
    validation_stage = Column(String(20))

    skill_path = Column(String(255), nullable=False)

    format_valid = Column(Boolean, default=False)
    format_errors = Column(JSON, default=list)
    format_warnings = Column(JSON, default=list)

    layer1_passed = Column(Boolean, default=False)
    layer1_report = Column(JSON)

    blind_test_passed = Column(Boolean, default=False)
    skill_triggered = Column(Boolean, default=False)
    trigger_accuracy = Column(Float)
    network_test_passed = Column(Boolean, default=False)
    offline_capable = Column(Boolean, default=False)
    blocked_network_calls = Column(Integer, default=0)
    execution_metrics = Column(JSON)
    task_results = Column(JSON)

    completion_score = Column(Integer)
    trigger_accuracy_score = Column(Integer)
    offline_capability_score = Column(Integer)
    resource_efficiency_score = Column(Integer)

    score_weights = Column(JSON)
    task_completion_details = Column(JSON)

    layer2_passed = Column(Boolean, default=False)
    layer2_report = Column(JSON)

    regression_results = Column(JSON)

    validation_score = Column(Float)
    validation_report = Column(JSON)
    validated_at = Column(DateTime)

    installed_dependencies = Column(JSON)
    docker_image = Column(String(255))
    requirements = Column(Text)

    runtime_image_version = Column(String(50))

    approved_by = Column(String(50), ForeignKey("users.user_id"))
    approved_at = Column(DateTime)
    rejected_by = Column(String(50), ForeignKey("users.user_id"))
    rejected_at = Column(DateTime)
    reject_reason = Column(String(500))

    created_by = Column(String(50), ForeignKey("users.user_id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ImageVersion(Base):
    """Image version model for skill runtime images."""
    __tablename__ = "image_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(50), unique=True, nullable=False)
    skill_id = Column(String(50), ForeignKey("skills.skill_id"))
    created_at = Column(DateTime, server_default=func.now())
    is_current = Column(Boolean, default=False)
    dependencies_snapshot = Column(JSON)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)
