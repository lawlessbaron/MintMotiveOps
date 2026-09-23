import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from ..db import get_db, now_str
from .. import email_client

bp = Blueprint("auth", __name__)

RESET_CODE_TTL_MINUTES = 15
RESET_CODE_MAX_ATTEMPTS = 5


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html")
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_role"] = user["role"]
        session["can_view_analytics"] = bool(user["can_view_analytics"])
        next_url = request.args.get("next") or url_for("dashboard.index")
        return redirect(next_url)
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
        if user is not None:
            # Only the newest code should ever be valid for a given user.
            db.execute(
                "UPDATE password_reset_tokens SET used=1 WHERE user_id=? AND used=0", (user["id"],)
            )
            code = f"{secrets.randbelow(1_000_000):06d}"
            expires_at = (datetime.utcnow() + timedelta(minutes=RESET_CODE_TTL_MINUTES)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            db.execute(
                "INSERT INTO password_reset_tokens (user_id, code_hash, expires_at) VALUES (?,?,?)",
                (user["id"], generate_password_hash(code), expires_at),
            )
            db.commit()
            sent = email_client.send_email(
                user["email"],
                "Your MintMotive Ops password reset code",
                f"Hi {user['name']},\n\n"
                f"Your password reset code is: {code}\n\n"
                f"This code expires in {RESET_CODE_TTL_MINUTES} minutes and can only be used once. "
                f"If you didn't request this, you can safely ignore this email — your password hasn't "
                f"been changed.\n\nMintMotive Ops",
            )
            if not sent:
                current_app.logger.warning(
                    f"SMTP not configured — a password reset code was generated for {user['email']} but "
                    f"NOT emailed. Set SMTP_HOST/SMTP_USER/SMTP_PASSWORD to enable real delivery."
                )
        # Identical response whether or not the account exists — otherwise
        # this endpoint would let anyone enumerate registered email addresses.
        flash(
            f"If that email is registered, a 6-digit code has been sent to it — enter it below "
            f"(expires in {RESET_CODE_TTL_MINUTES} minutes).",
            "success",
        )
        return redirect(url_for("auth.reset_password", email=email))
    return render_template("auth/forgot_password.html")


@bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        code = request.form.get("code", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        generic_error = "That code is invalid, expired, or already used — request a new one below."

        if len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
            return render_template("auth/reset_password.html", email=email)
        if new_password != confirm_password:
            flash("Passwords don't match.", "error")
            return render_template("auth/reset_password.html", email=email)

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
        if user is None:
            flash(generic_error, "error")
            return render_template("auth/reset_password.html", email=email)

        token = db.execute(
            "SELECT * FROM password_reset_tokens WHERE user_id=? AND used=0 ORDER BY id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        if token is None or token["expires_at"] < now_str() or token["attempts"] >= RESET_CODE_MAX_ATTEMPTS:
            flash(generic_error, "error")
            return render_template("auth/reset_password.html", email=email)
        if not check_password_hash(token["code_hash"], code):
            db.execute(
                "UPDATE password_reset_tokens SET attempts=attempts+1 WHERE id=?", (token["id"],)
            )
            db.commit()
            flash(generic_error, "error")
            return render_template("auth/reset_password.html", email=email)

        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_password), user["id"])
        )
        db.execute("UPDATE password_reset_tokens SET used=1 WHERE id=?", (token["id"],))
        db.commit()
        flash("Password reset — log in with your new password.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", email=request.args.get("email", ""))
