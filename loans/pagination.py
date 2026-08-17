"""Standard list pagination — 10 rows per page everywhere."""

from django.core.paginator import Paginator

PAGE_SIZE = 10


def paginate(request, queryset, page_param: str = 'page', per_page: int = PAGE_SIZE):
    """Return page_obj for a queryset."""
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get(page_param))


def page_querystring(request, *exclude_keys: str) -> str:
    """GET query string without page (and any extra keys)."""
    params = request.GET.copy()
    params.pop('page', None)
    for key in exclude_keys:
        params.pop(key, None)
    return params.urlencode()
