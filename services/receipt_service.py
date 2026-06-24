import json
import re

from extensions import openai_client
from services.logger import logger


def extract_products_rules(receipt_text):

    brands = [
        "Samsung",
        "LG",
        "Defy",
        "Hisense",
        "KIC",
        "Bosch",
        "Siemens",
        "Miele",
        "Whirlpool",
        "GE",
        "Russell Hobbs",
        "Apple",
        "Sony",
        "Huawei",
        "Philips"
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
            except Exception:
                pass

        products.append(
            {
                "brand": found_brand,
                "model": line[:100],
                "category": "other",
                "purchase_date": "Unknown",
                "purchase_price": price,
                "retailer": "Unknown"
            }
        )

    total = sum(
        p["purchase_price"]
        for p in products
        if p["purchase_price"]
    )

    return {
        "products": products,
        "total_spent": round(total, 2)
    }


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

Return ONLY JSON:

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
                "role": "user",
                "content": receipt_text[:4000]
            }
        ]
    )

    return json.loads(
        response.choices[0].message.content
    )


def extract_products_from_receipt(receipt_text):

    try:

        return extract_products_ai(receipt_text)

    except Exception as e:

        logger.error(
            f"AI extraction failed: {e}"
        )

        return extract_products_rules(
            receipt_text
        )


def extract_products_from_image(base64_image):

    try:

        response = openai_client.chat.completions.create(

            model="gpt-4o",

            max_tokens=1000,

            messages=[

                {
                    "role": "system",

                    "content": """
Return ONLY JSON:

{
 "products":[],
 "total_spent":0
}
"""
                },

                {
                    "role": "user",

                    "content": [

                        {
                            "type": "text",

                            "text": "Extract products"
                        },

                        {
                            "type": "image_url",

                            "image_url": {
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

    except Exception as e:

        logger.error(
            f"Image extraction failed: {e}"
        )

        return {
            "products": [],
            "total_spent": 0
        }
