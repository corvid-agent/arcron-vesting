# pyright: reportMissingModuleSource=false
"""Linear ALGO vest on Algorand TestNet, credited by Arcron, pulled by the beneficiary.

Pull-not-push: the Arcron hook only updates global state. `claim()` is the only
method that inner-pays, and only the beneficiary can call it.

TestNet only. Unaudited. Not a product. Do not send real funds.

TRAP: a sloppy deploy that mapped every uint64 onto keeper app 769891898 would
freeze a cadence at ~68 years (769891898 rounds × ~2.8 s). `create()` takes
zero arguments. Interval is an Arcron *register* field, not a constructor arg.
Do not compare the inner sender against itob(keeper_app.id) — that is 8 bytes,
not an address. Auth is Application(keeper_app).address.

The keeper binding is upgradeable: the creator may `set_keeper` again. That is
a rug vector (the creator can retarget). Do not freeze after first set.
"""

from algopy import (
    ARC4Contract,
    Account,
    Application,
    Global,
    GlobalState,
    Txn,
    UInt64,
    gtxn,
    itxn,
)
from algopy.arc4 import abimethod

# Every Algorand account must hold this much. Held back from `locked` so
# `claim` cannot drain the app account below min balance.
APP_BASE_MBR = 100_000


class Vesting(ARC4Contract):
    """Locked ALGO released linearly to a beneficiary, credited by keeper 769891898.

    TestNet only. Unaudited.
    """

    def __init__(self) -> None:
        self.keeper_app = GlobalState(UInt64(0))
        self.beneficiary = GlobalState(Account())
        self.start_round = GlobalState(UInt64(0))
        self.duration_rounds = GlobalState(UInt64(0))
        self.locked = GlobalState(UInt64(0))
        self.credited = GlobalState(UInt64(0))
        self.claimed = GlobalState(UInt64(0))
        self.last_accrue_round = GlobalState(UInt64(0))

    @abimethod(create="require")
    def create(self) -> None:
        """No-op create. Zero arguments on purpose.

        A create_arg of type uint64 is how a sloppy deploy script confused the
        keeper app id with a cadence. There is nothing to pass here.
        """
        self.keeper_app.value = UInt64(0)
        self.beneficiary.value = Account()
        self.start_round.value = UInt64(0)
        self.duration_rounds.value = UInt64(0)
        self.locked.value = UInt64(0)
        self.credited.value = UInt64(0)
        self.claimed.value = UInt64(0)
        self.last_accrue_round.value = UInt64(0)

    @abimethod()
    def set_keeper(self, keeper: Application) -> None:
        """Name the Arcron keeper whose app account may call `accrue`.

        Creator only. Upgradeable: the creator may call this again to retarget
        a new keeper app. Pass the keeper *application*, store `.id`.
        `accrue` authorizes Application(keeper).address — never itob(keeper.id).
        """
        assert Txn.sender == Global.creator_address, "Only the creator can set the keeper"
        assert keeper.id != 0, "Keeper app required"
        self.keeper_app.value = keeper.id

    @abimethod()
    def configure(
        self,
        beneficiary: Account,
        start_round: UInt64,
        duration_rounds: UInt64,
    ) -> None:
        """Set beneficiary and vest window. Creator only, once.

        `duration_rounds` is a round count, not wall-clock. Arcron promises
        "not before this round", never "at 09:00".
        """
        assert Txn.sender == Global.creator_address, "Only the creator can configure"
        assert self.beneficiary.value == Global.zero_address, "Already configured"
        assert beneficiary != Global.zero_address, "Beneficiary required"
        assert duration_rounds > 0, "Duration must be > 0"
        self.beneficiary.value = beneficiary
        self.start_round.value = start_round
        self.duration_rounds.value = duration_rounds

    @abimethod()
    def fund(self, payment: gtxn.PaymentTransaction) -> UInt64:
        """Lock principal in the app account. Creator only.

        Payment to this app, no rekey, no close. The first 100_000 µALGO is
        APP_BASE_MBR and is not added to `locked`, so `claim` cannot drain the
        account below min balance. Remainder is locked principal.
        """
        assert Txn.sender == Global.creator_address, "Only the creator can fund"
        assert (
            payment.receiver == Global.current_application_address
        ), "Payment must fund the app account"
        assert payment.sender == Txn.sender, "Payment must come from the caller"
        assert payment.rekey_to == Global.zero_address, "Payment must not rekey"
        assert (
            payment.close_remainder_to == Global.zero_address
        ), "Payment must not close"

        if self.locked.value == 0:
            assert payment.amount > APP_BASE_MBR, "First fund must cover MBR plus principal"
            self.locked.value = payment.amount - APP_BASE_MBR
        else:
            self.locked.value += payment.amount
        locked: UInt64 = self.locked.value
        return locked

    @abimethod()
    def accrue(self) -> UInt64:
        """Arcron hook. Zero arguments; selector is the only app arg.

        Accounting only: updates `credited` from the linear vest. Moves
        nothing, calls nothing, names no extra accounts. Fail-soft: if there
        is nothing to credit, return the current credited amount (or 0).
        """
        # Inner-call sender is the keeper *app account*, not itob(keeper.id).
        assert (
            Txn.sender == Application(self.keeper_app.value).address
        ), "Only the keeper app may accrue"

        credited: UInt64 = self.credited.value
        duration: UInt64 = self.duration_rounds.value
        # Unconfigured: nothing to do. Return rather than reject so a keeper
        # is not backed off for a no-work call.
        if duration == 0:
            return credited

        current: UInt64 = Global.round
        start: UInt64 = self.start_round.value
        locked: UInt64 = self.locked.value

        vested: UInt64
        if current < start:
            vested = UInt64(0)
        elif current - start >= duration:
            vested = locked
        else:
            elapsed: UInt64 = current - start
            vested = locked * elapsed // duration

        if vested <= credited:
            return credited

        self.credited.value = vested
        self.last_accrue_round.value = current
        return vested

    @abimethod()
    def claim(self) -> UInt64:
        """Beneficiary pulls credited-but-unclaimed ALGO.

        The only method that inner-pays. Cover the inner fee with extra_fee
        on the outer call. If nothing is payable, return 0 (do not reject).
        """
        assert Txn.sender == self.beneficiary.value, "Only the beneficiary may claim"
        payable: UInt64 = self.credited.value - self.claimed.value
        if payable == 0:
            return UInt64(0)
        self.claimed.value += payable
        itxn.Payment(receiver=Txn.sender, amount=payable, fee=0).submit()
        return payable
