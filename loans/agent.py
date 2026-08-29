"""Agentic Assist — create bare loan requests; register collateral shells only.

PRODUCTION POLICY (enforced server-side):
  - Create loan request application only — no documents, appraisal draft, queue/approval.
  - Register collateral placeholders (building / land / other) — NO valuation/estimation values.
  - Never committee submit / disburse / approve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.db import transaction


AGENT_ROLES = (
    'branch_manager',
    'loan_officer',
    'credit_loan_officer',
    'admin',
    'superadmin',
)

# Irreversible / estimation / approval tools — blocked for the agent entirely.
FORBIDDEN_TOOLS = frozenset({
    'submit_to_committee',
    'disburse',
    'committee_vote',
    'approve_disbursement',
    'complete_documents',
    'attach_demo_documents',
    'draft_appraisal',
    'seed_appraisal',
    'queue_approve',
    'estimate_collateral',
    'run_valuation',
    'building_valuation',
})


def user_can_use_agent(user) -> bool:
    from loans.agent_permissions import user_can_use_agent as _can
    return _can(user)


@dataclass
class ToolResult:
    tool: str
    ok: bool
    detail: str = ''
    data: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            'tool': self.tool,
            'ok': self.ok,
            'detail': self.detail,
            'data': self.data,
        }


@dataclass
class AgentRequest:
    """Create-loan payload. Docs/appraisal/queue flags are ignored (always off)."""
    applicant_name: str
    phone_number: str = '0911000000'
    amount: Decimal = Decimal('1000000')
    reason: str = 'Working capital'
    category_id: Optional[int] = None
    collateral_type_id: Optional[int] = None
    branch_id: Optional[int] = None
    assign_officer_id: Optional[int] = None
    corporate: bool = False
    complete_documents: bool = False
    draft_appraisal: bool = False
    queue_approved: bool = False
    customer_number: str = ''
    declared_address: str = ''
    intent_text: str = ''


def _d(value, default: Decimal = Decimal('0')) -> Decimal:
    try:
        if value is None or value == '':
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def resolve_branch_for_user(user, branch_id: Optional[int] = None):
    from loans.models import Branch

    role = getattr(user, 'role', None)
    if role == 'branch_manager':
        if not user.branch_id:
            raise PermissionError('Branch manager has no branch assigned.')
        if branch_id and int(branch_id) != int(user.branch_id):
            raise PermissionError('You can only create loans in your own branch.')
        return user.branch
    if role == 'loan_officer':
        if user.branch_id:
            if branch_id and int(branch_id) != int(user.branch_id):
                raise PermissionError('Loan officers are limited to their branch.')
            return user.branch
        if branch_id:
            return Branch.objects.select_related('district').get(pk=branch_id)
        raise PermissionError('Select a branch or assign the officer to a branch.')
    if branch_id:
        return Branch.objects.select_related('district').get(pk=branch_id)
    if user.branch_id:
        return user.branch
    raise PermissionError('Branch is required.')


def resolve_officer(user, officer_id: Optional[int], branch):
    User = get_user_model()
    role = getattr(user, 'role', None)
    if role == 'loan_officer':
        return user
    if officer_id:
        officer = User.objects.filter(
            pk=officer_id,
            role__in=('loan_officer', 'credit_loan_officer'),
        ).first()
        if not officer:
            raise ValueError('Assigned user is not a loan officer.')
        if officer.branch_id and branch and officer.branch_id != branch.id:
            if role == 'branch_manager' and officer.branch_id != branch.id:
                raise PermissionError('Loan officer must belong to your branch.')
        return officer
    return None


def tool_create_loan(user, req: AgentRequest) -> ToolResult:
    from loans.models import CollateralType, LoanCategory, LoanRequest
    from loans.ids import generate_incremental_loan_request_id
    from loans.agent_permissions import user_can_create_loan_via_agent

    if not user_can_use_agent(user):
        return ToolResult('create_loan', False, 'Not allowed to use Agentic Assist.')
    if not user_can_create_loan_via_agent(user):
        return ToolResult(
            'create_loan',
            False,
            'Only branch managers can create loan requests. '
            'Loan officers register collateral shells on assigned files (no estimation).',
        )

    try:
        branch = resolve_branch_for_user(user, req.branch_id)
    except Exception as e:
        return ToolResult('create_loan', False, str(e))

    try:
        officer = resolve_officer(user, req.assign_officer_id, branch)
    except Exception as e:
        return ToolResult('create_loan', False, str(e))

    name = (req.applicant_name or '').strip()
    if len(name) < 2:
        return ToolResult('create_loan', False, 'Applicant name is required.')

    amount = _d(req.amount)
    if amount <= 0:
        return ToolResult('create_loan', False, 'Amount must be positive.')

    category = None
    if req.category_id:
        category = LoanCategory.objects.filter(pk=req.category_id).first()
    if not category:
        if req.corporate:
            category = (
                LoanCategory.objects.filter(name__icontains='Corporate').order_by('id').first()
                or LoanCategory.objects.order_by('id').first()
            )
        else:
            category = (
                LoanCategory.objects.filter(name__icontains='MSME').order_by('id').first()
                or LoanCategory.objects.order_by('id').first()
            )
    if not category:
        return ToolResult('create_loan', False, 'No loan category configured.')

    coll = None
    if req.collateral_type_id:
        coll = CollateralType.objects.filter(pk=req.collateral_type_id).first()
    if not coll:
        coll = (
            CollateralType.objects.filter(name__icontains='Machinery').first()
            or CollateralType.objects.filter(name__icontains='Building').first()
            or CollateralType.objects.order_by('id').first()
        )
    if not coll:
        return ToolResult('create_loan', False, 'No collateral type configured.')

    phone = (req.phone_number or '0911000000').strip()[:15]
    loan = LoanRequest(
        loan_request_id=generate_incremental_loan_request_id(),
        applicant_name=name[:255],
        phone_number=phone,
        amount_requested=amount,
        reason=(req.reason or 'Working capital')[:5000],
        category=category,
        collateral=coll,
        branch=branch,
        district=branch.district if branch else None,
        assigned_loan_officer=officer,
        origin_level=LoanRequest.ORIGIN_BRANCH,
        customer_number=(req.customer_number or '')[:50] or '',
        declared_address_text=(req.declared_address or '')[:2000],
        queue_approved=False,
        operation_manager_approval=False,
        finance_approval=False,
        finance_disbursement_approval=False,
        status='Pending',
        committee_status='',
        appraisal_completed_at=None,
    )
    loan.save()
    return ToolResult(
        'create_loan',
        True,
        (
            f'Created application {loan.loan_request_id} in {branch.name} only. '
            'No documents, appraisal, estimation, or approvals were applied.'
        ),
        {
            'loan_request_id': loan.pk,
            'loan_request_code': loan.loan_request_id,
            'branch_id': branch.pk,
            'officer_id': officer.pk if officer else None,
        },
    )


def tool_complete_documents(user, loan) -> ToolResult:
    return ToolResult(
        'complete_documents',
        False,
        'Illegal for Assist in production: do not attach or verify documents via the agent. '
        'Use the Documents page in the UI.',
    )


def tool_draft_appraisal(user, loan, corporate: bool = False) -> ToolResult:
    return ToolResult(
        'draft_appraisal',
        False,
        'Illegal for Assist in production: appraisal is never seeded or completed by the agent. '
        'Officers fill appraisal sheets in the UI.',
    )


def tool_register_collateral(user, loan, kind: str, label: str = '', notes: str = '') -> ToolResult:
    """Register an empty collateral shell only — never valuations/BOQ/unit prices."""
    from loans.agent_permissions import user_may_access_loan

    if not user_can_use_agent(user):
        return ToolResult('register_collateral', False, 'Not allowed.')
    role = getattr(user, 'role', None)
    if role not in (
        'loan_officer', 'credit_loan_officer', 'branch_manager', 'admin', 'superadmin',
    ) and not getattr(user, 'is_superuser', False):
        return ToolResult('register_collateral', False, 'Role cannot register collateral via Assist.')
    if not user_may_access_loan(user, loan):
        return ToolResult('register_collateral', False, 'Loan not in your scope.')
    if role == 'loan_officer':
        if loan.assigned_loan_officer_id not in (None, user.id) and loan.assigned_loan_officer_id != user.id:
            return ToolResult('register_collateral', False, 'Loan not assigned to you.')
    if role == 'branch_manager' and loan.branch_id != user.branch_id:
        return ToolResult('register_collateral', False, 'Loan not in your branch.')

    kind = (kind or '').strip().lower()
    label = (label or '').strip() or 'Registered collateral'
    notes = (notes or '').strip()[:2000]

    try:
        from collateral.models import Building, LandValuation, OtherCollateralItem
    except Exception as e:
        return ToolResult('register_collateral', False, f'Collateral app unavailable: {e}')

    if kind in ('building', 'buildings', 'structure'):
        b = Building.objects.create(
            loan_request=loan,
            name=label[:255],
            construction_type='',
            floors=None,
            city=None,
        )
        return ToolResult(
            'register_collateral',
            True,
            f'Registered building shell “{b.name}” with no valuation/BOQ lines.',
            {
                'kind': 'building',
                'building_id': b.pk,
                'loan_request_code': loan.loan_request_id,
                'estimation': False,
            },
        )

    if kind in ('land', 'plot'):
        land, created = LandValuation.objects.get_or_create(
            loan_request=loan,
            defaults={
                'land_size_sqm': None,
                'unit_price_per_sqm': None,
                'notes': notes or 'Registered via Assist — estimation pending',
            },
        )
        if not created and notes:
            land.notes = ((land.notes or '') + '\n' + notes).strip()[:2000]
            land.save(update_fields=['notes', 'updated_at'])
        return ToolResult(
            'register_collateral',
            True,
            (
                'Registered land placeholder with no size/price estimation.'
                if created
                else 'Land already registered; no estimation applied.'
            ),
            {
                'kind': 'land',
                'land_id': land.pk,
                'loan_request_code': loan.loan_request_id,
                'estimation': False,
            },
        )

    if kind in ('other', 'vehicle', 'machinery', 'equipment', 'movable'):
        item = OtherCollateralItem.objects.create(
            loan_request=loan,
            name=label[:255],
            estimated_value=Decimal('0'),
            notes=notes or 'Registered via Assist — estimation pending in field UI',
        )
        return ToolResult(
            'register_collateral',
            True,
            f'Registered other collateral “{item.name}” with estimated_value=0 (no estimation).',
            {
                'kind': 'other',
                'item_id': item.pk,
                'loan_request_code': loan.loan_request_id,
                'estimation': False,
            },
        )

    return ToolResult(
        'register_collateral',
        False,
        'kind must be building, land, or other (vehicle/machinery/equipment).',
    )


@transaction.atomic
def run_bootstrap_pipeline(user, req: AgentRequest) -> Dict[str, Any]:
    """Production: create_loan ONLY. Never documents, appraisal, queue approval."""
    from loans.models import AgentRun, LoanRequest

    req.complete_documents = False
    req.draft_appraisal = False
    req.queue_approved = False

    steps: List[Dict[str, Any]] = []
    run = AgentRun.objects.create(
        user=user,
        intent_text=req.intent_text or f'Create application {req.applicant_name}',
        status=AgentRun.STATUS_OK,
        steps=[],
    )

    if not user_can_use_agent(user):
        run.status = AgentRun.STATUS_ERROR
        run.error = 'Permission denied'
        run.save(update_fields=['status', 'error'])
        return {'ok': False, 'error': run.error, 'run_id': run.pk, 'steps': []}

    create_res = tool_create_loan(user, req)
    steps.append(create_res.as_dict())
    if not create_res.ok:
        run.status = AgentRun.STATUS_ERROR
        run.error = create_res.detail
        run.steps = steps
        run.save()
        return {'ok': False, 'error': create_res.detail, 'run_id': run.pk, 'steps': steps}

    loan = LoanRequest.objects.get(pk=create_res.data['loan_request_id'])
    run.loan_request = loan
    run.steps = steps
    run.status = AgentRun.STATUS_OK
    run.error = ''
    run.save()
    return {
        'ok': True,
        'run_id': run.pk,
        'loan_request_id': loan.pk,
        'loan_request_code': loan.loan_request_id,
        'steps': steps,
        'next_steps': [
            'Upload documents in the UI (Assist will not attach/verify docs).',
            'Loan officer may register collateral shells via Assist (no estimation).',
            'Complete appraisal and estimation only in the application UI / field visit.',
            'Approvals and committee submit only through normal product workflows — never via Assist.',
        ],
    }
