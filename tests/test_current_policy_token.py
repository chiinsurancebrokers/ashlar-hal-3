import pytest

from backend.app.services.current_policy_token import create_current_policy_token, verify_current_policy_token
from backend.app.core import config as config_module


def test_current_policy_token_round_trip_and_tamper_rejection(monkeypatch):
    config_module.get_settings.cache_clear()
    monkeypatch.setenv('CURRENT_POLICY_SIGNING_SECRET','test-secret')
    config_module.get_settings.cache_clear()
    try:
        policy={'plan_name':'Bupa Global renewal package','premium':{'amount':'8727.32','currency':'EUR'}}
        token=create_current_policy_token(policy)
        assert verify_current_policy_token(token)['premium']['amount']=='8727.32'
        body,sig=token.split('.',1)
        bad=body+'.'+('A' if sig[0] != 'A' else 'B')+sig[1:]
        with pytest.raises(ValueError): verify_current_policy_token(bad)
    finally:
        monkeypatch.delenv('CURRENT_POLICY_SIGNING_SECRET',raising=False)
        config_module.get_settings.cache_clear()
