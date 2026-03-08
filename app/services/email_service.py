"""Email service using SendGrid — templates pulled from DB."""
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, To, From
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.admin import EmailTemplate
from app.core.config import settings
import re


async def get_template(db: AsyncSession, slug: str) -> EmailTemplate | None:
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.slug == slug, EmailTemplate.is_active == True))
    return result.scalar_one_or_none()


def render_template(template_str: str, variables: dict) -> str:
    """Replace {{variable}} placeholders with values."""
    for key, value in variables.items():
        template_str = template_str.replace(f"{{{{{key}}}}}", str(value))
    return template_str


async def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_body: str,
    text_body: str = "",
) -> bool:
    """Send email via SendGrid."""
    try:
        sg = SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
        message = Mail(
            from_email=(settings.FROM_EMAIL, settings.FROM_NAME),
            to_emails=To(email=to_email, name=to_name),
            subject=subject,
            html_content=html_body,
            plain_text_content=text_body,
        )
        response = sg.send(message)
        return response.status_code in (200, 202)
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


async def send_test_invitation(
    db: AsyncSession,
    candidate_name: str,
    candidate_email: str,
    test_link: str,
    role_title: str,
    company_name: str,
    expires_hours: int = 48,
) -> bool:
    template = await get_template(db, "test_invitation")
    if template:
        subject = render_template(template.subject, {
            "candidate_name": candidate_name, "role_title": role_title, "company_name": company_name
        })
        html_body = render_template(template.html_body, {
            "candidate_name": candidate_name, "role_title": role_title,
            "company_name": company_name, "test_link": test_link, "expires_hours": expires_hours,
        })
    else:
        subject = f"[TopDev] Your {role_title} Assessment at {company_name}"
        html_body = f"""
        <h2>Hello {candidate_name},</h2>
        <p>You've been invited to complete a technical assessment for <strong>{role_title}</strong> at <strong>{company_name}</strong>.</p>
        <p><a href="{test_link}" style="background:#6366f1;color:white;padding:12px 24px;text-decoration:none;border-radius:6px;">Start Assessment</a></p>
        <p>This link expires in {expires_hours} hours.</p>
        <p>Good luck!</p>
        """
    return await send_email(candidate_email, candidate_name, subject, html_body)


async def send_result_notification(
    db: AsyncSession,
    candidate_name: str,
    candidate_email: str,
    score: float,
    badge: str,
    role_title: str,
) -> bool:
    template = await get_template(db, "result_notification")
    if template:
        subject = render_template(template.subject, {
            "candidate_name": candidate_name, "role_title": role_title, "badge": badge
        })
        html_body = render_template(template.html_body, {
            "candidate_name": candidate_name, "score": score, "badge": badge, "role_title": role_title,
        })
    else:
        subject = f"[TopDev] Your assessment results for {role_title}"
        html_body = f"""
        <h2>Results for {candidate_name}</h2>
        <p>Role: <strong>{role_title}</strong></p>
        <p>Score: <strong>{score}/100</strong> — <span style="color:#6366f1">{badge.replace('_',' ').title()}</span></p>
        <p>Thank you for completing the assessment. You'll hear from the hiring team soon.</p>
        """
    return await send_email(candidate_email, candidate_name, subject, html_body)
