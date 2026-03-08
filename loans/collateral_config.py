# loans/collateral_config.py – who does collateral estimation (loan officer vs engineering team)

from .models import CollateralEstimationConfig

def get_collateral_estimation_mode():
    """Return 'loan_officer', 'engineering_team', or 'both'. Defaults to 'loan_officer' if no config."""
    config = CollateralEstimationConfig.objects.first()
    if config:
        return config.mode
    return CollateralEstimationConfig.MODE_LOAN_OFFICER


def allows_loan_officer(mode=None):
    """True if loan officers can do collateral estimation (mode is loan_officer or both)."""
    if mode is None:
        mode = get_collateral_estimation_mode()
    return mode in (CollateralEstimationConfig.MODE_LOAN_OFFICER, CollateralEstimationConfig.MODE_BOTH)


def allows_engineering_team(mode=None):
    """True if engineering team can do collateral estimation (mode is engineering_team or both)."""
    if mode is None:
        mode = get_collateral_estimation_mode()
    return mode in (CollateralEstimationConfig.MODE_ENGINEERING_TEAM, CollateralEstimationConfig.MODE_BOTH)
