"""What the assistant can look up and do. Shared by the Claude engine and the offline rules.

Every action runs as the *caller* (the account behind the request's token), never as an
account named in the chat, so a message can't act on someone else's behalf. Results are
plain JSON-able dicts: Claude reads them, the rules engine turns them into sentences.
Side effects the UI should react to (barrier opening, checkout to open...) are collected
in `actions`.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.services.accounts import (
    AccountBlockedError,
    AccountService,
    AlreadyReservedError,
    InsufficientFundsError,
)
from app.services.gate import GateService
from app.services.parking import ParkingService, ReservationNotFoundError, SpotUnavailableError
from app.services.stats import StatsService

Channel = Literal["app", "kiosk"]

NOT_IDENTIFIED = {
    "ok": False,
    "error": "not_identified",
    "how_to_fix": "Sign in to the app, or at the gate show the QR code from the app's "
    "Account page to the kiosk camera (or type its 6 digits).",
}


@dataclass
class Caller:
    uid: str | None
    channel: Channel = "app"


@dataclass
class ToolBox:
    caller: Caller
    parking: ParkingService
    accounts: AccountService
    gate: GateService
    stats: StatsService
    actions: list[dict[str, Any]] = field(default_factory=list)

    def money(self, millimes: int) -> str:
        return f"{millimes / 1000:.3f} {self.accounts.settings.currency}"

    async def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            return {"ok": False, "error": f"unknown tool {name}"}
        return await handler(**args)

    # ------------------------------------------------------------------ read-only

    async def tool_parking_status(self) -> dict[str, Any]:
        state = self.parking.get_state()
        return {
            "ok": True,
            "spots": [{"spot_id": s.spot_id, "status": s.status} for s in state.spots],
            "free": state.summary.free,
            "reserved": state.summary.reserved,
            "occupied": state.summary.occupied,
            "total": state.summary.total,
            "sensors_online": state.device.online,
            "barrier": state.barrier_state,
        }

    async def tool_pricing(self) -> dict[str, Any]:
        p = self.accounts.pricing()
        return {
            "ok": True,
            "hourly_rate": self.money(p.hourly_rate),
            "free_minutes": p.free_minutes,
            "billed_per_started_block_of_min": p.billing_block_min,
            "reservation_fee": self.money(p.reservation_fee),
            "minimum_credit_to_enter": self.money(p.min_entry_balance),
            "max_reservation_min": self.accounts.settings.reservation_max_min,
            "payment": "prepaid wallet, topped up by card in the app",
            "gate_needs_account": p.gate_mode == "account",
        }

    async def tool_busy_hours(self) -> dict[str, Any]:
        end = datetime.now(UTC)
        try:
            summary = await self.stats.summary(end - timedelta(days=7), end)
        except Exception:
            return {"ok": False, "error": "statistics unavailable"}
        return {
            "ok": True,
            "period": "last 7 days",
            "timezone": summary.timezone,
            "average_occupancy": _pct(summary.avg_rate),
            "busiest_hours": [
                {"hour": f"{h.hour:02d}:00", "occupancy": _pct(h.rate)} for h in summary.peak_hours
            ],
            "average_stay_min": round(summary.avg_duration_min)
            if summary.avg_duration_min
            else None,
        }

    async def tool_my_account(self) -> dict[str, Any]:
        if not self.caller.uid:
            return self._not_identified()
        user = await self.accounts.user_out(await self.accounts.get_user(self.caller.uid))
        result: dict[str, Any] = {
            "ok": True,
            "name": user.name,
            "uid": user.uid,
            "balance": self.money(user.balance),
            "status": user.status,
            "inside_parking": user.stay is not None,
        }
        if user.stay:
            result["minutes_inside"] = user.stay.minutes
            result["cost_if_leaving_now"] = self.money(user.stay.fee_so_far)
        if user.reservation:
            left = user.reservation.expires_at - self.parking.clock()
            result["reservation"] = {
                "spot_id": user.reservation.spot_id,
                "minutes_left": max(0, round(left / 60)),
            }
        return result

    # ------------------------------------------------------------------ actions

    async def tool_reserve_spot(self, spot_id: str = "any", duration_min: int = 15) -> dict:
        if not self.caller.uid:
            return self._not_identified()
        max_min = self.accounts.settings.reservation_max_min
        if not 1 <= duration_min <= max_min:
            return {"ok": False, "error": f"duration must be between 1 and {max_min} minutes"}
        if spot_id == "any":
            free = [s.spot_id for s in self.parking.get_state().spots if s.status == "free"]
            if not free:
                return {"ok": False, "error": "no_free_spot"}
            spot_id = free[0]
        try:
            res = await self.accounts.reserve(self.caller.uid, spot_id, duration_min)
        except InsufficientFundsError as e:
            return {
                "ok": False,
                "error": "insufficient_credit",
                "fee": self.money(e.needed),
                "balance": self.money(e.balance),
            }
        except AccountBlockedError as e:
            return {"ok": False, "error": e.reason}
        except AlreadyReservedError:
            return {"ok": False, "error": "already_has_a_reservation"}
        except SpotUnavailableError as e:
            return {"ok": False, "error": "spot_unavailable", "detail": str(e)}
        self.actions.append(
            {"type": "reservation_created", "spot_id": res.spot_id, "expires_at": res.expires_at}
        )
        return {
            "ok": True,
            "spot_id": res.spot_id,
            "duration_min": duration_min,
            "fee_paid": self.money(self.accounts.settings.reservation_fee),
            "expires_at_utc": datetime.fromtimestamp(res.expires_at, UTC).strftime("%H:%M"),
        }

    async def tool_cancel_reservation(self) -> dict[str, Any]:
        if not self.caller.uid:
            return self._not_identified()
        res = self.parking.reservation_of_user(self.caller.uid)
        if res is None:
            return {"ok": False, "error": "no_active_reservation"}
        try:
            await self.accounts.cancel_reservation(self.caller.uid, res.id)
        except ReservationNotFoundError:
            return {"ok": False, "error": "no_active_reservation"}
        self.actions.append({"type": "reservation_cancelled", "spot_id": res.spot_id})
        return {
            "ok": True,
            "spot_id": res.spot_id,
            "refunded": self.money(self.accounts.settings.reservation_fee),
        }

    async def tool_open_gate(self, direction: str = "auto") -> dict[str, Any]:
        if not self.caller.uid:
            return self._not_identified()
        if direction == "auto":
            inside = await self.accounts.repo.get_open_stay(self.caller.uid)
            direction = "exit" if inside else "entry"
        if direction == "exit":
            decision = await self.gate.exit(self.caller.uid)
        else:
            decision = await self.gate.enter(self.caller.uid)
        result: dict[str, Any] = {
            "ok": decision.allowed,
            "direction": decision.direction,
            "reason": decision.reason,
            "balance": self.money(decision.balance) if decision.balance is not None else None,
            "sensors_online": decision.device_online,
        }
        if decision.fee is not None:
            result["charged"] = self.money(decision.fee)
            result["minutes"] = decision.minutes
        if decision.spot_hint:
            result["your_reserved_spot"] = decision.spot_hint
        if decision.reason == "low_balance":
            result["minimum_credit_to_enter"] = self.money(self.accounts.settings.min_entry_balance)
        if decision.allowed:
            self.actions.append({"type": "barrier_opening", "direction": decision.direction})
        elif decision.reason in ("debt", "low_balance"):
            self.actions.append({"type": "open_top_up", "amount": None})
        return result

    async def tool_top_up(self, amount_tnd: float = 0) -> dict[str, Any]:
        if not self.caller.uid:
            return self._not_identified()
        s = self.accounts.settings
        amount = round(amount_tnd * 1000) if amount_tnd else None
        if amount is not None and not s.topup_min <= amount <= s.topup_max:
            return {
                "ok": False,
                "error": "amount_out_of_range",
                "min": self.money(s.topup_min),
                "max": self.money(s.topup_max),
            }
        if self.caller.channel == "kiosk":
            return {
                "ok": False,
                "error": "card_payment_only_in_the_app",
                "how_to_fix": "Open the app on your phone, Account page, Top up.",
            }
        self.actions.append({"type": "open_top_up", "amount": amount})
        shown = self.money(amount) if amount else None
        return {"ok": True, "checkout_opened": True, "amount": shown}

    def _not_identified(self) -> dict[str, Any]:
        self.actions.append({"type": "login_required"})
        return dict(NOT_IDENTIFIED)


def _pct(rate: float | None) -> str | None:
    return None if rate is None else f"{rate * 100:.0f}%"


# JSON schemas given to Claude. Strict mode guarantees the arguments match them exactly;
# ranges are still checked in the handlers above.
NO_ARGS = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "parking_status",
        "description": "Live state of every parking spot (free / occupied / reserved / "
        "unknown), the counts, whether the sensors are online and the barrier state.",
        "input_schema": NO_ARGS,
    },
    {
        "name": "pricing",
        "description": "Prices and rules: hourly rate, free minutes, reservation fee, "
        "minimum credit needed to enter, maximum reservation length.",
        "input_schema": NO_ARGS,
    },
    {
        "name": "busy_hours",
        "description": "Busiest hours and average occupancy over the last 7 days, to advise "
        "when to come.",
        "input_schema": NO_ARGS,
    },
    {
        "name": "my_account",
        "description": "The caller's account: name, UID, wallet balance and status "
        "(ok / low / debt), whether they are inside the parking and what leaving now would "
        "cost, and their active reservation.",
        "input_schema": NO_ARGS,
    },
    {
        "name": "reserve_spot",
        "description": "Reserves a free spot for the caller and pays the reservation fee "
        "from their wallet. Use spot_id 'any' unless the user named a spot. Use 15 minutes "
        "unless the user asked for another duration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spot_id": {"type": "string", "enum": ["any", "P1", "P2", "P3", "P4"]},
                "duration_min": {"type": "integer", "description": "Minutes, 1 to 60"},
            },
            "required": ["spot_id", "duration_min"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_reservation",
        "description": "Cancels the caller's active reservation and refunds its fee.",
        "input_schema": NO_ARGS,
    },
    {
        "name": "open_gate",
        "description": "Opens the barrier for the caller. 'entry' checks their credit and that "
        "a spot is available; 'exit' charges the stay to their wallet. 'auto' picks exit if "
        "they are inside, entry otherwise. Only call it when the user asks to open, enter or "
        "leave.",
        "input_schema": {
            "type": "object",
            "properties": {"direction": {"type": "string", "enum": ["auto", "entry", "exit"]}},
            "required": ["direction"],
            "additionalProperties": False,
        },
    },
    {
        "name": "top_up",
        "description": "Opens the secure card checkout in the app so the caller can add credit "
        "to their wallet. amount_tnd is the amount the user asked for, or 0 if they did not "
        "say. Never ask for card details in the chat.",
        "input_schema": {
            "type": "object",
            "properties": {"amount_tnd": {"type": "number"}},
            "required": ["amount_tnd"],
            "additionalProperties": False,
        },
    },
]
