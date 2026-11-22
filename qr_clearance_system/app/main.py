
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import urlsplit

import qrcode
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import AuditLog, ClearanceItem, ClearanceRequest, Department, User

main_bp = Blueprint("main", __name__)


# ==========================================================
# HOME PAGE
# ==========================================================

@main_bp.route("/")
def index():

    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    return redirect(url_for("auth.login"))


# ==========================================================
# ROLE-BASED DASHBOARDS
# ==========================================================

@main_bp.route("/dashboard")
@login_required
def dashboard():

    # ======================================================
    # STUDENT DASHBOARD
    # ======================================================

    if current_user.role == "student":

        student_requests = (
            ClearanceRequest.query
            .filter_by(student_id=current_user.id)
            .order_by(ClearanceRequest.submitted_at.desc())
            .all()
        )

        return render_template(
            "dashboards/student.html",
            requests=student_requests
        )

    # ======================================================
    # OFFICER DASHBOARD
    # ======================================================

    if current_user.role == "officer":

        if not current_user.department_id:

            flash(
                "Your account has not been assigned to a department. "
                "Contact the system administrator.",
                "warning"
            )

            return render_template(
                "dashboards/officer.html",
                clearance_items=[]
            )

        clearance_items = (
            ClearanceItem.query
            .join(ClearanceRequest)
            .filter(
                ClearanceItem.department_id == current_user.department_id,
                ClearanceItem.status == "pending",
                ClearanceRequest.status.in_(
                    ["pending", "in_progress"]
                )
            )
            .order_by(ClearanceRequest.submitted_at.asc())
            .all()
        )

        return render_template(
            "dashboards/officer.html",
            clearance_items=clearance_items
        )

    # ======================================================
    # ADMINISTRATOR DASHBOARD
    # ======================================================

    if current_user.role == "admin":

        # --------------------------------------------------
        # USER STATISTICS
        # --------------------------------------------------

        total_students = User.query.filter_by(
            role="student"
        ).count()

        total_officers = User.query.filter_by(
            role="officer"
        ).count()

        total_verifiers = User.query.filter_by(
            role="verifier"
        ).count()

        total_departments = Department.query.count()

        # --------------------------------------------------
        # CLEARANCE STATISTICS
        # --------------------------------------------------

        total_requests = ClearanceRequest.query.count()

        approved_requests = ClearanceRequest.query.filter_by(
            status="approved"
        ).count()

        pending_requests = ClearanceRequest.query.filter(
            ClearanceRequest.status.in_(
                ["pending", "in_progress"]
            )
        ).count()

        rejected_requests = ClearanceRequest.query.filter_by(
            status="rejected"
        ).count()

        # --------------------------------------------------
        # REGISTERED OFFICERS
        # --------------------------------------------------

        registered_officers = (
            User.query
            .filter_by(role="officer")
            .order_by(User.full_name.asc())
            .all()
        )

        # --------------------------------------------------
        # REGISTERED VERIFIERS
        # --------------------------------------------------

        registered_verifiers = (
            User.query
            .filter_by(role="verifier")
            .order_by(User.full_name.asc())
            .all()
        )

        # --------------------------------------------------
        # RECENT CLEARANCE REQUESTS
        # --------------------------------------------------

        recent_requests = (
            ClearanceRequest.query
            .order_by(
                ClearanceRequest.submitted_at.desc()
            )
            .limit(6)
            .all()
        )

        # --------------------------------------------------
        # CLEARANCE STATUS DISTRIBUTION
        # --------------------------------------------------

        clearance_status_data = [
            approved_requests,
            pending_requests,
            rejected_requests
        ]

        # --------------------------------------------------
        # DEPARTMENT CLEARANCE PROGRESS
        # --------------------------------------------------

        departments = (
            Department.query
            .order_by(Department.name.asc())
            .all()
        )

        department_progress = []

        for department in departments:

            total_items = ClearanceItem.query.filter_by(
                department_id=department.id
            ).count()

            approved_items = ClearanceItem.query.filter_by(
                department_id=department.id,
                status="approved"
            ).count()

            progress = (
                round((approved_items / total_items) * 100)
                if total_items > 0
                else 0
            )

            department_progress.append({
                "name": department.name,
                "total": total_items,
                "approved": approved_items,
                "progress": progress
            })

        # --------------------------------------------------
        # RENDER ADMINISTRATOR DASHBOARD
        # --------------------------------------------------

        return render_template(
            "dashboards/admin.html",

            # Statistics
            students=total_students,
            officers=total_officers,
            departments=total_departments,
            requests=total_requests,

            approved_requests=approved_requests,
            pending_requests=pending_requests,
            rejected_requests=rejected_requests,
            verifiers=total_verifiers,

            # Registered users
            registered_officers=registered_officers,
            registered_verifiers=registered_verifiers,

            # Analytics
            clearance_status_data=clearance_status_data,
            department_progress=department_progress,

            # Recent activities
            recent_requests=recent_requests
        )

    # ======================================================
    # VERIFIER DASHBOARD
    # ======================================================

    if current_user.role == "verifier":

        return render_template(
            "dashboards/verifier.html"
        )

    abort(403)

# ==========================================================
# STUDENT CLEARANCE APPLICATION
# ==========================================================

@main_bp.route("/clearance/apply", methods=["GET", "POST"])
@login_required
def apply_clearance():

    # Only students can apply.
    if current_user.role != "student":
        abort(403)

    # Prevent multiple active applications.
    existing_request = ClearanceRequest.query.filter(
        ClearanceRequest.student_id == current_user.id,
        ClearanceRequest.status.in_(
            ["pending", "in_progress"]
        )
    ).first()

    if existing_request:

        flash(
            "You already have an active clearance application.",
            "warning"
        )

        return redirect(url_for("main.dashboard"))

    # Retrieve active departments.
    departments = Department.query.filter_by(
        is_active=True
    ).all()

    if not departments:

        flash(
            "No active departments are available for clearance.",
            "danger"
        )

        return redirect(url_for("main.dashboard"))

    # Process application submission.
    if request.method == "POST":

        try:

            # Create clearance request.
            clearance_request = ClearanceRequest(
                student_id=current_user.id,
                status="pending"
            )

            db.session.add(clearance_request)

            # Obtain generated request ID.
            db.session.flush()

            # Create an item for every active department.
            for department in departments:

                clearance_item = ClearanceItem(
                    request_id=clearance_request.id,
                    department_id=department.id,
                    status="pending"
                )

                db.session.add(clearance_item)

            # Create audit record.
            audit = AuditLog(
                user_id=current_user.id,
                action="Submitted clearance application",
                entity_type="ClearanceRequest",
                entity_id=clearance_request.id,
                details=(
                    "Student submitted a new university "
                    "clearance application."
                )
            )

            db.session.add(audit)

            db.session.commit()

            flash(
                "Your clearance application has been submitted successfully!",
                "success"
            )

            return redirect(url_for("main.dashboard"))

        except SQLAlchemyError:

            db.session.rollback()

            flash(
                "An error occurred while submitting your application. "
                "Please try again.",
                "danger"
            )

    return render_template(
        "apply_clearance.html"
    )


# ==========================================================
# STUDENT CLEARANCE PROGRESS TRACKING
# ==========================================================

@main_bp.route("/clearance/<int:request_id>")
@login_required
def clearance_details(request_id):

    # Only students can view their clearance details.
    if current_user.role != "student":
        abort(403)

    # Retrieve only the logged-in student's application.
    clearance_request = ClearanceRequest.query.filter_by(
        id=request_id,
        student_id=current_user.id
    ).first_or_404()

    # Sort departments alphabetically.
    items = sorted(
        clearance_request.items,
        key=lambda item: item.department.name
    )

    # Calculate progress.
    total_departments = len(items)

    approved_departments = sum(
        1 for item in items
        if item.status == "approved"
    )

    progress = (
        round(
            (approved_departments / total_departments) * 100
        )
        if total_departments > 0
        else 0
    )

    return render_template(
        "clearance_details.html",
        clearance_request=clearance_request,
        items=items,
        total_departments=total_departments,
        approved_departments=approved_departments,
        progress=progress
    )


# ==========================================================
# DEPARTMENT OFFICER CLEARANCE REVIEW
# ==========================================================

@main_bp.route(
    "/officer/clearance/<int:item_id>/review",
    methods=["POST"]
)
@login_required
def review_clearance(item_id):

    # Only officers can review clearance applications.
    if current_user.role != "officer":
        abort(403)

    # Ensure the officer has an assigned department.
    if not current_user.department_id:
        abort(403)

    # Retrieve the clearance item.
    clearance_item = ClearanceItem.query.get_or_404(item_id)

    # Restrict officers to their assigned department.
    if clearance_item.department_id != current_user.department_id:
        abort(403)

    # Prevent reviewing an item more than once.
    if clearance_item.status != "pending":

        flash(
            "This clearance item has already been reviewed.",
            "warning"
        )

        return redirect(url_for("main.dashboard"))

    # Retrieve submitted decision and remarks.
    decision = request.form.get(
        "decision",
        ""
    ).strip().lower()

    remarks = request.form.get(
        "remarks",
        ""
    ).strip()

    # Validate decision.
    if decision not in ["approved", "rejected"]:

        flash(
            "Please select a valid clearance decision.",
            "danger"
        )

        return redirect(url_for("main.dashboard"))

    # Require remarks when rejecting.
    if decision == "rejected" and not remarks:

        flash(
            "Please provide a reason when rejecting clearance.",
            "danger"
        )

        return redirect(url_for("main.dashboard"))

    try:

        # --------------------------------------------------
        # UPDATE DEPARTMENTAL CLEARANCE ITEM
        # --------------------------------------------------

        clearance_item.status = decision

        clearance_item.remarks = remarks

        clearance_item.reviewed_by = current_user.id

        clearance_item.reviewed_at = datetime.now(UTC)

        db.session.flush()

        # Retrieve the parent clearance request.
        clearance_request = clearance_item.request

        # Retrieve all departmental clearance items.
        all_items = clearance_request.items

        # --------------------------------------------------
        # AUTOMATIC OVERALL STATUS UPDATE
        # --------------------------------------------------

        pending_items = [
            item for item in all_items
            if item.status == "pending"
        ]

        rejected_items = [
            item for item in all_items
            if item.status == "rejected"
        ]

        # Case 1: Some departments have not completed
        # their reviews.
        if pending_items:

            # No department has reviewed the application yet.
            if len(pending_items) == len(all_items):

                clearance_request.status = "pending"

            else:

                # Other departments must continue reviewing.
                clearance_request.status = "in_progress"

        # Case 2: Every department has approved clearance.
        elif (
            all_items
            and all(item.status == "approved" for item in all_items)
        ):

            clearance_request.status = "approved"

        # Case 3: All departments have completed their reviews,
        # but at least one department rejected clearance.
        elif rejected_items:

            clearance_request.status = "rejected"

        # Defensive fallback.
        else:

            clearance_request.status = "pending"

        # --------------------------------------------------
        # AUDIT LOGGING
        # --------------------------------------------------

        audit = AuditLog(
            user_id=current_user.id,
            action=f"Clearance {decision}",
            entity_type="ClearanceItem",
            entity_id=clearance_item.id,
            details=(
                f"{current_user.department.name} department "
                f"{decision} clearance for "
                f"{clearance_request.student.full_name}. "
                f"Remarks: {remarks or 'None'}"
            )
        )

        db.session.add(audit)

        # Save all changes.
        db.session.commit()

        flash(
            f"Clearance successfully {decision}.",
            "success"
        )

    except SQLAlchemyError:

        db.session.rollback()

        flash(
            "An error occurred while processing the clearance decision.",
            "danger"
        )

    return redirect(url_for("main.dashboard"))


# ==========================================================
# ADMIN: REGISTER DEPARTMENT OFFICER
# ==========================================================

@main_bp.route("/admin/officers/add", methods=["GET", "POST"])
@login_required
def add_officer():

    # Only administrators can create officer accounts.
    if current_user.role != "admin":
        abort(403)

    # Retrieve active departments.
    departments = Department.query.filter_by(
        is_active=True
    ).order_by(Department.name.asc()).all()

    if request.method == "POST":

        full_name = request.form.get(
            "full_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        department_id = request.form.get(
            "department_id", ""
        )

        # Validate required fields.
        if not all([full_name, email, password, department_id]):

            flash(
                "Please complete all fields.",
                "danger"
            )

            return redirect(url_for("main.add_officer"))

        if len(password) < 8:

            flash(
                "Password must contain at least 8 characters.",
                "danger"
            )

            return redirect(url_for("main.add_officer"))

        # Check for an existing email.
        if User.query.filter_by(email=email).first():

            flash(
                "An account with that email already exists.",
                "danger"
            )

            return redirect(url_for("main.add_officer"))

        # Validate department selection.
        department = Department.query.filter_by(
            id=department_id,
            is_active=True
        ).first()

        if not department:

            flash(
                "Please select a valid department.",
                "danger"
            )

            return redirect(url_for("main.add_officer"))

        try:

            # Create officer account.
            officer = User(
                full_name=full_name,
                email=email,
                password_hash=generate_password_hash(password),
                role="officer",
                department_id=department.id
            )

            db.session.add(officer)
            db.session.flush()

            # Record officer creation.
            audit = AuditLog(
                user_id=current_user.id,
                action="Created department officer",
                entity_type="User",
                entity_id=officer.id,
                details=(
                    f"Created officer account for {full_name}, "
                    f"assigned to {department.name}."
                )
            )

            db.session.add(audit)
            db.session.commit()

            flash(
                f"Officer account for {full_name} created successfully.",
                "success"
            )

            return redirect(url_for("main.dashboard"))

        except SQLAlchemyError:

            db.session.rollback()

            flash(
                "An error occurred while creating the officer account.",
                "danger"
            )

    return render_template(
        "admin/add_officer.html",
        departments=departments
    )

# ==========================================================
# ADMIN: ACTIVATE / DEACTIVATE OFFICER ACCOUNTS
# ==========================================================

@main_bp.route(
    "/admin/officers/<int:officer_id>/toggle-status",
    methods=["POST"]
)
@login_required
def toggle_officer_status(officer_id):

    # Only administrators can manage officer accounts.
    if current_user.role != "admin":
        abort(403)

    # Retrieve the officer.
    officer = User.query.filter_by(
        id=officer_id,
        role="officer"
    ).first_or_404()

    try:

        # Change account status.
        officer.is_active = not officer.is_active

        status = "activated" if officer.is_active else "deactivated"

        # Record the action.
        audit = AuditLog(
            user_id=current_user.id,
            action=f"Officer account {status}",
            entity_type="User",
            entity_id=officer.id,
            details=(
                f"Administrator {current_user.full_name} "
                f"{status} the account belonging to "
                f"{officer.full_name}."
            )
        )

        db.session.add(audit)
        db.session.commit()

        flash(
            f"Officer account successfully {status}.",
            "success"
        )

    except SQLAlchemyError:

        db.session.rollback()

        flash(
            "An error occurred while updating the officer account.",
            "danger"
        )

    return redirect(url_for("main.dashboard"))

# ==========================================================
# ADMIN: EDIT DEPARTMENT OFFICER
# ==========================================================

@main_bp.route(
    "/admin/officers/<int:officer_id>/edit",
    methods=["GET", "POST"]
)
@login_required
def edit_officer(officer_id):

    # Only administrators can edit officer accounts.
    if current_user.role != "admin":
        abort(403)

    # Retrieve the officer.
    officer = User.query.filter_by(
        id=officer_id,
        role="officer"
    ).first_or_404()

    # Retrieve active departments.
    departments = (
        Department.query
        .filter_by(is_active=True)
        .order_by(Department.name.asc())
        .all()
    )

    if request.method == "POST":

        full_name = request.form.get(
            "full_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        department_id = request.form.get(
            "department_id", ""
        )

        # Validate required fields.
        if not all([full_name, email, department_id]):

            flash(
                "Please complete all fields.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.edit_officer",
                    officer_id=officer.id
                )
            )

        # Check whether another account uses this email.
        existing_email = User.query.filter(
            User.email == email,
            User.id != officer.id
        ).first()

        if existing_email:

            flash(
                "Another account already uses that email address.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.edit_officer",
                    officer_id=officer.id
                )
            )

        # Validate the selected active department.
        try:
            selected_department_id = int(department_id)
        except (TypeError, ValueError):
            selected_department_id = None

        department = Department.query.filter_by(
            id=selected_department_id,
            is_active=True
        ).first()

        if not department:

            flash(
                "Please select a valid active department.",
                "danger"
            )

            return redirect(
                url_for(
                    "main.edit_officer",
                    officer_id=officer.id
                )
            )

        try:

            old_name = officer.full_name
            old_email = officer.email
            old_department = (
                officer.department.name
                if officer.department
                else "Unassigned"
            )

            # Update officer information.
            officer.full_name = full_name
            officer.email = email
            officer.department_id = department.id

            # Record the changes.
            audit = AuditLog(
                user_id=current_user.id,
                action="Updated department officer",
                entity_type="User",
                entity_id=officer.id,
                details=(
                    f"Updated officer from {old_name} "
                    f"({old_email}), department: {old_department}, "
                    f"to {full_name} ({email}), "
                    f"department: {department.name}."
                )
            )

            db.session.add(audit)
            db.session.commit()

            flash(
                f"Officer {full_name} updated successfully.",
                "success"
            )

            return redirect(url_for("main.dashboard"))

        except SQLAlchemyError:

            db.session.rollback()

            flash(
                "An error occurred while updating the officer.",
                "danger"
            )

    return render_template(
        "admin/edit_officer.html",
        officer=officer,
        departments=departments
    )

@main_bp.route("/admin/officers")
@login_required
def manage_officers():

    if current_user.role != "admin":
        abort(403)

    search = request.args.get("search", "").strip()

    officers_query = User.query.filter_by(role="officer")

    # Search by officer name, email or department
    if search:
        officers_query = officers_query.filter(
            db.or_(
                User.full_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.department.has(
                    Department.name.ilike(f"%{search}%")
                )
            )
        )

    officers = (
        officers_query
        .order_by(User.full_name.asc())
        .all()
    )

    # Officer statistics
    total_officers = User.query.filter_by(
        role="officer"
    ).count()

    active_officers = User.query.filter_by(
        role="officer",
        is_active=True
    ).count()

    inactive_officers = User.query.filter_by(
        role="officer",
        is_active=False
    ).count()

    return render_template(
        "admin/officers.html",
        officers=officers,
        search=search,
        total_officers=total_officers,
        active_officers=active_officers,
        inactive_officers=inactive_officers
    )

# ==========================================================
# ADMIN: DEPARTMENT MANAGEMENT
# ==========================================================

@main_bp.route("/admin/departments")
@login_required
def manage_departments():

    if current_user.role != "admin":
        abort(403)

    departments = (
        Department.query
        .order_by(Department.name.asc())
        .all()
    )

    department_data = []

    for department in departments:

        officer_count = User.query.filter_by(
            role="officer",
            department_id=department.id
        ).count()

        department_data.append({
            "department": department,
            "officer_count": officer_count
        })

    return render_template(
        "admin/departments.html",
        department_data=department_data
    )


# ==========================================================
# ADMIN: ADD DEPARTMENT
# ==========================================================

@main_bp.route("/admin/departments/add", methods=["GET", "POST"])
@login_required
def add_department():

    if current_user.role != "admin":
        abort(403)

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()

        if not name or not code:

            flash("Please complete all department fields.", "danger")

            return redirect(url_for("main.add_department"))

        if Department.query.filter(
            db.or_(
                db.func.lower(Department.name) == name.lower(),
                db.func.upper(Department.code) == code
            )
        ).first():

            flash(
                "A department with that name or code already exists.",
                "danger"
            )

            return redirect(url_for("main.add_department"))

        try:

            department = Department(
                name=name,
                code=code,
                is_active=True
            )

            db.session.add(department)
            db.session.flush()

            audit = AuditLog(
                user_id=current_user.id,
                action="Created department",
                entity_type="Department",
                entity_id=department.id,
                details=f"Created department {name} with code {code}."
            )

            db.session.add(audit)
            db.session.commit()

            flash("Department created successfully.", "success")

            return redirect(url_for("main.manage_departments"))

        except SQLAlchemyError:

            db.session.rollback()

            flash("An error occurred while creating the department.", "danger")

    return render_template("admin/add_department.html")


# ==========================================================
# ADMIN: EDIT DEPARTMENT
# ==========================================================

@main_bp.route(
    "/admin/departments/<int:department_id>/edit",
    methods=["GET", "POST"]
)
@login_required
def edit_department(department_id):

    if current_user.role != "admin":
        abort(403)

    department = Department.query.get_or_404(department_id)

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()

        if not name or not code:

            flash("Please complete all fields.", "danger")

            return redirect(
                url_for("main.edit_department", department_id=department.id)
            )

        duplicate = Department.query.filter(
            Department.id != department.id,
            db.or_(
                db.func.lower(Department.name) == name.lower(),
                db.func.upper(Department.code) == code
            )
        ).first()

        if duplicate:

            flash(
                "Another department already uses that name or code.",
                "danger"
            )

            return redirect(
                url_for("main.edit_department", department_id=department.id)
            )

        try:

            old_name = department.name
            old_code = department.code

            department.name = name
            department.code = code

            audit = AuditLog(
                user_id=current_user.id,
                action="Updated department",
                entity_type="Department",
                entity_id=department.id,
                details=(
                    f"Updated department from {old_name} ({old_code}) "
                    f"to {name} ({code})."
                )
            )

            db.session.add(audit)
            db.session.commit()

            flash("Department updated successfully.", "success")

            return redirect(url_for("main.manage_departments"))

        except SQLAlchemyError:

            db.session.rollback()

            flash("An error occurred while updating the department.", "danger")

    return render_template(
        "admin/edit_department.html",
        department=department
    )


# ==========================================================
# ADMIN: ACTIVATE / DEACTIVATE DEPARTMENT
# ==========================================================

@main_bp.route(
    "/admin/departments/<int:department_id>/toggle-status",
    methods=["POST"]
)
@login_required
def toggle_department_status(department_id):

    if current_user.role != "admin":
        abort(403)

    department = Department.query.get_or_404(department_id)

    try:

        department.is_active = not department.is_active

        status = "activated" if department.is_active else "deactivated"

        audit = AuditLog(
            user_id=current_user.id,
            action=f"Department {status}",
            entity_type="Department",
            entity_id=department.id,
            details=f"Administrator {status} department {department.name}."
        )

        db.session.add(audit)
        db.session.commit()

        flash(
            f"Department successfully {status}.",
            "success"
        )

    except SQLAlchemyError:

        db.session.rollback()

        flash(
            "An error occurred while updating the department.",
            "danger"
        )

    return redirect(url_for("main.manage_departments"))

# ==========================================================
# QR CODE GENERATION AND CERTIFICATE VERIFICATION
# ==========================================================

def get_verification_serializer():

    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="uniclear-certificate-verification"
    )


# ----------------------------------------------------------
# GENERATE QR CODE
# ----------------------------------------------------------

@main_bp.route("/clearance/<int:request_id>/qr")
@login_required
def generate_clearance_qr(request_id):

    # Only students can access their QR codes.
    if current_user.role != "student":
        abort(403)

    clearance_request = ClearanceRequest.query.filter_by(
        id=request_id,
        student_id=current_user.id
    ).first_or_404()

    # QR codes are available only after complete approval.
    if clearance_request.status != "approved":

        flash(
            "Your QR certificate will be available after all departments approve your clearance.",
            "warning"
        )

        return redirect(
            url_for(
                "main.clearance_details",
                request_id=clearance_request.id
            )
        )

    # Generate a secure signed token.
    token = get_verification_serializer().dumps({
        "request_id": clearance_request.id,
        "purpose": "certificate_verification"
    })

    verification_url = url_for(
        "main.verify_certificate",
        token=token,
        _external=True
    )

    # Generate QR image.
    qr = qrcode.make(verification_url)

    image_buffer = BytesIO()
    qr.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    return send_file(
        image_buffer,
        mimetype="image/png",
        download_name=f"UniClear_UC-{clearance_request.id:06d}.png"
    )


# ----------------------------------------------------------
# VERIFY CERTIFICATE
# ----------------------------------------------------------

@main_bp.route("/verify/<token>")
@login_required
def verify_certificate(token):

    # Only university verifiers can verify certificates.
    if current_user.role != "verifier":
        abort(403)

    try:

        data = get_verification_serializer().loads(token)

        request_id = data.get("request_id")

        if data.get("purpose") != "certificate_verification":
            abort(400)

        clearance_request = ClearanceRequest.query.get(
            request_id
        )

        if not clearance_request:
            return render_template(
                "verification_result.html",
                valid=False,
                clearance_request=None
            )

        # Check actual departmental approval records.
        all_items = clearance_request.items

        fully_approved = (
            len(all_items) > 0
            and all(
                item.status == "approved"
                for item in all_items
            )
        )

        valid = (
            clearance_request.status == "approved"
            and fully_approved
        )

        return render_template(
            "verification_result.html",
            valid=valid,
            clearance_request=clearance_request
        )

    except BadSignature:

        return render_template(
            "verification_result.html",
            valid=False,
            clearance_request=None
        )

# Verify a student's QR-code certificate using its signed token.
@main_bp.route("/verify-certificate", methods=["POST"])
@login_required
def submit_verification_link():

    if current_user.role != "verifier":
        abort(403)

    verification_url = request.form.get(
        "verification_url", ""
    ).strip()

    if not verification_url:
        flash("Please enter a verification URL.", "warning")
        return redirect(url_for("main.dashboard"))

    parsed_url = urlsplit(verification_url)

    path_parts = parsed_url.path.strip("/").split("/")

    if len(path_parts) != 2 or path_parts[0] != "verify":
        flash("Invalid certificate verification URL.", "danger")
        return redirect(url_for("main.dashboard"))

    token = path_parts[1]

    return redirect(
        url_for("main.verify_certificate", token=token)
    )

# ==========================================================
# ADMIN: REGISTER CERTIFICATE VERIFIER
# ==========================================================

@main_bp.route("/admin/verifiers/add", methods=["GET", "POST"])
@login_required
def add_verifier():

    # Only administrators can create verifier accounts.
    if current_user.role != "admin":
        abort(403)

    if request.method == "POST":

        full_name = request.form.get(
            "full_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        # Validate required fields.
        if not all([full_name, email, password]):

            flash(
                "Please complete all fields.",
                "danger"
            )

            return redirect(url_for("main.add_verifier"))

        if len(password) < 8:

            flash(
                "Password must contain at least 8 characters.",
                "danger"
            )

            return redirect(url_for("main.add_verifier"))

        # Check whether the email already exists.
        if User.query.filter_by(email=email).first():

            flash(
                "An account with that email already exists.",
                "danger"
            )

            return redirect(url_for("main.add_verifier"))

        try:

            # Create verifier account.
            verifier = User(
                full_name=full_name,
                email=email,
                password_hash=generate_password_hash(password),
                role="verifier"
            )

            db.session.add(verifier)
            db.session.flush()

            # Record the action.
            audit = AuditLog(
                user_id=current_user.id,
                action="Created certificate verifier",
                entity_type="User",
                entity_id=verifier.id,
                details=f"Created verifier account for {full_name}."
            )

            db.session.add(audit)
            db.session.commit()

            flash(
                f"Verifier account for {full_name} created successfully.",
                "success"
            )

            return redirect(url_for("main.dashboard"))

        except SQLAlchemyError:

            db.session.rollback()

            flash(
                "An error occurred while creating the verifier account.",
                "danger"
            )

    return render_template("admin/add_verifier.html")

# ==========================================================
# ADMIN: STUDENT MANAGEMENT
# ==========================================================

@main_bp.route("/admin/students")
@login_required
def manage_students():

    print("\n========== STUDENT MANAGEMENT DEBUG ==========")
    print("User ID:", current_user.id)
    print("User Name:", current_user.full_name)
    print("User Role:", repr(current_user.role))
    print("Authenticated:", current_user.is_authenticated)
    print("==============================================\n")

    # Only administrators can manage student accounts.
    if current_user.role != "admin":
        abort(403)

    # Get the search term.
    search = request.args.get("search", "").strip()

    # Retrieve student accounts.
    students_query = User.query.filter_by(role="student")

    # Apply search filter.
    if search:
        students_query = students_query.filter(
            db.or_(
                User.full_name.ilike(f"%{search}%"),
                User.registration_number.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
        )

    # Order students alphabetically.
    students = (
        students_query
        .order_by(User.full_name.asc())
        .all()
    )

    # Calculate student statistics.
    total_students = User.query.filter_by(
        role="student"
    ).count()

    active_students = User.query.filter_by(
        role="student",
        is_active=True
    ).count()

    inactive_students = User.query.filter_by(
        role="student",
        is_active=False
    ).count()

    return render_template(
        "admin/students.html",
        students=students,
        search=search,
        total_students=total_students,
        active_students=active_students,
        inactive_students=inactive_students
    )


# ==========================================================
# ADMIN: ACTIVATE / DEACTIVATE STUDENT ACCOUNTS
# ==========================================================

@main_bp.route(
    "/admin/students/<int:student_id>/toggle-status",
    methods=["POST"]
)
@login_required
def toggle_student_status(student_id):

    # Only administrators can manage student accounts.
    if current_user.role != "admin":
        abort(403)

    # Retrieve the student.
    student = User.query.filter_by(
        id=student_id,
        role="student"
    ).first_or_404()

    try:

        # Change student account status.
        student.is_active = not student.is_active

        status = (
            "activated"
            if student.is_active
            else "deactivated"
        )

        # Record the action.
        audit = AuditLog(
            user_id=current_user.id,
            action=f"Student account {status}",
            entity_type="User",
            entity_id=student.id,
            details=(
                f"Administrator {current_user.full_name} "
                f"{status} the student account belonging to "
                f"{student.full_name} "
                f"({student.registration_number or 'No registration number'})."
            )
        )

        db.session.add(audit)
        db.session.commit()

        flash(
            f"Student account for {student.full_name} "
            f"successfully {status}.",
            "success"
        )

    except SQLAlchemyError:

        db.session.rollback()

        flash(
            "An error occurred while updating the student account.",
            "danger"
        )

    return redirect(url_for("main.manage_students"))

@main_bp.route("/admin/verifiers")
@login_required
def manage_verifiers():

    if current_user.role != "admin":
        abort(403)

    search = request.args.get("search", "").strip()

    verifiers_query = User.query.filter_by(role="verifier")

    # Search by verifier name or email
    if search:
        verifiers_query = verifiers_query.filter(
            db.or_(
                User.full_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
        )

    verifiers = (
        verifiers_query
        .order_by(User.full_name.asc())
        .all()
    )

    # Verifier statistics
    total_verifiers = User.query.filter_by(
        role="verifier"
    ).count()

    active_verifiers = User.query.filter_by(
        role="verifier",
        is_active=True
    ).count()

    inactive_verifiers = User.query.filter_by(
        role="verifier",
        is_active=False
    ).count()

    return render_template(
        "admin/verifiers.html",
        verifiers=verifiers,
        search=search,
        total_verifiers=total_verifiers,
        active_verifiers=active_verifiers,
        inactive_verifiers=inactive_verifiers
    )