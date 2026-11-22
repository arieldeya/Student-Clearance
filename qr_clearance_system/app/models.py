from datetime import UTC, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash

from .extensions import db, login_manager


def utc_now():
    return datetime.now(UTC)

class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    code = db.Column(db.String(20), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    registration_number = db.Column(db.String(40), unique=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    department = db.relationship("Department", backref="officers")
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ClearanceRequest(db.Model):
    __tablename__ = "clearance_requests"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    student = db.relationship("User", backref="clearance_requests")

class ClearanceItem(db.Model):
    __tablename__ = "clearance_items"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("clearance_requests.id"), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)
    remarks = db.Column(db.Text)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    request = db.relationship("ClearanceRequest", backref="items")
    department = db.relationship("Department")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    user = db.relationship("User")

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
