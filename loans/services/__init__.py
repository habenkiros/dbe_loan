from .customer import fetch_customer_by_number  # re-export for existing imports

# loans/services/ — customer API + analysis helpers
from .customer import fetch_customer_by_number

__all__ = ['fetch_customer_by_number']
