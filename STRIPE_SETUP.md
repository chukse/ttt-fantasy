# TTT Pro — Stripe Freemium Setup

The paywall code is **already built + deployed**. This checklist activates real payments.
**Do it all in Stripe TEST mode first** (test keys + card `4242 4242 4242 4242`, any future expiry, any CVC). Flip to live keys once it works.

**Plan:** Free = 1 league + start/sit + waivers + draft tools. Pro = unlimited leagues + Ask the Towel AI + Trade Analyzer + Chance-to-Win odds.
**Price:** $4.99/mo (recurring) + $19.99/season (one-time, auto-expires ~Feb 15).

---

## 1. Add 2 DB columns  (Supabase → SQL Editor → Run)

```sql
alter table public.user_state add column if not exists plan_expires timestamptz;
alter table public.user_state add column if not exists stripe_customer_id text;
```

## 2. Create the product  (Stripe → Products → Add product)

Product name: **TTT Pro**. Add **two prices** to it:

| Price | Type |
|---|---|
| **$4.99** | Recurring · Monthly |
| **$19.99** | One-time |

Copy **both Price IDs** (look like `price_1Abc...`).

## 3. Worker variables  (Cloudflare → ttt-espn-proxy → Settings → Variables and Secrets)

| Name | Type | Value |
|---|---|---|
| `STRIPE_SECRET` | **Secret** | `sk_test_...` (Stripe → Developers → API keys) |
| `STRIPE_PRICE_MONTHLY` | Text | the **$4.99** `price_...` |
| `STRIPE_PRICE_SEASON` | Text | the **$19.99** `price_...` |
| `SUPABASE_SERVICE_ROLE` | **Secret** | Supabase → Settings → API → **`service_role`** key |
| `STRIPE_WEBHOOK_SECRET` | **Secret** | from step 4 (`whsec_...`) |

> ⚠️ **`service_role` and `sk_` are secrets** — Secret type only. Never put them in the app or repo.
> The `anon` key (already in the app) is fine to be public; the `service_role` key is NOT.

## 4. Add the webhook  (Stripe → Developers → Webhooks → Add endpoint)

- **Endpoint URL:** `https://ttt-espn-proxy.chukegbuchunam.workers.dev/?stripe_webhook`
- **Events to send:**
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
- Save, then **reveal the Signing secret** (`whsec_...`) → paste it into `STRIPE_WEBHOOK_SECRET` (step 3).

## 5. Redeploy the worker

Repaste `engine/proxy-worker.js` into the Cloudflare worker editor → **Deploy**.
(Same worker as the chat proxy — the file already contains both.)

---

## Test it (TEST mode)

1. Open the app → **Sign in** (magic link).
2. Tap **Trade / Odds / Chat** → you'll see the **Pro** lock card → **Go Pro**.
3. Choose Season or Monthly → Stripe Checkout → pay with `4242 4242 4242 4242`.
4. You land back on the app → within a few seconds it unlocks and shows **"⚡ You're Pro"**.
5. In Stripe → Customers you'll see the payment; in Supabase → `user_state` your row shows `plan = 'pro'`.

To test downgrade: Stripe → cancel the test subscription → `customer.subscription.deleted` fires → row flips back to `free`.

## Go live

Swap the Stripe **test** keys for **live** keys in the worker (`STRIPE_SECRET`), create a **live-mode** webhook (repeat step 4 in live mode → new `whsec_`), and use the **live** Price IDs. Everything else stays the same.

---

## How it works (for reference)

- **Checkout:** app → `POST /?stripe_checkout=1 {user_id, email, kind, return_url}` → worker creates a Stripe Checkout Session (subscription for monthly, one-time payment for season), stamped with your Supabase `user_id` → returns the Stripe URL → app redirects.
- **Fulfillment:** Stripe → `POST /?stripe_webhook` → worker verifies the signature → writes `plan='pro'` (and `plan_expires` for season) to your `user_state` row using the Supabase `service_role` key (bypasses RLS).
- **Unlock:** app returns to `?upgraded=1`, polls Supabase until `plan` flips, unlocks the Pro screens.

**Known gap (harden later):** the AI chat endpoint is gated in the app but not yet server-side, so a technical user could call the worker directly. Fine for launch; when it matters, the worker will verify the Supabase token + plan before calling Claude.
