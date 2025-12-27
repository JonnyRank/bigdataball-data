import smtplib
from email.message import EmailMessage
import config


def send_email_alert(subject, body):
    """Sends an email notification using settings from config.py."""
    if not getattr(config, "EMAIL_ENABLED", False):
        print("Email notifications are disabled in config.")
        return

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_SENDER
    msg["To"] = config.EMAIL_RECEIVER

    try:
        # Connect to Gmail's SMTP server using SSL
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"Notification email sent to {config.EMAIL_RECEIVER}")
    except Exception as e:
        print(f"Failed to send email notification: {e}")
