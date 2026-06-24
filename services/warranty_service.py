from extensions import supabase


def match_products_to_warranties(extracted_data):
    matches = []
    seen_pairs = set()

    for product in extracted_data.get("products", []):
        brand = product.get("brand", "")
        model = product.get("model", "")

        if not brand:
            continue

        response = (
            supabase.table("warranties")
            .select("*")
            .ilike("brand", f"%{brand}%")
            .limit(5)
            .execute()
        )

        for warranty in response.data:

            pair_key = (model, warranty["id"])

            if pair_key in seen_pairs:
                continue

            seen_pairs.add(pair_key)

            matches.append({
                "product": product,
                "warranty": {
                    "id": warranty["id"],
                    "brand": warranty["brand"],
                    "part_covered": warranty["part_covered"],
                    "duration_years": warranty["duration_years"],
                    "type": warranty["warranty_type"],
                    "region": warranty.get("region", "global")
                }
            })

    return matches
