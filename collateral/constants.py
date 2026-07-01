"""Shared collateral field-work constants."""

MIN_IMAGES_PER_BUILDING = 5
MIN_IMAGES_PER_LAND = 3
MIN_IMAGES_PER_OTHER_ITEM = 3

FIELD_VISIT_STEPS = (
    (1, 'Site & building'),
    (2, 'BOQ quantities'),
    (3, 'Photos'),
    (4, 'Review'),
)

LAND_FIELD_STEPS = (
    (1, 'Land & site'),
    (2, 'Photos'),
    (3, 'Review'),
)

OTHER_FIELD_STEPS = (
    (1, 'Asset & site'),
    (2, 'Photos'),
    (3, 'Review'),
)

# Above this accuracy (metres), officer must attest GPS for audit / AI provenance.
GPS_ACCURACY_WEAK_THRESHOLD_M = 100
