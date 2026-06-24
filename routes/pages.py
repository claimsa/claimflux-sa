from flask import Blueprint, render_template, redirect

from extensions import supabase
from services.auth_service import set_auth_token

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
def home():
    return render_template("index.html")


@pages_bp.route("/scan")
def scan():
    return render_template("scan.html")


@pages_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@pages_bp.route("/verify-login/<token>")
def verify_login(token):

    response = (
        supabase.table("login_tokens")
        .select("*")
        .eq("token", token)
        .eq("used", False)
        .execute()
    )

    if response.data:

        email = response.data[0]["email"]

        (
            supabase.table("login_tokens")
            .update({"used": True})
            .eq("token", token)
            .execute()
        )

        resp = redirect(
            f"/dashboard?email={email}"
        )

        resp = set_auth_token(
            email,
            resp
        )

        return resp

    return "Invalid or expired link", 401
