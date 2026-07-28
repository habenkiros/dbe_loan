"""Template context for collateral / maps."""


def gebeta_maps(request):
    from collateral.geocoding import map_provider_context

    return {'map_provider': map_provider_context()}
