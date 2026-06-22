from datetime import timedelta, datetime
from config import Config


def calculate_cpa_deadline(purchase_date):
    return purchase_date + timedelta(days=Config.DEFAULT_CPA_DAYS)


def check_cpa_eligibility(purchase_date_str):
    try:
        purchase_date = datetime.strptime(
            purchase_date_str,
            "%Y-%m-%d"
        )
    except ValueError:
        return {
            "error": "Use YYYY-MM-DD format"
        }

    deadline = calculate_cpa_deadline(purchase_date)

    days_remaining = (deadline - datetime.now()).days

    if days_remaining < 0:
        return {
            "cpa_eligible": False,
            "days_expired": abs(days_remaining),
            "deadline": deadline.strftime("%d %B %Y")
        }

    urgency = (
        "HIGH"
        if days_remaining < 30
        else "MEDIUM"
        if days_remaining < 90
        else "LOW"
    )

    return {
        "cpa_eligible": True,
        "days_remaining": days_remaining,
        "deadline": deadline.strftime("%d %B %Y"),
        "urgency": urgency,
        "rights": [
            "Full refund",
            "Free replacement",
            "Free repair"
        ]
    }
