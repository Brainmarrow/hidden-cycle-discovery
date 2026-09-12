from fastapi import APIRouter, Request, HTTPException
from app.core.config import settings

router = APIRouter()

@router.post("/stripe")
async def stripe_webhook(request: Request):
    import stripe   # lazy: billing is optional — desktop/lite installs skip it
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(400, "Invalid signature")
    if event["type"] == "customer.subscription.updated":
        pass  # Update user plan in DB
    elif event["type"] == "customer.subscription.deleted":
        pass  # Downgrade to free
    return {"status": "ok"}
