"""Who may pass the barrier, and what leaving costs.

Entry: an identified user, not already inside, with no debt, at least the minimum credit,
and a place to park (their reservation, or a free spot). The barrier command goes to the
ESP32 in its next heartbeat and a "stay" starts.
Exit: always allowed for someone inside. The stay is charged (may go negative) and closed.
"""

import uuid
from datetime import UTC, datetime

from app.schemas.accounts import GateDecisionOut
from app.services.accounts import AccountService
from app.services.parking import ParkingService


class GateService:
    def __init__(self, accounts: AccountService, parking: ParkingService) -> None:
        self.accounts = accounts
        self.parking = parking

    async def enter(self, uid: str) -> GateDecisionOut:
        async with self.accounts.locks(uid):
            user = await self.accounts.get_user(uid)
            balance = user["balance"]

            def refuse(reason: str) -> GateDecisionOut:
                return GateDecisionOut(
                    allowed=False,
                    reason=reason,
                    direction="entry",
                    balance=balance,
                    device_online=self.parking.online,
                )

            if await self.accounts.repo.get_open_stay(uid):
                return refuse("already_inside")
            status = self.accounts.status_of(balance)
            if status == "debt":
                return refuse("debt")
            if status == "low":
                return refuse("low_balance")
            reservation = self.parking.reservation_of_user(uid)
            if reservation is None and self.parking.free_count() == 0:
                return refuse("full")

            await self.parking.submit_barrier_command("open", source=f"user:{uid}")
            await self.accounts.repo.open_stay(
                {
                    "_id": uuid.uuid4().hex,
                    "uid": uid,
                    "status": "open",
                    "started_at": self._now(),
                    "reservation_id": reservation.id if reservation else None,
                }
            )
            return GateDecisionOut(
                allowed=True,
                reason="ok",
                direction="entry",
                balance=balance,
                spot_hint=reservation.spot_id if reservation else None,
                device_online=self.parking.online,
            )

    async def exit(self, uid: str) -> GateDecisionOut:
        async with self.accounts.locks(uid):
            stay = await self.accounts.repo.get_open_stay(uid)
            if stay is None:
                user = await self.accounts.get_user(uid)
                return GateDecisionOut(
                    allowed=False,
                    reason="not_inside",
                    direction="exit",
                    balance=user["balance"],
                    device_online=self.parking.online,
                )

            minutes = self.accounts.stay_minutes(stay)
            fee = self.accounts.parking_fee(minutes)
            if fee:
                balance = await self.accounts.debit(
                    uid, fee, "parking", f"Parking, {minutes} min", stay["_id"], allow_negative=True
                )
            else:
                balance = (await self.accounts.get_user(uid))["balance"]
            await self.accounts.repo.close_stay(
                stay["_id"], {"ended_at": self._now(), "minutes": minutes, "fee": fee}
            )
            # Entered with a reservation that the sensors never saw used (parked elsewhere):
            # release the spot now rather than at its expiry. The fee was for the entry.
            res_id = stay.get("reservation_id")
            if res_id and self.parking.reservation_owner(res_id) == uid:
                await self.parking.cancel_reservation(res_id)
            await self.parking.submit_barrier_command("open", source=f"user:{uid}")
            return GateDecisionOut(
                allowed=True,
                reason="ok",
                direction="exit",
                balance=balance,
                fee=fee,
                minutes=minutes,
                device_online=self.parking.online,
            )

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.accounts.clock(), UTC)
