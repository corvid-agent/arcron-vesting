"""Static checks that the hook rules hold. No TestNet, no mnemonic."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "smart_contracts" / "vesting" / "contract.py").read_text()
README = (ROOT / "README.md").read_text()


def test_hook_is_zero_arg() -> None:
    assert "def accrue(self) -> UInt64:" in SRC
    assert "def accrue(self, " not in SRC


def test_accrue_does_not_inner_pay() -> None:
    """The scheduled call cannot push ALGO. Selector only."""
    start = SRC.index("def accrue(self)")
    end = SRC.index("def claim(self)")
    body = SRC[start:end]
    assert "itxn" not in body
    assert "Payment" not in body
    assert "self.credited.value = vested" in body


def test_claim_is_the_pull() -> None:
    claim = SRC[SRC.index("def claim(") :]
    assert "itxn.Payment" in claim
    assert "Only the beneficiary may claim" in claim


def test_auth_uses_application_address_not_itob() -> None:
    assert "Application(self.keeper_app.value).address" in SRC
    accrue = SRC[SRC.index("def accrue(self)") : SRC.index("def claim(self)")]
    assert "Txn.sender == Application(self.keeper_app.value).address" in accrue
    for line in accrue.splitlines():
        code = line.split("#", 1)[0]
        assert "itob(" not in code


def test_keeper_id_is_not_baked_into_logic() -> None:
    assert "self.keeper_app.value = keeper.id" in SRC
    assert "UInt64(769891898)" not in SRC


def test_create_does_not_take_the_keeper() -> None:
    assert "def create(self) -> None:" in SRC
    assert "def create(self, " not in SRC
    assert "def set_keeper(self, keeper: Application) -> None:" in SRC


def test_unconfigured_accrue_returns_rather_than_asserting() -> None:
    start = SRC.index("def accrue(self)")
    body = SRC[start:]
    assert "if duration == 0:" in body
    assert "return credited" in body


def test_readme_says_accrue_is_accounting_only() -> None:
    assert "accrue() is accounting only" in README.lower()
