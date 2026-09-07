"""DECSI default. All hooks empty so existing MSME/corporate files are ungated."""

from loans.engines.base import ProductEngine
from loans.product_family import FAMILY_GENERAL


class GeneralEngine(ProductEngine):
    family = FAMILY_GENERAL
