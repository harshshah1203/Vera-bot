#!/usr/bin/env python3
"""
Deterministic Vera message engine for the magicpin AI Challenge.

Core artifact:
    compose(category, merchant, trigger, customer=None) -> dict

Server wrapper:
    uvicorn bot:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import re
import time
import os
from datetime import datetime, timezone
from typing import Any

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except Exception:  # pragma: no cover - compose() still works without FastAPI.
    FastAPI = None
    BaseModel = object


START = time.time()
TEAM_METADATA = {
    "team_name": "One Signal One Smart Move",
    "team_members": ["Harsh"],
    "model": "deterministic-python",
    "approach": "context-grounded compose engine with trigger-specific decision logic",
    "contact_email": "not-provided@example.com",
    "version": "1.0.0",
    "submitted_at": "2026-05-01T00:00:00Z",
}

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}
contexts: dict[tuple[str, str], dict[str, Any]] = {}
conversations: dict[str, dict[str, Any]] = {}
sent_suppression_keys: set[str] = set()
suppressed_merchants: set[str] = set()


def compose(
    category: dict[str, Any],
    merchant: dict[str, Any],
    trigger: dict[str, Any],
    customer: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Compose Vera's next WhatsApp message from the four challenge contexts."""
    kind = trigger.get("kind", "")
    if customer or trigger.get("scope") == "customer":
        return _compose_customer(category, merchant, trigger, customer)

    composers = {
        "research_digest": _research_or_digest,
        "regulation_change": _research_or_digest,
        "cde_opportunity": _research_or_digest,
        "category_seasonal": _seasonal_or_festival,
        "festival_upcoming": _seasonal_or_festival,
        "ipl_match_today": _ipl_match,
        "perf_dip": _performance_change,
        "perf_spike": _performance_change,
        "seasonal_perf_dip": _performance_change,
        "milestone_reached": _milestone,
        "active_planning_intent": _active_planning,
        "curious_ask_due": _curious_ask,
        "competitor_opened": _competitor_opened,
        "review_theme_emerged": _review_theme,
        "renewal_due": _renewal_due,
        "winback_eligible": _winback,
        "dormant_with_vera": _dormant,
        "gbp_unverified": _gbp_unverified,
        "supply_alert": _supply_alert,
    }
    builder = composers.get(kind, _generic_merchant)
    return _with_common_fields(builder(category, merchant, trigger), trigger, "vera")


def should_send(
    category: dict[str, Any],
    merchant: dict[str, Any],
    trigger: dict[str, Any],
    customer: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Deterministic decision gate: restraint is better than low-signal spam."""
    suppression_key = trigger.get("suppression_key") or trigger.get("id", "")
    if suppression_key in sent_suppression_keys:
        return False, "suppression key already sent"
    if merchant.get("merchant_id") in suppressed_merchants:
        return False, "merchant opted out"
    # The judge controls simulated time through available_triggers. Do not
    # compare expires_at to wall-clock time here, because replay data may use
    # older dates while still being active in the scenario.
    if trigger.get("scope") == "customer":
        if not customer:
            return False, "customer context missing"
        consent = customer.get("consent", {})
        prefs = customer.get("preferences", {})
        if not consent.get("opted_in_at") or prefs.get("reminder_opt_in") is False:
            return False, "customer consent missing"
    if trigger.get("urgency", 1) <= 1 and _recent_no_reply(merchant):
        return False, "low-urgency trigger after recent no-reply"
    return True, "signal is useful and actionable"


def respond_to_reply(
    conversation_id: str,
    merchant_id: str | None,
    customer_id: str | None,
    message: str,
    turn_number: int,
) -> dict[str, Any]:
    """Handle replay turns deterministically."""
    conv = conversations.setdefault(
        conversation_id,
        {"turns": [], "auto_count": 0, "last_bot_body": "", "ended": False},
    )
    conv["turns"].append({"from": "merchant", "body": message, "turn": turn_number})
    text = _clean(message).lower()

    if _is_hostile_or_opt_out(text):
        if merchant_id:
            suppressed_merchants.add(merchant_id)
        conv["ended"] = True
        return {
            "action": "end",
            "rationale": "Merchant explicitly opted out or showed frustration; ending without further nudges.",
        }

    if _looks_like_auto_reply(text, conv):
        conv["auto_count"] += 1
        if conv["auto_count"] == 1:
            body = "Looks like this may be an auto-reply. I will wait for the owner/manager before taking the next step."
            return _reply_send(conv, body, "none", "Detected likely WhatsApp Business auto-reply; backing off once.")
        if conv["auto_count"] == 2:
            return {
                "action": "wait",
                "wait_seconds": 86400,
                "rationale": "Same auto-reply pattern repeated; waiting 24h instead of wasting turns.",
            }
        conv["ended"] = True
        return {
            "action": "end",
            "rationale": "Auto-reply repeated multiple times with no human signal; closing conversation.",
        }

    conv["auto_count"] = 0

    if _is_positive_intent(text):
        body = _action_mode_body(conversation_id, merchant_id)
        return _reply_send(
            conv,
            body,
            "binary_confirm_cancel",
            "Merchant committed; switching immediately from pitch to action mode.",
        )

    if _is_off_topic(text):
        body = "That is outside Vera's merchant-growth scope, so your CA or specialist is the right person. Coming back to this signal: reply YES and I will prepare the merchant-growth draft from the context we discussed."
        return _reply_send(conv, body, "binary_yes_no", "Politely declined off-topic ask and redirected to Vera's scope.")

    body = "Got it. I will keep this focused: I can turn the current signal into one ready draft for your listing or customer WhatsApp. Reply YES and I will prepare it."
    return _reply_send(conv, body, "binary_yes_no", "Acknowledged merchant reply and offered one low-friction next step.")


# ---------------------------------------------------------------------------
# Merchant composers
# ---------------------------------------------------------------------------


def _research_or_digest(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    item = _find_digest_item(category, trigger)
    sal = _merchant_salutation(category, merchant)
    cat = _category_label(category)
    source = item.get("source", "this week's category digest")
    title = item.get("title", "a new category update")
    trial = item.get("trial_n")
    segment = item.get("patient_segment") or _signal_phrase(merchant, "high_risk_adult_cohort")
    cta = "Want me to draft a customer WhatsApp + Google post from this?"

    if trigger.get("kind") == "regulation_change":
        deadline = trigger.get("payload", {}).get("deadline_iso")
        body = f"{sal}, compliance alert from {source}: {title}."
        if deadline:
            body += f" Deadline: {deadline}."
        body += " Smart move: document the change in your SOP and post a short patient-safe note only if needed. Reply YES and I will draft both."
        rationale = "Uses a source-cited compliance signal and recommends one concrete operational next step."
        return {"body": body, "cta": "binary_yes_no", "rationale": rationale}

    if trigger.get("kind") == "cde_opportunity":
        credits = trigger.get("payload", {}).get("credits") or item.get("credits")
        fee = trigger.get("payload", {}).get("fee") or item.get("actionable", "")
        body = f"{sal}, {source} has a relevant CDE: {title}."
        if credits:
            body += f" It carries {credits} credits."
        if fee:
            body += f" Fee note: {fee}."
        body += " Smart move: I can turn it into a 2-line calendar reminder plus a patient-facing post after you attend. Reply YES to save it."
        return {"body": body, "cta": "binary_yes_no", "rationale": "CDE trigger converted into a low-effort professional growth action."}

    body = f"{sal}, {source}: {title}."
    if trial:
        body += f" It cites {trial:,} patients."
    if segment:
        body += f" This matches your {segment.replace('_', ' ')} cohort."
    body += " Smart move: I can turn it into a patient WhatsApp + Google post. Reply YES and I will draft both."
    return {
        "body": body,
        "cta": "binary_yes_no",
        "rationale": "Research digest grounded in category source and merchant signal; converts knowledge into ready content.",
    }


def _performance_change(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "performance")
    delta = payload.get("delta_pct") or _delta_for_metric(merchant, metric)
    delta_text = _pct(delta) if delta is not None else "changed"
    perf = merchant.get("performance", {})
    views = perf.get("views")
    calls = perf.get("calls")
    offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    kind = trigger.get("kind")

    if kind == "perf_spike":
        body = f"{sal}, {metric} is up {delta_text} in the {payload.get('window', 'recent window')}."
        if views and calls:
            body += f" Current 30d base: {views:,} views and {calls:,} calls."
        body += f" Smart move: capture this demand with one fresh GBP post around {offer}. Reply YES and I will draft it."
        rationale = "Performance spike converted into demand-capture action using existing offer context."
    elif kind == "seasonal_perf_dip":
        members = merchant.get("customer_aggregate", {}).get("total_active_members")
        season_note = payload.get("season_note", "seasonal demand shift")
        body = f"{sal}, {metric} is down {delta_text}, but the trigger flags it as {season_note.replace('_', ' ')}."
        if members:
            body += f" You already have {members} active members."
        body += " Smart move: avoid panic discounts; run a retention nudge instead. Reply YES and I will draft a 7-day challenge message."
        rationale = "Seasonal dip is diagnosed as expected, then turned into a retention action."
    else:
        verified = merchant.get("identity", {}).get("verified")
        body = f"{sal}, {metric} dropped {delta_text} in the {payload.get('window', 'latest window')}."
        if views and calls:
            body += f" Your 30d base is {views:,} views but only {calls:,} calls."
        if verified is False:
            body += " Diagnosis: trust is leaking because your Google profile is unverified."
            body += f" Smart move: verify GBP first, then publish {offer}. Reply YES and I will prepare both steps."
        else:
            body += f" Diagnosis: people are seeing you but fewer are converting. Smart move: refresh the listing with {offer} and one review-led post. Reply YES and I will draft it."
        rationale = "Performance dip grounded in merchant numbers and turned into a single recovery action."
    return {"body": body, "cta": "binary_yes_no", "rationale": rationale}


def _competitor_opened(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    comp = p.get("competitor_name", "a new competitor")
    dist = p.get("distance_km")
    their_offer = p.get("their_offer")
    opened = p.get("opened_date")
    own_offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    body = f"{sal}, {comp}"
    if dist:
        body += f" opened {dist}km away"
    if opened:
        body += f" on {opened}"
    body += "."
    if their_offer:
        body += f" Their hook is {their_offer}."
    body += f" Smart move: do not blindly cut price; position your {own_offer} with trust and outcome clarity. Reply YES and I will draft the comparison-safe GBP post."
    return {
        "body": body,
        "cta": "binary_yes_no",
        "rationale": "Competitor signal converted into defensive positioning without inventing competitor facts.",
    }


def _review_theme(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    theme = p.get("theme", "review theme").replace("_", " ")
    count = p.get("occurrences_30d")
    quote = p.get("common_quote")
    body = f"{sal}, review pattern spotted: {count} recent reviews mention {theme}." if count else f"{sal}, review pattern spotted around {theme}."
    if quote:
        body += f" Common wording: \"{quote}\"."
    body += " Smart move: reply publicly with empathy and fix the root cause in one line. Reply YES and I will draft the review reply + staff note."
    return {"body": body, "cta": "binary_yes_no", "rationale": "Review theme is turned into a reputation repair action and internal micro-fix."}


def _active_planning(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    topic = trigger.get("payload", {}).get("intent_topic", "the plan").replace("_", " ")
    last = trigger.get("payload", {}).get("merchant_last_message", "")
    offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    body = f"{sal}, picking up your request on {topic}."
    if last:
        body += f" You said: \"{last}\"."
    body += f" Starter move: package it around {offer}, publish one GBP post, and use a short WhatsApp script for interested customers. Reply CONFIRM and I will prepare the first draft."
    return {"body": body, "cta": "binary_confirm_cancel", "rationale": "Merchant already showed intent, so Vera moves directly to a concrete draft action."}


def _curious_ask(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    business = merchant.get("identity", {}).get("name", "your business")
    category_name = category.get("display_name") or category.get("slug", "business")
    body = f"{sal}, quick merchant question: what is the most asked-for {category_name.lower()} service at {business} this week? Reply with one service name and I will turn it into a Google post + 4-line WhatsApp pricing reply."
    return {"body": body, "cta": "open_ended", "rationale": "Curious-ask trigger uses asking-the-merchant as the engagement lever and offers immediate content work."}


def _ipl_match(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    match = p.get("match", "tonight's match")
    time_iso = p.get("match_time_iso", "")
    city = p.get("city") or merchant.get("identity", {}).get("city", "")
    offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    body = f"{sal}, {match} is in {city}"
    if time_iso:
        body += f" at {time_iso}"
    body += f". Smart move: use your existing {offer} as a match-night delivery hook, not a generic discount. Reply YES and I will draft the WhatsApp + listing copy."
    return {"body": body, "cta": "binary_yes_no", "rationale": "Local event trigger mapped to an existing restaurant offer and one campaign action."}


def _seasonal_or_festival(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    festival = p.get("festival") or p.get("season") or p.get("metric_or_topic") or "seasonal demand"
    offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    body = f"{sal}, {festival} is a relevant demand moment for {category.get('display_name', category.get('slug', 'your category'))}."
    if "trends" in p:
        body += f" Trend signals: {', '.join(p.get('trends', [])[:3])}."
    if p.get("days_until"):
        body += f" It is {p['days_until']} days away."
    body += f" Smart move: prepare one timely post around {offer}. Reply YES and I will draft it in your category tone."
    return {"body": body, "cta": "binary_yes_no", "rationale": "Seasonal trigger converted into a timely, category-fit campaign action."}


def _milestone(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    metric = p.get("metric", "milestone").replace("_", " ")
    now = p.get("value_now")
    target = p.get("milestone_value")
    body = f"{sal}, you are close to a milestone"
    if now and target:
        body += f": {now} {metric}, almost {target}"
    body += ". Smart move: ask recent happy customers for reviews while the signal is warm. Reply YES and I will draft the review-request WhatsApp."
    return {"body": body, "cta": "binary_yes_no", "rationale": "Milestone trigger converted into a timely review-growth action."}


def _renewal_due(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    days = p.get("days_remaining") or merchant.get("subscription", {}).get("days_remaining")
    amount = p.get("renewal_amount")
    body = f"{sal}, your {p.get('plan', merchant.get('subscription', {}).get('plan', 'plan'))} renewal is due"
    if days is not None:
        body += f" in {days} days"
    body += "."
    if amount:
        body += f" Amount shown: ₹{amount}."
    body += " Smart move: before renewal, I can send a 30-day value summary using your actual views, calls, and leads. Reply YES and I will prepare it."
    return {"body": body, "cta": "binary_yes_no", "rationale": "Renewal trigger reframed as a value-proof summary rather than a generic reminder."}


def _winback(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    days = p.get("days_since_expiry")
    lapsed = p.get("lapsed_customers_added_since_expiry") or merchant.get("customer_aggregate", {}).get("lapsed_90d_plus") or merchant.get("customer_aggregate", {}).get("lapsed_180d_plus")
    body = f"{sal}, winback signal"
    if days:
        body += f": subscription expired {days} days ago"
    if lapsed:
        body += f", and {lapsed} customers are now lapsed"
    body += ". Smart move: restart with one lapsed-customer campaign before pushing broad ads. Reply YES and I will draft the winback WhatsApp."
    return {"body": body, "cta": "binary_yes_no", "rationale": "Winback trigger focuses on recoverable customer value, not a generic subscription pitch."}


def _dormant(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    days = trigger.get("payload", {}).get("days_since_last_merchant_message")
    body = f"{sal}, it has been {days} days since your last Vera reply." if days else f"{sal}, quick check-in from Vera."
    body += " I will keep this useful: reply with your slowest day this week, and I will suggest one offer/post that can fill that slot."
    return {"body": body, "cta": "open_ended", "rationale": "Dormancy trigger uses a low-effort merchant question instead of a generic nudge."}


def _gbp_unverified(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    path = p.get("verification_path", "Google verification").replace("_", " ")
    uplift = _pct(p.get("estimated_uplift_pct"))
    body = f"{sal}, your Google Business Profile is unverified. Diagnosis: customers see you, but trust is weaker before they call."
    if uplift:
        body += f" Estimated upside in the context: {uplift}."
    body += f" Smart move: start with {path}, then publish one proof-led post. Reply YES and I will list the exact steps."
    return {"body": body, "cta": "binary_yes_no", "rationale": "GBP trust issue converted into a clear verification-first action."}


def _supply_alert(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    p = trigger.get("payload", {})
    molecule = p.get("molecule", "medicine")
    batches = ", ".join(p.get("affected_batches", [])[:3])
    manufacturer = p.get("manufacturer", "manufacturer")
    chronic = merchant.get("customer_aggregate", {}).get("chronic_rx_count")
    body = f"{sal}, urgent supply alert: {molecule}"
    if batches:
        body += f" batches {batches}"
    body += f" from {manufacturer} need attention."
    if chronic:
        body += f" You have {chronic} chronic-Rx customers in context."
    body += " Smart move: prepare a replacement-pickup workflow and customer note. Reply YES and I will draft both."
    return {"body": body, "cta": "binary_yes_no", "rationale": "Pharmacy alert uses precise batch/molecule context and offers an operational workflow."}


def _generic_merchant(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> dict[str, str]:
    sal = _merchant_salutation(category, merchant)
    kind = trigger.get("kind", "new signal").replace("_", " ")
    offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    body = f"{sal}, Vera found a {kind} signal for {merchant.get('identity', {}).get('name', 'your business')}. Smart move: turn it into one listing/customer message around {offer}. Reply YES and I will draft it."
    return {"body": body, "cta": "binary_yes_no", "rationale": "Fallback composer still follows signal-diagnosis-action-CTA without inventing data."}


# ---------------------------------------------------------------------------
# Customer composers
# ---------------------------------------------------------------------------


def _compose_customer(
    category: dict[str, Any],
    merchant: dict[str, Any],
    trigger: dict[str, Any],
    customer: dict[str, Any] | None,
) -> dict[str, str]:
    if not customer:
        return _with_common_fields(
            {
                "body": "Customer context is missing, so Vera should not send this customer-facing message.",
                "cta": "none",
                "rationale": "Customer-scoped trigger requires CustomerContext.",
            },
            trigger,
            "merchant_on_behalf",
        )

    kind = trigger.get("kind", "")
    if kind == "recall_due":
        result = _customer_recall(category, merchant, trigger, customer)
    elif kind in {"customer_lapsed_hard", "customer_lapsed_soft"}:
        result = _customer_winback(category, merchant, trigger, customer)
    elif kind == "chronic_refill_due":
        result = _customer_refill(category, merchant, trigger, customer)
    elif kind == "trial_followup":
        result = _customer_trial_followup(category, merchant, trigger, customer)
    elif kind == "wedding_package_followup":
        result = _customer_bridal_followup(category, merchant, trigger, customer)
    else:
        result = _customer_generic(category, merchant, trigger, customer)
    return _with_common_fields(result, trigger, "merchant_on_behalf")


def _customer_recall(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any]) -> dict[str, str]:
    p = trigger.get("payload", {})
    cname = _customer_name(customer)
    clinic = _merchant_short_name(merchant)
    due = p.get("service_due", "recall").replace("_", " ")
    last = p.get("last_service_date")
    slots = p.get("available_slots", [])
    offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    body = f"Hi {cname}, {clinic} here. Your {due} is due"
    if last:
        body += f" after your last visit on {last}"
    body += "."
    if slots:
        body += " Slots ready: " + " or ".join(s.get("label", "") for s in slots[:2] if s.get("label")) + "."
    body += f" {offer}. Reply 1 for the first slot, 2 for the second, or share a better time."
    return {"body": _apply_customer_language(body, customer), "cta": "multi_choice_slot", "rationale": "Customer recall uses consented relationship, real slots, and merchant offer."}


def _customer_winback(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any]) -> dict[str, str]:
    cname = _customer_name(customer)
    owner = merchant.get("identity", {}).get("owner_first_name") or _merchant_short_name(merchant)
    p = trigger.get("payload", {})
    days = p.get("days_since_last_visit")
    focus = p.get("previous_focus") or customer.get("preferences", {}).get("training_focus") or "your routine"
    offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    body = f"Hi {cname}, {owner} from {_merchant_short_name(merchant)} here."
    if days:
        body += f" It has been {days} days since your last visit."
    body += f" No pressure; if {focus.replace('_', ' ')} is still relevant, we can restart with {offer}. Reply YES and I will hold a trial/check-in slot."
    return {"body": _apply_customer_language(body, customer), "cta": "binary_yes_no", "rationale": "Winback is no-shame, goal-aware, and anchored to merchant offer."}


def _customer_refill(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any]) -> dict[str, str]:
    cname = _customer_name(customer)
    p = trigger.get("payload", {})
    meds = ", ".join(p.get("molecule_list", [])[:4])
    runs_out = p.get("stock_runs_out_iso")
    delivery = " Saved address delivery is available." if p.get("delivery_address_saved") else ""
    body = f"Namaste {cname}, {_merchant_short_name(merchant)} here. Your regular medicines"
    if meds:
        body += f" ({meds})"
    if runs_out:
        body += f" run out on {runs_out}"
    body += f".{delivery} Reply CONFIRM to dispatch, or reply CHANGE if dosage/brand changed."
    return {"body": _apply_customer_language(body, customer), "cta": "binary_confirm_cancel", "rationale": "Refill reminder uses molecule names, run-out date, and precise pharmacy CTA."}


def _customer_trial_followup(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any]) -> dict[str, str]:
    cname = _customer_name(customer)
    p = trigger.get("payload", {})
    trial = p.get("trial_date")
    slots = p.get("next_session_options", [])
    body = f"Hi {cname}, {_merchant_short_name(merchant)} here. Thanks for trying the session"
    if trial:
        body += f" on {trial}"
    body += "."
    if slots:
        body += f" Next option: {slots[0].get('label')}."
    body += " Reply YES and I will reserve it."
    return {"body": _apply_customer_language(body, customer), "cta": "binary_yes_no", "rationale": "Trial follow-up offers one concrete next session."}


def _customer_bridal_followup(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any]) -> dict[str, str]:
    cname = _customer_name(customer)
    p = trigger.get("payload", {})
    days = p.get("days_to_wedding")
    window = p.get("next_step_window_open", "next prep window").replace("_", " ")
    body = f"Hi {cname}, {_merchant_short_name(merchant)} here."
    if days:
        body += f" {days} days to your wedding."
    body += f" This is a good time for {window}. Reply YES and I will block your preferred slot for the first session."
    return {"body": _apply_customer_language(body, customer), "cta": "binary_yes_no", "rationale": "Bridal follow-up uses wedding timeline and preference-led next step."}


def _customer_generic(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any]) -> dict[str, str]:
    cname = _customer_name(customer)
    offer = _active_offer_title(merchant) or _catalog_offer_title(category)
    body = f"Hi {cname}, {_merchant_short_name(merchant)} here. We have a timely update for you: {offer}. Reply YES and we will help you book or get details."
    return {"body": _apply_customer_language(body, customer), "cta": "binary_yes_no", "rationale": "Fallback customer message stays consent-aware and offer-grounded."}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _with_common_fields(result: dict[str, str], trigger: dict[str, Any], send_as: str) -> dict[str, str]:
    return {
        "body": _polish(result.get("body", "")),
        "cta": result.get("cta", "binary_yes_no"),
        "send_as": send_as,
        "suppression_key": trigger.get("suppression_key", trigger.get("id", "")),
        "rationale": result.get("rationale", "Grounded deterministic composition."),
    }


def _merchant_salutation(category: dict[str, Any], merchant: dict[str, Any]) -> str:
    identity = merchant.get("identity", {})
    first = identity.get("owner_first_name") or identity.get("name", "there")
    first = str(first).replace("Dr.", "").strip()
    if category.get("slug") == "dentists":
        return f"Dr. {first.split()[0]}"
    return first.split()[0] if first else "Hi"


def _merchant_short_name(merchant: dict[str, Any]) -> str:
    name = merchant.get("identity", {}).get("name", "the clinic")
    return name.replace("'s Dental Clinic", "'s clinic").replace(" Dental Clinic", " clinic")


def _category_label(category: dict[str, Any]) -> str:
    label = category.get("display_name") or category.get("slug", "business")
    label = str(label).lower()
    singulars = {
        "dentists": "dentistry",
        "salons": "salon",
        "restaurants": "restaurant",
        "gyms": "fitness",
        "pharmacies": "pharmacy",
    }
    return singulars.get(label, label)


def _customer_name(customer: dict[str, Any]) -> str:
    return str(customer.get("identity", {}).get("name", "there")).split("(")[0].strip() or "there"


def _find_digest_item(category: dict[str, Any], trigger: dict[str, Any]) -> dict[str, Any]:
    payload = trigger.get("payload", {})
    target = payload.get("top_item_id") or payload.get("digest_item_id") or payload.get("alert_id")
    for item in category.get("digest", []):
        if item.get("id") == target:
            return item
    return category.get("digest", [{}])[0] if category.get("digest") else {}


def _active_offer_title(merchant: dict[str, Any]) -> str | None:
    for offer in merchant.get("offers", []):
        if offer.get("status") == "active" and offer.get("title"):
            return offer["title"]
    return None


def _catalog_offer_title(category: dict[str, Any]) -> str:
    offers = category.get("offer_catalog", [])
    return offers[0].get("title", "one specific service offer") if offers else "one specific service offer"


def _delta_for_metric(merchant: dict[str, Any], metric: str) -> float | None:
    key = f"{metric}_pct"
    return merchant.get("performance", {}).get("delta_7d", {}).get(key)


def _pct(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return str(value)


def _signal_phrase(merchant: dict[str, Any], signal: str) -> str:
    return signal if signal in merchant.get("signals", []) else ""


def _recent_no_reply(merchant: dict[str, Any]) -> bool:
    history = merchant.get("conversation_history", [])
    if not history:
        return False
    last = history[-1]
    return last.get("from") == "vera" and last.get("engagement") == "merchant_no_reply"


def _apply_customer_language(body: str, customer: dict[str, Any]) -> str:
    lang = str(customer.get("identity", {}).get("language_pref", "")).lower()
    if "hi" in lang or lang == "hi":
        return body.replace("Reply", "Reply").replace("here.", "yahan.")
    return body


def _polish(body: str) -> str:
    body = re.sub(r"\s+", " ", body).strip()
    body = body.replace("..", ".")
    return body


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_hostile_or_opt_out(text: str) -> bool:
    patterns = ["stop", "not interested", "spam", "useless", "do not message", "don't message", "unsubscribe", "band karo"]
    return any(p in text for p in patterns)


def _looks_like_auto_reply(text: str, conv: dict[str, Any]) -> bool:
    canned = [
        "thank you for contacting",
        "team will respond",
        "we will get back",
        "automated assistant",
        "our team will respond shortly",
        "business hours",
    ]
    previous = [t.get("body", "").lower() for t in conv.get("turns", [])[:-1] if t.get("from") == "merchant"]
    repeated = previous.count(text) >= 1
    return repeated or any(p in text for p in canned)


def _is_positive_intent(text: str) -> bool:
    patterns = [
        "yes",
        "go ahead",
        "do it",
        "let's do",
        "lets do",
        "confirm",
        "send",
        "please share",
        "ok",
        "join",
        "start",
        "proceed",
    ]
    return any(p in text for p in patterns)


def _is_off_topic(text: str) -> bool:
    return any(p in text for p in ["gst", "tax", "file my", "loan", "insurance", "rent agreement"])


def _action_mode_body(conversation_id: str, merchant_id: str | None) -> str:
    conv = conversations.get(conversation_id, {})
    goal = conv.get("goal") or "the draft"
    return f"Great. I am switching to action mode. I will prepare {goal} from the current merchant context. Reply CONFIRM to approve the draft, or CHANGE if you want edits first."


def _reply_send(conv: dict[str, Any], body: str, cta: str, rationale: str) -> dict[str, Any]:
    body = _polish(body)
    if body == conv.get("last_bot_body"):
        body += " I will keep it to this one next step."
    conv["last_bot_body"] = body
    conv.setdefault("turns", []).append({"from": "vera", "body": body})
    return {"action": "send", "body": body, "cta": cta, "rationale": rationale}


# ---------------------------------------------------------------------------
# FastAPI wrapper
# ---------------------------------------------------------------------------


if FastAPI is not None:
    app = FastAPI(title="Vera Message Engine", version=TEAM_METADATA["version"])

    class CtxBody(BaseModel):
        scope: str
        context_id: str
        version: int
        payload: dict[str, Any]
        delivered_at: str | None = None

    class TickBody(BaseModel):
        now: str
        available_triggers: list[str] = []

    class ReplyBody(BaseModel):
        conversation_id: str
        merchant_id: str | None = None
        customer_id: str | None = None
        from_role: str
        message: str
        received_at: str | None = None
        turn_number: int = 1

    @app.get("/v1/healthz")
    async def healthz() -> dict[str, Any]:
        counts = {scope: 0 for scope in VALID_SCOPES}
        for (scope, _), _value in contexts.items():
            counts[scope] = counts.get(scope, 0) + 1
        return {"status": "ok", "uptime_seconds": int(time.time() - START), "contexts_loaded": counts}

    @app.get("/v1/metadata")
    async def metadata() -> dict[str, Any]:
        return TEAM_METADATA

    @app.post("/v1/context")
    async def push_context(body: CtxBody) -> dict[str, Any]:
        if body.scope not in VALID_SCOPES:
            return {"accepted": False, "reason": "invalid_scope", "details": f"scope must be one of {sorted(VALID_SCOPES)}"}
        key = (body.scope, body.context_id)
        cur = contexts.get(key)
        if cur and cur["version"] >= body.version:
            return {"accepted": False, "reason": "stale_version", "current_version": cur["version"]}
        contexts[key] = {"version": body.version, "payload": body.payload}
        return {
            "accepted": True,
            "ack_id": f"ack_{body.context_id}_v{body.version}",
            "stored_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    @app.post("/v1/tick")
    async def tick(body: TickBody) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        trigger_payloads = []
        for tid in body.available_triggers:
            trigger = contexts.get(("trigger", tid), {}).get("payload")
            if trigger:
                trigger_payloads.append(trigger)
        trigger_payloads.sort(key=lambda t: int(t.get("urgency", 1)), reverse=True)

        for trigger in trigger_payloads:
            if len(actions) >= 20:
                break
            merchant_id = trigger.get("merchant_id")
            merchant = contexts.get(("merchant", merchant_id), {}).get("payload")
            if not merchant:
                continue
            category = contexts.get(("category", merchant.get("category_slug")), {}).get("payload")
            if not category:
                continue
            customer = None
            if trigger.get("customer_id"):
                customer = contexts.get(("customer", trigger.get("customer_id")), {}).get("payload")

            send, _reason = should_send(category, merchant, trigger, customer)
            if not send:
                continue
            message = compose(category, merchant, trigger, customer)
            suppression = message["suppression_key"]
            sent_suppression_keys.add(suppression)
            conv_id = _conversation_id(trigger, merchant, customer)
            conversations[conv_id] = {
                "turns": [{"from": message["send_as"], "body": message["body"]}],
                "auto_count": 0,
                "last_bot_body": message["body"],
                "goal": _goal_for_trigger(trigger),
                "ended": False,
            }
            action = {
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": trigger.get("customer_id"),
                "send_as": message["send_as"],
                "trigger_id": trigger.get("id"),
                "template_name": _template_name(trigger, message),
                "template_params": _template_params(message),
                **message,
            }
            actions.append(action)
        return {"actions": actions}

    @app.post("/v1/reply")
    async def reply(body: ReplyBody) -> dict[str, Any]:
        return respond_to_reply(
            body.conversation_id,
            body.merchant_id,
            body.customer_id,
            body.message,
            body.turn_number,
        )


def _conversation_id(trigger: dict[str, Any], merchant: dict[str, Any], customer: dict[str, Any] | None) -> str:
    target = customer.get("customer_id") if customer else merchant.get("merchant_id")
    raw = f"conv_{target}_{trigger.get('kind')}_{trigger.get('id')}"
    return re.sub(r"[^a-zA-Z0-9_]+", "_", raw)[:120]


def _goal_for_trigger(trigger: dict[str, Any]) -> str:
    kind = trigger.get("kind", "signal").replace("_", " ")
    return f"one {kind} action draft"


def _template_name(trigger: dict[str, Any], message: dict[str, str]) -> str:
    if message.get("send_as") == "merchant_on_behalf":
        return f"merchant_{trigger.get('kind', 'message')}_v1"
    return f"vera_{trigger.get('kind', 'message')}_v1"


def _template_params(message: dict[str, str]) -> list[str]:
    body = message.get("body", "")
    protected = body.replace("Dr. ", "Dr| ")
    parts = [p.strip().replace("Dr| ", "Dr. ") for p in re.split(r"(?<=[.!?])\s+", protected) if p.strip()]
    return parts[:3] or [body]


if __name__ == "__main__":
    if FastAPI is None:
        raise SystemExit("FastAPI is not installed. Install requirements or run compose() directly.")
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=False)
