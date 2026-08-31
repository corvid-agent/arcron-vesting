"""Static honesty: TestNet deploy.json stays 0; LocalNet proof stays localnet."""

from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = json.loads((ROOT / "docs" / "deploy.json").read_text())
LOCALNET = json.loads((ROOT / "docs" / "localnet.json").read_text())
README = (ROOT / "README.md").read_text()
RECREATE = (ROOT / "scripts" / "localnet_recreate.py").read_text()
LISTEN_SRC = ROOT / "scripts" / "localnet_listen.py"
APP_JS = (ROOT / "docs" / "app.js").read_text()


def test_deploy_json_stays_testnet_undeployed() -> None:
    assert DEPLOY.get("network") == "testnet"
    assert int(DEPLOY.get("appId") or 0) == 0
    assert int(DEPLOY.get("upkeepId") or 0) == 0
    assert DEPLOY.get("executeTxid") in ("", None)
    assert DEPLOY.get("claimTxid") in ("", None)


def test_localnet_json_is_localnet_not_testnet() -> None:
    assert LOCALNET.get("network") == "localnet"
    assert int(LOCALNET.get("appId") or 0) > 0
    genesis = str(LOCALNET.get("genesisId") or "").lower()
    assert "testnet" not in genesis
    assert "mainnet" not in genesis
    assert "localhost:4001" in str(LOCALNET.get("algod") or "")


def test_localnet_appid_not_copied_into_deploy() -> None:
    assert int(DEPLOY.get("appId") or 0) != int(LOCALNET.get("appId") or 0)
    assert str(LOCALNET.get("appId")) not in json.dumps(DEPLOY)


def test_recreate_never_writes_deploy_json() -> None:
    assert "Never writes docs/deploy.json" in RECREATE
    assert "DEPLOY_JSON.write" not in RECREATE
    assert "docs/deploy.json" in RECREATE  # it may warn, but must not write
    assert "OUT.write_text" in RECREATE


def test_listen_never_writes_deploy_json() -> None:
    src = LISTEN_SRC.read_text()
    assert "Never writes docs/deploy.json" in src
    assert "DEPLOY_JSON.write" not in src
    assert "LISTEN_JSON.write_text" in src


def test_readme_says_testnet_appid_stays_zero() -> None:
    lowered = README.lower()
    assert "appid stays 0" in lowered or "appid: 0" in lowered or "appId stays 0" in README
    assert "python scripts/localnet_recreate.py" in README
    assert "not TestNet" in README or "not testnet" in lowered


def test_pages_does_not_paint_localnet_as_testnet() -> None:
    assert "loadLocalnetProof" in APP_JS
    assert 'ln.network !== "localnet"' in APP_JS
    assert "INDEXER" in APP_JS
    # deploy.json is the TestNet source; localnet.json is optional CRT footnote
    assert "./deploy.json" in APP_JS
    assert "./localnet.json" in APP_JS


def test_listen_json_is_localnet_not_testnet() -> None:
    listen_path = ROOT / "docs" / "listen.json"
    assert listen_path.is_file()
    listen = json.loads(listen_path.read_text())
    assert listen.get("network") == "localnet"
    assert int(listen.get("appId") or 0) == int(LOCALNET.get("appId") or 0)
    assert int(listen.get("mockKeeperAppId") or 0) > 0
    assert int(listen.get("mockKeeperAppId") or 0) != int(DEPLOY.get("appId") or 0)
    genesis = str(listen.get("genesisId") or "").lower()
    assert "testnet" not in genesis
    assert "mainnet" not in genesis
    g = listen.get("global") or {}
    assert int(g.get("credited") or 0) > 0
    assert int(g.get("claimed") or 0) > 0
    calls = listen.get("calls") or []
    methods = [c.get("method") for c in calls]
    assert "set_keeper" in methods
    assert "accrue" in methods
    assert "claim" in methods
    assert str(listen.get("appId")) not in json.dumps(DEPLOY)


def test_mock_keeper_is_localnet_only_source() -> None:
    src = (ROOT / "smart_contracts" / "mock_keeper" / "contract.py").read_text()
    assert "Not for TestNet" in src
    assert "def accrue(self, app: Application)" in src
    assert "arc4_signature(\"accrue()uint64\")" in src
