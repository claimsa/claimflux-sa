from dotenv import load_dotenv

load_dotenv()

from flask import Flask, render_template, request, jsonify, session, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client
import openai
import os
import secrets
import json
import base64
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(16))
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per hour"],
    storage_uri="memory://"
)
def set_auth_token(email, response):
    """Set auth token as cookie"""
    token = secrets.token_urlsafe(32)
    supabase.table('auth_tokens').insert({
        'email': email,
        'token': token,
        'expires': 'NOW() + INTERVAL \'30 days\''
    }).execute()
    response.set_cookie('auth_token', token, max_age=30*24*60*60, httponly=True, samesite='Lax')
    return response

def get_user_from_token():
    """Get user email from auth token cookie"""
    token = request.cookies.get('auth_token')
    if not token:
        return None
    result = supabase.table('auth_tokens').select('*').eq('token', token).gte('expires', 'NOW()').execute()
    if result.data:
        return result.data[0]['email']
    return None
# ============ RECEIPT SCANNER (Hybrid: Rules + AI fallback) ============

def extract_products_rules(receipt_text):
    """Free rule-based extraction — always works, no API needed"""

    import re
    from datetime import datetime

    brands = [
        'Samsung', 'LG', 'Defy', 'Hisense', 'KIC', 'Bosch', 'Siemens',
        'Miele', 'Whirlpool', 'GE', 'Russell Hobbs', 'Salton', 'Apple',
        'Sony', 'Xiaomi', 'Huawei', 'Voltas', 'Sunbeam', 'Philips',
        'Tedelex', 'Kelvinator', 'AEG', 'Smeg', 'Hoover', 'Electrolux'
    ]

    retailers = ['Takealot', 'Makro', 'Game', 'Checkers', 'Woolworths',
                 'Builders', "Hirsch's", 'Dion Wired', 'Pick n Pay', 'Spar']

    products = []
    lines = receipt_text.split('\\n')

    for line in lines:
        line = line.strip()
        if not line or len(line) < 10:
            continue

        found_brand = None
        for brand in brands:
            if brand.lower() in line.lower():
                found_brand = brand
                break

        if not found_brand:
            continue

        model_match = re.search(r'([A-Z]{2,4}[-\\s]?\\d{2,4}[A-Za-z0-9]*)', line)
        model = model_match.group(1) if model_match else line.split(found_brand)[-1].strip()[:50]

        price_match = re.search(r'R\s?(\d[\d\s,]*\.?\d{0,2})', line)
        if not price_match:
            price_match = re.search(r'[--]\s*R?\s*(\d[\d\s,]*\.?\d{0,2})', line)
        if not price_match:
            price_match = re.search(r'(\d[\d,]*\.\d{2})', line)
        price = float(price_match.group(1).replace(',', '').replace(' ', '').replace('R', '')) if price_match else None

        line_lower = line.lower()
        if any(w in line_lower for w in ['fridge', 'refrigerator']):
            category = 'fridge'
        elif any(w in line_lower for w in ['washer', 'washing']):
            category = 'washer'
        elif any(w in line_lower for w in ['dryer', 'tumble']):
            category = 'dryer'
        elif any(w in line_lower for w in ['dishwasher']):
            category = 'dishwasher'
        elif any(w in line_lower for w in ['tv', 'television']):
            category = 'tv'
        elif any(w in line_lower for w in ['microwave']):
            category = 'microwave'
        elif any(w in line_lower for w in ['kettle']):
            category = 'kettle'
        elif any(w in line_lower for w in ['stove', 'oven', 'hob']):
            category = 'stove'
        elif any(w in line_lower for w in ['phone', 'smartphone']):
            category = 'phone'
        elif any(w in line_lower for w in ['laptop', 'notebook']):
            category = 'laptop'
        else:
            category = 'other'

        date_match = re.search(r'(\\d{1,2}[-\\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-\\s]\\d{4})', line, re.IGNORECASE)
        if not date_match:
            date_match = re.search(r'(\\d{4}[-/]\\d{2}[-/]\\d{2})', line)
        if not date_match:
            date_match = re.search(r'(\\d{2}[-/]\\d{2}[-/]\\d{4})', line)

        purchase_date = None
        if date_match:
            try:
                date_str = date_match.group(1)
                for fmt in ['%d %B %Y', '%d %b %Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y']:
                    try:
                        purchase_date = datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
                        break
                    except ValueError:
                        continue
            except:
                pass

        found_retailer = None
        for retailer in retailers:
            if retailer.lower() in receipt_text.lower():
                found_retailer = retailer
                break

        products.append({
            'brand': found_brand,
            'model': model[:100] if model else '',
            'category': category,
            'purchase_date': purchase_date or 'Unknown',
            'purchase_price': price,
            'retailer': found_retailer or 'Unknown'
        })

    total = sum(p['purchase_price'] for p in products if p['purchase_price'])
    return {"products": products[:10], "total_spent": round(total, 2)}

def extract_products_ai(receipt_text):
    """AI-powered extraction — uses OpenAI when credits available"""

    import json

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": """You are a South African receipt extraction system. Extract ALL products from the receipt.

Return ONLY valid JSON with this structure:
{
    "products": [
      {
        "brand": "Samsung",
        "model": "RF23M8070SG",
        "category": "fridge",
        "purchase_date": "2026-03-15",
        "purchase_price": 12999.00,
        "retailer": "Takealot"
      }
    ],
    "total_spent": 12999.00
}
If no products found, return {"products": [], "total_spent": 0}."""
            },
            {
                "role": "user",
                "content": f"Extract all products from this SA receipt:\n\n{receipt_text[:4000]}"
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.1
    )

    return json.loads(response.choices[0].message.content)

def extract_products_from_receipt(receipt_text):
    """Hybrid extractor: tries AI first, falls back to rules"""

    # Try AI first
    try:
        return extract_products_ai(receipt_text)
    except Exception:
        pass  # Fall back to rules

    # Fall back to free rule-based extraction
    return extract_products_rules(receipt_text)

def match_products_to_warranties(extracted_data):
    """Take extracted products and find matching warranties"""
    
    matches = []
    seen_pairs = set()
    
    for product in extracted_data.get('products', []):
        brand = product.get('brand', '')
        model = product.get('model', '')
        
        if brand:
            response = supabase.table('warranties') \
                .select('*') \
                .ilike('brand', f'%{brand}%') \
                .limit(5) \
                .execute()
            
            for warranty in response.data:
                pair_key = (product.get('model', ''), warranty['id'])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                matches.append({
                    "product": product,
                    "warranty": {
                        "id": warranty['id'],
                        "brand": warranty['brand'],
                        "part_covered": warranty['part_covered'],
                        "duration_years": warranty['duration_years'],
                        "type": warranty['warranty_type'],
                        "region": warranty.get('region', 'global')
                    }
                })
    
    return matches

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE"))
openai.api_key = os.getenv("OPENAI_API_KEY")

# ============ CPA LETTER GENERATOR ============

def check_cpa_deadlines(user_email):
    """Check all user's CPA claims and return urgency alerts"""
    
    cpa_claims = supabase.table('cpa_claims') \
        .select('*') \
        .eq('user_email', user_email) \
        .eq('status', 'initiated') \
        .execute()
    
    alerts = []
    today = datetime.now()
    
    for claim in cpa_claims.data:
        if not claim.get('cpa_deadline'):
            continue
        
        try:
            deadline = datetime.strptime(claim['cpa_deadline'], '%Y-%m-%d')
            days_left = (deadline - today).days
            
            if days_left <= 0:
                urgency = 'expired'
                message = f"CPA deadline PASSED for {claim['product_name']}"
            elif days_left <= 14:
                urgency = 'critical'
                message = f"ONLY {days_left} DAYS LEFT - {claim['product_name']}"
            elif days_left <= 30:
                urgency = 'warning'
                message = f"{days_left} days left - {claim['product_name']}"
            else:
                urgency = 'ok'
                message = f"{days_left} days remaining - {claim['product_name']}"
            
            alerts.append({
                'claim_id': claim['id'],
                'product_name': claim['product_name'],
                'retailer': claim.get('retailer', ''),
                'deadline': claim['cpa_deadline'],
                'days_left': days_left,
                'urgency': urgency,
                'message': message
            })
        except ValueError:
            continue
    
    # Sort: most urgent first
    alerts.sort(key=lambda x: x['days_left'])
    
    return alerts

def send_email(to_email, subject, body):
    """Send email via Gmail SMTP"""

    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        print("Gmail credentials not set. Skipping email.")
        return False

    msg = MIMEMultipart()
    msg['From'] = f"ClaimFlux SA <{gmail_user}>"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        print(f"Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False

def generate_cpa_letter(user_data, product_data, retailer_data):
    """Generate a formal CPA Section 56 claim letter"""


    ref = f"CLAIMFLUX-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"

    letter = f"""

{user_data.get('name', '[Your Full Name]')}
{user_data.get('address', '[Your Address]')}
{user_data.get('phone', '[Your Phone Number]')}
{user_data.get('email', '[Your Email]')}

Date: {datetime.now().strftime('%d %B %Y')}

To: {retailer_data.get('retailer_name', '[Retailer Name]')}
Email: {retailer_data.get('customer_service_email', '[Retailer Email]')}
Phone: {retailer_data.get('customer_service_phone', '[Retailer Phone]')}

RE: FORMAL CLAIM UNDER SECTION 56 OF THE CONSUMER PROTECTION ACT 68 OF 2008

Product: {product_data.get('product_name', '[Product]')}
Date of Purchase: {product_data.get('purchase_date', '[Purchase Date]')}

Dear Sir/Madam,

I am writing to lodge a formal claim under Section 56 of the Consumer Protection Act 68 of 2008 ("the CPA").

On {product_data.get('purchase_date', '[purchase date]')}, I purchased a {product_data.get('product_name', '[product]')} from {retailer_data.get('retailer_name', '[retailer]')}. The product has developed the following issue:

"{product_data.get('issue_description', '[Describe the defect]')}"

MY RIGHTS UNDER THE CPA:

Section 56(2) of the CPA states that within six months of delivery, I am entitled to choose whether you must:
(a) Repair the goods;
(b) Replace the goods; or
(c) Refund the full purchase price.

My preferred remedy is: {product_data.get('desired_outcome', 'Repair')}

YOUR OBLIGATIONS:

1. Section 56(3)(a) states the SUPPLIER must take the remedial action at my direction.
2. You CANNOT refer me to the manufacturer - liability rests with you as the supplier.
3. You bear the cost of collecting or transporting defective goods if needed.

Should you fail to comply, I will escalate to:

- The National Consumer Commission (NCC): 012 428 7000 / [complaints@thencc.gov.za](mailto:complaints@thencc.gov.za)
- The Consumer Goods and Services Ombud (CGSO): 0860 000 272 / [info@cgso.org.za](mailto:info@cgso.org.za)

I await your response within 14 days.

Yours faithfully,

{user_data.get('name', '[Your Name]')}

---

Reference: {ref}
"""
    return letter

# ============ PAGES ============


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/scan")
def scan():
    return render_template("scan.html")

@app.route("/dashboard")
def dashboard():
    email = requests.args.get("email")
    if not email:
        return redirect("/")
    return render_template("dashboard.html", user_email_=email)


@app.route("/verify-login/<token>")
def verify_login(token):
    response = (
        supabase.table("login_tokens")
        .select("*")
        .eq("token", token)
        .eq("used", False)
        .gte("expires", "NOW()")
        .execute()
    )

    if response.data:
        email = response.data[0]["email"]
        supabase.table("login_tokens").update({"used": True}).eq(
            "token", token
        ).execute()
        resp = redirect("/dashboard")
        resp = set_auth_token(email,resp)
        return resp

    return "Invalid or expired link", 401


# ============ API ENDPOINTS ============

@limiter.limit("30 per minute")
@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return jsonify({"match": False, "message": "Enter at least 2 characters."})

    response = (
        supabase.table("warranties")
        .select("*")
        .or_(f"brand.ilike.%{query}%,model_pattern.ilike.%{query}%")
        .limit(10)
        .execute()
    )

    matches = response.data

    if not matches:
        return jsonify(
            {
                "match": False,
                "message": "No warranties found. Try including the brand (e.g. 'Samsung fridge').",
            }
        )

    results = []
    seen = set()
    for m in matches:
        key = (m['brand'], m['part_covered'], m['duration_years'])
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "id": m["id"],
                "brand": m["brand"],
                "part_covered": m["part_covered"],
                "duration": f"{m['duration_years']} years",
                "type": m["warranty_type"],
                "region": m.get("region", "global"),
            }
        )

    return jsonify({"match": True, "count": len(results), "results": results})

@app.route("/api/check-cpa", methods=["POST"])
def check_cpa():
    data = request.json
    purchase_date = data.get('purchase_date', '')
    
    try:
        purchase_date_obj = datetime.strptime(purchase_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({"error": "Use YYYY-MM-DD format"}), 400
    
    cpa_deadline = purchase_date_obj + timedelta(days=182)
    today = datetime.now()
    days_remaining = (cpa_deadline - today).days
    
    if days_remaining < 0:
        return jsonify({
            "cpa_eligible": False,
            "message": f"CPA warranty expired on {cpa_deadline.strftime('%d %B %Y')}.",
            "days_expired": abs(days_remaining)
        })
    
    urgency = "HIGH" if days_remaining < 30 else "MEDIUM" if days_remaining < 90 else "LOW"
    
    return jsonify({
        "cpa_eligible": True,
        "days_remaining": days_remaining,
        "deadline": cpa_deadline.strftime('%d %B %Y'),
        "urgency": urgency,
        "rights": ["Full refund", "Free replacement", "Free repair at supplier's cost"],
        "next_step": "We can generate a formal CPA claim letter for you."
    })

@limiter.limit("10 per hour")
@app.route('/api/scan-receipt-image', methods=['POST'])
def scan_receipt_image():
    """Upload receipt image and extract products using GPT-4o Vision"""
    
    data = request.json
    image_base64 = data.get('image_base64', '')
    user_email = data.get('email', '').strip()
    
    if not image_base64:
        return jsonify({"error": "No image provided."}), 400
    if not user_email:
        return jsonify({"error": "Email is required."}), 400
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Extract all products from this SA receipt image. Return ONLY JSON: {\"products\": [{\"brand\": \"\", \"model\": \"\", \"category\": \"\", \"purchase_date\": \"YYYY-MM-DD\", \"purchase_price\": 0.00, \"retailer\": \"\"}], \"total_spent\": 0.00}"
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all products from this receipt."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            max_tokens=1000
        )
        
        extracted = json.loads(response.choices[0].message.content)
        
    except Exception as e:
        return jsonify({"error": f"Failed to analyze image: {str(e)}"}), 500
    
    if not extracted.get('products'):
        return jsonify({"success": True, "products_found": 0, "message": "No products detected."})
    
    matches = match_products_to_warranties(extracted)
    
    existing = supabase.table('users').select('*').eq('email', user_email).execute()
    if not existing.data:
        supabase.table('users').insert({'email': user_email}).execute()
    
    resp = jsonify({
        "success": True,
        "products_found": len(extracted.get('products', [])),
        "warranty_matches": len(matches),
        "total_spent": extracted.get('total_spent', 0),
        "products": extracted.get('products', []),
        "matches": [{"product": m['product'], "warranty": {"part_covered": m['warranty']['part_covered'], "duration": f"{m['warranty']['duration_years']} years", "type": m['warranty']['type']}} for m in matches]
    })
    resp = set_auth_token(user_email, resp)
    return resp

@app.route('/api/scan-receipt', methods=['POST'])
def scan_receipt():
    """Upload receipt text or image description and get warranty matches"""
    data = request.json
    receipt_text = data.get('receipt_text', '').strip()
    user_email = data.get('email', '').strip()

    if len(receipt_text) < 20:
        return jsonify({"error": "Receipt text too short. Paste the full receipt content."}), 400

    if not user_email:
        return jsonify({"error": "Email is required to save your results."}), 400

    # Extract products using GPT-4o
    try:
        extracted = extract_products_from_receipt(receipt_text)
    except Exception as e:
        return jsonify({"error": f"Failed to parse receipt: {str(e)}"}), 500

    if not extracted.get('products'):
        return jsonify({
            "success": True,
            "products_found": 0,
            "message": "No products detected in the receipt. Try pasting the full receipt text including product names and prices."
        })

    # Match against warranties
    matches = match_products_to_warranties(extracted)

    # Save user and discoveries
    existing = supabase.table('users').select('*').eq('email', user_email).execute()
    if not existing.data:
        supabase.table('users').insert({'email': user_email}).execute()

    return jsonify({
        "success": True,
        "products_found": len(extracted.get('products', [])),
        "warranty_matches": len(matches),
        "total_spent": extracted.get('total_spent', 0),
        "products": extracted.get('products', []),
        "matches": [
            {
                "product": m['product'],
                "warranty": {
                    "part_covered": m['warranty']['part_covered'],
                    "duration": f"{m['warranty']['duration_years']} years",
                    "type": m['warranty']['type']
                }
            } for m in matches
        ]
    })
    resp = set_auth_token(user_email, resp)
    return resp
def check_cpa():
    data = request.json
    purchase_date = data.get("purchase_date", "")

    try:
        purchase_date_obj = datetime.strptime(purchase_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Use YYYY-MM-DD format"}), 400

    cpa_deadline = purchase_date_obj + timedelta(days=18)
    today = datetime.now()
    days_remaining = (cpa_deadline - today).days

    if days_remaining < 0:
        return jsonify(
            {
                "cpa_eligible": False,
                "message": f"CPA warranty expired on {cpa_deadline.strftime('%d %B %Y')}.",
                "days_expired": abs(days_remaining),
            }
        )

    urgency = (
        "HIGH" if days_remaining < 30 else "MEDIUM" if days_remaining < 90 else "LOW"
    )

    return jsonify(
        {
            "cpa_eligible": True,
            "days_remaining": days_remaining,
            "deadline": cpa_deadline.strftime("%d %B %Y"),
            "urgency": urgency,
            "rights": [
                "Full refund",
                "Free replacement",
                "Free repair at supplier's cost",
            ],
            "next_step": "We can generate a formal CPA claim letter for you.",
        }
    )

@limiter.limit("20 per hour")
@app.route("/api/start-claim", methods=["POST"])
def start_claim():
    data = request.json
    email = data.get("email")
    purchase_date = data.get("purchase_date")
    product_query = data.get("product_query")
    warranty_id = data.get("warranty_id")
    claim_type = data.get("claim_type", "warranty")
    issue = data.get("issue_description", "Product defective")
    retailer = data.get("retailer", "")

    # Save user
    existing = supabase.table("users").select("*").eq("email", email).execute()
    if not existing.data:
        supabase.table("users").insert({"email": email}).execute()

    # Calculate CPA deadline
    cpa_deadline = None
    if claim_type == "cpa" or True:
        try:
            purchase_date_obj = datetime.strptime(purchase_date, "%Y-%m-%d")
            cpa_deadline = purchase_date_obj + timedelta(days=182)
        except ValueError:
            pass

    # Save claim
    claim_data = {"user_email": email, "status": "initiated", "claim_amount": 0}
    if warranty_id:
        claim_data["warranty_id"] = warranty_id

    claim = supabase.table("claims").insert(claim_data).execute()
    claim_id = claim.data[0]["id"]

    # Save CPA-specific data
    if retailer:
        supabase.table("cpa_claims").insert(
            {
                "user_email": email,
                "product_name": product_query,
                "retailer": retailer,
                "purchase_date": purchase_date,
                "issue_description": issue,
                "cpa_deadline": cpa_deadline.strftime("%Y-%m-%d")
                if cpa_deadline
                else None,
                "desired_outcome": data.get("desired_outcome", "repair"),
                "status": "initiated",
            }
        ).execute()

    # Generate CPA letter
    cpa_letter = None
    if retailer:
        user_data = {
            "name": data.get("name", ""),
            "address": data.get("address", ""),
            "phone": data.get("phone", ""),
            "email": email,
        }
        product_data = {
            "product_name": product_query,
            "purchase_date": purchase_date,
            "issue_description": issue,
            "desired_outcome": data.get("desired_outcome", "repair"),
        }

        retailer_info = (
            supabase.table("retailer_policies")
            .select("*")
            .ilike("retailer_name", f"%{retailer}%")
            .execute()
        )

        retailer_data = (
            retailer_info.data[0]
            if retailer_info.data
            else {
                "retailer_name": retailer,
                "customer_service_email": "",
                 "customer_service_phone": "",
            }
        )

        cpa_letter = generate_cpa_letter(user_data, product_data, retailer_data)

    # Send CPA letter via email
    if cpa_letter and email:
        import threading
        def send_later():
            try:
                subject = f"Your CPA Claim Letter - {product_query}"
                email_body = f"""Hi there,

Your CPA claim has been started with ClaimFlux SA.

{cpa_letter}

---
ClaimFlux SA
https://claimflux.co.za
"""
                result = send_email(email, subject, email_body)
                if not result:
                    print(f"Failed to send email to {email}")
            except Exception as e:
                print(f"Email error: {e}")

        threading.Thread(target=send_later).start()

    # set auth token    
    return jsonify(
        {
            "success": True,
            "message": "Claim started! We'll review within 48 hours.",
            "claim_id": claim_id,
            "cpa_deadline": cpa_deadline.strftime("%d %B %Y") if cpa_deadline else None,
            "cpa_letter": cpa_letter if cpa_letter else None,
        }
    )
    resp = set_auth_token(email, resp)
    return resp

@app.route("/api/generate-letter", methods=["POST"])
def generate_letter():
    """Generate CPA letter on demand"""
    data = request.json

    user_data = {
        "name": data.get("name", ""),
        "address": data.get("address", ""),
        "phone": data.get("phone", ""),
        "email": data.get("email", ""),
    }
    product_data = {
        "product_name": data.get("product_name", ""),
        "purchase_date": data.get("purchase_date", ""),
        "issue_description": data.get("issue_description", ""),
        "desired_outcome": data.get("desired_outcome", "repair"),
        "order_number": data.get("order_number", ""),
    }

    retailer = data.get("retailer", "")
    retailer_info = (
        supabase.table("retailer_policies")
        .select("*")
        .ilike("retailer_name", f"%{retailer}%")
        .execute()
    )

    retailer_data = (
        retailer_info.data[0]
        if retailer_info.data
        else {
            "retailer_name": retailer,
            "customer_service_email": "",
            "customer_service_phone": "",
        }
    )

    letter = generate_cpa_letter(user_data, product_data, retailer_data)

    return jsonify({"letter": letter})


@app.route("/api/login", methods=["POST"])
def login():
    email = request.json.get("email")
    token = secrets.token_urlsafe(32)

    supabase.table("login_tokens").insert(
        {"email": email, "token": token, "expires": "NOW() + INTERVAL '1 hour'"}
    ).execute()

    login_link = f"/verify-login/{token}"

    # Send magic link via email
    login_url = f"<http://127.0.0.1:5000/verify-login/{token}>"
    email_body = f"""Hi there,

Click this link to log in to ClaimFlux SA:

{login_url}

This link expires in 1 hour.

---

ClaimFlux SA
"""
    send_email(email, "Your ClaimFlux SA Login Link", email_body)

    return jsonify({
        "message": "Check your email for login link.", 
        "dev_link": login_link
     })


@app.route('/api/my-claims')
def my_claims():
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "No email", "claims": [], "count": 0, "cpa_alerts": [], "urgent_count": 0}), 200
    
    
    claims = supabase.table('claims') \
        .select('*, warranties(*)') \
        .eq('user_email', email) \
        .order('filed_date', desc=True) \
        .execute()
    
    # Get CPA alerts
    cpa_alerts = check_cpa_deadlines(email)
    
    # Calculate totals
    total_recovered = sum(c['user_payout'] or 0 for c in claims.data if c['status'] == 'paid')
    
    return jsonify({
        "claims": claims.data,
        "count": len(claims.data),
        "total_recovered": total_recovered,
        "cpa_alerts": cpa_alerts,
        "urgent_count": len([a for a in cpa_alerts if a['urgency'] in ['critical', 'expired']])
    })


@app.route("/api/seed-data")
def seed_data():
    """Visit this URL once to populate database"""

    warranties = [
        {
            "brand": "ALL",
            "model_pattern": "%",
            "part_covered": "Full product (CPA Section 56) - Refund/Replace/Repair",
            "duration_years": 0.5,
            "warranty_type": "cpa_implied",
            "region": "ZA",
        },
        {
            "brand": "Samsung",
            "model_pattern": "RF%",
            "part_covered": "Sealed System (compressor, evaporator)",
            "duration_years": 10,
            "warranty_type": "parts_only",
            "region": "global",
        },
        {
            "brand": "LG",
            "model_pattern": "WM%",
            "part_covered": "Direct Drive Motor",
            "duration_years": 10,
            "warranty_type": "parts_and_labor",
            "region": "global",
        },
        {
            "brand": "LG",
            "model_pattern": "RF%",
            "part_covered": "Linear Compressor",
            "duration_years": 10,
            "warranty_type": "parts_only",
            "region": "global",
        },
        {
            "brand": "Defy",
            "model_pattern": "%",
            "part_covered": "General warranty (all parts)",
            "duration_years": 2,
            "warranty_type": "parts_and_labor",
            "region": "ZA",
        },
        {
            "brand": "Hisense",
            "model_pattern": "%",
            "part_covered": "General warranty",
            "duration_years": 2,
            "warranty_type": "parts_and_labor",
            "region": "ZA",
        },
        {
            "brand": "Hisense",
            "model_pattern": "H%Fridge%",
            "part_covered": "Compressor",
            "duration_years": 10,
            "warranty_type": "parts_only",
            "region": "ZA",
        },
        {
            "brand": "KIC",
            "model_pattern": "%",
            "part_covered": "General warranty",
            "duration_years": 2,
            "warranty_type": "parts_and_labor",
            "region": "ZA",
        },
        {
            "brand": "Bosch",
            "model_pattern": "%",
            "part_covered": "General warranty",
            "duration_years": 2,
            "warranty_type": "parts_and_labor",
            "region": "global",
        },
        {
            "brand": "Bosch",
            "model_pattern": "S%",
            "part_covered": "EcoSilence Drive Motor",
            "duration_years": 10,
            "warranty_type": "parts_only",
            "region": "global",
        },
        {
            "brand": "Siemens",
            "model_pattern": "%",
            "part_covered": "General warranty",
            "duration_years": 2,
            "warranty_type": "parts_and_labor",
            "region": "global",
        },
        {
            "brand": "Miele",
            "model_pattern": "%",
            "part_covered": "General warranty",
            "duration_years": 2,
            "warranty_type": "parts_and_labor",
            "region": "global",
        },
        {
            "brand": "Russell Hobbs",
            "model_pattern": "%",
            "part_covered": "General warranty",
            "duration_years": 2,
            "warranty_type": "parts",
            "region": "ZA",
        },
        {
            "brand": "Whirlpool",
            "model_pattern": "%",
            "part_covered": "Drive Motor",
            "duration_years": 10,
            "warranty_type": "parts_only",
            "region": "global",
        },
        {
            "brand": "GE",
            "model_pattern": "%",
            "part_covered": "Motor",
            "duration_years": 10,
            "warranty_type": "parts_only",
            "region": "global",
        },
    ]

    for w in warranties:
        supabase.table("warranties").insert(w).execute()

    retailers = [
        {
            "retailer_name": "Takealot",
            "return_window_days": 30,
            "customer_service_email": "help@takealot.com",
            "customer_service_phone": "087 362 8000",
            "notes": "6-month CPA still applies after 30-day window",
        },
        {
            "retailer_name": "Makro",
            "return_window_days": 30,
            "customer_service_email": "customerservices@makro.co.za",
            "customer_service_phone": "0860 600 999",
            "notes": "CPA obligations apply regardless of store policy",
        },
        {
            "retailer_name": "Game",
            "return_window_days": 30,
            "customer_service_email": "customerservices@game.co.za",
            "customer_service_phone": "0861 426 333",
            "notes": "Massmart group. CPA compliance generally good",
        },
        {
            "retailer_name": "Builders Warehouse",
            "return_window_days": 30,
            "customer_service_email": "customerservices@builders.co.za",
            "customer_service_phone": "0860 284 533",
            "notes": "Home improvement. CPA applies",
        },
        {
            "retailer_name": "Hirsch's",
            "return_window_days": 14,
            "customer_service_email": "info@hirschs.co.za",
            "customer_service_phone": "0860 447 7247",
            "notes": "Independent. Generally helpful with warranty claims",
        },
        {
            "retailer_name": "Dion Wired",
            "return_window_days": 30,
            "customer_service_email": "info@dionwired.co.za",
            "customer_service_phone": "0860 338 999",
            "notes": "Electronics specialist",
        },
        {
            "retailer_name": "Checkers",
            "return_window_days": 30,
            "customer_service_email": "customerservice@shoprite.co.za",
            "customer_service_phone": "0800 01 07 09",
            "notes": "Appliances via Checkers Hyper",
        },
        {
            "retailer_name": "Woolworths",
            "return_window_days": 30,
            "customer_service_email": "custserv@woolworths.co.za",
            "customer_service_phone": "0860 022 002",
            "notes": "Limited appliances. Strong returns culture",
        },
    ]

    for r in retailers:
        supabase.table("retailer_policies").insert(r).execute()

    return jsonify(
        {
            "success": True,
            "warranties_seeded": len(warranties),
            "retailers_seeded": len(retailers),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
