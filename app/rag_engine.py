import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from google import genai

from app.config import DATA_PATH, GEMINI_API_KEY, MODEL_NAME, TOP_K_CONTEXT_LINES

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "can",
    "do",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "with",
    "you",
    "your",
}

PREFERRED_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
]

MENU_KEYWORDS = {"menu", "food", "foods", "item", "items", "dish", "dishes", "price", "prices"}
HOURS_KEYWORDS = {"hour", "hours", "open", "opening", "close", "closing", "timing", "time"}
POLICY_KEYWORDS = {"policy", "policies", "rule", "rules", "outside", "delivery"}
GREETING_KEYWORDS = {"hi", "hello", "hey"}
ORDER_KEYWORDS = {"order", "bill", "total", "buy", "want", "add", "cart", "checkout"}
CONFIRM_KEYWORDS = {"ok", "okay", "yes", "confirm", "proceed", "place"}
CANCEL_KEYWORDS = {"cancel", "stop", "clear", "remove"}
AMBIGUOUS_ALIAS_WORDS = {"veg", "nonveg", "vegetarian", "non-vegetarian", "vegan", "dessert"}

DINE_IN_PHRASES = {"dine in", "dine-in", "dinein", "table", "eat in", "eat-in"}
DELIVERY_PHRASES = {"online delivery", "home delivery", "delivery", "deliver", "door delivery"}
SLOT_HINTS = {"breakfast", "lunch", "dinner", "morning", "afternoon", "evening", "night"}

GST_RATE = 0.05
MIN_ADDRESS_LENGTH = 10


@dataclass
class MenuItem:
    name: str
    price: int
    item_type: str
    ingredients: str


def _read_restaurant_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except OSError as exc:
        return f"DATA_LOAD_ERROR: {exc}"


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _normalize_model_name(name: str) -> str:
    return name.replace("models/", "")


def _create_client_and_model() -> Tuple[object, str, str]:
    if not GEMINI_API_KEY:
        return None, "", "Missing GEMINI_API_KEY. Using local retrieval fallback only."

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        available = []
        try:
            for item in client.models.list():
                methods = getattr(item, "supported_actions", None)
                if methods is None or "generateContent" in methods:
                    available.append(_normalize_model_name(item.name))
        except Exception:
            available = []

        candidates = [_normalize_model_name(MODEL_NAME)] + PREFERRED_FALLBACK_MODELS
        if available:
            for candidate in candidates:
                if candidate in available:
                    return client, candidate, ""
            return client, available[0], ""

        return client, _normalize_model_name(MODEL_NAME), ""
    except Exception as exc:
        return None, "", f"Model initialization error: {exc}"


def _find_line_index(lines: List[str], prefix: str) -> int:
    target = prefix.lower()
    for idx, line in enumerate(lines):
        if line.lower().startswith(target):
            return idx
    return -1


def _section_between(lines: List[str], start_prefix: str, end_prefixes: Tuple[str, ...]) -> List[str]:
    start_idx = _find_line_index(lines, start_prefix)
    if start_idx == -1:
        return []

    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        line_lower = lines[idx].lower()
        if any(line_lower.startswith(end_prefix.lower()) for end_prefix in end_prefixes):
            end_idx = idx
            break
    return lines[start_idx:end_idx]


def _extract_menu_items(lines: List[str]) -> List[MenuItem]:
    menu_lines = _section_between(lines, "Menu:", ("Policies:",))
    if not menu_lines:
        return []

    items: List[MenuItem] = []
    current = None
    for raw_line in menu_lines[1:]:
        line = raw_line.strip()
        match = re.match(r"^\d+\.\s*(.+?)\s*-\s*Rs\s*(\d+)", line, flags=re.IGNORECASE)
        if match:
            if current:
                items.append(current)
            current = {
                "name": match.group(1).strip(),
                "price": int(match.group(2)),
                "type": "",
                "ingredients": "",
            }
            continue

        if current is None:
            continue

        if line.lower().startswith("type:"):
            current["type"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("ingredients:"):
            current["ingredients"] = line.split(":", 1)[1].strip()

    if current:
        items.append(current)

    return [
        MenuItem(
            name=item["name"],
            price=item["price"],
            item_type=item["type"] or "N/A",
            ingredients=item["ingredients"] or "N/A",
        )
        for item in items
    ]


def _build_menu_alias_map(menu_items: List[MenuItem]) -> Dict[str, MenuItem]:
    aliases: Dict[str, MenuItem] = {}
    for item in menu_items:
        name = item.name.lower()
        aliases[name] = item
        words = name.split()
        if words:
            first = words[0]
            last = words[-1]
            if first not in AMBIGUOUS_ALIAS_WORDS and len(first) > 3:
                aliases[first] = item
            if last not in AMBIGUOUS_ALIAS_WORDS and len(last) > 3:
                aliases[last] = item
    return aliases


def _parse_order_from_query(query: str, alias_map: Dict[str, MenuItem]) -> Dict[str, int]:
    q = query.lower()
    order: Dict[str, int] = {}

    for alias, item in alias_map.items():
        alias_pattern = rf"\b{re.escape(alias)}\b"
        if not re.search(alias_pattern, q):
            continue

        qty = 1
        left = re.search(rf"(\d+)\s*(?:x\s*)?{alias_pattern}", q)
        right = re.search(rf"{alias_pattern}\s*(?:x\s*)?(\d+)", q)
        if left:
            qty = int(left.group(1))
        elif right:
            qty = int(right.group(1))

        order[item.name] = max(order.get(item.name, 0), qty)

    return order


def _default_session_context() -> Dict[str, str]:
    return {
        "mode": "",  # dine_in | delivery
        "stage": "choose_mode",  # choose_mode | await_slot | ordering | await_address
        "slot": "",
        "address": "",
    }


def _detect_service_mode(query: str) -> str:
    q = query.lower()
    if any(phrase in q for phrase in DINE_IN_PHRASES):
        return "dine_in"
    if any(phrase in q for phrase in DELIVERY_PHRASES):
        return "delivery"
    return ""


def _extract_slot(query: str) -> str:
    q = query.strip()
    q_lower = q.lower()

    slot_range = re.search(
        r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\s*(?:-|to)\s*\d{1,2}(?::\d{2})?\s?(?:am|pm)\b",
        q_lower,
    )
    if slot_range:
        return re.sub(r"\s+", " ", slot_range.group(0)).upper().replace(" TO ", " - ")

    slot_range_suffix = re.search(
        r"\b\d{1,2}(?::\d{2})?\s*(?:-|to)\s*\d{1,2}(?::\d{2})?\s?(?:am|pm)\b",
        q_lower,
    )
    if slot_range_suffix:
        return re.sub(r"\s+", " ", slot_range_suffix.group(0)).upper().replace(" TO ", " - ")

    time_ampm = re.search(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", q_lower)
    if time_ampm:
        return re.sub(r"\s+", " ", time_ampm.group(0)).upper()

    time_24h = re.search(r"\b\d{1,2}:\d{2}\b", q_lower)
    if time_24h:
        return time_24h.group(0)

    for hint in SLOT_HINTS:
        if hint in q_lower:
            return hint.title()

    return ""


def _looks_like_address(query: str) -> bool:
    q = query.strip()
    if len(q) < MIN_ADDRESS_LENGTH:
        return False
    if _detect_service_mode(q):
        return False

    q_lower = q.lower()
    if q_lower in {"confirm", "ok", "yes", "menu", "cancel"}:
        return False

    # Practical heuristic: address usually has spaces, numbers, commas, or landmarks.
    word_count = len(q.split())
    has_numeric = bool(re.search(r"\d", q))
    has_separator = "," in q or "-" in q
    return word_count >= 3 or has_numeric or has_separator


def _split_address_lines(address: str) -> List[str]:
    value = (address or "").strip()
    if not value:
        return []

    if "\n" in value:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if lines:
            return lines

    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) >= 2:
        return parts

    words = value.split()
    if len(words) >= 8:
        midpoint = len(words) // 2
        return [" ".join(words[:midpoint]), " ".join(words[midpoint:])]

    return [value]


def _mode_label(mode: str) -> str:
    if mode == "dine_in":
        return "Dine-In"
    if mode == "delivery":
        return "Online Delivery"
    return ""


def _order_summary(order: Dict[str, int], menu_items: List[MenuItem], context: Dict[str, str]) -> Tuple[str, int]:
    menu_by_name = {item.name: item for item in menu_items}
    lines = ["Pending Order:"]
    mode_label = _mode_label(context.get("mode", ""))
    if mode_label:
        lines.append(f"Order Type: {mode_label}")
    if context.get("mode") == "dine_in" and context.get("slot"):
        lines.append(f"Dine-In Slot: {context['slot']}")

    subtotal = 0
    for idx, (item_name, qty) in enumerate(order.items(), start=1):
        item = menu_by_name[item_name]
        line_total = item.price * qty
        subtotal += line_total
        lines.append(f"{idx}. {item.name} x{qty} = Rs {line_total}")

    lines.append(f"Estimated Subtotal: Rs {subtotal}")
    if context.get("mode") == "delivery" and not context.get("address"):
        lines.append("At confirm, you will be asked for delivery address.")
    lines.append("Type 'confirm' to place order and generate final bill, or 'cancel' to discard.")
    return "\n".join(lines), subtotal


def _generate_bill(
    order: Dict[str, int], menu_items: List[MenuItem], context: Dict[str, str]
) -> Tuple[str, Dict[str, object]]:
    menu_by_name = {item.name: item for item in menu_items}
    lines = ["Final Bill:"]

    mode_label = _mode_label(context.get("mode", ""))
    if mode_label:
        lines.append(f"Order Type: {mode_label}")
    if context.get("mode") == "dine_in" and context.get("slot"):
        lines.append(f"Dine-In Slot: {context['slot']}")
    if context.get("mode") == "delivery" and context.get("address"):
        lines.append("Delivery Address:")
        for addr_line in _split_address_lines(context["address"]):
            lines.append(f"- {addr_line}")

    subtotal = 0
    item_rows: List[Dict[str, object]] = []

    for idx, (item_name, qty) in enumerate(order.items(), start=1):
        item = menu_by_name[item_name]
        line_total = item.price * qty
        subtotal += line_total
        item_rows.append(
            {
                "name": item.name,
                "quantity": qty,
                "unit_price": item.price,
                "line_total": line_total,
            }
        )
        lines.append(f"{idx}. {item.name} x{qty} = Rs {line_total}")

    gst = round(subtotal * GST_RATE)
    total = subtotal + gst
    bill_id = f"CN-{uuid.uuid4().hex[:8].upper()}"
    issued_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append(f"Subtotal: Rs {subtotal}")
    lines.append(f"GST (5%): Rs {gst}")
    lines.append(f"Total: Rs {total}")
    lines.append(f"Bill ID: {bill_id}")

    bill_data: Dict[str, object] = {
        "bill_id": bill_id,
        "issued_at": issued_at,
        "items": item_rows,
        "subtotal": subtotal,
        "gst": gst,
        "total": total,
        "mode": context.get("mode", ""),
        "slot": context.get("slot", ""),
        "address": context.get("address", ""),
        "address_lines": _split_address_lines(context.get("address", "")),
    }
    return "\n".join(lines), bill_data


def _format_menu_list(menu_items: List[MenuItem]) -> str:
    if not menu_items:
        return "Menu is currently unavailable."

    lines = ["Menu Items:"]
    for item in menu_items:
        lines.append(f"- {item.name} - Rs {item.price} ({item.item_type}, Ingredients: {item.ingredients})")
    return "\n".join(lines)


restaurant_text = _read_restaurant_text(DATA_PATH)
restaurant_lines = [line.strip() for line in restaurant_text.splitlines() if line.strip()]
client, ACTIVE_MODEL_NAME, MODEL_INIT_ERROR = _create_client_and_model()

orders_by_session: Dict[str, Dict[str, int]] = {}
latest_bill_by_session: Dict[str, Dict[str, object]] = {}
session_context_by_session: Dict[str, Dict[str, str]] = {}


def get_latest_bill(session_id: str) -> Dict[str, object] | None:
    return latest_bill_by_session.get(session_id)


def _get_session_context(session_id: str) -> Dict[str, str]:
    if session_id not in session_context_by_session:
        session_context_by_session[session_id] = _default_session_context()
    return session_context_by_session[session_id]


def _reset_session_context(session_id: str) -> None:
    session_context_by_session[session_id] = _default_session_context()


def _new_response(
    answer: str,
    kind: str = "message",
    order_pending: bool = False,
    total: int = 0,
    bill_id: str = "",
    context: Dict[str, str] | None = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "answer": answer,
        "kind": kind,
        "order_pending": order_pending,
        "total": total,
        "bill_id": bill_id,
    }

    if context:
        payload["service_mode"] = context.get("mode", "")
        payload["service_stage"] = context.get("stage", "")
        payload["service_slot"] = context.get("slot", "")
    else:
        payload["service_mode"] = ""
        payload["service_stage"] = ""
        payload["service_slot"] = ""

    return payload


def _score_line(line: str, query: str, query_tokens: List[str]) -> int:
    line_lower = line.lower()
    line_tokens = set(_tokenize(line))
    keyword_hits = sum(1 for token in query_tokens if token in line_tokens)
    phrase_bonus = 2 if query.lower().strip() and query.lower().strip() in line_lower else 0
    return keyword_hits + phrase_bonus


def _get_current_restaurant_lines() -> List[str]:
    current_text = _read_restaurant_text(DATA_PATH)
    if current_text.startswith("DATA_LOAD_ERROR:"):
        return restaurant_lines
    return [line.strip() for line in current_text.splitlines() if line.strip()]


def retrieve_context(query: str, top_k: int = TOP_K_CONTEXT_LINES) -> str:
    lines = _get_current_restaurant_lines()
    if not lines:
        return restaurant_text

    query_tokens = [token for token in _tokenize(query) if token not in STOP_WORDS]
    if not query_tokens:
        return "\n".join(lines[:top_k])

    scored: List[Tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        score = _score_line(line, query, query_tokens)
        if score > 0:
            scored.append((score, idx, line))

    if not scored:
        return "\n".join(lines[:top_k])

    top_scored = sorted(scored, key=lambda item: (-item[0], item[1]))[:top_k]
    selected_indices = sorted({idx for _, idx, _ in top_scored})
    return "\n".join(lines[i] for i in selected_indices)


def _handle_order_flow(
    query: str,
    session_id: str,
    menu_items: List[MenuItem],
    context: Dict[str, str],
) -> Dict[str, object]:
    tokens = set(_tokenize(query))
    pending = dict(orders_by_session.get(session_id, {}))

    if tokens & CANCEL_KEYWORDS:
        if pending:
            orders_by_session.pop(session_id, None)
            if context.get("mode") == "delivery" and context.get("stage") == "await_address":
                context["stage"] = "ordering"
            return _new_response("Pending order cancelled.", kind="order_cancelled", context=context)
        return _new_response("No pending order to cancel.", context=context)

    if tokens & CONFIRM_KEYWORDS:
        if not pending:
            return _new_response("No pending order found. Add items first, then type confirm.", context=context)

        if not context.get("mode"):
            context["stage"] = "choose_mode"
            return _new_response(
                "Before placing order, please tell me: Dine-In or Online Delivery?",
                kind="mode_required",
                order_pending=True,
                context=context,
            )

        if context["mode"] == "dine_in" and not context.get("slot"):
            context["stage"] = "await_slot"
            return _new_response(
                "Please share your preferred dine-in slot (example: 7:30 PM, Dinner, 8 PM).",
                kind="slot_required",
                order_pending=True,
                context=context,
            )

        if context["mode"] == "delivery" and not context.get("address"):
            context["stage"] = "await_address"
            summary, subtotal = _order_summary(pending, menu_items, context)
            return _new_response(
                summary + "\nPlease share complete delivery address to generate final bill.",
                kind="address_required",
                order_pending=True,
                total=subtotal,
                context=context,
            )

        bill_text, bill_data = _generate_bill(pending, menu_items, context)
        orders_by_session.pop(session_id, None)
        latest_bill_by_session[session_id] = bill_data
        _reset_session_context(session_id)
        return _new_response(
            bill_text,
            kind="bill",
            total=int(bill_data["total"]),
            bill_id=str(bill_data["bill_id"]),
            context=_get_session_context(session_id),
        )

    menu_alias_map = _build_menu_alias_map(menu_items)
    parsed = _parse_order_from_query(query, menu_alias_map)

    if not parsed:
        if (tokens & ORDER_KEYWORDS) and pending:
            summary, subtotal = _order_summary(pending, menu_items, context)
            return _new_response(summary, kind="pending_order", order_pending=True, total=subtotal, context=context)

        if tokens & ORDER_KEYWORDS:
            return _new_response(
                "Add items with quantity, for example: 2 Margherita Pizza and 1 Veg Salad.",
                context=context,
            )

        return _new_response("", context=context)

    if not context.get("mode"):
        context["stage"] = "choose_mode"
        return _new_response(
            "Before adding items, tell me your order type: Dine-In or Online Delivery?",
            kind="mode_required",
            context=context,
        )

    if context["mode"] == "dine_in" and not context.get("slot"):
        context["stage"] = "await_slot"
        return _new_response(
            "Please confirm your dine-in slot first (example: 7:30 PM or Dinner).",
            kind="slot_required",
            context=context,
        )

    if "add" in tokens and pending:
        for item_name, qty in parsed.items():
            pending[item_name] = pending.get(item_name, 0) + qty
        orders_by_session[session_id] = pending
    else:
        orders_by_session[session_id] = parsed

    context["stage"] = "ordering"
    summary, subtotal = _order_summary(orders_by_session[session_id], menu_items, context)
    return _new_response(summary, kind="pending_order", order_pending=True, total=subtotal, context=context)


def _rule_based_response(query: str, session_id: str, lines: List[str]) -> Dict[str, object]:
    tokens = set(_tokenize(query))
    menu_items = _extract_menu_items(lines)
    context = _get_session_context(session_id)

    service_mode = _detect_service_mode(query)
    if service_mode:
        if orders_by_session.get(session_id) and service_mode != context.get("mode"):
            orders_by_session.pop(session_id, None)

        if service_mode == "dine_in":
            context["mode"] = "dine_in"
            context["stage"] = "await_slot"
            context["address"] = ""
            return _new_response(
                "Dine-In selected. Please share your preferred time slot (example: 7:30 PM, 8 PM, Dinner).",
                kind="mode_selected",
                context=context,
            )

        if service_mode == "delivery":
            context["mode"] = "delivery"
            context["stage"] = "ordering"
            context["slot"] = ""
            return _new_response(
                "Online Delivery selected. Now choose Veg/Non-Veg, add items, and confirm. I will ask delivery address at the end.",
                kind="mode_selected",
                context=context,
            )

    if context["stage"] == "await_slot":
        slot = _extract_slot(query)
        if slot:
            context["slot"] = slot
            context["stage"] = "ordering"
            return _new_response(
                f"Dine-In slot confirmed: {slot}. Now choose Veg/Non-Veg and add items from menu.",
                kind="slot_confirmed",
                context=context,
            )
        return _new_response(
            "Please share a valid time slot (example: 7:30 PM, 8 PM, Dinner).",
            kind="slot_required",
            context=context,
        )

    if context.get("mode") == "dine_in" and context.get("stage") == "ordering":
        updated_slot = _extract_slot(query)
        if updated_slot:
            context["slot"] = updated_slot
            return _new_response(
                f"Dine-In slot updated: {updated_slot}. You can continue ordering.",
                kind="slot_confirmed",
                context=context,
            )

    if context["stage"] == "await_address":
        if tokens & CANCEL_KEYWORDS:
            orders_by_session.pop(session_id, None)
            context["stage"] = "ordering"
            context["address"] = ""
            return _new_response("Pending order cancelled.", kind="order_cancelled", context=context)

        if _looks_like_address(query):
            context["address"] = query.strip()
            context["stage"] = "ordering"

            pending = dict(orders_by_session.get(session_id, {}))
            if pending:
                bill_text, bill_data = _generate_bill(pending, menu_items, context)
                orders_by_session.pop(session_id, None)
                latest_bill_by_session[session_id] = bill_data
                _reset_session_context(session_id)
                return _new_response(
                    bill_text,
                    kind="bill",
                    total=int(bill_data["total"]),
                    bill_id=str(bill_data["bill_id"]),
                    context=_get_session_context(session_id),
                )

            return _new_response("Address saved. You can continue ordering.", context=context)

        return _new_response(
            "Please provide complete delivery address (house/flat, area, city, pincode).",
            kind="address_required",
            context=context,
        )

    if not context.get("mode"):
        if tokens & (GREETING_KEYWORDS | ORDER_KEYWORDS | MENU_KEYWORDS | CONFIRM_KEYWORDS | CANCEL_KEYWORDS):
            return _new_response(
                "Is this for Dine-In or Online Delivery?",
                kind="mode_required",
                context=context,
            )

    if tokens & GREETING_KEYWORDS:
        if not context.get("mode"):
            return _new_response("Hello. Is this for Dine-In or Online Delivery?", context=context)
        return _new_response("Hello. You can now choose Veg/Non-Veg and place your order.", context=context)

    order_response = _handle_order_flow(query, session_id, menu_items, context)
    if order_response["answer"]:
        return order_response

    if tokens & MENU_KEYWORDS:
        return _new_response(_format_menu_list(menu_items), kind="menu", context=context)

    if tokens & HOURS_KEYWORDS:
        hours_lines = _section_between(lines, "Opening Hours:", ("Menu:", "Policies:"))
        if hours_lines:
            return _new_response("\n".join(hours_lines), kind="hours", context=context)

    if tokens & POLICY_KEYWORDS:
        policy_lines = _section_between(lines, "Policies:", ())
        if policy_lines:
            return _new_response("\n".join(policy_lines), kind="policy", context=context)

    return _new_response("", context=context)


def ask_question(query: str, session_id: str = "default") -> Dict[str, object]:
    question = query.strip()
    context = _get_session_context(session_id)

    if not question:
        return _new_response("Please enter a valid question.", context=context)

    if restaurant_text.startswith("DATA_LOAD_ERROR:"):
        return _new_response(restaurant_text, context=context)

    current_lines = _get_current_restaurant_lines()
    direct = _rule_based_response(question, session_id, current_lines)
    if direct["answer"]:
        return direct

    if client is None:
        context_text = retrieve_context(question, top_k=8)
        fallback = (
            f"I could not use the model right now ({MODEL_INIT_ERROR}).\n{context_text}"
            if MODEL_INIT_ERROR
            else context_text
        )
        return _new_response(fallback, context=context)

    context_text = retrieve_context(question)
    prompt = (
        "You are a restaurant assistant. "
        "Answer only from the provided context. "
        "If answer is missing, say: I could not find that in the restaurant data.\n\n"
        f"Context:\n{context_text}\n\n"
        f"Question: {question}"
    )

    try:
        response = client.models.generate_content(model=ACTIVE_MODEL_NAME, contents=prompt)
        answer = (getattr(response, "text", "") or "").strip()
        if answer:
            return _new_response(answer, context=context)
        return _new_response("I could not find that in the restaurant data.", context=context)
    except Exception as exc:
        error_text = str(exc).lower()
        if "quota" in error_text or "429" in error_text or "rate" in error_text:
            context_text = retrieve_context(question, top_k=8)
            return _new_response(f"Model quota exceeded.\n{context_text}", context=context)
        if "404" in error_text or "not found" in error_text:
            context_text = retrieve_context(question, top_k=8)
            return _new_response(f"Model is unavailable.\n{context_text}", context=context)
        return _new_response("I could not find that in the restaurant data.", context=context)
