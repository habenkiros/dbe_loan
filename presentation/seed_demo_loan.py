"""Seed polished demo data for loan 15919 screenshots (AI-powered Credit Intelligence)."""
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from loans.models import (
    LoanRequest,
    LoanRequestBasicInfo,
    LoanAppraisal,
    LoanRequestDocument,
    QUALITATIVE_RATING_CHOICES_BY_FACTOR,
    CustomUser,
)
from loans.qualitative_scoring import update_appraisal_qualitative_totals
from loans.appraisal_scorecard import build_credit_scorecard, persist_credit_scorecard
from loans.cashflow_utils import seed_monthly_grid_from_averages


LOAN_ID = 15919


def run():
    lr = LoanRequest.objects.select_related('basic_info', 'appraisal', 'assigned_loan_officer').get(pk=LOAN_ID)
    officer = lr.assigned_loan_officer or CustomUser.objects.filter(role='loan_officer').first()

    # --- Loan request header ---
    lr.applicant_name = 'Aster Bekele Trading PLC'
    lr.phone_number = '0911223344'
    lr.email = 'aster.bekele@example.com'
    lr.customer_number = 'OB-784512'
    lr.amount_requested = Decimal('2500000.00')
    lr.status = 'Approved'
    lr.save()

    # --- Basic info (Sheet 1) ---
    bi, _ = LoanRequestBasicInfo.objects.get_or_create(loan_request=lr)
    bi.tin_number = '0078521456'
    bi.gender = 'Female'
    bi.age = 42
    bi.marital_status = 'Married'
    bi.education_level = 'Degree'
    bi.home_address = 'Bole Sub-city, Woreda 03, Addis Ababa'
    bi.spouse_name = 'Dawit Haile'
    bi.spouse_occupation = 'Accountant'
    bi.father_name = 'Bekele Tesfaye'
    bi.grandfather_name = 'Tesfaye Alemu'
    bi.business_name = 'Aster Bekele Trading PLC'
    bi.business_description = (
        'Wholesale distributor of FMCG and household goods serving retailers across '
        'Addis Ababa and Oromia with 8 years of continuous operations.'
    )
    bi.business_address = 'CMC Road, Around Megenagna, Addis Ababa'
    bi.date_business_started = date(2018, 3, 15)
    bi.form_of_ownership = 'Private Limited Company'
    bi.economic_sector = 'Trade'
    bi.subsector_activity = 'Wholesale of food and consumer goods'
    bi.employees_full_time = 18
    bi.employees_part_time = 4
    bi.employees_seasonal = 6
    bi.employees_ft_equivalent = Decimal('22.00')
    bi.family_members_employed = 2
    bi.peak_sales_months = 'Sep–Dec'
    bi.lowest_sales_months = 'Feb–Apr'
    bi.peak_sales_percent = Decimal('35.00')
    bi.lowest_sales_percent = Decimal('12.00')
    bi.number_business_owners = 2
    bi.term_months = 36
    bi.repayment_frequency = 'Monthly'
    bi.interest_rate = Decimal('16.50')
    bi.interest_basis = 'Declining'
    bi.grace_period_months = 3
    bi.interest_only_months = 0
    bi.instalments_per_year = 12
    bi.cash_contribution = Decimal('750000.00')
    bi.field_sources = {
        'applicant_name': 'banking',
        'phone_number': 'banking',
        'tin_number': 'banking',
        'business_name': 'banking',
        'home_address': 'officer',
        'gender': 'banking',
    }
    bi.save()

    # --- Appraisal (Sheets 2–7) ---
    ap, _ = LoanAppraisal.objects.get_or_create(
        loan_request=lr,
        defaults={'created_by': officer, 'appraisal_mode': 'msme'},
    )
    ap.appraisal_mode = 'msme'
    ap.created_by = officer or ap.created_by

    # Cashflow
    ap.cf_monthly_sales = Decimal('1850000.00')
    ap.cf_monthly_cogs = Decimal('1280000.00')
    ap.cf_monthly_salaries = Decimal('145000.00')
    ap.cf_monthly_rent = Decimal('45000.00')
    ap.cf_monthly_utilities = Decimal('18000.00')
    ap.cf_monthly_transport = Decimal('32000.00')
    ap.cf_monthly_other_operating = Decimal('55000.00')
    ap.cf_monthly_taxes = Decimal('42000.00')
    ap.monthly_business_income = Decimal('1850000.00')
    ap.monthly_business_expenses = Decimal('1617000.00')
    ap.other_monthly_income = Decimal('25000.00')
    ap.other_monthly_expenses = Decimal('10000.00')
    ap.proposed_monthly_installment = Decimal('95000.00')
    ap.net_monthly_cashflow = Decimal('248000.00')
    ap.dscr = Decimal('2.61')
    ap.cf_annual_net_cashflow = Decimal('2976000.00')
    ap.cf_annual_debt_service = Decimal('1140000.00')
    ap.dscr_annual = Decimal('2.61')
    ap.suggested_monthly_installment = Decimal('92000.00')
    ap.stress_sales_drop_pct = Decimal('15.00')
    ap.stress_cost_increase_pct = Decimal('10.00')
    ap.stressed_net_monthly_cashflow = Decimal('145000.00')
    ap.stressed_dscr = Decimal('1.53')

    # Bureau
    ap.bureau_score = Decimal('712')
    ap.bureau_score_band = 'A'
    ap.bureau_report_date = date.today() - timedelta(days=12)
    ap.bureau_active_loans_count = 1
    ap.bureau_total_outstanding = Decimal('380000.00')
    ap.bureau_total_monthly_debt_service = Decimal('28000.00')
    ap.bureau_inquiries_6m = 1
    ap.bureau_defaults_ever = False
    ap.bureau_restructured_ever = False
    ap.bureau_thin_file = False

    # Balance sheet highlights (if fields exist)
    for name, val in [
        ('bs_current_assets', Decimal('4200000')),
        ('bs_current_liabilities', Decimal('1800000')),
        ('bs_inventory', Decimal('2100000')),
        ('bs_equity', Decimal('3500000')),
        ('current_ratio', Decimal('2.33')),
        ('acid_test_ratio', Decimal('1.17')),
        ('debt_equity_ratio', Decimal('0.65')),
        ('nbe_credit_report_obtained', True),
    ]:
        if hasattr(ap, name):
            setattr(ap, name, val)

    # E&S
    ap.es_risk_category = 'Low'
    ap.es_eligibility_decision = 'PASS'
    ap.es_assessment_date = date.today() - timedelta(days=5)
    ap.es_notes = 'Low environmental footprint wholesale trading activity. No high-risk sub-projects identified.'
    if officer:
        ap.es_screened_by = officer
        ap.es_checked_by = officer
        ap.es_approved_by = officer

    # Collateral worksheet values (aligned with existing high valuation demo)
    ap.collateral_total_value = Decimal('20900000.00')
    ap.collateral_immovable_value = Decimal('20900000.00')
    ap.collateral_moveable_value = Decimal('0')
    ap.collateral_coverage_ratio = Decimal('8.36')  # vs 2.5M ask

    # Recommendation
    ap.recommendation = 'approve'
    ap.recommendation_comment = (
        'Strong cashflow capacity (annual DSCR 2.61), solid qualitative score, '
        'adequate collateral coverage (8.36x), and clean bureau record. '
        'Recommend approval of ETB 2,500,000 for 36 months.'
    )
    if hasattr(ap, 'recommended_amount'):
        ap.recommended_amount = Decimal('2500000.00')
    if hasattr(ap, 'strengths'):
        ap.strengths = 'Stable wholesale revenues; experienced management; strong collateral; clean credit bureau.'
    if hasattr(ap, 'weaknesses'):
        ap.weaknesses = 'Seasonal sales variation in Q1; single-warehouse concentration — monitor.'
    ap.term_approved_months = 36
    ap.save()

    # Monthly grid
    try:
        seed_monthly_grid_from_averages(ap)
        ap.save(update_fields=['monthly_cashflow_grid'])
    except Exception as e:
        print('grid seed skip', e)

    # Qualitative factors — pick strong ratings
    for factor in ap.qualitative_factors.all():
        opts = QUALITATIVE_RATING_CHOICES_BY_FACTOR.get(factor.factor_key) or []
        if not opts:
            continue
        # take first (usually best) rating choice value
        best = opts[0][0] if isinstance(opts[0], (list, tuple)) else opts[0]
        factor.rating = best
        factor.weight = Decimal('10')
        factor.notes = 'Verified from field visit and management interview.'
        factor.save()
    total, passed = update_appraisal_qualitative_totals(ap)
    print('qualitative total', total, 'passed', passed)

    # E&S checklist — mark compliant answers if model supports
    for item in ap.es_checklist_items.all():
        updated = False
        for field, val in [
            ('response', 'No'),
            ('answer', 'No'),
            ('value', 'No'),
            ('is_compliant', True),
            ('status', 'ok'),
        ]:
            if hasattr(item, field):
                # For exposure questions "No" is often the good answer
                setattr(item, field, val if field != 'response' else 'No')
                updated = True
        if hasattr(item, 'notes'):
            item.notes = 'Reviewed — no material E&S concern.'
            updated = True
        if updated:
            item.save()

    # Scorecard
    try:
        card = persist_credit_scorecard(ap)
        print('scorecard', card)
    except Exception as e:
        print('scorecard err', e)
        try:
            print(build_credit_scorecard(ap))
        except Exception as e2:
            print('build scorecard err', e2)

    # Documents verified
    for doc in lr.application_documents.all():
        doc.auth_status = LoanRequestDocument.AUTH_VERIFIED
        doc.auth_verdict = 'authentic'
        doc.auth_notes = 'Identity fields matched. Document verified by branch manager.'
        doc.authenticated_by = officer
        doc.authenticated_at = timezone.now()
        doc.automated_checks = {
            'integrity': 'passed',
            'ocr': 'passed',
            'identity_match': {'score': 92, 'status': 'matched'},
        }
        doc.save()
        print('verified doc', doc.document_type)

    # Purpose lines if exist
    try:
        from loans.models import AppraisalPurposeLine
        # may be on basic_info
    except Exception:
        pass
    if hasattr(bi, 'purpose_lines'):
        bi.purpose_lines.all().delete()
        Purpose = bi.purpose_lines.model
        Purpose.objects.create(
            basic_info=bi if 'basic_info' in [f.name for f in Purpose._meta.fields] else None,
            **{k: v for k, v in {
                'loan_request': lr,
                'basic_info': bi,
                'description': 'Working capital — inventory restocking',
                'quantity': Decimal('1'),
                'unit_price': Decimal('1800000'),
                'value': Decimal('1800000'),
            }.items() if k in [f.name for f in Purpose._meta.fields]}
        )

    # Credit history entry
    if hasattr(ap, 'credit_history_entries'):
        ap.credit_history_entries.all().delete()
        CH = ap.credit_history_entries.model
        fields = {f.name for f in CH._meta.fields}
        payload = {
            'appraisal': ap,
            'lender_name': 'Oromia Bank',
            'loan_type': 'Working capital',
            'original_amount': Decimal('500000'),
            'outstanding_balance': Decimal('120000'),
            'monthly_installment': Decimal('28000'),
            'status': 'Performing',
            'remarks': 'On-time repayment for 24 months',
        }
        CH.objects.create(**{k: v for k, v in payload.items() if k in fields})

    # Amortization — generate if helper exists
    try:
        from loans.views import _generate_amortization_schedule
        _generate_amortization_schedule(ap, bi, lr)
        print('amortization generated')
    except Exception as e:
        print('amort skip', e)

    print('DONE demo loan', lr.loan_request_id, lr.applicant_name, lr.amount_requested)


if __name__ == '__main__':
    import django
    django.setup()
    run()
