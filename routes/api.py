from flask import Blueprint, jsonify, request

from extensions import limiter
from extensions import supabase

import secrets
from datetime import datetime, timedelta

from services.cpa_service import check_cpa_eligibility
from services.auth_service import set_auth_token

from services.receipt_service import (
    extract_products_from_receipt,
    extract_products_from_image
)

from services.warranty_service import (
    match_products_to_warranties
)

from services.email_service import send_email

from services.cpa_letter_service import (
    generate_cpa_letter
)

api_bp = Blueprint("api", __name__)

@api_bp.route("/api/search")
@limiter.limit("30 per minute")
def search():

    query = request.args.get("q", "").strip()

    if len(query) < 2:

        return jsonify({

            "match": False,

            "message": "Enter at least 2 characters."

        })

    response = (

        supabase.table("warranties")

        .select("*")

        .or_(f"brand.ilike.%{query}%,model_pattern.ilike.%{query}%")

        .limit(10)

        .execute()

    )

    matches = response.data

    if not matches:

        return jsonify({

            "match": False,

            "message":
            "No warranties found."

        })

    results = []

    seen = set()

    for m in matches:

        key = (

            m["brand"],
            m["part_covered"],
            m["duration_years"]

        )

        if key in seen:

            continue

        seen.add(key)

        results.append({

            "id": m["id"],

            "brand": m["brand"],

            "part_covered": m["part_covered"],

            "duration":
            f"{m['duration_years']} years",

            "type":
            m["warranty_type"],

            "region":
            m.get("region", "global")

        })

    return jsonify({

        "match": True,

        "count": len(results),

        "results": results

    })

@api_bp.route("/api/check-cpa", methods=["POST"])
def check_cpa():

    data = request.json

    purchase_date = data.get(

        "purchase_date",

        ""

    )

    result = check_cpa_eligibility(

        purchase_date

    )

    if "error" in result:

        return jsonify(result), 400

    return jsonify(result)

@api_bp.route("/api/scan-receipt", methods=["POST"])
def scan_receipt():

    data = request.json

    receipt_text = data.get(

        "receipt_text",

        ""

    ).strip()

    user_email = data.get(

        "email",

        ""

    ).strip()

    if len(receipt_text) < 20:

        return jsonify({

            "error":
            "Receipt text too short."

        }), 400

    if not user_email:

        return jsonify({

            "error":
            "Email required."

        }), 400

    extracted = extract_products_from_receipt(

        receipt_text

    )

    matches = match_products_to_warranties(

        extracted

    )

    payload = {

        "success": True,

        "products_found":
        len(extracted.get("products", [])),

        "warranty_matches":
        len(matches),

        "total_spent":
        extracted.get("total_spent", 0),

        "products":
        extracted.get("products", []),

        "matches": matches

    }

    resp = jsonify(payload)

    resp = set_auth_token(

        user_email,

        resp

    )

    return resp

@api_bp.route(
    "/api/scan-receipt-image",
    methods=["POST"]
)
@limiter.limit("10 per hour")
def scan_receipt_image():

    data = request.json

    image_base64 = data.get(

        "image_base64",

        ""

    )

    email = data.get(

        "email",

        ""

    )

    if not image_base64:

        return jsonify({

            "error":
            "No image supplied."

        }), 400

    extracted = extract_products_from_image(

        image_base64

    )

    matches = match_products_to_warranties(

        extracted

    )

    payload = {

        "success": True,

        "products_found":
        len(extracted.get("products", [])),

        "matches":
        matches

    }

    resp = jsonify(payload)

    resp = set_auth_token(

        email,

        resp

    )

    return resp

@api_bp.route("/api/scan-structured", methods=["POST"])
def scan_structured():

    data = request.json

    user_email = data.get("email", "").strip()
    retailer = data.get("retailer", "")
    purchase_date = data.get("purchase_date", "")
    products = data.get("products", [])

    if not user_email:
        return jsonify({
            "error": "Email is required."
        }), 400

    if not products:
        return jsonify({
            "error": "No products provided."
        }), 400

    # Create user if not already present
    existing = (
        supabase.table("users")
        .select("*")
        .eq("email", user_email)
        .execute()
    )

    if not existing.data:
        supabase.table("users").insert({
            "email": user_email
        }).execute()

    all_products = []
    all_matches = []

    for p in products:

        brand = p.get("name", "")
        model = p.get("model", "")
        price = p.get("price", 0)

        product_data = {
            "brand": brand,
            "model": model,
            "category": "other",
            "purchase_date": purchase_date,
            "purchase_price": price,
            "retailer": retailer
        }

        all_products.append(product_data)

        # Warranty search
        if brand:

            response = (
                supabase.table("warranties")
                .select("*")
                .ilike("brand", f"%{brand}%")
                .limit(3)
                .execute()
            )

            for warranty in response.data:

                all_matches.append({

                    "product": {

                        "brand": brand,
                        "model": model

                    },

                    "warranty": {

                        "id": warranty["id"],
                        "brand": warranty["brand"],
                        "part_covered": warranty["part_covered"],
                        "duration": f"{warranty['duration_years']} years",
                        "type": warranty["warranty_type"],
                        "region": warranty.get("region", "global")

                    }

                })

    # Remove duplicates
    unique_matches = []
    seen = set()

    for match in all_matches:

        key = (
            match["product"]["model"],
            match["warranty"]["id"]
        )

        if key in seen:
            continue

        seen.add(key)
        unique_matches.append(match)

    payload = {

        "success": True,

        "products_found": len(all_products),

        "warranty_matches": len(unique_matches),

        "products": all_products,

        "matches": unique_matches

    }

    resp = jsonify(payload)

    resp = set_auth_token(
        user_email,
        resp
    )

    return resp

@api_bp.route("/api/login", methods=["POST"])
def login():

    email = request.json.get(
        "email",
        ""
    )

    token = secrets.token_urlsafe(32)

    expires = (
        datetime.now()
        + timedelta(hours=1)
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    supabase.table(
        "login_tokens"
    ).insert({

        "email": email,

        "token": token,

        "expires": expires,

        "used": False

    }).execute()

    login_url = (
        f"http://127.0.0.1:5000/"
        f"verify-login/{token}"
    )

    body = f"""
Hi there,

Click this link to login:

{login_url}

This expires in one hour.

ClaimFlux SA
"""

    send_email(
        email,
        "Your ClaimFlux Login Link",
        body
    )

    return jsonify({

        "success": True,

        "message":
        "Check your email."

    })

@api_bp.route(
    "/api/generate-letter",
    methods=["POST"]
)
def generate_letter():

    data = request.json

    user_data = {

        "name": data.get("name", "")

    }

    product_data = {

        "product_name":
        data.get("product_name", ""),

        "issue_description":
        data.get(
            "issue_description",
            ""
        ),

        "desired_outcome":
        data.get(
            "desired_outcome",
            "repair"
        )
    }

    retailer_data = {

        "retailer_name":
        data.get(
            "retailer",
            ""
        )

    }

    letter = generate_cpa_letter(

        user_data,

        product_data,

        retailer_data

    )

    return jsonify({

        "letter": letter

    })

@api_bp.route("/api/start-claim", methods=["POST"])
def start_claim():

    data = request.json

    email = data.get("email")

    issue = data.get(

        "issue_description",

        "Defective product"

    )

    claim = supabase.table(

        "claims"

    ).insert({

        "user_email": email,

        "status": "initiated",

        "claim_amount": 0,

        "issue_description": issue

    }).execute()

    return jsonify({

        "success": True,

        "claim_id":

        claim.data[0]["id"],

        "message":

        "Claim started successfully."

    })

@api_bp.route("/api/my-claims")
def my_claims():

    email = request.args.get("email")

    if not email:
        return jsonify({
            "claims": [],
            "count": 0,
            "active_claims": 0,
            "total_recovered": 0,
            "urgent_count": 0,
            "cpa_alerts": []
        })

    claims_response = (
        supabase.table("claims")
        .select("*")
        .eq("user_email", email)
        .execute()
    )

    claims = claims_response.data

    total_recovered = sum(
        claim.get("user_payout", 0) or 0
        for claim in claims
        if claim.get("status") == "paid"
    )

    active_claims = len([
        claim for claim in claims
        if claim.get("status") in ["initiated", "pending"]
    ])

    urgent_count = 0

    return jsonify({
        "claims": claims,
        "count": len(claims),
        "active_claims": active_claims,
        "total_recovered": total_recovered,
        "urgent_count": urgent_count,
        "cpa_alerts": []
    })
