import secrets
from datetime import datetime, timedelta
from flask import request

from extensions import supabase


def set_auth_token(email, response):
    token = secrets.token_urlsafe(32)

    expiry = (
        datetime.now() + timedelta(days=30)
    ).strftime("%Y-%m-%d %H:%M:%S")

    supabase.table("auth_tokens").insert({
        "email": email,
        "token": token,
        "expires": expiry
    }).execute()

    response.set_cookie(
        "auth_token",
        token,
        max_age=30*24*60*60,
        httponly=True,
        secure=True,
        samesite="Lax"
    )

    return response


def get_user_from_token():
    token = request.cookies.get("auth_token")

    if not token:
        return None

    response = (
        supabase.table("auth_tokens")
        .select("*")
        .eq("token", token)
        .execute()
    )

    if response.data:
        return response.data[0]["email"]

    return None
