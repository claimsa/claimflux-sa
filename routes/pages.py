from flask import Blueprint, render_template, redirect

from extensions import supabase

from services.auth_service import set_auth_token


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

        supabase.table("login_tokens")\
            .update({"used": True})\
            .eq("token", token)\
            .execute()

        resp = redirect("/dashboard")

        resp = set_auth_token(

            email,

            resp

        )

        return resp

    return "Invalid or expired link", 401
