import smtplib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import Config


def send_email(to_email, subject, body):

    if not Config.GMAIL_USER or not Config.GMAIL_APP_PASSWORD:

        print("Email credentials not configured.")

        return False

    msg = MIMEMultipart()

    msg["From"] = f"ClaimFlux SA <{Config.GMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(
        MIMEText(body, "plain")
    )

    try:

        server = smtplib.SMTP(
            "smtp.gmail.com",
            587
        )

        server.starttls()

        server.login(
            Config.GMAIL_USER,
            Config.GMAIL_APP_PASSWORD
        )

        server.send_message(msg)

        server.quit()

        return True

    except Exception as e:

        print("Email error:", e)

        return False
