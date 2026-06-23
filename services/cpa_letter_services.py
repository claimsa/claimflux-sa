from datetime import datetime
import secrets


def generate_cpa_letter(
        user_data,
        product_data,
        retailer_data
):

    ref = (
        f"CLAIMFLUX-"
        f"{datetime.now().strftime('%Y%m%d')}-"
        f"{secrets.token_hex(4).upper()}"
    )

    return f"""
{user_data['name']}

Date: {datetime.now().strftime('%d %B %Y')}

To: {retailer_data['retailer_name']}

RE: FORMAL CLAIM UNDER SECTION 56 OF THE CPA

Product:
{product_data['product_name']}

Issue:

{product_data['issue_description']}

Preferred outcome:

{product_data['desired_outcome']}

Reference:

{ref}
"""
