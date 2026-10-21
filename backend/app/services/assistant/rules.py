"""Offline assistant: keyword intents in English, French and Arabic (MSA + Tunisian Darija).

Used when no Claude API key is configured, or when the Claude API can't be reached, so the
kiosk keeps answering the essential requests: free spots, open the gate, leave, reserve,
balance, prices, top-up. It calls the same tools as Claude, so the same rules apply.
"""

import re
from typing import Any

from app.services.assistant.language import detect_language, fold
from app.services.assistant.tools import ToolBox

# Checked in this order: the first intent with a matching keyword wins (see `classify`).
INTENTS: list[tuple[str, list[str]]] = [
    ("cancel", ["cancel", "annul", "الغاء", "الغي", "بطل", "ابطل", "fasa5", "batel"]),
    (
        "exit",
        [
            "leave",
            "leaving",
            "exit",
            "going out",
            "get out",
            "sortir",
            "sortie",
            "je pars",
            "quitter",
            "partir",
            "نخرج",
            "خروج",
            "اخرج",
            "نمشي",
            "ماشي",
            "مروح",
            "nokhrej",
            "na5rej",
            "nemchi",
        ],
    ),
    (
        "open",
        [
            "open",
            "let me in",
            "enter",
            "entry",
            "gate",
            "ouvr",
            "entrer",
            "entree",
            "barriere",
            "افتح",
            "افتحلي",
            "فتح",
            "حل",
            "حلي",
            "ادخل",
            "ندخل",
            "دخول",
            "الباب",
            "7ell",
            "7el",
            "7allou",
            "ndkhol",
            "nodkhel",
        ],
    ),
    (
        "reserve",
        ["reserv", "book", "hold a spot", "احجز", "حجز", "نحجز", "ريزرف", "ne7jez", "7jez"],
    ),
    (
        "price",
        [
            "price",
            "cost",
            "how much",
            "rate",
            "fee",
            "tarif",
            "prix",
            "combien",
            "cout",
            "سعر",
            "سوم",
            "قداش",
            "بقداش",
            "ثمن",
            "تسعيره",
            "9adech",
            "b9adech",
        ],
    ),
    (
        "topup",
        [
            "top up",
            "topup",
            "recharge",
            "add credit",
            "add money",
            "pay",
            "payer",
            "paiement",
            "alimenter",
            "اشحن",
            "شحن",
            "نشحن",
            "خلص",
            "نخلص",
            "دفع",
            "ندفع",
            "chahen",
        ],
    ),
    (
        "balance",
        [
            "balance",
            "credit",
            "wallet",
            "account",
            "my uid",
            "solde",
            "compte",
            "porte-monnaie",
            "رصيد",
            "حسابي",
            "حساب",
            "فلوسي",
            "كريدي",
            "sold",
        ],
    ),
    (
        "busy",
        [
            "busy",
            "peak",
            "crowd",
            "best time",
            "rush",
            "affluence",
            "pointe",
            "charge",
            "meilleur moment",
            "زحمه",
            "ذروه",
            "مزحوم",
            "وقت",
            "ze7ma",
        ],
    ),
    (
        "status",
        [
            "free",
            "available",
            "spot",
            "space",
            "room",
            "full",
            "place",
            "libre",
            "disponible",
            "complet",
            "بلاصه",
            "بلايص",
            "مكان",
            "اماكن",
            "فارغ",
            "شاغر",
            "متاح",
            "فما",
            "معمر",
            "blasa",
            "famma",
        ],
    ),
    (
        "greet",
        [
            "hello",
            "hi",
            "hey",
            "good morning",
            "bonjour",
            "bonsoir",
            "salut",
            "salam",
            "سلام",
            "السلام",
            "مرحبا",
            "عسلامه",
            "اهلا",
            "3aslema",
            "ahla",
        ],
    ),
    ("thanks", ["thank", "merci", "شكرا", "يعيشك", "ya3ichek", "barcha"]),
]

T: dict[str, dict[str, str]] = {
    "greet": {
        "en": "Hello! I can tell you which spots are free, open the gate, reserve a spot, "
        "or check your balance.",
        "fr": "Bonjour ! Je peux vous dire quelles places sont libres, ouvrir la barrière, "
        "réserver une place ou consulter votre solde.",
        "ar": "مرحبا! نجم نقلك وين فما بلايص فارغة، نحل الباب، نحجزلك بلاصة، ولا نشوفلك رصيدك.",
    },
    "help": {
        "en": "Sorry, I didn't get that. Try: “any free spot?”, “open the gate”, "
        "“reserve a spot for 30 minutes”, “my balance” or “I'm leaving”.",
        "fr": "Désolé, je n'ai pas compris. Essayez : « une place libre ? », « ouvrez la "
        "barrière », « réserver 30 minutes », « mon solde » ou « je pars ».",
        "ar": "سامحني، ما فهمتش. جرب: «فما بلاصة فارغة؟»، «حل الباب»، «احجزلي نص ساعة»، "
        "«رصيدي» ولا «باش نخرج».",
    },
    "thanks": {
        "en": "You're welcome, drive safely!",
        "fr": "Avec plaisir, bonne route !",
        "ar": "بالسلامة، ربي يسهل!",
    },
    "status": {
        "en": "{free} of {total} spots are free right now{list}.",
        "fr": "{free} place(s) libre(s) sur {total} en ce moment{list}.",
        "ar": "توا فما {free} بلايص فارغة من {total}{list}.",
    },
    "status_full": {
        "en": "The parking is full right now.",
        "fr": "Le parking est complet pour le moment.",
        "ar": "الباركينغ معمّر توا.",
    },
    "not_identified": {
        "en": "I need to know who you are first: sign in to the app, or show the QR code "
        "from the app's Account page to the camera.",
        "fr": "Je dois d'abord vous identifier : connectez-vous dans l'application, ou "
        "montrez le QR code de la page Compte à la caméra.",
        "ar": "لازم نعرفك قبل: ادخل للتطبيق، ولا ورّي الكود QR متاع صفحة الحساب للكاميرا.",
    },
    "entry_ok": {
        "en": "Welcome {name}, the barrier is opening.{spot}",
        "fr": "Bienvenue {name}, la barrière s'ouvre.{spot}",
        "ar": "مرحبا {name}، الباب يتحل.{spot}",
    },
    "spot_hint": {
        "en": " Your spot is {spot}.",
        "fr": " Votre place est la {spot}.",
        "ar": " بلاصتك هي {spot}.",
    },
    "exit_ok": {
        "en": "Goodbye {name}! {minutes} min, {fee} charged. Balance: {balance}.",
        "fr": "Au revoir {name} ! {minutes} min, {fee} débités. Solde : {balance}.",
        "ar": "بالسلامة {name}! {minutes} دقيقة، تخلّص {fee}. رصيدك: {balance}.",
    },
    "already_inside": {
        "en": "You are already inside. Say “I'm leaving” when you want to go out.",
        "fr": "Vous êtes déjà à l'intérieur. Dites « je pars » pour sortir.",
        "ar": "إنت داخل ديجا. قول «باش نخرج» كي تحب تخرج.",
    },
    "not_inside": {
        "en": "You are not parked inside at the moment.",
        "fr": "Vous n'êtes pas dans le parking en ce moment.",
        "ar": "إنت موش داخل الباركينغ توا.",
    },
    "debt": {
        "en": "Your balance is negative ({balance}). Please top up in the app before entering.",
        "fr": "Votre solde est négatif ({balance}). Rechargez dans l'application avant d'entrer.",
        "ar": "رصيدك ناقص ({balance}). اشحن في التطبيق قبل ما تدخل.",
    },
    "low_balance": {
        "en": "You need at least {min} to enter; your balance is {balance}. Please top up.",
        "fr": "Il faut au moins {min} pour entrer ; votre solde est de {balance}. Rechargez svp.",
        "ar": "يلزمك على الأقل {min} باش تدخل، ورصيدك {balance}. اشحن من فضلك.",
    },
    "full": {
        "en": "Sorry, the parking is full and you have no reservation.",
        "fr": "Désolé, le parking est complet et vous n'avez pas de réservation.",
        "ar": "سامحني، الباركينغ معمّر وما عندكش حجز.",
    },
    "reserved": {
        "en": "Done: {spot} is reserved for {minutes} min ({fee} paid).",
        "fr": "C'est fait : la place {spot} est réservée pour {minutes} min ({fee} payés).",
        "ar": "تم: البلاصة {spot} محجوزة {minutes} دقيقة (خلّصت {fee}).",
    },
    "no_free_spot": {
        "en": "There is no free spot to reserve right now.",
        "fr": "Aucune place libre à réserver pour le moment.",
        "ar": "ما فماش بلاصة فارغة للحجز توا.",
    },
    "already_has_a_reservation": {
        "en": "You already have a reservation. Cancel it first if you want another spot.",
        "fr": "Vous avez déjà une réservation. Annulez-la d'abord pour en prendre une autre.",
        "ar": "عندك حجز ديجا. بطّلو قبل إذا تحب بلاصة أخرى.",
    },
    "insufficient_credit": {
        "en": "A reservation costs {fee} and your balance is {balance}. Please top up.",
        "fr": "Une réservation coûte {fee} et votre solde est de {balance}. Rechargez svp.",
        "ar": "الحجز سومو {fee} ورصيدك {balance}. اشحن من فضلك.",
    },
    "spot_unavailable": {
        "en": "That spot is not available. Ask me for the free spots.",
        "fr": "Cette place n'est pas disponible. Demandez-moi les places libres.",
        "ar": "البلاصة هاذي موش متاحة. اسألني على البلايص الفارغة.",
    },
    "cancelled": {
        "en": "Your reservation of {spot} is cancelled and {refund} refunded.",
        "fr": "Votre réservation de {spot} est annulée et {refund} remboursés.",
        "ar": "تبطّل الحجز متاع {spot} ورجعولك {refund}.",
    },
    "no_active_reservation": {
        "en": "You have no active reservation.",
        "fr": "Vous n'avez aucune réservation active.",
        "ar": "ما عندك حتى حجز.",
    },
    "balance": {
        "en": "{name}, your balance is {balance}.{extra}",
        "fr": "{name}, votre solde est de {balance}.{extra}",
        "ar": "{name}، رصيدك {balance}.{extra}",
    },
    "balance_inside": {
        "en": " You've been inside {minutes} min; leaving now costs {fee}.",
        "fr": " Vous êtes là depuis {minutes} min ; sortir maintenant coûte {fee}.",
        "ar": " عندك {minutes} دقيقة داخل؛ كان تخرج توا تخلّص {fee}.",
    },
    "price": {
        "en": "Parking costs {rate} per hour, the first {free} minutes are free. "
        "A reservation costs {fee}, and you need {min} of credit to enter.",
        "fr": "Le stationnement coûte {rate} de l'heure, les {free} premières minutes sont "
        "gratuites. Une réservation coûte {fee}, et il faut {min} de crédit pour entrer.",
        "ar": "الساعة بـ {rate}، أول {free} دقيقة بلاش. الحجز بـ {fee}، ويلزمك {min} "
        "في الرصيد باش تدخل.",
    },
    "busy": {
        "en": "Over the last week the busiest hours were {hours}.",
        "fr": "La semaine dernière, les heures les plus chargées étaient {hours}.",
        "ar": "في الجمعة اللي فاتت، أكثر وقت زحمة كان {hours}.",
    },
    "busy_none": {
        "en": "I don't have enough history yet to tell the busy hours.",
        "fr": "Je n'ai pas encore assez d'historique pour les heures de pointe.",
        "ar": "ما عنديش معطيات كافية توا على أوقات الزحمة.",
    },
    "topup": {
        "en": "I've opened the secure checkout: enter your card there.",
        "fr": "J'ai ouvert le paiement sécurisé : saisissez votre carte là-bas.",
        "ar": "حليتلك صفحة الخلاص الآمنة: دخّل الكارطة غادي.",
    },
    "topup_kiosk": {
        "en": "Card payments are made in the app on your phone: Account, then Top up.",
        "fr": "Le paiement par carte se fait dans l'application : Compte, puis Recharger.",
        "ar": "الخلاص بالكارطة يتعمل في التطبيق على تليفونك: الحساب، وبعد اشحن.",
    },
    "done_barrier_opening": {
        "en": "The barrier is opening.",
        "fr": "La barrière s'ouvre.",
        "ar": "الباب يتحل.",
    },
    "done_reservation_created": {
        "en": "Your spot {spot_id} is reserved.",
        "fr": "Votre place {spot_id} est réservée.",
        "ar": "البلاصة {spot_id} محجوزتلك.",
    },
    "done_reservation_cancelled": {
        "en": "Your reservation is cancelled.",
        "fr": "Votre réservation est annulée.",
        "ar": "تبطّل الحجز.",
    },
    "done_open_top_up": {
        "en": "Please top up your wallet in the app.",
        "fr": "Veuillez recharger votre solde dans l'application.",
        "ar": "اشحن رصيدك في التطبيق من فضلك.",
    },
    "error": {
        "en": "Something went wrong, please try again.",
        "fr": "Un problème est survenu, veuillez réessayer.",
        "ar": "صار مشكل، عاود جرب من فضلك.",
    },
}


def _t(key: str, lang: str, **values: Any) -> str:
    return T[key][lang].format(**values)


def _matches(keyword: str, folded: str) -> bool:
    # Latin and short Arabic keywords must start a word ("pay" in "payer" but not in
    # "repaying"; "حل" in "حل الباب" but not in "محل")
    pattern = re.escape(fold(keyword))
    if keyword.isascii() or len(keyword) <= 3:
        pattern = r"(?<!\w)" + pattern
    return re.search(pattern, folded) is not None


def classify(text: str) -> str:
    folded = fold(text)
    found = [intent for intent, kws in INTENTS if any(_matches(kw, folded) for kw in kws)]
    if not found:
        return "help"
    if found[0] == "price" and "balance" in found:  # "how much is left on my balance?"
        return "balance"
    return found[0]


def _duration(text: str) -> int:
    folded = fold(text)
    if re.search(r"half an hour|demi[- ]heure|نص ساعه|نصف ساعه", folded):
        return 30
    if re.search(r"\b(an|one) hour\b|\bune heure\b|ساعه", folded):
        return 60
    m = re.search(r"(\d{1,3})\s*(min|mn|m\b|دقيق|دق)", folded)
    if m:
        return int(m.group(1))
    return 15


def _spot(text: str) -> str:
    m = re.search(r"\bp\s?([1-4])\b", fold(text))
    return f"P{m.group(1)}" if m else "any"


class RulesEngine:
    def describe(self, actions: list[dict[str, Any]], lang: str) -> str:
        """Sentences for actions already performed (used when Claude failed half-way)."""
        parts = []
        for action in actions:
            key = f"done_{action['type']}"
            if key in T:
                parts.append(T[key][lang].format(**action))
        return " ".join(parts) or _t("error", lang)

    async def reply(self, text: str, tools: ToolBox, lang: str | None = None) -> tuple[str, str]:
        """Returns (reply, language)."""
        lang = lang or detect_language(text)
        intent = classify(text)
        try:
            return await self._answer(intent, text, tools, lang), lang
        except Exception:
            return _t("error", lang), lang

    async def _answer(self, intent: str, text: str, tools: ToolBox, lang: str) -> str:
        if intent in ("greet", "thanks", "help"):
            return _t(intent, lang)

        if intent == "status":
            r = await tools.tool_parking_status()
            if r["free"] == 0:
                return _t("status_full", lang)
            free = [s["spot_id"] for s in r["spots"] if s["status"] == "free"]
            return _t(
                "status", lang, free=r["free"], total=r["total"], list=f" ({', '.join(free)})"
            )

        if intent == "price":
            r = await tools.tool_pricing()
            return _t(
                "price",
                lang,
                rate=r["hourly_rate"],
                free=r["free_minutes"],
                fee=r["reservation_fee"],
                min=r["minimum_credit_to_enter"],
            )

        if intent == "busy":
            r = await tools.tool_busy_hours()
            if not r["ok"] or not r["busiest_hours"]:
                return _t("busy_none", lang)
            hours = ", ".join(f"{h['hour']} ({h['occupancy']})" for h in r["busiest_hours"])
            return _t("busy", lang, hours=hours)

        if intent == "balance":
            r = await tools.tool_my_account()
            if not r["ok"]:
                return _t(r["error"], lang)
            extra = ""
            if r["inside_parking"]:
                extra = _t(
                    "balance_inside",
                    lang,
                    minutes=r["minutes_inside"],
                    fee=r["cost_if_leaving_now"],
                )
            return _t("balance", lang, name=r["name"], balance=r["balance"], extra=extra)

        if intent == "topup":
            m = re.search(r"(\d+(?:[.,]\d+)?)", text)
            amount = float(m.group(1).replace(",", ".")) if m else 0
            r = await tools.tool_top_up(amount)
            if r["ok"]:
                return _t("topup", lang)
            if r["error"] == "card_payment_only_in_the_app":
                return _t("topup_kiosk", lang)
            if r["error"] == "amount_out_of_range":
                return f"{r['min']} – {r['max']}"
            return _t(r["error"], lang)

        if intent == "reserve":
            r = await tools.tool_reserve_spot(_spot(text), _duration(text))
            if r["ok"]:
                return _t(
                    "reserved",
                    lang,
                    spot=r["spot_id"],
                    minutes=r["duration_min"],
                    fee=r["fee_paid"],
                )
            if r["error"] == "insufficient_credit":
                return _t("insufficient_credit", lang, fee=r["fee"], balance=r["balance"])
            if r["error"] in T:
                return _t(r["error"], lang)
            return r["error"]

        if intent == "cancel":
            r = await tools.tool_cancel_reservation()
            if r["ok"]:
                return _t("cancelled", lang, spot=r["spot_id"], refund=r["refunded"])
            return _t(r["error"], lang)

        # open / exit
        r = await tools.tool_open_gate("exit" if intent == "exit" else "auto")
        if r.get("error") == "not_identified":
            return _t("not_identified", lang)
        account = await tools.tool_my_account()
        name = account.get("name", "")
        if r["ok"] and r["direction"] == "exit":
            return _t(
                "exit_ok",
                lang,
                name=name,
                minutes=r["minutes"],
                fee=r["charged"],
                balance=r["balance"],
            )
        if r["ok"]:
            spot = r.get("your_reserved_spot")
            hint = _t("spot_hint", lang, spot=spot) if spot else ""
            return _t("entry_ok", lang, name=name, spot=hint)
        if r["reason"] == "low_balance":
            return _t("low_balance", lang, min=r["minimum_credit_to_enter"], balance=r["balance"])
        if r["reason"] == "debt":
            return _t("debt", lang, balance=r["balance"])
        return _t(r["reason"], lang)
