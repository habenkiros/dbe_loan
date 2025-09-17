import requests
from django.conf import settings

def fetch_customer_by_number(customer_number):
    url = f"{settings.DECSI_BASE_URL}/getCusByCusNo/api/v1.0.0/party/custid/{customer_number}/custdets"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        if data.get("header", {}).get("status") == "success" and data.get("body"):
            customer = data["body"][0]
            return {
                "customer_number": customer.get("customerId"),
                "name": customer.get("name"),
                "phone_number": customer.get("phoneNumber"),
                "status": customer.get("customerType"),  # ACTIVE, INACTIVE etc.
            }
    return None
