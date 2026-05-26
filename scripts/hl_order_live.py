import sys, time, types
sys.path.insert(0, 'scripts')

import hl_executor as he
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
import hyperliquid.info as hi
import requests
import httpx
from hl_executor import REGISTRY

def make_exchange(agent_key, main_wallet):
    account = Account.from_key(agent_key)
    orig = hi.Info.__init__
    def fast_init(self, base_url=None, skip_ws=False, meta=None, spot_meta=None, perp_dexs=None, timeout=None):
        self.base_url = base_url or 'https://api.hyperliquid.xyz'
        self.session = requests.Session()
        self.ws_manager = None
        self.name_to_coin = {}
        self.coin_to_asset = {}
        self.name_to_asset = types.MethodType(lambda s, n: s.coin_to_asset.get(n, 0), self)
    hi.Info.__init__ = fast_init
    exc = Exchange(account, constants.MAINNET_API_URL, account_address=main_wallet)
    hi.Info.__init__ = orig

    class HttpxSession:
        def post(self, url, json=None, timeout=None):
            r = httpx.post(url, json=json, verify=he._SSL_CTX, timeout=30.0)
            class Resp:
                status_code = r.status_code
                text = r.text
                def json(self): return r.json()
                def raise_for_status(self): r.raise_for_status()
            return Resp()
    exc.info.session = HttpxSession()

    REGISTRY.load()
    for name, idx in REGISTRY._name_to_index.items():
        exc.info.name_to_coin[name] = name
        exc.info.coin_to_asset[name] = idx

    exc.expires_after = int(time.time() * 1000) + 60_000
    return exc


agent_key   = he.os.getenv('HL_AGENT_PRIVATE_KEY')
main_wallet = he.os.getenv('HL_MAIN_WALLET_ADDRESS')

exc  = make_exchange(agent_key, main_wallet)
coin = REGISTRY.resolve('BTC')
print(f'BTC asset index: {exc.info.coin_to_asset.get(coin)}')
print('Placing: BUY 0.0006 BTC @ $74,000 LIMIT GTC (LIVE)')
result = exc.order(coin, True, 0.0006, 74000.0, {'limit': {'tif': 'Gtc'}})
print('Result:', result)
