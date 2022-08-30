import abc
from abc import ABC
from django.utils import timezone

from faucet.faucet_manager.credit_strategy import (
    CreditStrategy,
    CreditStrategyFactory,
    WeeklyCreditStrategy,
)
from faucet.faucet_manager.fund_manager import EVMFundManager
from faucet.models import ClaimReceipt, BrightUser, GlobalSettings
from django.db import transaction


class ClaimManager(ABC):
    @abc.abstractmethod
    def claim(self, amount) -> ClaimReceipt:
        pass

    @abc.abstractmethod
    def get_credit_strategy(self) -> CreditStrategy:
        pass


class SimpleClaimManager(ClaimManager):
    def __init__(self, credit_strategy: CreditStrategy):
        self.credit_strategy = credit_strategy

    @property
    def fund_manager(self):
        return EVMFundManager(self.credit_strategy.chain)

    def claim(self, amount):
        with transaction.atomic():
            bright_user = BrightUser.objects.select_for_update().get(
                pk=self.credit_strategy.bright_user.pk
            )
            self.assert_pre_claim_conditions(amount, bright_user)
            return self.create_pending_claim_receipt(
                amount
            )  # all pending claims will be processed periodically

    def assert_pre_claim_conditions(self, amount, bright_user):
        assert amount <= self.credit_strategy.get_unclaimed()
        assert (
            self.credit_strategy.bright_user.verification_status == BrightUser.VERIFIED
        )
        assert not ClaimReceipt.objects.filter(
            chain=self.credit_strategy.chain,
            bright_user=bright_user,
            _status=BrightUser.PENDING,
        ).exists()

    def create_pending_claim_receipt(self, amount):
        return ClaimReceipt.objects.create(
            chain=self.credit_strategy.chain,
            bright_user=self.credit_strategy.bright_user,
            datetime=timezone.now(),
            amount=amount,
            _status=ClaimReceipt.PENDING,
        )

    def get_credit_strategy(self) -> CreditStrategy:
        return self.credit_strategy


class LimitedChainClaimManager(SimpleClaimManager):
    def get_weekly_limit(self):
        limit = GlobalSettings.objects.first().weekly_chain_claim_limit
        return limit

    @staticmethod
    def get_total_weekly_claims(bright_user):
        last_monday = WeeklyCreditStrategy.get_last_monday()
        return ClaimReceipt.objects.filter(
            bright_user=bright_user,
            _status__in=[BrightUser.PENDING, BrightUser.VERIFIED],
            datetime__gte=last_monday,
        ).count()

    def assert_pre_claim_conditions(self, amount, bright_user):
        super().assert_pre_claim_conditions(amount, bright_user)
        total_claims = self.get_total_weekly_claims(bright_user)
        assert total_claims < self.get_weekly_limit()


class ClaimManagerFactory:
    def __init__(self, chain, bright_user):
        self.chain = chain
        self.bright_user = bright_user

    def get_manager_class(self):
        return LimitedChainClaimManager

    def get_manager(self) -> ClaimManager:
        _Manager = self.get_manager_class()
        assert _Manager is not None, f"Manager for chain {self.chain.pk} not found"
        _strategy = CreditStrategyFactory(self.chain, self.bright_user).get_strategy()
        return _Manager(_strategy)
