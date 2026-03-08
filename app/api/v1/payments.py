"""Stripe webhooks and subscription management."""
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import require_client, get_current_user
from app.models.user import User
from app.models.client import Client, SubscriptionPlan
from app.models.subscription import Subscription, Payment, SubscriptionStatus
from app.core.config import settings
from datetime import datetime, timezone

router = APIRouter(prefix="/payments", tags=["payments"])
stripe.api_key = settings.STRIPE_SECRET_KEY

PLAN_PRICE_MAP = {
    "starter": settings.STRIPE_STARTER_PRICE_ID,
    "growth": settings.STRIPE_GROWTH_PRICE_ID,
    "enterprise": settings.STRIPE_ENTERPRISE_PRICE_ID,
}


class CreateCheckoutRequest(BaseModel):
    plan: str  # starter / growth / enterprise
    success_url: str
    cancel_url: str


@router.post("/checkout")
async def create_checkout_session(
    data: CreateCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_client),
):
    if data.plan not in PLAN_PRICE_MAP:
        raise HTTPException(400, "Invalid plan")
    price_id = PLAN_PRICE_MAP[data.plan]
    if not price_id:
        raise HTTPException(400, f"Stripe Price ID for '{data.plan}' not configured")

    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()

    # Create or reuse Stripe customer
    if not client.stripe_customer_id:
        customer = stripe.Customer.create(email=current_user.email, name=current_user.full_name)
        client.stripe_customer_id = customer.id
        await db.commit()

    session = stripe.checkout.Session.create(
        customer=client.stripe_customer_id,
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=data.success_url,
        cancel_url=data.cancel_url,
        metadata={"client_id": str(client.id), "plan": data.plan},
    )
    return {"checkout_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(alias="stripe-signature"), db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")

    et = event["type"]
    data = event["data"]["object"]

    if et == "checkout.session.completed":
        client_id = int(data["metadata"].get("client_id", 0))
        plan = data["metadata"].get("plan", "starter")
        stripe_sub_id = data.get("subscription")
        if client_id and stripe_sub_id:
            client_res = await db.execute(select(Client).where(Client.id == client_id))
            client = client_res.scalar_one_or_none()
            if client:
                client.subscription_plan = SubscriptionPlan(plan)
                client.roles_used_this_month = 0
                from datetime import datetime, timezone
                client.billing_cycle_start = datetime.now(timezone.utc)
                # Create Subscription record
                sub = Subscription(
                    client_id=client_id,
                    stripe_subscription_id=stripe_sub_id,
                    stripe_price_id=PLAN_PRICE_MAP.get(plan, ""),
                    plan=plan,
                    status=SubscriptionStatus.ACTIVE,
                )
                db.add(sub)
                await db.commit()

    elif et == "invoice.payment_succeeded":
        amount = data.get("amount_paid", 0) / 100
        currency = data.get("currency", "usd")
        stripe_invoice_id = data.get("id")
        stripe_sub_id = data.get("subscription")
        # Find subscription
        if stripe_sub_id:
            sub_res = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id))
            sub = sub_res.scalar_one_or_none()
            if sub:
                payment = Payment(
                    subscription_id=sub.id,
                    client_id=sub.client_id,
                    stripe_invoice_id=stripe_invoice_id,
                    amount=amount,
                    currency=currency,
                    status="paid",
                    paid_at=datetime.now(timezone.utc),
                )
                db.add(payment)
                await db.commit()

    elif et in ("customer.subscription.deleted", "customer.subscription.updated"):
        stripe_sub_id = data.get("id")
        new_status = data.get("status", "cancelled")
        sub_res = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id))
        sub = sub_res.scalar_one_or_none()
        if sub:
            sub.status = SubscriptionStatus(new_status) if new_status in SubscriptionStatus._value2member_map_ else SubscriptionStatus.CANCELLED
            await db.commit()

    return {"received": True}


@router.get("/subscription")
async def get_subscription(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_client)):
    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Client not found")
    return {"plan": client.subscription_plan, "roles_used": client.roles_used_this_month}
