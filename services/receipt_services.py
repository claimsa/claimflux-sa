import json
import re
from datetime import datetime

from extensions import openai_client

# 2. Rule-based extraction
def extract_products_rules(receipt_text):

    brands = [
        "Samsung","LG","Defy","Hisense","KIC",
        "Bosch","Siemens","Miele","Whirlpool",
        "GE","Russell Hobbs","Apple","Sony",
        "Huawei","Philips"
    ]

    retailers = [
        "Takealot",
        "Makro",
        "Game",
        "Checkers",
        "Woolworths",
        "Builders",
        "Pick n Pay",
        "Spar"
    ]

    products = []

    lines = receipt_text.split("\n")

    for line in lines:

        line = line.strip()

        if len(line) < 10:
            continue

        found_brand = None

        for brand in brands:

            if brand.lower() in line.lower():

                found_brand = brand
                break

        if not found_brand:
            continue

        price_match = re.search(
            r'R\s?(\d[\d\s,]*\.?\d{0,2})',
            line
        )

        price = None

        if price_match:

            try:
                price = float(
                    price_match.group(1)
                    .replace(",", "")
                    .replace(" ", "")
                )

            except:
                pass

        products.append({

            "brand": found_brand,

            "model": line[:100],

            "category": "other",

            "purchase_date": "Unknown",

            "purchase_price": price,

            "retailer": "Unknown"

        })

    total = sum(
        p["purchase_price"]
        for p in products
        if p["purchase_price"]
    )

    return {

        "products": products,

        "total_spent": round(total, 2)

    }

# 3. AI extraction
def extract_products_ai(receipt_text):

    response = openai_client.chat.completions.create(

        model="gpt-4o",

        response_format={"type": "json_object"},

        temperature=0.1,

        messages=[

            {
                "role": "system",
                "content": """
Extract ALL products.

Return only JSON:

{
 "products":[
   {
      "brand":"",
      "model":"",
      "category":"",
      "purchase_date":"",
      "purchase_price":0,
      "retailer":""
   }
 ],
 "total_spent":0
}
"""
            },

            {
                "role":"user",
                "content":receipt_text[:4000]
            }

        ]
    )

    return json.loads(
        response.choices[0].message.content
    )

# 4. Hybrid extraction
def extract_products_from_receipt(receipt_text):

    try:

        return extract_products_ai(receipt_text)

    except Exception as e:

        print("AI extraction failed:", e)

        return extract_products_rules(receipt_text)

# 5. Image receipt extraction
def extract_products_from_image(base64_image):

    response = openai_client.chat.completions.create(

        model="gpt-4o",

        max_tokens=1000,

        messages=[

            {
                "role":"system",

                "content":"""
Return ONLY JSON:
{
 "products":[],
 "total_spent":0
}
"""
            },

            {
                "role":"user",

                "content":[

                    {
                        "type":"text",

                        "text":"Extract products"
                    },

                    {
                        "type":"image_url",

                        "image_url":{
                            "url":
                            f"data:image/jpeg;base64,{base64_image}"
                        }
                    }

                ]
            }
        ]
    )

    return json.loads(
        response.choices[0].message.content
    )
