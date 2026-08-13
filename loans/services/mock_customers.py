"""Offline DECSI party mock customers (same JSON shape as docs/customer API.txt).

Catalog IDs (demo / UAT without DECSI_BASE_URL):

  2000050041  Tekeste Jigar Meles     (original sample)
  2000050042  Samrawit Berhe Gebre
  2000050043  Hagos Weldekidan Abraha
  2000050044  Selamawit Tadesse Hailu
  2000050045  Mulugeta Gebremariam Desta
  2000050046  Kidist Alemayehu Tsegay
  2000050047  Abel Fisseha Girmay
  2000050048  Rahel Mehari Tesfay
  2000050049  Yonas Berhane Kahsay
  2000050050  Helen Asmelash Goitom
  2000050051  Daniel Gebrekidan Reda
  2000050052  Meron Hailemariam Zewde

Use customer number MISSING / NONE / 0 to simulate not found.
Any other id falls back to a generic DEMO Customer {id}.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Original sample from docs/customer API.txt
SAMPLE_CUSTOMER_ID = '2000050041'
SAMRAWIT_CUSTOMER_ID = '2000050042'

# Catalog: customer_number → party fields (subset; builder fills Temenos-like body)
_MOCK_CATALOG: Dict[str, Dict[str, Any]] = {
    '2000050041': {
        'name': 'Tekeste Jigar Meles',
        'title': 'MR',
        'gender': 'MALE',
        'maritalStatus': 'SINGLE',
        'dateOfBirth': '19900920',
        'age': '35',
        'phone': '945517351',
        'street': 'MEKELE Debubu ADIHKI',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '117',
        'mnemonic': 'TJMT900901',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5003',
        'sector': '5000',
    },
    '2000050042': {
        'name': 'Samrawit Berhe Gebre',
        'title': 'MS',
        'gender': 'FEMALE',
        'maritalStatus': 'MARRIED',
        'dateOfBirth': '19920515',
        'age': '33',
        'phone': '914220481',
        'street': 'MEKELE Hawelti Kebele 05',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '118',
        'mnemonic': 'SBGB920515',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5001',
        'sector': '5000',
    },
    '2000050043': {
        'name': 'Hagos Weldekidan Abraha',
        'title': 'MR',
        'gender': 'MALE',
        'maritalStatus': 'MARRIED',
        'dateOfBirth': '19850312',
        'age': '40',
        'phone': '922881034',
        'street': 'ADIGRAT Inda Silassie',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '121',
        'mnemonic': 'HWAB850312',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5002',
        'sector': '5000',
    },
    '2000050044': {
        'name': 'Selamawit Tadesse Hailu',
        'title': 'MS',
        'gender': 'FEMALE',
        'maritalStatus': 'SINGLE',
        'dateOfBirth': '19971108',
        'age': '28',
        'phone': '911556702',
        'street': 'AXUM Mai Koho',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '119',
        'mnemonic': 'STHA971108',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5004',
        'sector': '5100',
    },
    '2000050045': {
        'name': 'Mulugeta Gebremariam Desta',
        'title': 'MR',
        'gender': 'MALE',
        'maritalStatus': 'MARRIED',
        'dateOfBirth': '19780822',
        'age': '47',
        'phone': '934112890',
        'street': 'SHIRE Endasilassie',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '122',
        'mnemonic': 'MGDE780822',
        'customerStatus': 'Premium Rated - Private Client',
        'industry': '5003',
        'sector': '5000',
    },
    '2000050046': {
        'name': 'Kidist Alemayehu Tsegay',
        'title': 'MS',
        'gender': 'FEMALE',
        'maritalStatus': 'DIVORCED',
        'dateOfBirth': '19940130',
        'age': '32',
        'phone': '913778245',
        'street': 'MEKELE Ayder',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '117',
        'mnemonic': 'KATS940130',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5005',
        'sector': '5200',
    },
    '2000050047': {
        'name': 'Abel Fisseha Girmay',
        'title': 'MR',
        'gender': 'MALE',
        'maritalStatus': 'SINGLE',
        'dateOfBirth': '20010214',
        'age': '25',
        'phone': '970334561',
        'street': 'WUKRO Agulae Road',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '120',
        'mnemonic': 'AFGI010214',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5001',
        'sector': '5000',
    },
    '2000050048': {
        'name': 'Rahel Mehari Tesfay',
        'title': 'MS',
        'gender': 'FEMALE',
        'maritalStatus': 'MARRIED',
        'dateOfBirth': '19891205',
        'age': '36',
        'phone': '915889012',
        'street': 'ADWA Menafesha',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '118',
        'mnemonic': 'RMTE891205',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5002',
        'sector': '5100',
    },
    '2000050049': {
        'name': 'Yonas Berhane Kahsay',
        'title': 'MR',
        'gender': 'MALE',
        'maritalStatus': 'MARRIED',
        'dateOfBirth': '19820618',
        'age': '43',
        'phone': '924667133',
        'street': 'MEKELLE Quiha',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '123',
        'mnemonic': 'YBKA820618',
        'customerStatus': 'Premium Rated - Private Client',
        'industry': '5003',
        'sector': '5000',
    },
    '2000050050': {
        'name': 'Helen Asmelash Goitom',
        'title': 'MS',
        'gender': 'FEMALE',
        'maritalStatus': 'SINGLE',
        'dateOfBirth': '19960921',
        'age': '29',
        'phone': '912445678',
        'street': 'HUMERA Setit',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '124',
        'mnemonic': 'HAGO960921',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5004',
        'sector': '5200',
    },
    '2000050051': {
        'name': 'Daniel Gebrekidan Reda',
        'title': 'MR',
        'gender': 'MALE',
        'maritalStatus': 'WIDOWED',
        'dateOfBirth': '19750403',
        'age': '51',
        'phone': '931220099',
        'street': 'ALAMATA Waja',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '121',
        'mnemonic': 'DGRE750403',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5002',
        'sector': '5000',
    },
    '2000050052': {
        'name': 'Meron Hailemariam Zewde',
        'title': 'MS',
        'gender': 'FEMALE',
        'maritalStatus': 'MARRIED',
        'dateOfBirth': '19930827',
        'age': '32',
        'phone': '916778890',
        'street': 'MEKELE Kedamay Weyane',
        'suburbTown': 'Tigray',
        'cityMunicipal': 'Ethiopia',
        'accountOfficer': '117',
        'mnemonic': 'MHZE930827',
        'customerStatus': 'Standard Rated - Private Client',
        'industry': '5001',
        'sector': '5100',
    },
}


def list_mock_customer_ids() -> list:
    return sorted(_MOCK_CATALOG.keys())


def mock_customer_summaries() -> list:
    """[{id, name, phone, gender}, …] for docs / UI hints."""
    rows = []
    for cid, row in sorted(_MOCK_CATALOG.items()):
        rows.append({
            'customer_number': cid,
            'name': row['name'],
            'phone': '0' + row['phone'] if len(row['phone']) == 9 else row['phone'],
            'gender': row['gender'],
            'town': row.get('street', '').split()[0] if row.get('street') else '',
        })
    return rows


def build_mock_party_body(customer_number: str) -> Optional[Dict[str, Any]]:
    """
    Return Temenos-like party body for a catalog id, or None to use generic fallback.
    """
    cid = (customer_number or '').strip()
    row = _MOCK_CATALOG.get(cid)
    if not row:
        return None
    name = row['name']
    phone = row['phone']
    return {
        'code': cid,
        'gender': row['gender'],
        'industry': row.get('industry', '5003'),
        'title': row.get('title', 'MR'),
        'resideYN': 'Y',
        'customerStatus': row.get('customerStatus', 'Standard Rated - Private Client'),
        'suburbTown': row.get('suburbTown', 'Tigray'),
        'customerType': 'ACTIVE',
        'taxInvoice': 'Y',
        'countryCode': 'ET',
        'street': row.get('street', ''),
        'familyName': name,
        'loansWof': 'N',
        'customerId': cid,
        'sms': phone,
        'mnemonic': row.get('mnemonic', ''),
        'cityMunicipal': row.get('cityMunicipal', 'Ethiopia'),
        'residence': 'ET',
        'sector': row.get('sector', '5000'),
        'isMobileBankingService': 'NULL',
        'givenName': name,
        'dateOfBirth': row.get('dateOfBirth', ''),
        'firstName': name,
        'accountOfficer': row.get('accountOfficer', '117'),
        'phoneNumber': phone,
        'currAddress': 'Y',
        'idTypes': '1',
        'birthIncorpDate': row.get('dateOfBirth', ''),
        'name': name,
        'internetBankingService': 'NULL',
        'middleName': name,
        'shortName': name,
        'maritalStatus': row.get('maritalStatus', 'SINGLE'),
        'age': str(row.get('age', '')),
        'provider': 'mock',
    }
