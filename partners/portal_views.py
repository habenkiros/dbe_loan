"""External market portal — 2-step submit, catalog XOR free-text product modes."""

from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from collateral.models import MainWork, SubSubWork, SubWork
from loans.models import City, Region, Zone
from partners.forms import (
    PortalLoginForm,
    PortalProfileForm,
    PortalRegisterForm,
    PortalStep1AreaForm,
    PortalStep2ProductForm,
)
from partners.market_bands import recompute_all_bands
from partners.models import MarketActor, MarketObservation

SESSION_ACTOR_KEY = 'market_portal_actor_id'
SESSION_DRAFT_KEY = 'market_portal_draft'


def get_portal_actor(request):
    pk = request.session.get(SESSION_ACTOR_KEY)
    if not pk:
        return None
    actor = (
        MarketActor.objects.filter(pk=pk)
        .select_related('primary_city', 'primary_city__zone', 'primary_city__zone__region')
        .first()
    )
    if not actor or not actor.can_use_portal():
        request.session.pop(SESSION_ACTOR_KEY, None)
        return None
    return actor


def portal_login_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        actor = get_portal_actor(request)
        if not actor:
            return redirect('market_portal:login')
        request.portal_actor = actor
        return view(request, *args, **kwargs)

    return _wrapped


def _draft_from_city(city: City) -> dict:
    """Session draft keyed only by city (registered actors store this on the profile)."""
    city = City.objects.select_related('zone', 'zone__region').get(pk=city.pk)
    return {
        'city_id': city.pk,
        'city_label': str(city),
        'region_id': city.zone.region_id if city.zone_id else None,
        'zone_id': city.zone_id,
    }


def _bind_observation(step1: dict, step2: dict, actor: MarketActor, channel: str) -> MarketObservation:
    city = City.objects.get(pk=step1['city_id'])
    obs = MarketObservation(
        market_actor=actor,
        branch=actor.branch,
        city=city,
        asset_class=MarketObservation.ASSET_BUILDING,
        sub_work=step2.get('sub_work'),
        sub_sub_work=step2.get('sub_sub_work'),
        item_label=(step2.get('item_label') or '')[:255],
        unit=(step2.get('unit') or '')[:40],
        unit_price_etb=step2['unit_price_etb'],
        condition=step2.get('condition') or MarketObservation.CONDITION_NA,
        observed_at=step2.get('observed_at'),
        notes=(step2.get('notes') or '')[:5000],
        channel=channel,
        status=MarketObservation.STATUS_ACTIVE,
        recorded_by=None,
    )
    return obs


def _resolve_or_create_guest_actor(step1: dict) -> MarketActor:
    guest_name = (step1.get('guest_name') or 'Guest reporter').strip()
    guest_phone = (step1.get('guest_phone') or '').strip()
    city = City.objects.filter(pk=step1.get('city_id')).first()
    if guest_phone:
        actor, _ = MarketActor.objects.get_or_create(
            portal_username=f'guest:{guest_phone}',
            defaults={
                'name': guest_name,
                'phone_number': guest_phone[:30],
                'actor_kind': MarketActor.KIND_DEALER,
                'trust_status': MarketActor.TRUST_PENDING,
                'portal_enabled': False,
                'is_active': True,
                'product_focus': MarketActor.FOCUS_BUILDING,
                'notes': 'Guest portal submission',
            },
        )
        if actor.name != guest_name and guest_name != 'Guest reporter':
            actor.name = guest_name
            actor.save(update_fields=['name', 'updated_at'])
    else:
        actor = MarketActor.objects.create(
            name=guest_name,
            phone_number='',
            actor_kind=MarketActor.KIND_OTHER,
            trust_status=MarketActor.TRUST_PENDING,
            portal_enabled=False,
            is_active=True,
            product_focus=MarketActor.FOCUS_BUILDING,
            notes='One-off guest quote (no phone)',
        )
    if city:
        actor.primary_city = city
        actor.save(update_fields=['primary_city', 'updated_at'])
    return actor


# ---------- Step 1: area ----------

@require_http_methods(['GET', 'POST'])
def portal_landing(request):
    """Step 1 (guest): who + where."""
    if get_portal_actor(request):
        return redirect('market_portal:home')

    form = PortalStep1AreaForm(request.POST or None, for_guest=True)
    if request.method == 'POST' and form.is_valid():
        request.session[SESSION_DRAFT_KEY] = form.to_session_dict()
        return redirect('market_portal:submit_product')

    return render(request, 'market_portal/step1_area.html', {
        'form': form,
        'is_guest': True,
        'step': 1,
        'step_total': 2,
    })


@portal_login_required
@require_http_methods(['GET', 'POST'])
def portal_home(request):
    """Member hub: use saved primary city for quotes, or set/change it once."""
    actor = request.portal_actor
    change_location = request.GET.get('change') == '1' or request.method == 'POST'

    form = PortalStep1AreaForm(request.POST or None, for_guest=False)
    if request.method == 'POST' and form.is_valid():
        draft = form.to_session_dict()
        request.session[SESSION_DRAFT_KEY] = draft
        actor.primary_city_id = draft['city_id']
        actor.save(update_fields=['primary_city', 'updated_at'])
        messages.success(request, f'Location set to {draft.get("city_label")}.')
        return redirect('market_portal:submit_product')

    # Registered actors with a saved city skip area selection every time.
    if actor.primary_city_id and not change_location:
        request.session[SESSION_DRAFT_KEY] = _draft_from_city(actor.primary_city)
        return redirect('market_portal:submit_product')

    recent = (
        actor.observations.select_related('city', 'sub_work', 'sub_sub_work')
        .order_by('-observed_at', '-id')[:15]
    )
    return render(request, 'market_portal/step1_area.html', {
        'form': form,
        'is_guest': False,
        'actor': actor,
        'recent': recent,
        'step': 1,
        'step_total': 2,
        'changing_location': bool(actor.primary_city_id),
    })


# ---------- Step 2: product mode + price ----------

@require_http_methods(['GET', 'POST'])
def portal_submit_product(request):
    actor = get_portal_actor(request)
    draft = request.session.get(SESSION_DRAFT_KEY)

    # Members: always prefer profile location unless they explicitly changed it this session.
    if actor and actor.primary_city_id and (not draft or not draft.get('city_id')):
        draft = _draft_from_city(actor.primary_city)
        request.session[SESSION_DRAFT_KEY] = draft

    if not draft or not draft.get('city_id'):
        messages.info(request, 'Start by choosing your location.')
        return redirect('market_portal:home' if actor else 'market_portal:landing')

    form = PortalStep2ProductForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if actor:
            who = actor
            channel = MarketObservation.CHANNEL_PORTAL
            after = 'market_portal:home'
        else:
            who = _resolve_or_create_guest_actor(draft)
            channel = MarketObservation.CHANNEL_INVITE
            after = 'market_portal:landing'

        obs = _bind_observation(draft, form.cleaned_data, who, channel)
        obs.save()
        if actor:
            # Keep profile location in sync with submitted city.
            if actor.primary_city_id != draft['city_id']:
                actor.primary_city_id = draft['city_id']
                actor.save(update_fields=['primary_city', 'updated_at'])
        recompute_all_bands()
        # Keep location draft for members so the next quote is one screen only.
        if not actor:
            request.session.pop(SESSION_DRAFT_KEY, None)
        messages.success(
            request,
            f'Saved {obs.item_label} @ {obs.unit_price_etb} ETB in {draft.get("city_label")}.',
        )
        return redirect(after)

    return render(request, 'market_portal/step2_product.html', {
        'form': form,
        'draft': draft,
        'is_guest': actor is None,
        'actor': actor,
        'recent': (
            actor.observations.select_related('city', 'sub_work', 'sub_sub_work')
            .order_by('-observed_at', '-id')[:10]
            if actor else []
        ),
        'step': 2,
        'step_total': 1 if actor and actor.primary_city_id else 2,
        'back_url': 'market_portal:home' if actor else 'market_portal:landing',
        'change_location_url': (
            reverse('market_portal:home') + '?change=1' if actor else None
        ),
        'main_works': MainWork.objects.order_by('order', 'name'),
    })


@require_http_methods(['GET', 'POST'])
def portal_register(request):
    if get_portal_actor(request):
        return redirect('market_portal:home')
    form = PortalRegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        actor = form.save()
        request.session[SESSION_ACTOR_KEY] = actor.pk
        request.session[SESSION_DRAFT_KEY] = _draft_from_city(actor.primary_city)
        request.session.cycle_key()
        messages.success(
            request,
            f'Welcome, {actor.name}. Your location is saved — just add product & price.',
        )
        return redirect('market_portal:submit_product')
    return render(request, 'market_portal/register.html', {'form': form})


@portal_login_required
@require_http_methods(['GET', 'POST'])
def portal_profile(request):
    actor = request.portal_actor
    form = PortalProfileForm(request.POST or None, actor=actor)
    if request.method == 'POST' and form.is_valid():
        actor = form.save()
        request.session[SESSION_DRAFT_KEY] = _draft_from_city(actor.primary_city)
        messages.success(request, 'Profile updated.')
        return redirect('market_portal:profile')
    return render(request, 'market_portal/profile.html', {
        'form': form,
        'actor': actor,
    })


@require_http_methods(['GET', 'POST'])
def portal_login(request):
    if get_portal_actor(request):
        return redirect('market_portal:home')
    form = PortalLoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        actor = form.cleaned_data['actor']
        request.session[SESSION_ACTOR_KEY] = actor.pk
        if actor.primary_city_id:
            request.session[SESSION_DRAFT_KEY] = _draft_from_city(actor.primary_city)
        request.session.cycle_key()
        messages.success(request, f'Welcome back, {actor.name}.')
        return redirect(
            'market_portal:submit_product' if actor.primary_city_id else 'market_portal:home'
        )
    return render(request, 'market_portal/login.html', {'form': form})


def portal_logout(request):
    request.session.pop(SESSION_ACTOR_KEY, None)
    request.session.pop(SESSION_DRAFT_KEY, None)
    messages.info(request, 'Signed out.')
    return redirect('market_portal:landing')


# ---------- Public cascade APIs ----------

@require_GET
def ajax_zones(request):
    region_id = request.GET.get('region_id')
    qs = Zone.objects.filter(region_id=region_id).order_by('name') if region_id else Zone.objects.none()
    return JsonResponse(list(qs.values('id', 'name')), safe=False)


@require_GET
def ajax_cities(request):
    zone_id = request.GET.get('zone_id')
    qs = City.objects.filter(zone_id=zone_id).order_by('name') if zone_id else City.objects.none()
    return JsonResponse(list(qs.values('id', 'name')), safe=False)


@require_GET
def ajax_sub_works(request):
    main_work_id = request.GET.get('main_work_id')
    qs = (
        SubWork.objects.filter(main_work_id=main_work_id).order_by('order', 'name')
        if main_work_id else SubWork.objects.none()
    )
    return JsonResponse(list(qs.values('id', 'name', 'order')), safe=False)


@require_GET
def ajax_sub_sub_works(request):
    sub_work_id = request.GET.get('sub_work_id')
    qs = (
        SubSubWork.objects.filter(sub_work_id=sub_work_id).order_by('order', 'name')
        if sub_work_id else SubSubWork.objects.none()
    )
    return JsonResponse(list(qs.values('id', 'name', 'order')), safe=False)
